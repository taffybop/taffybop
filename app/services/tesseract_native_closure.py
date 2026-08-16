"""Bounded native-code identity for the supervised Tesseract broker.

This module deliberately does not claim to contain an adversarial native
binary.  The latency evidence architecture treats the staged Tesseract image
and its recursively resolved Mach-O dependencies as trusted, pinned
computation.  Non-system images are content hashed before launch and again at
broker shutdown.  Images supplied by Apple's dyld shared cache are bound to
the sealed-OS/cache identity described below.

The parser is intentionally implemented without invoking ``otool`` (or any
other child process), so the controller and the spawn-constrained broker can
derive exactly the same canonical record.
"""

from __future__ import annotations

import hashlib
import os
import platform
import stat
import struct
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    KernelProcessIdentity,
    _validate_runtime_scan_structure,
    canonical_json_bytes,
    canonical_sha256,
)


NATIVE_CLOSURE_SCHEMA = "parser-tesseract-native-closure-v1"
NATIVE_CLOSURE_TRUST_MODEL = "frozen-native-closure-trusted-v1"
SYSTEM_CACHE_AUTHORITY = "apple-sealed-system-volume-dyld-shared-cache-v1"
NON_SYSTEM_IMAGE_OWNER_POLICY = "root-or-effective-user-v1"
NON_SYSTEM_IMAGE_MUTABILITY_POLICY = (
    "single-link-non-setid-not-group-or-world-writable-v1"
)
RUNPATH_RESOLUTION_POLICY = (
    "loader-or-main-rpath-with-proven-zero-ancestor-only-edges-v1"
)
NATIVE_RUNTIME_SCAN_SCHEMA = "parser-tesseract-native-runtime-scan-v1"
NATIVE_RUNTIME_SCAN_AUTHORITY = "darwin-libproc-executable-regions-v1"
NATIVE_RUNTIME_POLLING_COMPLETENESS = (
    "bounded-100ms-not-event-complete-trusted-pinned-code-v1"
)
NATIVE_RUNTIME_GATE_SCHEMA = "parser-tesseract-runtime-constructor-gate-v1"
NATIVE_RUNTIME_GATE_AUTHORITY = (
    "dyld-inserted-frozen-constructor-self-sigstop-before-main-v1"
)
NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION = (
    "before-main-not-before-every-trusted-dependency-initializer-v1"
)
NATIVE_RUNTIME_GATE_ACK_AUTHORITY = (
    "native-fixed-binary-pipe-RTGATE1-big-endian-v1"
)
NATIVE_RUNTIME_GATE_ACK_BYTES = 56
NATIVE_RUNTIME_GATE_FD = 3

_MAX_IMAGES = 512
_MAX_EDGES = 8_192
_MAX_TRAVERSAL_PAIRS = 1_024
_MAX_FILE_BYTES = 1024 * 1024 * 1024
_MAX_TOTAL_HASHED_BYTES = 8 * 1024 * 1024 * 1024
_MAX_LOAD_COMMAND_BYTES = 16 * 1024 * 1024
_MAX_LOAD_COMMANDS = 8_192
_MAX_FAT_SLICES = 32
_MAX_SYMLINKS = 16
_MAX_CACHE_FILES = 128

_LC_LOAD_DYLIB = 0x0000000C
_LC_LOAD_WEAK_DYLIB = 0x80000018
_LC_REEXPORT_DYLIB = 0x8000001F
_LC_LAZY_LOAD_DYLIB = 0x00000020
_LC_LOAD_UPWARD_DYLIB = 0x80000023
_LC_RPATH = 0x8000001C
_LC_LOAD_DYLINKER = 0x0000000E
_LC_SYMTAB = 0x00000002
_DEPENDENCY_COMMANDS = {
    _LC_LOAD_DYLIB: "load_dylib",
    _LC_LOAD_WEAK_DYLIB: "load_weak_dylib",
    _LC_REEXPORT_DYLIB: "reexport_dylib",
    _LC_LAZY_LOAD_DYLIB: "lazy_load_dylib",
    _LC_LOAD_UPWARD_DYLIB: "load_upward_dylib",
    _LC_LOAD_DYLINKER: "load_dylinker",
}

_THIN_MAGICS: dict[bytes, tuple[str, bool]] = {
    b"\xce\xfa\xed\xfe": ("<", False),
    b"\xfe\xed\xfa\xce": (">", False),
    b"\xcf\xfa\xed\xfe": ("<", True),
    b"\xfe\xed\xfa\xcf": (">", True),
}
_FAT_MAGICS: dict[bytes, tuple[str, bool]] = {
    b"\xca\xfe\xba\xbe": (">", False),
    b"\xbe\xba\xfe\xca": ("<", False),
    b"\xca\xfe\xba\xbf": (">", True),
    b"\xbf\xba\xfe\xca": ("<", True),
}
_SYSTEM_PREFIXES = ("/usr/lib/", "/System/Library/")
_MAX_SYMBOLS = 2_000_000
_MAX_SYMBOL_TABLE_BYTES = 128 * 1024 * 1024
_MAX_STRING_TABLE_BYTES = 256 * 1024 * 1024
_DYNAMIC_LOADER_IMPORT_MARKERS = (
    "dlopen",
    "NSBundle",
    "CFBundleLoadExecutable",
    "NSCreateObjectFileImageFromFile",
)


def _process_mapping(identity: KernelProcessIdentity) -> dict[str, int]:
    if type(identity) is not KernelProcessIdentity:
        raise BrokerProtocolError("runtime scan process identity differs")
    return {
        "pid": identity.pid,
        "start_abstime": identity.start_abstime,
        "ppid": identity.ppid,
        "pgid": identity.pgid,
        "sid": identity.sid,
    }


def _strict_object(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise BrokerProtocolError(f"{name} fields differ")
    return dict(value)


def _read_at(descriptor: int, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0:
        raise BrokerProtocolError("Mach-O read range is negative")
    result = bytearray()
    while len(result) < size:
        chunk = os.pread(descriptor, size - len(result), offset + len(result))
        if not chunk:
            break
        result.extend(chunk)
    if len(result) != size:
        raise BrokerProtocolError("Mach-O image is truncated")
    return bytes(result)


def _stable_file(path: str) -> tuple[dict[str, Any], int]:
    if (
        not isinstance(path, str)
        or not os.path.isabs(path)
        or os.path.realpath(path) != path
        or "\x00" in path
    ):
        raise BrokerProtocolError("native image path is not absolute and resolved")
    before = os.lstat(path)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size <= 0
        or before.st_size > _MAX_FILE_BYTES
        or before.st_mode & (stat.S_ISUID | stat.S_ISGID)
        or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or before.st_nlink != 1
        or before.st_uid not in {0, os.geteuid()}
    ):
        raise BrokerProtocolError(
            "native image ownership/mutability policy differs"
        )
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_uid,
            opened.st_gid,
            opened.st_nlink,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        if identity != (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ):
            raise BrokerProtocolError("native image changed before open")
        digest = hashlib.sha256()
        offset = 0
        while offset < opened.st_size:
            chunk = os.pread(descriptor, min(1024 * 1024, opened.st_size - offset), offset)
            if not chunk:
                raise BrokerProtocolError("native image ended during hashing")
            digest.update(chunk)
            offset += len(chunk)
        after = os.fstat(descriptor)
        if identity != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise BrokerProtocolError("native image changed during hashing")
        return (
            {
                "resolved_path": path,
                "sha256": digest.hexdigest(),
                "device": opened.st_dev,
                "inode": opened.st_ino,
                "mode": opened.st_mode,
                "uid": opened.st_uid,
                "gid": opened.st_gid,
                "nlink": opened.st_nlink,
                "size": opened.st_size,
                "mtime_ns": opened.st_mtime_ns,
                "ctime_ns": opened.st_ctime_ns,
            },
            descriptor,
        )
    except BaseException:
        os.close(descriptor)
        raise


def _c_string(command: bytes, offset: int, name: str) -> str:
    if offset < 8 or offset >= len(command):
        raise BrokerProtocolError(f"Mach-O {name} offset differs")
    raw = command[offset:].split(b"\x00", 1)[0]
    if not raw or len(raw) > 4096:
        raise BrokerProtocolError(f"Mach-O {name} is empty or oversized")
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise BrokerProtocolError(f"Mach-O {name} is not UTF-8") from exc
    if "\x00" in value:
        raise BrokerProtocolError(f"Mach-O {name} contains NUL")
    return value


def _dynamic_loader_imports(
    descriptor: int,
    *,
    slice_offset: int,
    slice_size: int,
    endian: str,
    is_64: bool,
    symtab: tuple[int, int, int, int] | None,
) -> list[str]:
    if symtab is None:
        return []
    symbol_offset, symbol_count, string_offset, string_size = symtab
    entry_size = 16 if is_64 else 12
    symbol_bytes = symbol_count * entry_size
    if (
        symbol_count > _MAX_SYMBOLS
        or symbol_bytes > _MAX_SYMBOL_TABLE_BYTES
        or string_size <= 0
        or string_size > _MAX_STRING_TABLE_BYTES
        or symbol_offset < 0
        or string_offset < 0
        or symbol_offset + symbol_bytes > slice_size
        or string_offset + string_size > slice_size
    ):
        raise BrokerProtocolError("Mach-O symbol-table bounds differ")
    symbols = _read_at(descriptor, slice_offset + symbol_offset, symbol_bytes)
    strings = _read_at(descriptor, slice_offset + string_offset, string_size)
    matches: set[str] = set()
    for index in range(symbol_count):
        cursor = index * entry_size
        string_index = struct.unpack_from(f"{endian}I", symbols, cursor)[0]
        symbol_type = symbols[cursor + 4]
        if string_index == 0 or string_index >= len(strings):
            continue
        # Only undefined external symbols are executable import authority.
        if symbol_type & 0x0E or not symbol_type & 0x01:
            continue
        end = strings.find(b"\x00", string_index)
        if end < 0 or end - string_index > 4096:
            raise BrokerProtocolError("Mach-O imported symbol is malformed")
        try:
            name = strings[string_index:end].decode("utf-8", "strict")
        except UnicodeDecodeError:
            continue
        if any(marker in name for marker in _DYNAMIC_LOADER_IMPORT_MARKERS):
            matches.add(name)
    return sorted(matches)


def _slice_specs(descriptor: int, size: int) -> list[tuple[int, int, str, bool, int, int]]:
    magic = _read_at(descriptor, 0, 4)
    thin = _THIN_MAGICS.get(magic)
    if thin is not None:
        endian, is_64 = thin
        header_size = 32 if is_64 else 28
        header = _read_at(descriptor, 0, header_size)
        values = struct.unpack(f"{endian}{'8I' if is_64 else '7I'}", header)
        return [(0, size, endian, is_64, values[1], values[2])]
    fat = _FAT_MAGICS.get(magic)
    if fat is None:
        raise BrokerProtocolError("native dependency is not a Mach-O image")
    endian, fat64 = fat
    count = struct.unpack(f"{endian}I", _read_at(descriptor, 4, 4))[0]
    if count <= 0 or count > _MAX_FAT_SLICES:
        raise BrokerProtocolError("Mach-O fat slice count differs")
    entry_size = 32 if fat64 else 20
    table = _read_at(descriptor, 8, count * entry_size)
    result: list[tuple[int, int, str, bool, int, int]] = []
    seen_ranges: list[tuple[int, int]] = []
    for index in range(count):
        entry = table[index * entry_size : (index + 1) * entry_size]
        if fat64:
            cpu_type, cpu_subtype, offset, slice_size, _align, _reserved = struct.unpack(
                f"{endian}IIQQII", entry
            )
        else:
            cpu_type, cpu_subtype, offset, slice_size, _align = struct.unpack(
                f"{endian}IIIII", entry
            )
        if (
            slice_size <= 0
            or offset < 8 + count * entry_size
            or offset + slice_size > size
            or any(offset < other_end and other_start < offset + slice_size for other_start, other_end in seen_ranges)
        ):
            raise BrokerProtocolError("Mach-O fat slice range differs")
        seen_ranges.append((offset, offset + slice_size))
        slice_magic = _read_at(descriptor, offset, 4)
        parsed = _THIN_MAGICS.get(slice_magic)
        if parsed is None:
            raise BrokerProtocolError("Mach-O fat slice magic differs")
        slice_endian, is_64 = parsed
        header_size = 32 if is_64 else 28
        header = _read_at(descriptor, offset, header_size)
        values = struct.unpack(
            f"{slice_endian}{'8I' if is_64 else '7I'}", header
        )
        if values[1] != cpu_type or values[2] != cpu_subtype:
            raise BrokerProtocolError("Mach-O fat architecture identity differs")
        result.append((offset, slice_size, slice_endian, is_64, cpu_type, cpu_subtype))
    return result


def _parse_macho(descriptor: int, size: int) -> dict[str, Any]:
    slices: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    for slice_index, (offset, slice_size, endian, is_64, cpu_type, cpu_subtype) in enumerate(
        _slice_specs(descriptor, size)
    ):
        header_size = 32 if is_64 else 28
        header = _read_at(descriptor, offset, header_size)
        values = struct.unpack(f"{endian}{'8I' if is_64 else '7I'}", header)
        command_count = values[4]
        command_bytes = values[5]
        if (
            command_count <= 0
            or command_count > _MAX_LOAD_COMMANDS
            or command_bytes <= 0
            or command_bytes > _MAX_LOAD_COMMAND_BYTES
            or header_size + command_bytes > slice_size
        ):
            raise BrokerProtocolError("Mach-O load-command bounds differ")
        raw_commands = _read_at(descriptor, offset + header_size, command_bytes)
        cursor = 0
        rpaths: list[str] = []
        slice_dependencies: list[dict[str, Any]] = []
        symtab: tuple[int, int, int, int] | None = None
        for command_index in range(command_count):
            if cursor + 8 > len(raw_commands):
                raise BrokerProtocolError("Mach-O load-command header is truncated")
            command, command_size = struct.unpack_from(f"{endian}II", raw_commands, cursor)
            if command_size < 8 or command_size % 4 or cursor + command_size > len(raw_commands):
                raise BrokerProtocolError("Mach-O load-command size differs")
            raw_command = raw_commands[cursor : cursor + command_size]
            if command == _LC_RPATH:
                path_offset = struct.unpack_from(f"{endian}I", raw_command, 8)[0]
                rpath = _c_string(raw_command, path_offset, "rpath")
                if rpath in rpaths:
                    raise BrokerProtocolError("Mach-O rpath is duplicated")
                rpaths.append(rpath)
            elif command in _DEPENDENCY_COMMANDS:
                path_offset = struct.unpack_from(f"{endian}I", raw_command, 8)[0]
                dependency = {
                    "slice_index": slice_index,
                    "command_index": command_index,
                    "command": _DEPENDENCY_COMMANDS[command],
                    "install_name": _c_string(raw_command, path_offset, "dependency"),
                }
                slice_dependencies.append(dependency)
                dependencies.append(dependency)
            elif command == _LC_SYMTAB:
                if command_size != 24 or symtab is not None:
                    raise BrokerProtocolError("Mach-O symbol-table command differs")
                symtab = struct.unpack_from(f"{endian}IIII", raw_command, 8)
            cursor += command_size
        if cursor != len(raw_commands):
            raise BrokerProtocolError("Mach-O load-command bytes are not exact")
        slices.append(
            {
                "slice_index": slice_index,
                "cpu_type": cpu_type,
                "cpu_subtype": cpu_subtype,
                "is_64_bit": is_64,
                "byte_order": "little" if endian == "<" else "big",
                "file_offset": offset,
                "file_size": slice_size,
                "load_command_count": command_count,
                "load_command_bytes": command_bytes,
                "load_commands_sha256": hashlib.sha256(raw_commands).hexdigest(),
                "rpaths": rpaths,
                "dependencies": slice_dependencies,
                "dynamic_loader_imports": _dynamic_loader_imports(
                    descriptor,
                    slice_offset=offset,
                    slice_size=slice_size,
                    endian=endian,
                    is_64=is_64,
                    symtab=symtab,
                ),
            }
        )
    return {"slices": slices, "dependencies": dependencies}


def _expand_token(value: str, *, loader: str, executable: str) -> str:
    loader_directory = os.path.dirname(loader)
    executable_directory = os.path.dirname(executable)
    if value == "@loader_path":
        return loader_directory
    if value.startswith("@loader_path/"):
        return os.path.join(loader_directory, value[len("@loader_path/") :])
    if value == "@executable_path":
        return executable_directory
    if value.startswith("@executable_path/"):
        return os.path.join(executable_directory, value[len("@executable_path/") :])
    return value


def _resolve_symlinks(path: str) -> tuple[str | None, list[dict[str, Any]]]:
    if not os.path.isabs(path) or "\x00" in path:
        raise BrokerProtocolError("native dependency lookup path differs")
    components = [item for item in os.path.normpath(path).split("/") if item]
    resolved_components: list[str] = []
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    link_count = 0
    while components:
        component = components.pop(0)
        if component == ".":
            continue
        if component == "..":
            if not resolved_components:
                raise BrokerProtocolError("native dependency escapes filesystem root")
            resolved_components.pop()
            continue
        current = "/" + "/".join([*resolved_components, component])
        try:
            observed = os.lstat(current)
        except FileNotFoundError:
            return None, chain
        if not stat.S_ISLNK(observed.st_mode):
            resolved_components.append(component)
            continue
        link_count += 1
        if link_count > _MAX_SYMLINKS or current in seen:
            raise BrokerProtocolError("native dependency symlink chain exceeds its bound")
        seen.add(current)
        target = os.readlink(current)
        after = os.lstat(current)
        if (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_uid,
            observed.st_gid,
            observed.st_size,
            observed.st_mtime_ns,
            observed.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise BrokerProtocolError("native dependency symlink changed during read")
        chain.append(
            {
                "path": current,
                "target": target,
                "device": observed.st_dev,
                "inode": observed.st_ino,
                "mode": observed.st_mode,
                "uid": observed.st_uid,
                "gid": observed.st_gid,
                "size": observed.st_size,
            }
        )
        target_components = [item for item in target.split("/") if item]
        if os.path.isabs(target):
            resolved_components = []
        components = [*target_components, *components]
    resolved = "/" + "/".join(resolved_components)
    if os.path.realpath(resolved) != resolved:
        raise BrokerProtocolError("native dependency did not resolve exactly")
    return resolved, chain


def _dependency_candidates(
    install_name: str,
    *,
    loader_path: str,
    executable_path: str,
    loader_rpaths: list[str],
    executable_rpaths: list[str],
) -> list[str]:
    if install_name.startswith("@rpath/"):
        suffix = install_name[len("@rpath/") :]
        candidates: list[str] = []
        for raw_rpath in [*loader_rpaths, *executable_rpaths]:
            expanded = _expand_token(
                raw_rpath, loader=loader_path, executable=executable_path
            )
            if expanded.startswith("@rpath"):
                raise BrokerProtocolError("recursive Mach-O @rpath is unsupported")
            if not os.path.isabs(expanded):
                raise BrokerProtocolError("Mach-O rpath is not absolute after expansion")
            candidate = os.path.normpath(os.path.join(expanded, suffix))
            if candidate not in candidates:
                candidates.append(candidate)
        if not candidates:
            raise BrokerProtocolError("Mach-O @rpath has no frozen search path")
        return candidates
    expanded = _expand_token(
        install_name, loader=loader_path, executable=executable_path
    )
    if not os.path.isabs(expanded):
        raise BrokerProtocolError("Mach-O dependency path is not absolute")
    return [os.path.normpath(expanded)]


def _regular_file_identity(path: str, *, allow_large: bool = False) -> dict[str, Any]:
    before = os.lstat(path)
    maximum = _MAX_FILE_BYTES if allow_large else 64 * 1024 * 1024
    if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or before.st_size > maximum:
        raise BrokerProtocolError("system identity file differs")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        digest = hashlib.sha256()
        total = 0
        while total < opened.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, opened.st_size - total))
            if not chunk:
                raise BrokerProtocolError("system identity file ended during hashing")
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(opened, field) or getattr(opened, field) != getattr(after, field) for field in fields):
            raise BrokerProtocolError("system identity file changed during hashing")
        return {
            "resolved_path": path,
            "sha256": digest.hexdigest(),
            "device": opened.st_dev,
            "inode": opened.st_ino,
            "mode": opened.st_mode,
            "uid": opened.st_uid,
            "gid": opened.st_gid,
            "nlink": opened.st_nlink,
            "size": opened.st_size,
            "mtime_ns": opened.st_mtime_ns,
            "ctime_ns": opened.st_ctime_ns,
        }
    finally:
        os.close(descriptor)


def _system_cache_identity(system_references: list[str]) -> dict[str, Any]:
    if platform.system() != "Darwin":
        raise BrokerProtocolError("native closure is approved only on Darwin")
    uname = os.uname()
    dyld_identity = _regular_file_identity("/usr/lib/dyld")
    machine = platform.machine()
    cache_roots = (
        Path("/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld"),
        Path("/System/Library/dyld"),
    )
    selected_root: Path | None = None
    files: list[Path] = []
    preferred_names = (
        ("dyld_shared_cache_arm64e", "dyld_shared_cache_arm64")
        if machine.startswith("arm64")
        else (f"dyld_shared_cache_{machine}",)
    )
    for root in cache_roots:
        if not root.is_dir() or os.path.realpath(root) != str(root):
            continue
        for preferred in preferred_names:
            candidate = root / preferred
            if candidate.is_file():
                selected_root = root
                files = sorted(root.glob(f"{preferred}*"), key=lambda item: item.name)
                break
        if selected_root is not None:
            break
    if selected_root is None or not files or len(files) > _MAX_CACHE_FILES:
        raise BrokerProtocolError("Darwin dyld shared cache identity is unavailable")
    cache_records: list[dict[str, Any]] = []
    main_identity: dict[str, Any] | None = None
    for path in files:
        observed = os.lstat(path)
        if not stat.S_ISREG(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
            raise BrokerProtocolError("dyld cache manifest contains a non-file")
        record: dict[str, Any] = {
            "name": path.name,
            "device": observed.st_dev,
            "inode": observed.st_ino,
            "mode": observed.st_mode,
            "uid": observed.st_uid,
            "gid": observed.st_gid,
            "nlink": observed.st_nlink,
            "size": observed.st_size,
            "mtime_ns": observed.st_mtime_ns,
            "ctime_ns": observed.st_ctime_ns,
        }
        if "." not in path.name[len("dyld_shared_cache_") :]:
            main_identity = _regular_file_identity(str(path), allow_large=True)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            try:
                header = _read_at(descriptor, 0, min(observed.st_size, 4096))
            finally:
                os.close(descriptor)
            if len(header) < 104 or not header.startswith(b"dyld_v1"):
                raise BrokerProtocolError("dyld shared-cache header differs")
            record["main_content_sha256"] = main_identity["sha256"]
            record["cache_uuid_hex"] = header[88:104].hex()
        cache_records.append(record)
    if main_identity is None:
        raise BrokerProtocolError("dyld main shared cache is absent")
    host = {
        "sysname": uname.sysname,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
    }
    manifest_sha256 = canonical_sha256(
        {"root": str(selected_root), "files": cache_records}
    )
    return {
        "authority": SYSTEM_CACHE_AUTHORITY,
        "content_scope": (
            "main-cache-fully-hashed-subcache-metadata-and-sealed-os-trusted-v1"
        ),
        "host": host,
        "host_sha256": canonical_sha256(host),
        "dyld": dyld_identity,
        "cache_root": str(selected_root),
        "cache_files": cache_records,
        "cache_manifest_sha256": manifest_sha256,
        "system_references": sorted(set(system_references)),
    }


def derive_native_closure(
    source_path: str | os.PathLike[str],
    staged_path: str | os.PathLike[str],
    *,
    runtime_gate_source_path: str | os.PathLike[str] | None = None,
    runtime_gate_library_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Derive one strict recursive closure for source and staged Tesseract.

    The returned object is canonical JSON data and may be embedded directly in
    the broker launch template.  Both paths must already be absolute, resolved
    regular files; staging/path construction remains controller-owned.
    """

    if platform.system() != "Darwin":
        raise BrokerProtocolError("native closure is approved only on Darwin")
    try:
        source_path = os.fspath(source_path)
        staged_path = os.fspath(staged_path)
    except TypeError as exc:
        raise BrokerProtocolError("native closure root path is malformed") from exc
    for name, value in (("source_path", source_path), ("staged_path", staged_path)):
        if (
            not isinstance(value, str)
            or not os.path.isabs(value)
            or os.path.realpath(value) != value
            or "\x00" in value
        ):
            raise BrokerProtocolError(f"{name} must be absolute and resolved")
    if (runtime_gate_source_path is None) != (
        runtime_gate_library_path is None
    ):
        raise BrokerProtocolError(
            "native runtime gate source/library custody is incomplete"
        )
    runtime_gate_source_identity: dict[str, Any] | None = None
    runtime_gate_library: str | None = None
    if runtime_gate_source_path is not None:
        try:
            runtime_gate_source = os.fspath(runtime_gate_source_path)
            runtime_gate_library = os.fspath(runtime_gate_library_path)
        except TypeError as exc:
            raise BrokerProtocolError(
                "native runtime gate path is malformed"
            ) from exc
        for name, value in (
            ("runtime_gate_source_path", runtime_gate_source),
            ("runtime_gate_library_path", runtime_gate_library),
        ):
            if (
                not isinstance(value, str)
                or not os.path.isabs(value)
                or os.path.realpath(value) != value
                or "\x00" in value
            ):
                raise BrokerProtocolError(
                    f"{name} must be absolute and resolved"
                )
        runtime_gate_source_identity, runtime_gate_source_fd = _stable_file(
            runtime_gate_source
        )
        os.close(runtime_gate_source_fd)
        if (
            stat.S_IMODE(runtime_gate_source_identity["mode"]) != 0o500
            or runtime_gate_source_identity["uid"] != os.geteuid()
            or runtime_gate_source_identity["nlink"] != 1
        ):
            raise BrokerProtocolError(
                "native runtime gate source custody differs"
            )
    queue: list[tuple[str, str]] = [
        (source_path, source_path),
        (staged_path, staged_path),
    ]
    if runtime_gate_library is not None:
        queue.append((runtime_gate_library, runtime_gate_library))
    images_by_path: dict[str, dict[str, Any]] = {}
    parsed_by_path: dict[str, dict[str, Any]] = {}
    visited_pairs: set[tuple[str, str]] = set()
    executable_rpaths_by_root: dict[str, list[str]] = {}
    edges: list[dict[str, Any]] = []
    system_references: list[str] = []
    total_hashed_bytes = 0
    index = 0
    while index < len(queue):
        path, root_executable = queue[index]
        index += 1
        pair = (path, root_executable)
        if pair in visited_pairs:
            continue
        if len(visited_pairs) >= _MAX_TRAVERSAL_PAIRS:
            raise BrokerProtocolError("native closure traversal exceeds its bound")
        visited_pairs.add(pair)
        if path not in images_by_path:
            if len(images_by_path) >= _MAX_IMAGES:
                raise BrokerProtocolError("native closure image count exceeds its bound")
            identity, descriptor = _stable_file(path)
            try:
                parsed = _parse_macho(descriptor, identity["size"])
            finally:
                os.close(descriptor)
            total_hashed_bytes += identity["size"]
            if total_hashed_bytes > _MAX_TOTAL_HASHED_BYTES:
                raise BrokerProtocolError("native closure bytes exceed their bound")
            dynamic_loader_imports = sorted(
                {
                    symbol
                    for slice_record in parsed["slices"]
                    for symbol in slice_record["dynamic_loader_imports"]
                }
            )
            image = {
                **identity,
                "slices": parsed["slices"],
                "dynamic_loader_imports": dynamic_loader_imports,
                "imports_dynamic_loader_family": bool(
                    dynamic_loader_imports
                ),
            }
            images_by_path[path] = image
            parsed_by_path[path] = parsed
        else:
            identity = {
                key: value
                for key, value in images_by_path[path].items()
                if key != "slices"
            }
            parsed = parsed_by_path[path]
        if path == root_executable:
            root_rpaths: list[str] = []
            for slice_record in parsed["slices"]:
                for rpath in slice_record["rpaths"]:
                    if rpath not in root_rpaths:
                        root_rpaths.append(rpath)
            executable_rpaths_by_root[root_executable] = root_rpaths
        root_rpaths = executable_rpaths_by_root.get(root_executable, [])
        for dependency in parsed["dependencies"]:
            if len(edges) >= _MAX_EDGES:
                raise BrokerProtocolError("native closure edge count exceeds its bound")
            loader_rpaths = parsed["slices"][dependency["slice_index"]]["rpaths"]
            candidates = _dependency_candidates(
                dependency["install_name"],
                loader_path=path,
                executable_path=root_executable,
                loader_rpaths=loader_rpaths,
                executable_rpaths=root_rpaths,
            )
            loader_only_candidates: list[str] = []
            executable_only_candidates: list[str] = []
            if dependency["install_name"].startswith("@rpath/"):
                if loader_rpaths:
                    loader_only_candidates = _dependency_candidates(
                        dependency["install_name"],
                        loader_path=path,
                        executable_path=root_executable,
                        loader_rpaths=loader_rpaths,
                        executable_rpaths=[],
                    )
                if root_rpaths:
                    executable_only_candidates = _dependency_candidates(
                        dependency["install_name"],
                        loader_path=path,
                        executable_path=root_executable,
                        loader_rpaths=[],
                        executable_rpaths=root_rpaths,
                    )
            selected_lookup: str | None = None
            selected_resolved: str | None = None
            selected_chain: list[dict[str, Any]] = []
            for candidate in candidates:
                resolved, chain = _resolve_symlinks(candidate)
                if resolved is not None:
                    selected_lookup = candidate
                    selected_resolved = resolved
                    selected_chain = chain
                    break
            system_reference = all(
                candidate.startswith(_SYSTEM_PREFIXES) for candidate in candidates
            )
            if selected_resolved is None and not system_reference:
                raise BrokerProtocolError("non-system native dependency is missing")
            if selected_resolved is None:
                selected_lookup = candidates[0]
                system_references.append(dependency["install_name"])
                resolution_kind = "apple-dyld-shared-cache"
                target_sha256 = ""
            else:
                resolution_kind = "regular-file"
                target_identity, target_fd = _stable_file(selected_resolved)
                os.close(target_fd)
                target_sha256 = target_identity["sha256"]
                queue.append((selected_resolved, root_executable))
            if not dependency["install_name"].startswith("@rpath/"):
                runpath_resolution_scope = "not-rpath"
            elif selected_lookup in loader_only_candidates:
                runpath_resolution_scope = "loader-rpath"
            elif selected_lookup in executable_only_candidates:
                runpath_resolution_scope = "main-executable-rpath"
            else:
                # The frozen resolver intentionally fails rather than silently
                # model an ancestor-only dyld runpath.  The retained zero count
                # is therefore a directly recomputable property of the graph.
                raise BrokerProtocolError(
                    "native dependency requires an ancestor-only runpath"
                )
            edges.append(
                {
                    "root_executable": root_executable,
                    "loader_path": path,
                    "loader_sha256": identity["sha256"],
                    "slice_index": dependency["slice_index"],
                    "command_index": dependency["command_index"],
                    "command": dependency["command"],
                    "install_name": dependency["install_name"],
                    "candidate_paths": candidates,
                    "lookup_path": selected_lookup,
                    "resolved_path": selected_resolved,
                    "resolution_kind": resolution_kind,
                    "target_sha256": target_sha256,
                    "symlink_chain": selected_chain,
                    "runpath_resolution_scope": runpath_resolution_scope,
                }
            )
    system_cache = _system_cache_identity(system_references)
    cache_binding = canonical_sha256(system_cache)
    for edge in edges:
        if edge["resolution_kind"] == "apple-dyld-shared-cache":
            edge["target_sha256"] = canonical_sha256(
                {
                    "authority": SYSTEM_CACHE_AUTHORITY,
                    "cache_binding_sha256": cache_binding,
                    "install_name": edge["install_name"],
                }
            )
    def root_projection(root_executable: str) -> list[dict[str, Any]]:
        return [
            {
                "loader_sha256": edge["loader_sha256"],
                "slice_index": edge["slice_index"],
                "command_index": edge["command_index"],
                "command": edge["command"],
                "install_name": edge["install_name"],
                "resolution_kind": edge["resolution_kind"],
                "target_sha256": edge["target_sha256"],
                "runpath_resolution_scope": edge[
                    "runpath_resolution_scope"
                ],
            }
            for edge in sorted(
                (
                    item
                    for item in edges
                    if item["root_executable"] == root_executable
                ),
                key=lambda item: (
                    item["loader_sha256"],
                    item["slice_index"],
                    item["command_index"],
                    item["install_name"],
                    item["target_sha256"],
                ),
            )
        ]

    source_projection = root_projection(source_path)
    staged_projection = root_projection(staged_path)
    source_projection_sha256 = canonical_sha256(
        {"dependencies": source_projection}
    )
    staged_projection_sha256 = canonical_sha256(
        {"dependencies": staged_projection}
    )
    if source_projection_sha256 != staged_projection_sha256:
        raise BrokerProtocolError(
            "source/staged native dependency projections differ"
        )
    roots = {
        "source_executable": source_path,
        "staged_executable": staged_path,
        "source_sha256": images_by_path[source_path]["sha256"],
        "staged_sha256": images_by_path[staged_path]["sha256"],
        "source_dependency_projection_sha256": source_projection_sha256,
        "staged_dependency_projection_sha256": staged_projection_sha256,
    }
    if roots["source_sha256"] != roots["staged_sha256"]:
        raise BrokerProtocolError("staged Tesseract bytes differ from source")
    runtime_gate: dict[str, Any] | None = None
    if runtime_gate_library is not None:
        runtime_gate_library_identity = images_by_path[runtime_gate_library]
        if (
            stat.S_IMODE(runtime_gate_library_identity["mode"]) != 0o500
            or runtime_gate_library_identity["uid"] != os.geteuid()
            or runtime_gate_library_identity["nlink"] != 1
            or runtime_gate_source_identity is None
        ):
            raise BrokerProtocolError(
                "native runtime gate library custody differs"
            )
        runtime_gate = {
            "schema_id": NATIVE_RUNTIME_GATE_SCHEMA,
            "authority": NATIVE_RUNTIME_GATE_AUTHORITY,
            "initializer_order_limitation": (
                NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION
            ),
            "ack_authority": NATIVE_RUNTIME_GATE_ACK_AUTHORITY,
            "ack_bytes": NATIVE_RUNTIME_GATE_ACK_BYTES,
            "inherited_gate_fd": NATIVE_RUNTIME_GATE_FD,
            "source": runtime_gate_source_identity,
            "library": {
                key: value
                for key, value in runtime_gate_library_identity.items()
                if key
                not in {
                    "slices",
                    "dynamic_loader_imports",
                    "imports_dynamic_loader_family",
                }
            },
            "dyld_environment_names": [
                "DYLD_INSERT_LIBRARIES",
                "PARSER_TESSERACT_RUNTIME_GATE_FD",
                "PARSER_TESSERACT_RUNTIME_GATE_NONCE",
            ],
            "constructor_self_sigstop_before_main": True,
            "malicious_initializer_containment_claim": False,
        }
        runtime_gate["record_sha256"] = canonical_sha256(runtime_gate)
    mapping: dict[str, Any] = {
        "schema_id": NATIVE_CLOSURE_SCHEMA,
        "trust_model": NATIVE_CLOSURE_TRUST_MODEL,
        "containment_claim": "none-trusted-pinned-native-computation",
        "non_system_image_owner_policy": NON_SYSTEM_IMAGE_OWNER_POLICY,
        "non_system_image_mutability_policy": (
            NON_SYSTEM_IMAGE_MUTABILITY_POLICY
        ),
        "runpath_resolution_policy": RUNPATH_RESOLUTION_POLICY,
        "ancestor_only_runpath_edge_count": 0,
        "dynamic_loader_import_markers": list(
            _DYNAMIC_LOADER_IMPORT_MARKERS
        ),
        "dynamic_loader_importing_images": [
            {
                "resolved_path": image["resolved_path"],
                "sha256": image["sha256"],
                "dynamic_loader_imports": image[
                    "dynamic_loader_imports"
                ],
            }
            for image in sorted(
                images_by_path.values(),
                key=lambda item: item["resolved_path"],
            )
            if image["imports_dynamic_loader_family"]
        ],
        "roots": roots,
        "runtime_gate": runtime_gate,
        "images": sorted(images_by_path.values(), key=lambda item: item["resolved_path"]),
        "edges": sorted(
            edges,
            key=lambda item: (
                item["root_executable"],
                item["loader_path"],
                item["slice_index"],
                item["command_index"],
                item["install_name"],
            ),
        ),
        "system_cache": system_cache,
        "total_hashed_bytes": total_hashed_bytes,
        "image_count": len(images_by_path),
        "edge_count": len(edges),
    }
    mapping["dynamic_loader_importing_image_count"] = len(
        mapping["dynamic_loader_importing_images"]
    )
    mapping["dynamic_loader_imports_sha256"] = canonical_sha256(
        {
            "markers": mapping["dynamic_loader_import_markers"],
            "images": mapping["dynamic_loader_importing_images"],
        }
    )
    mapping["closure_sha256"] = canonical_sha256(mapping)
    return mapping


def native_runtime_non_system_projection(
    closure: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the exact staged-root runtime image projection.

    The closure contains traversal rows for both the source and staged root.
    Runtime custody is specifically the staged-root graph; using the closure's
    global image table would accidentally admit a strict subset or a
    source-only path.  This projection is bounded by the already-validated
    closure and is fully replayable without observing a live process.
    """

    frozen = validate_native_closure(dict(closure), reobserve=False)
    staged_root = frozen["roots"]["staged_executable"]
    expected_paths = {staged_root}
    for edge in frozen["edges"]:
        if (
            edge["root_executable"] == staged_root
            and edge["resolution_kind"] == "regular-file"
        ):
            resolved = edge["resolved_path"]
            if not isinstance(resolved, str) or not resolved:
                raise BrokerProtocolError(
                    "staged runtime dependency path differs"
                )
            if not resolved.startswith(_SYSTEM_PREFIXES):
                expected_paths.add(resolved)
    runtime_gate = frozen["runtime_gate"]
    if runtime_gate is not None:
        gate_root = runtime_gate["library"]["resolved_path"]
        expected_paths.add(gate_root)
        for edge in frozen["edges"]:
            if (
                edge["root_executable"] == gate_root
                and edge["resolution_kind"] == "regular-file"
            ):
                resolved = edge["resolved_path"]
                if not isinstance(resolved, str) or not resolved:
                    raise BrokerProtocolError(
                        "runtime gate dependency path differs"
                    )
                if not resolved.startswith(_SYSTEM_PREFIXES):
                    expected_paths.add(resolved)
    images_by_path = {
        item["resolved_path"]: item for item in frozen["images"]
    }
    rows: list[dict[str, Any]] = []
    for path in sorted(expected_paths):
        image = images_by_path.get(path)
        if image is None or path.startswith(_SYSTEM_PREFIXES):
            raise BrokerProtocolError(
                "staged runtime projection is outside the frozen image set"
            )
        rows.append(
            {
                "resolved_path": image["resolved_path"],
                "sha256": image["sha256"],
                "device": image["device"],
                "inode": image["inode"],
                "mode": image["mode"],
                "uid": image["uid"],
                "gid": image["gid"],
                "nlink": image["nlink"],
                "size": image["size"],
                "mtime_ns": image["mtime_ns"],
                "ctime_ns": image["ctime_ns"],
            }
        )
    if not rows:
        raise BrokerProtocolError("staged runtime projection is empty")
    projection: dict[str, Any] = {
        "schema_id": "parser-tesseract-runtime-non-system-projection-v1",
        "staged_root": staged_root,
        "image_count": len(rows),
        "images": rows,
    }
    projection["projection_sha256"] = canonical_sha256(projection)
    return projection


def observe_runtime_native_scan(
    pid: int,
    expected_process: KernelProcessIdentity,
    closure: Mapping[str, Any],
) -> dict[str, Any]:
    """Take one kernel-backed executable mapping scan and bind it to closure.

    The staged executable is content-hashed on both sides of the libproc scan;
    other non-system images are matched by the mapped vnode identity to their
    prehashed closure rows and are all rehashed when the closure is validated
    after the exact wait4 tombstone.
    """

    from app.services.tesseract_broker_native import (
        native_executable_region_inventory,
    )

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise BrokerProtocolError("runtime native scan PID differs")
    if type(expected_process) is not KernelProcessIdentity or expected_process.pid != pid:
        raise BrokerProtocolError("runtime native scan process differs")
    frozen = validate_native_closure(dict(closure), reobserve=False)
    expected_projection = native_runtime_non_system_projection(frozen)
    roots = frozen["roots"]
    staged_path = roots["staged_executable"]
    bracket_started = time.monotonic_ns()
    staged_before, staged_before_fd = _stable_file(staged_path)
    os.close(staged_before_fd)
    inventory = native_executable_region_inventory(pid)
    staged_after, staged_after_fd = _stable_file(staged_path)
    os.close(staged_after_fd)
    bracket_completed = time.monotonic_ns()
    if (
        inventory.process != expected_process
        or staged_before != staged_after
        or staged_before["sha256"] != roots["staged_sha256"]
    ):
        raise BrokerProtocolError("runtime native scan bracket differs")
    images_by_path = {
        item["resolved_path"]: item for item in frozen["images"]
    }
    grouped: dict[str, list[Any]] = {}
    for region in inventory.regions:
        grouped.setdefault(region.resolved_path, []).append(region)
    mapped_images: list[dict[str, Any]] = []
    staged_mapping_count = 0
    for path in sorted(grouped):
        regions = grouped[path]
        first = regions[0]
        observed_identity = {
            "resolved_path": first.resolved_path,
            "device": first.device,
            "inode": first.inode,
            "mode": first.mode,
            "uid": first.uid,
            "gid": first.gid,
            "nlink": first.nlink,
            "size": first.file_size,
            "mtime_ns": first.mtime_ns,
            "ctime_ns": first.ctime_ns,
        }
        if any(
            {
                "resolved_path": item.resolved_path,
                "device": item.device,
                "inode": item.inode,
                "mode": item.mode,
                "uid": item.uid,
                "gid": item.gid,
                "nlink": item.nlink,
                "size": item.file_size,
                "mtime_ns": item.mtime_ns,
                "ctime_ns": item.ctime_ns,
            }
            != observed_identity
            for item in regions
        ):
            raise BrokerProtocolError("mapped native image vnode identity drifted")
        system_image = path.startswith(_SYSTEM_PREFIXES)
        if system_image:
            closure_image_sha256 = canonical_sha256(
                {
                    "authority": SYSTEM_CACHE_AUTHORITY,
                    "system_cache_sha256": canonical_sha256(
                        frozen["system_cache"]
                    ),
                    "mapped_path": path,
                }
            )
        else:
            closure_image = images_by_path.get(path)
            if closure_image is None:
                raise BrokerProtocolError(
                    "runtime loaded a non-system image outside frozen closure"
                )
            for name in (
                "resolved_path",
                "device",
                "inode",
                "mode",
                "uid",
                "gid",
                "nlink",
                "size",
                "mtime_ns",
                "ctime_ns",
            ):
                if closure_image[name] != observed_identity[name]:
                    raise BrokerProtocolError(
                        "runtime mapped native image identity differs from closure"
                    )
            closure_image_sha256 = closure_image["sha256"]
        if path == staged_path:
            staged_mapping_count += 1
            if any(
                staged_before[name] != observed_identity[name]
                for name in (
                    "resolved_path",
                    "device",
                    "inode",
                    "mode",
                    "uid",
                    "gid",
                    "nlink",
                    "size",
                    "mtime_ns",
                    "ctime_ns",
                )
            ):
                raise BrokerProtocolError(
                    "runtime staged executable vnode identity differs"
                )
        region_rows = [asdict(item) for item in regions]
        image_row: dict[str, Any] = {
            **observed_identity,
            "system_image": system_image,
            "closure_image_sha256": closure_image_sha256,
            "executable_regions": region_rows,
            "executable_region_count": len(region_rows),
        }
        image_row["record_sha256"] = canonical_sha256(image_row)
        mapped_images.append(image_row)
    if staged_mapping_count != 1:
        raise BrokerProtocolError(
            "runtime scan lacks the exact staged executable mapping"
        )
    system_cache_sha256 = canonical_sha256(frozen["system_cache"])
    observed_non_system_rows = [
        {
            "resolved_path": item["resolved_path"],
            "sha256": item["closure_image_sha256"],
            "device": item["device"],
            "inode": item["inode"],
            "mode": item["mode"],
            "uid": item["uid"],
            "gid": item["gid"],
            "nlink": item["nlink"],
            "size": item["size"],
            "mtime_ns": item["mtime_ns"],
            "ctime_ns": item["ctime_ns"],
        }
        for item in mapped_images
        if item["system_image"] is False
    ]
    observed_projection: dict[str, Any] = {
        "schema_id": "parser-tesseract-runtime-non-system-projection-v1",
        "staged_root": staged_path,
        "image_count": len(observed_non_system_rows),
        "images": observed_non_system_rows,
    }
    observed_projection_sha256 = canonical_sha256(observed_projection)
    if (
        observed_non_system_rows != expected_projection["images"]
        or observed_projection_sha256
        != expected_projection["projection_sha256"]
    ):
        raise BrokerProtocolError(
            "runtime non-system image projection is incomplete"
        )
    mapping: dict[str, Any] = {
        "schema_id": NATIVE_RUNTIME_SCAN_SCHEMA,
        "authority": NATIVE_RUNTIME_SCAN_AUTHORITY,
        "process": _process_mapping(inventory.process),
        "native_closure_sha256": frozen["closure_sha256"],
        "system_cache_sha256": system_cache_sha256,
        "staged_executable_sha256": staged_before["sha256"],
        "staged_executable_device": staged_before["device"],
        "staged_executable_inode": staged_before["inode"],
        "staged_executable_content_stable": True,
        "bracket_started_monotonic_ns": bracket_started,
        "kernel_scan_started_monotonic_ns": (
            inventory.scan_started_monotonic_ns
        ),
        "kernel_scan_completed_monotonic_ns": (
            inventory.scan_completed_monotonic_ns
        ),
        "bracket_completed_monotonic_ns": bracket_completed,
        "total_region_count": inventory.total_region_count,
        "executable_region_count": len(inventory.regions),
        "mapped_image_count": len(mapped_images),
        "mapped_images": mapped_images,
        "expected_non_system_image_count": expected_projection[
            "image_count"
        ],
        "expected_non_system_projection_sha256": expected_projection[
            "projection_sha256"
        ],
        "observed_non_system_image_count": len(observed_non_system_rows),
        "observed_non_system_projection_sha256": (
            observed_projection_sha256
        ),
        "raw_kernel_inventory_sha256": inventory.inventory_sha256,
        "all_non_system_images_in_frozen_closure": True,
        "sealed_system_images_bound_to_cache": True,
    }
    mapping["record_sha256"] = canonical_sha256(mapping)
    return mapping


def validate_runtime_native_scan(
    value: object,
    closure: Mapping[str, Any],
    expected_process: KernelProcessIdentity,
) -> dict[str, Any]:
    """Validate a retained runtime scan without observing the live process."""

    mapping = _validate_runtime_scan_structure(value)
    frozen = validate_native_closure(dict(closure), reobserve=False)
    expected_projection = native_runtime_non_system_projection(frozen)
    if (
        mapping["schema_id"] != NATIVE_RUNTIME_SCAN_SCHEMA
        or mapping["authority"] != NATIVE_RUNTIME_SCAN_AUTHORITY
        or mapping["process"] != _process_mapping(expected_process)
        or mapping["native_closure_sha256"] != frozen["closure_sha256"]
        or mapping["system_cache_sha256"]
        != canonical_sha256(frozen["system_cache"])
        or mapping["staged_executable_sha256"]
        != frozen["roots"]["staged_sha256"]
        or mapping["staged_executable_content_stable"] is not True
        or mapping["all_non_system_images_in_frozen_closure"] is not True
        or mapping["sealed_system_images_bound_to_cache"] is not True
    ):
        raise BrokerProtocolError("runtime native scan authority differs")
    images_by_path = {
        item["resolved_path"]: item for item in frozen["images"]
    }
    staged_count = 0
    observed_non_system_rows: list[dict[str, Any]] = []
    for mapped in mapping["mapped_images"]:
        path = mapped["resolved_path"]
        if mapped["system_image"] is True:
            expected_member_sha256 = canonical_sha256(
                {
                    "authority": SYSTEM_CACHE_AUTHORITY,
                    "system_cache_sha256": canonical_sha256(
                        frozen["system_cache"]
                    ),
                    "mapped_path": path,
                }
            )
        else:
            closure_image = images_by_path.get(path)
            if closure_image is None:
                raise BrokerProtocolError(
                    "runtime scan contains an image outside closure"
                )
            for name in (
                "resolved_path",
                "device",
                "inode",
                "mode",
                "uid",
                "gid",
                "nlink",
                "size",
                "mtime_ns",
                "ctime_ns",
            ):
                if mapped[name] != closure_image[name]:
                    raise BrokerProtocolError(
                        "runtime scan image identity differs from closure"
                    )
            expected_member_sha256 = closure_image["sha256"]
        if mapped["closure_image_sha256"] != expected_member_sha256:
            raise BrokerProtocolError("runtime scan membership digest differs")
        if path == frozen["roots"]["staged_executable"]:
            staged_count += 1
        if mapped["system_image"] is False:
            observed_non_system_rows.append(
                {
                    "resolved_path": mapped["resolved_path"],
                    "sha256": mapped["closure_image_sha256"],
                    "device": mapped["device"],
                    "inode": mapped["inode"],
                    "mode": mapped["mode"],
                    "uid": mapped["uid"],
                    "gid": mapped["gid"],
                    "nlink": mapped["nlink"],
                    "size": mapped["size"],
                    "mtime_ns": mapped["mtime_ns"],
                    "ctime_ns": mapped["ctime_ns"],
                }
            )
    observed_projection = {
        "schema_id": "parser-tesseract-runtime-non-system-projection-v1",
        "staged_root": frozen["roots"]["staged_executable"],
        "image_count": len(observed_non_system_rows),
        "images": observed_non_system_rows,
    }
    observed_projection_sha256 = canonical_sha256(observed_projection)
    if (
        staged_count != 1
        or mapping["expected_non_system_image_count"]
        != expected_projection["image_count"]
        or mapping["observed_non_system_image_count"]
        != len(observed_non_system_rows)
        or mapping["expected_non_system_projection_sha256"]
        != expected_projection["projection_sha256"]
        or mapping["observed_non_system_projection_sha256"]
        != observed_projection_sha256
        or observed_non_system_rows != expected_projection["images"]
        or observed_projection_sha256
        != expected_projection["projection_sha256"]
    ):
        raise BrokerProtocolError("runtime scan staged executable differs")
    return mapping


def validate_native_closure(
    value: object,
    *,
    reobserve: bool = True,
) -> dict[str, Any]:
    """Strictly validate and, by default, rederive a closure from disk."""

    mapping = _strict_object(
        value,
        {
            "schema_id",
            "trust_model",
            "containment_claim",
            "non_system_image_owner_policy",
            "non_system_image_mutability_policy",
            "runpath_resolution_policy",
            "ancestor_only_runpath_edge_count",
            "dynamic_loader_import_markers",
            "dynamic_loader_importing_images",
            "dynamic_loader_importing_image_count",
            "dynamic_loader_imports_sha256",
            "roots",
            "runtime_gate",
            "images",
            "edges",
            "system_cache",
            "total_hashed_bytes",
            "image_count",
            "edge_count",
            "closure_sha256",
        },
        "native closure",
    )
    if (
        mapping["schema_id"] != NATIVE_CLOSURE_SCHEMA
        or mapping["trust_model"] != NATIVE_CLOSURE_TRUST_MODEL
        or mapping["containment_claim"]
        != "none-trusted-pinned-native-computation"
        or mapping["non_system_image_owner_policy"]
        != NON_SYSTEM_IMAGE_OWNER_POLICY
        or mapping["non_system_image_mutability_policy"]
        != NON_SYSTEM_IMAGE_MUTABILITY_POLICY
        or mapping["runpath_resolution_policy"] != RUNPATH_RESOLUTION_POLICY
        or type(mapping["ancestor_only_runpath_edge_count"]) is not int
        or mapping["ancestor_only_runpath_edge_count"] != 0
        or mapping["dynamic_loader_import_markers"]
        != list(_DYNAMIC_LOADER_IMPORT_MARKERS)
        or not isinstance(mapping["dynamic_loader_importing_images"], list)
        or type(mapping["dynamic_loader_importing_image_count"]) is not int
        or mapping["dynamic_loader_importing_image_count"]
        != len(mapping["dynamic_loader_importing_images"])
        or mapping["dynamic_loader_imports_sha256"]
        != canonical_sha256(
            {
                "markers": mapping["dynamic_loader_import_markers"],
                "images": mapping["dynamic_loader_importing_images"],
            }
        )
    ):
        raise BrokerProtocolError("native closure trust boundary differs")
    roots = _strict_object(
        mapping["roots"],
        {
            "source_executable",
            "staged_executable",
            "source_sha256",
            "staged_sha256",
            "source_dependency_projection_sha256",
            "staged_dependency_projection_sha256",
        },
        "native closure roots",
    )
    runtime_gate = mapping["runtime_gate"]
    if runtime_gate is not None:
        runtime_gate = _strict_object(
            runtime_gate,
            {
                "schema_id",
                "authority",
                "initializer_order_limitation",
                "ack_authority",
                "ack_bytes",
                "inherited_gate_fd",
                "source",
                "library",
                "dyld_environment_names",
                "constructor_self_sigstop_before_main",
                "malicious_initializer_containment_claim",
                "record_sha256",
            },
            "native runtime gate",
        )
        identity_keys = {
            "resolved_path",
            "sha256",
            "device",
            "inode",
            "mode",
            "uid",
            "gid",
            "nlink",
            "size",
            "mtime_ns",
            "ctime_ns",
        }
        source_identity = _strict_object(
            runtime_gate["source"], identity_keys, "runtime gate source"
        )
        library_identity = _strict_object(
            runtime_gate["library"], identity_keys, "runtime gate library"
        )
        if (
            runtime_gate["schema_id"] != NATIVE_RUNTIME_GATE_SCHEMA
            or runtime_gate["authority"] != NATIVE_RUNTIME_GATE_AUTHORITY
            or runtime_gate["initializer_order_limitation"]
            != NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION
            or runtime_gate["ack_authority"]
            != NATIVE_RUNTIME_GATE_ACK_AUTHORITY
            or runtime_gate["ack_bytes"] != NATIVE_RUNTIME_GATE_ACK_BYTES
            or runtime_gate["inherited_gate_fd"] != NATIVE_RUNTIME_GATE_FD
            or runtime_gate["dyld_environment_names"]
            != [
                "DYLD_INSERT_LIBRARIES",
                "PARSER_TESSERACT_RUNTIME_GATE_FD",
                "PARSER_TESSERACT_RUNTIME_GATE_NONCE",
            ]
            or runtime_gate["constructor_self_sigstop_before_main"] is not True
            or runtime_gate["malicious_initializer_containment_claim"] is not False
            or stat.S_IMODE(source_identity["mode"]) != 0o500
            or stat.S_IMODE(library_identity["mode"]) != 0o500
            or source_identity["uid"] != os.geteuid()
            or library_identity["uid"] != os.geteuid()
            or source_identity["nlink"] != 1
            or library_identity["nlink"] != 1
            or runtime_gate["record_sha256"]
            != canonical_sha256(
                {
                    key: item
                    for key, item in runtime_gate.items()
                    if key != "record_sha256"
                }
            )
        ):
            raise BrokerProtocolError("native runtime gate custody differs")
    raw_images = mapping["images"]
    if not isinstance(raw_images, list):
        raise BrokerProtocolError("native closure images must be an array")
    expected_dynamic_images: list[dict[str, Any]] = []
    for raw_image in raw_images:
        if not isinstance(raw_image, dict):
            raise BrokerProtocolError("native closure image differs")
        imports = raw_image.get("dynamic_loader_imports")
        imports_family = raw_image.get("imports_dynamic_loader_family")
        if (
            not isinstance(imports, list)
            or imports != sorted(set(imports))
            or any(
                not isinstance(symbol, str)
                or not symbol
                or len(symbol) > 4096
                or not any(
                    marker in symbol
                    for marker in _DYNAMIC_LOADER_IMPORT_MARKERS
                )
                for symbol in imports
            )
            or type(imports_family) is not bool
            or imports_family != bool(imports)
        ):
            raise BrokerProtocolError(
                "native dynamic-loader import disclosure differs"
            )
        if imports_family:
            expected_dynamic_images.append(
                {
                    "resolved_path": raw_image.get("resolved_path"),
                    "sha256": raw_image.get("sha256"),
                    "dynamic_loader_imports": imports,
                }
            )
    if mapping["dynamic_loader_importing_images"] != expected_dynamic_images:
        raise BrokerProtocolError(
            "native dynamic-loader image projection differs"
        )
    if runtime_gate is not None:
        image_by_path = {
            raw_image.get("resolved_path"): raw_image
            for raw_image in raw_images
            if isinstance(raw_image, dict)
        }
        gate_image = image_by_path.get(runtime_gate["library"]["resolved_path"])
        if gate_image is None or any(
            gate_image.get(name) != runtime_gate["library"][name]
            for name in runtime_gate["library"]
        ):
            raise BrokerProtocolError(
                "native runtime gate is outside the frozen image graph"
            )
    supplied_sha256 = mapping["closure_sha256"]
    if (
        not isinstance(supplied_sha256, str)
        or len(supplied_sha256) != 64
        or any(character not in "0123456789abcdef" for character in supplied_sha256)
        or supplied_sha256
        != canonical_sha256({key: item for key, item in mapping.items() if key != "closure_sha256"})
    ):
        raise BrokerProtocolError("native closure digest differs")
    if not reobserve:
        # Canonical round-trip rejects non-JSON values and preserves exact
        # bool-vs-int distinctions before a caller retains the mapping.
        canonical_json_bytes(mapping)
        return mapping
    observed = derive_native_closure(
        roots["source_executable"],
        roots["staged_executable"],
        runtime_gate_source_path=(
            None
            if runtime_gate is None
            else runtime_gate["source"]["resolved_path"]
        ),
        runtime_gate_library_path=(
            None
            if runtime_gate is None
            else runtime_gate["library"]["resolved_path"]
        ),
    )
    if canonical_json_bytes(observed) != canonical_json_bytes(mapping):
        raise BrokerProtocolError("native closure changed during reobservation")
    return mapping


def native_closure_sha256(value: Mapping[str, Any]) -> str:
    """Return the validated closure digest without re-reading disk."""

    return str(validate_native_closure(dict(value), reobserve=False)["closure_sha256"])


__all__ = [
    "NATIVE_CLOSURE_SCHEMA",
    "NATIVE_CLOSURE_TRUST_MODEL",
    "NATIVE_RUNTIME_POLLING_COMPLETENESS",
    "NATIVE_RUNTIME_GATE_ACK_AUTHORITY",
    "NATIVE_RUNTIME_GATE_ACK_BYTES",
    "NATIVE_RUNTIME_GATE_AUTHORITY",
    "NATIVE_RUNTIME_GATE_FD",
    "NATIVE_RUNTIME_GATE_INITIALIZER_LIMITATION",
    "NATIVE_RUNTIME_GATE_SCHEMA",
    "NATIVE_RUNTIME_SCAN_AUTHORITY",
    "NATIVE_RUNTIME_SCAN_SCHEMA",
    "NON_SYSTEM_IMAGE_MUTABILITY_POLICY",
    "NON_SYSTEM_IMAGE_OWNER_POLICY",
    "RUNPATH_RESOLUTION_POLICY",
    "SYSTEM_CACHE_AUTHORITY",
    "derive_native_closure",
    "native_closure_sha256",
    "native_runtime_non_system_projection",
    "observe_runtime_native_scan",
    "validate_runtime_native_scan",
    "validate_native_closure",
]
