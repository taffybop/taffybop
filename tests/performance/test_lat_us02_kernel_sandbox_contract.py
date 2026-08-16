from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import stat
import struct
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks import latency_prewarm_contracts as contracts


ZERO_SHA = "0" * 64
ATTEMPT_NONCE = hashlib.sha256(b"attempt-nonce").hexdigest()
SCOPE_SHA = hashlib.sha256(b"scope").hexdigest()
UID = 501


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _record(model_type, **fields):
    provisional = model_type.model_construct(**fields, record_sha256=ZERO_SHA)
    projection = provisional.model_dump(mode="json", exclude={"record_sha256"})
    return model_type(**fields, record_sha256=contracts._canonical_hash(projection))


def _replace(value, **updates):
    fields = {
        name: getattr(value, name)
        for name in type(value).model_fields
        if name != "record_sha256"
    }
    fields.update(updates)
    return _record(type(value), **fields)


def _file(path: str, label: str) -> contracts.KernelSandboxFileIdentity:
    return _record(
        contracts.KernelSandboxFileIdentity,
        resolved_path=path,
        resolved_path_sha256=hashlib.sha256(path.encode("utf-8")).hexdigest(),
        content_sha256=_sha(f"{label}-content"),
        device=1,
        inode=int.from_bytes(hashlib.sha256(label.encode()).digest()[:4], "big") + 1,
        mode=stat.S_IFREG | 0o500,
        uid=UID,
        effective_uid=UID,
        nlink=1,
        size_bytes=17,
        mtime_ns=10,
        ctime_ns=11,
        first_descriptor=80,
        first_open_flags=os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        first_observed_at_monotonic_ns=50,
        second_descriptor=81,
        second_open_flags=os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        second_observed_at_monotonic_ns=10_000,
    )


def _directory(path: str, label: str) -> contracts.KernelSandboxDirectoryIdentity:
    inode = int.from_bytes(hashlib.sha256(label.encode()).digest()[:4], "big") + 1
    mode = stat.S_IFDIR | 0o700
    fstat_identity = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-held-directory-fstat-v1",
            "device": 1,
            "inode": inode,
            "mode": mode,
            "uid": UID,
            "nlink": 2,
        }
    )
    return _record(
        contracts.KernelSandboxDirectoryIdentity,
        resolved_path=path,
        resolved_path_sha256=hashlib.sha256(path.encode("utf-8")).hexdigest(),
        device=1,
        inode=inode,
        mode=mode,
        uid=UID,
        controller_euid=UID,
        holder_pid=800,
        holder_start_abstime=900,
        nlink=2,
        held_directory_fd=90,
        held_open_flags=(
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        ),
        opened_at_monotonic_ns=1,
        first_path_observed_at_monotonic_ns=2,
        first_fstat_observed_at_monotonic_ns=3,
        second_fstat_observed_at_monotonic_ns=9_998,
        second_path_observed_at_monotonic_ns=9_999,
        closed_at_monotonic_ns=10_000,
        opened_fstat_sha256=fstat_identity,
        final_fstat_sha256=fstat_identity,
        first_path_identity_sha256=fstat_identity,
        second_path_identity_sha256=fstat_identity,
    )


def _sentinel(
    target_sha256: str,
    *,
    root: contracts.KernelSandboxDirectoryIdentity,
    target_name: str,
    observed: int,
    exists: bool,
    dac: bool,
    label: str,
    parent_inventory_jsonl: str | None = None,
    identity_override: dict[str, Any] | None = None,
) -> contracts.KernelSandboxSentinelObservation:
    identity: dict[str, Any]
    if exists:
        identity = {
            "device": 1,
            "inode": int.from_bytes(
                hashlib.sha256(label.encode()).digest()[:4], "big"
            )
            + 1,
            "mode": stat.S_IFREG | 0o600,
            "uid": UID,
            "nlink": 1,
            "size_bytes": 17,
            "content_sha256": _sha(f"{label}-content"),
        }
    else:
        identity = {
            "device": None,
            "inode": None,
            "mode": None,
            "uid": None,
            "nlink": None,
            "size_bytes": None,
            "content_sha256": None,
        }
    if identity_override is not None:
        if not exists:
            raise ValueError("absent sentinel cannot override an identity")
        identity = dict(identity_override)
    if parent_inventory_jsonl is None:
        if exists:
            entry = {"name": target_name, **identity}
            parent_inventory_jsonl = (
                json.dumps(
                    entry,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
        else:
            parent_inventory_jsonl = ""
    return _record(
        contracts.KernelSandboxSentinelObservation,
        target_sha256=target_sha256,
        parent_directory_record_sha256=root.record_sha256,
        parent_directory_inventory_jsonl=parent_inventory_jsonl,
        parent_directory_inventory_entry_count=len(
            contracts._kernel_sandbox_directory_inventory(
                parent_inventory_jsonl
            )
        ),
        parent_directory_inventory_sha256=hashlib.sha256(
            parent_inventory_jsonl.encode("utf-8")
        ).hexdigest(),
        observed_at_monotonic_ns=observed,
        dac_write_authority_required=dac,
        parent_writable_by_effective_uid=dac,
        target_writable_by_effective_uid=(True if dac and exists else None),
        exists=exists,
        **identity,
    )


def _network_socket_descriptor(
    *,
    fd: int,
    family: int,
    socket_type: int,
    protocol: int,
    label: str,
    local_identity_sha256: str | None = None,
    peer_identity_sha256: str | None = None,
) -> contracts.NativeFileDescriptorIdentity:
    return _record(
        contracts.NativeFileDescriptorIdentity,
        fd=fd,
        kernel_type=2,
        open_flags=0,
        kernel_status_flags=0,
        descriptor_offset=0,
        descriptor_type=2,
        guard_flags=0,
        close_on_exec=True,
        close_on_fork=False,
        guarded=False,
        shared=False,
        vnode=None,
        socket=contracts.NativeSocketFileDescriptorIdentity(
            family=family,
            socket_type=socket_type,
            protocol=protocol,
            socket_kind=1,
            socket_state=1,
            local_identity_sha256=(
                local_identity_sha256 or _sha(f"{label}-local")
            ),
            peer_identity_sha256=(
                peer_identity_sha256 or _sha(f"{label}-peer")
            ),
        ),
        pipe=None,
        kqueue=None,
    )


def _network_target(
    role: str,
    operation: str,
) -> contracts.KernelSandboxNetworkTarget:
    kind, family, ip_literal = {
        "ipv4_tcp_connect": ("tcp_ipv4", "AF_INET", "127.0.0.1"),
        "ipv6_tcp_connect": ("tcp_ipv6", "AF_INET6", "::1"),
        "ipv4_udp_sendto": ("udp_ipv4", "AF_INET", "127.0.0.1"),
        "ipv6_udp_sendto": ("udp_ipv6", "AF_INET6", "::1"),
        "unix_connect": ("unix_stream", "AF_UNIX", None),
        "ipv4_bind_listen": ("bind_ipv4", "AF_INET", "127.0.0.1"),
        "ipv6_bind_listen": ("bind_ipv6", "AF_INET6", "::1"),
        "unix_bind": ("bind_unix", "AF_UNIX", None),
        "hostname_resolution": ("hostname", "none", None),
    }[operation]
    bind = kind.startswith("bind_")
    unix = kind in {"unix_stream", "bind_unix"}
    hostname = kind == "hostname"
    udp = kind.startswith("udp_")
    unix_root = (
        _directory(
            "/private/tmp/lat-us02/probes/network-traps", "network-traps"
        )
        if unix
        else None
    )
    unix_relative_path = (
        "fresh-bind.sock" if kind == "bind_unix" else "controller.sock"
    ) if unix else None
    unix_sockaddr = None
    if unix_root is not None and unix_relative_path is not None:
        path_bytes = unix_relative_path.encode("utf-8")
        unix_sockaddr = bytes(
            (3 + len(path_bytes), int(socket.AF_UNIX))
        ) + path_bytes + b"\0"
    target_port = (
        (0 if bind else 41_000 + len(role) + len(operation))
        if not unix and not hostname
        else None
    )
    target_sockaddr = unix_sockaddr
    if family == "AF_INET":
        assert ip_literal is not None and target_port is not None
        target_sockaddr = (
            bytes((16, int(socket.AF_INET)))
            + target_port.to_bytes(2, "big")
            + socket.inet_pton(socket.AF_INET, ip_literal)
            + b"\0" * 8
        )
    elif family == "AF_INET6":
        assert ip_literal is not None and target_port is not None
        target_sockaddr = (
            bytes((28, int(socket.AF_INET6)))
            + target_port.to_bytes(2, "big")
            + b"\0" * 4
            + socket.inet_pton(socket.AF_INET6, ip_literal)
            + b"\0" * 4
        )
    family_number = {
        "none": 0,
        "AF_INET": int(socket.AF_INET),
        "AF_INET6": int(socket.AF_INET6),
        "AF_UNIX": int(socket.AF_UNIX),
    }[family]
    socket_type = (
        int(socket.SOCK_DGRAM) if udp else int(socket.SOCK_STREAM)
    )
    protocol = (
        int(socket.IPPROTO_UDP)
        if udp
        else int(socket.IPPROTO_TCP)
        if family in {"AF_INET", "AF_INET6"}
        else 0
    )
    endpoint = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-network-endpoint-v1",
            "target_kind": kind,
            "address_family": family,
            "ip_literal": ip_literal,
            "port": target_port,
            "unix_root_record_sha256": (
                unix_root.record_sha256 if unix_root is not None else None
            ),
            "unix_relative_path": unix_relative_path,
            "unix_sockaddr_sha256": (
                hashlib.sha256(unix_sockaddr).hexdigest()
                if unix_sockaddr is not None
                else None
            ),
            "hostname": "lat-us02-probe.local" if hostname else None,
        }
    )
    base_fd = 300 + int.from_bytes(
        hashlib.sha256(f"{role}-{operation}".encode()).digest()[:4], "big"
    )
    client_local = _sha(f"{role}-{operation}-client-kernel-object")
    connected_peer = _sha(f"{role}-{operation}-accepted-kernel-object")
    client_descriptor = (
        None
        if hostname
        else _network_socket_descriptor(
            fd=base_fd,
            family=family_number,
            socket_type=socket_type,
            protocol=protocol,
            label=f"{role}-{operation}-client",
            local_identity_sha256=client_local,
            peer_identity_sha256=connected_peer,
        )
    )
    server_descriptor = (
        _network_socket_descriptor(
            fd=base_fd + 1,
            family=family_number,
            socket_type=socket_type,
            protocol=protocol,
            label=f"{role}-{operation}-server",
        )
        if not hostname and not bind
        else None
    )
    accepted_descriptor = (
        _network_socket_descriptor(
            fd=base_fd + 2,
            family=family_number,
            socket_type=socket_type,
            protocol=protocol,
            label=f"{role}-{operation}-accepted",
            local_identity_sha256=connected_peer,
            peer_identity_sha256=client_local,
        )
        if not hostname and not bind and not udp
        else None
    )
    control_nonce = _sha(f"{role}-{operation}-positive-control")
    payload = (
        b"KSNP1" + bytes.fromhex(control_nonce)
        if (udp or (not bind and not hostname))
        else b""
    )
    addrinfo_jsonl = (
        json.dumps(
            {
                "family": int(socket.AF_INET),
                "socket_type": int(socket.SOCK_STREAM),
                "protocol": int(socket.IPPROTO_TCP),
                "address": "127.0.0.1",
                "port": 0,
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
        if hostname
        else ""
    )
    control_descriptors = tuple(
        sorted(
            (
                item
                for item in (
                    client_descriptor,
                    server_descriptor,
                    accepted_descriptor,
                )
                if item is not None
            ),
            key=lambda item: item.fd,
        )
    )
    if not control_descriptors:
        control_descriptors = (
            _network_socket_descriptor(
                fd=base_fd,
                family=int(socket.AF_UNIX),
                socket_type=int(socket.SOCK_STREAM),
                protocol=0,
                label=f"{role}-{operation}-controller-baseline",
            ),
        )
    control_inventory = contracts.native_file_descriptor_inventory(
        process=contracts.NativeKernelProcessIdentity(
            pid=800,
            start_abstime=900,
            ppid=700,
            pgid=800,
            sid=800,
        ),
        first_scan_started_monotonic_ns=42,
        first_scan_completed_monotonic_ns=43,
        second_scan_started_monotonic_ns=44,
        second_scan_completed_monotonic_ns=45,
        descriptors=control_descriptors,
    )
    positive_control = _record(
        contracts.KernelSandboxNetworkPositiveControl,
        target_kind=kind,
        endpoint_sha256=endpoint,
        target_sockaddr_hex=(
            target_sockaddr.hex() if target_sockaddr is not None else None
        ),
        target_sockaddr_length=(
            len(target_sockaddr) if target_sockaddr is not None else None
        ),
        target_sockaddr_sha256=(
            hashlib.sha256(target_sockaddr).hexdigest()
            if target_sockaddr is not None
            else None
        ),
        controller=contracts.NativeKernelProcessIdentity(
            pid=800,
            start_abstime=900,
            ppid=700,
            pgid=800,
            sid=800,
        ),
        controller_effective_uid=UID,
        control_nonce_sha256=control_nonce,
        syscall_stage=(
            "sendto" if udp else "bind" if bind else "getaddrinfo" if hostname else "connect"
        ),
        client_descriptor=client_descriptor,
        server_descriptor=server_descriptor,
        accepted_descriptor=accepted_descriptor,
        controller_fd_inventory_during_control=control_inventory,
        syscall_return=(len(payload) if udp else 0),
        secondary_syscall_return=(
            len(payload)
            if udp
            else accepted_descriptor.fd
            if accepted_descriptor is not None
            else None
        ),
        getsockname_syscall_return=(0 if bind else None),
        listen_syscall_return=(0 if bind else None),
        payload_sha256=(hashlib.sha256(payload).hexdigest() if payload else None),
        payload_hex=(payload.hex() if payload else None),
        received_payload_sha256=(
            hashlib.sha256(payload).hexdigest() if payload else None
        ),
        received_source_endpoint_sha256=(client_local if payload else None),
        payload_size_bytes=len(payload),
        bytes_sent=len(payload),
        bytes_received=len(payload),
        accept_count=(1 if accepted_descriptor is not None else 0),
        datagram_count=(1 if udp else 0),
        getaddrinfo_results_jsonl=addrinfo_jsonl,
        getaddrinfo_result_count=(1 if hostname else 0),
        getaddrinfo_results_sha256=hashlib.sha256(
            addrinfo_jsonl.encode("utf-8")
        ).hexdigest(),
        started_monotonic_ns=40,
        completed_monotonic_ns=50,
    )
    fields = {
        "target_kind": kind,
        "address_family": family,
        "ip_literal": ip_literal,
        "port": target_port,
        "unix_root": unix_root,
        "unix_relative_path": unix_relative_path,
        "unix_sockaddr_hex": (
            unix_sockaddr.hex() if unix_sockaddr is not None else None
        ),
        "unix_sockaddr_length": (
            len(unix_sockaddr) if unix_sockaddr is not None else None
        ),
        "unix_sockaddr_sha256": (
            hashlib.sha256(unix_sockaddr).hexdigest()
            if unix_sockaddr is not None
            else None
        ),
        "hostname": "lat-us02-probe.local" if hostname else None,
        "endpoint_sha256": endpoint,
        "positive_control": positive_control,
        "controller_prebound": not bind and not hostname,
        "positive_control_started_monotonic_ns": 40,
        "positive_control_completed_monotonic_ns": 50,
        "positive_control_syscall_stage": (
            "sendto"
            if udp
            else "bind"
            if bind
            else "getaddrinfo"
            if hostname
            else "connect"
        ),
        "positive_control_syscall_return": len(payload) if udp else 0,
        "positive_control_raw_errno": 0,
        "positive_control_bytes_sent": len(payload),
        "positive_control_bytes_received": len(payload),
        "positive_control_succeeded": True,
    }
    provisional = contracts.KernelSandboxNetworkTarget.model_construct(
        **fields, target_sha256=ZERO_SHA
    )
    return contracts.KernelSandboxNetworkTarget(
        **fields,
        target_sha256=contracts._canonical_hash(
            provisional.model_dump(mode="json", exclude={"target_sha256"})
        ),
    )


def _directory_anchor(
    *,
    root: contracts.KernelSandboxDirectoryIdentity,
    primary: str,
    started: int,
    completed: int,
    secondary: str | None = None,
) -> contracts.KernelSandboxDirectoryOperationAnchor:
    primary_bytes = primary.encode("utf-8")
    secondary_bytes = secondary.encode("utf-8") if secondary is not None else None
    return _record(
        contracts.KernelSandboxDirectoryOperationAnchor,
        root=root,
        held_directory_fd=root.held_directory_fd,
        primary_relative_path=primary,
        primary_path_bytes_hex=primary_bytes.hex(),
        primary_path_bytes_sha256=hashlib.sha256(primary_bytes).hexdigest(),
        secondary_relative_path=secondary,
        secondary_path_bytes_hex=(
            secondary_bytes.hex() if secondary_bytes is not None else None
        ),
        secondary_path_bytes_sha256=(
            hashlib.sha256(secondary_bytes).hexdigest()
            if secondary_bytes is not None
            else None
        ),
        anchored_at_monotonic_ns=started,
        restored_at_monotonic_ns=completed,
    )


def _trap(
    *,
    kind: str,
    target: contracts.KernelSandboxNetworkTarget,
    family: str,
    socket_type: int,
    protocol: int,
    observed: int,
    label: str,
) -> contracts.KernelSandboxTrapObservation:
    nonce = _sha(f"{label}-nonce")
    device = -1 if family == "AF_UNIX" else 0
    inode = int.from_bytes(hashlib.sha256(label.encode()).digest()[:4], "big") + 1
    endpoint = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-socket-endpoint-v1",
            "address_family": target.address_family,
            "ip_literal": target.ip_literal,
            "port": target.port,
            "unix_root_record_sha256": (
                target.unix_root.record_sha256
                if target.unix_root is not None
                else None
            ),
            "unix_relative_path": target.unix_relative_path,
        }
    )
    descriptor = target.positive_control.server_descriptor
    assert descriptor is not None
    socket_identity = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-trap-socket-v1",
            "trap_nonce_sha256": nonce,
            "endpoint_sha256": endpoint,
            "address_family": family,
            "socket_type": socket_type,
            "socket_protocol": protocol,
            "device": device,
            "inode": inode,
            "controller_descriptor_record_sha256": descriptor.record_sha256,
        }
    )
    return _record(
        contracts.KernelSandboxTrapObservation,
        trap_kind=kind,
        trap_nonce_sha256=nonce,
        target_sha256=target.target_sha256,
        target=target,
        address_family=family,
        socket_type=socket_type,
        socket_protocol=protocol,
        controller_descriptor=descriptor,
        device=device,
        inode=inode,
        getsockname_sockaddr_hex=target.positive_control.target_sockaddr_hex,
        getsockname_sockaddr_length=target.positive_control.target_sockaddr_length,
        getsockname_sockaddr_sha256=target.positive_control.target_sockaddr_sha256,
        getsockname_endpoint_sha256=endpoint,
        socket_identity_sha256=socket_identity,
        bound_at_monotonic_ns=1,
        observed_at_monotonic_ns=observed,
        accept_count=0,
        datagram_count=0,
        byte_count=0,
    )


def _process(role: str) -> contracts.KernelSandboxProcessIdentity:
    pid = {
        "parser_worker": 1_001,
        "tesseract_broker": 2_001,
        "tesseract_child": 3_001,
    }[role]
    broker_pid = 2_001
    return _record(
        contracts.KernelSandboxProcessIdentity,
        role=role,
        pid=pid,
        start_abstime=pid + 100,
        parent_pid=(broker_pid if role == "tesseract_child" else 900),
        process_group_id=(broker_pid if role == "tesseract_child" else pid),
        session_id=(broker_pid if role == "tesseract_child" else pid),
        real_uid=UID,
        effective_uid=UID,
    )


def _authority(role: str) -> contracts.KernelSandboxAuthorityIdentity:
    pid = 800 if role == "logical_controller" else 900
    return _record(
        contracts.KernelSandboxAuthorityIdentity,
        role=role,
        pid=pid,
        start_abstime=pid + 100,
        parent_pid=(700 if role == "logical_controller" else 800),
        process_group_id=(pid if role == "watchdog_launcher" else 800),
        session_id=(pid if role == "watchdog_launcher" else 800),
        real_uid=UID,
        effective_uid=UID,
    )


def _profile(role: str) -> contracts.KernelSandboxProfilePolicy:
    paths = {
        "artifact_root": "/private/tmp/lat-us02/production-artifacts",
        "tessdata_root": "/private/tmp/lat-us02/production-tessdata",
        "request_root": "/private/tmp/lat-us02/request",
        "input_probe_root": "/private/tmp/lat-us02/probes/input-read",
        "immutable_executable": "/private/tmp/lat-us02/stage/tesseract",
        "outside_probe_root": "/private/tmp/lat-us02/outside-probes",
        "network_trap_root": "/private/tmp/lat-us02/probes/network-traps",
        "artifact_probe_clone_root": "/private/tmp/lat-us02/probes/artifact",
        "tessdata_probe_clone_root": "/private/tmp/lat-us02/probes/tessdata",
        "staged_executable_probe_clone_root": (
            "/private/tmp/lat-us02/probes/staged-executable"
        ),
    }
    worker = role == "parser_worker"
    worker_scratch = paths["request_root"] if worker else None
    template = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-profile-template-v1",
            "role": role,
            "network_outbound_denied": True,
            "network_inbound_denied": True,
            "process_fork_denied": worker,
            "deny_all_file_writes": not worker,
            "worker_scratch_exception_count": int(worker),
            "artifact_subpath_denied": True,
            "tessdata_subpath_denied": True,
            "immutable_executable_literal_denied": True,
            "request_root_subpath_denied": not worker,
            "outside_probe_root_bound": True,
            "network_trap_root_bound": True,
            "input_probe_root_denied": True,
            "private_probe_clone_count": 3,
            "artifact_probe_clone_denied": True,
            "tessdata_probe_clone_denied": True,
            "staged_executable_probe_clone_denied": True,
        }
    )
    return _record(
        contracts.KernelSandboxProfilePolicy,
        role=role,
        **paths,
        artifact_read_relative_path="model.bin",
        tessdata_read_relative_path="eng.traineddata",
        input_probe_relative_path="input.bin",
        worker_scratch_root=worker_scratch,
        artifact_root_sha256=hashlib.sha256(paths["artifact_root"].encode()).hexdigest(),
        tessdata_root_sha256=hashlib.sha256(paths["tessdata_root"].encode()).hexdigest(),
        request_root_sha256=hashlib.sha256(paths["request_root"].encode()).hexdigest(),
        input_probe_root_sha256=hashlib.sha256(
            paths["input_probe_root"].encode()
        ).hexdigest(),
        immutable_executable_sha256=hashlib.sha256(
            paths["immutable_executable"].encode()
        ).hexdigest(),
        outside_probe_root_sha256=hashlib.sha256(
            paths["outside_probe_root"].encode()
        ).hexdigest(),
        network_trap_root_sha256=hashlib.sha256(
            paths["network_trap_root"].encode()
        ).hexdigest(),
        artifact_probe_clone_root_sha256=hashlib.sha256(
            paths["artifact_probe_clone_root"].encode()
        ).hexdigest(),
        tessdata_probe_clone_root_sha256=hashlib.sha256(
            paths["tessdata_probe_clone_root"].encode()
        ).hexdigest(),
        staged_executable_probe_clone_root_sha256=hashlib.sha256(
            paths["staged_executable_probe_clone_root"].encode()
        ).hexdigest(),
        worker_scratch_root_sha256=(
            hashlib.sha256(worker_scratch.encode()).hexdigest()
            if worker_scratch is not None
            else None
        ),
        process_fork_denied=worker,
        deny_all_file_writes=not worker,
        template_sha256=template,
    )


def _custody(kind: str) -> str:
    return _sha(f"configured-{kind}-custody")


def _target_fixture(
    operation: str,
    policy: contracts.KernelSandboxProfilePolicy,
) -> contracts.KernelSandboxPolicyTargetFixture:
    if operation.startswith("artifact_"):
        kind = "artifact_private_clone"
        root_path = policy.artifact_probe_clone_root
        binding = policy.artifact_probe_clone_root_sha256
        custody = _custody("artifact-private-clone")
    elif operation.startswith("tessdata_"):
        kind = "tessdata_private_clone"
        root_path = policy.tessdata_probe_clone_root
        binding = policy.tessdata_probe_clone_root_sha256
        custody = _custody("tessdata-private-clone")
    elif operation.startswith("staged_executable_"):
        kind = "staged_executable_private_clone"
        root_path = policy.staged_executable_probe_clone_root
        binding = policy.staged_executable_probe_clone_root_sha256
        custody = _custody("staged-private-clone")
    else:
        kind = "outside_probe_root"
        root_path = policy.outside_probe_root
        binding = policy.outside_probe_root_sha256
        custody = _custody("outside")
    relative = f"{operation}.probe"
    target_path = f"{root_path}/{relative}"
    target_sha = hashlib.sha256(target_path.encode()).hexdigest()
    exists = operation not in {"outside_create", "outside_mkdir"}
    secondary_relative = "outside-rename-destination.probe" if operation == "outside_rename" else None
    secondary_sha = (
        hashlib.sha256(f"{root_path}/{secondary_relative}".encode()).hexdigest()
        if secondary_relative is not None
        else None
    )
    write_operations = {
        "outside_truncate",
        "artifact_write",
        "artifact_truncate",
        "tessdata_write",
        "tessdata_truncate",
        "staged_executable_write",
        "staged_executable_truncate",
    }
    root = _directory(root_path, f"{kind}-root")
    target_before = _sentinel(
        target_sha,
        root=root,
        target_name=relative,
        observed=19,
        exists=exists,
        dac=True,
        label=operation,
    )
    target_after = _sentinel(
        target_sha,
        root=root,
        target_name=relative,
        observed=31,
        exists=exists,
        dac=True,
        label=operation,
    )
    secondary_before = (
        _sentinel(
            secondary_sha,
            root=root,
            target_name=str(secondary_relative),
            observed=19,
            exists=False,
            dac=True,
            label="outside-rename-secondary",
            parent_inventory_jsonl=target_before.parent_directory_inventory_jsonl,
        )
        if secondary_sha is not None
        else None
    )
    secondary_after = (
        _sentinel(
            secondary_sha,
            root=root,
            target_name=str(secondary_relative),
            observed=31,
            exists=False,
            dac=True,
            label="outside-rename-secondary",
            parent_inventory_jsonl=target_after.parent_directory_inventory_jsonl,
        )
        if secondary_sha is not None
        else None
    )
    control_stage = (
        "rename"
        if operation == "outside_rename"
        else "unlink"
        if operation.endswith("unlink")
        else "mkdir"
        if operation == "outside_mkdir"
        else "open"
    )
    control_bytes = 8 if operation in write_operations else 0
    return _record(
        contracts.KernelSandboxPolicyTargetFixture,
        operation=operation,
        root=root,
        target_relative_path=relative,
        target_sha256=target_sha,
        secondary_target_relative_path=secondary_relative,
        secondary_target_sha256=secondary_sha,
        policy_binding_kind=kind,
        policy_binding_sha256=binding,
        configured_custody_sha256=custody,
        controller_uid=UID,
        controller_euid=UID,
        control_started_monotonic_ns=20,
        control_completed_monotonic_ns=30,
        target_before=target_before,
        target_after=target_after,
        secondary_target_before=secondary_before,
        secondary_target_after=secondary_after,
        same_operation_syscall_stage=control_stage,
        same_operation_syscall_return=91 if control_stage == "open" else 0,
        same_operation_opened_fd=91 if control_stage == "open" else None,
        same_operation_write_return=(
            control_bytes if control_stage == "open" else None
        ),
        control_bytes_written=control_bytes,
    )


def _read_fixture(
    operation: str,
    policy: contracts.KernelSandboxProfilePolicy,
) -> contracts.KernelSandboxReadFixture:
    kind = {
        "staged_executable_read": "production-staged",
        "tessdata_read": "production-tessdata",
        "input_read": "source",
        "artifact_read": "production-artifact",
    }[operation]
    if operation == "staged_executable_read":
        path = policy.immutable_executable
    elif operation == "tessdata_read":
        path = f"{policy.tessdata_root}/{policy.tessdata_read_relative_path}"
    elif operation == "input_read":
        path = f"{policy.input_probe_root}/{policy.input_probe_relative_path}"
    else:
        path = f"{policy.artifact_root}/{policy.artifact_read_relative_path}"
    root_path = os.path.dirname(path)
    relative = os.path.basename(path)
    return _record(
        contracts.KernelSandboxReadFixture,
        operation=operation,
        root=_directory(root_path, f"{operation}-read-root"),
        target_relative_path=relative,
        target_sha256=hashlib.sha256(path.encode()).hexdigest(),
        file_identity=_file(path, operation),
        configured_custody_sha256=_custody(kind),
    )


def _scratch_fixture(policy: contracts.KernelSandboxProfilePolicy):
    root = _directory(policy.worker_scratch_root, "worker-scratch")
    relative = "sandbox-control.bin"
    target_sha = hashlib.sha256(
        f"{policy.worker_scratch_root}/{relative}".encode()
    ).hexdigest()
    inventory = _sha("empty-worker-scratch-inventory")
    return _record(
        contracts.KernelSandboxScratchFixture,
        root=root,
        target_relative_path=relative,
        target_sha256=target_sha,
        inventory_before_sha256=inventory,
        inventory_after_sha256=inventory,
        intermediate_file_identity_sha256=_sha("scratch-intermediate-file"),
    )


def _capability(
    *,
    owner: contracts.KernelSandboxProcessIdentity,
    peer_role: str,
    peer_pid: int,
    peer_start: int,
    kind: str,
    descriptor: int,
) -> contracts.KernelSandboxCapabilityIdentity:
    pipe = kind.startswith("child_")
    close_on_exec = kind not in {
        "child_stdin_pipe",
        "child_stdout_pipe",
        "child_stderr_pipe",
    }
    peer_descriptor_number = (
        descriptor if kind == "worker_broker_rpc" else descriptor + 100
    )
    owner_endpoint_identity = _sha(
        f"{owner.role}-{owner.pid}-{owner.start_abstime}-{kind}-endpoint"
    )
    peer_endpoint_identity = _sha(
        f"{peer_role}-{peer_pid}-{peer_start}-{kind}-endpoint"
    )

    def descriptor_identity(
        *,
        fd: int,
        local_identity_sha256: str,
        peer_identity_sha256: str,
        descriptor_close_on_exec: bool,
    ) -> contracts.NativeFileDescriptorIdentity:
        nested: dict[str, Any]
        if pipe:
            nested = {
                "pipe": contracts.NativePipeFileDescriptorIdentity(
                    device=0,
                    inode=10_000 + fd + owner.pid,
                    mode=stat.S_IFIFO | 0o600,
                    nlink=1,
                    uid=UID,
                    gid=20,
                    pipe_status=0,
                    local_handle_sha256=local_identity_sha256,
                    peer_handle_sha256=peer_identity_sha256,
                )
            }
            kernel_type = 6
        else:
            nested = {
                "socket": contracts.NativeSocketFileDescriptorIdentity(
                    family=int(socket.AF_UNIX),
                    socket_type=int(socket.SOCK_STREAM),
                    protocol=0,
                    socket_kind=1,
                    socket_state=1,
                    local_identity_sha256=local_identity_sha256,
                    peer_identity_sha256=peer_identity_sha256,
                )
            }
            kernel_type = 2
        return _record(
            contracts.NativeFileDescriptorIdentity,
            fd=fd,
            kernel_type=kernel_type,
            open_flags=0,
            kernel_status_flags=0,
            descriptor_offset=0,
            descriptor_type=kernel_type,
            guard_flags=0,
            close_on_exec=descriptor_close_on_exec,
            close_on_fork=False,
            guarded=False,
            shared=False,
            **(
                {"vnode": None, "socket": None, "pipe": None, "kqueue": None}
                | nested
            ),
        )

    owner_descriptor = descriptor_identity(
        fd=descriptor,
        local_identity_sha256=owner_endpoint_identity,
        peer_identity_sha256=peer_endpoint_identity,
        descriptor_close_on_exec=close_on_exec,
    )
    peer_descriptor = descriptor_identity(
        fd=peer_descriptor_number,
        local_identity_sha256=peer_endpoint_identity,
        peer_identity_sha256=owner_endpoint_identity,
        descriptor_close_on_exec=(
            close_on_exec if kind == "worker_broker_rpc" else True
        ),
    )
    owner_endpoint = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-capability-endpoint-v1",
            "role": owner.role,
            "pid": owner.pid,
            "start_abstime": owner.start_abstime,
            "descriptor": owner_descriptor.model_dump(mode="json"),
        }
    )
    peer_endpoint = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-capability-endpoint-v1",
            "role": peer_role,
            "pid": peer_pid,
            "start_abstime": peer_start,
            "descriptor": peer_descriptor.model_dump(mode="json"),
        }
    )
    channel = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-capability-channel-v1",
            "capability_kind": kind,
            "endpoint_sha256s": sorted((owner_endpoint, peer_endpoint)),
        }
    )
    nonce = _sha(f"{owner.role}-{kind}-nonce")
    ack = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-capability-ack-v1",
            "channel_binding_sha256": channel,
            "nonce_sha256": nonce,
            "owner_pid": owner.pid,
            "owner_start_abstime": owner.start_abstime,
            "peer_pid": peer_pid,
            "peer_start_abstime": peer_start,
        }
    )
    return _record(
        contracts.KernelSandboxCapabilityIdentity,
        capability_kind=kind,
        descriptor=descriptor,
        owner_descriptor=owner_descriptor,
        peer_descriptor=peer_descriptor,
        descriptor_kind=("pipe" if pipe else "socket"),
        close_on_exec=close_on_exec,
        owner_role=owner.role,
        peer_role=peer_role,
        owner_pid=owner.pid,
        owner_start_abstime=owner.start_abstime,
        peer_pid=peer_pid,
        peer_start_abstime=peer_start,
        channel_binding_sha256=channel,
        peer_binding_sha256=peer_endpoint,
        controller_issued_nonce_sha256=nonce,
        controller_peer_ack_sha256=ack,
    )


def _capabilities(
    role: str,
    worker: contracts.KernelSandboxProcessIdentity,
    broker: contracts.KernelSandboxProcessIdentity,
    controller: contracts.KernelSandboxAuthorityIdentity,
    watchdog: contracts.KernelSandboxAuthorityIdentity,
):
    owner = {"parser_worker": worker, "tesseract_broker": broker, "tesseract_child": _process("tesseract_child")}[role]
    if role == "parser_worker":
        definitions = (
            ("worker_broker_rpc", "tesseract_broker", broker.pid, broker.start_abstime),
            ("request_control", "logical_controller", controller.pid, controller.start_abstime),
            ("phase_control", "logical_controller", controller.pid, controller.start_abstime),
        )
    elif role == "tesseract_broker":
        definitions = (
            ("worker_broker_rpc", "parser_worker", worker.pid, worker.start_abstime),
            ("broker_watchdog", "watchdog_launcher", watchdog.pid, watchdog.start_abstime),
        )
    else:
        definitions = tuple(
            (kind, "tesseract_broker", broker.pid, broker.start_abstime)
            for kind in (
                "child_stdin_pipe",
                "child_stdout_pipe",
                "child_stderr_pipe",
                "child_ready_pipe",
                "child_release_pipe",
            )
        )
    return tuple(
        _capability(
            owner=owner,
            peer_role=peer_role,
            peer_pid=peer_pid,
            peer_start=peer_start,
            kind=kind,
            descriptor=40 + index,
        )
        for index, (kind, peer_role, peer_pid, peer_start) in enumerate(definitions)
    )


def _probe_row(
    *,
    role: str,
    process: contracts.KernelSandboxProcessIdentity,
    policy: contracts.KernelSandboxProfilePolicy,
    helper_source: contracts.KernelSandboxFileIdentity,
    helper_executable: contracts.KernelSandboxFileIdentity,
    operation: str,
    sequence: int,
    previous: str,
    target_fixtures: dict[str, contracts.KernelSandboxPolicyTargetFixture],
    read_fixtures: dict[str, contracts.KernelSandboxReadFixture],
    capabilities: dict[str, contracts.KernelSandboxCapabilityIdentity],
    scratch: contracts.KernelSandboxScratchFixture | None,
) -> contracts.KernelSandboxProbeRow:
    started = 1_000 + {"parser_worker": 0, "tesseract_broker": 1_000, "tesseract_child": 2_000}[role] + sequence * 10
    completed = started + 4
    fields: dict[str, Any] = {
        "schema_id": "phase-latency-kernel-sandbox-probe-row-v1",
        "attempt_id": "attempt",
        "attempt_nonce_sha256": ATTEMPT_NONCE,
        "scope_sha256": SCOPE_SHA,
        "role": role,
        "profile_sha256": hashlib.sha256(policy.render_profile().encode()).hexdigest(),
        "profile_policy_sha256": policy.record_sha256,
        "helper_source_sha256": helper_source.content_sha256,
        "helper_executable_sha256": helper_executable.content_sha256,
        "process": process,
        "probe_sequence": sequence,
        "previous_probe_record_sha256": previous,
        "probe_id": f"{role}-probe-{sequence}-{operation}",
        "probe_nonce_sha256": _sha(f"{role}-{operation}-probe-nonce"),
        "expected_operation_matrix_sha256": contracts._kernel_sandbox_matrix_sha256(role),
        "operation": operation,
        "socket_type": None,
        "socket_protocol": None,
        "open_flags": None,
        "create_mode": None,
        "network_target": None,
        "directory_operation_anchor": None,
        "secondary_target_sha256": None,
        "policy_target_fixture_sha256": None,
        "known_read_fixture_sha256": None,
        "started_monotonic_ns": started,
        "completed_monotonic_ns": completed,
        "syscall_return": -1,
        "raw_errno": 1,
        "getaddrinfo_return_eai": None,
        "bytes_sent": 0,
        "bytes_received": 0,
        "trap_before": None,
        "trap_after": None,
        "target_before": None,
        "target_after": None,
        "secondary_target_before": None,
        "secondary_target_after": None,
        "allowed_read_sha256": None,
        "allowed_read_bytes": None,
        "intermediate_identity_sha256": None,
        "capability_identity": None,
        "frame_nonce_sha256": None,
        "peer_ack_nonce_sha256": None,
        "disposition": "denied",
        "authoritative_kernel_probe": True,
    }
    network = {
        "ipv4_tcp_connect": ("connect", "AF_INET", socket.SOCK_STREAM, socket.IPPROTO_TCP, "tcp_ipv4"),
        "ipv6_tcp_connect": ("connect", "AF_INET6", socket.SOCK_STREAM, socket.IPPROTO_TCP, "tcp_ipv6"),
        "ipv4_udp_sendto": ("sendto", "AF_INET", socket.SOCK_DGRAM, socket.IPPROTO_UDP, "udp_ipv4"),
        "ipv6_udp_sendto": ("sendto", "AF_INET6", socket.SOCK_DGRAM, socket.IPPROTO_UDP, "udp_ipv6"),
        "unix_connect": ("connect", "AF_UNIX", socket.SOCK_STREAM, 0, "unix_stream"),
        "ipv4_bind_listen": ("bind", "AF_INET", socket.SOCK_STREAM, socket.IPPROTO_TCP, None),
        "ipv6_bind_listen": ("bind", "AF_INET6", socket.SOCK_STREAM, socket.IPPROTO_TCP, None),
        "unix_bind": ("bind", "AF_UNIX", socket.SOCK_STREAM, 0, None),
    }
    if operation in network:
        stage, family, sock_type, protocol, trap_kind = network[operation]
        target = _network_target(role, operation)
        fields.update(
            syscall_stage=stage,
            address_family=family,
            socket_type=int(sock_type),
            socket_protocol=int(protocol),
            target_sha256=target.target_sha256,
            network_target=target,
        )
        if target.unix_root is not None and target.unix_relative_path is not None:
            fields["directory_operation_anchor"] = _directory_anchor(
                root=target.unix_root,
                primary=target.unix_relative_path,
                started=started,
                completed=completed,
            )
        if trap_kind is not None:
            fields["trap_before"] = _trap(
                kind=trap_kind,
                target=target,
                family=family,
                socket_type=int(sock_type),
                protocol=int(protocol),
                observed=started - 1,
                label=f"{role}-{operation}",
            )
            fields["trap_after"] = _trap(
                kind=trap_kind,
                target=target,
                family=family,
                socket_type=int(sock_type),
                protocol=int(protocol),
                observed=completed + 1,
                label=f"{role}-{operation}",
            )
        elif operation == "unix_bind":
            assert target.unix_root is not None
            assert target.unix_relative_path is not None
            fields["target_before"] = _sentinel(
                target.target_sha256,
                root=target.unix_root,
                target_name=target.unix_relative_path,
                observed=started - 1,
                exists=False,
                dac=True,
                label=f"{role}-{operation}-before",
            )
            fields["target_after"] = _sentinel(
                target.target_sha256,
                root=target.unix_root,
                target_name=target.unix_relative_path,
                observed=completed + 1,
                exists=False,
                dac=True,
                label=f"{role}-{operation}-after",
            )
    elif operation == "hostname_resolution":
        target = _network_target(role, operation)
        fields.update(
            syscall_stage="getaddrinfo",
            address_family="none",
            target_sha256=target.target_sha256,
            network_target=target,
            syscall_return=None,
            raw_errno=0,
            getaddrinfo_return_eai=-2,
            authoritative_kernel_probe=False,
        )
    elif operation in contracts.KERNEL_SANDBOX_FILE_DENIAL_OPERATIONS:
        fixture = target_fixtures[operation]
        flags = {
            "outside_create": os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            "outside_truncate": os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW,
            "artifact_write": os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            "artifact_truncate": os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW,
            "tessdata_write": os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            "tessdata_truncate": os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW,
            "staged_executable_write": os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            "staged_executable_truncate": os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW,
        }.get(operation)
        stage = (
            "rename"
            if operation == "outside_rename"
            else "unlink"
            if operation.endswith("unlink")
            else "mkdir"
            if operation == "outside_mkdir"
            else "open"
        )
        fields.update(
            syscall_stage=stage,
            address_family="none",
            open_flags=flags,
            create_mode=(0o600 if operation == "outside_create" else 0o700 if operation == "outside_mkdir" else None),
            target_sha256=fixture.target_sha256,
            secondary_target_sha256=fixture.secondary_target_sha256,
            policy_target_fixture_sha256=fixture.record_sha256,
            target_before=_replace(
                fixture.target_after, observed_at_monotonic_ns=started - 1
            ),
            target_after=_replace(
                fixture.target_after, observed_at_monotonic_ns=completed + 1
            ),
            secondary_target_before=(
                _replace(
                    fixture.secondary_target_after,
                    observed_at_monotonic_ns=started - 1,
                )
                if fixture.secondary_target_after is not None
                else None
            ),
            secondary_target_after=(
                _replace(
                    fixture.secondary_target_after,
                    observed_at_monotonic_ns=completed + 1,
                )
                if fixture.secondary_target_after is not None
                else None
            ),
            directory_operation_anchor=_directory_anchor(
                root=fixture.root,
                primary=fixture.target_relative_path,
                secondary=fixture.secondary_target_relative_path,
                started=started,
                completed=completed,
            ),
        )
    elif operation in read_fixtures:
        fixture = read_fixtures[operation]
        identity = fixture.file_identity
        fields.update(
            syscall_stage="read",
            address_family="none",
            open_flags=os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            target_sha256=fixture.target_sha256,
            known_read_fixture_sha256=fixture.record_sha256,
            syscall_return=identity.size_bytes,
            raw_errno=0,
            bytes_received=identity.size_bytes,
            disposition="allowed",
            allowed_read_sha256=identity.content_sha256,
            allowed_read_bytes=identity.size_bytes,
            target_before=_sentinel(
                fixture.target_sha256,
                root=fixture.root,
                target_name=fixture.target_relative_path,
                observed=started - 1,
                exists=True,
                dac=False,
                label=operation,
                identity_override={
                    "device": identity.device,
                    "inode": identity.inode,
                    "mode": identity.mode,
                    "uid": identity.uid,
                    "nlink": identity.nlink,
                    "size_bytes": identity.size_bytes,
                    "content_sha256": identity.content_sha256,
                },
            ),
            target_after=_sentinel(
                fixture.target_sha256,
                root=fixture.root,
                target_name=fixture.target_relative_path,
                observed=completed + 1,
                exists=True,
                dac=False,
                label=operation,
                identity_override={
                    "device": identity.device,
                    "inode": identity.inode,
                    "mode": identity.mode,
                    "uid": identity.uid,
                    "nlink": identity.nlink,
                    "size_bytes": identity.size_bytes,
                    "content_sha256": identity.content_sha256,
                },
            ),
            directory_operation_anchor=_directory_anchor(
                root=fixture.root,
                primary=fixture.target_relative_path,
                started=started,
                completed=completed,
            ),
        )
    elif operation == "worker_scratch_roundtrip":
        assert scratch is not None
        fields.update(
            syscall_stage="complete",
            address_family="none",
            open_flags=os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            create_mode=0o600,
            target_sha256=scratch.target_sha256,
            policy_target_fixture_sha256=scratch.record_sha256,
            syscall_return=0,
            raw_errno=0,
            bytes_sent=8,
            bytes_received=8,
            disposition="allowed",
            intermediate_identity_sha256=scratch.intermediate_file_identity_sha256,
            target_before=_sentinel(
                scratch.target_sha256,
                root=scratch.root,
                target_name=scratch.target_relative_path,
                observed=started - 1,
                exists=False,
                dac=False,
                label="scratch",
            ),
            target_after=_sentinel(
                scratch.target_sha256,
                root=scratch.root,
                target_name=scratch.target_relative_path,
                observed=completed + 1,
                exists=False,
                dac=False,
                label="scratch",
            ),
            directory_operation_anchor=_directory_anchor(
                root=scratch.root,
                primary=scratch.target_relative_path,
                started=started,
                completed=completed,
            ),
        )
    else:
        capability_by_operation = {
            "worker_broker_rpc_roundtrip": "worker_broker_rpc",
            "worker_request_control_roundtrip": "request_control",
            "worker_phase_control_roundtrip": "phase_control",
            "broker_worker_rpc_roundtrip": "worker_broker_rpc",
            "broker_watchdog_roundtrip": "broker_watchdog",
            "child_stdin_roundtrip": "child_stdin_pipe",
            "child_stdout_roundtrip": "child_stdout_pipe",
            "child_stderr_roundtrip": "child_stderr_pipe",
            "child_ready_roundtrip": "child_ready_pipe",
            "child_release_roundtrip": "child_release_pipe",
        }
        capability = capabilities[capability_by_operation[operation]]
        pipe = capability.descriptor_kind == "pipe"
        receive_only = capability.capability_kind in {
            "child_stdin_pipe",
            "child_release_pipe",
        }
        send_only = capability.capability_kind in {
            "child_stdout_pipe",
            "child_stderr_pipe",
            "child_ready_pipe",
        }
        fields.update(
            syscall_stage="complete",
            address_family=("none" if pipe else "AF_UNIX"),
            socket_type=(None if pipe else int(socket.SOCK_STREAM)),
            socket_protocol=(None if pipe else 0),
            target_sha256=capability.record_sha256,
            syscall_return=0,
            raw_errno=0,
            bytes_sent=(0 if receive_only else 8),
            bytes_received=(0 if send_only else 8),
            disposition="allowed",
            capability_identity=capability,
            frame_nonce_sha256=capability.controller_issued_nonce_sha256,
            peer_ack_nonce_sha256=capability.controller_issued_nonce_sha256,
        )
    parameters = {
        "syscall_stage": fields["syscall_stage"],
        "address_family": fields["address_family"],
        "socket_type": fields["socket_type"],
        "socket_protocol": fields["socket_protocol"],
        "open_flags": fields["open_flags"],
        "create_mode": fields["create_mode"],
        "target_sha256": fields["target_sha256"],
        "directory_operation_anchor_sha256": (
            fields["directory_operation_anchor"].record_sha256
            if fields["directory_operation_anchor"] is not None
            else None
        ),
        "secondary_target_sha256": fields["secondary_target_sha256"],
        "policy_target_fixture_sha256": fields["policy_target_fixture_sha256"],
        "known_read_fixture_sha256": fields["known_read_fixture_sha256"],
    }
    fields["syscall_parameters_sha256"] = contracts._canonical_hash(parameters)
    path_codes = {
        "outside_create": 1,
        "outside_truncate": 1,
        "outside_rename": 2,
        "outside_unlink": 3,
        "outside_mkdir": 4,
        "artifact_write": 1,
        "artifact_truncate": 1,
        "artifact_unlink": 3,
        "tessdata_write": 1,
        "tessdata_truncate": 1,
        "tessdata_unlink": 3,
        "staged_executable_write": 1,
        "staged_executable_truncate": 1,
        "staged_executable_unlink": 3,
        "staged_executable_read": 5,
        "tessdata_read": 5,
        "input_read": 5,
        "artifact_read": 5,
        "worker_scratch_roundtrip": 6,
    }
    network_codes = {
        "ipv4_tcp_connect": 1,
        "ipv6_tcp_connect": 1,
        "unix_connect": 1,
        "ipv4_udp_sendto": 2,
        "ipv6_udp_sendto": 2,
        "ipv4_bind_listen": 3,
        "ipv6_bind_listen": 3,
        "unix_bind": 3,
    }
    stage_codes = {
        "open": 2,
        "read": 5,
        "rename": 6,
        "unlink": 7,
        "mkdir": 8,
        "connect": 10,
        "sendto": 11,
        "bind": 12,
    }
    if operation in {*path_codes, *network_codes}:
        path_probe = operation in path_codes
        operation_code = (
            path_codes[operation] if path_probe else network_codes[operation]
        )
        anchor = fields["directory_operation_anchor"]
        payload = (
            b"probe123"
            if operation
            in {
                "worker_scratch_roundtrip",
                "ipv4_udp_sendto",
                "ipv6_udp_sendto",
            }
            else b""
        )
        invocation_fields = {
            "schema_id": "phase-latency-kernel-sandbox-native-invocation-v1",
            "abi_version": 2,
            "helper_function": (
                "lat_us02_sandbox_probe_path"
                if path_probe
                else "lat_us02_sandbox_probe_network"
            ),
            "operation_code": operation_code,
            "held_directory_fd": (
                anchor.held_directory_fd if anchor is not None else -1
            ),
            "primary_relative_path_hex": (
                anchor.primary_path_bytes_hex
                if path_probe and anchor is not None
                else None
            ),
            "secondary_relative_path_hex": (
                anchor.secondary_path_bytes_hex
                if path_probe and anchor is not None
                else None
            ),
            "open_flags": fields["open_flags"] if path_probe else None,
            "create_mode": fields["create_mode"] if path_probe else None,
            "domain": (
                None
                if path_probe
                else {
                    "AF_INET": int(socket.AF_INET),
                    "AF_INET6": int(socket.AF_INET6),
                    "AF_UNIX": int(socket.AF_UNIX),
                }[fields["address_family"]]
            ),
            "socket_type": fields["socket_type"] if not path_probe else None,
            "protocol": fields["socket_protocol"] if not path_probe else None,
            "sockaddr_hex": (
                fields["network_target"].positive_control.target_sockaddr_hex
                if not path_probe
                else None
            ),
            "payload_hex": payload.hex(),
            "payload_size_bytes": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "native_thread_identity_basis": (
                "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
            ),
            "native_thread_ids_before": (701,),
            "native_thread_ids_after": (701,),
            "prior_signal_mask": (),
            "blocked_signal_mask": tuple(
                sorted(
                    int(value)
                    for value in signal.valid_signals()
                    if value not in {signal.SIGKILL, signal.SIGSTOP}
                )
            ),
            "restored_signal_mask": (),
            "signals_blocked_at_monotonic_ns": started + 1,
            "syscall_returned_at_monotonic_ns": started + 2,
            "signals_restored_at_monotonic_ns": started + 3,
        }
        invocation = contracts.KernelSandboxNativeProbeInvocation(
            **invocation_fields,
            invocation_sha256=contracts._canonical_hash(invocation_fields),
        )
        terminal_stage = (
            7
            if operation == "worker_scratch_roundtrip"
            else stage_codes[fields["syscall_stage"]]
        )
        raw_struct = struct.pack(
            "<iiiiqqqii",
            2,
            operation_code,
            terminal_stage,
            int(fields["raw_errno"]),
            int(fields["syscall_return"]),
            int(fields["bytes_sent"]),
            int(fields["bytes_received"]),
            0,
            0,
        )
        result_fields = {
            "schema_id": "phase-latency-kernel-sandbox-native-result-v1",
            "abi_version": 2,
            "byte_order": "little-endian-darwin-v1",
            "struct_size_bytes": 48,
            "raw_struct_hex": raw_struct.hex(),
            "raw_struct_sha256": hashlib.sha256(raw_struct).hexdigest(),
            "operation_code": operation_code,
            "terminal_stage_code": terminal_stage,
            "raw_errno": fields["raw_errno"],
            "syscall_return": fields["syscall_return"],
            "bytes_sent": fields["bytes_sent"],
            "bytes_received": fields["bytes_received"],
            "cwd_restore_return": 0,
            "cwd_restore_errno": 0,
            "top_level_return": 0,
            "top_level_errno": fields["raw_errno"],
        }
        fields["native_invocation"] = invocation
        fields["native_result"] = _record(
            contracts.KernelSandboxNativeProbeResult, **result_fields
        )
    else:
        fields["native_invocation"] = None
        fields["native_result"] = None
    fields["probe_capability_sha256"] = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-probe-capability-v1",
            "attempt_nonce_sha256": ATTEMPT_NONCE,
            "scope_sha256": SCOPE_SHA,
            "role": role,
            "probe_sequence": sequence,
            "probe_nonce_sha256": fields["probe_nonce_sha256"],
            "process_record_sha256": process.record_sha256,
            "helper_executable_sha256": helper_executable.content_sha256,
            "expected_operation_matrix_sha256": fields["expected_operation_matrix_sha256"],
        }
    )
    fields["controller_observation_sha256"] = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-controller-observation-v1",
            "attempt_id": "attempt",
            "role": role,
            "probe_sequence": sequence,
            "probe_nonce_sha256": fields["probe_nonce_sha256"],
            "process_record_sha256": process.record_sha256,
            "started_monotonic_ns": started,
            "completed_monotonic_ns": completed,
            "syscall_parameters_sha256": fields["syscall_parameters_sha256"],
            "syscall_return": fields["syscall_return"],
            "raw_errno": fields["raw_errno"],
            "getaddrinfo_return_eai": fields["getaddrinfo_return_eai"],
            "bytes_sent": fields["bytes_sent"],
            "bytes_received": fields["bytes_received"],
            "native_invocation_sha256": (
                fields["native_invocation"].invocation_sha256
                if fields["native_invocation"] is not None
                else None
            ),
            "native_result_sha256": (
                fields["native_result"].record_sha256
                if fields["native_result"] is not None
                else None
            ),
            "trap_after_sha256": (
                fields["trap_after"].record_sha256 if fields["trap_after"] else None
            ),
            "target_after_sha256": (
                fields["target_after"].record_sha256 if fields["target_after"] else None
            ),
            "secondary_target_after_sha256": (
                fields["secondary_target_after"].record_sha256
                if fields["secondary_target_after"]
                else None
            ),
            "capability_record_sha256": (
                fields["capability_identity"].record_sha256
                if fields["capability_identity"]
                else None
            ),
        }
    )
    return _record(contracts.KernelSandboxProbeRow, **fields)


def _role(
    role: str,
    *,
    controller: contracts.KernelSandboxAuthorityIdentity,
    watchdog: contracts.KernelSandboxAuthorityIdentity,
    worker: contracts.KernelSandboxProcessIdentity,
    broker: contracts.KernelSandboxProcessIdentity,
) -> contracts.KernelSandboxRoleEvidence:
    process = {"parser_worker": worker, "tesseract_broker": broker, "tesseract_child": _process("tesseract_child")}[role]
    policy = _profile(role)
    helper_source = _file("/private/tmp/lat-us02/probe.c", "helper-source")
    helper_executable = _file("/private/tmp/lat-us02/probe", "helper-executable")
    target_fixtures_tuple = tuple(
        _target_fixture(operation, policy)
        for operation in contracts.KERNEL_SANDBOX_FILE_DENIAL_OPERATIONS
    )
    target_fixtures = {item.operation: item for item in target_fixtures_tuple}
    read_fixtures_tuple = tuple(
        _read_fixture(operation, policy)
        for operation in (
            "staged_executable_read",
            "tessdata_read",
            "input_read",
            "artifact_read",
        )
    )
    read_fixtures = {item.operation: item for item in read_fixtures_tuple}
    capabilities_tuple = _capabilities(role, worker, broker, controller, watchdog)
    capabilities = {item.capability_kind: item for item in capabilities_tuple}
    scratch = _scratch_fixture(policy) if role == "parser_worker" else None
    rows = []
    previous = ZERO_SHA
    for sequence, operation in enumerate(contracts._kernel_sandbox_operations(role), 1):
        row = _probe_row(
            role=role,
            process=process,
            policy=policy,
            helper_source=helper_source,
            helper_executable=helper_executable,
            operation=operation,
            sequence=sequence,
            previous=previous,
            target_fixtures=target_fixtures,
            read_fixtures=read_fixtures,
            capabilities=capabilities,
            scratch=scratch,
        )
        rows.append(row)
        previous = row.record_sha256
    rows_tuple = tuple(rows)
    last_completed = rows_tuple[-1].completed_monotonic_ns
    row_bytes = b"".join(contracts.canonical_model_bytes(row) + b"\n" for row in rows_tuple)
    executable = _file(f"/private/tmp/lat-us02/{role}", f"{role}-executable")
    native_process = contracts.NativeKernelProcessIdentity(
        pid=process.pid,
        start_abstime=process.start_abstime,
        ppid=process.parent_pid,
        pgid=process.process_group_id,
        sid=process.session_id,
    )
    inventory_descriptors = tuple(
        sorted(
            (item.owner_descriptor for item in capabilities_tuple),
            key=lambda item: item.fd,
        )
    )
    if role == "tesseract_broker":
        child_capabilities = _capabilities(
            "tesseract_child",
            worker,
            broker,
            controller,
            watchdog,
        )
        inventory_descriptors = tuple(
            sorted(
                (
                    *inventory_descriptors,
                    *(item.peer_descriptor for item in child_capabilities),
                ),
                key=lambda item: item.fd,
            )
        )
    inventory_fields = {
        "process": native_process,
        "descriptors": inventory_descriptors,
    }
    before_inventory = contracts.native_file_descriptor_inventory(
        **inventory_fields,
        first_scan_started_monotonic_ns=101,
        first_scan_completed_monotonic_ns=102,
        second_scan_started_monotonic_ns=103,
        second_scan_completed_monotonic_ns=104,
    )
    post_inventory_offset = (
        2_300
        if role == "parser_worker"
        else 1_100
        if role == "tesseract_broker"
        else 1
    )
    after_inventory = contracts.native_file_descriptor_inventory(
        **inventory_fields,
        first_scan_started_monotonic_ns=last_completed + post_inventory_offset,
        first_scan_completed_monotonic_ns=(
            last_completed + post_inventory_offset + 1
        ),
        second_scan_started_monotonic_ns=(
            last_completed + post_inventory_offset + 2
        ),
        second_scan_completed_monotonic_ns=(
            last_completed + post_inventory_offset + 3
        ),
    )
    return _record(
        contracts.KernelSandboxRoleEvidence,
        attempt_id="attempt",
        attempt_nonce_sha256=ATTEMPT_NONCE,
        scope_sha256=SCOPE_SHA,
        role=role,
        policy_application_kind=("inherited_broker_profile" if role == "tesseract_child" else "direct_sandbox_exec"),
        final_profile_utf8=policy.render_profile(),
        final_profile_sha256=hashlib.sha256(policy.render_profile().encode()).hexdigest(),
        profile_policy_sha256=policy.record_sha256,
        profile_policy=policy,
        sandbox_exec_identity=_file("/usr/bin/sandbox-exec", "sandbox-exec"),
        platform_release="25.6.0",
        platform_build="25G86",
        machine_architecture="arm64",
        process_before=process,
        process_after=process,
        parent_broker=(broker if role == "tesseract_child" else None),
        inherited_broker_profile_sha256=(hashlib.sha256(_profile("tesseract_broker").render_profile().encode()).hexdigest() if role == "tesseract_child" else None),
        executable_identity=executable,
        helper_source_identity=helper_source,
        helper_executable_identity=helper_executable,
        helper_argv_sha256=_sha(f"{role}-helper-argv"),
        helper_environment_sha256=_sha("helper-environment"),
        guard_to_exec_transition_sha256=(_sha("guard-exec-transition") if role == "tesseract_child" else None),
        native_closure_sha256=_sha("native-closure"),
        read_fixtures=read_fixtures_tuple,
        policy_target_fixtures=target_fixtures_tuple,
        worker_scratch_fixture=scratch,
        capabilities=capabilities_tuple,
        file_descriptor_inventory_before_probes=before_inventory,
        file_descriptor_inventory_after_probes=after_inventory,
        sandbox_applied_at_monotonic_ns=100,
        rlimit_nproc_soft=(0 if role != "tesseract_broker" else None),
        rlimit_nproc_hard=(0 if role != "tesseract_broker" else None),
        nproc_applied_at_monotonic_ns=(110 if role != "tesseract_broker" else None),
        ready_published_at_monotonic_ns=(
            after_inventory.second_scan_completed_monotonic_ns + 6
            if role != "tesseract_child"
            else None
        ),
        exec_release_e_monotonic_ns=(last_completed + 10 if role == "tesseract_child" else None),
        rows=rows_tuple,
        expected_operation_matrix_sha256=contracts._kernel_sandbox_matrix_sha256(role),
        row_log_sha256=hashlib.sha256(row_bytes).hexdigest(),
        row_log_count=len(rows_tuple),
        row_log_size_bytes=len(row_bytes),
        pre_exec_release_e=(role == "tesseract_child"),
    )


def _valid_evidence() -> contracts.KernelSandboxEvidence:
    controller = _authority("logical_controller")
    watchdog = _authority("watchdog_launcher")
    worker_process = _process("parser_worker")
    broker_process = _process("tesseract_broker")
    worker = _role("parser_worker", controller=controller, watchdog=watchdog, worker=worker_process, broker=broker_process)
    broker = _role("tesseract_broker", controller=controller, watchdog=watchdog, worker=worker_process, broker=broker_process)
    child = _role("tesseract_child", controller=controller, watchdog=watchdog, worker=worker_process, broker=broker_process)
    roles = (worker, broker, child)
    capabilities = tuple(item for role in roles for item in role.capabilities)
    transcripts = []
    previous = ZERO_SHA
    for sequence, capability in enumerate(capabilities, 1):
        receive_only = capability.capability_kind in {
            "child_stdin_pipe",
            "child_release_pipe",
        }
        send_only = capability.capability_kind in {
            "child_stdout_pipe",
            "child_stderr_pipe",
            "child_ready_pipe",
        }
        transcript = _record(
            contracts.KernelSandboxCapabilityTranscriptRow,
            row_sequence=sequence,
            previous_row_sha256=previous,
            owner_role=capability.owner_role,
            capability_kind=capability.capability_kind,
            capability_record_sha256=capability.record_sha256,
            channel_binding_sha256=capability.channel_binding_sha256,
            owner_pid=capability.owner_pid,
            owner_start_abstime=capability.owner_start_abstime,
            peer_pid=capability.peer_pid,
            peer_start_abstime=capability.peer_start_abstime,
            controller_issued_nonce_sha256=capability.controller_issued_nonce_sha256,
            peer_ack_sha256=capability.controller_peer_ack_sha256,
            bytes_sent=(0 if receive_only else 8),
            bytes_received=(0 if send_only else 8),
            issued_at_monotonic_ns=200 + sequence * 3,
            acknowledged_at_monotonic_ns=201 + sequence * 3,
            retained_at_monotonic_ns=202 + sequence * 3,
        )
        transcripts.append(transcript)
        previous = transcript.record_sha256
    transcripts_tuple = tuple(transcripts)
    transcript_bytes = b"".join(contracts.canonical_model_bytes(item) + b"\n" for item in transcripts_tuple)
    last_row_time = max(row.completed_monotonic_ns for role in roles for row in role.rows)
    terminal = _record(
        contracts.KernelSandboxAttemptTerminalCustody,
        attempt_id="attempt",
        attempt_nonce_sha256=ATTEMPT_NONCE,
        scope_sha256=SCOPE_SHA,
        worker=worker_process,
        broker=broker_process,
        worker_wait_record_sha256=_sha("worker-wait"),
        broker_wait_record_sha256=_sha("broker-wait"),
        worker_reaped_at_monotonic_ns=last_row_time + 20,
        broker_reaped_at_monotonic_ns=last_row_time + 21,
        worker_group_esrch_at_monotonic_ns=last_row_time + 22,
        broker_group_esrch_at_monotonic_ns=last_row_time + 23,
        registered_child_count=1,
        last_child_wait4_record_sha256=_sha("child-wait4"),
        last_child_wait4_observed_monotonic_ns=last_row_time + 19,
        watchdog_terminal_record_sha256=_sha("watchdog-terminal"),
        terminal_observed_monotonic_ns=last_row_time + 24,
    )
    terminals = []
    previous = ZERO_SHA
    for sequence, (row, source_trap) in enumerate(
        (
            (row, row.trap_after)
            for role in roles
            for row in role.rows
            if row.trap_after is not None
        ),
        1,
    ):
        assert source_trap is not None
        fresh = _trap(
            kind=source_trap.trap_kind,
            target=source_trap.target,
            family=source_trap.address_family,
            socket_type=source_trap.socket_type,
            protocol=source_trap.socket_protocol,
            observed=terminal.terminal_observed_monotonic_ns + sequence,
            label=f"{role.role if False else source_trap.trap_nonce_sha256}",
        )
        fresh = _replace(
            fresh,
            trap_nonce_sha256=source_trap.trap_nonce_sha256,
            device=source_trap.device,
            inode=source_trap.inode,
            getsockname_endpoint_sha256=(
                source_trap.getsockname_endpoint_sha256
            ),
            socket_identity_sha256=source_trap.socket_identity_sha256,
            controller_descriptor=source_trap.controller_descriptor,
            bound_at_monotonic_ns=source_trap.bound_at_monotonic_ns,
        )
        item = _record(
            contracts.KernelSandboxTerminalTrapObservation,
            terminal_sequence=sequence,
            previous_terminal_record_sha256=previous,
            source_probe_record_sha256=row.record_sha256,
            source_trap_record_sha256=source_trap.record_sha256,
            attempt_terminal_record_sha256=terminal.record_sha256,
            attempt_terminal_observed_monotonic_ns=terminal.terminal_observed_monotonic_ns,
            trap=fresh,
        )
        terminals.append(item)
        previous = item.record_sha256
    terminals_tuple = tuple(terminals)
    terminal_bytes = b"".join(contracts.canonical_model_bytes(item) + b"\n" for item in terminals_tuple)
    authority_after_time = max(
        item.trap.observed_at_monotonic_ns for item in terminals_tuple
    ) + 1
    pairing = contracts._canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-pairing-v1",
            "roles": tuple(
                {
                    "role": item.role,
                    "policy_application_kind": item.policy_application_kind,
                    "profile_template_sha256": item.profile_policy.template_sha256,
                    "sandbox_exec_sha256": item.sandbox_exec_identity.content_sha256,
                    "helper_source_sha256": item.helper_source_identity.content_sha256,
                    "helper_executable_sha256": item.helper_executable_identity.content_sha256,
                    "native_closure_sha256": item.native_closure_sha256,
                    "native_trust_model": item.native_trust_model,
                    "native_containment_claim": item.native_containment_claim,
                    "matrix_sha256": item.expected_operation_matrix_sha256,
                }
                for item in roles
            ),
        }
    )

    def authority_inventories(
        authority: contracts.KernelSandboxAuthorityIdentity,
        descriptors: tuple[contracts.NativeFileDescriptorIdentity, ...],
    ) -> tuple[
        contracts.NativeFileDescriptorInventory,
        contracts.NativeFileDescriptorInventory,
    ]:
        process = contracts.NativeKernelProcessIdentity(
            pid=authority.pid,
            start_abstime=authority.start_abstime,
            ppid=authority.parent_pid,
            pgid=authority.process_group_id,
            sid=authority.session_id,
        )
        common = {
            "process": process,
            "descriptors": tuple(sorted(descriptors, key=lambda item: item.fd)),
        }
        return (
            contracts.native_file_descriptor_inventory(
                **common,
                first_scan_started_monotonic_ns=51,
                first_scan_completed_monotonic_ns=52,
                second_scan_started_monotonic_ns=53,
                second_scan_completed_monotonic_ns=54,
            ),
            contracts.native_file_descriptor_inventory(
                **common,
                first_scan_started_monotonic_ns=authority_after_time,
                first_scan_completed_monotonic_ns=authority_after_time + 1,
                second_scan_started_monotonic_ns=authority_after_time + 2,
                second_scan_completed_monotonic_ns=authority_after_time + 3,
            ),
        )

    controller_inventories = authority_inventories(
        controller,
        tuple(
            {
                descriptor.record_sha256: descriptor
                for descriptor in (
                    *(
                        capability.peer_descriptor
                        for capability in worker.capabilities
                        if capability.peer_role == "logical_controller"
                    ),
                    *(
                        row.trap_after.controller_descriptor
                        for role in roles
                        for row in role.rows
                        if row.trap_after is not None
                    ),
                )
            }.values()
        ),
    )
    watchdog_inventories = authority_inventories(
        watchdog,
        tuple(
            capability.peer_descriptor
            for capability in broker.capabilities
            if capability.peer_role == "watchdog_launcher"
        ),
    )
    return _record(
        contracts.KernelSandboxEvidence,
        attempt_id="attempt",
        attempt_nonce_sha256=ATTEMPT_NONCE,
        scope_sha256=SCOPE_SHA,
        logical_controller=controller,
        watchdog_launcher=watchdog,
        logical_controller_fd_inventory_before_probes=controller_inventories[0],
        logical_controller_fd_inventory_after_probes=controller_inventories[1],
        watchdog_launcher_fd_inventory_before_probes=watchdog_inventories[0],
        watchdog_launcher_fd_inventory_after_probes=watchdog_inventories[1],
        source_custody_sha256=_custody("source"),
        production_artifact_custody_sha256=_custody("production-artifact"),
        production_tessdata_custody_sha256=_custody("production-tessdata"),
        production_staged_executable_custody_sha256=_custody(
            "production-staged"
        ),
        artifact_private_clone_custody_sha256=_custody(
            "artifact-private-clone"
        ),
        tessdata_private_clone_custody_sha256=_custody(
            "tessdata-private-clone"
        ),
        staged_executable_private_clone_custody_sha256=_custody(
            "staged-private-clone"
        ),
        outside_probe_root_custody_sha256=_custody("outside"),
        approved_sandbox_exec_sha256=worker.sandbox_exec_identity.content_sha256,
        approved_helper_source_sha256=worker.helper_source_identity.content_sha256,
        approved_helper_executable_sha256=worker.helper_executable_identity.content_sha256,
        approved_worker_executable_sha256=worker.executable_identity.content_sha256,
        approved_broker_executable_sha256=broker.executable_identity.content_sha256,
        approved_child_executable_sha256=child.executable_identity.content_sha256,
        worker=worker,
        broker=broker,
        child=child,
        attempt_terminal=terminal,
        capability_transcript_rows=transcripts_tuple,
        terminal_trap_observations=terminals_tuple,
        capability_transcript_log_sha256=hashlib.sha256(transcript_bytes).hexdigest(),
        capability_transcript_log_count=len(transcripts_tuple),
        capability_transcript_log_size_bytes=len(transcript_bytes),
        terminal_trap_log_sha256=hashlib.sha256(terminal_bytes).hexdigest(),
        terminal_trap_log_count=len(terminals_tuple),
        terminal_trap_log_size_bytes=len(terminal_bytes),
        pairing_projection_sha256=pairing,
    )


def test_kernel_sandbox_evidence_recomputes_closed_matrix() -> None:
    evidence = _valid_evidence()
    assert evidence.hosted_calls == 0
    assert evidence.capability_transcript_log_count == 10
    assert evidence.terminal_trap_log_count == 15


def test_kernel_sandbox_rejects_permissive_profile_and_wrong_target_root() -> None:
    evidence = _valid_evidence()
    with pytest.raises(ValidationError, match="role binding"):
        _replace(
            evidence.worker,
            final_profile_utf8="(version 1)(allow default)",
            final_profile_sha256=hashlib.sha256(
                b"(version 1)(allow default)"
            ).hexdigest(),
        )
    fixture = evidence.worker.policy_target_fixtures[0]
    with pytest.raises(ValidationError, match="target|DAC-positive"):
        _replace(
            evidence.worker,
            policy_target_fixtures=(
                _replace(
                    fixture,
                    root=_directory("/private/tmp/unrelated", "unrelated"),
                    target_relative_path="outside_create.probe",
                    target_sha256=hashlib.sha256(
                        b"/private/tmp/unrelated/outside_create.probe"
                    ).hexdigest(),
                ),
                *evidence.worker.policy_target_fixtures[1:],
            ),
        )


def test_kernel_sandbox_rejects_unjoined_dac_and_read_custody() -> None:
    evidence = _valid_evidence()
    fixture = evidence.worker.policy_target_fixtures[1]
    with pytest.raises(ValidationError, match="DAC-positive"):
        _replace(
            fixture,
            target_before=_replace(
                fixture.target_before,
                parent_writable_by_effective_uid=False,
            ),
        )
    read = evidence.worker.read_fixtures[0]
    with pytest.raises(ValidationError, match="allowed read|configured custody"):
        _replace(
            evidence,
            worker=_replace(
                evidence.worker,
                read_fixtures=(
                    _replace(read, configured_custody_sha256=_sha("wrong")),
                    *evidence.worker.read_fixtures[1:],
                ),
            ),
        )
    with pytest.raises(ValidationError, match="configured custody"):
        _replace(
            evidence,
            production_artifact_custody_sha256=_sha(
                "substituted-production-artifact-custody"
            ),
        )
    with pytest.raises(ValidationError, match="configured custody"):
        _replace(
            evidence,
            artifact_private_clone_custody_sha256=_sha(
                "substituted-artifact-private-clone-custody"
            ),
        )


def test_kernel_sandbox_rejects_peer_and_controller_transcript_splice() -> None:
    evidence = _valid_evidence()
    capability = evidence.worker.capabilities[0]
    with pytest.raises(ValidationError, match="capability"):
        _replace(
            evidence,
            worker=_replace(
                evidence.worker,
                capabilities=(
                    _replace(capability, peer_pid=9_999),
                    *evidence.worker.capabilities[1:],
                ),
            ),
        )
    assert capability.owner_descriptor.socket is not None
    substituted_socket = capability.owner_descriptor.socket.model_copy(
        update={"local_identity_sha256": _sha("substituted-socket-endpoint")}
    )
    substituted_descriptor = _replace(
        capability.owner_descriptor,
        socket=substituted_socket,
    )
    with pytest.raises(ValidationError, match="capability"):
        _replace(capability, owner_descriptor=substituted_descriptor)

    before_inventory = evidence.worker.file_descriptor_inventory_before_probes
    substituted_inventory = contracts.native_file_descriptor_inventory(
        process=before_inventory.process,
        first_scan_started_monotonic_ns=(
            before_inventory.first_scan_started_monotonic_ns
        ),
        first_scan_completed_monotonic_ns=(
            before_inventory.first_scan_completed_monotonic_ns
        ),
        second_scan_started_monotonic_ns=(
            before_inventory.second_scan_started_monotonic_ns
        ),
        second_scan_completed_monotonic_ns=(
            before_inventory.second_scan_completed_monotonic_ns
        ),
        descriptors=(
            substituted_descriptor,
            *before_inventory.descriptors[1:],
        ),
    )
    with pytest.raises(ValidationError, match="capability FD inventory"):
        _replace(
            evidence.worker,
            file_descriptor_inventory_before_probes=substituted_inventory,
        )
    controller_before = (
        evidence.logical_controller_fd_inventory_before_probes
    )
    substituted_peer_descriptor = _replace(
        controller_before.descriptors[0],
        fd=918,
    )
    substituted_controller_inventory = contracts.native_file_descriptor_inventory(
        process=controller_before.process,
        first_scan_started_monotonic_ns=(
            controller_before.first_scan_started_monotonic_ns
        ),
        first_scan_completed_monotonic_ns=(
            controller_before.first_scan_completed_monotonic_ns
        ),
        second_scan_started_monotonic_ns=(
            controller_before.second_scan_started_monotonic_ns
        ),
        second_scan_completed_monotonic_ns=(
            controller_before.second_scan_completed_monotonic_ns
        ),
        descriptors=tuple(
            sorted(
                (
                    substituted_peer_descriptor,
                    *controller_before.descriptors[1:],
                ),
                key=lambda item: item.fd,
            )
        ),
    )
    with pytest.raises(ValidationError, match="authority FD inventory|peer FD"):
        _replace(
            evidence,
            logical_controller_fd_inventory_before_probes=(
                substituted_controller_inventory
            ),
        )
    transcript = evidence.capability_transcript_rows[0]
    with pytest.raises(ValidationError, match="capability transcript"):
        _replace(
            evidence,
            capability_transcript_rows=(
                _replace(transcript, bytes_received=9),
                *evidence.capability_transcript_rows[1:],
            ),
        )


def test_kernel_sandbox_rejects_early_terminal_trap_and_wrong_topology() -> None:
    evidence = _valid_evidence()
    terminal = evidence.terminal_trap_observations[0]
    source = next(
        row.trap_after
        for role in (evidence.worker, evidence.broker, evidence.child)
        for row in role.rows
        if row.record_sha256 == terminal.source_probe_record_sha256
    )
    assert source is not None
    with pytest.raises(ValidationError, match="terminal trap"):
        _replace(terminal, trap=source)
    child_process = evidence.child.process_before
    with pytest.raises(ValidationError, match="inheritance"):
        _replace(
            evidence.child,
            process_before=_replace(child_process, parent_pid=9_999),
            process_after=_replace(child_process, parent_pid=9_999),
        )


def test_kernel_sandbox_rejects_scratch_escape_and_helper_drift() -> None:
    evidence = _valid_evidence()
    scratch = evidence.worker.worker_scratch_fixture
    assert scratch is not None
    with pytest.raises(ValidationError, match="scratch fixture"):
        _replace(
            evidence.worker,
            worker_scratch_fixture=_replace(
                scratch,
                root=_directory("/private/tmp/elsewhere", "elsewhere"),
                target_sha256=hashlib.sha256(
                    b"/private/tmp/elsewhere/sandbox-control.bin"
                ).hexdigest(),
            ),
        )
    with pytest.raises(ValidationError, match="child/profile closure"):
        _replace(
            evidence,
            approved_helper_executable_sha256=_sha("unapproved-helper"),
        )


def test_kernel_sandbox_rejects_mutable_or_unbracketed_helper_bytes() -> None:
    evidence = _valid_evidence()
    with pytest.raises(ValidationError, match="file identity"):
        _replace(
            evidence.worker.helper_executable_identity,
            mode=stat.S_IFREG | 0o522,
        )
    with pytest.raises(ValidationError, match="observation window"):
        _replace(
            evidence.worker,
            helper_executable_identity=_replace(
                evidence.worker.helper_executable_identity,
                second_observed_at_monotonic_ns=(
                    evidence.worker.ready_published_at_monotonic_ns - 1
                ),
            ),
        )


@pytest.mark.parametrize(
    "scratch_path",
    ("/", "/private/tmp/lat-us02/outside-probes"),
)
def test_kernel_sandbox_rejects_overlapping_worker_scratch(
    scratch_path: str,
) -> None:
    policy = _valid_evidence().worker.profile_policy
    with pytest.raises(ValidationError, match="worker sandbox policy|roots overlap"):
        _replace(
            policy,
            worker_scratch_root=scratch_path,
            worker_scratch_root_sha256=hashlib.sha256(
                scratch_path.encode("utf-8")
            ).hexdigest(),
        )


def test_kernel_sandbox_probe_clones_cannot_alias_production_or_each_other() -> None:
    policy = _profile("parser_worker")
    rendered = policy.render_profile()
    assert policy.artifact_root in rendered
    assert policy.tessdata_root in rendered
    assert policy.input_probe_root in rendered
    assert policy.network_trap_root in rendered
    assert policy.artifact_probe_clone_root in rendered
    assert policy.tessdata_probe_clone_root in rendered
    assert policy.staged_executable_probe_clone_root in rendered

    with pytest.raises(ValidationError, match="path identity|roots overlap"):
        _replace(
            policy,
            artifact_probe_clone_root=policy.artifact_root,
            artifact_probe_clone_root_sha256=policy.artifact_root_sha256,
        )
    with pytest.raises(ValidationError, match="path identity|roots overlap"):
        _replace(
            policy,
            artifact_probe_clone_root=policy.tessdata_probe_clone_root,
            artifact_probe_clone_root_sha256=(
                policy.tessdata_probe_clone_root_sha256
            ),
        )
    with pytest.raises(ValidationError, match="path identity|roots overlap"):
        _replace(
            policy,
            input_probe_root=policy.request_root,
            input_probe_root_sha256=policy.request_root_sha256,
        )
    with pytest.raises(ValidationError, match="path identity|roots overlap"):
        _replace(
            policy,
            network_trap_root=policy.outside_probe_root,
            network_trap_root_sha256=policy.outside_probe_root_sha256,
        )


def test_kernel_sandbox_input_probe_relative_path_is_not_opaque() -> None:
    evidence = _valid_evidence()
    with pytest.raises(
        ValidationError,
        match="role binding|read fixture path custody",
    ):
        _replace(
            evidence.worker,
            profile_policy=_replace(
                evidence.worker.profile_policy,
                input_probe_relative_path="substituted-input.bin",
            ),
        )


def test_kernel_sandbox_rejects_privileged_or_spliced_network_target() -> None:
    target = _network_target("parser_worker", "ipv4_tcp_connect")
    fields = target.model_dump(mode="python", exclude={"target_sha256"})
    fields["port"] = 80
    with pytest.raises(ValidationError, match="target authority"):
        contracts.KernelSandboxNetworkTarget(
            **fields,
            target_sha256=contracts._canonical_hash(fields),
        )

    unix_target = _network_target("parser_worker", "unix_connect")
    unix_fields = unix_target.model_dump(mode="python", exclude={"target_sha256"})
    long_root = _directory(
        "/private/tmp/" + ("x" * 96),
        "overlong-network-root",
    )
    long_path = (
        f"{long_root.resolved_path}/{unix_target.unix_relative_path}"
    ).encode("utf-8")
    raw_sockaddr = bytes(
        (3 + len(long_path), int(socket.AF_UNIX))
    ) + long_path + b"\0"
    unix_fields.update(
        unix_root=long_root,
        unix_sockaddr_hex=raw_sockaddr.hex(),
        unix_sockaddr_length=len(raw_sockaddr),
        unix_sockaddr_sha256=hashlib.sha256(raw_sockaddr).hexdigest(),
    )
    with pytest.raises(ValidationError, match="AF_UNIX|sockaddr|length"):
        provisional = contracts.KernelSandboxNetworkTarget.model_construct(
            **unix_fields,
            target_sha256=ZERO_SHA,
        )
        contracts.KernelSandboxNetworkTarget(
            **unix_fields,
            target_sha256=contracts._canonical_hash(
                provisional.model_dump(mode="json", exclude={"target_sha256"})
            ),
        )

    worker = _valid_evidence().worker
    row = next(item for item in worker.rows if item.operation == "ipv4_tcp_connect")
    other = _network_target("parser_worker", "ipv6_tcp_connect")
    with pytest.raises(ValidationError, match="network operation|trap"):
        _replace(
            row,
            network_target=other,
            target_sha256=other.target_sha256,
        )


def test_kernel_sandbox_requires_held_dirfd_relative_syscall_anchor() -> None:
    worker = _valid_evidence().worker
    file_row = next(
        item for item in worker.rows if item.operation == "outside_unlink"
    )
    parameters = {
        "syscall_stage": file_row.syscall_stage,
        "address_family": file_row.address_family,
        "socket_type": file_row.socket_type,
        "socket_protocol": file_row.socket_protocol,
        "open_flags": file_row.open_flags,
        "create_mode": file_row.create_mode,
        "target_sha256": file_row.target_sha256,
        "directory_operation_anchor_sha256": None,
        "secondary_target_sha256": file_row.secondary_target_sha256,
        "policy_target_fixture_sha256": file_row.policy_target_fixture_sha256,
        "known_read_fixture_sha256": file_row.known_read_fixture_sha256,
    }
    with pytest.raises(ValidationError, match="dirfd anchor"):
        _replace(
            file_row,
            directory_operation_anchor=None,
            syscall_parameters_sha256=contracts._canonical_hash(parameters),
        )

    unix_row = next(
        item for item in worker.rows if item.operation == "unix_connect"
    )
    assert unix_row.directory_operation_anchor is not None
    wrong_root = _directory("/private/tmp/lat-us02/swapped", "swapped-root")
    wrong_anchor = _replace(
        unix_row.directory_operation_anchor,
        root=wrong_root,
        held_directory_fd=wrong_root.held_directory_fd,
    )
    unix_parameters = {
        "syscall_stage": unix_row.syscall_stage,
        "address_family": unix_row.address_family,
        "socket_type": unix_row.socket_type,
        "socket_protocol": unix_row.socket_protocol,
        "open_flags": unix_row.open_flags,
        "create_mode": unix_row.create_mode,
        "target_sha256": unix_row.target_sha256,
        "directory_operation_anchor_sha256": wrong_anchor.record_sha256,
        "secondary_target_sha256": unix_row.secondary_target_sha256,
        "policy_target_fixture_sha256": unix_row.policy_target_fixture_sha256,
        "known_read_fixture_sha256": unix_row.known_read_fixture_sha256,
    }
    with pytest.raises(ValidationError, match="AF_UNIX dirfd anchor"):
        _replace(
            unix_row,
            directory_operation_anchor=wrong_anchor,
            syscall_parameters_sha256=contracts._canonical_hash(unix_parameters),
        )


def test_kernel_sandbox_positive_control_binds_nonce_payload_and_open_fds() -> None:
    target = _network_target("parser_worker", "ipv4_tcp_connect")
    control = target.positive_control
    assert control.accepted_descriptor is not None
    assert control.payload_hex is not None
    with pytest.raises(ValidationError, match="FD/payload"):
        _replace(
            control,
            payload_hex=("00" + control.payload_hex[2:]),
        )

    substituted = _replace(
        control.accepted_descriptor,
        fd=control.accepted_descriptor.fd + 100,
    )
    with pytest.raises(ValidationError, match="FD/payload"):
        _replace(
            control,
            accepted_descriptor=substituted,
            secondary_syscall_return=substituted.fd,
        )


def test_kernel_sandbox_positive_control_and_trap_bind_raw_target_sockaddr() -> None:
    target = _network_target("parser_worker", "ipv4_tcp_connect")
    assert target.port is not None
    substituted_sockaddr = (
        bytes((16, int(socket.AF_INET)))
        + (target.port + 1).to_bytes(2, "big")
        + socket.inet_pton(socket.AF_INET, "127.0.0.1")
        + b"\0" * 8
    )
    substituted_control = _replace(
        target.positive_control,
        target_sockaddr_hex=substituted_sockaddr.hex(),
        target_sockaddr_length=len(substituted_sockaddr),
        target_sockaddr_sha256=hashlib.sha256(substituted_sockaddr).hexdigest(),
    )
    target_fields = {
        name: getattr(target, name)
        for name in type(target).model_fields
        if name != "target_sha256"
    }
    target_fields["positive_control"] = substituted_control
    target_projection = contracts.KernelSandboxNetworkTarget.model_construct(
        **target_fields,
        target_sha256=ZERO_SHA,
    ).model_dump(mode="json", exclude={"target_sha256"})
    with pytest.raises(ValidationError, match="target authority"):
        contracts.KernelSandboxNetworkTarget(
            **target_fields,
            target_sha256=contracts._canonical_hash(target_projection),
        )

    trap = _trap(
        kind="tcp_ipv4",
        target=target,
        family="AF_INET",
        socket_type=int(socket.SOCK_STREAM),
        protocol=int(socket.IPPROTO_TCP),
        observed=70,
        label="raw-target-sockaddr",
    )
    with pytest.raises(ValidationError, match="trap identity"):
        _replace(
            trap,
            getsockname_sockaddr_hex=substituted_sockaddr.hex(),
            getsockname_sockaddr_length=len(substituted_sockaddr),
            getsockname_sockaddr_sha256=hashlib.sha256(
                substituted_sockaddr
            ).hexdigest(),
        )


def test_kernel_sandbox_native_result_bytes_and_invocation_are_not_opaque() -> None:
    row = next(
        item
        for item in _valid_evidence().worker.rows
        if item.operation == "outside_unlink"
    )
    assert row.native_result is not None
    assert row.native_invocation is not None
    raw = bytearray.fromhex(row.native_result.raw_struct_hex)
    raw[12] ^= 1
    with pytest.raises(ValidationError, match="native sandbox result"):
        _record(
            contracts.KernelSandboxNativeProbeResult,
            **{
                **row.native_result.model_dump(
                    mode="python", exclude={"record_sha256"}
                ),
                "raw_struct_hex": bytes(raw).hex(),
                "raw_struct_sha256": hashlib.sha256(raw).hexdigest(),
            },
        )

    invocation_fields = row.native_invocation.model_dump(
        mode="python", exclude={"invocation_sha256"}
    )
    invocation_fields["held_directory_fd"] += 1
    substituted = contracts.KernelSandboxNativeProbeInvocation(
        **invocation_fields,
        invocation_sha256=contracts._canonical_hash(invocation_fields),
    )
    with pytest.raises(ValidationError, match="native helper join"):
        _replace(row, native_invocation=substituted)

    changed_thread = row.native_invocation.model_dump(
        mode="python", exclude={"invocation_sha256"}
    )
    changed_thread["native_thread_ids_after"] = (702,)
    with pytest.raises(ValidationError, match="native sandbox invocation"):
        contracts.KernelSandboxNativeProbeInvocation(
            **changed_thread,
            invocation_sha256=contracts._canonical_hash(changed_thread),
        )

    incomplete_block = row.native_invocation.model_dump(
        mode="python", exclude={"invocation_sha256"}
    )
    incomplete_block["blocked_signal_mask"] = tuple(
        incomplete_block["blocked_signal_mask"][:-1]
    )
    with pytest.raises(ValidationError, match="native sandbox invocation"):
        contracts.KernelSandboxNativeProbeInvocation(
            **incomplete_block,
            invocation_sha256=contracts._canonical_hash(incomplete_block),
        )

    unrestored_mask = row.native_invocation.model_dump(
        mode="python", exclude={"invocation_sha256"}
    )
    unrestored_mask["restored_signal_mask"] = (int(signal.SIGTERM),)
    with pytest.raises(ValidationError, match="native sandbox invocation"):
        contracts.KernelSandboxNativeProbeInvocation(
            **unrestored_mask,
            invocation_sha256=contracts._canonical_hash(unrestored_mask),
        )
