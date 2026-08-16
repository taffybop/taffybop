from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.text_run_semantics import _target_path_key


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "p03_us05_target_path_order.json"
)


def test_backend_target_path_order_matches_frontend_interop_fixture() -> None:
    fixture: dict[str, Any] = json.loads(FIXTURE_PATH.read_text("utf-8"))
    assert fixture["policy_id"] == "p03-text-run-semantics-v1"

    ordered_paths = [tuple(path) for path in fixture["ordered_paths"]]
    assert sorted(
        reversed(ordered_paths),
        key=_target_path_key,
    ) == ordered_paths
