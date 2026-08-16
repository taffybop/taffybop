"""Owned startup lifecycle for the optional prewarmed parser worker."""

from __future__ import annotations

import asyncio
import base64
import contextvars
import gc
import hashlib
import hmac
import importlib.metadata
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.errors import ExtractionEngineUnavailableError
from app.services.input_documents import InputKind
from app.services.tesseract_broker_native import (
    native_detailed_file_descriptor_inventory,
    native_detailed_thread_inventory,
)
from app.services.tesseract_broker_protocol import (
    BrokerBarrierSnapshot,
    BrokerPostReleaseBaseline,
    BrokerProtocolError,
    BrokerRequestReceipt,
    CustodiedProcessIdentity,
    FrameworkThreadBaseline,
    WorkerForkDenialEvidence,
)


PREWARM_RUNTIME_STATE_KEY = "parser_worker_runtime"
STARTUP_TIMEOUT_EXIT_CODE = 78
SHUTDOWN_TIMEOUT_EXIT_CODE = 79
REQUEST_BARRIER_TIMEOUT_EXIT_CODE = 80
_HASH_CHUNK_BYTES = 1024 * 1024
_MAXIMUM_TREE_ENTRIES = 8_192
_MAXIMUM_TREE_FILES = 4_096
_MAXIMUM_ARTIFACT_BYTES = 16 * 1024 * 1024 * 1024
_MAXIMUM_DISTRIBUTION_BYTES = 4 * 1024 * 1024 * 1024
_MAXIMUM_SINGLE_FILE_BYTES = 4 * 1024 * 1024 * 1024
_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CORE_DISTRIBUTIONS = (
    "docling",
    "docling-core",
    "docling-ibm-models",
    "docling-parse",
    "fastapi",
    "numpy",
    "pdfminer.six",
    "pdfplumber",
    "pillow",
    "pydantic",
    "pypdfium2",
    "safetensors",
    "starlette",
    "torch",
    "torchvision",
    "transformers",
)


class WorkerState(str, Enum):
    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"
    CLOSED = "closed"


async def _preseed_framework_thread_pools(
    broker_post_release_baseline: BrokerPostReleaseBaseline,
) -> FrameworkThreadBaseline:
    """Create the exact framework workers before request CPU BEGIN.

    The full-ASGI broker phase begins in middleware before the endpoint first
    calls Starlette's ``run_in_threadpool``.  Without this preseed, request one
    would create and retain an AnyIO worker between BEGIN and END.  The
    supervised paths initialize both pools before publishing runtime READY;
    the ordinary flag-off/no-capability application never calls this helper.
    """

    if type(broker_post_release_baseline) is not BrokerPostReleaseBaseline:
        raise RuntimeError("broker post-release baseline is unavailable")
    event_loop_identity = (threading.get_ident(), threading.get_native_id())

    def identity() -> tuple[int, int]:
        return threading.get_ident(), threading.get_native_id()

    asyncio_identity = await asyncio.to_thread(identity)
    from starlette.concurrency import run_in_threadpool

    anyio_identity = await run_in_threadpool(identity)
    if (
        any(value <= 0 for value in (*event_loop_identity, *asyncio_identity, *anyio_identity))
        or event_loop_identity == asyncio_identity
        or event_loop_identity == anyio_identity
        or asyncio_identity == anyio_identity
    ):
        raise RuntimeError("framework thread-pool baseline differs")
    # A second dispatch must reuse the initialized AnyIO worker in the
    # single-admission topology.  Growth here would make request-one resource
    # baselines nondeterministic before any user work runs.
    if await run_in_threadpool(identity) != anyio_identity:
        raise RuntimeError("AnyIO framework worker was not stable")
    full_inventory = native_detailed_thread_inventory(os.getpid())
    file_descriptor_inventory = native_detailed_file_descriptor_inventory(
        os.getpid()
    )
    mapping = {
        "schema_id": "parser-framework-thread-baseline-v2",
        "worker_pid": full_inventory.process.pid,
        "worker_start_abstime": full_inventory.process.start_abstime,
        "worker_ppid": full_inventory.process.ppid,
        "worker_pgid": full_inventory.process.pgid,
        "worker_sid": full_inventory.process.sid,
        "event_loop_python_thread_id": event_loop_identity[0],
        "event_loop_native_thread_id": event_loop_identity[1],
        "asyncio_executor_python_thread_id": asyncio_identity[0],
        "asyncio_executor_native_thread_id": asyncio_identity[1],
        "anyio_worker_python_thread_id": anyio_identity[0],
        "anyio_worker_native_thread_id": anyio_identity[1],
        "selected_python_native_thread_identity_basis": (
            "python-threading-get_native_id-pthread_threadid_np-v1"
        ),
        "full_worker_thread_inventory_identity_basis": (
            full_inventory.identity_basis
        ),
        "full_worker_proc_thread_ids": full_inventory.thread_ids,
        "full_worker_proc_thread_count": full_inventory.thread_count,
        "full_worker_proc_thread_inventory_sha256": (
            full_inventory.inventory_sha256
        ),
        "first_full_inventory_observed_at_monotonic_ns": (
            full_inventory.first_scan_started_monotonic_ns
        ),
        "second_full_inventory_observed_at_monotonic_ns": (
            full_inventory.second_scan_completed_monotonic_ns
        ),
        "full_worker_file_descriptor_inventory": file_descriptor_inventory,
        "broker_post_release_baseline": broker_post_release_baseline,
        "observed_at_monotonic_ns": time.monotonic_ns(),
    }
    mapping["record_sha256"] = _canonical_sha256(
        {
            **mapping,
            "full_worker_file_descriptor_inventory": asdict(
                file_descriptor_inventory
            ),
            "broker_post_release_baseline": asdict(
                broker_post_release_baseline
            ),
        }
    )
    return FrameworkThreadBaseline(**mapping)


@dataclass(frozen=True, slots=True)
class FileTreeIdentity:
    sha256: str
    metadata_sha256: str
    file_count: int
    aggregate_bytes: int


@dataclass(frozen=True, slots=True)
class DependencyIdentity:
    sha256: str
    distribution_count: int
    verified_file_count: int
    verified_aggregate_bytes: int
    tesseract_version: str
    language_count: int


@dataclass(frozen=True, slots=True)
class WorkerSnapshot:
    state: WorkerState
    owner_pid: int
    settings_sha256: str
    artifacts_sha256: str | None
    artifact_metadata_sha256: str | None
    dependency_sha256: str | None
    converter_sha256: str | None
    offline_environment_sha256: str | None
    initialization_started_ns: int | None
    ready_at_ns: int | None
    failure_code: str | None
    active_leases: int


@dataclass(frozen=True, slots=True)
class ArmedBrokerRequestSnapshot:
    request_id: str
    state: str
    binding_sha256: str
    arm_capability_sha256: str
    arm_issued_at_monotonic_ns: int
    arm_consumed_at_monotonic_ns: int | None
    phase_deadline_monotonic_ns: int
    request_epoch: int | None
    request_sequence: int | None


@dataclass(slots=True)
class _ArmedBrokerRequest:
    request_id: str
    binding: dict[str, Any]
    binding_sha256: str
    arm_capability: str
    arm_capability_sha256: str
    arm_issued_at_monotonic_ns: int
    phase_deadline_monotonic_ns: int
    state: str = "armed"
    phase_lease: Any | None = None
    claim_started: bool = False
    claim_completed: bool = False
    response_complete: bool = False
    response_witness: dict[str, Any] | None = None
    observed_scope: dict[str, Any] | None = None
    actual_request_bound: bool = False


_ARMED_REQUEST_CONTEXT: contextvars.ContextVar[
    tuple[int, str, str] | None
] = contextvars.ContextVar("parser_broker_armed_request", default=None)


@dataclass(slots=True)
class OwnedConverters:
    pdf: Any
    image: Any
    conversion_lock: threading.Lock
    picture_classifier_enabled: bool
    picture_description_enabled: bool


def offline_environment_identity() -> str:
    """Validate the enabled worker's process-level no-download contract."""

    values: dict[str, str] = {}
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        value = os.getenv(name, "").strip().casefold()
        if value not in {"1", "true", "yes", "on"}:
            raise RuntimeError(f"{name} must be enabled for parser prewarming")
        values[name] = "true"
    return _canonical_sha256(
        {
            "schema_id": "parser-prewarm-offline-environment-v1",
            "values": values,
        }
    )


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_REQUEST_BINDING_KEYS = frozenset(
    {
        "schema_id",
        "method",
        "path",
        "query_sha256",
        "output_format",
        "source_sha256",
        "source_bytes",
        "safe_filename_sha256",
        "upload_content_type_sha256",
    }
)


def _strict_sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} differs")
    return value


def canonical_parse_query_identity(query_string: bytes) -> tuple[str, str]:
    """Return the closed parse-query identity used by ARM and middleware."""

    if not isinstance(query_string, bytes) or len(query_string) > 4_096:
        raise ValueError("parse query differs")
    try:
        text = query_string.decode("ascii", "strict")
        pairs = urllib.parse.parse_qsl(
            text,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        ) if text else []
    except (UnicodeError, ValueError) as exc:
        raise ValueError("parse query differs") from exc
    if (
        len(pairs) > 1
        or any(key != "output_format" for key, _value in pairs)
    ):
        raise ValueError("parse query differs")
    output_format = pairs[0][1] if pairs else "json"
    if output_format not in {"json", "markdown"}:
        raise ValueError("parse output format differs")
    identity = {
        "schema_id": "parser-parse-query-v1",
        "output_format": output_format,
    }
    return _canonical_sha256(identity), output_format


def canonical_parse_query_sha256(query_string: bytes) -> str:
    """Public helper for the evidence controller's exact ARM binding."""

    return canonical_parse_query_identity(query_string)[0]


def _validate_armed_request_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(binding)
    if set(value) != _REQUEST_BINDING_KEYS:
        raise ValueError("armed request binding keys differ")
    if (
        value.get("schema_id") != "parser-broker-request-binding-v2"
        or value.get("method") != "POST"
        or value.get("path") != "/v1/parse"
        or value.get("output_format") not in {"json", "markdown"}
        or type(value.get("source_bytes")) is not int
        or value["source_bytes"] <= 0
    ):
        raise ValueError("armed request binding differs")
    for name in (
        "query_sha256",
        "source_sha256",
        "safe_filename_sha256",
        "upload_content_type_sha256",
    ):
        _strict_sha256(value.get(name), name)
    return value


def _settings_sha256(settings: Settings) -> str:
    return _canonical_sha256(asdict(settings))


def _stat_token(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_descriptor_tree_support() -> None:
    if (
        not getattr(os, "O_NOFOLLOW", 0)
        or not getattr(os, "O_DIRECTORY", 0)
        or os.open not in os.supports_dir_fd
        or os.scandir not in os.supports_fd
    ):
        raise RuntimeError("descriptor-relative artifact validation is unavailable")


def _hash_open_file(
    descriptor: int,
    expected: os.stat_result,
    *,
    maximum_bytes: int,
) -> tuple[int, str]:
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or _stat_token(opened) != _stat_token(expected)
        or opened.st_size > maximum_bytes
    ):
        raise RuntimeError("validated file identity changed before read")
    digest = hashlib.sha256()
    total = 0
    while chunk := os.read(descriptor, _HASH_CHUNK_BYTES):
        total += len(chunk)
        if total > maximum_bytes:
            raise RuntimeError("validated file exceeds its byte bound")
        digest.update(chunk)
    if total != opened.st_size or _stat_token(os.fstat(descriptor)) != _stat_token(opened):
        raise RuntimeError("validated file identity changed during read")
    return total, digest.hexdigest()


def _tree_identity(root: Path, *, include_contents: bool) -> FileTreeIdentity:
    _require_descriptor_tree_support()
    root_lstat = root.lstat()
    if stat.S_ISLNK(root_lstat.st_mode) or not stat.S_ISDIR(root_lstat.st_mode):
        raise RuntimeError("artifact root must be a non-symlink directory")
    root_descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    content_records: list[dict[str, Any]] = []
    metadata_records: list[dict[str, Any]] = []
    aggregate_bytes = 0
    entry_count = 0

    def visit(directory_descriptor: int, prefix: str) -> None:
        nonlocal aggregate_bytes, entry_count
        before = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(before.st_mode):
            raise RuntimeError("artifact directory identity differs")
        with os.scandir(directory_descriptor) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
            entry_count += 1
            if entry_count > _MAXIMUM_TREE_ENTRIES:
                raise RuntimeError("artifact tree exceeds its entry-count bound")
            if entry.name in {"", ".", ".."} or "/" in entry.name or "\x00" in entry.name:
                raise RuntimeError("artifact tree contains an invalid name")
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            observed = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(observed.st_mode):
                raise RuntimeError("artifact tree cannot contain symlinks")
            if stat.S_ISDIR(observed.st_mode):
                child_descriptor = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_descriptor,
                )
                try:
                    if _stat_token(os.fstat(child_descriptor)) != _stat_token(observed):
                        raise RuntimeError("artifact directory changed before open")
                    metadata_records.append(
                        {
                            "path": relative,
                            "kind": "directory",
                            "stat": _stat_token(observed),
                        }
                    )
                    visit(child_descriptor, relative)
                finally:
                    os.close(child_descriptor)
                continue
            if not stat.S_ISREG(observed.st_mode):
                raise RuntimeError("artifact tree contains a non-regular entry")
            if len(content_records) >= _MAXIMUM_TREE_FILES:
                raise RuntimeError("artifact tree exceeds its file-count bound")
            remaining = _MAXIMUM_ARTIFACT_BYTES - aggregate_bytes
            if observed.st_size > remaining:
                raise RuntimeError("artifact tree exceeds its aggregate byte bound")
            sha256 = "metadata-only"
            size_bytes = observed.st_size
            if include_contents:
                file_descriptor = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=directory_descriptor,
                )
                try:
                    size_bytes, sha256 = _hash_open_file(
                        file_descriptor,
                        observed,
                        maximum_bytes=min(remaining, _MAXIMUM_SINGLE_FILE_BYTES),
                    )
                finally:
                    os.close(file_descriptor)
            aggregate_bytes += size_bytes
            metadata_records.append(
                {
                    "path": relative,
                    "kind": "file",
                    "stat": _stat_token(observed),
                }
            )
            content_records.append(
                {"path": relative, "sha256": sha256, "size_bytes": size_bytes}
            )
        if _stat_token(os.fstat(directory_descriptor)) != _stat_token(before):
            raise RuntimeError("artifact directory changed during traversal")

    try:
        if _stat_token(os.fstat(root_descriptor)) != _stat_token(root_lstat):
            raise RuntimeError("artifact root changed before open")
        visit(root_descriptor, "")
    finally:
        os.close(root_descriptor)
    if not content_records:
        raise RuntimeError("artifact tree cannot be empty")
    content_sha256 = (
        _canonical_sha256(content_records) if include_contents else "metadata-only"
    )
    return FileTreeIdentity(
        sha256=content_sha256,
        metadata_sha256=_canonical_sha256(metadata_records),
        file_count=len(content_records),
        aggregate_bytes=aggregate_bytes,
    )


def artifact_identity(path: str | os.PathLike[str]) -> FileTreeIdentity:
    return _tree_identity(Path(path), include_contents=True)


def artifact_metadata_identity(path: str | os.PathLike[str]) -> str:
    return _tree_identity(Path(path), include_contents=False).metadata_sha256


def _absolute_file_identity(path: Path, *, maximum_bytes: int) -> tuple[int, str]:
    observed = path.lstat()
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise RuntimeError("dependency file must be regular and non-symlinked")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        return _hash_open_file(descriptor, observed, maximum_bytes=maximum_bytes)
    finally:
        os.close(descriptor)


def _resolve_bounded_symlink_chain(
    path: Path,
    *,
    final_kind: str,
) -> tuple[Path, list[dict[str, Any]]]:
    current = Path(os.path.abspath(path))
    seen: set[str] = set()
    links: list[dict[str, Any]] = []
    for _ in range(8):
        current_key = str(current)
        if current_key in seen:
            raise RuntimeError("dependency symlink chain contains a cycle")
        seen.add(current_key)
        observed = current.lstat()
        if not stat.S_ISLNK(observed.st_mode):
            if final_kind == "file" and not stat.S_ISREG(observed.st_mode):
                raise RuntimeError("dependency symlink target must be a regular file")
            if final_kind == "directory" and not stat.S_ISDIR(observed.st_mode):
                raise RuntimeError("dependency symlink target must be a directory")
            return current, links
        target = os.readlink(current)
        if not target or len(target) > 4_096 or "\x00" in target:
            raise RuntimeError("dependency symlink target is invalid")
        if _stat_token(current.lstat()) != _stat_token(observed):
            raise RuntimeError("dependency symlink changed during validation")
        links.append(
            {
                "path": current_key,
                "target": target,
                "stat": _stat_token(observed),
            }
        )
        target_path = Path(target)
        current = Path(
            os.path.abspath(
                target_path if target_path.is_absolute() else current.parent / target_path
            )
        )
    raise RuntimeError("dependency symlink chain exceeds its hop bound")


def _distribution_identity(name: str) -> tuple[dict[str, Any], int, int]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(f"required distribution {name!r} is unavailable") from exc
    prefix = Path(sys.prefix).resolve(strict=True)
    records: list[dict[str, Any]] = []
    aggregate_bytes = 0
    files = tuple(item for item in (distribution.files or ()) if item.hash is not None)
    if not files or len(files) > 20_000:
        raise RuntimeError("installed distribution file inventory is invalid")
    for item in sorted(files, key=str):
        located = Path(distribution.locate_file(item))
        located_lstat = located.lstat()
        if stat.S_ISLNK(located_lstat.st_mode):
            raise RuntimeError("installed distribution contains a symlinked file")
        resolved = located.resolve(strict=True)
        if (
            resolved != Path(os.path.abspath(located))
            or _stat_token(located.lstat()) != _stat_token(located_lstat)
        ):
            raise RuntimeError("installed distribution path contains a symlink")
        try:
            resolved.relative_to(prefix)
        except ValueError as exc:
            raise RuntimeError("installed distribution escaped the runtime prefix") from exc
        remaining = _MAXIMUM_DISTRIBUTION_BYTES - aggregate_bytes
        if remaining <= 0:
            raise RuntimeError("installed distributions exceed their byte bound")
        size_bytes, sha256 = _absolute_file_identity(
            resolved,
            maximum_bytes=min(remaining, _MAXIMUM_SINGLE_FILE_BYTES),
        )
        declared = item.hash
        if declared is None or declared.mode != "sha256":
            raise RuntimeError("installed distribution RECORD digest is unsupported")
        try:
            declared_sha256 = base64.urlsafe_b64decode(
                declared.value + "=" * (-len(declared.value) % 4)
            ).hex()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("installed distribution RECORD digest is malformed") from exc
        if not hmac.compare_digest(declared_sha256, sha256):
            raise RuntimeError("installed distribution differs from its RECORD")
        aggregate_bytes += size_bytes
        records.append(
            {"path": str(item), "sha256": sha256, "size_bytes": size_bytes}
        )
    return (
        {
            "name": name,
            "version": distribution.version,
            "files_sha256": _canonical_sha256(records),
            "file_count": len(records),
            "aggregate_bytes": aggregate_bytes,
        },
        len(records),
        aggregate_bytes,
    )


def _tesseract_identity(settings: Settings) -> tuple[dict[str, Any], int, int, str]:
    command = settings.tesseract_cmd.strip()
    executable_value = shutil.which(command) if command else None
    if executable_value is None:
        raise RuntimeError("configured Tesseract executable is unavailable")
    executable_candidate = Path(executable_value)
    executable, executable_links = _resolve_bounded_symlink_chain(
        executable_candidate,
        final_kind="file",
    )
    executable_size, executable_sha256 = _absolute_file_identity(
        executable, maximum_bytes=512 * 1024 * 1024
    )
    version_run = subprocess.run(
        (str(executable), "--version"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=True,
    )
    version = (version_run.stdout or version_run.stderr).splitlines()[0].strip()
    if not version or len(version) > 256:
        raise RuntimeError("Tesseract version identity is invalid")

    if settings.tesseract_data_path:
        data_root_candidate = Path(settings.tesseract_data_path)
        data_root, data_root_links = _resolve_bounded_symlink_chain(
            data_root_candidate,
            final_kind="directory",
        )
    else:
        languages_run = subprocess.run(
            (str(executable), "--list-langs"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )
        listing = "\n".join((languages_run.stdout, languages_run.stderr))
        match = re.search(r'List of available languages in "([^"]+)"', listing)
        if match is None:
            raise RuntimeError("Tesseract language directory is unavailable")
        data_root_candidate = Path(match.group(1))
        data_root, data_root_links = _resolve_bounded_symlink_chain(
            data_root_candidate,
            final_kind="directory",
        )
    if not data_root.is_dir():
        raise RuntimeError("Tesseract language directory must be non-symlinked")

    language_names: list[str] = []
    for configured in settings.ocr_languages:
        for language in configured.split("+"):
            if not _LANGUAGE_RE.fullmatch(language):
                raise RuntimeError("configured OCR language identity is invalid")
            if language not in language_names:
                language_names.append(language)
    language_records = []
    aggregate_bytes = executable_size
    for language in sorted(language_names):
        traineddata = data_root / f"{language}.traineddata"
        size_bytes, sha256 = _absolute_file_identity(
            traineddata, maximum_bytes=512 * 1024 * 1024
        )
        aggregate_bytes += size_bytes
        language_records.append(
            {"language": language, "sha256": sha256, "size_bytes": size_bytes}
        )
    executable_after, executable_links_after = _resolve_bounded_symlink_chain(
        executable_candidate,
        final_kind="file",
    )
    data_root_after, data_root_links_after = _resolve_bounded_symlink_chain(
        data_root_candidate,
        final_kind="directory",
    )
    if (
        executable_after != executable
        or executable_links_after != executable_links
        or data_root_after != data_root
        or data_root_links_after != data_root_links
    ):
        raise RuntimeError("Tesseract symlink identity changed during validation")
    return (
        {
            "executable_sha256": executable_sha256,
            "executable_size_bytes": executable_size,
            "executable_links": executable_links,
            "version": version,
            "language_directory_links": data_root_links,
            "languages": language_records,
        },
        1 + len(language_records),
        aggregate_bytes,
        version,
    )


def dependency_identity(settings: Settings) -> DependencyIdentity:
    distributions = []
    verified_file_count = 0
    verified_aggregate_bytes = 0
    for name in _CORE_DISTRIBUTIONS:
        record, file_count, aggregate_bytes = _distribution_identity(name)
        distributions.append(record)
        verified_file_count += file_count
        verified_aggregate_bytes += aggregate_bytes
        if verified_aggregate_bytes > _MAXIMUM_DISTRIBUTION_BYTES:
            raise RuntimeError("installed distributions exceed their byte bound")
    tesseract, binary_count, binary_bytes, version = _tesseract_identity(settings)
    verified_file_count += binary_count
    verified_aggregate_bytes += binary_bytes
    payload = {
        "schema_id": "parser-prewarm-dependency-identity-v1",
        "python_implementation": sys.implementation.name,
        "python_version": tuple(sys.version_info[:3]),
        "python_cache_tag": sys.implementation.cache_tag,
        "distributions": distributions,
        "tesseract": tesseract,
    }
    return DependencyIdentity(
        sha256=_canonical_sha256(payload),
        distribution_count=len(distributions),
        verified_file_count=verified_file_count,
        verified_aggregate_bytes=verified_aggregate_bytes,
        tesseract_version=version,
        language_count=len(tesseract["languages"]),
    )


def converter_identity(owned: OwnedConverters, settings: Settings) -> str:
    """Validate and identify the concrete converters and their live options."""

    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import ImageFormatOption, PdfFormatOption

    from app.services import pipeline

    if owned.conversion_lock is not pipeline._DOCLING_CONVERSION_LOCK:
        raise RuntimeError("converter does not own the configured conversion lock")
    expected_options = pipeline._docling_pipeline_options(
        tuple(settings.ocr_languages),
        settings.tesseract_cmd,
        settings.tesseract_data_path,
        settings.docling_artifacts_path,
        settings.document_timeout_seconds,
        classify_pictures=owned.picture_classifier_enabled,
        describe_pictures=owned.picture_description_enabled,
        picture_description_prompt=(
            settings.image_captioning_prompt
            if owned.picture_description_enabled
            else None
        ),
    )
    expected_options_dump = expected_options.model_dump(mode="json")
    records: list[dict[str, Any]] = []
    for name, converter, input_format, option_type in (
        ("pdf", owned.pdf, InputFormat.PDF, PdfFormatOption),
        ("image", owned.image, InputFormat.IMAGE, ImageFormatOption),
    ):
        if converter is None or tuple(converter.allowed_formats) != (input_format,):
            raise RuntimeError("converter allowed-format identity differs")
        if set(converter.format_to_options) != {input_format}:
            raise RuntimeError("converter format-option identity differs")
        format_option = converter.format_to_options[input_format]
        if type(format_option) is not option_type:
            raise RuntimeError("converter format-option type differs")
        options = format_option.pipeline_options
        if options is None or options.model_dump(mode="json") != expected_options_dump:
            raise RuntimeError("converter pipeline options differ")
        options_hash = converter._get_pipeline_options_hash(options)
        initialized = converter.initialized_pipelines
        if len(initialized) != 1:
            raise RuntimeError("converter initialized-pipeline count differs")
        ((pipeline_type, initialized_hash), initialized_pipeline), = initialized.items()
        if (
            pipeline_type is not format_option.pipeline_cls
            or initialized_hash != options_hash
            or not isinstance(initialized_pipeline, pipeline_type)
        ):
            raise RuntimeError("converter initialized-pipeline identity differs")
        records.append(
            {
                "name": name,
                "converter_type": (
                    f"{type(converter).__module__}.{type(converter).__qualname__}"
                ),
                "format_option_type": (
                    f"{option_type.__module__}.{option_type.__qualname__}"
                ),
                "pipeline_type": (
                    f"{pipeline_type.__module__}.{pipeline_type.__qualname__}"
                ),
                "options": expected_options_dump,
                "options_hash": options_hash,
            }
        )
    return _canonical_sha256(
        {"schema_id": "parser-prewarm-converter-identity-v1", "converters": records}
    )


def _initialize_owned_converters(settings: Settings) -> OwnedConverters:
    from docling.datamodel.base_models import InputFormat

    from app.services import pipeline

    classifier_enabled = pipeline._picture_classifier_model_available(
        settings.docling_artifacts_path
    )
    description_enabled = (
        settings.image_captioning_enabled
        and pipeline._picture_description_model_available(settings.docling_artifacts_path)
    )
    converter_args = {
        "languages": tuple(settings.ocr_languages),
        "tesseract_cmd": settings.tesseract_cmd,
        "tesseract_data_path": settings.tesseract_data_path,
        "artifacts_path": settings.docling_artifacts_path,
        "timeout_seconds": settings.document_timeout_seconds,
        "classify_pictures": classifier_enabled,
    }
    pdf, conversion_lock = pipeline._build_pdf_converter(
        **converter_args,
        describe_pictures=description_enabled,
        picture_description_prompt=(
            settings.image_captioning_prompt if description_enabled else None
        ),
    )
    image, image_lock = pipeline._build_image_converter(
        **converter_args,
        describe_pictures=description_enabled,
        picture_description_prompt=(
            settings.image_captioning_prompt if description_enabled else None
        ),
    )
    if image_lock is not conversion_lock:
        raise RuntimeError("converter lock identity differs")
    with conversion_lock:
        pdf.initialize_pipeline(InputFormat.PDF)
        image.initialize_pipeline(InputFormat.IMAGE)
    return OwnedConverters(
        pdf=pdf,
        image=image,
        conversion_lock=conversion_lock,
        picture_classifier_enabled=classifier_enabled,
        picture_description_enabled=description_enabled,
    )


def _clear_owned_converters(owned: OwnedConverters | None) -> None:
    if owned is None:
        return
    for converter in (owned.pdf, owned.image):
        pipelines = getattr(converter, "initialized_pipelines", None)
        if isinstance(pipelines, dict):
            pipelines.clear()
    owned.pdf = None
    owned.image = None


def _fatal_exit_after_grace(
    future: Future[Any],
    grace_seconds: float,
    fatal_exit: Callable[[int], Any],
    exit_code: int,
) -> threading.Timer | None:
    def terminate_if_stuck() -> None:
        if not future.done():
            fatal_exit(exit_code)

    if future.done():
        return None
    timer = threading.Timer(grace_seconds, terminate_if_stuck)
    timer.name = "parser-prewarm-fatal-watchdog"
    timer.daemon = True
    timer.start()
    return timer


def _require_request_control_complete_before_shutdown(control: Any) -> None:
    """Forbid a later shutdown deadline while a request authority is open."""

    snapshot = control.snapshot()
    if (
        snapshot.failure_code is not None
        or snapshot.current_request_id is not None
        or snapshot.current_request_epoch is not None
        or snapshot.current_request_sequence is not None
        or snapshot.completed_request_count != snapshot.expected_request_count
        or snapshot.state not in {"ready", "closed"}
    ):
        raise RuntimeError(
            "request-control request remains incomplete at shutdown"
        )


class _BrokerASGIRequestBoundary:
    """One-shot full-ASGI request admission for a supervised runtime."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.armed: _ArmedBrokerRequest | None = None
        self.last_response_witness: dict[str, Any] | None = None

    def snapshot(self) -> ArmedBrokerRequestSnapshot | None:
        with self.runtime._condition:
            armed = self.armed
            if armed is None:
                return None
            lease = armed.phase_lease
            return ArmedBrokerRequestSnapshot(
                request_id=armed.request_id,
                state=armed.state,
                binding_sha256=armed.binding_sha256,
                arm_capability_sha256=armed.arm_capability_sha256,
                arm_issued_at_monotonic_ns=armed.arm_issued_at_monotonic_ns,
                arm_consumed_at_monotonic_ns=(
                    lease.arm_consumed_at_monotonic_ns
                    if lease is not None
                    else None
                ),
                phase_deadline_monotonic_ns=armed.phase_deadline_monotonic_ns,
                request_epoch=(lease.request_epoch if lease is not None else None),
                request_sequence=(
                    lease.request_sequence if lease is not None else None
                ),
            )

    def arm(
        self,
        request_id: str,
        binding: Mapping[str, Any],
        *,
        phase_deadline_monotonic_ns: int | None = None,
        arm_issued_at_monotonic_ns: int | None = None,
    ) -> ArmedBrokerRequestSnapshot:
        runtime = self.runtime
        client = runtime._broker_client
        ready_validator = getattr(runtime, "_validate_ready", None)
        if callable(ready_validator):
            ready_validator(runtime.settings)
        if (
            client is None
            or not isinstance(request_id, str)
            or not request_id
            or len(request_id) > 256
            or not isinstance(binding, Mapping)
        ):
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        binding_value = _validate_armed_request_binding(binding)
        binding_sha256 = _canonical_sha256(binding_value)
        deadline_ns = phase_deadline_monotonic_ns
        if deadline_ns is None:
            deadline_ns = min(
                client.config.attempt_deadline_monotonic_ns,
                time.monotonic_ns()
                + math.ceil(runtime.settings.document_timeout_seconds * 1_000_000_000),
            )
        if (
            isinstance(deadline_ns, bool)
            or not isinstance(deadline_ns, int)
            or deadline_ns <= time.monotonic_ns()
            or deadline_ns > client.config.attempt_deadline_monotonic_ns
        ):
            raise ValueError("armed request deadline differs")
        phase_control = runtime._phase_control
        if phase_control is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        phase_snapshot = phase_control.advance("request", deadline_ns)
        if phase_snapshot.phase_record.deadline_monotonic_ns != deadline_ns:
            raise ValueError("armed request phase deadline differs")
        with runtime._condition:
            if runtime._state is not WorkerState.READY or self.armed is not None:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            arm_capability = client.issue_arm_capability(
                request_id,
                binding_value,
                phase_deadline_monotonic_ns=deadline_ns,
                arm_issued_at_monotonic_ns=arm_issued_at_monotonic_ns,
            )
            issued_at = client.issued_arm_snapshot()[4]
            self.armed = _ArmedBrokerRequest(
                request_id=request_id,
                binding=binding_value,
                binding_sha256=binding_sha256,
                arm_capability=arm_capability,
                arm_capability_sha256=hashlib.sha256(
                    arm_capability.encode("ascii")
                ).hexdigest(),
                arm_issued_at_monotonic_ns=issued_at,
                phase_deadline_monotonic_ns=deadline_ns,
            )
            self.last_response_witness = None
            runtime._condition.notify_all()
        snapshot = self.snapshot()
        if snapshot is None:
            raise RuntimeError("armed request disappeared")
        return snapshot

    def _conversion_lock(self) -> threading.Lock:
        runtime = self.runtime
        owned = getattr(runtime, "_owned", None)
        result = owned.conversion_lock if owned is not None else getattr(
            runtime, "_conversion_lock", None
        )
        if result is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        return result

    def enter_asgi(
        self,
        scope: Mapping[str, Any],
    ) -> contextvars.Token[tuple[int, str, str] | None] | None:
        runtime = self.runtime
        method = scope.get("method")
        path = scope.get("path")
        query_string = scope.get("query_string", b"")
        try:
            query_sha256, output_format = canonical_parse_query_identity(
                query_string
            )
        except ValueError:
            runtime._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        with runtime._condition:
            armed = self.armed
            if armed is None:
                return None
            observed_scope = {
                "method": method,
                "path": path,
                "query_sha256": query_sha256,
                "output_format": output_format,
            }
            if (
                armed.state != "armed"
                or runtime._state is not WorkerState.READY
                or any(
                    armed.binding[name] != actual
                    for name, actual in observed_scope.items()
                )
            ):
                runtime._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            armed.observed_scope = observed_scope
            armed.state = "entering"
        runtime._broker_request_lock.acquire()
        conversion_lock = self._conversion_lock()
        conversion_lock.acquire()
        counted = False
        try:
            with runtime._condition:
                if runtime._state is not WorkerState.READY or self.armed is not armed:
                    raise ExtractionEngineUnavailableError(
                        details={"component": "parser_worker", "reason": "unavailable"}
                    )
                runtime._active_leases += 1
                counted = True
            client = runtime._broker_client
            if client is None:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            lease = client.begin_phase(
                "request",
                armed.request_id,
                armed.binding,
                phase_deadline_monotonic_ns=armed.phase_deadline_monotonic_ns,
                arm_capability=armed.arm_capability,
                require_thread_transfer=True,
            )
            with runtime._condition:
                armed.phase_lease = lease
                armed.state = "begin"
                runtime._broker_barrier = client.barrier_snapshot()
                runtime._condition.notify_all()
                while runtime._broker_barrier is not None:
                    remaining_ns = (
                        armed.phase_deadline_monotonic_ns - time.monotonic_ns()
                    )
                    if remaining_ns <= 0:
                        runtime._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                        raise ExtractionEngineUnavailableError(
                            details={"component": "parser_worker", "reason": "unavailable"}
                        )
                    runtime._condition.wait(
                        min(0.1, remaining_ns / 1_000_000_000)
                    )
                armed.state = "active"
            return _ARMED_REQUEST_CONTEXT.set(
                (id(runtime), armed.request_id, armed.arm_capability_sha256)
            )
        except BaseException:
            if counted:
                with runtime._condition:
                    runtime._active_leases -= 1
                    runtime._condition.notify_all()
            conversion_lock.release()
            runtime._broker_request_lock.release()
            raise

    def bind_actual_request(
        self,
        *,
        data: bytes,
        safe_filename: str,
        upload_content_type: str,
        output_format: str,
    ) -> None:
        """Bind endpoint-validated bytes to the one armed ASGI request."""

        runtime = self.runtime
        context = _ARMED_REQUEST_CONTEXT.get()
        if (
            not isinstance(data, bytes)
            or not isinstance(safe_filename, str)
            or not isinstance(upload_content_type, str)
            or output_format not in {"json", "markdown"}
        ):
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        with runtime._condition:
            armed = self.armed
            if (
                armed is None
                or context
                != (id(runtime), armed.request_id, armed.arm_capability_sha256)
                or armed.state != "active"
                or armed.phase_lease is None
                or armed.observed_scope is None
                or armed.actual_request_bound
                or armed.claim_started
            ):
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            actual = {
                "schema_id": "parser-broker-request-binding-v2",
                **armed.observed_scope,
                "source_sha256": hashlib.sha256(data).hexdigest(),
                "source_bytes": len(data),
                "safe_filename_sha256": hashlib.sha256(
                    safe_filename.encode("utf-8")
                ).hexdigest(),
                "upload_content_type_sha256": hashlib.sha256(
                    upload_content_type.encode("utf-8")
                ).hexdigest(),
            }
            if output_format != actual["output_format"] or actual != armed.binding:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            lease = armed.phase_lease
        client = runtime._broker_client
        if client is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        try:
            evidence = client.bind_actual_request(lease, actual)
        except BaseException:
            runtime._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
            raise
        with runtime._condition:
            if self.armed is not armed or evidence.binding_record_sha256 != (
                armed.binding_sha256
            ):
                runtime._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            armed.actual_request_bound = True
            runtime._condition.notify_all()

    def current(self) -> bool:
        runtime = self.runtime
        context = _ARMED_REQUEST_CONTEXT.get()
        with runtime._condition:
            armed = self.armed
            return bool(
                armed is not None
                and context
                == (id(runtime), armed.request_id, armed.arm_capability_sha256)
                and armed.state == "active"
            )

    @contextmanager
    def claim_conversion(self) -> Iterator[Any]:
        runtime = self.runtime
        context = _ARMED_REQUEST_CONTEXT.get()
        with runtime._condition:
            armed = self.armed
            if (
                armed is None
                or context
                != (id(runtime), armed.request_id, armed.arm_capability_sha256)
                or armed.state != "active"
                or armed.phase_lease is None
                or armed.claim_started
                or not armed.actual_request_bound
            ):
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            armed.claim_started = True
            origin = armed.phase_lease
        client = runtime._broker_client
        if client is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        claimed = client.claim_phase_on_current_thread(origin)
        runtime._local.conversion_lock_held = True
        try:
            yield runtime
        finally:
            try:
                returned = client.release_phase_claim(claimed)
            finally:
                runtime._local.conversion_lock_held = False
            with runtime._condition:
                if self.armed is not armed or returned is not origin:
                    runtime._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                    raise ExtractionEngineUnavailableError(
                        details={"component": "parser_worker", "reason": "unavailable"}
                    )
                armed.claim_completed = True
                runtime._condition.notify_all()

    def response_materialized(self, witness: Mapping[str, Any]) -> None:
        runtime = self.runtime
        ready_validator = getattr(runtime, "_validate_ready", None)
        if callable(ready_validator):
            ready_validator(runtime.settings)
        raw_witness = dict(witness)
        expected_witness_keys = {
            "schema_id",
            "status_code",
            "response_start_message_keys",
            "ordered_headers",
            "headers_sha256",
            "response_start_send_completed_monotonic_ns",
            "response_body_message_keys",
            "body_sha256",
            "body_bytes",
            "response_body_send_completed_monotonic_ns",
            "inner_asgi_returned_monotonic_ns",
            "record_sha256",
        }
        supplied_witness_sha256 = raw_witness.pop("record_sha256", None)
        if (
            set(witness) != expected_witness_keys
            or supplied_witness_sha256 != _canonical_sha256(raw_witness)
            or raw_witness.get("schema_id")
            != "parser-asgi-response-witness-v1"
            or raw_witness.get("status_code") != 200
            or raw_witness.get("response_start_message_keys")
            != ["headers", "status", "type"]
            or raw_witness.get("response_body_message_keys")
            not in (["body", "type"], ["body", "more_body", "type"])
            or not isinstance(raw_witness.get("ordered_headers"), list)
            or raw_witness.get("headers_sha256")
            != _canonical_sha256(
                {"ordered_headers": raw_witness.get("ordered_headers")}
            )
            or not isinstance(raw_witness.get("body_bytes"), int)
            or raw_witness["body_bytes"] <= 0
            or not isinstance(raw_witness.get("body_sha256"), str)
            or len(raw_witness["body_sha256"]) != 64
            or not (
                raw_witness["response_start_send_completed_monotonic_ns"]
                <= raw_witness["response_body_send_completed_monotonic_ns"]
                <= raw_witness["inner_asgi_returned_monotonic_ns"]
            )
        ):
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        retained_witness = {
            **raw_witness,
            "record_sha256": supplied_witness_sha256,
        }
        with runtime._condition:
            armed = self.armed
            if armed is None or armed.state != "active" or not armed.claim_completed:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            armed.response_witness = retained_witness
            self.last_response_witness = dict(retained_witness)
            armed.response_complete = True

    def response_witness(self) -> dict[str, Any] | None:
        with self.runtime._condition:
            armed = self.armed
            if armed is not None and armed.response_witness is not None:
                return dict(armed.response_witness)
            if self.last_response_witness is not None:
                return dict(self.last_response_witness)
            return None

    def finish_asgi(
        self,
        error: BaseException | None,
        token: contextvars.Token[tuple[int, str, str] | None],
    ) -> BrokerRequestReceipt:
        runtime = self.runtime
        with runtime._condition:
            armed = self.armed
            if (
                armed is None
                or armed.phase_lease is None
                or armed.state != "active"
                or (error is None and not armed.response_complete)
            ):
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            armed.state = "ending"
        client = runtime._broker_client
        if client is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        try:
            receipt = (
                client.abort_phase(armed.phase_lease, error)
                if error is not None or not armed.claim_completed
                else client.end_phase(armed.phase_lease)
            )
            runtime._last_broker_receipt = receipt
            with runtime._condition:
                armed.state = "end"
                runtime._broker_barrier = client.barrier_snapshot()
                runtime._condition.notify_all()
                while runtime._broker_barrier is not None:
                    remaining_ns = (
                        armed.phase_deadline_monotonic_ns - time.monotonic_ns()
                    )
                    if remaining_ns <= 0:
                        runtime._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                        raise ExtractionEngineUnavailableError(
                            details={"component": "parser_worker", "reason": "unavailable"}
                        )
                    runtime._condition.wait(
                        min(0.1, remaining_ns / 1_000_000_000)
                    )
            return receipt
        finally:
            _ARMED_REQUEST_CONTEXT.reset(token)
            with runtime._condition:
                self.armed = None
                runtime._active_leases -= 1
                runtime._condition.notify_all()
            self._conversion_lock().release()
            runtime._broker_request_lock.release()
            runtime._finalize_shutdown_if_drained()


class ParserWorkerRuntime:
    """Own exactly one enabled parser lifecycle inside one application process."""

    instrument_only = False

    def __init__(
        self,
        settings: Settings,
        *,
        fatal_exit: Callable[[int], Any] = os._exit,
        initializer: Callable[[Settings], OwnedConverters] = _initialize_owned_converters,
        artifact_validator: Callable[[str | os.PathLike[str]], FileTreeIdentity] = artifact_identity,
        dependency_validator: Callable[[Settings], DependencyIdentity] = dependency_identity,
        metadata_validator: Callable[[str | os.PathLike[str]], str] = artifact_metadata_identity,
        converter_validator: Callable[
            [OwnedConverters, Settings], str
        ] = converter_identity,
        offline_validator: Callable[[], str] = offline_environment_identity,
        broker_client_resolver: Callable[[], Any] | None = None,
        fork_denial_resolver: Callable[[], WorkerForkDenialEvidence] | None = None,
        phase_control_resolver: Callable[[], Any] | None = None,
        request_control_resolver: Callable[[], Any] | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if not settings.parser_latency_prewarm_enabled:
            raise ValueError("ParserWorkerRuntime requires enabled prewarming")
        self.settings = settings
        self._owner_pid = os.getpid()
        self._settings_sha256 = _settings_sha256(settings)
        self._fatal_exit = fatal_exit
        self._initializer = initializer
        self._artifact_validator = artifact_validator
        self._dependency_validator = dependency_validator
        self._metadata_validator = metadata_validator
        self._converter_validator = converter_validator
        self._offline_validator = offline_validator
        if (
            broker_client_resolver is None
            or fork_denial_resolver is None
            or phase_control_resolver is None
            or request_control_resolver is None
        ):
            from app.services.tesseract_broker_client import (
                require_tesseract_broker_client,
                worker_fork_denial_evidence,
            )

            broker_client_resolver = (
                broker_client_resolver or require_tesseract_broker_client
            )
            fork_denial_resolver = (
                fork_denial_resolver or worker_fork_denial_evidence
            )
            from app.services.parser_phase_control import (
                require_parser_phase_control,
            )

            phase_control_resolver = (
                phase_control_resolver or require_parser_phase_control
            )
            from app.services.parser_request_control import (
                require_parser_request_control,
            )

            request_control_resolver = (
                request_control_resolver or require_parser_request_control
            )
        self._broker_client_resolver = broker_client_resolver
        self._fork_denial_resolver = fork_denial_resolver
        self._phase_control_resolver = phase_control_resolver
        self._request_control_resolver = request_control_resolver
        self._clock_ns = clock_ns
        self._condition = threading.Condition()
        self._local = threading.local()
        self._state = WorkerState.CREATED
        self._owned: OwnedConverters | None = None
        self._future: Future[OwnedConverters] | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._fatal_timer: threading.Timer | None = None
        self._artifacts: FileTreeIdentity | None = None
        self._dependencies: DependencyIdentity | None = None
        self._converter_sha256: str | None = None
        self._offline_environment_sha256: str | None = None
        self._owned_instance_identity: tuple[int, int, int] | None = None
        self._initialization_started_ns: int | None = None
        self._ready_at_ns: int | None = None
        self._failure_code: str | None = None
        self._active_leases = 0
        self._broker_client: Any | None = None
        self._fork_denial_evidence: WorkerForkDenialEvidence | None = None
        self._phase_control: Any | None = None
        self._request_control: Any | None = None
        self._broker_request_lock = threading.Lock()
        self._broker_barrier: BrokerBarrierSnapshot | None = None
        self._last_broker_receipt: BrokerRequestReceipt | None = None
        self._startup_broker_receipt: BrokerRequestReceipt | None = None
        self._shutdown_broker_receipt: BrokerRequestReceipt | None = None
        self._framework_thread_baseline: FrameworkThreadBaseline | None = None
        self._asgi_boundary = _BrokerASGIRequestBoundary(self)

    def snapshot(self) -> WorkerSnapshot:
        with self._condition:
            return WorkerSnapshot(
                state=self._state,
                owner_pid=self._owner_pid,
                settings_sha256=self._settings_sha256,
                artifacts_sha256=self._artifacts.sha256 if self._artifacts else None,
                artifact_metadata_sha256=(
                    self._artifacts.metadata_sha256 if self._artifacts else None
                ),
                dependency_sha256=(
                    self._dependencies.sha256 if self._dependencies else None
                ),
                converter_sha256=self._converter_sha256,
                offline_environment_sha256=self._offline_environment_sha256,
                initialization_started_ns=self._initialization_started_ns,
                ready_at_ns=self._ready_at_ns,
                failure_code=self._failure_code,
                active_leases=self._active_leases,
            )

    def _validate_expected_identities(
        self,
    ) -> tuple[FileTreeIdentity, DependencyIdentity]:
        artifact_path = self.settings.docling_artifacts_path
        if artifact_path is None:
            raise RuntimeError("configured local artifacts are unavailable")
        artifacts = self._artifact_validator(artifact_path)
        dependencies = self._dependency_validator(self.settings)
        expected_artifacts = self.settings.parser_latency_prewarm_artifacts_sha256
        expected_dependencies = self.settings.parser_latency_prewarm_dependency_sha256
        if expected_artifacts is None or not hmac.compare_digest(
            artifacts.sha256, expected_artifacts
        ):
            raise RuntimeError("configured artifact identity differs")
        if expected_dependencies is None or not hmac.compare_digest(
            dependencies.sha256, expected_dependencies
        ):
            raise RuntimeError("configured dependency identity differs")
        return artifacts, dependencies

    def _bind_supervised_broker(self) -> None:
        try:
            client = self._broker_client_resolver()
            evidence = self._fork_denial_resolver()
            phase_control = self._phase_control_resolver()
            request_control = self._request_control_resolver()
            phase_snapshot = phase_control.snapshot()
            config = client.config
            if (
                evidence.worker.pid != self._owner_pid
                or evidence.worker.process_group_id != self._owner_pid
                or evidence.worker.session_id != self._owner_pid
                or evidence.broker.pid != config.broker_pid
                or evidence.broker.start_abstime != config.broker_start_abstime
                or evidence.broker.process_group_id != config.broker_pgid
                or evidence.broker.session_id != config.broker_sid
                or evidence.native_closure_sha256
                != config.native_closure_sha256
                or evidence.broker_native_spawn_guard_library_sha256
                != config.native_spawn_guard_sha256
                or evidence.broker_native_spawn_guard_source_sha256
                != config.native_spawn_guard_source_sha256
                or evidence.native_runtime_gate_source_sha256
                != config.native_runtime_gate_source_sha256
                or evidence.native_runtime_gate_library_sha256
                != config.native_runtime_gate_library_sha256
                or evidence.native_runtime_gate_record_sha256
                != config.native_runtime_gate_record_sha256
                or evidence.native_trust_model
                != "frozen-native-closure-trusted-v1"
                or evidence.native_containment_claim
                != "none-trusted-pinned-native-computation"
                or self.settings.tesseract_cmd != config.executable
                or self.settings.tesseract_data_path != config.tessdata_root
                or tuple(sorted(self.settings.ocr_languages))
                != tuple(sorted(set(self.settings.ocr_languages)))
                or any(
                    language not in config.languages
                    for language in self.settings.ocr_languages
                )
                or phase_snapshot.phase_record.phase != "startup"
                or phase_snapshot.phase_record.attempt_id
                != phase_control.attempt_id
                or phase_control.worker_pid != self._owner_pid
                or request_control.worker_identity.pid != self._owner_pid
                or request_control.broker_identity.pid != config.broker_pid
                or request_control.broker_identity.start_abstime
                != config.broker_start_abstime
                or request_control.attempt_nonce_sha256
                != config.attempt_nonce_sha256
                or request_control.scope_sha256 != config.scope_sha256
            ):
                raise RuntimeError("supervised broker identity differs")
        except BaseException as exc:
            self._mark_unavailable("broker_capability_unavailable")
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        self._broker_client = client
        self._fork_denial_evidence = evidence
        self._phase_control = phase_control
        self._request_control = request_control

    def _initialize_transaction(self) -> OwnedConverters:
        owned: OwnedConverters | None = None
        try:
            client = self._broker_client
            if client is None:
                raise RuntimeError("supervised broker was not bound")
            deadline_ns = min(
                client.config.attempt_deadline_monotonic_ns,
                self._phase_control.snapshot().phase_record.deadline_monotonic_ns,
                time.monotonic_ns()
                + math.ceil(
                    self.settings.parser_latency_prewarm_timeout_seconds
                    * 1_000_000_000
                ),
            )
            with client.phase(
                "startup",
                "parser-startup",
                {
                    "settings_sha256": self._settings_sha256,
                    "owner_pid": self._owner_pid,
                },
                phase_deadline_monotonic_ns=deadline_ns,
            ):
                offline_environment_before = self._offline_validator()
                artifacts_before, dependencies_before = (
                    self._validate_expected_identities()
                )
                owned = self._initializer(self.settings)
                converter_sha256 = self._converter_validator(owned, self.settings)
                artifacts_after, dependencies_after = (
                    self._validate_expected_identities()
                )
                offline_environment_after = self._offline_validator()
            startup_receipt = client.last_receipt()
            if (
                startup_receipt is None
                or startup_receipt.logical_phase != "startup"
                or startup_receipt.terminal_kind != "end"
            ):
                raise RuntimeError("startup broker receipt is unavailable")
            with self._condition:
                self._startup_broker_receipt = startup_receipt
            if (
                artifacts_after != artifacts_before
                or dependencies_after != dependencies_before
                or offline_environment_after != offline_environment_before
            ):
                raise RuntimeError("startup identity changed during initialization")
            with self._condition:
                self._artifacts = artifacts_after
                self._dependencies = dependencies_after
                self._converter_sha256 = converter_sha256
                self._offline_environment_sha256 = offline_environment_after
            return owned
        except BaseException:
            _clear_owned_converters(owned)
            raise

    def _mark_unavailable(self, code: str) -> None:
        with self._condition:
            if self._state not in {WorkerState.STOPPING, WorkerState.CLOSED}:
                self._state = WorkerState.UNAVAILABLE
                self._failure_code = code
                self._condition.notify_all()

    def _discard_late_result(self, future: Future[OwnedConverters]) -> None:
        owned: OwnedConverters | None = None
        try:
            owned = future.result()
        except BaseException:
            pass
        with self._condition:
            adopted = owned is not None and self._owned is owned
            timer = self._fatal_timer
            self._fatal_timer = None
            executor = self._executor
            self._executor = None
        if owned is not None and not adopted:
            _clear_owned_converters(owned)
        if timer is not None:
            timer.cancel()
            if timer is not threading.current_thread():
                timer.join(timeout=0.25)
        if executor is not None:
            # This callback can execute on the initializer itself. ``wait=False``
            # releases the executor without attempting to join the current thread.
            executor.shutdown(wait=False, cancel_futures=True)
        self._finalize_shutdown_if_drained()

    def _finalize_shutdown_if_drained(
        self,
        *,
        broker_shutdown_lease: bool = False,
    ) -> bool:
        with self._condition:
            future = self._future
            if (
                self._state is not WorkerState.STOPPING
                or self._active_leases
                or (future is not None and not future.done())
                or (
                    self._broker_client is not None
                    and not broker_shutdown_lease
                )
            ):
                return False
            owned = self._owned
            self._owned = None
            self._owned_instance_identity = None
            timer = self._fatal_timer
            self._fatal_timer = None
            executor = self._executor
            self._executor = None
            self._future = None
            self._state = WorkerState.CLOSED
            self._condition.notify_all()
        _clear_owned_converters(owned)
        if timer is not None:
            timer.cancel()
            if timer is not threading.current_thread():
                timer.join(timeout=0.25)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        return True

    async def start(self) -> WorkerSnapshot:
        with self._condition:
            if self._state is not WorkerState.CREATED:
                raise RuntimeError("parser worker startup is not repeatable")
            if os.getpid() != self._owner_pid:
                self._state = WorkerState.UNAVAILABLE
                self._failure_code = "owner_pid_mismatch"
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
        self._bind_supervised_broker()
        with self._condition:
            if self._state is not WorkerState.CREATED:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            self._state = WorkerState.INITIALIZING
            self._initialization_started_ns = self._clock_ns()
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="parser-prewarm-init",
            )
            self._future = self._executor.submit(self._initialize_transaction)
            future = self._future
        wrapped = asyncio.wrap_future(future)
        try:
            owned = await asyncio.wait_for(
                asyncio.shield(wrapped),
                timeout=self.settings.parser_latency_prewarm_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            self._mark_unavailable("startup_timeout")
            self._fatal_timer = _fatal_exit_after_grace(
                future,
                self.settings.parser_latency_prewarm_shutdown_grace_seconds,
                self._fatal_exit,
                STARTUP_TIMEOUT_EXIT_CODE,
            )
            future.add_done_callback(self._discard_late_result)
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        except asyncio.CancelledError:
            self._mark_unavailable("startup_cancelled")
            self._fatal_timer = _fatal_exit_after_grace(
                future,
                self.settings.parser_latency_prewarm_shutdown_grace_seconds,
                self._fatal_exit,
                STARTUP_TIMEOUT_EXIT_CODE,
            )
            future.add_done_callback(self._discard_late_result)
            raise
        except BaseException as exc:
            self._mark_unavailable("initialization_failed")
            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._executor = None
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        # The initializer is a startup-only owner.  Its worker thread must be
        # fully joined before the immutable READY inventory is captured;
        # otherwise READY would attest a thread that disappears before the
        # first BEGIN edge.
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        try:
            if self._broker_client is None:
                raise RuntimeError("broker client is unavailable")
            framework_thread_baseline = await _preseed_framework_thread_pools(
                self._broker_client.post_release_baseline()
            )
        except BaseException as exc:
            self._mark_unavailable("framework_thread_baseline_failed")
            _clear_owned_converters(owned)
            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._executor = None
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        with self._condition:
            adopt = self._state is WorkerState.INITIALIZING
            if adopt:
                self._owned = owned
                self._owned_instance_identity = (
                    id(owned.pdf),
                    id(owned.image),
                    id(owned.conversion_lock),
                )
                self._state = WorkerState.READY
                self._ready_at_ns = self._clock_ns()
                self._failure_code = None
                self._framework_thread_baseline = framework_thread_baseline
                self._condition.notify_all()
        if not adopt:
            _clear_owned_converters(owned)
            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._executor = None
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        try:
            if self._request_control is None:
                raise RuntimeError("parser request-control capability is unavailable")
            self._request_control.bind_runtime(self)
        except BaseException as exc:
            self._mark_unavailable("request_control_unavailable")
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        return self.snapshot()


    def _validate_ready(self, settings: Settings) -> None:
        with self._condition:
            ready = self._state is WorkerState.READY and self._owned is not None
            owned = self._owned
            converter_sha256 = self._converter_sha256
            offline_environment_sha256 = self._offline_environment_sha256
            instance_identity = self._owned_instance_identity
        if (
            not ready
            or os.getpid() != self._owner_pid
            or _settings_sha256(settings) != self._settings_sha256
            or settings.docling_artifacts_path is None
            or self._artifacts is None
            or owned is None
            or converter_sha256 is None
            or offline_environment_sha256 is None
            or instance_identity
            != (id(owned.pdf), id(owned.image), id(owned.conversion_lock))
        ):
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        try:
            metadata_sha256 = self._metadata_validator(settings.docling_artifacts_path)
            current_dependencies = self._dependency_validator(settings)
            current_converter_sha256 = self._converter_validator(owned, settings)
            current_offline_environment_sha256 = self._offline_validator()
        except BaseException as exc:
            self._mark_unavailable("runtime_identity_unavailable")
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        if not hmac.compare_digest(
            metadata_sha256,
            self._artifacts.metadata_sha256,
        ):
            self._mark_unavailable("artifact_metadata_changed")
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        if self._dependencies is None or not hmac.compare_digest(
            current_dependencies.sha256,
            self._dependencies.sha256,
        ):
            self._mark_unavailable("dependency_identity_changed")
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        if not hmac.compare_digest(current_converter_sha256, converter_sha256):
            self._mark_unavailable("converter_identity_changed")
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        if not hmac.compare_digest(
            current_offline_environment_sha256,
            offline_environment_sha256,
        ):
            self._mark_unavailable("offline_environment_changed")
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )

    @contextmanager
    def lease(
        self,
        settings: Settings,
        *,
        request_id: str | None = None,
        binding: dict[str, Any] | None = None,
    ) -> Iterator[ParserWorkerRuntime]:
        self._validate_ready(settings)
        if not request_id or binding is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        self._broker_request_lock.acquire()
        conversion_lock: threading.Lock | None = None
        broker_lease: Any | None = None
        try:
            with self._condition:
                if self._state is not WorkerState.READY or self._owned is None:
                    raise ExtractionEngineUnavailableError(
                        details={"component": "parser_worker", "reason": "unavailable"}
                    )
                conversion_lock = self._owned.conversion_lock
            # Admission owns the exact predecessor conversion lock before the
            # broker BEGIN edge.  The pipeline detects this thread-local
            # ownership and does not recursively acquire the non-reentrant lock.
            conversion_lock.acquire()
            with self._condition:
                if self._state is not WorkerState.READY or self._owned is None:
                    raise ExtractionEngineUnavailableError(
                        details={"component": "parser_worker", "reason": "unavailable"}
                    )
                self._active_leases += 1
                self._local.lease_depth = (
                    int(getattr(self._local, "lease_depth", 0)) + 1
                )
                self._local.conversion_lock_held = True
            client = self._broker_client
            if client is None:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            deadline_ns = min(
                client.config.attempt_deadline_monotonic_ns,
                time.monotonic_ns()
                + math.ceil(settings.document_timeout_seconds * 1_000_000_000),
            )
            broker_lease = client.begin_phase(
                "request",
                request_id,
                binding,
                phase_deadline_monotonic_ns=deadline_ns,
            )
            barrier = client.barrier_snapshot()
            with self._condition:
                self._broker_barrier = barrier
                self._condition.notify_all()
                while (
                    barrier is not None
                    and barrier.kind == "BEGIN"
                    and client.barrier_snapshot() is not None
                ):
                    remaining_ns = deadline_ns - time.monotonic_ns()
                    if remaining_ns <= 0:
                        self._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                        raise ExtractionEngineUnavailableError(
                            details={
                                "component": "parser_worker",
                                "reason": "unavailable",
                            }
                        )
                    self._condition.wait(min(0.1, remaining_ns / 1_000_000_000))
            try:
                yield self
            except BaseException as exc:
                receipt = client.abort_phase(broker_lease, exc)
                self._last_broker_receipt = receipt
                with self._condition:
                    self._broker_barrier = client.barrier_snapshot()
                    self._condition.notify_all()
                    while self._broker_barrier is not None:
                        remaining_ns = deadline_ns - time.monotonic_ns()
                        if remaining_ns <= 0:
                            self._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                            raise ExtractionEngineUnavailableError(
                                details={
                                    "component": "parser_worker",
                                    "reason": "unavailable",
                                }
                            ) from exc
                        self._condition.wait(
                            min(0.1, remaining_ns / 1_000_000_000)
                        )
                raise
            else:
                receipt = client.end_phase(broker_lease)
                self._last_broker_receipt = receipt
                with self._condition:
                    self._broker_barrier = client.barrier_snapshot()
                    self._condition.notify_all()
                    while self._broker_barrier is not None:
                        remaining_ns = deadline_ns - time.monotonic_ns()
                        if remaining_ns <= 0:
                            self._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                            raise ExtractionEngineUnavailableError(
                                details={
                                    "component": "parser_worker",
                                    "reason": "unavailable",
                                }
                            )
                        self._condition.wait(
                            min(0.1, remaining_ns / 1_000_000_000)
                        )
        finally:
            with self._condition:
                lease_depth = int(getattr(self._local, "lease_depth", 0))
                if lease_depth:
                    self._local.lease_depth = lease_depth - 1
                    self._active_leases -= 1
                self._local.conversion_lock_held = False
                self._condition.notify_all()
            if conversion_lock is not None:
                conversion_lock.release()
            self._broker_request_lock.release()
            self._finalize_shutdown_if_drained()

    def conversion_lock_held_by_current_thread(self) -> bool:
        return bool(getattr(self._local, "conversion_lock_held", False))

    def fork_denial_evidence(self) -> WorkerForkDenialEvidence:
        evidence = self._fork_denial_evidence
        if evidence is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        return evidence

    def framework_thread_baseline(self) -> FrameworkThreadBaseline:
        baseline = self._framework_thread_baseline
        if baseline is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        return baseline

    def broker_process_identity(self) -> CustodiedProcessIdentity:
        return self.fork_denial_evidence().broker

    def phase_control_snapshot(self) -> Any:
        phase_control = self._phase_control
        if phase_control is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        return phase_control.snapshot()

    def broker_barrier_snapshot(self) -> BrokerBarrierSnapshot | None:
        with self._condition:
            return self._broker_barrier

    def arm_broker_request(
        self,
        request_id: str,
        binding: Mapping[str, Any],
        *,
        phase_deadline_monotonic_ns: int | None = None,
        arm_issued_at_monotonic_ns: int | None = None,
    ) -> ArmedBrokerRequestSnapshot:
        return self._asgi_boundary.arm(
            request_id,
            binding,
            phase_deadline_monotonic_ns=phase_deadline_monotonic_ns,
            arm_issued_at_monotonic_ns=arm_issued_at_monotonic_ns,
        )

    def armed_broker_request_snapshot(self) -> ArmedBrokerRequestSnapshot | None:
        return self._asgi_boundary.snapshot()

    def wait_for_controller_arm(self) -> bool:
        control = self._request_control
        return bool(
            control is not None
            and control.wait_for_arm(self.settings.document_timeout_seconds)
        )

    def publish_broker_request_result(self, result: Mapping[str, Any]) -> None:
        control = self._request_control
        if control is None:
            raise RuntimeError("request-control capability is unavailable")
        control.publish_result(result)

    def request_control_snapshot(self) -> Any:
        control = self._request_control
        if control is None:
            raise RuntimeError("request-control capability is unavailable")
        return control.snapshot()

    def pending_asgi_response_witness(self) -> dict[str, Any] | None:
        return self._asgi_boundary.response_witness()

    def has_current_armed_broker_request(self) -> bool:
        return self._asgi_boundary.current()

    def claim_armed_broker_request(self) -> Any:
        return self._asgi_boundary.claim_conversion()

    def validate_armed_request_input(
        self,
        data: bytes,
        safe_filename: str,
        upload_content_type: str,
        output_format: str,
    ) -> None:
        self._asgi_boundary.bind_actual_request(
            data=data,
            safe_filename=safe_filename,
            upload_content_type=upload_content_type,
            output_format=output_format,
        )

    def release_broker_begin(self, request_id: str, request_epoch: int) -> None:
        client = self._broker_client
        with self._condition:
            barrier = self._broker_barrier
            if (
                client is None
                or barrier is None
                or barrier.kind != "BEGIN"
                or barrier.request_id != request_id
                or barrier.request_epoch != request_epoch
            ):
                raise RuntimeError("broker BEGIN release binding differs")
            client.release_begin()
            self._broker_barrier = None
            self._condition.notify_all()

    def pending_broker_request_receipt(self) -> BrokerRequestReceipt | None:
        client = self._broker_client
        return client.pending_receipt() if client is not None else None

    def release_broker_request_receipt(
        self,
        request_id: str,
        request_epoch: int,
        receipt_sha256: str,
    ) -> BrokerRequestReceipt:
        client = self._broker_client
        if client is None:
            raise RuntimeError("broker client is unavailable")
        receipt = client.pending_receipt()
        if (
            receipt is None
            or receipt.request_id != request_id
            or receipt.request_epoch != request_epoch
            or receipt.receipt_sha256 != receipt_sha256
        ):
            raise RuntimeError("broker receipt release binding differs")
        released = client.release_receipt(receipt)
        with self._condition:
            self._broker_barrier = None
            self._condition.notify_all()
        return released

    def last_broker_request_receipt(self) -> BrokerRequestReceipt | None:
        return self._last_broker_receipt

    def startup_broker_receipt(self) -> BrokerRequestReceipt:
        with self._condition:
            receipt = self._startup_broker_receipt
        if receipt is None:
            raise RuntimeError("startup broker receipt is unavailable")
        return receipt

    def shutdown_broker_receipt(self) -> BrokerRequestReceipt:
        with self._condition:
            receipt = self._shutdown_broker_receipt
        if receipt is None:
            raise RuntimeError("shutdown broker receipt is unavailable")
        return receipt

    def converter_for(self, input_kind: InputKind) -> tuple[Any, threading.Lock]:
        with self._condition:
            if (
                self._state is not WorkerState.READY
                or self._owned is None
                or os.getpid() != self._owner_pid
                or int(getattr(self._local, "lease_depth", 0)) <= 0
            ):
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            converter = (
                self._owned.pdf if input_kind is InputKind.PDF else self._owned.image
            )
            return converter, self._owned.conversion_lock

    def optional_model_decisions(self) -> tuple[bool, bool]:
        with self._condition:
            if self._owned is None or int(getattr(self._local, "lease_depth", 0)) <= 0:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            return (
                self._owned.picture_classifier_enabled,
                self._owned.picture_description_enabled,
            )

    def _wait_for_leases(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._active_leases:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    async def shutdown(self) -> WorkerSnapshot:
        with self._condition:
            if self._state is WorkerState.CLOSED:
                already_closed = True
                future = None
                timer = None
            else:
                already_closed = False
                self._state = WorkerState.STOPPING
                future = self._future
                timer = self._fatal_timer
                self._fatal_timer = None
                self._condition.notify_all()
        if already_closed:
            return self.snapshot()
        if timer is not None:
            timer.cancel()
            if timer is not threading.current_thread():
                timer.join(timeout=0.25)
        grace = self.settings.parser_latency_prewarm_shutdown_grace_seconds
        if future is not None and not future.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(future)),
                    timeout=grace,
                )
            except asyncio.TimeoutError:
                self._fatal_exit(SHUTDOWN_TIMEOUT_EXIT_CODE)
            except asyncio.CancelledError:
                self._fatal_exit(SHUTDOWN_TIMEOUT_EXIT_CODE)
                raise
            except BaseException:
                pass
        try:
            leases_closed = await asyncio.to_thread(self._wait_for_leases, grace)
        except asyncio.CancelledError:
            self._fatal_exit(SHUTDOWN_TIMEOUT_EXIT_CODE)
            raise
        if not leases_closed:
            self._fatal_exit(SHUTDOWN_TIMEOUT_EXIT_CODE)
        client = self._broker_client
        if client is not None:
            try:
                request_control = self._request_control
                if request_control is None:
                    raise RuntimeError("request-control capability is unavailable")
                _require_request_control_complete_before_shutdown(
                    request_control
                )
                phase_control = self._phase_control
                if phase_control is None:
                    raise RuntimeError("parser phase-control capability is unavailable")
                deadline_ns = min(
                    client.config.attempt_deadline_monotonic_ns,
                    time.monotonic_ns() + math.ceil(grace * 1_000_000_000),
                )
                phase_snapshot = phase_control.advance("shutdown", deadline_ns)
                if phase_snapshot.phase_record.deadline_monotonic_ns != deadline_ns:
                    raise RuntimeError("shutdown phase deadline differs")
                with client.phase(
                    "shutdown",
                    "parser-shutdown",
                    {"owner_pid": self._owner_pid},
                    phase_deadline_monotonic_ns=deadline_ns,
                ):
                    if not self._finalize_shutdown_if_drained(
                        broker_shutdown_lease=True
                    ):
                        raise RuntimeError("parser converters did not drain")
                    # Converter destructors/finalizers must run while the
                    # shutdown broker lease and fork denial are still active.
                    gc.collect()
                shutdown_receipt = client.last_receipt()
                if (
                    shutdown_receipt is None
                    or shutdown_receipt.logical_phase != "shutdown"
                    or shutdown_receipt.terminal_kind != "end"
                ):
                    raise RuntimeError("shutdown broker receipt is unavailable")
                with self._condition:
                    self._shutdown_broker_receipt = shutdown_receipt
                client.close()
                self._broker_client = None
                phase_control.close()
                self._phase_control = None
                request_control.close()
                self._request_control = None
            except BaseException:
                self._fatal_exit(SHUTDOWN_TIMEOUT_EXIT_CODE)
                raise
        else:
            self._finalize_shutdown_if_drained()
        return self.snapshot()


class BrokerInstrumentedLazyRuntime:
    """Private evidence-only broker lifecycle around the exact lazy predecessor.

    This runtime is reachable only when the pre-import supervisor has installed
    a validated one-to-one broker capability while public prewarming remains
    disabled.  It deliberately owns no converter and does not initialize one at
    startup; the predecessor's cached converter builders remain authoritative.
    """

    instrument_only = True

    def __init__(
        self,
        settings: Settings,
        *,
        fatal_exit: Callable[[int], Any] = os._exit,
        broker_client_resolver: Callable[[], Any] | None = None,
        fork_denial_resolver: Callable[[], WorkerForkDenialEvidence] | None = None,
        phase_control_resolver: Callable[[], Any] | None = None,
        request_control_resolver: Callable[[], Any] | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if settings.parser_latency_prewarm_enabled:
            raise ValueError("lazy broker instrumentation requires prewarming disabled")
        if (
            broker_client_resolver is None
            or fork_denial_resolver is None
            or phase_control_resolver is None
            or request_control_resolver is None
        ):
            from app.services.tesseract_broker_client import (
                require_tesseract_broker_client,
                worker_fork_denial_evidence,
            )

            broker_client_resolver = (
                broker_client_resolver or require_tesseract_broker_client
            )
            fork_denial_resolver = (
                fork_denial_resolver or worker_fork_denial_evidence
            )
            from app.services.parser_phase_control import (
                require_parser_phase_control,
            )

            phase_control_resolver = (
                phase_control_resolver or require_parser_phase_control
            )
            from app.services.parser_request_control import (
                require_parser_request_control,
            )

            request_control_resolver = (
                request_control_resolver or require_parser_request_control
            )
        self.settings = settings
        self._owner_pid = os.getpid()
        self._settings_sha256 = _settings_sha256(settings)
        self._fatal_exit = fatal_exit
        self._broker_client_resolver = broker_client_resolver
        self._fork_denial_resolver = fork_denial_resolver
        self._phase_control_resolver = phase_control_resolver
        self._request_control_resolver = request_control_resolver
        self._clock_ns = clock_ns
        self._condition = threading.Condition()
        self._local = threading.local()
        self._state = WorkerState.CREATED
        self._failure_code: str | None = None
        self._initialization_started_ns: int | None = None
        self._ready_at_ns: int | None = None
        self._active_leases = 0
        self._broker_client: Any | None = None
        self._fork_denial_evidence: WorkerForkDenialEvidence | None = None
        self._phase_control: Any | None = None
        self._request_control: Any | None = None
        self._conversion_lock: threading.Lock | None = None
        self._broker_request_lock = threading.Lock()
        self._broker_barrier: BrokerBarrierSnapshot | None = None
        self._last_broker_receipt: BrokerRequestReceipt | None = None
        self._startup_broker_receipt: BrokerRequestReceipt | None = None
        self._shutdown_broker_receipt: BrokerRequestReceipt | None = None
        self._framework_thread_baseline: FrameworkThreadBaseline | None = None
        self._asgi_boundary = _BrokerASGIRequestBoundary(self)

    def snapshot(self) -> WorkerSnapshot:
        with self._condition:
            return WorkerSnapshot(
                state=self._state,
                owner_pid=self._owner_pid,
                settings_sha256=self._settings_sha256,
                artifacts_sha256=None,
                artifact_metadata_sha256=None,
                dependency_sha256=None,
                converter_sha256=None,
                offline_environment_sha256=None,
                initialization_started_ns=self._initialization_started_ns,
                ready_at_ns=self._ready_at_ns,
                failure_code=self._failure_code,
                active_leases=self._active_leases,
            )

    def _bind_supervised_broker(self) -> None:
        try:
            client = self._broker_client_resolver()
            evidence = self._fork_denial_resolver()
            phase_control = self._phase_control_resolver()
            request_control = self._request_control_resolver()
            phase_snapshot = phase_control.snapshot()
            config = client.config
            if (
                evidence.worker.pid != self._owner_pid
                or evidence.worker.process_group_id != self._owner_pid
                or evidence.worker.session_id != self._owner_pid
                or evidence.broker.pid != config.broker_pid
                or evidence.broker.start_abstime != config.broker_start_abstime
                or evidence.broker.process_group_id != config.broker_pgid
                or evidence.broker.session_id != config.broker_sid
                or evidence.native_closure_sha256
                != config.native_closure_sha256
                or evidence.broker_native_spawn_guard_library_sha256
                != config.native_spawn_guard_sha256
                or evidence.broker_native_spawn_guard_source_sha256
                != config.native_spawn_guard_source_sha256
                or evidence.native_runtime_gate_source_sha256
                != config.native_runtime_gate_source_sha256
                or evidence.native_runtime_gate_library_sha256
                != config.native_runtime_gate_library_sha256
                or evidence.native_runtime_gate_record_sha256
                != config.native_runtime_gate_record_sha256
                or evidence.native_trust_model
                != "frozen-native-closure-trusted-v1"
                or evidence.native_containment_claim
                != "none-trusted-pinned-native-computation"
                or self.settings.tesseract_cmd != config.executable
                or self.settings.tesseract_data_path != config.tessdata_root
                or any(
                    language not in config.languages
                    for language in self.settings.ocr_languages
                )
                or phase_snapshot.phase_record.phase != "startup"
                or phase_control.worker_pid != self._owner_pid
                or request_control.worker_identity.pid != self._owner_pid
                or request_control.broker_identity.pid != config.broker_pid
                or request_control.broker_identity.start_abstime
                != config.broker_start_abstime
                or request_control.attempt_nonce_sha256
                != config.attempt_nonce_sha256
                or request_control.scope_sha256 != config.scope_sha256
            ):
                raise RuntimeError("supervised predecessor broker identity differs")
        except BaseException as exc:
            with self._condition:
                self._state = WorkerState.UNAVAILABLE
                self._failure_code = "broker_capability_unavailable"
                self._condition.notify_all()
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        self._broker_client = client
        self._fork_denial_evidence = evidence
        self._phase_control = phase_control
        self._request_control = request_control

    async def start(self) -> WorkerSnapshot:
        with self._condition:
            if self._state is not WorkerState.CREATED or os.getpid() != self._owner_pid:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            self._initialization_started_ns = self._clock_ns()
        self._bind_supervised_broker()
        client = self._broker_client
        if client is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        # Importing the pipeline obtains only the predecessor's process-global
        # conversion lock.  It does not construct or initialize a converter.
        from app.services import pipeline

        self._conversion_lock = pipeline._DOCLING_CONVERSION_LOCK
        deadline_ns = min(
            client.config.attempt_deadline_monotonic_ns,
            self._phase_control.snapshot().phase_record.deadline_monotonic_ns,
            time.monotonic_ns()
            + math.ceil(self.settings.document_timeout_seconds * 1_000_000_000),
        )
        try:
            with client.phase(
                "startup",
                "parser-lazy-startup",
                {
                    "settings_sha256": self._settings_sha256,
                    "owner_pid": self._owner_pid,
                    "instrument_only": True,
                },
                phase_deadline_monotonic_ns=deadline_ns,
            ):
                pass
            startup_receipt = client.last_receipt()
            if (
                startup_receipt is None
                or startup_receipt.logical_phase != "startup"
                or startup_receipt.terminal_kind != "end"
            ):
                raise RuntimeError("startup broker receipt is unavailable")
            with self._condition:
                self._startup_broker_receipt = startup_receipt
        except BaseException as exc:
            with self._condition:
                self._state = WorkerState.UNAVAILABLE
                self._failure_code = "broker_startup_failed"
                self._condition.notify_all()
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        try:
            if self._broker_client is None:
                raise RuntimeError("broker client is unavailable")
            framework_thread_baseline = await _preseed_framework_thread_pools(
                self._broker_client.post_release_baseline()
            )
        except BaseException as exc:
            with self._condition:
                self._state = WorkerState.UNAVAILABLE
                self._failure_code = "framework_thread_baseline_failed"
                self._condition.notify_all()
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        with self._condition:
            self._state = WorkerState.READY
            self._ready_at_ns = self._clock_ns()
            self._framework_thread_baseline = framework_thread_baseline
            self._condition.notify_all()
        try:
            if self._request_control is None:
                raise RuntimeError("parser request-control capability is unavailable")
            self._request_control.bind_runtime(self)
        except BaseException as exc:
            with self._condition:
                self._state = WorkerState.UNAVAILABLE
                self._failure_code = "request_control_unavailable"
                self._condition.notify_all()
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            ) from exc
        return self.snapshot()

    @contextmanager
    def lease(
        self,
        settings: Settings,
        *,
        request_id: str | None = None,
        binding: dict[str, Any] | None = None,
    ) -> Iterator[BrokerInstrumentedLazyRuntime]:
        if (
            not request_id
            or binding is None
            or os.getpid() != self._owner_pid
            or _settings_sha256(settings) != self._settings_sha256
        ):
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        self._broker_request_lock.acquire()
        conversion_lock = self._conversion_lock
        if conversion_lock is None:
            self._broker_request_lock.release()
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        conversion_lock.acquire()
        lease_counted = False
        try:
            with self._condition:
                if self._state is not WorkerState.READY:
                    raise ExtractionEngineUnavailableError(
                        details={"component": "parser_worker", "reason": "unavailable"}
                    )
                self._active_leases += 1
                lease_counted = True
                self._local.conversion_lock_held = True
            client = self._broker_client
            if client is None:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )
            deadline_ns = min(
                client.config.attempt_deadline_monotonic_ns,
                time.monotonic_ns()
                + math.ceil(settings.document_timeout_seconds * 1_000_000_000),
            )
            broker_lease = client.begin_phase(
                "request",
                request_id,
                binding,
                phase_deadline_monotonic_ns=deadline_ns,
            )
            with self._condition:
                self._broker_barrier = client.barrier_snapshot()
                self._condition.notify_all()
                while self._broker_barrier is not None:
                    remaining_ns = deadline_ns - time.monotonic_ns()
                    if remaining_ns <= 0:
                        self._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                        raise ExtractionEngineUnavailableError(
                            details={"component": "parser_worker", "reason": "unavailable"}
                        )
                    self._condition.wait(min(0.1, remaining_ns / 1_000_000_000))
            try:
                yield self
            except BaseException as exc:
                receipt = client.abort_phase(broker_lease, exc)
                terminal_error: BaseException | None = exc
            else:
                receipt = client.end_phase(broker_lease)
                terminal_error = None
            self._last_broker_receipt = receipt
            with self._condition:
                self._broker_barrier = client.barrier_snapshot()
                self._condition.notify_all()
                while self._broker_barrier is not None:
                    remaining_ns = deadline_ns - time.monotonic_ns()
                    if remaining_ns <= 0:
                        self._fatal_exit(REQUEST_BARRIER_TIMEOUT_EXIT_CODE)
                        raise ExtractionEngineUnavailableError(
                            details={"component": "parser_worker", "reason": "unavailable"}
                        )
                    self._condition.wait(min(0.1, remaining_ns / 1_000_000_000))
            if terminal_error is not None:
                raise terminal_error
        finally:
            with self._condition:
                self._local.conversion_lock_held = False
                if lease_counted:
                    self._active_leases -= 1
                self._condition.notify_all()
            conversion_lock.release()
            self._broker_request_lock.release()

    def conversion_lock_held_by_current_thread(self) -> bool:
        return bool(getattr(self._local, "conversion_lock_held", False))

    def fork_denial_evidence(self) -> WorkerForkDenialEvidence:
        evidence = self._fork_denial_evidence
        if evidence is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        return evidence

    def framework_thread_baseline(self) -> FrameworkThreadBaseline:
        baseline = self._framework_thread_baseline
        if baseline is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        return baseline

    def broker_process_identity(self) -> CustodiedProcessIdentity:
        return self.fork_denial_evidence().broker

    def phase_control_snapshot(self) -> Any:
        phase_control = self._phase_control
        if phase_control is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        return phase_control.snapshot()

    def broker_barrier_snapshot(self) -> BrokerBarrierSnapshot | None:
        with self._condition:
            return self._broker_barrier

    def arm_broker_request(
        self,
        request_id: str,
        binding: Mapping[str, Any],
        *,
        phase_deadline_monotonic_ns: int | None = None,
        arm_issued_at_monotonic_ns: int | None = None,
    ) -> ArmedBrokerRequestSnapshot:
        return self._asgi_boundary.arm(
            request_id,
            binding,
            phase_deadline_monotonic_ns=phase_deadline_monotonic_ns,
            arm_issued_at_monotonic_ns=arm_issued_at_monotonic_ns,
        )

    def armed_broker_request_snapshot(self) -> ArmedBrokerRequestSnapshot | None:
        return self._asgi_boundary.snapshot()

    def wait_for_controller_arm(self) -> bool:
        control = self._request_control
        return bool(
            control is not None
            and control.wait_for_arm(self.settings.document_timeout_seconds)
        )

    def publish_broker_request_result(self, result: Mapping[str, Any]) -> None:
        control = self._request_control
        if control is None:
            raise RuntimeError("request-control capability is unavailable")
        control.publish_result(result)

    def request_control_snapshot(self) -> Any:
        control = self._request_control
        if control is None:
            raise RuntimeError("request-control capability is unavailable")
        return control.snapshot()

    def pending_asgi_response_witness(self) -> dict[str, Any] | None:
        return self._asgi_boundary.response_witness()

    def has_current_armed_broker_request(self) -> bool:
        return self._asgi_boundary.current()

    def claim_armed_broker_request(self) -> Any:
        return self._asgi_boundary.claim_conversion()

    def validate_armed_request_input(
        self,
        data: bytes,
        safe_filename: str,
        upload_content_type: str,
        output_format: str,
    ) -> None:
        self._asgi_boundary.bind_actual_request(
            data=data,
            safe_filename=safe_filename,
            upload_content_type=upload_content_type,
            output_format=output_format,
        )

    def release_broker_begin(self, request_id: str, request_epoch: int) -> None:
        client = self._broker_client
        with self._condition:
            barrier = self._broker_barrier
            if (
                client is None
                or barrier is None
                or barrier.kind != "BEGIN"
                or barrier.request_id != request_id
                or barrier.request_epoch != request_epoch
            ):
                raise RuntimeError("broker BEGIN release binding differs")
            client.release_begin()
            self._broker_barrier = None
            self._condition.notify_all()

    def pending_broker_request_receipt(self) -> BrokerRequestReceipt | None:
        client = self._broker_client
        return client.pending_receipt() if client is not None else None

    def release_broker_request_receipt(
        self,
        request_id: str,
        request_epoch: int,
        receipt_sha256: str,
    ) -> BrokerRequestReceipt:
        client = self._broker_client
        if client is None:
            raise RuntimeError("broker client is unavailable")
        receipt = client.pending_receipt()
        if (
            receipt is None
            or receipt.request_id != request_id
            or receipt.request_epoch != request_epoch
            or receipt.receipt_sha256 != receipt_sha256
        ):
            raise RuntimeError("broker receipt release binding differs")
        released = client.release_receipt(receipt)
        with self._condition:
            self._broker_barrier = None
            self._condition.notify_all()
        return released

    def last_broker_request_receipt(self) -> BrokerRequestReceipt | None:
        return self._last_broker_receipt

    def startup_broker_receipt(self) -> BrokerRequestReceipt:
        with self._condition:
            receipt = self._startup_broker_receipt
        if receipt is None:
            raise RuntimeError("startup broker receipt is unavailable")
        return receipt

    def shutdown_broker_receipt(self) -> BrokerRequestReceipt:
        with self._condition:
            receipt = self._shutdown_broker_receipt
        if receipt is None:
            raise RuntimeError("shutdown broker receipt is unavailable")
        return receipt

    def _wait_for_leases(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._active_leases:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    async def shutdown(self) -> WorkerSnapshot:
        with self._condition:
            if self._state is WorkerState.CLOSED:
                return self.snapshot()
            self._state = WorkerState.STOPPING
            self._condition.notify_all()
        grace = self.settings.document_timeout_seconds
        try:
            drained = await asyncio.to_thread(self._wait_for_leases, grace)
        except asyncio.CancelledError:
            self._fatal_exit(SHUTDOWN_TIMEOUT_EXIT_CODE)
            raise
        if not drained:
            self._fatal_exit(SHUTDOWN_TIMEOUT_EXIT_CODE)
        client = self._broker_client
        if client is not None:
            try:
                request_control = self._request_control
                if request_control is None:
                    raise RuntimeError("request-control capability is unavailable")
                _require_request_control_complete_before_shutdown(
                    request_control
                )
                phase_control = self._phase_control
                if phase_control is None:
                    raise RuntimeError("parser phase-control capability is unavailable")
                deadline_ns = min(
                    client.config.attempt_deadline_monotonic_ns,
                    time.monotonic_ns() + math.ceil(grace * 1_000_000_000),
                )
                phase_snapshot = phase_control.advance("shutdown", deadline_ns)
                if phase_snapshot.phase_record.deadline_monotonic_ns != deadline_ns:
                    raise RuntimeError("shutdown phase deadline differs")
                with client.phase(
                    "shutdown",
                    "parser-lazy-shutdown",
                    {"owner_pid": self._owner_pid, "instrument_only": True},
                    phase_deadline_monotonic_ns=deadline_ns,
                ):
                    gc.collect()
                shutdown_receipt = client.last_receipt()
                if (
                    shutdown_receipt is None
                    or shutdown_receipt.logical_phase != "shutdown"
                    or shutdown_receipt.terminal_kind != "end"
                ):
                    raise RuntimeError("shutdown broker receipt is unavailable")
                with self._condition:
                    self._shutdown_broker_receipt = shutdown_receipt
                client.close()
                phase_control.close()
                request_control.close()
            except BaseException:
                self._fatal_exit(SHUTDOWN_TIMEOUT_EXIT_CODE)
                raise
            self._broker_client = None
            self._phase_control = None
            self._request_control = None
        with self._condition:
            self._state = WorkerState.CLOSED
            self._condition.notify_all()
        return self.snapshot()


class BrokerRequestBoundaryMiddleware:
    """Measure one armed parse through the inner ASGI callable's return."""

    _MAX_CAPTURED_RESPONSE_BYTES = 128 * 1024 * 1024

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/v1/parse":
            await self.app(scope, receive, send)
            return
        application = scope.get("app")
        state = getattr(application, "state", None)
        runtime = (
            getattr(state, PREWARM_RUNTIME_STATE_KEY, None)
            if state is not None
            else None
        )
        boundary = getattr(runtime, "_asgi_boundary", None)
        if boundary is None:
            await self.app(scope, receive, send)
            return
        if boundary.snapshot() is None:
            request_control = getattr(runtime, "_request_control", None)
            if request_control is None:
                await self.app(scope, receive, send)
                return
            armed = await asyncio.to_thread(runtime.wait_for_controller_arm)
            if not armed or boundary.snapshot() is None:
                raise ExtractionEngineUnavailableError(
                    details={"component": "parser_worker", "reason": "unavailable"}
                )

        token = boundary.enter_asgi(scope)
        if token is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        body_bytes = 0
        response_started = False
        response_finished = False
        response_status = 0
        ordered_headers: list[dict[str, str]] = []
        response_start_message_keys: list[str] = []
        response_body_message_keys: list[str] = []
        response_start_send_completed_monotonic_ns = 0
        response_body_send_completed_monotonic_ns = 0
        response_body_sha256 = ""

        async def bounded_send(message: dict[str, Any]) -> None:
            nonlocal body_bytes, response_started, response_finished
            nonlocal response_status, ordered_headers
            nonlocal response_start_message_keys, response_body_message_keys
            nonlocal response_start_send_completed_monotonic_ns
            nonlocal response_body_send_completed_monotonic_ns
            nonlocal response_body_sha256
            if not isinstance(message, dict):
                raise RuntimeError("ASGI response message is malformed")
            message_type = message.get("type")
            if message_type == "http.response.start":
                status = message.get("status")
                headers = message.get("headers")
                if (
                    response_started
                    or response_finished
                    or set(message) != {"type", "status", "headers"}
                    or isinstance(status, bool)
                    or not isinstance(status, int)
                    or not 100 <= status <= 599
                    or not isinstance(headers, list)
                    or any(
                        not isinstance(item, tuple)
                        or len(item) != 2
                        or not isinstance(item[0], bytes)
                        or not isinstance(item[1], bytes)
                        for item in headers
                    )
                ):
                    raise RuntimeError("ASGI response start was repeated")
                response_status = status
                response_start_message_keys = sorted(message)
                ordered_headers = [
                    {"name_hex": name.hex(), "value_hex": value.hex()}
                    for name, value in headers
                ]
                response_started = True
            elif message_type == "http.response.body":
                body = message.get("body", b"")
                more_body = message.get("more_body", False)
                if (
                    not response_started
                    or response_finished
                    or set(message)
                    not in ({"type", "body"}, {"type", "body", "more_body"})
                    or not isinstance(body, bytes)
                    or type(more_body) is not bool
                    or more_body
                ):
                    # Production parse responses are fully materialized.  A
                    # streaming response would put work outside the CPU edge.
                    raise RuntimeError("streaming ASGI response is not evidence-safe")
                body_bytes += len(body)
                if body_bytes > self._MAX_CAPTURED_RESPONSE_BYTES:
                    raise RuntimeError("captured ASGI response exceeds its bound")
                response_body_message_keys = sorted(message)
                response_body_sha256 = hashlib.sha256(body).hexdigest()
                response_finished = True
            else:
                raise RuntimeError("unexpected ASGI response message")
            # Transport/copy work is deliberately inside the measured edge.
            await send(message)
            completed = time.monotonic_ns()
            if message_type == "http.response.start":
                response_start_send_completed_monotonic_ns = completed
            else:
                response_body_send_completed_monotonic_ns = completed

        try:
            await self.app(scope, receive, bounded_send)
            if not response_started or not response_finished:
                raise RuntimeError("ASGI response did not complete")
            # The inner callable has returned here, so dependency teardown and
            # Starlette background callbacks are inside the measured boundary.
            inner_asgi_returned_monotonic_ns = time.monotonic_ns()
            response_witness: dict[str, Any] = {
                "schema_id": "parser-asgi-response-witness-v1",
                "status_code": response_status,
                "response_start_message_keys": response_start_message_keys,
                "ordered_headers": ordered_headers,
                "headers_sha256": _canonical_sha256(
                    {"ordered_headers": ordered_headers}
                ),
                "response_start_send_completed_monotonic_ns": (
                    response_start_send_completed_monotonic_ns
                ),
                "response_body_message_keys": response_body_message_keys,
                "body_sha256": response_body_sha256,
                "body_bytes": body_bytes,
                "response_body_send_completed_monotonic_ns": (
                    response_body_send_completed_monotonic_ns
                ),
                "inner_asgi_returned_monotonic_ns": (
                    inner_asgi_returned_monotonic_ns
                ),
            }
            response_witness["record_sha256"] = _canonical_sha256(
                response_witness
            )
            boundary.response_materialized(response_witness)
        except BaseException as exc:
            boundary.finish_asgi(exc, token)
            raise
        else:
            boundary.finish_asgi(None, token)


@asynccontextmanager
async def parser_worker_lifespan(application: FastAPI) -> Iterator[None]:
    settings = get_settings()
    runtime = ParserWorkerRuntime(settings)
    setattr(application.state, PREWARM_RUNTIME_STATE_KEY, runtime)
    try:
        await runtime.start()
        yield
    finally:
        try:
            await runtime.shutdown()
        finally:
            if getattr(application.state, PREWARM_RUNTIME_STATE_KEY, None) is runtime:
                delattr(application.state, PREWARM_RUNTIME_STATE_KEY)


@asynccontextmanager
async def instrumented_lazy_parser_lifespan(
    application: FastAPI,
) -> Iterator[None]:
    settings = get_settings()
    runtime = BrokerInstrumentedLazyRuntime(settings)
    setattr(application.state, PREWARM_RUNTIME_STATE_KEY, runtime)
    try:
        await runtime.start()
        yield
    finally:
        try:
            await runtime.shutdown()
        finally:
            if getattr(application.state, PREWARM_RUNTIME_STATE_KEY, None) is runtime:
                delattr(application.state, PREWARM_RUNTIME_STATE_KEY)
