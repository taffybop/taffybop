"""Bounded diagnostic custody for opaque Docling raw-group relationships.

The public v1 response deliberately does not expose Docling's internal group
nodes.  A table-marked P04 response can nevertheless retain those source graph
edges as a non-authoritative, digest-only audit surface.  This module validates
and seals that audit surface; its caller exclusively owns output authority.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import hashlib
import json
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models import CanonicalSourceCustody
    from app.services.ir import DocumentIR, ElementRecord, RelationshipRecord


POLICY_ID = "p04-opaque-raw-group-custody-v1"
SCHEMA_VERSION = "1.0"
AUTHORITY = "diagnostic_only"
ROOT_SINGLETON_POLICY = "nonsemantic_placement_not_claimed"
MAX_RECORDS = 65_536
MAX_RAW_DEFINITIONS_SCANNED = 262_144
MAX_CONTENT_ITEM_BYTES = 8 * 1024 * 1024
MAX_CONTENT_DOCUMENT_BYTES = 64 * 1024 * 1024
_MAX_TABLE_MARKER_PAGES = 4_096

_GROUP_PREFIX = "#/groups/"
_RAW_REF_RE = re.compile(
    r"^#/(?:groups|texts|pictures|tables|key_value_items|form_items|"
    r"field_regions|field_items)/(?:0|[1-9][0-9]{0,9})$"
)


@dataclass(frozen=True)
class DetachedOpaqueGroupEdges:
    original_relationship_ids: tuple[str, ...]
    detached: tuple[tuple[int, "RelationshipRecord"], ...]
    raw_closure: "FrozenRelevantRawClosure"

    @property
    def raw_closure_sha256(self) -> str:
        return self.raw_closure.closure_sha256

    @property
    def raw_closure_size_bytes(self) -> int:
        return self.raw_closure.closure_size_bytes


@dataclass(frozen=True)
class FrozenRawDefinition:
    """Owned, bounded identity/provenance facts for one relevant raw node."""

    raw_ref: str
    collection: str
    collection_index: int
    label: str
    selected_source_sha256: str


@dataclass(frozen=True)
class FrozenRawAssertion:
    """One exact supported literal assertion that touches an opaque group."""

    owner_order: int
    owner_raw_ref: str
    literal_target_raw_ref: str
    relationship_field: str
    raw_slot_index: int
    raw_target_slot_index: int | None
    relationship_type: str
    source_raw_ref: str
    target_raw_ref: str
    raw_assertion_sha256: str


@dataclass(frozen=True)
class FrozenRelevantRawClosure:
    """Compact source closure; unrelated raw payloads are intentionally absent."""

    definitions: tuple[FrozenRawDefinition, ...]
    assertions: tuple[FrozenRawAssertion, ...]
    closure_sha256: str
    closure_size_bytes: int


class OpaqueGroupCustodyResourceError(ValueError):
    """A bounded P04 custody projection exceeded its resource envelope."""


class OpaqueGroupCustodyIntegrityError(ValueError):
    """A relevant raw-group assertion could not be closed losslessly."""


class OpaqueGroupCustodyTimeoutError(TimeoutError):
    """The caller-owned cumulative P04 document deadline expired."""


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.perf_counter() > deadline:
        raise OpaqueGroupCustodyTimeoutError(
            "opaque group custody document deadline exceeded"
        )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_digest_and_size(
    value: Any,
    *,
    maximum_bytes: int | None = None,
    deadline: float | None = None,
) -> tuple[str, int]:
    try:
        encoder = json.JSONEncoder(
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256()
        total = 0
        for chunk in encoder.iterencode(value):
            _check_deadline(deadline)
            encoded = chunk.encode("utf-8")
            total += len(encoded)
            if maximum_bytes is not None and total > maximum_bytes:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group custody JSON exceeds its byte cap"
                )
            digest.update(encoded)
        return digest.hexdigest(), total
    except (
        OpaqueGroupCustodyIntegrityError,
        OpaqueGroupCustodyResourceError,
        OpaqueGroupCustodyTimeoutError,
    ):
        raise
    except MemoryError as exc:
        raise OpaqueGroupCustodyResourceError(
            "opaque group custody JSON exhausted resources"
        ) from exc
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group custody JSON is not finite strict data"
        ) from exc


def _frozen_json_bytes(
    value: Any,
    *,
    maximum_bytes: int,
    deadline: float | None = None,
) -> bytes:
    """Capture one bounded, owned canonical JSON closure."""

    try:
        encoder = json.JSONEncoder(
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        chunks: list[bytes] = []
        total = 0
        for chunk in encoder.iterencode(value):
            _check_deadline(deadline)
            encoded = chunk.encode("utf-8")
            total += len(encoded)
            if total > maximum_bytes:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group custody JSON exceeds its byte cap"
                )
            chunks.append(encoded)
        return b"".join(chunks)
    except (
        OpaqueGroupCustodyIntegrityError,
        OpaqueGroupCustodyResourceError,
        OpaqueGroupCustodyTimeoutError,
    ):
        raise
    except MemoryError as exc:
        raise OpaqueGroupCustodyResourceError(
            "opaque group custody JSON exhausted resources"
        ) from exc
    except (
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group custody JSON is not finite strict data"
        ) from exc


def stable_id(prefix: str, *parts: Any) -> str:
    """Reproduce the stable IR identity algorithm for closed custody fields."""

    return f"{prefix}-{hashlib.sha256(_canonical_bytes(parts)).hexdigest()[:20]}"


def member_content_sha256(element: ElementRecord) -> str:
    """Digest semantic content without projecting raw text into the sidecar."""

    digest, _size = _json_digest_and_size(
        {
            "markdown": element.markdown,
            "type": element.type,
            "value": element.value,
        },
        maximum_bytes=MAX_CONTENT_ITEM_BYTES,
    )
    return digest


def empty_group_content_sha256(element_type: str) -> str:
    """Return the independently reproducible digest for an opaque empty group."""

    if element_type not in {"group", "list"}:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group semantic type differs"
        )
    digest, _size = _json_digest_and_size(
        {"markdown": None, "type": element_type, "value": None},
        maximum_bytes=MAX_CONTENT_ITEM_BYTES,
    )
    return digest


def _member_content_digest_and_size(
    element: ElementRecord,
    *,
    deadline: float | None = None,
) -> tuple[str, int]:
    return _json_digest_and_size(
        {
            "markdown": element.markdown,
            "type": element.type,
            "value": element.value,
        },
        maximum_bytes=MAX_CONTENT_ITEM_BYTES,
        deadline=deadline,
    )


def record_id(
    record_without_id: Mapping[str, Any],
    source_sha256: str,
) -> str:
    return "custody-" + hashlib.sha256(
        _canonical_bytes(
            {
                "record": record_without_id,
                "source_sha256": source_sha256,
            }
        )
    ).hexdigest()


def records_sha256(
    records: list[dict[str, Any]],
    *,
    deadline: float | None = None,
) -> str:
    digest, _size = _json_digest_and_size(
        records,
        maximum_bytes=MAX_CONTENT_DOCUMENT_BYTES,
        deadline=deadline,
    )
    return digest


def has_literal_table_marker(document: Mapping[str, Any]) -> bool:
    """Return true only for a concrete valid-or-diagnostic P04 table marker."""

    pages = document.get("pages")
    return isinstance(pages, list) and any(
        type(page) is dict
        and type(page.get("items")) is list
        and any(
            type(item) is dict and type(item.get("table_evidence")) is dict
            for item in page["items"]
        )
        for page in pages
    )


def _capture_table_marker_bytes(
    document: Mapping[str, Any],
    *,
    deadline: float | None = None,
) -> int:
    """Read and size every literal marker once before source closure checks."""

    _check_deadline(deadline)
    if not isinstance(document, Mapping):
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group custody document differs"
        )
    pages = document.get("pages")
    if type(pages) is not list or len(pages) > _MAX_TABLE_MARKER_PAGES:
        raise OpaqueGroupCustodyResourceError(
            "opaque group custody page coverage exceeds its cap"
        )
    marker_bytes = 0
    item_count = 0
    marker_count = 0
    for page in pages:
        _check_deadline(deadline)
        if not isinstance(page, Mapping):
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group custody page differs"
            )
        items = page.get("items")
        if type(items) is not list:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group custody item coverage differs"
            )
        item_count += len(items)
        if item_count > MAX_RECORDS:
            raise OpaqueGroupCustodyResourceError(
                "opaque group custody item coverage exceeds its cap"
            )
        for item in items:
            _check_deadline(deadline)
            if not isinstance(item, Mapping):
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group custody item differs"
                )
            marker = item.get("table_evidence")
            if type(marker) is not dict:
                continue
            marker_count += 1
            _digest, size = _json_digest_and_size(
                marker,
                maximum_bytes=MAX_CONTENT_ITEM_BYTES,
                deadline=deadline,
            )
            marker_bytes += size
            if marker_bytes > MAX_CONTENT_DOCUMENT_BYTES:
                raise OpaqueGroupCustodyResourceError(
                    "table evidence and custody exceed their document byte cap"
                )
    if marker_count == 0:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group custody requires a literal table marker"
        )
    return marker_bytes


def _raw_refs(element: ElementRecord) -> tuple[str, ...]:
    raw = element.properties.get("raw_refs")
    if not isinstance(raw, list):
        return ()
    return tuple(value for value in raw if isinstance(value, str))


def _opaque_group_descriptor(
    relationship: RelationshipRecord,
    elements: Mapping[str, ElementRecord],
) -> tuple[str, str, ElementRecord, ElementRecord, str, str] | None:
    metadata = relationship.metadata
    if metadata.get("normalization_origin") != "docling_reference_graph":
        return None
    owner_ref = metadata.get("source_ref")
    referenced_ref = metadata.get("target_ref")
    if (
        not isinstance(owner_ref, str)
        or not isinstance(referenced_ref, str)
        or _RAW_REF_RE.fullmatch(owner_ref) is None
        or _RAW_REF_RE.fullmatch(referenced_ref) is None
    ):
        return None
    source = elements.get(relationship.source_id)
    target = elements.get(relationship.target_id)
    if source is None or target is None:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group relationship endpoint is unavailable"
        )
    endpoint_by_ref = {
        raw_ref: element
        for raw_ref in (owner_ref, referenced_ref)
        for element in (source, target)
        if raw_ref in _raw_refs(element)
    }
    if set(endpoint_by_ref) != {owner_ref, referenced_ref}:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group raw reference binding differs"
        )
    group_refs = [
        raw_ref
        for raw_ref in (owner_ref, referenced_ref)
        if raw_ref.startswith(_GROUP_PREFIX)
    ]
    if not group_refs:
        return None
    group_ref = group_refs[0]
    member_ref = referenced_ref if group_ref == owner_ref else owner_ref
    group = endpoint_by_ref[group_ref]
    member = endpoint_by_ref[member_ref]
    if group.id == member.id:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group relationship collapses its endpoints"
        )
    source_raw_ref = group_ref if source.id == group.id else member_ref
    target_raw_ref = group_ref if target.id == group.id else member_ref
    return (
        group_ref,
        member_ref,
        group,
        member,
        source_raw_ref,
        target_raw_ref,
    )


def _raw_reference(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return str(value.get("$ref") or value.get("cref") or "").strip()


def _raw_sequence(value: Any) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return value
    return None


_RAW_COLLECTIONS = (
    "groups",
    "texts",
    "pictures",
    "tables",
    "key_value_items",
    "form_items",
    "field_regions",
    "field_items",
)
_RAW_RELATION_FIELDS: dict[str, tuple[str, bool]] = {
    "children": ("contains", False),
    "captions": ("caption_of", True),
    "caption": ("caption_of", True),
    "source_notes": ("source_note_of", True),
    "source_note": ("source_note_of", True),
    "footnotes": ("footnote_of", True),
    "footnote": ("footnote_of", True),
    "legends": ("legend_of", True),
    "legend": ("legend_of", True),
    "axes": ("axis_of", True),
    "axis": ("axis_of", True),
    "alternatives": ("alternative_of", True),
    "alternative": ("alternative_of", True),
    "annotations": ("annotation_of", True),
    "comments": ("annotation_of", True),
    "references": ("references", False),
}
_FIELD_TOKEN_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)(.*)$")
_FIELD_INDEX_RE = re.compile(r"\[([0-9]+)\]")


def _raw_assertion_slots(
    owner: Mapping[str, Any],
    *,
    deadline: float | None = None,
) -> Iterator[
    tuple[str, int, int | None, Any, str, bool, Mapping[str, Any]]
]:
    """Yield P01-supported literal paths without duplicating raw containers."""

    for field, (relationship_type, child_is_source) in _RAW_RELATION_FIELDS.items():
        if field not in owner:
            continue
        raw_values = owner.get(field)
        sequence_values = _raw_sequence(raw_values)
        values = (
            sequence_values if sequence_values is not None else (raw_values,)
        )
        for slot, raw_value in enumerate(values):
            _check_deadline(deadline)
            if (
                field == "annotations"
                and isinstance(raw_value, Mapping)
                and raw_value.get("kind")
                and not _raw_reference(raw_value)
            ):
                # P01 permits embedded typed annotation payloads here; their
                # nested chart-data refs are scanned separately below.
                continue
            yield (
                field,
                slot,
                None,
                raw_value,
                relationship_type,
                child_is_source,
                {},
            )

    def iter_table_cells(
        data: Any,
        *,
        path_prefix: str,
    ) -> Iterator[
        tuple[str, int, int | None, Any, str, bool, Mapping[str, Any]]
    ]:
        if not isinstance(data, Mapping):
            return
        cells = data.get("table_cells")
        cell_values = _raw_sequence(cells)
        if cell_values is None:
            return
        for cell_index, cell in enumerate(cell_values):
            _check_deadline(deadline)
            if not isinstance(cell, Mapping) or "ref" not in cell:
                continue
            raw_value = cell.get("ref")
            base_reference_metadata = {
                "cell_index": cell_index,
                "start_row_offset_idx": cell.get("start_row_offset_idx"),
                "end_row_offset_idx": cell.get("end_row_offset_idx"),
                "start_col_offset_idx": cell.get("start_col_offset_idx"),
                "end_col_offset_idx": cell.get("end_col_offset_idx"),
            }
            target_values = _raw_sequence(raw_value)
            raw_targets = (
                target_values if target_values is not None else (raw_value,)
            )
            for target_slot, raw_target in enumerate(raw_targets):
                _check_deadline(deadline)
                reference_metadata = dict(base_reference_metadata)
                if (
                    isinstance(raw_target, Mapping)
                    and raw_target.get("range") is not None
                ):
                    reference_metadata["range"] = raw_target.get("range")
                yield (
                    f"{path_prefix}.table_cells[{cell_index}].ref",
                    0,
                    target_slot if target_values is not None else None,
                    raw_target,
                    "contains",
                    False,
                    reference_metadata,
                )

    graph = owner.get("graph")
    if isinstance(graph, Mapping):
        cells = graph.get("cells")
        cell_values = _raw_sequence(cells)
        if cell_values is not None:
            for cell_index, cell in enumerate(cell_values):
                _check_deadline(deadline)
                if not isinstance(cell, Mapping) or "item_ref" not in cell:
                    continue
                raw_value = cell.get("item_ref")
                base_reference_metadata = {
                    "cell_index": cell_index,
                    "cell_id": cell.get("cell_id"),
                    "cell_label": cell.get("label"),
                }
                target_values = _raw_sequence(raw_value)
                raw_targets = (
                    target_values if target_values is not None else (raw_value,)
                )
                for target_slot, raw_target in enumerate(raw_targets):
                    _check_deadline(deadline)
                    reference_metadata = dict(base_reference_metadata)
                    if (
                        isinstance(raw_target, Mapping)
                        and raw_target.get("range") is not None
                    ):
                        reference_metadata["range"] = raw_target.get("range")
                    yield (
                        f"graph.cells[{cell_index}].item_ref",
                        0,
                        target_slot if target_values is not None else None,
                        raw_target,
                        "contains",
                        False,
                        reference_metadata,
                    )

    yield from iter_table_cells(owner.get("data"), path_prefix="data")
    annotations = owner.get("annotations")
    annotation_values = _raw_sequence(annotations)
    if annotation_values is not None:
        for annotation_index, annotation in enumerate(annotation_values):
            _check_deadline(deadline)
            if isinstance(annotation, Mapping):
                yield from iter_table_cells(
                    annotation.get("chart_data"),
                    path_prefix=(
                        f"annotations[{annotation_index}].chart_data"
                    ),
                )
    meta = owner.get("meta")
    if isinstance(meta, Mapping):
        tabular_chart = meta.get("tabular_chart")
        if isinstance(tabular_chart, Mapping):
            yield from iter_table_cells(
                tabular_chart.get("chart_data"),
                path_prefix="meta.tabular_chart.chart_data",
            )
    if "parent" in owner and owner.get("parent") is not None:
        _check_deadline(deadline)
        yield (
            "parent",
            0,
            None,
            owner.get("parent"),
            "contains",
            False,
            {},
        )


class _SparseRawSequence(Sequence[Any]):
    """Expose selected source slots without retaining disconnected payloads."""

    __slots__ = ("_length", "_selected")

    def __init__(
        self,
        length: int,
        selected: Mapping[int, Mapping[str, Any]],
    ) -> None:
        self._length = length
        self._selected = dict(selected)

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, index: int | slice) -> Any:
        if isinstance(index, slice):
            return tuple(self[offset] for offset in range(*index.indices(self._length)))
        if index < 0:
            index += self._length
        if index < 0 or index >= self._length:
            raise IndexError(index)
        return self._selected.get(index)


class _RawRefComponents:
    """Compact union-find for one bounded scan of group-touching raw refs."""

    __slots__ = ("indexes", "parents", "ranks")

    def __init__(self, seeds: set[str]) -> None:
        self.indexes: dict[str, int] = {}
        self.parents = array("I")
        self.ranks = bytearray()
        for raw_ref in sorted(seeds):
            self.ensure(raw_ref)

    def ensure(self, raw_ref: str) -> int:
        index = self.indexes.get(raw_ref)
        if index is not None:
            return index
        index = len(self.parents)
        self.indexes[raw_ref] = index
        self.parents.append(index)
        self.ranks.append(0)
        return index

    def find_index(self, index: int) -> int:
        root = index
        while self.parents[root] != root:
            root = self.parents[root]
        while self.parents[index] != index:
            next_index = self.parents[index]
            self.parents[index] = root
            index = next_index
        return root

    def union(self, left_ref: str, right_ref: str) -> None:
        left_root = self.find_index(self.ensure(left_ref))
        right_root = self.find_index(self.ensure(right_ref))
        if left_root == right_root:
            return
        left_rank = self.ranks[left_root]
        right_rank = self.ranks[right_root]
        if left_rank < right_rank:
            left_root, right_root = right_root, left_root
            left_rank, right_rank = right_rank, left_rank
        self.parents[right_root] = left_root
        if left_rank == right_rank:
            self.ranks[left_root] = left_rank + 1

    def selected_refs(self, seeds: set[str]) -> set[str]:
        selected_roots = {
            self.find_index(self.indexes[raw_ref]) for raw_ref in seeds
        }
        return {
            raw_ref
            for raw_ref, index in self.indexes.items()
            if self.find_index(index) in selected_roots
        }


def _scoped_raw_graph(
    raw_graph: Mapping[str, Any],
    *,
    required_raw_refs: set[str],
    deadline: float | None,
) -> Mapping[str, Any]:
    """Stream global source once, then retain only selected raw components.

    The source definition and assertion caps remain document-wide.  Connectivity
    needs only raw-ref identities, so disconnected mappings and assertion
    payloads are never accumulated while finding the selected component.
    """

    scanned_definition_count = 0
    for collection in _RAW_COLLECTIONS:
        _check_deadline(deadline)
        values = raw_graph.get(collection)
        sequence_values = _raw_sequence(values)
        if sequence_values is None:
            continue
        for value in sequence_values:
            _check_deadline(deadline)
            if not isinstance(value, Mapping):
                continue
            raw_ref = str(value.get("self_ref") or "").strip()
            if _RAW_REF_RE.fullmatch(raw_ref) is None:
                continue
            scanned_definition_count += 1
            if scanned_definition_count > MAX_RAW_DEFINITIONS_SCANNED:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group raw definition scan cap exceeded"
                )

    components = _RawRefComponents(required_raw_refs)
    assertion_count = 0
    for collection in _RAW_COLLECTIONS:
        _check_deadline(deadline)
        values = raw_graph.get(collection)
        sequence_values = _raw_sequence(values)
        if sequence_values is None:
            continue
        for value in sequence_values:
            _check_deadline(deadline)
            if not isinstance(value, Mapping):
                continue
            owner_ref = str(value.get("self_ref") or "").strip()
            if _RAW_REF_RE.fullmatch(owner_ref) is None:
                continue
            group_owner = owner_ref.startswith(_GROUP_PREFIX)
            for (
                field,
                _slot,
                _target_slot,
                raw_value,
                _relationship_type,
                _child_is_source,
                _reference_metadata,
            ) in _raw_assertion_slots(value, deadline=deadline):
                literal_target_ref = _raw_reference(raw_value)
                if not (
                    group_owner
                    or literal_target_ref.startswith(_GROUP_PREFIX)
                ):
                    continue
                if not literal_target_ref:
                    continue
                if field == "parent" and literal_target_ref in {
                    "#/body",
                    "#/furniture",
                }:
                    continue
                assertion_count += 1
                if assertion_count > MAX_RECORDS:
                    raise OpaqueGroupCustodyResourceError(
                        "opaque group relevant assertion cap exceeded"
                    )
                # Non-empty malformed references remain graph identities here.
                # If the same malformed literal bridges into a selected
                # component, the legacy closure must still reject that entire
                # component with its established error ordering.
                components.union(owner_ref, literal_target_ref)

    for root_name in ("body", "furniture"):
        _check_deadline(deadline)
        root = raw_graph.get(root_name)
        if not isinstance(root, Mapping):
            continue
        raw_children = root.get("children")
        child_sequence = _raw_sequence(raw_children)
        children = child_sequence if child_sequence is not None else (raw_children,)
        prior_ref = ""
        has_prior = False
        for child_value in children:
            _check_deadline(deadline)
            child_ref = _raw_reference(child_value)
            if has_prior and (
                prior_ref.startswith(_GROUP_PREFIX)
                or child_ref.startswith(_GROUP_PREFIX)
            ):
                if prior_ref and child_ref:
                    assertion_count += 1
                    if assertion_count > MAX_RECORDS:
                        raise OpaqueGroupCustodyResourceError(
                            "opaque group relevant assertion cap exceeded"
                        )
                    components.union(prior_ref, child_ref)
            prior_ref = child_ref
            has_prior = True

    selected_refs = components.selected_refs(required_raw_refs)
    filtered: dict[str, Any] = {}
    for collection in _RAW_COLLECTIONS:
        _check_deadline(deadline)
        values = raw_graph.get(collection)
        sequence_values = _raw_sequence(values)
        if sequence_values is None:
            continue
        selected_slots: dict[int, Mapping[str, Any]] = {}
        for collection_index, value in enumerate(sequence_values):
            _check_deadline(deadline)
            if not isinstance(value, Mapping):
                continue
            raw_ref = str(value.get("self_ref") or "").strip()
            if raw_ref in selected_refs:
                selected_slots[collection_index] = value
        filtered[collection] = _SparseRawSequence(
            len(sequence_values),
            selected_slots,
        )

    for root_name in ("body", "furniture"):
        _check_deadline(deadline)
        root = raw_graph.get(root_name)
        if not isinstance(root, Mapping):
            continue
        raw_children = root.get("children")
        child_sequence = _raw_sequence(raw_children)
        children = child_sequence if child_sequence is not None else (raw_children,)
        prior_ref = ""
        has_prior = False
        selected_root = False
        for child_value in children:
            _check_deadline(deadline)
            child_ref = _raw_reference(child_value)
            if child_ref.startswith(_GROUP_PREFIX) and child_ref in selected_refs:
                selected_root = True
            if has_prior and (
                prior_ref.startswith(_GROUP_PREFIX)
                or child_ref.startswith(_GROUP_PREFIX)
            ) and (prior_ref in selected_refs or child_ref in selected_refs):
                selected_root = True
            prior_ref = child_ref
            has_prior = True
        filtered[root_name] = (
            root
            if selected_root
            else {"self_ref": f"#/{root_name}", "children": []}
        )
    return filtered


def _capture_relevant_raw_closure_unscoped(
    raw_graph: Mapping[str, Any],
    *,
    required_raw_refs: set[str] | None = None,
    deadline: float | None = None,
) -> FrozenRelevantRawClosure:
    """Freeze only group-touching definitions and literal assertions.

    The scan is deliberately shallow outside the fixed P01 relationship path
    families.  Unrelated metadata, including large/deep payloads and duplicate
    unrelated owners, never enters the closure or its resource accounting.
    """

    try:
        if required_raw_refs is not None:
            if (
                type(required_raw_refs) is not set
                or len(required_raw_refs) > MAX_RECORDS * 2
                or any(
                    type(raw_ref) is not str
                    or _RAW_REF_RE.fullmatch(raw_ref) is None
                    for raw_ref in required_raw_refs
                )
            ):
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group required raw scope differs"
                )
            if not required_raw_refs:
                empty_payload = {
                    "assertions": [],
                    "definitions": [],
                    "root_singleton_policy": ROOT_SINGLETON_POLICY,
                }
                closure_sha256, closure_size_bytes = _json_digest_and_size(
                    empty_payload,
                    maximum_bytes=MAX_CONTENT_DOCUMENT_BYTES,
                    deadline=deadline,
                )
                return FrozenRelevantRawClosure(
                    definitions=(),
                    assertions=(),
                    closure_sha256=closure_sha256,
                    closure_size_bytes=closure_size_bytes,
                )
        candidates: dict[
            str,
            list[tuple[str, int, Mapping[str, Any]]],
        ] = {}
        candidate_order: list[tuple[str, str, int, Mapping[str, Any]]] = []
        scanned_definition_count = 0
        for collection in _RAW_COLLECTIONS:
            _check_deadline(deadline)
            values = raw_graph.get(collection)
            sequence_values = _raw_sequence(values)
            if sequence_values is None:
                continue
            for collection_index, value in enumerate(sequence_values):
                _check_deadline(deadline)
                if not isinstance(value, Mapping):
                    continue
                raw_ref = str(value.get("self_ref") or "").strip()
                if _RAW_REF_RE.fullmatch(raw_ref) is None:
                    continue
                scanned_definition_count += 1
                if scanned_definition_count > MAX_RAW_DEFINITIONS_SCANNED:
                    raise OpaqueGroupCustodyResourceError(
                        "opaque group raw definition scan cap exceeded"
                    )
                candidates.setdefault(raw_ref, []).append(
                    (collection, collection_index, value)
                )
                candidate_order.append(
                    (raw_ref, collection, collection_index, value)
                )

        roots: dict[str, Mapping[str, Any]] = {}
        malformed_root_refs: set[str] = set()
        for root_name in ("body", "furniture"):
            _check_deadline(deadline)
            root = raw_graph.get(root_name)
            if not isinstance(root, Mapping):
                continue
            expected_root_ref = f"#/{root_name}"
            declared_root_ref = root.get("self_ref", expected_root_ref)
            root_ref = expected_root_ref
            if declared_root_ref != expected_root_ref:
                # A malformed root matters only if it mentions a group.  The
                # bounded field scan below establishes that relevance.
                malformed_root_refs.add(root_ref)
            roots[root_ref] = root

        relevant_refs = set(required_raw_refs or ())
        pending: list[
            tuple[
                str,
                str,
                int,
                int | None,
                Any,
                str,
                bool,
                Mapping[str, Any],
            ]
        ] = []
        malformed_nested_owner_refs: set[str] = set()
        malformed_assertion_owner_refs: set[str] = set()
        for owner_ref, _collection, _collection_index, owner in candidate_order:
            _check_deadline(deadline)
            group_owner = owner_ref.startswith(_GROUP_PREFIX)
            nested_path: tuple[str, int] | None = None
            nested_path_malformed = False
            nested_path_relevant = group_owner
            for (
                field,
                slot,
                target_slot,
                raw_value,
                relationship_type,
                child_is_source,
                reference_metadata,
            ) in _raw_assertion_slots(owner, deadline=deadline):
                literal_target_ref = _raw_reference(raw_value)
                group_target = literal_target_ref.startswith(_GROUP_PREFIX)
                if target_slot is not None:
                    current_nested_path = (field, slot)
                    if current_nested_path != nested_path:
                        nested_path = current_nested_path
                        nested_path_malformed = False
                        nested_path_relevant = group_owner
                    if _RAW_REF_RE.fullmatch(literal_target_ref) is None:
                        nested_path_malformed = True
                        if nested_path_relevant:
                            malformed_nested_owner_refs.add(owner_ref)
                    elif group_target:
                        nested_path_relevant = True
                        if nested_path_malformed:
                            malformed_nested_owner_refs.add(owner_ref)
                if not (group_owner or group_target):
                    continue
                if not literal_target_ref:
                    if target_slot is not None:
                        malformed_nested_owner_refs.add(owner_ref)
                    else:
                        malformed_assertion_owner_refs.add(owner_ref)
                    continue
                if field == "parent" and literal_target_ref in {
                    "#/body",
                    "#/furniture",
                }:
                    # Root parent declarations are placement metadata, not a
                    # normalized semantic edge.  Singleton root placement is
                    # intentionally outside this normalized-edge sidecar.
                    continue
                pending.append(
                    (
                        owner_ref,
                        field,
                        slot,
                        target_slot,
                        raw_value,
                        relationship_type,
                        child_is_source,
                        reference_metadata,
                    )
                )
                if len(pending) > MAX_RECORDS:
                    raise OpaqueGroupCustodyResourceError(
                        "opaque group relevant assertion cap exceeded"
                    )

        root_pending: list[tuple[str, int, str, str, Any, Any]] = []
        malformed_root_identity_component_refs: set[str] = set()
        malformed_root_assertion_component_refs: set[str] = set()
        for root_ref, root in roots.items():
            raw_children = root.get("children")
            child_sequence = _raw_sequence(raw_children)
            children = (
                child_sequence if child_sequence is not None else (raw_children,)
            )
            prior_value: Any = None
            prior_ref = ""
            has_prior = False
            malformed_seen = False
            root_touches_group = False
            root_group_refs: set[str] = set()
            for child_index, child_value in enumerate(children):
                _check_deadline(deadline)
                child_ref = _raw_reference(child_value)
                if not child_ref:
                    malformed_seen = True
                if child_ref.startswith(_GROUP_PREFIX):
                    root_touches_group = True
                    root_group_refs.add(child_ref)
                if root_touches_group and not child_ref:
                    malformed_seen = True
                if has_prior and (
                    prior_ref.startswith(_GROUP_PREFIX)
                    or child_ref.startswith(_GROUP_PREFIX)
                ):
                    if not prior_ref or not child_ref:
                        malformed_seen = True
                    else:
                        root_pending.append(
                            (
                                root_ref,
                                child_index - 1,
                                prior_ref,
                                child_ref,
                                prior_value,
                                child_value,
                            )
                        )
                        if len(pending) + len(root_pending) > MAX_RECORDS:
                            raise OpaqueGroupCustodyResourceError(
                                "opaque group relevant assertion cap exceeded"
                            )
                prior_value = child_value
                prior_ref = child_ref
                has_prior = True
            if root_group_refs and root_ref in malformed_root_refs:
                malformed_root_identity_component_refs.update(root_group_refs)
            if root_group_refs and malformed_seen:
                malformed_root_assertion_component_refs.update(root_group_refs)

        if required_raw_refs is None:
            if malformed_nested_owner_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group nested raw assertion is malformed"
                )
            if malformed_assertion_owner_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group raw assertion is malformed"
                )
            if malformed_root_identity_component_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group root identity is malformed"
                )
            if malformed_root_assertion_component_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group root assertion is malformed"
                )

        if required_raw_refs is not None:
            assertion_adjacency: dict[str, list[tuple[str, int]]] = {}
            for assertion_index, assertion in enumerate(pending):
                owner_ref = assertion[0]
                literal_target_ref = _raw_reference(assertion[4])
                assertion_adjacency.setdefault(owner_ref, []).append(
                    ("assertion", assertion_index)
                )
                assertion_adjacency.setdefault(literal_target_ref, []).append(
                    ("assertion", assertion_index)
                )
            for assertion_index, assertion in enumerate(root_pending):
                source_ref = assertion[2]
                target_ref = assertion[3]
                assertion_adjacency.setdefault(source_ref, []).append(
                    ("root", assertion_index)
                )
                assertion_adjacency.setdefault(target_ref, []).append(
                    ("root", assertion_index)
                )

            reached_refs = set(required_raw_refs)
            selected_pending_indexes: set[int] = set()
            selected_root_indexes: set[int] = set()
            queue = list(sorted(required_raw_refs))
            queue_offset = 0
            while queue_offset < len(queue):
                _check_deadline(deadline)
                raw_ref = queue[queue_offset]
                queue_offset += 1
                for assertion_kind, assertion_index in assertion_adjacency.get(
                    raw_ref, ()
                ):
                    if assertion_kind == "assertion":
                        if assertion_index in selected_pending_indexes:
                            continue
                        selected_pending_indexes.add(assertion_index)
                        assertion = pending[assertion_index]
                        endpoints = (
                            assertion[0],
                            _raw_reference(assertion[4]),
                        )
                    else:
                        if assertion_index in selected_root_indexes:
                            continue
                        selected_root_indexes.add(assertion_index)
                        assertion = root_pending[assertion_index]
                        endpoints = (assertion[2], assertion[3])
                    for endpoint_ref in endpoints:
                        if endpoint_ref not in reached_refs:
                            reached_refs.add(endpoint_ref)
                            queue.append(endpoint_ref)
            if malformed_nested_owner_refs & reached_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group nested raw assertion is malformed"
                )
            if malformed_assertion_owner_refs & reached_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group raw assertion is malformed"
                )
            if malformed_root_identity_component_refs & reached_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group root identity is malformed"
                )
            if malformed_root_assertion_component_refs & reached_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group root assertion is malformed"
                )
            pending = [
                assertion
                for assertion_index, assertion in enumerate(pending)
                if assertion_index in selected_pending_indexes
            ]
            root_pending = [
                assertion
                for assertion_index, assertion in enumerate(root_pending)
                if assertion_index in selected_root_indexes
            ]

        relevant_refs = set(required_raw_refs or ())
        for assertion in pending:
            relevant_refs.update((assertion[0], _raw_reference(assertion[4])))
        for assertion in root_pending:
            relevant_refs.update((assertion[2], assertion[3]))

        selected: dict[str, tuple[str, int, Mapping[str, Any]]] = {}
        for raw_ref in sorted(relevant_refs):
            definitions = candidates.get(raw_ref, [])
            if len(definitions) != 1:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group relevant raw definition is ambiguous"
                )
            selected[raw_ref] = definitions[0]

        definitions: list[FrozenRawDefinition] = []
        definition_order: dict[str, int] = {}
        relevant_source_bytes = 0
        for owner_order, (
            raw_ref,
            (collection, collection_index, raw_item),
        ) in enumerate(
            sorted(
                selected.items(),
                key=lambda value: (
                    _RAW_COLLECTIONS.index(value[1][0]),
                    value[1][1],
                    value[0],
                ),
            )
        ):
            _check_deadline(deadline)
            raw_label = raw_item.get("label")
            if raw_label is not None and not isinstance(raw_label, str):
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group relevant label differs"
                )
            label = raw_label or ""
            selected_source_sha256, selected_bytes = _json_digest_and_size(
                {
                    "label": label,
                    "prov": raw_item.get("prov"),
                    "self_ref": raw_ref,
                },
                maximum_bytes=MAX_CONTENT_ITEM_BYTES,
                deadline=deadline,
            )
            relevant_source_bytes += selected_bytes
            if relevant_source_bytes > MAX_CONTENT_DOCUMENT_BYTES:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group relevant source exceeds its document byte cap"
                )
            definition_order[raw_ref] = owner_order
            definitions.append(
                FrozenRawDefinition(
                    raw_ref=raw_ref,
                    collection=collection,
                    collection_index=collection_index,
                    label=label,
                    selected_source_sha256=selected_source_sha256,
                )
            )

        assertions: list[FrozenRawAssertion] = []
        for (
            owner_ref,
            field,
            slot,
            target_slot,
            raw_value,
            base_relationship_type,
            child_is_source,
            reference_metadata,
        ) in pending:
            _check_deadline(deadline)
            literal_target_ref = _raw_reference(raw_value)
            relationship_type = base_relationship_type
            if field == "children":
                target_definition = selected[literal_target_ref][2]
                target_label = str(target_definition.get("label") or "").casefold()
                if "caption" in target_label:
                    relationship_type, child_is_source = "caption_of", True
                elif "footnote" in target_label:
                    relationship_type, child_is_source = "footnote_of", True
                elif "source" in target_label and "note" in target_label:
                    relationship_type, child_is_source = "source_note_of", True
            if field == "parent":
                source_ref, target_ref = literal_target_ref, owner_ref
            else:
                source_ref, target_ref = (
                    (literal_target_ref, owner_ref)
                    if child_is_source
                    else (owner_ref, literal_target_ref)
                )
            raw_assertion_sha256, assertion_bytes = _json_digest_and_size(
                {
                    "field": field,
                    "owner_raw_ref": owner_ref,
                    "raw_slot_index": slot,
                    "raw_target_slot_index": target_slot,
                    "reference_metadata": dict(reference_metadata),
                    "value": raw_value,
                },
                maximum_bytes=MAX_CONTENT_ITEM_BYTES,
                deadline=deadline,
            )
            relevant_source_bytes += assertion_bytes
            if relevant_source_bytes > MAX_CONTENT_DOCUMENT_BYTES:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group relevant source exceeds its document byte cap"
                )
            assertions.append(
                FrozenRawAssertion(
                    owner_order=definition_order[owner_ref],
                    owner_raw_ref=owner_ref,
                    literal_target_raw_ref=literal_target_ref,
                    relationship_field=field,
                    raw_slot_index=slot,
                    raw_target_slot_index=target_slot,
                    relationship_type=relationship_type,
                    source_raw_ref=source_ref,
                    target_raw_ref=target_ref,
                    raw_assertion_sha256=raw_assertion_sha256,
                )
            )

        root_owner_order = {
            root_ref: len(definition_order) + offset
            for offset, root_ref in enumerate(sorted(roots))
        }
        for (
            root_ref,
            slot,
            source_ref,
            target_ref,
            source_value,
            target_value,
        ) in root_pending:
            raw_assertion_sha256, assertion_bytes = _json_digest_and_size(
                {
                    "field": f"{root_ref[2:]}.children.reading_order",
                    "owner_raw_ref": root_ref,
                    "raw_slot_index": slot,
                    "raw_target_slot_index": slot + 1,
                    "value": {"source": source_value, "target": target_value},
                },
                maximum_bytes=MAX_CONTENT_ITEM_BYTES,
                deadline=deadline,
            )
            relevant_source_bytes += assertion_bytes
            if relevant_source_bytes > MAX_CONTENT_DOCUMENT_BYTES:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group relevant source exceeds its document byte cap"
                )
            assertions.append(
                FrozenRawAssertion(
                    owner_order=root_owner_order[root_ref],
                    owner_raw_ref=root_ref,
                    literal_target_raw_ref=target_ref,
                    relationship_field=(
                        f"{root_ref[2:]}.children.reading_order"
                    ),
                    raw_slot_index=slot,
                    raw_target_slot_index=slot + 1,
                    relationship_type="reading_before",
                    source_raw_ref=source_ref,
                    target_raw_ref=target_ref,
                    raw_assertion_sha256=raw_assertion_sha256,
                )
            )

        assertions.sort(
            key=lambda value: (
                value.owner_order,
                value.relationship_field,
                value.raw_slot_index,
                value.raw_target_slot_index
                if value.raw_target_slot_index is not None
                else -1,
                value.source_raw_ref,
                value.target_raw_ref,
            )
        )
        closure_payload = {
            "assertions": [
                {
                    "owner_order": value.owner_order,
                    "owner_raw_ref": value.owner_raw_ref,
                    "literal_target_raw_ref": value.literal_target_raw_ref,
                    "relationship_field": value.relationship_field,
                    "raw_slot_index": value.raw_slot_index,
                    "raw_target_slot_index": value.raw_target_slot_index,
                    "relationship_type": value.relationship_type,
                    "source_raw_ref": value.source_raw_ref,
                    "target_raw_ref": value.target_raw_ref,
                    "raw_assertion_sha256": value.raw_assertion_sha256,
                }
                for value in assertions
            ],
            "definitions": [
                {
                    "raw_ref": value.raw_ref,
                    "collection": value.collection,
                    "collection_index": value.collection_index,
                    "label": value.label,
                    "selected_source_sha256": value.selected_source_sha256,
                }
                for value in definitions
            ],
            "root_singleton_policy": ROOT_SINGLETON_POLICY,
        }
        closure_sha256, closure_size_bytes = _json_digest_and_size(
            closure_payload,
            maximum_bytes=MAX_CONTENT_DOCUMENT_BYTES,
            deadline=deadline,
        )
        return FrozenRelevantRawClosure(
            definitions=tuple(definitions),
            assertions=tuple(assertions),
            closure_sha256=closure_sha256,
            closure_size_bytes=closure_size_bytes,
        )
    except (
        OpaqueGroupCustodyIntegrityError,
        OpaqueGroupCustodyResourceError,
        OpaqueGroupCustodyTimeoutError,
    ):
        raise
    except MemoryError as exc:
        raise OpaqueGroupCustodyResourceError(
            "opaque group relevant closure exhausted resources"
        ) from exc
    except (
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group relevant closure is invalid"
        ) from exc


def _capture_relevant_raw_closure(
    raw_graph: Mapping[str, Any],
    *,
    required_raw_refs: set[str] | None = None,
    deadline: float | None = None,
) -> FrozenRelevantRawClosure:
    """Capture a full closure or a memory-bounded selected component."""

    try:
        if required_raw_refs is None:
            return _capture_relevant_raw_closure_unscoped(
                raw_graph,
                deadline=deadline,
            )
        if (
            type(required_raw_refs) is not set
            or len(required_raw_refs) > MAX_RECORDS * 2
            or any(
                type(raw_ref) is not str
                or _RAW_REF_RE.fullmatch(raw_ref) is None
                for raw_ref in required_raw_refs
            )
        ):
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group required raw scope differs"
            )
        if not required_raw_refs:
            # The legacy helper returns the exact constant closure before
            # consulting raw_graph, preserving the no-access boundary.
            return _capture_relevant_raw_closure_unscoped(
                raw_graph,
                required_raw_refs=set(),
                deadline=deadline,
            )
        scoped_graph = _scoped_raw_graph(
            raw_graph,
            required_raw_refs=required_raw_refs,
            deadline=deadline,
        )
        return _capture_relevant_raw_closure_unscoped(
            scoped_graph,
            required_raw_refs=set(required_raw_refs),
            deadline=deadline,
        )
    except (
        OpaqueGroupCustodyIntegrityError,
        OpaqueGroupCustodyResourceError,
        OpaqueGroupCustodyTimeoutError,
    ):
        raise
    except MemoryError as exc:
        raise OpaqueGroupCustodyResourceError(
            "opaque group relevant closure exhausted resources"
        ) from exc
    except (
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group relevant closure is invalid"
        ) from exc


def _raw_reference_records(
    raw_graph: Mapping[str, Any],
    *,
    deadline: float | None = None,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for collection in _RAW_COLLECTIONS:
        _check_deadline(deadline)
        values = raw_graph.get(collection)
        if not isinstance(values, list):
            continue
        for value in values:
            _check_deadline(deadline)
            if not isinstance(value, Mapping):
                continue
            raw_ref = value.get("self_ref")
            if not isinstance(raw_ref, str) or _RAW_REF_RE.fullmatch(raw_ref) is None:
                continue
            if raw_ref in records:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group raw owner identity repeats"
                )
            records[raw_ref] = value
    for root_name in ("body", "furniture"):
        _check_deadline(deadline)
        value = raw_graph.get(root_name)
        if not isinstance(value, Mapping):
            continue
        raw_ref = value.get("self_ref", f"#/{root_name}")
        if raw_ref != f"#/{root_name}" or raw_ref in records:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group raw root identity differs"
            )
        records[raw_ref] = value
    return records


def _field_value(owner: Mapping[str, Any], field: str) -> Any:
    value: Any = owner
    for token in field.split("."):
        match = _FIELD_TOKEN_RE.fullmatch(token)
        if match is None or not isinstance(value, Mapping):
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group raw relationship field differs"
            )
        name, indexes = match.groups()
        if name not in value:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group raw relationship field is unavailable"
            )
        value = value[name]
        consumed = ""
        for index_match in _FIELD_INDEX_RE.finditer(indexes):
            consumed += index_match.group(0)
            if not isinstance(value, list):
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group raw relationship index differs"
                )
            index = int(index_match.group(1))
            if index >= len(value):
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group raw relationship index differs"
                )
            value = value[index]
        if consumed != indexes:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group raw relationship field differs"
            )
    return value


def _literal_slots(owner: Mapping[str, Any], field: str) -> tuple[str, ...]:
    raw = _field_value(owner, field)
    values = raw if isinstance(raw, list) else [raw]
    references = tuple(_raw_reference(value) for value in values)
    if (
        not references
        or any(_RAW_REF_RE.fullmatch(value) is None for value in references)
        or len(references) != len(set(references))
    ):
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group raw relationship slots are not exact"
        )
    return references


def _literal_owner_slot(
    records: Mapping[str, Mapping[str, Any]],
    *,
    normalized_owner_ref: str,
    normalized_target_ref: str,
    field: str,
) -> tuple[str, str, int, int | None]:
    if field in {"body.children.reading_order", "furniture.children.reading_order"}:
        root_ref = f"#/{field.split('.', 1)[0]}"
        root = records.get(root_ref)
        if root is None:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group raw reading-order root is unavailable"
            )
        slots = _literal_slots(root, "children")
        candidates = [
            (root_ref, normalized_target_ref, index, index + 1)
            for index, (source_ref, target_ref) in enumerate(
                zip(slots, slots[1:], strict=False)
            )
            if (
                source_ref == normalized_owner_ref
                and target_ref == normalized_target_ref
            )
        ]
        if len(candidates) != 1:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group raw reading-order slot binding differs"
            )
        return candidates[0]

    candidates: list[tuple[str, str, int, int | None]] = []
    normalized_owner = records.get(normalized_owner_ref)
    if normalized_owner is not None:
        try:
            slots = _literal_slots(normalized_owner, field)
        except ValueError:
            slots = ()
        candidates.extend(
            (normalized_owner_ref, normalized_target_ref, index, None)
            for index, value in enumerate(slots)
            if value == normalized_target_ref
        )

    # Parent edges are normalized as parent->child contains relationships even
    # though the literal raw field is child.parent -> parent.
    normalized_target = records.get(normalized_target_ref)
    if normalized_target is not None and field == "parent":
        try:
            slots = _literal_slots(normalized_target, field)
        except ValueError:
            slots = ()
        candidates.extend(
            (normalized_target_ref, normalized_owner_ref, index, None)
            for index, value in enumerate(slots)
            if value == normalized_owner_ref
        )
    if len(candidates) != 1:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group raw owner/field/slot binding differs"
        )
    return candidates[0]


def capture_opaque_group_edges(
    ir: DocumentIR,
    raw_graph: Mapping[str, Any],
    *,
    target_element_ids: frozenset[str] | None = None,
    deadline: float | None = None,
) -> DetachedOpaqueGroupEdges:
    """Capture exact group-edge custody without copying the complete IR."""

    elements = {element.id: element for element in ir.elements}
    if (
        target_element_ids is not None
        and (
            type(target_element_ids) is not frozenset
            or len(target_element_ids) > MAX_RECORDS
            or any(
                type(element_id) is not str or not element_id
                for element_id in target_element_ids
            )
            or not target_element_ids <= set(elements)
        )
    ):
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group custody target scope differs"
        )
    original_relationship_ids = tuple(
        relationship.id for relationship in ir.relationships
    )
    detached: list[tuple[int, RelationshipRecord]] = []
    for original_index, relationship in enumerate(ir.relationships):
        _check_deadline(deadline)
        metadata = relationship.metadata
        owner_ref = metadata.get("source_ref")
        target_ref = metadata.get("target_ref")
        if (
            metadata.get("normalization_origin")
            != "docling_reference_graph"
            or not isinstance(owner_ref, str)
            or not isinstance(target_ref, str)
            or _RAW_REF_RE.fullmatch(owner_ref) is None
            or _RAW_REF_RE.fullmatch(target_ref) is None
            or not (
                owner_ref.startswith(_GROUP_PREFIX)
                or target_ref.startswith(_GROUP_PREFIX)
            )
        ):
            continue
        detached.append((original_index, relationship.model_copy(deep=True)))
    if len(detached) > MAX_RECORDS:
        raise OpaqueGroupCustodyResourceError(
            "opaque group custody relationship count exceeds its cap"
        )
    if target_element_ids is not None:
        incident: dict[str, list[int]] = {}
        for detached_offset, (_original_index, relationship) in enumerate(detached):
            incident.setdefault(relationship.source_id, []).append(detached_offset)
            incident.setdefault(relationship.target_id, []).append(detached_offset)
        reached = set(target_element_ids)
        selected_offsets: set[int] = set()
        queue = list(sorted(target_element_ids))
        queue_offset = 0
        while queue_offset < len(queue):
            _check_deadline(deadline)
            element_id = queue[queue_offset]
            queue_offset += 1
            for detached_offset in incident.get(element_id, ()):
                if detached_offset in selected_offsets:
                    continue
                selected_offsets.add(detached_offset)
                relationship = detached[detached_offset][1]
                for endpoint_id in (
                    relationship.source_id,
                    relationship.target_id,
                ):
                    if endpoint_id not in reached:
                        reached.add(endpoint_id)
                        queue.append(endpoint_id)
        detached = [
            value
            for detached_offset, value in enumerate(detached)
            if detached_offset in selected_offsets
        ]
    for _original_index, relationship in detached:
        _check_deadline(deadline)
        if _opaque_group_descriptor(relationship, elements) is None:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group selected relationship differs"
            )
        field = relationship.metadata.get("field")
        if not isinstance(field, str) or not field:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group relationship metadata differs"
            )
        # A normalized edge may represent more than one literal assertion
        # (duplicate children slots and reciprocal child.parent are both
        # legitimate diagnostics).  Selection freezes the complete connected
        # component before semantic prohibitions are applied.
        if relationship.type.value == "alternative_of":
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group alternative cannot be isolated after reconciliation"
            )
    required_raw_refs = {
        value
        for _index, relationship in detached
        for value in (
            relationship.metadata.get("source_ref"),
            relationship.metadata.get("target_ref"),
        )
        if isinstance(value, str) and _RAW_REF_RE.fullmatch(value) is not None
    }
    raw_closure = _capture_relevant_raw_closure(
        raw_graph,
        required_raw_refs=(
            required_raw_refs if target_element_ids is not None else None
        ),
        deadline=deadline,
    )
    return DetachedOpaqueGroupEdges(
        original_relationship_ids=original_relationship_ids,
        detached=tuple(detached),
        raw_closure=raw_closure,
    )


def detach_opaque_group_edges(
    ir: DocumentIR,
    raw_graph: Mapping[str, Any],
    *,
    deadline: float | None = None,
) -> tuple[DocumentIR, DetachedOpaqueGroupEdges]:
    """Remove raw-created group edges before layout-only semantic consumers."""

    from app.services.ir import DocumentIR

    custody = capture_opaque_group_edges(ir, raw_graph, deadline=deadline)
    detached_ids = {
        relationship.id for _index, relationship in custody.detached
    }
    working = ir.model_copy(deep=True)
    working.relationships = [
        relationship
        for relationship in working.relationships
        if relationship.id not in detached_ids
    ]
    return DocumentIR.model_validate(working.model_dump(mode="json")), custody


def restore_diagnostic_group_edges(
    ir: DocumentIR,
    custody: DetachedOpaqueGroupEdges,
    *,
    deadline: float | None = None,
) -> DocumentIR:
    """Restore original relationship bytes/order before runtime custody."""

    from app.services.ir import DocumentIR

    if not custody.detached:
        return ir
    working = ir.model_copy(deep=True)
    known_ids = {element.id for element in working.elements}
    detached_by_id = {
        original.id: original
        for _original_index, original in custody.detached
    }
    current_by_id = {relationship.id: relationship for relationship in working.relationships}
    original_id_set = set(custody.original_relationship_ids)
    original_relationships: list[RelationshipRecord] = []
    for relationship_id in custody.original_relationship_ids:
        _check_deadline(deadline)
        original = detached_by_id.get(relationship_id)
        relationship = (
            original.model_copy(deep=True)
            if original is not None
            else current_by_id.get(relationship_id)
        )
        if relationship is None:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group predecessor relationship is unavailable"
            )
        if (
            relationship.source_id not in known_ids
            or relationship.target_id not in known_ids
        ):
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group diagnostic endpoint is unavailable"
            )
        original_relationships.append(relationship)
    overlays = [
        relationship
        for relationship in working.relationships
        if relationship.id not in original_id_set
    ]
    working.relationships = [*original_relationships, *overlays]
    _check_deadline(deadline)
    restored = DocumentIR.model_validate(working.model_dump(mode="json"))
    _check_deadline(deadline)
    restored_by_id = {relationship.id: relationship for relationship in restored.relationships}
    if any(
        restored_by_id[original.id].model_dump(mode="json")
        != original.model_dump(mode="json")
        for _original_index, original in custody.detached
    ):
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group relationship restoration differs"
        )
    if tuple(
        relationship.id for relationship in restored.relationships[: len(original_id_set)]
    ) != custody.original_relationship_ids:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group relationship order restoration differs"
        )
    return restored


def _project_records_legacy(
    ir: DocumentIR,
    raw_graph: Mapping[str, Any],
    *,
    deadline: float | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    elements = {element.id: element for element in ir.elements}
    pages = {page.id: page for page in ir.pages}
    raw_records = _raw_reference_records(raw_graph, deadline=deadline)
    raw_owner_rank = {raw_ref: index for index, raw_ref in enumerate(raw_records)}
    elements_by_ref: dict[str, ElementRecord] = {}
    for element in ir.elements:
        _check_deadline(deadline)
        for raw_ref in _raw_refs(element):
            if raw_ref in elements_by_ref and elements_by_ref[raw_ref].id != element.id:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group raw endpoint identity repeats"
                )
            elements_by_ref[raw_ref] = element
    relationships_by_edge: dict[tuple[str, str, str], RelationshipRecord] = {}
    for relationship in ir.relationships:
        edge = (
            relationship.type.value,
            relationship.source_id,
            relationship.target_id,
        )
        if edge in relationships_by_edge:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group normalized edge repeats"
            )
        relationships_by_edge[edge] = relationship
    records: list[dict[str, Any]] = []
    relationship_ids: set[str] = set()
    relationship_occurrences: dict[str, int] = {}
    relationship_digest_cache: dict[str, str] = {}
    content_cache: dict[str, tuple[str, int]] = {}
    content_aggregate_bytes = 0
    records_aggregate_bytes = 0

    def content_digest(element: ElementRecord) -> str:
        nonlocal content_aggregate_bytes
        cached = content_cache.get(element.id)
        if cached is None:
            cached = _member_content_digest_and_size(
                element,
                deadline=deadline,
            )
            content_aggregate_bytes += cached[1]
            if content_aggregate_bytes > MAX_CONTENT_DOCUMENT_BYTES:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group custody content exceeds its document byte cap"
                )
            content_cache[element.id] = cached
        return cached[0]

    def content_claim(
        element: ElementRecord,
    ) -> tuple[str, str, str | None]:
        if (
            element.type in {"group", "list"}
            and element.presentation_role == "subordinate"
            and element.properties.get("normalization_origin")
            == "docling_reference_graph"
        ):
            if element.value is not None or element.markdown is not None:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group semantic content differs"
                )
            digest = empty_group_content_sha256(element.type)
            if digest != content_digest(element):
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group semantic digest differs"
                )
            return element.type, "opaque_group_empty", digest
        if (
            element.presentation_role == "subordinate"
            and element.properties.get("normalization_origin")
            == "docling_reference_graph"
            and "legacy_item" not in element.properties
        ):
            # A non-group endpoint has semantic content that cannot be
            # independently rebound at the public ParseResult boundary.  Do
            # not emit an unverifiable digest/basis: the caller must atomically
            # retain the exact P03 predecessor instead.
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group raw-only semantic endpoint is unavailable"
            )
        return element.type, "public_ir", content_digest(element)

    def add_assertion_record(
        *,
        owner_ref: str,
        literal_target_ref: str,
        field: str,
        slot: int,
        target_slot: int | None,
        relationship_type: str,
        source_ref: str,
        target_ref: str,
        normalization_outcome: str,
        relationship: RelationshipRecord,
        raw_assertion_value: Any,
    ) -> None:
        nonlocal records_aggregate_bytes
        if len(records) >= MAX_RECORDS:
            raise OpaqueGroupCustodyResourceError(
                "opaque group custody record cap exceeded"
            )
        owner = elements_by_ref.get(owner_ref)
        literal_target = elements_by_ref.get(literal_target_ref)
        source = elements_by_ref.get(source_ref)
        target = elements_by_ref.get(target_ref)
        if literal_target is None or source is None or target is None:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group literal endpoint is unavailable"
            )
        group_refs = [
            raw_ref
            for raw_ref in (source_ref, target_ref)
            if raw_ref.startswith(_GROUP_PREFIX)
        ]
        if not group_refs:
            return
        group_ref = group_refs[0]
        group = elements_by_ref.get(group_ref)
        if group is None or group.type not in {"group", "list"}:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group endpoint type differs"
            )
        counterpart_ref = target_ref if group_ref == source_ref else source_ref
        counterpart = elements_by_ref.get(counterpart_ref)
        if counterpart is None or counterpart.id == group.id:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group counterpart binding differs"
            )
        if owner_ref not in {"#/body", "#/furniture"} and owner is None:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group literal owner is unavailable"
            )
        normalized_field = relationship.metadata.get("field")
        if not isinstance(normalized_field, str) or not normalized_field:
            normalized_field = field
        expected_relationship_id = stable_id(
            "rel",
            relationship_type,
            relationship.source_id,
            relationship.target_id,
            normalized_field,
        )
        if relationship.id != expected_relationship_id:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group relationship identity differs"
            )
        page = pages.get(counterpart.page_id)
        if page is None:
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group owner page is unavailable"
            )
        member_type, member_basis, member_digest = content_claim(literal_target)
        (
            counterpart_type,
            counterpart_basis,
            counterpart_digest,
        ) = content_claim(counterpart)
        raw_assertion_sha256, _raw_assertion_bytes = _json_digest_and_size(
            {
                "field": field,
                "owner_raw_ref": owner_ref,
                "raw_slot_index": slot,
                "raw_target_slot_index": target_slot,
                "value": raw_assertion_value,
            },
            maximum_bytes=MAX_CONTENT_ITEM_BYTES,
            deadline=deadline,
        )
        normalized_relationship_sha256 = relationship_digest_cache.get(
            relationship.id
        )
        if normalized_relationship_sha256 is None:
            (
                normalized_relationship_sha256,
                _normalized_relationship_bytes,
            ) = _json_digest_and_size(
                relationship.model_dump(mode="json"),
                maximum_bytes=MAX_CONTENT_ITEM_BYTES,
                deadline=deadline,
            )
            relationship_digest_cache[relationship.id] = (
                normalized_relationship_sha256
            )
        record: dict[str, Any] = {
            "page_index": page.page_index,
            "owner_order": raw_owner_rank[owner_ref],
            "edge_kind": (
                "root_reading_order"
                if owner_ref in {"#/body", "#/furniture"}
                else "group_membership"
                if owner_ref == group_ref and field == "children"
                else "group_reference"
            ),
            "owner_element_id": owner.id if owner is not None else None,
            "owner_raw_ref": owner_ref,
            "raw_slot_index": slot,
            "raw_target_slot_index": target_slot,
            "raw_assertion_sha256": raw_assertion_sha256,
            "member_element_id": literal_target.id,
            "member_raw_ref": literal_target_ref,
            "member_type": member_type,
            "member_content_basis": member_basis,
            "member_content_sha256": member_digest,
            "group_element_id": group.id,
            "group_raw_ref": group_ref,
            "group_type": group.type,
            "counterpart_element_id": counterpart.id,
            "counterpart_raw_ref": counterpart_ref,
            "counterpart_type": counterpart_type,
            "counterpart_content_basis": counterpart_basis,
            "counterpart_content_sha256": counterpart_digest,
            "relationship_id": relationship.id,
            "relationship_type": relationship_type,
            "relationship_field": field,
            "normalized_relationship_field": normalized_field,
            "normalization_outcome": normalization_outcome,
            "normalized_relationship_sha256": normalized_relationship_sha256,
            "normalized_evidence_count": len(relationship.evidence_ids),
            "source_element_id": relationship.source_id,
            "target_element_id": relationship.target_id,
            "source_raw_ref": source_ref,
            "target_raw_ref": target_ref,
        }
        records.append(record)
        relationship_ids.add(relationship.id)
        relationship_occurrences[relationship.id] = (
            relationship_occurrences.get(relationship.id, 0) + 1
        )

    for owner_ref, raw_owner in raw_records.items():
        _check_deadline(deadline)
        if owner_ref in {"#/body", "#/furniture"}:
            continue
        for field, (base_type, child_is_source) in _RAW_RELATION_FIELDS.items():
            if field not in raw_owner:
                continue
            raw_values = raw_owner.get(field)
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            for slot, raw_value in enumerate(values):
                _check_deadline(deadline)
                literal_target_ref = _raw_reference(raw_value)
                if not literal_target_ref:
                    if owner_ref.startswith(_GROUP_PREFIX):
                        raise OpaqueGroupCustodyIntegrityError(
                            "opaque group raw assertion is malformed"
                        )
                    continue
                if not (
                    owner_ref.startswith(_GROUP_PREFIX)
                    or literal_target_ref.startswith(_GROUP_PREFIX)
                ):
                    continue
                owner = elements_by_ref.get(owner_ref)
                literal_target = elements_by_ref.get(literal_target_ref)
                if owner is None or literal_target is None:
                    raise OpaqueGroupCustodyIntegrityError(
                        "opaque group raw assertion is unresolved"
                    )
                relationship_type = base_type
                assertion_child_is_source = child_is_source
                if field == "children":
                    target_label = str(
                        (raw_records.get(literal_target_ref) or {}).get("label") or ""
                    ).casefold()
                    if "caption" in target_label:
                        relationship_type, assertion_child_is_source = (
                            "caption_of",
                            True,
                        )
                    elif "footnote" in target_label:
                        relationship_type, assertion_child_is_source = (
                            "footnote_of",
                            True,
                        )
                    elif "source" in target_label and "note" in target_label:
                        relationship_type, assertion_child_is_source = (
                            "source_note_of",
                            True,
                        )
                source_ref, target_ref = (
                    (literal_target_ref, owner_ref)
                    if assertion_child_is_source
                    else (owner_ref, literal_target_ref)
                )
                source = elements_by_ref[source_ref]
                target = elements_by_ref[target_ref]
                relationship = relationships_by_edge.get(
                    (relationship_type, source.id, target.id)
                )
                if relationship is None:
                    raise OpaqueGroupCustodyIntegrityError(
                        "opaque group raw assertion was not normalized"
                    )
                exact_metadata = (
                    relationship.metadata.get("normalization_origin")
                    == "docling_reference_graph"
                    and relationship.metadata.get("source_ref") == owner_ref
                    and relationship.metadata.get("target_ref")
                    == literal_target_ref
                    and relationship.metadata.get("field") == field
                )
                occurrence_count = relationship_occurrences.get(
                    relationship.id, 0
                )
                add_assertion_record(
                    owner_ref=owner_ref,
                    literal_target_ref=literal_target_ref,
                    field=field,
                    slot=slot,
                    target_slot=None,
                    relationship_type=relationship_type,
                    source_ref=source_ref,
                    target_ref=target_ref,
                    normalization_outcome=(
                        "normalized_edge"
                        if exact_metadata and occurrence_count == 0
                        else "merged_edge"
                    ),
                    relationship=relationship,
                    raw_assertion_value=raw_value,
                )

        parent_ref = _raw_reference(raw_owner.get("parent"))
        if parent_ref in {"#/body", "#/furniture"}:
            # Docling root-container parent declarations carry placement, not
            # a semantic group edge.  P01 retains them through root reading
            # order; custody must not reinterpret them as inverse contains.
            continue
        if parent_ref and (
            owner_ref.startswith(_GROUP_PREFIX)
            or parent_ref.startswith(_GROUP_PREFIX)
        ):
            owner = elements_by_ref.get(owner_ref)
            parent = elements_by_ref.get(parent_ref)
            if owner is None or parent is None:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group inverse parent assertion is unresolved"
                )
            relationship = relationships_by_edge.get(
                ("contains", parent.id, owner.id)
            )
            if relationship is None:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group inverse parent assertion was not normalized"
                )
            occurrence_count = relationship_occurrences.get(relationship.id, 0)
            add_assertion_record(
                owner_ref=owner_ref,
                literal_target_ref=parent_ref,
                field="parent",
                slot=0,
                target_slot=None,
                relationship_type="contains",
                source_ref=parent_ref,
                target_ref=owner_ref,
                normalization_outcome=(
                    "normalized_edge"
                    if relationship.metadata.get("field") == "parent"
                    and occurrence_count == 0
                    else "merged_edge"
                ),
                relationship=relationship,
                raw_assertion_value=raw_owner.get("parent"),
            )

    for root_ref in ("#/body", "#/furniture"):
        root = raw_records.get(root_ref)
        if root is None:
            continue
        slots = tuple(
            _raw_reference(value)
            for value in (
                root.get("children")
                if isinstance(root.get("children"), list)
                else [root.get("children")]
            )
        )
        if any(not value for value in slots):
            if any(value.startswith(_GROUP_PREFIX) for value in slots if value):
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group root assertion is malformed"
                )
            continue
        for slot, (source_ref, target_ref) in enumerate(
            zip(slots, slots[1:], strict=False)
        ):
            if not (
                source_ref.startswith(_GROUP_PREFIX)
                or target_ref.startswith(_GROUP_PREFIX)
            ):
                continue
            source = elements_by_ref.get(source_ref)
            target = elements_by_ref.get(target_ref)
            if source is None or target is None:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group root assertion is unresolved"
                )
            relationship = relationships_by_edge.get(
                ("reading_before", source.id, target.id)
            )
            if relationship is None:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group root assertion was not normalized"
                )
            add_assertion_record(
                owner_ref=root_ref,
                literal_target_ref=target_ref,
                field=f"{root_ref[2:]}.children.reading_order",
                slot=slot,
                target_slot=slot + 1,
                relationship_type="reading_before",
                source_ref=source_ref,
                target_ref=target_ref,
                normalization_outcome="root_reading_order",
                relationship=relationship,
                raw_assertion_value={
                    "source": root.get("children")[slot],
                    "target": root.get("children")[slot + 1],
                },
            )

    records.sort(
        key=lambda value: (
            value["owner_order"],
            value["relationship_field"],
            value["raw_slot_index"],
            value["raw_target_slot_index"]
            if value["raw_target_slot_index"] is not None
            else -1,
            value["relationship_id"],
        )
    )
    normalized_assertion_counts: dict[str, int] = {}
    for record in records:
        relationship_id = record["relationship_id"]
        normalized_assertion_counts[relationship_id] = (
            normalized_assertion_counts.get(relationship_id, 0) + 1
        )
    for order, record in enumerate(records):
        record["normalized_assertion_count"] = (
            normalized_assertion_counts[record["relationship_id"]]
        )
        record["record_order"] = order
        record["record_id"] = record_id(record, ir.source_sha256)
        _record_digest, record_bytes = _json_digest_and_size(
            record,
            maximum_bytes=MAX_CONTENT_ITEM_BYTES,
            deadline=deadline,
        )
        records_aggregate_bytes += record_bytes
        if records_aggregate_bytes > MAX_CONTENT_DOCUMENT_BYTES:
            raise OpaqueGroupCustodyResourceError(
                "opaque group custody exceeds its document byte cap"
            )
    expected_relationship_ids = {
        relationship.id
        for relationship in ir.relationships
        if _opaque_group_descriptor(relationship, elements) is not None
    }
    if relationship_ids != expected_relationship_ids:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group literal/normalized relationship coverage differs"
        )
    return records, relationship_ids


def _project_records(
    ir: DocumentIR,
    raw_closure: FrozenRelevantRawClosure | Mapping[str, Any],
    *,
    deadline: float | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Project exact diagnostic records from the owned compact closure."""

    try:
        elements = {element.id: element for element in ir.elements}
        pages = {page.id: page for page in ir.pages}
        elements_by_ref: dict[str, ElementRecord] = {}
        refs_by_element: dict[str, set[str]] = {}
        for element in ir.elements:
            _check_deadline(deadline)
            for raw_ref in _raw_refs(element):
                prior = elements_by_ref.get(raw_ref)
                if prior is not None and prior.id != element.id:
                    raise OpaqueGroupCustodyIntegrityError(
                        "opaque group raw endpoint identity repeats"
                    )
                elements_by_ref[raw_ref] = element
                refs_by_element.setdefault(element.id, set()).add(raw_ref)
        if isinstance(raw_closure, FrozenRelevantRawClosure):
            frozen = raw_closure
        else:
            required_refs = {
                raw_ref
                for relationship in ir.relationships
                if relationship.metadata.get("normalization_origin")
                == "docling_reference_graph"
                for raw_ref in (
                    relationship.metadata.get("source_ref"),
                    relationship.metadata.get("target_ref"),
                )
                if isinstance(raw_ref, str)
                and (
                    raw_ref.startswith(_GROUP_PREFIX)
                    or any(
                        value.startswith(_GROUP_PREFIX)
                        for value in (
                            relationship.metadata.get("source_ref", ""),
                            relationship.metadata.get("target_ref", ""),
                        )
                        if isinstance(value, str)
                    )
                )
            }
            frozen = _capture_relevant_raw_closure(
                raw_closure,
                required_raw_refs=required_refs,
                deadline=deadline,
            )

        definition_refs = {value.raw_ref for value in frozen.definitions}
        if any(raw_ref not in elements_by_ref for raw_ref in definition_refs):
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group relevant endpoint is unavailable"
            )

        relationships_by_edge: dict[
            tuple[str, str, str], RelationshipRecord
        ] = {}
        for relationship in ir.relationships:
            edge = (
                relationship.type.value,
                relationship.source_id,
                relationship.target_id,
            )
            if edge in relationships_by_edge:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group normalized edge repeats"
                )
            relationships_by_edge[edge] = relationship

        # Component pages are grounded only by public IR elements.  Empty raw
        # group nodes inherit a page through their connected public endpoint;
        # unanchored or multi-page components fail closed.
        parent: dict[str, str] = {raw_ref: raw_ref for raw_ref in definition_refs}

        def find(raw_ref: str) -> str:
            root = raw_ref
            while parent[root] != root:
                root = parent[root]
            while parent[raw_ref] != raw_ref:
                next_ref = parent[raw_ref]
                parent[raw_ref] = root
                raw_ref = next_ref
            return root

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for assertion in frozen.assertions:
            union(assertion.source_raw_ref, assertion.target_raw_ref)

        component_pages: dict[str, set[int]] = {}
        for raw_ref in definition_refs:
            element = elements_by_ref[raw_ref]
            if "legacy_item" not in element.properties:
                continue
            page = pages.get(element.page_id)
            if page is None:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group public endpoint page is unavailable"
                )
            component_pages.setdefault(find(raw_ref), set()).add(page.page_index)
        component_page: dict[str, int] = {}
        group_components = {
            find(raw_ref)
            for raw_ref in definition_refs
            if raw_ref.startswith(_GROUP_PREFIX)
        }
        for component in group_components:
            page_indexes = component_pages.get(component, set())
            if len(page_indexes) != 1:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group component page anchor differs"
                )
            component_page[component] = next(iter(page_indexes))

        content_cache: dict[str, tuple[str, int]] = {}
        content_aggregate_bytes = 0

        def content_digest(element: ElementRecord) -> str:
            nonlocal content_aggregate_bytes
            cached = content_cache.get(element.id)
            if cached is None:
                cached = _member_content_digest_and_size(
                    element,
                    deadline=deadline,
                )
                content_aggregate_bytes += cached[1]
                if content_aggregate_bytes > MAX_CONTENT_DOCUMENT_BYTES:
                    raise OpaqueGroupCustodyResourceError(
                        "opaque group custody content exceeds its document byte cap"
                    )
                content_cache[element.id] = cached
            return cached[0]

        def content_claim(
            element: ElementRecord,
        ) -> tuple[str, str, str]:
            if "legacy_item" in element.properties:
                return element.type, "public_ir", content_digest(element)
            if (
                element.type in {"group", "list"}
                and element.presentation_role == "subordinate"
                and element.properties.get("normalization_origin")
                == "docling_reference_graph"
                and element.value is None
                and element.markdown is None
            ):
                digest = empty_group_content_sha256(element.type)
                if digest != content_digest(element):
                    raise OpaqueGroupCustodyIntegrityError(
                        "opaque group semantic digest differs"
                    )
                return element.type, "opaque_group_empty", digest
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group raw-only semantic endpoint is unavailable"
            )

        records: list[dict[str, Any]] = []
        relationship_ids: set[str] = set()
        relationship_occurrences: dict[str, int] = {}
        relationship_digest_cache: dict[str, str] = {}
        records_aggregate_bytes = 0
        for assertion in frozen.assertions:
            _check_deadline(deadline)
            if len(records) >= MAX_RECORDS:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group custody record cap exceeded"
                )
            source = elements_by_ref.get(assertion.source_raw_ref)
            target = elements_by_ref.get(assertion.target_raw_ref)
            literal_target = elements_by_ref.get(
                assertion.literal_target_raw_ref
            )
            owner = elements_by_ref.get(assertion.owner_raw_ref)
            if source is None or target is None or literal_target is None:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group literal endpoint is unavailable"
                )
            if (
                assertion.owner_raw_ref not in {"#/body", "#/furniture"}
                and owner is None
            ):
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group literal owner is unavailable"
                )
            group_refs = [
                raw_ref
                for raw_ref in (
                    assertion.source_raw_ref,
                    assertion.target_raw_ref,
                )
                if raw_ref.startswith(_GROUP_PREFIX)
            ]
            if not group_refs:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group assertion lost its group endpoint"
                )
            group_ref = group_refs[0]
            group = elements_by_ref[group_ref]
            if group.type not in {"group", "list"}:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group endpoint type differs"
                )
            counterpart_ref = (
                assertion.target_raw_ref
                if group_ref == assertion.source_raw_ref
                else assertion.source_raw_ref
            )
            counterpart = elements_by_ref[counterpart_ref]
            relationship = relationships_by_edge.get(
                (
                    assertion.relationship_type,
                    source.id,
                    target.id,
                )
            )
            if relationship is None:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group raw assertion was not normalized"
                )
            normalized_field = relationship.metadata.get("field")
            if not isinstance(normalized_field, str) or not normalized_field:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group normalized relationship field differs"
                )
            expected_relationship_id = stable_id(
                "rel",
                assertion.relationship_type,
                source.id,
                target.id,
                normalized_field,
            )
            if relationship.id != expected_relationship_id:
                raise OpaqueGroupCustodyIntegrityError(
                    "opaque group relationship identity differs"
                )
            exact_metadata = (
                relationship.metadata.get("normalization_origin")
                == "docling_reference_graph"
                and relationship.metadata.get("source_ref")
                == (
                    assertion.source_raw_ref
                    if assertion.relationship_field == "parent"
                    else assertion.owner_raw_ref
                )
                and relationship.metadata.get("target_ref")
                == (
                    assertion.target_raw_ref
                    if assertion.relationship_field == "parent"
                    else assertion.literal_target_raw_ref
                )
                and normalized_field == assertion.relationship_field
            )
            occurrence_count = relationship_occurrences.get(relationship.id, 0)
            normalization_outcome = (
                "root_reading_order"
                if assertion.owner_raw_ref in {"#/body", "#/furniture"}
                else "normalized_edge"
                if exact_metadata and occurrence_count == 0
                else "merged_edge"
            )
            normalized_relationship_sha256 = relationship_digest_cache.get(
                relationship.id
            )
            if normalized_relationship_sha256 is None:
                normalized_relationship_sha256, _relationship_bytes = (
                    _json_digest_and_size(
                        relationship.model_dump(mode="json"),
                        maximum_bytes=MAX_CONTENT_ITEM_BYTES,
                        deadline=deadline,
                    )
                )
                relationship_digest_cache[relationship.id] = (
                    normalized_relationship_sha256
                )
            member_type, member_basis, member_digest = content_claim(
                literal_target
            )
            counterpart_type, counterpart_basis, counterpart_digest = (
                content_claim(counterpart)
            )
            source_type, source_basis, source_digest = content_claim(source)
            target_type, target_basis, target_digest = content_claim(target)
            page_index = component_page[find(group_ref)]
            record: dict[str, Any] = {
                "page_index": page_index,
                "owner_order": assertion.owner_order,
                "edge_kind": (
                    "root_reading_order"
                    if assertion.owner_raw_ref in {"#/body", "#/furniture"}
                    else "group_membership"
                    if (
                        assertion.owner_raw_ref == group_ref
                        and assertion.relationship_field == "children"
                    )
                    else "group_reference"
                ),
                "owner_element_id": owner.id if owner is not None else None,
                "owner_raw_ref": assertion.owner_raw_ref,
                "raw_slot_index": assertion.raw_slot_index,
                "raw_target_slot_index": assertion.raw_target_slot_index,
                "raw_assertion_sha256": assertion.raw_assertion_sha256,
                "member_element_id": literal_target.id,
                "member_raw_ref": assertion.literal_target_raw_ref,
                "member_type": member_type,
                "member_content_basis": member_basis,
                "member_content_sha256": member_digest,
                "group_element_id": group.id,
                "group_raw_ref": group_ref,
                "group_type": group.type,
                "counterpart_element_id": counterpart.id,
                "counterpart_raw_ref": counterpart_ref,
                "counterpart_type": counterpart_type,
                "counterpart_content_basis": counterpart_basis,
                "counterpart_content_sha256": counterpart_digest,
                "relationship_id": relationship.id,
                "relationship_type": assertion.relationship_type,
                "relationship_field": assertion.relationship_field,
                "normalized_relationship_field": normalized_field,
                "normalization_outcome": normalization_outcome,
                "normalized_relationship_sha256": (
                    normalized_relationship_sha256
                ),
                "normalized_evidence_count": len(relationship.evidence_ids),
                "source_element_id": source.id,
                "source_raw_ref": assertion.source_raw_ref,
                "source_type": source_type,
                "source_content_basis": source_basis,
                "source_content_sha256": source_digest,
                "target_element_id": target.id,
                "target_raw_ref": assertion.target_raw_ref,
                "target_type": target_type,
                "target_content_basis": target_basis,
                "target_content_sha256": target_digest,
            }
            records.append(record)
            relationship_ids.add(relationship.id)
            relationship_occurrences[relationship.id] = occurrence_count + 1

        records.sort(
            key=lambda value: (
                value["owner_order"],
                value["relationship_field"],
                value["raw_slot_index"],
                value["raw_target_slot_index"]
                if value["raw_target_slot_index"] is not None
                else -1,
                value["relationship_id"],
            )
        )
        normalized_assertion_counts: dict[str, int] = {}
        for record in records:
            relationship_id = record["relationship_id"]
            normalized_assertion_counts[relationship_id] = (
                normalized_assertion_counts.get(relationship_id, 0) + 1
            )
        for record_order, record in enumerate(records):
            record["normalized_assertion_count"] = (
                normalized_assertion_counts[record["relationship_id"]]
            )
            record["record_order"] = record_order
            record["record_id"] = record_id(record, ir.source_sha256)
            _record_digest, record_bytes = _json_digest_and_size(
                record,
                maximum_bytes=MAX_CONTENT_ITEM_BYTES,
                deadline=deadline,
            )
            records_aggregate_bytes += record_bytes
            if records_aggregate_bytes > MAX_CONTENT_DOCUMENT_BYTES:
                raise OpaqueGroupCustodyResourceError(
                    "opaque group custody exceeds its document byte cap"
                )
        return records, relationship_ids
    except (
        OpaqueGroupCustodyIntegrityError,
        OpaqueGroupCustodyResourceError,
        OpaqueGroupCustodyTimeoutError,
    ):
        raise
    except MemoryError as exc:
        raise OpaqueGroupCustodyResourceError(
            "opaque group custody projection exhausted resources"
        ) from exc
    except (
        KeyError,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group custody projection is invalid"
        ) from exc


def _assert_frozen_relationship_closure(
    ir: DocumentIR,
    custody: DetachedOpaqueGroupEdges,
    *,
    deadline: float | None = None,
) -> None:
    """Close the final raw-origin relationship bytes against capture time."""

    frozen = [relationship for _index, relationship in custody.detached]
    frozen_ids = {relationship.id for relationship in frozen}
    if len(frozen_ids) != len(frozen):
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group frozen relationship identity repeats"
        )
    current = [
        relationship
        for relationship in ir.relationships
        if relationship.id in frozen_ids
    ]
    if [relationship.id for relationship in current] != [
        relationship.id for relationship in frozen
    ]:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group frozen relationship topology differs"
        )
    for current_relationship, frozen_relationship in zip(
        current,
        frozen,
        strict=True,
    ):
        _check_deadline(deadline)
        if current_relationship.model_dump(
            mode="json"
        ) != frozen_relationship.model_dump(mode="json"):
            raise OpaqueGroupCustodyIntegrityError(
                "opaque group frozen relationship content differs"
            )


def seal_diagnostic_custody(
    document: Mapping[str, Any],
    ir: DocumentIR,
    *,
    raw_graph: Mapping[str, Any] | None = None,
    detached_custody: DetachedOpaqueGroupEdges | None = None,
    deadline: float | None = None,
) -> tuple[CanonicalSourceCustody, tuple[str, ...]]:
    """Seal an exact diagnostic sidecar without mutating any caller input."""

    marker_bytes = _capture_table_marker_bytes(document, deadline=deadline)
    _check_deadline(deadline)
    if detached_custody is None:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group raw closure was not frozen"
        )
    raw_graph = raw_graph or {}
    required_raw_refs = {
        value.raw_ref for value in detached_custody.raw_closure.definitions
    }
    live_closure = _capture_relevant_raw_closure(
        raw_graph,
        required_raw_refs=required_raw_refs,
        deadline=deadline,
    )
    if live_closure != detached_custody.raw_closure:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group raw closure changed after capture"
        )
    _assert_frozen_relationship_closure(
        ir,
        detached_custody,
        deadline=deadline,
    )
    records, relationship_ids = _project_records(
        ir,
        detached_custody.raw_closure,
        deadline=deadline,
    )
    # Close the capture again after projection.  Callback-bearing Mapping
    # adapters cannot mutate live raw data or final IR during the projection
    # window and still commit a candidate.
    final_closure = _capture_relevant_raw_closure(
        raw_graph,
        required_raw_refs=required_raw_refs,
        deadline=deadline,
    )
    if final_closure != detached_custody.raw_closure:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group raw closure changed during projection"
        )
    _assert_frozen_relationship_closure(
        ir,
        detached_custody,
        deadline=deadline,
    )
    _check_deadline(deadline)
    raw_sidecar = {
        "policy_id": POLICY_ID,
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "source_sha256": ir.source_sha256,
        "record_count": len(records),
        "records_sha256": records_sha256(records, deadline=deadline),
        "records": records,
    }
    remaining_bytes = MAX_CONTENT_DOCUMENT_BYTES - marker_bytes
    _sidecar_digest, _sidecar_size = _json_digest_and_size(
        raw_sidecar,
        maximum_bytes=remaining_bytes,
        deadline=deadline,
    )
    # Validation closes the generated schema and enforces the same inclusive
    # resource limits used at the public model boundary.
    from app.models import CanonicalSourceCustody

    try:
        sidecar = CanonicalSourceCustody.model_validate(raw_sidecar)
    except (TypeError, ValueError) as exc:
        raise OpaqueGroupCustodyIntegrityError(
            "generated canonical source custody is invalid"
        ) from exc
    frozen_relationship_ids = {
        relationship.id for _index, relationship in detached_custody.detached
    }
    sidecar_relationship_ids = {
        record.relationship_id for record in sidecar.records
    }
    if (
        type(relationship_ids) is not set
        or any(type(value) is not str or not value for value in relationship_ids)
        or relationship_ids != sidecar_relationship_ids
        or relationship_ids != frozen_relationship_ids
    ):
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group custody relationship identity closure differs"
        )
    post_validation_closure = _capture_relevant_raw_closure(
        raw_graph,
        required_raw_refs=required_raw_refs,
        deadline=deadline,
    )
    if post_validation_closure != detached_custody.raw_closure:
        raise OpaqueGroupCustodyIntegrityError(
            "opaque group raw closure changed during sidecar validation"
        )
    _assert_frozen_relationship_closure(
        ir,
        detached_custody,
        deadline=deadline,
    )
    _check_deadline(deadline)
    return sidecar, tuple(sorted(relationship_ids))
