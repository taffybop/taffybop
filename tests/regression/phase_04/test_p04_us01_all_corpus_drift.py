"""Offline all-corpus drift screen for P04-US01 table span fidelity.

The gate is intentionally opt-in and expensive: every parametrized result
performs one default-off parse and two independent enabled parses of one of the
15 reviewed PDFs.  Run it with ``P04_US01_RUN_ALL_CORPUS_DRIFT=1``.  Each case
publishes a compact JSON review record through pytest's ``record_property`` so
CI can retain per-document results in JUnit output.

Default-off output must equal the sealed post-US07/Phase-03 predecessor after
normalizing only declared processing timings.  Enabled output may add P04-US01
evidence to table items; it may change canonical table structure only for the
two source-frozen positive recoveries already accepted by the US01 oracle and
production benchmark.  Every nonvalid candidate must remain the exact
predecessor table once its diagnostic sidecar is removed.  Canonical
presentation content may change only when an authoritative marked table
projection changes, and only in the block and views bound to that exact table.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import os
import socket
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

import pytest

from app.config import Settings
from app.models import (
    CanonicalSourceCustody,
    ContentItem,
    ParseResult,
    _TABLE_MAX_DOCUMENT_SIDECAR_BYTES,
    _canonical_ir_id,
    _canonical_item_primary_id,
    _canonical_presentation_sha256,
    _canonical_table_text,
)
from app.services.presentation import CanonicalPresentation
from tests.fixtures.phase_03.running_regions.contract import OFFLINE_ENVIRONMENT
from tests.fixtures.phase_03.running_regions.oracle import (
    PREDECESSOR_CONFIGURATION,
    PREDECESSOR_OUTPUT_IDENTITIES,
    PREDECESSOR_OUTPUT_ROOT,
    SOURCE_IDENTITIES,
)
from tests.fixtures.phase_04.tables.content_bbox_oracle import (
    source_content_bbox_oracle_metadata,
)
from tests.fixtures.phase_04.tables.metrics import (
    HOSTED_USAGE,
    _score_exact_table,
    oracle_sha256,
)
from tests.fixtures.phase_04.tables.oracle import (
    EXHIBIT7_EXACT,
    P04_US01_REAL_ORACLE,
)


WORKSPACE = Path(__file__).resolve().parents[3]
RUN_ALL_CORPUS_ENVIRONMENT = "P04_US01_RUN_ALL_CORPUS_DRIFT"
CASE_IDS = tuple(SOURCE_IDENTITIES)
P04_REVIEWED_CASE_IDS = frozenset(
    source.case_id for source in P04_US01_REAL_ORACLE.sources
)
DECLARED_TIMING_PATHS = (
    ("processing", "duration_ms"),
    ("processing", "form_semantics", "extraction_ms"),
    ("processing", "form_semantics", "projection_ms"),
    ("processing", "form_semantics", "total_ms"),
    ("processing", "outline_structure", "extraction_ms"),
    ("processing", "outline_structure", "projection_ms"),
    ("processing", "outline_structure", "total_ms"),
)
LATER_PHASE04_FIELDS = ("reconciliation", "gate", "continuation")
PHASE05_FIELDS = frozenset(
    {
        "visual_structure",
        "chart_structure",
        "diagram_topology",
        "axes",
        "legends",
        "series",
        "points",
        "nodes",
        "edges",
        "connectors",
        "values_not_structured",
        "relationships_not_structured",
    }
)
AUTHORIZED_CANONICAL_TABLE_DELTAS = frozenset(
    {
        ("catastrophe-recap", 1, "p1-i3"),
        ("postal-10k", 1, "p1-i3"),
    }
)
TABLE_OWNED_CANONICAL_FIELDS = frozenset(
    {
        "value",
        "rows",
        "cells",
        "row_count",
        "column_count",
        "html",
        "md",
        "csv",
        "table_evidence",
    }
)
_ABSENT_CUSTODY = object()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pop_path(value: dict[str, Any], path: tuple[str, ...]) -> None:
    owner: Any = value
    for component in path[:-1]:
        if type(owner) is not dict:
            return
        owner = owner.get(component)
    if type(owner) is dict:
        owner.pop(path[-1], None)


def _timing_normalized(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    for path in DECLARED_TIMING_PATHS:
        _pop_path(normalized, path)
    return normalized


def _blocked_network(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("hosted/network use is forbidden in P04-US01 corpus drift")


def _verified_source(case_id: str) -> bytes:
    identity = SOURCE_IDENTITIES[case_id]
    source = (WORKSPACE / identity["path"]).read_bytes()
    if len(source) != identity["size_bytes"]:
        raise AssertionError(f"{case_id}: reviewed source size drifted")
    if _sha256_bytes(source) != identity["sha256"]:
        raise AssertionError(f"{case_id}: reviewed source digest drifted")
    return source


def _frozen_predecessor(case_id: str) -> dict[str, Any]:
    path = WORKSPACE / PREDECESSOR_OUTPUT_ROOT / case_id / "our-output.json"
    raw = path.read_bytes()
    identity = PREDECESSOR_OUTPUT_IDENTITIES[case_id]
    if len(raw) != identity["size_bytes"]:
        raise AssertionError(f"{case_id}: Phase03 predecessor size drifted")
    if _sha256_bytes(raw) != identity["sha256"]:
        raise AssertionError(f"{case_id}: Phase03 predecessor digest drifted")
    value = json.loads(raw)
    if type(value) is not dict:
        raise AssertionError(f"{case_id}: Phase03 predecessor is not an object")
    return value


def _settings(*, enabled: bool) -> Settings:
    settings = Settings(
        **PREDECESSOR_CONFIGURATION,
        table_span_fidelity_enabled=enabled,
    )
    if settings.table_evidence_reconciliation_enabled:
        raise AssertionError("P04-US02 reconciliation must remain disabled")
    if settings.table_candidate_gate_enabled:
        raise AssertionError("P04-US04 candidate gating must remain disabled")
    if settings.table_multi_page_merge_enabled:
        raise AssertionError("P04-US03 continuation merging must remain disabled")
    return settings


def _parse_local(case_id: str, *, enabled: bool) -> tuple[dict[str, Any], float]:
    # Import after the offline/network guards are installed so optional model
    # loaders cannot silently turn this local regression into hosted use.
    source = _verified_source(case_id)
    started = time.perf_counter()
    with (
        patch.dict(os.environ, dict(OFFLINE_ENVIRONMENT), clear=False),
        patch.object(socket.socket, "connect", _blocked_network),
        patch("socket.create_connection", _blocked_network),
    ):
        from app.services.pipeline import parse_document

        result = parse_document(
            source,
            f"{case_id}.pdf",
            _settings(enabled=enabled),
        )
    elapsed = time.perf_counter() - started
    payload = result.model_dump(mode="json", exclude_none=True)
    ParseResult.model_validate(payload)
    return payload, elapsed


def _tables(payload: Mapping[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    return [
        (page["page_index"], item)
        for page in payload.get("pages", [])
        if type(page) is dict
        for item in page.get("items", [])
        if type(item) is dict and item.get("type") == "table"
    ]


def _assert_no_phase05_fields(value: Any, *, case_id: str, path: str = "$") -> None:
    if type(value) is dict:
        found = sorted(PHASE05_FIELDS.intersection(value))
        if found:
            raise AssertionError(
                f"{case_id}: Phase05 fields appeared at {path}: {found}"
            )
        for key, member in value.items():
            _assert_no_phase05_fields(
                member,
                case_id=case_id,
                path=f"{path}/{key}",
            )
    elif type(value) is list:
        for index, member in enumerate(value):
            _assert_no_phase05_fields(
                member,
                case_id=case_id,
                path=f"{path}/{index}",
            )


def _expected_html(rows: list[list[str]]) -> str:
    lines = ["<table>", "  <thead>", "    <tr>"]
    for value in rows[0]:
        escaped = html.escape(value).replace("\n", "<br>")
        lines.append(f'      <th scope="col">{escaped}</th>')
    lines.extend(("    </tr>", "  </thead>", "  <tbody>"))
    for row in rows[1:]:
        lines.append("    <tr>")
        for value in row:
            escaped = html.escape(value).replace("\n", "<br>")
            lines.append(f"      <td>{escaped}</td>")
        lines.append("    </tr>")
    lines.extend(("  </tbody>", "</table>"))
    return "\n".join(lines)


def _expected_csv(rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().rstrip("\n")


def _assert_table_noncanonical_fields_unchanged(
    predecessor: Mapping[str, Any],
    enabled: Mapping[str, Any],
    *,
    case_id: str,
    table_id: str,
) -> None:
    fields = (set(predecessor) | set(enabled)) - TABLE_OWNED_CANONICAL_FIELDS
    changed = sorted(
        field for field in fields if predecessor.get(field) != enabled.get(field)
    )
    if changed:
        raise AssertionError(
            f"{case_id}/{table_id}: non-table-owned fields drifted: {changed}"
        )


def _assert_catastrophe_delta(
    predecessor: Mapping[str, Any],
    enabled: Mapping[str, Any],
) -> None:
    _assert_table_noncanonical_fields_unchanged(
        predecessor,
        enabled,
        case_id="catastrophe-recap",
        table_id="p1-i3",
    )
    scored = _score_exact_table(
        {"pages": [{"page_index": 1, "items": [dict(enabled)]}]},
        EXHIBIT7_EXACT,
    )
    if scored["passed"] is not True:
        raise AssertionError(
            "catastrophe-recap/p1-i3: canonical delta differs from exact "
            f"Exhibit 7 truth: {scored}"
        )


def _assert_postal_delta(
    predecessor: Mapping[str, Any],
    enabled: Mapping[str, Any],
) -> None:
    _assert_table_noncanonical_fields_unchanged(
        predecessor,
        enabled,
        case_id="postal-10k",
        table_id="p1-i3",
    )
    predecessor_rows = predecessor.get("rows")
    rows = enabled.get("rows")
    if type(predecessor_rows) is not list or type(rows) is not list:
        raise AssertionError("postal-10k/p1-i3: table rows are unavailable")
    expected_rows = [*deepcopy(predecessor_rows), [
        "FERS",
        "Federal Employees Retirement System",
    ]]
    if rows != expected_rows or enabled.get("value") != expected_rows:
        raise AssertionError(
            "postal-10k/p1-i3: only the reviewed FERS boundary row may be added"
        )
    if (
        enabled.get("row_count") != 40
        or enabled.get("column_count") != 2
        or len(rows) != 40
    ):
        raise AssertionError("postal-10k/p1-i3: reviewed grid shape differs")
    cells = enabled.get("cells")
    if type(cells) is not list or len(cells) != 80:
        raise AssertionError("postal-10k/p1-i3: reviewed explicit cells differ")
    by_position = {
        (cell.get("row"), cell.get("column")): cell
        for cell in cells
        if type(cell) is dict
    }
    if set(by_position) != {(row, column) for row in range(40) for column in range(2)}:
        raise AssertionError("postal-10k/p1-i3: explicit cell positions differ")
    for row_index, row in enumerate(expected_rows):
        for column_index, text in enumerate(row):
            cell = by_position[(row_index, column_index)]
            if (
                cell.get("text") != text
                or cell.get("row_span") != 1
                or cell.get("col_span") != 1
                or cell.get("column_header") is not (row_index == 0)
            ):
                raise AssertionError(
                    "postal-10k/p1-i3: a reviewed explicit cell differs at "
                    f"({row_index}, {column_index})"
                )
    for position in ((39, 0), (39, 1)):
        cell = by_position[position]
        bbox = cell.get("bbox")
        if (
            type(bbox) is not dict
            or bbox.get("unit") != "pt"
            or not all(
                type(bbox.get(field)) in (int, float)
                and type(bbox.get(field)) is not bool
                and math.isfinite(float(bbox[field]))
                for field in ("x", "y", "width", "height")
            )
            or not cell.get("source_object_ids")
            or not cell.get("evidence_ids")
        ):
            raise AssertionError(
                "postal-10k/p1-i3: FERS bbox/provenance is unsupported"
            )
    expected_html = _expected_html(expected_rows)
    if (
        enabled.get("html") != expected_html
        or enabled.get("md") != expected_html
        or enabled.get("csv") != _expected_csv(expected_rows)
    ):
        raise AssertionError(
            "postal-10k/p1-i3: canonical representations diverged"
        )


def _assert_authorized_canonical_delta(
    case_id: str,
    page_index: int,
    predecessor: Mapping[str, Any],
    enabled: Mapping[str, Any],
) -> None:
    table_id = str(enabled.get("id") or "")
    key = (case_id, page_index, table_id)
    if key not in AUTHORIZED_CANONICAL_TABLE_DELTAS:
        raise AssertionError(
            f"{case_id}/{table_id}: canonical table drift lacks reviewed US01 truth"
        )
    if key[0] == "catastrophe-recap":
        _assert_catastrophe_delta(predecessor, enabled)
    else:
        _assert_postal_delta(predecessor, enabled)


def _assert_marked_table(
    case_id: str,
    page_index: int,
    predecessor: Mapping[str, Any],
    enabled: Mapping[str, Any],
) -> tuple[str, bool]:
    table_id = str(enabled.get("id") or "")
    sidecar = enabled.get("table_evidence")
    if type(sidecar) is not dict:
        raise AssertionError(f"{case_id}/{table_id}: table marker is malformed")
    for field in LATER_PHASE04_FIELDS:
        if field not in sidecar or sidecar[field] is not None:
            raise AssertionError(
                f"{case_id}/{table_id}: later Phase04 field {field} is active"
            )
    if sidecar.get("scope") != ["P04-US01"]:
        raise AssertionError(f"{case_id}/{table_id}: table scope escaped US01")
    validated = ContentItem.model_validate(dict(enabled))
    if validated.model_dump(mode="json", exclude_none=True) != dict(enabled):
        raise AssertionError(
            f"{case_id}/{table_id}: table API round-trip silently changed authority"
        )
    projection = dict(enabled)
    projection.pop("table_evidence")
    projection_changed = projection != dict(predecessor)
    status = sidecar.get("status")
    authorized_key = (case_id, page_index, table_id)
    if authorized_key in AUTHORIZED_CANONICAL_TABLE_DELTAS:
        if status != "valid":
            raise AssertionError(
                f"{case_id}/{table_id}: reviewed positive table is not valid"
            )
        _assert_authorized_canonical_delta(
            case_id,
            page_index,
            predecessor,
            enabled,
        )
    if status != "valid" and projection_changed:
        raise AssertionError(
            f"{case_id}/{table_id}: nonvalid table did not preserve predecessor"
        )
    if (
        status == "valid"
        and projection_changed
        and authorized_key not in AUTHORIZED_CANONICAL_TABLE_DELTAS
    ):
        _assert_authorized_canonical_delta(
            case_id,
            page_index,
            predecessor,
            enabled,
        )
    return str(status), projection_changed


def _assert_canonical_view_delta(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    changed_block_ids: set[str],
    case_id: str,
    view_path: str,
) -> None:
    if set(before) != {"block_ids", "markdown", "text"} or set(after) != set(
        before
    ):
        raise AssertionError(f"{case_id}: canonical view fields drifted at {view_path}")
    before_ids = before.get("block_ids")
    after_ids = after.get("block_ids")
    if before_ids != after_ids:
        raise AssertionError(
            f"{case_id}: canonical block order/IDs drifted at {view_path}"
        )
    if type(before_ids) is not list:
        raise AssertionError(f"{case_id}: canonical block IDs malformed at {view_path}")
    view_changed = bool(changed_block_ids.intersection(before_ids))
    if not view_changed and before != after:
        raise AssertionError(
            f"{case_id}: unrelated canonical view drifted at {view_path}"
        )


def _canonical_table_cell_closure(
    primary_id: str,
    table: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    """Reproduce only the target-seeded public-table cell closure."""

    cells = table.get("cells")
    if (
        type(primary_id) is not str
        or not primary_id
        or type(cells) is not list
        or not cells
        or len(cells) > 65_536
        or any(type(cell) is not dict for cell in cells)
    ):
        raise AssertionError("canonical target-seeded cell closure differs")
    element_ids = [
        _canonical_ir_id("el", primary_id, "cells", index, cell)
        for index, cell in enumerate(cells)
    ]
    relationship_ids = [
        _canonical_ir_id(
            "rel",
            "contains",
            primary_id,
            element_id,
            "cells",
            index,
        )
        for index, element_id in enumerate(element_ids)
    ]
    if (
        len(element_ids) != len(set(element_ids))
        or len(relationship_ids) != len(set(relationship_ids))
    ):
        raise AssertionError("canonical target-seeded cell closure differs")
    return element_ids, relationship_ids


def _assert_target_seeded_table_graph_delta(
    before_block: Mapping[str, Any],
    after_block: Mapping[str, Any],
    before_table: Mapping[str, Any],
    after_table: Mapping[str, Any],
) -> None:
    """Permit only exact old-cell -> new-cell replacement on one table seed."""

    primary_id = after_block.get("primary_element_id")
    if (
        type(primary_id) is not str
        or not primary_id
        or before_block.get("primary_element_id") != primary_id
    ):
        raise AssertionError("canonical target-seeded cell closure differs")
    before_cell_ids, before_cell_relationship_ids = (
        _canonical_table_cell_closure(primary_id, before_table)
    )
    after_cell_ids, after_cell_relationship_ids = (
        _canonical_table_cell_closure(primary_id, after_table)
    )
    before_contributors = before_block.get("contributing_element_ids")
    after_contributors = after_block.get("contributing_element_ids")
    if not all(
        type(values) is list
        and all(type(value) is str and value for value in values)
        and len(values) == len(set(values))
        for values in (before_contributors, after_contributors)
    ):
        raise AssertionError("canonical target-seeded cell closure differs")
    assert isinstance(before_contributors, list)
    assert isinstance(after_contributors, list)
    if (
        before_contributors[-len(before_cell_ids) :] != before_cell_ids
        or after_contributors[-len(after_cell_ids) :] != after_cell_ids
    ):
        raise AssertionError("canonical target-seeded cell closure differs")
    before_prefix = before_contributors[: -len(before_cell_ids)]
    after_prefix = after_contributors[: -len(after_cell_ids)]
    if (
        not before_prefix
        or before_prefix[0] != primary_id
        or after_prefix != before_prefix
    ):
        raise AssertionError("canonical target-seeded cell closure differs")

    before_relationships = before_block.get("relationship_ids")
    after_relationships = after_block.get("relationship_ids")
    if not all(
        type(values) is list
        and all(type(value) is str and value for value in values)
        and values == sorted(values)
        and len(values) == len(set(values))
        for values in (before_relationships, after_relationships)
    ):
        raise AssertionError("canonical target-seeded cell closure differs")
    assert isinstance(before_relationships, list)
    assert isinstance(after_relationships, list)
    before_cell_relationship_set = set(before_cell_relationship_ids)
    after_cell_relationship_set = set(after_cell_relationship_ids)
    if (
        not before_cell_relationship_set.issubset(before_relationships)
        or not after_cell_relationship_set.issubset(after_relationships)
        or set(before_relationships) - before_cell_relationship_set
        != set(after_relationships) - after_cell_relationship_set
    ):
        raise AssertionError("canonical target-seeded cell closure differs")


def _canonical_table_owned_output(
    table: Mapping[str, Any] | ContentItem,
) -> tuple[str, str]:
    validated = (
        table
        if isinstance(table, ContentItem)
        else ContentItem.model_validate(table)
    )
    raw_html = (validated.model_extra or {}).get("html")
    if type(raw_html) is not str or not raw_html.strip():
        raise AssertionError("canonical target-seeded content closure differs")
    return raw_html.strip(), _canonical_table_text(validated)


def _target_seeded_scalar_with_preserved_overlay(
    baseline_scalar: Any,
    predecessor_table_scalar: str,
    candidate_table_scalar: str,
) -> str:
    if type(baseline_scalar) is not str or not predecessor_table_scalar:
        raise AssertionError("canonical target-seeded content closure differs")
    if baseline_scalar == predecessor_table_scalar:
        return candidate_table_scalar
    suffix = f"\n\n{predecessor_table_scalar}"
    if not baseline_scalar.endswith(suffix):
        raise AssertionError("canonical target-seeded content closure differs")
    overlay = baseline_scalar[: -len(suffix)]
    if not overlay or overlay != overlay.strip():
        raise AssertionError("canonical target-seeded content closure differs")
    return f"{overlay}\n\n{candidate_table_scalar}"


def _assert_target_seeded_table_content_delta(
    before_block: Mapping[str, Any],
    after_block: Mapping[str, Any],
    before_table: Mapping[str, Any],
    after_table: Mapping[str, Any] | ContentItem,
) -> None:
    """Replace only the exact table-owned scalar tail under a P03 overlay."""

    before_output = _canonical_table_owned_output(before_table)
    after_output = _canonical_table_owned_output(after_table)
    for index, field in enumerate(("markdown", "text")):
        expected = _target_seeded_scalar_with_preserved_overlay(
            before_block.get(field),
            before_output[index],
            after_output[index],
        )
        if after_block.get(field) != expected:
            raise AssertionError(
                "canonical target-seeded content closure differs"
            )


def _assert_correlated_canonical_delta(
    case_id: str,
    predecessor: Mapping[str, Any],
    enabled: Mapping[str, Any],
    changed_tables: Mapping[
        str,
        tuple[int, Mapping[str, Any], Mapping[str, Any], ContentItem],
    ],
) -> dict[str, Any]:
    """Allow exact target-seeded table closure changes on marked primaries."""

    if type(predecessor) is not dict or type(enabled) is not dict:
        raise AssertionError(f"{case_id}: canonical presentation is unavailable")
    # These validators close graph, page, block, relationship, and page/document
    # view consistency before the pairwise custody comparison below.
    CanonicalPresentation.model_validate(predecessor)
    CanonicalPresentation.model_validate(enabled)
    if not changed_tables:
        if predecessor != enabled:
            raise AssertionError(
                f"{case_id}: sidecar-only tables changed canonical bytes"
            )
        return {"changed_canonical_block_ids": []}

    root_fields = {"schema_version", "source_ir_version", "policy_id"}
    if any(predecessor.get(field) != enabled.get(field) for field in root_fields):
        raise AssertionError(f"{case_id}: canonical root policy/version drifted")
    before_pages = predecessor.get("pages")
    after_pages = enabled.get("pages")
    if type(before_pages) is not list or type(after_pages) is not list:
        raise AssertionError(f"{case_id}: canonical pages are unavailable")
    if len(before_pages) != len(after_pages):
        raise AssertionError(f"{case_id}: canonical page membership drifted")

    changed_block_ids: set[str] = set()
    changed_primary_ids: set[str] = set()
    for before_page, after_page in zip(before_pages, after_pages, strict=True):
        page_identity_fields = {
            "page_id",
            "page_index",
            "page_number",
            "page_label",
            "page_identity",
        }
        if any(
            before_page.get(field) != after_page.get(field)
            for field in page_identity_fields
        ):
            raise AssertionError(
                f"{case_id}: canonical page identity drifted on "
                f"{before_page.get('page_index')}"
            )
        before_blocks = before_page.get("blocks")
        after_blocks = after_page.get("blocks")
        if type(before_blocks) is not list or type(after_blocks) is not list:
            raise AssertionError(f"{case_id}: canonical blocks are unavailable")
        if len(before_blocks) != len(after_blocks):
            raise AssertionError(
                f"{case_id}: canonical block membership drifted on "
                f"{before_page.get('page_index')}"
            )
        for before_block, after_block in zip(
            before_blocks,
            after_blocks,
            strict=True,
        ):
            if before_block == after_block:
                continue
            primary_id = str(after_block.get("primary_element_id") or "")
            binding = changed_tables.get(primary_id)
            if binding is None:
                raise AssertionError(
                    f"{case_id}: changed canonical block does not map to a "
                    f"changed marked table: {after_block.get('id')}"
                )
            immutable_fields = set(before_block) | set(after_block)
            immutable_fields -= {
                "contributing_element_ids",
                "markdown",
                "relationship_ids",
                "text",
            }
            changed_immutable = sorted(
                field
                for field in immutable_fields
                if before_block.get(field) != after_block.get(field)
            )
            if changed_immutable:
                raise AssertionError(
                    f"{case_id}: canonical block IDs/order/relationships drifted "
                    f"for {before_block.get('id')}: {changed_immutable}"
                )
            page_index, before_table, after_table, table = binding
            _assert_target_seeded_table_graph_delta(
                before_block,
                after_block,
                before_table,
                after_table,
            )
            _assert_target_seeded_table_content_delta(
                before_block,
                after_block,
                before_table,
                table,
            )
            content_mismatches = [
                field
                for field, matches in (
                    ("page_index", after_page.get("page_index") == page_index),
                    (
                        "primary_element_type",
                        str(after_block.get("primary_element_type") or "").casefold()
                        == "table",
                    ),
                    ("omission_reason", after_block.get("omission_reason") is None),
                )
                if not matches
            ]
            if content_mismatches:
                raise AssertionError(
                    f"{case_id}: canonical block/table content custody differs "
                    f"for {after_block.get('id')}: {content_mismatches}"
                )
            changed_block_ids.add(str(after_block.get("id") or ""))
            changed_primary_ids.add(primary_id)

        for view_name in ("full", "body", "header", "footer"):
            _assert_canonical_view_delta(
                before_page[view_name],
                after_page[view_name],
                changed_block_ids=changed_block_ids,
                case_id=case_id,
                view_path=f"pages/{before_page.get('page_index')}/{view_name}",
            )

    for view_name in ("full", "body", "header", "footer"):
        _assert_canonical_view_delta(
            predecessor[view_name],
            enabled[view_name],
            changed_block_ids=changed_block_ids,
            case_id=case_id,
            view_path=view_name,
        )
    if changed_primary_ids != set(changed_tables):
        raise AssertionError("canonical target-seeded content closure differs")
    return {"changed_canonical_block_ids": sorted(changed_block_ids)}


def _assert_canonical_source_custody_delta(
    case_id: str,
    predecessor_custody: Any,
    enabled_custody: Any,
    *,
    enabled: Mapping[str, Any],
    enabled_canonical: Mapping[str, Any],
    marked_table_bindings: Mapping[str, tuple[int, str, str, bool]],
) -> dict[str, Any]:
    """Admit only target-scoped, diagnostic P04 custody.

    The terminal producer selects the connected raw-group components that
    touch its marked table targets.  This gate independently checks the same
    public invariant.  It deliberately does not require every record to touch
    a table directly: a selected group can retain other members in the same
    component.  It also does not require every marked table to have a record,
    because a source can have no opaque group edge at all.
    """

    if predecessor_custody is not _ABSENT_CUSTODY:
        raise AssertionError(
            f"{case_id}: Phase03 predecessor carries canonical source custody"
        )
    if not marked_table_bindings:
        if enabled_custody is not _ABSENT_CUSTODY:
            raise AssertionError(
                f"{case_id}: custody appeared without a marked table target"
            )
        return {
            "canonical_source_custody_present": False,
            "canonical_source_custody_record_count": 0,
            "canonical_source_custody_records_sha256": None,
            "canonical_source_custody_bytes": 0,
            "table_marker_and_custody_bytes": 0,
            "custody_relationship_ids": [],
            "custody_component_target_table_ids": [],
        }
    if type(enabled_custody) is not dict:
        raise AssertionError(
            f"{case_id}: marked tables lack exact canonical source custody"
        )

    try:
        custody = CanonicalSourceCustody.model_validate(
            deepcopy(enabled_custody)
        )
    except (TypeError, ValueError) as exc:
        raise AssertionError(
            f"{case_id}: canonical source custody schema differs"
        ) from exc
    if custody.model_dump(mode="json", exclude_unset=True) != enabled_custody:
        raise AssertionError(
            f"{case_id}: canonical source custody API round-trip differs"
        )

    document = enabled.get("document")
    if type(document) is not dict or type(document.get("sha256")) is not str:
        raise AssertionError(f"{case_id}: document identity is unavailable")
    if (
        custody.policy_id != "p04-opaque-raw-group-custody-v1"
        or custody.schema_version != "1.0"
        or custody.authority != "diagnostic_only"
        or custody.source_sha256 != document["sha256"]
        or custody.canonical_presentation_sha256
        != _canonical_presentation_sha256(enabled_canonical)
    ):
        raise AssertionError(
            f"{case_id}: canonical source custody identity differs"
        )

    marked_primary_ids = set(marked_table_bindings)
    canonical_primary_ids: set[str] = set()
    canonical_primary_locations: dict[str, list[tuple[Any, Any]]] = {}
    canonical_authority_ids: set[str] = set()
    canonical_relationship_ids: set[str] = set()
    canonical_pages = enabled_canonical.get("pages")
    if type(canonical_pages) is not list:
        raise AssertionError(f"{case_id}: canonical custody pages are unavailable")
    for page in canonical_pages:
        if type(page) is not dict or type(page.get("blocks")) is not list:
            raise AssertionError(
                f"{case_id}: canonical custody block coverage differs"
            )
        page_id = page.get("page_id")
        if type(page_id) is str:
            canonical_authority_ids.add(page_id)
        for block in page["blocks"]:
            if type(block) is not dict:
                raise AssertionError(
                    f"{case_id}: canonical custody block shape differs"
                )
            block_id = block.get("id")
            if type(block_id) is str:
                canonical_authority_ids.add(block_id)
            primary_id = block.get("primary_element_id")
            if type(primary_id) is str:
                canonical_primary_ids.add(primary_id)
                canonical_authority_ids.add(primary_id)
                canonical_primary_locations.setdefault(primary_id, []).append(
                    (page.get("page_index"), block.get("primary_element_type"))
                )
            for element_id in block.get("contributing_element_ids", []):
                if type(element_id) is str:
                    canonical_authority_ids.add(element_id)
            suppressed_id = block.get("suppressed_by_element_id")
            if type(suppressed_id) is str:
                canonical_authority_ids.add(suppressed_id)
            for relationship_id in block.get("relationship_ids", []):
                if type(relationship_id) is str:
                    canonical_relationship_ids.add(relationship_id)
            for exclusion in block.get("excluded_contributions", []):
                if type(exclusion) is not dict:
                    continue
                excluded_id = exclusion.get("element_id")
                if type(excluded_id) is str:
                    canonical_authority_ids.add(excluded_id)
                for relationship_id in exclusion.get("relationship_ids", []):
                    if type(relationship_id) is str:
                        canonical_relationship_ids.add(relationship_id)
    if not marked_primary_ids <= canonical_primary_ids:
        raise AssertionError(
            f"{case_id}: marked table canonical target coverage differs"
        )
    for primary_id, binding in marked_table_bindings.items():
        if canonical_primary_locations.get(primary_id) != [(binding[0], "table")]:
            raise AssertionError(
                f"{case_id}: marked table canonical target binding differs"
            )

    custody_relationship_ids = {
        record.relationship_id for record in custody.records
    }
    if custody_relationship_ids & canonical_relationship_ids:
        raise AssertionError(
            f"{case_id}: diagnostic custody relationship reached canonical authority"
        )
    diagnostic_group_ids = {
        record.group_element_id for record in custody.records
    }
    if diagnostic_group_ids & canonical_authority_ids:
        raise AssertionError(
            f"{case_id}: diagnostic custody group reached canonical authority"
        )

    adjacency: dict[str, set[str]] = {}
    for record in custody.records:
        adjacency.setdefault(record.source_element_id, set()).add(
            record.target_element_id
        )
        adjacency.setdefault(record.target_element_id, set()).add(
            record.source_element_id
        )
    unseen = set(adjacency)
    component_targets: list[list[str]] = []
    while unseen:
        seed = min(unseen)
        component: set[str] = set()
        pending = [seed]
        while pending:
            element_id = pending.pop()
            if element_id in component:
                continue
            component.add(element_id)
            pending.extend(adjacency[element_id] - component)
        unseen -= component
        targets = component & marked_primary_ids
        if not targets:
            component_relationship_ids = sorted(
                record.relationship_id
                for record in custody.records
                if record.source_element_id in component
            )
            raise AssertionError(
                f"{case_id}: custody component is not target-scoped to a "
                f"marked table: {component_relationship_ids}"
            )
        component_targets.append(
            sorted(marked_table_bindings[target][1] for target in targets)
        )

    marker_bytes = sum(
        len(_canonical_bytes(item["table_evidence"]))
        for page in enabled.get("pages", [])
        if type(page) is dict
        for item in page.get("items", [])
        if type(item) is dict and type(item.get("table_evidence")) is dict
    )
    custody_bytes = len(_canonical_bytes(enabled_custody))
    aggregate_bytes = marker_bytes + custody_bytes
    if aggregate_bytes > _TABLE_MAX_DOCUMENT_SIDECAR_BYTES:
        raise AssertionError(
            f"{case_id}: table marker and custody resource envelope differs"
        )

    try:
        validated = ParseResult.model_validate(deepcopy(enabled))
    except (TypeError, ValueError) as exc:
        raise AssertionError(
            f"{case_id}: enabled table/custody API closure differs"
        ) from exc
    if validated.model_dump(mode="json", exclude_unset=True) != dict(enabled):
        raise AssertionError(
            f"{case_id}: enabled table/custody API round-trip differs"
        )

    return {
        "canonical_source_custody_present": True,
        "canonical_source_custody_record_count": custody.record_count,
        "canonical_source_custody_records_sha256": custody.records_sha256,
        "canonical_source_custody_bytes": custody_bytes,
        "table_marker_and_custody_bytes": aggregate_bytes,
        "custody_relationship_ids": sorted(custody_relationship_ids),
        "custody_component_target_table_ids": sorted(component_targets),
    }


def _assert_table_only_drift(
    case_id: str,
    predecessor: Mapping[str, Any],
    enabled: Mapping[str, Any],
) -> dict[str, Any]:
    before = _timing_normalized(predecessor)
    after = _timing_normalized(enabled)
    _assert_no_phase05_fields(after, case_id=case_id)

    before_without_pages = dict(before)
    after_without_pages = dict(after)
    before_pages = before_without_pages.pop("pages", None)
    after_pages = after_without_pages.pop("pages", None)
    before_canonical = before_without_pages.pop("canonical_presentation", None)
    after_canonical = after_without_pages.pop("canonical_presentation", None)
    before_custody = before_without_pages.pop(
        "canonical_source_custody",
        _ABSENT_CUSTODY,
    )
    after_custody = after_without_pages.pop(
        "canonical_source_custody",
        _ABSENT_CUSTODY,
    )
    if before_without_pages != after_without_pages:
        changed = sorted(
            key
            for key in set(before_without_pages) | set(after_without_pages)
            if before_without_pages.get(key) != after_without_pages.get(key)
        )
        raise AssertionError(
            f"{case_id}: non-page or processing metadata drifted: {changed}"
        )
    if type(before_pages) is not list or type(after_pages) is not list:
        raise AssertionError(f"{case_id}: page collections are unavailable")
    if len(before_pages) != len(after_pages):
        raise AssertionError(f"{case_id}: page membership drifted")

    marked: list[str] = []
    canonical_deltas: list[str] = []
    canonical_table_bindings: dict[
        str,
        tuple[int, Mapping[str, Any], Mapping[str, Any], ContentItem],
    ] = {}
    marked_table_bindings: dict[str, tuple[int, str, str, bool]] = {}
    exact_unmarked_fallbacks: list[str] = []
    statuses: dict[str, int] = {}
    for before_page, after_page in zip(before_pages, after_pages, strict=True):
        before_page_without_items = dict(before_page)
        after_page_without_items = dict(after_page)
        before_items = before_page_without_items.pop("items", None)
        after_items = after_page_without_items.pop("items", None)
        if before_page_without_items != after_page_without_items:
            changed = sorted(
                key
                for key in set(before_page_without_items)
                | set(after_page_without_items)
                if before_page_without_items.get(key)
                != after_page_without_items.get(key)
            )
            raise AssertionError(
                f"{case_id}: non-item page metadata drifted on page "
                f"{before_page.get('page_index')}: {changed}"
            )
        if type(before_items) is not list or type(after_items) is not list:
            raise AssertionError(f"{case_id}: item collections are unavailable")
        if len(before_items) != len(after_items):
            raise AssertionError(
                f"{case_id}: item membership drifted on page "
                f"{before_page.get('page_index')}"
            )
        page_index = int(before_page["page_index"])
        for item_offset, (before_item, after_item) in enumerate(
            zip(before_items, after_items, strict=True)
        ):
            identity = (
                before_item.get("id"),
                before_item.get("type"),
                before_item.get("reading_order"),
            )
            if identity != (
                after_item.get("id"),
                after_item.get("type"),
                after_item.get("reading_order"),
            ):
                raise AssertionError(
                    f"{case_id}: item identity/order/type drifted on page {page_index}"
                )
            if before_item.get("type") != "table":
                if before_item != after_item:
                    raise AssertionError(
                        f"{case_id}/{before_item.get('id')}: non-table item drifted"
                    )
                continue
            table_id = str(before_item.get("id") or "")
            if after_item.get("table_evidence") is None:
                if before_item != after_item:
                    raise AssertionError(
                        f"{case_id}/{table_id}: unmarked table drifted"
                    )
                exact_unmarked_fallbacks.append(table_id)
                continue
            status, projection_changed = _assert_marked_table(
                case_id,
                page_index,
                before_item,
                after_item,
            )
            marked.append(table_id)
            statuses[status] = statuses.get(status, 0) + 1
            document = after.get("document")
            if type(document) is not dict:
                raise AssertionError(f"{case_id}: document identity is unavailable")
            document_sha256 = document.get("sha256")
            if type(document_sha256) is not str:
                raise AssertionError(f"{case_id}: document identity is malformed")
            document_id = _canonical_ir_id("doc", document_sha256)
            validated_table = ContentItem.model_validate(after_item)
            primary_id = _canonical_item_primary_id(
                document_id,
                page_index,
                item_offset,
                validated_table,
            )
            if primary_id in marked_table_bindings:
                raise AssertionError(
                    f"{case_id}: marked table canonical primary repeats"
                )
            marked_table_bindings[primary_id] = (
                page_index,
                table_id,
                status,
                projection_changed,
            )
            if projection_changed:
                canonical_deltas.append(table_id)
                if primary_id in canonical_table_bindings:
                    raise AssertionError(
                        f"{case_id}: changed table canonical primary repeats"
                    )
                canonical_table_bindings[primary_id] = (
                    page_index,
                    before_item,
                    after_item,
                    validated_table,
                )

    required_positive = {
        "catastrophe-recap": "p1-i3",
        "postal-10k": "p1-i3",
    }.get(case_id)
    if required_positive is not None and required_positive not in marked:
        raise AssertionError(
            f"{case_id}/{required_positive}: reviewed positive table was not marked"
        )
    canonical_drift = _assert_correlated_canonical_delta(
        case_id,
        before_canonical,
        after_canonical,
        canonical_table_bindings,
    )
    custody_drift = _assert_canonical_source_custody_delta(
        case_id,
        before_custody,
        after_custody,
        enabled=enabled,
        enabled_canonical=after_canonical,
        marked_table_bindings=marked_table_bindings,
    )
    return {
        "marked_table_ids": marked,
        "table_status_counts": statuses,
        "canonical_delta_table_ids": canonical_deltas,
        "exact_unmarked_fallback_table_ids": exact_unmarked_fallbacks,
        "non_table_drift_count": 0,
        "later_phase04_fields_nonnull": 0,
        "phase05_fields_present": 0,
        **canonical_drift,
        **custody_drift,
    }


def _review_case(case_id: str) -> dict[str, Any]:
    predecessor = _frozen_predecessor(case_id)
    disabled, disabled_seconds = _parse_local(case_id, enabled=False)
    enabled, enabled_seconds = _parse_local(case_id, enabled=True)
    repeated, repeated_seconds = _parse_local(case_id, enabled=True)

    predecessor_stable = _timing_normalized(predecessor)
    disabled_stable = _timing_normalized(disabled)
    enabled_stable = _timing_normalized(enabled)
    repeated_stable = _timing_normalized(repeated)
    if disabled_stable != predecessor_stable:
        raise AssertionError(
            f"{case_id}: default-off output differs from the Phase03 predecessor"
        )
    if any(
        table.get("table_evidence") is not None for _page, table in _tables(disabled)
    ):
        raise AssertionError(f"{case_id}: default-off table marker leaked")
    drift = _assert_table_only_drift(case_id, predecessor, enabled)
    if enabled_stable != repeated_stable:
        raise AssertionError(f"{case_id}: enabled semantic output is unstable")

    return {
        "case_id": case_id,
        "source_identity": dict(SOURCE_IDENTITIES[case_id]),
        "phase03_predecessor_identity": dict(
            PREDECESSOR_OUTPUT_IDENTITIES[case_id]
        ),
        "p04_oracle_sha256": oracle_sha256(),
        "p04_content_bbox_oracle": source_content_bbox_oracle_metadata(),
        "p04_source_reviewed": case_id in P04_REVIEWED_CASE_IDS,
        "default_off_exact_phase03_predecessor": True,
        "enabled_semantically_stable": True,
        "timing_normalized_paths": [".".join(path) for path in DECLARED_TIMING_PATHS],
        "default_off_semantic_sha256": _sha256_bytes(
            _canonical_bytes(disabled_stable)
        ),
        "enabled_semantic_sha256": _sha256_bytes(_canonical_bytes(enabled_stable)),
        "enabled_repeat_semantic_sha256": _sha256_bytes(
            _canonical_bytes(repeated_stable)
        ),
        "wall_seconds": {
            "default_off": round(disabled_seconds, 6),
            "enabled": round(enabled_seconds, 6),
            "enabled_repeat": round(repeated_seconds, 6),
        },
        "settings": {
            "predecessor": dict(PREDECESSOR_CONFIGURATION),
            "only_changed_flag": "table_span_fidelity_enabled",
            "later_phase04_flags": {
                "table_evidence_reconciliation_enabled": False,
                "table_candidate_gate_enabled": False,
                "table_multi_page_merge_enabled": False,
            },
        },
        "offline_environment": dict(OFFLINE_ENVIRONMENT),
        "hosted_usage": dict(HOSTED_USAGE),
        **drift,
    }


def _render_canonical_view(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    included = [block for block in blocks if block.get("omission_reason") is None]

    def render(field: str) -> str:
        values = [
            str(block.get(field) or "").strip()
            for block in included
            if str(block.get(field) or "").strip()
        ]
        return "\n\n".join(values).rstrip() + "\n" if values else ""

    return {
        "block_ids": [block["id"] for block in included],
        "markdown": render("markdown"),
        "text": render("text"),
    }


def _rebuild_canonical_views(canonical: dict[str, Any]) -> None:
    all_blocks: list[dict[str, Any]] = []
    for page in canonical["pages"]:
        blocks = page["blocks"]
        all_blocks.extend(blocks)
        page["full"] = _render_canonical_view(blocks)
        for scope in ("body", "header", "footer"):
            page[scope] = _render_canonical_view(
                [block for block in blocks if block["scope"] == scope]
            )
    canonical["full"] = _render_canonical_view(all_blocks)
    for scope in ("body", "header", "footer"):
        canonical[scope] = _render_canonical_view(
            [block for block in all_blocks if block["scope"] == scope]
        )


def _synthetic_correlated_canonical_pair() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[
        str,
        tuple[int, Mapping[str, Any], Mapping[str, Any], ContentItem],
    ],
]:
    public = _frozen_predecessor("catastrophe-recap")
    before = deepcopy(public["canonical_presentation"])
    after = deepcopy(before)
    page = public["pages"][0]
    item_offset, raw_table = next(
        (offset, item)
        for offset, item in enumerate(page["items"])
        if item.get("type") == "table"
    )
    changed_table_payload = deepcopy(raw_table)
    changed_table_payload["rows"] = [["source-supported-change"]]
    changed_table_payload["value"] = [["source-supported-change"]]
    changed_table_payload["html"] = "<table><tr><td>source-supported-change</td></tr></table>"
    changed_table_payload["md"] = changed_table_payload["html"]
    changed_table = ContentItem.model_validate(changed_table_payload)
    document_id = _canonical_ir_id("doc", public["document"]["sha256"])
    primary_id = _canonical_item_primary_id(
        document_id,
        page["page_index"],
        item_offset,
        changed_table,
    )
    block = next(
        block
        for block in after["pages"][0]["blocks"]
        if block["primary_element_id"] == primary_id
    )
    before_output = _canonical_table_owned_output(raw_table)
    after_output = _canonical_table_owned_output(changed_table)
    block["markdown"] = _target_seeded_scalar_with_preserved_overlay(
        block["markdown"],
        before_output[0],
        after_output[0],
    )
    block["text"] = _target_seeded_scalar_with_preserved_overlay(
        block["text"],
        before_output[1],
        after_output[1],
    )
    _rebuild_canonical_views(after)
    return before, after, {
        primary_id: (1, raw_table, changed_table_payload, changed_table)
    }


def test_correlated_canonical_allowance_is_exact_and_graph_validated() -> None:
    before, after, changed_tables = _synthetic_correlated_canonical_pair()

    assert _assert_correlated_canonical_delta(
        "synthetic-canonical",
        before,
        after,
        changed_tables,
    )["changed_canonical_block_ids"]

    unrelated = deepcopy(after)
    unrelated_block = next(
        block
        for block in unrelated["pages"][0]["blocks"]
        if block["primary_element_id"] not in changed_tables
        and block.get("omission_reason") is None
    )
    unrelated_block["markdown"] += " unrelated"
    unrelated_block["text"] += " unrelated"
    _rebuild_canonical_views(unrelated)
    with pytest.raises(AssertionError, match="does not map"):
        _assert_correlated_canonical_delta(
            "synthetic-canonical",
            before,
            unrelated,
            changed_tables,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        None,
        "overlay_drop",
        "overlay_mutation",
        "predecessor_table_reuse",
        "candidate_suffix_injection",
    ),
)
def test_correlated_canonical_target_seeded_content_closure_is_exact(
    mutation: str | None,
) -> None:
    before, after, changed_tables = _synthetic_correlated_canonical_pair()
    primary_id, binding = next(iter(changed_tables.items()))
    _page_index, before_table, _after_table, changed_table = binding
    block = next(
        value
        for page in after["pages"]
        for value in page["blocks"]
        if value["primary_element_id"] == primary_id
    )
    if mutation == "overlay_drop":
        block["markdown"], block["text"] = _canonical_table_owned_output(
            changed_table
        )
    elif mutation == "overlay_mutation":
        block["markdown"] = f"forged {block['markdown']}"
        block["text"] = f"forged {block['text']}"
    elif mutation == "predecessor_table_reuse":
        before_block = next(
            value
            for page in before["pages"]
            for value in page["blocks"]
            if value["primary_element_id"] == primary_id
        )
        block["markdown"] = before_block["markdown"]
        block["text"] = before_block["text"]
    elif mutation == "candidate_suffix_injection":
        block["markdown"] += "\n\nforged"
        block["text"] += "\n\nforged"
    elif mutation is not None:  # pragma: no cover - parameter list is closed.
        raise AssertionError(mutation)
    _rebuild_canonical_views(after)

    if mutation is None:
        assert _assert_correlated_canonical_delta(
            "synthetic-target-seeded-content",
            before,
            after,
            changed_tables,
        )["changed_canonical_block_ids"]
    else:
        with pytest.raises(AssertionError, match="target-seeded content closure"):
            _assert_correlated_canonical_delta(
                "synthetic-target-seeded-content",
                before,
                after,
                changed_tables,
            )


def _synthetic_target_seeded_cell_graph_pair() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[
        str,
        tuple[int, Mapping[str, Any], Mapping[str, Any], ContentItem],
    ],
]:
    before, after, changed_tables = _synthetic_correlated_canonical_pair()
    primary_id, binding = next(iter(changed_tables.items()))
    page_index, before_table, after_table, _table = binding
    changed_table_payload = deepcopy(dict(after_table))
    cells = changed_table_payload.get("cells")
    assert type(cells) is list and cells and type(cells[0]) is dict
    first_cell = dict(cells[0])
    first_cell["column_header"] = not bool(first_cell.get("column_header"))
    cells[0] = first_cell
    changed_table = ContentItem.model_validate(changed_table_payload)

    block = next(
        value
        for page in after["pages"]
        for value in page["blocks"]
        if value["primary_element_id"] == primary_id
    )
    before_cell_ids, before_relationship_ids = _canonical_table_cell_closure(
        primary_id,
        before_table,
    )
    after_cell_ids, after_relationship_ids = _canonical_table_cell_closure(
        primary_id,
        changed_table_payload,
    )
    assert block["contributing_element_ids"][-len(before_cell_ids) :] == (
        before_cell_ids
    )
    block["contributing_element_ids"] = [
        *block["contributing_element_ids"][: -len(before_cell_ids)],
        *after_cell_ids,
    ]
    noncell_relationships = set(block["relationship_ids"]) - set(
        before_relationship_ids
    )
    block["relationship_ids"] = sorted(
        noncell_relationships | set(after_relationship_ids)
    )
    changed_tables[primary_id] = (
        page_index,
        before_table,
        changed_table_payload,
        changed_table,
    )
    return before, after, changed_tables


@pytest.mark.parametrize(
    "mutation",
    (
        None,
        "forged_contributor",
        "predecessor_cell_reuse",
        "forged_relationship",
        "overlay_relationship_injection",
        "overlay_contributor_injection",
    ),
)
def test_correlated_canonical_target_seeded_cell_closure_is_exact(
    mutation: str | None,
) -> None:
    before, after, changed_tables = _synthetic_target_seeded_cell_graph_pair()
    primary_id, binding = next(iter(changed_tables.items()))
    _page_index, before_table, after_table, _table = binding
    block = next(
        value
        for page in after["pages"]
        for value in page["blocks"]
        if value["primary_element_id"] == primary_id
    )
    before_cell_ids, _before_relationship_ids = _canonical_table_cell_closure(
        primary_id,
        before_table,
    )
    after_cell_ids, after_relationship_ids = _canonical_table_cell_closure(
        primary_id,
        after_table,
    )
    changed_cell_index = next(
        index
        for index, (before_id, after_id) in enumerate(
            zip(before_cell_ids, after_cell_ids, strict=True)
        )
        if before_id != after_id
    )
    if mutation == "forged_contributor":
        contributor_index = block["contributing_element_ids"].index(
            after_cell_ids[changed_cell_index]
        )
        block["contributing_element_ids"][contributor_index] = (
            "el-ffffffffffffffffffff"
        )
    elif mutation == "predecessor_cell_reuse":
        contributor_index = block["contributing_element_ids"].index(
            after_cell_ids[changed_cell_index]
        )
        block["contributing_element_ids"][contributor_index] = (
            before_cell_ids[changed_cell_index]
        )
    elif mutation == "forged_relationship":
        relationship_id = after_relationship_ids[changed_cell_index]
        block["relationship_ids"].remove(relationship_id)
        block["relationship_ids"].append("rel-ffffffffffffffffffff")
        block["relationship_ids"].sort()
    elif mutation == "overlay_relationship_injection":
        block["relationship_ids"].append("rel-eeeeeeeeeeeeeeeeeeee")
        block["relationship_ids"].sort()
    elif mutation == "overlay_contributor_injection":
        block["contributing_element_ids"].insert(
            1,
            "el-eeeeeeeeeeeeeeeeeeee",
        )
    elif mutation is not None:  # pragma: no cover - parameter list is closed.
        raise AssertionError(mutation)

    if mutation is None:
        assert _assert_correlated_canonical_delta(
            "synthetic-target-seeded",
            before,
            after,
            changed_tables,
        )["changed_canonical_block_ids"]
    else:
        with pytest.raises(AssertionError, match="target-seeded cell closure"):
            _assert_correlated_canonical_delta(
                "synthetic-target-seeded",
                before,
                after,
                changed_tables,
            )


def test_sidecar_only_table_requires_exact_canonical_bytes() -> None:
    before, after, _changed_tables = _synthetic_correlated_canonical_pair()
    with pytest.raises(AssertionError, match="sidecar-only"):
        _assert_correlated_canonical_delta(
            "synthetic-canonical",
            before,
            after,
            {},
        )


@pytest.fixture(scope="module")
def synthetic_target_scoped_custody() -> tuple[
    dict[str, Any],
    dict[str, tuple[int, str, str, bool]],
]:
    from tests.contract.test_p04_us01_p03_boundary import (
        _trusted_terminal_candidate,
    )

    _baseline, raw_candidate = _trusted_terminal_candidate()
    candidate = deepcopy(raw_candidate)
    assert ParseResult.model_validate(candidate).model_dump(
        mode="json",
        exclude_unset=True,
    ) == candidate
    document_id = _canonical_ir_id("doc", candidate["document"]["sha256"])
    bindings: dict[str, tuple[int, str, str, bool]] = {}
    for page in candidate["pages"]:
        for item_offset, item in enumerate(page["items"]):
            sidecar = item.get("table_evidence")
            if type(sidecar) is not dict:
                continue
            validated_item = ContentItem.model_validate(item)
            primary_id = _canonical_item_primary_id(
                document_id,
                page["page_index"],
                item_offset,
                validated_item,
            )
            bindings[primary_id] = (
                page["page_index"],
                item["id"],
                sidecar["status"],
                True,
            )
    assert bindings
    return candidate, bindings


def test_target_scoped_custody_allowance_is_closed_and_exact(
    synthetic_target_scoped_custody: tuple[
        dict[str, Any],
        dict[str, tuple[int, str, str, bool]],
    ],
) -> None:
    candidate, bindings = synthetic_target_scoped_custody
    report = _assert_canonical_source_custody_delta(
        "synthetic-targeted-custody",
        _ABSENT_CUSTODY,
        candidate["canonical_source_custody"],
        enabled=candidate,
        enabled_canonical=candidate["canonical_presentation"],
        marked_table_bindings=bindings,
    )

    assert report["canonical_source_custody_present"] is True
    assert report["canonical_source_custody_record_count"] == 2
    assert report["custody_component_target_table_ids"] == [
        sorted(binding[1] for binding in bindings.values())
    ]
    # Reciprocal/duplicate raw assertions may normalize to one relationship;
    # their complete assertion multiplicity remains in the sealed records.
    assert len(report["custody_relationship_ids"]) == 1


def test_disconnected_but_resealed_custody_cannot_use_table_allowance(
    synthetic_target_scoped_custody: tuple[
        dict[str, Any],
        dict[str, tuple[int, str, str, bool]],
    ],
) -> None:
    from app.services.opaque_group_custody import record_id, records_sha256
    from tests.contract.test_p04_us01_opaque_group_custody import (
        _production_payload_with_custody,
    )

    source, bindings = synthetic_target_scoped_custody
    candidate = deepcopy(source)
    unrelated = deepcopy(
        _production_payload_with_custody()["canonical_source_custody"]
    )
    unrelated["source_sha256"] = candidate["document"]["sha256"]
    unrelated["canonical_presentation_sha256"] = (
        _canonical_presentation_sha256(candidate["canonical_presentation"])
    )
    for record in unrelated["records"]:
        record.pop("record_id", None)
        record["record_id"] = record_id(
            record,
            unrelated["source_sha256"],
        )
    unrelated["records_sha256"] = records_sha256(unrelated["records"])
    unrelated = CanonicalSourceCustody.model_validate(unrelated).model_dump(
        mode="json",
        exclude_unset=True,
    )
    candidate["canonical_source_custody"] = unrelated

    with pytest.raises(AssertionError, match="not target-scoped"):
        _assert_canonical_source_custody_delta(
            "synthetic-disconnected-custody",
            _ABSENT_CUSTODY,
            unrelated,
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings=bindings,
        )


def test_custody_relationship_cannot_reenter_canonical_authority(
    synthetic_target_scoped_custody: tuple[
        dict[str, Any],
        dict[str, tuple[int, str, str, bool]],
    ],
) -> None:
    source, bindings = synthetic_target_scoped_custody
    candidate = deepcopy(source)
    relationship_id = candidate["canonical_source_custody"]["records"][0][
        "relationship_id"
    ]
    block = candidate["canonical_presentation"]["pages"][0]["blocks"][0]
    block["relationship_ids"] = sorted(
        {*block["relationship_ids"], relationship_id}
    )
    candidate["canonical_source_custody"][
        "canonical_presentation_sha256"
    ] = _canonical_presentation_sha256(candidate["canonical_presentation"])

    with pytest.raises(AssertionError, match="reached canonical authority"):
        _assert_canonical_source_custody_delta(
            "synthetic-canonical-custody-leak",
            _ABSENT_CUSTODY,
            candidate["canonical_source_custody"],
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings=bindings,
        )


def test_custody_group_cannot_collide_with_a_canonical_block_identity(
    synthetic_target_scoped_custody: tuple[
        dict[str, Any],
        dict[str, tuple[int, str, str, bool]],
    ],
) -> None:
    source, bindings = synthetic_target_scoped_custody
    candidate = deepcopy(source)
    group_id = candidate["canonical_source_custody"]["records"][0][
        "group_element_id"
    ]
    candidate["canonical_presentation"]["pages"][0]["blocks"][0][
        "id"
    ] = group_id
    candidate["canonical_source_custody"][
        "canonical_presentation_sha256"
    ] = _canonical_presentation_sha256(candidate["canonical_presentation"])

    with pytest.raises(AssertionError, match="group reached canonical authority"):
        _assert_canonical_source_custody_delta(
            "synthetic-canonical-group-leak",
            _ABSENT_CUSTODY,
            candidate["canonical_source_custody"],
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings=bindings,
        )


def test_marked_primary_requires_one_table_block_on_its_recorded_page(
    synthetic_target_scoped_custody: tuple[
        dict[str, Any],
        dict[str, tuple[int, str, str, bool]],
    ],
) -> None:
    source, bindings = synthetic_target_scoped_custody
    candidate = deepcopy(source)
    primary_id = next(iter(bindings))
    target_block = next(
        block
        for page in candidate["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block["primary_element_id"] == primary_id
    )
    target_block["primary_element_type"] = "text"
    candidate["canonical_source_custody"][
        "canonical_presentation_sha256"
    ] = _canonical_presentation_sha256(candidate["canonical_presentation"])

    with pytest.raises(AssertionError, match="target binding differs"):
        _assert_canonical_source_custody_delta(
            "synthetic-canonical-target-type",
            _ABSENT_CUSTODY,
            candidate["canonical_source_custody"],
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings=bindings,
        )


def test_zero_record_custody_is_valid_only_with_marked_targets(
    synthetic_target_scoped_custody: tuple[
        dict[str, Any],
        dict[str, tuple[int, str, str, bool]],
    ],
) -> None:
    from app.services.opaque_group_custody import records_sha256

    source, bindings = synthetic_target_scoped_custody
    candidate = deepcopy(source)
    sidecar = candidate["canonical_source_custody"]
    sidecar["record_count"] = 0
    sidecar["records"] = []
    sidecar["records_sha256"] = records_sha256([])

    report = _assert_canonical_source_custody_delta(
        "synthetic-empty-custody",
        _ABSENT_CUSTODY,
        sidecar,
        enabled=candidate,
        enabled_canonical=candidate["canonical_presentation"],
        marked_table_bindings=bindings,
    )
    assert report["canonical_source_custody_record_count"] == 0
    assert report["custody_component_target_table_ids"] == []

    with pytest.raises(AssertionError, match="without a marked table"):
        _assert_canonical_source_custody_delta(
            "synthetic-orphan-empty-custody",
            _ABSENT_CUSTODY,
            sidecar,
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings={},
        )


def test_table_marker_and_custody_aggregate_cap_is_explicit(
    synthetic_target_scoped_custody: tuple[
        dict[str, Any],
        dict[str, tuple[int, str, str, bool]],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, bindings = synthetic_target_scoped_custody
    monkeypatch.setattr(
        f"{__name__}._TABLE_MAX_DOCUMENT_SIDECAR_BYTES",
        0,
    )

    with pytest.raises(AssertionError, match="resource envelope differs"):
        _assert_canonical_source_custody_delta(
            "synthetic-custody-resource-cap",
            _ABSENT_CUSTODY,
            candidate["canonical_source_custody"],
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings=bindings,
        )


def test_custody_presence_and_seals_are_not_broadly_ignored(
    synthetic_target_scoped_custody: tuple[
        dict[str, Any],
        dict[str, tuple[int, str, str, bool]],
    ],
) -> None:
    source, bindings = synthetic_target_scoped_custody
    candidate = deepcopy(source)

    with pytest.raises(AssertionError, match="predecessor carries"):
        _assert_canonical_source_custody_delta(
            "synthetic-predecessor-custody",
            candidate["canonical_source_custody"],
            candidate["canonical_source_custody"],
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings=bindings,
        )

    with pytest.raises(AssertionError, match="lack exact"):
        _assert_canonical_source_custody_delta(
            "synthetic-missing-custody",
            _ABSENT_CUSTODY,
            _ABSENT_CUSTODY,
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings=bindings,
        )

    forged = deepcopy(candidate["canonical_source_custody"])
    forged["records_sha256"] = "0" * 64
    candidate["canonical_source_custody"] = forged
    with pytest.raises(AssertionError, match="schema differs"):
        _assert_canonical_source_custody_delta(
            "synthetic-forged-custody",
            _ABSENT_CUSTODY,
            forged,
            enabled=candidate,
            enabled_canonical=candidate["canonical_presentation"],
            marked_table_bindings=bindings,
        )


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv(RUN_ALL_CORPUS_ENVIRONMENT) != "1",
    reason=(
        "expensive all-15 local corpus gate; set "
        "P04_US01_RUN_ALL_CORPUS_DRIFT=1"
    ),
)
@pytest.mark.parametrize("case_id", CASE_IDS)
def test_enabled_tables_are_the_only_all_corpus_drift(
    case_id: str,
    record_property: Any,
) -> None:
    assert len(CASE_IDS) == 15
    assert set(CASE_IDS) == set(PREDECESSOR_OUTPUT_IDENTITIES)
    try:
        report = _review_case(case_id)
    except Exception as error:
        record_property(
            "p04_us01_all_corpus_drift",
            _canonical_bytes(
                {
                    "case_id": case_id,
                    "passed": False,
                    "error_class": type(error).__name__,
                    "error": str(error),
                    "source_identity": dict(SOURCE_IDENTITIES[case_id]),
                    "phase03_predecessor_identity": dict(
                        PREDECESSOR_OUTPUT_IDENTITIES[case_id]
                    ),
                    "p04_content_bbox_oracle": (
                        source_content_bbox_oracle_metadata()
                    ),
                    "offline_environment": dict(OFFLINE_ENVIRONMENT),
                    "hosted_usage": dict(HOSTED_USAGE),
                }
            ).decode("utf-8"),
        )
        raise
    record_property(
        "p04_us01_all_corpus_drift",
        _canonical_bytes(report).decode("utf-8"),
    )
    assert report["default_off_exact_phase03_predecessor"] is True
    assert report["enabled_semantically_stable"] is True
    assert report["hosted_usage"] == {
        "hosted_requests": 0,
        "hosted_tokens": 0,
        "hosted_cost_usd": 0,
    }
