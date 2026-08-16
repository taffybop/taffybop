"""Dedicated, spawn-authorized broker for one fork-denied parser worker."""

from __future__ import annotations

import argparse
import array
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import resource
import secrets
import selectors
import signal
import socket
import stat
import sys
import termios
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.tesseract_broker_native import (
    group_inventory,
    kernel_process_identity,
    native_detailed_file_descriptor_inventory,
    native_detailed_thread_inventory,
    native_executable_region_inventory,
    native_file_descriptor_inventory_from_mapping,
    native_process_path,
    native_thread_inventory,
    native_thread_inventory_from_mapping,
    native_wait4_exact,
    native_wait4_quiescence,
    raw_process_start_abstime,
    recursive_descendants,
    trusted_launcher_identity,
)
from app.services.tesseract_broker_protocol import (
    BROKER_PROTOCOL_SCHEMA,
    BROKER_AUDIT_COMMITMENT_BYTES,
    BROKER_AUDIT_CHILD_KIND_MAX_BYTES,
    BrokerChildBirth,
    BrokerChildBirthCommitment,
    BrokerChildFileDescriptorIdentity,
    BrokerChildSandboxProbeReport,
    BrokerChildWait4Tombstone,
    BrokerExecutableIdentity,
    BrokerForkDenialIdentity,
    BrokerProtocolError,
    BrokerPostReleaseBaseline,
    BrokerQuiescenceReceipt,
    BrokerRequestReceipt,
    BrokerRunInputManifest,
    BrokerScratchInventory,
    BrokerThreadTransfer,
    FramedChannel,
    KernelProcessIdentity,
    MAX_CAPTURE_BYTES,
    MAX_BROKER_AUDIT_BLOB_BYTES,
    MAX_BROKER_AUDIT_CHILD_BLOB_BYTES,
    MAX_BROKER_AUDIT_LEDGER_BYTES,
    MAX_BROKER_AUDIT_NON_CHILD_ROWS,
    MAX_BROKER_AUDIT_PHASE_BLOB_BYTES,
    MAX_REQUEST_RECEIPT_CHILDREN,
    MAX_RUN_INPUT_BYTES,
    MAX_RUN_STDOUT_BYTES,
    MAX_STDERR_BYTES,
    NATIVE_CHILD_LIMIT_ACK_AUTHORITY,
    NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY,
    NATIVE_RUNTIME_GATE_ACK_AUTHORITY,
    NATIVE_RUNTIME_GATE_C_CLOCK_AUTHORITY,
    NativeRuntimeImageAttestation,
    NativeRuntimeScanSample,
    TrustedLauncherIdentity,
    canonical_json_bytes,
    canonical_sha256,
    canonical_tesseract_logical_argv_sha256,
    build_request_receipt_transport,
    build_run_output_transport,
    child_birth_commitment_from_mapping,
    child_sandbox_probe_inheritance_sha256,
    child_sandbox_probe_report_from_mapping,
    child_sandbox_probe_phase_inheritance_head,
    child_watch_birth_from_commitment,
    broker_audit_row_mapping,
    dataclass_mapping,
    embedded_guard_argv,
    native_child_limit_ack_sha256,
    native_runtime_gate_ack_sha256,
    request_receipt_run_reservation_bytes,
    receive_run_blob_chunks,
    run_input_manifest_from_mapping,
    send_run_blob_chunks,
    send_request_receipt_chunks,
    validate_child_sandbox_probe_report_against_plan,
)
from app.services.tesseract_native_closure import (
    NATIVE_CLOSURE_TRUST_MODEL,
    NATIVE_RUNTIME_GATE_ACK_BYTES,
    NATIVE_RUNTIME_GATE_AUTHORITY,
    NATIVE_RUNTIME_GATE_FD,
    NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION,
    NATIVE_RUNTIME_POLLING_COMPLETENESS,
    NATIVE_RUNTIME_SCAN_AUTHORITY,
    derive_native_closure,
    observe_runtime_native_scan,
    validate_native_closure,
)
from app.services.tesseract_child_exec import (
    CHILD_READY_SCHEMA,
    MAX_CHILD_READY_BYTES,
    MAX_NATIVE_CHILD_CONFIG_BYTES,
    NATIVE_CHILD_CONFIG_SCHEMA,
    frozen_tesseract_environment,
    module_sha256 as child_wrapper_sha256,
)
from app.services.tesseract_child_sandbox_probe import (
    CHILD_SANDBOX_EXECUTOR_AUTHORITY,
    MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES,
    child_sandbox_probe_report_reservation_bytes,
    validate_child_sandbox_probe_plan,
)


BROKER_LAUNCH_SCHEMA = "parser-tesseract-broker-launch-template-v1"
BROKER_READY_SCHEMA = "parser-tesseract-broker-ready-v1"
MAX_CONFIG_BYTES = 512 * 1024
MAX_READY_BYTES = 16 * 1024
MAX_LEDGER_BYTES = MAX_BROKER_AUDIT_LEDGER_BYTES
MAX_JOBS_PER_PHASE = MAX_REQUEST_RECEIPT_CHILDREN
NATIVE_RUNTIME_SCAN_INTERVAL_NS = 100_000_000
# Poll well inside the externally claimed maximum cadence.  The margin keeps
# a terminal WNOWAIT observation inside the 100 ms bound even when a child
# exits between a nonterminal peek and the following libproc scan.
NATIVE_RUNTIME_SCAN_POLL_NS = 50_000_000
MAX_NATIVE_RUNTIME_SCAN_SAMPLES = 4_096
MAX_NATIVE_RUNTIME_SCAN_LOG_BYTES = 4 * 1024 * 1024
_ZERO_SHA256 = "0" * 64
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_NATIVE_CHILD_LIMIT_ACK_BYTES = 40
_NATIVE_CHILD_LIMIT_ACK_MAGIC = b"PN0ACK1!"
_NATIVE_RUNTIME_GATE_ACK_MAGIC = b"RTGATE1!"


def _blockable_signal_numbers() -> tuple[int, ...]:
    values = tuple(
        sorted(
            int(value)
            for value in signal.valid_signals()
            if int(value) not in {int(signal.SIGKILL), int(signal.SIGSTOP)}
        )
    )
    if (
        not values
        or int(signal.SIGTERM) not in values
        or int(signal.SIGHUP) not in values
    ):
        raise BrokerProtocolError("blockable signal inventory differs")
    return values


def _pipe_cloexec() -> tuple[int, int]:
    """Create a Darwin-compatible close-on-exec pipe.

    The broker proves it has one thread at every spawn boundary, so the small
    ``pipe``/``set_inheritable`` interval cannot race another local exec.
    """

    reader, writer = os.pipe()
    try:
        os.set_inheritable(reader, False)
        os.set_inheritable(writer, False)
        if os.get_inheritable(reader) or os.get_inheritable(writer):
            raise BrokerProtocolError("broker pipe remained inheritable")
        return reader, writer
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(reader)
        with contextlib.suppress(OSError):
            os.close(writer)
        raise


def _strict_object(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise BrokerProtocolError(f"{name} fields differ")
    return dict(value)


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BrokerProtocolError(f"{name} must be positive")
    return value


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BrokerProtocolError(f"{name} must be nonnegative")
    return value


def _sha(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BrokerProtocolError(f"{name} must be a SHA-256")
    return value


def _read_exact_file(path: str, maximum_bytes: int) -> tuple[bytes, os.stat_result]:
    observed = os.lstat(path)
    if not stat.S_ISREG(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise BrokerProtocolError("custody file is not regular")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
        ) != (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_size,
        ):
            raise BrokerProtocolError("custody file changed before open")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - total)):
            total += len(chunk)
            if total > maximum_bytes:
                raise BrokerProtocolError("custody file exceeds its bound")
            chunks.append(chunk)
        if total != opened.st_size or os.fstat(descriptor).st_mtime_ns != opened.st_mtime_ns:
            raise BrokerProtocolError("custody file changed during read")
        return b"".join(chunks), opened
    finally:
        os.close(descriptor)


def _executable_identity(mapping: object) -> BrokerExecutableIdentity:
    fields = _strict_object(
        mapping,
        {"resolved_path", "sha256", "device", "inode", "mode", "uid", "nlink", "size"},
        "executable identity",
    )
    identity = BrokerExecutableIdentity(**fields)
    body, observed = _read_exact_file(identity.resolved_path, 512 * 1024 * 1024)
    if (
        hashlib.sha256(body).hexdigest() != identity.sha256
        or (observed.st_dev, observed.st_ino, observed.st_mode, observed.st_uid, observed.st_nlink, observed.st_size)
        != (identity.device, identity.inode, identity.mode, identity.uid, identity.nlink, identity.size)
    ):
        raise BrokerProtocolError("executable identity differs from disk")
    return identity


def _observed_file_identity(path: str | os.PathLike[str]) -> BrokerExecutableIdentity:
    resolved = os.path.realpath(os.fspath(path))
    body, observed = _read_exact_file(resolved, 512 * 1024 * 1024)
    return BrokerExecutableIdentity(
        resolved_path=resolved,
        sha256=hashlib.sha256(body).hexdigest(),
        device=int(observed.st_dev),
        inode=int(observed.st_ino),
        mode=int(observed.st_mode),
        uid=int(observed.st_uid),
        nlink=int(observed.st_nlink),
        size=int(observed.st_size),
    )


def derive_guard_python_path_custody(
    path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Bind one root-owned interpreter and every pathname ancestor.

    Darwin lacks an fd-exec primitive.  The approved host therefore uses the
    root-owned Command Line Tools Python and proves that neither the binary nor
    any directory used by pathname resolution is writable by the campaign uid.
    """

    resolved = os.path.realpath(os.fspath(path))
    if (
        not os.path.isabs(resolved)
        or not resolved.startswith(
            "/Library/Developer/CommandLineTools/Library/Frameworks/"
        )
    ):
        raise BrokerProtocolError("guard Python is outside the approved host tree")
    rows: list[dict[str, Any]] = []
    current = Path(resolved)
    while True:
        observed = os.lstat(current)
        if (
            stat.S_ISLNK(observed.st_mode)
            or observed.st_uid != 0
            or observed.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or (
                current == Path(resolved)
                and not stat.S_ISREG(observed.st_mode)
            )
            or (
                current != Path(resolved)
                and not stat.S_ISDIR(observed.st_mode)
            )
        ):
            raise BrokerProtocolError(
                "guard Python path custody is mutable or has the wrong type"
            )
        rows.append(
            {
                "resolved_path": str(current),
                "device": int(observed.st_dev),
                "inode": int(observed.st_ino),
                "mode": int(observed.st_mode),
                "uid": int(observed.st_uid),
                "gid": int(observed.st_gid),
                "nlink": int(observed.st_nlink),
            }
        )
        if current.parent == current:
            break
        current = current.parent
        if len(rows) > 32:
            raise BrokerProtocolError("guard Python path chain exceeds its bound")
    mapping: dict[str, Any] = {
        "schema_id": "parser-root-owned-guard-python-path-v1",
        "resolved_path": resolved,
        "path_resolution_authority": (
            "darwin-root-owned-non-group-world-writable-ancestor-chain-v1"
        ),
        "ancestors": rows,
    }
    mapping["record_sha256"] = canonical_sha256(mapping)
    return mapping


def derive_guard_python_module_tree_custody(
    root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Hash the exact root-owned stdlib/extension tree used by the guard."""

    resolved_root = os.path.realpath(os.fspath(root))
    if (
        not os.path.isabs(resolved_root)
        or not resolved_root.startswith(
            "/Library/Developer/CommandLineTools/Library/Frameworks/"
        )
    ):
        raise BrokerProtocolError("guard Python module root differs")
    root_path = Path(resolved_root)
    records: list[dict[str, Any]] = []
    aggregate_bytes = 0
    for path in (
        root_path,
        *sorted(root_path.rglob("*"), key=lambda item: item.as_posix()),
    ):
        observed = os.lstat(path)
        relative = "." if path == root_path else path.relative_to(root_path).as_posix()
        if (
            observed.st_uid != 0
            or observed.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise BrokerProtocolError("guard Python module tree is mutable")
        common: dict[str, Any] = {
            "path": relative,
            "device": int(observed.st_dev),
            "inode": int(observed.st_ino),
            "mode": int(observed.st_mode),
            "uid": int(observed.st_uid),
            "gid": int(observed.st_gid),
            "nlink": int(observed.st_nlink),
        }
        if stat.S_ISDIR(observed.st_mode):
            record = {**common, "kind": "directory"}
        elif stat.S_ISREG(observed.st_mode):
            body, opened = _read_exact_file(path, 256 * 1024 * 1024)
            if opened.st_ino != observed.st_ino:
                raise BrokerProtocolError("guard Python module file raced")
            aggregate_bytes += len(body)
            record = {
                **common,
                "kind": "regular",
                "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        elif stat.S_ISLNK(observed.st_mode):
            target = os.readlink(path)
            resolved_target = os.path.realpath(path)
            if not (
                resolved_target == resolved_root
                or resolved_target.startswith(resolved_root + os.sep)
            ):
                raise BrokerProtocolError(
                    "guard Python module symlink escapes its root"
                )
            record = {
                **common,
                "kind": "symlink",
                "target": target,
                "resolved_target": resolved_target,
            }
        else:
            raise BrokerProtocolError(
                "guard Python module tree has an unsupported entry"
            )
        records.append(record)
        if len(records) > 8_192 or aggregate_bytes > 512 * 1024 * 1024:
            raise BrokerProtocolError("guard Python module tree exceeds its bound")
    mapping: dict[str, Any] = {
        "schema_id": "parser-root-owned-guard-python-module-tree-v1",
        "resolved_root": resolved_root,
        "entry_count": len(records),
        "aggregate_bytes": aggregate_bytes,
        "root_owned_non_writable": True,
        "records_sha256": canonical_sha256({"records": records}),
    }
    mapping["record_sha256"] = canonical_sha256(mapping)
    return mapping


def _tree_content_identity(root: str) -> str:
    root_path = Path(root)
    root_before = os.lstat(root_path)
    records: list[dict[str, object]] = []
    aggregate_bytes = 0
    for path in sorted(root_path.rglob("*"), key=lambda item: item.as_posix()):
        observed = os.lstat(path)
        if stat.S_ISLNK(observed.st_mode):
            raise BrokerProtocolError("tessdata tree contains a symlink")
        if stat.S_ISDIR(observed.st_mode):
            continue
        if not stat.S_ISREG(observed.st_mode):
            raise BrokerProtocolError("tessdata tree contains a non-file leaf")
        body, opened = _read_exact_file(path, 4 * 1024 * 1024 * 1024)
        aggregate_bytes += len(body)
        if aggregate_bytes > 16 * 1024 * 1024 * 1024 or len(records) >= 4_096:
            raise BrokerProtocolError("tessdata tree exceeds its identity bound")
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_uid,
            opened.st_nlink,
            opened.st_size,
        ) != (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_uid,
            observed.st_nlink,
            observed.st_size,
        ):
            raise BrokerProtocolError("tessdata entry changed during hashing")
        records.append(
            {
                "path": path.relative_to(root_path).as_posix(),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            }
        )
    root_after = os.lstat(root_path)
    if (
        root_before.st_dev,
        root_before.st_ino,
        root_before.st_mode,
        root_before.st_uid,
        root_before.st_mtime_ns,
        root_before.st_ctime_ns,
    ) != (
        root_after.st_dev,
        root_after.st_ino,
        root_after.st_mode,
        root_after.st_uid,
        root_after.st_mtime_ns,
        root_after.st_ctime_ns,
    ):
        raise BrokerProtocolError("tessdata root changed during hashing")
    encoded = json.dumps(
        tuple(records),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class BrokerLaunchConfig:
    def __init__(self, value: object) -> None:
        mapping = _strict_object(
            value,
            {
                "schema_id",
                "attempt_nonce",
                "scope_sha256",
                "controller",
                "launcher",
                "source_executable",
                "executable",
                "native_closure",
                "tessdata",
                "allowed_languages",
                "request_root",
                "ledger",
                "broker_profile_sha256",
                "child_wrapper_sha256",
                "broker_sandbox_probe_plan",
                "child_sandbox_probe_executor",
                "child_sandbox_probe_plan",
                "guard_python",
                "guard_python_path_custody",
                "guard_python_native_closure",
                "guard_python_module_tree_custody",
                "native_spawn_guard",
                "native_spawn_guard_source_sha256",
                "watchdog_protocol_sha256",
                "attempt_deadline_monotonic_ns",
                "limits",
            },
            "broker launch template",
        )
        if mapping["schema_id"] != BROKER_LAUNCH_SCHEMA:
            raise BrokerProtocolError("broker launch schema differs")
        self.attempt_nonce = _sha(mapping["attempt_nonce"], "attempt_nonce")
        self.scope_sha256 = _sha(mapping["scope_sha256"], "scope_sha256")
        controller = _strict_object(mapping["controller"], {"pid", "start_abstime"}, "controller")
        self.controller_pid = _positive_int(controller["pid"], "controller.pid")
        self.controller_start_abstime = _positive_int(
            controller["start_abstime"], "controller.start_abstime"
        )
        launcher = _strict_object(
            mapping["launcher"],
            {"pid", "start_abstime", "ppid", "pgid", "sid", "uid", "euid"},
            "launcher",
        )
        try:
            self.launcher = TrustedLauncherIdentity(**launcher)
        except TypeError as exc:
            raise BrokerProtocolError("launcher identity fields differ") from exc
        self.launcher_pid = self.launcher.pid
        self.launcher_start_abstime = self.launcher.start_abstime
        if (
            self.launcher_pid == self.controller_pid
            or self.launcher.ppid != self.controller_pid
        ):
            raise BrokerProtocolError(
                "broker launcher/controller topology differs"
            )
        self.source_executable = _executable_identity(mapping["source_executable"])
        self.executable = _executable_identity(mapping["executable"])
        if self.source_executable.sha256 != self.executable.sha256:
            raise BrokerProtocolError("staged Tesseract bytes differ from source")
        self.native_closure = validate_native_closure(mapping["native_closure"])
        self.native_closure_sha256 = self.native_closure["closure_sha256"]
        runtime_gate = self.native_closure["runtime_gate"]
        if runtime_gate is None:
            raise BrokerProtocolError(
                "broker launch lacks the native runtime constructor gate"
            )
        self.native_runtime_gate = runtime_gate
        self.native_runtime_gate_source = _executable_identity(
            {
                key: runtime_gate["source"][key]
                for key in (
                    "resolved_path",
                    "sha256",
                    "device",
                    "inode",
                    "mode",
                    "uid",
                    "nlink",
                    "size",
                )
            }
        )
        self.native_runtime_gate_library = _executable_identity(
            {
                key: runtime_gate["library"][key]
                for key in (
                    "resolved_path",
                    "sha256",
                    "device",
                    "inode",
                    "mode",
                    "uid",
                    "nlink",
                    "size",
                )
            }
        )
        if (
            runtime_gate["authority"] != NATIVE_RUNTIME_GATE_AUTHORITY
            or runtime_gate["initializer_order_limitation"]
            != NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION
            or runtime_gate["ack_authority"]
            != NATIVE_RUNTIME_GATE_ACK_AUTHORITY
            or runtime_gate["ack_bytes"] != NATIVE_RUNTIME_GATE_ACK_BYTES
            or runtime_gate["inherited_gate_fd"] != NATIVE_RUNTIME_GATE_FD
        ):
            raise BrokerProtocolError(
                "broker native runtime gate authority differs"
            )
        closure_roots = self.native_closure["roots"]
        if (
            closure_roots["source_executable"]
            != self.source_executable.resolved_path
            or closure_roots["staged_executable"]
            != self.executable.resolved_path
            or closure_roots["source_sha256"] != self.source_executable.sha256
            or closure_roots["staged_sha256"] != self.executable.sha256
            or self.native_closure["trust_model"]
            != NATIVE_CLOSURE_TRUST_MODEL
            or self.native_closure["containment_claim"]
            != "none-trusted-pinned-native-computation"
        ):
            raise BrokerProtocolError("native closure executable binding differs")
        tessdata = _strict_object(
            mapping["tessdata"], {"resolved_root", "tree_sha256"}, "tessdata"
        )
        self.tessdata_root = tessdata["resolved_root"]
        if (
            not isinstance(self.tessdata_root, str)
            or not os.path.isabs(self.tessdata_root)
            or os.path.realpath(self.tessdata_root) != self.tessdata_root
            or not stat.S_ISDIR(os.lstat(self.tessdata_root).st_mode)
        ):
            raise BrokerProtocolError("tessdata root differs")
        self.tessdata_sha256 = _sha(tessdata["tree_sha256"], "tessdata.tree_sha256")
        if _tree_content_identity(self.tessdata_root) != self.tessdata_sha256:
            raise BrokerProtocolError("tessdata tree identity differs")
        languages = mapping["allowed_languages"]
        if (
            not isinstance(languages, list)
            or not languages
            or languages != sorted(set(languages))
            or any(not isinstance(item, str) or not item or len(item) > 64 for item in languages)
        ):
            raise BrokerProtocolError("allowed Tesseract languages differ")
        self.languages = tuple(languages)
        request_root = _strict_object(
            mapping["request_root"], {"resolved_path", "device", "inode", "mode", "uid"}, "request root"
        )
        self.request_root = request_root["resolved_path"]
        root_stat = os.lstat(self.request_root)
        if (
            not isinstance(self.request_root, str)
            or not os.path.isabs(self.request_root)
            or os.path.realpath(self.request_root) != self.request_root
            or not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_IMODE(root_stat.st_mode) != 0o700
            or (root_stat.st_dev, root_stat.st_ino, root_stat.st_mode, root_stat.st_uid)
            != (request_root["device"], request_root["inode"], request_root["mode"], request_root["uid"])
        ):
            raise BrokerProtocolError("request root identity differs")
        self.request_root_fd = os.open(
            self.request_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened_root = os.fstat(self.request_root_fd)
        if (
            opened_root.st_dev,
            opened_root.st_ino,
            opened_root.st_mode,
            opened_root.st_uid,
        ) != (
            root_stat.st_dev,
            root_stat.st_ino,
            root_stat.st_mode,
            root_stat.st_uid,
        ):
            os.close(self.request_root_fd)
            raise BrokerProtocolError("request-root descriptor identity differs")
        ledger = _strict_object(mapping["ledger"], {"maximum_bytes"}, "ledger")
        if ledger["maximum_bytes"] != MAX_LEDGER_BYTES:
            raise BrokerProtocolError("ledger custody differs")
        self.broker_profile_sha256 = _sha(
            mapping["broker_profile_sha256"], "broker_profile_sha256"
        )
        self.child_wrapper_sha256 = _sha(
            mapping["child_wrapper_sha256"], "child_wrapper_sha256"
        )
        if self.child_wrapper_sha256 != child_wrapper_sha256():
            raise BrokerProtocolError("child wrapper bytes differ")
        self.guard_wrapper_source, _ = _read_exact_file(
            str(Path(__file__).with_name("tesseract_child_exec.py")),
            256 * 1024,
        )
        if (
            hashlib.sha256(self.guard_wrapper_source).hexdigest()
            != self.child_wrapper_sha256
        ):
            raise BrokerProtocolError("fresh child guard source bytes differ")
        broker_sandbox_plan = _strict_object(
            mapping["broker_sandbox_probe_plan"],
            {
                "schema_id",
                "attempt_id",
                "attempt_nonce_sha256",
                "scope_sha256",
                "role",
                "profile_sha256",
                "native_closure_sha256",
                "probe_executor_authority",
                "probe_executor_source_sha256",
                "probe_library_path",
                "probe_library_sha256",
                "held_directories",
                "operations",
                "plan_sha256",
            },
            "broker sandbox probe plan",
        )
        broker_sandbox_plan_sha256 = _sha(
            broker_sandbox_plan.pop("plan_sha256"),
            "broker sandbox probe plan_sha256",
        )
        if (
            broker_sandbox_plan["schema_id"]
            != "phase-latency-kernel-sandbox-role-plan-v1"
            or broker_sandbox_plan["role"] != "tesseract_broker"
            or broker_sandbox_plan["attempt_nonce_sha256"]
            != hashlib.sha256(self.attempt_nonce.encode("ascii")).hexdigest()
            or broker_sandbox_plan["scope_sha256"] != self.scope_sha256
            or broker_sandbox_plan["profile_sha256"]
            != self.broker_profile_sha256
            or broker_sandbox_plan["probe_executor_authority"]
            != "workspace-python-native-ctypes-seatbelt-probe-v1"
            or not isinstance(broker_sandbox_plan["operations"], list)
            or not 1 <= len(broker_sandbox_plan["operations"]) <= 128
            or not isinstance(broker_sandbox_plan["held_directories"], list)
            or len(broker_sandbox_plan["held_directories"]) != 9
            or broker_sandbox_plan_sha256
            != canonical_sha256(broker_sandbox_plan)
        ):
            raise BrokerProtocolError("broker sandbox probe plan differs")
        for name in (
            "native_closure_sha256",
            "probe_executor_source_sha256",
            "probe_library_sha256",
        ):
            _sha(broker_sandbox_plan[name], f"broker sandbox {name}")
        broker_sandbox_plan["plan_sha256"] = broker_sandbox_plan_sha256
        self.broker_sandbox_probe_plan = broker_sandbox_plan
        sandbox_executor = _strict_object(
            mapping["child_sandbox_probe_executor"],
            {"authority", "source_hex", "source_sha256"},
            "child sandbox probe executor",
        )
        if (
            sandbox_executor["authority"]
            != CHILD_SANDBOX_EXECUTOR_AUTHORITY
            or not isinstance(sandbox_executor["source_hex"], str)
            or len(sandbox_executor["source_hex"])
            > 2 * MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES
        ):
            raise BrokerProtocolError(
                "child sandbox probe executor authority differs"
            )
        try:
            self.child_sandbox_probe_executor_source = bytes.fromhex(
                sandbox_executor["source_hex"]
            )
        except ValueError as exc:
            raise BrokerProtocolError(
                "child sandbox probe executor source differs"
            ) from exc
        self.child_sandbox_probe_executor_source_sha256 = _sha(
            sandbox_executor["source_sha256"],
            "child sandbox probe executor source_sha256",
        )
        expected_executor_source, _ = _read_exact_file(
            str(Path(__file__).with_name("tesseract_child_sandbox_probe.py")),
            MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES,
        )
        if (
            not self.child_sandbox_probe_executor_source
            or hashlib.sha256(
                self.child_sandbox_probe_executor_source
            ).hexdigest()
            != self.child_sandbox_probe_executor_source_sha256
            or self.child_sandbox_probe_executor_source
            != expected_executor_source
        ):
            raise BrokerProtocolError(
                "child sandbox probe executor bytes differ"
            )
        self.child_sandbox_probe_executor = dict(sandbox_executor)
        self.child_sandbox_probe_plan = validate_child_sandbox_probe_plan(
            mapping["child_sandbox_probe_plan"]
        )
        sandbox_plan = self.child_sandbox_probe_plan
        if (
            sandbox_plan["attempt_nonce_sha256"]
            != hashlib.sha256(self.attempt_nonce.encode("ascii")).hexdigest()
            or sandbox_plan["scope_sha256"] != self.scope_sha256
            or sandbox_plan["profile_sha256"]
            != self.broker_profile_sha256
            or sandbox_plan["probe_executor_authority"]
            != CHILD_SANDBOX_EXECUTOR_AUTHORITY
            or sandbox_plan["probe_executor_source_sha256"]
            != self.child_sandbox_probe_executor_source_sha256
            or broker_sandbox_plan["native_closure_sha256"]
            != sandbox_plan["native_closure_sha256"]
            or broker_sandbox_plan["probe_library_path"]
            != sandbox_plan["probe_library_path"]
            or broker_sandbox_plan["probe_library_sha256"]
            != sandbox_plan["probe_library_sha256"]
            or broker_sandbox_plan["held_directories"]
            != sandbox_plan["held_directories"]
        ):
            raise BrokerProtocolError("child sandbox probe plan binding differs")
        self.child_sandbox_probe_report_reservation_bytes = (
            child_sandbox_probe_report_reservation_bytes(sandbox_plan)
        )
        probe_library_path = sandbox_plan["probe_library_path"]
        probe_library_body, probe_library_stat = _read_exact_file(
            probe_library_path,
            16 * 1024 * 1024,
        )
        if (
            not stat.S_ISREG(probe_library_stat.st_mode)
            or stat.S_IMODE(probe_library_stat.st_mode) != 0o500
            or probe_library_stat.st_uid != os.geteuid()
            or probe_library_stat.st_nlink != 1
            or hashlib.sha256(probe_library_body).hexdigest()
            != sandbox_plan["probe_library_sha256"]
        ):
            raise BrokerProtocolError(
                "child sandbox probe library custody differs"
            )
        self.child_sandbox_probe_library_identity = {
            "resolved_path": probe_library_path,
            "device": int(probe_library_stat.st_dev),
            "inode": int(probe_library_stat.st_ino),
            "mode": int(probe_library_stat.st_mode),
            "uid": int(probe_library_stat.st_uid),
            "nlink": int(probe_library_stat.st_nlink),
            "size": int(probe_library_stat.st_size),
            "sha256": sandbox_plan["probe_library_sha256"],
        }
        self._validate_child_sandbox_held_directories()
        self.guard_python = _executable_identity(mapping["guard_python"])
        if (
            self.guard_python.uid != 0
            or self.guard_python.nlink != 1
            or self.guard_python.mode
            & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
        ):
            raise BrokerProtocolError("guard Python executable custody differs")
        self.guard_python_path_custody = derive_guard_python_path_custody(
            self.guard_python.resolved_path
        )
        if mapping["guard_python_path_custody"] != self.guard_python_path_custody:
            raise BrokerProtocolError("guard Python path chain differs")
        self.guard_python_native_closure = validate_native_closure(
            mapping["guard_python_native_closure"]
        )
        self.guard_python_native_closure_sha256 = (
            self.guard_python_native_closure["closure_sha256"]
        )
        guard_roots = self.guard_python_native_closure["roots"]
        if (
            guard_roots["source_executable"]
            != self.guard_python.resolved_path
            or guard_roots["staged_executable"]
            != self.guard_python.resolved_path
            or guard_roots["source_sha256"] != self.guard_python.sha256
            or guard_roots["staged_sha256"] != self.guard_python.sha256
            or self.guard_python_native_closure["runtime_gate"] is not None
        ):
            raise BrokerProtocolError("guard Python native closure differs")
        module_tree = _strict_object(
            mapping["guard_python_module_tree_custody"],
            {
                "schema_id",
                "resolved_root",
                "entry_count",
                "aggregate_bytes",
                "root_owned_non_writable",
                "records_sha256",
                "record_sha256",
            },
            "guard Python module tree custody",
        )
        self.guard_python_module_tree_custody = (
            derive_guard_python_module_tree_custody(
                module_tree["resolved_root"]
            )
        )
        if module_tree != self.guard_python_module_tree_custody:
            raise BrokerProtocolError("guard Python module tree identity differs")
        self.native_spawn_guard = _executable_identity(
            mapping["native_spawn_guard"]
        )
        self.native_spawn_guard_source_sha256 = _sha(
            mapping["native_spawn_guard_source_sha256"],
            "native_spawn_guard_source_sha256",
        )
        self.watchdog_protocol_sha256 = _sha(
            mapping["watchdog_protocol_sha256"], "watchdog_protocol_sha256"
        )
        self.attempt_deadline_ns = _positive_int(
            mapping["attempt_deadline_monotonic_ns"], "attempt_deadline_monotonic_ns"
        )
        if self.attempt_deadline_ns <= time.monotonic_ns():
            raise BrokerProtocolError("attempt deadline already expired")
        limits = _strict_object(
            mapping["limits"],
            {"max_input_bytes", "max_stdout_bytes", "max_stderr_bytes", "max_jobs_per_phase"},
            "broker limits",
        )
        expected_limits = (
            MAX_RUN_INPUT_BYTES,
            MAX_RUN_STDOUT_BYTES,
            MAX_STDERR_BYTES,
            MAX_JOBS_PER_PHASE,
        )
        if tuple(limits[name] for name in (
            "max_input_bytes", "max_stdout_bytes", "max_stderr_bytes", "max_jobs_per_phase"
        )) != expected_limits:
            raise BrokerProtocolError("broker limits differ")
        self.mapping = mapping

    def _validate_child_sandbox_held_directories(self) -> None:
        for authority in self.child_sandbox_probe_plan["held_directories"]:
            descriptor = authority["descriptor"]
            before = os.fstat(descriptor)
            path = authority["resolved_path"]
            observed = os.lstat(path)
            after = os.fstat(descriptor)
            identity = (
                authority["device"],
                authority["inode"],
                authority["mode"],
                authority["uid"],
                authority["nlink"],
            )
            if (
                os.path.realpath(path) != path
                or hashlib.sha256(path.encode("utf-8")).hexdigest()
                != authority["path_sha256"]
                or fcntl.fcntl(descriptor, fcntl.F_GETFL)
                != authority["open_flags"]
                or tuple(
                    getattr(before, name)
                    for name in (
                        "st_dev",
                        "st_ino",
                        "st_mode",
                        "st_uid",
                        "st_nlink",
                    )
                )
                != identity
                or tuple(
                    getattr(observed, name)
                    for name in (
                        "st_dev",
                        "st_ino",
                        "st_mode",
                        "st_uid",
                        "st_nlink",
                    )
                )
                != identity
                or tuple(
                    getattr(after, name)
                    for name in (
                        "st_dev",
                        "st_ino",
                        "st_mode",
                        "st_uid",
                        "st_nlink",
                    )
                )
                != identity
            ):
                raise BrokerProtocolError(
                    "child sandbox held directory custody changed"
                )

    def validate_immutable_inputs(self) -> dict[str, Any]:
        if (
            _executable_identity(asdict(self.source_executable))
            != self.source_executable
            or _executable_identity(asdict(self.executable)) != self.executable
            or _executable_identity(asdict(self.native_spawn_guard))
            != self.native_spawn_guard
            or _executable_identity(asdict(self.native_runtime_gate_source))
            != self.native_runtime_gate_source
            or _executable_identity(asdict(self.native_runtime_gate_library))
            != self.native_runtime_gate_library
            or _executable_identity(asdict(self.guard_python))
            != self.guard_python
            or _tree_content_identity(self.tessdata_root)
            != self.tessdata_sha256
        ):
            raise BrokerProtocolError("broker immutable input identity changed")
        observed_closure = validate_native_closure(self.native_closure)
        if observed_closure["closure_sha256"] != self.native_closure_sha256:
            raise BrokerProtocolError("broker native closure identity changed")
        if (
            validate_native_closure(self.guard_python_native_closure)[
                "closure_sha256"
            ]
            != self.guard_python_native_closure_sha256
            or derive_guard_python_path_custody(
                self.guard_python.resolved_path
            )
            != self.guard_python_path_custody
            or derive_guard_python_module_tree_custody(
                self.guard_python_module_tree_custody["resolved_root"]
            )
            != self.guard_python_module_tree_custody
            or hashlib.sha256(
                _read_exact_file(
                    str(Path(__file__).with_name("tesseract_child_exec.py")),
                    256 * 1024,
                )[0]
            ).hexdigest()
            != self.child_wrapper_sha256
        ):
            raise BrokerProtocolError("guard Python custody changed")
        current_executor_source, _ = _read_exact_file(
            str(Path(__file__).with_name("tesseract_child_sandbox_probe.py")),
            MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES,
        )
        probe_library_body, probe_library_stat = _read_exact_file(
            self.child_sandbox_probe_library_identity["resolved_path"],
            16 * 1024 * 1024,
        )
        self._validate_child_sandbox_held_directories()
        if (
            current_executor_source
            != self.child_sandbox_probe_executor_source
            or hashlib.sha256(probe_library_body).hexdigest()
            != self.child_sandbox_probe_library_identity["sha256"]
            or (
                int(probe_library_stat.st_dev),
                int(probe_library_stat.st_ino),
                int(probe_library_stat.st_mode),
                int(probe_library_stat.st_uid),
                int(probe_library_stat.st_nlink),
                int(probe_library_stat.st_size),
            )
            != tuple(
                self.child_sandbox_probe_library_identity[name]
                for name in (
                    "device",
                    "inode",
                    "mode",
                    "uid",
                    "nlink",
                    "size",
                )
            )
        ):
            raise BrokerProtocolError(
                "child sandbox probe immutable input changed"
            )
        observed_at = time.monotonic_ns()
        return {
            "schema_id": "parser-tesseract-immutable-input-observation-v1",
            "native_closure_sha256": self.native_closure_sha256,
            "native_trust_model": NATIVE_CLOSURE_TRUST_MODEL,
            "native_containment_claim": "none-trusted-pinned-native-computation",
            "source_executable_sha256": self.source_executable.sha256,
            "staged_executable_sha256": self.executable.sha256,
            "native_spawn_guard_sha256": self.native_spawn_guard.sha256,
            "native_spawn_guard_source_sha256": (
                self.native_spawn_guard_source_sha256
            ),
            "native_runtime_gate_source_sha256": (
                self.native_runtime_gate_source.sha256
            ),
            "native_runtime_gate_library_sha256": (
                self.native_runtime_gate_library.sha256
            ),
            "native_runtime_gate_record_sha256": (
                self.native_runtime_gate["record_sha256"]
            ),
            "guard_python_sha256": self.guard_python.sha256,
            "guard_python_path_custody_sha256": (
                self.guard_python_path_custody["record_sha256"]
            ),
            "guard_python_native_closure_sha256": (
                self.guard_python_native_closure_sha256
            ),
            "guard_python_module_tree_sha256": (
                self.guard_python_module_tree_custody["record_sha256"]
            ),
            "guard_wrapper_source_sha256": self.child_wrapper_sha256,
            "guard_wrapper_delivery_basis": (
                "execve-python-c-embedded-source-v1"
            ),
            "tessdata_sha256": self.tessdata_sha256,
            "observed_at_monotonic_ns": observed_at,
        }


class DurableLedger:
    """External-watchdog-owned durable append log."""

    def __init__(self, channel: FramedChannel, config: BrokerLaunchConfig) -> None:
        self.channel = channel
        self.sequence = 0
        self.head_sha256 = _ZERO_SHA256
        self.size_bytes = 0
        self.reserved_child_count = 0
        self.record_blob_count = 0
        self.record_blob_size_bytes = 0
        self.record_blob_head_sha256 = _ZERO_SHA256
        self.child_record_blob_size_bytes = 0
        self.phase_record_blob_size_bytes = 0
        request = {
            "attempt_nonce_sha256": hashlib.sha256(
                config.attempt_nonce.encode("ascii")
            ).hexdigest(),
            "scope_sha256": config.scope_sha256,
            "maximum_bytes": MAX_LEDGER_BYTES,
            "maximum_record_blob_bytes": MAX_BROKER_AUDIT_BLOB_BYTES,
            "compact_commitment_bytes": BROKER_AUDIT_COMMITMENT_BYTES,
            "watchdog_protocol_sha256": config.watchdog_protocol_sha256,
        }
        request["record_sha256"] = canonical_sha256(request)
        self.channel.send("broker_audit_open", request)
        _, ack, body = self.channel.receive(expected_kind="broker_audit_open_ack")
        if body or not isinstance(ack, dict) or set(ack) != {
            "record_sha256",
            "ledger",
            "record_blob_root",
            "watchdog_record_sha256",
        }:
            raise BrokerProtocolError("watchdog audit-open ACK fields differ")
        ack_sha = ack.pop("watchdog_record_sha256")
        if ack["record_sha256"] != request["record_sha256"] or ack_sha != canonical_sha256(ack):
            raise BrokerProtocolError("watchdog audit-open ACK binding differs")
        ledger = _strict_object(
            ack["ledger"],
            {
                "resolved_path", "device", "inode", "mode", "uid", "nlink",
                "size_bytes", "head_sha256",
            },
            "watchdog ledger identity",
        )
        if (
            not isinstance(ledger["resolved_path"], str)
            or not os.path.isabs(ledger["resolved_path"])
            or ledger["nlink"] != 1
            or stat.S_IMODE(ledger["mode"]) != 0o600
            or ledger["size_bytes"] != 0
            or ledger["head_sha256"] != _ZERO_SHA256
        ):
            raise BrokerProtocolError("watchdog ledger initial identity differs")
        self.identity = ledger
        blob_root = _strict_object(
            ack["record_blob_root"],
            {
                "schema_id",
                "resolved_path",
                "device",
                "inode",
                "mode",
                "uid",
                "nlink",
                "entry_count",
                "aggregate_bytes",
                "head_sha256",
                "record_sha256",
            },
            "watchdog record-blob root identity",
        )
        blob_root_sha = blob_root.pop("record_sha256")
        if (
            blob_root["schema_id"]
            != "parser-tesseract-broker-audit-record-blob-root-v1"
            or not isinstance(blob_root["resolved_path"], str)
            or not os.path.isabs(blob_root["resolved_path"])
            or not stat.S_ISDIR(blob_root["mode"])
            or stat.S_IMODE(blob_root["mode"]) != 0o700
            or blob_root["uid"] != os.geteuid()
            or blob_root["nlink"] < 2
            or blob_root["entry_count"] != 0
            or blob_root["aggregate_bytes"] != 0
            or blob_root["head_sha256"] != _ZERO_SHA256
            or blob_root_sha != canonical_sha256(blob_root)
        ):
            raise BrokerProtocolError(
                "watchdog record-blob root custody differs"
            )
        blob_root["record_sha256"] = blob_root_sha
        self.record_blob_root = blob_root

    def reserve_child(self, spawn_sequence: int) -> None:
        """Reserve every durable child row before the native fork."""

        next_reserved_child_count = self.reserved_child_count + 1
        if (
            isinstance(spawn_sequence, bool)
            or not isinstance(spawn_sequence, int)
            or spawn_sequence <= 0
            or spawn_sequence > MAX_JOBS_PER_PHASE
            or next_reserved_child_count > MAX_JOBS_PER_PHASE
            or next_reserved_child_count * MAX_BROKER_AUDIT_CHILD_BLOB_BYTES
            + MAX_BROKER_AUDIT_PHASE_BLOB_BYTES
            > MAX_BROKER_AUDIT_BLOB_BYTES
            or (
                next_reserved_child_count * 10
                + MAX_BROKER_AUDIT_NON_CHILD_ROWS
            )
            * BROKER_AUDIT_COMMITMENT_BYTES
            > MAX_LEDGER_BYTES
        ):
            raise BrokerProtocolError(
                "broker audit child reservation exceeds its bound"
            )
        self.reserved_child_count = next_reserved_child_count

    def append(self, kind: str, record: Mapping[str, Any]) -> str:
        next_sequence = self.sequence + 1
        row = broker_audit_row_mapping(
            row_sequence=next_sequence,
            previous_row_sha256=self.head_sha256,
            kind=kind,
            record=record,
        )
        row_sha = row["row_sha256"]
        next_child_blob_bytes = self.child_record_blob_size_bytes
        next_phase_blob_bytes = self.phase_record_blob_size_bytes
        if kind in BROKER_AUDIT_CHILD_KIND_MAX_BYTES:
            next_child_blob_bytes += row["record_bytes"]
        else:
            next_phase_blob_bytes += row["record_bytes"]
        if (
            self.size_bytes + BROKER_AUDIT_COMMITMENT_BYTES > MAX_LEDGER_BYTES
            or next_child_blob_bytes
            > self.reserved_child_count * MAX_BROKER_AUDIT_CHILD_BLOB_BYTES
            or next_phase_blob_bytes > MAX_BROKER_AUDIT_PHASE_BLOB_BYTES
            or next_child_blob_bytes + next_phase_blob_bytes
            > MAX_BROKER_AUDIT_BLOB_BYTES
        ):
            raise BrokerProtocolError("broker ledger exceeds its byte bound")
        self.channel.send("broker_audit_append", row)
        _, ack, body = self.channel.receive(expected_kind="broker_audit_append_ack")
        if body or not isinstance(ack, dict) or set(ack) != {
            "row_sequence", "row_sha256", "head_sha256", "size_bytes",
            "record_blob", "record_blob_count", "record_blob_size_bytes",
            "record_blob_head_sha256",
            "watchdog_record_sha256",
        }:
            raise BrokerProtocolError("watchdog audit-append ACK fields differ")
        ack_sha = ack.pop("watchdog_record_sha256")
        record_blob = _strict_object(
            ack["record_blob"],
            {
                "schema_id",
                "row_sequence",
                "kind",
                "record_bytes",
                "record_sha256",
                "resolved_path",
                "device",
                "inode",
                "mode",
                "uid",
                "nlink",
                "previous_blob_record_sha256",
                "blob_record_sha256",
            },
            "watchdog audit record blob",
        )
        blob_record_sha = record_blob.pop("blob_record_sha256")
        blob_path = Path(record_blob["resolved_path"])
        if (
            ack["row_sequence"] != next_sequence
            or ack["row_sha256"] != row_sha
            or ack["head_sha256"] != row_sha
            or ack["size_bytes"]
            != self.size_bytes + BROKER_AUDIT_COMMITMENT_BYTES
            or ack["size_bytes"] > MAX_LEDGER_BYTES
            or record_blob["schema_id"]
            != "parser-tesseract-broker-audit-record-blob-v1"
            or record_blob["row_sequence"] != next_sequence
            or record_blob["kind"] != kind
            or record_blob["record_bytes"] != row["record_bytes"]
            or record_blob["record_sha256"] != row["record_sha256"]
            or not blob_path.is_absolute()
            or blob_path.parent
            != Path(self.record_blob_root["resolved_path"])
            or not isinstance(record_blob["device"], int)
            or not isinstance(record_blob["inode"], int)
            or record_blob["inode"] <= 0
            or not stat.S_ISREG(record_blob["mode"])
            or stat.S_IMODE(record_blob["mode"]) != 0o600
            or record_blob["uid"] != os.geteuid()
            or record_blob["nlink"] != 1
            or record_blob["previous_blob_record_sha256"]
            != self.record_blob_head_sha256
            or blob_record_sha != canonical_sha256(record_blob)
            or ack["record_blob_count"] != self.record_blob_count + 1
            or ack["record_blob_size_bytes"]
            != self.record_blob_size_bytes + row["record_bytes"]
            or ack["record_blob_size_bytes"] > MAX_BROKER_AUDIT_BLOB_BYTES
            or ack["record_blob_head_sha256"] != blob_record_sha
            or ack_sha != canonical_sha256(ack)
        ):
            raise BrokerProtocolError("watchdog audit-append ACK binding differs")
        self.sequence = next_sequence
        self.size_bytes = ack["size_bytes"]
        self.head_sha256 = row_sha
        self.record_blob_count = ack["record_blob_count"]
        self.record_blob_size_bytes = ack["record_blob_size_bytes"]
        self.record_blob_head_sha256 = blob_record_sha
        self.child_record_blob_size_bytes = next_child_blob_bytes
        self.phase_record_blob_size_bytes = next_phase_blob_bytes
        return row_sha

    def ready_identity(self) -> dict[str, Any]:
        return {
            **self.identity,
            "size_bytes": self.size_bytes,
            "head_sha256": self.head_sha256,
        }

    def close(self, broker_identity: KernelProcessIdentity) -> None:
        thread_ids = native_thread_inventory(broker_identity.pid)
        thread_observed_at = time.monotonic_ns()
        thread_count = len(thread_ids)
        thread_inventory_sha256 = canonical_sha256(
            {
                "schema_id": "parser-tesseract-broker-thread-inventory-v1",
                "broker_pid": broker_identity.pid,
                "broker_start_abstime": broker_identity.start_abstime,
                "thread_ids": list(thread_ids),
            }
        )
        if thread_count != 1:
            raise BrokerProtocolError(
                "broker terminal thread inventory differs"
            )
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
        applied_at = time.monotonic_ns()
        if (soft, hard) != (0, 0):
            raise BrokerProtocolError("broker terminal fork denial differs")
        request = {
            "row_sequence": self.sequence,
            "head_sha256": self.head_sha256,
            "size_bytes": self.size_bytes,
            "record_blob_count": self.record_blob_count,
            "record_blob_size_bytes": self.record_blob_size_bytes,
            "record_blob_head_sha256": self.record_blob_head_sha256,
            "broker": asdict(broker_identity),
            "broker_thread_count": thread_count,
            "broker_thread_inventory_sha256": thread_inventory_sha256,
            "broker_thread_observed_at_monotonic_ns": thread_observed_at,
            "rlimit_nproc_soft": soft,
            "rlimit_nproc_hard": hard,
            "terminal_fork_denial_applied_at_monotonic_ns": applied_at,
            "terminal_no_fork": True,
        }
        request["record_sha256"] = canonical_sha256(request)
        self.channel.send("broker_audit_close", request)
        _, ack, body = self.channel.receive(expected_kind="broker_audit_close_ack")
        if not isinstance(ack, dict) or set(ack) != {
            "record_sha256", "terminal_head_sha256", "terminal_size_bytes",
            "terminal_record_blob_count", "terminal_record_blob_size_bytes",
            "terminal_record_blob_head_sha256",
            "broker", "rlimit_nproc_soft", "rlimit_nproc_hard",
            "broker_thread_count", "broker_thread_inventory_sha256",
            "broker_thread_observed_at_monotonic_ns",
            "terminal_fork_denial_applied_at_monotonic_ns",
            "terminal_no_fork", "watchdog_record_sha256",
        }:
            raise BrokerProtocolError("watchdog audit-close ACK fields differ")
        ack_digest = ack.pop("watchdog_record_sha256")
        if (
            body
            or ack["record_sha256"] != request["record_sha256"]
            or ack["terminal_head_sha256"] != self.head_sha256
            or ack["terminal_size_bytes"] != self.size_bytes
            or ack["terminal_record_blob_count"] != self.record_blob_count
            or ack["terminal_record_blob_size_bytes"]
            != self.record_blob_size_bytes
            or ack["terminal_record_blob_head_sha256"]
            != self.record_blob_head_sha256
            or ack["broker"] != asdict(broker_identity)
            or ack["broker_thread_count"] != 1
            or ack["broker_thread_inventory_sha256"]
            != thread_inventory_sha256
            or ack["broker_thread_observed_at_monotonic_ns"]
            != thread_observed_at
            or (ack["rlimit_nproc_soft"], ack["rlimit_nproc_hard"])
            != (0, 0)
            or ack["terminal_fork_denial_applied_at_monotonic_ns"]
            != applied_at
            or ack["terminal_no_fork"] is not True
            or ack_digest != canonical_sha256(ack)
        ):
            raise BrokerProtocolError("watchdog audit-close ACK differs")


def _write_ready(fd: int, record: Mapping[str, Any]) -> None:
    encoded = canonical_json_bytes(record) + b"\n"
    if len(encoded) > MAX_READY_BYTES:
        raise BrokerProtocolError("broker READY exceeds its bound")
    view = memoryview(encoded)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise BrokerProtocolError("broker READY write failed")
        view = view[written:]


def validate_broker_ready_record(
    mapping: object,
    *,
    config_sha256: str,
    expected_pid: int,
    expected_start_abstime: int,
    expected_launcher: Mapping[str, Any],
) -> dict[str, Any]:
    record = _strict_object(
        mapping,
        {
            "schema_id", "attempt_nonce_sha256", "scope_sha256", "config_sha256",
            "controller", "launcher", "broker", "capability", "profile_sha256",
            "executable_sha256", "tessdata_sha256", "native_closure_sha256",
            "native_trust_model", "native_containment_claim",
            "native_spawn_guard_sha256", "native_spawn_guard_source_sha256",
            "native_runtime_gate_source_sha256",
            "native_runtime_gate_library_sha256",
            "native_runtime_gate_record_sha256",
            "watchdog_protocol_sha256", "ledger",
            "pre_release_thread_inventory",
            "pre_release_file_descriptor_inventory",
            "retired_descriptor_fds",
            "ready_at_monotonic_ns", "ready_sha256",
        },
        "broker READY",
    )
    if record["schema_id"] != BROKER_READY_SCHEMA or record["config_sha256"] != config_sha256:
        raise BrokerProtocolError("broker READY config differs")
    _sha(record["native_closure_sha256"], "native_closure_sha256")
    _sha(
        record["native_spawn_guard_sha256"],
        "native_spawn_guard_sha256",
    )
    _sha(
        record["native_spawn_guard_source_sha256"],
        "native_spawn_guard_source_sha256",
    )
    _sha(
        record["native_runtime_gate_source_sha256"],
        "native_runtime_gate_source_sha256",
    )
    _sha(
        record["native_runtime_gate_library_sha256"],
        "native_runtime_gate_library_sha256",
    )
    _sha(
        record["native_runtime_gate_record_sha256"],
        "native_runtime_gate_record_sha256",
    )
    if (
        record["native_trust_model"] != NATIVE_CLOSURE_TRUST_MODEL
        or record["native_containment_claim"]
        != "none-trusted-pinned-native-computation"
    ):
        raise BrokerProtocolError("broker READY native trust boundary differs")
    ready_sha = _sha(record.pop("ready_sha256"), "ready_sha256")
    if ready_sha != canonical_sha256(record):
        raise BrokerProtocolError("broker READY digest differs")
    broker = _strict_object(
        record["broker"], {"pid", "start_abstime", "ppid", "pgid", "sid", "uid", "euid"}, "broker identity"
    )
    controller = _strict_object(
        record["controller"], {"pid", "start_abstime"}, "controller identity"
    )
    controller_pid = _positive_int(controller["pid"], "controller.pid")
    _positive_int(controller["start_abstime"], "controller.start_abstime")
    launcher_mapping = _strict_object(
        record["launcher"],
        {"pid", "start_abstime", "ppid", "pgid", "sid", "uid", "euid"},
        "launcher identity",
    )
    try:
        launcher = TrustedLauncherIdentity(**launcher_mapping)
    except TypeError as exc:
        raise BrokerProtocolError("broker READY launcher fields differ") from exc
    expected_launcher_mapping = _strict_object(
        expected_launcher,
        {"pid", "start_abstime", "ppid", "pgid", "sid", "uid", "euid"},
        "expected launcher identity",
    )
    try:
        expected_launcher_identity = TrustedLauncherIdentity(
            **expected_launcher_mapping
        )
    except TypeError as exc:
        raise BrokerProtocolError("expected launcher fields differ") from exc
    if (
        launcher != expected_launcher_identity
        or launcher.ppid != controller_pid
        or broker["pid"] != expected_pid
        or broker["start_abstime"] != expected_start_abstime
        or broker["ppid"] != launcher.pid
        or broker["pgid"] != expected_pid
        or broker["sid"] != expected_pid
    ):
        raise BrokerProtocolError("broker READY identity differs")
    broker_kernel_identity = KernelProcessIdentity(
        pid=broker["pid"],
        start_abstime=broker["start_abstime"],
        ppid=broker["ppid"],
        pgid=broker["pgid"],
        sid=broker["sid"],
    )
    thread_inventory = native_thread_inventory_from_mapping(
        record["pre_release_thread_inventory"]
    )
    descriptor_inventory = native_file_descriptor_inventory_from_mapping(
        record["pre_release_file_descriptor_inventory"]
    )
    retired_fds = record["retired_descriptor_fds"]
    if (
        thread_inventory.process != broker_kernel_identity
        or thread_inventory.thread_count != 1
        or descriptor_inventory.process != broker_kernel_identity
        or type(retired_fds) is not list
        or len(retired_fds) != 2
        or tuple(sorted(set(retired_fds))) != tuple(retired_fds)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 3
            for value in retired_fds
        )
        or not set(retired_fds).issubset(
            {item.fd for item in descriptor_inventory.descriptors}
        )
    ):
        raise BrokerProtocolError("broker READY kernel inventory differs")
    record["ready_sha256"] = ready_sha
    return record


class _BoundedCaptureStream:
    __slots__ = (
        "retained",
        "digest",
        "maximum_retained_bytes",
        "observed_bytes",
        "disposition",
    )

    def __init__(self, *, maximum_retained_bytes: int, disposition: str) -> None:
        if disposition not in {"captured", "discarded"}:
            raise BrokerProtocolError("capture stream disposition differs")
        self.retained = bytearray()
        self.digest = hashlib.sha256()
        self.maximum_retained_bytes = maximum_retained_bytes
        self.observed_bytes = 0
        self.disposition = disposition

    def consume(self, chunk: bytes) -> bool:
        self.digest.update(chunk)
        self.observed_bytes += len(chunk)
        if self.disposition == "discarded":
            return False
        if len(self.retained) + len(chunk) > self.maximum_retained_bytes:
            allowed = max(
                0, self.maximum_retained_bytes - len(self.retained)
            )
            self.retained.extend(chunk[:allowed])
            return True
        self.retained.extend(chunk)
        return False


class TesseractBroker:
    def __init__(
        self,
        sock: socket.socket,
        watchdog_channel: FramedChannel,
        config: BrokerLaunchConfig,
        ledger: DurableLedger,
    ) -> None:
        self.channel = FramedChannel(sock)
        self.channel.set_absolute_deadline_ns(config.attempt_deadline_ns)
        self.watchdog_channel = watchdog_channel
        self.config = config
        self.ledger = ledger
        self.identity = kernel_process_identity(os.getpid())
        self.worker_identity: KernelProcessIdentity | None = None
        self.pre_release_ready_sha256: str | None = None
        self.pre_release_thread_inventory: Any | None = None
        self.pre_release_file_descriptor_inventory: Any | None = None
        self.retired_descriptor_fds: tuple[int, int] | None = None
        self.active: dict[str, Any] | None = None
        self.births: list[BrokerChildBirth] = []
        self.tombstones: list[BrokerChildWait4Tombstone] = []
        self.completed_spawns = 0
        self.previous_receipt_sha256 = _ZERO_SHA256
        self.last_epoch = 0
        self.last_request_sequence = 0
        self.pending_receipt: BrokerRequestReceipt | None = None
        self.thread_transfers: list[BrokerThreadTransfer] = []
        self.child_sandbox_probe_report: BrokerChildSandboxProbeReport | None = None
        self.child_sandbox_probe_report_ledger_row_sha256: str | None = None
        self._child_line_buffers: dict[int, bytearray] = {}
        self._closed = False
        self._lifecycle_state = "awaiting_startup"
        self._native_spawn_library = ctypes.CDLL(
            self.config.native_spawn_guard.resolved_path,
            use_errno=True,
        )
        self._native_fork_child_denied = (
            self._native_spawn_library.parser_broker_raw_fork_exec_child_denied
        )
        self._native_fork_child_denied.argtypes = (
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_size_t,
        )
        self._native_fork_child_denied.restype = ctypes.c_int64

    def _spawn_child_with_native_denial(
        self,
        pre_python_release_fd: int,
        absolute_deadline_ns: int,
        *,
        child_state_ack_fd: int | None = None,
        guard_exec_error_fd: int | None = None,
        guard_argv: Sequence[str] = (),
        guard_environment: Mapping[str, str] | None = None,
        inherited_guard_fds: Sequence[int] = (),
    ) -> tuple[int, int, str, int, int]:
        """Fork once and wait for native proof of NPROC=0 before custody.

        The fixed binary acknowledgement is written by the raw-fork child
        before it can return to Python.  The parent cannot observe or ledger a
        provisional PID until that record has been read and independently
        reconstructed, so parent-first scheduling cannot invert the custody
        chronology.
        """

        child_error = ctypes.c_int(0)
        applied_monotonic_ns = ctypes.c_uint64(0)
        ack_read, ack_write = _pipe_cloexec()
        native_exec_handoff = child_state_ack_fd is not None
        if native_exec_handoff != (guard_exec_error_fd is not None):
            raise BrokerProtocolError("native child guard handoff differs")
        if native_exec_handoff and (
            not guard_argv
            or guard_environment is None
            or any(not isinstance(item, str) or not item for item in guard_argv)
            or any(
                not isinstance(key, str)
                or not key
                or "=" in key
                or "\x00" in key
                or not isinstance(value, str)
                or "\x00" in value
                for key, value in guard_environment.items()
            )
        ):
            raise BrokerProtocolError("native child guard exec vector differs")
        encoded_argv = tuple(os.fsencode(item) for item in guard_argv)
        encoded_environment = tuple(
            os.fsencode(f"{key}={guard_environment[key]}")
            for key in sorted(guard_environment or {})
        )
        argv_array = (ctypes.c_char_p * (len(encoded_argv) + 1))(
            *encoded_argv,
            None,
        )
        environment_array = (
            ctypes.c_char_p * (len(encoded_environment) + 1)
        )(
            *encoded_environment,
            None,
        )
        inherited_fd_array = (ctypes.c_int * len(inherited_guard_fds))(
            *inherited_guard_fds
        )
        pid = -1
        ctypes.set_errno(0)
        try:
            for descriptor in inherited_guard_fds:
                os.set_inheritable(descriptor, True)
            if any(
                not os.get_inheritable(descriptor)
                for descriptor in inherited_guard_fds
            ):
                raise BrokerProtocolError(
                    "native child guard descriptor was not inheritable"
                )
            if native_exec_handoff:
                assert child_state_ack_fd is not None
                assert guard_exec_error_fd is not None
                pid = int(
                    self._native_fork_child_denied(
                        ctypes.byref(child_error),
                        ctypes.byref(applied_monotonic_ns),
                        pre_python_release_fd,
                        ack_write,
                        child_state_ack_fd,
                        guard_exec_error_fd,
                        encoded_argv[0],
                        argv_array,
                        environment_array,
                        inherited_fd_array,
                        len(inherited_guard_fds),
                    )
                )
            else:
                pid = int(
                    self._native_fork_child_denied(
                        ctypes.byref(child_error),
                        ctypes.byref(applied_monotonic_ns),
                        pre_python_release_fd,
                        ack_write,
                    )
                )
            if pid < 0:
                error_number = ctypes.get_errno() or errno.EIO
                raise OSError(error_number, "native broker fork failed")
            if pid == 0:
                if not native_exec_handoff and (
                    child_error.value == 0
                    and applied_monotonic_ns.value > 0
                    and resource.getrlimit(resource.RLIMIT_NPROC) == (0, 0)
                ):
                    return (
                        0,
                        int(applied_monotonic_ns.value),
                        "",
                        0,
                        0,
                    )
                # A production raw child never returns through libffi/Python.
                os._exit(125)

            parent_returned_ns = time.monotonic_ns()
            for descriptor in inherited_guard_fds:
                os.set_inheritable(descriptor, False)
            if native_exec_handoff:
                assert child_state_ack_fd is not None
                assert guard_exec_error_fd is not None
                os.close(child_state_ack_fd)
                child_state_ack_fd = -1
                os.close(guard_exec_error_fd)
                guard_exec_error_fd = -1
            os.close(ack_write)
            ack_write = -1
            selector = selectors.DefaultSelector()
            selector.register(ack_read, selectors.EVENT_READ)
            body = bytearray()
            try:
                while len(body) < _NATIVE_CHILD_LIMIT_ACK_BYTES:
                    remaining_ns = absolute_deadline_ns - time.monotonic_ns()
                    if remaining_ns <= 0:
                        raise TimeoutError(
                            "native child limit acknowledgement timed out"
                        )
                    if not selector.select(remaining_ns / 1_000_000_000):
                        raise TimeoutError(
                            "native child limit acknowledgement timed out"
                        )
                    chunk = os.read(
                        ack_read,
                        _NATIVE_CHILD_LIMIT_ACK_BYTES - len(body),
                    )
                    if not chunk:
                        raise BrokerProtocolError(
                            "native child limit acknowledgement was truncated"
                        )
                    body.extend(chunk)
                remaining_ns = absolute_deadline_ns - time.monotonic_ns()
                if remaining_ns <= 0 or not selector.select(
                    remaining_ns / 1_000_000_000
                ):
                    raise TimeoutError(
                        "native child limit acknowledgement EOF timed out"
                    )
                if os.read(ack_read, 1):
                    raise BrokerProtocolError(
                        "native child limit acknowledgement has trailing bytes"
                    )
            finally:
                selector.close()
            raw = bytes(body)
            if raw[:8] != _NATIVE_CHILD_LIMIT_ACK_MAGIC:
                raise BrokerProtocolError(
                    "native child limit acknowledgement magic differs"
                )
            values = tuple(
                int.from_bytes(raw[offset : offset + 8], "big")
                for offset in (8, 16, 24, 32)
            )
            ack_pid, applied_ns, soft_limit, hard_limit = values
            if (
                ack_pid != pid
                or applied_ns <= 0
                or (soft_limit, hard_limit) != (0, 0)
                or hashlib.sha256(raw).hexdigest()
                != native_child_limit_ack_sha256(
                    pid=pid,
                    applied_monotonic_ns=applied_ns,
                )
            ):
                raise BrokerProtocolError(
                    "native child limit acknowledgement fields differ"
                )
            acknowledged_ns = time.monotonic_ns()
            return (
                pid,
                applied_ns,
                hashlib.sha256(raw).hexdigest(),
                parent_returned_ns,
                acknowledged_ns,
            )
        except BaseException:
            if pid == 0:
                os._exit(125)
            if pid > 0:
                self._reap_unregistered_native_child(
                    pid,
                    absolute_deadline_ns,
                )
            raise
        finally:
            for descriptor in (
                ack_read,
                ack_write,
                child_state_ack_fd if child_state_ack_fd is not None else -1,
                guard_exec_error_fd if guard_exec_error_fd is not None else -1,
            ):
                if descriptor >= 0:
                    with contextlib.suppress(OSError):
                        os.close(descriptor)
            if pid != 0:
                for descriptor in inherited_guard_fds:
                    with contextlib.suppress(OSError):
                        os.set_inheritable(descriptor, False)

    @staticmethod
    def _reap_unregistered_native_child(pid: int, deadline_ns: int) -> None:
        """Kill and exact-wait4 a child that failed before watcher custody."""

        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        cleanup_deadline = min(
            deadline_ns,
            time.monotonic_ns() + 2_000_000_000,
        )
        while time.monotonic_ns() < cleanup_deadline:
            try:
                waited = native_wait4_exact(
                    pid,
                    absolute_deadline_ns=cleanup_deadline,
                )
            except ChildProcessError:
                return
            if waited is not None:
                return
            time.sleep(0.001)
        raise BrokerProtocolError(
            "unregistered native child did not reach exact wait4"
        )

    def _sole_thread_observation(self) -> tuple[int, str, int]:
        thread_ids = native_thread_inventory(self.identity.pid)
        observed_at = time.monotonic_ns()
        count = len(thread_ids)
        digest = canonical_sha256(
            {
                "schema_id": "parser-tesseract-broker-thread-inventory-v1",
                "broker_pid": self.identity.pid,
                "broker_start_abstime": self.identity.start_abstime,
                "thread_ids": list(thread_ids),
            }
        )
        if count != 1:
            raise BrokerProtocolError(
                "spawn-authorized broker is not single-threaded"
            )
        return count, digest, observed_at

    def _socket_pending_bytes(self) -> int:
        pending = array.array("i", [0])
        fcntl.ioctl(self.channel.fileno, termios.FIONREAD, pending, True)
        return int(pending[0])

    def _scratch_inventory(self) -> BrokerScratchInventory:
        started = time.monotonic_ns()
        before = os.fstat(self.config.request_root_fd)
        try:
            entries = os.listdir(self.config.request_root_fd)
        except OSError as exc:
            raise BrokerProtocolError("request-root scan failed") from exc
        completed = time.monotonic_ns()
        after = os.fstat(self.config.request_root_fd)
        if (
            entries
            or (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_nlink,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_nlink,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
        ):
            raise BrokerProtocolError("request-root scan is not empty/stable")
        mapping: dict[str, Any] = {
            "schema_id": "parser-broker-scratch-inventory-v1",
            "root_device": before.st_dev,
            "root_inode": before.st_ino,
            "root_mode": stat.S_IMODE(before.st_mode),
            "root_uid": before.st_uid,
            "entry_count": 0,
            "aggregate_bytes": 0,
            "empty": True,
            "scan_started_monotonic_ns": started,
            "scan_completed_monotonic_ns": completed,
            "scan_sha256": canonical_sha256(
                {
                    "schema_id": "parser-broker-scratch-empty-scan-v1",
                    "root_device": before.st_dev,
                    "root_inode": before.st_ino,
                    "entries": [],
                }
            ),
        }
        mapping["record_sha256"] = canonical_sha256(mapping)
        return BrokerScratchInventory(**mapping)

    def _quiescence(self, phase: str) -> BrokerQuiescenceReceipt:
        if self.active is None or self.worker_identity is None:
            raise BrokerProtocolError("quiescence lacks an active phase")
        native_wait4_quiescence(absolute_deadline_ns=self.active["phase_deadline_ns"])
        broker_group = group_inventory(self.identity.pgid)
        worker_group = group_inventory(self.worker_identity.pgid)
        descendants = recursive_descendants(self.identity.pid)
        (
            broker_thread_count,
            broker_thread_inventory_sha256,
            broker_thread_observed_at_monotonic_ns,
        ) = self._sole_thread_observation()
        scratch_inventory = self._scratch_inventory()
        launched = tuple(item.spawn_sequence for item in self.births) if phase != "begin" else ()
        reaped = tuple(item.spawn_sequence for item in self.tombstones) if phase != "begin" else ()
        mapping: dict[str, Any] = {
            "request_id": self.active["request_id"],
            "request_epoch": self.active["request_epoch"],
            "request_sequence": self.active["request_sequence"],
            "phase": phase,
            "worker_identity": asdict(self.worker_identity),
            "active_job_count": 0,
            "launched_spawn_sequences": launched,
            "reaped_spawn_sequences": reaped,
            "wait4_echild": True,
            "broker_identity": asdict(self.identity),
            "broker_group_members": [asdict(item) for item in broker_group],
            "worker_group_members": [asdict(item) for item in worker_group],
            "recursive_descendants": [asdict(item) for item in descendants],
            "protocol_pending_bytes": self._socket_pending_bytes(),
            "ledger_head_sha256": (
                self.previous_receipt_sha256
                if phase == "begin"
                else (
                    self.tombstones[-1].record_sha256
                    if self.tombstones
                    else self.previous_receipt_sha256
                )
            ),
            "completed_spawn_count": (
                self.completed_spawns - len(self.tombstones)
                if phase == "begin"
                else self.completed_spawns
            ),
            "process_group_scan_complete": True,
            "admission_lock_held": True,
            "broker_armed_and_blocked": True,
            "worker_fork_denial_active": True,
            "broker_thread_count": broker_thread_count,
            "broker_thread_inventory_sha256": (
                broker_thread_inventory_sha256
            ),
            "broker_thread_observed_at_monotonic_ns": (
                broker_thread_observed_at_monotonic_ns
            ),
            "request_root_inventory": asdict(scratch_inventory),
            "observed_at_monotonic_ns": time.monotonic_ns(),
        }
        mapping["observation_sha256"] = canonical_sha256(mapping)
        receipt = BrokerQuiescenceReceipt(
            **{
                **mapping,
                "worker_identity": self.worker_identity,
                "broker_identity": self.identity,
                "broker_group_members": broker_group,
                "worker_group_members": worker_group,
                "recursive_descendants": descendants,
                "request_root_inventory": scratch_inventory,
            }
        )
        receipt.assert_complete(self.identity.pid)
        self.ledger.append("quiescence", dataclass_mapping(receipt))
        return receipt

    def _validate_phase_message(self, payload: object) -> dict[str, Any]:
        if self.active is None:
            raise BrokerProtocolError("broker has no active phase")
        mapping = _strict_object(
            payload,
            {
                "request_id", "request_epoch", "request_sequence",
                "worker_python_thread_id", "worker_thread_id",
                "capability_sha256", "arm_capability_sha256", "binding_sha256",
            },
            "phase binding",
        )
        for name in mapping:
            if mapping[name] != self.active[name]:
                raise BrokerProtocolError("broker phase binding differs")
        return mapping

    def _handle_hello(self, payload: object, body: bytes) -> None:
        if body:
            raise BrokerProtocolError("broker hello body is forbidden")
        mapping = _strict_object(
            payload,
            {
                "attempt_nonce_sha256", "scope_sha256", "worker_pid", "worker_start_abstime",
                "worker_ppid", "worker_pgid", "worker_sid",
            },
            "broker hello",
        )
        if (
            mapping["attempt_nonce_sha256"]
            != hashlib.sha256(self.config.attempt_nonce.encode("ascii")).hexdigest()
            or mapping["scope_sha256"] != self.config.scope_sha256
        ):
            raise BrokerProtocolError("broker hello capability differs")
        worker = kernel_process_identity(_positive_int(mapping["worker_pid"], "worker_pid"))
        if (
            worker.start_abstime != mapping["worker_start_abstime"]
            or worker.ppid != mapping["worker_ppid"]
            or worker.pgid != mapping["worker_pgid"]
            or worker.sid != mapping["worker_sid"]
            or worker.pid != worker.pgid
            or worker.pid != worker.sid
            or worker.pgid == self.identity.pgid
        ):
            raise BrokerProtocolError("broker worker identity differs")
        self.worker_identity = worker
        self.ledger.append(
            "hello",
            {
                "attempt_nonce_sha256": hashlib.sha256(self.config.attempt_nonce.encode("ascii")).hexdigest(),
                "scope_sha256": self.config.scope_sha256,
                "worker": asdict(worker),
            },
        )
        if (
            self.pre_release_ready_sha256 is None
            or self.pre_release_thread_inventory is None
            or self.pre_release_file_descriptor_inventory is None
            or self.retired_descriptor_fds is None
        ):
            raise BrokerProtocolError("broker pre-release baseline is unavailable")
        post_release_threads = native_detailed_thread_inventory(
            self.identity.pid
        )
        post_release_descriptors = (
            native_detailed_file_descriptor_inventory(self.identity.pid)
        )
        baseline_mapping: dict[str, Any] = {
            "schema_id": "parser-tesseract-broker-post-release-baseline-v1",
            "broker": self.identity,
            "pre_release_ready_sha256": self.pre_release_ready_sha256,
            "retired_descriptor_fds": self.retired_descriptor_fds,
            "pre_release_thread_inventory": self.pre_release_thread_inventory,
            "pre_release_file_descriptor_inventory": (
                self.pre_release_file_descriptor_inventory
            ),
            "post_release_thread_inventory": post_release_threads,
            "post_release_file_descriptor_inventory": (
                post_release_descriptors
            ),
            "transition_observed_at_monotonic_ns": time.monotonic_ns(),
        }
        baseline_mapping["record_sha256"] = canonical_sha256(
            {
                key: asdict(value)
                if hasattr(value, "__dataclass_fields__")
                else value
                for key, value in baseline_mapping.items()
            }
        )
        post_release_baseline = BrokerPostReleaseBaseline(
            **baseline_mapping
        )
        self.channel.send(
            "hello_ack",
            {
                "attempt_nonce_sha256": hashlib.sha256(self.config.attempt_nonce.encode("ascii")).hexdigest(),
                "scope_sha256": self.config.scope_sha256,
                "broker_pid": self.identity.pid,
                "broker_start_abstime": self.identity.start_abstime,
                "broker_pgid": self.identity.pgid,
                "broker_sid": self.identity.sid,
                "post_release_baseline": asdict(post_release_baseline),
            },
        )

    def _handle_begin(self, payload: object, body: bytes) -> None:
        if body or self.worker_identity is None or self.active is not None or self.pending_receipt is not None:
            raise BrokerProtocolError("broker begin state differs")
        mapping = _strict_object(
            payload,
            {
                "attempt_nonce_sha256", "scope_sha256", "phase", "request_id",
                "request_epoch", "request_sequence", "worker_python_thread_id",
                "worker_thread_id", "capability", "arm_capability", "binding",
                "binding_sha256", "phase_deadline_monotonic_ns",
                "thread_transfer_required", "arm_issued_at_monotonic_ns",
            },
            "broker begin",
        )
        if (
            mapping["attempt_nonce_sha256"] != hashlib.sha256(self.config.attempt_nonce.encode("ascii")).hexdigest()
            or mapping["scope_sha256"] != self.config.scope_sha256
            or mapping["phase"] not in {"startup", "request", "shutdown"}
            or not isinstance(mapping["request_id"], str)
            or not 0 < len(mapping["request_id"]) <= 256
            or mapping["request_epoch"] != self.last_epoch + 1
            or canonical_sha256(mapping["binding"]) != mapping["binding_sha256"]
        ):
            raise BrokerProtocolError("broker begin binding differs")
        expected_phases = {
            "awaiting_startup": {"startup"},
            "ready": {"request", "shutdown"},
            "closed": set(),
        }
        if mapping["phase"] not in expected_phases[self._lifecycle_state]:
            raise BrokerProtocolError("broker lifecycle phase order differs")
        _positive_int(mapping["worker_thread_id"], "worker_thread_id")
        _positive_int(
            mapping["worker_python_thread_id"], "worker_python_thread_id"
        )
        if type(mapping["thread_transfer_required"]) is not bool or (
            mapping["thread_transfer_required"]
            and mapping["phase"] != "request"
        ):
            raise BrokerProtocolError("thread-transfer requirement differs")
        deadline = _positive_int(mapping["phase_deadline_monotonic_ns"], "phase deadline")
        if deadline > self.config.attempt_deadline_ns or deadline <= time.monotonic_ns():
            raise BrokerProtocolError("broker phase deadline differs")
        arm_issued_at = _positive_int(
            mapping["arm_issued_at_monotonic_ns"],
            "arm_issued_at_monotonic_ns",
        )
        arm_consumed_at = time.monotonic_ns()
        if arm_issued_at > arm_consumed_at or arm_consumed_at > deadline:
            raise BrokerProtocolError("broker arm lifetime differs")
        request_sequence = _positive_int(mapping["request_sequence"], "request_sequence")
        if mapping["phase"] == "request":
            if request_sequence != self.last_request_sequence + 1:
                raise BrokerProtocolError("broker request sequence differs")
        elif request_sequence != max(1, self.last_request_sequence):
            raise BrokerProtocolError("broker lifecycle request sequence differs")
        capability = mapping.pop("capability")
        if not isinstance(capability, str) or len(capability) != 64:
            raise BrokerProtocolError("broker phase capability differs")
        mapping["capability_sha256"] = hashlib.sha256(capability.encode("ascii")).hexdigest()
        arm_capability = mapping.pop("arm_capability")
        if (
            not isinstance(arm_capability, str)
            or len(arm_capability) != 64
            or any(value not in "0123456789abcdef" for value in arm_capability)
        ):
            raise BrokerProtocolError("broker arm capability differs")
        mapping["arm_capability_sha256"] = hashlib.sha256(
            arm_capability.encode("ascii")
        ).hexdigest()
        self.active = {
            "request_id": mapping["request_id"],
            "request_epoch": mapping["request_epoch"],
            "request_sequence": request_sequence,
            "worker_python_thread_id": mapping["worker_python_thread_id"],
            "worker_thread_id": mapping["worker_thread_id"],
            "capability_sha256": mapping["capability_sha256"],
            "arm_capability_sha256": mapping["arm_capability_sha256"],
            "binding_sha256": mapping["binding_sha256"],
            "phase": mapping["phase"],
            "phase_deadline_ns": deadline,
            "begin_released": False,
            "thread_transfer_required": mapping["thread_transfer_required"],
            "thread_transfer_state": "unclaimed",
            "binding": mapping["binding"],
            "request_binding": None,
            "arm_issued_at_monotonic_ns": arm_issued_at,
            "arm_consumed_at_monotonic_ns": arm_consumed_at,
        }
        self.births = []
        self.tombstones = []
        self.thread_transfers = []
        begin = self._quiescence("begin")
        self.active["begin"] = begin
        self.last_epoch = mapping["request_epoch"]
        if mapping["phase"] == "request":
            self.last_request_sequence = request_sequence
        self.channel.send(
            "begin_ack",
            {
                "quiescence": dataclass_mapping(begin),
                "arm_consumed_at_monotonic_ns": arm_consumed_at,
            },
        )

    def _handle_request_match(self, payload: object, body: bytes) -> None:
        if body or self.active is None:
            raise BrokerProtocolError("request match lacks an active phase")
        mapping = _strict_object(
            payload,
            {
                "request_id", "request_epoch", "request_sequence",
                "worker_python_thread_id", "worker_thread_id",
                "capability_sha256", "arm_capability_sha256", "binding_sha256",
                "actual_request",
            },
            "actual request match",
        )
        self._validate_phase_message(
            {key: value for key, value in mapping.items() if key != "actual_request"}
        )
        actual = _strict_object(
            mapping["actual_request"],
            {
                "schema_id", "method", "path", "query_sha256",
                "output_format", "source_sha256", "source_bytes",
                "safe_filename_sha256", "upload_content_type_sha256",
            },
            "actual request identity",
        )
        if (
            self.active["phase"] != "request"
            or self.active["thread_transfer_required"] is not True
            or self.active["begin_released"] is not True
            or self.active["thread_transfer_state"] != "unclaimed"
            or self.active["request_binding"] is not None
            or actual != self.active["binding"]
            or canonical_sha256(actual) != self.active["binding_sha256"]
        ):
            raise BrokerProtocolError("actual request does not match its arm")
        evidence: dict[str, Any] = {
            **actual,
            "binding_record_sha256": self.active["binding_sha256"],
            "actual_request_matched": True,
            "matched_at_monotonic_ns": time.monotonic_ns(),
        }
        evidence["record_sha256"] = canonical_sha256(evidence)
        from app.services.tesseract_broker_protocol import (
            BrokerRequestBindingEvidence,
        )

        request_binding = BrokerRequestBindingEvidence(**evidence)
        self.ledger.append("request_match", dataclass_mapping(request_binding))
        self.active["request_binding"] = request_binding
        self.channel.send(
            "request_match_ack",
            {"request_binding": dataclass_mapping(request_binding)},
        )

    def _handle_thread_transfer(
        self,
        kind: str,
        payload: object,
        body: bytes,
    ) -> None:
        if body or self.active is None or self.worker_identity is None:
            raise BrokerProtocolError("broker thread transfer lacks an active phase")
        mapping = _strict_object(
            payload,
            {
                "request_id", "request_epoch", "request_sequence",
                "worker_python_thread_id", "worker_thread_id",
                "capability_sha256", "arm_capability_sha256", "binding_sha256",
                "to_python_thread_id", "to_native_thread_id",
            },
            "thread transfer",
        )
        self._validate_phase_message(
            {
                key: value
                for key, value in mapping.items()
                if key not in {"to_python_thread_id", "to_native_thread_id"}
            }
        )
        if (
            self.active["phase"] != "request"
            or self.active["begin_released"] is not True
            or self.active["thread_transfer_required"] is not True
            or self.active["request_binding"] is None
        ):
            raise BrokerProtocolError("broker thread transfer phase differs")
        expected_state = "unclaimed" if kind == "thread_claim" else "claimed"
        if (
            self.active["thread_transfer_state"] != expected_state
            or len(self.thread_transfers) != (0 if kind == "thread_claim" else 1)
            or (kind == "thread_claim" and self.births)
        ):
            raise BrokerProtocolError("broker thread transfer order differs")
        to_python_thread_id = _positive_int(
            mapping["to_python_thread_id"], "to_python_thread_id"
        )
        to_native_thread_id = _positive_int(
            mapping["to_native_thread_id"], "to_native_thread_id"
        )
        if (
            to_python_thread_id == self.active["worker_python_thread_id"]
            or to_native_thread_id == self.active["worker_thread_id"]
        ):
            raise BrokerProtocolError("broker thread transfer did not change owner")
        if kind == "thread_release":
            first = self.thread_transfers[0]
            if (
                to_python_thread_id != first.from_python_thread_id
                or to_native_thread_id != first.from_native_thread_id
            ):
                raise BrokerProtocolError("broker thread authority was not returned")
        issued_at = time.monotonic_ns()
        transfer_mapping: dict[str, Any] = {
            "attempt_nonce_sha256": hashlib.sha256(
                self.config.attempt_nonce.encode("ascii")
            ).hexdigest(),
            "scope_sha256": self.config.scope_sha256,
            "request_id": self.active["request_id"],
            "request_epoch": self.active["request_epoch"],
            "request_sequence": self.active["request_sequence"],
            "transfer_sequence": len(self.thread_transfers) + 1,
            "kind": "claim" if kind == "thread_claim" else "release",
            "worker_pid": self.worker_identity.pid,
            "worker_start_abstime": self.worker_identity.start_abstime,
            "from_python_thread_id": self.active["worker_python_thread_id"],
            "from_native_thread_id": self.active["worker_thread_id"],
            "to_python_thread_id": to_python_thread_id,
            "to_native_thread_id": to_native_thread_id,
            "arm_capability_sha256": self.active["arm_capability_sha256"],
            "logical_phase": self.active["phase"],
            "binding_sha256": self.active["binding_sha256"],
            "phase_deadline_monotonic_ns": self.active["phase_deadline_ns"],
            "first_permitted_spawn_sequence": (
                self.thread_transfers[0].first_permitted_spawn_sequence
                if self.thread_transfers
                else len(self.births) + 1
            ),
            "last_permitted_spawn_sequence": len(self.births),
            "previous_transfer_sha256": (
                self.thread_transfers[-1].record_sha256
                if self.thread_transfers
                else _ZERO_SHA256
            ),
            "issued_at_monotonic_ns": issued_at,
            "acknowledged_at_monotonic_ns": time.monotonic_ns(),
        }
        transfer_mapping["record_sha256"] = canonical_sha256(transfer_mapping)
        transfer = BrokerThreadTransfer(**transfer_mapping)
        self.ledger.append("thread_transfer", dataclass_mapping(transfer))
        self.thread_transfers.append(transfer)
        self.active["worker_python_thread_id"] = to_python_thread_id
        self.active["worker_thread_id"] = to_native_thread_id
        self.active["thread_transfer_state"] = (
            "claimed" if kind == "thread_claim" else "returned"
        )
        self.channel.send(f"{kind}_ack", {"transfer": dataclass_mapping(transfer)})

    def _validate_command(
        self, value: object, body: bytes | bytearray
    ) -> tuple[str, tuple[str, ...], dict[str, str]]:
        command = _strict_object(
            value,
            {
                "operation", "language", "tessdata", "psm", "input_suffix",
                "input_bytes", "input_sha256", "input_transport",
                "logical_argv_sha256", "stderr_mode",
                "stdout_disposition", "stderr_disposition",
            },
            "broker command",
        )
        operation = command["operation"]
        if operation not in {"version", "list_languages", "ocr_tsv", "ocr_text", "osd"}:
            raise BrokerProtocolError("broker operation differs")
        if command["stderr_mode"] not in {"separate", "merge", "discard"}:
            raise BrokerProtocolError("broker stderr mode differs")
        if (
            command["stdout_disposition"] not in {"captured", "discarded"}
            or command["stderr_disposition"]
            != (
                "discarded"
                if command["stderr_mode"] == "discard"
                else "captured"
            )
        ):
            raise BrokerProtocolError("broker stream disposition differs")
        if command["input_bytes"] != len(body) or command["input_sha256"] != hashlib.sha256(body).hexdigest():
            raise BrokerProtocolError("broker input identity differs")
        language = command["language"]
        if language is not None and (
            not isinstance(language, str)
            or any(item not in self.config.languages for item in language.split("+"))
        ):
            raise BrokerProtocolError("broker language differs")
        if command["tessdata"] not in {None, self.config.tessdata_root}:
            raise BrokerProtocolError("broker tessdata differs")
        psm = command["psm"]
        if psm is not None and (isinstance(psm, bool) or not isinstance(psm, int) or not 0 <= psm <= 13):
            raise BrokerProtocolError("broker PSM differs")
        suffix = command["input_suffix"]
        input_transport = command["input_transport"]
        allowed_suffixes = {
            ".bin", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
            ".bmp", ".pnm", ".pbm", ".pgm", ".ppm",
        }
        if operation in {"version", "list_languages"}:
            if (
                body
                or command["input_bytes"] != 0
                or command["input_sha256"] != _EMPTY_SHA256
                or command["language"] is not None
                or command["tessdata"] is not None
                or psm is not None
                or suffix != ""
                or input_transport != "none"
            ):
                raise BrokerProtocolError("metadata command shape differs")
        else:
            if (
                not body
                or suffix not in allowed_suffixes
                or input_transport not in {"stdin", "custodied-request-file"}
            ):
                raise BrokerProtocolError("OCR command input shape differs")
            if operation == "osd" and (psm != 0 or language != "osd"):
                raise BrokerProtocolError("OSD command shape differs")
            if operation != "osd" and psm == 0:
                raise BrokerProtocolError("OCR command PSM differs")
        executable = self.config.executable.resolved_path
        if operation == "version":
            argv = (executable, "--version")
        elif operation == "list_languages":
            argv = (executable, "--list-langs")
        else:
            values: list[str] = [executable]
            if language is not None:
                values.extend(("-l", language))
            if command["tessdata"] is not None:
                values.extend(("--tessdata-dir", self.config.tessdata_root))
            if psm is not None:
                values.extend(("--psm", str(psm)))
            values.extend(("stdin", "stdout"))
            if operation == "ocr_tsv":
                values.append("tsv")
            argv = tuple(values)
        expected_logical_sha256 = canonical_tesseract_logical_argv_sha256(
            source_executable=self.config.source_executable.resolved_path,
            operation=operation,
            language=language,
            tessdata=command["tessdata"],
            psm=psm,
            input_transport=input_transport,
            input_suffix=suffix,
            input_sha256=command["input_sha256"],
            input_bytes=command["input_bytes"],
        )
        if expected_logical_sha256 != command["logical_argv_sha256"]:
            raise BrokerProtocolError("logical Tesseract argv differs")
        return operation, argv, frozen_tesseract_environment(self.config.tessdata_root)

    def _watchdog_register_child(
        self,
        *,
        child: KernelProcessIdentity,
        spawn_sequence: int,
        spawn_nonce_sha256: str,
        child_deadline_ns: int,
        provisional_child_ledger_row_sha256: str,
        spawn_intent_sha256: str,
        spawn_intent_ledger_row_sha256: str,
        native_child_limit_applied_monotonic_ns: int,
        native_child_limit_ack_sha256_value: str,
        native_fork_parent_returned_monotonic_ns: int,
        native_child_limit_acknowledged_monotonic_ns: int,
    ) -> tuple[str, str, int]:
        if self.active is None:
            raise BrokerProtocolError("watchdog registration lacks phase")
        record: dict[str, Any] = {
            "attempt_nonce_sha256": hashlib.sha256(
                self.config.attempt_nonce.encode("ascii")
            ).hexdigest(),
            "scope_sha256": self.config.scope_sha256,
            "request_id": self.active["request_id"],
            "request_epoch": self.active["request_epoch"],
            "request_sequence": self.active["request_sequence"],
            "spawn_sequence": spawn_sequence,
            "spawn_nonce_sha256": spawn_nonce_sha256,
            "pid": child.pid,
            "start_abstime": child.start_abstime,
            "ppid": child.ppid,
            "pgid": child.pgid,
            "sid": child.sid,
            "child_deadline_monotonic_ns": child_deadline_ns,
            "provisional_child_ledger_row_sha256": (
                provisional_child_ledger_row_sha256
            ),
            "spawn_intent_sha256": spawn_intent_sha256,
            "spawn_intent_ledger_row_sha256": (
                spawn_intent_ledger_row_sha256
            ),
            "native_child_limit_ack_authority": (
                NATIVE_CHILD_LIMIT_ACK_AUTHORITY
            ),
            "native_child_limit_applied_clock_authority": (
                NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
            ),
            "native_child_limit_ack_pid": child.pid,
            "native_child_limit_applied_monotonic_ns": (
                native_child_limit_applied_monotonic_ns
            ),
            "native_child_limit_ack_sha256": (
                native_child_limit_ack_sha256_value
            ),
            "native_fork_parent_returned_monotonic_ns": (
                native_fork_parent_returned_monotonic_ns
            ),
            "native_child_limit_acknowledged_monotonic_ns": (
                native_child_limit_acknowledged_monotonic_ns
            ),
        }
        record["registration_sha256"] = canonical_sha256(record)
        self.watchdog_channel.send("child_watch_register", record)
        _, ack, body = self.watchdog_channel.receive(
            expected_kind="child_watch_register_ack"
        )
        expected_identity = {
            key: record[key]
            for key in (
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
                "pid",
                "start_abstime",
                "ppid",
                "pgid",
                "sid",
                "registration_sha256",
                "spawn_intent_sha256",
                "spawn_intent_ledger_row_sha256",
                "provisional_child_ledger_row_sha256",
                "native_child_limit_ack_authority",
                "native_child_limit_applied_clock_authority",
                "native_child_limit_ack_pid",
                "native_child_limit_applied_monotonic_ns",
                "native_child_limit_ack_sha256",
                "native_fork_parent_returned_monotonic_ns",
                "native_child_limit_acknowledged_monotonic_ns",
            )
        }
        if body or not isinstance(ack, dict) or set(ack) != {
            *expected_identity,
            "watchdog_observed_monotonic_ns",
            "watchdog_record_sha256",
        }:
            raise BrokerProtocolError("watchdog registration ACK fields differ")
        ack_sha = ack.pop("watchdog_record_sha256")
        if (
            any(ack[key] != value for key, value in expected_identity.items())
            or _positive_int(
                ack["watchdog_observed_monotonic_ns"],
                "watchdog_observed_monotonic_ns",
            )
            <= 0
            or ack_sha != canonical_sha256(ack)
        ):
            raise BrokerProtocolError("watchdog registration ACK binding differs")
        ack["watchdog_record_sha256"] = ack_sha
        self.ledger.append("watchdog_register_ack", ack)
        return (
            record["registration_sha256"],
            ack_sha,
            int(ack["watchdog_observed_monotonic_ns"]),
        )

    def _watchdog_close_child(
        self,
        *,
        birth: BrokerChildBirth,
        tombstone: BrokerChildWait4Tombstone,
        tombstone_ledger_row_sha256: str,
        absolute_deadline_ns: int,
    ) -> None:
        if time.monotonic_ns() >= absolute_deadline_ns:
            raise TimeoutError(
                "child watchdog REAP publication preceded by an expired deadline"
            )
        record: dict[str, Any] = {
            "request_id": birth.request_id,
            "request_epoch": birth.request_epoch,
            "request_sequence": birth.request_sequence,
            "spawn_sequence": birth.spawn_sequence,
            "spawn_nonce_sha256": birth.spawn_nonce_sha256,
            "pid": birth.pid,
            "start_abstime": birth.start_abstime,
            "registration_sha256": birth.watchdog_registration_sha256,
            "birth_record_sha256": birth.birth_commitment_sha256,
            "tombstone_record_sha256": tombstone.record_sha256,
            "raw_wait_status": tombstone.raw_wait_status,
            "wait4_observed_monotonic_ns": tombstone.observed_monotonic_ns,
            "tombstone_ledger_row_sha256": tombstone_ledger_row_sha256,
            "native_runtime_attestation_sha256": (
                tombstone.native_runtime_attestation.record_sha256
            ),
            "native_runtime_scan_log_sha256": (
                tombstone.native_runtime_attestation.scan_log_sha256
            ),
            "guard_to_exec_transition_sha256": (
                tombstone.native_runtime_attestation.guard_to_exec_transition_sha256
            ),
            "native_closure_post_wait4_sha256": (
                tombstone.native_runtime_attestation.static_closure_post_wait4_sha256
            ),
        }
        record["reaped_record_sha256"] = canonical_sha256(record)
        self.watchdog_channel.send("child_watch_reaped", record)
        _, ack, body = self.watchdog_channel.receive(
            expected_kind="child_watch_reaped_ack"
        )
        identity_keys = (
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "pid",
            "start_abstime",
            "registration_sha256",
            "tombstone_record_sha256",
        )
        if body or not isinstance(ack, dict) or set(ack) != {
            *identity_keys,
            "watchdog_observed_monotonic_ns",
            "watchdog_record_sha256",
        }:
            raise BrokerProtocolError("watchdog reaped ACK fields differ")
        ack_sha = ack.pop("watchdog_record_sha256")
        if (
            any(ack[key] != record[key] for key in identity_keys)
            or _positive_int(
                ack["watchdog_observed_monotonic_ns"],
                "watchdog_observed_monotonic_ns",
            )
            <= 0
            or ack_sha != canonical_sha256(ack)
            or ack["watchdog_observed_monotonic_ns"]
            >= absolute_deadline_ns
        ):
            raise BrokerProtocolError("watchdog reaped ACK binding differs")
        ack["watchdog_record_sha256"] = ack_sha
        self.ledger.append("watchdog_reaped_ack", ack)
        if time.monotonic_ns() >= absolute_deadline_ns:
            raise TimeoutError(
                "child watchdog REAP publication crossed its deadline"
            )

    def _watchdog_bind_birth(
        self,
        birth_commitment: Mapping[str, Any],
        *,
        birth_ledger_row_sha256: str,
    ) -> tuple[str, str, int]:
        record: dict[str, Any] = {
            "request_id": birth_commitment["request_id"],
            "request_epoch": birth_commitment["request_epoch"],
            "request_sequence": birth_commitment["request_sequence"],
            "spawn_sequence": birth_commitment["spawn_sequence"],
            "spawn_nonce_sha256": birth_commitment["spawn_nonce_sha256"],
            "pid": birth_commitment["pid"],
            "start_abstime": birth_commitment["start_abstime"],
            "registration_sha256": birth_commitment[
                "watchdog_registration_sha256"
            ],
            "birth_record_sha256": birth_commitment[
                "birth_commitment_sha256"
            ],
            "spawn_intent_sha256": birth_commitment[
                "spawn_intent_sha256"
            ],
            "spawn_intent_ledger_row_sha256": birth_commitment[
                "spawn_intent_ledger_row_sha256"
            ],
            "provisional_record_sha256": birth_commitment[
                "provisional_record_sha256"
            ],
            "provisional_child_ledger_row_sha256": birth_commitment[
                "provisional_child_ledger_row_sha256"
            ],
            "child_ready_intent_ledger_row_sha256": birth_commitment[
                "child_ready_intent_ledger_row_sha256"
            ],
            "child_ready_sha256": birth_commitment["child_ready_sha256"],
            "open_fd_count": birth_commitment["open_fd_count"],
            "open_file_descriptors": birth_commitment[
                "open_file_descriptors"
            ],
            "open_fd_inventory_sha256": birth_commitment[
                "open_fd_inventory_sha256"
            ],
            "native_thread_count": birth_commitment["native_thread_count"],
            "native_thread_ids": birth_commitment["native_thread_ids"],
            "native_thread_inventory_sha256": birth_commitment[
                "native_thread_inventory_sha256"
            ],
            "native_spawn_guard_sha256": birth_commitment[
                "native_spawn_guard_sha256"
            ],
            "native_spawn_guard_source_sha256": birth_commitment[
                "native_spawn_guard_source_sha256"
            ],
            "native_spawn_guard_kind": birth_commitment[
                "native_spawn_guard_kind"
            ],
            "guard_python_sha256": birth_commitment[
                "guard_python_sha256"
            ],
            "guard_python_path_custody_sha256": birth_commitment[
                "guard_python_path_custody_sha256"
            ],
            "guard_python_native_closure_sha256": birth_commitment[
                "guard_python_native_closure_sha256"
            ],
            "guard_python_module_tree_sha256": birth_commitment[
                "guard_python_module_tree_sha256"
            ],
            "guard_python_path_exec_trust_model": birth_commitment[
                "guard_python_path_exec_trust_model"
            ],
            "guard_python_path_exec_containment_claim": birth_commitment[
                "guard_python_path_exec_containment_claim"
            ],
            "guard_wrapper_delivery_basis": birth_commitment[
                "guard_wrapper_delivery_basis"
            ],
            "guard_config_fd": birth_commitment["guard_config_fd"],
            "guard_ready_fd": birth_commitment["guard_ready_fd"],
            "guard_exec_argv_sha256": birth_commitment[
                "guard_exec_argv_sha256"
            ],
            "guard_exec_environment_sha256": birth_commitment[
                "guard_exec_environment_sha256"
            ],
            "guard_post_exec_environment_sha256": birth_commitment[
                "guard_post_exec_environment_sha256"
            ],
            "native_child_config_sha256": birth_commitment[
                "native_child_config_sha256"
            ],
            "native_child_config_projection": birth_commitment[
                "native_child_config_projection"
            ],
            "native_child_config_projection_sha256": birth_commitment[
                "native_child_config_projection_sha256"
            ],
            "child_sandbox_probe_mode": birth_commitment[
                "child_sandbox_probe_mode"
            ],
            "child_sandbox_probe_plan_sha256": birth_commitment[
                "child_sandbox_probe_plan_sha256"
            ],
            "child_sandbox_probe_executor_authority": birth_commitment[
                "child_sandbox_probe_executor_authority"
            ],
            "child_sandbox_probe_executor_source_sha256": birth_commitment[
                "child_sandbox_probe_executor_source_sha256"
            ],
            "child_sandbox_probe_library_sha256": birth_commitment[
                "child_sandbox_probe_library_sha256"
            ],
            "child_sandbox_probe_representative_report_sha256": birth_commitment[
                "child_sandbox_probe_representative_report_sha256"
            ],
            "child_sandbox_probe_report_ledger_row_sha256": birth_commitment[
                "child_sandbox_probe_report_ledger_row_sha256"
            ],
            "child_sandbox_probe_report_reservation_bytes": birth_commitment[
                "child_sandbox_probe_report_reservation_bytes"
            ],
            "native_child_limit_applied_monotonic_ns": birth_commitment[
                "native_child_limit_applied_monotonic_ns"
            ],
            "native_child_limit_ack_authority": birth_commitment[
                "native_child_limit_ack_authority"
            ],
            "native_child_limit_applied_clock_authority": birth_commitment[
                "native_child_limit_applied_clock_authority"
            ],
            "native_child_limit_ack_pid": birth_commitment[
                "native_child_limit_ack_pid"
            ],
            "native_child_limit_ack_sha256": birth_commitment[
                "native_child_limit_ack_sha256"
            ],
            "native_fork_parent_returned_monotonic_ns": birth_commitment[
                "native_fork_parent_returned_monotonic_ns"
            ],
            "native_child_limit_acknowledged_monotonic_ns": birth_commitment[
                "native_child_limit_acknowledged_monotonic_ns"
            ],
            "child_guard_applied_at_monotonic_ns": birth_commitment[
                "child_guard_applied_at_monotonic_ns"
            ],
            "child_guard_applied_clock_authority": birth_commitment[
                "child_guard_applied_clock_authority"
            ],
            "child_reported_guard_release_a_monotonic_ns": (
                birth_commitment[
                    "child_reported_guard_release_a_monotonic_ns"
                ]
            ),
            "child_guard_release_a_record_sha256": birth_commitment[
                "child_guard_release_a_record_sha256"
            ],
            "child_guard_ready_observed_monotonic_ns": birth_commitment[
                "child_guard_ready_observed_monotonic_ns"
            ],
            "hard_limit_installed_before_python_return": birth_commitment[
                "hard_limit_installed_before_python_return"
            ],
            "pthread_atfork_callbacks_bypassed": birth_commitment[
                "pthread_atfork_callbacks_bypassed"
            ],
            "native_python_release_n_monotonic_ns": birth_commitment[
                "native_python_release_n_monotonic_ns"
            ],
            "prior_signal_mask": birth_commitment["prior_signal_mask"],
            "prior_signal_mask_sha256": birth_commitment[
                "prior_signal_mask_sha256"
            ],
            "restored_signal_mask": birth_commitment[
                "restored_signal_mask"
            ],
            "restored_signal_mask_sha256": birth_commitment[
                "restored_signal_mask_sha256"
            ],
            "exact_prior_signal_mask_restored_before_ready": birth_commitment[
                "exact_prior_signal_mask_restored_before_ready"
            ],
            "broker_thread_count_immediately_before_fork": birth_commitment[
                "broker_thread_count_immediately_before_fork"
            ],
            "broker_thread_inventory_immediately_before_fork_sha256": birth_commitment[
                "broker_thread_inventory_immediately_before_fork_sha256"
            ],
            "broker_thread_immediately_before_fork_observed_at_monotonic_ns": birth_commitment[
                "broker_thread_immediately_before_fork_observed_at_monotonic_ns"
            ],
            "born_monotonic_ns": birth_commitment["born_monotonic_ns"],
            "blocked_signals_across_fork": birth_commitment[
                "blocked_signals_across_fork"
            ],
            "blocked_signals_across_fork_sha256": birth_commitment[
                "blocked_signals_across_fork_sha256"
            ],
            "blockable_signals_masked_across_fork": birth_commitment[
                "blockable_signals_masked_across_fork"
            ],
            "birth_ledger_row_sha256": birth_ledger_row_sha256,
            "released_monotonic_ns": birth_commitment[
                "guard_release_a_monotonic_ns"
            ],
            "executable_sha256": birth_commitment["executable_sha256"],
            "native_closure_sha256": birth_commitment[
                "native_closure_sha256"
            ],
            "native_trust_model": birth_commitment["native_trust_model"],
            "native_containment_claim": birth_commitment[
                "native_containment_claim"
            ],
            "native_runtime_attestation_required": birth_commitment[
                "native_runtime_attestation_required"
            ],
            "native_runtime_scan_interval_ns": birth_commitment[
                "native_runtime_scan_interval_ns"
            ],
            "logical_argv_sha256": birth_commitment[
                "logical_argv_sha256"
            ],
            "actual_argv_sha256": birth_commitment["actual_argv_sha256"],
            "logical_environment_sha256": birth_commitment[
                "logical_environment_sha256"
            ],
            "actual_environment_projection_sha256": birth_commitment[
                "actual_environment_projection_sha256"
            ],
            "native_runtime_gate_authority": birth_commitment[
                "native_runtime_gate_authority"
            ],
            "native_runtime_gate_initializer_order_limitation": birth_commitment[
                "native_runtime_gate_initializer_order_limitation"
            ],
            "native_runtime_gate_source_sha256": birth_commitment[
                "native_runtime_gate_source_sha256"
            ],
            "native_runtime_gate_library_sha256": birth_commitment[
                "native_runtime_gate_library_sha256"
            ],
            "native_runtime_gate_record_sha256": birth_commitment[
                "native_runtime_gate_record_sha256"
            ],
            "runtime_gate_nonce_sha256": birth_commitment[
                "runtime_gate_nonce_sha256"
            ],
            "runtime_gate_ack_authority": birth_commitment[
                "runtime_gate_ack_authority"
            ],
        }
        delegated_record = child_watch_birth_from_commitment(
            birth_commitment,
            birth_ledger_row_sha256=birth_ledger_row_sha256,
        )
        if json.loads(canonical_json_bytes(record)) != delegated_record:
            raise BrokerProtocolError(
                "watchdog BIRTH projection differs from its commitment"
            )
        record = delegated_record
        record["watch_birth_sha256"] = canonical_sha256(record)
        self.watchdog_channel.send("child_watch_birth", record)
        _, ack, body = self.watchdog_channel.receive(
            expected_kind="child_watch_birth_ack"
        )
        identity_keys = (
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "pid",
            "start_abstime",
            "registration_sha256",
            "birth_record_sha256",
            "watch_birth_sha256",
        )
        if body or not isinstance(ack, dict) or set(ack) != {
            *identity_keys,
            "watchdog_observed_monotonic_ns",
            "watchdog_record_sha256",
        }:
            raise BrokerProtocolError("watchdog birth ACK fields differ")
        ack_sha = ack.pop("watchdog_record_sha256")
        if (
            any(ack[key] != record[key] for key in identity_keys)
            or _positive_int(
                ack["watchdog_observed_monotonic_ns"],
                "watchdog_observed_monotonic_ns",
            )
            <= 0
            or ack_sha != canonical_sha256(ack)
        ):
            raise BrokerProtocolError("watchdog birth ACK binding differs")
        ack["watchdog_record_sha256"] = ack_sha
        self.ledger.append("watchdog_birth_ack", ack)
        return (
            record["watch_birth_sha256"],
            ack_sha,
            int(ack["watchdog_observed_monotonic_ns"]),
        )

    def _read_child_line(
        self,
        fd: int,
        deadline_ns: int,
        *,
        guard_exec_error_fd: int | None = None,
        maximum_bytes: int = MAX_CHILD_READY_BYTES,
    ) -> dict[str, Any]:
        if (
            isinstance(maximum_bytes, bool)
            or not isinstance(maximum_bytes, int)
            or maximum_bytes <= 0
            or maximum_bytes > MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES + 1
        ):
            raise BrokerProtocolError("child record bound differs")
        selector = selectors.DefaultSelector()
        selector.register(fd, selectors.EVENT_READ)
        if guard_exec_error_fd is not None:
            selector.register(guard_exec_error_fd, selectors.EVENT_READ)
        data = self._child_line_buffers.pop(fd, bytearray())
        exec_error = bytearray()
        exec_error_eof = guard_exec_error_fd is None
        ready_eof = False
        try:
            while b"\n" not in data or not exec_error_eof:
                if ready_eof and exec_error_eof:
                    raise BrokerProtocolError(
                        "child gate closed before READY"
                    )
                remaining = deadline_ns - time.monotonic_ns()
                if remaining <= 0:
                    raise TimeoutError("child gate deadline expired")
                events = selector.select(remaining / 1_000_000_000)
                if not events:
                    raise TimeoutError("child gate deadline expired")
                for key, _ in events:
                    if key.fd == fd:
                        if b"\n" in data:
                            selector.unregister(fd)
                            continue
                        chunk = os.read(
                            fd, maximum_bytes + 1 - len(data)
                        )
                        if not chunk:
                            selector.unregister(fd)
                            ready_eof = True
                            continue
                        data.extend(chunk)
                        if len(data) > maximum_bytes:
                            raise BrokerProtocolError(
                                "child record exceeds its bound"
                            )
                        if b"\n" in data:
                            selector.unregister(fd)
                    else:
                        chunk = os.read(
                            key.fd, 25 - len(exec_error)
                        )
                        if chunk:
                            exec_error.extend(chunk)
                            if len(exec_error) > 24:
                                raise BrokerProtocolError(
                                    "native guard exec error exceeds its bound"
                                )
                        else:
                            selector.unregister(key.fd)
                            exec_error_eof = True
                            if exec_error:
                                if (
                                    len(exec_error) != 24
                                    or bytes(exec_error[:8]) != b"GEXEC1!!"
                                ):
                                    raise BrokerProtocolError(
                                        "native guard exec error is malformed"
                                    )
                                error_pid = int.from_bytes(
                                    exec_error[8:16], "big"
                                )
                                error_number = int.from_bytes(
                                    exec_error[16:24], "big"
                                )
                                raise BrokerProtocolError(
                                    "native guard exec failed "
                                    f"for pid {error_pid} with errno "
                                    f"{error_number}"
                                )
        finally:
            selector.close()
        line, trailing = bytes(data).split(b"\n", 1)
        if trailing:
            self._child_line_buffers[fd] = bytearray(trailing)
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrokerProtocolError("child READY is malformed") from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) != line:
            raise BrokerProtocolError("child READY is not canonical")
        if value.get("schema_id") == "parser-tesseract-child-guard-error-v1":
            raise BrokerProtocolError(
                "fresh child guard failed: "
                f"{value.get('stage')!r} {value.get('error')!r}"
            )
        return value

    @staticmethod
    def _write_child_config(
        fd: int,
        body: bytes,
        deadline_ns: int,
    ) -> None:
        """Stream one prebound config without exceeding its absolute deadline."""

        if not body or len(body) > MAX_NATIVE_CHILD_CONFIG_BYTES:
            raise BrokerProtocolError("native child config size differs")
        original_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        selector = selectors.DefaultSelector()
        view = memoryview(body)
        try:
            fcntl.fcntl(fd, fcntl.F_SETFL, original_flags | os.O_NONBLOCK)
            selector.register(fd, selectors.EVENT_WRITE)
            while view:
                remaining_ns = deadline_ns - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise TimeoutError("native child config write timed out")
                if not selector.select(remaining_ns / 1_000_000_000):
                    raise TimeoutError("native child config write timed out")
                try:
                    written = os.write(fd, view)
                except BlockingIOError:
                    continue
                if written <= 0 or time.monotonic_ns() >= deadline_ns:
                    raise TimeoutError("native child config write timed out")
                view = view[written:]
        finally:
            selector.close()

    @staticmethod
    def _runtime_scan_sample(
        scan: Mapping[str, Any], sequence: int
    ) -> NativeRuntimeScanSample:
        mapping = {
            "scan_sequence": sequence,
            "bracket_started_monotonic_ns": scan[
                "bracket_started_monotonic_ns"
            ],
            "kernel_scan_started_monotonic_ns": scan[
                "kernel_scan_started_monotonic_ns"
            ],
            "kernel_scan_completed_monotonic_ns": scan[
                "kernel_scan_completed_monotonic_ns"
            ],
            "bracket_completed_monotonic_ns": scan[
                "bracket_completed_monotonic_ns"
            ],
            "total_region_count": scan["total_region_count"],
            "raw_kernel_inventory_sha256": scan[
                "raw_kernel_inventory_sha256"
            ],
            "full_scan_record_sha256": scan["record_sha256"],
        }
        mapping["record_sha256"] = canonical_sha256(mapping)
        return NativeRuntimeScanSample(**mapping)

    def _append_runtime_scan(
        self,
        state: dict[str, Any],
        child: KernelProcessIdentity,
    ) -> dict[str, Any]:
        if len(state["samples"]) >= MAX_NATIVE_RUNTIME_SCAN_SAMPLES:
            raise BrokerProtocolError("native runtime scan log exceeds its bound")
        scan = observe_runtime_native_scan(
            child.pid,
            child,
            self.config.native_closure,
        )
        if (
            scan["bracket_completed_monotonic_ns"]
            - scan["bracket_started_monotonic_ns"]
            > NATIVE_RUNTIME_SCAN_INTERVAL_NS
        ):
            raise BrokerProtocolError("native runtime scan exceeded its duration bound")
        initial = state.get("initial_scan")
        if initial is None:
            state["initial_scan"] = scan
            state["inventory_sha256"] = scan["raw_kernel_inventory_sha256"]
        elif scan["raw_kernel_inventory_sha256"] != state["inventory_sha256"]:
            raise BrokerProtocolError("native runtime mapped-image inventory drifted")
        sample = self._runtime_scan_sample(scan, len(state["samples"]) + 1)
        if state["samples"]:
            gap = (
                sample.bracket_started_monotonic_ns
                - state["samples"][-1].bracket_completed_monotonic_ns
            )
            if gap < 0 or gap > NATIVE_RUNTIME_SCAN_INTERVAL_NS:
                raise BrokerProtocolError("native runtime scan cadence drifted")
        state["samples"].append(sample)
        state["scan_log_bytes"] = state.get("scan_log_bytes", 0) + len(
            canonical_json_bytes(asdict(sample))
        )
        if state["scan_log_bytes"] > MAX_NATIVE_RUNTIME_SCAN_LOG_BYTES:
            raise BrokerProtocolError("native runtime scan log exceeds its byte bound")
        return scan

    @staticmethod
    def _record_terminal_waitid(
        state: dict[str, Any],
        pid: int,
        terminal: object,
    ) -> None:
        if (
            getattr(terminal, "si_pid", None) != pid
            or getattr(terminal, "si_code", None)
            not in {os.CLD_EXITED, os.CLD_KILLED, os.CLD_DUMPED}
        ):
            raise BrokerProtocolError("native child terminal WNOWAIT differs")
        observed_ns = time.monotonic_ns()
        samples = state.get("samples")
        if not isinstance(samples, list) or not samples:
            raise BrokerProtocolError("native child terminal lacks a scan")
        last_scan_ns = samples[-1].bracket_completed_monotonic_ns
        if (
            observed_ns < last_scan_ns
            or observed_ns - last_scan_ns
            > NATIVE_RUNTIME_SCAN_INTERVAL_NS
        ):
            raise BrokerProtocolError(
                "native child terminal exceeded the scan cadence"
            )
        state["terminal_waitid"] = {
            "pid": terminal.si_pid,
            "code": terminal.si_code,
            "status": terminal.si_status,
            "observed_monotonic_ns": observed_ns,
        }

    def _observe_runtime_terminal_or_scan(
        self,
        state: dict[str, Any],
        child: KernelProcessIdentity,
        *,
        scan_if_live: bool,
    ) -> bool:
        """Observe terminal state without reaping, or append one live scan.

        A direct child can exit after the first WNOWAIT peek but before libproc
        opens its process identity.  ESRCH is accepted only when a second
        exact, still-unreaped WNOWAIT observation proves that terminal state.
        Every other scan error, and ESRCH while the child remains live, is
        fatal.
        """

        terminal = os.waitid(
            os.P_PID,
            child.pid,
            os.WEXITED | os.WNOHANG | os.WNOWAIT,
        )
        if terminal is not None:
            self._record_terminal_waitid(state, child.pid, terminal)
            return True
        if not scan_if_live:
            return False
        try:
            self._append_runtime_scan(state, child)
        except OSError as error:
            if error.errno != errno.ESRCH:
                raise
            # Darwin can make libproc return ESRCH a few scheduler ticks
            # before waitid publishes the terminal event.  Distinguish that
            # bounded publication race from an unreadable *live* child: a
            # successful exact identity observation is fatal, while an absent
            # identity permits only a short wait for the still-unreaped exact
            # terminal record.
            terminal_after_esrch = None
            publication_deadline_ns = min(
                state["samples"][-1].bracket_completed_monotonic_ns
                + NATIVE_RUNTIME_SCAN_INTERVAL_NS,
                time.monotonic_ns() + 10_000_000,
            )
            while terminal_after_esrch is None:
                terminal_after_esrch = os.waitid(
                    os.P_PID,
                    child.pid,
                    os.WEXITED | os.WNOHANG | os.WNOWAIT,
                )
                if terminal_after_esrch is not None:
                    break
                try:
                    observed_identity = kernel_process_identity(child.pid)
                except ProcessLookupError:
                    observed_identity = None
                if observed_identity is not None:
                    raise BrokerProtocolError(
                        "native runtime scan lost a nonterminal child"
                    ) from error
                if time.monotonic_ns() >= publication_deadline_ns:
                    raise BrokerProtocolError(
                        "native runtime scan lost a nonterminal child; "
                        "terminal publication did not converge"
                    ) from error
                time.sleep(0.0005)
            self._record_terminal_waitid(
                state,
                child.pid,
                terminal_after_esrch,
            )
            return True
        return False

    @staticmethod
    def _wait_for_nonreaping_child_event(
        pid: int,
        *,
        expected_code: int,
        expected_status: int,
        options: int,
        deadline_ns: int,
    ) -> os.waitid_result:
        while time.monotonic_ns() < deadline_ns:
            try:
                event = os.waitid(
                    os.P_PID,
                    pid,
                    options | os.WEXITED | os.WNOHANG | os.WNOWAIT,
                )
            except ChildProcessError as exc:
                raise BrokerProtocolError(
                    "native child disappeared before gated event"
                ) from exc
            if event is None:
                time.sleep(0.001)
                continue
            if (
                event.si_pid != pid
                or event.si_code != expected_code
                or event.si_status != expected_status
            ):
                raise BrokerProtocolError(
                    "native child reached an unexpected gated state"
                )
            return event
        raise TimeoutError("native child gated event deadline expired")

    def _gate_actual_child_for_native_scan(
        self,
        child: KernelProcessIdentity,
        deadline_ns: int,
        *,
        runtime_gate_fd: int,
        runtime_gate_nonce_sha256: str,
        exec_release_e_monotonic_ns: int,
    ) -> dict[str, Any]:
        """Validate the constructor ACK and scan the self-stopped image."""

        state: dict[str, Any] = {"initial_scan": None, "samples": []}
        selector = selectors.DefaultSelector()
        selector.register(runtime_gate_fd, selectors.EVENT_READ)
        raw_ack = bytearray()
        ack_observed_ns = 0
        eof_observed_ns = 0
        try:
            while len(raw_ack) < NATIVE_RUNTIME_GATE_ACK_BYTES:
                remaining = deadline_ns - time.monotonic_ns()
                if remaining <= 0:
                    raise TimeoutError("native runtime gate ACK expired")
                if not selector.select(remaining / 1_000_000_000):
                    raise TimeoutError("native runtime gate ACK expired")
                chunk = os.read(
                    runtime_gate_fd,
                    NATIVE_RUNTIME_GATE_ACK_BYTES - len(raw_ack),
                )
                if not chunk:
                    raise BrokerProtocolError(
                        "native runtime gate ACK is truncated"
                    )
                raw_ack.extend(chunk)
            ack_observed_ns = time.monotonic_ns()
            remaining = deadline_ns - time.monotonic_ns()
            if remaining <= 0 or not selector.select(
                remaining / 1_000_000_000
            ):
                raise TimeoutError("native runtime gate EOF expired")
            if os.read(runtime_gate_fd, 1) != b"":
                raise BrokerProtocolError(
                    "native runtime gate ACK has trailing bytes"
                )
            eof_observed_ns = time.monotonic_ns()
        finally:
            selector.close()
        ack_magic = bytes(raw_ack[:8])
        ack_pid = int.from_bytes(raw_ack[8:16], "big")
        ack_c_monotonic_ns = int.from_bytes(raw_ack[16:24], "big")
        raw_nonce = bytes(raw_ack[24:56])
        observed_nonce_sha256 = hashlib.sha256(raw_nonce).hexdigest()
        raw_ack_sha256 = hashlib.sha256(raw_ack).hexdigest()
        ack_sha256 = native_runtime_gate_ack_sha256(
            pid=ack_pid,
            observed_c_monotonic_ns=ack_c_monotonic_ns,
            nonce_sha256=observed_nonce_sha256,
        )
        if (
            ack_magic != _NATIVE_RUNTIME_GATE_ACK_MAGIC
            or ack_pid != child.pid
            or ack_c_monotonic_ns <= 0
            or observed_nonce_sha256 != runtime_gate_nonce_sha256
            or exec_release_e_monotonic_ns > ack_observed_ns
            or ack_observed_ns > eof_observed_ns
            or kernel_process_identity(child.pid) != child
            or native_process_path(child.pid)
            != self.config.executable.resolved_path
        ):
            raise BrokerProtocolError("native runtime gate ACK differs")
        same_pid_exec_observed_ns = time.monotonic_ns()
        self._wait_for_nonreaping_child_event(
            child.pid,
            expected_code=os.CLD_STOPPED,
            expected_status=int(signal.SIGSTOP),
            options=os.WSTOPPED,
            deadline_ns=deadline_ns,
        )
        stop_observed_ns = time.monotonic_ns()
        if (
            kernel_process_identity(child.pid) != child
            or native_process_path(child.pid)
            != self.config.executable.resolved_path
        ):
            raise BrokerProtocolError("stopped native child identity differs")
        stopped_threads = native_detailed_thread_inventory(child.pid)
        stopped_descriptors = native_detailed_file_descriptor_inventory(
            child.pid
        )
        if (
            stopped_threads.process != child
            or stopped_threads.thread_count != 1
            or stopped_descriptors.process != child
            or tuple(item.fd for item in stopped_descriptors.descriptors)
            != (0, 1, 2)
            or any(
                item.kernel_type != 6
                or item.close_on_exec
                or item.close_on_fork
                for item in stopped_descriptors.descriptors
            )
        ):
            raise BrokerProtocolError(
                "stopped native runtime gate inventory differs"
            )
        first = self._append_runtime_scan(state, child)
        time.sleep(0.001)
        second = self._append_runtime_scan(state, child)
        if (
            first["raw_kernel_inventory_sha256"]
            != second["raw_kernel_inventory_sha256"]
        ):
            raise BrokerProtocolError("stopped native child scan is not stable")
        consumed_stop = os.waitid(os.P_PID, child.pid, os.WSTOPPED | os.WNOHANG)
        if (
            consumed_stop is None
            or consumed_stop.si_pid != child.pid
            or consumed_stop.si_code != os.CLD_STOPPED
            or consumed_stop.si_status != int(signal.SIGSTOP)
        ):
            raise BrokerProtocolError("native child stop event was not exact")
        transition: dict[str, Any] = {
            "schema_id": "parser-tesseract-runtime-gate-transition-v1",
            "pid": child.pid,
            "start_abstime": child.start_abstime,
            "native_runtime_gate_authority": NATIVE_RUNTIME_GATE_AUTHORITY,
            "native_runtime_gate_initializer_order_limitation": (
                NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION
            ),
            "native_runtime_gate_source_sha256": (
                self.config.native_runtime_gate_source.sha256
            ),
            "native_runtime_gate_library_sha256": (
                self.config.native_runtime_gate_library.sha256
            ),
            "native_runtime_gate_record_sha256": (
                self.config.native_runtime_gate["record_sha256"]
            ),
            "runtime_gate_nonce_sha256": runtime_gate_nonce_sha256,
            "runtime_gate_ack_authority": NATIVE_RUNTIME_GATE_ACK_AUTHORITY,
            "runtime_gate_ack_c_clock_authority": (
                NATIVE_RUNTIME_GATE_C_CLOCK_AUTHORITY
            ),
            "runtime_gate_ack_pid": ack_pid,
            "runtime_gate_ack_c_monotonic_ns": ack_c_monotonic_ns,
            "runtime_gate_raw_ack_hex": bytes(raw_ack).hex(),
            "runtime_gate_raw_ack_sha256": raw_ack_sha256,
            "runtime_gate_ack_sha256": ack_sha256,
            "exec_release_e_monotonic_ns": exec_release_e_monotonic_ns,
            "runtime_gate_ack_observed_monotonic_ns": ack_observed_ns,
            "runtime_gate_fd_eof_observed_monotonic_ns": eof_observed_ns,
            "same_pid_exec_observed_monotonic_ns": same_pid_exec_observed_ns,
            "constructor_stop_observed_monotonic_ns": stop_observed_ns,
            "pre_exec_ready_fd": NATIVE_RUNTIME_GATE_FD,
            "pre_exec_ready_fd_close_on_exec": True,
            "runtime_gate_fd": NATIVE_RUNTIME_GATE_FD,
            "runtime_gate_fd_inheritable_for_exec": True,
            "runtime_gate_fd_closed_before_continue": True,
            "stopped_thread_inventory": asdict(stopped_threads),
            "stopped_file_descriptor_inventory": asdict(
                stopped_descriptors
            ),
            "first_stopped_scan_sha256": first["record_sha256"],
            "second_stopped_scan_sha256": second["record_sha256"],
        }
        transition["record_sha256"] = canonical_sha256(transition)
        transition_ledger_row_sha256 = self.ledger.append(
            "child_runtime_gate", transition
        )
        continued_sent_ns = time.monotonic_ns()
        os.kill(child.pid, signal.SIGCONT)
        self._wait_for_nonreaping_child_event(
            child.pid,
            expected_code=os.CLD_CONTINUED,
            expected_status=int(signal.SIGCONT),
            options=os.WCONTINUED,
            deadline_ns=deadline_ns,
        )
        continued_observed_ns = time.monotonic_ns()
        consumed_continued = os.waitid(
            os.P_PID, child.pid, os.WCONTINUED | os.WNOHANG
        )
        if (
            consumed_continued is None
            or consumed_continued.si_pid != child.pid
            or consumed_continued.si_code != os.CLD_CONTINUED
            or consumed_continued.si_status != int(signal.SIGCONT)
        ):
            raise BrokerProtocolError("native child continue event was not exact")
        state.update(
            {
                "same_pid_exec_observed_monotonic_ns": (
                    same_pid_exec_observed_ns
                ),
                "runtime_gate_transition": transition,
                "runtime_gate_transition_ledger_row_sha256": (
                    transition_ledger_row_sha256
                ),
                "stop_observed_monotonic_ns": stop_observed_ns,
                "continued_signal_sent_monotonic_ns": continued_sent_ns,
                "continued_observed_monotonic_ns": continued_observed_ns,
                "stopped_scan_count": 2,
            }
        )
        return state

    def _capture_child(
        self,
        pid: int,
        stdin_fd: int,
        stdin_body: bytes | bytearray,
        stdout_fd: int,
        stderr_fd: int,
        deadline_ns: int,
        child: KernelProcessIdentity,
        runtime_state: dict[str, Any],
        stdout_disposition: str,
        stderr_disposition: str,
    ) -> tuple[bytearray, bytearray, int, str, int, str, bool, bool, int]:
        selector = selectors.DefaultSelector()
        streams = {
            stdout_fd: _BoundedCaptureStream(
                maximum_retained_bytes=MAX_CAPTURE_BYTES,
                disposition=stdout_disposition,
            ),
            stderr_fd: _BoundedCaptureStream(
                maximum_retained_bytes=MAX_STDERR_BYTES,
                disposition=stderr_disposition,
            ),
        }
        for descriptor in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)
        cancel_fd = self.channel.fileno
        selector.register(cancel_fd, selectors.EVENT_READ)
        cancel_registered = True
        stdin_offset = 0
        os.set_blocking(stdin_fd, False)
        if stdin_body:
            selector.register(stdin_fd, selectors.EVENT_WRITE)
        else:
            os.close(stdin_fd)
        overflowed = False
        timed_out = False
        signaled = False
        first_input_write_monotonic_ns = 0
        try:
            while selector.get_map():
                now = time.monotonic_ns()
                remaining = deadline_ns - now
                if remaining <= 0:
                    timed_out = True
                    if not signaled:
                        os.kill(pid, signal.SIGKILL)
                        signaled = True
                    remaining = 1_000_000_000
                next_scan_ns = (
                    runtime_state["samples"][-1].bracket_completed_monotonic_ns
                    + NATIVE_RUNTIME_SCAN_POLL_NS
                )
                events = selector.select(
                    max(0, min(remaining, next_scan_ns - now))
                    / 1_000_000_000
                )
                for key, _ in events:
                    if key.fd == cancel_fd:
                        selector.unregister(cancel_fd)
                        cancel_registered = False
                        if not signaled:
                            os.kill(pid, signal.SIGKILL)
                            signaled = True
                        continue
                    if key.fd == stdin_fd:
                        try:
                            write_started = time.monotonic_ns()
                            written = os.write(
                                stdin_fd,
                                stdin_body[stdin_offset : stdin_offset + 64 * 1024],
                            )
                            if written and first_input_write_monotonic_ns == 0:
                                first_input_write_monotonic_ns = write_started
                        except BrokenPipeError:
                            written = len(stdin_body) - stdin_offset
                        stdin_offset += written
                        if stdin_offset >= len(stdin_body):
                            selector.unregister(stdin_fd)
                            os.close(stdin_fd)
                        continue
                    chunk = os.read(key.fd, 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fd)
                        os.close(key.fd)
                        continue
                    stream = streams[key.fd]
                    if stream.consume(chunk):
                        overflowed = True
                        if not signaled:
                            os.kill(pid, signal.SIGKILL)
                            signaled = True
                if time.monotonic_ns() >= next_scan_ns:
                    self._observe_runtime_terminal_or_scan(
                        runtime_state,
                        child,
                        scan_if_live=True,
                    )
                if (
                    cancel_registered
                    and runtime_state.get("terminal_waitid") is not None
                ):
                    selector.unregister(cancel_fd)
                    cancel_registered = False
        finally:
            for descriptor in tuple(selector.get_map()):
                with contextlib.suppress(OSError):
                    selector.unregister(descriptor)
                    if descriptor != cancel_fd:
                        os.close(descriptor)
            selector.close()
        return (
            streams[stdout_fd].retained,
            streams[stderr_fd].retained,
            streams[stdout_fd].observed_bytes,
            streams[stdout_fd].digest.hexdigest(),
            streams[stderr_fd].observed_bytes,
            streams[stderr_fd].digest.hexdigest(),
            timed_out,
            overflowed,
            first_input_write_monotonic_ns,
        )

    def _run_child(
        self,
        operation: str,
        argv: tuple[str, ...],
        environment: dict[str, str],
        body: bytes | bytearray,
        deadline_ns: int,
        logical_argv_sha256: str,
        stderr_mode: str,
        stdout_disposition: str = "captured",
        stderr_disposition: str = "captured",
    ) -> tuple[
        BrokerChildBirth,
        BrokerChildWait4Tombstone,
        bytearray,
        bytearray,
        bool,
        bool,
    ]:
        if self.active is None:
            raise BrokerProtocolError("broker child lacks phase")
        spawn_sequence = len(self.births) + 1
        if spawn_sequence > MAX_JOBS_PER_PHASE:
            raise BrokerProtocolError("broker phase exceeds its job bound")
        # Establish sole-thread authority before touching launch configuration
        # or allocating child capabilities.  A second stable observation is
        # made with all blockable signals masked immediately before the native
        # fork, after the durable spawn intent, to close the intervening race.
        (
            broker_thread_count_before_fork,
            broker_thread_inventory_sha256,
            broker_thread_observed_at_monotonic_ns,
        ) = self._sole_thread_observation()
        reserve_child = getattr(self.ledger, "reserve_child", None)
        if callable(reserve_child):
            reserve_child(spawn_sequence)
        # Reserve the complete fixed receipt row for this child before any
        # protected transition.  The immutable phase deadline also bounds the
        # aggregate population of 50 ms live-scan rows, so a successful RUN
        # can never discover terminal-transport exhaustion only at END.
        phase_deadline = self.active.get("phase_deadline_ns")
        begin_receipt = self.active.get("begin")
        if phase_deadline is not None or begin_receipt is not None:
            if (
                not isinstance(phase_deadline, int)
                or type(begin_receipt) is not BrokerQuiescenceReceipt
            ):
                raise BrokerProtocolError(
                    "broker receipt reservation authority differs"
                )
            request_receipt_run_reservation_bytes(
                next_spawn_sequence=spawn_sequence,
                phase_started_monotonic_ns=(
                    begin_receipt.observed_at_monotonic_ns
                ),
                phase_deadline_monotonic_ns=phase_deadline,
            )
        spawn_nonce = secrets.token_hex(32)
        spawn_nonce_sha256 = hashlib.sha256(spawn_nonce.encode("ascii")).hexdigest()
        runtime_gate_nonce = secrets.token_hex(32)
        runtime_gate_nonce_sha256 = hashlib.sha256(
            bytes.fromhex(runtime_gate_nonce)
        ).hexdigest()
        logical_environment_sha256 = canonical_sha256(environment)
        actual_environment_projection: dict[str, Any] = {
            "schema_id": "parser-tesseract-actual-exec-environment-v1",
            "logical_environment": environment,
            "logical_environment_sha256": logical_environment_sha256,
            "runtime_gate_library_path": (
                self.config.native_runtime_gate_library.resolved_path
            ),
            "runtime_gate_library_sha256": (
                self.config.native_runtime_gate_library.sha256
            ),
            "runtime_gate_fd": NATIVE_RUNTIME_GATE_FD,
            "runtime_gate_nonce_sha256": runtime_gate_nonce_sha256,
            "exact_exec_environment_keys": sorted(
                (
                    *environment,
                    "DYLD_INSERT_LIBRARIES",
                    "PARSER_TESSERACT_RUNTIME_GATE_FD",
                    "PARSER_TESSERACT_RUNTIME_GATE_NONCE",
                )
            ),
            "dyld_search_or_fallback_environment_absent": True,
        }
        actual_environment_projection_sha256 = canonical_sha256(
            actual_environment_projection
        )
        # Every admitted child executes the frozen sandbox authority.  Tests
        # that exercise this private path must supply the same exact plan;
        # there is no legacy evidence grammar or production bypass.
        sandbox_enabled = True
        sandbox_representative = getattr(
            self, "child_sandbox_probe_report", None
        ) is None
        sandbox_representative_report_sha256 = (
            _ZERO_SHA256
            if sandbox_representative
            else (
                self.child_sandbox_probe_report.record_sha256
                if self.child_sandbox_probe_report is not None
                else _ZERO_SHA256
            )
        )
        ready_read, ready_write = _pipe_cloexec()
        release_read, release_write = _pipe_cloexec()
        stdout_read, stdout_write = _pipe_cloexec()
        stderr_read, stderr_write = _pipe_cloexec()
        stdin_read, stdin_write = _pipe_cloexec()
        child_config_read, child_config_write = _pipe_cloexec()
        child_state_read, child_state_write = _pipe_cloexec()
        guard_exec_error_read, guard_exec_error_write = _pipe_cloexec()
        with contextlib.ExitStack():
            try:
                child_descriptor_sources = (
                    (0, 6, "stdin_pipe", False, stdin_read),
                    (1, 6, "stdout_pipe", False, stdout_write),
                    (
                        2,
                        6,
                        "stderr_pipe",
                        False,
                        stdout_write if stderr_mode == "merge" else stderr_write,
                    ),
                    (3, 6, "ready_pipe", True, ready_write),
                    (4, 6, "release_pipe", True, release_read),
                )
                expected_child_descriptors = []
                for (
                    fd,
                    fd_type,
                    role,
                    close_on_exec,
                    source_fd,
                ) in child_descriptor_sources:
                    observed = os.fstat(source_fd)
                    expected_child_descriptors.append(
                        BrokerChildFileDescriptorIdentity(
                            fd=fd,
                            kernel_fd_type=fd_type,
                            role=role,
                            close_on_exec=close_on_exec,
                            stat_device=int(observed.st_dev),
                            stat_inode=int(observed.st_ino),
                            stat_mode=int(observed.st_mode),
                            stat_mode_type=int(stat.S_IFMT(observed.st_mode)),
                        )
                    )
                expected_child_descriptors.append(
                    BrokerChildFileDescriptorIdentity(
                        fd=5,
                        kernel_fd_type=1,
                        role="staged_executable",
                        close_on_exec=True,
                        stat_device=self.config.executable.device,
                        stat_inode=self.config.executable.inode,
                        stat_mode=self.config.executable.mode,
                        stat_mode_type=int(
                            stat.S_IFMT(self.config.executable.mode)
                        ),
                    )
                )
                expected_child_descriptors_tuple = tuple(
                    expected_child_descriptors
                )
                prepared_signal_mask = tuple(
                    sorted(
                        int(item)
                        for item in signal.pthread_sigmask(
                            signal.SIG_BLOCK, set()
                        )
                    )
                )
                prepared_signal_mask_sha256 = canonical_sha256(
                    {"signal_mask": list(prepared_signal_mask)}
                )
                # BrokerLaunchConfig captured and validated both authorities
                # before READY.  Child admission must consume those immutable
                # bytes directly; it must never re-open the mutable workspace
                # wrapper or re-resolve the interpreter during a request.
                guard_python = self.config.guard_python
                guard_wrapper_source = self.config.guard_wrapper_source
                guard_wrapper_source_sha256 = hashlib.sha256(
                    guard_wrapper_source
                ).hexdigest()
                if (
                    guard_wrapper_source_sha256
                    != self.config.child_wrapper_sha256
                    or len(guard_wrapper_source) > 256 * 1024
                ):
                    raise BrokerProtocolError(
                        "embedded child guard source differs"
                    )
                guard_wrapper_delivery_basis = (
                    "execve-python-c-embedded-source-v1"
                )
                sandbox_guard_kwargs: dict[str, Any] = {}
                if sandbox_enabled:
                    sandbox_guard_kwargs = {
                        "sandbox_executor_source": (
                            self.config.child_sandbox_probe_executor_source
                        ),
                        "sandbox_executor_source_sha256": (
                            self.config.child_sandbox_probe_executor_source_sha256
                        ),
                        "sandbox_executor_authority": (
                            CHILD_SANDBOX_EXECUTOR_AUTHORITY
                        ),
                    }
                guard_argv = embedded_guard_argv(
                    python_path=guard_python.resolved_path,
                    source=guard_wrapper_source,
                    source_sha256=guard_wrapper_source_sha256,
                    config_fd=child_config_read,
                    ready_fd=ready_write,
                    **sandbox_guard_kwargs,
                )
                guard_exec_argv_sha256 = canonical_sha256(
                    {"argv": list(guard_argv)}
                )
                guard_environment = {"LANG": "C", "LC_ALL": "C"}
                guard_exec_environment_sha256 = canonical_sha256(
                    guard_environment
                )
                guard_path_custody = getattr(
                    self.config, "guard_python_path_custody", None
                )
                if guard_path_custody is None:
                    guard_path_custody = derive_guard_python_path_custody(
                        guard_python.resolved_path
                    )
                guard_python_path_custody_sha256 = guard_path_custody[
                    "record_sha256"
                ]
                guard_python_native_closure_sha256 = getattr(
                    self.config,
                    "guard_python_native_closure_sha256",
                    None,
                )
                if guard_python_native_closure_sha256 is None:
                    guard_python_native_closure_sha256 = (
                        derive_native_closure(
                            guard_python.resolved_path,
                            guard_python.resolved_path,
                        )["closure_sha256"]
                    )
                guard_python_module_tree = getattr(
                    self.config,
                    "guard_python_module_tree_custody",
                    None,
                )
                if guard_python_module_tree is None:
                    guard_python_module_tree = (
                        derive_guard_python_module_tree_custody(
                            str(Path(guard_python.resolved_path).parents[1])
                        )
                    )
                child_config: dict[str, Any] = {
                    "schema_id": NATIVE_CHILD_CONFIG_SCHEMA,
                    "attempt_nonce_sha256": hashlib.sha256(
                        getattr(
                            self.config, "attempt_nonce", "f" * 64
                        ).encode("ascii")
                    ).hexdigest(),
                    "scope_sha256": getattr(
                        self.config, "scope_sha256", "e" * 64
                    ),
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "spawn_sequence": spawn_sequence,
                    "spawn_nonce_sha256": spawn_nonce_sha256,
                    "broker_pid": self.identity.pid,
                    "broker_start_abstime": self.identity.start_abstime,
                    "broker_pgid": self.identity.pgid,
                    "broker_sid": self.identity.sid,
                    "config_fd": child_config_read,
                    "native_state_fd": child_state_read,
                    "ready_fd": ready_write,
                    "release_fd": release_read,
                    "stdin_fd": stdin_read,
                    "stdout_fd": stdout_write,
                    "stderr_fd": (
                        stdout_write
                        if stderr_mode == "merge"
                        else stderr_write
                    ),
                    "executable": self.config.executable.resolved_path,
                    "expected_executable_sha256": (
                        self.config.executable.sha256
                    ),
                    "expected_executable_device": (
                        self.config.executable.device
                    ),
                    "expected_executable_inode": (
                        self.config.executable.inode
                    ),
                    "argv": list(argv),
                    "environment": environment,
                    "native_spawn_guard_sha256": (
                        self.config.native_spawn_guard.sha256
                    ),
                    "previous_signal_mask": list(prepared_signal_mask),
                    "previous_signal_mask_sha256": (
                        prepared_signal_mask_sha256
                    ),
                    "runtime_gate_library": (
                        self.config.native_runtime_gate_library.resolved_path
                    ),
                    "runtime_gate_library_sha256": (
                        self.config.native_runtime_gate_library.sha256
                    ),
                    "runtime_gate_library_device": (
                        self.config.native_runtime_gate_library.device
                    ),
                    "runtime_gate_library_inode": (
                        self.config.native_runtime_gate_library.inode
                    ),
                    "runtime_gate_nonce": runtime_gate_nonce,
                    "guard_python_path": guard_python.resolved_path,
                    "guard_python_sha256": guard_python.sha256,
                    "guard_python_device": guard_python.device,
                    "guard_python_inode": guard_python.inode,
                    "guard_python_path_custody_sha256": (
                        guard_python_path_custody_sha256
                    ),
                    "guard_python_native_closure_sha256": (
                        guard_python_native_closure_sha256
                    ),
                    "guard_python_module_tree_root": (
                        guard_python_module_tree["resolved_root"]
                    ),
                    "guard_python_module_tree_sha256": (
                        guard_python_module_tree["record_sha256"]
                    ),
                    "guard_wrapper_sha256": guard_wrapper_source_sha256,
                    "guard_wrapper_delivery_basis": (
                        guard_wrapper_delivery_basis
                    ),
                    "guard_exec_argv_sha256": guard_exec_argv_sha256,
                    "guard_exec_environment_sha256": (
                        guard_exec_environment_sha256
                    ),
                }
                if sandbox_enabled:
                    child_config.update(
                        {
                            "child_sandbox_probe_mode": (
                                "representative-full-matrix"
                                if sandbox_representative
                                else "inherited-profile-commitment"
                            ),
                            "child_sandbox_probe_executor_authority": (
                                CHILD_SANDBOX_EXECUTOR_AUTHORITY
                            ),
                            "child_sandbox_probe_executor_source_sha256": (
                                self.config.child_sandbox_probe_executor_source_sha256
                            ),
                            "child_sandbox_probe_plan": (
                                self.config.child_sandbox_probe_plan
                            ),
                            "child_sandbox_probe_report_reservation_bytes": (
                                self.config.child_sandbox_probe_report_reservation_bytes
                            ),
                            "child_sandbox_probe_representative_report_sha256": (
                                sandbox_representative_report_sha256
                            ),
                        }
                    )
                child_config["config_sha256"] = canonical_sha256(
                    child_config
                )
                native_child_config_projection = {
                    key: value
                    for key, value in child_config.items()
                    if key
                    not in {"schema_id", "runtime_gate_nonce", "config_sha256"}
                }
                native_child_config_projection.update(
                    {
                        "schema_id": (
                            "parser-tesseract-native-child-config-projection-v1"
                        ),
                        "runtime_gate_nonce_sha256": (
                            runtime_gate_nonce_sha256
                        ),
                        "native_child_config_sha256": child_config[
                            "config_sha256"
                        ],
                    }
                )
                native_child_config_projection_sha256 = canonical_sha256(
                    native_child_config_projection
                )
                child_config_bytes = canonical_json_bytes(child_config)
                if len(child_config_bytes) > MAX_NATIVE_CHILD_CONFIG_BYTES:
                    raise BrokerProtocolError(
                        "native child config exceeds its bound"
                    )
                inherited_guard_fd_set = {
                    child_config_read,
                    child_state_read,
                    ready_write,
                    release_read,
                    stdin_read,
                    stdout_write,
                    stderr_write,
                }
                if sandbox_representative:
                    inherited_guard_fd_set.update(
                        authority["descriptor"]
                        for authority in self.config.child_sandbox_probe_plan[
                            "held_directories"
                        ]
                    )
                inherited_guard_fds = tuple(
                    sorted(
                        inherited_guard_fd_set
                    )
                )
                if (
                    sandbox_enabled
                    and len(inherited_guard_fds)
                    != (16 if sandbox_representative else 7)
                ) or len(inherited_guard_fds) > 16:
                    raise BrokerProtocolError(
                        "native child inherited capability bound differs"
                    )
                spawn_intent_created_monotonic_ns = time.monotonic_ns()
                spawn_intent: dict[str, Any] = {
                    "schema_id": "parser-tesseract-spawn-intent-v1",
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "spawn_sequence": spawn_sequence,
                    "spawn_nonce_sha256": spawn_nonce_sha256,
                    "runtime_gate_nonce_sha256": (
                        runtime_gate_nonce_sha256
                    ),
                    "native_runtime_gate_record_sha256": (
                        self.config.native_runtime_gate["record_sha256"]
                    ),
                    "logical_environment_sha256": (
                        logical_environment_sha256
                    ),
                    "actual_environment_projection_sha256": (
                        actual_environment_projection_sha256
                    ),
                    "native_child_config_sha256": child_config[
                        "config_sha256"
                    ],
                    "native_child_config_projection_sha256": (
                        native_child_config_projection_sha256
                    ),
                    "guard_python_sha256": guard_python.sha256,
                    "guard_python_path_custody_sha256": (
                        guard_python_path_custody_sha256
                    ),
                    "guard_python_native_closure_sha256": (
                        guard_python_native_closure_sha256
                    ),
                    "guard_python_module_tree_sha256": (
                        guard_python_module_tree["record_sha256"]
                    ),
                    "guard_wrapper_sha256": (
                        guard_wrapper_source_sha256
                    ),
                    "guard_wrapper_delivery_basis": (
                        guard_wrapper_delivery_basis
                    ),
                    "guard_exec_argv_sha256": guard_exec_argv_sha256,
                    "guard_exec_environment_sha256": (
                        guard_exec_environment_sha256
                    ),
                    "broker_pid": self.identity.pid,
                    "broker_start_abstime": self.identity.start_abstime,
                    "broker_pgid": self.identity.pgid,
                    "broker_sid": self.identity.sid,
                    "child_deadline_monotonic_ns": deadline_ns,
                    "broker_thread_count_before_fork": (
                        broker_thread_count_before_fork
                    ),
                    "broker_thread_inventory_sha256": (
                        broker_thread_inventory_sha256
                    ),
                    "broker_thread_observed_at_monotonic_ns": (
                        broker_thread_observed_at_monotonic_ns
                    ),
                    "intent_created_monotonic_ns": (
                        spawn_intent_created_monotonic_ns
                    ),
                }
                spawn_intent["spawn_intent_sha256"] = canonical_sha256(
                    spawn_intent
                )
                spawn_intent_ledger_row_sha256 = self.ledger.append(
                    "spawn_intent", spawn_intent
                )
                spawn_intent_durable_acknowledged_monotonic_ns = (
                    time.monotonic_ns()
                )
            except BaseException:
                # A raced/persistent extra broker thread is detected before
                # fork.  Close every pipe allocated for the rejected intent so
                # repeated adversarial probes cannot exhaust broker FDs.
                for descriptor in (
                    ready_read,
                    ready_write,
                    release_read,
                    release_write,
                    stdout_read,
                    stdout_write,
                    stderr_read,
                    stderr_write,
                    stdin_read,
                    stdin_write,
                    child_config_read,
                    child_config_write,
                    child_state_read,
                    child_state_write,
                    guard_exec_error_read,
                    guard_exec_error_write,
                ):
                    if descriptor >= 0:
                        with contextlib.suppress(OSError):
                            os.close(descriptor)
                raise
            blockable_signals = _blockable_signal_numbers()
            blockable_signal_set = set(blockable_signals)
            pid = -1
            previous_signal_mask: set[signal.Signals] | None = None
            try:
                previous_signal_mask = signal.pthread_sigmask(
                    signal.SIG_BLOCK,
                    blockable_signal_set,
                )
                previous_signal_mask_tuple = tuple(
                    sorted(int(item) for item in previous_signal_mask)
                )
                previous_signal_mask_sha256 = canonical_sha256(
                    {"signal_mask": list(previous_signal_mask_tuple)}
                )
                if (
                    previous_signal_mask_tuple != prepared_signal_mask
                    or previous_signal_mask_sha256
                    != prepared_signal_mask_sha256
                ):
                    raise BrokerProtocolError(
                        "native child prepared signal mask changed"
                    )
                observed_signal_mask = signal.pthread_sigmask(
                    signal.SIG_BLOCK,
                    set(),
                )
                if not blockable_signal_set.issubset(observed_signal_mask):
                    raise BrokerProtocolError(
                        "blockable signals were not masked before fork"
                    )
                (
                    broker_thread_count_immediately_before_fork,
                    broker_thread_inventory_immediately_before_fork_sha256,
                    broker_thread_immediately_before_fork_observed_at_monotonic_ns,
                ) = self._sole_thread_observation()
                if (
                    broker_thread_count_immediately_before_fork != 1
                    or broker_thread_inventory_immediately_before_fork_sha256
                    != broker_thread_inventory_sha256
                ):
                    raise BrokerProtocolError(
                        "broker thread authority changed before fork"
                    )
                blocked_signals_across_fork_sha256 = canonical_sha256(
                    {"blocked_signals": list(blockable_signals)}
                )
                born_ns = time.monotonic_ns()
                (
                    pid,
                    native_child_limit_applied_monotonic_ns,
                    native_child_limit_ack_sha256_value,
                    native_fork_parent_returned_monotonic_ns,
                    native_child_limit_acknowledged_monotonic_ns,
                ) = self._spawn_child_with_native_denial(
                    release_read,
                    deadline_ns,
                    child_state_ack_fd=child_state_write,
                    guard_exec_error_fd=guard_exec_error_write,
                    guard_argv=guard_argv,
                    guard_environment=guard_environment,
                    inherited_guard_fds=inherited_guard_fds,
                )
                child_state_write = -1
                guard_exec_error_write = -1
                if pid > 0:
                    signal.pthread_sigmask(
                        signal.SIG_SETMASK,
                        previous_signal_mask,
                    )
            except BaseException:
                if pid == 0:
                    os._exit(125)
                if previous_signal_mask is not None:
                    with contextlib.suppress(OSError):
                        signal.pthread_sigmask(
                            signal.SIG_SETMASK,
                            previous_signal_mask,
                        )
                if pid > 0:
                    with contextlib.suppress(OSError):
                        os.close(release_write)
                    self._reap_unregistered_native_child(pid, deadline_ns)
                for descriptor in (
                    ready_read,
                    ready_write,
                    release_read,
                    release_write,
                    stdout_read,
                    stdout_write,
                    stderr_read,
                    stderr_write,
                    stdin_read,
                    stdin_write,
                    child_config_read,
                    child_config_write,
                    child_state_read,
                    child_state_write,
                    guard_exec_error_read,
                    guard_exec_error_write,
                ):
                    if descriptor >= 0:
                        with contextlib.suppress(OSError):
                            os.close(descriptor)
                raise
            for descriptor in (
                ready_write,
                release_read,
                stdout_write,
                stderr_write,
                stdin_read,
                child_config_read,
                child_state_read,
            ):
                if descriptor >= 0:
                    os.close(descriptor)
            child_reaped = False
            try:
                child = kernel_process_identity(pid)
                if (
                    child.ppid != self.identity.pid
                    or child.pgid != self.identity.pid
                    or child.sid != self.identity.pid
                    or time.monotonic_ns() >= deadline_ns
                ):
                    raise BrokerProtocolError(
                        "provisional child identity differs"
                    )
                provisional_observed_monotonic_ns = time.monotonic_ns()
                provisional_child: dict[str, Any] = {
                    "schema_id": "parser-tesseract-child-provisional-v1",
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "spawn_sequence": spawn_sequence,
                    "spawn_nonce_sha256": spawn_nonce_sha256,
                    "pid": child.pid,
                    "start_abstime": child.start_abstime,
                    "ppid": child.ppid,
                    "pgid": child.pgid,
                    "sid": child.sid,
                    "spawn_intent_sha256": spawn_intent[
                        "spawn_intent_sha256"
                    ],
                    "spawn_intent_ledger_row_sha256": (
                        spawn_intent_ledger_row_sha256
                    ),
                    "broker_thread_count_immediately_before_fork": (
                        broker_thread_count_immediately_before_fork
                    ),
                    "broker_thread_inventory_immediately_before_fork_sha256": (
                        broker_thread_inventory_immediately_before_fork_sha256
                    ),
                    "broker_thread_immediately_before_fork_observed_at_monotonic_ns": (
                        broker_thread_immediately_before_fork_observed_at_monotonic_ns
                    ),
                    "born_monotonic_ns": born_ns,
                    "blocked_signals_across_fork": list(blockable_signals),
                    "blocked_signals_across_fork_sha256": (
                        blocked_signals_across_fork_sha256
                    ),
                    "blockable_signals_masked_across_fork": True,
                    "native_child_limit_ack_authority": (
                        NATIVE_CHILD_LIMIT_ACK_AUTHORITY
                    ),
                    "native_child_limit_applied_clock_authority": (
                        NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
                    ),
                    "native_child_limit_ack_pid": pid,
                    "native_child_limit_applied_monotonic_ns": (
                        native_child_limit_applied_monotonic_ns
                    ),
                    "native_child_limit_ack_sha256": (
                        native_child_limit_ack_sha256_value
                    ),
                    "native_fork_parent_returned_monotonic_ns": (
                        native_fork_parent_returned_monotonic_ns
                    ),
                    "native_child_limit_acknowledged_monotonic_ns": (
                        native_child_limit_acknowledged_monotonic_ns
                    ),
                    "provisional_observed_monotonic_ns": (
                        provisional_observed_monotonic_ns
                    ),
                }
                provisional_child["provisional_record_sha256"] = (
                    canonical_sha256(provisional_child)
                )
                provisional_child_ledger_row_sha256 = self.ledger.append(
                    "child_provisional", provisional_child
                )
                (
                    watchdog_registration_sha256,
                    watchdog_registration_ack_sha256,
                    registration_acknowledged_monotonic_ns,
                ) = self._watchdog_register_child(
                    child=child,
                    spawn_sequence=spawn_sequence,
                    spawn_nonce_sha256=spawn_nonce_sha256,
                    child_deadline_ns=deadline_ns,
                    provisional_child_ledger_row_sha256=(
                        provisional_child_ledger_row_sha256
                    ),
                    spawn_intent_sha256=spawn_intent[
                        "spawn_intent_sha256"
                    ],
                    spawn_intent_ledger_row_sha256=(
                        spawn_intent_ledger_row_sha256
                    ),
                    native_child_limit_applied_monotonic_ns=(
                        native_child_limit_applied_monotonic_ns
                    ),
                    native_child_limit_ack_sha256_value=(
                        native_child_limit_ack_sha256_value
                    ),
                    native_fork_parent_returned_monotonic_ns=(
                        native_fork_parent_returned_monotonic_ns
                    ),
                    native_child_limit_acknowledged_monotonic_ns=(
                        native_child_limit_acknowledged_monotonic_ns
                    ),
                )
                native_python_release_n_monotonic_ns = time.monotonic_ns()
                if os.write(release_write, b"N") != 1:
                    raise BrokerProtocolError(
                        "native child Python-release gate write failed"
                    )
                self._write_child_config(
                    child_config_write,
                    child_config_bytes,
                    deadline_ns,
                )
                os.close(child_config_write)
                child_config_write = -1
                if sandbox_representative:
                    sandbox_report_mapping = self._read_child_line(
                        ready_read,
                        deadline_ns,
                        guard_exec_error_fd=guard_exec_error_read,
                        maximum_bytes=(
                            self.config.child_sandbox_probe_report_reservation_bytes
                            + 1
                        ),
                    )
                    sandbox_report = child_sandbox_probe_report_from_mapping(
                        sandbox_report_mapping
                    )
                    plan = self.config.child_sandbox_probe_plan
                    validate_child_sandbox_probe_report_against_plan(
                        sandbox_report,
                        plan,
                    )
                    report_process = sandbox_report.process
                    if (
                        sandbox_report.attempt_id != plan["attempt_id"]
                        or sandbox_report.attempt_nonce_sha256
                        != plan["attempt_nonce_sha256"]
                        or sandbox_report.scope_sha256 != self.config.scope_sha256
                        or sandbox_report.request_id != self.active["request_id"]
                        or sandbox_report.request_epoch
                        != self.active["request_epoch"]
                        or sandbox_report.request_sequence
                        != self.active["request_sequence"]
                        or sandbox_report.spawn_sequence != spawn_sequence
                        or sandbox_report.spawn_nonce_sha256
                        != spawn_nonce_sha256
                        or sandbox_report.profile_sha256
                        != self.config.broker_profile_sha256
                        or sandbox_report.native_closure_sha256
                        != plan["native_closure_sha256"]
                        or sandbox_report.plan_sha256 != plan["plan_sha256"]
                        or sandbox_report.executor_source_sha256
                        != self.config.child_sandbox_probe_executor_source_sha256
                        or sandbox_report.probe_library_sha256
                        != plan["probe_library_sha256"]
                        or sandbox_report.broker_pid != self.identity.pid
                        or sandbox_report.broker_start_abstime
                        != self.identity.start_abstime
                        or sandbox_report.native_child_limit_ack_sha256
                        != native_child_limit_ack_sha256_value
                        or sandbox_report.report_reservation_bytes
                        != self.config.child_sandbox_probe_report_reservation_bytes
                        or tuple(
                            report_process[name]
                            for name in ("pid", "start_abstime", "ppid", "pgid", "sid")
                        )
                        != (
                            child.pid,
                            child.start_abstime,
                            child.ppid,
                            child.pgid,
                            child.sid,
                        )
                    ):
                        raise BrokerProtocolError(
                            "child sandbox representative report binding differs"
                        )
                    sandbox_report_ledger_row_sha256 = self.ledger.append(
                        "child_sandbox_probe",
                        dataclass_mapping(sandbox_report),
                    )
                    self.child_sandbox_probe_report = sandbox_report
                    self.child_sandbox_probe_report_ledger_row_sha256 = (
                        sandbox_report_ledger_row_sha256
                    )
                child_ready = self._read_child_line(
                    ready_read,
                    deadline_ns,
                    guard_exec_error_fd=(
                        None
                        if sandbox_representative
                        else guard_exec_error_read
                    ),
                )
                child_guard_ready_observed_monotonic_ns = time.monotonic_ns()
                os.close(guard_exec_error_read)
                guard_exec_error_read = -1
                required_ready = {
                    "schema_id", "pid", "ppid", "pgid", "sid", "real_uid", "effective_uid",
                    "rlimit_nproc_soft", "rlimit_nproc_hard", "guard_applied_at_monotonic_ns",
                    "guard_applied_clock_authority",
                    "guard_sha256", "open_fd_count", "executable_sha256", "executable_device",
                    "executable_inode", "record_sha256",
                    "term_hup_unblocked",
                    "open_file_descriptors", "open_fd_inventory_sha256",
                    "native_thread_count", "native_thread_ids",
                    "native_thread_inventory_sha256",
                    "native_spawn_guard_sha256", "native_spawn_guard_kind",
                    "guard_python_sha256",
                    "guard_python_path_custody_sha256",
                    "guard_python_native_closure_sha256",
                    "guard_python_module_tree_sha256",
                    "guard_python_path_exec_trust_model",
                    "guard_python_path_exec_containment_claim",
                    "guard_wrapper_delivery_basis",
                    "guard_exec_argv_sha256",
                    "guard_exec_environment_sha256",
                    "guard_post_exec_environment_sha256",
                    "native_child_config_sha256",
                    "native_child_limit_ack_authority",
                    "native_child_limit_applied_clock_authority",
                    "native_child_limit_ack_pid",
                    "native_child_limit_ack_sha256",
                    "native_child_limit_applied_monotonic_ns",
                    "hard_limit_installed_before_python_return",
                    "pthread_atfork_callbacks_bypassed",
                    "prior_signal_mask", "prior_signal_mask_sha256",
                    "restored_signal_mask", "restored_signal_mask_sha256",
                    "exact_prior_signal_mask_restored_before_ready",
                }
                if sandbox_enabled:
                    required_ready.update(
                        {
                            "child_sandbox_probe_mode",
                            "child_sandbox_probe_plan_sha256",
                            "child_sandbox_probe_executor_authority",
                            "child_sandbox_probe_executor_source_sha256",
                            "child_sandbox_probe_library_sha256",
                            "child_sandbox_probe_report_sha256",
                            "child_sandbox_probe_report_reservation_bytes",
                        }
                    )
                if set(child_ready) != required_ready or child_ready["schema_id"] != CHILD_READY_SCHEMA:
                    raise BrokerProtocolError("child READY fields differ")
                child_ready_sha = child_ready.pop("record_sha256")
                if child_ready_sha != canonical_sha256(child_ready):
                    raise BrokerProtocolError("child READY digest differs")
                raw_descriptors = child_ready["open_file_descriptors"]
                if not isinstance(raw_descriptors, list):
                    raise BrokerProtocolError(
                        "child READY descriptor inventory differs"
                    )
                try:
                    child_descriptors = tuple(
                        BrokerChildFileDescriptorIdentity(**descriptor)
                        for descriptor in raw_descriptors
                        if isinstance(descriptor, dict)
                    )
                except TypeError as exc:
                    raise BrokerProtocolError(
                        "child READY descriptor identity differs"
                    ) from exc
                raw_thread_ids = child_ready["native_thread_ids"]
                raw_prior_signal_mask = child_ready["prior_signal_mask"]
                raw_restored_signal_mask = child_ready[
                    "restored_signal_mask"
                ]
                if (
                    len(child_descriptors) != len(raw_descriptors)
                    or child_descriptors != expected_child_descriptors_tuple
                    or child_ready["open_fd_count"] != len(child_descriptors)
                    or child_ready["open_fd_inventory_sha256"]
                    != canonical_sha256(
                        {
                            "open_file_descriptors": [
                                asdict(descriptor)
                                for descriptor in child_descriptors
                            ]
                        }
                    )
                    or not isinstance(raw_thread_ids, list)
                    or len(raw_thread_ids) != 1
                    or any(
                        isinstance(thread_id, bool)
                        or not isinstance(thread_id, int)
                        or thread_id <= 0
                        for thread_id in raw_thread_ids
                    )
                    or child_ready["native_thread_count"] != len(raw_thread_ids)
                    or child_ready["native_thread_inventory_sha256"]
                    != canonical_sha256(
                        {"native_thread_ids": raw_thread_ids}
                    )
                    != canonical_sha256({"native_thread_ids": raw_thread_ids})
                ):
                    raise BrokerProtocolError(
                        "child READY kernel inventory differs"
                    )
                if (
                    child.pid != child_ready["pid"]
                    or child.ppid != child_ready["ppid"]
                    or child.pgid != child_ready["pgid"]
                    or child.sid != child_ready["sid"]
                    or child.ppid != self.identity.pid
                    or child.pgid != self.identity.pid
                    or child.sid != self.identity.pid
                    or (child_ready["rlimit_nproc_soft"], child_ready["rlimit_nproc_hard"]) != (0, 0)
                    or child_ready["real_uid"] == 0
                    or child_ready["effective_uid"] == 0
                    or child_ready["guard_sha256"] != self.config.child_wrapper_sha256
                    or child_ready["open_fd_count"] != 6
                    or child_ready["executable_sha256"] != self.config.executable.sha256
                    or child_ready["executable_device"] != self.config.executable.device
                    or child_ready["executable_inode"] != self.config.executable.inode
                    or child_ready["term_hup_unblocked"] is not True
                    or child_ready["native_spawn_guard_sha256"]
                    != self.config.native_spawn_guard.sha256
                    or child_ready["native_spawn_guard_kind"]
                    != "darwin-__fork-child-nproc0-before-python-v1"
                    or child_ready["guard_applied_clock_authority"]
                    != "clt-python39-time-monotonic-clock-monotonic-v1"
                    or child_ready["guard_python_sha256"]
                    != guard_python.sha256
                    or child_ready["guard_python_path_custody_sha256"]
                    != guard_python_path_custody_sha256
                    or child_ready["guard_python_native_closure_sha256"]
                    != guard_python_native_closure_sha256
                    or child_ready["guard_python_module_tree_sha256"]
                    != guard_python_module_tree["record_sha256"]
                    or child_ready["guard_python_path_exec_trust_model"]
                    != "root-owned-pinned-clt-python-native-closure-v1"
                    or child_ready[
                        "guard_python_path_exec_containment_claim"
                    ]
                    != "none-trusted-host-path-exec"
                    or child_ready["guard_wrapper_delivery_basis"]
                    != guard_wrapper_delivery_basis
                    or child_ready["guard_exec_argv_sha256"]
                    != guard_exec_argv_sha256
                    or child_ready["guard_exec_environment_sha256"]
                    != guard_exec_environment_sha256
                    or child_ready["guard_post_exec_environment_sha256"]
                    != canonical_sha256(
                        {
                            **guard_environment,
                            "__CF_USER_TEXT_ENCODING": (
                                f"0x{os.geteuid():X}:0x0:0x0"
                            ),
                        }
                    )
                    or child_ready["native_child_config_sha256"]
                    != child_config["config_sha256"]
                    or child_ready["native_child_limit_ack_authority"]
                    != NATIVE_CHILD_LIMIT_ACK_AUTHORITY
                    or child_ready[
                        "native_child_limit_applied_clock_authority"
                    ]
                    != NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
                    or child_ready["native_child_limit_ack_pid"] != pid
                    or child_ready["native_child_limit_ack_sha256"]
                    != native_child_limit_ack_sha256_value
                    or child_ready[
                        "native_child_limit_applied_monotonic_ns"
                    ]
                    <= 0
                    or child_ready[
                        "native_child_limit_applied_monotonic_ns"
                    ]
                    != native_child_limit_applied_monotonic_ns
                    or native_child_limit_ack_sha256_value
                    != native_child_limit_ack_sha256(
                        pid=pid,
                        applied_monotonic_ns=(
                            native_child_limit_applied_monotonic_ns
                        ),
                    )
                    or born_ns > native_fork_parent_returned_monotonic_ns
                    or native_fork_parent_returned_monotonic_ns
                    > native_child_limit_acknowledged_monotonic_ns
                    or native_child_limit_acknowledged_monotonic_ns
                    > provisional_observed_monotonic_ns
                    or child_ready[
                        "hard_limit_installed_before_python_return"
                    ]
                    is not True
                    or child_ready["pthread_atfork_callbacks_bypassed"]
                    is not True
                    or not isinstance(raw_prior_signal_mask, list)
                    or raw_prior_signal_mask
                    != list(previous_signal_mask_tuple)
                    or child_ready["prior_signal_mask_sha256"]
                    != previous_signal_mask_sha256
                    or not isinstance(raw_restored_signal_mask, list)
                    or raw_restored_signal_mask != raw_prior_signal_mask
                    or child_ready["restored_signal_mask_sha256"]
                    != previous_signal_mask_sha256
                    or child_ready[
                        "exact_prior_signal_mask_restored_before_ready"
                    ]
                    is not True
                ):
                    raise BrokerProtocolError(
                        "child gated identity differs: "
                        + repr(
                            {
                                "kernel": asdict(child),
                                "ready": {
                                    key: child_ready[key]
                                    for key in (
                                        "pid",
                                        "ppid",
                                        "pgid",
                                        "sid",
                                        "real_uid",
                                        "effective_uid",
                                        "rlimit_nproc_soft",
                                        "rlimit_nproc_hard",
                                        "guard_sha256",
                                        "open_fd_count",
                                        "executable_sha256",
                                        "executable_device",
                                        "executable_inode",
                                        "term_hup_unblocked",
                                        "native_spawn_guard_sha256",
                                        "native_spawn_guard_kind",
                                        "native_child_limit_ack_authority",
                                        "native_child_limit_applied_clock_authority",
                                        "native_child_limit_ack_pid",
                                        "native_child_limit_ack_sha256",
                                        "native_child_limit_applied_monotonic_ns",
                                        "hard_limit_installed_before_python_return",
                                        "pthread_atfork_callbacks_bypassed",
                                        "prior_signal_mask",
                                        "prior_signal_mask_sha256",
                                        "restored_signal_mask",
                                        "restored_signal_mask_sha256",
                                        "exact_prior_signal_mask_restored_before_ready",
                                    )
                                },
                                "broker_identity": asdict(self.identity),
                                "expected_child_wrapper_sha256": (
                                    self.config.child_wrapper_sha256
                                ),
                                "expected_executable": asdict(
                                    self.config.executable
                                ),
                                "expected_native_spawn_guard": asdict(
                                    self.config.native_spawn_guard
                                ),
                                "expected_previous_signal_mask": list(
                                    previous_signal_mask_tuple
                                ),
                                "expected_previous_signal_mask_sha256": (
                                    previous_signal_mask_sha256
                                ),
                                "expected_native_child_limit_applied_monotonic_ns": (
                                    native_child_limit_applied_monotonic_ns
                                ),
                                "expected_native_child_limit_ack_sha256": (
                                    native_child_limit_ack_sha256_value
                                ),
                                "born_ns": born_ns,
                                "native_fork_parent_returned_monotonic_ns": (
                                    native_fork_parent_returned_monotonic_ns
                                ),
                                "native_child_limit_acknowledged_monotonic_ns": (
                                    native_child_limit_acknowledged_monotonic_ns
                                ),
                                "provisional_observed_monotonic_ns": (
                                    provisional_observed_monotonic_ns
                                ),
                            }
                        )
                    )
                if sandbox_enabled:
                    expected_sandbox_mode = (
                        "representative-full-matrix"
                        if sandbox_representative
                        else "inherited-profile-commitment"
                    )
                    if (
                        self.child_sandbox_probe_report is None
                        or self.child_sandbox_probe_report_ledger_row_sha256
                        is None
                        or child_ready["child_sandbox_probe_mode"]
                        != expected_sandbox_mode
                        or child_ready["child_sandbox_probe_plan_sha256"]
                        != self.config.child_sandbox_probe_plan["plan_sha256"]
                        or child_ready[
                            "child_sandbox_probe_executor_authority"
                        ]
                        != CHILD_SANDBOX_EXECUTOR_AUTHORITY
                        or child_ready[
                            "child_sandbox_probe_executor_source_sha256"
                        ]
                        != self.config.child_sandbox_probe_executor_source_sha256
                        or child_ready["child_sandbox_probe_library_sha256"]
                        != self.config.child_sandbox_probe_plan[
                            "probe_library_sha256"
                        ]
                        or child_ready["child_sandbox_probe_report_sha256"]
                        != self.child_sandbox_probe_report.record_sha256
                        or child_ready[
                            "child_sandbox_probe_report_reservation_bytes"
                        ]
                        != self.config.child_sandbox_probe_report_reservation_bytes
                    ):
                        raise BrokerProtocolError(
                            "child READY sandbox inheritance differs"
                        )
                intent = {
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "spawn_sequence": spawn_sequence,
                    "spawn_nonce_sha256": spawn_nonce_sha256,
                    "pid": pid,
                    "start_abstime": child.start_abstime,
                    "child_ready_sha256": child_ready_sha,
                    "spawn_intent_sha256": spawn_intent[
                        "spawn_intent_sha256"
                    ],
                    "spawn_intent_ledger_row_sha256": (
                        spawn_intent_ledger_row_sha256
                    ),
                    "provisional_child_ledger_row_sha256": (
                        provisional_child_ledger_row_sha256
                    ),
                    "provisional_record_sha256": provisional_child[
                        "provisional_record_sha256"
                    ],
                    "watchdog_registration_sha256": (
                        watchdog_registration_sha256
                    ),
                    "watchdog_registration_ack_sha256": (
                        watchdog_registration_ack_sha256
                    ),
                }
                child_ready_intent_ledger_row_sha256 = self.ledger.append(
                    "child_intent", intent
                )
                os.write(release_write, b"A")
                child_release = self._read_child_line(ready_read, deadline_ns)
                guard_release_a_observed_monotonic_ns = time.monotonic_ns()
                required_release = {"schema_id", "pid", "released_monotonic_ns", "ready_record_sha256", "record_sha256"}
                if set(child_release) != required_release or child_release["schema_id"] != "parser-tesseract-child-release-v1":
                    raise BrokerProtocolError("child release fields differ")
                release_sha = child_release.pop("record_sha256")
                if (
                    release_sha != canonical_sha256(child_release)
                    or child_release["pid"] != pid
                    or child_release["ready_record_sha256"] != child_ready_sha
                ):
                    raise BrokerProtocolError("child release binding differs")
                child_reported_guard_release_a_monotonic_ns = _positive_int(
                    child_release["released_monotonic_ns"],
                    "child-reported guard release A monotonic value",
                )
                record_sequence = len(self.births) + len(self.tombstones) + 1
                previous_record = (
                    self.tombstones[-1].record_sha256
                    if self.tombstones
                    else self.previous_receipt_sha256
                )
                fork_denial_mapping = {
                    "platform": "darwin",
                    "profile_sha256": self.config.broker_profile_sha256,
                    "wrapper_sha256": self.config.child_wrapper_sha256,
                    "native_spawn_guard_sha256": (
                        self.config.native_spawn_guard.sha256
                    ),
                    "native_spawn_guard_source_sha256": (
                        self.config.native_spawn_guard_source_sha256
                    ),
                    "native_spawn_guard_kind": (
                        "darwin-__fork-child-nproc0-before-python-v1"
                    ),
                    "guard_python_sha256": child_ready[
                        "guard_python_sha256"
                    ],
                    "guard_python_path_custody_sha256": child_ready[
                        "guard_python_path_custody_sha256"
                    ],
                    "guard_python_native_closure_sha256": child_ready[
                        "guard_python_native_closure_sha256"
                    ],
                    "guard_python_module_tree_sha256": child_ready[
                        "guard_python_module_tree_sha256"
                    ],
                    "guard_python_path_exec_trust_model": child_ready[
                        "guard_python_path_exec_trust_model"
                    ],
                    "guard_python_path_exec_containment_claim": child_ready[
                        "guard_python_path_exec_containment_claim"
                    ],
                    "guard_wrapper_delivery_basis": child_ready[
                        "guard_wrapper_delivery_basis"
                    ],
                    "guard_exec_argv_sha256": child_ready[
                        "guard_exec_argv_sha256"
                    ],
                    "guard_exec_environment_sha256": child_ready[
                        "guard_exec_environment_sha256"
                    ],
                    "guard_post_exec_environment_sha256": child_ready[
                        "guard_post_exec_environment_sha256"
                    ],
                    "native_child_config_sha256": child_ready[
                        "native_child_config_sha256"
                    ],
                    "rlimit_nproc_soft": 0,
                    "rlimit_nproc_hard": 0,
                    "real_uid": child_ready["real_uid"],
                    "effective_uid": child_ready["effective_uid"],
                    "applied_at_monotonic_ns": child_ready["guard_applied_at_monotonic_ns"],
                    "child_guard_applied_clock_authority": child_ready[
                        "guard_applied_clock_authority"
                    ],
                    "child_reported_guard_release_a_monotonic_ns": (
                        child_reported_guard_release_a_monotonic_ns
                    ),
                    "child_guard_release_a_record_sha256": release_sha,
                    "child_guard_ready_observed_monotonic_ns": (
                        child_guard_ready_observed_monotonic_ns
                    ),
                    "native_child_limit_applied_monotonic_ns": child_ready[
                        "native_child_limit_applied_monotonic_ns"
                    ],
                    "native_child_limit_ack_authority": (
                        NATIVE_CHILD_LIMIT_ACK_AUTHORITY
                    ),
                    "native_child_limit_applied_clock_authority": (
                        NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
                    ),
                    "native_child_limit_ack_pid": pid,
                    "native_child_limit_ack_sha256": (
                        native_child_limit_ack_sha256_value
                    ),
                    "native_fork_parent_returned_monotonic_ns": (
                        native_fork_parent_returned_monotonic_ns
                    ),
                    "native_child_limit_acknowledged_monotonic_ns": (
                        native_child_limit_acknowledged_monotonic_ns
                    ),
                    "native_python_release_n_monotonic_ns": (
                        native_python_release_n_monotonic_ns
                    ),
                    "hard_limit_installed_before_python_return": True,
                    "pthread_atfork_callbacks_bypassed": True,
                    "native_python_release_n_monotonic_ns": (
                        native_python_release_n_monotonic_ns
                    ),
                    "prior_signal_mask": raw_prior_signal_mask,
                    "prior_signal_mask_sha256": previous_signal_mask_sha256,
                    "restored_signal_mask": raw_restored_signal_mask,
                    "restored_signal_mask_sha256": (
                        previous_signal_mask_sha256
                    ),
                    "exact_prior_signal_mask_restored_before_ready": True,
                    "prior_signal_mask": tuple(raw_prior_signal_mask),
                    "prior_signal_mask_sha256": previous_signal_mask_sha256,
                    "restored_signal_mask": tuple(raw_restored_signal_mask),
                    "restored_signal_mask_sha256": previous_signal_mask_sha256,
                    "exact_prior_signal_mask_restored_before_ready": True,
                    "ready_record_sha256": child_ready_sha,
                }
                fork_denial = BrokerForkDenialIdentity(**fork_denial_mapping)
                logical_argv_digest = logical_argv_sha256
                actual_argv_digest = canonical_sha256({"argv": list(argv)})
                birth_commitment: dict[str, Any] = {
                    "schema_id": "parser-tesseract-child-birth-commitment-v1",
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "spawn_sequence": spawn_sequence,
                    "spawn_nonce_sha256": spawn_nonce_sha256,
                    "pid": pid,
                    "start_abstime": child.start_abstime,
                    "ppid": child.ppid,
                    "pgid": child.pgid,
                    "sid": child.sid,
                    "broker_pid": self.identity.pid,
                    "broker_start_abstime": self.identity.start_abstime,
                    "operation": operation,
                    "logical_argv_sha256": logical_argv_digest,
                    "actual_argv_sha256": actual_argv_digest,
                    "logical_environment_sha256": (
                        logical_environment_sha256
                    ),
                    "actual_environment_projection_sha256": (
                        actual_environment_projection_sha256
                    ),
                    "input_sha256": hashlib.sha256(body).hexdigest(),
                    "input_bytes": len(body),
                    "executable_sha256": self.config.executable.sha256,
                    "native_closure_sha256": self.config.native_closure_sha256,
                    "native_trust_model": NATIVE_CLOSURE_TRUST_MODEL,
                    "native_containment_claim": (
                        "none-trusted-pinned-native-computation"
                    ),
                    "native_runtime_attestation_required": True,
                    "native_runtime_scan_interval_ns": (
                        NATIVE_RUNTIME_SCAN_INTERVAL_NS
                    ),
                    "native_runtime_gate_authority": (
                        NATIVE_RUNTIME_GATE_AUTHORITY
                    ),
                    "native_runtime_gate_initializer_order_limitation": (
                        NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION
                    ),
                    "native_runtime_gate_source_sha256": (
                        self.config.native_runtime_gate_source.sha256
                    ),
                    "native_runtime_gate_library_sha256": (
                        self.config.native_runtime_gate_library.sha256
                    ),
                    "native_runtime_gate_record_sha256": (
                        self.config.native_runtime_gate["record_sha256"]
                    ),
                    "runtime_gate_nonce_sha256": (
                        runtime_gate_nonce_sha256
                    ),
                    "runtime_gate_ack_authority": (
                        NATIVE_RUNTIME_GATE_ACK_AUTHORITY
                    ),
                    "watchdog_registration_sha256": watchdog_registration_sha256,
                    "watchdog_registration_ack_sha256": (
                        watchdog_registration_ack_sha256
                    ),
                    "broker_thread_count_before_fork": (
                        broker_thread_count_before_fork
                    ),
                    "broker_thread_inventory_sha256": (
                        broker_thread_inventory_sha256
                    ),
                    "broker_thread_observed_at_monotonic_ns": (
                        broker_thread_observed_at_monotonic_ns
                    ),
                    "broker_thread_count_immediately_before_fork": (
                        broker_thread_count_immediately_before_fork
                    ),
                    "broker_thread_inventory_immediately_before_fork_sha256": (
                        broker_thread_inventory_immediately_before_fork_sha256
                    ),
                    "broker_thread_immediately_before_fork_observed_at_monotonic_ns": (
                        broker_thread_immediately_before_fork_observed_at_monotonic_ns
                    ),
                    "born_monotonic_ns": born_ns,
                    "blocked_signals_across_fork": list(blockable_signals),
                    "blocked_signals_across_fork_sha256": (
                        blocked_signals_across_fork_sha256
                    ),
                    "blockable_signals_masked_across_fork": True,
                    "registration_acknowledged_monotonic_ns": (
                        registration_acknowledged_monotonic_ns
                    ),
                    "guard_release_a_monotonic_ns": (
                        guard_release_a_observed_monotonic_ns
                    ),
                    "spawn_intent_sha256": spawn_intent[
                        "spawn_intent_sha256"
                    ],
                    "spawn_intent_ledger_row_sha256": (
                        spawn_intent_ledger_row_sha256
                    ),
                    "spawn_intent_durable_acknowledged_monotonic_ns": (
                        spawn_intent_durable_acknowledged_monotonic_ns
                    ),
                    "provisional_record_sha256": provisional_child[
                        "provisional_record_sha256"
                    ],
                    "provisional_child_ledger_row_sha256": (
                        provisional_child_ledger_row_sha256
                    ),
                    "provisional_observed_monotonic_ns": (
                        provisional_observed_monotonic_ns
                    ),
                    "child_ready_sha256": child_ready_sha,
                    "child_ready_intent_ledger_row_sha256": (
                        child_ready_intent_ledger_row_sha256
                    ),
                    "open_fd_count": child_ready["open_fd_count"],
                    "open_file_descriptors": [
                        asdict(descriptor) for descriptor in child_descriptors
                    ],
                    "open_fd_inventory_sha256": child_ready[
                        "open_fd_inventory_sha256"
                    ],
                    "native_thread_count": child_ready["native_thread_count"],
                    "native_thread_ids": raw_thread_ids,
                    "native_thread_inventory_sha256": child_ready[
                        "native_thread_inventory_sha256"
                    ],
                    "native_spawn_guard_sha256": child_ready[
                        "native_spawn_guard_sha256"
                    ],
                    "native_spawn_guard_source_sha256": (
                        self.config.native_spawn_guard_source_sha256
                    ),
                    "native_spawn_guard_kind": child_ready[
                        "native_spawn_guard_kind"
                    ],
                    "guard_python_sha256": child_ready[
                        "guard_python_sha256"
                    ],
                    "guard_python_path_custody_sha256": child_ready[
                        "guard_python_path_custody_sha256"
                    ],
                    "guard_python_native_closure_sha256": child_ready[
                        "guard_python_native_closure_sha256"
                    ],
                    "guard_python_module_tree_sha256": child_ready[
                        "guard_python_module_tree_sha256"
                    ],
                    "guard_python_path_exec_trust_model": child_ready[
                        "guard_python_path_exec_trust_model"
                    ],
                    "guard_python_path_exec_containment_claim": child_ready[
                        "guard_python_path_exec_containment_claim"
                    ],
                    "guard_wrapper_delivery_basis": child_ready[
                        "guard_wrapper_delivery_basis"
                    ],
                    "guard_config_fd": child_config_read,
                    "guard_ready_fd": ready_write,
                    "guard_exec_argv_sha256": child_ready[
                        "guard_exec_argv_sha256"
                    ],
                    "guard_exec_environment_sha256": child_ready[
                        "guard_exec_environment_sha256"
                    ],
                    "guard_post_exec_environment_sha256": child_ready[
                        "guard_post_exec_environment_sha256"
                    ],
                    "native_child_config_sha256": child_ready[
                        "native_child_config_sha256"
                    ],
                    "native_child_config_projection": (
                        native_child_config_projection
                    ),
                    "native_child_config_projection_sha256": (
                        native_child_config_projection_sha256
                    ),
                    "child_sandbox_probe_mode": child_ready[
                        "child_sandbox_probe_mode"
                    ],
                    "child_sandbox_probe_plan_sha256": child_ready[
                        "child_sandbox_probe_plan_sha256"
                    ],
                    "child_sandbox_probe_executor_authority": child_ready[
                        "child_sandbox_probe_executor_authority"
                    ],
                    "child_sandbox_probe_executor_source_sha256": child_ready[
                        "child_sandbox_probe_executor_source_sha256"
                    ],
                    "child_sandbox_probe_library_sha256": child_ready[
                        "child_sandbox_probe_library_sha256"
                    ],
                    "child_sandbox_probe_representative_report_sha256": (
                        child_ready["child_sandbox_probe_report_sha256"]
                    ),
                    "child_sandbox_probe_report_ledger_row_sha256": (
                        self.child_sandbox_probe_report_ledger_row_sha256
                    ),
                    "child_sandbox_probe_report_reservation_bytes": child_ready[
                        "child_sandbox_probe_report_reservation_bytes"
                    ],
                    "native_child_limit_applied_monotonic_ns": child_ready[
                        "native_child_limit_applied_monotonic_ns"
                    ],
                    "native_child_limit_ack_authority": (
                        NATIVE_CHILD_LIMIT_ACK_AUTHORITY
                    ),
                    "native_child_limit_applied_clock_authority": (
                        NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
                    ),
                    "native_child_limit_ack_pid": pid,
                    "native_child_limit_ack_sha256": (
                        native_child_limit_ack_sha256_value
                    ),
                    "native_fork_parent_returned_monotonic_ns": (
                        native_fork_parent_returned_monotonic_ns
                    ),
                    "native_child_limit_acknowledged_monotonic_ns": (
                        native_child_limit_acknowledged_monotonic_ns
                    ),
                    "native_python_release_n_monotonic_ns": (
                        native_python_release_n_monotonic_ns
                    ),
                    "child_guard_applied_at_monotonic_ns": child_ready[
                        "guard_applied_at_monotonic_ns"
                    ],
                    "child_guard_applied_clock_authority": child_ready[
                        "guard_applied_clock_authority"
                    ],
                    "child_reported_guard_release_a_monotonic_ns": (
                        child_reported_guard_release_a_monotonic_ns
                    ),
                    "child_guard_release_a_record_sha256": release_sha,
                    "child_guard_ready_observed_monotonic_ns": (
                        child_guard_ready_observed_monotonic_ns
                    ),
                    "hard_limit_installed_before_python_return": True,
                    "pthread_atfork_callbacks_bypassed": True,
                    "prior_signal_mask": raw_prior_signal_mask,
                    "prior_signal_mask_sha256": previous_signal_mask_sha256,
                    "restored_signal_mask": raw_restored_signal_mask,
                    "restored_signal_mask_sha256": previous_signal_mask_sha256,
                    "exact_prior_signal_mask_restored_before_ready": True,
                }
                birth_commitment["birth_commitment_sha256"] = canonical_sha256(
                    birth_commitment
                )
                birth_commitment_model = child_birth_commitment_from_mapping(
                    birth_commitment
                )
                birth_commitment = asdict(birth_commitment_model)
                birth_ledger_sha256 = self.ledger.append(
                    "child_birth", birth_commitment
                )
                (
                    watchdog_birth_sha256,
                    watchdog_birth_ack_sha256,
                    birth_durable_acknowledged_monotonic_ns,
                ) = self._watchdog_bind_birth(
                    birth_commitment,
                    birth_ledger_row_sha256=birth_ledger_sha256,
                )
                os.write(release_write, b"E")
                exec_release_e_monotonic_ns = time.monotonic_ns()
                exec_release_record = {
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "spawn_sequence": spawn_sequence,
                    "spawn_nonce_sha256": spawn_nonce_sha256,
                    "pid": pid,
                    "start_abstime": child.start_abstime,
                    "birth_commitment_sha256": birth_commitment[
                        "birth_commitment_sha256"
                    ],
                    "watchdog_birth_ack_sha256": watchdog_birth_ack_sha256,
                    "exec_release_e_monotonic_ns": exec_release_e_monotonic_ns,
                }
                exec_release_ledger_row_sha256 = self.ledger.append(
                    "child_exec_release", exec_release_record
                )
                birth_mapping: dict[str, Any] = {
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "spawn_sequence": spawn_sequence,
                    "spawn_nonce_sha256": spawn_nonce_sha256,
                    "record_sequence": record_sequence,
                    "previous_record_sha256": previous_record,
                    "pid": pid,
                    "start_abstime": child.start_abstime,
                    "ppid": child.ppid,
                    "pgid": child.pgid,
                    "sid": child.sid,
                    "broker_pid": self.identity.pid,
                    "broker_start_abstime": self.identity.start_abstime,
                    "identity_basis": "direct-parent-unreaped-spawn-token-v1",
                    "born_monotonic_ns": born_ns,
                    "spawn_intent_sha256": spawn_intent[
                        "spawn_intent_sha256"
                    ],
                    "spawn_intent_ledger_row_sha256": (
                        spawn_intent_ledger_row_sha256
                    ),
                    "spawn_intent_durable_acknowledged_monotonic_ns": (
                        spawn_intent_durable_acknowledged_monotonic_ns
                    ),
                    "provisional_record_sha256": provisional_child[
                        "provisional_record_sha256"
                    ],
                    "provisional_child_ledger_row_sha256": (
                        provisional_child_ledger_row_sha256
                    ),
                    "provisional_observed_monotonic_ns": (
                        provisional_observed_monotonic_ns
                    ),
                    "child_ready_sha256": child_ready_sha,
                    "child_ready_intent_ledger_row_sha256": (
                        child_ready_intent_ledger_row_sha256
                    ),
                    "open_fd_count": child_ready["open_fd_count"],
                    "open_file_descriptors": [
                        asdict(descriptor) for descriptor in child_descriptors
                    ],
                    "open_fd_inventory_sha256": child_ready[
                        "open_fd_inventory_sha256"
                    ],
                    "native_thread_count": child_ready["native_thread_count"],
                    "native_thread_ids": raw_thread_ids,
                    "native_thread_inventory_sha256": child_ready[
                        "native_thread_inventory_sha256"
                    ],
                    "broker_thread_count_before_fork": (
                        broker_thread_count_before_fork
                    ),
                    "broker_thread_inventory_sha256": (
                        broker_thread_inventory_sha256
                    ),
                    "broker_thread_observed_at_monotonic_ns": (
                        broker_thread_observed_at_monotonic_ns
                    ),
                    "broker_thread_count_immediately_before_fork": (
                        broker_thread_count_immediately_before_fork
                    ),
                    "broker_thread_inventory_immediately_before_fork_sha256": (
                        broker_thread_inventory_immediately_before_fork_sha256
                    ),
                    "broker_thread_immediately_before_fork_observed_at_monotonic_ns": (
                        broker_thread_immediately_before_fork_observed_at_monotonic_ns
                    ),
                    "blocked_signals_across_fork": list(blockable_signals),
                    "blocked_signals_across_fork_sha256": (
                        blocked_signals_across_fork_sha256
                    ),
                    "blockable_signals_masked_across_fork": True,
                    "registration_acknowledged_monotonic_ns": (
                        registration_acknowledged_monotonic_ns
                    ),
                    "guard_release_a_monotonic_ns": (
                        guard_release_a_observed_monotonic_ns
                    ),
                    "child_reported_guard_release_a_monotonic_ns": (
                        child_reported_guard_release_a_monotonic_ns
                    ),
                    "child_guard_release_a_record_sha256": release_sha,
                    "birth_durable_acknowledged_monotonic_ns": (
                        birth_durable_acknowledged_monotonic_ns
                    ),
                    "exec_release_e_monotonic_ns": exec_release_e_monotonic_ns,
                    "operation": operation,
                    "logical_argv_sha256": logical_argv_digest,
                    "actual_argv_sha256": actual_argv_digest,
                    "logical_environment_sha256": (
                        logical_environment_sha256
                    ),
                    "actual_environment_projection_sha256": (
                        actual_environment_projection_sha256
                    ),
                    "input_sha256": hashlib.sha256(body).hexdigest(),
                    "input_bytes": len(body),
                    "executable": asdict(self.config.executable),
                    "native_closure_sha256": self.config.native_closure_sha256,
                    "native_trust_model": NATIVE_CLOSURE_TRUST_MODEL,
                    "native_containment_claim": (
                        "none-trusted-pinned-native-computation"
                    ),
                    "native_runtime_attestation_required": True,
                    "native_runtime_scan_interval_ns": (
                        NATIVE_RUNTIME_SCAN_INTERVAL_NS
                    ),
                    "native_runtime_gate_authority": (
                        NATIVE_RUNTIME_GATE_AUTHORITY
                    ),
                    "native_runtime_gate_initializer_order_limitation": (
                        NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION
                    ),
                    "native_runtime_gate_source_sha256": (
                        self.config.native_runtime_gate_source.sha256
                    ),
                    "native_runtime_gate_library_sha256": (
                        self.config.native_runtime_gate_library.sha256
                    ),
                    "native_runtime_gate_record_sha256": (
                        self.config.native_runtime_gate["record_sha256"]
                    ),
                    "runtime_gate_nonce_sha256": runtime_gate_nonce_sha256,
                    "runtime_gate_ack_authority": (
                        NATIVE_RUNTIME_GATE_ACK_AUTHORITY
                    ),
                    "guard_python_sha256": child_ready[
                        "guard_python_sha256"
                    ],
                    "guard_python_path_custody_sha256": child_ready[
                        "guard_python_path_custody_sha256"
                    ],
                    "guard_python_native_closure_sha256": child_ready[
                        "guard_python_native_closure_sha256"
                    ],
                    "guard_python_module_tree_sha256": child_ready[
                        "guard_python_module_tree_sha256"
                    ],
                    "guard_python_path_exec_trust_model": child_ready[
                        "guard_python_path_exec_trust_model"
                    ],
                    "guard_python_path_exec_containment_claim": child_ready[
                        "guard_python_path_exec_containment_claim"
                    ],
                    "guard_wrapper_delivery_basis": child_ready[
                        "guard_wrapper_delivery_basis"
                    ],
                    "guard_config_fd": child_config_read,
                    "guard_ready_fd": ready_write,
                    "guard_exec_argv_sha256": child_ready[
                        "guard_exec_argv_sha256"
                    ],
                    "guard_exec_environment_sha256": child_ready[
                        "guard_exec_environment_sha256"
                    ],
                    "guard_post_exec_environment_sha256": child_ready[
                        "guard_post_exec_environment_sha256"
                    ],
                    "native_child_config_sha256": child_ready[
                        "native_child_config_sha256"
                    ],
                    "native_child_config_projection": (
                        native_child_config_projection
                    ),
                    "native_child_config_projection_sha256": (
                        native_child_config_projection_sha256
                    ),
                    "child_sandbox_probe_mode": child_ready[
                        "child_sandbox_probe_mode"
                    ],
                    "child_sandbox_probe_plan_sha256": child_ready[
                        "child_sandbox_probe_plan_sha256"
                    ],
                    "child_sandbox_probe_executor_authority": child_ready[
                        "child_sandbox_probe_executor_authority"
                    ],
                    "child_sandbox_probe_executor_source_sha256": child_ready[
                        "child_sandbox_probe_executor_source_sha256"
                    ],
                    "child_sandbox_probe_library_sha256": child_ready[
                        "child_sandbox_probe_library_sha256"
                    ],
                    "child_sandbox_probe_representative_report_sha256": (
                        child_ready["child_sandbox_probe_report_sha256"]
                    ),
                    "child_sandbox_probe_report_ledger_row_sha256": (
                        self.child_sandbox_probe_report_ledger_row_sha256
                    ),
                    "child_sandbox_probe_report_reservation_bytes": child_ready[
                        "child_sandbox_probe_report_reservation_bytes"
                    ],
                    "fork_denial": asdict(fork_denial),
                    "child_reported_identity_matched": True,
                    "registration_durable_before_guard_release_a": True,
                    "birth_durable_before_exec_release_e": True,
                    "pre_exec_gate_closed_before_custody": True,
                    "hard_nproc_zero_before_exec": True,
                    "watchdog_registration_sha256": watchdog_registration_sha256,
                    "watchdog_registration_ack_sha256": (
                        watchdog_registration_ack_sha256
                    ),
                    "birth_commitment_sha256": birth_commitment[
                        "birth_commitment_sha256"
                    ],
                    "birth_ledger_row_sha256": birth_ledger_sha256,
                    "watchdog_birth_sha256": watchdog_birth_sha256,
                    "watchdog_birth_ack_sha256": watchdog_birth_ack_sha256,
                    "exec_release_ledger_row_sha256": (
                        exec_release_ledger_row_sha256
                    ),
                }
                birth_mapping["record_sha256"] = canonical_sha256(birth_mapping)
                birth = BrokerChildBirth(
                    **{
                        **birth_mapping,
                        "executable": self.config.executable,
                        "fork_denial": fork_denial,
                        "open_file_descriptors": child_descriptors,
                        "native_thread_ids": tuple(raw_thread_ids),
                        "blocked_signals_across_fork": blockable_signals,
                    }
                )
                os.close(release_write)
                runtime_state = self._gate_actual_child_for_native_scan(
                    child,
                    deadline_ns,
                    runtime_gate_fd=ready_read,
                    runtime_gate_nonce_sha256=(
                        runtime_gate_nonce_sha256
                    ),
                    exec_release_e_monotonic_ns=(
                        exec_release_e_monotonic_ns
                    ),
                )
                os.close(ready_read)
                (
                    stdout,
                    stderr,
                    stdout_observed_bytes,
                    stdout_observed_sha256,
                    stderr_observed_bytes,
                    stderr_observed_sha256,
                    timed_out,
                    overflowed,
                    first_input_write_monotonic_ns,
                ) = self._capture_child(
                    pid=pid,
                    stdin_fd=stdin_write,
                    stdin_body=body,
                    stdout_fd=stdout_read,
                    stderr_fd=stderr_read,
                    deadline_ns=deadline_ns,
                    child=child,
                    runtime_state=runtime_state,
                    stdout_disposition=stdout_disposition,
                    stderr_disposition=stderr_disposition,
                )
                terminal_waitid = runtime_state.get("terminal_waitid")
                while terminal_waitid is None:
                    scan_due = (
                        time.monotonic_ns()
                        >= runtime_state["samples"][-1].bracket_completed_monotonic_ns
                        + NATIVE_RUNTIME_SCAN_POLL_NS
                    )
                    self._observe_runtime_terminal_or_scan(
                        runtime_state,
                        child,
                        scan_if_live=scan_due,
                    )
                    terminal_waitid = runtime_state.get("terminal_waitid")
                    if terminal_waitid is not None:
                        break
                    if time.monotonic_ns() >= deadline_ns:
                        with contextlib.suppress(ProcessLookupError):
                            os.kill(pid, signal.SIGKILL)
                    time.sleep(0.001)
                wait_result = None
                nonreaping_wait4_probe_count = 0
                wait4_deadline_ns = min(
                    deadline_ns,
                    self.config.attempt_deadline_ns,
                )
                while wait_result is None:
                    candidate_wait_result = native_wait4_exact(
                        pid,
                        absolute_deadline_ns=wait4_deadline_ns,
                    )
                    if candidate_wait_result is None:
                        nonreaping_wait4_probe_count += 1
                        time.sleep(0.001)
                    else:
                        # From this exact instruction onward the direct child
                        # has been reaped and its numeric PID is reusable.  No
                        # later validation/ledger failure may signal or wait
                        # that number again.
                        wait_result = candidate_wait_result
                        child_reaped = True
                observed_wait_ns = time.monotonic_ns()
                terminal_nonreaping_observed_ns = terminal_waitid[
                    "observed_monotonic_ns"
                ]
                waitid_matches_wait4 = (
                    terminal_waitid["code"] == os.CLD_EXITED
                    and os.WIFEXITED(wait_result.raw_status)
                    and terminal_waitid["status"]
                    == os.WEXITSTATUS(wait_result.raw_status)
                ) or (
                    terminal_waitid["code"] in {os.CLD_KILLED, os.CLD_DUMPED}
                    and os.WIFSIGNALED(wait_result.raw_status)
                    and terminal_waitid["status"]
                    == os.WTERMSIG(wait_result.raw_status)
                )
                if (
                    not waitid_matches_wait4
                    or observed_wait_ns >= wait4_deadline_ns
                    or terminal_nonreaping_observed_ns > observed_wait_ns
                    or runtime_state["continued_observed_monotonic_ns"]
                    > terminal_nonreaping_observed_ns
                    or
                    terminal_nonreaping_observed_ns
                    - runtime_state["samples"][-1].bracket_completed_monotonic_ns
                    > NATIVE_RUNTIME_SCAN_INTERVAL_NS
                ):
                    raise BrokerProtocolError(
                        "native runtime sampling did not reach child terminality"
                    )
                post_wait_closure = validate_native_closure(
                    self.config.native_closure
                )
                if (
                    post_wait_closure["closure_sha256"]
                    != self.config.native_closure_sha256
                ):
                    raise BrokerProtocolError(
                        "native closure changed after child wait4"
                    )
                runtime_samples = tuple(runtime_state["samples"])
                scan_gaps = [
                    current.bracket_started_monotonic_ns
                    - previous.bracket_completed_monotonic_ns
                    for previous, current in zip(
                        runtime_samples,
                        runtime_samples[1:],
                    )
                ]
                operation_family_sha256 = canonical_sha256(
                    {
                        "operation": operation,
                        "logical_argv_sha256": logical_argv_digest,
                        "actual_argv_sha256": actual_argv_digest,
                        "logical_environment_sha256": (
                            logical_environment_sha256
                        ),
                        "actual_environment_projection_sha256": (
                            actual_environment_projection_sha256
                        ),
                        "tessdata_sha256": self.config.tessdata_sha256,
                        "native_closure_sha256": (
                            self.config.native_closure_sha256
                        ),
                    }
                )
                guard_to_exec_transition_sha256 = canonical_sha256(
                    {
                        "schema_id": (
                            "parser-tesseract-guard-to-exec-transition-v1"
                        ),
                        "pid": birth.pid,
                        "start_abstime": birth.start_abstime,
                        "child_ready_sha256": birth.child_ready_sha256,
                        "native_child_config_sha256": (
                            birth.native_child_config_sha256
                        ),
                        "native_child_config_projection_sha256": (
                            birth.native_child_config_projection_sha256
                        ),
                        "native_child_limit_ack_sha256": (
                            birth.fork_denial.native_child_limit_ack_sha256
                        ),
                        "birth_record_sha256": birth.record_sha256,
                        "exec_release_e_monotonic_ns": (
                            birth.exec_release_e_monotonic_ns
                        ),
                        "runtime_gate_transition_sha256": runtime_state[
                            "runtime_gate_transition"
                        ]["record_sha256"],
                        "first_stopped_scan_sha256": runtime_samples[
                            0
                        ].full_scan_record_sha256,
                        "terminal_waitid_code": terminal_waitid["code"],
                        "terminal_waitid_status": terminal_waitid["status"],
                        "terminal_nonreaping_observed_monotonic_ns": (
                            terminal_nonreaping_observed_ns
                        ),
                        "exact_wait4_observed_monotonic_ns": observed_wait_ns,
                        "raw_wait_status": wait_result.raw_status,
                    }
                )
                runtime_attestation_mapping: dict[str, Any] = {
                    "schema_id": (
                        "parser-tesseract-native-runtime-attestation-v1"
                    ),
                    "authority": NATIVE_RUNTIME_SCAN_AUTHORITY,
                    "operation": operation,
                    "operation_family_sha256": operation_family_sha256,
                    "logical_environment_sha256": (
                        logical_environment_sha256
                    ),
                    "actual_environment_projection": (
                        actual_environment_projection
                    ),
                    "actual_environment_projection_sha256": (
                        actual_environment_projection_sha256
                    ),
                    "native_closure_sha256": (
                        self.config.native_closure_sha256
                    ),
                    "expected_non_system_image_count": runtime_state[
                        "initial_scan"
                    ]["expected_non_system_image_count"],
                    "expected_non_system_projection_sha256": runtime_state[
                        "initial_scan"
                    ]["expected_non_system_projection_sha256"],
                    "observed_non_system_image_count": runtime_state[
                        "initial_scan"
                    ]["observed_non_system_image_count"],
                    "observed_non_system_projection_sha256": runtime_state[
                        "initial_scan"
                    ]["observed_non_system_projection_sha256"],
                    "system_cache_sha256": runtime_state["initial_scan"][
                        "system_cache_sha256"
                    ],
                    "dynamic_loader_imports_sha256": self.config.native_closure[
                        "dynamic_loader_imports_sha256"
                    ],
                    "dynamic_loader_importing_image_count": self.config.native_closure[
                        "dynamic_loader_importing_image_count"
                    ],
                    "native_trust_model": NATIVE_CLOSURE_TRUST_MODEL,
                    "native_containment_claim": (
                        "none-trusted-pinned-native-computation"
                    ),
                    **{
                        name: getattr(birth, name)
                        for name in (
                            "child_sandbox_probe_mode",
                            "child_sandbox_probe_plan_sha256",
                            "child_sandbox_probe_executor_authority",
                            "child_sandbox_probe_executor_source_sha256",
                            "child_sandbox_probe_library_sha256",
                            "child_sandbox_probe_representative_report_sha256",
                            "child_sandbox_probe_report_ledger_row_sha256",
                            "child_sandbox_probe_report_reservation_bytes",
                        )
                    },
                    "polling_completeness": (
                        NATIVE_RUNTIME_POLLING_COMPLETENESS
                    ),
                    "scan_interval_limit_ns": (
                        NATIVE_RUNTIME_SCAN_INTERVAL_NS
                    ),
                    "native_runtime_gate_authority": (
                        NATIVE_RUNTIME_GATE_AUTHORITY
                    ),
                    "native_runtime_gate_initializer_order_limitation": (
                        NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION
                    ),
                    "native_runtime_gate_source_sha256": (
                        self.config.native_runtime_gate_source.sha256
                    ),
                    "native_runtime_gate_library_sha256": (
                        self.config.native_runtime_gate_library.sha256
                    ),
                    "native_runtime_gate_record_sha256": (
                        self.config.native_runtime_gate["record_sha256"]
                    ),
                    "runtime_gate_nonce_sha256": (
                        runtime_gate_nonce_sha256
                    ),
                    "runtime_gate_ack_authority": (
                        NATIVE_RUNTIME_GATE_ACK_AUTHORITY
                    ),
                    "runtime_gate_ack_c_clock_authority": (
                        NATIVE_RUNTIME_GATE_C_CLOCK_AUTHORITY
                    ),
                    "runtime_gate_ack_pid": runtime_state[
                        "runtime_gate_transition"
                    ]["runtime_gate_ack_pid"],
                    "runtime_gate_ack_c_monotonic_ns": runtime_state[
                        "runtime_gate_transition"
                    ]["runtime_gate_ack_c_monotonic_ns"],
                    "runtime_gate_raw_ack_hex": runtime_state[
                        "runtime_gate_transition"
                    ]["runtime_gate_raw_ack_hex"],
                    "runtime_gate_raw_ack_sha256": runtime_state[
                        "runtime_gate_transition"
                    ]["runtime_gate_raw_ack_sha256"],
                    "runtime_gate_ack_sha256": runtime_state[
                        "runtime_gate_transition"
                    ]["runtime_gate_ack_sha256"],
                    "exec_release_e_monotonic_ns": (
                        exec_release_e_monotonic_ns
                    ),
                    "runtime_gate_ack_observed_monotonic_ns": runtime_state[
                        "runtime_gate_transition"
                    ]["runtime_gate_ack_observed_monotonic_ns"],
                    "runtime_gate_fd_eof_observed_monotonic_ns": runtime_state[
                        "runtime_gate_transition"
                    ]["runtime_gate_fd_eof_observed_monotonic_ns"],
                    "same_pid_exec_observed_monotonic_ns": runtime_state[
                        "same_pid_exec_observed_monotonic_ns"
                    ],
                    "constructor_stop_observed_monotonic_ns": runtime_state[
                        "stop_observed_monotonic_ns"
                    ],
                    "stopped_signal_number": int(signal.SIGSTOP),
                    "stopped_thread_inventory": runtime_state[
                        "runtime_gate_transition"
                    ]["stopped_thread_inventory"],
                    "stopped_file_descriptor_inventory": runtime_state[
                        "runtime_gate_transition"
                    ]["stopped_file_descriptor_inventory"],
                    "runtime_gate_transition_sha256": runtime_state[
                        "runtime_gate_transition"
                    ]["record_sha256"],
                    "runtime_gate_transition_ledger_row_sha256": runtime_state[
                        "runtime_gate_transition_ledger_row_sha256"
                    ],
                    "guard_to_exec_transition_sha256": (
                        guard_to_exec_transition_sha256
                    ),
                    "continued_signal_sent_monotonic_ns": runtime_state[
                        "continued_signal_sent_monotonic_ns"
                    ],
                    "continued_observed_monotonic_ns": runtime_state[
                        "continued_observed_monotonic_ns"
                    ],
                    "actual_child_stop_gated": True,
                    "initial_scan": runtime_state["initial_scan"],
                    "scan_samples": [
                        asdict(sample) for sample in runtime_samples
                    ],
                    "scan_count": len(runtime_samples),
                    "stopped_scan_count": 2,
                    "post_continue_scan_count": len(runtime_samples) - 2,
                    "fast_terminal_after_gate": len(runtime_samples) == 2,
                    "scan_log_sha256": canonical_sha256(
                        {
                            "scan_samples": [
                                asdict(sample) for sample in runtime_samples
                            ]
                        }
                    ),
                    "first_scan_started_monotonic_ns": runtime_samples[
                        0
                    ].bracket_started_monotonic_ns,
                    "double_stable_completed_monotonic_ns": runtime_samples[
                        1
                    ].bracket_completed_monotonic_ns,
                    "first_input_write_monotonic_ns": (
                        first_input_write_monotonic_ns
                    ),
                    "last_scan_completed_monotonic_ns": runtime_samples[
                        -1
                    ].bracket_completed_monotonic_ns,
                    "terminal_waitid_code": terminal_waitid["code"],
                    "terminal_waitid_status": terminal_waitid["status"],
                    "terminal_nonreaping_observed_monotonic_ns": (
                        terminal_nonreaping_observed_ns
                    ),
                    "maximum_scan_gap_ns": max(scan_gaps, default=0),
                    "all_scans_same_inventory": True,
                    "instrumentation_through_terminal": True,
                    "static_closure_revalidated_after_wait4": True,
                    "static_closure_post_wait4_sha256": post_wait_closure[
                        "closure_sha256"
                    ],
                    "transient_dlopen_polling_gap_disclosed": True,
                }
                runtime_attestation_mapping["record_sha256"] = (
                    canonical_sha256(runtime_attestation_mapping)
                )
                native_runtime_attestation = NativeRuntimeImageAttestation(
                    **{
                        **runtime_attestation_mapping,
                        "scan_samples": runtime_samples,
                    }
                )
                record_sequence += 1
                tombstone_mapping: dict[str, Any] = {
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "spawn_sequence": spawn_sequence,
                    "spawn_nonce_sha256": spawn_nonce_sha256,
                    "record_sequence": record_sequence,
                    "previous_record_sha256": birth.record_sha256,
                    "birth_record_sha256": birth.record_sha256,
                    "pid": pid,
                    "start_abstime": child.start_abstime,
                    "raw_wait_status": wait_result.raw_status,
                    "exited": os.WIFEXITED(wait_result.raw_status),
                    "exit_code": os.WEXITSTATUS(wait_result.raw_status) if os.WIFEXITED(wait_result.raw_status) else None,
                    "signaled": os.WIFSIGNALED(wait_result.raw_status),
                    "signal_number": os.WTERMSIG(wait_result.raw_status) if os.WIFSIGNALED(wait_result.raw_status) else None,
                    "core_dumped": bool(os.WCOREDUMP(wait_result.raw_status)) if os.WIFSIGNALED(wait_result.raw_status) and hasattr(os, "WCOREDUMP") else False,
                    "rusage": asdict(wait_result.rusage),
                    "stdout_bytes": stdout_observed_bytes,
                    "stdout_retained_bytes": len(stdout),
                    "stdout_sha256": stdout_observed_sha256,
                    "stdout_disposition": stdout_disposition,
                    "stderr_bytes": stderr_observed_bytes,
                    "stderr_retained_bytes": len(stderr),
                    "stderr_sha256": stderr_observed_sha256,
                    "stderr_disposition": stderr_disposition,
                    "overflowed": overflowed,
                    "observed_monotonic_ns": observed_wait_ns,
                    "maximum_resident_set_size_bytes": wait_result.maximum_resident_set_size_bytes,
                    "minor_faults": wait_result.minor_faults,
                    "major_faults": wait_result.major_faults,
                    "voluntary_context_switches": wait_result.voluntary_context_switches,
                    "involuntary_context_switches": wait_result.involuntary_context_switches,
                    "nonreaping_wait4_probe_count": nonreaping_wait4_probe_count,
                    "terminal_wait4_reap_count": 1,
                    "direct_parent_waited": True,
                    "native_runtime_attestation": asdict(
                        native_runtime_attestation
                    ),
                }
                tombstone_mapping[
                    "child_sandbox_probe_inheritance_sha256"
                ] = child_sandbox_probe_inheritance_sha256(
                    request_id=self.active["request_id"],
                    request_epoch=self.active["request_epoch"],
                    request_sequence=self.active["request_sequence"],
                    spawn_sequence=spawn_sequence,
                    spawn_nonce_sha256=spawn_nonce_sha256,
                    pid=pid,
                    start_abstime=child.start_abstime,
                    attestation=native_runtime_attestation,
                )
                tombstone_mapping["record_sha256"] = canonical_sha256(tombstone_mapping)
                tombstone = BrokerChildWait4Tombstone(
                    **{
                        **tombstone_mapping,
                        "rusage": wait_result.rusage,
                        "native_runtime_attestation": (
                            native_runtime_attestation
                        ),
                    }
                )
                tombstone_ledger_sha256 = self.ledger.append(
                    "child_wait4", dataclass_mapping(tombstone)
                )
                if time.monotonic_ns() >= wait4_deadline_ns:
                    raise TimeoutError(
                        "child tombstone ledger publication crossed its deadline"
                    )
                self._watchdog_close_child(
                    birth=birth,
                    tombstone=tombstone,
                    tombstone_ledger_row_sha256=tombstone_ledger_sha256,
                    absolute_deadline_ns=wait4_deadline_ns,
                )
                if time.monotonic_ns() >= wait4_deadline_ns:
                    raise TimeoutError(
                        "child terminal receipt crossed its deadline"
                    )
                return birth, tombstone, stdout, stderr, timed_out, overflowed
            except BaseException:
                if not child_reaped:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)
                    # Never use waitpid/Popen; exact wait4 remains the only
                    # reaper.  The unreaped direct child pins this PID, so it
                    # cannot refer to an unrelated process in this branch.
                    with contextlib.suppress(BaseException):
                        end = min(
                            self.config.attempt_deadline_ns,
                            time.monotonic_ns() + 2_000_000_000,
                        )
                        while native_wait4_exact(
                            pid,
                            absolute_deadline_ns=end,
                        ) is None:
                            time.sleep(0.001)
                for descriptor in (
                    ready_read,
                    release_write,
                    stdout_read,
                    stderr_read,
                    stdin_write,
                    guard_exec_error_read,
                ):
                    if descriptor >= 0:
                        with contextlib.suppress(OSError):
                            os.close(descriptor)
                raise

    def _handle_run(self, payload: object, body: bytes) -> None:
        if self.active is None or self.active["begin_released"] is not True:
            raise BrokerProtocolError("broker run lacks phase")
        if body:
            raise BrokerProtocolError("broker RUN header body is forbidden")
        if (
            self.active["thread_transfer_required"] is True
            and self.active["thread_transfer_state"] != "claimed"
        ):
            raise BrokerProtocolError("broker run lacks conversion-thread authority")
        if self.active["phase"] == "shutdown":
            raise BrokerProtocolError("shutdown phase cannot launch Tesseract")
        mapping = _strict_object(
            payload,
            {
                "request_id", "request_epoch", "request_sequence",
                "worker_python_thread_id", "worker_thread_id", "capability_sha256",
                "arm_capability_sha256", "binding_sha256",
                "absolute_deadline_monotonic_ns", "command", "input_manifest",
            },
            "broker run",
        )
        self._validate_phase_message({key: mapping[key] for key in mapping if key not in {"absolute_deadline_monotonic_ns", "command", "input_manifest"}})
        deadline_ns = _positive_int(mapping["absolute_deadline_monotonic_ns"], "command deadline")
        if deadline_ns > self.active["phase_deadline_ns"] or deadline_ns <= time.monotonic_ns():
            raise BrokerProtocolError("broker command deadline differs")
        input_manifest = run_input_manifest_from_mapping(
            mapping["input_manifest"]
        )
        command_header = _strict_object(
            mapping["command"],
            {
                "operation", "language", "tessdata", "psm", "input_suffix",
                "input_bytes", "input_sha256", "input_transport",
                "logical_argv_sha256", "stderr_mode",
                "stdout_disposition", "stderr_disposition",
            },
            "broker command header",
        )
        if (
            type(input_manifest) is not BrokerRunInputManifest
            or input_manifest.request_id != self.active["request_id"]
            or input_manifest.request_epoch != self.active["request_epoch"]
            or input_manifest.request_sequence != self.active["request_sequence"]
            or input_manifest.input_bytes != command_header["input_bytes"]
            or input_manifest.input_sha256 != command_header["input_sha256"]
        ):
            raise BrokerProtocolError("broker RUN input manifest differs")
        self.channel.set_absolute_deadline_ns(deadline_ns)
        try:
            input_body = receive_run_blob_chunks(self.channel, input_manifest)
            if time.monotonic_ns() >= deadline_ns:
                raise BrokerProtocolError(
                    "broker RUN input completed after its deadline"
                )
            operation, argv, environment = self._validate_command(
                command_header, input_body
            )
            (
                birth,
                tombstone,
                stdout,
                stderr,
                timed_out,
                overflowed,
            ) = self._run_child(
                operation,
                argv,
                environment,
                input_body,
                deadline_ns,
                command_header["logical_argv_sha256"],
                command_header["stderr_mode"],
                command_header["stdout_disposition"],
                command_header["stderr_disposition"],
            )
            del input_body
            self.births.append(birth)
            self.tombstones.append(tombstone)
            self.completed_spawns += 1
            outcome = (
                "timeout"
                if timed_out
                else "overflow"
                if overflowed
                else "completed"
            )
            returncode = (
                tombstone.exit_code
                if tombstone.exited
                else -int(tombstone.signal_number or 1)
            )
            output_manifest, output_blob, output_commitments = (
                build_run_output_transport(
                    request_id=self.active["request_id"],
                    request_epoch=self.active["request_epoch"],
                    request_sequence=self.active["request_sequence"],
                    outcome=outcome,
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_disposition=command_header[
                        "stdout_disposition"
                    ],
                    stderr_disposition=command_header[
                        "stderr_disposition"
                    ],
                )
            )
            self.channel.send(
                "run_ack",
                {
                    "request_id": self.active["request_id"],
                    "request_epoch": self.active["request_epoch"],
                    "request_sequence": self.active["request_sequence"],
                    "outcome": outcome,
                    "returncode": returncode,
                    "birth_record_sha256": birth.record_sha256,
                    "tombstone_record_sha256": tombstone.record_sha256,
                    "output_manifest": asdict(output_manifest),
                },
            )
            send_run_blob_chunks(
                self.channel,
                output_manifest,
                output_blob,
                output_commitments,
            )
            if time.monotonic_ns() >= deadline_ns:
                raise TimeoutError(
                    "broker RUN output crossed its absolute deadline"
                )
            self.channel.set_absolute_deadline_ns(
                self.active["phase_deadline_ns"]
            )
        except BaseException:
            # A RUN failure terminalizes the capability; retain the immutable
            # command deadline instead of widening authority to the phase.
            raise

    def _finish_phase(self, kind: str, payload: object, body: bytes) -> None:
        if body:
            raise BrokerProtocolError("phase terminal body is forbidden")
        terminal = _strict_object(
            payload,
            {
                "request_id", "request_epoch", "request_sequence",
                "worker_python_thread_id", "worker_thread_id",
                "capability_sha256", "arm_capability_sha256", "binding_sha256",
                "failure_reason_sha256",
            },
            "phase terminal binding",
        )
        self._validate_phase_message(
            {key: value for key, value in terminal.items() if key != "failure_reason_sha256"}
        )
        failure_reason_sha256 = _sha(
            terminal["failure_reason_sha256"], "failure_reason_sha256"
        )
        if (kind == "end") != (failure_reason_sha256 == _EMPTY_SHA256):
            raise BrokerProtocolError("phase terminal failure binding differs")
        if self.active is None or self.active["begin_released"] is not True:
            raise BrokerProtocolError("phase terminal preceded BEGIN release")
        phase_deadline_ns = min(
            self.active["phase_deadline_ns"],
            self.config.attempt_deadline_ns,
        )
        if time.monotonic_ns() >= phase_deadline_ns:
            raise TimeoutError("broker phase terminal deadline expired")
        self.channel.set_absolute_deadline_ns(phase_deadline_ns)
        if (
            self.active["thread_transfer_required"] is True
            and (
                self.active["thread_transfer_state"] != "returned"
                or len(self.thread_transfers) != 2
            )
            and kind == "end"
        ):
            raise BrokerProtocolError("phase ended before thread authority returned")
        phase = "abort" if kind == "abort" else "end"
        # Aborts have already synchronously killed/wait4-reaped any known job.
        end = self._quiescence("end")
        if self.active is None:
            raise BrokerProtocolError("phase disappeared")
        if (
            end.observed_at_monotonic_ns >= phase_deadline_ns
            or time.monotonic_ns() >= phase_deadline_ns
        ):
            raise TimeoutError("broker END quiescence crossed its deadline")
        phase_sandbox_report = (
            self.child_sandbox_probe_report
            if any(
                birth.child_sandbox_probe_mode
                == "representative-full-matrix"
                for birth in self.births
            )
            else None
        )
        sandbox_inheritance_count, sandbox_inheritance_head = (
            child_sandbox_probe_phase_inheritance_head(tuple(self.births))
        )
        sandbox_representative_report_sha256 = (
            self.child_sandbox_probe_report.record_sha256
            if self.child_sandbox_probe_report is not None
            else _ZERO_SHA256
        )
        sandbox_report_ledger_row_sha256 = (
            self.child_sandbox_probe_report_ledger_row_sha256
            if self.child_sandbox_probe_report_ledger_row_sha256 is not None
            else _ZERO_SHA256
        )
        receipt_mapping: dict[str, Any] = {
            "schema_id": BROKER_PROTOCOL_SCHEMA,
            "attempt_nonce_sha256": hashlib.sha256(self.config.attempt_nonce.encode("ascii")).hexdigest(),
            "scope_sha256": self.config.scope_sha256,
            "request_id": self.active["request_id"],
            "request_epoch": self.active["request_epoch"],
            "request_sequence": self.active["request_sequence"],
            "worker_thread_id": self.active["worker_thread_id"],
            "arm_capability_sha256": self.active["arm_capability_sha256"],
            "arm_issued_at_monotonic_ns": self.active[
                "arm_issued_at_monotonic_ns"
            ],
            "arm_consumed_at_monotonic_ns": self.active[
                "arm_consumed_at_monotonic_ns"
            ],
            "arm_terminal_disposition": (
                "aborted" if kind == "abort" else "ended"
            ),
            "thread_transfer_required": self.active[
                "thread_transfer_required"
            ],
            "logical_phase": self.active["phase"],
            "terminal_kind": kind,
            "phase_deadline_monotonic_ns": self.active["phase_deadline_ns"],
            "binding_sha256": self.active["binding_sha256"],
            "request_binding": (
                dataclass_mapping(self.active["request_binding"])
                if self.active["request_binding"] is not None
                else None
            ),
            "thread_claim_count": sum(
                value.kind == "claim" for value in self.thread_transfers
            ),
            "failure_reason_sha256": failure_reason_sha256,
            "native_closure_sha256": self.config.native_closure_sha256,
            "native_closure": self.config.native_closure,
            "guard_python": asdict(self.config.guard_python),
            "guard_python_path_custody": (
                self.config.guard_python_path_custody
            ),
            "guard_python_native_closure": (
                self.config.guard_python_native_closure
            ),
            "guard_python_module_tree_custody": (
                self.config.guard_python_module_tree_custody
            ),
            "guard_wrapper_source_hex": self.config.guard_wrapper_source.hex(),
            "guard_wrapper_source_sha256": self.config.child_wrapper_sha256,
            "guard_wrapper_delivery_basis": (
                "execve-python-c-embedded-source-v1"
            ),
            "child_sandbox_probe_executor_authority": (
                CHILD_SANDBOX_EXECUTOR_AUTHORITY
            ),
            "child_sandbox_probe_executor_source_hex": (
                self.config.child_sandbox_probe_executor_source.hex()
            ),
            "child_sandbox_probe_executor_source_sha256": (
                self.config.child_sandbox_probe_executor_source_sha256
            ),
            "child_sandbox_probe_plan": (
                self.config.child_sandbox_probe_plan
            ),
            "child_sandbox_probe_report": (
                dataclass_mapping(phase_sandbox_report)
                if phase_sandbox_report is not None
                else None
            ),
            "child_sandbox_probe_representative_report_sha256": (
                sandbox_representative_report_sha256
            ),
            "child_sandbox_probe_report_ledger_row_sha256": (
                sandbox_report_ledger_row_sha256
            ),
            "child_sandbox_probe_inheritance_count": (
                sandbox_inheritance_count
            ),
            "child_sandbox_probe_inheritance_head_sha256": (
                sandbox_inheritance_head
            ),
            "begin": dataclass_mapping(self.active["begin"]),
            "thread_transfers": [
                dataclass_mapping(value) for value in self.thread_transfers
            ],
            "births": [dataclass_mapping(value) for value in self.births],
            "tombstones": [dataclass_mapping(value) for value in self.tombstones],
            "end": dataclass_mapping(end),
            "previous_receipt_sha256": self.previous_receipt_sha256,
        }
        receipt_mapping["receipt_sha256"] = canonical_sha256(receipt_mapping)
        receipt = BrokerRequestReceipt(
            **{
                **receipt_mapping,
                "guard_python": self.config.guard_python,
                "child_sandbox_probe_report": phase_sandbox_report,
                "begin": self.active["begin"],
                "thread_transfers": tuple(self.thread_transfers),
                "births": tuple(self.births),
                "tombstones": tuple(self.tombstones),
                "end": end,
            }
        )
        receipt_manifest, receipt_blob, receipt_chunks = (
            build_request_receipt_transport(receipt)
        )
        # The authoritative audit log retains only the small typed manifest.
        # Full receipt bytes travel as bounded bodies and are durably retained
        # by the external controller's O_EXCL blob authority.
        self.ledger.append(
            "phase_terminal",
            {"receipt_manifest": dataclass_mapping(receipt_manifest)},
        )
        if time.monotonic_ns() >= phase_deadline_ns:
            raise TimeoutError(
                "broker terminal receipt ledger publication crossed its deadline"
            )
        self.pending_receipt = receipt
        completed_phase = self.active["phase"]
        self.active = None
        if kind == "abort":
            self._lifecycle_state = "closed"
        elif completed_phase == "startup":
            self._lifecycle_state = "ready"
        elif completed_phase == "shutdown":
            self._lifecycle_state = "closed"
        self.channel.send(
            "abort_ack" if kind == "abort" else "end_ack",
            {"receipt_manifest": dataclass_mapping(receipt_manifest)},
        )
        send_request_receipt_chunks(
            self.channel,
            receipt_manifest,
            receipt_blob,
            receipt_chunks,
        )
        if time.monotonic_ns() >= phase_deadline_ns:
            raise TimeoutError("broker terminal receipt publication crossed its deadline")

    def _release(self, payload: object, body: bytes) -> None:
        if body or self.pending_receipt is None:
            raise BrokerProtocolError("broker release state differs")
        mapping = _strict_object(payload, {"request_id", "request_epoch", "receipt_sha256"}, "release")
        receipt = self.pending_receipt
        if mapping != {
            "request_id": receipt.request_id,
            "request_epoch": receipt.request_epoch,
            "receipt_sha256": receipt.receipt_sha256,
        }:
            raise BrokerProtocolError("broker release binding differs")
        self.previous_receipt_sha256 = receipt.receipt_sha256
        self.ledger.append("phase_release", mapping)
        self.pending_receipt = None
        self.channel.send(
            "release_ack",
            {"request_id": receipt.request_id, "request_epoch": receipt.request_epoch},
        )

    def serve(self) -> None:
        kind, payload, body = self.channel.receive(expected_kind="hello")
        self._handle_hello(payload, body)
        while not self._closed:
            kind, payload, body = self.channel.receive()
            if kind == "begin":
                self._handle_begin(payload, body)
            elif kind == "begin_release":
                if body or self.active is None or self.active["begin_released"] is True:
                    raise BrokerProtocolError("begin release state differs")
                self._validate_phase_message(payload)
                self.ledger.append("begin_release", payload)
                self.active["begin_released"] = True
                self.channel.send(
                    "begin_release_ack",
                    {"request_id": self.active["request_id"], "request_epoch": self.active["request_epoch"]},
                )
            elif kind in {"thread_claim", "thread_release"}:
                self._handle_thread_transfer(kind, payload, body)
            elif kind == "request_match":
                self._handle_request_match(payload, body)
            elif kind == "run":
                self._handle_run(payload, body)
            elif kind in {"end", "abort"}:
                self._finish_phase(kind, payload, body)
            elif kind == "release":
                self._release(payload, body)
            elif kind == "shutdown":
                if (
                    self._lifecycle_state != "closed"
                    or self.active is not None
                    or self.pending_receipt is not None
                    or body
                ):
                    raise BrokerProtocolError("broker shutdown is not quiescent")
                expected = {"attempt_nonce_sha256": hashlib.sha256(self.config.attempt_nonce.encode("ascii")).hexdigest()}
                if payload != expected:
                    raise BrokerProtocolError("broker shutdown capability differs")
                immutable_observation = self.config.validate_immutable_inputs()
                self._scratch_inventory()
                self.ledger.append(
                    "shutdown_immutable_inputs", immutable_observation
                )
                self.ledger.append("shutdown", expected)
                self.channel.send(
                    "shutdown_ack",
                    {
                        "ledger": self.ledger.ready_identity(),
                        "immutable_inputs": immutable_observation,
                    },
                )
                self._closed = True
            else:
                raise BrokerProtocolError("broker message kind is not admitted")


def _load_config(path: str, expected_sha256: str) -> tuple[BrokerLaunchConfig, str]:
    body, observed = _read_exact_file(path, MAX_CONFIG_BYTES)
    if stat.S_IMODE(observed.st_mode) != 0o600 or observed.st_nlink != 1:
        raise BrokerProtocolError("broker config custody differs")
    digest = hashlib.sha256(body).hexdigest()
    if digest != expected_sha256:
        raise BrokerProtocolError("broker config digest differs")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerProtocolError("broker config is malformed") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != body:
        raise BrokerProtocolError("broker config is not canonical")
    return BrokerLaunchConfig(value), digest


def main(argv: Sequence[str] | None = None) -> int:
    sandbox_process_entered_at_monotonic_ns = time.monotonic_ns()
    parser = argparse.ArgumentParser(description="private Tesseract broker")
    parser.add_argument("--capability-fd", type=int, required=True)
    parser.add_argument("--ready-fd", type=int, required=True)
    parser.add_argument("--release-fd", type=int, required=True)
    parser.add_argument("--watchdog-fd", type=int, required=True)
    parser.add_argument("--sandbox-probe-report-fd", type=int, required=True)
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args(argv)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM, signal.SIGHUP})
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    if signal.SIGTERM in blocked or signal.SIGHUP in blocked:
        raise BrokerProtocolError("broker TERM/HUP signal mask differs")
    config, config_sha256 = _load_config(args.config_json, _sha(args.config_sha256, "config_sha256"))
    observed_launcher = trusted_launcher_identity(config.launcher_pid)
    if (
        os.getpid() != os.getpgid(0)
        or os.getpid() != os.getsid(0)
        or os.getppid() != config.launcher_pid
        or observed_launcher != config.launcher
        or config.launcher.uid != os.getuid()
        or config.launcher.euid != os.geteuid()
        or raw_process_start_abstime(config.controller_pid) != config.controller_start_abstime
        or os.getuid() == 0
        or os.geteuid() == 0
    ):
        raise BrokerProtocolError("broker launch topology differs")
    for descriptor in (
        args.capability_fd,
        args.ready_fd,
        args.release_fd,
        args.watchdog_fd,
        args.sandbox_probe_report_fd,
    ):
        if descriptor < 3:
            raise BrokerProtocolError("broker launch descriptor is unsafe")
        os.set_inheritable(descriptor, False)
    from app.services.parser_sandbox_probe import (
        run_native_sandbox_probe_plan,
    )

    sandbox_probe_report = run_native_sandbox_probe_plan(
        config.broker_sandbox_probe_plan,
        sandbox_applied_at_monotonic_ns=(
            sandbox_process_entered_at_monotonic_ns
        ),
    )
    sandbox_report_bytes = canonical_json_bytes(sandbox_probe_report) + b"\n"
    if len(sandbox_report_bytes) > 256 * 1024:
        raise BrokerProtocolError("broker sandbox report exceeds its bound")
    sandbox_report_view = memoryview(sandbox_report_bytes)
    while sandbox_report_view:
        sandbox_written = os.write(
            args.sandbox_probe_report_fd, sandbox_report_view
        )
        if sandbox_written <= 0:
            raise BrokerProtocolError("broker sandbox report write failed")
        sandbox_report_view = sandbox_report_view[sandbox_written:]
    os.close(args.sandbox_probe_report_fd)
    args.sandbox_probe_report_fd = -1
    sock = socket.socket(fileno=args.capability_fd)
    watchdog_sock = socket.socket(fileno=args.watchdog_fd)
    watchdog_channel = FramedChannel(watchdog_sock)
    watchdog_channel.set_absolute_deadline_ns(config.attempt_deadline_ns)
    ledger = DurableLedger(watchdog_channel, config)
    broker = TesseractBroker(sock, watchdog_channel, config, ledger)
    worker_socket_stat = os.fstat(args.capability_fd)
    watchdog_socket_stat = os.fstat(args.watchdog_fd)
    ready_thread_inventory = native_detailed_thread_inventory(
        broker.identity.pid
    )
    if ready_thread_inventory.thread_count != 1:
        raise BrokerProtocolError("broker READY thread inventory differs")
    ready_file_descriptor_inventory = (
        native_detailed_file_descriptor_inventory(broker.identity.pid)
    )
    ready: dict[str, Any] = {
        "schema_id": BROKER_READY_SCHEMA,
        "attempt_nonce_sha256": hashlib.sha256(config.attempt_nonce.encode("ascii")).hexdigest(),
        "scope_sha256": config.scope_sha256,
        "config_sha256": config_sha256,
        "controller": {"pid": config.controller_pid, "start_abstime": config.controller_start_abstime},
        "launcher": asdict(config.launcher),
        "broker": {
            "pid": broker.identity.pid,
            "start_abstime": broker.identity.start_abstime,
            "ppid": broker.identity.ppid,
            "pgid": broker.identity.pgid,
            "sid": broker.identity.sid,
            "uid": os.getuid(),
            "euid": os.geteuid(),
        },
        "capability": {
            "worker": {
                "family": "AF_UNIX", "type": "SOCK_STREAM", "cloexec": True,
                "device": worker_socket_stat.st_dev, "inode": worker_socket_stat.st_ino,
            },
            "watchdog": {
                "family": "AF_UNIX", "type": "SOCK_STREAM", "cloexec": True,
                "device": watchdog_socket_stat.st_dev, "inode": watchdog_socket_stat.st_ino,
            },
        },
        "profile_sha256": config.broker_profile_sha256,
        "executable_sha256": config.executable.sha256,
        "tessdata_sha256": config.tessdata_sha256,
        "native_closure_sha256": config.native_closure_sha256,
        "native_trust_model": NATIVE_CLOSURE_TRUST_MODEL,
        "native_containment_claim": "none-trusted-pinned-native-computation",
        "native_spawn_guard_sha256": config.native_spawn_guard.sha256,
        "native_spawn_guard_source_sha256": (
            config.native_spawn_guard_source_sha256
        ),
        "native_runtime_gate_source_sha256": (
            config.native_runtime_gate_source.sha256
        ),
        "native_runtime_gate_library_sha256": (
            config.native_runtime_gate_library.sha256
        ),
        "native_runtime_gate_record_sha256": (
            config.native_runtime_gate["record_sha256"]
        ),
        "watchdog_protocol_sha256": config.watchdog_protocol_sha256,
        "ledger": ledger.ready_identity(),
        "pre_release_thread_inventory": asdict(ready_thread_inventory),
        "pre_release_file_descriptor_inventory": asdict(
            ready_file_descriptor_inventory
        ),
        "retired_descriptor_fds": sorted(
            (args.ready_fd, args.release_fd)
        ),
        "ready_at_monotonic_ns": time.monotonic_ns(),
    }
    ready["ready_sha256"] = canonical_sha256(ready)
    broker.pre_release_ready_sha256 = ready["ready_sha256"]
    broker.pre_release_thread_inventory = ready_thread_inventory
    broker.pre_release_file_descriptor_inventory = (
        ready_file_descriptor_inventory
    )
    broker.retired_descriptor_fds = tuple(
        sorted((args.ready_fd, args.release_fd))
    )
    _write_ready(args.ready_fd, ready)
    os.close(args.ready_fd)
    if os.read(args.release_fd, 1) != b"R":
        raise BrokerProtocolError("broker release gate differs")
    os.close(args.release_fd)
    try:
        broker.serve()
    finally:
        try:
            ledger.close(broker.identity)
        finally:
            # EOF is part of terminal custody: after the watchdog ACKs the
            # hard no-fork close record, make the child-watch capability
            # irreversibly unusable before returning from the broker entry
            # point.  The watchdog requires this EOF in addition to the close
            # record and exact process disappearance.
            try:
                watchdog_channel.close()
            finally:
                os.close(config.request_root_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BROKER_LAUNCH_SCHEMA",
    "BROKER_READY_SCHEMA",
    "BrokerLaunchConfig",
    "TesseractBroker",
    "main",
    "validate_broker_ready_record",
]
