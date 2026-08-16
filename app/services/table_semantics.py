from app.services.tables import RawTable
from collections import defaultdict
from copy import deepcopy
from csv import writer as csv_writer
from hashlib import sha256
from html import escape as html_escape
from io import StringIO
from json import JSONEncoder, dumps
from math import isfinite
from re import fullmatch
from struct import pack
from time import perf_counter


_TABLE_SIDECAR_KEYS = (
    "policy_id", "version", "scope", "status", "table_id", "candidate_id",
    "page_index", "grid", "slots", "source_objects", "evidence",
    "span_decisions", "representation_custody", "reconciliation", "gate",
    "continuation", "concerns",
)
_TABLE_CELL_KEYS = (
    "id", "row", "column", "row_span", "col_span", "text",
    "column_header", "row_header", "row_section", "bbox", "source",
    "page_index", "evidence_ids", "source_object_ids", "span_decision_id",
    "confidence_dimensions",
)
_TABLE_SLOT_KEYS = (
    "id", "row", "column", "kind", "cell_id", "covered_by_cell_id",
)
_TABLE_SOURCE_KEYS = (
    "id", "engine", "object_type", "page_index", "raw_ref",
    "content_sha256",
)
_TABLE_PDFPLUMBER_SOURCE_KEYS = (
    "id", "engine", "object_type", "page_index", "raw_ref", "role",
    "target_row", "target_column", "words", "content_sha256",
)
_TABLE_WORD_KEYS = ("id", "text", "bbox", "font_name", "bold")
_TABLE_EVIDENCE_KEYS = (
    "id", "method", "dimension", "page_index", "bbox",
    "source_object_ids", "confidence", "content_sha256",
)
_TABLE_SPAN_KEYS = (
    "id", "cell_id", "claimed_row_span", "claimed_col_span",
    "emitted_row_span", "emitted_col_span", "outcome", "evidence_ids",
    "concern_codes",
)
_TABLE_CUSTODY_KEYS = (
    "serializer_policy_id", "grid_shape", "cells_sha256", "rows_sha256",
    "html_sha256", "markdown_sha256", "csv_sha256",
)
_TABLE_CONCERN_CODES = (
    "table_ambiguous_border_evidence",
    "table_malformed_source_evidence",
    "table_resource_limit_exceeded",
    "table_source_cell_bbox_unresolved",
    "table_source_cell_grid_unresolved",
    "table_source_form_grid_topology_unresolved",
    "table_source_header_ownership_unresolved",
    "table_source_provenance_unresolved",
    "table_source_rotation_mapping_unresolved",
    "table_source_row_boundary_unresolved",
    "table_source_span_evidence_unresolved",
    "table_reconciliation_conflict",
    "table_reconciliation_low_margin",
    "table_reconciliation_malformed_candidate",
    "table_candidate_chart_owned",
    "table_candidate_form_owned",
    "table_candidate_key_value_alternative",
    "table_candidate_ownership_ambiguous",
    "table_candidate_structure_invalid",
    "table_continuation_ambiguous",
    "table_continuation_incompatible",
)
_TABLE_SCOPE_ORDER = ("P04-US01", "P04-US02", "P04-US04", "P04-US03")
_TABLE_RECONCILIATION_KEYS = (
    "cluster_id", "candidate_ids", "selected_candidate_id", "outcome",
    "absolute_threshold", "selection_margin", "scores", "evidence_ids",
    "concern_codes",
)
_TABLE_RECONCILIATION_SCORE_KEYS = (
    "candidate_id", "engine", "total", "geometry", "grid",
    "cell_coverage", "text_coverage", "spans", "provenance", "bbox",
    "row_count", "column_count", "content_sha256", "candidate",
)
_TABLE_GATE_KEYS = (
    "decision_id", "candidate_id", "outcome", "owner_item_ids",
    "feature_scores", "evidence_ids", "concern_codes",
)
_TABLE_GATE_FEATURE_KEYS = (
    "alignment", "cell_coverage", "geometry", "grid",
    "owner_overlap", "provenance", "region_type", "table_support",
)
_TABLE_CONTINUATION_KEYS = (
    "merge_id", "outcome", "source_table_ids", "continued_from",
    "page_indexes", "signal_ids", "repeated_header_cell_ids",
    "evidence_ids", "concern_codes",
)
_TABLE_CONTINUATION_THRESHOLD = 0.65
_TABLE_PREDECESSOR_SNAPSHOT_KEY = "_p04_predecessor_snapshot"
_TABLE_RECOVERY_PLAN_KEY = "_p04_table_recovery_plan"
_TABLE_REPRESENTATION_NUMBER_TAG = "$p04_f64"
_TABLE_DOCUMENT_SIDECAR_MAX_BYTES = 67108864
_TABLE_DOWNSTREAM_LIST_MAX_ITEMS = 65536
# Docling's table-region and content rectangles are independently rounded and
# can differ by a small sub-point edge amount (the reviewed postal header is
# 0.338 pt above its table region).  This ownership tolerance is deliberately
# separate from the stricter 0.011 pt exact-oracle comparison: it can establish
# only that source content belongs to the bound table, never its grid slot.
_TABLE_CONTENT_REGION_TOLERANCE_PT = 0.500
_TABLE_AUTHORITATIVE_PROJECTION_KEYS = (
    "rows",
    "cells",
    "value",
    "html",
    "md",
    "csv",
    "row_count",
    "column_count",
)
# The terminal transaction is predecessor-based: only this source-supported
# P04 delta may be replayed over the exact P03 terminal item.  Every other key
# (including present/future P03 running/form/outline/text-run sidecars) remains
# byte-exact from that predecessor.
_TABLE_P04_DELTA_KEYS = frozenset(
    {
        *_TABLE_AUTHORITATIVE_PROJECTION_KEYS,
        "table_evidence",
        "table_candidate_gate_reasons",
        # The table-region bbox is source-supported US01 provenance.  Image
        # ownership, engine/confidence, and legacy concern fields remain P03
        # predecessor state and are intentionally not replayable deltas.
        "bbox",
    }
)
_TABLE_DOWNSTREAM_SNAPSHOT_KEYS = (
    "id",
    "reading_order",
    "caption_ids",
    "caption_of",
    "relationships",
    "source_note_ids",
    "footnote_ids",
    "contains_ids",
    "contained_items",
    "layout_source_notes_projected",
    "layout_visual_relationships_projected",
)


class _TableLocalSourceRejection(ValueError):
    pass


class _TableDocumentResourceRejection(ValueError):
    pass


class _TablePredecessorIntegrityError(ValueError):
    pass


def _bounded_table_iterable(value, limit):
    if type(limit) is not int or limit < 0 or limit > 65536:
        raise ValueError("invalid table iteration limit")
    if type(value) not in (dict, list, range, tuple):
        raise TypeError("table iteration input must be bounded")
    if len(value) > limit:
        raise ValueError("table iteration limit exceeded")
    return tuple(value)


def _bounded_table_text(value):
    if type(value) is not str:
        raise TypeError("table regex input must be exact text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("table text must be valid UTF-8") from None
    if len(encoded) > 65536:
        raise ValueError("table regex input limit exceeded")
    return value


def _check_table_deadline(deadline):
    if type(deadline) not in (int, float) or not isfinite(float(deadline)):
        raise ValueError("invalid table deadline")
    if perf_counter() > float(deadline):
        raise TimeoutError("table operation deadline exceeded")


def table_span_fidelity_document_deadline():
    return perf_counter() + 5.000


def _resolve_table_document_deadline(value):
    now = perf_counter()
    if value is None:
        return now + 5.000
    if (
        type(value) not in (int, float)
        or type(value) is bool
        or not isfinite(float(value))
        or float(value) > now + 5.000
    ):
        raise ValueError("table document deadline differs")
    if float(value) <= now:
        raise TimeoutError("table operation deadline exceeded")
    return float(value)


def table_span_fidelity_page_deadline(table_span_fidelity_document_deadline=None):
    now = perf_counter()
    deadline = now + 0.500
    if table_span_fidelity_document_deadline is not None:
        document_deadline = _resolve_table_document_deadline(
            table_span_fidelity_document_deadline
        )
        deadline = min(deadline, document_deadline)
    return deadline


def _resolve_table_page_deadline(value, document_deadline=None):
    now = perf_counter()
    if value is None:
        deadline = now + 0.500
    elif (
        type(value) not in (int, float)
        or type(value) is bool
        or not isfinite(float(value))
        or float(value) > now + 0.500
    ):
        raise ValueError("table page deadline differs")
    elif float(value) <= now:
        raise TimeoutError("table operation deadline exceeded")
    else:
        deadline = float(value)
    if document_deadline is not None:
        deadline = min(
            deadline,
            _resolve_table_document_deadline(document_deadline),
        )
    return deadline


def _inspect_plain_table_value(
    value,
    deadline,
    *,
    json_only=False,
    capture_canonical_failures=False,
):
    """Inspect one plain graph and optionally retain deferred JSON failures.

    Pipeline-owned Docling roots need to preserve the legacy local-rejection
    path, which admits tuples and bytes before deciding whether the source is
    usable, without walking a usable root again merely to discover whether it
    is canonical JSON.  The two retained failures are sufficient because the
    recovery-plan key is the only field this module may replace between
    admission and serialization.
    """

    if (
        type(json_only) is not bool
        or type(capture_canonical_failures) is not bool
    ):
        raise TypeError("invalid JSON-only table policy")
    _check_table_deadline(deadline)
    active = {}
    node_count = 0
    aggregate_bytes = 0
    canonical_failure_order = 0
    recovery_plan_failure = None
    other_canonical_failure = None

    def canonical_failure(error_type, message, root_key):
        nonlocal canonical_failure_order
        nonlocal recovery_plan_failure, other_canonical_failure
        if json_only:
            raise error_type(message)
        if not capture_canonical_failures:
            return
        canonical_failure_order += 1
        record = (canonical_failure_order, error_type, message)
        if root_key == _TABLE_RECOVERY_PLAN_KEY:
            if recovery_plan_failure is None:
                recovery_plan_failure = record
        elif other_canonical_failure is None:
            other_canonical_failure = record

    def visit(current, depth, root_key=None):
        nonlocal aggregate_bytes, node_count
        _check_table_deadline(deadline)
        node_count += 1
        if node_count > 4194304:
            raise ValueError("table node limit exceeded")
        current_type = type(current)
        if current is None or current_type is bool:
            aggregate_bytes += 16
            if aggregate_bytes > 67108864:
                raise ValueError("table aggregate byte limit exceeded")
            return
        if current_type is int:
            aggregate_bytes += 32 + (current.bit_length() + 7) // 8
            if aggregate_bytes > 67108864:
                raise ValueError("table aggregate byte limit exceeded")
            return
        if current_type is float:
            if not isfinite(current):
                raise ValueError("non-finite table value")
            aggregate_bytes += 32
            if aggregate_bytes > 67108864:
                raise ValueError("table aggregate byte limit exceeded")
            return
        if current_type is str:
            try:
                encoded = current.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("table text must be valid UTF-8") from None
            if len(encoded) > 1048576:
                raise ValueError("table string limit exceeded")
            aggregate_bytes += 64 + len(encoded)
            if aggregate_bytes > 67108864:
                raise ValueError("table aggregate byte limit exceeded")
            return
        if current_type is bytes:
            canonical_failure(
                TypeError,
                "canonical table JSON must not contain bytes",
                root_key,
            )
            if len(current) > 1048576:
                raise ValueError("table string limit exceeded")
            aggregate_bytes += 64 + len(current)
            if aggregate_bytes > 67108864:
                raise ValueError("table aggregate byte limit exceeded")
            return
        if current_type not in (dict, list, tuple):
            raise TypeError("table value must be exact plain data")
        if current_type is tuple:
            canonical_failure(
                TypeError,
                "canonical table JSON must use lists",
                root_key,
            )
        if depth >= 32:
            raise ValueError("table nesting limit exceeded")
        identity = id(current)
        if identity in active:
            raise ValueError("cyclic table value")
        container_limit = 4096 if current_type is dict else 65536
        if len(current) > container_limit:
            raise ValueError("table container limit exceeded")
        aggregate_bytes += 64 + len(current) * (
            32 if current_type is dict else 16
        )
        if aggregate_bytes > 67108864:
            raise ValueError("table aggregate byte limit exceeded")
        active[identity] = True
        try:
            if current_type is dict:
                entries = tuple(current.items())
                aggregate_bytes += 64 + len(entries) * 16
                if aggregate_bytes > 67108864:
                    raise ValueError("table aggregate byte limit exceeded")
                for key, _item in entries:
                    _check_table_deadline(deadline)
                    if type(key) is not str:
                        canonical_failure(
                            TypeError,
                            "canonical table JSON keys must be text",
                            key if depth == 0 else root_key,
                        )
                # Match the previous LIFO walk while retaining only one
                # child path.  Dict entry snapshots stay bounded at 4,096.
                for key, item in reversed(entries):
                    child_root_key = key if depth == 0 else root_key
                    visit(item, depth + 1, child_root_key)
                    visit(key, depth + 1, child_root_key)
            else:
                # Snapshot exact list/tuple contents before visiting them so
                # validation does not observe a changing length mid-walk.
                # Recursive depth is capped at 32, avoiding the former eager
                # O(width * depth) pending-node frontier.
                children = tuple(current)
                for item in reversed(children):
                    _check_table_deadline(deadline)
                    visit(item, depth + 1, root_key)
            # Preserve the former leaving-marker deadline check without
            # masking a validation exception raised by a child.
            _check_table_deadline(deadline)
        finally:
            active.pop(identity, None)

    visit(value, 0)
    return (
        aggregate_bytes,
        recovery_plan_failure,
        other_canonical_failure,
    )


def _assert_plain_table_value(
    value, deadline, json_only=False, return_aggregate=False
):
    if type(json_only) is not bool or type(return_aggregate) is not bool:
        raise TypeError("invalid JSON-only table policy")
    aggregate_bytes, _plan_failure, _other_failure = (
        _inspect_plain_table_value(
            value,
            deadline,
            json_only=json_only,
        )
    )
    return aggregate_bytes if return_aggregate else value


def _validate_plain_table_value(value, deadline):
    _assert_plain_table_value(value, deadline)
    _check_table_deadline(deadline)
    return deepcopy(value)


_OWNED_CANONICAL_TABLE_ROOT_SEAL = object()


class _OwnedCanonicalTableRoot:
    """One internally admitted, independently owned Docling source root."""

    __slots__ = (
        "_aggregate_bytes",
        "_other_canonical_failure",
        "_recovery_plan_failure",
        "_root",
        "_root_identity",
        "_seal",
        "_top_level_shape",
    )

    def __init__(
        self,
        seal,
        root,
        aggregate_bytes,
        recovery_plan_failure,
        other_canonical_failure,
    ):
        if seal is not _OWNED_CANONICAL_TABLE_ROOT_SEAL:
            raise TypeError("owned canonical table root cannot be constructed")
        if type(root) is not dict:
            raise TypeError("owned canonical table root differs")
        self._seal = seal
        self._root = root
        self._root_identity = id(root)
        self._aggregate_bytes = aggregate_bytes
        self._recovery_plan_failure = recovery_plan_failure
        self._other_canonical_failure = other_canonical_failure
        self._top_level_shape = _owned_table_root_shape(root)


def _owned_table_root_shape(root):
    if type(root) is not dict:
        raise TypeError("owned canonical table root differs")
    return tuple(
        (key, type(value), id(value)) for key, value in root.items()
    )


def _assert_owned_table_root_state(owned):
    if (
        type(owned) is not _OwnedCanonicalTableRoot
        or owned._seal is not _OWNED_CANONICAL_TABLE_ROOT_SEAL
        or type(owned._root) is not dict
        or id(owned._root) != owned._root_identity
        or _owned_table_root_shape(owned._root) != owned._top_level_shape
        or type(owned._aggregate_bytes) is not int
        or not 0 <= owned._aggregate_bytes <= 67108864
    ):
        raise TypeError("owned canonical table root differs")
    return owned._root


def _admit_owned_canonical_table_root(value, deadline):
    """Admit/copy one untrusted root and retain deferred JSON-shape proof."""

    aggregate_bytes, recovery_plan_failure, other_canonical_failure = (
        _inspect_plain_table_value(
            value,
            deadline,
            capture_canonical_failures=True,
        )
    )
    _check_table_deadline(deadline)
    owned_root = deepcopy(value)
    _check_table_deadline(deadline)
    return _OwnedCanonicalTableRoot(
        _OWNED_CANONICAL_TABLE_ROOT_SEAL,
        owned_root,
        aggregate_bytes,
        recovery_plan_failure,
        other_canonical_failure,
    )


def _owned_canonical_table_root_value(owned, deadline):
    _check_table_deadline(deadline)
    return _assert_owned_table_root_state(owned)


def _install_owned_table_recovery_plan(owned, plan, deadline):
    """Install the sole permitted mutation into an admitted private root."""

    root = _owned_canonical_table_root_value(owned, deadline)
    if type(plan) is not dict:
        raise TypeError("owned table recovery plan differs")
    plan_aggregate = _assert_plain_table_value(
        plan,
        deadline,
        True,
        True,
    )
    _check_table_deadline(deadline)
    installed_plan = deepcopy(plan)
    _check_table_deadline(deadline)
    if _TABLE_RECOVERY_PLAN_KEY in root:
        prior_aggregate = _assert_plain_table_value(
            root[_TABLE_RECOVERY_PLAN_KEY],
            deadline,
            False,
            True,
        )
        aggregate_bytes = (
            owned._aggregate_bytes - prior_aggregate + plan_aggregate
        )
    else:
        entry_aggregate = _assert_plain_table_value(
            {_TABLE_RECOVERY_PLAN_KEY: installed_plan},
            deadline,
            True,
            True,
        )
        # Empty-dict accounting is 128 bytes. The remainder is the exact
        # contribution of the new key/value entry to an existing mapping.
        aggregate_bytes = owned._aggregate_bytes + entry_aggregate - 128
    if aggregate_bytes > 67108864:
        raise ValueError("table aggregate byte limit exceeded")
    root[_TABLE_RECOVERY_PLAN_KEY] = installed_plan
    owned._aggregate_bytes = aggregate_bytes
    owned._recovery_plan_failure = None
    owned._top_level_shape = _owned_table_root_shape(root)
    _check_table_deadline(deadline)
    return None


def _copy_table_mapping(value, deadline):
    if type(value) not in (dict, defaultdict):
        raise TypeError("table mapping must be exact dict/defaultdict")
    _check_table_deadline(deadline)
    entries = tuple(value.items())
    if len(entries) > 4096:
        raise ValueError("table mapping limit exceeded")
    copied = {}
    for entry in _bounded_table_iterable(entries, 4096):
        _check_table_deadline(deadline)
        key, item = entry
        _assert_plain_table_value(key, deadline)
        _assert_plain_table_value(item, deadline)
        copied[key] = item
    return _validate_plain_table_value(copied, deadline)


def _copy_raw_table_graph(vector_tables, deadline):
    if type(vector_tables) not in (dict, defaultdict):
        raise TypeError("vector table graph must be exact dict/defaultdict")
    _check_table_deadline(deadline)
    page_entries = tuple(vector_tables.items())
    if len(page_entries) > 4096:
        raise ValueError("vector table page limit exceeded")
    copied = {}
    candidate_count = 0
    for page_entry in _bounded_table_iterable(page_entries, 4096):
        _check_table_deadline(deadline)
        page_index, raw_tables = page_entry
        if type(page_index) is not int or page_index < 1:
            raise TypeError("vector table page index differs")
        if type(raw_tables) is not list:
            raise TypeError("vector table candidates must be exact list")
        candidate_count = candidate_count + len(raw_tables)
        if candidate_count > 65536:
            raise ValueError("vector table candidate limit exceeded")
    for page_entry in _bounded_table_iterable(page_entries, 4096):
        _check_table_deadline(deadline)
        page_index, raw_tables = page_entry
        copied_candidates = []
        for raw_table in _bounded_table_iterable(raw_tables, 4096):
            _check_table_deadline(deadline)
            if type(raw_table) is RawTable:
                candidate = _validate_plain_table_value(
                    {
                        "page_index": raw_table.page_index,
                        "bbox": raw_table.bbox,
                        "rows": raw_table.rows,
                        "row_bboxes": raw_table.row_bboxes,
                        "parse_concerns": raw_table.parse_concerns,
                        "cell_bboxes": raw_table.cell_bboxes,
                        "geometry_inferred": raw_table.geometry_inferred,
                    },
                    deadline,
                )
            elif type(raw_table) in (dict, defaultdict):
                candidate = _copy_table_mapping(raw_table, deadline)
                candidate_keys = set(candidate)
                predecessor_keys = {
                    "page_index", "bbox", "rows", "row_bboxes",
                    "parse_concerns",
                }
                geometry_keys = predecessor_keys | {
                    "cell_bboxes", "geometry_inferred",
                }
                if candidate_keys == predecessor_keys:
                    candidate["cell_bboxes"] = ()
                    candidate["geometry_inferred"] = None
                elif candidate_keys != geometry_keys:
                    raise ValueError("raw table mapping fields differ")
            else:
                raise TypeError("raw table candidate type differs")
            copied_candidates.append(candidate)
        copied[page_index] = copied_candidates
    _assert_plain_table_value(copied, deadline)
    return copied


def _assert_source_sha256(value, deadline):
    _check_table_deadline(deadline)
    if (
        type(value) is not str
        or len(value) != 64
        or fullmatch(r"[0-9a-f]{64}", value) is None
    ):
        raise ValueError("source SHA-256 differs")
    return value


def _stream_accounted_canonical_table_json(
    value,
    maximum_bytes,
    deadline,
    aggregate_bytes,
    *,
    collect_bytes=False,
    compute_sha256=False,
):
    if (
        type(maximum_bytes) is not int
        or maximum_bytes < 0
        or maximum_bytes > 67108864
        or type(aggregate_bytes) is not int
        or not 0 <= aggregate_bytes <= 67108864
        or type(collect_bytes) is not bool
        or type(compute_sha256) is not bool
    ):
        raise ValueError("canonical table JSON stream policy differs")
    _check_table_deadline(deadline)
    encoded_parts = bytearray() if collect_bytes else None
    digest = sha256() if compute_sha256 else None
    total_bytes = 0
    try:
        if (
            maximum_bytes <= 8388608
            and aggregate_bytes <= maximum_bytes // 6
        ):
            canonical = dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            encoded = canonical.encode("utf-8")
            total_bytes = len(encoded)
            if total_bytes > maximum_bytes:
                raise ValueError("canonical table JSON limit exceeded")
            if encoded_parts is not None:
                encoded_parts.extend(encoded)
            if digest is not None:
                digest.update(encoded)
            _check_table_deadline(deadline)
            return [
                bytes(encoded_parts) if encoded_parts is not None else None,
                digest.hexdigest() if digest is not None else None,
                total_bytes,
            ]
        chunks = JSONEncoder(
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).iterencode(value)
        pending_chunks = []
        pending_characters = 0
        for chunk in chunks:
            pending_chunks.append(chunk)
            pending_characters += len(chunk)
            if len(pending_chunks) < 256 and pending_characters < 65536:
                continue
            _check_table_deadline(deadline)
            encoded = "".join(pending_chunks).encode("utf-8")
            total_bytes += len(encoded)
            if total_bytes > maximum_bytes:
                raise ValueError("canonical table JSON limit exceeded")
            if encoded_parts is not None:
                encoded_parts.extend(encoded)
            if digest is not None:
                digest.update(encoded)
            pending_chunks = []
            pending_characters = 0
        if pending_chunks:
            _check_table_deadline(deadline)
            encoded = "".join(pending_chunks).encode("utf-8")
            total_bytes += len(encoded)
            if total_bytes > maximum_bytes:
                raise ValueError("canonical table JSON limit exceeded")
            if encoded_parts is not None:
                encoded_parts.extend(encoded)
            if digest is not None:
                digest.update(encoded)
    except UnicodeEncodeError:
        raise ValueError("canonical table JSON must be valid UTF-8") from None
    except (RecursionError, TypeError, ValueError) as exc:
        if str(exc) == "canonical table JSON limit exceeded":
            raise
        raise ValueError("canonical table JSON serialization failed") from None
    _check_table_deadline(deadline)
    return [
        bytes(encoded_parts) if encoded_parts is not None else None,
        digest.hexdigest() if digest is not None else None,
        total_bytes,
    ]


def _stream_canonical_table_json(
    value,
    maximum_bytes,
    deadline,
    *,
    collect_bytes=False,
    compute_sha256=False,
):
    if (
        type(maximum_bytes) is not int
        or maximum_bytes < 0
        or maximum_bytes > 67108864
        or type(collect_bytes) is not bool
        or type(compute_sha256) is not bool
    ):
        raise ValueError("canonical table JSON stream policy differs")
    aggregate_bytes = _assert_plain_table_value(
        value, deadline, True, True
    )
    return _stream_accounted_canonical_table_json(
        value,
        maximum_bytes,
        deadline,
        aggregate_bytes,
        collect_bytes=collect_bytes,
        compute_sha256=compute_sha256,
    )


def _assert_owned_canonical_table_json(owned, maximum_bytes, deadline):
    """Serialize one private admission without a second graph admission."""

    root = _owned_canonical_table_root_value(owned, deadline)
    failures = [
        failure
        for failure in (
            owned._recovery_plan_failure,
            owned._other_canonical_failure,
        )
        if failure is not None
    ]
    if failures:
        _order, error_type, message = min(failures, key=lambda value: value[0])
        raise error_type(message)
    _stream_accounted_canonical_table_json(
        root,
        maximum_bytes,
        deadline,
        owned._aggregate_bytes,
    )
    return None


def _canonical_table_json_bytes(value, maximum_bytes, deadline):
    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):
        raise ValueError("canonical table JSON limit differs")
    return _stream_canonical_table_json(
        value,
        maximum_bytes,
        deadline,
        collect_bytes=True,
    )[0]


def _canonical_table_json_size(value, maximum_bytes, deadline):
    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):
        raise ValueError("canonical table JSON limit differs")
    return _stream_canonical_table_json(
        value, maximum_bytes, deadline
    )[2]


def _bounded_table_sha256(value, maximum_bytes, deadline):
    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):
        raise ValueError("table SHA-256 limit differs")
    if type(value) is not bytes:
        raise TypeError("table SHA-256 input must be exact bytes")
    if len(value) > maximum_bytes:
        raise ValueError("table SHA-256 input limit exceeded")
    _check_table_deadline(deadline)
    digest = sha256(value).hexdigest()
    _check_table_deadline(deadline)
    return digest


def _canonical_table_sha256(value, maximum_bytes, deadline):
    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):
        raise ValueError("canonical table JSON limit differs")
    return _stream_canonical_table_json(
        value,
        maximum_bytes,
        deadline,
        compute_sha256=True,
    )[1]


def _canonical_table_sha256_and_size(value, maximum_bytes, deadline):
    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):
        raise ValueError("canonical table JSON limit differs")
    streamed = _stream_canonical_table_json(
        value,
        maximum_bytes,
        deadline,
        compute_sha256=True,
    )
    return [streamed[1], streamed[2]]


def _table_representation_number_projection(value, deadline):
    _check_table_deadline(deadline)
    value_type = type(value)
    if value is None or value_type in (bool, str):
        return value
    if value_type in (int, float):
        try:
            numeric = float(value)
        except (OverflowError, ValueError):
            raise ValueError("table representation number differs") from None
        if not isfinite(numeric):
            raise ValueError("table representation number differs")
        if numeric == 0.0:
            numeric = 0.0
        return {_TABLE_REPRESENTATION_NUMBER_TAG: pack(">d", numeric).hex()}
    if value_type is list:
        projected_list = []
        for item in _bounded_table_iterable(value, 65536):
            _check_table_deadline(deadline)
            projected_list.append(
                _table_representation_number_projection(item, deadline)
            )
        return projected_list
    if value_type is dict:
        if _TABLE_REPRESENTATION_NUMBER_TAG in value:
            raise ValueError("table representation number tag collision")
        keys = list(value)
        keys.sort()
        projected_mapping = {}
        for key in _bounded_table_iterable(keys, 4096):
            _check_table_deadline(deadline)
            if type(key) is not str or not key.isascii():
                raise ValueError("table representation schema key differs")
            projected_mapping[key] = _table_representation_number_projection(
                value.get(key), deadline
            )
        return projected_mapping
    raise TypeError("table representation value differs")


def _table_representation_sha256(
    value,
    deadline,
    *,
    value_is_plain=False,
):
    if type(value_is_plain) is not bool:
        raise TypeError("table representation validation policy differs")
    if not value_is_plain:
        _assert_plain_table_value(value, deadline, True)
    projected_node_count = 0
    projected_aggregate_bytes = 0
    active = {}
    digest = sha256()
    total_bytes = 0
    output_limit_exceeded = False

    def account_node() -> None:
        nonlocal projected_node_count
        projected_node_count += 1
        if projected_node_count > 4194304:
            raise ValueError("table node limit exceeded")

    def account_bytes(size: int) -> None:
        nonlocal projected_aggregate_bytes
        projected_aggregate_bytes += size
        if projected_aggregate_bytes > 67108864:
            raise ValueError("table aggregate byte limit exceeded")

    def raw_string_bytes(member: str) -> bytes:
        try:
            encoded = member.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("table text must be valid UTF-8") from None
        if len(encoded) > 1048576:
            raise ValueError("table string limit exceeded")
        return encoded

    def feed(encoded: bytes) -> None:
        nonlocal output_limit_exceeded, total_bytes
        if output_limit_exceeded:
            return
        if total_bytes + len(encoded) > 8388608:
            # The prior implementation completed projected-graph admission
            # before attempting canonical serialization. Remember overflow
            # but continue only the cheap logical walk so a later aggregate,
            # node, depth, or string rejection keeps the same precedence.
            total_bytes = 8388609
            output_limit_exceeded = True
            return
        total_bytes += len(encoded)
        digest.update(encoded)

    def encoded_string(member):
        try:
            return dumps(
                member,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, UnicodeEncodeError, ValueError):
            raise ValueError(
                "canonical table JSON serialization failed"
            ) from None

    def stream(member, depth):
        _check_table_deadline(deadline)
        member_type = type(member)
        if member_type in (int, float):
            if depth >= 32:
                raise ValueError("table nesting limit exceeded")
            try:
                numeric = float(member)
            except (OverflowError, ValueError):
                raise ValueError(
                    "table representation number differs"
                ) from None
            if not isfinite(numeric):
                raise ValueError("table representation number differs")
            if numeric == 0.0:
                numeric = 0.0
            # Exact logical footprint of the projected numeric wrapper:
            # dict node/container+entry snapshot (176), 16-byte hex value
            # string node (80), and `$p04_f64` key string node (72).
            account_node()
            account_bytes(96)
            account_bytes(80)
            account_node()
            account_bytes(80)
            account_node()
            account_bytes(72)
            if not output_limit_exceeded:
                feed(
                    b'{"$p04_f64":"'
                    + pack(">d", numeric).hex().encode("ascii")
                    + b'"}'
                )
            return
        account_node()
        if member is None:
            account_bytes(16)
            feed(b"null")
            return
        if member_type is bool:
            account_bytes(16)
            feed(b"true" if member else b"false")
            return
        if member_type is str:
            account_bytes(64 + len(raw_string_bytes(member)))
            if not output_limit_exceeded:
                feed(encoded_string(member))
            return
        if member_type not in (dict, list):
            raise TypeError("table representation value differs")
        if depth >= 32:
            raise ValueError("table nesting limit exceeded")
        identity = id(member)
        if identity in active:
            raise ValueError("cyclic table value")
        active[identity] = True
        try:
            if member_type is list:
                if len(member) > 65536:
                    raise ValueError("table container limit exceeded")
                account_bytes(64 + len(member) * 16)
                feed(b"[")
                for index, child in enumerate(
                    _bounded_table_iterable(member, 65536)
                ):
                    if index:
                        feed(b",")
                    stream(child, depth + 1)
                feed(b"]")
                return
            if len(member) > 4096:
                raise ValueError("table container limit exceeded")
            if _TABLE_REPRESENTATION_NUMBER_TAG in member:
                raise ValueError("table representation number tag collision")
            keys = list(member)
            try:
                keys.sort()
            except TypeError:
                raise ValueError(
                    "table representation schema key differs"
                ) from None
            account_bytes(128 + len(member) * 48)
            feed(b"{")
            for index, key in enumerate(_bounded_table_iterable(keys, 4096)):
                _check_table_deadline(deadline)
                if type(key) is not str or not key.isascii():
                    raise ValueError(
                        "table representation schema key differs"
                    )
                account_node()
                account_bytes(64 + len(raw_string_bytes(key)))
                if index:
                    feed(b",")
                if not output_limit_exceeded:
                    feed(encoded_string(key))
                feed(b":")
                stream(member[key], depth + 1)
            feed(b"}")
        finally:
            active.pop(identity, None)

    stream(value, 0)
    _check_table_deadline(deadline)
    if output_limit_exceeded:
        raise ValueError("canonical table JSON limit exceeded")
    return digest.hexdigest()


def _batch_table_sha256(values, maximum_bytes, deadline):
    if type(maximum_bytes) is not int or maximum_bytes not in (8388608, 67108864):
        raise ValueError("table batch SHA-256 limit differs")
    if type(values) is not list:
        raise TypeError("table batch SHA-256 input must be exact list")
    if len(values) > 65536:
        raise ValueError("table batch SHA-256 count exceeded")
    aggregate_bytes = _assert_plain_table_value(
        values, deadline, True, True
    )
    total_bytes = 0
    digests = []
    use_bounded_fast_path = (
        maximum_bytes <= 8388608
        and aggregate_bytes <= maximum_bytes // 6
    )
    for value in _bounded_table_iterable(values, 65536):
        _check_table_deadline(deadline)
        if use_bounded_fast_path:
            try:
                encoded = dumps(
                    value,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            except (TypeError, UnicodeEncodeError, ValueError):
                raise ValueError(
                    "table batch SHA-256 serialization failed"
                ) from None
            total_bytes += len(encoded)
            if total_bytes > maximum_bytes:
                raise ValueError(
                    "table batch SHA-256 aggregate limit exceeded"
                )
            digests.append(sha256(encoded).hexdigest())
            continue
        try:
            streamed = _stream_canonical_table_json(
                value,
                maximum_bytes - total_bytes,
                deadline,
                compute_sha256=True,
            )
        except ValueError as exc:
            if str(exc) == "canonical table JSON limit exceeded":
                raise ValueError(
                    "table batch SHA-256 aggregate limit exceeded"
                ) from None
            raise ValueError(
                "table batch SHA-256 serialization failed"
            ) from None
        total_bytes += streamed[2]
        digests.append(streamed[1])
    _check_table_deadline(deadline)
    return digests


def _assert_canonical_table_json(value, maximum_bytes, deadline):
    _canonical_table_json_size(value, maximum_bytes, deadline)
    return None


def _plain_table_length(value, deadline):
    _assert_plain_table_value(value, deadline)
    if type(value) not in (bytes, dict, list, str, tuple):
        raise TypeError("table length input differs")
    return len(value)


def _table_text_has_unsafe_control(value, deadline):
    text = _bounded_table_text(value)
    controls = (
        "\x00", "\x01", "\x02", "\x03", "\x04", "\x05", "\x06", "\x07",
        "\x08", "\x0b", "\x0c", "\x0d", "\x0e", "\x0f", "\x10", "\x11",
        "\x12", "\x13", "\x14", "\x15", "\x16", "\x17", "\x18", "\x19",
        "\x1a", "\x1b", "\x1c", "\x1d", "\x1e", "\x1f", "\x7f",
    )
    for character in _bounded_table_iterable(controls, 31):
        _check_table_deadline(deadline)
        if character in text:
            return True
    return False


def _table_font_name_is_safe(value, deadline):
    _check_table_deadline(deadline)
    if type(value) is not str or not value:
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if len(encoded) > 256:
        return False
    for character in _bounded_table_iterable(tuple(value), 256):
        _check_table_deadline(deadline)
        if ord(character) < 32 or ord(character) == 127:
            return False
    return True


def _validate_docling_table_source(raw_item, deadline):
    _assert_plain_table_value(raw_item, deadline)
    return _validate_docling_table_source_fields(raw_item, deadline)


def _validate_docling_table_source_fields(raw_item, deadline):
    """Validate fields on an adjacent, already admitted owned raw graph."""

    _check_table_deadline(deadline)
    _docling_table_page(raw_item, deadline)
    table_reference = _table_required_reference(
        raw_item.get("self_ref"), deadline
    )
    data = raw_item.get("data")
    if type(data) is not dict:
        raise TypeError("table source data differs")
    row_count = data.get("num_rows")
    column_count = data.get("num_cols")
    if (
        type(row_count) is not int
        or row_count < 1
        or row_count > 4096
        or type(column_count) is not int
        or column_count < 1
        or column_count > 256
        or row_count > 65536 // column_count
    ):
        raise ValueError("table source dimensions differ")
    raw_cells = data.get("table_cells")
    if type(raw_cells) is not list or len(raw_cells) > 65536:
        raise ValueError("table source cell count differs")
    observed_structural_locations = {}
    observed_direct_references = {}
    for raw_cell in _bounded_table_iterable(raw_cells, 65536):
        _check_table_deadline(deadline)
        if type(raw_cell) is not dict:
            raise TypeError("table source cell differs")
        row = raw_cell.get("start_row_offset_idx")
        column = raw_cell.get("start_col_offset_idx")
        row_span = raw_cell.get("row_span")
        col_span = raw_cell.get("col_span")
        end_row = raw_cell.get("end_row_offset_idx")
        end_column = raw_cell.get("end_col_offset_idx")
        if (
            type(row) is not int
            or row < 0
            or row >= row_count
            or type(column) is not int
            or column < 0
            or column >= column_count
            or type(row_span) is not int
            or row_span < 1
            or row_span > row_count - row
            or type(col_span) is not int
            or col_span < 1
            or col_span > column_count - column
        ):
            raise ValueError("table source cell coordinates differ")
        if (
            type(end_row) is not int
            or end_row != row + row_span
            or type(end_column) is not int
            or end_column != column + col_span
        ):
            raise _TableLocalSourceRejection(
                "table source cell end offsets differ"
            )
        structural_location = (
            row,
            column,
            end_row,
            end_column,
            row_span,
            col_span,
        )
        if structural_location in observed_structural_locations:
            raise _TableLocalSourceRejection(
                "table source cell structural locator differs"
            )
        observed_structural_locations[structural_location] = True
        reference_result = _docling_cell_reference(
            raw_cell,
            table_reference,
            deadline,
        )
        raw_reference, has_direct_reference = reference_result
        if has_direct_reference:
            if (
                raw_reference == table_reference
                or raw_reference in observed_direct_references
            ):
                raise _TableLocalSourceRejection(
                    "table source cell reference differs"
                )
            observed_direct_references[raw_reference] = True
        text = _bounded_table_text(raw_cell.get("text"))
        encoded = _bounded_table_text(text).encode("utf-8")
        if len(encoded) > 16384:
            raise ValueError("table source cell text limit exceeded")
        if _table_text_has_unsafe_control(text, deadline):
            raise ValueError("table source cell text control differs")
        for header_field in _bounded_table_iterable(
            ("column_header", "row_header", "row_section"), 3
        ):
            _check_table_deadline(deadline)
            header_value = raw_cell.get(header_field)
            if type(header_value) is not bool:
                raise TypeError("table source header ownership differs")
        bbox = raw_cell.get("bbox")
        if bbox is not None:
            if type(bbox) is not dict:
                raise TypeError("table source cell bbox differs")
            if bbox.get("coord_origin") != "TOPLEFT":
                raise ValueError("table source cell bbox origin differs")
            left = bbox.get("l")
            top = bbox.get("t")
            right = bbox.get("r")
            bottom = bbox.get("b")
            if (
                type(left) not in (int, float)
                or type(left) is bool
                or not isfinite(left)
                or type(top) not in (int, float)
                or type(top) is bool
                or not isfinite(top)
                or type(right) not in (int, float)
                or type(right) is bool
                or not isfinite(right)
                or type(bottom) not in (int, float)
                or type(bottom) is bool
                or not isfinite(bottom)
                or right <= left
                or bottom <= top
            ):
                raise ValueError("table source cell bbox geometry differs")
    return None


def _bounded_table_output_bytes(value, deadline):
    if type(value) is not str:
        raise TypeError("table representation must be exact text")
    _check_table_deadline(deadline)
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("table representation must be valid UTF-8")
    if len(encoded) > 8388608:
        raise ValueError("table representation limit exceeded")
    _check_table_deadline(deadline)
    return encoded


def _table_exact_keys(value, keys, deadline):
    _check_table_deadline(deadline)
    if type(value) is not dict or type(keys) not in (list, tuple):
        return False
    if len(value) != len(keys):
        return False
    expected = set(keys)
    observed = set(value)
    return observed == expected


def _table_reference_is_safe(value, deadline):
    _check_table_deadline(deadline)
    if type(value) is not str or not value or not value.startswith("#/"):
        return False
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        return False
    if len(encoded) > 256 or "\\" in value or _table_text_has_unsafe_control(
        value, deadline
    ):
        return False
    components = value[2:].split("/")
    if not components:
        return False
    for component in _bounded_table_iterable(components, 256):
        _check_table_deadline(deadline)
        if not component or component in (".", ".."):
            return False
        for character in _bounded_table_iterable(tuple(component), 256):
            _check_table_deadline(deadline)
            if ord(character) < 0x21 or ord(character) > 0x7e:
                return False
    return True


def _table_required_reference(value, deadline):
    if not _table_reference_is_safe(value, deadline):
        raise _TableLocalSourceRejection("table source reference differs")
    return value


def _docling_cell_reference(raw_cell, table_reference, deadline):
    _check_table_deadline(deadline)
    table_reference = _table_required_reference(table_reference, deadline)
    reference = raw_cell.get("ref")
    if reference is None:
        return [table_reference, False]
    if type(reference) is not dict:
        raise _TableLocalSourceRejection(
            "table source cell reference differs"
        )
    candidates = []
    for name in _bounded_table_iterable(("$ref", "cref"), 2):
        _check_table_deadline(deadline)
        candidate = reference.get(name)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates and not reference:
        return [table_reference, False]
    if len(candidates) != 1 or len(reference) != 1:
        raise _TableLocalSourceRejection(
            "table source cell reference differs"
        )
    return [_table_required_reference(candidates[0], deadline), True]


def _docling_table_page(raw_item, deadline):
    _check_table_deadline(deadline)
    provenance = raw_item.get("prov")
    if type(provenance) is not list or len(provenance) != 1:
        raise _TableLocalSourceRejection(
            "table source provenance differs"
        )
    first = provenance[0]
    if type(first) is not dict:
        raise _TableLocalSourceRejection(
            "table source provenance differs"
        )
    page_index = first.get("page_no")
    if type(page_index) is not int or page_index < 1 or page_index > 1000000:
        raise _TableLocalSourceRejection(
            "table source provenance differs"
        )
    return page_index


def _docling_table_bbox(item, deadline):
    _check_table_deadline(deadline)
    raw_bbox = item.get("bbox")
    if type(raw_bbox) is not dict:
        return None
    left = raw_bbox.get("x")
    top = raw_bbox.get("y")
    width = raw_bbox.get("width")
    height = raw_bbox.get("height")
    if (
        type(left) not in (int, float)
        or type(left) is bool
        or type(top) not in (int, float)
        or type(top) is bool
        or type(width) not in (int, float)
        or type(width) is bool
        or type(height) not in (int, float)
        or type(height) is bool
        or not isfinite(left)
        or not isfinite(top)
        or not isfinite(width)
        or not isfinite(height)
        or left < 0
        or top < 0
        or width <= 0
        or height <= 0
        or raw_bbox.get("unit") != "pt"
    ):
        return None
    return {
        "x": left,
        "y": top,
        "width": width,
        "height": height,
        "unit": "pt",
    }


def _table_content_bbox_within_region(content_bbox, table_bbox, deadline):
    """Require an exact content rectangle to remain in its owning table.

    A content rectangle need not fill the structural slots claimed by a span;
    the separately closed Docling grid owns that structural fact.  The check
    only prevents unrelated, displaced page content from being presented as
    geometry evidence for the table.
    """

    _check_table_deadline(deadline)
    if (
        type(content_bbox) is not dict
        or type(table_bbox) is not dict
        or not _table_bbox_is_valid(content_bbox, deadline)
        or not _table_bbox_is_valid(table_bbox, deadline)
    ):
        return False
    tolerance = _TABLE_CONTENT_REGION_TOLERANCE_PT
    content_left = float(content_bbox["x"])
    content_top = float(content_bbox["y"])
    content_right = content_left + float(content_bbox["width"])
    content_bottom = content_top + float(content_bbox["height"])
    table_left = float(table_bbox["x"])
    table_top = float(table_bbox["y"])
    table_right = table_left + float(table_bbox["width"])
    table_bottom = table_top + float(table_bbox["height"])
    return (
        content_left >= table_left - tolerance
        and content_top >= table_top - tolerance
        and content_right <= table_right + tolerance
        and content_bottom <= table_bottom + tolerance
    )


def _docling_cell_record(raw_cell, table_reference, deadline):
    _check_table_deadline(deadline)
    row = raw_cell.get("start_row_offset_idx")
    column = raw_cell.get("start_col_offset_idx")
    row_span = raw_cell.get("row_span")
    col_span = raw_cell.get("col_span")
    text = _bounded_table_text(raw_cell.get("text")).strip()
    column_header = raw_cell.get("column_header", False)
    row_header = raw_cell.get("row_header", False)
    row_section = raw_cell.get("row_section", False)
    recovered_header = (
        raw_cell.get("p04_header_evidence") == "native_bold_transition"
    )
    raw_reference = _docling_cell_reference(
        raw_cell, table_reference, deadline
    )[0]
    raw_bbox = raw_cell.get("bbox")
    bbox_marker = 0
    left = 0.0
    top = 0.0
    width = 0.0
    height = 0.0
    if type(raw_bbox) is dict:
        raw_left = raw_bbox.get("l")
        raw_top = raw_bbox.get("t")
        raw_right = raw_bbox.get("r")
        raw_bottom = raw_bbox.get("b")
        if (
            type(raw_left) in (int, float)
            and type(raw_left) is not bool
            and type(raw_top) in (int, float)
            and type(raw_top) is not bool
            and type(raw_right) in (int, float)
            and type(raw_right) is not bool
            and type(raw_bottom) in (int, float)
            and type(raw_bottom) is not bool
            and isfinite(raw_left)
            and isfinite(raw_top)
            and isfinite(raw_right)
            and isfinite(raw_bottom)
            and raw_left >= 0
            and raw_top >= 0
            and raw_right > raw_left
            and raw_bottom > raw_top
        ):
            bbox_marker = 1
            left = raw_left
            top = raw_top
            width = raw_right - raw_left
            height = raw_bottom - raw_top
    return [
        row,
        column,
        row_span,
        col_span,
        text,
        column_header,
        row_header,
        row_section,
        bbox_marker,
        left,
        top,
        width,
        height,
        raw_reference,
        recovered_header,
    ]


def _normalized_docling_cells(raw_item, deadline):
    _check_table_deadline(deadline)
    data = raw_item.get("data")
    raw_cells = data.get("table_cells")
    table_reference = _table_required_reference(
        raw_item.get("self_ref"), deadline
    )
    cells = []
    for raw_cell in _bounded_table_iterable(raw_cells, 65536):
        _check_table_deadline(deadline)
        cells.append(
            _docling_cell_record(raw_cell, table_reference, deadline)
        )
    cells.sort()
    return cells


def _table_record_bbox(record, deadline):
    _check_table_deadline(deadline)
    if record[8] != 1:
        return None
    return {
        "x": record[9],
        "y": record[10],
        "width": record[11],
        "height": record[12],
        "unit": "pt",
    }


def _ordered_table_ids(first, second, third, fourth, deadline):
    _check_table_deadline(deadline)
    values = []
    if first is not None:
        values = [first]
    if second is not None:
        values = values + [second]
    if third is not None:
        values = values + [third]
    if fourth is not None:
        values = values + [fourth]
    values.sort()
    return values


def _unique_ordered_table_records(pairs, deadline):
    _check_table_deadline(deadline)
    observed = {}
    collision = False
    for pair in _bounded_table_iterable(pairs, 65536):
        _check_table_deadline(deadline)
        if type(pair) is not list or len(pair) != 2:
            collision = True
            continue
        identifier = pair[0]
        if identifier in observed:
            collision = True
        else:
            observed[identifier] = pair[1]
    identifiers = list(observed)
    identifiers.sort()
    records = []
    for identifier in _bounded_table_iterable(identifiers, 65536):
        _check_table_deadline(deadline)
        records.append(observed.get(identifier))
    return [records, collision]


def _build_table_slots(records, cell_ids, row_count, column_count, source_sha256, page_index, table_id, candidate_id, deadline):
    _check_table_deadline(deadline)
    owners = {}
    collision = False
    for pair in _bounded_table_iterable(list(zip(records, cell_ids)), 65536):
        _check_table_deadline(deadline)
        record, cell_id = pair
        for row_offset in _bounded_table_iterable(range(record[2]), 4096):
            _check_table_deadline(deadline)
            for column_offset in _bounded_table_iterable(range(record[3]), 256):
                _check_table_deadline(deadline)
                slot_row = record[0] + row_offset
                slot_column = record[1] + column_offset
                slot_key = f"{slot_row}:{slot_column}"
                if owners.get(slot_key) is not None:
                    collision = True
                owners[slot_key] = [
                    cell_id,
                    row_offset == 0 and column_offset == 0,
                    record[4],
                ]
    drafts = []
    preimages = []
    missing = False
    for row in _bounded_table_iterable(range(row_count), 4096):
        _check_table_deadline(deadline)
        for column in _bounded_table_iterable(range(column_count), 256):
            _check_table_deadline(deadline)
            slot_key = f"{row}:{column}"
            owner = owners.get(slot_key)
            if owner is None:
                missing = True
                draft = {
                    "id": None,
                    "row": row,
                    "column": column,
                    "kind": "covered",
                    "cell_id": None,
                    "covered_by_cell_id": None,
                }
            elif owner[1]:
                draft = {
                    "id": None,
                    "row": row,
                    "column": column,
                    "kind": "explicit_blank" if owner[2] == "" else "anchor",
                    "cell_id": owner[0],
                    "covered_by_cell_id": None,
                }
            else:
                draft = {
                    "id": None,
                    "row": row,
                    "column": column,
                    "kind": "covered",
                    "cell_id": None,
                    "covered_by_cell_id": owner[0],
                }
            drafts.append(draft)
            preimages.append(
                [
                    "p04-slot-id-v1",
                    source_sha256,
                    page_index,
                    table_id,
                    candidate_id,
                    row,
                    column,
                ]
            )
    slot_ids = _batch_table_sha256(preimages, 8388608, deadline)
    slots = []
    for pair in _bounded_table_iterable(list(zip(drafts, slot_ids)), 65536):
        _check_table_deadline(deadline)
        draft, slot_id = pair
        draft["id"] = slot_id
        slots.append(draft)
    return [slots, missing, collision]


def _table_representation_custody(
    item,
    row_count,
    column_count,
    deadline,
    *,
    item_is_plain=False,
):
    _check_table_deadline(deadline)
    if type(item_is_plain) is not bool:
        raise TypeError("table custody validation policy differs")
    cells_sha256 = _table_representation_sha256(
        item.get("cells"), deadline, value_is_plain=item_is_plain
    )
    rows_sha256 = _table_representation_sha256(
        item.get("rows"), deadline, value_is_plain=item_is_plain
    )
    html_bytes = _bounded_table_output_bytes(item.get("html"), deadline)
    markdown_bytes = _bounded_table_output_bytes(item.get("md"), deadline)
    csv_bytes = _bounded_table_output_bytes(item.get("csv"), deadline)
    html_sha256 = _bounded_table_sha256(html_bytes, 8388608, deadline)
    markdown_sha256 = _bounded_table_sha256(markdown_bytes, 8388608, deadline)
    csv_sha256 = _bounded_table_sha256(csv_bytes, 8388608, deadline)
    return {
        "serializer_policy_id": "p04-table-grid-serializer-v1",
        "grid_shape": [row_count, column_count],
        "cells_sha256": cells_sha256,
        "rows_sha256": rows_sha256,
        "html_sha256": html_sha256,
        "markdown_sha256": markdown_sha256,
        "csv_sha256": csv_sha256,
    }


def _serialize_table_grid(cells, slots, row_count, column_count, deadline):
    _check_table_deadline(deadline)
    if (
        type(cells) is not list
        or type(slots) is not list
        or type(row_count) is not int
        or type(column_count) is not int
        or row_count < 1
        or column_count < 1
        or row_count > 65536 // column_count
        or len(slots) != row_count * column_count
    ):
        raise ValueError("table serializer grid differs")
    cells_by_id = {}
    for cell in _bounded_table_iterable(cells, 65536):
        _check_table_deadline(deadline)
        if type(cell) is not dict or cell.get("id") in cells_by_id:
            raise ValueError("table serializer cell differs")
        cells_by_id[cell.get("id")] = cell
    rows = []
    slot_rows = []
    cursor = 0
    for row_index in _bounded_table_iterable(range(row_count), 4096):
        _check_table_deadline(deadline)
        row_values = []
        row_slots = []
        for column_index in _bounded_table_iterable(range(column_count), 256):
            _check_table_deadline(deadline)
            slot = slots[cursor]
            cursor += 1
            if (
                type(slot) is not dict
                or slot.get("row") != row_index
                or slot.get("column") != column_index
            ):
                raise ValueError("table serializer slot order differs")
            text = ""
            if slot.get("kind") in ("anchor", "explicit_blank"):
                cell = cells_by_id.get(slot.get("cell_id"))
                if type(cell) is not dict:
                    raise ValueError("table serializer slot linkage differs")
                text = cell.get("text")
                if type(text) is not str:
                    raise ValueError("table serializer cell text differs")
            row_values.append(text)
            row_slots.append(slot)
        rows.append(row_values)
        slot_rows.append(row_slots)
    leading_header_rows = 0
    for row_slots in _bounded_table_iterable(slot_rows, 4096):
        _check_table_deadline(deadline)
        header_anchor_count = 0
        non_header_anchor_count = 0
        for slot in _bounded_table_iterable(row_slots, 256):
            _check_table_deadline(deadline)
            if slot.get("kind") in ("anchor", "explicit_blank"):
                cell = cells_by_id.get(slot.get("cell_id"))
                if cell.get("column_header") is True:
                    header_anchor_count += 1
                else:
                    non_header_anchor_count += 1
        if header_anchor_count and not non_header_anchor_count:
            leading_header_rows += 1
        else:
            break
    html_lines = ["<table>"]
    for row_index in _bounded_table_iterable(range(row_count), 4096):
        _check_table_deadline(deadline)
        if row_index == 0 and leading_header_rows:
            html_lines.append("  <thead>")
        if row_index == leading_header_rows:
            if leading_header_rows:
                html_lines.append("  </thead>")
            html_lines.append("  <tbody>")
        html_lines.append("    <tr>")
        for slot in _bounded_table_iterable(slot_rows[row_index], 256):
            _check_table_deadline(deadline)
            if slot.get("kind") == "covered":
                continue
            cell = cells_by_id.get(slot.get("cell_id"))
            if type(cell) is not dict:
                raise ValueError("table serializer anchor differs")
            attributes = ""
            tag = "td"
            if cell.get("column_header") is True:
                tag = "th"
                attributes += ' scope="col"'
            elif cell.get("row_header") is True:
                tag = "th"
                attributes += ' scope="row"'
            row_span = cell.get("row_span")
            col_span = cell.get("col_span")
            if row_span > 1:
                attributes += f' rowspan="{row_span}"'
            if col_span > 1:
                attributes += f' colspan="{col_span}"'
            escaped = html_escape(cell.get("text"), quote=True).replace(
                "\n", "<br>"
            )
            html_lines.append(
                f"      <{tag}{attributes}>{escaped}</{tag}>"
            )
        html_lines.append("    </tr>")
    if leading_header_rows == row_count:
        html_lines.append("  </thead>")
    else:
        html_lines.append("  </tbody>")
    html_lines.append("</table>")
    rendered = "\n".join(html_lines)
    csv_output = StringIO(newline="")
    csv_writer(csv_output, lineterminator="\n").writerows(rows)
    csv_value = csv_output.getvalue().rstrip("\n")
    _bounded_table_output_bytes(rendered, deadline)
    _bounded_table_output_bytes(csv_value, deadline)
    return {
        "rows": rows,
        "value": deepcopy(rows),
        "html": rendered,
        "md": rendered,
        "csv": csv_value,
        "row_count": row_count,
        "column_count": column_count,
    }


def _apply_table_grid_serialization(item, cells, slots, row_count, column_count, deadline):
    projection = _serialize_table_grid(
        cells, slots, row_count, column_count, deadline
    )
    for name in _bounded_table_iterable(
        ("rows", "value", "html", "md", "csv", "row_count", "column_count"),
        7,
    ):
        _check_table_deadline(deadline)
        item[name] = projection.get(name)
    return None


def _table_projection_matches_grid(item, slots, cells, row_count, column_count, deadline):
    _check_table_deadline(deadline)
    expected = _serialize_table_grid(
        cells, slots, row_count, column_count, deadline
    )
    coherent = True
    for name in _bounded_table_iterable(
        ("rows", "value", "html", "md", "csv", "row_count", "column_count"),
        7,
    ):
        _check_table_deadline(deadline)
        if item.get(name) != expected.get(name):
            coherent = False
    return coherent


def _diagnostic_table_sidecar(item, table_id, candidate_id, page_index, row_count, column_count, source_objects, evidence, concerns, status, deadline):
    _check_table_deadline(deadline)
    ordered_concerns = list(concerns)
    ordered_concerns.sort()
    custody_row_count = item.get("row_count")
    custody_column_count = item.get("column_count")
    if (
        type(custody_row_count) is not int
        or custody_row_count < 1
        or type(custody_column_count) is not int
        or custody_column_count < 1
    ):
        raise ValueError("table predecessor dimensions differ")
    custody = _table_representation_custody(
        item,
        custody_row_count,
        custody_column_count,
        deadline,
        item_is_plain=True,
    )
    return {
        "policy_id": "p04-table-evidence-v1",
        "version": "1.1",
        "scope": ["P04-US01"],
        "status": status,
        "table_id": table_id,
        "candidate_id": candidate_id,
        "page_index": page_index,
        "grid": {
            "row_count": row_count,
            "column_count": column_count,
            "cell_ids": [],
        },
        "slots": [],
        "source_objects": source_objects,
        "evidence": evidence,
        "span_decisions": [],
        "representation_custody": custody,
        "reconciliation": None,
        "gate": None,
        "continuation": None,
        "concerns": ordered_concerns,
    }


def _table_structure_source_content(table_reference, row_count, column_count, records, deadline):
    _check_table_deadline(deadline)
    normalized_cells = []
    for record in _bounded_table_iterable(records, 65536):
        _check_table_deadline(deadline)
        normalized_cells.append(
            [
                record[0],
                record[1],
                record[2],
                record[3],
                record[4],
                record[5],
                record[6],
                record[7],
                _table_record_bbox(record, deadline),
                record[13],
            ]
        )
    return [
        "p04-structure-source-content-v1",
        table_reference,
        row_count,
        column_count,
        normalized_cells,
    ]


def _table_recovery_words_fit_bbox(words, bbox, deadline):
    _check_table_deadline(deadline)
    if bbox is None:
        return False
    for word in _bounded_table_iterable(words, 64):
        _check_table_deadline(deadline)
        center_x = (word["x0"] + word["x1"]) / 2.0
        center_y = (word["top"] + word["bottom"]) / 2.0
        if not (
            bbox[0] - 1.0 <= center_x <= bbox[2] + 1.0
            and bbox[1] - 1.0 <= center_y <= bbox[3] + 1.0
        ):
            return False
    return True


def _validated_table_recovery_projection(raw_item, base_records, deadline):
    """Validate the private recovery plan and derive an immutable projection.

    The original Docling data/grid remains authoritative and byte-for-byte
    unchanged.  Invalid or tampered plans are ignored, so recovery cannot turn
    unsupported pdfplumber geometry into Docling provenance.
    """

    _check_table_deadline(deadline)
    plan = raw_item.get(_TABLE_RECOVERY_PLAN_KEY)
    if plan is None:
        return [base_records, None]
    if not _table_exact_keys(
        plan,
        (
            "policy_id",
            "page_index",
            "table_ref",
            "predecessor_grid",
            "header",
            "bottom_row",
        ),
        deadline,
    ):
        return [base_records, None]
    data = raw_item.get("data")
    predecessor_rows = data.get("num_rows")
    predecessor_columns = data.get("num_cols")
    page_index = _docling_table_page(raw_item, deadline)
    table_reference = _table_required_reference(raw_item.get("self_ref"), deadline)
    predecessor_grid = plan.get("predecessor_grid")
    if (
        plan.get("policy_id") != "p04-table-recovery-plan-v1"
        or plan.get("page_index") != page_index
        or plan.get("table_ref") != table_reference
        or not _table_exact_keys(
            predecessor_grid, ("row_count", "column_count"), deadline
        )
        or predecessor_grid.get("row_count") != predecessor_rows
        or predecessor_grid.get("column_count") != predecessor_columns
    ):
        return [base_records, None]
    header = plan.get("header")
    bottom_row = plan.get("bottom_row")
    if (
        type(header) is not list
        or len(header) > 16
        or bottom_row is not None and type(bottom_row) is not dict
    ):
        return [base_records, None]
    base_by_location = {}
    for record in _bounded_table_iterable(base_records, 65536):
        location = (record[0], record[1])
        if location in base_by_location:
            return [base_records, None]
        base_by_location[location] = record
    emitted_records = [list(record) for record in base_records]
    emitted_by_location = {
        (record[0], record[1]): record for record in emitted_records
    }
    word_set_specs = []
    seen_word_geometry = {}
    header_by_column = {}
    if header:
        if len(header) != predecessor_columns:
            return [base_records, None]
        for expected_column, entry in enumerate(
            _bounded_table_iterable(header, 16)
        ):
            _check_table_deadline(deadline)
            if not _table_exact_keys(
                entry,
                (
                    "target_row",
                    "target_column",
                    "header_words",
                    "body_control_words",
                ),
                deadline,
            ) or (
                entry.get("target_row") != 0
                or entry.get("target_column") != expected_column
            ):
                return [base_records, None]
            target_record = emitted_by_location.get((0, expected_column))
            body_record = emitted_by_location.get((1, expected_column))
            if (
                target_record is None
                or body_record is None
                or target_record[5] is not False
            ):
                return [base_records, None]
            header_words = _normalized_table_recovery_words(
                entry.get("header_words"), deadline
            )
            body_words = _normalized_table_recovery_words(
                entry.get("body_control_words"), deadline
            )
            if (
                header_words != entry.get("header_words")
                or body_words != entry.get("body_control_words")
                or len(header_words) > 64
                or len(body_words) > 64
                or any(word["bold"] is not True for word in header_words)
                or any(word["bold"] is not False for word in body_words)
                or " ".join(word["text"] for word in header_words)
                != " ".join(_bounded_table_text(target_record[4]).split())
                or " ".join(word["text"] for word in body_words)
                != " ".join(_bounded_table_text(body_record[4]).split())
                or not _table_recovery_words_fit_bbox(
                    header_words,
                    (
                        target_record[9],
                        target_record[10],
                        target_record[9] + target_record[11],
                        target_record[10] + target_record[12],
                    ) if target_record[8] == 1 else None,
                    deadline,
                )
                or not _table_recovery_words_fit_bbox(
                    body_words,
                    (
                        body_record[9],
                        body_record[10],
                        body_record[9] + body_record[11],
                        body_record[10] + body_record[12],
                    ) if body_record[8] == 1 else None,
                    deadline,
                )
            ):
                return [base_records, None]
            for role, words in (
                ("header", header_words),
                ("body_control", body_words),
            ):
                for word in _bounded_table_iterable(words, 64):
                    geometry = _table_recovery_word_geometry(word, deadline)
                    if geometry in seen_word_geometry:
                        return [base_records, None]
                    seen_word_geometry[geometry] = True
                word_set_specs.append(
                    {
                        "role": role,
                        "target_row": 0 if role == "header" else 1,
                        "target_column": expected_column,
                        "words": words,
                    }
                )
            target_record[5] = True
            target_record[14] = True
            header_by_column[expected_column] = entry
    bottom_by_column = {}
    row_pitch = None
    same_line_band = None
    column_starts = None
    if bottom_row is not None:
        if not _table_exact_keys(
            bottom_row,
            (
                "target_row",
                "row_pitch",
                "same_line_band",
                "column_starts",
                "cells",
            ),
            deadline,
        ):
            return [base_records, None]
        row_pitch = bottom_row.get("row_pitch")
        same_line_band = bottom_row.get("same_line_band")
        column_starts = bottom_row.get("column_starts")
        recovered_cells = bottom_row.get("cells")
        if (
            bottom_row.get("target_row") != predecessor_rows
            or type(row_pitch) is not float
            or not isfinite(row_pitch)
            or row_pitch < 4.0
            or row_pitch > 64.0
            or not _table_exact_keys(
                same_line_band, ("top", "bottom", "tolerance"), deadline
            )
            or type(same_line_band.get("top")) is not float
            or type(same_line_band.get("bottom")) is not float
            or same_line_band.get("bottom") <= same_line_band.get("top")
            or same_line_band.get("tolerance") != 1.0
            or type(column_starts) is not list
            or len(column_starts) != predecessor_columns
            or any(type(value) is not float or not isfinite(value) for value in column_starts)
            or column_starts != sorted(column_starts)
            or len(column_starts) != len(set(column_starts))
            or type(recovered_cells) is not list
            or len(recovered_cells) != predecessor_columns
        ):
            return [base_records, None]
        expected_starts = []
        for column in _bounded_table_iterable(range(predecessor_columns), 256):
            last_record = base_by_location.get((predecessor_rows - 1, column))
            if last_record is None or last_record[8] != 1:
                return [base_records, None]
            expected_starts.append(float(last_record[9]))
        first_previous = base_by_location.get((predecessor_rows - 2, 0))
        first_last = base_by_location.get((predecessor_rows - 1, 0))
        if (
            first_previous is None
            or first_last is None
            or first_previous[8] != 1
            or first_last[8] != 1
            or float(first_last[10] - first_previous[10]) != row_pitch
            or expected_starts != column_starts
        ):
            return [base_records, None]
        all_bottom_words = []
        for expected_column, recovered_cell in enumerate(
            _bounded_table_iterable(recovered_cells, 256)
        ):
            if not _table_exact_keys(
                recovered_cell,
                ("target_row", "target_column", "text", "bbox", "words"),
                deadline,
            ) or (
                recovered_cell.get("target_row") != predecessor_rows
                or recovered_cell.get("target_column") != expected_column
                or not _table_bbox_is_valid(recovered_cell.get("bbox"), deadline)
            ):
                return [base_records, None]
            words = _normalized_table_recovery_words(
                recovered_cell.get("words"), deadline
            )
            bbox = recovered_cell.get("bbox")
            if words is None:
                return [base_records, None]
            expected_bbox = {
                "x": min(word["x0"] for word in words),
                "y": min(word["top"] for word in words),
                "width": max(word["x1"] for word in words)
                - min(word["x0"] for word in words),
                "height": max(word["bottom"] for word in words)
                - min(word["top"] for word in words),
                "unit": "pt",
            }
            if (
                words != recovered_cell.get("words")
                or len(words) > 64
                or recovered_cell.get("text")
                != " ".join(word["text"] for word in words)
                or bbox != expected_bbox
            ):
                return [base_records, None]
            for word in _bounded_table_iterable(words, 64):
                geometry = _table_recovery_word_geometry(word, deadline)
                if geometry in seen_word_geometry:
                    return [base_records, None]
                seen_word_geometry[geometry] = True
                all_bottom_words.append(word)
            record = [
                predecessor_rows,
                expected_column,
                1,
                1,
                recovered_cell.get("text"),
                False,
                False,
                False,
                1,
                bbox["x"],
                bbox["y"],
                bbox["width"],
                bbox["height"],
                None,
                False,
            ]
            emitted_records.append(record)
            bottom_by_column[expected_column] = recovered_cell
            word_set_specs.append(
                {
                    "role": "bottom_row",
                    "target_row": predecessor_rows,
                    "target_column": expected_column,
                    "words": words,
                }
            )
        if (
            min(word["top"] for word in all_bottom_words)
            != same_line_band.get("top")
            or max(word["bottom"] for word in all_bottom_words)
            != same_line_band.get("bottom")
            or any(
                abs(word["top"] - same_line_band.get("top")) > 1.0
                or abs(word["bottom"] - same_line_band.get("bottom")) > 1.0
                for word in all_bottom_words
            )
        ):
            return [base_records, None]
    if not word_set_specs or len(word_set_specs) > 48:
        return [base_records, None]
    emitted_records.sort()
    return [
        emitted_records,
        {
            "predecessor_rows": predecessor_rows,
            "predecessor_columns": predecessor_columns,
            "header_by_column": header_by_column,
            "bottom_by_column": bottom_by_column,
            "word_set_specs": word_set_specs,
            "row_pitch": row_pitch,
            "same_line_band": same_line_band,
            "column_starts": column_starts,
        },
    ]


def _table_pdf_word_source_objects(
    recovery,
    source_sha256,
    page_index,
    table_reference,
    deadline,
):
    _check_table_deadline(deadline)
    if type(recovery) is not dict:
        return [[], {}]
    predecessor_rows = recovery.get("predecessor_rows")
    predecessor_columns = recovery.get("predecessor_columns")
    source_pairs = []
    source_by_locator = {}
    for spec in _bounded_table_iterable(recovery.get("word_set_specs"), 48):
        _check_table_deadline(deadline)
        role = spec.get("role")
        target_row = spec.get("target_row")
        target_column = spec.get("target_column")
        public_words = []
        word_ids = []
        for word in _bounded_table_iterable(spec.get("words"), 64):
            bbox = _table_recovery_word_bbox(word, deadline)
            word_id = _canonical_table_sha256(
                [
                    "p04-pdfplumber-word-id-v1",
                    source_sha256,
                    page_index,
                    table_reference,
                    predecessor_rows,
                    predecessor_columns,
                    role,
                    target_row,
                    target_column,
                    bbox,
                ],
                8388608,
                deadline,
            )
            public_words.append(
                {
                    "id": word_id,
                    "text": word.get("text"),
                    "bbox": bbox,
                    "font_name": word.get("font_name"),
                    "bold": word.get("bold"),
                }
            )
            word_ids.append(word_id)
        content_sha256 = _canonical_table_sha256(
            [
                "p04-pdfplumber-word-set-content-v1",
                role,
                target_row,
                target_column,
                [
                    [
                        word.get("id"),
                        word.get("text"),
                        word.get("bbox"),
                        word.get("font_name"),
                        word.get("bold"),
                    ]
                    for word in public_words
                ],
            ],
            8388608,
            deadline,
        )
        source_id = _canonical_table_sha256(
            [
                "p04-pdfplumber-word-set-id-v1",
                source_sha256,
                page_index,
                table_reference,
                predecessor_rows,
                predecessor_columns,
                role,
                target_row,
                target_column,
                word_ids,
            ],
            8388608,
            deadline,
        )
        source_record = {
            "id": source_id,
            "engine": "pdfplumber",
            "object_type": "table_word_set",
            "page_index": page_index,
            "raw_ref": None,
            "role": role,
            "target_row": target_row,
            "target_column": target_column,
            "words": public_words,
            "content_sha256": content_sha256,
        }
        locator = (role, target_row, target_column)
        if locator in source_by_locator:
            raise ValueError("table recovery word-set locator differs")
        source_by_locator[locator] = source_record
        source_pairs.append([source_id, source_record])
    ordered_sources = _unique_ordered_table_records(source_pairs, deadline)
    if ordered_sources[1] or len(ordered_sources[0]) != len(source_pairs):
        raise ValueError("table recovery word-set identity collision")
    return [ordered_sources[0], source_by_locator]


def _table_recovered_structure_evidence(
    recovery,
    pdf_sources,
    structure_source_id,
    source_sha256,
    page_index,
    table_reference,
    table_bbox,
    deadline,
):
    _check_table_deadline(deadline)
    predecessor_rows = recovery.get("predecessor_rows")
    predecessor_columns = recovery.get("predecessor_columns")
    bottom_assignments = []
    for source in _bounded_table_iterable(pdf_sources, 48):
        if source.get("role") != "bottom_row":
            continue
        for word in _bounded_table_iterable(source.get("words"), 64):
            bottom_assignments.append(
                [
                    word.get("id"),
                    source.get("target_column"),
                    word.get("bbox"),
                ]
            )
    bottom_assignments.sort(
        key=lambda assignment: (
            assignment[2]["y"],
            assignment[2]["x"],
            assignment[2]["height"],
            assignment[2]["width"],
        )
    )
    emitted_coordinates = []
    for column in sorted(recovery.get("header_by_column")):
        emitted_coordinates.append([0, column, "column_header"])
    for column in sorted(recovery.get("bottom_by_column")):
        cell = recovery.get("bottom_by_column").get(column)
        emitted_coordinates.append(
            [
                (
                    cell.get("target_row")
                    if type(cell.get("target_row")) is int
                    else cell.get("row")
                ),
                (
                    cell.get("target_column")
                    if type(cell.get("target_column")) is int
                    else cell.get("column")
                ),
                cell.get("bbox"),
                cell.get("text"),
            ]
        )
    recovery_source_ids = [structure_source_id] + [
        source.get("id") for source in pdf_sources
    ]
    recovery_source_ids.sort()
    content_preimage = [
        "p04-recovered-table-structure-content-v1",
        "p04-table-recovery-rule-v1",
        structure_source_id,
        [predecessor_rows, predecessor_columns],
        recovery.get("row_pitch"),
        recovery.get("same_line_band"),
        recovery.get("column_starts"),
        bottom_assignments,
        emitted_coordinates,
        recovery_source_ids,
    ]
    content_sha256 = _canonical_table_sha256(
        content_preimage, 8388608, deadline
    )
    evidence_id = _canonical_table_sha256(
        [
            "p04-recovered-table-structure-evidence-id-v1",
            source_sha256,
            page_index,
            table_reference,
            predecessor_rows,
            predecessor_columns,
            recovery_source_ids,
            content_sha256,
        ],
        8388608,
        deadline,
    )
    return {
        "id": evidence_id,
        "method": "recovered_structure",
        "dimension": "structure",
        "page_index": page_index,
        "bbox": table_bbox,
        "source_object_ids": recovery_source_ids,
        "confidence": 1.0,
        "content_sha256": content_sha256,
    }


def _table_recovered_header_evidence(
    column,
    target_bbox,
    source_by_locator,
    structure_source_id,
    source_sha256,
    page_index,
    table_reference,
    predecessor_rows,
    predecessor_columns,
    deadline,
):
    _check_table_deadline(deadline)
    header_source = source_by_locator.get(("header", 0, column))
    body_source = source_by_locator.get(("body_control", 1, column))
    if type(header_source) is not dict or type(body_source) is not dict:
        raise ValueError("table recovered header sources differ")
    source_ids = [
        structure_source_id,
        header_source.get("id"),
        body_source.get("id"),
    ]
    source_ids.sort()
    content_sha256 = _canonical_table_sha256(
        [
            "p04-recovered-header-content-v1",
            0,
            column,
            structure_source_id,
            header_source.get("content_sha256"),
            body_source.get("content_sha256"),
            target_bbox,
            [True, False],
        ],
        8388608,
        deadline,
    )
    evidence_id = _canonical_table_sha256(
        [
            "p04-recovered-header-evidence-id-v1",
            source_sha256,
            page_index,
            table_reference,
            predecessor_rows,
            predecessor_columns,
            0,
            column,
            source_ids,
            target_bbox,
            content_sha256,
        ],
        8388608,
        deadline,
    )
    return {
        "id": evidence_id,
        "method": "recovered_structure",
        "dimension": "header",
        "page_index": page_index,
        "bbox": target_bbox,
        "source_object_ids": source_ids,
        "confidence": 1.0,
        "content_sha256": content_sha256,
    }


def _project_docling_table(item, raw_item, source_sha256, deadline, predecessor_item=None):
    _check_table_deadline(deadline)
    data = raw_item.get("data")
    predecessor_row_count = data.get("num_rows")
    predecessor_column_count = data.get("num_cols")
    page_index = _docling_table_page(raw_item, deadline)
    table_reference = _table_required_reference(
        raw_item.get("self_ref"), deadline
    )
    table_bbox = _docling_table_bbox(item, deadline)
    engine = item.get("engine")
    cell_source = item.get("source")
    if engine != "docling" or cell_source not in ("native", "ocr"):
        return item
    base_records = _normalized_docling_cells(raw_item, deadline)
    records, recovery = _validated_table_recovery_projection(
        raw_item, base_records, deadline
    )

    def independent_diagnostic_item():
        if predecessor_item is None:
            return item
        # With no admitted recovery plan the enabled and predecessor public
        # items were constructed independently from the same exact raw table.
        # Reuse the already-owned enabled item when equality proves that it is
        # the predecessor projection; this keeps the snapshot independent
        # without another full-table allocation. A recovery delta or any
        # mismatch still receives an isolated predecessor copy.
        if recovery is None and item == predecessor_item:
            return item
        return deepcopy(predecessor_item)

    row_count = predecessor_row_count + (
        1
        if type(recovery) is dict and recovery.get("bottom_by_column")
        else 0
    )
    column_count = predecessor_column_count
    table_identity = [
        "p04-table-id-v1",
        source_sha256,
        page_index,
        engine,
        table_reference,
        table_bbox,
        row_count,
        column_count,
    ]
    candidate_identity = [
        "p04-candidate-id-v1",
        source_sha256,
        page_index,
        engine,
        table_reference,
        table_bbox,
        predecessor_row_count,
        predecessor_column_count,
    ]
    table_id = _canonical_table_sha256(
        table_identity, 8388608, deadline
    )
    candidate_id = _canonical_table_sha256(
        candidate_identity, 8388608, deadline
    )
    geometry_source_content = [
        "p04-geometry-source-content-v1",
        table_bbox,
        page_index,
    ]
    structure_source_content = _table_structure_source_content(
        table_reference,
        predecessor_row_count,
        predecessor_column_count,
        base_records,
        deadline,
    )
    geometry_source_content_sha256 = _canonical_table_sha256(
        geometry_source_content, 8388608, deadline
    )
    (
        structure_source_content_sha256,
        structure_source_size,
    ) = _canonical_table_sha256_and_size(
        structure_source_content, 67108864, deadline
    )
    structure_resource_limited = structure_source_size > 8388608
    geometry_source_id = _canonical_table_sha256(
        [
            "p04-geometry-source-id-v1",
            source_sha256,
            page_index,
            engine,
            table_reference,
            table_bbox,
        ],
        8388608,
        deadline,
    )
    structure_source_id = _canonical_table_sha256(
        [
            "p04-structure-source-id-v1",
            source_sha256,
            page_index,
            engine,
            table_reference,
            predecessor_row_count,
            predecessor_column_count,
        ],
        8388608,
        deadline,
    )
    geometry_evidence_id = _canonical_table_sha256(
        [
            "p04-geometry-evidence-id-v1",
            source_sha256,
            page_index,
            engine,
            table_reference,
            table_bbox,
        ],
        8388608,
        deadline,
    )
    structure_evidence_id = _canonical_table_sha256(
        [
            "p04-structure-evidence-id-v1",
            source_sha256,
            page_index,
            engine,
            table_reference,
            predecessor_row_count,
            column_count,
        ],
        8388608,
        deadline,
    )
    header_evidence_id = _canonical_table_sha256(
        [
            "p04-header-evidence-id-v1",
            source_sha256,
            page_index,
            engine,
            table_reference,
            row_count,
            column_count,
        ],
        8388608,
        deadline,
    )
    if structure_resource_limited:
        diagnostic_item = independent_diagnostic_item()
        source_objects = [
            {
                "id": geometry_source_id,
                "engine": engine,
                "object_type": "table_geometry",
                "page_index": page_index,
                "raw_ref": table_reference,
                "content_sha256": geometry_source_content_sha256,
            },
            {
                "id": structure_source_id,
                "engine": engine,
                "object_type": "table_grid",
                "page_index": page_index,
                "raw_ref": table_reference,
                "content_sha256": structure_source_content_sha256,
            },
        ]
        if source_objects[0].get("id") > source_objects[1].get("id"):
            source_objects.reverse()
        evidence = [
            {
                "id": geometry_evidence_id,
                "method": "embedded_grid",
                "dimension": "geometry",
                "page_index": page_index,
                "bbox": table_bbox,
                "source_object_ids": [geometry_source_id],
                "confidence": 1.0,
                "content_sha256": geometry_source_content_sha256,
            },
            {
                "id": structure_evidence_id,
                "method": "source_grid",
                "dimension": "structure",
                "page_index": page_index,
                "bbox": table_bbox,
                "source_object_ids": [structure_source_id],
                "confidence": 1.0,
                "content_sha256": structure_source_content_sha256,
            },
        ]
        if evidence[0].get("id") > evidence[1].get("id"):
            evidence.reverse()
        diagnostic_item["table_evidence"] = _diagnostic_table_sidecar(
            diagnostic_item,
            table_id,
            candidate_id,
            page_index,
            row_count,
            column_count,
            source_objects,
            evidence,
            ["table_resource_limit_exceeded"],
            "unresolved",
            deadline,
        )
        return diagnostic_item
    pdf_sources, pdf_source_by_locator = _table_pdf_word_source_objects(
        recovery,
        source_sha256,
        page_index,
        table_reference,
        deadline,
    )
    recovered_structure_evidence = None
    recovered_header_evidence_by_column = {}
    if type(recovery) is dict:
        recovered_structure_evidence = _table_recovered_structure_evidence(
            recovery,
            pdf_sources,
            structure_source_id,
            source_sha256,
            page_index,
            table_reference,
            table_bbox,
            deadline,
        )
        structure_evidence_id = recovered_structure_evidence.get("id")
        for column in _bounded_table_iterable(
            sorted(recovery.get("header_by_column")), 16
        ):
            target_record = next(
                record
                for record in records
                if record[0] == 0 and record[1] == column
            )
            recovered_header_evidence_by_column[column] = (
                _table_recovered_header_evidence(
                    column,
                    _table_record_bbox(target_record, deadline),
                    pdf_source_by_locator,
                    structure_source_id,
                    source_sha256,
                    page_index,
                    table_reference,
                    predecessor_row_count,
                    predecessor_column_count,
                    deadline,
                )
            )
    cell_id_preimages = []
    source_id_preimages = []
    content_preimages = []
    text_evidence_preimages = []
    cell_geometry_evidence_preimages = []
    span_decision_preimages = []
    has_header = False
    has_recovered_header = False
    has_native_header = False
    has_missing_bbox = False
    has_out_of_region_bbox = table_bbox is None
    has_unsupported_span = False
    for record in _bounded_table_iterable(records, 65536):
        _check_table_deadline(deadline)
        bbox = _table_record_bbox(record, deadline)
        bbox_belongs_to_table = (
            bbox is not None
            and table_bbox is not None
            and _table_content_bbox_within_region(
                bbox,
                table_bbox,
                deadline,
            )
        )
        if record[13] is None:
            recovered_source = pdf_source_by_locator.get(
                ("bottom_row", record[0], record[1])
            )
            if type(recovered_source) is not dict:
                raise ValueError("table recovered cell source differs")
            identity_tail = [
                source_sha256,
                page_index,
                table_reference,
                predecessor_row_count,
                predecessor_column_count,
                recovered_source.get("id"),
                bbox,
                record[0],
                record[1],
            ]
            cell_id_preimages.append(
                ["p04-recovered-cell-id-v1", identity_tail]
            )
            source_id_preimages.append(
                ["p04-recovered-cell-source-alias-v1", identity_tail]
            )
            content_preimages.append(
                ["p04-recovered-cell-content-alias-v1", identity_tail]
            )
            text_evidence_preimages.append(
                ["p04-recovered-text-evidence-id-v1", identity_tail]
            )
            cell_geometry_evidence_preimages.append(
                ["p04-recovered-geometry-evidence-id-v1", identity_tail]
            )
            span_decision_preimages.append(
                ["p04-recovered-span-decision-unused-v1", identity_tail]
            )
        else:
            identity_tail = [
                source_sha256,
                page_index,
                engine,
                record[13],
                bbox,
                record[0],
                record[1],
                record[2],
                record[3],
            ]
            cell_id_preimages.append(["p04-cell-id-v1", identity_tail])
            source_id_preimages.append(["p04-cell-source-id-v1", identity_tail])
            content_preimages.append(
                [
                    "p04-cell-content-v1",
                    record[13],
                    bbox,
                    record[0],
                    record[1],
                    record[2],
                    record[3],
                    record[4],
                    False if record[14] else record[5],
                    record[6],
                    record[7],
                ]
            )
            text_evidence_preimages.append(
                ["p04-text-evidence-id-v1", identity_tail]
            )
            cell_geometry_evidence_preimages.append(
                ["p04-cell-geometry-evidence-id-v1", identity_tail]
            )
            span_decision_preimages.append(
                ["p04-span-decision-id-v1", identity_tail]
            )
        if record[5] or record[6]:
            has_header = True
            if not record[14]:
                has_native_header = True
        if record[14]:
            has_recovered_header = True
        if record[8] != 1:
            has_missing_bbox = True
        elif not bbox_belongs_to_table:
            has_out_of_region_bbox = True
        if (
            record[2] > 1 or record[3] > 1
        ) and not bbox_belongs_to_table:
            has_unsupported_span = True
    cell_ids = _batch_table_sha256(
        cell_id_preimages, 8388608, deadline
    )
    cell_source_ids = _batch_table_sha256(
        source_id_preimages, 8388608, deadline
    )
    cell_content_hashes = _batch_table_sha256(
        content_preimages, 8388608, deadline
    )
    text_evidence_ids = _batch_table_sha256(
        text_evidence_preimages, 8388608, deadline
    )
    cell_geometry_evidence_ids = _batch_table_sha256(
        cell_geometry_evidence_preimages, 8388608, deadline
    )
    span_decision_ids = _batch_table_sha256(
        span_decision_preimages, 8388608, deadline
    )
    for index, record in enumerate(records):
        if record[13] is not None:
            continue
        recovered_source = pdf_source_by_locator.get(
            ("bottom_row", record[0], record[1])
        )
        cell_source_ids[index] = recovered_source.get("id")
        cell_content_hashes[index] = recovered_source.get("content_sha256")
    identity_collision = (
        len(cell_ids) != len(set(cell_ids))
        or len(cell_source_ids) != len(set(cell_source_ids))
        or len(text_evidence_ids) != len(set(text_evidence_ids))
        or len(cell_geometry_evidence_ids)
        != len(set(cell_geometry_evidence_ids))
        or len(span_decision_ids) != len(set(span_decision_ids))
    )
    source_pairs = []
    evidence_pairs = []
    cells = []
    decision_groups = []
    for values in _bounded_table_iterable(
        list(
            zip(
                records,
                cell_ids,
                cell_source_ids,
                cell_content_hashes,
                text_evidence_ids,
                cell_geometry_evidence_ids,
                span_decision_ids,
            )
        ),
        65536,
    ):
        _check_table_deadline(deadline)
        record, cell_id, source_id, content_hash, text_evidence_id, cell_geometry_evidence_id, decision_id = values
        bbox = _table_record_bbox(record, deadline)
        recovered_bottom_cell = record[13] is None
        source_record = None if recovered_bottom_cell else {
            "id": source_id,
            "engine": engine,
            "object_type": "table_cell",
            "page_index": page_index,
            "raw_ref": record[13],
            "content_sha256": content_hash,
        }
        text_evidence_record = {
            "id": text_evidence_id,
            "method": (
                "native_text"
                if recovered_bottom_cell or cell_source == "native"
                else "ocr_text"
            ),
            "dimension": "text",
            "page_index": page_index,
            "bbox": bbox,
            "source_object_ids": [source_id],
            "confidence": 1.0,
            "content_sha256": content_hash,
        }
        cell_geometry_evidence_record = {
            "id": cell_geometry_evidence_id,
            "method": (
                "recovered_structure"
                if recovered_bottom_cell
                else "embedded_grid"
            ),
            "dimension": "geometry",
            "page_index": page_index,
            "bbox": bbox,
            "source_object_ids": [source_id],
            "confidence": 1.0,
            "content_sha256": content_hash,
        }
        span_claimed = record[2] > 1 or record[3] > 1
        recovered_header_evidence = (
            recovered_header_evidence_by_column.get(record[1])
            if record[14]
            else None
        )
        cell_header_evidence_id = (
            recovered_header_evidence.get("id")
            if type(recovered_header_evidence) is dict
            else header_evidence_id if record[5] or record[6] else None
        )
        evidence_ids = _ordered_table_ids(
            text_evidence_id,
            cell_geometry_evidence_id
            if (span_claimed or recovered_bottom_cell) and bbox is not None
            else None,
            structure_evidence_id
            if span_claimed or recovered_bottom_cell or record[14]
            else None,
            cell_header_evidence_id,
            deadline,
        )
        cell_record = {
            "id": cell_id,
            "row": record[0],
            "column": record[1],
            "row_span": record[2],
            "col_span": record[3],
            "text": record[4],
            "column_header": record[5],
            "row_header": record[6],
            "row_section": record[7],
            "bbox": bbox,
            "source": "native" if recovered_bottom_cell else cell_source,
            "page_index": page_index,
            "evidence_ids": evidence_ids,
            "source_object_ids": [source_id],
            "span_decision_id": decision_id if span_claimed else None,
            "confidence_dimensions": {
                "text": 1.0,
                "geometry": 1.0 if bbox is not None else None,
                "structure": 1.0,
                "header": 1.0 if record[5] or record[6] else None,
            },
        }
        decision_record = {
            "id": decision_id,
            "cell_id": cell_id,
            "claimed_row_span": record[2],
            "claimed_col_span": record[3],
            "emitted_row_span": record[2],
            "emitted_col_span": record[3],
            "outcome": "supported",
            "evidence_ids": _ordered_table_ids(
                cell_geometry_evidence_id,
                structure_evidence_id,
                None,
                None,
                deadline,
            ),
            "concern_codes": [],
        }
        if source_record is not None:
            source_pairs.append([source_id, source_record])
        evidence_pairs.append([text_evidence_id, text_evidence_record])
        if (span_claimed or recovered_bottom_cell) and bbox is not None:
            evidence_pairs.append(
                [cell_geometry_evidence_id, cell_geometry_evidence_record]
            )
        cells.append(cell_record)
        decision_groups.append([decision_record] if span_claimed else [])
    source_pairs = source_pairs + [
        [
            geometry_source_id,
            {
                "id": geometry_source_id,
                "engine": engine,
                "object_type": "table_geometry",
                "page_index": page_index,
                "raw_ref": table_reference,
                "content_sha256": geometry_source_content_sha256,
            },
        ],
        [
            structure_source_id,
            {
                "id": structure_source_id,
                "engine": engine,
                "object_type": "table_grid",
                "page_index": page_index,
                "raw_ref": table_reference,
                "content_sha256": structure_source_content_sha256,
            },
        ],
    ] + [[source.get("id"), source] for source in pdf_sources]
    structure_evidence_record = (
        recovered_structure_evidence
        if type(recovered_structure_evidence) is dict
        else {
            "id": structure_evidence_id,
            "method": "source_grid",
            "dimension": "structure",
            "page_index": page_index,
            "bbox": table_bbox,
            "source_object_ids": [structure_source_id],
            "confidence": 1.0,
            "content_sha256": structure_source_content_sha256,
        }
    )
    evidence_pairs = evidence_pairs + [
        [
            geometry_evidence_id,
            {
                "id": geometry_evidence_id,
                "method": "embedded_grid",
                "dimension": "geometry",
                "page_index": page_index,
                "bbox": table_bbox,
                "source_object_ids": [geometry_source_id],
                "confidence": 1.0,
                "content_sha256": geometry_source_content_sha256,
            },
        ],
        [
            structure_evidence_id,
            structure_evidence_record,
        ],
    ]
    if has_native_header:
        evidence_pairs = evidence_pairs + [
            [
                header_evidence_id,
                {
                    "id": header_evidence_id,
                    "method": "model_structure",
                    "dimension": "header",
                    "page_index": page_index,
                    "bbox": table_bbox,
                    "source_object_ids": [structure_source_id],
                    "confidence": 1.0,
                    "content_sha256": structure_source_content_sha256,
                },
            ]
        ]
    for recovered_header_evidence in recovered_header_evidence_by_column.values():
        evidence_pairs.append(
            [recovered_header_evidence.get("id"), recovered_header_evidence]
        )
    ordered_sources = _unique_ordered_table_records(source_pairs, deadline)
    ordered_evidence = _unique_ordered_table_records(evidence_pairs, deadline)
    source_objects = ordered_sources[0]
    evidence = ordered_evidence[0]
    identity_collision = (
        identity_collision or ordered_sources[1] or ordered_evidence[1]
    )
    span_decisions = sum(decision_groups, [])
    slot_result = _build_table_slots(
        records,
        cell_ids,
        row_count,
        column_count,
        source_sha256,
        page_index,
        table_id,
        candidate_id,
        deadline,
    )
    slots = slot_result[0]
    missing = slot_result[1]
    collision = slot_result[2]
    collision = collision or identity_collision
    concerns = []
    if missing:
        concerns = concerns + [
            "table_ambiguous_border_evidence",
            "table_source_cell_grid_unresolved",
        ]
    if collision:
        concerns = concerns + [
            "table_malformed_source_evidence",
            "table_source_form_grid_topology_unresolved",
        ]
    if has_missing_bbox or has_out_of_region_bbox:
        concerns = concerns + ["table_source_cell_bbox_unresolved"]
    if has_unsupported_span:
        concerns = concerns + ["table_source_span_evidence_unresolved"]
    valid = (
        not missing
        and not collision
        and not has_out_of_region_bbox
        and not has_unsupported_span
    )
    if valid:
        item["cells"] = cells
        _apply_table_grid_serialization(
            item, cells, slots, row_count, column_count, deadline
        )
        if not _table_projection_matches_grid(
            item,
            slots,
            cells,
            row_count,
            column_count,
            deadline,
        ):
            valid = False
            concerns = concerns + ["table_source_cell_grid_unresolved"]
    if not valid:
        status = "structural_failure" if collision else "unresolved"
        diagnostic_item = independent_diagnostic_item()
        sidecar = _diagnostic_table_sidecar(
            diagnostic_item,
            table_id,
            candidate_id,
            page_index,
            row_count,
            column_count,
            source_objects,
            evidence,
            concerns,
            status,
            deadline,
        )
        diagnostic_item["table_evidence"] = sidecar
        return diagnostic_item
    custody = _table_representation_custody(
        item, row_count, column_count, deadline
    )
    concerns.sort()
    sidecar = {
        "policy_id": "p04-table-evidence-v1",
        "version": "1.1",
        "scope": ["P04-US01"],
        "status": "valid",
        "table_id": table_id,
        "candidate_id": candidate_id,
        "page_index": page_index,
        "grid": {
            "row_count": row_count,
            "column_count": column_count,
            "cell_ids": cell_ids,
        },
        "slots": slots,
        "source_objects": source_objects,
        "evidence": evidence,
        "span_decisions": span_decisions,
        "representation_custody": custody,
        "reconciliation": None,
        "gate": None,
        "continuation": None,
        "concerns": concerns,
    }
    _assert_canonical_table_json(sidecar, 8388608, deadline)
    item["table_evidence"] = sidecar
    return item


def _normalized_table_recovery_words(page_words, deadline):
    """Return source-exact, geometry-ordered pdfplumber words or fail closed."""

    _check_table_deadline(deadline)
    if type(page_words) is not list or not page_words or len(page_words) > 65536:
        return None
    normalized = []
    observed_geometry = {}
    for word in _bounded_table_iterable(page_words, 65536):
        _check_table_deadline(deadline)
        if not _table_exact_keys(
            word,
            ("text", "x0", "x1", "top", "bottom", "font_name", "bold"),
            deadline,
        ):
            return None
        text = word.get("text")
        font_name = word.get("font_name")
        bold = word.get("bold")
        try:
            text_bytes = text.encode("utf-8") if type(text) is str else b""
            if type(font_name) is str:
                font_name.encode("utf-8")
        except UnicodeEncodeError:
            return None
        if (
            type(text) is not str
            or not text.strip()
            or len(text_bytes) > 16384
            or _table_text_has_unsafe_control(text, deadline)
            or not _table_font_name_is_safe(font_name, deadline)
            or type(bold) is not bool
            or bold != ("bold" in font_name.casefold())
        ):
            return None
        coordinates = (
            word.get("x0"),
            word.get("x1"),
            word.get("top"),
            word.get("bottom"),
        )
        if any(
            type(value) not in (int, float)
            or type(value) is bool
            or not isfinite(value)
            for value in coordinates
        ):
            return None
        x0, x1, top, bottom = (float(value) for value in coordinates)
        if x0 < 0 or top < 0 or x1 <= x0 or bottom <= top:
            return None
        bbox = {
            "x": x0,
            "y": top,
            "width": x1 - x0,
            "height": bottom - top,
            "unit": "pt",
        }
        geometry = (bbox["y"], bbox["x"], bbox["height"], bbox["width"])
        if geometry in observed_geometry:
            return None
        observed_geometry[geometry] = True
        normalized.append(
            {
                "text": text,
                "x0": x0,
                "x1": x1,
                "top": top,
                "bottom": bottom,
                "font_name": font_name,
                "bold": bold,
            }
        )
    normalized.sort(
        key=lambda word: (
            word["top"],
            word["x0"],
            word["bottom"] - word["top"],
            word["x1"] - word["x0"],
        )
    )
    return normalized


def _table_recovery_word_bbox(word, deadline):
    _check_table_deadline(deadline)
    return {
        "x": word["x0"],
        "y": word["top"],
        "width": word["x1"] - word["x0"],
        "height": word["bottom"] - word["top"],
        "unit": "pt",
    }


def _table_recovery_word_geometry(word, deadline):
    bbox = _table_recovery_word_bbox(word, deadline)
    return (bbox["y"], bbox["x"], bbox["height"], bbox["width"])


def _table_recovery_cell_bbox(raw_cell, deadline):
    _check_table_deadline(deadline)
    if type(raw_cell) is not dict or type(raw_cell.get("bbox")) is not dict:
        return None
    bbox = raw_cell.get("bbox")
    values = (bbox.get("l"), bbox.get("t"), bbox.get("r"), bbox.get("b"))
    if any(
        type(value) not in (int, float)
        or type(value) is bool
        or not isfinite(value)
        for value in values
    ):
        return None
    left, top, right, bottom = (float(value) for value in values)
    if left < 0 or top < 0 or right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _recover_supported_header_ownership(raw_item, page_words_by_page, deadline):
    _check_table_deadline(deadline)
    if type(page_words_by_page) is not dict:
        return None
    data = raw_item.get("data")
    raw_cells = data.get("table_cells")
    row_count = data.get("num_rows")
    column_count = data.get("num_cols")
    page_index = _docling_table_page(raw_item, deadline)
    if (
        type(row_count) is not int
        or row_count < 2
        or type(column_count) is not int
        or column_count < 1
        or column_count > 16
        or type(raw_cells) is not list
        or len(raw_cells) != row_count * column_count
    ):
        return None
    page_words = _normalized_table_recovery_words(
        page_words_by_page.get(page_index), deadline
    )
    if type(page_words) is not list or not page_words:
        return None
    anchors = {}
    complete = True
    has_existing_header = False
    for raw_cell in _bounded_table_iterable(raw_cells, 65536):
        _check_table_deadline(deadline)
        cell_row = raw_cell.get("start_row_offset_idx")
        cell_column = raw_cell.get("start_col_offset_idx")
        if (
            raw_cell.get("row_span") != 1
            or raw_cell.get("col_span") != 1
            or type(cell_row) is not int
            or type(cell_column) is not int
            or anchors.get(f"{cell_row}:{cell_column}") is not None
        ):
            complete = False
        if raw_cell.get("column_header") is True:
            has_existing_header = True
        anchors[f"{cell_row}:{cell_column}"] = raw_cell
    if (
        not complete
        or has_existing_header
        or len(anchors) != row_count * column_count
    ):
        return None
    header_cells = []
    body_cells = []
    for column in _bounded_table_iterable(range(column_count), 16):
        _check_table_deadline(deadline)
        header_cells.append(anchors.get(f"0:{column}"))
        body_cells.append(anchors.get(f"1:{column}"))
    cells_are_plain = True
    for cell in _bounded_table_iterable(header_cells + body_cells, 32):
        _check_table_deadline(deadline)
        if type(cell) is not dict:
            cells_are_plain = False
    if not cells_are_plain:
        return None
    recovered = []
    assigned_geometry = {}
    for pair in _bounded_table_iterable(
        list(zip(range(column_count), header_cells, body_cells)), 16
    ):
        _check_table_deadline(deadline)
        column, header_cell, body_cell = pair
        header_bbox = _table_recovery_cell_bbox(header_cell, deadline)
        body_bbox = _table_recovery_cell_bbox(body_cell, deadline)
        if header_bbox is None or body_bbox is None:
            return None
        header_words = []
        body_words = []
        for word in _bounded_table_iterable(page_words, 65536):
            _check_table_deadline(deadline)
            center_x = (word.get("x0") + word.get("x1")) / 2.0
            center_y = (word.get("top") + word.get("bottom")) / 2.0
            if (
                center_x >= header_bbox[0] - 1.0
                and center_x <= header_bbox[2] + 1.0
                and center_y >= header_bbox[1] - 1.0
                and center_y <= header_bbox[3] + 1.0
            ):
                header_words.append(word)
            if (
                center_x >= body_bbox[0] - 1.0
                and center_x <= body_bbox[2] + 1.0
                and center_y >= body_bbox[1] - 1.0
                and center_y <= body_bbox[3] + 1.0
            ):
                body_words.append(word)
        if (
            not 1 <= len(header_words) <= 64
            or not 1 <= len(body_words) <= 64
        ):
            return None
        for role_words in _bounded_table_iterable(
            (header_words, body_words), 2
        ):
            for word in _bounded_table_iterable(role_words, 64):
                geometry = _table_recovery_word_geometry(word, deadline)
                if geometry in assigned_geometry:
                    return None
                assigned_geometry[geometry] = True
        header_parts = []
        for word in _bounded_table_iterable(header_words, 64):
            _check_table_deadline(deadline)
            header_parts.append(word.get("text"))
            if word.get("bold") is not True:
                return None
        body_parts = []
        for word in _bounded_table_iterable(body_words, 64):
            _check_table_deadline(deadline)
            body_parts.append(word.get("text"))
            if word.get("bold") is not False:
                return None
        observed_header = " ".join(header_parts)
        observed_body = " ".join(body_parts)
        expected_header = " ".join(
            _bounded_table_text(header_cell.get("text")).split()
        )
        expected_body = " ".join(
            _bounded_table_text(body_cell.get("text")).split()
        )
        if observed_header != expected_header or observed_body != expected_body:
            return None
        recovered.append(
            {
                "target_row": 0,
                "target_column": column,
                "header_words": header_words,
                "body_control_words": body_words,
            }
        )
    return recovered


def _recover_supported_bottom_row(raw_item, page_heights, page_words_by_page, deadline):
    _check_table_deadline(deadline)
    if type(page_heights) is not dict or type(page_words_by_page) is not dict:
        return None
    data = raw_item.get("data")
    raw_cells = data.get("table_cells")
    row_count = data.get("num_rows")
    column_count = data.get("num_cols")
    page_index = _docling_table_page(raw_item, deadline)
    page_height = page_heights.get(page_index)
    if (
        type(row_count) is not int
        or row_count < 2
        or type(column_count) is not int
        or column_count < 2
        or column_count > 16
        or type(raw_cells) is not list
        or len(raw_cells) != row_count * column_count
        or type(page_height) not in (int, float)
        or type(page_height) is bool
        or not isfinite(page_height)
        or page_height <= 0
    ):
        return None
    page_words = _normalized_table_recovery_words(
        page_words_by_page.get(page_index), deadline
    )
    if type(page_words) is not list or not page_words:
        return None
    anchors = {}
    complete = True
    for raw_cell in _bounded_table_iterable(raw_cells, 65536):
        _check_table_deadline(deadline)
        cell_row = raw_cell.get("start_row_offset_idx")
        cell_column = raw_cell.get("start_col_offset_idx")
        if (
            raw_cell.get("row_span") != 1
            or raw_cell.get("col_span") != 1
            or type(cell_row) is not int
            or type(cell_column) is not int
            or anchors.get(f"{cell_row}:{cell_column}") is not None
        ):
            complete = False
        anchors[f"{cell_row}:{cell_column}"] = raw_cell
    if not complete or len(anchors) != row_count * column_count:
        return None
    previous_cells = []
    last_cells = []
    for column in _bounded_table_iterable(range(column_count), 16):
        _check_table_deadline(deadline)
        previous_cells.append(anchors.get(f"{row_count - 2}:{column}"))
        last_cells.append(anchors.get(f"{row_count - 1}:{column}"))
    cells_are_plain = True
    for cell in _bounded_table_iterable(previous_cells + last_cells, 32):
        _check_table_deadline(deadline)
        if type(cell) is not dict:
            cells_are_plain = False
    if not cells_are_plain:
        return None
    previous_first_cell = previous_cells[0]
    last_first_cell = last_cells[0]
    previous_first_bbox = previous_first_cell.get("bbox")
    last_first_bbox = last_first_cell.get("bbox")
    if type(previous_first_bbox) is not dict or type(last_first_bbox) is not dict:
        return None
    previous_top = previous_first_bbox.get("t")
    last_top = last_first_bbox.get("t")
    last_bottom = last_first_bbox.get("b")
    if (
        type(previous_top) not in (int, float)
        or type(previous_top) is bool
        or type(last_top) not in (int, float)
        or type(last_top) is bool
        or type(last_bottom) not in (int, float)
        or type(last_bottom) is bool
        or not isfinite(previous_top)
        or not isfinite(last_top)
        or not isfinite(last_bottom)
    ):
        return None
    row_pitch = last_top - previous_top
    if row_pitch < 4.0 or row_pitch > 64.0:
        return None
    provenance = raw_item.get("prov")
    first_provenance = provenance[0]
    table_raw_bbox = first_provenance.get("bbox")
    if type(table_raw_bbox) is not dict:
        return None
    table_left = table_raw_bbox.get("l")
    table_right = table_raw_bbox.get("r")
    table_bottom = page_height - table_raw_bbox.get("b")
    if (
        type(table_left) not in (int, float)
        or type(table_left) is bool
        or type(table_right) not in (int, float)
        or type(table_right) is bool
        or type(table_bottom) not in (int, float)
        or type(table_bottom) is bool
        or not isfinite(table_left)
        or not isfinite(table_right)
        or not isfinite(table_bottom)
    ):
        return None
    candidate_words = []
    for word in _bounded_table_iterable(page_words, 65536):
        _check_table_deadline(deadline)
        if type(word) is not dict:
            continue
        text = word.get("text")
        x0 = word.get("x0")
        x1 = word.get("x1")
        top = word.get("top")
        bottom = word.get("bottom")
        if (
            type(text) is str
            and text.strip()
            and type(x0) in (int, float)
            and type(x0) is not bool
            and type(x1) in (int, float)
            and type(x1) is not bool
            and type(top) in (int, float)
            and type(top) is not bool
            and type(bottom) in (int, float)
            and type(bottom) is not bool
            and isfinite(x0)
            and isfinite(x1)
            and isfinite(top)
            and isfinite(bottom)
            and x0 >= table_left - 1.0
            and x1 <= table_right + 1.0
            and top > last_bottom + 1.0
            and top >= last_top + row_pitch - 2.0
            and top <= last_top + row_pitch + 2.0
            and bottom <= table_bottom + 1.0
        ):
            candidate_words.append(word)
    if not candidate_words:
        return None
    if len(candidate_words) > 1024:
        return None
    candidate_words.sort(
        key=lambda word: _table_recovery_word_geometry(word, deadline)
    )
    candidate_top = candidate_words[0]["top"]
    candidate_bottom = candidate_words[0]["bottom"]
    same_line = True
    for word in _bounded_table_iterable(candidate_words, 65536):
        _check_table_deadline(deadline)
        if (
            abs(word["top"] - candidate_top) > 1.0
            or abs(word["bottom"] - candidate_bottom) > 1.0
        ):
            same_line = False
    if not same_line:
        return None
    column_starts = []
    for cell in _bounded_table_iterable(last_cells, 16):
        _check_table_deadline(deadline)
        raw_bbox = cell.get("bbox")
        if type(raw_bbox) is not dict:
            return None
        column_start = raw_bbox.get("l")
        if (
            type(column_start) not in (int, float)
            or type(column_start) is bool
            or not isfinite(column_start)
        ):
            return None
        column_starts.append(column_start)
    if column_starts != sorted(column_starts) or len(column_starts) != len(
        set(column_starts)
    ):
        return None
    column_groups = []
    for column in _bounded_table_iterable(range(column_count), 16):
        _check_table_deadline(deadline)
        column_groups.append([])
    for word in _bounded_table_iterable(candidate_words, 65536):
        _check_table_deadline(deadline)
        center = (word["x0"] + word["x1"]) / 2.0
        assigned_columns = []
        for column in _bounded_table_iterable(range(column_count), 16):
            _check_table_deadline(deadline)
            lower = column_starts[column]
            upper = (
                (column_starts[column] + column_starts[column + 1]) / 2.0
                if column + 1 < column_count
                else table_right + 1.0
            )
            if center >= lower - 1.0 and center < upper:
                assigned_columns.append(column)
        if len(assigned_columns) != 1:
            return None
        column_groups[assigned_columns[0]].append(word)
    groups_are_complete = True
    for group in _bounded_table_iterable(column_groups, 16):
        _check_table_deadline(deadline)
        if not group:
            groups_are_complete = False
    if not groups_are_complete:
        return None
    recovered_cells = []
    for values in _bounded_table_iterable(
        list(zip(range(column_count), column_groups)), 16
    ):
        _check_table_deadline(deadline)
        column, group = values
        text_parts = []
        if len(group) > 64:
            return None
        for word in _bounded_table_iterable(group, 64):
            _check_table_deadline(deadline)
            text_parts.append(word["text"])
        text = " ".join(text_parts)
        left = min(word["x0"] for word in group)
        top = min(word["top"] for word in group)
        right = max(word["x1"] for word in group)
        bottom = max(word["bottom"] for word in group)
        recovered_cells.append(
            {
                "target_row": row_count,
                "target_column": column,
                "text": text,
                "bbox": {
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                    "unit": "pt",
                },
                "words": group,
            }
        )
    return {
        "target_row": row_count,
        "row_pitch": float(row_pitch),
        "same_line_band": {
            "top": float(min(word["top"] for word in candidate_words)),
            "bottom": float(max(word["bottom"] for word in candidate_words)),
            "tolerance": 1.0,
        },
        "column_starts": [float(value) for value in column_starts],
        "cells": recovered_cells,
    }


def _scoped_table_recovery_mapping(value, page_index, deadline):
    """Validate only the physical page that can support this table candidate."""

    _check_table_deadline(deadline)
    if type(value) is not dict:
        raise TypeError("table recovery page mapping must be an exact dict")
    if len(value) > 4096:
        raise ValueError("table recovery page mapping limit exceeded")
    scoped = {}
    for key, item in _bounded_table_iterable(tuple(value.items()), 4096):
        _check_table_deadline(deadline)
        _assert_plain_table_value(key, deadline)
        if key == page_index:
            # Own only the selected physical-page value. Unrelated page
            # evidence is never cloned or retained by the table transaction.
            scoped[page_index] = _validate_plain_table_value(item, deadline)
    return scoped


def _supported_table_recovery_plan(
    raw_item,
    page_heights,
    page_words_by_page,
    deadline,
):
    recovered_header = _recover_supported_header_ownership(
        raw_item, page_words_by_page, deadline
    )
    recovered_bottom_row = _recover_supported_bottom_row(
        raw_item, page_heights, page_words_by_page, deadline
    )
    recovered_set_count = (
        (2 * len(recovered_header) if type(recovered_header) is list else 0)
        + (
            len(recovered_bottom_row.get("cells"))
            if type(recovered_bottom_row) is dict
            and type(recovered_bottom_row.get("cells")) is list
            else 0
        )
    )
    if 0 < recovered_set_count <= 48:
        data = raw_item.get("data")
        return {
            "policy_id": "p04-table-recovery-plan-v1",
            "page_index": _docling_table_page(raw_item, deadline),
            "table_ref": _table_required_reference(
                raw_item.get("self_ref"), deadline
            ),
            "predecessor_grid": {
                "row_count": data.get("num_rows"),
                "column_count": data.get("num_cols"),
            },
            "header": recovered_header if type(recovered_header) is list else [],
            "bottom_row": recovered_bottom_row,
        }
    return None


def _install_supported_table_recovery_plan(
    raw_item,
    page_heights,
    page_words_by_page,
    deadline,
):
    plan = _supported_table_recovery_plan(
        raw_item,
        page_heights,
        page_words_by_page,
        deadline,
    )
    if plan is not None:
        raw_item[_TABLE_RECOVERY_PLAN_KEY] = plan
    return None


def _prepare_docling_table_inputs(raw_item, page_heights, page_words_by_page, *, table_span_fidelity_enabled=False, table_span_fidelity_deadline=None, table_span_fidelity_document_deadline=None):
    if not table_span_fidelity_enabled:
        return [raw_item, raw_item]
    deadline = _resolve_table_page_deadline(
        table_span_fidelity_deadline,
        table_span_fidelity_document_deadline,
    )
    predecessor_raw_item = _validate_plain_table_value(raw_item, deadline)
    try:
        # `_validate_plain_table_value` admitted the complete untrusted graph
        # immediately above and returned this independent owned copy.  Repeat
        # only the Docling field checks here; every public projection entry
        # point still performs the full graph admission.
        _validate_docling_table_source_fields(predecessor_raw_item, deadline)
    except _TableLocalSourceRejection:
        rejected_candidate = deepcopy(predecessor_raw_item)
        return [predecessor_raw_item, rejected_candidate]
    page_index = _docling_table_page(predecessor_raw_item, deadline)
    page_heights = _scoped_table_recovery_mapping(
        page_heights, page_index, deadline
    )
    page_words_by_page = _scoped_table_recovery_mapping(
        page_words_by_page, page_index, deadline
    )
    recovered_raw_item = deepcopy(predecessor_raw_item)
    _install_supported_table_recovery_plan(
        recovered_raw_item,
        page_heights,
        page_words_by_page,
        deadline,
    )
    _assert_canonical_table_json(recovered_raw_item, 8388608, deadline)
    return [predecessor_raw_item, recovered_raw_item]


def _orchestrate_docling_table_projection(
    raw_item,
    page_heights,
    page_words_by_page,
    native_texts,
    source_document_identity,
    image_regions,
    *,
    table_span_fidelity_deadline=None,
    table_span_fidelity_document_deadline=None,
):
    """Run the internal owned-root Docling projection synchronously.

    The raw root crosses one admission/copy boundary and one canonical closure.
    No raw value, authority token, callback, or caller-selectable trust policy
    is returned or accepted by this private orchestration seam.
    """

    deadline = _resolve_table_page_deadline(
        table_span_fidelity_deadline,
        table_span_fidelity_document_deadline,
    )
    owned_raw = None
    admitted_raw = None
    scoped_page_heights = None
    scoped_page_words = None
    try:
        if type(raw_item) is not dict:
            raise TypeError("table source must be an exact dict")
        owned_raw = _admit_owned_canonical_table_root(raw_item, deadline)
        admitted_raw = _owned_canonical_table_root_value(
            owned_raw, deadline
        )
        from app.services.pipeline import _build_docling_table_predecessor

        try:
            page_index = _docling_table_page(admitted_raw, deadline)
            _validate_docling_table_source_fields(admitted_raw, deadline)
        except _TableLocalSourceRejection:
            # A locally unusable table remains an exact generic predecessor.
            # It receives neither early candidate confidence nor a P04 marker.
            # Mirror `_bbox_from_prov` exactly here.  In particular, generic
            # normalization accepts tuple provenance and propagates malformed
            # first-record/page-number failures; local P04 rejection must not
            # silently relocate either case to page one.
            fallback_provenance = admitted_raw.get("prov") or []
            fallback_page_index = (
                1
                if not fallback_provenance
                else int(fallback_provenance[0].get("page_no") or 1)
            )
            scoped_page_heights = _scoped_table_recovery_mapping(
                page_heights, fallback_page_index, deadline
            )
            scoped_page_words = _scoped_table_recovery_mapping(
                {} if page_words_by_page is None else page_words_by_page,
                fallback_page_index,
                deadline,
            )
            built_page_index, predecessor = _build_docling_table_predecessor(
                admitted_raw,
                scoped_page_heights,
                scoped_page_words,
                native_texts,
                None,
            )
            if built_page_index != fallback_page_index:
                raise ValueError("table predecessor page identity differs")
            predecessor.pop("source_document_identity", None)
            predecessor.pop("table_evidence", None)
            predecessor.pop(_TABLE_PREDECESSOR_SNAPSHOT_KEY, None)
            _assert_canonical_table_json(predecessor, 8388608, deadline)
            return fallback_page_index, predecessor

        scoped_page_heights = _scoped_table_recovery_mapping(
            page_heights, page_index, deadline
        )
        scoped_page_words = _scoped_table_recovery_mapping(
            {} if page_words_by_page is None else page_words_by_page,
            page_index,
            deadline,
        )

        recovery_plan = _supported_table_recovery_plan(
            admitted_raw,
            scoped_page_heights,
            scoped_page_words,
            deadline,
        )
        if recovery_plan is not None:
            _install_owned_table_recovery_plan(
                owned_raw,
                recovery_plan,
                deadline,
            )
        # Close recovery data before the fixed builder or projector sees it.
        # The private admission already completed the only full graph walk;
        # this seam performs only bounded canonical serialization over the
        # independently owned value and its retained size accounting.
        _assert_owned_canonical_table_json(
            owned_raw, 8388608, deadline
        )

        source_sha256 = (
            None
            if source_document_identity is None
            else _assert_source_sha256(source_document_identity, deadline)
        )
        built_page_index, item = _build_docling_table_predecessor(
            admitted_raw,
            scoped_page_heights,
            scoped_page_words,
            native_texts,
            image_regions if source_sha256 is not None else None,
        )
        if built_page_index != page_index or type(item) is not dict:
            raise ValueError("table predecessor page identity differs")
        _assert_canonical_table_json(item, 8388608, deadline)
        predecessor_item = deepcopy(item)
        _check_table_deadline(deadline)
        if source_sha256 is None:
            return page_index, predecessor_item

        item = _project_docling_table(
            item,
            admitted_raw,
            source_sha256,
            deadline,
            predecessor_item,
        )
        _assert_canonical_table_json(item, 8388608, deadline)
        if type(item.get("table_evidence")) is dict:
            if (
                item is predecessor_item
                or "table_evidence" in predecessor_item
                or _TABLE_PREDECESSOR_SNAPSHOT_KEY in predecessor_item
            ):
                raise ValueError("table predecessor snapshot aliases overlay")
            item[_TABLE_PREDECESSOR_SNAPSHOT_KEY] = predecessor_item
        return page_index, item
    finally:
        # Release the only transaction-owned roots before returning to the
        # page loop; outputs contain copied/derived plain values only.
        owned_raw = None
        admitted_raw = None
        scoped_page_heights = None
        scoped_page_words = None


def prepare_docling_table_inputs(raw_item, page_heights, page_words_by_page, *, table_span_fidelity_enabled=False, table_span_fidelity_deadline=None, table_span_fidelity_document_deadline=None):
    if not table_span_fidelity_enabled:
        return [raw_item, raw_item]
    return _prepare_docling_table_inputs(
        raw_item,
        page_heights,
        page_words_by_page,
        table_span_fidelity_enabled=True,
        table_span_fidelity_deadline=table_span_fidelity_deadline,
        table_span_fidelity_document_deadline=table_span_fidelity_document_deadline,
    )


def prepare_docling_table_input(raw_item, page_heights, page_words_by_page, *, table_span_fidelity_enabled=False, table_span_fidelity_deadline=None, table_span_fidelity_document_deadline=None):
    if not table_span_fidelity_enabled:
        return raw_item
    prepared = prepare_docling_table_inputs(
        raw_item,
        page_heights,
        page_words_by_page,
        table_span_fidelity_enabled=True,
        table_span_fidelity_deadline=table_span_fidelity_deadline,
        table_span_fidelity_document_deadline=table_span_fidelity_document_deadline,
    )
    return prepared[1]


def prepare_docling_table(item, raw_item, *, predecessor_item=None, table_span_fidelity_enabled=False, table_span_fidelity_deadline=None, table_span_fidelity_document_deadline=None, table_inputs_are_owned=False):
    if not table_span_fidelity_enabled:
        return item
    if type(table_inputs_are_owned) is not bool:
        raise TypeError("table input ownership policy differs")
    deadline = _resolve_table_page_deadline(
        table_span_fidelity_deadline,
        table_span_fidelity_document_deadline,
    )
    if table_inputs_are_owned:
        # This public compatibility keyword is never authority.  In
        # particular, callers cannot use it to skip graph admission or take
        # ownership of values that remain reachable to them.
        raise ValueError("table input ownership bypass is unavailable")
    item = _validate_plain_table_value(item, deadline)
    if predecessor_item is not None:
        predecessor_item = _validate_plain_table_value(
            predecessor_item, deadline
        )
    try:
        _validate_docling_table_source(raw_item, deadline)
    except _TableLocalSourceRejection:
        fallback_item = (
            predecessor_item if predecessor_item is not None else item
        )
        fallback_item.pop("source_document_identity", None)
        _assert_canonical_table_json(fallback_item, 8388608, deadline)
        return fallback_item
    # Admission above observes the complete caller graph exactly once.  Own
    # that admitted graph before projection so later caller mutation cannot
    # affect representation or custody decisions.
    raw_item = deepcopy(raw_item)
    _check_table_deadline(deadline)
    source_document_identity = item.pop("source_document_identity", None)
    if source_document_identity is None:
        uncustodied_item = (
            predecessor_item if predecessor_item is not None else item
        )
        uncustodied_item.pop("source_document_identity", None)
        uncustodied_item.pop("table_evidence", None)
        uncustodied_item.pop(_TABLE_PREDECESSOR_SNAPSHOT_KEY, None)
        _assert_canonical_table_json(uncustodied_item, 8388608, deadline)
        return uncustodied_item
    source_document_identity = _assert_source_sha256(
        source_document_identity, deadline
    )
    item = _project_docling_table(
        item,
        raw_item,
        source_document_identity,
        deadline,
        predecessor_item,
    )
    _assert_canonical_table_json(item, 8388608, deadline)
    return item


def prepare_vector_table(item, raw_table, *, table_span_fidelity_enabled=False, table_span_fidelity_deadline=None, table_span_fidelity_document_deadline=None):
    if not table_span_fidelity_enabled:
        return item
    deadline = _resolve_table_page_deadline(
        table_span_fidelity_deadline,
        table_span_fidelity_document_deadline,
    )
    item = _validate_plain_table_value(item, deadline)
    _assert_canonical_table_json(item, 8388608, deadline)
    validated_item_output = _assert_plain_table_value(item, deadline)
    return item


def _table_bbox_fits_page(value, page_width, page_height, deadline):
    _check_table_deadline(deadline)
    if (
        type(page_width) not in (int, float)
        or type(page_width) is bool
        or not isfinite(page_width)
        or page_width <= 0
        or type(page_height) not in (int, float)
        or type(page_height) is bool
        or not isfinite(page_height)
        or page_height <= 0
    ):
        return False
    if value is None:
        return True
    if type(value) is not dict:
        return False
    x = value.get("x")
    y = value.get("y")
    width = value.get("width")
    height = value.get("height")
    return (
        type(x) in (int, float)
        and type(x) is not bool
        and isfinite(x)
        and x >= 0
        and type(y) in (int, float)
        and type(y) is not bool
        and isfinite(y)
        and y >= 0
        and type(width) in (int, float)
        and type(width) is not bool
        and isfinite(width)
        and width > 0
        and type(height) in (int, float)
        and type(height) is not bool
        and isfinite(height)
        and height > 0
        and value.get("unit") == "pt"
        and x + width <= page_width + 0.000001
        and y + height <= page_height + 0.000001
    )


def _table_shared_page_deadline(page_index, page_deadlines, deadline):
    _check_table_deadline(deadline)
    if page_deadlines is None:
        return deadline
    if (
        type(page_deadlines) is not dict
        or len(page_deadlines) > 65536
        or type(page_index) is not int
        or page_index < 1
    ):
        raise ValueError("table page deadline map differs")
    page_deadline = page_deadlines.get(page_index)
    if page_deadline is None:
        page_deadline = min(deadline, perf_counter() + 0.500)
        page_deadlines[page_index] = page_deadline
    if (
        type(page_deadline) not in (int, float)
        or type(page_deadline) is bool
        or not isfinite(float(page_deadline))
        or float(page_deadline) > deadline
    ):
        raise ValueError("table page deadline differs")
    page_deadline = float(page_deadline)
    _check_table_deadline(page_deadline)
    return page_deadline


def _complete_table_page_segment(
    page_deadlines,
    active_page_index,
    segment_started,
    segment_finished,
    document_deadline,
):
    if page_deadlines is None:
        return None
    if (
        type(page_deadlines) is not dict
        or len(page_deadlines) > 65536
        or (
            active_page_index is not None
            and (
                type(active_page_index) is not int
                or active_page_index < 1
                or active_page_index not in page_deadlines
            )
        )
        or type(segment_started) not in (int, float)
        or type(segment_started) is bool
        or not isfinite(float(segment_started))
        or type(segment_finished) not in (int, float)
        or type(segment_finished) is bool
        or not isfinite(float(segment_finished))
        or float(segment_finished) < float(segment_started)
        or type(document_deadline) not in (int, float)
        or type(document_deadline) is bool
        or not isfinite(float(document_deadline))
    ):
        raise ValueError("table page segment differs")
    _check_table_deadline(document_deadline)
    elapsed = float(segment_finished) - float(segment_started)
    validated_deadlines = {}
    for page_index, page_deadline in tuple(page_deadlines.items()):
        _check_table_deadline(document_deadline)
        if (
            type(page_index) is not int
            or page_index < 1
            or type(page_deadline) not in (int, float)
            or type(page_deadline) is bool
            or not isfinite(float(page_deadline))
            or float(page_deadline) > float(document_deadline)
        ):
            raise ValueError("table page segment differs")
        validated_deadlines[page_index] = float(page_deadline)
    for page_index, page_deadline in validated_deadlines.items():
        _check_table_deadline(document_deadline)
        if page_index != active_page_index:
            page_deadlines[page_index] = min(
                float(document_deadline),
                page_deadline + elapsed,
            )
    if (
        active_page_index is not None
        and float(segment_finished) > validated_deadlines[active_page_index]
    ):
        raise TimeoutError("table page deadline exceeded")
    return None


def _seal_table_page_overlay(
    page,
    source_sha256,
    deadline,
    retain_snapshot,
    page_deadlines,
    sidecar_bytes,
    has_table_overlay,
):
    if type(page) is not dict:
        return sidecar_bytes
    page_index = page.get("page_index")
    page_width = page.get("page_width")
    page_height = page.get("page_height")
    page_geometry_valid = (
        type(page_index) is int
        and page_index >= 1
        and type(page_width) in (int, float)
        and type(page_width) is not bool
        and isfinite(page_width)
        and page_width > 0
        and type(page_height) in (int, float)
        and type(page_height) is not bool
        and isfinite(page_height)
        and page_height > 0
        and page.get("unit") == "pt"
    )
    items = page.get("items")
    if type(items) is not list:
        return sidecar_bytes
    operation_deadline = (
        _table_shared_page_deadline(page_index, page_deadlines, deadline)
        if has_table_overlay
        else deadline
    )
    for item in _bounded_table_iterable(items, 65536):
        _check_table_deadline(operation_deadline)
        if type(item) is not dict:
            continue
        if "table_evidence" not in item:
            if _TABLE_PREDECESSOR_SNAPSHOT_KEY in item:
                _reject_table_overlay(item, operation_deadline)
            continue
        table_evidence = item.get("table_evidence")
        if type(table_evidence) is not dict:
            _reject_table_overlay(item, operation_deadline)
            continue
        _replay_table_overlay(
            item,
            table_evidence,
            operation_deadline,
            source_sha256,
            True,
        )
        retained = item.get("table_evidence")
        if type(retained) is not dict:
            continue
        geometry_valid = page_geometry_valid and (
            retained.get("page_index") == page_index
        ) and _table_bbox_fits_page(
            item.get("bbox"), page_width, page_height, operation_deadline
        )
        cells = item.get("cells")
        if type(cells) is not list:
            geometry_valid = False
            cells = []
        for cell in _bounded_table_iterable(cells, 65536):
            _check_table_deadline(operation_deadline)
            if type(cell) is not dict or not _table_bbox_fits_page(
                cell.get("bbox"), page_width, page_height, operation_deadline
            ):
                geometry_valid = False
        evidence = retained.get("evidence")
        if type(evidence) is not list:
            geometry_valid = False
            evidence = []
        for evidence_record in _bounded_table_iterable(evidence, 65536):
            _check_table_deadline(operation_deadline)
            if type(evidence_record) is not dict or not _table_bbox_fits_page(
                evidence_record.get("bbox"),
                page_width,
                page_height,
                operation_deadline,
            ):
                geometry_valid = False
        if not geometry_valid:
            _reject_table_overlay(item, operation_deadline)
            continue
        try:
            public_item = _table_without_snapshot(item, operation_deadline)
            _canonical_table_json_size(
                public_item, 8388608, operation_deadline
            )
            retained_sidecar_bytes = _canonical_table_json_size(
                retained, 8388608, operation_deadline
            )
        except TimeoutError:
            raise
        except (TypeError, ValueError):
            _reject_table_overlay(item, perf_counter() + 0.500)
            continue
        sidecar_bytes += retained_sidecar_bytes
        if sidecar_bytes > _TABLE_DOCUMENT_SIDECAR_MAX_BYTES:
            raise _TableDocumentResourceRejection(
                "table document sidecar aggregate limit exceeded"
            )
    # Final snapshot removal is the caller's document transaction commit.
    # Keeping every snapshot through this page loop lets a later same-page or
    # document timeout restore earlier candidates exactly.
    return sidecar_bytes


def _seal_table_page_overlays(
    pages,
    source_sha256,
    deadline,
    retain_snapshot=True,
    page_deadlines=None,
):
    _check_table_deadline(deadline)
    sidecar_bytes = 0
    for page in _bounded_table_iterable(pages, 65536):
        _check_table_deadline(deadline)
        segment_started = perf_counter()
        items = page.get("items") if type(page) is dict else None
        has_table_overlay = type(items) is list and any(
            type(item) is dict
            and (
                "table_evidence" in item
                or _TABLE_PREDECESSOR_SNAPSHOT_KEY in item
            )
            for item in items[:65536]
        )
        page_index = page.get("page_index") if type(page) is dict else None
        active_page_index = (
            page_index
            if has_table_overlay
            and type(page_index) is int
            and page_index >= 1
            else None
        )
        try:
            sidecar_bytes = _seal_table_page_overlay(
                page,
                source_sha256,
                deadline,
                retain_snapshot,
                page_deadlines,
                sidecar_bytes,
                has_table_overlay,
            )
        finally:
            _complete_table_page_segment(
                page_deadlines,
                active_page_index,
                segment_started,
                perf_counter(),
                deadline,
            )
    return sidecar_bytes


_TABLE_RECONCILIATION_ABSOLUTE_THRESHOLD = 0.58
_TABLE_RECONCILIATION_SELECTION_MARGIN = 0.10
_SELECTED_VECTOR_PUBLIC_KEYS = (
    "type",
    "bbox",
    "source",
    "confidence",
    "rows",
    "cells",
    "row_bboxes",
    "row_count",
    "column_count",
    "parse_concerns",
    "engine",
    "embedded_images",
    "value",
    "md",
    "html",
    "csv",
)


def _table_reconciliation_bbox(value):
    if type(value) is not dict:
        return None
    x = value.get("x")
    y = value.get("y")
    width = value.get("width", value.get("w"))
    height = value.get("height", value.get("h"))
    if any(
        type(number) not in (int, float)
        or type(number) is bool
        or not isfinite(number)
        for number in (x, y, width, height)
    ):
        return None
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    unit = value.get("unit", "pt")
    if unit != "pt":
        return None
    return {
        "x": float(x),
        "y": float(y),
        "width": float(width),
        "height": float(height),
        "unit": "pt",
    }


def _table_reconciliation_overlap(first, second):
    if first is None or second is None:
        return 0.0
    left = max(first["x"], second["x"])
    top = max(first["y"], second["y"])
    right = min(
        first["x"] + first["width"],
        second["x"] + second["width"],
    )
    bottom = min(
        first["y"] + first["height"],
        second["y"] + second["height"],
    )
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    smaller = min(
        first["width"] * first["height"],
        second["width"] * second["height"],
    )
    return intersection / smaller if smaller > 0 else 0.0


def _selected_vector_public_projection_matches(
    candidate,
    expected,
    *,
    attached_keys=(),
):
    if type(candidate) is not dict or type(expected) is not dict:
        return False
    try:
        allowed_attached = set(attached_keys)
        return (
            set(candidate) == set(expected) | allowed_attached
            and all(
                candidate.get(key) == expected.get(key) for key in expected
            )
        )
    except (MemoryError, RecursionError, TypeError, ValueError):
        return False


def _table_reconciliation_text(value):
    if type(value) is not str:
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if len(encoded) > 16384 or any(
        ord(character) < 0x20
        and character not in ("\t", "\n", "\r")
        or ord(character) == 0x7F
        for character in value
    ):
        return None
    return " ".join(value.casefold().split())


def _table_reconciliation_rows(value):
    if type(value) is not list or not value or len(value) > 4096:
        return None
    rows = []
    column_count = None
    for row in value:
        if type(row) is not list or not row or len(row) > 256:
            return None
        if column_count is None:
            column_count = len(row)
        if len(row) != column_count:
            return None
        normalized_row = []
        for cell in row:
            normalized = _table_reconciliation_text(cell)
            if normalized is None:
                return None
            normalized_row.append(normalized)
        rows.append(normalized_row)
    if column_count is None or len(rows) * column_count > 65536:
        return None
    return rows


def _table_reconciliation_raw_vector(raw_table):
    try:
        if type(raw_table) is RawTable:
            page_index = raw_table.page_index
            bbox = raw_table.bbox
            rows = raw_table.rows
            row_bboxes = raw_table.row_bboxes
            parse_concerns = raw_table.parse_concerns
            cell_bboxes = raw_table.cell_bboxes
            geometry_inferred = raw_table.geometry_inferred
            logical_rows_recovered = raw_table.logical_rows_recovered
        elif type(raw_table) in (dict, defaultdict):
            page_index = raw_table.get("page_index")
            bbox = raw_table.get("bbox")
            rows = raw_table.get("rows")
            row_bboxes = raw_table.get("row_bboxes")
            parse_concerns = raw_table.get("parse_concerns")
            cell_bboxes = raw_table.get("cell_bboxes", ())
            geometry_inferred = raw_table.get("geometry_inferred")
            logical_rows_recovered = raw_table.get(
                "logical_rows_recovered", False
            )
        else:
            return None
        normalized_rows = _table_reconciliation_rows(rows)
        normalized_bbox = _table_reconciliation_bbox(bbox)
        if (
            type(page_index) is not int
            or page_index < 1
            or normalized_rows is None
            or normalized_bbox is None
            or type(row_bboxes) is not list
            or type(parse_concerns) is not list
            or type(cell_bboxes) not in (list, tuple)
            or geometry_inferred not in (None, True, False)
            or type(logical_rows_recovered) is not bool
        ):
            return None
        normalized_cell_bboxes = []
        if cell_bboxes:
            if len(cell_bboxes) != len(normalized_rows):
                return None
            for raw_row, normalized_row in zip(
                cell_bboxes, normalized_rows, strict=True
            ):
                if type(raw_row) not in (list, tuple) or len(raw_row) != len(
                    normalized_row
                ):
                    return None
                normalized_cell_bboxes.append(
                    [_table_reconciliation_bbox(cell) for cell in raw_row]
                )
        return {
            "raw": raw_table,
            "page_index": page_index,
            "bbox": normalized_bbox,
            "rows": deepcopy(rows),
            "normalized_rows": normalized_rows,
            "cell_bboxes": normalized_cell_bboxes,
            "geometry_inferred": geometry_inferred,
            "logical_rows_recovered": logical_rows_recovered,
        }
    except (AttributeError, MemoryError, RecursionError, TypeError, ValueError):
        return None


def _selected_vector_authority_projection(
    raw_record,
    candidate_id,
    content_sha256,
    page_index,
    source_document_identity,
    deadline,
):
    """Freeze one complete selected RawTable without retaining its object."""

    _check_table_deadline(deadline)
    if type(raw_record) is not dict or type(raw_record.get("raw")) is not RawTable:
        return None
    try:
        source_sha256 = _assert_source_sha256(
            source_document_identity, deadline
        )
    except (TypeError, ValueError):
        return None
    raw_table = raw_record["raw"]
    rows = raw_record.get("rows")
    normalized_rows = raw_record.get("normalized_rows")
    table_bbox = raw_record.get("bbox")
    raw_row_bboxes = raw_table.row_bboxes
    cell_bboxes = raw_record.get("cell_bboxes")
    if (
        not _is_table_sha256(candidate_id, deadline)
        or not _is_table_sha256(content_sha256, deadline)
        or type(page_index) is not int
        or page_index < 1
        or raw_record.get("page_index") != page_index
        or raw_table.page_index != page_index
        or type(rows) is not list
        or type(normalized_rows) is not list
        or not rows
        or len(rows) != len(normalized_rows)
        or type(raw_row_bboxes) is not list
        or len(raw_row_bboxes) != len(rows)
        or type(cell_bboxes) is not list
        or len(cell_bboxes) != len(rows)
        or type(raw_table.parse_concerns) is not list
        or raw_table.parse_concerns != []
        or raw_table.geometry_inferred not in (None, True, False)
        or type(raw_table.logical_rows_recovered) is not bool
        or (
            raw_table.geometry_inferred is True
            and raw_table.logical_rows_recovered is not True
        )
    ):
        return None
    column_count = len(rows[0]) if type(rows[0]) is list else 0
    if (
        column_count < 1
        or column_count > 256
        or len(rows) > 4096
        or len(rows) * column_count > 10_000
        or any(type(row) is not list or len(row) != column_count for row in rows)
    ):
        return None
    row_bboxes = [
        _table_reconciliation_bbox(value) for value in raw_row_bboxes
    ]
    if any(value is None for value in row_bboxes):
        return None
    normalized_cell_bboxes = []
    for row_index, raw_boxes in enumerate(cell_bboxes):
        _check_table_deadline(deadline)
        if type(raw_boxes) is not list or len(raw_boxes) != column_count:
            return None
        normalized_boxes = []
        for cell_bbox in raw_boxes:
            if type(cell_bbox) is not dict:
                return None
            normalized = _table_reconciliation_bbox(cell_bbox)
            if normalized is None:
                return None
            normalized_boxes.append(normalized)
        normalized_cell_bboxes.append(normalized_boxes)

    def contains(outer, inner):
        return (
            inner["x"] >= outer["x"] - 0.05
            and inner["y"] >= outer["y"] - 0.05
            and inner["x"] + inner["width"]
            <= outer["x"] + outer["width"] + 0.05
            and inner["y"] + inner["height"]
            <= outer["y"] + outer["height"] + 0.05
        )

    tolerance = 0.05

    def close(first, second):
        return abs(first - second) <= tolerance

    for row_index, row_bbox in enumerate(row_bboxes):
        _check_table_deadline(deadline)
        row_left = row_bbox["x"]
        row_top = row_bbox["y"]
        row_right = row_left + row_bbox["width"]
        row_bottom = row_top + row_bbox["height"]
        if (
            not contains(table_bbox, row_bbox)
            or not close(row_left, table_bbox["x"])
            or not close(
                row_right,
                table_bbox["x"] + table_bbox["width"],
            )
            or (
                row_index == 0
                and not close(row_top, table_bbox["y"])
            )
            or (
                row_index > 0
                and not close(
                    row_top,
                    row_bboxes[row_index - 1]["y"]
                    + row_bboxes[row_index - 1]["height"],
                )
            )
            or (
                row_index == len(row_bboxes) - 1
                and not close(
                    row_bottom,
                    table_bbox["y"] + table_bbox["height"],
                )
            )
        ):
            return None
        row_cells = normalized_cell_bboxes[row_index]
        for column_index, cell_bbox in enumerate(row_cells):
            cell_left = cell_bbox["x"]
            cell_top = cell_bbox["y"]
            cell_right = cell_left + cell_bbox["width"]
            cell_bottom = cell_top + cell_bbox["height"]
            if (
                not contains(table_bbox, cell_bbox)
                or not contains(row_bbox, cell_bbox)
                or not close(cell_top, row_top)
                or not close(cell_bottom, row_bottom)
                or (
                    column_index == 0
                    and not close(cell_left, row_left)
                )
                or (
                    column_index > 0
                    and not close(
                        cell_left,
                        row_cells[column_index - 1]["x"]
                        + row_cells[column_index - 1]["width"],
                    )
                )
                or (
                    column_index == len(row_cells) - 1
                    and not close(cell_right, row_right)
                )
            ):
                return None
            if row_index > 0:
                prior_cell = normalized_cell_bboxes[row_index - 1][column_index]
                if (
                    not close(cell_left, prior_cell["x"])
                    or not close(cell_right, prior_cell["x"] + prior_cell["width"])
                ):
                    return None
    raw_public_item = _table_reconciliation_vector_item(raw_record)
    if type(raw_public_item) is not dict:
        return None
    public_projection = {
        key: deepcopy(raw_public_item.get(key))
        for key in _SELECTED_VECTOR_PUBLIC_KEYS
    }
    if (
        set(raw_public_item) != set(_SELECTED_VECTOR_PUBLIC_KEYS)
        or public_projection["type"] != "table"
        or public_projection["source"] != "native"
        or public_projection["confidence"] is not None
        or public_projection["engine"] != "pdfplumber"
        or public_projection["cells"] != []
        or public_projection["parse_concerns"] != []
        or public_projection["embedded_images"] != []
        or public_projection["rows"] != rows
        or public_projection["row_count"] != len(rows)
        or public_projection["column_count"] != column_count
        or _table_reconciliation_bbox(public_projection["bbox"])
        != table_bbox
        or [
            _table_reconciliation_bbox(value)
            for value in public_projection["row_bboxes"]
        ]
        != row_bboxes
    ):
        return None
    frozen = {
        "schema_version": "1.0",
        "policy_id": "p02-selected-vector-representation-v1",
        "page_index": page_index,
        "source_sha256": source_sha256,
        "candidate_id": candidate_id,
        "content_sha256": content_sha256,
        "bbox": deepcopy(table_bbox),
        "rows": deepcopy(rows),
        "normalized_rows": deepcopy(normalized_rows),
        "row_bboxes": deepcopy(row_bboxes),
        "cell_bboxes": deepcopy(normalized_cell_bboxes),
        "geometry_inferred": raw_table.geometry_inferred,
        "logical_rows_recovered": raw_table.logical_rows_recovered,
        "public_projection": public_projection,
    }
    frozen["vector_sha256"] = _canonical_table_sha256(
        [
            frozen["policy_id"],
            frozen["page_index"],
            frozen["source_sha256"],
            frozen["candidate_id"],
            frozen["content_sha256"],
            frozen["bbox"],
            frozen["rows"],
            frozen["row_bboxes"],
            frozen["cell_bboxes"],
            frozen["geometry_inferred"],
            frozen["logical_rows_recovered"],
            frozen["public_projection"],
        ],
        8388608,
        deadline,
    )
    return frozen


def _table_reconciliation_vector_item(raw_record):
    try:
        from app.services.pipeline import _vector_table_item

        return _vector_table_item(
            raw_record["raw"],
            table_span_fidelity_enabled=True,
        )
    except (MemoryError, RecursionError, TypeError, ValueError):
        return None


def _table_reconciliation_candidate(
    item,
    page_index,
    deadline,
    raw_vector=None,
    selected_vector_raw=None,
):
    _check_table_deadline(deadline)
    if type(item) is not dict:
        return None
    try:
        candidate = _validate_plain_table_value(item, deadline)
    except (MemoryError, RecursionError, TypeError, ValueError):
        return None
    if candidate.get("type") != "table":
        return None
    engine = candidate.get("engine")
    if engine not in ("docling", "pdfplumber"):
        engine = "unknown"
    bbox = _table_reconciliation_bbox(candidate.get("bbox"))
    normalized_rows = _table_reconciliation_rows(candidate.get("rows"))
    if normalized_rows is None:
        return None
    row_count = len(normalized_rows)
    column_count = len(normalized_rows[0])
    if (
        candidate.get("row_count") != row_count
        or candidate.get("column_count") != column_count
    ):
        return None
    sidecar = candidate.get("table_evidence")
    if type(sidecar) is dict and sidecar.get("page_index") != page_index:
        return None
    cells = candidate.get("cells")
    if type(cells) is not list or len(cells) > 65536:
        return None
    normalized_cells = []
    occupied_slots = 0
    explicit_geometry = 0
    explicit_provenance = 0
    header_count = 0
    span_count = 0
    cells_valid = True
    for cell in cells:
        _check_table_deadline(deadline)
        if type(cell) is not dict:
            cells_valid = False
            continue
        row = cell.get("row")
        column = cell.get("column")
        row_span = cell.get("row_span")
        col_span = cell.get("col_span")
        text = _table_reconciliation_text(cell.get("text"))
        if (
            type(row) is not int
            or type(column) is not int
            or type(row_span) is not int
            or type(col_span) is not int
            or row < 0
            or column < 0
            or row_span < 1
            or col_span < 1
            or row + row_span > row_count
            or column + col_span > column_count
            or text is None
        ):
            cells_valid = False
            continue
        normalized_cells.append(
            [
                row,
                column,
                row_span,
                col_span,
                text,
                cell.get("column_header") is True,
                cell.get("row_header") is True,
                cell.get("row_section") is True,
            ]
        )
        occupied_slots += row_span * col_span
        explicit_geometry += _table_reconciliation_bbox(cell.get("bbox")) is not None
        explicit_provenance += bool(cell.get("source_object_ids")) and bool(
            cell.get("evidence_ids")
        )
        header_count += (
            cell.get("column_header") is True or cell.get("row_header") is True
        )
        span_count += row_span > 1 or col_span > 1
    if cells and not cells_valid:
        return None
    raw_cell_bboxes = (
        raw_vector.get("cell_bboxes")
        if type(raw_vector) is dict
        else []
    )
    raw_geometry_count = sum(
        cell_bbox is not None
        for row in raw_cell_bboxes
        for cell_bbox in row
    )
    slot_count = row_count * column_count
    if not cells:
        occupied_slots = slot_count
    geometry_coverage = max(
        explicit_geometry / len(cells) if cells else 0.0,
        raw_geometry_count / slot_count if slot_count else 0.0,
    )
    geometry_score = (
        1.0
        if bbox is not None and geometry_coverage == 1.0
        else 0.65
        if bbox is not None
        else 0.0
    )
    cell_coverage = min(1.0, occupied_slots / slot_count) if slot_count else 0.0
    span_score = (
        1.0
        if cells and all(
            record[2] >= 1 and record[3] >= 1 for record in normalized_cells
        )
        else 0.75
    )
    provenance_score = (
        min(1.0, 0.55 + 0.45 * explicit_provenance / len(cells))
        if cells
        else 0.85
        if raw_geometry_count == slot_count and slot_count
        else 0.50
    )
    content_sha256 = _canonical_table_sha256(
        [
            "p04-us02-candidate-content-v1",
            normalized_rows,
            normalized_cells,
            raw_cell_bboxes,
        ],
        8388608,
        deadline,
    )
    sidecar_candidate_id = (
        sidecar.get("candidate_id") if type(sidecar) is dict else None
    )
    structural_identity = [
        "p04-us02-candidate-v1",
        page_index,
        engine,
        bbox,
        row_count,
        column_count,
        content_sha256,
    ]
    candidate_id = (
        sidecar_candidate_id
        if _is_table_sha256(sidecar_candidate_id, deadline)
        else _canonical_table_sha256(
            structural_identity,
            8388608,
            deadline,
        )
    )
    cell_values = [value for row in normalized_rows for value in row if value]
    tokens = {
        token
        for value in cell_values
        for token in value.split()
        if token
    }
    evidence_ids = []
    if type(sidecar) is dict and type(sidecar.get("evidence")) is list:
        evidence_ids = sorted(
            {
                record.get("id")
                for record in sidecar.get("evidence")
                if type(record) is dict
                and _is_table_sha256(record.get("id"), deadline)
            }
        )[:64]
    candidate_summary = {
        "candidate_id": candidate_id,
        "engine": engine,
        "bbox": bbox,
        "rows": deepcopy(candidate.get("rows")),
        "cells": deepcopy(cells[:4096]),
        "row_count": row_count,
        "column_count": column_count,
        "content_sha256": content_sha256,
    }
    for name in (
        "caption_ids",
        "source_note_ids",
        "footnote_ids",
        "relationships",
    ):
        value = candidate.get(name)
        if type(value) is list and len(value) <= 64:
            candidate_summary[name] = deepcopy(value)
    return {
        "item": candidate,
        # Private only: the reconciliation cluster uses this exact raw match
        # to mint a selected-vector authority sink.  It is never copied into
        # the public score/candidate sidecar.
        "raw_vector": selected_vector_raw,
        "page_index": page_index,
        "candidate_id": candidate_id,
        "content_sha256": content_sha256,
        "engine": engine,
        "bbox": bbox,
        "rows": normalized_rows,
        "cell_signature": normalized_cells,
        "cell_values": cell_values,
        "tokens": tokens,
        "row_count": row_count,
        "column_count": column_count,
        "geometry": geometry_score,
        "grid": 1.0,
        "cell_coverage": cell_coverage,
        "spans": span_score,
        "provenance": provenance_score,
        "headers": header_count,
        "span_count": span_count,
        "logical_rows_recovered": (
            type(raw_vector) is dict
            and raw_vector.get("logical_rows_recovered") is True
            and raw_geometry_count == slot_count
            and geometry_score == 1.0
        ),
        "evidence_ids": evidence_ids,
        "summary": candidate_summary,
    }


def _table_reconciliation_multiset_is_subset(subset, superset):
    remaining = {}
    for value in superset:
        remaining[value] = remaining.get(value, 0) + 1
    for value in subset:
        available = remaining.get(value, 0)
        if available < 1:
            return False
        remaining[value] = available - 1
    return True


def _table_reconciliation_attach(item, reconciliation, concerns, deadline):
    _check_table_deadline(deadline)
    retained = deepcopy(item)
    sidecar = retained.get("table_evidence")
    if type(sidecar) is dict:
        sidecar = deepcopy(sidecar)
        sidecar["scope"] = ["P04-US01", "P04-US02"]
        sidecar["reconciliation"] = deepcopy(reconciliation)
        sidecar["concerns"] = sorted(
            set(sidecar.get("concerns") or []) | set(concerns)
        )
        if reconciliation.get("outcome") == "unresolved":
            sidecar["status"] = "unresolved"
        retained["table_evidence"] = sidecar
    else:
        retained["table_reconciliation"] = deepcopy(reconciliation)
    parse_concerns = retained.get("parse_concerns")
    if type(parse_concerns) is not list:
        parse_concerns = []
    retained["parse_concerns"] = sorted(set(parse_concerns) | set(concerns))
    _assert_canonical_table_json(retained, 8388608, deadline)
    return retained


def _table_reconciliation_cluster(features, malformed_concern, deadline):
    _check_table_deadline(deadline)
    features_by_id = {}
    for feature in features:
        current = features_by_id.get(feature["candidate_id"])
        if current is None or feature["content_sha256"] < current["content_sha256"]:
            features_by_id[feature["candidate_id"]] = feature
    features = [features_by_id[key] for key in sorted(features_by_id)]
    candidate_ids = [feature["candidate_id"] for feature in features]
    cluster_id = _canonical_table_sha256(
        ["p04-us02-cluster-v1", candidate_ids],
        8388608,
        deadline,
    )
    maximum_slots = max(
        feature["row_count"] * feature["column_count"] for feature in features
    )
    union_tokens = set().union(*(feature["tokens"] for feature in features))
    scores = []
    for feature in features:
        _check_table_deadline(deadline)
        feature["cell_coverage"] = min(
            feature["cell_coverage"],
            (
                feature["row_count"] * feature["column_count"] / maximum_slots
                if maximum_slots
                else 0.0
            ),
        )
        text_coverage = (
            len(feature["tokens"] & union_tokens) / len(union_tokens)
            if union_tokens
            else 1.0
        )
        total = (
            0.18 * feature["geometry"]
            + 0.18 * feature["grid"]
            + 0.22 * feature["cell_coverage"]
            + 0.22 * text_coverage
            + 0.08 * feature["spans"]
            + 0.12 * feature["provenance"]
        )
        feature["text_coverage"] = text_coverage
        feature["total"] = total
        scores.append(
            {
                "candidate_id": feature["candidate_id"],
                "engine": feature["engine"],
                "total": round(total, 6),
                "geometry": round(feature["geometry"], 6),
                "grid": round(feature["grid"], 6),
                "cell_coverage": round(feature["cell_coverage"], 6),
                "text_coverage": round(text_coverage, 6),
                "spans": round(feature["spans"], 6),
                "provenance": round(feature["provenance"], 6),
                "bbox": feature["bbox"],
                "row_count": feature["row_count"],
                "column_count": feature["column_count"],
                "content_sha256": feature["content_sha256"],
                "candidate": feature["summary"],
            }
        )
    ranked = sorted(
        features,
        key=lambda feature: (-feature["total"], feature["candidate_id"]),
    )
    winner = ranked[0]
    margin = (
        max(0.0, winner["total"] - ranked[1]["total"])
        if len(ranked) > 1
        else 1.0
    )
    exact_duplicate = len(features) > 1 and all(
        feature["rows"] == winner["rows"]
        and (
            not feature["cell_signature"]
            or not winner["cell_signature"]
            or feature["cell_signature"] == winner["cell_signature"]
        )
        and _table_reconciliation_overlap(feature["bbox"], winner["bbox"])
        >= 0.80
        for feature in features
    )
    winner_covers_all = all(
        _table_reconciliation_multiset_is_subset(
            feature["cell_values"], winner["cell_values"]
        )
        for feature in features
    )
    # A source grid can contain several visible text baselines between two
    # drawn horizontal rules.  When those baselines were expanded using exact
    # vector cell boundaries, prefer the resulting complete two-dimensional
    # candidate over a competing model that contains the same words but has
    # silently lost rows or columns.  The explicit recovery marker confines
    # this low-margin exception to candidates proven from both source geometry
    # and source word baselines; ordinary pdfplumber candidates retain the
    # normal reconciliation margin.
    source_grid_covers_all = (
        winner["logical_rows_recovered"]
        and all(feature["tokens"] <= winner["tokens"] for feature in features)
        and all(
            winner["row_count"] >= feature["row_count"]
            and winner["column_count"] >= feature["column_count"]
            for feature in features
        )
    )
    same_text_conflicting_structure = len(features) > 1 and any(
        feature["rows"] == winner["rows"]
        and feature["cell_signature"]
        and winner["cell_signature"]
        and feature["cell_signature"] != winner["cell_signature"]
        for feature in features
    )
    concerns = []
    if malformed_concern:
        concerns.append("table_reconciliation_malformed_candidate")
    if len(features) == 1:
        outcome = "singleton"
        selected_candidate_id = winner["candidate_id"]
    elif exact_duplicate:
        outcome = "duplicate_collapsed"
        selected_candidate_id = winner["candidate_id"]
    elif (
        winner["total"] >= _TABLE_RECONCILIATION_ABSOLUTE_THRESHOLD
        and (
            margin >= _TABLE_RECONCILIATION_SELECTION_MARGIN
            or source_grid_covers_all
        )
        and (winner_covers_all or source_grid_covers_all)
        and not same_text_conflicting_structure
    ):
        outcome = "selected"
        selected_candidate_id = winner["candidate_id"]
    else:
        outcome = "unresolved"
        selected_candidate_id = None
        concerns.extend(
            ["table_reconciliation_conflict", "table_reconciliation_low_margin"]
        )
    concerns = sorted(set(concerns))
    evidence_ids = sorted(
        {
            evidence_id
            for feature in features
            for evidence_id in feature["evidence_ids"]
        }
    )[:64]
    reconciliation = {
        "cluster_id": cluster_id,
        "candidate_ids": candidate_ids,
        "selected_candidate_id": selected_candidate_id,
        "outcome": outcome,
        "absolute_threshold": _TABLE_RECONCILIATION_ABSOLUTE_THRESHOLD,
        "selection_margin": round(min(1.0, margin), 6),
        "scores": scores,
        "evidence_ids": evidence_ids,
        "concern_codes": concerns,
    }
    anchor = winner
    attached = _table_reconciliation_attach(
        anchor["item"], reconciliation, concerns, deadline
    )
    selected_raw_vector = (
        {
            "raw_record": winner.get("raw_vector"),
            "candidate_id": winner.get("candidate_id"),
            "content_sha256": winner.get("content_sha256"),
            "page_index": winner.get("page_index"),
        }
        if selected_candidate_id == winner.get("candidate_id")
        and type(winner.get("raw_vector")) is dict
        and not malformed_concern
        and not concerns
        else None
    )
    return attached, selected_raw_vector


def reconcile_table_candidates(merged, docling_tables, vector_tables, *, table_span_fidelity_enabled=False, table_evidence_reconciliation_enabled=False, selected_vector_sink=None, selected_vector_source_sha256=None):
    if type(selected_vector_sink) is dict:
        selected_vector_sink.clear()
    if not table_span_fidelity_enabled:
        return merged
    if not table_evidence_reconciliation_enabled:
        return merged
    deadline = perf_counter() + 5.0
    if type(merged) not in (dict, defaultdict) or len(merged) > 4096:
        return merged
    try:
        output = {}
        selected_vector_descriptors = {}
        selected_vector_descriptors_valid = True
        selected_vector_descriptor_count = 0
        selected_vector_descriptor_slots = 0
        raw_pages = (
            vector_tables
            if type(vector_tables) in (dict, defaultdict)
            else {}
        )
        for page_index, page_candidates in tuple(merged.items()):
            _check_table_deadline(deadline)
            if (
                type(page_index) is not int
                or page_index < 1
                or type(page_candidates) is not list
                or len(page_candidates) > 128
            ):
                output[page_index] = page_candidates
                continue
            raw_vectors = []
            malformed_raw = False
            raw_page = raw_pages.get(page_index, [])
            if type(raw_page) is list and len(raw_page) <= 128:
                for raw_table in tuple(raw_page):
                    _check_table_deadline(deadline)
                    raw_record = _table_reconciliation_raw_vector(raw_table)
                    if (
                        raw_record is None
                        or raw_record.get("page_index") != page_index
                    ):
                        malformed_raw = True
                    else:
                        raw_vectors.append(raw_record)
            elif raw_page:
                malformed_raw = True
            working_candidates = []
            for candidate in tuple(page_candidates):
                _check_table_deadline(deadline)
                if type(candidate) is dict:
                    working_candidates.append(candidate)
                else:
                    malformed_raw = True
            for raw_record in raw_vectors:
                projected = _table_reconciliation_vector_item(raw_record)
                if type(projected) is not dict:
                    malformed_raw = True
                    continue
                raw_record["public_projection"] = projected
                already_present = any(
                    type(candidate) is dict
                    and candidate.get("engine") == "pdfplumber"
                    and _table_reconciliation_rows(candidate.get("rows"))
                    == raw_record["normalized_rows"]
                    and _table_reconciliation_overlap(
                        _table_reconciliation_bbox(candidate.get("bbox")),
                        raw_record["bbox"],
                    )
                    >= 0.95
                    for candidate in working_candidates
                )
                if not already_present:
                    working_candidates.append(projected)
            features = []
            malformed_candidate = False
            for candidate in working_candidates:
                raw_match = None
                selected_vector_raw = None
                if candidate.get("engine") == "pdfplumber":
                    loose_raw_matches = [
                        raw_record
                        for raw_record in raw_vectors
                        if (
                            _table_reconciliation_rows(candidate.get("rows"))
                            == raw_record["normalized_rows"]
                            and _table_reconciliation_overlap(
                                _table_reconciliation_bbox(candidate.get("bbox")),
                                raw_record["bbox"],
                            )
                            >= 0.95
                        )
                    ]
                    if loose_raw_matches:
                        raw_match = loose_raw_matches[0]
                    authority_raw_matches = [
                        raw_record
                        for raw_record in raw_vectors
                        if (
                            _selected_vector_public_projection_matches(
                                candidate,
                                raw_record.get("public_projection"),
                            )
                        )
                    ]
                    if len(authority_raw_matches) == 1:
                        selected_vector_raw = authority_raw_matches[0]
                feature = _table_reconciliation_candidate(
                    candidate,
                    page_index,
                    deadline,
                    raw_match,
                    selected_vector_raw,
                )
                if feature is None:
                    malformed_candidate = True
                else:
                    features.append(feature)
            if not features:
                output[page_index] = deepcopy(page_candidates)
                continue
            components = []
            remaining = set(range(len(features)))
            comparisons = 0
            while remaining:
                seed = min(remaining)
                remaining.remove(seed)
                component = {seed}
                frontier = [seed]
                while frontier:
                    current = frontier.pop()
                    for other in tuple(sorted(remaining)):
                        comparisons += 1
                        if comparisons > 8192:
                            raise ValueError(
                                "table reconciliation comparison limit exceeded"
                            )
                        if _table_reconciliation_overlap(
                            features[current]["bbox"], features[other]["bbox"]
                        ) >= 0.55:
                            remaining.remove(other)
                            component.add(other)
                            frontier.append(other)
                components.append(sorted(component))
            if len(components) > 64:
                output[page_index] = deepcopy(page_candidates)
                continue
            reconciled_page = []
            for component in components:
                cluster_features = [features[index] for index in component]
                reconciled_item, selected_raw_vector = (
                    _table_reconciliation_cluster(
                        cluster_features,
                        malformed_raw or malformed_candidate,
                        deadline,
                    )
                )
                reconciled_page.append(
                    (reconciled_item, selected_raw_vector)
                )
            reconciled_page.sort(
                key=lambda pair: (
                    float(
                        (_table_reconciliation_bbox(pair[0].get("bbox")) or {}).get(
                            "y", 0.0
                        )
                    ),
                    float(
                        (_table_reconciliation_bbox(pair[0].get("bbox")) or {}).get(
                            "x", 0.0
                        )
                    ),
                    str(
                        (
                            pair[0].get("table_evidence")
                            if type(pair[0].get("table_evidence")) is dict
                            else {}
                        ).get("candidate_id", "")
                    ),
                )
            )
            output[page_index] = [pair[0] for pair in reconciled_page]
            page_selected_descriptors = []
            for output_position, (candidate, raw_descriptor) in enumerate(
                reconciled_page
            ):
                if type(raw_descriptor) is not dict:
                    continue
                reconciliation = candidate.get("table_reconciliation")
                if type(reconciliation) is not dict:
                    sidecar = candidate.get("table_evidence")
                    reconciliation = (
                        sidecar.get("reconciliation")
                        if type(sidecar) is dict
                        else None
                    )
                selected_candidate_id = (
                    reconciliation.get("selected_candidate_id")
                    if type(reconciliation) is dict
                    else None
                )
                if (
                    raw_descriptor.get("candidate_id")
                    != selected_candidate_id
                ):
                    continue
                if type(selected_vector_sink) is not dict:
                    continue
                raw_rows = (
                    raw_descriptor.get("raw_record", {}).get("rows")
                    if type(raw_descriptor.get("raw_record")) is dict
                    else None
                )
                raw_columns = (
                    len(raw_rows[0])
                    if type(raw_rows) is list
                    and raw_rows
                    and type(raw_rows[0]) is list
                    else 0
                )
                selected_vector_descriptor_count += 1
                selected_vector_descriptor_slots += (
                    len(raw_rows) * raw_columns
                    if type(raw_rows) is list
                    else 0
                )
                if (
                    selected_vector_descriptor_count > 128
                    or selected_vector_descriptor_slots > 10_000
                ):
                    selected_vector_descriptors_valid = False
                    continue
                page_selected_descriptors.append(
                    {
                        "page_index": page_index,
                        "output_position": output_position,
                        **raw_descriptor,
                    }
                )
            if page_selected_descriptors:
                selected_vector_descriptors[page_index] = (
                    page_selected_descriptors
                )
        for page_index, page_candidates in tuple(merged.items()):
            if page_index not in output:
                output[page_index] = deepcopy(page_candidates)
        if type(selected_vector_sink) is dict:
            selected_vector_sink.clear()
            authority_deadline = perf_counter() + 0.500
            try:
                if not selected_vector_descriptors_valid:
                    raise ValueError(
                        "selected vector descriptor limit exceeded"
                    )
                selected_vectors = {}
                selected_vector_count = 0
                selected_vector_slot_count = 0
                for page_index, descriptors in tuple(
                    selected_vector_descriptors.items()
                ):
                    page_selected_vectors = []
                    for descriptor in tuple(descriptors):
                        _check_table_deadline(authority_deadline)
                        raw_vector = _selected_vector_authority_projection(
                            descriptor.get("raw_record"),
                            descriptor.get("candidate_id"),
                            descriptor.get("content_sha256"),
                            page_index,
                            selected_vector_source_sha256,
                            authority_deadline,
                        )
                        if type(raw_vector) is not dict:
                            raise ValueError(
                                "selected vector authority differs"
                            )
                        selected_vector_count += 1
                        selected_vector_slot_count += len(
                            raw_vector["rows"]
                        ) * len(raw_vector["rows"][0])
                        if (
                            selected_vector_count > 128
                            or selected_vector_slot_count > 10_000
                        ):
                            raise ValueError(
                                "selected vector resource limit exceeded"
                            )
                        page_selected_vectors.append(
                            {
                                "page_index": page_index,
                                "output_position": descriptor[
                                    "output_position"
                                ],
                                **deepcopy(raw_vector),
                            }
                        )
                    if page_selected_vectors:
                        selected_vectors[page_index] = page_selected_vectors
                _canonical_table_json_size(
                    [
                        [page_index, selected_vectors[page_index]]
                        for page_index in sorted(selected_vectors)
                    ],
                    8388608,
                    authority_deadline,
                )
                selected_vector_sink.update(selected_vectors)
            except (
                MemoryError,
                RecursionError,
                TimeoutError,
                TypeError,
                ValueError,
            ):
                selected_vector_sink.clear()
        return output
    except (MemoryError, RecursionError, TimeoutError, TypeError, ValueError):
        if type(selected_vector_sink) is dict:
            selected_vector_sink.clear()
        return merged


def _table_gate_candidate_id(candidate, page_index, source_identity, deadline):
    _check_table_deadline(deadline)
    sidecar = candidate.get("table_evidence")
    if type(sidecar) is dict and _is_table_sha256(
        sidecar.get("candidate_id"), deadline
    ):
        return sidecar["candidate_id"]
    reconciliation = candidate.get("table_reconciliation")
    if type(reconciliation) is dict:
        selected = reconciliation.get("selected_candidate_id")
        if _is_table_sha256(selected, deadline):
            return selected
        candidate_ids = reconciliation.get("candidate_ids")
        if type(candidate_ids) is list:
            valid_ids = sorted(
                {
                    value
                    for value in candidate_ids
                    if _is_table_sha256(value, deadline)
                }
            )
            if valid_ids:
                return valid_ids[0]
    return _canonical_table_sha256(
        [
            "p04-us04-candidate-v1",
            source_identity,
            page_index,
            candidate.get("engine")
            if type(candidate.get("engine")) is str
            else "unknown",
            _table_reconciliation_bbox(candidate.get("bbox")),
            candidate.get("row_count")
            if type(candidate.get("row_count")) is int
            else None,
            candidate.get("column_count")
            if type(candidate.get("column_count")) is int
            else None,
        ],
        8388608,
        deadline,
    )


def _table_gate_owner_id(owner, page_index, source_identity, deadline):
    _check_table_deadline(deadline)
    identifier = owner.get("id")
    if type(identifier) is str and identifier and len(identifier.encode("utf-8")) <= 256:
        return identifier
    digest = _canonical_table_sha256(
        [
            "p04-us04-owner-v1",
            source_identity,
            page_index,
            owner.get("type"),
            owner.get("content_type"),
            owner.get("label"),
            _table_reconciliation_bbox(owner.get("bbox")),
        ],
        8388608,
        deadline,
    )
    return f"p04-owner-{digest}"


def _table_gate_owner_kind(owner):
    item_type = str(owner.get("type") or "").casefold()
    content_type = str(owner.get("content_type") or "").casefold()
    label = str(owner.get("label") or "").casefold()
    if "chart" in (item_type, content_type, label):
        return "chart"
    if item_type == "form" or label == "form":
        return "form"
    if item_type == "key_value" or label == "key_value_region":
        return "key_value"
    if item_type in ("image", "diagram") or content_type in (
        "image", "diagram"
    ):
        return "visual"
    return None


def _table_gate_owner_records(
    page_owners, candidate_bbox, page_index, source_identity, deadline
):
    records = []
    if type(page_owners) is not list or len(page_owners) > 128:
        return records
    for owner in tuple(page_owners):
        _check_table_deadline(deadline)
        if type(owner) is not dict:
            continue
        kind = _table_gate_owner_kind(owner)
        if kind is None:
            continue
        owner_bbox = _table_reconciliation_bbox(owner.get("bbox"))
        overlap = _table_reconciliation_overlap(candidate_bbox, owner_bbox)
        if overlap < 0.70:
            continue
        records.append(
            {
                "id": _table_gate_owner_id(
                    owner, page_index, source_identity, deadline
                ),
                "kind": kind,
                "bbox": owner_bbox,
                "overlap": round(min(1.0, overlap), 6),
                "item": owner,
            }
        )
    records.sort(
        key=lambda record: (
            {"chart": 0, "form": 1, "key_value": 2, "visual": 3}[
                record["kind"]
            ],
            record["id"],
        )
    )
    unique = []
    observed = set()
    for record in records:
        identity = (record["id"], record["kind"])
        if identity in observed:
            continue
        observed.add(identity)
        unique.append(record)
    return unique[:64]


def _table_gate_features(candidate, page_index, deadline):
    _check_table_deadline(deadline)
    bbox = _table_reconciliation_bbox(candidate.get("bbox"))
    rows = _table_reconciliation_rows(candidate.get("rows"))
    hard_failure = bbox is None or rows is None
    structural_failure = hard_failure
    if rows is None:
        row_count = 0
        column_count = 0
        nonblank = 0
        aligned_rows = 0
    else:
        row_count = len(rows)
        column_count = len(rows[0])
        nonblank = sum(bool(value) for row in rows for value in row)
        aligned_rows = sum(sum(bool(value) for value in row) >= 2 for row in rows)
        hard_failure = hard_failure or (
            candidate.get("row_count") != row_count
            or candidate.get("column_count") != column_count
        )
        structural_failure = hard_failure or row_count < 2 or column_count < 2
    slot_count = row_count * column_count
    cells = candidate.get("cells")
    cells_valid = type(cells) is list and len(cells) <= 65536
    occupied = set()
    explicit_geometry = 0
    explicit_provenance = 0
    header_count = 0
    if cells_valid:
        for cell in tuple(cells):
            _check_table_deadline(deadline)
            if type(cell) is not dict:
                cells_valid = False
                break
            row = cell.get("row")
            column = cell.get("column")
            row_span = cell.get("row_span", 1)
            col_span = cell.get("col_span", 1)
            if (
                type(row) is not int
                or type(column) is not int
                or type(row_span) is not int
                or type(col_span) is not int
                or row < 0
                or column < 0
                or row_span < 1
                or col_span < 1
                or row + row_span > row_count
                or column + col_span > column_count
            ):
                cells_valid = False
                break
            slots = {
                (row + row_offset, column + column_offset)
                for row_offset in range(row_span)
                for column_offset in range(col_span)
            }
            if occupied & slots:
                cells_valid = False
                break
            occupied.update(slots)
            explicit_geometry += (
                _table_reconciliation_bbox(cell.get("bbox")) is not None
            )
            explicit_provenance += bool(cell.get("source_object_ids")) and bool(
                cell.get("evidence_ids")
            )
            header_count += cell.get("column_header") is True
    if not cells_valid:
        hard_failure = True
        structural_failure = True
        cells = []
        occupied = set()
    sidecar = candidate.get("table_evidence")
    reconciliation = (
        sidecar.get("reconciliation")
        if type(sidecar) is dict
        else candidate.get("table_reconciliation")
    )
    if type(sidecar) is dict and sidecar.get("status") == "structural_failure":
        hard_failure = True
        structural_failure = True
    unresolved_reconciliation = (
        type(reconciliation) is dict
        and reconciliation.get("outcome") == "unresolved"
    ) or (
        type(sidecar) is dict and sidecar.get("status") == "unresolved"
    )
    grid = (
        1.0
        if not structural_failure and row_count >= 2 and column_count >= 2
        else 0.0
    )
    alignment = aligned_rows / row_count if row_count else 0.0
    cell_coverage = (
        len(occupied) / slot_count
        if cells and slot_count
        else nonblank / slot_count
        if slot_count
        else 0.0
    )
    provenance = (
        explicit_provenance / len(cells)
        if cells
        else 0.85
        if type(reconciliation) is dict
        and reconciliation.get("outcome") in (
            "singleton", "selected", "duplicate_collapsed"
        )
        else 0.35
    )
    geometry = (
        max(
            0.75,
            explicit_geometry / len(cells) if cells else 0.0,
        )
        if bbox is not None
        else 0.0
    )
    table_support = min(
        1.0,
        0.24 * grid
        + 0.20 * alignment
        + 0.22 * cell_coverage
        + 0.16 * geometry
        + 0.18 * provenance,
    )
    headerless_pair_grid = (
        not structural_failure
        and column_count == 2
        and row_count >= 3
        and cell_coverage >= 0.75
        and alignment >= 0.90
        and header_count == 0
    )
    weak_headerless_pair_grid = (
        not structural_failure
        and column_count == 2
        and row_count < 3
        and header_count == 0
    )
    return {
        "bbox": bbox,
        "rows": rows,
        "row_count": row_count,
        "column_count": column_count,
        "hard_failure": hard_failure,
        "structural_failure": structural_failure,
        "unresolved_reconciliation": unresolved_reconciliation,
        "headerless_pair_grid": headerless_pair_grid,
        "weak_headerless_pair_grid": weak_headerless_pair_grid,
        "scores": {
            "alignment": round(min(1.0, alignment), 6),
            "cell_coverage": round(min(1.0, cell_coverage), 6),
            "geometry": round(min(1.0, geometry), 6),
            "grid": round(min(1.0, grid), 6),
            "owner_overlap": 0.0,
            "provenance": round(min(1.0, provenance), 6),
            "region_type": 0.0,
            "table_support": round(min(1.0, table_support), 6),
        },
    }


def _table_gate_decision(
    candidate, page_owners, page_index, source_identity, deadline
):
    _check_table_deadline(deadline)
    features = _table_gate_features(candidate, page_index, deadline)
    candidate_id = _table_gate_candidate_id(
        candidate, page_index, source_identity, deadline
    )
    owner_records = _table_gate_owner_records(
        page_owners,
        features["bbox"],
        page_index,
        source_identity,
        deadline,
    )
    owner_kinds = sorted({record["kind"] for record in owner_records})
    strongest_overlap = max(
        (record["overlap"] for record in owner_records), default=0.0
    )
    scores = dict(features["scores"])
    scores["owner_overlap"] = strongest_overlap
    scores["region_type"] = 1.0 if owner_records else 0.0
    concerns = []
    reasons = []
    if features["hard_failure"]:
        outcome = "structural_failure"
        concerns.append("table_candidate_structure_invalid")
        reasons.append("invalid_or_incomplete_grid")
        owner_records = []
    elif features["unresolved_reconciliation"]:
        outcome = "unresolved"
        concerns.append("table_candidate_ownership_ambiguous")
        reasons.append("upstream_reconciliation_unresolved")
        owner_records = []
    elif len(owner_kinds) > 1:
        outcome = "unresolved"
        concerns.append("table_candidate_ownership_ambiguous")
        reasons.append("competing_typed_owners")
    elif owner_records:
        outcome = owner_records[0]["kind"]
        reasons.append(f"typed_{outcome}_owns_region")
        if outcome == "chart":
            concerns.append("table_candidate_chart_owned")
        elif outcome == "form":
            concerns.append("table_candidate_form_owned")
        elif outcome == "key_value":
            concerns.append("table_candidate_key_value_alternative")
        else:
            concerns.append("table_candidate_ownership_ambiguous")
    elif features["structural_failure"]:
        outcome = "structural_failure"
        concerns.append("table_candidate_structure_invalid")
        reasons.append("unsupported_grid_shape")
    elif features["headerless_pair_grid"]:
        outcome = "key_value"
        concerns.append("table_candidate_key_value_alternative")
        reasons.append("supported_headerless_pair_grid")
    elif features["weak_headerless_pair_grid"]:
        outcome = "unresolved"
        concerns.append("table_candidate_ownership_ambiguous")
        reasons.append("insufficient_headerless_pair_support")
    elif scores["table_support"] >= 0.62:
        outcome = "canonical_table"
        reasons.append("source_supported_rectangular_grid")
    else:
        outcome = "unresolved"
        concerns.append("table_candidate_ownership_ambiguous")
        reasons.append("insufficient_table_support")
    owner_ids = sorted({record["id"] for record in owner_records})
    sidecar = candidate.get("table_evidence")
    reconciliation = (
        sidecar.get("reconciliation")
        if type(sidecar) is dict
        else candidate.get("table_reconciliation")
    )
    evidence_ids = sorted(
        {
            evidence_id
            for evidence_id in (
                reconciliation.get("evidence_ids", [])
                if type(reconciliation) is dict
                else []
            )
            if _is_table_sha256(evidence_id, deadline)
        }
    )[:64]
    if type(sidecar) is dict and type(sidecar.get("evidence")) is list:
        evidence_ids = sorted(
            set(evidence_ids)
            | {
                record.get("id")
                for record in sidecar["evidence"]
                if type(record) is dict
                and _is_table_sha256(record.get("id"), deadline)
            }
        )[:64]
    concerns = sorted(set(concerns))
    scores = {key: scores[key] for key in _TABLE_GATE_FEATURE_KEYS}
    decision_id = _canonical_table_sha256(
        [
            "p04-us04-gate-v1",
            candidate_id,
            outcome,
            owner_ids,
            scores,
            evidence_ids,
            concerns,
        ],
        8388608,
        deadline,
    )
    gate = {
        "decision_id": decision_id,
        "candidate_id": candidate_id,
        "outcome": outcome,
        "owner_item_ids": owner_ids,
        "feature_scores": scores,
        "evidence_ids": evidence_ids,
        "concern_codes": concerns,
    }
    return gate, sorted(set(reasons)), owner_records, features


def _table_gate_attach_canonical(candidate, gate, reasons, deadline):
    retained = _validate_plain_table_value(candidate, deadline)
    sidecar = retained.get("table_evidence")
    if type(sidecar) is dict:
        sidecar["scope"] = ["P04-US01", "P04-US02", "P04-US04"]
        sidecar["gate"] = deepcopy(gate)
        sidecar["concerns"] = sorted(
            set(sidecar.get("concerns") or []) | set(gate["concern_codes"])
        )
        retained["table_evidence"] = sidecar
    else:
        retained["table_candidate_gate"] = deepcopy(gate)
    retained["table_candidate_gate_reasons"] = deepcopy(reasons)
    return retained


def _selected_vector_reconciliation_matches(candidate, projection, deadline):
    _check_table_deadline(deadline)
    reconciliation = candidate.get("table_reconciliation")
    if (
        type(reconciliation) is not dict
        or reconciliation.get("selected_candidate_id")
        != projection.get("candidate_id")
        or reconciliation.get("outcome")
        not in ("singleton", "duplicate_collapsed", "selected")
        or reconciliation.get("concern_codes") != []
    ):
        return False
    scores = reconciliation.get("scores")
    if type(scores) is not list or not 1 <= len(scores) <= 128:
        return False
    selected_scores = [
        score
        for score in scores
        if type(score) is dict
        and score.get("candidate_id") == projection.get("candidate_id")
    ]
    if len(selected_scores) != 1:
        return False
    selected_score = selected_scores[0]
    summary = selected_score.get("candidate")
    public = projection.get("public_projection")
    return (
        selected_score.get("engine") == "pdfplumber"
        and selected_score.get("content_sha256")
        == projection.get("content_sha256")
        and type(summary) is dict
        and summary.get("candidate_id") == projection.get("candidate_id")
        and summary.get("content_sha256")
        == projection.get("content_sha256")
        and summary.get("engine") == "pdfplumber"
        and type(public) is dict
        and summary.get("bbox")
        == _table_reconciliation_bbox(public.get("bbox"))
        and summary.get("rows") == public.get("rows")
        and summary.get("cells") == []
        and summary.get("row_count") == public.get("row_count")
        and summary.get("column_count") == public.get("column_count")
    )


def _selected_vector_gate_matches(candidate, projection, deadline):
    _check_table_deadline(deadline)
    gate = candidate.get("table_candidate_gate")
    reasons = candidate.get("table_candidate_gate_reasons")
    if not (
        type(gate) is dict
        and gate.get("outcome") == "canonical_table"
        and gate.get("candidate_id") == projection.get("candidate_id")
        and gate.get("concern_codes") == []
        and _is_table_sha256(gate.get("decision_id"), deadline)
        and type(reasons) is list
        and len(reasons) <= 64
        and all(type(reason) is str for reason in reasons)
    ):
        return False
    story = {
        "scope": ["P04-US01", "P04-US02", "P04-US04"],
        "candidate_id": projection.get("candidate_id"),
        "reconciliation": candidate.get("table_reconciliation"),
        "gate": gate,
        "continuation": None,
    }
    if not _table_story_metadata_is_well_formed(story, deadline):
        return False
    try:
        predecessor = deepcopy(candidate)
        predecessor.pop("table_candidate_gate", None)
        predecessor.pop("table_candidate_gate_reasons", None)
        replayed_gate, replayed_reasons, owner_records, _features = (
            _table_gate_decision(
                predecessor,
                [],
                projection.get("page_index"),
                projection.get("source_sha256"),
                deadline,
            )
        )
    except (
        MemoryError,
        RecursionError,
        TimeoutError,
        TypeError,
        ValueError,
    ):
        return False
    return (
        owner_records == []
        and replayed_gate == gate
        and replayed_reasons == reasons
    )


def _replay_selected_vector_projection(projection, page_index, deadline):
    _check_table_deadline(deadline)
    if type(projection) is not dict:
        return None
    expected_keys = {
        "schema_version",
        "policy_id",
        "page_index",
        "candidate_id",
        "content_sha256",
        "bbox",
        "rows",
        "normalized_rows",
        "row_bboxes",
        "cell_bboxes",
        "geometry_inferred",
        "logical_rows_recovered",
        "public_projection",
        "source_sha256",
        "vector_sha256",
    }
    if (
        set(projection) != expected_keys
        or projection.get("schema_version") != "1.0"
        or projection.get("policy_id")
        != "p02-selected-vector-representation-v1"
        or projection.get("page_index") != page_index
    ):
        return None
    try:
        raw_table = RawTable(
            page_index=page_index,
            bbox=deepcopy(projection.get("bbox")),
            rows=deepcopy(projection.get("rows")),
            row_bboxes=deepcopy(projection.get("row_bboxes")),
            parse_concerns=[],
            cell_bboxes=tuple(
                tuple(deepcopy(row))
                for row in projection.get("cell_bboxes")
            ),
            geometry_inferred=projection.get("geometry_inferred"),
            logical_rows_recovered=projection.get(
                "logical_rows_recovered"
            ),
        )
        raw_record = _table_reconciliation_raw_vector(raw_table)
        replayed = _selected_vector_authority_projection(
            raw_record,
            projection.get("candidate_id"),
            projection.get("content_sha256"),
            page_index,
            projection.get("source_sha256"),
            deadline,
        )
    except (MemoryError, RecursionError, TypeError, ValueError):
        return None
    return replayed if replayed == projection else None


def finalize_selected_vector_representations(
    tables,
    preliminary_representations,
    source_document_identity,
    selected_vector_sink,
    *,
    table_span_fidelity_enabled=False,
    table_evidence_reconciliation_enabled=False,
    table_candidate_gate_enabled=False,
):
    """Seal optional selected-vector authority after the local table gate."""

    if type(selected_vector_sink) is dict:
        selected_vector_sink.clear()
    if not (
        table_span_fidelity_enabled
        and table_evidence_reconciliation_enabled
        and table_candidate_gate_enabled
        and type(selected_vector_sink) is dict
    ):
        return None
    deadline = perf_counter() + 0.500
    try:
        source_sha256 = _assert_source_sha256(
            source_document_identity, deadline
        )
        if (
            type(tables) not in (dict, defaultdict)
            or type(preliminary_representations) not in (dict, defaultdict)
            or len(tables) > 4096
            or len(preliminary_representations) > 4096
        ):
            return None
        output = {}
        table_count = 0
        slot_count = 0
        for page_index, raw_records in tuple(
            preliminary_representations.items()
        ):
            _check_table_deadline(deadline)
            page_tables = tables.get(page_index)
            if (
                type(page_index) is not int
                or page_index < 1
                or type(raw_records) is not list
                or type(page_tables) is not list
                or len(raw_records) > 128
                or len(page_tables) > 128
            ):
                raise ValueError("selected vector page shape differs")
            sealed_page = []
            consumed_positions = set()
            for raw_record in tuple(raw_records):
                _check_table_deadline(deadline)
                if type(raw_record) is not dict:
                    raise TypeError("selected vector record differs")
                preliminary = deepcopy(raw_record)
                preliminary.pop("output_position", None)
                projection = _replay_selected_vector_projection(
                    preliminary, page_index, deadline
                )
                if projection is None:
                    raise ValueError("selected vector projection differs")
                if projection.get("source_sha256") != source_sha256:
                    raise ValueError("selected vector source differs")
                matches = [
                    (position, candidate)
                    for position, candidate in enumerate(page_tables)
                    if position not in consumed_positions
                    and _selected_vector_public_projection_matches(
                        candidate,
                        projection.get("public_projection"),
                        attached_keys=(
                            "table_reconciliation",
                            "table_candidate_gate",
                            "table_candidate_gate_reasons",
                        ),
                    )
                    and _selected_vector_reconciliation_matches(
                        candidate, projection, deadline
                    )
                    and _selected_vector_gate_matches(
                        candidate, projection, deadline
                    )
                ]
                if len(matches) != 1:
                    raise ValueError("selected vector public binding differs")
                output_position, candidate = matches[0]
                consumed_positions.add(output_position)
                candidate_sha256 = _canonical_table_sha256(
                    candidate, 8388608, deadline
                )
                sealed = {
                    **projection,
                    "output_position": output_position,
                    "post_gate_table_sha256": candidate_sha256,
                    "table_candidate_gate": deepcopy(
                        candidate["table_candidate_gate"]
                    ),
                    "table_candidate_gate_reasons": deepcopy(
                        candidate["table_candidate_gate_reasons"]
                    ),
                }
                sealed["post_gate_authority_sha256"] = _canonical_table_sha256(
                    [
                        "p02-selected-vector-representation-seal-v1",
                        sealed,
                    ],
                    8388608,
                    deadline,
                )
                table_count += 1
                slot_count += len(projection["rows"]) * len(
                    projection["rows"][0]
                )
                if table_count > 128 or slot_count > 10_000:
                    raise ValueError("selected vector resource limit exceeded")
                sealed_page.append(sealed)
            if sealed_page:
                output[page_index] = sealed_page
        _canonical_table_json_size(
            [
                [page_index, output[page_index]]
                for page_index in sorted(output)
            ],
            8388608,
            deadline,
        )
        selected_vector_sink.update(deepcopy(output))
    except (
        MemoryError,
        RecursionError,
        TimeoutError,
        TypeError,
        ValueError,
    ):
        selected_vector_sink.clear()
    return None


def admit_selected_vector_representation(
    representation,
    public_table,
    source_document_identity,
    page_width,
    page_height,
    *,
    deadline=None,
):
    """Rebuild one sealed vector/table binding for a destructive consumer."""

    active_deadline = (
        float(deadline)
        if type(deadline) in (int, float)
        and type(deadline) is not bool
        and isfinite(float(deadline))
        else perf_counter() + 0.500
    )
    try:
        _check_table_deadline(active_deadline)
        source_sha256 = _assert_source_sha256(
            source_document_identity, active_deadline
        )
        if type(representation) is not dict or type(public_table) is not dict:
            return None
        terminal_binding = representation.get("terminal_binding")
        terminal_authority_sha256 = representation.get(
            "terminal_authority_sha256"
        )
        sealed = deepcopy(representation)
        sealed.pop("terminal_binding", None)
        sealed.pop("terminal_authority_sha256", None)
        projection_keys = {
            "schema_version",
            "policy_id",
            "page_index",
            "source_sha256",
            "candidate_id",
            "content_sha256",
            "bbox",
            "rows",
            "normalized_rows",
            "row_bboxes",
            "cell_bboxes",
            "geometry_inferred",
            "logical_rows_recovered",
            "public_projection",
            "vector_sha256",
        }
        sealed_keys = projection_keys | {
            "output_position",
            "post_gate_table_sha256",
            "table_candidate_gate",
            "table_candidate_gate_reasons",
            "post_gate_authority_sha256",
        }
        if (
            set(sealed) != sealed_keys
            or sealed.get("source_sha256") != source_sha256
            or type(sealed.get("output_position")) is not int
            or sealed.get("output_position") < 0
        ):
            return None
        projection = {
            key: deepcopy(sealed[key]) for key in projection_keys
        }
        if _replay_selected_vector_projection(
            projection,
            sealed.get("page_index"),
            active_deadline,
        ) != projection:
            return None
        expected_post_gate_authority = _canonical_table_sha256(
            [
                "p02-selected-vector-representation-seal-v1",
                {
                    key: value
                    for key, value in sealed.items()
                    if key != "post_gate_authority_sha256"
                },
            ],
            8388608,
            active_deadline,
        )
        if (
            sealed.get("post_gate_authority_sha256")
            != expected_post_gate_authority
        ):
            return None
        public_id = public_table.get("id")
        reading_order = public_table.get("reading_order")
        if (
            type(public_id) is not str
            or not public_id
            or len(public_id.encode("utf-8")) > 256
            or type(reading_order) is not int
            or reading_order < 0
            or set(public_table)
            != set(projection["public_projection"])
            | {
                "id",
                "reading_order",
                "table_reconciliation",
                "table_candidate_gate",
                "table_candidate_gate_reasons",
            }
            or public_table.get("parse_concerns") != []
        ):
            return None
        post_gate_table = deepcopy(public_table)
        post_gate_table.pop("id", None)
        post_gate_table.pop("reading_order", None)
        if (
            not _selected_vector_public_projection_matches(
                post_gate_table,
                projection.get("public_projection"),
                attached_keys=(
                    "table_reconciliation",
                    "table_candidate_gate",
                    "table_candidate_gate_reasons",
                ),
            )
            or not _selected_vector_reconciliation_matches(
                post_gate_table, projection, active_deadline
            )
            or not _selected_vector_gate_matches(
                post_gate_table, projection, active_deadline
            )
            or post_gate_table.get("table_candidate_gate")
            != sealed.get("table_candidate_gate")
            or post_gate_table.get("table_candidate_gate_reasons")
            != sealed.get("table_candidate_gate_reasons")
            or _canonical_table_sha256(
                post_gate_table, 8388608, active_deadline
            )
            != sealed.get("post_gate_table_sha256")
        ):
            return None
        if (
            not _table_bbox_fits_page(
                projection.get("bbox"),
                page_width,
                page_height,
                active_deadline,
            )
            or any(
                not _table_bbox_fits_page(
                    bbox,
                    page_width,
                    page_height,
                    active_deadline,
                )
                for bbox in projection.get("row_bboxes")
            )
            or any(
                not _table_bbox_fits_page(
                    bbox,
                    page_width,
                    page_height,
                    active_deadline,
                )
                for row in projection.get("cell_bboxes")
                for bbox in row
            )
        ):
            return None
        if terminal_binding is not None or terminal_authority_sha256 is not None:
            if (
                type(terminal_binding) is not dict
                or not _is_table_sha256(
                    terminal_authority_sha256, active_deadline
                )
                or _canonical_table_sha256(
                    [
                        "p02-selected-vector-terminal-binding-v1",
                        sealed,
                        terminal_binding,
                    ],
                    8388608,
                    active_deadline,
                )
                != terminal_authority_sha256
            ):
                return None
        return {
            **deepcopy(sealed),
            "public_table_id": public_id,
            "reading_order": reading_order,
            **(
                {
                    "terminal_binding": deepcopy(terminal_binding),
                    "terminal_authority_sha256": terminal_authority_sha256,
                }
                if terminal_binding is not None
                else {}
            ),
        }
    except (
        MemoryError,
        RecursionError,
        TimeoutError,
        TypeError,
        ValueError,
    ):
        return None


def _table_gate_alternative(
    candidate, gate, reasons, features, owner_records, deadline
):
    try:
        alternative = _validate_plain_table_value(candidate, deadline)
    except (RecursionError, TypeError, ValueError):
        alternative = {
            "type": "table_candidate",
            "value": None,
            "md": None,
            "bbox": None,
            "source": "derived",
            "confidence": None,
            "rows": [],
            "cells": [],
            "row_count": 0,
            "column_count": 0,
        }
    sidecar = alternative.pop("table_evidence", None)
    alternative.pop(_TABLE_PREDECESSOR_SNAPSHOT_KEY, None)
    alternative.pop(_TABLE_RECOVERY_PLAN_KEY, None)
    alternative["type"] = "table_candidate"
    if type(sidecar) is dict:
        alternative["candidate_table_evidence"] = sidecar
    if features["bbox"] is None:
        alternative["bbox"] = None
    alternative["table_candidate_gate"] = deepcopy(gate)
    alternative["table_candidate_gate_reasons"] = deepcopy(reasons)
    alternative["table_candidate_gate_sources"] = [
        {
            "owner_item_id": record["id"],
            "owner_type": record["kind"],
            "bbox": deepcopy(record["bbox"]),
            "overlap": record["overlap"],
        }
        for record in owner_records
    ]
    parse_concerns = alternative.get("parse_concerns")
    if type(parse_concerns) is not list:
        parse_concerns = []
    alternative["parse_concerns"] = sorted(
        {
            value
            for value in (*parse_concerns, *gate["concern_codes"])
            if type(value) is str
        }
    )
    return alternative


def gate_table_candidates(
    tables,
    body_items,
    image_regions,
    raw_docling,
    source_document_identity,
    *,
    table_span_fidelity_enabled=False,
    table_evidence_reconciliation_enabled=False,
    table_candidate_gate_enabled=False,
):
    if not (
        table_span_fidelity_enabled
        and table_evidence_reconciliation_enabled
        and table_candidate_gate_enabled
    ):
        return tables
    deadline = perf_counter() + 5.0
    if (
        type(tables) not in (dict, defaultdict)
        or type(body_items) not in (dict, defaultdict)
        or len(tables) > 4096
        or len(body_items) > 4096
    ):
        return tables
    staged_body_additions = defaultdict(list)
    staged_owner_ids = []
    output = {}
    try:
        source_identity = _assert_source_sha256(
            source_document_identity, deadline
        )
        for page_index, page_candidates in tuple(tables.items()):
            _check_table_deadline(deadline)
            if (
                type(page_index) is not int
                or page_index < 1
                or type(page_candidates) is not list
                or len(page_candidates) > 128
            ):
                output[page_index] = page_candidates
                continue
            page_owners = body_items.get(page_index, [])
            if type(page_owners) is not list or len(page_owners) > 128:
                output[page_index] = page_candidates
                continue
            retained_page = []
            for candidate in tuple(page_candidates):
                _check_table_deadline(deadline)
                if type(candidate) is not dict:
                    candidate = {}
                try:
                    gate, reasons, owner_records, features = _table_gate_decision(
                        candidate,
                        page_owners,
                        page_index,
                        source_identity,
                        deadline,
                    )
                except (RecursionError, TypeError, ValueError):
                    candidate_id = _canonical_table_sha256(
                        ["p04-us04-malformed-v1", source_identity, page_index],
                        8388608,
                        deadline,
                    )
                    scores = {
                        key: 0.0 for key in _TABLE_GATE_FEATURE_KEYS
                    }
                    concerns = ["table_candidate_structure_invalid"]
                    gate = {
                        "decision_id": _canonical_table_sha256(
                            [
                                "p04-us04-gate-v1",
                                candidate_id,
                                "structural_failure",
                                [],
                                scores,
                                [],
                                concerns,
                            ],
                            8388608,
                            deadline,
                        ),
                        "candidate_id": candidate_id,
                        "outcome": "structural_failure",
                        "owner_item_ids": [],
                        "feature_scores": scores,
                        "evidence_ids": [],
                        "concern_codes": concerns,
                    }
                    reasons = ["malformed_candidate"]
                    owner_records = []
                    features = {"bbox": None}
                if gate["outcome"] == "canonical_table":
                    try:
                        retained_page.append(
                            _table_gate_attach_canonical(
                                candidate, gate, reasons, deadline
                            )
                        )
                    except (RecursionError, TypeError, ValueError):
                        gate["outcome"] = "structural_failure"
                        gate["owner_item_ids"] = []
                        gate["concern_codes"] = [
                            "table_candidate_structure_invalid"
                        ]
                        gate["decision_id"] = _canonical_table_sha256(
                            [
                                "p04-us04-gate-v1",
                                gate["candidate_id"],
                                gate["outcome"],
                                [],
                                gate["feature_scores"],
                                gate["evidence_ids"],
                                gate["concern_codes"],
                            ],
                            8388608,
                            deadline,
                        )
                        reasons = ["canonical_projection_rejected"]
                        staged_body_additions[page_index].append(
                            _table_gate_alternative(
                                candidate,
                                gate,
                                reasons,
                                features,
                                [],
                                deadline,
                            )
                        )
                else:
                    staged_body_additions[page_index].append(
                        _table_gate_alternative(
                            candidate,
                            gate,
                            reasons,
                            features,
                            owner_records,
                            deadline,
                        )
                    )
                    staged_owner_ids.extend(
                        (record["item"], record["id"])
                        for record in owner_records
                        if not (
                            type(record["item"].get("id")) is str
                            and record["item"].get("id")
                        )
                    )
            output[page_index] = retained_page
        for page_index, page_candidates in tuple(tables.items()):
            output.setdefault(page_index, page_candidates)
        for page_index, additions in staged_body_additions.items():
            body_items.setdefault(page_index, []).extend(additions)
        for owner, owner_id in staged_owner_ids:
            owner.setdefault("table_gate_source_id", owner_id)
        return output
    except (MemoryError, RecursionError, TimeoutError, TypeError, ValueError):
        return tables


def _table_overlay_transaction_items(pages, deadline):
    """Retain every initial overlay candidate for document-wide quarantine."""

    candidates = []
    for page in _bounded_table_iterable(pages, 65536):
        _check_table_deadline(deadline)
        items = page.get("items")
        for item in _bounded_table_iterable(items, 65536):
            _check_table_deadline(deadline)
            if type(item) is dict and (
                "table_evidence" in item
                or _TABLE_PREDECESSOR_SNAPSHOT_KEY in item
            ):
                candidates.append(item)
    return candidates


def seal_table_pages(pages, source_sha256, native_texts, *, table_span_fidelity_enabled=False, table_evidence_reconciliation_enabled=False, table_candidate_gate_enabled=False, table_multi_page_merge_enabled=False, table_span_fidelity_document_deadline=None, table_span_fidelity_page_deadlines=None, table_span_fidelity_state=None):
    if not table_span_fidelity_enabled:
        return
    transaction_items = []
    try:
        deadline = _resolve_table_document_deadline(
            table_span_fidelity_document_deadline
        )
        document_segment_started = perf_counter()
        try:
            _assert_table_page_container(pages, deadline)
            source_sha256 = _assert_source_sha256(source_sha256, deadline)
            if type(native_texts) is not list or len(native_texts) > 65536:
                raise TypeError("table native-text index differs")
        finally:
            _complete_table_page_segment(
                table_span_fidelity_page_deadlines,
                None,
                document_segment_started,
                perf_counter(),
                deadline,
            )
        transaction_items = _table_overlay_transaction_items(
            pages, deadline
        )
        if table_span_fidelity_page_deadlines is None:
            _seal_table_page_overlays(
                pages, source_sha256, deadline, True
            )
        else:
            _seal_table_page_overlays(
                pages,
                source_sha256,
                deadline,
                True,
                table_span_fidelity_page_deadlines,
            )
        document_segment_started = perf_counter()
        try:
            _assert_table_page_container(pages, deadline)
        finally:
            _complete_table_page_segment(
                table_span_fidelity_page_deadlines,
                None,
                document_segment_started,
                perf_counter(),
                deadline,
            )
    except _TablePredecessorIntegrityError:
        _quarantine_table_overlay_items(transaction_items)
        raise
    except (TimeoutError, _TableDocumentResourceRejection):
        if (
            type(table_span_fidelity_state) is dict
            and type(table_span_fidelity_document_deadline) in (int, float)
            and type(table_span_fidelity_document_deadline) is not bool
            and perf_counter() > table_span_fidelity_document_deadline
        ):
            table_span_fidelity_state["timed_out"] = True
        _restore_all_table_predecessors(
            pages, perf_counter() + 0.500
        )
    except (TypeError, ValueError):
        _restore_all_table_predecessors(
            pages, perf_counter() + 0.500
        )
    except (MemoryError, RecursionError):
        if type(table_span_fidelity_state) is dict:
            table_span_fidelity_state["custody_rejected"] = True
        _restore_all_table_predecessors(
            pages, perf_counter() + 0.500
        )
    return None


def finalize_table_pages(pages, source_sha256, *, table_span_fidelity_enabled=False, table_span_fidelity_document_deadline=None, table_span_fidelity_page_deadlines=None, table_span_fidelity_state=None):
    if not table_span_fidelity_enabled:
        return None
    transaction_items = []
    try:
        deadline = _resolve_table_document_deadline(
            table_span_fidelity_document_deadline
        )
        document_segment_started = perf_counter()
        try:
            _assert_table_page_container(pages, deadline)
            source_sha256 = _assert_source_sha256(source_sha256, deadline)
        finally:
            _complete_table_page_segment(
                table_span_fidelity_page_deadlines,
                None,
                document_segment_started,
                perf_counter(),
                deadline,
            )
        transaction_items = _table_overlay_transaction_items(
            pages, deadline
        )
        if table_span_fidelity_page_deadlines is None:
            _seal_table_page_overlays(
                pages, source_sha256, deadline, False
            )
        else:
            _seal_table_page_overlays(
                pages,
                source_sha256,
                deadline,
                False,
                table_span_fidelity_page_deadlines,
            )
        document_segment_started = perf_counter()
        try:
            _assert_table_page_container(pages, deadline)
        finally:
            _complete_table_page_segment(
                table_span_fidelity_page_deadlines,
                None,
                document_segment_started,
                perf_counter(),
                deadline,
            )
    except _TablePredecessorIntegrityError:
        _quarantine_table_overlay_items(transaction_items)
        raise
    except (TimeoutError, _TableDocumentResourceRejection):
        if (
            type(table_span_fidelity_state) is dict
            and type(table_span_fidelity_document_deadline) in (int, float)
            and type(table_span_fidelity_document_deadline) is not bool
            and perf_counter() > table_span_fidelity_document_deadline
        ):
            table_span_fidelity_state["timed_out"] = True
        _restore_all_table_predecessors(
            pages, perf_counter() + 0.500
        )
    except (TypeError, ValueError):
        _restore_all_table_predecessors(
            pages, perf_counter() + 0.500
        )
    except (MemoryError, RecursionError):
        if type(table_span_fidelity_state) is dict:
            table_span_fidelity_state["custody_rejected"] = True
        _restore_all_table_predecessors(
            pages, perf_counter() + 0.500
        )
    finally:
        if type(pages) is list:
            for page in tuple(pages[:65536]):
                if type(page) is not dict:
                    continue
                items = page.get("items")
                if type(items) is not list:
                    continue
                for item in tuple(items[:65536]):
                    if type(item) is dict:
                        item.pop(_TABLE_PREDECESSOR_SNAPSHOT_KEY, None)
    return None


def _table_continuation_header_rows(cells, row_count, column_count, deadline):
    leading = 0
    for row in range(row_count):
        _check_table_deadline(deadline)
        anchors = [
            cell
            for cell in cells
            if cell.get("row") == row
        ]
        covered = {
            column
            for cell in anchors
            for column in range(
                cell.get("column"),
                cell.get("column") + cell.get("col_span"),
            )
        }
        if (
            not anchors
            or covered != set(range(column_count))
            or any(cell.get("column_header") is not True for cell in anchors)
        ):
            break
        leading += 1
    return leading


def _table_continuation_caption(item, deadline):
    _check_table_deadline(deadline)
    values = []
    for name in ("caption", "title", "table_caption"):
        value = item.get(name)
        if type(value) is str:
            normalized = _table_reconciliation_text(value)
            if normalized:
                values.append(normalized)
    caption_ids = item.get("caption_ids")
    if type(caption_ids) is list and len(caption_ids) <= 64:
        for value in caption_ids:
            if type(value) is str and value:
                normalized = _table_reconciliation_text(value)
                if normalized:
                    values.append(normalized)
    return tuple(sorted(set(values)))


def _table_continuation_candidate(page, item, source_sha256, deadline):
    _check_table_deadline(deadline)
    if type(page) is not dict or type(item) is not dict or item.get("type") != "table":
        return None
    sidecar = item.get("table_evidence")
    gate = (
        sidecar.get("gate")
        if type(sidecar) is dict
        else item.get("table_candidate_gate")
    )
    if type(gate) is not dict or gate.get("outcome") != "canonical_table":
        return None
    if type(sidecar) is not dict or sidecar.get("status") != "valid":
        return None
    if sidecar.get("continuation") is not None:
        return None
    reconciliation = sidecar.get("reconciliation")
    if (
        sidecar.get("scope") != ["P04-US01", "P04-US02", "P04-US04"]
        or type(reconciliation) is not dict
        or reconciliation.get("outcome") not in (
            "singleton", "selected", "duplicate_collapsed"
        )
        or gate.get("candidate_id") != sidecar.get("candidate_id")
        or not _table_story_metadata_is_well_formed(sidecar, deadline)
        or not _table_overlay_is_well_formed(
            item,
            sidecar,
            deadline,
            source_sha256=source_sha256,
        )
    ):
        return None
    page_index = page.get("page_index")
    page_width = page.get("page_width")
    page_height = page.get("page_height")
    bbox = _table_reconciliation_bbox(item.get("bbox"))
    rows = _table_reconciliation_rows(item.get("rows"))
    row_count = len(rows) if rows is not None else 0
    column_count = len(rows[0]) if rows else 0
    cells = item.get("cells")
    table_id = sidecar.get("table_id")
    if (
        type(page_index) is not int
        or page_index < 1
        or sidecar.get("page_index") != page_index
        or type(page_width) not in (int, float)
        or type(page_width) is bool
        or not isfinite(page_width)
        or page_width <= 0
        or type(page_height) not in (int, float)
        or type(page_height) is bool
        or not isfinite(page_height)
        or page_height <= 0
        or bbox is None
        or rows is None
        or row_count < 2
        or column_count < 2
        or item.get("row_count") != row_count
        or item.get("column_count") != column_count
        or not _is_table_sha256(table_id, deadline)
        or type(cells) is not list
        or not cells
        or len(cells) > 65536
    ):
        return None
    validated_cells = []
    occupied = set()
    for cell in tuple(cells):
        _check_table_deadline(deadline)
        if type(cell) is not dict:
            return None
        row = cell.get("row")
        column = cell.get("column")
        row_span = cell.get("row_span")
        col_span = cell.get("col_span")
        cell_bbox = _table_reconciliation_bbox(cell.get("bbox"))
        if (
            not _is_table_sha256(cell.get("id"), deadline)
            or type(row) is not int
            or type(column) is not int
            or type(row_span) is not int
            or type(col_span) is not int
            or row < 0
            or column < 0
            or row_span < 1
            or col_span < 1
            or row + row_span > row_count
            or column + col_span > column_count
            or cell_bbox is None
            or cell.get("page_index") != page_index
            or type(cell.get("text")) is not str
            or type(cell.get("source_object_ids")) is not list
            or not cell.get("source_object_ids")
            or type(cell.get("evidence_ids")) is not list
            or not cell.get("evidence_ids")
        ):
            return None
        slots = {
            (row + row_offset, column + column_offset)
            for row_offset in range(row_span)
            for column_offset in range(col_span)
        }
        if occupied & slots:
            return None
        occupied.update(slots)
        validated_cells.append(cell)
    if occupied != {
        (row, column)
        for row in range(row_count)
        for column in range(column_count)
    }:
        return None
    header_rows = _table_continuation_header_rows(
        validated_cells, row_count, column_count, deadline
    )
    evidence_ids = sorted(
        {
            record.get("id")
            for record in sidecar.get("evidence", [])
            if type(record) is dict
            and _is_table_sha256(record.get("id"), deadline)
        }
    )
    if len(evidence_ids) > 64:
        return None
    return {
        "page": page,
        "item": item,
        "page_index": page_index,
        "page_width": float(page_width),
        "page_height": float(page_height),
        "bbox": bbox,
        "rows": rows,
        "cells": validated_cells,
        "row_count": row_count,
        "column_count": column_count,
        "header_rows": header_rows,
        "headers": tuple(tuple(row) for row in rows[:header_rows]),
        "caption": _table_continuation_caption(item, deadline),
        "table_id": table_id,
        "candidate_id": sidecar.get("candidate_id"),
        "evidence_ids": evidence_ids,
    }


def _table_continuation_signal_id(
    source_sha256, signal, first, second, value, deadline
):
    return _canonical_table_sha256(
        [
            "p04-us03-signal-v1",
            source_sha256,
            signal,
            first["table_id"],
            second["table_id"],
            value,
        ],
        8388608,
        deadline,
    )


def _table_continuation_pair(first, second, source_sha256, deadline):
    _check_table_deadline(deadline)
    page_indexes = [first["page_index"], second["page_index"]]
    compatible_grid = (
        second["page_index"] == first["page_index"] + 1
        and first["column_count"] == second["column_count"]
    )
    header_match = bool(
        first["headers"]
        and second["headers"]
        and first["headers"] == second["headers"]
    )
    explicit_header_conflict = bool(
        first["headers"]
        and second["headers"]
        and first["headers"] != second["headers"]
    )
    first_x = first["bbox"]["x"] / first["page_width"]
    second_x = second["bbox"]["x"] / second["page_width"]
    first_width = first["bbox"]["width"] / first["page_width"]
    second_width = second["bbox"]["width"] / second["page_width"]
    geometry_match = (
        abs(first_x - second_x) <= 0.04
        and abs(first_width - second_width) <= 0.06
    )
    first_bottom = first["bbox"]["y"] + first["bbox"]["height"]
    boundary_match = (
        first_bottom / first["page_height"] >= 0.85
        and second["bbox"]["y"] / second["page_height"] <= 0.15
    )
    caption_match = bool(
        first["caption"]
        and second["caption"]
        and any(
            "continued" in value or " cont " in f" {value} "
            for value in second["caption"]
        )
    )
    values = {
        "grid": 1.0 if compatible_grid else 0.0,
        "header": 1.0 if header_match else 0.0,
        "geometry": 1.0 if geometry_match else 0.0,
        "page_boundary": 1.0 if boundary_match else 0.0,
        "caption": 1.0 if caption_match else 0.0,
    }
    score = round(
        0.30 * values["header"]
        + 0.20 * values["geometry"]
        + 0.25 * values["page_boundary"]
        + 0.25 * values["caption"],
        6,
    )
    active_signals = [
        name for name, value in values.items() if name != "grid" and value == 1.0
    ]
    supported = (
        compatible_grid
        and not explicit_header_conflict
        and len(active_signals) >= 2
        and (header_match or caption_match)
        and score >= _TABLE_CONTINUATION_THRESHOLD
    )
    if supported:
        outcome = "merged"
        concerns = []
    elif not compatible_grid or explicit_header_conflict:
        outcome = "ineligible"
        concerns = ["table_continuation_incompatible"]
    else:
        outcome = "unresolved"
        concerns = ["table_continuation_ambiguous"]
    signal_records = []
    for name in sorted(active_signals):
        signal_id = _table_continuation_signal_id(
            source_sha256,
            name,
            first,
            second,
            values[name],
            deadline,
        )
        signal_records.append(
            {
                "id": signal_id,
                "signal": name,
                "score": values[name],
                "source_table_ids": sorted(
                    [first["table_id"], second["table_id"]]
                ),
                "source_bboxes": [
                    deepcopy(first["bbox"]),
                    deepcopy(second["bbox"]),
                ],
                "page_indexes": page_indexes,
            }
        )
    return {
        "first": first,
        "second": second,
        "outcome": outcome,
        "score": score,
        "values": values,
        "signals": signal_records,
        "concerns": concerns,
    }


def _table_continuation_merge_id(source_table_ids, page_indexes, deadline):
    return _canonical_table_sha256(
        [
            "p04-us03-merge-v1",
            sorted(source_table_ids),
            sorted(page_indexes),
        ],
        8388608,
        deadline,
    )


def _table_continuation_metadata(
    *,
    merge_id,
    outcome,
    source_table_ids,
    continued_from,
    page_indexes,
    signal_ids,
    repeated_header_cell_ids,
    evidence_ids,
    concern_codes,
):
    source_table_ids = sorted(set(source_table_ids))
    page_indexes = sorted(set(page_indexes))
    signal_ids = sorted(set(signal_ids))
    repeated_header_cell_ids = sorted(set(repeated_header_cell_ids))
    evidence_ids = sorted(set(evidence_ids))
    concern_codes = sorted(set(concern_codes))
    if (
        not source_table_ids
        or len(source_table_ids) > 32
        or not page_indexes
        or len(page_indexes) > 32
        or len(signal_ids) > 64
        or len(repeated_header_cell_ids) > 64
        or len(evidence_ids) > 64
        or len(concern_codes) > 64
    ):
        raise ValueError("table continuation metadata exceeds its cap")
    return {
        "merge_id": merge_id,
        "outcome": outcome,
        "source_table_ids": source_table_ids,
        "continued_from": continued_from,
        "page_indexes": page_indexes,
        "signal_ids": signal_ids,
        "repeated_header_cell_ids": repeated_header_cell_ids,
        "evidence_ids": evidence_ids,
        "concern_codes": concern_codes,
    }


def _table_continuation_local_sidecar(
    feature, metadata, concern_codes, deadline
):
    item = feature["item"]
    sidecar = deepcopy(item.get("table_evidence"))
    sidecar["scope"] = [
        "P04-US01", "P04-US02", "P04-US04", "P04-US03"
    ]
    sidecar["continuation"] = deepcopy(metadata)
    sidecar["concerns"] = sorted(
        set(sidecar.get("concerns") or []) | set(concern_codes)
    )
    probe = deepcopy(item)
    probe["table_evidence"] = sidecar
    if not _table_overlay_is_well_formed(
        probe,
        sidecar,
        deadline,
        source_sha256=None,
    ):
        raise ValueError("table continuation local overlay differs")
    return sidecar


def _table_continuation_derived(
    chain, edges, source_sha256, reading_order, deadline
):
    _check_table_deadline(deadline)
    source_table_ids = [feature["table_id"] for feature in chain]
    page_indexes = [feature["page_index"] for feature in chain]
    merge_id = _table_continuation_merge_id(
        source_table_ids, page_indexes, deadline
    )
    signal_records = [
        record for edge in edges for record in edge["signals"]
    ]
    signal_ids = sorted({record["id"] for record in signal_records})
    evidence_ids = sorted(
        {
            evidence_id
            for feature in chain
            for evidence_id in feature["evidence_ids"]
        }
    )
    repeated_header_cells = []
    repeated_header_ids = []
    derived_cells = []
    row_provenance = []
    row_offset = 0
    for table_index, feature in enumerate(chain):
        _check_table_deadline(deadline)
        omit_rows = 0
        if table_index > 0 and edges[table_index - 1]["values"]["header"] == 1.0:
            omit_rows = feature["header_rows"]
        for cell in feature["cells"]:
            _check_table_deadline(deadline)
            source_row = cell["row"]
            if source_row < omit_rows:
                if source_row + cell["row_span"] > omit_rows:
                    raise ValueError(
                        "table continuation header span crosses the body"
                    )
                repeated_header_cells.append(deepcopy(cell))
                repeated_header_ids.append(cell["id"])
                continue
            derived_cell = deepcopy(cell)
            derived_cell["source_cell_id"] = cell["id"]
            derived_cell["source_row"] = source_row
            derived_cell["source_column"] = cell["column"]
            derived_cell["source_table_id"] = feature["table_id"]
            derived_cell["row"] = row_offset + source_row - omit_rows
            derived_cell["derived_row"] = derived_cell["row"]
            derived_cells.append(derived_cell)
        for source_row in range(omit_rows, feature["row_count"]):
            _check_table_deadline(deadline)
            source_cells = [
                cell
                for cell in feature["cells"]
                if cell["row"] <= source_row < cell["row"] + cell["row_span"]
            ]
            if not source_cells:
                raise ValueError("table continuation row provenance differs")
            cell_bboxes = [
                _table_reconciliation_bbox(cell.get("bbox"))
                for cell in source_cells
            ]
            if any(bbox is None for bbox in cell_bboxes):
                raise ValueError("table continuation row bbox differs")
            left = min(bbox["x"] for bbox in cell_bboxes)
            top = min(bbox["y"] for bbox in cell_bboxes)
            right = max(bbox["x"] + bbox["width"] for bbox in cell_bboxes)
            bottom = max(bbox["y"] + bbox["height"] for bbox in cell_bboxes)
            derived_row = row_offset + source_row - omit_rows
            row_provenance.append(
                {
                    "id": _canonical_table_sha256(
                        [
                            "p04-us03-row-v1",
                            feature["table_id"],
                            feature["page_index"],
                            source_row,
                            derived_row,
                        ],
                        8388608,
                        deadline,
                    ),
                    "row": derived_row,
                    "page_index": feature["page_index"],
                    "source_row": source_row,
                    "source_table_id": feature["table_id"],
                    "bbox": {
                        "x": left,
                        "y": top,
                        "width": right - left,
                        "height": bottom - top,
                        "unit": "pt",
                    },
                    "source_cell_ids": sorted(
                        {cell["id"] for cell in source_cells}
                    ),
                }
            )
        row_offset += feature["row_count"] - omit_rows
    if (
        row_offset < 1
        or row_offset > 4096
        or len(derived_cells) > 65536
        or len({cell["id"] for cell in derived_cells}) != len(derived_cells)
        or len(signal_ids) != len({record["id"] for record in signal_records})
    ):
        raise ValueError("table continuation derived grid differs")
    derived_cells.sort(
        key=lambda cell: (cell["row"], cell["column"], cell["id"])
    )
    records = [
        [
            cell["row"],
            cell["column"],
            cell["row_span"],
            cell["col_span"],
            cell["text"],
        ]
        for cell in derived_cells
    ]
    cell_ids = [cell["id"] for cell in derived_cells]
    slots, missing, collision = _build_table_slots(
        records,
        cell_ids,
        row_offset,
        chain[0]["column_count"],
        source_sha256,
        chain[0]["page_index"],
        merge_id,
        merge_id,
        deadline,
    )
    if missing or collision:
        raise ValueError("table continuation derived topology differs")
    if len(repeated_header_ids) > 64 or len(evidence_ids) > 64:
        raise ValueError("table continuation traceability limit exceeded")
    continuation = _table_continuation_metadata(
        merge_id=merge_id,
        outcome="merged",
        source_table_ids=source_table_ids,
        continued_from=chain[0]["table_id"],
        page_indexes=page_indexes,
        signal_ids=signal_ids,
        repeated_header_cell_ids=repeated_header_ids,
        evidence_ids=evidence_ids,
        concern_codes=[],
    )
    derived = {
        "id": f"p04-merged-{merge_id}",
        "type": "table",
        "reading_order": reading_order,
        "bbox": None,
        "source": "derived",
        "confidence": None,
        "engine": "derived",
        "cells": derived_cells,
        "slots": slots,
        "grid": {
            "row_count": row_offset,
            "column_count": chain[0]["column_count"],
            "cell_ids": cell_ids,
        },
        "derived_from_table_ids": sorted(source_table_ids),
        "source_page_indexes": sorted(page_indexes),
        "continuation_sources": [
            {
                "table_id": feature["table_id"],
                "public_item_id": feature["item"].get("id"),
                "page_index": feature["page_index"],
                "bbox": deepcopy(feature["bbox"]),
            }
            for feature in chain
        ],
        "row_provenance": row_provenance,
        "continued_from": chain[0]["table_id"],
        "table_continuation": continuation,
        "continuation_signals": sorted(
            signal_records, key=lambda record: record["id"]
        ),
        "repeated_header_evidence": sorted(
            repeated_header_cells, key=lambda cell: cell["id"]
        ),
        "original_tables_normative": True,
        "parse_concerns": [],
        "embedded_images": [],
    }
    _apply_table_grid_serialization(
        derived,
        derived_cells,
        slots,
        row_offset,
        chain[0]["column_count"],
        deadline,
    )
    derived["representation_custody"] = _table_representation_custody(
        derived,
        row_offset,
        chain[0]["column_count"],
        deadline,
    )
    _assert_plain_table_value(derived, deadline, True)
    _assert_canonical_table_json(derived, 8388608, deadline)
    return derived, continuation


def merge_continued_tables(
    pages,
    source_sha256,
    *,
    table_span_fidelity_enabled=False,
    table_evidence_reconciliation_enabled=False,
    table_candidate_gate_enabled=False,
    table_multi_page_merge_enabled=False,
):
    if not (
        table_span_fidelity_enabled
        and table_evidence_reconciliation_enabled
        and table_candidate_gate_enabled
        and table_multi_page_merge_enabled
    ):
        return None
    if type(pages) is not list or len(pages) > 65536:
        return None
    deadline = perf_counter() + 2.0
    staged_sidecars = []
    staged_derived = []
    try:
        source_sha256 = _assert_source_sha256(source_sha256, deadline)
        if any(
            type(item) is dict
            and (
                type(item.get("table_continuation")) is dict
                or type(item.get("table_evidence")) is dict
                and item["table_evidence"].get("continuation") is not None
            )
            for page in pages
            if type(page) is dict and type(page.get("items")) is list
            for item in page["items"][:65536]
        ):
            return None
        candidates_by_page = defaultdict(list)
        features_by_id = {}
        for page in tuple(pages):
            _check_table_deadline(deadline)
            if type(page) is not dict:
                continue
            items = page.get("items")
            if type(items) is not list or len(items) > 65536:
                continue
            for item in tuple(items):
                _check_table_deadline(deadline)
                try:
                    feature = _table_continuation_candidate(
                        page, item, source_sha256, deadline
                    )
                except (RecursionError, TypeError, ValueError):
                    feature = None
                if feature is None:
                    continue
                if feature["table_id"] in features_by_id:
                    continue
                features_by_id[feature["table_id"]] = feature
                candidates_by_page[feature["page_index"]].append(feature)
        for features in candidates_by_page.values():
            features.sort(key=lambda feature: feature["table_id"])
        pair_decisions = []
        comparisons = 0
        for page_index in sorted(candidates_by_page):
            next_candidates = candidates_by_page.get(page_index + 1, [])
            if not next_candidates:
                continue
            for first in candidates_by_page[page_index]:
                for second in next_candidates:
                    comparisons += 1
                    if comparisons > 512:
                        raise ValueError(
                            "table continuation comparison limit exceeded"
                        )
                    pair_decisions.append(
                        _table_continuation_pair(
                            first, second, source_sha256, deadline
                        )
                    )
        supported_decisions = [
            decision
            for decision in pair_decisions
            if decision["outcome"] == "merged"
        ]
        outgoing_counts = defaultdict(int)
        incoming_counts = defaultdict(int)
        for decision in supported_decisions:
            outgoing_counts[decision["first"]["table_id"]] += 1
            incoming_counts[decision["second"]["table_id"]] += 1
        for decision in supported_decisions:
            if (
                outgoing_counts[decision["first"]["table_id"]] > 1
                or incoming_counts[decision["second"]["table_id"]] > 1
            ):
                decision["outcome"] = "unresolved"
                decision["concerns"] = ["table_continuation_ambiguous"]
        supported = sorted(
            (
                decision
                for decision in pair_decisions
                if decision["outcome"] == "merged"
            ),
            key=lambda decision: (
                -decision["score"],
                decision["first"]["table_id"],
                decision["second"]["table_id"],
            ),
        )
        outgoing = {}
        incoming = {}
        for decision in supported:
            first_id = decision["first"]["table_id"]
            second_id = decision["second"]["table_id"]
            if first_id in outgoing or second_id in incoming:
                continue
            outgoing[first_id] = decision
            incoming[second_id] = decision
        chains = []
        for table_id in sorted(outgoing):
            if table_id in incoming:
                continue
            chain = [features_by_id[table_id]]
            edges = []
            current_id = table_id
            observed = {table_id}
            while current_id in outgoing:
                edge = outgoing[current_id]
                next_feature = edge["second"]
                if next_feature["table_id"] in observed:
                    raise ValueError("cyclic table continuation chain")
                observed.add(next_feature["table_id"])
                edges.append(edge)
                chain.append(next_feature)
                current_id = next_feature["table_id"]
            if len(chain) >= 2:
                chains.append((chain, edges))
        consumed_ids = set()
        for chain, edges in chains:
            if len(chain) > 32:
                continue
            try:
                anchor_page = chain[0]["page"]
                reading_order = len(anchor_page.get("items") or []) + sum(
                    staged_page is anchor_page
                    for staged_page, _derived in staged_derived
                )
                derived, merged_metadata = _table_continuation_derived(
                    chain,
                    edges,
                    source_sha256,
                    reading_order,
                    deadline,
                )
            except (RecursionError, TypeError, ValueError):
                continue
            source_ids = [feature["table_id"] for feature in chain]
            signal_ids = merged_metadata["signal_ids"]
            repeated_ids = merged_metadata["repeated_header_cell_ids"]
            evidence_ids = merged_metadata["evidence_ids"]
            merge_id = merged_metadata["merge_id"]
            for index, feature in enumerate(chain):
                local_metadata = _table_continuation_metadata(
                    merge_id=merge_id,
                    outcome="page_local",
                    source_table_ids=source_ids,
                    continued_from=(
                        None if index == 0 else chain[index - 1]["table_id"]
                    ),
                    page_indexes=merged_metadata["page_indexes"],
                    signal_ids=signal_ids,
                    repeated_header_cell_ids=repeated_ids,
                    evidence_ids=evidence_ids,
                    concern_codes=[],
                )
                new_sidecar = _table_continuation_local_sidecar(
                    feature, local_metadata, [], deadline
                )
                staged_sidecars.append((feature["item"], new_sidecar, []))
                consumed_ids.add(feature["table_id"])
            staged_derived.append((chain[0]["page"], derived))
        best_refusals = {}
        for decision in pair_decisions:
            if decision["outcome"] == "merged":
                continue
            first_id = decision["first"]["table_id"]
            second_id = decision["second"]["table_id"]
            if first_id in consumed_ids or second_id in consumed_ids:
                continue
            key = (
                decision["first"]["page_index"],
                decision["second"]["page_index"],
            )
            current = best_refusals.get(key)
            if current is None or (
                -decision["score"], first_id, second_id
            ) < (
                -current["score"],
                current["first"]["table_id"],
                current["second"]["table_id"],
            ):
                best_refusals[key] = decision
        refused_ids = set()
        for decision in best_refusals.values():
            first = decision["first"]
            second = decision["second"]
            if first["table_id"] in refused_ids or second["table_id"] in refused_ids:
                continue
            source_ids = [first["table_id"], second["table_id"]]
            page_indexes = [first["page_index"], second["page_index"]]
            merge_id = _table_continuation_merge_id(
                source_ids, page_indexes, deadline
            )
            signal_ids = [record["id"] for record in decision["signals"]]
            evidence_ids = sorted(
                set(first["evidence_ids"]) | set(second["evidence_ids"])
            )
            repeated_ids = (
                [
                    cell["id"]
                    for cell in second["cells"]
                    if cell["row"] < second["header_rows"]
                ]
                if decision["values"]["header"] == 1.0
                else []
            )
            for index, feature in enumerate((first, second)):
                metadata = _table_continuation_metadata(
                    merge_id=merge_id,
                    outcome=decision["outcome"],
                    source_table_ids=source_ids,
                    continued_from=(None if index == 0 else first["table_id"]),
                    page_indexes=page_indexes,
                    signal_ids=signal_ids,
                    repeated_header_cell_ids=repeated_ids,
                    evidence_ids=evidence_ids,
                    concern_codes=decision["concerns"],
                )
                new_sidecar = _table_continuation_local_sidecar(
                    feature,
                    metadata,
                    decision["concerns"],
                    deadline,
                )
                staged_sidecars.append(
                    (feature["item"], new_sidecar, decision["concerns"])
                )
                refused_ids.add(feature["table_id"])
        sidecar_backups = [
            (
                item,
                item.get("table_evidence"),
                "parse_concerns" in item,
                item.get("parse_concerns"),
            )
            for item, _sidecar, _concerns in staged_sidecars
        ]
        page_backups = [
            (page, len(page["items"])) for page, _derived in staged_derived
        ]
        try:
            for item, sidecar, concerns in staged_sidecars:
                item["table_evidence"] = sidecar
                if concerns:
                    parse_concerns = item.get("parse_concerns")
                    if type(parse_concerns) is not list:
                        parse_concerns = []
                    item["parse_concerns"] = sorted(
                        {
                            value
                            for value in (*parse_concerns, *concerns)
                            if type(value) is str
                        }
                    )
            for page, derived in staged_derived:
                page["items"].append(derived)
        except (MemoryError, RecursionError, TypeError, ValueError):
            for item, sidecar, had_concerns, parse_concerns in sidecar_backups:
                item["table_evidence"] = sidecar
                if had_concerns:
                    item["parse_concerns"] = parse_concerns
                else:
                    item.pop("parse_concerns", None)
            for page, original_length in page_backups:
                del page["items"][original_length:]
            raise
        return None
    except (MemoryError, RecursionError, TimeoutError, TypeError, ValueError):
        return None


def _is_table_sha256(value, deadline):
    _check_table_deadline(deadline)
    return (
        type(value) is str
        and len(value) == 64
        and fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _ordered_table_hashes_are_valid(values, known, deadline):
    _check_table_deadline(deadline)
    if type(values) is not list or len(values) > 64:
        return False
    previous = ""
    valid = True
    for value in _bounded_table_iterable(values, 64):
        _check_table_deadline(deadline)
        if (
            not _is_table_sha256(value, deadline)
            or value <= previous
            or value not in known
        ):
            valid = False
        previous = value if type(value) is str else previous
    return valid


def _table_bbox_is_valid(value, deadline):
    _check_table_deadline(deadline)
    if value is None:
        return True
    if not _table_exact_keys(
        value, ("x", "y", "width", "height", "unit"), deadline
    ):
        return False
    x = value.get("x")
    y = value.get("y")
    width = value.get("width")
    height = value.get("height")
    return (
        type(x) in (int, float)
        and type(x) is not bool
        and isfinite(x)
        and x >= 0
        and type(y) in (int, float)
        and type(y) is not bool
        and isfinite(y)
        and y >= 0
        and type(width) in (int, float)
        and type(width) is not bool
        and isfinite(width)
        and width > 0
        and type(height) in (int, float)
        and type(height) is not bool
        and isfinite(height)
        and height > 0
        and value.get("unit") == "pt"
    )


def _table_public_projection(table, deadline):
    _check_table_deadline(deadline)
    if type(table) is not dict:
        raise TypeError("table projection differs")
    projected = {}
    for entry in _bounded_table_iterable(tuple(table.items()), 4096):
        _check_table_deadline(deadline)
        key, value = entry
        if key not in ("table_evidence", _TABLE_PREDECESSOR_SNAPSHOT_KEY):
            projected[key] = value
    return projected


def _table_authoritative_projection_matches(table, snapshot, deadline):
    _check_table_deadline(deadline)
    if type(table) is not dict or type(snapshot) is not dict:
        return False
    for key in _bounded_table_iterable(
        _TABLE_AUTHORITATIVE_PROJECTION_KEYS,
        len(_TABLE_AUTHORITATIVE_PROJECTION_KEYS),
    ):
        _check_table_deadline(deadline)
        if (key in table) != (key in snapshot) or table.get(key) != snapshot.get(
            key
        ):
            return False
    return True


def _table_snapshot_with_current_unrelated_fields(table, snapshot, deadline):
    _check_table_deadline(deadline)
    if type(table) is not dict or type(snapshot) is not dict:
        raise TypeError("table snapshot refresh differs")
    # `_table_predecessor_snapshot` admitted this graph immediately before
    # this private helper. Copy its aliases without a redundant traversal;
    # the completed refresh is fully revalidated below after bounded fields
    # are applied.
    refreshed = deepcopy(snapshot)
    for key in _bounded_table_iterable(
        _TABLE_DOWNSTREAM_SNAPSHOT_KEYS,
        len(_TABLE_DOWNSTREAM_SNAPSHOT_KEYS),
    ):
        _check_table_deadline(deadline)
        if key not in table:
            refreshed.pop(key, None)
            continue
        value = table.get(key)
        valid = False
        if key == "id":
            valid = (
                type(value) is str
                and bool(value)
                and len(value.encode("utf-8")) <= 256
                and not _table_text_has_unsafe_control(value, deadline)
            )
        elif key == "reading_order":
            valid = type(value) is int and 0 <= value <= 65535
        elif key in (
            "caption_ids",
            "caption_of",
            "source_note_ids",
            "footnote_ids",
            "contains_ids",
        ):
            if type(value) is list and len(value) <= 64:
                valid = True
                observed = {}
                for identifier in _bounded_table_iterable(value, 64):
                    _check_table_deadline(deadline)
                    if (
                        type(identifier) is not str
                        or not identifier
                        or len(identifier.encode("utf-8")) > 256
                        or _table_text_has_unsafe_control(
                            identifier, deadline
                        )
                        or identifier in observed
                    ):
                        valid = False
                    observed[identifier] = True
        elif key in ("relationships", "contained_items"):
            # These fields are owned and bounded by predecessor projection
            # stages.  Preserve their exact current value without imposing a
            # narrower table-specific cardinality: the strict plain-data,
            # active-deadline, 8 MiB marked-item, and document aggregate gates
            # below still apply.
            valid = (
                type(value) is list
                and len(value) <= _TABLE_DOWNSTREAM_LIST_MAX_ITEMS
            )
            if valid:
                for record in _bounded_table_iterable(
                    value, _TABLE_DOWNSTREAM_LIST_MAX_ITEMS
                ):
                    _check_table_deadline(deadline)
                    if type(record) is not dict or len(record) > 64:
                        valid = False
        else:
            valid = value is True
        if not valid:
            raise ValueError("table downstream snapshot field differs")
        refreshed[key] = value
    # ``refreshed`` is already an owned deep copy. Validate the completed
    # snapshot in place rather than allocating and traversing a second copy.
    _assert_plain_table_value(refreshed, deadline)
    return refreshed


def _table_without_snapshot(table, deadline):
    _check_table_deadline(deadline)
    if type(table) is not dict:
        raise TypeError("table projection differs")
    projected = {}
    for entry in _bounded_table_iterable(tuple(table.items()), 4096):
        _check_table_deadline(deadline)
        key, value = entry
        if key != _TABLE_PREDECESSOR_SNAPSHOT_KEY:
            projected[key] = value
    return projected


def _table_predecessor_snapshot(table, deadline):
    _check_table_deadline(deadline)
    snapshot = table.get(_TABLE_PREDECESSOR_SNAPSHOT_KEY)
    if type(snapshot) is not dict:
        return None
    try:
        _assert_canonical_table_json(snapshot, 8388608, deadline)
    except (TypeError, ValueError, TimeoutError):
        return None
    if (
        "table_evidence" in snapshot
        or _TABLE_PREDECESSOR_SNAPSHOT_KEY in snapshot
    ):
        return None
    return snapshot


def _restore_table_predecessor(table, snapshot, deadline):
    _check_table_deadline(deadline)
    if not _restore_table_predecessor_exact(table, snapshot):
        if type(table) is dict:
            table.clear()
        raise _TablePredecessorIntegrityError(
            "table predecessor snapshot is unavailable"
        )
    return None


def _table_snapshot_is_structurally_restorable(snapshot):
    try:
        if (
            type(snapshot) is not dict
            or len(snapshot) > 4096
            or "table_evidence" in snapshot
            or _TABLE_PREDECESSOR_SNAPSHOT_KEY in snapshot
        ):
            return False
        pending = [(snapshot, 0, False)]
        active = {}
        node_count = 0
        encoded_bytes = 0
        while pending:
            current, depth, leaving = pending.pop()
            if leaving:
                active.pop(id(current), None)
                continue
            node_count += 1
            if node_count > 4194304 or depth > 32:
                return False
            current_type = type(current)
            if current is None:
                encoded_bytes += 4
            elif current_type is bool:
                encoded_bytes += 4 if current else 5
            elif current_type is int:
                if current.bit_length() > 3321928:
                    return False
                encoded_bytes += len(str(current).encode("ascii"))
            elif current_type is float:
                if not isfinite(current):
                    return False
                encoded_bytes += len(
                    dumps(current, allow_nan=False).encode("ascii")
                )
            elif current_type is str:
                raw = current.encode("utf-8")
                if len(raw) > 1048576:
                    return False
                encoded_bytes += len(
                    dumps(current, ensure_ascii=False).encode("utf-8")
                )
            elif current_type in (dict, list):
                if depth >= 32:
                    return False
                identity = id(current)
                if identity in active:
                    return False
                active[identity] = True
                if current_type is dict:
                    if len(current) > 4096:
                        return False
                    entries = tuple(current.items())
                    encoded_bytes += 2 + max(len(entries) - 1, 0)
                    pending.append((current, depth, True))
                    for key, value in entries:
                        if type(key) is not str:
                            return False
                        raw_key = key.encode("utf-8")
                        if len(raw_key) > 1048576:
                            return False
                        encoded_bytes += 1 + len(
                            dumps(key, ensure_ascii=False).encode("utf-8")
                        )
                        pending.append((value, depth + 1, False))
                else:
                    if len(current) > 65536:
                        return False
                    encoded_bytes += 2 + max(len(current) - 1, 0)
                    pending.append((current, depth, True))
                    for value in current:
                        pending.append((value, depth + 1, False))
            else:
                return False
            if encoded_bytes > 8388608:
                return False
        return True
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        return False


def _restore_table_predecessor_exact(table, snapshot):
    if type(table) is not dict or not _table_snapshot_is_structurally_restorable(
        snapshot
    ):
        return False
    try:
        restored = deepcopy(snapshot)
        table.clear()
        table.update(restored)
    except (MemoryError, RecursionError, TypeError, ValueError):
        # A failed install must not leave a partially restored projection.
        # ``dict.clear`` does not allocate, so it remains the fail-closed
        # terminal state even when the copy/update failed for lack of memory.
        table.clear()
        return False
    return True


def _quarantine_table_overlay_items(items):
    """Remove every candidate when an exact document rollback is impossible."""

    for item in items:
        if type(item) is dict:
            item.clear()


def _restore_all_table_predecessors(pages, deadline):
    # Emergency rollback intentionally remains available after the governed
    # deadline has expired.  Validate and copy every predecessor before the
    # first mutation so the document commits wholly to predecessor state or
    # returns no table candidate at all.
    candidates = []
    staged = []
    try:
        if type(pages) is not list or len(pages) > 65536:
            raise _TablePredecessorIntegrityError(
                "table predecessor snapshot is unavailable"
            )
        for page in tuple(pages):
            if type(page) is not dict:
                continue
            items = page.get("items")
            if type(items) is not list or len(items) > 65536:
                raise _TablePredecessorIntegrityError(
                    "table predecessor snapshot is unavailable"
                )
            for item in tuple(items):
                if type(item) is not dict or (
                    "table_evidence" not in item
                    and _TABLE_PREDECESSOR_SNAPSHOT_KEY not in item
                ):
                    continue
                candidates.append(item)
        for item in candidates:
            snapshot = item.get(_TABLE_PREDECESSOR_SNAPSHOT_KEY)
            if not _table_snapshot_is_structurally_restorable(snapshot):
                raise _TablePredecessorIntegrityError(
                    "table predecessor snapshot is unavailable"
                )
            staged.append((item, deepcopy(snapshot)))
    except _TablePredecessorIntegrityError:
        _quarantine_table_overlay_items(candidates)
        raise
    except (MemoryError, RecursionError, TypeError, ValueError) as exc:
        _quarantine_table_overlay_items(candidates)
        raise _TablePredecessorIntegrityError(
            "table predecessor snapshot is unavailable"
        ) from exc

    try:
        for item, restored in staged:
            item.clear()
            item.update(restored)
    except (MemoryError, RecursionError, TypeError, ValueError) as exc:
        _quarantine_table_overlay_items(candidates)
        raise _TablePredecessorIntegrityError(
            "table predecessor snapshot is unavailable"
        ) from exc
    return None


def _reject_table_overlay(table, deadline):
    if type(table) is not dict:
        return None
    snapshot = table.get(_TABLE_PREDECESSOR_SNAPSHOT_KEY)
    if not _restore_table_predecessor_exact(table, snapshot):
        table.clear()
        raise _TablePredecessorIntegrityError(
            "table predecessor snapshot is unavailable"
        )
    return None


def _assert_table_page_container(pages, deadline):
    _check_table_deadline(deadline)
    if type(pages) is not list or len(pages) > 65536:
        raise TypeError("table pages container differs")
    for page in _bounded_table_iterable(pages, 65536):
        _check_table_deadline(deadline)
        if type(page) is not dict:
            raise TypeError("table page differs")
        items = page.get("items")
        if type(items) is not list or len(items) > 65536:
            raise TypeError("table page items differ")
        for item in _bounded_table_iterable(items, 65536):
            _check_table_deadline(deadline)
            if type(item) is not dict:
                raise TypeError("table page item differs")
    return None


def detach_table_overlays_for_phase03(pages, *, deadline):
    """Hold literal P04 table dictionaries outside every P03 consumer.

    The returned tuple is the transaction token.  Raw Docling relationships
    are deliberately untouched: this seam replaces only public table
    dictionaries with their exact predecessor snapshots.
    """

    _assert_table_page_container(pages, deadline)
    staged = []
    replacements = []
    seen_ids = {}
    for page_offset, page in enumerate(_bounded_table_iterable(pages, 65536)):
        _check_table_deadline(deadline)
        page_index = page.get("page_index")
        if type(page_index) is not int or page_index < 1:
            raise ValueError("table overlay page identity differs")
        items = page["items"]
        for item_offset, item in enumerate(
            _bounded_table_iterable(items, 65536)
        ):
            _check_table_deadline(deadline)
            if type(item.get("table_evidence")) is not dict:
                continue
            snapshot = _table_predecessor_snapshot(item, deadline)
            if snapshot is None:
                raise ValueError("table overlay predecessor snapshot is absent")
            # Hold only the public P04 overlay.  Copying the complete marked
            # item here also copied its independently retained predecessor,
            # even though the transaction stores a separately frozen
            # predecessor below and never consumes the embedded snapshot.
            # Project before copying so an untrusted non-cyclic alias between
            # a public field and the snapshot is split by the two independent
            # ownership operations rather than preserved by one deepcopy.
            public_overlay = _table_without_snapshot(item, deadline)
            overlay = _validate_plain_table_value(public_overlay, deadline)
            # `_table_predecessor_snapshot` has already completed the stricter
            # canonical/plain admission. Keep one private frozen copy for the
            # transaction without repeating that full validation traversal.
            predecessor = deepcopy(snapshot)
            _check_table_deadline(deadline)
            delta_keys = {
                key
                for key in set(overlay) | set(predecessor)
                if key != _TABLE_PREDECESSOR_SNAPSHOT_KEY
                and (
                    (key in overlay) != (key in predecessor)
                    or overlay.get(key) != predecessor.get(key)
                )
            }
            if (
                "table_evidence" not in delta_keys
                or not delta_keys <= _TABLE_P04_DELTA_KEYS
            ):
                raise ValueError("table overlay P04 delta differs")
            item_id = predecessor.get("id")
            reading_order = predecessor.get("reading_order")
            if (
                type(item_id) is not str
                or not item_id
                or type(reading_order) is not int
                or reading_order != item_offset
                or item_id in seen_ids
            ):
                raise ValueError("table overlay predecessor identity differs")
            seen_ids[item_id] = True
            staged.append(
                (
                    page_offset,
                    page_index,
                    item_offset,
                    item_id,
                    reading_order,
                    overlay,
                    predecessor,
                )
            )
            replacements.append(
                (
                    page_offset,
                    item_offset,
                    deepcopy(predecessor),
                )
            )
    # Commit only after every marked item is closed, so a malformed later
    # overlay cannot leave a partially detached document.
    for page_offset, item_offset, installed_predecessor in replacements:
        pages[page_offset]["items"][item_offset] = installed_predecessor
    return tuple(staged)


def rebind_table_overlays_after_phase03(
    pages,
    transaction,
    *,
    deadline,
    transaction_is_owned=False,
):
    """Reapply one held overlay to an exact P03 terminal predecessor copy."""

    _assert_table_page_container(pages, deadline)
    if type(transaction_is_owned) is not bool:
        raise TypeError("table overlay transaction ownership differs")
    if type(transaction) is not tuple or len(transaction) > 65536:
        raise TypeError("table overlay transaction differs")
    if transaction_is_owned:
        # The pipeline's private token was fully admitted and copied by the
        # atomic detacher. It is never exposed to a Phase 03 consumer.
        _check_table_deadline(deadline)
    else:
        transaction = _validate_plain_table_value(transaction, deadline)
    candidate_pages = _validate_plain_table_value(pages, deadline)
    terminal_locations = {}
    for terminal_page_offset, terminal_page in enumerate(candidate_pages):
        terminal_items = terminal_page.get("items")
        if type(terminal_items) is not list or [
            item.get("reading_order") if type(item) is dict else None
            for item in terminal_items
        ] != list(range(len(terminal_items))):
            raise ValueError("table overlay terminal reading order differs")
        for terminal_offset, terminal_item in enumerate(terminal_items):
            _check_table_deadline(deadline)
            terminal_id = terminal_item.get("id")
            if type(terminal_id) is not str or not terminal_id:
                raise ValueError("table overlay terminal item identity differs")
            terminal_locations.setdefault(terminal_id, []).append(
                (terminal_page_offset, terminal_offset, terminal_item)
            )
    seen_locations = {}
    for record in _bounded_table_iterable(transaction, 65536):
        _check_table_deadline(deadline)
        if type(record) is not tuple or len(record) != 7:
            raise TypeError("table overlay transaction record differs")
        (
            page_offset,
            page_index,
            item_offset,
            item_id,
            reading_order,
            overlay,
            original_snapshot,
        ) = record
        location = (page_index, item_id)
        if (
            type(page_offset) is not int
            or type(page_index) is not int
            or type(item_offset) is not int
            or type(item_id) is not str
            or type(reading_order) is not int
            or location in seen_locations
            or not 0 <= page_offset < len(candidate_pages)
        ):
            raise ValueError("table overlay transaction identity differs")
        seen_locations[location] = True
        page = candidate_pages[page_offset]
        items = page.get("items")
        if (
            page.get("page_index") != page_index
            or type(items) is not list
        ):
            raise ValueError("table overlay terminal page binding differs")
        terminal_matches = terminal_locations.get(item_id, [])
        if len(terminal_matches) != 1:
            raise ValueError("table overlay terminal item identity differs")
        matched_page_offset, terminal_offset, predecessor = terminal_matches[0]
        if (
            matched_page_offset != page_offset
            or type(predecessor) is not dict
            or predecessor.get("type") != "table"
            or predecessor.get("reading_order") != terminal_offset
            or "table_evidence" in predecessor
            or _TABLE_PREDECESSOR_SNAPSHOT_KEY in predecessor
        ):
            raise ValueError("table overlay terminal item binding differs")
        # `candidate_pages` is already a validated private deep copy. Retain
        # exactly one independent terminal predecessor, then apply the bounded
        # P04 delta in place instead of allocating and validating two more
        # complete table graphs.
        candidate = predecessor
        terminal_snapshot = deepcopy(predecessor)
        _check_table_deadline(deadline)
        original_overlay = overlay
        frozen_snapshot = original_snapshot
        delta_keys = {
            key
            for key in set(original_overlay) | set(frozen_snapshot)
            if key != _TABLE_PREDECESSOR_SNAPSHOT_KEY
            and (
                (key in original_overlay) != (key in frozen_snapshot)
                or original_overlay.get(key) != frozen_snapshot.get(key)
            )
        }
        if (
            "table_evidence" not in delta_keys
            or not delta_keys <= _TABLE_P04_DELTA_KEYS
        ):
            raise ValueError("table overlay P04 delta differs")
        for key in _bounded_table_iterable(tuple(sorted(delta_keys)), 64):
            _check_table_deadline(deadline)
            if key in original_overlay:
                candidate[key] = deepcopy(original_overlay[key])
            else:
                candidate.pop(key, None)
        candidate[_TABLE_PREDECESSOR_SNAPSHOT_KEY] = terminal_snapshot
        items[terminal_offset] = candidate
    _assert_table_page_container(candidate_pages, deadline)
    return candidate_pages


def _table_pdf_recovery_sources_are_exact(
    source_objects,
    source_sha256,
    page_index,
    table_reference,
    emitted_rows,
    emitted_columns,
    deadline,
):
    _check_table_deadline(deadline)
    pdf_sources = [
        source
        for source in source_objects
        if source.get("engine") == "pdfplumber"
    ]
    if not pdf_sources:
        return [True, emitted_rows, {}]
    if source_sha256 is None or len(pdf_sources) > 48:
        return [False, emitted_rows, {}]
    has_bottom = any(source.get("role") == "bottom_row" for source in pdf_sources)
    predecessor_rows = emitted_rows - (1 if has_bottom else 0)
    if predecessor_rows < 2:
        return [False, emitted_rows, {}]
    by_locator = {}
    observed_geometry = {}
    roles = {"header": 0, "body_control": 0, "bottom_row": 0}
    for source in _bounded_table_iterable(pdf_sources, 48):
        _check_table_deadline(deadline)
        if not _table_exact_keys(
            source, _TABLE_PDFPLUMBER_SOURCE_KEYS, deadline
        ):
            return [False, predecessor_rows, {}]
        role = source.get("role")
        target_row = source.get("target_row")
        target_column = source.get("target_column")
        words = source.get("words")
        if (
            source.get("object_type") != "table_word_set"
            or source.get("raw_ref") is not None
            or role not in roles
            or type(target_row) is not int
            or type(target_column) is not int
            or target_column < 0
            or target_column >= emitted_columns
            or target_row
            != (
                0
                if role == "header"
                else 1
                if role == "body_control"
                else predecessor_rows
            )
            or type(words) is not list
            or not 1 <= len(words) <= 64
        ):
            return [False, predecessor_rows, {}]
        locator = (role, target_row, target_column)
        if locator in by_locator:
            return [False, predecessor_rows, {}]
        roles[role] += 1
        by_locator[locator] = source
        previous_geometry = None
        word_ids = []
        content_words = []
        for word in _bounded_table_iterable(words, 64):
            _check_table_deadline(deadline)
            if not _table_exact_keys(word, _TABLE_WORD_KEYS, deadline):
                return [False, predecessor_rows, {}]
            text = word.get("text")
            font_name = word.get("font_name")
            bbox = word.get("bbox")
            try:
                text_size = len(text.encode("utf-8")) if type(text) is str else 0
                if type(font_name) is str:
                    font_name.encode("utf-8")
            except UnicodeEncodeError:
                return [False, predecessor_rows, {}]
            if (
                type(text) is not str
                or not text.strip()
                or text_size > 16384
                or _table_text_has_unsafe_control(text, deadline)
                or not _table_font_name_is_safe(font_name, deadline)
                or type(word.get("bold")) is not bool
                or word.get("bold") != ("bold" in font_name.casefold())
                or not _table_bbox_is_valid(bbox, deadline)
            ):
                return [False, predecessor_rows, {}]
            geometry = (
                bbox.get("y"),
                bbox.get("x"),
                bbox.get("height"),
                bbox.get("width"),
            )
            if (
                previous_geometry is not None
                and geometry <= previous_geometry
                or geometry in observed_geometry
            ):
                return [False, predecessor_rows, {}]
            previous_geometry = geometry
            observed_geometry[geometry] = True
            expected_word_id = _canonical_table_sha256(
                [
                    "p04-pdfplumber-word-id-v1",
                    source_sha256,
                    page_index,
                    table_reference,
                    predecessor_rows,
                    emitted_columns,
                    role,
                    target_row,
                    target_column,
                    bbox,
                ],
                8388608,
                deadline,
            )
            if word.get("id") != expected_word_id:
                return [False, predecessor_rows, {}]
            word_ids.append(expected_word_id)
            content_words.append(
                [
                    expected_word_id,
                    text,
                    bbox,
                    font_name,
                    word.get("bold"),
                ]
            )
        expected_content_sha256 = _canonical_table_sha256(
            [
                "p04-pdfplumber-word-set-content-v1",
                role,
                target_row,
                target_column,
                content_words,
            ],
            8388608,
            deadline,
        )
        expected_source_id = _canonical_table_sha256(
            [
                "p04-pdfplumber-word-set-id-v1",
                source_sha256,
                page_index,
                table_reference,
                predecessor_rows,
                emitted_columns,
                role,
                target_row,
                target_column,
                word_ids,
            ],
            8388608,
            deadline,
        )
        if (
            source.get("content_sha256") != expected_content_sha256
            or source.get("id") != expected_source_id
        ):
            return [False, predecessor_rows, {}]
    header_present = roles["header"] > 0 or roles["body_control"] > 0
    if header_present and (
        roles["header"] != emitted_columns
        or roles["body_control"] != emitted_columns
    ):
        return [False, predecessor_rows, {}]
    if has_bottom and roles["bottom_row"] != emitted_columns:
        return [False, predecessor_rows, {}]
    if not has_bottom and roles["bottom_row"] != 0:
        return [False, predecessor_rows, {}]
    return [True, predecessor_rows, by_locator]


def _table_source_bound_identity_is_valid(table, sidecar, source_objects, source_sha256, deadline):
    _check_table_deadline(deadline)
    geometry_sources = []
    grid_sources = []
    cell_references = []
    for source_object in _bounded_table_iterable(source_objects, 65536):
        _check_table_deadline(deadline)
        object_type = source_object.get("object_type")
        if object_type == "table_geometry":
            geometry_sources.append(source_object)
        elif object_type == "table_grid":
            grid_sources.append(source_object)
        elif object_type == "table_cell":
            cell_references.append(source_object.get("raw_ref"))
    if len(geometry_sources) != 1 or len(grid_sources) != 1:
        return False
    geometry_source = geometry_sources[0]
    grid_source = grid_sources[0]
    table_reference = geometry_source.get("raw_ref")
    if (
        grid_source.get("raw_ref") != table_reference
        or table.get("type") != "table"
        or table.get("engine") != "docling"
        or table.get("source") not in ("native", "ocr")
    ):
        return False
    observed_direct_references = {}
    for raw_reference in _bounded_table_iterable(
        cell_references, 65536
    ):
        _check_table_deadline(deadline)
        if raw_reference == table_reference:
            continue
        if raw_reference in observed_direct_references:
            return False
        observed_direct_references[raw_reference] = True
    page_index = sidecar.get("page_index")
    grid = sidecar.get("grid")
    row_count = grid.get("row_count")
    column_count = grid.get("column_count")
    recovery_result = _table_pdf_recovery_sources_are_exact(
        source_objects,
        source_sha256,
        page_index,
        table_reference,
        row_count,
        column_count,
        deadline,
    )
    if not recovery_result[0]:
        return False
    predecessor_row_count = recovery_result[1]
    table_bbox = _docling_table_bbox(table, deadline)
    expected_geometry_content = _canonical_table_sha256(
        ["p04-geometry-source-content-v1", table_bbox, page_index],
        8388608,
        deadline,
    )
    if geometry_source.get("content_sha256") != expected_geometry_content:
        return False
    if source_sha256 is None:
        return True
    expected_table_id = _canonical_table_sha256(
        [
            "p04-table-id-v1",
            source_sha256,
            page_index,
            "docling",
            table_reference,
            table_bbox,
            row_count,
            column_count,
        ],
        8388608,
        deadline,
    )
    expected_candidate_id = _canonical_table_sha256(
        [
            "p04-candidate-id-v1",
            source_sha256,
            page_index,
            "docling",
            table_reference,
            table_bbox,
            predecessor_row_count,
            column_count,
        ],
        8388608,
        deadline,
    )
    expected_geometry_source_id = _canonical_table_sha256(
        [
            "p04-geometry-source-id-v1",
            source_sha256,
            page_index,
            "docling",
            table_reference,
            table_bbox,
        ],
        8388608,
        deadline,
    )
    expected_grid_source_id = _canonical_table_sha256(
        [
            "p04-structure-source-id-v1",
            source_sha256,
            page_index,
            "docling",
            table_reference,
            predecessor_row_count,
            column_count,
        ],
        8388608,
        deadline,
    )
    return (
        sidecar.get("table_id") == expected_table_id
        and sidecar.get("candidate_id") == expected_candidate_id
        and geometry_source.get("id") == expected_geometry_source_id
        and grid_source.get("id") == expected_grid_source_id
    )


def _table_cell_evidence_is_valid(cell, source_by_id, evidence_by_id, concerns, deadline):
    _check_table_deadline(deadline)
    linked_source_ids = cell.get("source_object_ids")
    linked_evidence_ids = cell.get("evidence_ids")
    if (
        type(linked_source_ids) is not list
        or len(linked_source_ids) != 1
        or type(linked_evidence_ids) is not list
        or not linked_evidence_ids
    ):
        return False
    cell_source = source_by_id.get(linked_source_ids[0])
    if type(cell_source) is not dict or cell_source.get("object_type") not in (
        "table_cell",
        "table_word_set",
    ):
        return False
    recovered_bottom = cell_source.get("object_type") == "table_word_set"
    if recovered_bottom and cell_source.get("role") != "bottom_row":
        return False
    text_count = 0
    geometry_count = 0
    structure_count = 0
    header_count = 0
    recovered_header = False
    for evidence_id in _bounded_table_iterable(linked_evidence_ids, 64):
        _check_table_deadline(deadline)
        evidence_record = evidence_by_id.get(evidence_id)
        if type(evidence_record) is not dict:
            return False
        dimension = evidence_record.get("dimension")
        linked = evidence_record.get("source_object_ids")
        if dimension == "text":
            if (
                linked != linked_source_ids
                or evidence_record.get("bbox") != cell.get("bbox")
                or evidence_record.get("content_sha256")
                != cell_source.get("content_sha256")
                or evidence_record.get("method")
                != ("native_text" if cell.get("source") == "native" else "ocr_text")
            ):
                return False
            text_count += 1
        elif dimension == "geometry":
            if (
                linked != linked_source_ids
                or evidence_record.get("bbox") != cell.get("bbox")
                or evidence_record.get("content_sha256")
                != cell_source.get("content_sha256")
                or evidence_record.get("method")
                != (
                    "recovered_structure"
                    if recovered_bottom
                    else "embedded_grid"
                )
            ):
                return False
            geometry_count += 1
        elif dimension == "structure":
            linked_types = [
                source_by_id.get(source_id, {}).get("object_type")
                for source_id in linked
            ]
            if linked_types.count("table_grid") != 1 or (
                evidence_record.get("method") == "source_grid"
                and len(linked) != 1
                or evidence_record.get("method")
                not in ("source_grid", "recovered_structure")
            ):
                return False
            structure_count += 1
        elif dimension == "header":
            linked_types = [
                source_by_id.get(source_id, {}).get("object_type")
                for source_id in linked
            ]
            if linked_types.count("table_grid") != 1 or (
                evidence_record.get("method") == "model_structure"
                and len(linked) != 1
                or evidence_record.get("method") == "recovered_structure"
                and (
                    len(linked) != 3
                    or linked_types.count("table_word_set") != 2
                )
                or evidence_record.get("method")
                not in ("model_structure", "recovered_structure")
            ):
                return False
            if evidence_record.get("method") == "recovered_structure":
                recovered_header = True
            header_count += 1
        else:
            return False
    has_span = cell.get("row_span") > 1 or cell.get("col_span") > 1
    has_header = cell.get("column_header") is True or cell.get("row_header") is True
    bbox = cell.get("bbox")
    if (
        text_count != 1
        or geometry_count != (1 if has_span or recovered_bottom else 0)
        or structure_count
        != (1 if has_span or recovered_bottom or recovered_header else 0)
        or header_count != (1 if has_header else 0)
        or (bbox is None and "table_source_cell_bbox_unresolved" not in concerns)
        or (has_span and bbox is None)
    ):
        return False
    return True


def _table_valid_cells_are_source_bound(table, sidecar, cells, source_by_id, evidence_by_id, source_sha256, deadline):
    _check_table_deadline(deadline)
    grid = sidecar.get("grid")
    emitted_rows = grid.get("row_count")
    emitted_columns = grid.get("column_count")
    page_index = sidecar.get("page_index")
    grid_sources = [
        source
        for source in source_by_id.values()
        if source.get("object_type") == "table_grid"
    ]
    geometry_sources = [
        source
        for source in source_by_id.values()
        if source.get("object_type") == "table_geometry"
    ]
    if len(grid_sources) != 1 or len(geometry_sources) != 1:
        return False
    grid_source = grid_sources[0]
    geometry_source = geometry_sources[0]
    table_reference = grid_source.get("raw_ref")
    pdf_result = _table_pdf_recovery_sources_are_exact(
        list(source_by_id.values()),
        source_sha256,
        page_index,
        table_reference,
        emitted_rows,
        emitted_columns,
        deadline,
    )
    if not pdf_result[0]:
        return False
    predecessor_rows = pdf_result[1]
    pdf_by_locator = pdf_result[2]
    pdf_sources = [
        source
        for source in source_by_id.values()
        if source.get("object_type") == "table_word_set"
    ]
    recovered_header_columns = {
        source.get("target_column")
        for source in pdf_sources
        if source.get("role") == "header"
    }
    base_cells_by_location = {}
    recovered_bottom_by_column = {}
    normalized_cells = []
    expected_source_by_id = {}
    expected_evidence_by_id = {}
    table_bbox = _docling_table_bbox(table, deadline)
    if table_bbox is None:
        return False

    if source_sha256 is not None:
        expected_geometry_source_id = _canonical_table_sha256(
            [
                "p04-geometry-source-id-v1",
                source_sha256,
                page_index,
                "docling",
                table_reference,
                table_bbox,
            ],
            8388608,
            deadline,
        )
        expected_geometry_content = _canonical_table_sha256(
            ["p04-geometry-source-content-v1", table_bbox, page_index],
            8388608,
            deadline,
        )
        expected_geometry_source = {
            "id": expected_geometry_source_id,
            "engine": "docling",
            "object_type": "table_geometry",
            "page_index": page_index,
            "raw_ref": table_reference,
            "content_sha256": expected_geometry_content,
        }
        expected_source_by_id[expected_geometry_source_id] = (
            expected_geometry_source
        )
        expected_geometry_evidence_id = _canonical_table_sha256(
            [
                "p04-geometry-evidence-id-v1",
                source_sha256,
                page_index,
                "docling",
                table_reference,
                table_bbox,
            ],
            8388608,
            deadline,
        )
        expected_evidence_by_id[expected_geometry_evidence_id] = {
            "id": expected_geometry_evidence_id,
            "method": "embedded_grid",
            "dimension": "geometry",
            "page_index": page_index,
            "bbox": table_bbox,
            "source_object_ids": [expected_geometry_source_id],
            "confidence": 1.0,
            "content_sha256": expected_geometry_content,
        }

    for cell in _bounded_table_iterable(cells, 65536):
        _check_table_deadline(deadline)
        linked_source_ids = cell.get("source_object_ids")
        cell_source = source_by_id.get(linked_source_ids[0])
        bbox = cell.get("bbox")
        if bbox is not None and not _table_content_bbox_within_region(
            bbox,
            table_bbox,
            deadline,
        ):
            return False
        source_type = cell_source.get("object_type")
        if source_type == "table_cell":
            location = (cell.get("row"), cell.get("column"))
            if location in base_cells_by_location or cell.get("row") >= predecessor_rows:
                return False
            base_cells_by_location[location] = cell
            recovered_header = cell.get("column") in recovered_header_columns and (
                cell.get("row") == 0
            )
            original_column_header = (
                False if recovered_header else cell.get("column_header")
            )
            raw_reference = cell_source.get("raw_ref")
            normalized_cells.append(
                [
                    cell.get("row"),
                    cell.get("column"),
                    cell.get("row_span"),
                    cell.get("col_span"),
                    cell.get("text"),
                    original_column_header,
                    cell.get("row_header"),
                    cell.get("row_section"),
                    bbox,
                    raw_reference,
                ]
            )
            expected_content_sha256 = _canonical_table_sha256(
                [
                    "p04-cell-content-v1",
                    raw_reference,
                    bbox,
                    cell.get("row"),
                    cell.get("column"),
                    cell.get("row_span"),
                    cell.get("col_span"),
                    cell.get("text"),
                    original_column_header,
                    cell.get("row_header"),
                    cell.get("row_section"),
                ],
                8388608,
                deadline,
            )
            if cell_source.get("content_sha256") != expected_content_sha256:
                return False
            if source_sha256 is None:
                continue
            identity_tail = [
                source_sha256,
                page_index,
                "docling",
                raw_reference,
                bbox,
                cell.get("row"),
                cell.get("column"),
                cell.get("row_span"),
                cell.get("col_span"),
            ]
            expected_cell_id = _canonical_table_sha256(
                ["p04-cell-id-v1", identity_tail], 8388608, deadline
            )
            expected_source_id = _canonical_table_sha256(
                ["p04-cell-source-id-v1", identity_tail], 8388608, deadline
            )
            expected_text_evidence_id = _canonical_table_sha256(
                ["p04-text-evidence-id-v1", identity_tail],
                8388608,
                deadline,
            )
            if (
                cell.get("id") != expected_cell_id
                or cell_source.get("id") != expected_source_id
                or expected_text_evidence_id not in cell.get("evidence_ids")
            ):
                return False
            expected_source_by_id[expected_source_id] = {
                "id": expected_source_id,
                "engine": "docling",
                "object_type": "table_cell",
                "page_index": page_index,
                "raw_ref": raw_reference,
                "content_sha256": expected_content_sha256,
            }
            expected_evidence_by_id[expected_text_evidence_id] = {
                "id": expected_text_evidence_id,
                "method": (
                    "native_text"
                    if cell.get("source") == "native"
                    else "ocr_text"
                ),
                "dimension": "text",
                "page_index": page_index,
                "bbox": bbox,
                "source_object_ids": [expected_source_id],
                "confidence": 1.0,
                "content_sha256": expected_content_sha256,
            }
            if cell.get("row_span") > 1 or cell.get("col_span") > 1:
                expected_geometry_id = _canonical_table_sha256(
                    ["p04-cell-geometry-evidence-id-v1", identity_tail],
                    8388608,
                    deadline,
                )
                expected_decision_id = _canonical_table_sha256(
                    ["p04-span-decision-id-v1", identity_tail],
                    8388608,
                    deadline,
                )
                if (
                    expected_geometry_id not in cell.get("evidence_ids")
                    or cell.get("span_decision_id") != expected_decision_id
                ):
                    return False
                expected_evidence_by_id[expected_geometry_id] = {
                    "id": expected_geometry_id,
                    "method": "embedded_grid",
                    "dimension": "geometry",
                    "page_index": page_index,
                    "bbox": bbox,
                    "source_object_ids": [expected_source_id],
                    "confidence": 1.0,
                    "content_sha256": expected_content_sha256,
                }
        elif source_type == "table_word_set":
            if (
                cell_source.get("role") != "bottom_row"
                or cell.get("row") != predecessor_rows
                or cell.get("column") != cell_source.get("target_column")
                or cell.get("row_span") != 1
                or cell.get("col_span") != 1
                or cell.get("column_header") is not False
                or cell.get("row_header") is not False
                or cell.get("row_section") is not False
                or cell.get("source") != "native"
                or cell.get("span_decision_id") is not None
            ):
                return False
            words = cell_source.get("words")
            expected_text = " ".join(word.get("text") for word in words)
            expected_bbox = {
                "x": min(word.get("bbox").get("x") for word in words),
                "y": min(word.get("bbox").get("y") for word in words),
                "width": max(
                    word.get("bbox").get("x")
                    + word.get("bbox").get("width")
                    for word in words
                )
                - min(word.get("bbox").get("x") for word in words),
                "height": max(
                    word.get("bbox").get("y")
                    + word.get("bbox").get("height")
                    for word in words
                )
                - min(word.get("bbox").get("y") for word in words),
                "unit": "pt",
            }
            if cell.get("text") != expected_text or bbox != expected_bbox:
                return False
            recovered_bottom_by_column[cell.get("column")] = cell
            if source_sha256 is None:
                return False
            identity_tail = [
                source_sha256,
                page_index,
                table_reference,
                predecessor_rows,
                emitted_columns,
                cell_source.get("id"),
                bbox,
                cell.get("row"),
                cell.get("column"),
            ]
            expected_cell_id = _canonical_table_sha256(
                ["p04-recovered-cell-id-v1", identity_tail],
                8388608,
                deadline,
            )
            expected_text_id = _canonical_table_sha256(
                ["p04-recovered-text-evidence-id-v1", identity_tail],
                8388608,
                deadline,
            )
            expected_geometry_id = _canonical_table_sha256(
                ["p04-recovered-geometry-evidence-id-v1", identity_tail],
                8388608,
                deadline,
            )
            if (
                cell.get("id") != expected_cell_id
                or expected_text_id not in cell.get("evidence_ids")
                or expected_geometry_id not in cell.get("evidence_ids")
            ):
                return False
            expected_evidence_by_id[expected_text_id] = {
                "id": expected_text_id,
                "method": "native_text",
                "dimension": "text",
                "page_index": page_index,
                "bbox": bbox,
                "source_object_ids": [cell_source.get("id")],
                "confidence": 1.0,
                "content_sha256": cell_source.get("content_sha256"),
            }
            expected_evidence_by_id[expected_geometry_id] = {
                "id": expected_geometry_id,
                "method": "recovered_structure",
                "dimension": "geometry",
                "page_index": page_index,
                "bbox": bbox,
                "source_object_ids": [cell_source.get("id")],
                "confidence": 1.0,
                "content_sha256": cell_source.get("content_sha256"),
            }
        else:
            return False

    normalized_cells.sort()
    expected_structure_sha256 = _canonical_table_sha256(
        [
            "p04-structure-source-content-v1",
            table_reference,
            predecessor_rows,
            emitted_columns,
            normalized_cells,
        ],
        8388608,
        deadline,
    )
    if grid_source.get("content_sha256") != expected_structure_sha256:
        return False
    if source_sha256 is None:
        structure_evidence = [
            evidence
            for evidence in evidence_by_id.values()
            if evidence.get("dimension") == "structure"
        ]
        return (
            len(structure_evidence) == 1
            and structure_evidence[0].get("method") == "source_grid"
            and structure_evidence[0].get("source_object_ids")
            == [grid_source.get("id")]
            and structure_evidence[0].get("content_sha256")
            == expected_structure_sha256
        )

    expected_grid_source_id = _canonical_table_sha256(
        [
            "p04-structure-source-id-v1",
            source_sha256,
            page_index,
            "docling",
            table_reference,
            predecessor_rows,
            emitted_columns,
        ],
        8388608,
        deadline,
    )
    expected_grid_source = {
        "id": expected_grid_source_id,
        "engine": "docling",
        "object_type": "table_grid",
        "page_index": page_index,
        "raw_ref": table_reference,
        "content_sha256": expected_structure_sha256,
    }
    expected_source_by_id[expected_grid_source_id] = expected_grid_source
    for source in pdf_sources:
        expected_source_by_id[source.get("id")] = source

    recovery = None
    if pdf_sources:
        header_by_column = {
            column: True for column in recovered_header_columns
        }
        row_pitch = None
        same_line_band = None
        column_starts = None
        if recovered_bottom_by_column:
            previous = base_cells_by_location.get((predecessor_rows - 2, 0))
            last = base_cells_by_location.get((predecessor_rows - 1, 0))
            if (
                type(previous) is not dict
                or type(last) is not dict
                or previous.get("bbox") is None
                or last.get("bbox") is None
                or len(recovered_bottom_by_column) != emitted_columns
            ):
                return False
            row_pitch = float(
                last.get("bbox").get("y") - previous.get("bbox").get("y")
            )
            bottom_words = [
                word
                for source in pdf_sources
                if source.get("role") == "bottom_row"
                for word in source.get("words")
            ]
            same_line_band = {
                "top": min(word.get("bbox").get("y") for word in bottom_words),
                "bottom": max(
                    word.get("bbox").get("y")
                    + word.get("bbox").get("height")
                    for word in bottom_words
                ),
                "tolerance": 1.0,
            }
            column_starts = []
            for column in _bounded_table_iterable(
                range(emitted_columns), 256
            ):
                base_cell = base_cells_by_location.get(
                    (predecessor_rows - 1, column)
                )
                if type(base_cell) is not dict or base_cell.get("bbox") is None:
                    return False
                column_starts.append(float(base_cell.get("bbox").get("x")))
        recovery = {
            "predecessor_rows": predecessor_rows,
            "predecessor_columns": emitted_columns,
            "header_by_column": header_by_column,
            "bottom_by_column": recovered_bottom_by_column,
            "row_pitch": row_pitch,
            "same_line_band": same_line_band,
            "column_starts": column_starts,
        }
        expected_structure_evidence = _table_recovered_structure_evidence(
            recovery,
            pdf_sources,
            expected_grid_source_id,
            source_sha256,
            page_index,
            table_reference,
            table_bbox,
            deadline,
        )
    else:
        expected_structure_id = _canonical_table_sha256(
            [
                "p04-structure-evidence-id-v1",
                source_sha256,
                page_index,
                "docling",
                table_reference,
                emitted_rows,
                emitted_columns,
            ],
            8388608,
            deadline,
        )
        expected_structure_evidence = {
            "id": expected_structure_id,
            "method": "source_grid",
            "dimension": "structure",
            "page_index": page_index,
            "bbox": table_bbox,
            "source_object_ids": [expected_grid_source_id],
            "confidence": 1.0,
            "content_sha256": expected_structure_sha256,
        }
    expected_evidence_by_id[expected_structure_evidence.get("id")] = (
        expected_structure_evidence
    )

    native_header_present = False
    for cell in _bounded_table_iterable(cells, 65536):
        if not (cell.get("column_header") or cell.get("row_header")):
            continue
        if cell.get("row") == 0 and cell.get("column") in recovered_header_columns:
            header_source = pdf_by_locator.get(
                ("header", 0, cell.get("column"))
            )
            body_source = pdf_by_locator.get(
                ("body_control", 1, cell.get("column"))
            )
            body_cell = base_cells_by_location.get((1, cell.get("column")))
            if (
                type(header_source) is not dict
                or type(body_source) is not dict
                or type(body_cell) is not dict
                or " ".join(
                    word.get("text") for word in header_source.get("words")
                ) != cell.get("text")
                or " ".join(
                    word.get("text") for word in body_source.get("words")
                ) != body_cell.get("text")
            ):
                return False
            expected_header = _table_recovered_header_evidence(
                cell.get("column"),
                cell.get("bbox"),
                pdf_by_locator,
                expected_grid_source_id,
                source_sha256,
                page_index,
                table_reference,
                predecessor_rows,
                emitted_columns,
                deadline,
            )
            if expected_header.get("id") not in cell.get("evidence_ids"):
                return False
            expected_evidence_by_id[expected_header.get("id")] = expected_header
        else:
            native_header_present = True
    if native_header_present:
        expected_header_id = _canonical_table_sha256(
            [
                "p04-header-evidence-id-v1",
                source_sha256,
                page_index,
                "docling",
                table_reference,
                emitted_rows,
                emitted_columns,
            ],
            8388608,
            deadline,
        )
        expected_header = {
            "id": expected_header_id,
            "method": "model_structure",
            "dimension": "header",
            "page_index": page_index,
            "bbox": table_bbox,
            "source_object_ids": [expected_grid_source_id],
            "confidence": 1.0,
            "content_sha256": expected_structure_sha256,
        }
        expected_evidence_by_id[expected_header_id] = expected_header

    return (
        source_by_id == expected_source_by_id
        and evidence_by_id == expected_evidence_by_id
    )


def _table_slot_topology_is_valid(cells, slots, sidecar, source_sha256, deadline):
    _check_table_deadline(deadline)
    grid = sidecar.get("grid")
    row_count = grid.get("row_count")
    column_count = grid.get("column_count")
    if len(slots) != row_count * column_count:
        return False
    observed_cell_ids = []
    expected_owners = {}
    previous_position = [-1, -1]
    for cell in _bounded_table_iterable(cells, 65536):
        _check_table_deadline(deadline)
        position = [cell.get("row"), cell.get("column")]
        if position <= previous_position:
            return False
        previous_position = position
        cell_id = cell.get("id")
        observed_cell_ids.append(cell_id)
        for row_offset in _bounded_table_iterable(
            range(cell.get("row_span")), 4096
        ):
            _check_table_deadline(deadline)
            for column_offset in _bounded_table_iterable(
                range(cell.get("col_span")), 256
            ):
                _check_table_deadline(deadline)
                row = cell.get("row") + row_offset
                column = cell.get("column") + column_offset
                key = f"{row}:{column}"
                if key in expected_owners:
                    return False
                expected_owners[key] = [
                    cell_id,
                    row_offset == 0 and column_offset == 0,
                    cell.get("text") == "",
                ]
    if observed_cell_ids != grid.get("cell_ids"):
        return False
    cursor = 0
    for row in _bounded_table_iterable(range(row_count), 4096):
        _check_table_deadline(deadline)
        for column in _bounded_table_iterable(range(column_count), 256):
            _check_table_deadline(deadline)
            slot = slots[cursor]
            cursor += 1
            owner = expected_owners.get(f"{row}:{column}")
            if owner is None or not _table_exact_keys(
                slot, _TABLE_SLOT_KEYS, deadline
            ):
                return False
            expected_kind = (
                "explicit_blank"
                if owner[1] and owner[2]
                else "anchor"
                if owner[1]
                else "covered"
            )
            if (
                slot.get("row") != row
                or slot.get("column") != column
                or slot.get("kind") != expected_kind
                or slot.get("cell_id") != (owner[0] if owner[1] else None)
                or slot.get("covered_by_cell_id")
                != (None if owner[1] else owner[0])
                or not _is_table_sha256(slot.get("id"), deadline)
            ):
                return False
            if source_sha256 is not None:
                expected_slot_id = _canonical_table_sha256(
                    [
                        "p04-slot-id-v1",
                        source_sha256,
                        sidecar.get("page_index"),
                        sidecar.get("table_id"),
                        sidecar.get("candidate_id"),
                        row,
                        column,
                    ],
                    8388608,
                    deadline,
                )
                if slot.get("id") != expected_slot_id:
                    return False
    return len(expected_owners) == row_count * column_count


def _valid_table_evidence_graph_is_closed(
    table,
    cells,
    decisions,
    source_by_id,
    evidence_by_id,
    deadline,
):
    _check_table_deadline(deadline)
    expected_evidence_ids = {}
    expected_source_ids = {}
    for cell in _bounded_table_iterable(cells, 65536):
        _check_table_deadline(deadline)
        for source_id in _bounded_table_iterable(
            cell.get("source_object_ids"), 64
        ):
            expected_source_ids[source_id] = True
        for evidence_id in _bounded_table_iterable(
            cell.get("evidence_ids"), 64
        ):
            expected_evidence_ids[evidence_id] = True
    for decision in _bounded_table_iterable(decisions, 65536):
        _check_table_deadline(deadline)
        for evidence_id in _bounded_table_iterable(
            decision.get("evidence_ids"), 64
        ):
            expected_evidence_ids[evidence_id] = True
    table_bbox = _docling_table_bbox(table, deadline)
    geometry_evidence_ids = []
    structure_evidence_ids = []
    for evidence_id, evidence_record in _bounded_table_iterable(
        tuple(evidence_by_id.items()), 65536
    ):
        _check_table_deadline(deadline)
        linked_source_ids = evidence_record.get("source_object_ids")
        if type(linked_source_ids) is not list or not linked_source_ids:
            continue
        linked_sources = [source_by_id.get(value) for value in linked_source_ids]
        if any(type(source) is not dict for source in linked_sources):
            continue
        linked_types = [source.get("object_type") for source in linked_sources]
        if linked_types == ["table_geometry"]:
            linked_source = linked_sources[0]
            if (
                evidence_record.get("method") != "embedded_grid"
                or evidence_record.get("dimension") != "geometry"
                or evidence_record.get("bbox") != table_bbox
                or evidence_record.get("content_sha256")
                != linked_source.get("content_sha256")
            ):
                return False
            geometry_evidence_ids.append(evidence_id)
        elif evidence_record.get("dimension") == "structure" and (
            linked_types.count("table_grid") == 1
        ):
            grid_source = linked_sources[linked_types.index("table_grid")]
            if (
                evidence_record.get("bbox") != table_bbox
                or evidence_record.get("method") == "source_grid"
                and (
                    len(linked_sources) != 1
                    or evidence_record.get("content_sha256")
                    != grid_source.get("content_sha256")
                )
                or evidence_record.get("method") == "recovered_structure"
                and (
                    len(linked_sources) < 2
                    or linked_types.count("table_word_set")
                    != len(linked_sources) - 1
                )
                or evidence_record.get("method")
                not in ("source_grid", "recovered_structure")
            ):
                return False
            structure_evidence_ids.append(evidence_id)
    if len(geometry_evidence_ids) != 1 or len(structure_evidence_ids) != 1:
        return False
    expected_evidence_ids[geometry_evidence_ids[0]] = True
    expected_evidence_ids[structure_evidence_ids[0]] = True
    if set(evidence_by_id) != set(expected_evidence_ids):
        return False
    for evidence_id in _bounded_table_iterable(
        tuple(expected_evidence_ids), 65536
    ):
        _check_table_deadline(deadline)
        evidence_record = evidence_by_id.get(evidence_id)
        for source_id in _bounded_table_iterable(
            evidence_record.get("source_object_ids"), 64
        ):
            expected_source_ids[source_id] = True
    return set(source_by_id) == set(expected_source_ids)


def _diagnostic_table_evidence_graph_is_closed(
    table,
    sidecar,
    source_by_id,
    evidence_by_id,
    source_sha256,
    deadline,
):
    """Require every non-authoritative diagnostic node to be necessary."""

    _check_table_deadline(deadline)
    if any(
        source.get("engine") != "docling"
        for source in _bounded_table_iterable(
            list(source_by_id.values()), 65536
        )
    ):
        return False
    table_geometry_sources = [
        source
        for source in source_by_id.values()
        if source.get("object_type") == "table_geometry"
    ]
    grid_sources = [
        source
        for source in source_by_id.values()
        if source.get("object_type") == "table_grid"
    ]
    cell_sources = [
        source
        for source in source_by_id.values()
        if source.get("object_type") == "table_cell"
    ]
    if (
        len(table_geometry_sources) != 1
        or len(grid_sources) != 1
        or len(source_by_id) != 2 + len(cell_sources)
    ):
        return False
    table_geometry_source = table_geometry_sources[0]
    grid_source = grid_sources[0]
    table_bbox = _docling_table_bbox(table, deadline)
    page_index = sidecar.get("page_index")
    table_reference = table_geometry_source.get("raw_ref")
    if grid_source.get("raw_ref") != table_reference:
        return False
    evidence_by_source = {source_id: [] for source_id in source_by_id}
    for evidence in _bounded_table_iterable(
        list(evidence_by_id.values()), 65536
    ):
        linked = evidence.get("source_object_ids")
        if type(linked) is not list or len(linked) != 1:
            return False
        source_id = linked[0]
        linked_source = source_by_id.get(source_id)
        if type(linked_source) is not dict:
            return False
        if evidence.get("content_sha256") != linked_source.get(
            "content_sha256"
        ):
            return False
        evidence_by_source[source_id].append(evidence)
    for source_id, source in _bounded_table_iterable(
        tuple(source_by_id.items()), 65536
    ):
        linked_evidence = evidence_by_source.get(source_id)
        object_type = source.get("object_type")
        if object_type == "table_geometry":
            if len(linked_evidence) != 1:
                return False
            evidence = linked_evidence[0]
            if (
                evidence.get("method") != "embedded_grid"
                or evidence.get("dimension") != "geometry"
                or evidence.get("bbox") != table_bbox
            ):
                return False
        elif object_type == "table_grid":
            structure = [
                evidence
                for evidence in linked_evidence
                if evidence.get("dimension") == "structure"
            ]
            headers = [
                evidence
                for evidence in linked_evidence
                if evidence.get("dimension") == "header"
            ]
            if (
                len(structure) != 1
                or len(headers) > 1
                or len(linked_evidence) != len(structure) + len(headers)
                or structure[0].get("method") != "source_grid"
                or structure[0].get("bbox") != table_bbox
                or headers
                and (
                    headers[0].get("method") != "model_structure"
                    or headers[0].get("bbox") != table_bbox
                )
            ):
                return False
        elif object_type == "table_cell":
            text_evidence = [
                evidence
                for evidence in linked_evidence
                if evidence.get("dimension") == "text"
            ]
            geometry_evidence = [
                evidence
                for evidence in linked_evidence
                if evidence.get("dimension") == "geometry"
            ]
            if (
                len(text_evidence) != 1
                or len(geometry_evidence) > 1
                or len(linked_evidence)
                != len(text_evidence) + len(geometry_evidence)
                or text_evidence[0].get("method")
                != (
                    "native_text"
                    if table.get("source") == "native"
                    else "ocr_text"
                )
                or geometry_evidence
                and geometry_evidence[0].get("method") != "embedded_grid"
                or geometry_evidence
                and geometry_evidence[0].get("bbox")
                != text_evidence[0].get("bbox")
            ):
                return False
        else:
            return False
    if source_sha256 is not None:
        grid = sidecar.get("grid")
        expected_geometry_id = _canonical_table_sha256(
            [
                "p04-geometry-evidence-id-v1",
                source_sha256,
                page_index,
                "docling",
                table_reference,
                table_bbox,
            ],
            8388608,
            deadline,
        )
        expected_structure_id = _canonical_table_sha256(
            [
                "p04-structure-evidence-id-v1",
                source_sha256,
                page_index,
                "docling",
                table_reference,
                grid.get("row_count"),
                grid.get("column_count"),
            ],
            8388608,
            deadline,
        )
        if (
            evidence_by_source[table_geometry_source.get("id")][0].get("id")
            != expected_geometry_id
            or not any(
                evidence.get("id") == expected_structure_id
                for evidence in evidence_by_source[grid_source.get("id")]
            )
        ):
            return False
    return set(evidence_by_id) == {
        evidence.get("id")
        for evidence_list in evidence_by_source.values()
        for evidence in evidence_list
    }


def _table_story_metadata_is_well_formed(sidecar, deadline):
    _check_table_deadline(deadline)
    reconciliation = sidecar.get("reconciliation")
    gate = sidecar.get("gate")
    continuation = sidecar.get("continuation")
    expected_scope = ["P04-US01"]
    if reconciliation is not None:
        expected_scope.append("P04-US02")
    if gate is not None:
        if reconciliation is None:
            return False
        expected_scope.append("P04-US04")
    if continuation is not None:
        if gate is None:
            return False
        expected_scope.append("P04-US03")
    if sidecar.get("scope") != expected_scope:
        return False
    if reconciliation is not None:
        if not _table_exact_keys(
            reconciliation, _TABLE_RECONCILIATION_KEYS, deadline
        ):
            return False
        candidate_ids = reconciliation.get("candidate_ids")
        scores = reconciliation.get("scores")
        selected_candidate_id = reconciliation.get("selected_candidate_id")
        outcome = reconciliation.get("outcome")
        absolute_threshold = reconciliation.get("absolute_threshold")
        selection_margin = reconciliation.get("selection_margin")
        evidence_ids = reconciliation.get("evidence_ids")
        concern_codes = reconciliation.get("concern_codes")
        if (
            type(candidate_ids) is not list
            or not candidate_ids
            or len(candidate_ids) > 128
            or candidate_ids != sorted(set(candidate_ids))
            or any(not _is_table_sha256(value, deadline) for value in candidate_ids)
            or type(scores) is not list
            or len(scores) != len(candidate_ids)
            or outcome not in (
                "singleton", "selected", "duplicate_collapsed",
                "unresolved", "malformed_fallback",
            )
            or outcome == "unresolved" and selected_candidate_id is not None
            or outcome != "unresolved"
            and selected_candidate_id not in candidate_ids
            or type(absolute_threshold) not in (int, float)
            or type(absolute_threshold) is bool
            or not isfinite(absolute_threshold)
            or not 0 <= absolute_threshold <= 1
            or type(selection_margin) not in (int, float)
            or type(selection_margin) is bool
            or not isfinite(selection_margin)
            or not 0 <= selection_margin <= 1
            or type(evidence_ids) is not list
            or len(evidence_ids) > 64
            or evidence_ids != sorted(set(evidence_ids))
            or any(not _is_table_sha256(value, deadline) for value in evidence_ids)
            or type(concern_codes) is not list
            or len(concern_codes) > 64
            or concern_codes != sorted(set(concern_codes))
            or any(value not in _TABLE_CONCERN_CODES for value in concern_codes)
        ):
            return False
        expected_cluster_id = _canonical_table_sha256(
            ["p04-us02-cluster-v1", candidate_ids],
            8388608,
            deadline,
        )
        if reconciliation.get("cluster_id") != expected_cluster_id:
            return False
        observed_score_ids = []
        for score in _bounded_table_iterable(scores, 128):
            _check_table_deadline(deadline)
            if not _table_exact_keys(
                score, _TABLE_RECONCILIATION_SCORE_KEYS, deadline
            ):
                return False
            candidate_id = score.get("candidate_id")
            observed_score_ids.append(candidate_id)
            if (
                candidate_id not in candidate_ids
                or score.get("engine") not in (
                    "docling", "pdfplumber", "unknown"
                )
                or not _table_bbox_is_valid(score.get("bbox"), deadline)
                or type(score.get("row_count")) is not int
                or not 0 <= score.get("row_count") <= 4096
                or type(score.get("column_count")) is not int
                or not 0 <= score.get("column_count") <= 256
                or not _is_table_sha256(score.get("content_sha256"), deadline)
                or type(score.get("candidate")) is not dict
                or any(
                    type(key) is not str or key.startswith("_p04_")
                    for key in score.get("candidate")
                )
            ):
                return False
            for name in (
                "total", "geometry", "grid", "cell_coverage",
                "text_coverage", "spans", "provenance",
            ):
                value = score.get(name)
                if (
                    type(value) not in (int, float)
                    or type(value) is bool
                    or not isfinite(value)
                    or not 0 <= value <= 1
                ):
                    return False
        if observed_score_ids != candidate_ids:
            return False
    if gate is not None:
        if not _table_exact_keys(gate, _TABLE_GATE_KEYS, deadline):
            return False
        owner_ids = gate.get("owner_item_ids")
        feature_scores = gate.get("feature_scores")
        evidence_ids = gate.get("evidence_ids")
        concern_codes = gate.get("concern_codes")
        outcome = gate.get("outcome")
        if (
            gate.get("candidate_id") != sidecar.get("candidate_id")
            or outcome not in (
                "canonical_table", "form", "key_value", "chart", "visual",
                "unresolved", "structural_failure",
            )
            or type(owner_ids) is not list
            or len(owner_ids) > 64
            or owner_ids != sorted(set(owner_ids))
            or any(
                type(value) is not str
                or not value
                or len(value.encode("utf-8")) > 256
                for value in owner_ids
            )
            or outcome == "canonical_table" and owner_ids
            or type(feature_scores) is not dict
            or tuple(sorted(feature_scores))
            != tuple(sorted(_TABLE_GATE_FEATURE_KEYS))
            or any(
                type(value) not in (int, float)
                or type(value) is bool
                or not isfinite(value)
                or not 0 <= value <= 1
                for value in feature_scores.values()
            )
            or type(evidence_ids) is not list
            or len(evidence_ids) > 64
            or evidence_ids != sorted(set(evidence_ids))
            or any(not _is_table_sha256(value, deadline) for value in evidence_ids)
            or type(concern_codes) is not list
            or len(concern_codes) > 64
            or concern_codes != sorted(set(concern_codes))
            or any(value not in _TABLE_CONCERN_CODES for value in concern_codes)
        ):
            return False
        expected_gate_id = _canonical_table_sha256(
            [
                "p04-us04-gate-v1",
                gate.get("candidate_id"),
                outcome,
                owner_ids,
                feature_scores,
                evidence_ids,
                concern_codes,
            ],
            8388608,
            deadline,
        )
        if gate.get("decision_id") != expected_gate_id:
            return False
    if continuation is not None:
        if not _table_exact_keys(
            continuation, _TABLE_CONTINUATION_KEYS, deadline
        ):
            return False
        outcome = continuation.get("outcome")
        source_table_ids = continuation.get("source_table_ids")
        continued_from = continuation.get("continued_from")
        page_indexes = continuation.get("page_indexes")
        signal_ids = continuation.get("signal_ids")
        repeated_header_ids = continuation.get("repeated_header_cell_ids")
        evidence_ids = continuation.get("evidence_ids")
        concern_codes = continuation.get("concern_codes")
        if (
            sidecar.get("status") != "valid"
            or type(gate) is not dict
            or gate.get("outcome") != "canonical_table"
            or outcome not in (
                "page_local", "merged", "unresolved", "ineligible"
            )
            or type(source_table_ids) is not list
            or not source_table_ids
            or len(source_table_ids) > 32
            or source_table_ids != sorted(set(source_table_ids))
            or any(
                not _is_table_sha256(value, deadline)
                for value in source_table_ids
            )
            or sidecar.get("table_id") not in source_table_ids
            or continued_from is not None
            and continued_from not in source_table_ids
            or type(page_indexes) is not list
            or not page_indexes
            or len(page_indexes) > 32
            or page_indexes != sorted(set(page_indexes))
            or sidecar.get("page_index") not in page_indexes
            or any(
                type(page) is not int or page < 1 or page > 1_000_000
                for page in page_indexes
            )
            or any(
                second != first + 1
                for first, second in zip(page_indexes, page_indexes[1:])
            )
        ):
            return False
        for values in (
            signal_ids,
            repeated_header_ids,
            evidence_ids,
        ):
            if (
                type(values) is not list
                or len(values) > 64
                or values != sorted(set(values))
                or any(not _is_table_sha256(value, deadline) for value in values)
            ):
                return False
        if (
            type(concern_codes) is not list
            or len(concern_codes) > 64
            or concern_codes != sorted(set(concern_codes))
            or any(value not in _TABLE_CONCERN_CODES for value in concern_codes)
            or outcome in ("page_local", "merged")
            and (
                len(source_table_ids) < 2
                or len(page_indexes) < 2
                or len(signal_ids) < 2
                or concern_codes
            )
            or outcome == "merged" and continued_from is None
            or outcome == "unresolved"
            and "table_continuation_ambiguous" not in concern_codes
            or outcome == "ineligible"
            and "table_continuation_incompatible" not in concern_codes
            and "table_resource_limit_exceeded" not in concern_codes
        ):
            return False
        expected_merge_id = _table_continuation_merge_id(
            source_table_ids,
            page_indexes,
            deadline,
        )
        if continuation.get("merge_id") != expected_merge_id:
            return False
    return True


def _table_overlay_is_well_formed(
    table,
    sidecar,
    deadline,
    source_sha256=None,
    *,
    diagnostic_custody_item=None,
):
    _check_table_deadline(deadline)
    if source_sha256 is not None:
        try:
            _assert_source_sha256(source_sha256, deadline)
        except (TypeError, ValueError, TimeoutError):
            return False
    if not _table_exact_keys(sidecar, _TABLE_SIDECAR_KEYS, deadline):
        return False
    status = sidecar.get("status")
    if (
        sidecar.get("policy_id") != "p04-table-evidence-v1"
        or sidecar.get("version") != "1.1"
        or status not in ("valid", "unresolved", "structural_failure")
        or not _is_table_sha256(sidecar.get("table_id"), deadline)
        or not _is_table_sha256(sidecar.get("candidate_id"), deadline)
        or type(sidecar.get("page_index")) is not int
        or sidecar.get("page_index") < 1
        or sidecar.get("page_index") > 1000000
        or not _table_story_metadata_is_well_formed(sidecar, deadline)
    ):
        return False
    concerns = sidecar.get("concerns")
    if type(concerns) is not list or len(concerns) > 64:
        return False
    previous_concern = ""
    concerns_valid = True
    for concern in _bounded_table_iterable(concerns, 64):
        _check_table_deadline(deadline)
        if (
            type(concern) is not str
            or concern not in _TABLE_CONCERN_CODES
            or concern <= previous_concern
        ):
            concerns_valid = False
        previous_concern = concern if type(concern) is str else previous_concern
    if not concerns_valid:
        return False
    grid = sidecar.get("grid")
    if not _table_exact_keys(
        grid, ("row_count", "column_count", "cell_ids"), deadline
    ):
        return False
    row_count = grid.get("row_count")
    column_count = grid.get("column_count")
    cell_ids = grid.get("cell_ids")
    if (
        type(row_count) is not int
        or row_count < 1
        or row_count > 4096
        or type(column_count) is not int
        or column_count < 1
        or column_count > 256
        or row_count > 65536 // column_count
        or type(cell_ids) is not list
        or len(cell_ids) > 65536
    ):
        return False
    cells = table.get("cells")
    source_objects = sidecar.get("source_objects")
    evidence = sidecar.get("evidence")
    decisions = sidecar.get("span_decisions")
    slots = sidecar.get("slots")
    if (
        type(cells) is not list
        or len(cells) > 65536
        or type(source_objects) is not list
        or not source_objects
        or len(source_objects) > 65536
        or type(evidence) is not list
        or not evidence
        or len(evidence) > 65536
        or type(decisions) is not list
        or len(decisions) > 65536
        or type(slots) is not list
        or len(slots) > 65536
    ):
        return False
    source_ids = []
    source_valid = True
    for source_object in _bounded_table_iterable(source_objects, 65536):
        _check_table_deadline(deadline)
        is_docling_source = _table_exact_keys(
            source_object, _TABLE_SOURCE_KEYS, deadline
        )
        is_pdf_source = _table_exact_keys(
            source_object, _TABLE_PDFPLUMBER_SOURCE_KEYS, deadline
        )
        if not is_docling_source and not is_pdf_source:
            source_valid = False
            source_ids.append("")
            continue
        source_id = source_object.get("id")
        raw_ref = source_object.get("raw_ref")
        if (
            not _is_table_sha256(source_id, deadline)
            or source_object.get("page_index") != sidecar.get("page_index")
            or not _is_table_sha256(
                source_object.get("content_sha256"), deadline
            )
        ):
            source_valid = False
        if is_docling_source and (
            source_object.get("engine") != "docling"
            or source_object.get("object_type") not in (
                "table_cell", "table_geometry", "table_grid"
            )
            or not _table_reference_is_safe(raw_ref, deadline)
        ):
            source_valid = False
        if is_pdf_source and (
            source_object.get("engine") != "pdfplumber"
            or source_object.get("object_type") != "table_word_set"
            or raw_ref is not None
        ):
            source_valid = False
        source_ids.append(source_id)
    source_id_set = set(source_ids)
    if source_ids != sorted(source_ids) or len(source_ids) != len(source_id_set):
        source_valid = False
    if not source_valid:
        return False
    if not _table_source_bound_identity_is_valid(
        table, sidecar, source_objects, source_sha256, deadline
    ):
        return False
    evidence_ids = []
    evidence_valid = True
    for evidence_record in _bounded_table_iterable(evidence, 65536):
        _check_table_deadline(deadline)
        if not _table_exact_keys(
            evidence_record, _TABLE_EVIDENCE_KEYS, deadline
        ):
            evidence_valid = False
            evidence_ids.append("")
            continue
        evidence_id = evidence_record.get("id")
        confidence = evidence_record.get("confidence")
        if (
            not _is_table_sha256(evidence_id, deadline)
            or evidence_record.get("method") not in (
                "native_text", "ocr_text", "vector_rule", "source_grid",
                "embedded_grid", "model_structure", "recovered_structure",
                "derived_comparison",
            )
            or evidence_record.get("dimension") not in (
                "text", "geometry", "structure", "header", "ownership",
                "continuation",
            )
            or evidence_record.get("page_index") != sidecar.get("page_index")
            or not _table_bbox_is_valid(evidence_record.get("bbox"), deadline)
            or not _ordered_table_hashes_are_valid(
                evidence_record.get("source_object_ids"),
                source_id_set,
                deadline,
            )
            or not evidence_record.get("source_object_ids")
            or type(confidence) not in (int, float)
            or type(confidence) is bool
            or not isfinite(confidence)
            or confidence < 0
            or confidence > 1
            or not _is_table_sha256(
                evidence_record.get("content_sha256"), deadline
            )
        ):
            evidence_valid = False
        evidence_ids.append(evidence_id)
    evidence_id_set = set(evidence_ids)
    if (
        evidence_ids != sorted(evidence_ids)
        or len(evidence_ids) != len(evidence_id_set)
    ):
        evidence_valid = False
    if not evidence_valid:
        return False
    source_by_id = {}
    for source_object in _bounded_table_iterable(source_objects, 65536):
        _check_table_deadline(deadline)
        source_by_id[source_object.get("id")] = source_object
    evidence_by_id = {}
    for evidence_record in _bounded_table_iterable(evidence, 65536):
        _check_table_deadline(deadline)
        evidence_by_id[evidence_record.get("id")] = evidence_record
    reconciliation = sidecar.get("reconciliation")
    has_candidate_grid = status == "valid" or (
        status == "unresolved"
        and type(reconciliation) is dict
        and reconciliation.get("outcome") == "unresolved"
        and bool(cell_ids)
    )
    if not has_candidate_grid:
        if cell_ids or slots or decisions or not concerns:
            return False
        if not _diagnostic_table_evidence_graph_is_closed(
            table,
            sidecar,
            source_by_id,
            evidence_by_id,
            source_sha256,
            deadline,
        ):
            return False
        custody = sidecar.get("representation_custody")
        if not _table_exact_keys(custody, _TABLE_CUSTODY_KEYS, deadline):
            return False
        custody_item = (
            diagnostic_custody_item
            if type(diagnostic_custody_item) is dict
            else table
        )
        predecessor_row_count = custody_item.get("row_count")
        predecessor_column_count = custody_item.get("column_count")
        if (
            type(predecessor_row_count) is not int
            or predecessor_row_count < 1
            or type(predecessor_column_count) is not int
            or predecessor_column_count < 1
        ):
            return False
        expected_custody = _table_representation_custody(
            custody_item,
            predecessor_row_count,
            predecessor_column_count,
            deadline,
            item_is_plain=diagnostic_custody_item is not None,
        )
        if custody != expected_custody:
            return False
        _assert_canonical_table_json(sidecar, 8388608, deadline)
        return True
    cells_valid = True
    table_bbox = _docling_table_bbox(table, deadline)
    if table_bbox is None:
        return False
    observed_cell_ids = []
    for cell in _bounded_table_iterable(cells, 65536):
        _check_table_deadline(deadline)
        if not _table_exact_keys(cell, _TABLE_CELL_KEYS, deadline):
            cells_valid = False
            observed_cell_ids.append("")
            continue
        cell_id = cell.get("id")
        row = cell.get("row")
        column = cell.get("column")
        row_span = cell.get("row_span")
        col_span = cell.get("col_span")
        text = cell.get("text")
        confidence_dimensions = cell.get("confidence_dimensions")
        confidence_valid = True
        if type(confidence_dimensions) is dict:
            for confidence_value in _bounded_table_iterable(
                tuple(confidence_dimensions.values()), 4
            ):
                _check_table_deadline(deadline)
                if confidence_value is not None and (
                    type(confidence_value) not in (int, float)
                    or type(confidence_value) is bool
                    or not isfinite(confidence_value)
                    or confidence_value < 0
                    or confidence_value > 1
                ):
                    confidence_valid = False
        else:
            confidence_valid = False
        if (
            not _is_table_sha256(cell_id, deadline)
            or type(row) is not int
            or row < 0
            or row >= row_count
            or type(column) is not int
            or column < 0
            or column >= column_count
            or type(row_span) is not int
            or row_span < 1
            or row_span > row_count - row
            or type(col_span) is not int
            or col_span < 1
            or col_span > column_count - column
            or type(text) is not str
            or len(text.encode("utf-8")) > 16384
            or _table_text_has_unsafe_control(text, deadline)
            or type(cell.get("column_header")) is not bool
            or type(cell.get("row_header")) is not bool
            or type(cell.get("row_section")) is not bool
            or not _table_bbox_is_valid(cell.get("bbox"), deadline)
            or cell.get("bbox") is not None
            and not _table_content_bbox_within_region(
                cell.get("bbox"),
                table_bbox,
                deadline,
            )
            or cell.get("source") not in ("native", "ocr")
            or cell.get("page_index") != sidecar.get("page_index")
            or not _ordered_table_hashes_are_valid(
                cell.get("evidence_ids"), evidence_id_set, deadline
            )
            or not _ordered_table_hashes_are_valid(
                cell.get("source_object_ids"), source_id_set, deadline
            )
            or not _table_exact_keys(
                confidence_dimensions,
                ("text", "geometry", "structure", "header"),
                deadline,
            )
            or not confidence_valid
            or not _table_cell_evidence_is_valid(
                cell, source_by_id, evidence_by_id, concerns, deadline
            )
        ):
            cells_valid = False
        observed_cell_ids.append(cell_id)
    if len(observed_cell_ids) != len(set(observed_cell_ids)):
        cells_valid = False
    if has_candidate_grid and observed_cell_ids != cell_ids:
        cells_valid = False
    if not cells_valid:
        return False
    if not _table_valid_cells_are_source_bound(
        table,
        sidecar,
        cells,
        source_by_id,
        evidence_by_id,
        source_sha256,
        deadline,
    ):
        return False
    if not _table_slot_topology_is_valid(
        cells, slots, sidecar, source_sha256, deadline
    ):
        return False
    decision_valid = True
    decision_ids = []
    decisions_by_cell = {}
    cells_by_id = {}
    for cell in _bounded_table_iterable(cells, 65536):
        _check_table_deadline(deadline)
        cells_by_id[cell.get("id")] = cell
    for decision in _bounded_table_iterable(decisions, 65536):
        _check_table_deadline(deadline)
        if not _table_exact_keys(decision, _TABLE_SPAN_KEYS, deadline):
            decision_valid = False
            decision_ids.append("")
            continue
        decision_id = decision.get("id")
        decision_cell = cells_by_id.get(decision.get("cell_id"))
        claimed_row_span = decision.get("claimed_row_span")
        claimed_col_span = decision.get("claimed_col_span")
        emitted_row_span = decision.get("emitted_row_span")
        emitted_col_span = decision.get("emitted_col_span")
        concern_codes = decision.get("concern_codes")
        decision_evidence_ids = decision.get("evidence_ids")
        decision_dimensions = []
        if type(decision_evidence_ids) is list:
            for evidence_id in _bounded_table_iterable(
                decision_evidence_ids, 64
            ):
                _check_table_deadline(deadline)
                evidence_record = evidence_by_id.get(evidence_id)
                decision_dimensions.append(
                    evidence_record.get("dimension")
                    if type(evidence_record) is dict
                    else None
                )
        if (
            not _is_table_sha256(decision_id, deadline)
            or type(decision_cell) is not dict
            or decision.get("cell_id") in decisions_by_cell
            or type(claimed_row_span) is not int
            or claimed_row_span < 1
            or claimed_row_span > row_count - decision_cell.get("row")
            or type(claimed_col_span) is not int
            or claimed_col_span < 1
            or claimed_col_span > column_count - decision_cell.get("column")
            or (claimed_row_span == 1 and claimed_col_span == 1)
            or type(emitted_row_span) is not int
            or type(emitted_col_span) is not int
            or emitted_row_span != claimed_row_span
            or emitted_col_span != claimed_col_span
            or decision_cell.get("row_span") != emitted_row_span
            or decision_cell.get("col_span") != emitted_col_span
            or decision_cell.get("span_decision_id") != decision_id
            or decision.get("outcome") != "supported"
            or not _ordered_table_hashes_are_valid(
                decision_evidence_ids, evidence_id_set, deadline
            )
            or len(decision_evidence_ids) != 2
            or sorted(decision_dimensions) != ["geometry", "structure"]
            or type(concern_codes) is not list
            or concern_codes
        ):
            decision_valid = False
        if type(decision_cell) is dict:
            decisions_by_cell[decision.get("cell_id")] = decision
        decision_ids.append(decision_id)
    if len(decision_ids) != len(set(decision_ids)):
        decision_valid = False
    if not decision_valid:
        return False
    for cell in _bounded_table_iterable(cells, 65536):
        _check_table_deadline(deadline)
        has_span = cell.get("row_span") > 1 or cell.get("col_span") > 1
        if (
            has_span
            and cell.get("id") not in decisions_by_cell
            or not has_span
            and cell.get("span_decision_id") is not None
        ):
            return False
    if not _valid_table_evidence_graph_is_closed(
        table,
        cells,
        decisions,
        source_by_id,
        evidence_by_id,
        deadline,
    ):
        return False
    if not _table_projection_matches_grid(
        table, slots, cells, row_count, column_count, deadline
    ):
        return False
    custody = sidecar.get("representation_custody")
    if not _table_exact_keys(custody, _TABLE_CUSTODY_KEYS, deadline):
        return False
    expected_custody = _table_representation_custody(
        table, row_count, column_count, deadline
    )
    if custody != expected_custody:
        return False
    _assert_canonical_table_json(sidecar, 8388608, deadline)
    return True


def _replay_table_overlay(table, table_evidence, deadline, source_sha256=None, retain_snapshot=True):
    _check_table_deadline(deadline)
    snapshot = _table_predecessor_snapshot(table, deadline)
    if snapshot is None or type(table_evidence) is not dict:
        _reject_table_overlay(table, deadline)
        return None
    try:
        snapshot = _table_snapshot_with_current_unrelated_fields(
            table, snapshot, deadline
        )
        well_formed = _table_overlay_is_well_formed(
            table,
            table_evidence,
            deadline,
            source_sha256,
            diagnostic_custody_item=snapshot,
        )
        if well_formed and table_evidence.get("status") != "valid":
            well_formed = _table_authoritative_projection_matches(
                table, snapshot, deadline
            )
    except TimeoutError:
        _reject_table_overlay(table, perf_counter() + 0.500)
        raise
    except (MemoryError, RecursionError, TypeError, ValueError):
        well_formed = False
    if not well_formed:
        _reject_table_overlay(table, perf_counter() + 0.500)
        return None
    table["table_evidence"] = table_evidence
    if retain_snapshot:
        table[_TABLE_PREDECESSOR_SNAPSHOT_KEY] = snapshot
    else:
        table.pop(_TABLE_PREDECESSOR_SNAPSHOT_KEY, None)
    return None


def replay_table_semantics(table, table_evidence, *, source_sha256=None, table_span_fidelity_deadline=None, table_span_fidelity_document_deadline=None):
    deadline = _resolve_table_page_deadline(
        table_span_fidelity_deadline,
        table_span_fidelity_document_deadline,
    )
    try:
        _assert_plain_table_value(table, deadline)
        table_evidence = _validate_plain_table_value(
            table_evidence, deadline
        )
        if source_sha256 is not None:
            source_sha256 = _assert_source_sha256(
                source_sha256, deadline
            )
        _replay_table_overlay(
            table, table_evidence, deadline, source_sha256, True
        )
        public_table = _table_without_snapshot(table, deadline)
        _assert_canonical_table_json(public_table, 8388608, deadline)
        validated_table_output = _assert_plain_table_value(table, deadline)
    except _TablePredecessorIntegrityError:
        raise
    except (MemoryError, RecursionError, TypeError, ValueError, TimeoutError):
        _reject_table_overlay(table, perf_counter() + 0.500)
    return table


def validate_table_semantics(table, source_sha256):
    deadline = _resolve_table_page_deadline(None)
    try:
        table = _validate_plain_table_value(table, deadline)
        source_sha256 = _assert_source_sha256(source_sha256, deadline)
        table_evidence = table.get("table_evidence")
        if type(table_evidence) is not dict:
            return False
        table.pop(_TABLE_PREDECESSOR_SNAPSHOT_KEY, None)
        return _table_overlay_is_well_formed(
            table, table_evidence, deadline, source_sha256
        )
    except (TypeError, ValueError, TimeoutError):
        return False


def replace_marked_table_text(owner, *, selected_text, replacement_mode, original_text):
    deadline = perf_counter() + 0.25
    selected_text = _validate_plain_table_value(selected_text, deadline)
    replacement_mode = _validate_plain_table_value(replacement_mode, deadline)
    original_text = _validate_plain_table_value(original_text, deadline)
    return None
