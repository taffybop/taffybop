"""Bounded native-PDF text-run and redline evidence.

The feature flag lives at the pipeline boundary.  This module is deliberately
source-only and deterministic: it extracts native glyph/style and vector-rule
evidence, then projects only uniquely grounded sparse runs onto an existing
P03-US04 IR.
"""

from __future__ import annotations

import hashlib
import io
import json
import heapq
import math
import re
import time
import unicodedata
from bisect import bisect_left, bisect_right
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


TEXT_RUN_EVIDENCE_SCHEMA_VERSION = "1.0"
TEXT_RUN_POLICY_ID = "p03-text-run-semantics-v1"
TEXT_RUN_EXTRACTION_POLICY_ID = "p03-text-run-extraction-v1"
TEXT_RUN_ASSOCIATION_POLICY_ID = "p03-text-run-association-v1"
ACTIVE_TEXT_POLICY_ID = "omit-proven-deletions-v1"

MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_SOURCE_CHARACTERS = 500_000
MAX_RUNS_PER_PAGE = 4_096
MAX_RUNS_PER_DOCUMENT = 10_000
MAX_RULES_PER_PAGE = 4_096
MAX_RULES_PER_DOCUMENT = 10_000
MAX_RULES_PER_RUN = 64
MAX_RUNS_PER_RULE = 64
MAX_ASSOCIATIONS_PER_PAGE = 65_536
MAX_TEXT_BYTES_PER_RUN = 16 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_FONT_NAME_BYTES = 256
MAX_EXTRACTION_SECONDS = 2.0
MAX_CONCERNS_PER_PAGE = 16
MAX_CONCERNS_PER_DOCUMENT = 256
MAX_TOTAL_CONCERNS = 512
MAX_TARGET_CANDIDATES_PER_PAGE = 8_192
MAX_TARGET_TRAVERSAL_PER_PAGE = 65_536
MAX_TARGET_TEXT_BYTES_PER_PAGE = 1024 * 1024
MAX_TARGET_CANDIDATES_PER_DOCUMENT = 65_536
MAX_TARGET_TEXT_BYTES_PER_DOCUMENT = 8 * 1024 * 1024
MAX_ALIGNMENT_COMPARISONS_PER_PAGE = 65_536
MAX_ALIGNMENT_TEXT_WORK_PER_PAGE = 8 * 1024 * 1024

MIN_RULE_WIDTH = 2.0
MAX_RULE_THICKNESS = 1.5
MIN_RULE_ASPECT = 3.0
MIN_HORIZONTAL_OVERLAP = 2.0
MIN_RUN_COVERAGE = 0.80
MAX_COLOR_COMPONENT_DELTA = 1.0 / 255.0
STRIKE_BAND = (0.35, 0.70)
UNDERLINE_BAND = (0.75, 1.10)
RULE_GLYPH_CENTER_MARGIN = 0.25
_BAND_RATIO_EPSILON = Decimal("1e-12")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TextRunConcernCode = Literal[
    "text_run_source_unsupported",
    "text_run_source_invalid",
    "text_run_source_limit",
    "text_run_rule_limit",
    "text_run_alignment_limit",
    "text_run_alignment_ambiguous",
    "text_run_rule_ambiguous",
    "text_run_transform_unavailable",
    "text_run_projection_failed_closed",
    "text_run_concerns_truncated",
]
_BOLD_TOKENS = ("bold", "black", "demi")
_ITALIC_TOKENS = ("italic", "oblique")
_COMPARISON_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceBBox(_EvidenceModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"] = "pt"

    @model_validator(mode="after")
    def validate_finite(self) -> "SourceBBox":
        if not all(
            math.isfinite(value)
            for value in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("source bbox must be finite")
        return self


class SourceColor(_EvidenceModel):
    space: Literal["gray", "rgb", "cmyk", "unknown"]
    components: tuple[float, ...] = ()
    raw_value: float | tuple[float, ...] | Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def validate_color(self) -> "SourceColor":
        expected = {"gray": 1, "rgb": 3, "cmyk": 4, "unknown": 0}
        if len(self.components) != expected[self.space]:
            raise ValueError("normalized color component arity is invalid")
        if not all(
            math.isfinite(value) and 0 <= value <= 1
            for value in self.components
        ):
            raise ValueError("normalized color components must be finite")
        if isinstance(self.raw_value, (int, float)):
            if isinstance(self.raw_value, bool) or not math.isfinite(
                float(self.raw_value)
            ):
                raise ValueError("raw color component is invalid")
        elif isinstance(self.raw_value, tuple):
            if not 1 <= len(self.raw_value) <= 4 or not all(
                math.isfinite(value) for value in self.raw_value
            ):
                raise ValueError("raw color components are invalid")
        elif self.raw_value != "unknown":
            raise ValueError("raw color marker is invalid")
        return self


class SourceRuleEvidence(_EvidenceModel):
    id: str
    page_index: int = Field(ge=1)
    source_object_kind: Literal["line", "rect"]
    source_object_index: int = Field(ge=0)
    bbox: SourceBBox
    color: SourceColor
    width: float = Field(gt=0)
    thickness: float = Field(gt=0)
    extraction_policy_id: Literal["p03-text-run-extraction-v1"] = (
        TEXT_RUN_EXTRACTION_POLICY_ID
    )

    @model_validator(mode="after")
    def validate_geometry(self) -> "SourceRuleEvidence":
        if not self.id or len(self.id) > 256:
            raise ValueError("source rule ID is invalid")
        if (
            not math.isfinite(self.width)
            or not math.isfinite(self.thickness)
            or self.width < MIN_RULE_WIDTH
            or self.thickness > MAX_RULE_THICKNESS
            or self.width / self.thickness < MIN_RULE_ASPECT
            or not math.isclose(
                self.width,
                self.bbox.width,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            or not math.isclose(
                self.thickness,
                self.bbox.height,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        ):
            raise ValueError("source rule dimensions are inconsistent")
        return self


class SourceRunEvidence(_EvidenceModel):
    id: str
    page_index: int = Field(ge=1)
    line_index: int = Field(ge=0)
    text: str
    bbox: SourceBBox
    font_name: str
    font_size: float = Field(gt=0)
    bold: bool
    italic: bool
    color: SourceColor
    source_character_indexes: tuple[int, ...]
    change_group_id: str | None = None
    change_state: Literal[
        "deleted",
        "inserted",
        "replacement",
        "unknown",
        "unchanged",
    ]
    decorations: tuple[Literal["strikethrough", "underline"], ...] = ()
    placeholder: bool = False
    rule_ids: tuple[str, ...] = ()
    semantic_derivation: Literal[
        "source_style",
        "same_color_midline_rule",
        "same_color_underline_rule",
        "same_color_underlined_placeholder",
        "native_tracked_change",
    ]
    extraction_policy_id: Literal["p03-text-run-extraction-v1"] = (
        TEXT_RUN_EXTRACTION_POLICY_ID
    )
    association_policy_id: Literal["p03-text-run-association-v1"] = (
        TEXT_RUN_ASSOCIATION_POLICY_ID
    )

    @model_validator(mode="after")
    def validate_run(self) -> "SourceRunEvidence":
        if not self.id or len(self.id) > 256:
            raise ValueError("source run ID is invalid")
        if not self.text or not self.text.strip():
            raise ValueError("source run cannot be empty or whitespace-only")
        if len(self.text.encode("utf-8")) > MAX_TEXT_BYTES_PER_RUN:
            raise ValueError("source run text exceeds its byte limit")
        if len(self.font_name.encode("utf-8")) > MAX_FONT_NAME_BYTES:
            raise ValueError("source font name exceeds its byte limit")
        if not self.font_name:
            raise ValueError("source font name cannot be empty")
        if not math.isfinite(self.font_size):
            raise ValueError("source font size must be finite")
        if (
            not self.source_character_indexes
            or any(index < 0 for index in self.source_character_indexes)
            or tuple(sorted(set(self.source_character_indexes)))
            != self.source_character_indexes
        ):
            raise ValueError("source character indexes must be unique and sorted")
        if len(set(self.rule_ids)) != len(self.rule_ids):
            raise ValueError("source run repeats a rule")
        if any(not rule_id or len(rule_id) > 256 for rule_id in self.rule_ids):
            raise ValueError("source run has an invalid rule ID")
        if len(self.rule_ids) > MAX_RULES_PER_RUN:
            raise ValueError("source run exceeds its rule limit")
        if len(set(self.decorations)) != len(self.decorations):
            raise ValueError("source run repeats a decoration")
        decoration_order = {"strikethrough": 0, "underline": 1}
        if self.decorations != tuple(
            sorted(self.decorations, key=decoration_order.__getitem__)
        ):
            raise ValueError("source run decorations are out of canonical order")
        if self.change_group_id is not None and (
            not self.change_group_id or len(self.change_group_id) > 256
        ):
            raise ValueError("source run change-group ID is invalid")

        if self.semantic_derivation == "source_style":
            expected_state = (
                "unknown"
                if self.color.space != "unknown" and not _is_black(self.color)
                else "unchanged"
            )
            if (
                self.change_state != expected_state
                or self.decorations
                or self.placeholder
                or self.rule_ids
                or self.change_group_id is not None
            ):
                raise ValueError("source-style run has inconsistent semantics")
        elif self.semantic_derivation == "same_color_midline_rule":
            if (
                self.change_state != "deleted"
                or self.decorations != ("strikethrough",)
                or self.placeholder
                or not self.rule_ids
                or self.change_group_id is None
            ):
                raise ValueError("midline-rule run has inconsistent semantics")
        elif self.semantic_derivation == "same_color_underline_rule":
            if (
                self.change_state != "unchanged"
                or self.decorations != ("underline",)
                or self.placeholder
                or not self.rule_ids
                or self.change_group_id is None
            ):
                raise ValueError("underline-rule run has inconsistent semantics")
        elif self.semantic_derivation == "same_color_underlined_placeholder":
            if (
                self.change_state != "unknown"
                or self.decorations != ("underline",)
                or not self.placeholder
                or not self.rule_ids
                or self.change_group_id is None
                or not 3 <= len(self.text) <= 128
                or set(self.text) != {"_"}
            ):
                raise ValueError(
                    "underlined-placeholder run has inconsistent semantics"
                )
        elif (
            self.change_state not in {"deleted", "inserted", "replacement"}
            or self.placeholder
            or self.rule_ids
            or self.change_group_id is not None
        ):
            raise ValueError("native tracked-change run has inconsistent semantics")
        return self


class SourceSemanticsPage(_EvidenceModel):
    page_index: int = Field(ge=1)
    page_width: float = Field(gt=0)
    page_height: float = Field(gt=0)
    status: Literal["projectable", "unavailable"]
    concern_code: (
        Literal[
            "text_run_source_unsupported",
            "text_run_source_invalid",
            "text_run_source_limit",
            "text_run_rule_limit",
            "text_run_transform_unavailable",
        ]
        | None
    ) = None
    concern_codes: tuple[
        Literal["text_run_rule_ambiguous"],
        ...,
    ] = ()
    run_ids: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> "SourceSemanticsPage":
        if not math.isfinite(self.page_width) or not math.isfinite(
            self.page_height
        ):
            raise ValueError("source page dimensions must be finite")
        if self.status == "projectable" and self.concern_code is not None:
            raise ValueError("projectable page cannot carry a refusal")
        if self.status == "unavailable" and (
            self.concern_code is None or self.run_ids
        ):
            raise ValueError(
                "unavailable page requires one refusal and no runs"
            )
        if len(self.concern_codes) != len(set(self.concern_codes)):
            raise ValueError("source page repeats a concern")
        if len(self.run_ids) != len(set(self.run_ids)):
            raise ValueError("source page repeats a run")
        if len(self.rule_ids) != len(set(self.rule_ids)):
            raise ValueError("source page repeats a rule")
        if len(self.run_ids) > MAX_RUNS_PER_PAGE:
            raise ValueError("source page exceeds its run limit")
        if len(self.rule_ids) > MAX_RULES_PER_PAGE:
            raise ValueError("source page exceeds its rule limit")
        return self


class TextRunEvidence(_EvidenceModel):
    schema_version: Literal["1.0"] = TEXT_RUN_EVIDENCE_SCHEMA_VERSION
    policy_id: Literal["p03-text-run-semantics-v1"] = TEXT_RUN_POLICY_ID
    extraction_policy_id: Literal["p03-text-run-extraction-v1"] = (
        TEXT_RUN_EXTRACTION_POLICY_ID
    )
    association_policy_id: Literal["p03-text-run-association-v1"] = (
        TEXT_RUN_ASSOCIATION_POLICY_ID
    )
    source_sha256: str
    usable: bool
    refusal_code: _TextRunConcernCode | None = None
    page_count: int = Field(ge=0, le=101)
    character_count: int = Field(ge=0, le=MAX_SOURCE_CHARACTERS)
    candidate_rule_count: int = Field(ge=0, le=MAX_RULES_PER_DOCUMENT)
    pages: tuple[SourceSemanticsPage, ...] = ()
    runs: tuple[SourceRunEvidence, ...] = ()
    rules: tuple[SourceRuleEvidence, ...] = ()
    concerns: tuple[dict[str, Any], ...] = ()
    elapsed_ms: float = Field(ge=0, le=60_000)

    @model_validator(mode="after")
    def validate_report(self) -> "TextRunEvidence":
        if not _SHA256_RE.fullmatch(self.source_sha256):
            raise ValueError("source SHA-256 must be lowercase hexadecimal")
        if self.usable and self.refusal_code is not None:
            raise ValueError("usable evidence cannot carry a refusal")
        if not self.usable and not self.refusal_code:
            raise ValueError("unusable evidence requires a refusal")
        if self.usable and self.concerns:
            raise ValueError("usable evidence cannot carry document concerns")
        if not self.usable and self.concerns != (
            {
                "code": self.refusal_code,
                "policy_id": TEXT_RUN_POLICY_ID,
            },
        ):
            raise ValueError(
                "unusable evidence requires one content-free fixed concern"
            )
        if not math.isfinite(self.elapsed_ms):
            raise ValueError("text-run evidence elapsed time must be finite")
        run_ids = [run.id for run in self.runs]
        rule_ids = [rule.id for rule in self.rules]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("text-run evidence repeats a run ID")
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("text-run evidence repeats a rule ID")
        rule_id_set = set(rule_ids)
        if any(not set(run.rule_ids).issubset(rule_id_set) for run in self.runs):
            raise ValueError("text-run evidence has a dangling rule")
        if len(self.runs) > MAX_RUNS_PER_DOCUMENT:
            raise ValueError("text-run evidence exceeds the document run limit")
        if len(self.rules) > MAX_RULES_PER_DOCUMENT:
            raise ValueError("text-run evidence exceeds the document rule limit")
        if self.usable:
            if self.page_count > 100:
                raise ValueError("usable evidence exceeds the page limit")
            if (
                len(self.pages) != self.page_count
                or [page.page_index for page in self.pages]
                != list(range(1, self.page_count + 1))
                or self.candidate_rule_count != len(self.rules)
            ):
                raise ValueError("text-run evidence page inventory is invalid")
            pages_by_index = {page.page_index: page for page in self.pages}
            runs_by_page: dict[int, list[str]] = defaultdict(list)
            rules_by_page: dict[int, list[str]] = defaultdict(list)
            used_source_indexes: set[int] = set()
            for run in self.runs:
                page = pages_by_index.get(run.page_index)
                if page is None:
                    raise ValueError(
                        "text-run evidence has a run on an undeclared page"
                    )
                if (
                    run.bbox.x < 0
                    or run.bbox.y < 0
                    or run.bbox.x + run.bbox.width > page.page_width + 1e-6
                    or run.bbox.y + run.bbox.height > page.page_height + 1e-6
                ):
                    raise ValueError(
                        "text-run evidence has an out-of-page run bbox"
                    )
                run_source_indexes = set(run.source_character_indexes)
                if (
                    any(
                        index >= self.character_count
                        for index in run.source_character_indexes
                    )
                    or used_source_indexes.intersection(run_source_indexes)
                ):
                    raise ValueError(
                        "text-run evidence has invalid source-character custody"
                    )
                used_source_indexes.update(run_source_indexes)
                runs_by_page[run.page_index].append(run.id)
            for rule in self.rules:
                page = pages_by_index.get(rule.page_index)
                if page is None:
                    raise ValueError(
                        "text-run evidence has a rule on an undeclared page"
                    )
                if (
                    rule.bbox.x < 0
                    or rule.bbox.y < 0
                    or rule.bbox.x + rule.bbox.width > page.page_width + 1e-6
                    or rule.bbox.y + rule.bbox.height
                    > page.page_height + 1e-6
                ):
                    raise ValueError(
                        "text-run evidence has an out-of-page rule bbox"
                    )
                rules_by_page[rule.page_index].append(rule.id)
            for page in self.pages:
                if (
                    len(runs_by_page[page.page_index]) > MAX_RUNS_PER_PAGE
                    or len(rules_by_page[page.page_index]) > MAX_RULES_PER_PAGE
                ):
                    raise ValueError(
                        "text-run evidence exceeds a per-page record limit"
                    )
                if (
                    tuple(runs_by_page[page.page_index]) != page.run_ids
                    or tuple(rules_by_page[page.page_index]) != page.rule_ids
                ):
                    raise ValueError(
                        "text-run evidence page membership is invalid"
                    )

            rules_by_id = {rule.id: rule for rule in self.rules}
            rule_use_counts: dict[str, int] = defaultdict(int)
            for run in self.runs:
                expected_rule_ids = tuple(
                    sorted(
                        run.rule_ids,
                        key=lambda rule_id: (
                            rules_by_id[rule_id].bbox.y,
                            rules_by_id[rule_id].bbox.x,
                            rules_by_id[rule_id].bbox.width,
                            rules_by_id[rule_id].bbox.height,
                            rule_id,
                        ),
                    )
                )
                if run.rule_ids != expected_rule_ids:
                    raise ValueError(
                        "source run rule IDs are out of canonical bbox order"
                    )
                for rule_id in run.rule_ids:
                    rule = rules_by_id[rule_id]
                    if rule.page_index != run.page_index:
                        raise ValueError(
                            "text-run evidence has a cross-page rule link"
                        )
                    if not _colors_match(run.color, rule.color):
                        raise ValueError(
                            "text-run evidence has incompatible linked colors"
                        )
                    rule_use_counts[rule_id] += 1
                    if rule_use_counts[rule_id] > MAX_RUNS_PER_RULE:
                        raise ValueError(
                            "text-run evidence exceeds the per-rule run limit"
                        )

            groups: dict[str, list[SourceRunEvidence]] = defaultdict(list)
            for run in self.runs:
                if run.change_group_id is not None:
                    groups[run.change_group_id].append(run)
            for group_id, group_runs in groups.items():
                first = group_runs[0]
                semantic_key = (
                    first.page_index,
                    first.line_index,
                    first.change_state,
                    first.decorations,
                    first.placeholder,
                    first.semantic_derivation,
                )
                prior_source_index: int | None = None
                for run in group_runs:
                    if (
                        (
                            run.page_index,
                            run.line_index,
                            run.change_state,
                            run.decorations,
                            run.placeholder,
                            run.semantic_derivation,
                        )
                        != semantic_key
                    ):
                        raise ValueError(
                            f"source change group {group_id} is incoherent"
                        )
                    if (
                        prior_source_index is not None
                        and run.source_character_indexes[0]
                        != prior_source_index + 1
                    ):
                        raise ValueError(
                            f"source change group {group_id} is not adjacent"
                        )
                    prior_source_index = run.source_character_indexes[-1]
        elif self.pages or self.runs or self.rules:
            raise ValueError("unusable text-run evidence must be empty")
        if self.usable:
            page_payload_bytes = sum(
                len(
                    page.model_dump_json(exclude_none=True).encode("utf-8")
                )
                for page in self.pages
            )
            run_payload_bytes = sum(
                len(
                    run.model_dump_json(exclude_none=True).encode("utf-8")
                )
                for run in self.runs
            )
            rule_payload_bytes = sum(
                len(
                    rule.model_dump_json(exclude_none=True).encode("utf-8")
                )
                for rule in self.rules
            )
            if (
                _estimated_report_size(
                    source_sha256=self.source_sha256,
                    page_count=self.page_count,
                    character_count=self.character_count,
                    candidate_rule_count=self.candidate_rule_count,
                    page_payload_bytes=page_payload_bytes,
                    page_item_count=len(self.pages),
                    run_payload_bytes=run_payload_bytes,
                    run_item_count=len(self.runs),
                    rule_payload_bytes=rule_payload_bytes,
                    rule_item_count=len(self.rules),
                )
                > MAX_REPORT_BYTES
            ):
                raise ValueError("text-run evidence exceeds its byte limit")
        return self


class _Refusal(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DocumentRefusal(_Refusal):
    """A source-wide refusal that cannot be isolated to one physical page."""


@dataclass(frozen=True, slots=True)
class _Glyph:
    source_index: int
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    baseline: float
    font_name: str
    font_size: float
    bold: bool
    italic: bool
    color: SourceColor

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0


@dataclass(slots=True)
class _OnlineMedian:
    lower: list[float] = field(default_factory=list)
    upper: list[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        if not self.lower or value <= -self.lower[0]:
            heapq.heappush(self.lower, -value)
        else:
            heapq.heappush(self.upper, value)
        if len(self.lower) > len(self.upper) + 1:
            heapq.heappush(self.upper, -heapq.heappop(self.lower))
        elif len(self.upper) > len(self.lower):
            heapq.heappush(self.lower, -heapq.heappop(self.upper))

    @property
    def value(self) -> float:
        if len(self.lower) == len(self.upper):
            return (-self.lower[0] + self.upper[0]) / 2.0
        return -self.lower[0]


@dataclass(slots=True)
class _IntegerNode:
    key: int
    height: int = 1
    left: "_IntegerNode | None" = None
    right: "_IntegerNode | None" = None


def _node_height(node: _IntegerNode | None) -> int:
    return node.height if node is not None else 0


def _refresh_node(node: _IntegerNode) -> None:
    node.height = 1 + max(
        _node_height(node.left),
        _node_height(node.right),
    )


def _rotate_integer_left(node: _IntegerNode) -> _IntegerNode:
    replacement = node.right
    if replacement is None:
        return node
    node.right = replacement.left
    replacement.left = node
    _refresh_node(node)
    _refresh_node(replacement)
    return replacement


def _rotate_integer_right(node: _IntegerNode) -> _IntegerNode:
    replacement = node.left
    if replacement is None:
        return node
    node.left = replacement.right
    replacement.right = node
    _refresh_node(node)
    _refresh_node(replacement)
    return replacement


def _balance_integer_node(node: _IntegerNode) -> _IntegerNode:
    _refresh_node(node)
    balance = _node_height(node.left) - _node_height(node.right)
    if balance > 1:
        if (
            node.left is not None
            and _node_height(node.left.left)
            < _node_height(node.left.right)
        ):
            node.left = _rotate_integer_left(node.left)
        return _rotate_integer_right(node)
    if balance < -1:
        if (
            node.right is not None
            and _node_height(node.right.right)
            < _node_height(node.right.left)
        ):
            node.right = _rotate_integer_right(node.right)
        return _rotate_integer_left(node)
    return node


def _insert_integer(
    node: _IntegerNode | None,
    key: int,
) -> _IntegerNode:
    if node is None:
        return _IntegerNode(key=key)
    if key < node.key:
        node.left = _insert_integer(node.left, key)
    elif key > node.key:
        node.right = _insert_integer(node.right, key)
    return _balance_integer_node(node)


def _delete_integer(
    node: _IntegerNode | None,
    key: int,
) -> _IntegerNode | None:
    if node is None:
        return None
    if key < node.key:
        node.left = _delete_integer(node.left, key)
    elif key > node.key:
        node.right = _delete_integer(node.right, key)
    elif node.left is None:
        return node.right
    elif node.right is None:
        return node.left
    else:
        successor = node.right
        while successor.left is not None:
            successor = successor.left
        node.key = successor.key
        node.right = _delete_integer(node.right, successor.key)
    return _balance_integer_node(node)


@dataclass(slots=True)
class _OrderedIntegers:
    root: _IntegerNode | None = None

    def add(self, key: int) -> None:
        self.root = _insert_integer(self.root, key)

    def discard(self, key: int) -> None:
        self.root = _delete_integer(self.root, key)

    def between(
        self,
        minimum: int,
        maximum: int,
        *,
        limit: int,
    ) -> list[int]:
        output: list[int] = []

        def visit(node: _IntegerNode | None) -> None:
            if node is None or len(output) > limit:
                return
            if node.key > minimum:
                visit(node.left)
            if minimum <= node.key <= maximum:
                output.append(node.key)
            if node.key < maximum:
                visit(node.right)

        visit(self.root)
        return output


@dataclass(slots=True)
class _Line:
    first_source_index: int
    glyphs: list[_Glyph]
    baseline_median: _OnlineMedian = field(default_factory=_OnlineMedian)
    font_size_median: _OnlineMedian = field(default_factory=_OnlineMedian)
    minimum_top: float = field(init=False)
    maximum_bottom: float = field(init=False)

    def __post_init__(self) -> None:
        self.minimum_top = min(glyph.top for glyph in self.glyphs)
        self.maximum_bottom = max(glyph.bottom for glyph in self.glyphs)
        for glyph in self.glyphs:
            self.baseline_median.add(glyph.baseline)
            self.font_size_median.add(glyph.font_size)

    def add(self, glyph: _Glyph) -> None:
        self.glyphs.append(glyph)
        self.baseline_median.add(glyph.baseline)
        self.font_size_median.add(glyph.font_size)
        self.minimum_top = min(self.minimum_top, glyph.top)
        self.maximum_bottom = max(self.maximum_bottom, glyph.bottom)

    @property
    def median_baseline(self) -> float:
        return self.baseline_median.value

    @property
    def median_font_size(self) -> float:
        return self.font_size_median.value

    def vertical_overlap(self, glyph: _Glyph) -> float:
        overlap = max(
            0.0,
            min(glyph.bottom, self.maximum_bottom)
            - max(glyph.top, self.minimum_top),
        )
        smaller = min(
            glyph.height,
            self.maximum_bottom - self.minimum_top,
        )
        return overlap / smaller if smaller > 0 else 0.0


@dataclass(frozen=True, slots=True)
class _RuleMatch:
    rule: SourceRuleEvidence
    line_index: int
    glyphs: tuple[_Glyph, ...]
    decoration: Literal["strikethrough", "underline"]


@dataclass(slots=True)
class _IntervalNode:
    lower: float
    upper: float
    value: int
    maximum_upper: float
    left: "_IntervalNode | None" = None
    right: "_IntervalNode | None" = None


def _build_interval_index(
    intervals: Sequence[tuple[float, float, int]],
) -> _IntervalNode | None:
    ordered = sorted(intervals, key=lambda value: (value[0], value[1], value[2]))

    def build(start: int, end: int) -> _IntervalNode | None:
        if start >= end:
            return None
        middle = (start + end) // 2
        lower, upper, value = ordered[middle]
        left = build(start, middle)
        right = build(middle + 1, end)
        return _IntervalNode(
            lower=lower,
            upper=upper,
            value=value,
            maximum_upper=max(
                upper,
                left.maximum_upper if left is not None else upper,
                right.maximum_upper if right is not None else upper,
            ),
            left=left,
            right=right,
        )

    return build(0, len(ordered))


def _query_interval_index(
    root: _IntervalNode | None,
    point: float,
    *,
    limit: int,
) -> list[int]:
    output: list[int] = []

    def visit(node: _IntervalNode | None) -> None:
        if node is None or len(output) > limit:
            return
        if (
            node.left is not None
            and node.left.maximum_upper >= point
        ):
            visit(node.left)
        if node.lower <= point <= node.upper:
            output.append(node.value)
        if node.lower <= point:
            visit(node.right)

    visit(root)
    return output


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        _canonical_json(parts).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:20]}"


def _check_deadline(started: float) -> None:
    if time.perf_counter() - started > MAX_EXTRACTION_SECONDS:
        raise _DocumentRefusal("text_run_source_limit")


def _normalize_color(value: Any) -> SourceColor:
    if isinstance(value, bool) or value is None:
        return SourceColor(space="unknown")
    if isinstance(value, (int, float)):
        component = float(value)
        if math.isfinite(component) and 0 <= component <= 1:
            return SourceColor(
                space="gray",
                components=(component,),
                raw_value=component,
            )
        return SourceColor(space="unknown")
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        try:
            components = tuple(float(component) for component in value)
        except (TypeError, ValueError):
            return SourceColor(space="unknown")
        if not all(
            math.isfinite(component) and 0 <= component <= 1
            for component in components
        ):
            return SourceColor(space="unknown")
        space = {1: "gray", 3: "rgb", 4: "cmyk"}.get(len(components))
        if space is None:
            return SourceColor(space="unknown")
        return SourceColor(
            space=space,
            components=components,
            raw_value=components,
        )
    return SourceColor(space="unknown")


def _colors_match(left: SourceColor, right: SourceColor) -> bool:
    return (
        left.space != "unknown"
        and left.space == right.space
        and len(left.components) == len(right.components)
        and all(
            abs(a - b) <= MAX_COLOR_COMPONENT_DELTA
            for a, b in zip(left.components, right.components, strict=True)
        )
    )


def _is_black(color: SourceColor) -> bool:
    if color.space in {"gray", "rgb"}:
        return all(
            abs(component) <= MAX_COLOR_COMPONENT_DELTA
            for component in color.components
        )
    if color.space == "cmyk":
        cyan, magenta, yellow, black = color.components
        return (
            abs(cyan) <= MAX_COLOR_COMPONENT_DELTA
            and abs(magenta) <= MAX_COLOR_COMPONENT_DELTA
            and abs(yellow) <= MAX_COLOR_COMPONENT_DELTA
            and abs(1.0 - black) <= MAX_COLOR_COMPONENT_DELTA
        )
    return False


def _font_flags(font_name: str) -> tuple[bool, bool]:
    normalized = font_name.casefold()
    return (
        any(token in normalized for token in _BOLD_TOKENS),
        any(token in normalized for token in _ITALIC_TOKENS),
    )


def _bbox_for_glyphs(glyphs: Sequence[_Glyph]) -> SourceBBox:
    return SourceBBox(
        x=min(glyph.x0 for glyph in glyphs),
        y=min(glyph.top for glyph in glyphs),
        width=(
            max(glyph.x1 for glyph in glyphs)
            - min(glyph.x0 for glyph in glyphs)
        ),
        height=(
            max(glyph.bottom for glyph in glyphs)
            - min(glyph.top for glyph in glyphs)
        ),
    )


def _cluster_lines(
    glyphs: Sequence[_Glyph],
    *,
    started: float,
) -> list[list[_Glyph]]:
    lines: list[_Line] = []
    buckets: dict[int, set[int]] = defaultdict(set)
    bucket_keys = _OrderedIntegers()
    line_versions: list[int] = []
    font_size_max_heap: list[tuple[float, int, int]] = []

    def add_bucket(bucket: int, line_index: int) -> None:
        if bucket not in buckets or not buckets[bucket]:
            bucket_keys.add(bucket)
        buckets[bucket].add(line_index)

    def remove_bucket(bucket: int, line_index: int) -> None:
        buckets[bucket].discard(line_index)
        if not buckets[bucket]:
            del buckets[bucket]
            bucket_keys.discard(bucket)

    def maximum_line_font_size() -> float:
        while font_size_max_heap:
            negative_size, line_index, version = font_size_max_heap[0]
            if (
                line_index < len(line_versions)
                and line_versions[line_index] == version
                and math.isclose(
                    -negative_size,
                    lines[line_index].median_font_size,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                return -negative_size
            heapq.heappop(font_size_max_heap)
        return 0.0

    for glyph_index, glyph in enumerate(glyphs):
        if glyph_index % 2048 == 0:
            _check_deadline(started)
        maximum_tolerance = max(
            0.75,
            0.10 * max(glyph.font_size, maximum_line_font_size()),
        )
        minimum_bucket = math.floor(
            (glyph.baseline - maximum_tolerance) / 2.0
        )
        maximum_bucket = math.floor(
            (glyph.baseline + maximum_tolerance) / 2.0
        )
        candidate_indexes: set[int] = set()
        eligible_buckets = bucket_keys.between(
            minimum_bucket,
            maximum_bucket,
            limit=8,
        )
        if len(eligible_buckets) > 8:
            raise _Refusal("text_run_source_invalid")
        for bucket in eligible_buckets:
            for line_index in buckets[bucket]:
                candidate_indexes.add(line_index)
                if len(candidate_indexes) > 8:
                    raise _Refusal("text_run_source_invalid")
        qualified: list[tuple[float, float, int, int]] = []
        for line_index in candidate_indexes:
            line = lines[line_index]
            tolerance = max(
                0.75,
                0.10 * max(glyph.font_size, line.median_font_size),
            )
            distance = abs(glyph.baseline - line.median_baseline)
            overlap = line.vertical_overlap(glyph)
            if distance <= tolerance and overlap >= 0.50:
                qualified.append(
                    (
                        distance,
                        -overlap,
                        line.first_source_index,
                        line_index,
                    )
                )
        if qualified:
            _distance, _overlap, _first, line_index = min(qualified)
            line = lines[line_index]
            old_bucket = math.floor(line.median_baseline / 2.0)
            line.add(glyph)
            line_versions[line_index] += 1
            heapq.heappush(
                font_size_max_heap,
                (
                    -line.median_font_size,
                    line_index,
                    line_versions[line_index],
                ),
            )
            new_bucket = math.floor(line.median_baseline / 2.0)
            if old_bucket != new_bucket:
                remove_bucket(old_bucket, line_index)
                add_bucket(new_bucket, line_index)
        else:
            line_index = len(lines)
            lines.append(
                _Line(
                    first_source_index=glyph.source_index,
                    glyphs=[glyph],
                )
            )
            line_versions.append(0)
            heapq.heappush(
                font_size_max_heap,
                (-glyph.font_size, line_index, 0),
            )
            add_bucket(math.floor(glyph.baseline / 2.0), line_index)
    ordered = sorted(
        lines,
        key=lambda line: (
            min(glyph.top for glyph in line.glyphs),
            min(glyph.x0 for glyph in line.glyphs),
            line.first_source_index,
        ),
    )
    return [
        sorted(
            line.glyphs,
            key=lambda glyph: (glyph.x0, glyph.source_index),
        )
        for line in ordered
    ]


def _style_key(glyph: _Glyph) -> tuple[Any, ...]:
    return (
        glyph.font_name,
        glyph.bold,
        glyph.italic,
        glyph.color.space,
        glyph.color.components,
    )


def _split_style_runs(glyphs: Sequence[_Glyph]) -> list[list[_Glyph]]:
    output: list[list[_Glyph]] = []
    active: list[_Glyph] = []
    active_bytes = 0
    for glyph in glyphs:
        glyph_bytes = len(glyph.text.encode("utf-8"))
        split = False
        if active:
            previous = active[-1]
            gap = glyph.x0 - previous.x1
            split = (
                _style_key(glyph) != _style_key(previous)
                or abs(glyph.font_size - previous.font_size) > 0.01
                or glyph.source_index != previous.source_index + 1
                or gap > max(2.0, 0.5 * glyph.font_size)
                or gap < -1.0
                or active_bytes + glyph_bytes > MAX_TEXT_BYTES_PER_RUN
            )
        if split:
            output.append(active)
            active = []
            active_bytes = 0
        active.append(glyph)
        active_bytes += glyph_bytes
    if active:
        output.append(active)
    return output


def _trim_boundary_whitespace(
    glyphs: Sequence[_Glyph],
    *,
    rule: SourceRuleEvidence | None = None,
) -> tuple[_Glyph, ...]:
    def covered(glyph: _Glyph) -> bool:
        if rule is None:
            return False
        overlap = max(
            0.0,
            min(glyph.x1, rule.bbox.x + rule.bbox.width)
            - max(glyph.x0, rule.bbox.x),
        )
        return glyph.width > 0 and overlap / glyph.width >= MIN_RUN_COVERAGE

    start = 0
    end = len(glyphs)
    while (
        start < end
        and glyphs[start].text.isspace()
        and not covered(glyphs[start])
    ):
        start += 1
    while (
        end > start
        and glyphs[end - 1].text.isspace()
        and not covered(glyphs[end - 1])
    ):
        end -= 1
    return tuple(glyphs[start:end])


def _horizontal_overlap(
    bbox: SourceBBox,
    rule: SourceRuleEvidence,
) -> float:
    return max(
        0.0,
        min(bbox.x + bbox.width, rule.bbox.x + rule.bbox.width)
        - max(bbox.x, rule.bbox.x),
    )


def _rule_decoration(
    bbox: SourceBBox,
    rule: SourceRuleEvidence,
) -> Literal["strikethrough", "underline"] | None:
    # Decimal-from-shortest-float preserves a source coordinate that lies on
    # a frozen inclusive endpoint without widening the band to the next
    # representable value outside it.
    ratio = (
        (
            Decimal(str(rule.bbox.y))
            + Decimal(str(rule.bbox.height)) / Decimal(2)
        )
        - Decimal(str(bbox.y))
    ) / Decimal(str(bbox.height))
    if (
        Decimal("0.35") - _BAND_RATIO_EPSILON
        <= ratio
        <= Decimal("0.70") + _BAND_RATIO_EPSILON
    ):
        return "strikethrough"
    if (
        Decimal("0.75") - _BAND_RATIO_EPSILON
        <= ratio
        <= Decimal("1.10") + _BAND_RATIO_EPSILON
    ):
        return "underline"
    return None


def _candidate_rule_match(
    rule: SourceRuleEvidence,
    line_index: int,
    line: Sequence[_Glyph],
    candidate_positions: Sequence[int],
) -> tuple[_RuleMatch | None, bool]:
    selected_positions = [
        index for index in candidate_positions
        if 0 <= index < len(line)
        for glyph in (line[index],)
        if _colors_match(glyph.color, rule.color)
        and (
            rule.bbox.x - RULE_GLYPH_CENTER_MARGIN
            <= glyph.center_x
            <= rule.bbox.x + rule.bbox.width + RULE_GLYPH_CENTER_MARGIN
        )
    ]
    if not selected_positions:
        return None, False
    islands: list[list[_Glyph]] = []
    active: list[_Glyph] = []
    prior_position: int | None = None
    for position in selected_positions:
        glyph = line[position]
        if active and prior_position is not None:
            previous = active[-1]
            gap = glyph.x0 - previous.x1
            if (
                position != prior_position + 1
                or gap > max(2.0, 0.5 * glyph.font_size)
                or gap < -1.0
            ):
                trimmed = _trim_boundary_whitespace(active, rule=rule)
                if trimmed:
                    islands.append(list(trimmed))
                active = []
        active.append(glyph)
        prior_position = position
    trimmed = _trim_boundary_whitespace(active, rule=rule)
    if trimmed:
        islands.append(list(trimmed))
    islands = [
        island
        for island in islands
        if island and any(not glyph.text.isspace() for glyph in island)
    ]
    if len(islands) != 1:
        return None, len(islands) > 1
    glyphs = tuple(islands[0])
    bbox = _bbox_for_glyphs(glyphs)
    overlap = _horizontal_overlap(bbox, rule)
    if (
        overlap < MIN_HORIZONTAL_OVERLAP
        or overlap / bbox.width < MIN_RUN_COVERAGE
    ):
        return None, False
    overhang = rule.bbox.width - overlap
    if overhang > max(4.0, 0.20 * bbox.width):
        return None, False
    decoration = _rule_decoration(bbox, rule)
    if decoration is None:
        return None, False
    return (
        _RuleMatch(
            rule=rule,
            line_index=line_index,
            glyphs=glyphs,
            decoration=decoration,
        ),
        False,
    )


def _extract_glyphs(
    page: Any,
    *,
    page_index: int,
    character_offset: int,
    started: float,
    raw_characters: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[_Glyph], int]:
    rotation = int(getattr(page, "rotation", 0) or 0) % 360
    if rotation != 0:
        raise _Refusal("text_run_transform_unavailable")
    width = float(page.width)
    height = float(page.height)
    if raw_characters is None:
        raw_characters = page.chars
    if len(raw_characters) > MAX_SOURCE_CHARACTERS - character_offset:
        raise _Refusal("text_run_source_limit")
    glyphs: list[_Glyph] = []
    for local_index, raw in enumerate(raw_characters):
        if local_index % 2048 == 0:
            _check_deadline(started)
        source_index = character_offset + local_index
        try:
            text = str(raw.get("text") or "")
            x0 = float(raw["x0"])
            x1 = float(raw["x1"])
            top = float(raw["top"])
            bottom = float(raw["bottom"])
            font_size = float(raw["size"])
            font_name = str(raw.get("fontname") or "")
        except (KeyError, TypeError, ValueError):
            raise _Refusal("text_run_source_invalid") from None
        matrix = raw.get("matrix")
        if (
            not bool(raw.get("upright", True))
            or not isinstance(matrix, Sequence)
            or isinstance(matrix, (str, bytes, bytearray))
            or len(matrix) != 6
        ):
            raise _Refusal("text_run_transform_unavailable")
        try:
            a, b, c, d, _e, f = (float(value) for value in matrix)
        except (TypeError, ValueError):
            raise _Refusal("text_run_transform_unavailable") from None
        baseline = height - f
        if (
            not all(math.isfinite(value) for value in (a, b, c, d, baseline))
            or abs(b) > 1e-6
            or abs(c) > 1e-6
            or a <= 0
            or d <= 0
        ):
            raise _Refusal("text_run_transform_unavailable")
        values = (x0, x1, top, bottom, font_size)
        if (
            not text
            or not all(math.isfinite(value) for value in values)
            or x1 <= x0
            or bottom <= top
            or font_size <= 0
            or x0 < 0
            or top < 0
            or x1 > width + 1e-6
            or bottom > height + 1e-6
            or len(font_name.encode("utf-8")) > MAX_FONT_NAME_BYTES
        ):
            raise _Refusal("text_run_source_invalid")
        bold, italic = _font_flags(font_name)
        glyphs.append(
            _Glyph(
                source_index=source_index,
                text=text,
                x0=x0,
                top=top,
                x1=x1,
                bottom=bottom,
                baseline=baseline,
                font_name=font_name,
                font_size=font_size,
                bold=bold,
                italic=italic,
                color=_normalize_color(raw.get("non_stroking_color")),
            )
        )
    return glyphs, character_offset + len(raw_characters)


def _extract_rules(
    page: Any,
    *,
    page_index: int,
    source_sha256: str,
    started: float,
    remaining_document_rules: int,
) -> list[SourceRuleEvidence]:
    output: list[SourceRuleEvidence] = []
    for kind, objects in (("rect", page.rects), ("line", page.lines)):
        for source_index, raw in enumerate(objects):
            if source_index % 256 == 0:
                _check_deadline(started)
            try:
                x0 = float(raw["x0"])
                x1 = float(raw["x1"])
                top = float(raw["top"])
                bottom = float(raw["bottom"])
            except (KeyError, TypeError, ValueError):
                continue
            if kind == "rect" and not bool(raw.get("fill")):
                continue
            if kind == "line" and raw.get("stroke") is False:
                continue
            width = x1 - x0
            geometric_height = bottom - top
            if kind == "line":
                try:
                    line_width = float(raw.get("linewidth") or 0.0)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(line_width) or line_width < 0:
                    continue
                thickness = max(geometric_height, line_width)
                center_y = (top + bottom) / 2.0
                top = center_y - thickness / 2.0
                bottom = center_y + thickness / 2.0
            else:
                thickness = geometric_height
            if (
                not all(
                    math.isfinite(value)
                    for value in (x0, x1, top, bottom)
                )
                or width < MIN_RULE_WIDTH
                or thickness <= 0
                or thickness > MAX_RULE_THICKNESS
                or width / thickness < MIN_RULE_ASPECT
                or x0 < 0
                or top < 0
                or x1 > float(page.width) + 1e-6
                or bottom > float(page.height) + 1e-6
            ):
                continue
            if (
                len(output) >= MAX_RULES_PER_PAGE
                or len(output) >= remaining_document_rules
            ):
                raise _Refusal("text_run_rule_limit")
            color_value = (
                raw.get("non_stroking_color")
                if kind == "rect"
                else raw.get("stroking_color")
            )
            color = _normalize_color(color_value)
            output.append(
                SourceRuleEvidence(
                    id=_stable_id(
                        "trule",
                        source_sha256,
                        page_index,
                        kind,
                        source_index,
                        x0,
                        top,
                        x1,
                        bottom,
                        color.model_dump(mode="json"),
                    ),
                    page_index=page_index,
                    source_object_kind=kind,
                    source_object_index=source_index,
                    bbox=SourceBBox(
                        x=x0,
                        y=top,
                        width=width,
                        height=thickness,
                    ),
                    color=color,
                    width=width,
                    thickness=thickness,
                )
            )
    return sorted(
        output,
        key=lambda rule: (
            rule.page_index,
            rule.bbox.y,
            rule.bbox.x,
            rule.source_object_kind,
            rule.source_object_index,
            rule.id,
        ),
    )


def _make_source_run(
    *,
    source_sha256: str,
    page_index: int,
    line_index: int,
    glyphs: Sequence[_Glyph],
    change_group_id: str | None,
    change_state: Literal[
        "deleted", "inserted", "replacement", "unknown", "unchanged"
    ],
    decorations: Sequence[Literal["strikethrough", "underline"]],
    placeholder: bool,
    rule_ids: Sequence[str],
    semantic_derivation: Literal[
        "source_style",
        "same_color_midline_rule",
        "same_color_underline_rule",
        "same_color_underlined_placeholder",
        "native_tracked_change",
    ],
) -> SourceRunEvidence:
    text = "".join(glyph.text for glyph in glyphs)
    first = glyphs[0]
    bbox = _bbox_for_glyphs(glyphs)
    indexes = tuple(glyph.source_index for glyph in glyphs)
    return SourceRunEvidence(
        id=_stable_id(
            "trun",
            source_sha256,
            page_index,
            line_index,
            indexes,
            change_group_id,
            tuple(rule_ids),
        ),
        page_index=page_index,
        line_index=line_index,
        text=text,
        bbox=bbox,
        font_name=first.font_name,
        font_size=first.font_size,
        bold=first.bold,
        italic=first.italic,
        color=first.color,
        source_character_indexes=indexes,
        change_group_id=change_group_id,
        change_state=change_state,
        decorations=tuple(decorations),
        placeholder=placeholder,
        rule_ids=tuple(rule_ids),
        semantic_derivation=semantic_derivation,
    )


def _semantic_runs_for_page(
    *,
    source_sha256: str,
    page_index: int,
    lines: Sequence[Sequence[_Glyph]],
    rules: Sequence[SourceRuleEvidence],
    started: float,
) -> tuple[list[SourceRunEvidence], bool]:
    matches_by_rule: dict[str, list[_RuleMatch]] = defaultdict(list)
    candidate_count = 0
    glyph_check_count = 0
    rule_ambiguous = False
    horizontal_indexes: list[
        tuple[list[float], list[int]]
    ] = []
    vertical_intervals: list[tuple[float, float, int]] = []
    for line_index, line in enumerate(lines):
        if line_index % 256 == 0:
            _check_deadline(started)
        ordered_centers = sorted(
            (glyph.center_x, position)
            for position, glyph in enumerate(line)
        )
        horizontal_indexes.append(
            (
                [center for center, _position in ordered_centers],
                [position for _center, position in ordered_centers],
            )
        )
        bbox = _bbox_for_glyphs(line)
        vertical_intervals.append(
            (
                bbox.y,
                bbox.y + 1.10 * bbox.height + 1e-9,
                line_index,
            )
        )
    vertical_index = _build_interval_index(vertical_intervals)
    for rule_index, rule in enumerate(rules):
        if rule_index % 128 == 0:
            _check_deadline(started)
        left = rule.bbox.x - RULE_GLYPH_CENTER_MARGIN
        right = (
            rule.bbox.x
            + rule.bbox.width
            + RULE_GLYPH_CENTER_MARGIN
        )
        rule_center_y = rule.bbox.y + rule.bbox.height / 2.0
        nearby_lines = _query_interval_index(
            vertical_index,
            rule_center_y,
            limit=max(
                0,
                MAX_ASSOCIATIONS_PER_PAGE - candidate_count,
            ),
        )
        if (
            len(nearby_lines)
            > MAX_ASSOCIATIONS_PER_PAGE - candidate_count
        ):
            raise _Refusal("text_run_rule_limit")
        for line_index in sorted(nearby_lines):
            line = lines[line_index]
            candidate_count += 1
            if candidate_count % 2048 == 0:
                _check_deadline(started)
            if candidate_count > MAX_ASSOCIATIONS_PER_PAGE:
                raise _Refusal("text_run_rule_limit")
            centers, positions = horizontal_indexes[line_index]
            first = bisect_left(centers, left)
            last = bisect_right(centers, right)
            glyph_check_count += last - first
            if glyph_check_count > MAX_ASSOCIATIONS_PER_PAGE:
                raise _Refusal("text_run_rule_limit")
            match, ambiguous = _candidate_rule_match(
                rule,
                line_index,
                line,
                sorted(positions[first:last]),
            )
            rule_ambiguous = rule_ambiguous or ambiguous
            if match is not None:
                matches_by_rule[rule.id].append(match)

    accepted: list[_RuleMatch] = []
    for rule in rules:
        candidates = matches_by_rule.get(rule.id, ())
        if len(candidates) != 1:
            rule_ambiguous = rule_ambiguous or len(candidates) > 1
            continue
        accepted.append(candidates[0])

    group_map: dict[
        tuple[int, tuple[int, ...]],
        dict[str, Any],
    ] = {}
    for match in accepted:
        key = (
            match.line_index,
            tuple(glyph.source_index for glyph in match.glyphs),
        )
        entry = group_map.setdefault(
            key,
            {
                "line_index": match.line_index,
                "glyphs": match.glyphs,
                "decorations": set(),
                "rules": [],
            },
        )
        entry["decorations"].add(match.decoration)
        entry["rules"].append(match.rule)

    groups = sorted(
        group_map.values(),
        key=lambda entry: (
            entry["line_index"],
            entry["glyphs"][0].x0,
            entry["glyphs"][0].source_index,
        ),
    )
    logical_ids: dict[int, str] = {}
    prior_index: int | None = None
    logical_members: list[int] = []

    def commit_logical() -> None:
        if not logical_members:
            return
        first_entry = groups[logical_members[0]]
        last_entry = groups[logical_members[-1]]
        logical_id = _stable_id(
            "tgroup",
            source_sha256,
            page_index,
            first_entry["line_index"],
            first_entry["glyphs"][0].source_index,
            last_entry["glyphs"][-1].source_index,
        )
        for member in logical_members:
            logical_ids[member] = logical_id

    for index, entry in enumerate(groups):
        if prior_index is None:
            logical_members = [index]
            prior_index = index
            continue
        prior = groups[prior_index]
        gap = entry["glyphs"][0].x0 - prior["glyphs"][-1].x1
        same_semantics = (
            entry["line_index"] == prior["line_index"]
            and entry["glyphs"][0].source_index
            == prior["glyphs"][-1].source_index + 1
            and entry["decorations"] == prior["decorations"]
            and _colors_match(
                entry["glyphs"][0].color,
                prior["glyphs"][0].color,
            )
            and gap <= 2.0
            and gap >= -1.0
        )
        if same_semantics:
            logical_members.append(index)
        else:
            commit_logical()
            logical_members = [index]
        prior_index = index
    commit_logical()

    covered_indexes: set[int] = set()
    output: list[SourceRunEvidence] = []
    for index, entry in enumerate(groups):
        glyphs = tuple(entry["glyphs"])
        covered_indexes.update(glyph.source_index for glyph in glyphs)
        decorations = tuple(
            decoration
            for decoration in ("strikethrough", "underline")
            if decoration in entry["decorations"]
        )
        if len(decorations) != 1:
            rule_ambiguous = True
            continue
        rule_ids = tuple(
            rule.id
            for rule in sorted(
                entry["rules"],
                key=lambda rule: (
                    rule.bbox.y,
                    rule.bbox.x,
                    rule.bbox.width,
                    rule.bbox.height,
                    rule.id,
                ),
            )
        )
        if len(rule_ids) > MAX_RULES_PER_RUN:
            raise _Refusal("text_run_rule_limit")
        if decorations == ("strikethrough",):
            change_state = "deleted"
            placeholder = False
            derivation = "same_color_midline_rule"
        else:
            raw_text = "".join(glyph.text for glyph in glyphs)
            placeholder = (
                3 <= len(raw_text) <= 128
                and set(raw_text) == {"_"}
            )
            change_state = "unknown" if placeholder else "unchanged"
            derivation = (
                "same_color_underlined_placeholder"
                if placeholder
                else "same_color_underline_rule"
            )
        for styled in _split_style_runs(glyphs):
            trimmed = _trim_boundary_whitespace(
                styled,
                rule=entry["rules"][0],
            )
            if not trimmed or not any(
                not glyph.text.isspace() for glyph in trimmed
            ):
                continue
            output.append(
                _make_source_run(
                    source_sha256=source_sha256,
                    page_index=page_index,
                    line_index=entry["line_index"],
                    glyphs=trimmed,
                    change_group_id=logical_ids[index],
                    change_state=change_state,
                    decorations=decorations,
                    placeholder=placeholder,
                    rule_ids=rule_ids,
                    semantic_derivation=derivation,
                )
            )

    # Retain uncovered sparse style evidence.
    for line_index, line in enumerate(lines):
        for styled in _split_style_runs(line):
            active: list[_Glyph] = []
            segments: list[list[_Glyph]] = []
            for glyph in styled:
                if glyph.source_index in covered_indexes:
                    if active:
                        segments.append(active)
                        active = []
                else:
                    active.append(glyph)
            if active:
                segments.append(active)
            for segment in segments:
                trimmed = _trim_boundary_whitespace(segment)
                if (
                    not trimmed
                    or not any(not glyph.text.isspace() for glyph in trimmed)
                ):
                    continue
                first = trimmed[0]
                known_non_black = (
                    first.color.space != "unknown"
                    and not _is_black(first.color)
                )
                if not (first.bold or first.italic or known_non_black):
                    continue
                output.append(
                    _make_source_run(
                        source_sha256=source_sha256,
                        page_index=page_index,
                        line_index=line_index,
                        glyphs=trimmed,
                        change_group_id=None,
                        change_state="unknown" if known_non_black else "unchanged",
                        decorations=(),
                        placeholder=False,
                        rule_ids=(),
                        semantic_derivation="source_style",
                    )
                )

    output.sort(
        key=lambda run: (
            run.page_index,
            run.line_index,
            run.bbox.x,
            run.source_character_indexes,
            run.id,
        )
    )
    if len(output) > MAX_RUNS_PER_PAGE:
        raise _Refusal("text_run_source_limit")
    linked_counts: dict[str, int] = defaultdict(int)
    for run in output:
        for rule_id in run.rule_ids:
            linked_counts[rule_id] += 1
            if linked_counts[rule_id] > MAX_RUNS_PER_RULE:
                raise _Refusal("text_run_rule_limit")
    return output, rule_ambiguous


def _bounded_report_size(
    report: TextRunEvidence,
    *,
    started: float,
) -> None:
    # TextRunEvidence's strict validator already applies the conservative
    # incremental JSON-size bound. Avoid allocating the complete payload a
    # second time on the latency-sensitive extraction path.
    _ = report
    _check_deadline(started)


def _estimated_report_size(
    *,
    source_sha256: str,
    page_count: int,
    character_count: int,
    candidate_rule_count: int,
    page_payload_bytes: int,
    page_item_count: int,
    run_payload_bytes: int,
    run_item_count: int,
    rule_payload_bytes: int,
    rule_item_count: int,
) -> int:
    """Return an upper-bound JSON size without materializing the full report."""

    shell = TextRunEvidence.model_construct(
        schema_version=TEXT_RUN_EVIDENCE_SCHEMA_VERSION,
        policy_id=TEXT_RUN_POLICY_ID,
        extraction_policy_id=TEXT_RUN_EXTRACTION_POLICY_ID,
        association_policy_id=TEXT_RUN_ASSOCIATION_POLICY_ID,
        source_sha256=source_sha256,
        usable=True,
        refusal_code=None,
        page_count=page_count,
        character_count=character_count,
        candidate_rule_count=candidate_rule_count,
        pages=(),
        runs=(),
        rules=(),
        concerns=(),
        # This is longer than every permitted measured value below 60 seconds.
        elapsed_ms=60_000.0,
    )
    shell_size = len(
        shell.model_dump_json(exclude_none=True).encode("utf-8")
    )

    def populated_array_delta(payload_bytes: int, item_count: int) -> int:
        if item_count == 0:
            return 0
        return payload_bytes + item_count - 1

    return (
        shell_size
        + populated_array_delta(page_payload_bytes, page_item_count)
        + populated_array_delta(run_payload_bytes, run_item_count)
        + populated_array_delta(rule_payload_bytes, rule_item_count)
        # Python's bounded finite float representation can be longer than
        # the shell's elapsed value; reserve its maximum practical delta.
        + 32
    )


def _unusable_report(
    *,
    source_sha256: str,
    refusal_code: str,
    page_count: int,
    character_count: int,
    candidate_rule_count: int,
    started: float,
) -> TextRunEvidence:
    return TextRunEvidence(
        source_sha256=source_sha256,
        usable=False,
        refusal_code=refusal_code,
        page_count=min(max(page_count, 0), 101),
        character_count=min(
            max(character_count, 0),
            MAX_SOURCE_CHARACTERS,
        ),
        candidate_rule_count=min(
            max(candidate_rule_count, 0),
            MAX_RULES_PER_DOCUMENT,
        ),
        concerns=(
            {
                "code": refusal_code,
                "policy_id": TEXT_RUN_POLICY_ID,
            },
        ),
        elapsed_ms=min(
            max((time.perf_counter() - started) * 1000.0, 0.0),
            60_000.0,
        ),
    )


def extract_text_run_evidence(
    pdf_bytes: bytes,
    *,
    max_pages: int = 100,
) -> TextRunEvidence:
    """Extract bounded native glyph/style and vector-rule evidence."""

    started = time.perf_counter()
    source_sha256 = hashlib.sha256(b"").hexdigest()
    page_count = 0
    character_count = 0
    candidate_rule_count = 0
    try:
        if not isinstance(pdf_bytes, bytes):
            raise _Refusal("text_run_source_invalid")
        source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        if not pdf_bytes or len(pdf_bytes) > MAX_INPUT_BYTES:
            raise _Refusal("text_run_source_limit")
        if isinstance(max_pages, bool) or not 1 <= int(max_pages) <= 100:
            raise _Refusal("text_run_source_limit")
        import pdfplumber

        pages: list[SourceSemanticsPage] = []
        runs: list[SourceRunEvidence] = []
        rules: list[SourceRuleEvidence] = []
        page_json_bytes = 0
        run_json_bytes = 0
        rule_json_bytes = 0
        character_offset = 0

        def commit_page(
            page_record: SourceSemanticsPage,
            page_runs: Sequence[SourceRunEvidence] = (),
            page_rules: Sequence[SourceRuleEvidence] = (),
        ) -> None:
            nonlocal candidate_rule_count
            nonlocal page_json_bytes, run_json_bytes, rule_json_bytes
            candidate_total = candidate_rule_count + len(page_rules)
            added_page_bytes = len(
                page_record.model_dump_json(
                    exclude_none=True
                ).encode("utf-8")
            )
            added_run_bytes = sum(
                len(
                    run.model_dump_json(exclude_none=True).encode("utf-8")
                )
                for run in page_runs
            )
            added_rule_bytes = sum(
                len(
                    rule.model_dump_json(exclude_none=True).encode("utf-8")
                )
                for rule in page_rules
            )
            if (
                _estimated_report_size(
                    source_sha256=source_sha256,
                    page_count=page_count,
                    character_count=character_count,
                    candidate_rule_count=candidate_total,
                    page_payload_bytes=page_json_bytes + added_page_bytes,
                    page_item_count=len(pages) + 1,
                    run_payload_bytes=run_json_bytes + added_run_bytes,
                    run_item_count=len(runs) + len(page_runs),
                    rule_payload_bytes=rule_json_bytes + added_rule_bytes,
                    rule_item_count=len(rules) + len(page_rules),
                )
                > MAX_REPORT_BYTES
            ):
                raise _Refusal("text_run_source_limit")
            pages.append(page_record)
            runs.extend(page_runs)
            rules.extend(page_rules)
            page_json_bytes += added_page_bytes
            run_json_bytes += added_run_bytes
            rule_json_bytes += added_rule_bytes
            candidate_rule_count = candidate_total

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
            page_count = len(document.pages)
            if not 1 <= page_count <= int(max_pages):
                raise _Refusal("text_run_source_limit")
            for page_index, page in enumerate(document.pages, 1):
                _check_deadline(started)
                try:
                    page_width = float(page.width)
                    page_height = float(page.height)
                    if (
                        not math.isfinite(page_width)
                        or not math.isfinite(page_height)
                        or page_width <= 0
                        or page_height <= 0
                    ):
                        raise _DocumentRefusal("text_run_source_invalid")
                    raw_characters = page.chars
                    if (
                        len(raw_characters)
                        > MAX_SOURCE_CHARACTERS - character_offset
                    ):
                        raise _DocumentRefusal("text_run_source_limit")
                    page_character_offset = character_offset
                    character_offset += len(raw_characters)
                    character_count = character_offset
                    glyphs, _next_character_offset = _extract_glyphs(
                        page,
                        page_index=page_index,
                        character_offset=page_character_offset,
                        started=started,
                        raw_characters=raw_characters,
                    )
                    page_rules = _extract_rules(
                        page,
                        page_index=page_index,
                        source_sha256=source_sha256,
                        started=started,
                        remaining_document_rules=(
                            MAX_RULES_PER_DOCUMENT - len(rules)
                        ),
                    )
                    if not glyphs:
                        commit_page(
                            SourceSemanticsPage(
                                page_index=page_index,
                                page_width=page_width,
                                page_height=page_height,
                                status="unavailable",
                                concern_code="text_run_source_unsupported",
                                rule_ids=tuple(
                                    rule.id for rule in page_rules
                                ),
                            ),
                            page_rules=page_rules,
                        )
                        continue
                    lines = _cluster_lines(glyphs, started=started)
                    page_runs, rule_ambiguous = _semantic_runs_for_page(
                        source_sha256=source_sha256,
                        page_index=page_index,
                        lines=lines,
                        rules=page_rules,
                        started=started,
                    )
                    if len(runs) + len(page_runs) > MAX_RUNS_PER_DOCUMENT:
                        raise _Refusal("text_run_source_limit")
                    commit_page(
                        SourceSemanticsPage(
                            page_index=page_index,
                            page_width=page_width,
                            page_height=page_height,
                            status="projectable",
                            concern_codes=(
                                ("text_run_rule_ambiguous",)
                                if rule_ambiguous
                                else ()
                            ),
                            run_ids=tuple(run.id for run in page_runs),
                            rule_ids=tuple(rule.id for rule in page_rules),
                        ),
                        page_runs=page_runs,
                        page_rules=page_rules,
                    )
                except _DocumentRefusal:
                    raise
                except _Refusal as exc:
                    try:
                        commit_page(
                            SourceSemanticsPage(
                                page_index=page_index,
                                page_width=page_width,
                                page_height=page_height,
                                status="unavailable",
                                concern_code=exc.code,
                            )
                        )
                    except _Refusal as commit_exc:
                        raise _DocumentRefusal(
                            commit_exc.code
                        ) from commit_exc
                except Exception:
                    try:
                        commit_page(
                            SourceSemanticsPage(
                                page_index=page_index,
                                page_width=page_width,
                                page_height=page_height,
                                status="unavailable",
                                concern_code="text_run_source_invalid",
                            )
                        )
                    except Exception as commit_exc:
                        raise _DocumentRefusal(
                            "text_run_source_invalid"
                        ) from commit_exc
        report = TextRunEvidence(
            source_sha256=source_sha256,
            usable=True,
            page_count=page_count,
            character_count=character_count,
            candidate_rule_count=candidate_rule_count,
            pages=tuple(pages),
            runs=tuple(runs),
            rules=tuple(rules),
            elapsed_ms=min(
                max(
                    (time.perf_counter() - started) * 1000.0,
                    0.0,
                ),
                60_000.0,
            ),
        )
        _bounded_report_size(report, started=started)
        return report
    except _Refusal as exc:
        return _unusable_report(
            source_sha256=source_sha256,
            refusal_code=exc.code,
            page_count=page_count,
            character_count=character_count,
            candidate_rule_count=candidate_rule_count,
            started=started,
        )
    except Exception:
        return _unusable_report(
            source_sha256=source_sha256,
            refusal_code="text_run_source_invalid",
            page_count=page_count,
            character_count=character_count,
            candidate_rule_count=candidate_rule_count,
            started=started,
        )


def _normalization_clusters(value: str) -> list[tuple[int, int]]:
    clusters: list[tuple[int, int]] = []

    def is_hangul_jamo(character: str) -> bool:
        codepoint = ord(character)
        return (
            0x1100 <= codepoint <= 0x11FF
            or 0xA960 <= codepoint <= 0xA97F
            or 0xD7B0 <= codepoint <= 0xD7FF
        )

    start = 0
    for index, character in enumerate(value):
        if index == 0:
            continue
        previous = value[index - 1]
        if (
            unicodedata.combining(character) == 0
            and not (
                is_hangul_jamo(previous)
                and is_hangul_jamo(character)
            )
        ):
            clusters.append((start, index))
            start = index
    if value:
        clusters.append((start, len(value)))
    return clusters


def _comparison_view(
    value: str,
) -> tuple[str, list[tuple[int, int]]]:
    output: list[str] = []
    owners: list[tuple[int, int]] = []
    pending_space_owner: tuple[int, int] | None = None
    for start, end in _normalization_clusters(value):
        source_cluster = value[start:end]
        normalized = unicodedata.normalize(
            "NFKC",
            source_cluster,
        ).translate(
            _COMPARISON_TRANSLATION
        )
        for child in normalized:
            if child.isspace():
                if output:
                    if pending_space_owner is None:
                        pending_space_owner = (start, end)
                    else:
                        pending_space_owner = (
                            pending_space_owner[0],
                            end,
                        )
                continue
            if pending_space_owner is not None:
                if output and output[-1] != " ":
                    output.append(" ")
                    owners.append(pending_space_owner)
                pending_space_owner = None
            output.append(child)
            owners.append((start, end))
    return "".join(output), owners


def _markdown_escape(value: str, *, html_context: bool = False) -> str:
    escaped = (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    if html_context:
        return escaped
    escaped = re.sub(r"([\\`*_\[\]|~])", r"\\\1", escaped)
    escaped = re.sub(
        r"(?m)^([ \t]{0,3})([#>+-])(?=\s)",
        r"\1\\\2",
        escaped,
    )
    escaped = re.sub(
        r"(?m)^([ \t]{0,3})(-)(?=-*[ \t]*$)",
        r"\1\\\2",
        escaped,
    )
    escaped = re.sub(
        r"(?m)^([ \t]{0,3})(=)(?==*[ \t]*$)",
        r"\1\\\2",
        escaped,
    )
    return re.sub(
        r"(?m)^([ \t]{0,3})(\d+)([.)])(?=\s)",
        r"\1\2\\\3",
        escaped,
    )


@dataclass(frozen=True, slots=True)
class _TargetSlot:
    page_id: str
    element_id: str
    target_path: tuple[str | int, ...]
    text: str
    bbox: SourceBBox


@dataclass(frozen=True, slots=True)
class _MappedRun:
    source: SourceRunEvidence
    slot: _TargetSlot
    start: int
    end: int
    text: str


@dataclass(slots=True)
class _AlignmentBudget:
    started: float = field(default_factory=time.perf_counter)
    comparisons: int = 0
    text_work: int = 0
    occurrences: int = 0

    def check_deadline(self) -> None:
        if time.perf_counter() - self.started > MAX_EXTRACTION_SECONDS:
            raise _Refusal("text_run_alignment_limit")

    def add_comparisons(self, count: int = 1) -> None:
        self.check_deadline()
        self.comparisons += count
        if self.comparisons > MAX_ALIGNMENT_COMPARISONS_PER_PAGE:
            raise _Refusal("text_run_alignment_limit")

    def add_text_work(self, count: int) -> None:
        self.check_deadline()
        self.text_work += count
        if self.text_work > MAX_ALIGNMENT_TEXT_WORK_PER_PAGE:
            raise _Refusal("text_run_alignment_limit")

    def add_occurrence(self) -> None:
        self.check_deadline()
        self.occurrences += 1
        if self.occurrences > MAX_ALIGNMENT_COMPARISONS_PER_PAGE:
            raise _Refusal("text_run_alignment_limit")


def _public_bbox(value: Any) -> SourceBBox | None:
    if not isinstance(value, Mapping):
        return None
    try:
        width = float(value.get("width", value.get("w")))
        height = float(value.get("height", value.get("h")))
        unit = str(value.get("unit") or "pt")
        box = SourceBBox(
            x=float(value["x"]),
            y=float(value["y"]),
            width=width,
            height=height,
            unit="pt",
        )
    except (KeyError, TypeError, ValueError):
        return None
    return box if unit == "pt" else None


def _target_slots_for_page(
    ir: Any,
    page: Any,
    *,
    started: float | None = None,
    elements_by_id: Mapping[str, Any] | None = None,
) -> list[_TargetSlot]:
    elements = (
        elements_by_id
        if elements_by_id is not None
        else {element.id: element for element in ir.elements}
    )
    slots: list[_TargetSlot] = []
    inspected_bytes = 0
    traversed_candidates = 0

    def inspect_structure() -> None:
        nonlocal traversed_candidates
        traversed_candidates += 1
        if (
            started is not None
            and (
                traversed_candidates == 1
                or traversed_candidates % 256 == 0
            )
            and time.perf_counter() - started > MAX_EXTRACTION_SECONDS
        ):
            raise _Refusal("text_run_alignment_limit")
        if traversed_candidates > MAX_TARGET_TRAVERSAL_PER_PAGE:
            raise _Refusal("text_run_alignment_limit")

    def append_slot(slot: _TargetSlot) -> None:
        nonlocal inspected_bytes
        inspected_bytes += len(slot.text.encode("utf-8"))
        if (
            len(slots) >= MAX_TARGET_CANDIDATES_PER_PAGE
            or inspected_bytes > MAX_TARGET_TEXT_BYTES_PER_PAGE
        ):
            raise _Refusal("text_run_alignment_limit")
        slots.append(slot)

    from app.services.source_text_alignment import (
        supplemental_ocr_owner_is_attributable,
    )

    for element_id in page.presentation_element_ids:
        inspect_structure()
        element = elements[element_id]
        legacy = element.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            continue
        # Source-run semantics belong to native public owners. A closed,
        # pipeline-issued supplemental page-OCR owner remains public and
        # attributable, but cannot compete with an overlapping native table
        # cell for the same source run before table authority is resolved.
        if supplemental_ocr_owner_is_attributable(
            legacy,
            page_index=page.page_index,
            source_sha256=ir.source_sha256,
        ):
            continue
        child_aliases: list[tuple[str, SourceBBox]] = []
        scalar = legacy.get("value")
        scalar_bbox = _public_bbox(legacy.get("bbox"))
        nested_items = legacy.get("items")
        cells = legacy.get("cells")
        if isinstance(cells, Sequence) and not isinstance(
            cells, (str, bytes, bytearray)
        ):
            for index, cell in enumerate(cells):
                inspect_structure()
                if not isinstance(cell, Mapping):
                    continue
                text = cell.get("text")
                bbox = _public_bbox(cell.get("bbox"))
                if not isinstance(text, str) or bbox is None:
                    continue
                append_slot(
                    _TargetSlot(
                        page_id=page.id,
                        element_id=element.id,
                        target_path=("cells", index, "text"),
                        text=text,
                        bbox=bbox,
                    )
                )
                child_aliases.append((text, bbox))
        if isinstance(nested_items, Sequence) and not isinstance(
            nested_items, (str, bytes, bytearray)
        ):
            for index, child in enumerate(nested_items):
                inspect_structure()
                if not isinstance(child, Mapping):
                    continue
                bbox = _public_bbox(child.get("bbox"))
                if bbox is None:
                    continue
                for key in ("value", "text"):
                    text = child.get(key)
                    if not isinstance(text, str):
                        continue
                    append_slot(
                        _TargetSlot(
                            page_id=page.id,
                            element_id=element.id,
                            target_path=("items", index, key),
                            text=text,
                            bbox=bbox,
                        )
                    )
                    child_aliases.append((text, bbox))
        scalar_is_exact_child_alias = (
            isinstance(scalar, str)
            and scalar_bbox is not None
            and any(
                text == scalar
                and all(
                    math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                    for left, right in zip(
                        (
                            bbox.x,
                            bbox.y,
                            bbox.width,
                            bbox.height,
                        ),
                        (
                            scalar_bbox.x,
                            scalar_bbox.y,
                            scalar_bbox.width,
                            scalar_bbox.height,
                        ),
                        strict=True,
                    )
                )
                for text, bbox in child_aliases
            )
        )
        if (
            isinstance(scalar, str)
            and scalar_bbox is not None
            and not scalar_is_exact_child_alias
        ):
            append_slot(
                _TargetSlot(
                    page_id=page.id,
                    element_id=element.id,
                    target_path=("value",),
                    text=scalar,
                    bbox=scalar_bbox,
                )
            )
    if (
        started is not None
        and time.perf_counter() - started > MAX_EXTRACTION_SECONDS
    ):
        raise _Refusal("text_run_alignment_limit")
    return sorted(
        slots,
        key=lambda slot: (
            slot.bbox.y,
            slot.bbox.x,
            _target_path_key(slot.target_path),
            slot.element_id,
        ),
    )


def _target_path_key(path: Sequence[str | int]) -> tuple[Any, ...]:
    if tuple(path) == ("value",):
        return ("value", -1, "")
    if len(path) == 3 and path[0] == "cells":
        return ("cells", int(path[1]), str(path[2]))
    if len(path) == 3 and path[0] == "items":
        return ("items", int(path[1]), str(path[2]))
    return ("~invalid", -1, _canonical_json(list(path)))


def _contains_with_margin(
    outer: SourceBBox,
    inner: SourceBBox,
    margin: float = 2.0,
) -> bool:
    return (
        inner.x >= outer.x - margin
        and inner.y >= outer.y - margin
        and inner.x + inner.width <= outer.x + outer.width + margin
        and inner.y + inner.height <= outer.y + outer.height + margin
    )


def _page_extent_for_projection(
    ir: Any,
    page: Any,
    *,
    coordinates_by_id: Mapping[str, Any] | None = None,
    extents_by_coordinate: Mapping[str, Sequence[Any]] | None = None,
) -> SourceBBox | None:
    coordinates = (
        coordinates_by_id
        if coordinates_by_id is not None
        else {
            coordinate.id: coordinate
            for coordinate in ir.coordinate_systems
        }
    )
    coordinate = coordinates.get(page.coordinate_system_id)
    candidates = (
        list(extents_by_coordinate.get(page.coordinate_system_id, ()))
        if extents_by_coordinate is not None
        else [
            bbox
            for bbox in ir.bboxes
            if bbox.role == "page"
            and bbox.coordinate_system_id == page.coordinate_system_id
        ]
    )
    if (
        coordinate is None
        or coordinate.page_id != page.id
        or coordinate.unit != "pt"
        or coordinate.origin != "top_left"
        or coordinate.transform_to_page != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        or len(candidates) != 1
    ):
        return None
    [bbox] = candidates
    try:
        return SourceBBox(
            x=float(bbox.x),
            y=float(bbox.y),
            width=float(bbox.width),
            height=float(bbox.height),
        )
    except (TypeError, ValueError):
        return None


def _source_comparison(value: str) -> str:
    return _comparison_view(value)[0]


def _source_comparison_variants(value: str) -> tuple[str, ...]:
    """Include the pinned PDF adapter's generic curly-quote fallback."""

    strict = _source_comparison(value)
    generic_pdf_quotes = _comparison_view(
        value.translate(
            str.maketrans(
                {
                    "\u201c": "'",
                    "\u201d": "'",
                    "\u201e": "'",
                    "\u201f": "'",
                }
            )
        )
    )[0]
    return tuple(dict.fromkeys((strict, generic_pdf_quotes)))


def _candidate_slots(
    runs: Sequence[SourceRunEvidence],
    slots: Sequence[_TargetSlot],
    *,
    budget: _AlignmentBudget,
) -> dict[str, list[_TargetSlot]]:
    vertical_index = _build_interval_index(
        [
            (
                slot.bbox.y - 2.0,
                slot.bbox.y + slot.bbox.height + 2.0,
                index,
            )
            for index, slot in enumerate(slots)
        ]
    )
    output: dict[str, list[_TargetSlot]] = {}
    comparison_cache: dict[
        tuple[str, tuple[str | int, ...]],
        str,
    ] = {}
    for run in runs:
        nearby_indexes = _query_interval_index(
            vertical_index,
            run.bbox.y + run.bbox.height / 2.0,
            limit=MAX_TARGET_CANDIDATES_PER_PAGE,
        )
        if len(nearby_indexes) > MAX_TARGET_CANDIDATES_PER_PAGE:
            raise _Refusal("text_run_alignment_limit")
        spatial_candidates: list[_TargetSlot] = []
        for slot_index in nearby_indexes:
            slot = slots[slot_index]
            budget.add_comparisons()
            if _contains_with_margin(slot.bbox, run.bbox):
                spatial_candidates.append(slot)
                if len(spatial_candidates) > 8:
                    raise _Refusal("text_run_alignment_limit")
        candidates: list[_TargetSlot] = []
        source_views = tuple(
            view for view in _source_comparison_variants(run.text) if view
        )
        for slot in spatial_candidates:
            key = (slot.element_id, slot.target_path)
            target_view = comparison_cache.get(key)
            if target_view is None:
                target_view, _owners = _comparison_view(slot.text)
                comparison_cache[key] = target_view
            budget.add_text_work(
                len(target_view) + sum(len(view) for view in source_views)
            )
            if any(view in target_view for view in source_views):
                candidates.append(slot)
        if len(candidates) > 8:
            raise _Refusal("text_run_alignment_limit")
        output[run.id] = sorted(
            candidates,
            key=lambda slot: (
                _target_path_key(slot.target_path),
                slot.element_id,
            ),
        )
    return output


def _align_source_runs(
    runs: Sequence[SourceRunEvidence],
    slots: Sequence[_TargetSlot],
    *,
    started: float | None = None,
) -> list[_MappedRun]:
    budget = _AlignmentBudget(
        started=started if started is not None else time.perf_counter()
    )
    candidates = _candidate_slots(runs, slots, budget=budget)
    assigned: dict[str, _TargetSlot] = {}
    for run in runs:
        options = candidates.get(run.id, ())
        if len(options) != 1:
            raise _Refusal("text_run_alignment_ambiguous")
        assigned[run.id] = options[0]

    grouped: dict[
        tuple[str, tuple[str | int, ...]],
        list[SourceRunEvidence],
    ] = defaultdict(list)
    slots_by_key = {
        (slot.element_id, slot.target_path): slot for slot in slots
    }
    for run in runs:
        slot = assigned[run.id]
        grouped[(slot.element_id, slot.target_path)].append(run)

    mapped: list[_MappedRun] = []
    for key, target_runs in sorted(
        grouped.items(),
        key=lambda entry: (
            _target_path_key(entry[0][1]),
            entry[0][0],
        ),
    ):
        slot = slots_by_key[key]
        target_view, target_owners = _comparison_view(slot.text)
        ordered = sorted(
            target_runs,
            key=lambda run: (
                run.line_index,
                run.bbox.x,
                run.source_character_indexes,
                run.id,
            ),
        )
        occurrences_by_run: list[list[tuple[int, int]]] = []
        for run in ordered:
            source_views = tuple(
                view for view in _source_comparison_variants(run.text) if view
            )
            if not source_views:
                raise _Refusal("text_run_alignment_ambiguous")
            budget.add_text_work(
                len(target_view) + sum(len(view) for view in source_views)
            )
            occurrence_set: set[tuple[int, int]] = set()
            for source_view in source_views:
                search_from = 0
                while True:
                    position = target_view.find(source_view, search_from)
                    if position < 0:
                        break
                    occurrence = (position, position + len(source_view))
                    if occurrence not in occurrence_set:
                        occurrence_set.add(occurrence)
                        budget.add_occurrence()
                    search_from = position + 1
            occurrences = sorted(occurrence_set)
            if not occurrences:
                raise _Refusal("text_run_alignment_ambiguous")
            occurrences_by_run.append(occurrences)

        suffix_counts: list[list[int]] = [
            [] for _occurrences in occurrences_by_run
        ]
        suffix_counts[-1] = [1] * len(occurrences_by_run[-1])
        for index in range(len(occurrences_by_run) - 2, -1, -1):
            following = occurrences_by_run[index + 1]
            following_starts = [start for start, _end in following]
            following_counts = suffix_counts[index + 1]
            saturated_suffix = [0] * (len(following_counts) + 1)
            for position in range(len(following_counts) - 1, -1, -1):
                saturated_suffix[position] = min(
                    2,
                    saturated_suffix[position + 1]
                    + following_counts[position],
                )
            current_counts: list[int] = []
            for _start, end in occurrences_by_run[index]:
                compatible = bisect_left(following_starts, end)
                current_counts.append(saturated_suffix[compatible])
            suffix_counts[index] = current_counts
        if min(2, sum(suffix_counts[0])) != 1:
            raise _Refusal("text_run_alignment_ambiguous")

        cursor = 0
        for run, occurrences, counts in zip(
            ordered,
            occurrences_by_run,
            suffix_counts,
            strict=True,
        ):
            choices = [
                occurrence
                for occurrence, count in zip(
                    occurrences,
                    counts,
                    strict=True,
                )
                if occurrence[0] >= cursor and count > 0
            ]
            if len(choices) != 1:
                raise _Refusal("text_run_alignment_ambiguous")
            position, comparison_end = choices[0]
            last = comparison_end - 1
            if not 0 <= position <= last < len(target_owners):
                raise _Refusal("text_run_alignment_ambiguous")
            if (
                (position > 0 and target_owners[position - 1] == target_owners[position])
                or (
                    last + 1 < len(target_owners)
                    and target_owners[last + 1] == target_owners[last]
                )
            ):
                raise _Refusal("text_run_alignment_ambiguous")
            start = target_owners[position][0]
            end = target_owners[last][1]
            if run.text[0].isspace():
                while start > 0 and slot.text[start - 1].isspace():
                    start -= 1
            if run.text[-1].isspace():
                while end < len(slot.text) and slot.text[end].isspace():
                    end += 1
            if not 0 <= start < end <= len(slot.text):
                raise _Refusal("text_run_alignment_ambiguous")
            mapped.append(
                _MappedRun(
                    source=run,
                    slot=slot,
                    start=start,
                    end=end,
                    text=slot.text[start:end],
                )
            )
            cursor = comparison_end
    return sorted(
        mapped,
        key=lambda mapped_run: (
            mapped_run.source.page_index,
            mapped_run.slot.element_id,
            _target_path_key(mapped_run.slot.target_path),
            mapped_run.start,
            mapped_run.end,
            mapped_run.source.id,
        ),
    )


def _public_color(color: Any) -> dict[str, Any]:
    return {
        "space": str(getattr(color.space, "value", color.space)),
        "components": list(color.components),
    }


def _public_bbox_dict(bbox: Any) -> dict[str, Any]:
    return {
        "x": float(bbox.x),
        "y": float(bbox.y),
        "width": float(bbox.width),
        "height": float(bbox.height),
        "unit": "pt",
    }


def _render_scalar_markdown(
    value: str,
    runs: Sequence[Any],
    *,
    include_emphasis: bool = True,
) -> str:
    decoration_kind = Literal[
        "bold",
        "bold_italic",
        "deleted",
        "italic",
        "underline",
    ]
    decorated: list[tuple[int, int, decoration_kind]] = []
    deleted_groups: dict[str, list[Any]] = defaultdict(list)
    for run in runs:
        if run.change_state == "deleted":
            deleted_groups[run.change_group_id or run.id].append(run)
    for grouped in deleted_groups.values():
        decorated.append(
            (
                min(run.start for run in grouped),
                max(run.end for run in grouped),
                "deleted",
            )
        )
    for run in runs:
        if run.change_state != "deleted" and "underline" in run.decorations:
            decorated.append((run.start, run.end, "underline"))
    if include_emphasis:
        protected_ranges = [
            (start, end)
            for start, end, kind in decorated
            if kind in {"deleted", "underline"}
        ]
        for run in runs:
            if (
                run.change_state == "deleted"
                or not (run.bold or run.italic)
                or any(
                    run.start < protected_end and protected_start < run.end
                    for protected_start, protected_end in protected_ranges
                )
            ):
                continue
            kind: decoration_kind = (
                "bold_italic"
                if run.bold and run.italic
                else ("bold" if run.bold else "italic")
            )
            decorated.append((run.start, run.end, kind))
    decorated.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    for left, right in zip(decorated, decorated[1:], strict=False):
        if left[1] > right[0]:
            raise _Refusal("text_run_projection_failed_closed")
    output: list[str] = []
    cursor = 0
    for start, end, kind in decorated:
        output.append(_markdown_escape(value[cursor:start]))
        content = value[start:end]
        if kind == "deleted":
            output.append(f"~~{_markdown_escape(content)}~~")
        elif kind == "underline":
            underline_content = (
                _markdown_escape(content, html_context=True)
                if content and set(content) == {"_"}
                else _markdown_escape(content)
            )
            output.append(
                f"<u>{underline_content}</u>"
            )
        elif kind == "bold":
            output.append(f"**{_markdown_escape(content)}**")
        elif kind == "italic":
            output.append(f"*{_markdown_escape(content)}*")
        else:
            output.append(f"***{_markdown_escape(content)}***")
        cursor = end
    output.append(_markdown_escape(value[cursor:]))
    return "".join(output)


def _apply_markdown_envelope(
    element: Any,
    legacy: Mapping[str, Any],
    rendered_body: str,
) -> str | None:
    value = legacy.get("value")
    markdown = legacy.get("md")
    if not isinstance(value, str) or not isinstance(markdown, str):
        return None
    if element.type.casefold() == "heading":
        match = re.fullmatch(r"(#{1,6} )(.*)", markdown, flags=re.DOTALL)
        if match is None or match.group(2) != value:
            return None
        return f"{match.group(1)}{rendered_body}"
    if element.type.casefold() in {"text", "header", "footer"}:
        return rendered_body if markdown == value else None
    return None


def _active_text(value: str, runs: Sequence[Any]) -> tuple[str, list[str]]:
    deleted = sorted(
        (run for run in runs if run.change_state == "deleted"),
        key=lambda run: (run.start, run.end, run.id),
    )
    output: list[str] = []
    cursor = 0
    omitted: list[str] = []
    for run in deleted:
        if run.start < cursor:
            raise _Refusal("text_run_projection_failed_closed")
        output.append(value[cursor : run.start])
        omitted.append(run.id)
        cursor = run.end
    output.append(value[cursor:])
    return "".join(output), omitted


def _entire_heading_is_source_deleted(
    element: Any,
    value: str,
    scalar_runs: Sequence[Any],
    *,
    run_bbox: Any | None = None,
    page_width: float = math.nan,
    page_height: float = math.nan,
) -> bool:
    """Return true only for a compact, top-right deleted revision banner.

    A complete deletion alone cannot prove that a source heading is really a
    document-status banner: a legitimate struck heading still owns its
    heading envelope.  The functional-fidelity correction is therefore
    limited to the source-backed banner geometry found in the reviewed
    agreement (top band, right rail, compact width), in addition to the
    existing complete scalar and vector-strike proof.
    """

    if not (
        math.isfinite(page_width)
        and math.isfinite(page_height)
        and page_width > 0
        and page_height > 0
    ):
        return False
    run = scalar_runs[0] if len(scalar_runs) == 1 else None
    bbox = run_bbox

    return (
        element.type.casefold() == "heading"
        and run is not None
        and run.change_state == "deleted"
        and run.start == 0
        and run.end == len(value)
        and run.evidence_method.value == "vector"
        and run.semantic_derivation == "same_color_midline_rule"
        and len(run.rule_ids) == 1
        and bbox is not None
        and bbox.x >= page_width * 0.70
        and bbox.y >= 0
        and bbox.y + bbox.height <= page_height * 0.12
        and bbox.width <= page_width * 0.25
        and bbox.height <= page_height * 0.05
    )


def _refine_underlined_subordinate_heading(
    page: Any,
    elements: Mapping[str, Any],
    runs_by_element: Mapping[str, Sequence[Any]],
) -> None:
    """Project a source-proven underlined subordinate beneath one H1."""

    ordered = [
        elements[element_id]
        for element_id in page.presentation_element_ids
        if element_id in elements
    ]
    prior_headings: list[Any] = []
    for element in ordered:
        legacy = element.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            continue
        if element.type.casefold() != "heading":
            continue
        try:
            level = int(legacy.get("level") or 1)
        except (TypeError, ValueError):
            prior_headings.append(element)
            continue
        runs = [
            run
            for run in runs_by_element.get(element.id, ())
            if tuple(run.target_path) == ("value",)
        ]
        value = legacy.get("value")
        full_underline = (
            isinstance(value, str)
            and len(runs) == 1
            and runs[0].change_state == "unchanged"
            and runs[0].start == 0
            and runs[0].end == len(value)
            and "underline" in runs[0].decorations
        )
        if level != 1 or not full_underline:
            prior_headings.append(element)
            continue

        same_size_h1: list[tuple[Any, Any]] = []
        for predecessor in prior_headings:
            predecessor_legacy = predecessor.properties.get("legacy_item")
            if not isinstance(predecessor_legacy, Mapping):
                continue
            try:
                predecessor_level = int(predecessor_legacy.get("level") or 1)
            except (TypeError, ValueError):
                continue
            predecessor_runs = [
                run
                for run in runs_by_element.get(predecessor.id, ())
                if tuple(run.target_path) == ("value",)
            ]
            if (
                predecessor_level == 1
                and len(predecessor_runs) == 1
                and predecessor_runs[0].change_state == "unchanged"
                and predecessor_runs[0].start == 0
                and isinstance(predecessor_legacy.get("value"), str)
                and predecessor_runs[0].end
                == len(predecessor_legacy["value"])
                and "underline" not in predecessor_runs[0].decorations
                and abs(
                    float(predecessor_runs[0].font_size)
                    - float(runs[0].font_size)
                )
                <= 0.05
            ):
                same_size_h1.append((predecessor, predecessor_legacy))
        # More than one same-size H1 is competing hierarchy evidence; leave
        # the predecessor level untouched instead of guessing parentage.
        if len(same_size_h1) != 1:
            prior_headings.append(element)
            continue
        predecessor, predecessor_legacy = same_size_h1[0]
        candidate_box = legacy.get("bbox")
        predecessor_box = predecessor_legacy.get("bbox")
        if not (
            isinstance(candidate_box, Mapping)
            and isinstance(predecessor_box, Mapping)
            and float(candidate_box.get("y", 0.0))
            > float(predecessor_box.get("y", 0.0))
        ):
            prior_headings.append(element)
            continue
        markdown = legacy.get("md")
        if not isinstance(markdown, str) or not markdown.startswith("# "):
            prior_headings.append(element)
            continue
        refined = dict(legacy)
        refined["level"] = 2
        refined["md"] = f"## {markdown[2:]}"
        if isinstance(refined.get("redline_markdown"), str):
            redline = refined["redline_markdown"]
            if not redline.startswith("# "):
                prior_headings.append(element)
                continue
            refined["redline_markdown"] = f"## {redline[2:]}"
        element.markdown = refined["md"]
        element.properties["legacy_item"] = refined
        prior_headings.append(element)


def _add_projection_concern(
    ir: Any,
    *,
    code: str,
    page_id: str | None = None,
    error_type: str | None = None,
) -> None:
    from app.services.ir import IRConcern

    allowed_codes = {
        "text_run_source_unsupported",
        "text_run_source_invalid",
        "text_run_source_limit",
        "text_run_rule_limit",
        "text_run_alignment_limit",
        "text_run_alignment_ambiguous",
        "text_run_rule_ambiguous",
        "text_run_transform_unavailable",
        "text_run_projection_failed_closed",
        "text_run_concerns_truncated",
    }
    safe_code = (
        code if code in allowed_codes else "text_run_projection_failed_closed"
    )

    def metadata_page(concern: Any) -> str | None:
        metadata = getattr(concern, "metadata", None)
        return (
            metadata.get("page_id")
            if isinstance(metadata, Mapping)
            and isinstance(metadata.get("page_id"), str)
            else None
        )

    if any(
        concern.code == safe_code
        and metadata_page(concern) == page_id
        and (
            not isinstance(getattr(concern, "metadata", None), Mapping)
            or concern.metadata.get("policy_id") in {None, TEXT_RUN_POLICY_ID}
        )
        for concern in ir.concerns
    ):
        return

    detailed_text_run = [
        concern
        for concern in ir.concerns
        if concern.code.startswith("text_run_")
        and concern.code != "text_run_concerns_truncated"
    ]
    page_count = sum(
        1
        for concern in detailed_text_run
        if page_id is not None and metadata_page(concern) == page_id
    )
    detailed_total = sum(
        1
        for concern in ir.concerns
        if concern.code != "text_run_concerns_truncated"
    )
    if (
        len(detailed_text_run) >= MAX_CONCERNS_PER_DOCUMENT
        or (page_id is not None and page_count >= MAX_CONCERNS_PER_PAGE)
        or detailed_total >= MAX_TOTAL_CONCERNS
    ):
        if not any(
            concern.code == "text_run_concerns_truncated"
            for concern in ir.concerns
        ):
            ir.concerns.append(
                IRConcern(
                    code="text_run_concerns_truncated",
                    message="Text-run diagnostics exceeded their bounded limit.",
                    metadata={
                        "policy_id": TEXT_RUN_POLICY_ID,
                        "per_page_limit": MAX_CONCERNS_PER_PAGE,
                        "document_limit": MAX_CONCERNS_PER_DOCUMENT,
                        "total_limit": MAX_TOTAL_CONCERNS,
                    },
                )
            )
        return
    metadata: dict[str, Any] = {"policy_id": TEXT_RUN_POLICY_ID}
    if page_id is not None:
        metadata["page_id"] = page_id
    if error_type is not None and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error_type):
        metadata["error_type"] = error_type
    ir.concerns.append(
        IRConcern(
            code=safe_code,
            message="Text-run semantic projection failed closed.",
            metadata=metadata,
        )
    )


_PUBLIC_PROJECTION_KEYS = frozenset(
    {
        "text_run_policy",
        "text_runs",
        "text_rules",
        "redline_markdown",
        "active_text",
        "active_text_omitted_run_ids",
        "active_text_policy",
    }
)


def _restore_predecessor_public_projection(ir: Any) -> None:
    """Remove a prior public-only overlay before terminal IR re-entry."""

    for element in ir.elements:
        legacy = element.properties.get("legacy_item")
        if (
            not isinstance(legacy, Mapping)
            or legacy.get("text_run_policy") != TEXT_RUN_POLICY_ID
        ):
            continue
        public = {
            key: deepcopy(value)
            for key, value in legacy.items()
            if key not in _PUBLIC_PROJECTION_KEYS
        }
        value = public.get("value")
        markdown = public.get("md")
        if isinstance(value, str) and isinstance(markdown, str):
            element_type = element.type.casefold()
            if element_type == "heading":
                match = re.match(r"^(#{1,6} )", markdown)
                if match is not None:
                    public["md"] = f"{match.group(1)}{value}"
            elif element_type in {"text", "header", "footer"}:
                public["md"] = value
        element.markdown = (
            public.get("md")
            if isinstance(public.get("md"), str)
            else element.markdown
        )
        element.properties["legacy_item"] = public
        element.properties.pop("text_run_projection", None)


def _project_page_semantics(
    working: Any,
    *,
    page: Any,
    source_page: SourceSemanticsPage,
    mapped_runs: Sequence[_MappedRun],
    source_rules: Mapping[str, SourceRuleEvidence],
    elements_by_id: Mapping[str, Any] | None = None,
) -> None:
    from app.services.ir import (
        ConfidenceRecord,
        EvidenceMethod,
        EvidenceRecord,
        IRBoundingBox,
        TextColorRecord,
        TextRuleRecord,
        TextRunRecord,
    )

    elements = (
        elements_by_id
        if elements_by_id is not None
        else {element.id: element for element in working.elements}
    )
    coordinate_id = page.coordinate_system_id
    new_bbox_start = len(working.bboxes)
    ir_runs: list[Any] = []
    rules_by_id: dict[str, Any] = {}
    for mapped in mapped_runs:
        source = mapped.source
        element = elements[mapped.slot.element_id]
        run_bbox_id = _stable_id(
            "trbox",
            working.source_sha256,
            page.id,
            source.id,
            mapped.slot.target_path,
            mapped.start,
            mapped.end,
        )
        run_bbox = IRBoundingBox(
            id=run_bbox_id,
            coordinate_system_id=coordinate_id,
            x=source.bbox.x,
            y=source.bbox.y,
            width=source.bbox.width,
            height=source.bbox.height,
            role="field",
        )
        working.bboxes.append(run_bbox)
        evidence_id = _stable_id(
            "trev",
            working.source_sha256,
            element.id,
            source.id,
            mapped.start,
            mapped.end,
        )
        evidence_method = (
            EvidenceMethod.VECTOR
            if source.rule_ids
            else EvidenceMethod.NATIVE
        )
        working.evidence.append(
            EvidenceRecord(
                id=evidence_id,
                element_id=element.id,
                method=evidence_method,
                bbox_id=run_bbox_id,
                value={
                    "source_run_id": source.id,
                    "target_path": list(mapped.slot.target_path),
                },
                confidence=ConfidenceRecord(
                    scope="evidence",
                    unavailable_reason="source_semantics_not_probability_scored",
                ),
                metadata={
                    "story": "P03-US05",
                    "policy_id": TEXT_RUN_POLICY_ID,
                },
            )
        )
        element.evidence_ids.append(evidence_id)
        for rule_id in source.rule_ids:
            if rule_id in rules_by_id:
                continue
            source_rule = source_rules[rule_id]
            rule_bbox_id = _stable_id(
                "trbox",
                working.source_sha256,
                page.id,
                rule_id,
            )
            working.bboxes.append(
                IRBoundingBox(
                    id=rule_bbox_id,
                    coordinate_system_id=coordinate_id,
                    x=source_rule.bbox.x,
                    y=source_rule.bbox.y,
                    width=source_rule.bbox.width,
                    height=source_rule.bbox.height,
                    role="field",
                )
            )
            rules_by_id[rule_id] = TextRuleRecord(
                id=rule_id,
                source_sha256=working.source_sha256,
                page_id=page.id,
                bbox_id=rule_bbox_id,
                source_object_kind=source_rule.source_object_kind,
                source_object_index=source_rule.source_object_index,
                color=TextColorRecord(
                    space=source_rule.color.space,
                    components=source_rule.color.components,
                    raw_value=source_rule.color.raw_value,
                ),
                width=source_rule.width,
                thickness=source_rule.thickness,
                evidence_method=EvidenceMethod.VECTOR,
                extraction_policy_id=TEXT_RUN_EXTRACTION_POLICY_ID,
            )
        run_id = _stable_id(
            "trun",
            working.source_sha256,
            page.id,
            element.id,
            mapped.slot.target_path,
            mapped.start,
            mapped.end,
            source.id,
        )
        target_digest = hashlib.sha256(
            mapped.slot.text.encode("utf-8")
        ).hexdigest()
        ir_run = TextRunRecord(
            id=run_id,
            source_sha256=working.source_sha256,
            page_id=page.id,
            element_id=element.id,
            target_path=tuple(mapped.slot.target_path),
            target_text_sha256=target_digest,
            change_group_id=source.change_group_id,
            text=mapped.text,
            source_text=source.text,
            start=mapped.start,
            end=mapped.end,
            bbox_id=run_bbox_id,
            font_size=source.font_size,
            font_name=source.font_name,
            bold=source.bold,
            italic=source.italic,
            color=TextColorRecord(
                space=source.color.space,
                components=source.color.components,
                raw_value=source.color.raw_value,
            ),
            source_character_indexes=list(source.source_character_indexes),
            change_state=source.change_state,
            decorations=list(source.decorations),
            placeholder=source.placeholder,
            rule_ids=list(source.rule_ids),
            evidence_ids=[evidence_id],
            evidence_method=evidence_method,
            semantic_derivation=source.semantic_derivation,
            extraction_policy_id=TEXT_RUN_EXTRACTION_POLICY_ID,
            association_policy_id=TEXT_RUN_ASSOCIATION_POLICY_ID,
        )
        ir_runs.append(ir_run)

    working.text_rules.extend(
        sorted(
            rules_by_id.values(),
            key=lambda rule: (
                source_rules[rule.id].bbox.y,
                source_rules[rule.id].bbox.x,
                source_rules[rule.id].bbox.width,
                source_rules[rule.id].bbox.height,
                rule.id,
            ),
        )
    )
    working.text_runs.extend(ir_runs)

    runs_by_element: dict[str, list[Any]] = defaultdict(list)
    for run in ir_runs:
        runs_by_element[run.element_id].append(run)
    all_rules = rules_by_id
    all_bboxes = {
        bbox.id: bbox for bbox in working.bboxes[new_bbox_start:]
    }
    for element_id, element_runs in runs_by_element.items():
        element = elements[element_id]
        element_runs.sort(
            key=lambda run: (
                _target_path_key(run.target_path),
                run.start,
                run.end,
                run.id,
            )
        )
        element.text_run_ids.extend(run.id for run in element_runs)
        legacy = element.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            raise _Refusal("text_run_projection_failed_closed")
        public = dict(legacy)
        public_runs: list[dict[str, Any]] = []
        linked_rule_ids: set[str] = set()
        for run in element_runs:
            bbox = all_bboxes[run.bbox_id]
            public_runs.append(
                {
                    "id": run.id,
                    "element_id": run.element_id,
                    "target_path": list(run.target_path),
                    "text": run.text,
                    "source_text": run.source_text,
                    "start": run.start,
                    "end": run.end,
                    **(
                        {"change_group_id": run.change_group_id}
                        if run.change_group_id is not None
                        else {}
                    ),
                    "bbox": _public_bbox_dict(bbox),
                    "font_name": run.font_name,
                    "font_size": run.font_size,
                    "bold": run.bold,
                    "italic": run.italic,
                    "color": _public_color(run.color),
                    "change_state": run.change_state,
                    "decorations": list(run.decorations),
                    "placeholder": run.placeholder,
                    "rule_ids": list(run.rule_ids),
                    "evidence_method": run.evidence_method.value,
                    "semantic_derivation": run.semantic_derivation,
                    "extraction_policy_id": run.extraction_policy_id,
                    "association_policy_id": run.association_policy_id,
                }
            )
            linked_rule_ids.update(run.rule_ids)
        public_rules: list[dict[str, Any]] = []
        for rule_id in sorted(
            linked_rule_ids,
            key=lambda identifier: (
                all_bboxes[all_rules[identifier].bbox_id].y,
                all_bboxes[all_rules[identifier].bbox_id].x,
                all_bboxes[all_rules[identifier].bbox_id].width,
                all_bboxes[all_rules[identifier].bbox_id].height,
                identifier,
            ),
        ):
            rule = all_rules[rule_id]
            bbox = all_bboxes[rule.bbox_id]
            public_rules.append(
                {
                    "id": rule.id,
                    "bbox": _public_bbox_dict(bbox),
                    "source_object_kind": rule.source_object_kind,
                    "source_object_index": rule.source_object_index,
                    "color": _public_color(rule.color),
                    "width": rule.width,
                    "thickness": rule.thickness,
                    "evidence_method": rule.evidence_method.value,
                    "extraction_policy_id": rule.extraction_policy_id,
                }
            )
        public["text_run_policy"] = TEXT_RUN_POLICY_ID
        public["text_runs"] = public_runs
        public["text_rules"] = public_rules

        scalar_runs = [
            run for run in element_runs if tuple(run.target_path) == ("value",)
        ]
        scalar_value = public.get("value")
        if scalar_runs and isinstance(scalar_value, str):
            rendered_body = _render_scalar_markdown(
                scalar_value,
                scalar_runs,
                # Markdown headings already carry semantic emphasis. Avoid
                # redundant strong markers while retaining inline source
                # emphasis for ordinary text, headers, and footers.
                include_emphasis=element.type.casefold() != "heading",
            )
            redline_markdown = _apply_markdown_envelope(
                element,
                public,
                rendered_body,
            )
            if redline_markdown is not None:
                active, omitted_ids = _active_text(
                    scalar_value,
                    scalar_runs,
                )
                public["redline_markdown"] = redline_markdown
                public["active_text"] = active
                public["active_text_omitted_run_ids"] = omitted_ids
                public["active_text_policy"] = ACTIVE_TEXT_POLICY_ID
                public["md"] = redline_markdown
                element.markdown = redline_markdown
                if _entire_heading_is_source_deleted(
                    element,
                    scalar_value,
                    scalar_runs,
                    run_bbox=(
                        all_bboxes.get(scalar_runs[0].bbox_id)
                        if len(scalar_runs) == 1
                        else None
                    ),
                    page_width=source_page.page_width,
                    page_height=source_page.page_height,
                ):
                    public["type"] = "text"
                    public.pop("level", None)
                    public["redline_markdown"] = rendered_body
                    public["md"] = rendered_body
                    element.type = "text"
                    element.markdown = rendered_body
        element.properties["legacy_item"] = public
        element.properties["text_run_projection"] = {
            "story": "P03-US05",
            "policy_id": TEXT_RUN_POLICY_ID,
            "source_sha256": working.source_sha256,
        }
    _refine_underlined_subordinate_heading(
        page,
        elements,
        runs_by_element,
    )


@dataclass(frozen=True, slots=True)
class _PageProjectionSnapshot:
    bbox_count: int
    evidence_count: int
    text_rule_count: int
    text_run_count: int
    elements: tuple[tuple[int, Any], ...]


def _snapshot_page_projection(
    ir: Any,
    *,
    element_positions: Sequence[int],
) -> _PageProjectionSnapshot:
    return _PageProjectionSnapshot(
        bbox_count=len(ir.bboxes),
        evidence_count=len(ir.evidence),
        text_rule_count=len(ir.text_rules),
        text_run_count=len(ir.text_runs),
        elements=tuple(
            (position, ir.elements[position].model_copy(deep=True))
            for position in element_positions
        ),
    )


def _rollback_page_projection(
    ir: Any,
    snapshot: _PageProjectionSnapshot,
) -> None:
    del ir.bboxes[snapshot.bbox_count:]
    del ir.evidence[snapshot.evidence_count:]
    del ir.text_rules[snapshot.text_rule_count:]
    del ir.text_runs[snapshot.text_run_count:]
    for position, element in snapshot.elements:
        ir.elements[position] = element


def project_text_run_semantics(
    ir: Any,
    evidence: TextRunEvidence | None,
) -> Any:
    """Return a validated, non-mutating P03-US05 projection."""

    from app.services.ir import DocumentIR

    projection_started = time.perf_counter()
    predecessor = DocumentIR.model_validate(ir.model_dump(mode="json"))
    if predecessor.text_runs or predecessor.text_rules or any(
        element.text_run_ids for element in predecessor.elements
    ):
        markers = [
            element.properties.get("text_run_projection")
            for element in predecessor.elements
            if element.text_run_ids
        ]
        if markers and all(
            isinstance(marker, Mapping)
            and marker.get("story") == "P03-US05"
            and marker.get("policy_id") == TEXT_RUN_POLICY_ID
            and marker.get("source_sha256") == predecessor.source_sha256
            for marker in markers
        ):
            return predecessor
        failed = predecessor.model_copy(deep=True)
        _add_projection_concern(
            failed,
            code="text_run_projection_failed_closed",
        )
        return DocumentIR.model_validate(failed.model_dump(mode="json"))
    working = predecessor.model_copy(deep=True)
    _restore_predecessor_public_projection(working)
    if evidence is None:
        failed = working
        _add_projection_concern(
            failed,
            code="text_run_source_unsupported",
        )
        return DocumentIR.model_validate(failed.model_dump(mode="json"))
    if (
        not evidence.usable
        or evidence.source_sha256 != working.source_sha256
        or evidence.policy_id != TEXT_RUN_POLICY_ID
    ):
        failed = working
        _add_projection_concern(
            failed,
            code=(
                evidence.refusal_code
                if evidence is not None
                else "text_run_source_unsupported"
            )
            or "text_run_source_invalid",
        )
        return DocumentIR.model_validate(failed.model_dump(mode="json"))

    source_rules = {rule.id: rule for rule in evidence.rules}
    elements_by_id = {element.id: element for element in working.elements}
    coordinates_by_id = {
        coordinate.id: coordinate for coordinate in working.coordinate_systems
    }
    extents_by_coordinate: dict[str, list[Any]] = defaultdict(list)
    for bbox in working.bboxes:
        if bbox.role == "page":
            extents_by_coordinate[bbox.coordinate_system_id].append(bbox)
    element_positions_by_page: dict[str, list[int]] = defaultdict(list)
    for position, element in enumerate(working.elements):
        element_positions_by_page[element.page_id].append(position)
    runs_by_page: dict[int, list[SourceRunEvidence]] = defaultdict(list)
    for run in evidence.runs:
        runs_by_page[run.page_index].append(run)
    pages_by_index = {page.page_index: page for page in working.pages}
    source_pages_by_index = {
        page.page_index: page for page in evidence.pages
    }
    slots_by_page: dict[int, list[_TargetSlot]] = {}
    slot_refusals: dict[int, _Refusal] = {}
    preflight_expired_at: int | None = None
    document_slot_count = 0
    document_target_bytes = 0
    for page_index in sorted(runs_by_page):
        page = pages_by_index.get(page_index)
        if page is None:
            continue
        try:
            source_page = source_pages_by_index[page_index]
            extent = _page_extent_for_projection(
                working,
                page,
                coordinates_by_id=coordinates_by_id,
                extents_by_coordinate=extents_by_coordinate,
            )
            if (
                extent is None
                or not math.isclose(
                    extent.x,
                    0.0,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                or not math.isclose(
                    extent.y,
                    0.0,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                or not math.isclose(
                    extent.width,
                    source_page.page_width,
                    rel_tol=0.0,
                    abs_tol=1e-6,
                )
                or not math.isclose(
                    extent.height,
                    source_page.page_height,
                    rel_tol=0.0,
                    abs_tol=1e-6,
                )
            ):
                raise _Refusal("text_run_alignment_ambiguous")
            page_slots = _target_slots_for_page(
                working,
                page,
                started=projection_started,
                elements_by_id=elements_by_id,
            )
        except _Refusal as exc:
            slot_refusals[page_index] = exc
            if (
                exc.code == "text_run_alignment_limit"
                and time.perf_counter() - projection_started
                > MAX_EXTRACTION_SECONDS
            ):
                preflight_expired_at = page_index
                break
            continue
        document_slot_count += len(page_slots)
        document_target_bytes += sum(
            len(slot.text.encode("utf-8")) for slot in page_slots
        )
        if (
            document_slot_count
            > MAX_TARGET_CANDIDATES_PER_DOCUMENT
            or document_target_bytes
            > MAX_TARGET_TEXT_BYTES_PER_DOCUMENT
        ):
            _add_projection_concern(
                working,
                code="text_run_alignment_limit",
            )
            return DocumentIR.model_validate(
                working.model_dump(mode="json")
            )
        slots_by_page[page_index] = page_slots
    for source_page in evidence.pages:
        page = pages_by_index.get(source_page.page_index)
        if source_page.status == "unavailable":
            _add_projection_concern(
                working,
                code=(
                    source_page.concern_code
                    or "text_run_source_unsupported"
                ),
                page_id=page.id if page is not None else None,
            )
        for concern_code in source_page.concern_codes:
            _add_projection_concern(
                working,
                code=concern_code,
                page_id=page.id if page is not None else None,
            )
    projection_base = working.model_copy(deep=True)
    successful_pages: list[tuple[int, list[_MappedRun]]] = []
    for page_index, page_runs in sorted(runs_by_page.items()):
        if (
            preflight_expired_at is not None
            and page_index >= preflight_expired_at
        ):
            for target in (working, projection_base):
                _add_projection_concern(
                    target,
                    code="text_run_alignment_limit",
                )
            break
        page = pages_by_index.get(page_index)
        if page is None:
            _add_projection_concern(
                working,
                code="text_run_alignment_ambiguous",
            )
            _add_projection_concern(
                projection_base,
                code="text_run_alignment_ambiguous",
            )
            continue
        try:
            if page_index in slot_refusals:
                raise slot_refusals[page_index]
            slots = slots_by_page[page_index]
            mapped = _align_source_runs(
                page_runs,
                slots,
                started=projection_started,
            )
            element_positions = element_positions_by_page[page.id]
            snapshot = _snapshot_page_projection(
                working,
                element_positions=element_positions,
            )
            try:
                _project_page_semantics(
                    working,
                    page=page,
                    source_page=source_pages_by_index[page_index],
                    mapped_runs=mapped,
                    source_rules=source_rules,
                    elements_by_id={
                        working.elements[position].id: working.elements[position]
                        for position in element_positions
                    },
                )
                successful_pages.append((page_index, mapped))
            except Exception:
                _rollback_page_projection(working, snapshot)
                raise
        except Exception as exc:
            concern_code = (
                exc.code
                if isinstance(exc, _Refusal)
                else "text_run_projection_failed_closed"
            )
            for target in (working, projection_base):
                _add_projection_concern(
                    target,
                    code=concern_code,
                    page_id=page.id,
                    error_type=type(exc).__name__,
                )
            if (
                concern_code == "text_run_alignment_limit"
                and time.perf_counter() - projection_started
                > MAX_EXTRACTION_SECONDS
            ):
                for target in (working, projection_base):
                    _add_projection_concern(
                        target,
                        code="text_run_alignment_limit",
                    )
                break
    try:
        return DocumentIR.model_validate(working.model_dump(mode="json"))
    except Exception:
        # Valid pages take the O(document) commit path above. Only a combined
        # graph failure enters this diagnostic replay to isolate bad pages.
        replay = projection_base
        replay_pages = {page.page_index: page for page in replay.pages}
        for page_index, mapped in successful_pages:
            page = replay_pages[page_index]
            element_positions = element_positions_by_page[page.id]
            snapshot = _snapshot_page_projection(
                replay,
                element_positions=element_positions,
            )
            try:
                _project_page_semantics(
                    replay,
                    page=page,
                    source_page=source_pages_by_index[page_index],
                    mapped_runs=mapped,
                    source_rules=source_rules,
                    elements_by_id={
                        replay.elements[position].id: replay.elements[position]
                        for position in element_positions
                    },
                )
                replay = DocumentIR.model_validate(
                    replay.model_dump(mode="json")
                )
            except Exception as exc:
                _rollback_page_projection(replay, snapshot)
                _add_projection_concern(
                    replay,
                    code=(
                        exc.code
                        if isinstance(exc, _Refusal)
                        else "text_run_projection_failed_closed"
                    ),
                    page_id=page.id,
                    error_type=type(exc).__name__,
                )
        return DocumentIR.model_validate(replay.model_dump(mode="json"))
