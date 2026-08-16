"""Hash-bound source-content bbox oracle for P04-US01 Exhibit 7.

The Phase-00 Exhibit 7 oracle intentionally records structural grid-slot
rectangles.  P04-US01 publishes the source-supported Docling cell-content
rectangle instead.  This fixture keeps those two roles distinct: it derives
the public five-key bboxes only from the sealed Phase-03 predecessor after
verifying the predecessor and source-PDF identities, then requires every
content rectangle to remain inside its immutable Phase-00 grid slot.

Production code must not import this test-only module.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tests.fixtures.phase_03.running_regions.oracle import (
    PREDECESSOR_OUTPUT_IDENTITIES,
    PREDECESSOR_OUTPUT_ROOT,
    SOURCE_IDENTITIES,
)
from tests.fixtures.phase_04.tables.contract import validate_portable_workspace_path
from tests.fixtures.phase_04.tables.oracle import (
    EXHIBIT7_EXACT,
    EXHIBIT7_TRUTH_IDENTITY,
)


WORKSPACE = Path(__file__).resolve().parents[4]
SCHEMA_ID = "p04-us01-source-content-bbox-oracle-v1"
POLICY_ID = "p04-us01-dual-bbox-role-v1"
SEMANTIC_IDENTITY_SCHEMA_ID = (
    "p04-us01-source-content-bbox-oracle-semantic-identity-v1"
)
EXPECTED_SEMANTIC_SHA256 = (
    "f730746f00e15e5aeeed5fdaf277c957098714242e723a52c63f4ee5c5e4d4ff"
)
CONTENT_BBOX_ROLE = "source_content_bbox"
STRUCTURAL_BBOX_ROLE = "grid_slot_bbox"
DERIVATION_METHOD = "sealed_p03_predecessor_public_table_cells"
PUBLIC_TABLE_ID = "p1-i3"
NUMERIC_COMPARISON_SLACK_PT = 0.011
NORMALIZED_BBOX_KEYS = ("x", "y", "width", "height", "unit")
_PREDECESSOR_BBOX_KEYS = frozenset(
    {"x", "y", "w", "width", "h", "height", "unit"}
)

_EXPECTED_SOURCE_IDENTITY = {
    "path": "benchmark-expertmodeldata/catastrophe-recap.pdf",
    "size_bytes": 58_779,
    "sha256": "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e",
}
_EXPECTED_PREDECESSOR_IDENTITY = {
    "path": (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-post-US07-predecessor-20260801/"
        "catastrophe-recap/our-output.json"
    ),
    "size_bytes": 69_758,
    "sha256": "f9db554d1975d498a6f9e3d53c0058716847335ee661c3fb3cd6c0c0acc8a4a3",
}
_EXPECTED_STRUCTURAL_TRUTH_IDENTITY = {
    "path": "tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json",
    "size_bytes": 144_444,
    "sha256": "d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac",
}


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BoundFileIdentity(_ClosedModel):
    path: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def portable_path(cls, value: str) -> str:
        return validate_portable_workspace_path(value)


class ExactPtBBox(_ClosedModel):
    """The exact five-key public P04 bbox shape."""

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"]

    @field_validator("x", "y", "width", "height", mode="before")
    @classmethod
    def finite_real(cls, value: Any) -> Any:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("content bbox values must be finite real numbers")
        return float(value)


class SourceContentBBoxCell(_ClosedModel):
    cell_id: str
    row: int = Field(ge=0, lt=6)
    column: int = Field(ge=0, lt=5)
    text: str
    bbox: ExactPtBBox
    source_ref: str

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected_id = f"exhibit-7-r{self.row}-c{self.column}"
        expected_ref = (
            f"{_EXPECTED_PREDECESSOR_IDENTITY['path']}"
            f"#page=1&table={PUBLIC_TABLE_ID}&cell=r{self.row}c{self.column}"
        )
        if self.cell_id != expected_id or self.source_ref != expected_ref:
            raise ValueError("content bbox cell identity differs")
        return self


class SourceContentBBoxOracle(_ClosedModel):
    schema_id: Literal["p04-us01-source-content-bbox-oracle-v1"]
    policy_id: Literal["p04-us01-dual-bbox-role-v1"]
    story_id: Literal["P04-US01"]
    case_id: Literal["catastrophe-recap"]
    physical_page: Literal[1]
    public_table_id: Literal["p1-i3"]
    bbox_role: Literal["source_content_bbox"]
    structural_bbox_role: Literal["grid_slot_bbox"]
    derivation_method: Literal["sealed_p03_predecessor_public_table_cells"]
    coordinate_origin: Literal["top_left"]
    coordinate_space: Literal["displayed_pdf_page"]
    bbox_keys: tuple[
        Literal["x"],
        Literal["y"],
        Literal["width"],
        Literal["height"],
        Literal["unit"],
    ]
    row_count: Literal[6]
    column_count: Literal[5]
    cell_count: Literal[30]
    source_pdf_identity: BoundFileIdentity
    predecessor_identity: BoundFileIdentity
    structural_truth_identity: BoundFileIdentity
    cells: tuple[SourceContentBBoxCell, ...] = Field(min_length=30, max_length=30)

    @model_validator(mode="after")
    def validate_closed_oracle(self) -> Self:
        if self.bbox_keys != NORMALIZED_BBOX_KEYS:
            raise ValueError("content bbox key order differs")
        if self.source_pdf_identity.model_dump() != _EXPECTED_SOURCE_IDENTITY:
            raise ValueError("content bbox source-PDF identity differs")
        if self.predecessor_identity.model_dump() != _EXPECTED_PREDECESSOR_IDENTITY:
            raise ValueError("content bbox predecessor identity differs")
        if (
            self.structural_truth_identity.model_dump()
            != _EXPECTED_STRUCTURAL_TRUTH_IDENTITY
        ):
            raise ValueError("content bbox structural-truth identity differs")

        structural_by_position = {
            (cell.row, cell.column): cell for cell in EXHIBIT7_EXACT.cells
        }
        positions = [(cell.row, cell.column) for cell in self.cells]
        expected_positions = [
            (row, column)
            for row in range(self.row_count)
            for column in range(self.column_count)
        ]
        if positions != expected_positions:
            raise ValueError("content bbox cells must be complete row-major truth")
        for cell in self.cells:
            structural = structural_by_position[(cell.row, cell.column)]
            if cell.text != structural.text:
                raise ValueError("content bbox cell text differs from structural truth")
            if set(cell.bbox.model_dump()) != set(NORMALIZED_BBOX_KEYS):
                raise ValueError("content bbox must have exactly five public keys")
            if not _bbox_contained(cell.bbox, structural.bbox):
                raise ValueError("source-content bbox exceeds its structural grid slot")
        return self


def _bbox_contained(content: ExactPtBBox, structural: Any) -> bool:
    slack = NUMERIC_COMPARISON_SLACK_PT
    return (
        content.x >= float(structural.x) - slack
        and content.y >= float(structural.y) - slack
        and content.x + content.width
        <= float(structural.x) + float(structural.width) + slack
        and content.y + content.height
        <= float(structural.y) + float(structural.height) + slack
    )


def _stat_binding(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_bound_file(workspace: Path, identity: dict[str, Any], label: str) -> bytes:
    relative = validate_portable_workspace_path(identity["path"])
    try:
        root_initial = workspace.lstat()
    except OSError as error:
        raise ValueError(f"{label} workspace root differs") from error
    if stat.S_ISLNK(root_initial.st_mode) or not stat.S_ISDIR(root_initial.st_mode):
        raise ValueError(f"{label} workspace root differs")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    leaf_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptors: list[int] = []
    try:
        root_descriptor = os.open(workspace, directory_flags)
    except OSError as error:
        raise ValueError(f"{label} workspace root differs") from error
    descriptors.append(root_descriptor)
    root_binding = _stat_binding(os.fstat(root_descriptor))
    if root_binding != _stat_binding(root_initial):
        os.close(root_descriptor)
        descriptors.clear()
        raise ValueError(f"{label} workspace root changed before reading")

    current_descriptor = root_descriptor
    parent_bindings: list[tuple[int, str, tuple[int, ...]]] = []
    parts = Path(relative).parts
    try:
        for part in parts[:-1]:
            try:
                before = _stat_binding(
                    os.stat(part, dir_fd=current_descriptor, follow_symlinks=False)
                )
                next_descriptor = os.open(
                    part,
                    directory_flags,
                    dir_fd=current_descriptor,
                )
            except OSError as error:
                raise ValueError(
                    f"{label} cannot traverse a non-directory or symlink component"
                ) from error
            opened_directory = _stat_binding(os.fstat(next_descriptor))
            if (
                before != opened_directory
                or stat.S_ISLNK(before[2])
                or not stat.S_ISDIR(before[2])
            ):
                os.close(next_descriptor)
                raise ValueError(f"{label} directory component differs")
            parent_bindings.append((current_descriptor, part, before))
            descriptors.append(next_descriptor)
            current_descriptor = next_descriptor

        leaf = parts[-1]
        try:
            initial = _stat_binding(
                os.stat(leaf, dir_fd=current_descriptor, follow_symlinks=False)
            )
            descriptor = os.open(leaf, leaf_flags, dir_fd=current_descriptor)
        except OSError as error:
            raise ValueError(
                f"{label} must be a regular non-symlink file"
            ) from error
        descriptors.append(descriptor)
        opened = _stat_binding(os.fstat(descriptor))
        if (
            opened != initial
            or stat.S_ISLNK(initial[2])
            or not stat.S_ISREG(initial[2])
        ):
            raise ValueError(f"{label} must be a stable regular file")
        if opened[4] != identity["size_bytes"]:
            raise ValueError(f"{label} size differs")

        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, identity["size_bytes"] + 1))
            if not chunk:
                break
            observed += len(chunk)
            if observed > identity["size_bytes"]:
                raise ValueError(f"{label} byte count differs")
            chunks.append(chunk)
        raw = b"".join(chunks)
        if observed != identity["size_bytes"]:
            raise ValueError(f"{label} byte count differs")
        if _stat_binding(os.fstat(descriptor)) != opened:
            raise ValueError(f"{label} changed while reading")
        if (
            _stat_binding(
                os.stat(leaf, dir_fd=current_descriptor, follow_symlinks=False)
            )
            != initial
        ):
            raise ValueError(f"{label} changed after reading")
        for parent_descriptor, part, before in parent_bindings:
            if (
                _stat_binding(
                    os.stat(part, dir_fd=parent_descriptor, follow_symlinks=False)
                )
                != before
            ):
                raise ValueError(f"{label} directory changed after reading")
        if _stat_binding(os.fstat(root_descriptor)) != root_binding:
            raise ValueError(f"{label} workspace root changed while reading")
        if _stat_binding(workspace.lstat()) != _stat_binding(root_initial):
            raise ValueError(f"{label} workspace root changed after reading")
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
    if hashlib.sha256(raw).hexdigest() != identity["sha256"]:
        raise ValueError(f"{label} SHA-256 differs")
    return raw


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"predecessor JSON contains non-finite constant {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("predecessor JSON contains duplicate object keys")
        value[key] = item
    return value


def _derive_cells(predecessor_raw: bytes) -> tuple[SourceContentBBoxCell, ...]:
    try:
        predecessor = json.loads(
            predecessor_raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("predecessor is not strict UTF-8 JSON") from error
    if type(predecessor) is not dict or type(predecessor.get("pages")) is not list:
        raise ValueError("predecessor document shape differs")
    matches = [
        item
        for page in predecessor["pages"]
        if type(page) is dict and page.get("page_index") == 1
        for item in page.get("items", [])
        if type(item) is dict
        and item.get("type") == "table"
        and item.get("id") == PUBLIC_TABLE_ID
    ]
    if len(matches) != 1:
        raise ValueError("predecessor Exhibit 7 table selection differs")
    table = matches[0]
    if (table.get("row_count"), table.get("column_count")) != (6, 5):
        raise ValueError("predecessor Exhibit 7 shape differs")
    raw_cells = table.get("cells")
    if type(raw_cells) is not list or len(raw_cells) != 30:
        raise ValueError("predecessor Exhibit 7 cell denominator differs")

    structural_cells = list(EXHIBIT7_EXACT.cells)
    derived: list[SourceContentBBoxCell] = []
    for raw_cell, structural in zip(raw_cells, structural_cells, strict=True):
        if type(raw_cell) is not dict:
            raise ValueError("predecessor Exhibit 7 cell shape differs")
        expected_facts = {
            "row": structural.row,
            "column": structural.column,
            "row_span": structural.row_span,
            "col_span": structural.col_span,
            "text": structural.text,
            "column_header": structural.column_header,
            "row_header": structural.row_header,
        }
        if any(raw_cell.get(key) != value for key, value in expected_facts.items()):
            raise ValueError("predecessor Exhibit 7 cell facts differ")
        if raw_cell.get("source") != "native":
            raise ValueError("predecessor Exhibit 7 cell source differs")
        raw_bbox = raw_cell.get("bbox")
        if type(raw_bbox) is not dict or set(raw_bbox) != _PREDECESSOR_BBOX_KEYS:
            raise ValueError("predecessor Exhibit 7 bbox shape differs")
        if (
            raw_bbox.get("unit") != "pt"
            or raw_bbox.get("w") != raw_bbox.get("width")
            or raw_bbox.get("h") != raw_bbox.get("height")
        ):
            raise ValueError("predecessor Exhibit 7 bbox aliases differ")
        normalized = {
            key: raw_bbox[key]
            for key in NORMALIZED_BBOX_KEYS
        }
        bbox = ExactPtBBox.model_validate(normalized, strict=True)
        derived.append(
            SourceContentBBoxCell(
                cell_id=structural.cell_id,
                row=structural.row,
                column=structural.column,
                text=structural.text,
                bbox=bbox,
                source_ref=(
                    f"{_EXPECTED_PREDECESSOR_IDENTITY['path']}"
                    f"#page=1&table={PUBLIC_TABLE_ID}"
                    f"&cell=r{structural.row}c{structural.column}"
                ),
            )
        )
    return tuple(derived)


def derive_source_content_bbox_oracle(
    workspace: Path = WORKSPACE,
) -> SourceContentBBoxOracle:
    """Rebuild the oracle from the exact sealed inputs and validate both roles."""

    p03_source = SOURCE_IDENTITIES.get("catastrophe-recap")
    p03_predecessor = PREDECESSOR_OUTPUT_IDENTITIES.get("catastrophe-recap")
    if p03_source is None or {
        key: p03_source.get(key) for key in _EXPECTED_SOURCE_IDENTITY
    } != _EXPECTED_SOURCE_IDENTITY:
        raise ValueError("P03 source identity binding differs")
    expected_predecessor_from_p03 = {
        "path": f"{PREDECESSOR_OUTPUT_ROOT}/catastrophe-recap/our-output.json",
        **(p03_predecessor or {}),
    }
    if expected_predecessor_from_p03 != _EXPECTED_PREDECESSOR_IDENTITY:
        raise ValueError("P03 predecessor identity binding differs")
    if EXHIBIT7_TRUTH_IDENTITY != {
        "path": _EXPECTED_STRUCTURAL_TRUTH_IDENTITY["path"],
        "sha256": _EXPECTED_STRUCTURAL_TRUTH_IDENTITY["sha256"],
    }:
        raise ValueError("P00 structural-truth binding differs")

    _read_bound_file(workspace, _EXPECTED_SOURCE_IDENTITY, "catastrophe source PDF")
    _read_bound_file(
        workspace,
        _EXPECTED_STRUCTURAL_TRUTH_IDENTITY,
        "P00 Exhibit 7 structural truth",
    )
    predecessor_raw = _read_bound_file(
        workspace,
        _EXPECTED_PREDECESSOR_IDENTITY,
        "P03 catastrophe predecessor",
    )
    return SourceContentBBoxOracle(
        schema_id=SCHEMA_ID,
        policy_id=POLICY_ID,
        story_id="P04-US01",
        case_id="catastrophe-recap",
        physical_page=1,
        public_table_id=PUBLIC_TABLE_ID,
        bbox_role=CONTENT_BBOX_ROLE,
        structural_bbox_role=STRUCTURAL_BBOX_ROLE,
        derivation_method=DERIVATION_METHOD,
        coordinate_origin="top_left",
        coordinate_space="displayed_pdf_page",
        bbox_keys=NORMALIZED_BBOX_KEYS,
        row_count=6,
        column_count=5,
        cell_count=30,
        source_pdf_identity=BoundFileIdentity(**_EXPECTED_SOURCE_IDENTITY),
        predecessor_identity=BoundFileIdentity(**_EXPECTED_PREDECESSOR_IDENTITY),
        structural_truth_identity=BoundFileIdentity(
            **_EXPECTED_STRUCTURAL_TRUTH_IDENTITY
        ),
        cells=_derive_cells(predecessor_raw),
    )


def source_content_bbox_oracle_sha256(
    oracle: SourceContentBBoxOracle | None = None,
) -> str:
    selected = oracle or EXHIBIT7_SOURCE_CONTENT_BBOX_ORACLE
    payload = json.dumps(
        selected.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def source_content_bbox_oracle_metadata() -> dict[str, Any]:
    oracle = EXHIBIT7_SOURCE_CONTENT_BBOX_ORACLE
    return {
        "schema_id": oracle.schema_id,
        "policy_id": oracle.policy_id,
        "semantic_identity": {
            "schema_id": SEMANTIC_IDENTITY_SCHEMA_ID,
            "sha256": source_content_bbox_oracle_sha256(oracle),
        },
        "bbox_roles": {
            "public_cell_bbox": oracle.bbox_role,
            "structural_cell_bbox": oracle.structural_bbox_role,
        },
        "derivation_method": oracle.derivation_method,
        "bbox_keys": list(oracle.bbox_keys),
        "cell_count": oracle.cell_count,
        "source_pdf_identity": oracle.source_pdf_identity.model_dump(mode="json"),
        "predecessor_identity": oracle.predecessor_identity.model_dump(mode="json"),
        "structural_truth_identity": (
            oracle.structural_truth_identity.model_dump(mode="json")
        ),
    }


EXHIBIT7_SOURCE_CONTENT_BBOX_ORACLE = derive_source_content_bbox_oracle()
if (
    source_content_bbox_oracle_sha256(EXHIBIT7_SOURCE_CONTENT_BBOX_ORACLE)
    != EXPECTED_SEMANTIC_SHA256
):
    raise ValueError("source-content bbox oracle semantic identity differs")
EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION = MappingProxyType(
    {
        (cell.row, cell.column): cell
        for cell in EXHIBIT7_SOURCE_CONTENT_BBOX_ORACLE.cells
    }
)
