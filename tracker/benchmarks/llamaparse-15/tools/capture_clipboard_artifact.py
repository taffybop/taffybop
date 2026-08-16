#!/usr/bin/env python3
"""Persist a browser-captured artifact without shell interpolation."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("payload_base64", nargs="?")
    parser.add_argument("--stdin-base64", action="store_true")
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()

    if args.stdin_base64 == (args.payload_base64 is not None):
        raise SystemExit(
            "provide exactly one base64 payload argument or --stdin-base64"
        )

    destination = args.path.resolve()
    workspace = Path.cwd().resolve()
    if workspace not in destination.parents:
        raise SystemExit("destination must be inside the workspace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = sys.stdin.buffer.read() if args.stdin_base64 else args.payload_base64
    decoded = base64.b64decode(payload, validate=True)
    if args.text:
        decoded.decode("utf-8")
    destination.write_bytes(decoded)


if __name__ == "__main__":
    main()
