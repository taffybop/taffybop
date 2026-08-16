"""Executable, byte-exact readiness contract for P03-US07.

This module is test-only.  It freezes the closed source/IR/public schemas,
canonical predecessor custody, list serialization grammar, and terminal
re-entry rules before production implementation begins.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal


POLICY_ID = "p03-outline-structure-v1"
REPORT_VERSION = "1.0"

SEQUENCE_KINDS = ("unordered", "ordered", "legal")
MARKER_STYLES = (
    "bullet",
    "decimal",
    "lower_alpha",
)
MARKER_OWNERSHIP = ("separate", "value_prefix")
INTERSTITIAL_TYPES = ("table",)
RELATIONSHIP_TYPES = (
    "contains",
    "outline_parent_of",
    "outline_next",
    "outline_continuation_of",
)
CONCERN_CODES = (
    "outline_source_evidence_unavailable",
    "outline_source_limit",
    "outline_candidate_limit",
    "outline_geometry_ambiguous",
    "outline_marker_ambiguous",
    "outline_sequence_invalid",
    "outline_interstitial_ambiguous",
    "outline_relationship_limit",
    "outline_canonical_custody_invalid",
    "outline_projection_failed_closed",
    "outline_concerns_truncated",
)
CONFIDENCE_UNAVAILABLE_REASONS = (
    "not_calibrated",
    "source_state_unavailable",
)

SOURCE_REPORT_FIELDS = (
    "report_version",
    "policy_id",
    "source_sha256",
    "status",
    "pages",
    "counts",
    "concern_codes",
    "extraction_ms",
)
SOURCE_PAGE_FIELDS = (
    "page_index",
    "page_width",
    "page_height",
    "unit",
    "coordinate_system_id",
    "source_character_count",
    "source_word_count",
    "markers",
    "concern_codes",
)
SOURCE_MARKER_FIELDS = (
    "raw_marker",
    "marker_style",
    "ordinal",
    "bbox",
    "source_object",
)
SOURCE_COUNT_FIELDS = (
    "pages",
    "source_characters",
    "source_words",
    "marker_candidates",
    "concerns",
)
SOURCE_OBJECT_FIELDS = ("reader", "page_index", "word_index")
CONFIDENCE_FIELDS = ("scope", "score", "unavailable_reason")
BBOX_FIELDS = ("x", "y", "width", "height", "unit")

IR_GROUP_DESCRIPTOR_FIELDS = (
    "policy_id",
    "role",
    "record_id",
    "sequence_kind",
    "marker_style",
    "anchor_element_id",
    "anchor_public_item_id",
    "member_item_ids",
    "member_element_ids",
    "continuation_element_ids",
    "relationship_ids",
    "canonical_contributor_element_ids",
    "canonical_relationship_ids",
)
IR_ITEM_DESCRIPTOR_FIELDS = (
    "policy_id",
    "role",
    "record_id",
    "group_element_id",
    "public_anchor_element_id",
    "source_public_item_id",
    "source_public_path",
    "sequence_kind",
    "marker_style",
    "raw_marker",
    "marker_ownership",
    "marker_separator",
    "body_text",
    "level",
    "ordinal",
    "parent_element_id",
    "marker_bbox_id",
    "marker_evidence_id",
    "relationship_ids",
)
GROUP_ELEMENT_CONTRACT_FIELDS = (
    "id",
    "page_id",
    "type",
    "reading_order",
    "value",
    "markdown",
    "bbox_ids",
    "evidence_ids",
    "outline_group",
    "presentation_role",
    "presentation",
    "properties",
)

PUBLIC_GROUP_FIELDS = (
    "id",
    "element_id",
    "page_id",
    "sequence_kind",
    "marker_style",
    "anchor_public_item_id",
    "anchor_element_id",
    "anchor_public_path",
    "group_bbox",
    "member_item_ids",
    "member_element_ids",
    "continuation_ids",
    "continuation_element_ids",
    "relationship_ids",
    "relationship_cardinality",
    "canonical_block_id",
    "canonical_primary_element_id",
    "canonical_contributor_element_ids",
    "canonical_relationship_ids",
    "canonical_markdown_sha256",
    "canonical_text_sha256",
    "source_method",
    "confidence",
    "concern_codes",
)
PUBLIC_ITEM_FIELDS = (
    "id",
    "element_id",
    "source_public_item_id",
    "source_public_path",
    "source_bbox_id",
    "source_evidence_ids",
    "source_object",
    "sequence_kind",
    "marker_style",
    "raw_marker",
    "marker_bbox",
    "marker_ownership",
    "marker_separator",
    "body_text",
    "predecessor_value_sha256",
    "level",
    "ordinal",
    "parent_id",
    "marker_bbox_id",
    "marker_evidence_id",
    "source_method",
    "confidence",
    "concern_codes",
    "relationship_ids",
    "continuation_ids",
)
PUBLIC_CONTINUATION_FIELDS = (
    "id",
    "element_id",
    "source_public_item_id",
    "source_public_path",
    "source_type",
    "bbox_id",
    "bbox",
    "source_evidence_ids",
    "target_node_id",
    "source_method",
    "confidence",
    "concern_codes",
    "relationship_ids",
)
PUBLIC_RELATIONSHIP_BASE_FIELDS = (
    "id",
    "type",
    "source_id",
    "target_id",
    "evidence_ids",
    "canonical_inert",
    "outline_group_id",
    "outline_policy",
)
PROCESSING_SUMMARY_FIELDS = (
    "policy_id",
    "status",
    "reason",
    "group_count",
    "node_count",
    "relationship_count",
    "concern_count",
    "extraction_ms",
    "projection_ms",
    "total_ms",
)

# Minimum/maximum incident edges after the complete graph is known.  The
# group descriptor names every story edge, while the group element itself is
# incident only to its one ``contains`` edge per member.
INCIDENT_CARDINALITY = {
    "group_element": {
        "contains_in": (0, 0),
        "contains_out": (2, 256),
        "total": (2, 256),
    },
    "root_item": {
        "contains_in": (1, 1),
        "parent_in": (0, 0),
        "parent_out": (0, 255),
        "next_in": (0, 1),
        "next_out": (0, 1),
        "continuation_in": (0, 64),
        "total": (1, 322),
    },
    "nested_item": {
        "contains_in": (1, 1),
        "parent_in": (1, 1),
        "parent_out": (0, 255),
        "next_in": (0, 1),
        "next_out": (0, 1),
        "continuation_in": (0, 64),
        "total": (2, 323),
    },
    "continuation": {
        "continuation_out": (1, 1),
        "total": (1, 1),
    },
}

PUBLIC_OUTLINE_KEYS = frozenset(
    {
        "layout_outline_structure_projected",
        "outline_policy",
        "outline_group",
        "outline_items",
        "outline_continuations",
    }
)


class ReadinessContractError(ValueError):
    """Raised when a test witness violates the frozen US07 contract."""


def _exact_keys(value: Mapping[str, Any], expected: Sequence[str], path: str) -> None:
    if set(value) != set(expected):
        raise ReadinessContractError(f"{path} closed keys differ")


def _strict_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_text(value: str) -> str:
    """Return the UTF-8 SHA-256 used by canonical sidecar bindings."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    """Return the exact US07 ID framing: canonical JSON and 20 hex chars."""

    return f"{prefix}-{hashlib.sha256(_strict_json_bytes(parts)).hexdigest()[:20]}"


def validate_source_report(report: Mapping[str, Any]) -> None:
    """Validate the closed source-report shape used by readiness witnesses."""

    _exact_keys(report, SOURCE_REPORT_FIELDS, "report")
    if report["report_version"] != REPORT_VERSION or report["policy_id"] != POLICY_ID:
        raise ReadinessContractError("report identity differs")
    if report["status"] not in {"available", "unavailable", "refused"}:
        raise ReadinessContractError("report status differs")
    if (
        not isinstance(report["source_sha256"], str)
        or len(report["source_sha256"]) != 64
        or any(
            character not in "0123456789abcdef" for character in report["source_sha256"]
        )
    ):
        raise ReadinessContractError("report source identity differs")
    pages = report["pages"]
    if not isinstance(pages, (list, tuple)):
        raise ReadinessContractError("report pages are not ordered")
    page_indexes: list[int] = []
    page_concern_count = 0
    for page in pages:
        if not isinstance(page, Mapping):
            raise ReadinessContractError("report page is not an object")
        _exact_keys(page, SOURCE_PAGE_FIELDS, "report.page")
        page_index = page["page_index"]
        if (
            isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or page_index < 1
        ):
            raise ReadinessContractError("report page geometry differs")
        page_indexes.append(page_index)
        if page["unit"] != "pt" or any(
            not isinstance(page[key], (int, float))
            or not math.isfinite(page[key])
            or page[key] <= 0
            for key in ("page_width", "page_height")
        ):
            raise ReadinessContractError("report page geometry differs")
        for key, maximum in (
            ("source_character_count", 500_000),
            ("source_word_count", 100_000),
        ):
            value = page[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= maximum
            ):
                raise ReadinessContractError("report page source count differs")
        markers = page["markers"]
        if not isinstance(markers, (list, tuple)) or len(markers) > 2_048:
            raise ReadinessContractError("report page markers differ")
        for marker in markers:
            _exact_keys(marker, SOURCE_MARKER_FIELDS, "report.marker")
            _exact_keys(marker["bbox"], BBOX_FIELDS, "report.marker.bbox")
            _exact_keys(
                marker["source_object"],
                SOURCE_OBJECT_FIELDS,
                "report.marker.source_object",
            )
            if marker["source_object"]["reader"] != "pdfplumber":
                raise ReadinessContractError("report marker reader differs")
            source_page = marker["source_object"]["page_index"]
            word_index = marker["source_object"]["word_index"]
            if (
                source_page != page_index
                or isinstance(word_index, bool)
                or (
                    not isinstance(word_index, int)
                    or not 0 <= word_index < page["source_word_count"]
                )
            ):
                raise ReadinessContractError("report marker source object differs")
            if marker["marker_style"] not in MARKER_STYLES:
                raise ReadinessContractError("report marker style differs")
            raw_marker = marker["raw_marker"]
            ordinal = marker["ordinal"]
            if (
                not isinstance(raw_marker, str)
                or not raw_marker
                or len(raw_marker.encode("utf-8")) > 64
            ):
                raise ReadinessContractError("report raw marker differs")
            if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
                raise ReadinessContractError("report marker ordinal differs")
            bbox = marker["bbox"]
            values = tuple(bbox[key] for key in ("x", "y", "width", "height"))
            if bbox["unit"] != "pt" or any(
                not isinstance(value, (int, float)) or not math.isfinite(value)
                for value in values
            ):
                raise ReadinessContractError("report marker bbox differs")
            x, y, width, height = values
            if (
                x < 0
                or y < 0
                or width <= 0
                or height <= 0
                or x + width > page["page_width"] + 0.001
                or y + height > page["page_height"] + 0.001
            ):
                raise ReadinessContractError("report marker bbox differs")
        page_concerns = page["concern_codes"]
        if (
            not isinstance(page_concerns, (list, tuple))
            or len(page_concerns) > 64
            or len(page_concerns) != len(set(page_concerns))
            or any(value not in CONCERN_CODES for value in page_concerns)
        ):
            raise ReadinessContractError("report page concerns differ")
        page_concern_count += len(page_concerns)
    if page_indexes != sorted(set(page_indexes)):
        raise ReadinessContractError("report page order differs")
    document_concerns = report["concern_codes"]
    if (
        not isinstance(document_concerns, (list, tuple))
        or len(document_concerns) > 256
        or len(document_concerns) != len(set(document_concerns))
        or any(value not in CONCERN_CODES for value in document_concerns)
    ):
        raise ReadinessContractError("report document concerns differ")
    counts = report["counts"]
    if not isinstance(counts, Mapping):
        raise ReadinessContractError("report counts are not an object")
    _exact_keys(counts, SOURCE_COUNT_FIELDS, "report.counts")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        raise ReadinessContractError("report counts are invalid")
    expected_counts = {
        "pages": len(pages),
        "source_characters": sum(page["source_character_count"] for page in pages),
        "source_words": sum(page["source_word_count"] for page in pages),
        "marker_candidates": sum(len(page["markers"]) for page in pages),
        "concerns": page_concern_count + len(document_concerns),
    }
    if (
        dict(counts) != expected_counts
        or counts["source_characters"] > 2_000_000
        or counts["source_words"] > 500_000
        or counts["marker_candidates"] > 10_000
    ):
        raise ReadinessContractError("report count totals differ")
    extraction_ms = report["extraction_ms"]
    if (
        not isinstance(extraction_ms, (int, float))
        or not math.isfinite(extraction_ms)
        or extraction_ms < 0
    ):
        raise ReadinessContractError("report extraction timing differs")
    _strict_json_bytes(report)


def validate_processing_summary(summary: Mapping[str, Any]) -> None:
    """Validate the exact enabled-stage public processing summary."""

    _exact_keys(summary, PROCESSING_SUMMARY_FIELDS, "processing.outline_structure")
    if summary["policy_id"] != POLICY_ID or summary["status"] not in {
        "projected",
        "no_candidates",
        "unavailable",
        "failed_closed",
    }:
        raise ReadinessContractError("processing summary identity/status differs")
    reason = summary["reason"]
    if reason is not None and (
        not isinstance(reason, str)
        or reason not in CONCERN_CODES
        or len(reason.encode("utf-8")) > 128
    ):
        raise ReadinessContractError("processing summary reason differs")
    if summary["status"] in {"projected", "no_candidates"} and reason is not None:
        raise ReadinessContractError("successful processing summary has a reason")
    if summary["status"] in {"unavailable", "failed_closed"} and reason is None:
        raise ReadinessContractError("failed processing summary has no reason")
    if summary["status"] == "unavailable" and reason not in {
        "outline_source_evidence_unavailable",
        "outline_source_limit",
    }:
        raise ReadinessContractError("unavailable processing reason differs")
    if summary["status"] == "failed_closed" and reason in {
        "outline_source_evidence_unavailable",
        "outline_source_limit",
    }:
        raise ReadinessContractError("failed-closed processing reason differs")
    for key in (
        "group_count",
        "node_count",
        "relationship_count",
        "concern_count",
    ):
        value = summary[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ReadinessContractError("processing summary count differs")
    for key in ("extraction_ms", "projection_ms", "total_ms"):
        value = summary[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ReadinessContractError("processing summary timing differs")
    expected_total = round(
        float(summary["extraction_ms"]) + float(summary["projection_ms"]), 3
    )
    if float(summary["total_ms"]) != expected_total:
        raise ReadinessContractError("processing summary total differs")


def combine_terminal_processing_summaries(
    initial: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    """Count extraction once and sum the two projection passes exactly."""

    validate_processing_summary(initial)
    validate_processing_summary(terminal)
    combined = dict(terminal)
    combined["extraction_ms"] = round(float(initial["extraction_ms"]), 3)
    combined["projection_ms"] = round(
        float(initial["projection_ms"]) + float(terminal["projection_ms"]),
        3,
    )
    combined["total_ms"] = round(
        combined["extraction_ms"] + combined["projection_ms"],
        3,
    )
    validate_processing_summary(combined)
    return combined


def validate_relationship_descriptor(value: Mapping[str, Any]) -> None:
    """Validate one closed public relationship descriptor."""

    relationship_type = value.get("type")
    extra: tuple[str, ...] = ()
    if relationship_type == "outline_next":
        extra = ("intervening_element_ids",)
    elif relationship_type == "outline_continuation_of":
        extra = ("interstitial_kind",)
    elif relationship_type not in {"contains", "outline_parent_of"}:
        raise ReadinessContractError("relationship type differs")
    _exact_keys(
        value,
        (*PUBLIC_RELATIONSHIP_BASE_FIELDS, *extra),
        "relationship",
    )
    if value["canonical_inert"] is not True:
        raise ReadinessContractError("relationship is not canonical-inert")
    if value["outline_policy"] != POLICY_ID:
        raise ReadinessContractError("relationship policy differs")
    if relationship_type == "outline_continuation_of" and (
        value["interstitial_kind"] not in INTERSTITIAL_TYPES
    ):
        raise ReadinessContractError("interstitial type differs")
    _strict_json_bytes(value)


@dataclass(frozen=True, slots=True)
class CanonicalClosure:
    """Complete predecessor canonical custody transferred to one group."""

    block_id: str
    page_id: str
    primary_element_id: str
    primary_element_type: str
    scope: Literal["body"]
    predecessor_primary_ids: tuple[str, ...]
    contributing_element_ids: tuple[str, ...]
    predecessor_relationship_ids: tuple[str, ...]
    relationship_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectionTransactionResult:
    """Observable result of the readiness transaction state machine."""

    payload: dict[str, Any]
    committed: bool
    events: tuple[str, ...]


def canonical_closure(
    group: Mapping[str, Any],
    canonical_presentation: Mapping[str, Any],
    *,
    form_owned_element_ids: Sequence[str] = (),
) -> CanonicalClosure:
    """Resolve and validate complete predecessor blocks for one group.

    Every target element must have exactly one included predecessor owner.
    The whole block closure—not merely the target element—is transferred.
    Any form overlap rejects the group before mutation.
    """

    pages = canonical_presentation.get("pages")
    if not isinstance(pages, list):
        raise ReadinessContractError("canonical pages are unavailable")
    blocks = [
        block
        for page in pages
        if isinstance(page, Mapping)
        for block in page.get("blocks", [])
        if isinstance(block, Mapping) and block.get("omission_reason") is None
    ]
    target_ids = {
        group["anchor_element_id"],
        *group["member_element_ids"],
        *group.get("continuation_element_ids", ()),
    }
    owners: dict[str, list[Mapping[str, Any]]] = {value: [] for value in target_ids}
    for block in blocks:
        for contribution_id in block.get("contributing_element_ids", []):
            if contribution_id in owners:
                owners[contribution_id].append(block)
    if any(len(values) != 1 for values in owners.values()):
        raise ReadinessContractError("canonical target ownership is not exact")
    selected_ids = {str(values[0]["id"]) for values in owners.values()}
    selected = [block for block in blocks if str(block["id"]) in selected_ids]
    anchor_blocks = [
        block
        for block in selected
        if block.get("primary_element_id") == group["anchor_element_id"]
    ]
    if len(anchor_blocks) != 1:
        raise ReadinessContractError("canonical anchor ownership is not exact")
    [anchor] = anchor_blocks
    if anchor.get("scope") != "body":
        raise ReadinessContractError("outline anchor must be body scope")

    contributions: list[str] = []
    predecessor_relationships: list[str] = []
    predecessor_primaries: list[str] = []
    for block in selected:
        predecessor_primaries.append(str(block["primary_element_id"]))
        for value in block.get("contributing_element_ids", []):
            if value not in contributions:
                contributions.append(value)
        for value in block.get("relationship_ids", []):
            if value not in predecessor_relationships:
                predecessor_relationships.append(value)
    if contributions[0] != group["anchor_element_id"]:
        # Canonical block order is primary-first; move only the validated
        # anchor to the required first position without changing other order.
        contributions.remove(group["anchor_element_id"])
        contributions.insert(0, group["anchor_element_id"])
    if set(contributions) & set(form_owned_element_ids):
        raise ReadinessContractError("canonical closure overlaps form ownership")
    relationship_ids = sorted({*predecessor_relationships, *group["relationship_ids"]})
    return CanonicalClosure(
        block_id=str(anchor["id"]),
        page_id=str(anchor["page_id"]),
        primary_element_id=str(anchor["primary_element_id"]),
        primary_element_type=str(anchor["primary_element_type"]),
        scope="body",
        predecessor_primary_ids=tuple(predecessor_primaries),
        contributing_element_ids=tuple(contributions),
        predecessor_relationship_ids=tuple(predecessor_relationships),
        relationship_ids=tuple(relationship_ids),
    )


def build_group_element_contract(
    group: Mapping[str, Any],
    closure: CanonicalClosure,
) -> dict[str, Any]:
    """Build the exact new non-primary group ElementRecord input contract."""

    descriptor = {
        "policy_id": POLICY_ID,
        "role": "group",
        "record_id": group["id"],
        "sequence_kind": group["sequence_kind"],
        "marker_style": group["marker_style"],
        "anchor_element_id": group["anchor_element_id"],
        "anchor_public_item_id": group["anchor_public_item_id"],
        "member_item_ids": list(group["member_item_ids"]),
        "member_element_ids": list(group["member_element_ids"]),
        "continuation_element_ids": list(group["continuation_element_ids"]),
        "relationship_ids": list(group["relationship_ids"]),
        "canonical_contributor_element_ids": list(closure.contributing_element_ids),
        "canonical_relationship_ids": list(closure.relationship_ids),
    }
    _exact_keys(descriptor, IR_GROUP_DESCRIPTOR_FIELDS, "outline_group")
    record = {
        "id": group["element_id"],
        "page_id": group["page_id"],
        "type": "outline_group",
        "reading_order": None,
        "value": None,
        "markdown": None,
        "bbox_ids": [group["group_bbox_id"]],
        "evidence_ids": [group["evidence_id"]],
        "outline_group": descriptor,
        "presentation_role": "subordinate",
        "presentation": {
            "include_subordinate_ocr": None,
            "accepted": None,
        },
        "properties": {
            "outline_policy": POLICY_ID,
            "public_anchor_element_id": group["anchor_element_id"],
        },
    }
    _exact_keys(record, GROUP_ELEMENT_CONTRACT_FIELDS, "outline_group_element")
    return record


def _safe_plain_text(value: str) -> str:
    return "".join(
        character
        if character >= " " and character not in {"\x7f", "\u2028", "\u2029"}
        else "�"
        for character in value
    )


def _list_tag(group: Mapping[str, Any]) -> tuple[str, str]:
    if group["sequence_kind"] == "unordered":
        return "ul", ""
    style = group["marker_style"]
    type_value = {
        "decimal": "",
        "lower_alpha": "a",
        "upper_alpha": "A",
        "lower_roman": "i",
        "upper_roman": "I",
    }.get(style)
    if type_value is None:
        raise ReadinessContractError("ordered marker style is unsupported")
    return "ol", f' type="{type_value}"' if type_value else ""


def render_outline_group(
    group: Mapping[str, Any],
    *,
    continuation_markdown: Mapping[str, str] | None = None,
    continuation_text: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Render exact safe HTML-list Markdown and exact semantic plain text.

    V1 accepts only sibling sequences beginning at one, so every ``ol`` has
    literal ``start="1"``. Attribute order, two-space indentation, and LF
    newlines are normative. Accepted continuation Markdown is inserted
    byte-for-byte inside its owning ``li``; continuation text is indented one
    level.
    """

    markdown_by_id = dict(continuation_markdown or {})
    text_by_id = dict(continuation_text or {})
    nodes = list(group["nodes"])
    by_parent: dict[str | None, list[Mapping[str, Any]]] = {}
    for node in nodes:
        by_parent.setdefault(node["parent_id"], []).append(node)
    for siblings in by_parent.values():
        if [node["ordinal"] for node in siblings] != list(range(1, len(siblings) + 1)):
            raise ReadinessContractError("sibling ordinals must begin at one")
    roots = by_parent.get(None, [])
    if len(roots) < 2:
        raise ReadinessContractError("outline group requires at least two roots")
    continuation_by_target: dict[str, list[Mapping[str, Any]]] = {}
    for continuation in group.get("continuations") or ():
        continuation_by_target.setdefault(continuation["target_node_id"], []).append(
            continuation
        )
    tag, type_attribute = _list_tag(group)
    start_attribute = ' start="1"' if tag == "ol" else ""
    group_id = html.escape(str(group["id"]), quote=True)
    root_open = (
        f'<{tag} data-outline-group="{group_id}" '
        f'data-outline-policy="{POLICY_ID}"{type_attribute}'
        f"{start_attribute}>"
    )
    markdown_lines = [root_open]
    text_lines: list[str] = []

    def render_level(parent_id: str | None, level: int, *, root: bool) -> None:
        siblings = by_parent.get(parent_id, [])
        if not root:
            indent = "  " * level
            markdown_lines.append(f"{indent}<{tag}{type_attribute}{start_attribute}>")
        for node in siblings:
            if node["level"] != level:
                raise ReadinessContractError("node level differs from its parent")
            indent = "  " * (level + 1)
            item_id = html.escape(str(node["id"]), quote=True)
            marker = html.escape(str(node["raw_marker"]), quote=True)
            value_attribute = f' value="{node["ordinal"]}"' if tag == "ol" else ""
            body = html.escape(_safe_plain_text(str(node["body_text"])), quote=False)
            opening = (
                f'{indent}<li data-outline-item="{item_id}" '
                f'data-source-marker="{marker}"{value_attribute}>{body}'
            )
            text_lines.append(
                f"{'  ' * level}{_safe_plain_text(str(node['raw_marker']))} "
                f"{_safe_plain_text(str(node['body_text']))}"
            )
            has_children = node["id"] in by_parent
            owned_continuations = continuation_by_target.get(node["id"], [])
            if not has_children and not owned_continuations:
                markdown_lines.append(f"{opening}</li>")
                continue
            markdown_lines.append(opening)
            if has_children:
                render_level(node["id"], level + 1, root=False)
            for continuation in owned_continuations:
                element_id = continuation["element_id"]
                if element_id not in markdown_by_id or element_id not in text_by_id:
                    raise ReadinessContractError(
                        "continuation canonical block is absent"
                    )
                embedded_markdown = markdown_by_id[element_id]
                embedded_text = text_by_id[element_id]
                if embedded_markdown != embedded_markdown.strip() or (
                    embedded_text != embedded_text.strip()
                ):
                    raise ReadinessContractError("continuation has outer whitespace")
                markdown_lines.extend(embedded_markdown.split("\n"))
                text_lines.extend(
                    f"{'  ' * (level + 1)}{line}" for line in embedded_text.split("\n")
                )
            markdown_lines.append(f"{indent}</li>")
        if not root:
            markdown_lines.append(f"{'  ' * level}</{tag}>")

    render_level(None, 0, root=True)
    markdown_lines.append(f"</{tag}>")
    return "\n".join(markdown_lines), "\n".join(text_lines)


def validate_public_sidecar(
    anchor: Mapping[str, Any],
    canonical_block: Mapping[str, Any],
) -> None:
    """Validate anchor-only schema, graph backlinks, and canonical binding."""

    if anchor.get("layout_outline_structure_projected") is not True or (
        anchor.get("outline_policy") != POLICY_ID
    ):
        raise ReadinessContractError("outline anchor marker differs")
    group = anchor.get("outline_group")
    items = anchor.get("outline_items")
    continuations = anchor.get("outline_continuations")
    relationships = anchor.get("relationships")
    if (
        not isinstance(group, Mapping)
        or not isinstance(items, list)
        or (not isinstance(continuations, list) or not isinstance(relationships, list))
    ):
        raise ReadinessContractError("outline sidecar is incomplete")
    _exact_keys(group, PUBLIC_GROUP_FIELDS, "outline_group")
    for item in items:
        _exact_keys(item, PUBLIC_ITEM_FIELDS, "outline_item")
        _exact_keys(item["source_object"], SOURCE_OBJECT_FIELDS, "source_object")
        _exact_keys(item["marker_bbox"], BBOX_FIELDS, "marker_bbox")
        _exact_keys(item["confidence"], CONFIDENCE_FIELDS, "confidence")
    for continuation in continuations:
        _exact_keys(continuation, PUBLIC_CONTINUATION_FIELDS, "continuation")
    story_relationships = [
        value
        for value in relationships
        if isinstance(value, Mapping) and value.get("outline_policy") == POLICY_ID
    ]
    for relationship in story_relationships:
        validate_relationship_descriptor(relationship)
    relationship_ids = [value["id"] for value in story_relationships]
    if relationship_ids != list(group["relationship_ids"]):
        raise ReadinessContractError("relationship order differs")
    backlinks = Counter(
        relationship_id
        for item in items
        for relationship_id in item["relationship_ids"]
    )
    backlinks.update(
        relationship_id
        for continuation in continuations
        for relationship_id in continuation["relationship_ids"]
    )
    expected_backlinks = Counter()
    item_element_ids = {item["element_id"] for item in items}
    continuation_element_ids = {
        continuation["element_id"] for continuation in continuations
    }
    for relationship in story_relationships:
        for endpoint in (relationship["source_id"], relationship["target_id"]):
            if endpoint in item_element_ids or endpoint in continuation_element_ids:
                expected_backlinks[relationship["id"]] += 1
    if backlinks != expected_backlinks:
        raise ReadinessContractError("relationship backlinks differ")
    if group["canonical_block_id"] != canonical_block.get("id") or (
        group["canonical_primary_element_id"]
        != canonical_block.get("primary_element_id")
    ):
        raise ReadinessContractError("canonical primary binding differs")
    if list(group["canonical_contributor_element_ids"]) != canonical_block.get(
        "contributing_element_ids"
    ) or list(group["canonical_relationship_ids"]) != canonical_block.get(
        "relationship_ids"
    ):
        raise ReadinessContractError("canonical closure binding differs")
    if group["canonical_markdown_sha256"] != sha256_text(
        str(canonical_block.get("markdown"))
    ) or group["canonical_text_sha256"] != sha256_text(
        str(canonical_block.get("text"))
    ):
        raise ReadinessContractError("canonical output hash differs")
    compact_sidecar = _strict_json_bytes(
        {
            **{key: anchor[key] for key in PUBLIC_OUTLINE_KEYS},
            "relationships": story_relationships,
        }
    )
    if len(compact_sidecar) > 512 * 1024:
        raise ReadinessContractError("complete outline sidecar exceeds byte cap")


def strip_complete_outline_sidecars(document: Mapping[str, Any]) -> dict[str, Any]:
    """Strip only complete US07 sidecars; malformed markers stay untouched."""

    cleaned = deepcopy(dict(document))
    canonical = cleaned.get("canonical_presentation")
    canonical_blocks = [
        block
        for page in (
            canonical.get("pages", []) if isinstance(canonical, Mapping) else []
        )
        if isinstance(page, Mapping)
        for block in page.get("blocks", [])
        if isinstance(block, Mapping)
    ]
    for page in cleaned.get("pages", []):
        if not isinstance(page, dict):
            continue
        for item in page.get("items", []):
            if not isinstance(item, dict):
                continue
            marker = (
                item.get("layout_outline_structure_projected") is True
                and item.get("outline_policy") == POLICY_ID
            )
            group = item.get("outline_group")
            outline_items = item.get("outline_items")
            continuations = item.get("outline_continuations")
            relationships = item.get("relationships")
            if (
                not marker
                or not isinstance(group, Mapping)
                or (
                    not isinstance(outline_items, list)
                    or not isinstance(continuations, list)
                    or not isinstance(relationships, list)
                )
            ):
                continue
            try:
                _exact_keys(group, PUBLIC_GROUP_FIELDS, "outline_group")
                for value in outline_items:
                    _exact_keys(value, PUBLIC_ITEM_FIELDS, "outline_item")
                for value in continuations:
                    _exact_keys(value, PUBLIC_CONTINUATION_FIELDS, "continuation")
                expected_ids = list(group["relationship_ids"])
                story = [
                    value
                    for value in relationships
                    if isinstance(value, Mapping)
                    and value.get("outline_policy") == POLICY_ID
                ]
                if [value.get("id") for value in story] != expected_ids:
                    raise ReadinessContractError("story relationship set differs")
                for value in story:
                    validate_relationship_descriptor(value)
                matching_blocks = [
                    block
                    for block in canonical_blocks
                    if block.get("id") == group["canonical_block_id"]
                    and block.get("primary_element_id")
                    == group["canonical_primary_element_id"]
                ]
                if len(matching_blocks) != 1:
                    raise ReadinessContractError("canonical binding is unavailable")
                validate_public_sidecar(item, matching_blocks[0])
            except Exception:
                continue
            for key in PUBLIC_OUTLINE_KEYS:
                item.pop(key, None)
            retained = [
                value
                for value in relationships
                if not (
                    isinstance(value, Mapping)
                    and value.get("outline_policy") == POLICY_ID
                    and value.get("id") in set(expected_ids)
                )
            ]
            if retained:
                item["relationships"] = retained
            else:
                item.pop("relationships", None)
    return cleaned


def terminal_reentry_order(*, forms_enabled: bool) -> tuple[str, ...]:
    """Return the normative reverse-strip/one-rebuild/forward-replay trace."""

    trace = ["snapshot", "strip_outline"]
    if forms_enabled:
        trace.append("strip_forms")
    trace.append("drop_canonical")
    trace.extend(
        (
            "round_trip_once",
            "replay_forms" if forms_enabled else "skip_forms",
            "replay_outline",
            "validate_final_ir",
            "canonical_dry_run",
            "commit",
        )
    )
    return tuple(trace)


def execute_transaction_witness(
    predecessor: Mapping[str, Any],
    *,
    outcome: Literal[
        "success",
        "page_failure",
        "document_failure",
        "canonical_failure",
    ],
    page_index: int = 0,
) -> ProjectionTransactionResult:
    """Execute the frozen page/document/canonical rollback state machine."""

    before = deepcopy(dict(predecessor))
    candidate = deepcopy(before)
    pages = candidate.get("pages")
    if not isinstance(pages, list) or not 0 <= page_index < len(pages):
        raise ReadinessContractError("transaction page is unavailable")
    page_snapshot = deepcopy(pages[page_index])
    events = ["snapshot_document", "snapshot_page", "mutate_page"]
    if not isinstance(pages[page_index], dict):
        raise ReadinessContractError("transaction page is not an object")
    pages[page_index]["layout_outline_structure_projected"] = True
    if outcome == "page_failure":
        pages[page_index] = page_snapshot
        candidate.setdefault("outline_concerns", []).append(
            {
                "code": "outline_projection_failed_closed",
                "page_index": page_index + 1,
            }
        )
        return ProjectionTransactionResult(
            payload=candidate,
            committed=False,
            events=(*events, "restore_page", "emit_page_concern"),
        )
    if outcome in {"document_failure", "canonical_failure"}:
        restored = deepcopy(before)
        restored.setdefault("outline_concerns", []).append(
            {
                "code": (
                    "outline_canonical_custody_invalid"
                    if outcome == "canonical_failure"
                    else "outline_projection_failed_closed"
                )
            }
        )
        failure_check = (
            "canonical_dry_run"
            if outcome == "canonical_failure"
            else "validate_document"
        )
        return ProjectionTransactionResult(
            payload=restored,
            committed=False,
            events=(
                *events,
                failure_check,
                "restore_document",
                "emit_document_concern",
            ),
        )
    return ProjectionTransactionResult(
        payload=candidate,
        committed=True,
        events=(*events, "validate_document", "canonical_dry_run", "commit"),
    )


__all__ = [
    "BBOX_FIELDS",
    "CONCERN_CODES",
    "CONFIDENCE_FIELDS",
    "CONFIDENCE_UNAVAILABLE_REASONS",
    "CanonicalClosure",
    "GROUP_ELEMENT_CONTRACT_FIELDS",
    "INCIDENT_CARDINALITY",
    "INTERSTITIAL_TYPES",
    "IR_GROUP_DESCRIPTOR_FIELDS",
    "IR_ITEM_DESCRIPTOR_FIELDS",
    "MARKER_OWNERSHIP",
    "MARKER_STYLES",
    "POLICY_ID",
    "PROCESSING_SUMMARY_FIELDS",
    "ProjectionTransactionResult",
    "PUBLIC_CONTINUATION_FIELDS",
    "PUBLIC_GROUP_FIELDS",
    "PUBLIC_ITEM_FIELDS",
    "PUBLIC_OUTLINE_KEYS",
    "PUBLIC_RELATIONSHIP_BASE_FIELDS",
    "RELATIONSHIP_TYPES",
    "REPORT_VERSION",
    "ReadinessContractError",
    "SEQUENCE_KINDS",
    "SOURCE_MARKER_FIELDS",
    "SOURCE_COUNT_FIELDS",
    "SOURCE_OBJECT_FIELDS",
    "SOURCE_PAGE_FIELDS",
    "SOURCE_REPORT_FIELDS",
    "canonical_closure",
    "build_group_element_contract",
    "combine_terminal_processing_summaries",
    "execute_transaction_witness",
    "render_outline_group",
    "sha256_text",
    "stable_id",
    "strip_complete_outline_sidecars",
    "terminal_reentry_order",
    "validate_public_sidecar",
    "validate_processing_summary",
    "validate_relationship_descriptor",
    "validate_source_report",
]
