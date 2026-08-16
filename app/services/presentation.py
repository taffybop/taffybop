"""Canonical Markdown and semantic-text views derived from the internal IR."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import unicodedata
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from html import escape
from typing import Any, Literal, Mapping, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

from app.models import PageIdentity

from app.services.ir import (
    DocumentIR,
    ElementRecord,
    EvidenceMethod,
    RelationshipRecord,
    RelationshipType,
)
from app.services.visual_contracts import VisualStructure
from app.services.visual_model_contracts import VisualModelEvidenceBundle
from app.services.source_note_contracts import is_source_note_owner_item


PRESENTATION_SCHEMA_VERSION = "1.0"
PRESENTATION_POLICY_ID = "canonical-presentation-v1"
_VISUAL_TYPES = frozenset({"image", "chart", "diagram"})
_STRUCTURED_OWNER_TYPES = frozenset(
    {"table", "list", "header", "footer", "form", "key_value"}
)
_FORM_SEMANTIC_RELATIONSHIP_TYPES = frozenset(
    {
        RelationshipType.LABEL_OF,
        RelationshipType.VALUE_OF,
        RelationshipType.CONTROL_OF,
        RelationshipType.KEY_OF,
        RelationshipType.FORM_OVERLAY_OF,
    }
)
_OUTLINE_RELATIONSHIP_TYPES = frozenset(
    {
        RelationshipType.OUTLINE_PARENT_OF,
        RelationshipType.OUTLINE_NEXT,
        RelationshipType.OUTLINE_CONTINUATION_OF,
    }
)
_TRUSTED_CAPTION_METHODS = frozenset(
    {
        EvidenceMethod.NATIVE,
        EvidenceMethod.VECTOR,
        EvidenceMethod.EMBEDDED,
        EvidenceMethod.RECOVERED,
        EvidenceMethod.MODEL,
    }
)
_CLAIM_PRIORITY = {
    "caption": 0,
    "structure": 1,
    "ocr": 2,
    "source_note": 3,
    "footnote": 4,
}


class PresentationModel(BaseModel):
    """Strict base for the independently versioned additive contract."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ExcludedContribution(PresentationModel):
    element_id: str
    reason: Literal[
        "already_claimed",
        "alternate_representation",
        "caption_precedes_subordinate_ocr",
        "empty_contribution",
        "evidence_only_relationship",
        "overlapping_visual_table",
        "rejected_caption",
        "rejected_ocr",
        "unapproved_caption",
        "unapproved_ocr",
    ]
    relationship_ids: list[str]

    @model_validator(mode="after")
    def validate_unique_relationships(self) -> "ExcludedContribution":
        if len(self.relationship_ids) != len(set(self.relationship_ids)):
            raise ValueError("excluded contribution repeats a relationship")
        return self


class CanonicalBlock(PresentationModel):
    id: str
    page_id: str
    primary_element_id: str
    primary_element_type: str
    scope: Literal["body", "header", "footer"]
    markdown: str
    text: str
    contributing_element_ids: list[str]
    relationship_ids: list[str]
    excluded_contributions: list[ExcludedContribution]
    omission_reason: (
        Literal[
            "alternate_representation",
            "consumed_by_relationship",
            "empty_content",
            "empty_visual",
            "overlapping_visual_table",
            "source_contradicted_primary_ocr",
            "unsupported_primary_ocr",
        ]
        | None
    ) = None
    suppressed_by_element_id: str | None = None

    @model_validator(mode="after")
    def validate_block(self) -> "CanonicalBlock":
        expected_scope: Literal["body", "header", "footer"]
        element_type = self.primary_element_type.casefold()
        if element_type == "header":
            expected_scope = "header"
        elif element_type == "footer":
            expected_scope = "footer"
        else:
            expected_scope = "body"
        if self.scope != expected_scope:
            raise ValueError(
                "canonical block scope must match its primary element type"
            )
        if len(self.contributing_element_ids) != len(
            set(self.contributing_element_ids)
        ):
            raise ValueError("canonical block repeats a contributing element")
        if len(self.relationship_ids) != len(set(self.relationship_ids)):
            raise ValueError("canonical block repeats a relationship")
        exclusion_keys = [
            (entry.element_id, entry.reason) for entry in self.excluded_contributions
        ]
        if len(exclusion_keys) != len(set(exclusion_keys)):
            raise ValueError("canonical block repeats an exclusion")
        for exclusion in self.excluded_contributions:
            if not set(exclusion.relationship_ids).issubset(self.relationship_ids):
                raise ValueError(
                    "excluded-contribution relationship IDs must be "
                    "recorded by their canonical block"
                )
        if self.omission_reason is None:
            if not self.contributing_element_ids:
                raise ValueError("an included block requires contributing elements")
            if self.contributing_element_ids[0] != self.primary_element_id:
                raise ValueError("the primary element must be the first contribution")
            if not self.markdown and not self.text:
                raise ValueError("an included block cannot be empty")
            if len(self.contributing_element_ids) > 1 and not self.relationship_ids:
                raise ValueError(
                    "a multi-element included block requires an asserting relationship"
                )
            if self.suppressed_by_element_id is not None:
                raise ValueError(
                    "an included block cannot declare a suppressing element"
                )
        else:
            if self.markdown or self.text or self.contributing_element_ids:
                raise ValueError("an omitted block cannot present content")
            if self.suppressed_by_element_id == self.primary_element_id:
                raise ValueError("an omitted block cannot suppress itself")
            if (
                self.omission_reason
                in {
                    "alternate_representation",
                    "consumed_by_relationship",
                    "overlapping_visual_table",
                }
                and not self.suppressed_by_element_id
            ):
                raise ValueError("relationship/overlap omission requires a suppressor")
            if (
                self.omission_reason
                in {
                    "empty_content",
                    "empty_visual",
                    "source_contradicted_primary_ocr",
                    "unsupported_primary_ocr",
                }
                and self.suppressed_by_element_id is not None
            ):
                raise ValueError("an intrinsic omission cannot declare a suppressor")
            if (
                self.omission_reason == "overlapping_visual_table"
                and element_type != "table"
            ):
                raise ValueError("only a table can declare an overlap omission")
            if (
                self.omission_reason
                in {
                    "empty_visual",
                    "unsupported_primary_ocr",
                }
                and element_type not in _VISUAL_TYPES
            ):
                raise ValueError("visual omission reasons require a visual primary")
            if (
                self.omission_reason == "empty_content"
                and element_type in _VISUAL_TYPES
            ):
                raise ValueError("a visual primary cannot declare empty_content")
            if self.omission_reason == "source_contradicted_primary_ocr":
                if element_type not in {"text", "heading"}:
                    raise ValueError(
                        "source-contradicted OCR omission requires a text primary"
                    )
                if self.relationship_ids or self.excluded_contributions:
                    raise ValueError(
                        "source-contradicted OCR omission requires closed ownership"
                    )
        if self.markdown != self.markdown.strip():
            raise ValueError("block Markdown must not have outer whitespace")
        if self.text != self.text.strip():
            raise ValueError("block text must not have outer whitespace")
        return self


class CanonicalView(PresentationModel):
    block_ids: list[str]
    markdown: str
    text: str

    @model_validator(mode="after")
    def validate_view(self) -> "CanonicalView":
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("canonical view repeats a block")
        if not self.block_ids and (self.markdown or self.text):
            raise ValueError("an empty canonical view cannot contain content")
        if self.block_ids:
            if self.markdown and (
                not self.markdown.endswith("\n") or self.markdown.endswith("\n\n")
            ):
                raise ValueError("canonical Markdown must end with exactly one newline")
            if self.text and (
                not self.text.endswith("\n") or self.text.endswith("\n\n")
            ):
                raise ValueError("canonical text must end with exactly one newline")
        return self


class CanonicalPage(PresentationModel):
    page_id: str
    page_index: int = Field(ge=1)
    page_number: int | str
    page_label: str
    blocks: list[CanonicalBlock]
    full: CanonicalView
    body: CanonicalView
    header: CanonicalView
    footer: CanonicalView
    page_identity: PageIdentity | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_page(self) -> "CanonicalPage":
        if self.page_identity is not None and (
            self.page_identity.page_id != self.page_id
            or self.page_identity.physical_page_index != self.page_index
        ):
            raise ValueError("canonical page identity binding differs")
        block_ids = [block.id for block in self.blocks]
        primary_ids = [block.primary_element_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("canonical page repeats a block id")
        if len(primary_ids) != len(set(primary_ids)):
            raise ValueError("canonical page repeats a primary element")
        if any(block.page_id != self.page_id for block in self.blocks):
            raise ValueError("canonical page contains another page's block")
        primary_rank = {
            primary_id: index for index, primary_id in enumerate(primary_ids)
        }
        blocks_by_primary = {block.primary_element_id: block for block in self.blocks}
        for block in self.blocks:
            if block.omission_reason != "overlapping_visual_table":
                continue
            suppressor = blocks_by_primary.get(block.suppressed_by_element_id)
            if (
                suppressor is None
                or suppressor.primary_element_type.casefold() not in _VISUAL_TYPES
                or primary_rank[suppressor.primary_element_id]
                >= primary_rank[block.primary_element_id]
            ):
                raise ValueError(
                    "an overlap suppressor must be a preceding visual "
                    "primary on the same page"
                )
        _require_matching_view(self.full, self.blocks)
        _require_matching_view(
            self.body,
            [block for block in self.blocks if block.scope == "body"],
        )
        _require_matching_view(
            self.header,
            [block for block in self.blocks if block.scope == "header"],
        )
        _require_matching_view(
            self.footer,
            [block for block in self.blocks if block.scope == "footer"],
        )
        return self


class CanonicalPresentation(PresentationModel):
    schema_version: Literal["1.0"]
    source_ir_version: Literal["1.0"]
    policy_id: Literal["canonical-presentation-v1"]
    pages: list[CanonicalPage]
    full: CanonicalView
    body: CanonicalView
    header: CanonicalView
    footer: CanonicalView

    @model_validator(mode="after")
    def validate_document(self, info: ValidationInfo) -> "CanonicalPresentation":
        page_ids = [page.page_id for page in self.pages]
        page_indexes = [page.page_index for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("canonical presentation repeats a page id")
        if len(page_indexes) != len(set(page_indexes)):
            raise ValueError("canonical presentation repeats a page index")
        if page_indexes != sorted(page_indexes):
            raise ValueError(
                "canonical presentation pages must be ordered by page index"
            )

        blocks = [block for page in self.pages for block in page.blocks]
        block_ids = [block.id for block in blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("canonical presentation repeats a block id")
        primary_ids = [block.primary_element_id for block in blocks]
        if len(primary_ids) != len(set(primary_ids)):
            raise ValueError("canonical presentation repeats a primary element")
        claimed = [
            element_id
            for block in blocks
            if block.omission_reason is None
            for element_id in block.contributing_element_ids
        ]
        if len(claimed) != len(set(claimed)):
            raise ValueError("an element contributes to more than one canonical block")
        if not (
            isinstance(info.context, Mapping)
            and info.context.get("allow_unresolved_suppressors") is True
        ):
            presented = set(claimed)
            primary_blocks = {block.primary_element_id: block for block in blocks}
            included_owner_by_contribution = {
                element_id: block.primary_element_id
                for block in blocks
                if block.omission_reason is None
                for element_id in block.contributing_element_ids
            }
            for block in blocks:
                for exclusion in block.excluded_contributions:
                    if (
                        exclusion.reason == "already_claimed"
                        and exclusion.element_id not in presented
                    ):
                        raise ValueError(
                            "an already_claimed exclusion must resolve to "
                            "a presented element"
                        )
                if (
                    block.omission_reason is not None
                    and block.omission_reason != "consumed_by_relationship"
                    and block.primary_element_id in presented
                ):
                    raise ValueError(
                        "only a consumed omission may transfer its primary "
                        "element into presented contributions"
                    )
                if block.omission_reason not in {
                    "alternate_representation",
                    "consumed_by_relationship",
                    "overlapping_visual_table",
                }:
                    continue
                if block.omission_reason == "overlapping_visual_table":
                    suppressor = primary_blocks.get(block.suppressed_by_element_id)
                    if (
                        suppressor is None
                        or suppressor.primary_element_type.casefold()
                        not in _VISUAL_TYPES
                    ):
                        raise ValueError(
                            "an overlap suppressor must resolve to a "
                            "canonical visual primary"
                        )
                elif block.suppressed_by_element_id not in presented:
                    raise ValueError("a suppressor must resolve to a presented element")
                if (
                    block.omission_reason == "consumed_by_relationship"
                    and included_owner_by_contribution.get(block.primary_element_id)
                    != block.suppressed_by_element_id
                ):
                    raise ValueError(
                        "a consumed primary element must be transferred "
                        "to its declared owner block"
                    )
                if block.omission_reason in {
                    "alternate_representation",
                    "consumed_by_relationship",
                }:
                    expected_reason = (
                        "alternate_representation"
                        if block.omission_reason == "alternate_representation"
                        else "already_claimed"
                    )
                    suppressor_exclusions = [
                        exclusion
                        for exclusion in block.excluded_contributions
                        if (
                            exclusion.element_id == block.suppressed_by_element_id
                            and exclusion.reason == expected_reason
                        )
                    ]
                    if (
                        not block.relationship_ids
                        or not suppressor_exclusions
                        or any(
                            not exclusion.relationship_ids
                            or not set(exclusion.relationship_ids).issubset(
                                block.relationship_ids
                            )
                            for exclusion in suppressor_exclusions
                        )
                    ):
                        raise ValueError(
                            "a relationship omission requires asserting "
                            "relationship IDs and a matching suppressor "
                            "exclusion"
                        )
                    if block.omission_reason == "consumed_by_relationship":
                        owner_block = primary_blocks[block.suppressed_by_element_id]
                        consuming_ids = {
                            relationship_id
                            for exclusion in suppressor_exclusions
                            for relationship_id in exclusion.relationship_ids
                        }
                        if not consuming_ids.issubset(owner_block.relationship_ids):
                            raise ValueError(
                                "consumption relationship IDs must also be "
                                "recorded by the declared owner block"
                            )

        _require_matching_view(self.full, blocks)
        _require_matching_view(
            self.body,
            [block for block in blocks if block.scope == "body"],
        )
        _require_matching_view(
            self.header,
            [block for block in blocks if block.scope == "header"],
        )
        _require_matching_view(
            self.footer,
            [block for block in blocks if block.scope == "footer"],
        )
        return self


@dataclass(frozen=True)
class _EdgeGroup:
    type: RelationshipType
    source_id: str
    target_id: str
    relationships: tuple[RelationshipRecord, ...]

    @property
    def relationship_ids(self) -> tuple[str, ...]:
        return tuple(sorted(relationship.id for relationship in self.relationships))


@dataclass(frozen=True)
class _Claim:
    kind: Literal[
        "caption",
        "structure",
        "ocr",
        "source_note",
        "footnote",
    ]
    owner_id: str
    source_id: str
    edge: _EdgeGroup
    owner_rank: int
    nested_visual_id: str | None = None
    bridge_edge: _EdgeGroup | None = None
    output_override: tuple[str, str] | None = None
    requires_bridge: bool = False


@dataclass(frozen=True)
class _NestedVisualSpec:
    owner_id: str
    visual_id: str
    structure_edge: _EdgeGroup
    owner_rank: int


@dataclass(frozen=True)
class _VisualBox:
    anchor_rank: int
    element: ElementRecord
    box: tuple[float, float, float, float]

    @property
    def left(self) -> float:
        return self.box[0]

    @property
    def top(self) -> float:
        return self.box[1]

    @property
    def right(self) -> float:
        return self.box[0] + self.box[2]

    @property
    def bottom(self) -> float:
        return self.box[1] + self.box[3]


@dataclass
class _IntervalNode:
    center: float
    by_left: tuple[_VisualBox, ...]
    by_right: tuple[_VisualBox, ...]
    left: "_IntervalNode | None" = None
    right: "_IntervalNode | None" = None


def _build_interval_index(
    records: Sequence[_VisualBox],
) -> _IntervalNode | None:
    if not records:
        return None
    endpoints = sorted(
        coordinate for record in records for coordinate in (record.left, record.right)
    )
    center = endpoints[len(endpoints) // 2]
    left_records: list[_VisualBox] = []
    right_records: list[_VisualBox] = []
    crossing: list[_VisualBox] = []
    for record in records:
        if record.right < center:
            left_records.append(record)
        elif record.left > center:
            right_records.append(record)
        else:
            crossing.append(record)
    return _IntervalNode(
        center=center,
        by_left=tuple(
            sorted(
                crossing,
                key=lambda record: (
                    record.left,
                    record.anchor_rank,
                    record.element.id,
                ),
            )
        ),
        by_right=tuple(
            sorted(
                crossing,
                key=lambda record: (
                    -record.right,
                    record.anchor_rank,
                    record.element.id,
                ),
            )
        ),
        left=_build_interval_index(left_records),
        right=_build_interval_index(right_records),
    )


def _query_interval_index(
    node: _IntervalNode | None,
    x: float,
) -> list[_VisualBox]:
    matches: list[_VisualBox] = []
    current = node
    while current is not None:
        if x < current.center:
            for record in current.by_left:
                if record.left > x:
                    break
                matches.append(record)
            current = current.left
        elif x > current.center:
            for record in current.by_right:
                if record.right < x:
                    break
                matches.append(record)
            current = current.right
        else:
            matches.extend(current.by_left)
            break
    return matches


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = _canonical_json(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _plain_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        lines = []
        for key in sorted(value, key=str):
            rendered = _plain_value(value[key])
            if rendered:
                lines.append(f"{key}: {rendered}")
        return "\n".join(lines).strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if all(
            isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray))
            for row in value
        ):
            return _rows_text(value)
        return "\n".join(
            rendered for item in value if (rendered := _plain_value(item))
        ).strip()
    return str(value).strip()


def _rows_text(rows: Sequence[Any]) -> str:
    rendered_rows: list[str] = []
    for row in rows:
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            rendered_rows.append("\t".join(_plain_value(cell) for cell in row).rstrip())
        else:
            rendered_rows.append(_plain_value(row))
    return "\n".join(rendered_rows).strip()


def _render_values(values: Sequence[str]) -> str:
    cleaned = [value.strip() for value in values if value.strip()]
    return "\n\n".join(cleaned).rstrip() + "\n" if cleaned else ""


def _view_for(blocks: Sequence[CanonicalBlock]) -> CanonicalView:
    included = [block for block in blocks if block.omission_reason is None]
    return CanonicalView(
        block_ids=[block.id for block in included],
        markdown=_render_values([block.markdown for block in included]),
        text=_render_values([block.text for block in included]),
    )


def _require_matching_view(
    view: CanonicalView,
    blocks: Sequence[CanonicalBlock],
) -> None:
    expected = _view_for(blocks)
    if view.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError("canonical view does not match its ordered blocks")


def omit_source_contradicted_primary_ocr(
    raw_presentation: Any,
    primary_element_ids: Sequence[str],
) -> CanonicalPresentation:
    """Transactionally omit source-disproved primary OCR blocks.

    Source and render ownership are intentionally proved by the caller.  This
    helper accepts only the corresponding closed canonical predecessor shape,
    updates no unrelated block, and regenerates all canonical views.
    """

    raw_dump = getattr(raw_presentation, "model_dump", None)
    detached = (
        raw_dump(mode="json")
        if callable(raw_dump)
        else deepcopy(raw_presentation)
    )
    baseline = CanonicalPresentation.model_validate(detached, strict=True)
    if (
        not isinstance(primary_element_ids, Sequence)
        or isinstance(primary_element_ids, (str, bytes, bytearray))
        or not primary_element_ids
        or any(
            not isinstance(identifier, str) or not identifier
            for identifier in primary_element_ids
        )
        or len(primary_element_ids) != len(set(primary_element_ids))
    ):
        raise ValueError("canonical OCR omission identities are invalid")

    targets = set(primary_element_ids)
    candidate = baseline.model_copy(deep=True)
    matched: set[str] = set()
    for page in candidate.pages:
        for block in page.blocks:
            if block.primary_element_id not in targets:
                continue
            if (
                block.omission_reason is not None
                or block.primary_element_type.casefold() not in {"text", "heading"}
                or block.contributing_element_ids != [block.primary_element_id]
                or block.relationship_ids
                or block.excluded_contributions
                or block.suppressed_by_element_id is not None
                or (not block.markdown and not block.text)
            ):
                raise ValueError("canonical OCR omission predecessor differs")
            matched.add(block.primary_element_id)
            block.markdown = ""
            block.text = ""
            block.contributing_element_ids = []
            block.relationship_ids = []
            block.excluded_contributions = []
            block.omission_reason = "source_contradicted_primary_ocr"
            block.suppressed_by_element_id = None

        page.full = _view_for(page.blocks)
        page.body = _view_for(
            [block for block in page.blocks if block.scope == "body"]
        )
        page.header = _view_for(
            [block for block in page.blocks if block.scope == "header"]
        )
        page.footer = _view_for(
            [block for block in page.blocks if block.scope == "footer"]
        )
    if matched != targets:
        raise ValueError("canonical OCR omission target differs")

    blocks = [block for page in candidate.pages for block in page.blocks]
    candidate.full = _view_for(blocks)
    candidate.body = _view_for(
        [block for block in blocks if block.scope == "body"]
    )
    candidate.header = _view_for(
        [block for block in blocks if block.scope == "header"]
    )
    candidate.footer = _view_for(
        [block for block in blocks if block.scope == "footer"]
    )
    validated = CanonicalPresentation.model_validate(
        candidate.model_dump(mode="json"),
        strict=True,
    )

    baseline_pages = {page.page_id: page for page in baseline.pages}
    for page in validated.pages:
        before = baseline_pages.get(page.page_id)
        if before is None or [block.id for block in page.blocks] != [
            block.id for block in before.blocks
        ]:
            raise ValueError("canonical OCR omission block order differs")
        before_blocks = {block.id: block for block in before.blocks}
        for block in page.blocks:
            prior = before_blocks[block.id]
            if block.primary_element_id not in targets and (
                block.model_dump(mode="json", exclude_none=True)
                != prior.model_dump(mode="json", exclude_none=True)
            ):
                raise ValueError("canonical OCR omission changed another block")
    return validated


def augment_canonical_visual_model_evidence(
    raw_presentation: Any,
    public_pages: Any,
) -> CanonicalPresentation:
    """Transactionally append accepted model evidence to an existing graph.

    This deliberately does not rebuild canonical presentation.  It validates
    the Phase 05 contract first, binds each public primary item to the existing
    page/block in exact order, modifies only block Markdown/text, recomputes
    views, then validates the entire candidate before returning it.
    """

    raw_dump = getattr(raw_presentation, "model_dump", None)
    detached_presentation = (
        raw_dump(mode="json") if callable(raw_dump) else deepcopy(raw_presentation)
    )
    baseline = CanonicalPresentation.model_validate(
        detached_presentation,
        strict=True,
    )
    if not isinstance(public_pages, Sequence) or isinstance(
        public_pages,
        (str, bytes, bytearray),
    ):
        raise ValueError("public pages must be a sequence")
    if len(public_pages) != len(baseline.pages):
        raise ValueError("public/canonical page count differs")

    baseline_document_blocks = [
        block for page in baseline.pages for block in page.blocks
    ]
    if baseline.full.block_ids != [
        block.id
        for block in baseline_document_blocks
        if block.omission_reason is None
    ]:
        raise ValueError("canonical block order differs from document view")

    candidate = baseline.model_copy(deep=True)
    seen_observation_ids: set[str] = set()
    augmented = False
    for page_offset, (raw_page, canonical_page) in enumerate(
        zip(public_pages, candidate.pages),
    ):
        raw_page_dump = getattr(raw_page, "model_dump", None)
        if callable(raw_page_dump):
            raw_page = raw_page_dump(mode="json", exclude_none=True)
        if not isinstance(raw_page, Mapping):
            raise ValueError(f"public page {page_offset} must be an object")
        raw_page_index = raw_page.get("page_index")
        if (
            not isinstance(raw_page_index, int)
            or isinstance(raw_page_index, bool)
            or raw_page_index != canonical_page.page_index
        ):
            raise ValueError("public/canonical page identity differs")
        raw_items = raw_page.get("items")
        if not isinstance(raw_items, Sequence) or isinstance(
            raw_items,
            (str, bytes, bytearray),
        ):
            raise ValueError("public page items must be a sequence")
        if len(raw_items) != len(canonical_page.blocks):
            raise ValueError("public item/canonical block count differs")
        if canonical_page.full.block_ids != [
            block.id
            for block in canonical_page.blocks
            if block.omission_reason is None
        ]:
            raise ValueError("canonical block order differs from page view")

        for item_offset, (raw_item, block) in enumerate(
            zip(raw_items, canonical_page.blocks),
        ):
            raw_item_dump = getattr(raw_item, "model_dump", None)
            if callable(raw_item_dump):
                raw_item = raw_item_dump(mode="json", exclude_none=True)
            if not isinstance(raw_item, Mapping):
                raise ValueError(
                    f"public item {page_offset}:{item_offset} must be an object"
                )
            item_type = _clean(raw_item.get("type")).casefold()
            if item_type != block.primary_element_type.casefold():
                raise ValueError("public item/canonical block type order differs")
            raw_bundle = raw_item.get("visual_model_evidence")
            if raw_bundle is None:
                continue
            if item_type not in _VISUAL_TYPES:
                raise ValueError("visual-model evidence requires a visual item")
            if block.omission_reason is not None:
                raise ValueError("visual-model evidence owner block is omitted")
            bundle_dump = getattr(raw_bundle, "model_dump", None)
            bundle = VisualModelEvidenceBundle.model_validate(
                (
                    bundle_dump(mode="json")
                    if callable(bundle_dump)
                    else deepcopy(raw_bundle)
                ),
                strict=True,
            )
            if (
                _clean(raw_item.get("id")) != bundle.public_item_id
                or bundle.page_index != canonical_page.page_index
            ):
                raise ValueError("visual-model evidence public ownership differs")
            observation_ids = {
                observation.id for observation in bundle.observations
            }
            if seen_observation_ids & observation_ids:
                raise ValueError("visual-model observation identity repeats")
            seen_observation_ids.update(observation_ids)
            model_markdown, model_text = project_visual_model_evidence(bundle)
            if model_markdown in block.markdown or model_text in block.text:
                raise ValueError("canonical block already contains model evidence")
            block.markdown = "\n\n".join(
                value for value in (block.markdown, model_markdown) if value
            )
            block.text = "\n\n".join(
                value for value in (block.text, model_text) if value
            )
            augmented = True

        canonical_page.full = _view_for(canonical_page.blocks)
        canonical_page.body = _view_for(
            [block for block in canonical_page.blocks if block.scope == "body"]
        )
        canonical_page.header = _view_for(
            [block for block in canonical_page.blocks if block.scope == "header"]
        )
        canonical_page.footer = _view_for(
            [block for block in canonical_page.blocks if block.scope == "footer"]
        )

    if not augmented:
        return baseline
    blocks = [block for page in candidate.pages for block in page.blocks]
    candidate.full = _view_for(blocks)
    candidate.body = _view_for(
        [block for block in blocks if block.scope == "body"]
    )
    candidate.header = _view_for(
        [block for block in blocks if block.scope == "header"]
    )
    candidate.footer = _view_for(
        [block for block in blocks if block.scope == "footer"]
    )
    return CanonicalPresentation.model_validate(
        candidate.model_dump(mode="json"),
        strict=True,
    )


def _legacy_item(element: ElementRecord) -> Mapping[str, Any]:
    legacy = element.properties.get("legacy_item")
    return legacy if isinstance(legacy, Mapping) else {}


@dataclass(frozen=True)
class _StructuredVisualOutput:
    markdown: str
    text: str
    caption_occurrences: int


_VISUAL_MODEL_OBSERVATION_LABELS = {
    "generated_description": "Generated description",
    "visual_identification": "Visual identification",
    "derived_measurement": "Derived measurement",
    "inferred_relationship": "Inferred relationship",
}
_VISUAL_MODEL_MARKDOWN_ESCAPES = frozenset("\\`*_{}[]()#+!|~")


def _visual_model_plain_text(value: Any) -> str:
    """Return bounded contract text without layout or control semantics."""

    normalized = " ".join(str(value).split())
    return "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("C")
    )


def _visual_model_markdown_text(value: Any) -> str:
    plain = _visual_model_plain_text(value)
    markdown_escaped = "".join(
        f"\\{character}"
        if character in _VISUAL_MODEL_MARKDOWN_ESCAPES
        else character
        for character in plain
    )
    # Model text is untrusted even after contract validation.  HTML escaping
    # prevents raw tags while the backslashes above neutralize inline Markdown.
    return escape(markdown_escaped, quote=False)


def project_visual_model_evidence(
    bundle: VisualModelEvidenceBundle,
) -> tuple[str, str]:
    """Project accepted model evidence once, with explicit model provenance.

    The bundle is an additive channel: this helper deliberately renders only
    its observations and never derives or modifies a source caption/value.
    """

    markdown_lines: list[str] = []
    text_lines: list[str] = []
    for observation in bundle.observations:
        label = _VISUAL_MODEL_OBSERVATION_LABELS[observation.observation_type]
        identity = observation.identity
        plain_provenance = _visual_model_plain_text(
            f"origin={observation.origin}; "
            f"adapter={identity.adapter_kind}/{identity.adapter_name}"
            f"@{identity.adapter_version}; "
            f"model={identity.model_name}@{identity.model_version}; "
            f"prompt={identity.prompt_version}; "
            f"model-confidence={observation.confidence.model:.6f}"
        )
        plain_text = _visual_model_plain_text(observation.text)
        markdown_lines.append(
            f"> **Model-generated evidence - {label}** "
            f"({_visual_model_markdown_text(plain_provenance)}): "
            f"{_visual_model_markdown_text(plain_text)}"
        )
        text_lines.append(
            f"Model-generated evidence - {label} "
            f"[{plain_provenance}]: {plain_text}"
        )
    return "\n".join(markdown_lines), "\n".join(text_lines)


def _append_visual_model_evidence(
    element: ElementRecord,
    source_output: tuple[str, str],
) -> tuple[str, str]:
    if not _is_visual_payload(element) or element.visual_model_evidence is None:
        return source_output
    model_markdown, model_text = project_visual_model_evidence(
        element.visual_model_evidence
    )
    source_markdown, source_text = source_output
    return (
        "\n\n".join(
            value for value in (source_markdown, model_markdown) if value
        ),
        "\n\n".join(value for value in (source_text, model_text) if value),
    )


def _structured_visual_output(
    element: ElementRecord,
) -> _StructuredVisualOutput | None:
    """Resolve a closed visual serialization without weakening fallback.

    ``legacy_item`` is the public-owner snapshot retained by the IR.  Strictly
    revalidating its sidecar here keeps canonical presentation independent of
    analyzer internals and makes every invalid state take the predecessor path.
    """

    element_type = element.type.casefold()
    if element_type not in {"chart", "diagram"}:
        return None
    legacy = _legacy_item(element)
    raw_structure = legacy.get("visual_structure")
    model_dump = getattr(raw_structure, "model_dump", None)
    if callable(model_dump):
        raw_structure = model_dump(mode="json")
    if not isinstance(raw_structure, Mapping):
        return None
    try:
        structure = VisualStructure.model_validate(raw_structure, strict=True)
    except (TypeError, ValueError):
        return None
    serialization = structure.serialization
    expected_status = (
        "structured_chart" if element_type == "chart" else "diagram_topology"
    )
    if (
        structure.region.kind != element_type
        or structure.fallback.active
        or serialization is None
        or serialization.status != expected_status
    ):
        return None
    markdown = _clean(serialization.markdown)
    if not markdown:
        return None
    if _clean(legacy.get("caption")) and serialization.caption_occurrences != 1:
        return None
    return _StructuredVisualOutput(
        markdown=markdown,
        text=markdown,
        caption_occurrences=serialization.caption_occurrences,
    )


def _is_visual_payload(element: ElementRecord) -> bool:
    return (
        element.type.casefold() in _VISUAL_TYPES
        or element.properties.get("collection") == "embedded_images"
    )


def _element_output(element: ElementRecord) -> tuple[str, str]:
    markdown = _clean(element.markdown)
    text = _plain_value(element.value)
    return markdown or text, text or markdown


def _list_output(element: ElementRecord) -> tuple[str, str]:
    legacy = _legacy_item(element)
    values = legacy.get("items")
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes, bytearray))
        or not values
    ):
        return _element_output(element)
    ordered = bool(legacy.get("ordered"))
    markdown_lines: list[str] = []
    text_lines: list[str] = []
    for index, entry in enumerate(values, start=1):
        if isinstance(entry, Mapping):
            value = _clean(entry.get("value") or entry.get("text"))
            try:
                level = max(int(entry.get("level") or 0), 0)
            except (TypeError, ValueError):
                level = 0
        else:
            value = _clean(entry)
            level = 0
        if not value:
            continue
        marker = f"{index}." if ordered and level == 0 else "-"
        markdown_lines.append(f"{'  ' * level}{marker} {value}")
        text_lines.append(f"{'  ' * level}{value}")
    if not markdown_lines and not text_lines:
        return _element_output(element)
    return "\n".join(markdown_lines), "\n".join(text_lines)


def _table_span_value(
    cell: Mapping[str, Any],
    *keys: str,
) -> int:
    raw: Any = 1
    field_name = keys[0]
    for key in keys:
        if key in cell:
            raw = cell[key]
            field_name = key
            break
    if raw in (None, ""):
        return 1
    if isinstance(raw, bool):
        raise ValueError(f"canonical table {field_name} must be a positive integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"canonical table {field_name} must be a positive integer"
        ) from exc
    if value < 1 or (isinstance(raw, float) and not raw.is_integer()):
        raise ValueError(f"canonical table {field_name} must be a positive integer")
    return value


def _table_output(element: ElementRecord) -> tuple[str, str]:
    legacy = _legacy_item(element)
    markdown = _clean(element.markdown)
    html = _clean(legacy.get("html"))
    if html:
        markdown = html
    cells = legacy.get("cells") or []

    has_spans = (
        isinstance(cells, Sequence)
        and not isinstance(cells, (str, bytes, bytearray))
        and any(
            isinstance(cell, Mapping)
            and (
                _table_span_value(cell, "row_span", "rowspan") > 1
                or _table_span_value(cell, "col_span", "colspan") > 1
            )
            for cell in cells
        )
    )
    if has_spans and not markdown.casefold().startswith("<table"):
        raise ValueError("canonical table with spans requires an HTML presentation")
    rows = legacy.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        rows = element.value
    text = (
        _rows_text(rows)
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray))
        else _plain_value(rows)
    )
    return markdown, text


def _child_collection_index(
    element: ElementRecord,
) -> tuple[str, int] | None:
    collection = element.properties.get("collection")
    raw_index = element.properties.get("index")
    if not isinstance(collection, str):
        return None
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        return None
    if index < 0:
        return None
    return collection, index


def _replacement_value(output: tuple[str, str]) -> str:
    markdown, text = output
    return (text or markdown).strip()


def _list_output_from_selected_children(
    element: ElementRecord,
    selected_elements: Sequence[ElementRecord],
    declared_elements: Sequence[ElementRecord],
    visual_outputs: Mapping[str, tuple[str, str]],
    selected_structure_by_owner: Mapping[str, Sequence[ElementRecord]],
    declared_structure_by_owner: Mapping[str, Sequence[ElementRecord]],
) -> tuple[str, str]:
    legacy = _legacy_item(element)
    raw_items = legacy.get("items")
    items = (
        list(raw_items)
        if isinstance(raw_items, Sequence)
        and not isinstance(raw_items, (str, bytes, bytearray))
        else []
    )
    selected_ids = {child.id for child in selected_elements}
    declared_by_index = {
        location[1]: child
        for child in declared_elements
        if (location := _child_collection_index(child)) is not None
        and location[0] == "items"
    }
    ordered = bool(legacy.get("ordered"))
    markdown_lines: list[str] = []
    text_lines: list[str] = []
    for raw_index, entry in enumerate(items):
        child = declared_by_index.get(raw_index)
        if child is not None and child.id not in selected_ids:
            continue
        if child is not None and child.id in visual_outputs:
            value = _replacement_value(visual_outputs.get(child.id, ("", "")))
            level = 0
        elif child is not None and child.id in declared_structure_by_owner:
            value = _replacement_value(
                _standard_output(
                    child,
                    selected_structure_by_owner.get(child.id, ()),
                    declared_structure_elements=(
                        declared_structure_by_owner.get(child.id, ())
                    ),
                    visual_outputs=visual_outputs,
                    selected_structure_by_owner=(selected_structure_by_owner),
                    declared_structure_by_owner=(declared_structure_by_owner),
                )
            )
            level = 0
        elif isinstance(entry, Mapping):
            value = _clean(entry.get("value") or entry.get("text"))
            try:
                level = max(int(entry.get("level") or 0), 0)
            except (TypeError, ValueError):
                level = 0
        else:
            value = _clean(entry)
            level = 0
        if not value:
            continue
        marker = f"{raw_index + 1}." if ordered and level == 0 else "-"
        markdown_lines.append(f"{'  ' * level}{marker} {value}")
        text_lines.append(f"{'  ' * level}{value}")

    positioned_ids = {child.id for child in declared_by_index.values()}
    for child in selected_elements:
        if child.id in positioned_ids:
            continue
        output = (
            visual_outputs.get(child.id, ("", ""))
            if child.id in visual_outputs
            else _standard_output(
                child,
                selected_structure_by_owner.get(child.id, ()),
                declared_structure_elements=(
                    declared_structure_by_owner.get(child.id, ())
                ),
                visual_outputs=visual_outputs,
                selected_structure_by_owner=selected_structure_by_owner,
                declared_structure_by_owner=declared_structure_by_owner,
            )
        )
        value = _replacement_value(output)
        if not value:
            continue
        markdown_lines.append(f"- {value}")
        text_lines.append(value)
    return "\n".join(markdown_lines), "\n".join(text_lines)


def _table_cell_position(
    child: ElementRecord,
    legacy_cells: Sequence[Any],
) -> tuple[int, int] | None:
    location = _child_collection_index(child)
    candidates: list[Mapping[str, Any]] = []
    legacy_child = child.properties.get("legacy_child")
    if isinstance(legacy_child, Mapping):
        candidates.append(legacy_child)
    if (
        location is not None
        and location[0] == "cells"
        and location[1] < len(legacy_cells)
        and isinstance(legacy_cells[location[1]], Mapping)
    ):
        candidates.append(legacy_cells[location[1]])

    def integer(values: Mapping[str, Any], keys: Sequence[str]) -> int | None:
        for key in keys:
            if key not in values:
                continue
            try:
                result = int(values[key])
            except (TypeError, ValueError):
                return None
            return result if result >= 0 else None
        return None

    for candidate in candidates:
        row = integer(
            candidate,
            (
                "row",
                "row_index",
                "start_row_offset_idx",
            ),
        )
        column = integer(
            candidate,
            (
                "column",
                "col",
                "column_index",
                "start_col_offset_idx",
            ),
        )
        if row is not None and column is not None:
            return row, column
    return None


def _pipe_table(rows: Sequence[Sequence[Any]]) -> str:
    safe_rows = [
        [
            _plain_value(value)
            .replace("\\", "\\\\")
            .replace("|", "\\|")
            .replace("\n", "<br>")
            for value in row
        ]
        for row in rows
    ]
    if not safe_rows or not any(any(cell for cell in row) for row in safe_rows):
        return ""
    width = max(len(row) for row in safe_rows)
    padded = [row + [""] * (width - len(row)) for row in safe_rows]
    header = f"| {' | '.join(padded[0])} |"
    divider = f"| {' | '.join('---' for _ in range(width))} |"
    body = [f"| {' | '.join(row)} |" for row in padded[1:]]
    return "\n".join((header, divider, *body))


def _span_table_html(
    rows: Sequence[Sequence[Any]],
    cells: Sequence[Any],
) -> str:
    by_row: dict[int, list[tuple[int, Mapping[str, Any]]]] = {}
    for cell in cells:
        if not isinstance(cell, Mapping):
            continue
        try:
            row = int(
                cell.get(
                    "row",
                    cell.get(
                        "row_index",
                        cell.get("start_row_offset_idx"),
                    ),
                )
            )
            column = int(
                cell.get(
                    "column",
                    cell.get(
                        "col",
                        cell.get(
                            "column_index",
                            cell.get("start_col_offset_idx"),
                        ),
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
        if row < 0 or column < 0:
            continue
        by_row.setdefault(row, []).append((column, cell))
    if not by_row:
        raise ValueError(
            "canonical table visual-child redaction requires cell positions"
        )
    rendered_rows: list[str] = []
    for row_index in sorted(by_row):
        rendered_cells: list[str] = []
        for column, cell in sorted(by_row[row_index]):
            value = (
                rows[row_index][column]
                if row_index < len(rows) and column < len(rows[row_index])
                else ""
            )
            row_span = _table_span_value(cell, "row_span", "rowspan")
            col_span = _table_span_value(cell, "col_span", "colspan")
            tag = (
                "th"
                if bool(
                    cell.get("header")
                    or cell.get("is_header")
                    or cell.get("column_header")
                    or cell.get("row_header")
                )
                else "td"
            )
            attributes = ""
            if row_span > 1:
                attributes += f' rowspan="{row_span}"'
            if col_span > 1:
                attributes += f' colspan="{col_span}"'
            rendered_cells.append(
                f"<{tag}{attributes}>{escape(_plain_value(value))}</{tag}>"
            )
        rendered_rows.append(f"<tr>{''.join(rendered_cells)}</tr>")
    return f"<table>{''.join(rendered_rows)}</table>"


def _table_output_from_selected_children(
    element: ElementRecord,
    selected_elements: Sequence[ElementRecord],
    declared_elements: Sequence[ElementRecord],
    visual_outputs: Mapping[str, tuple[str, str]],
    selected_structure_by_owner: Mapping[str, Sequence[ElementRecord]],
    declared_structure_by_owner: Mapping[str, Sequence[ElementRecord]],
) -> tuple[str, str]:
    legacy = _legacy_item(element)
    raw_rows = legacy.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(
        raw_rows, (str, bytes, bytearray)
    ):
        raw_rows = element.value
    rows = [
        list(row)
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray))
        else [row]
        for row in (
            raw_rows
            if isinstance(raw_rows, Sequence)
            and not isinstance(raw_rows, (str, bytes, bytearray))
            else []
        )
    ]
    raw_cells = legacy.get("cells")
    cells = (
        list(raw_cells)
        if isinstance(raw_cells, Sequence)
        and not isinstance(raw_cells, (str, bytes, bytearray))
        else []
    )
    selected_ids = {child.id for child in selected_elements}
    positioned_ids: set[str] = set()
    for child in declared_elements:
        location = _child_collection_index(child)
        if location is None or location[0] != "cells":
            continue
        position = _table_cell_position(child, cells)
        if position is None:
            if child.id not in selected_ids or _is_visual_payload(child):
                raise ValueError(
                    "canonical table child redaction requires a cell position"
                )
            continue
        positioned_ids.add(child.id)
        row, column = position
        while len(rows) <= row:
            rows.append([])
        while len(rows[row]) <= column:
            rows[row].append("")
        if child.id not in selected_ids:
            rows[row][column] = ""
        elif child.id in visual_outputs:
            rows[row][column] = _replacement_value(
                visual_outputs.get(child.id, ("", ""))
            )
        elif child.id in declared_structure_by_owner:
            rows[row][column] = _replacement_value(
                _standard_output(
                    child,
                    selected_structure_by_owner.get(child.id, ()),
                    declared_structure_elements=(
                        declared_structure_by_owner.get(child.id, ())
                    ),
                    visual_outputs=visual_outputs,
                    selected_structure_by_owner=(selected_structure_by_owner),
                    declared_structure_by_owner=(declared_structure_by_owner),
                )
            )

    for child in selected_elements:
        if child.id in positioned_ids:
            continue
        output = (
            visual_outputs.get(child.id, ("", ""))
            if child.id in visual_outputs
            else _standard_output(
                child,
                selected_structure_by_owner.get(child.id, ()),
                declared_structure_elements=(
                    declared_structure_by_owner.get(child.id, ())
                ),
                visual_outputs=visual_outputs,
                selected_structure_by_owner=selected_structure_by_owner,
                declared_structure_by_owner=declared_structure_by_owner,
            )
        )
        value = _replacement_value(output)
        if value:
            rows.append([value])

    has_spans = any(
        isinstance(cell, Mapping)
        and (
            _table_span_value(cell, "row_span", "rowspan") > 1
            or _table_span_value(cell, "col_span", "colspan") > 1
        )
        for cell in cells
    )
    if (
        has_spans
        and not _clean(element.markdown).casefold().startswith("<table")
        and not _clean(legacy.get("html")).casefold().startswith("<table")
    ):
        raise ValueError("canonical table with spans requires an HTML presentation")
    markdown = _span_table_html(rows, cells) if has_spans else _pipe_table(rows)
    return markdown, _rows_text(rows)


def _field_output_from_selected_children(
    element: ElementRecord,
    selected_elements: Sequence[ElementRecord],
    declared_elements: Sequence[ElementRecord],
    visual_outputs: Mapping[str, tuple[str, str]],
    selected_structure_by_owner: Mapping[str, Sequence[ElementRecord]],
    declared_structure_by_owner: Mapping[str, Sequence[ElementRecord]],
) -> tuple[str, str]:
    legacy = _legacy_item(element)
    raw_fields = legacy.get("fields")
    fields = (
        list(raw_fields)
        if isinstance(raw_fields, Sequence)
        and not isinstance(raw_fields, (str, bytes, bytearray))
        else []
    )
    selected_ids = {child.id for child in selected_elements}
    declared_by_index = {
        location[1]: child
        for child in declared_elements
        if (location := _child_collection_index(child)) is not None
        and location[0] == "fields"
    }
    lines: list[str] = []
    for index, field in enumerate(fields):
        child = declared_by_index.get(index)
        if child is not None and child.id not in selected_ids:
            continue
        if isinstance(field, Mapping):
            key = _clean(field.get("key") or field.get("name"))
            value = _clean(field.get("value") or field.get("text"))
        else:
            key = ""
            value = _clean(field)
        if child is not None and child.id in visual_outputs:
            value = _replacement_value(visual_outputs.get(child.id, ("", "")))
        elif child is not None and child.id in declared_structure_by_owner:
            value = _replacement_value(
                _standard_output(
                    child,
                    selected_structure_by_owner.get(child.id, ()),
                    declared_structure_elements=(
                        declared_structure_by_owner.get(child.id, ())
                    ),
                    visual_outputs=visual_outputs,
                    selected_structure_by_owner=(selected_structure_by_owner),
                    declared_structure_by_owner=(declared_structure_by_owner),
                )
            )
        if not value:
            continue
        lines.append(f"{key}: {value}" if key else value)

    positioned_ids = {child.id for child in declared_by_index.values()}
    for child in selected_elements:
        if child.id in positioned_ids:
            continue
        output = (
            visual_outputs.get(child.id, ("", ""))
            if child.id in visual_outputs
            else _standard_output(
                child,
                selected_structure_by_owner.get(child.id, ()),
                declared_structure_elements=(
                    declared_structure_by_owner.get(child.id, ())
                ),
                visual_outputs=visual_outputs,
                selected_structure_by_owner=selected_structure_by_owner,
                declared_structure_by_owner=declared_structure_by_owner,
            )
        )
        value = _replacement_value(output)
        if value:
            lines.append(value)
    rendered = "\n".join(lines)
    return rendered, rendered


def _standard_output(
    element: ElementRecord,
    structure_elements: Sequence[ElementRecord],
    *,
    declared_structure_elements: Sequence[ElementRecord] = (),
    visual_outputs: Mapping[str, tuple[str, str]] | None = None,
    selected_structure_by_owner: Mapping[str, Sequence[ElementRecord]] | None = None,
    declared_structure_by_owner: Mapping[str, Sequence[ElementRecord]] | None = None,
) -> tuple[str, str]:
    element_type = element.type.casefold()
    legacy = _legacy_item(element)
    structured_visual = _structured_visual_output(element)
    if structured_visual is not None:
        return _append_visual_model_evidence(
            element,
            (structured_visual.markdown, structured_visual.text),
        )
    selected_structure_ids = {child.id for child in structure_elements}
    declared_structure_ids = {child.id for child in declared_structure_elements}
    selection_is_identity_neutral = (
        bool(declared_structure_elements)
        and selected_structure_ids == declared_structure_ids
        and not any(_is_visual_payload(child) for child in declared_structure_elements)
    )
    if element_type == "heading":
        value = _plain_value(element.value)
        if not value:
            return _element_output(element)
        try:
            level = min(max(int(legacy.get("level") or 1), 1), 6)
        except (TypeError, ValueError):
            level = 1
        projection = element.properties.get("text_run_projection")
        redline_markdown = _clean(element.markdown)
        if (
            isinstance(projection, Mapping)
            and projection.get("story") == "P03-US05"
            and projection.get("policy_id") == "p03-text-run-semantics-v1"
            and projection.get("source_sha256")
            and legacy.get("text_run_policy") == "p03-text-run-semantics-v1"
            and legacy.get("redline_markdown") == redline_markdown
            and redline_markdown.startswith(f"{'#' * level} ")
        ):
            return redline_markdown, value
        return (f"{'#' * level} {value}" if value else ""), value
    resolved_visual_outputs = visual_outputs or {}
    selected_by_owner = selected_structure_by_owner or {}
    declared_by_owner = declared_structure_by_owner or {}
    if (
        element_type == "list"
        and declared_structure_elements
        and not selection_is_identity_neutral
    ):
        return _list_output_from_selected_children(
            element,
            structure_elements,
            declared_structure_elements,
            resolved_visual_outputs,
            selected_by_owner,
            declared_by_owner,
        )
    if element_type == "list":
        return _list_output(element)
    if (
        element_type == "table"
        and declared_structure_elements
        and not selection_is_identity_neutral
    ):
        return _table_output_from_selected_children(
            element,
            structure_elements,
            declared_structure_elements,
            resolved_visual_outputs,
            selected_by_owner,
            declared_by_owner,
        )
    if element_type == "table":
        return _table_output(element)
    if element_type == "code":
        value = _plain_value(element.value)
        if not value:
            return _element_output(element)
        language = _clean(legacy.get("language"))
        return (
            f"```{language}\n{value}\n```" if value else "",
            value,
        )
    if element_type == "formula":
        value = _plain_value(element.value)
        if not value:
            return _element_output(element)
        return (f"$$\n{value}\n$$" if value else ""), value
    if element_type in {"header", "footer"}:
        if legacy.get("layout_value") is not None and any(
            _is_visual_payload(child) for child in declared_structure_elements
        ):
            raise ValueError(
                "canonical authoritative header/footer with a visual child "
                "requires segmented layout provenance"
            )
        if legacy.get("layout_value") is None:
            child_outputs = [
                (
                    resolved_visual_outputs.get(child.id, ("", ""))
                    if child.id in resolved_visual_outputs
                    else _standard_output(
                        child,
                        selected_by_owner.get(child.id, ()),
                        declared_structure_elements=(
                            declared_by_owner.get(child.id, ())
                        ),
                        visual_outputs=resolved_visual_outputs,
                        selected_structure_by_owner=selected_by_owner,
                        declared_structure_by_owner=declared_by_owner,
                    )
                )
                for child in structure_elements
            ]
            child_markdown = [markdown for markdown, _text in child_outputs if markdown]
            child_text = [text for _markdown, text in child_outputs if text]
            if child_markdown or child_text:
                return (
                    "\n\n".join(child_markdown),
                    "\n\n".join(child_text),
                )
            if declared_structure_elements:
                return "", ""
        return _element_output(element)
    if element_type in {"form", "key_value"} and (
        declared_structure_elements and not selection_is_identity_neutral
    ):
        return _field_output_from_selected_children(
            element,
            structure_elements,
            declared_structure_elements,
            resolved_visual_outputs,
            selected_by_owner,
            declared_by_owner,
        )
    markdown, text = _element_output(element)
    return _append_visual_model_evidence(element, (markdown, text))


def _scope_for(element: ElementRecord) -> Literal["body", "header", "footer"]:
    if element.type.casefold() == "header":
        return "header"
    if element.type.casefold() == "footer":
        return "footer"
    return "body"


def _structured_child_is_represented(
    owner: ElementRecord,
    child: ElementRecord,
) -> bool:
    """Return whether the owner's typed output represents this child."""

    provenance_matches = child.properties.get(
        "parent_element_id"
    ) == owner.id and child.properties.get("collection") in {"items", "cells", "fields"}
    if owner.type.casefold() in {"header", "footer"}:
        has_authoritative_layout = _legacy_item(owner).get("layout_value") is not None
        if child.type.casefold() in _VISUAL_TYPES:
            return has_authoritative_layout and provenance_matches
        if not has_authoritative_layout:
            return True
    return provenance_matches


def _evidence_methods(
    element: ElementRecord,
    evidence_by_id: Mapping[str, Any],
) -> set[EvidenceMethod]:
    return {
        evidence_by_id[evidence_id].method
        for evidence_id in element.evidence_ids
        if evidence_id in evidence_by_id
    }


def _has_ocr(
    element: ElementRecord,
    evidence_by_id: Mapping[str, Any],
) -> bool:
    return EvidenceMethod.OCR in _evidence_methods(element, evidence_by_id)


def _visual_ocr_allowed(element: ElementRecord) -> bool:
    directive = element.presentation.include_subordinate_ocr
    if element.properties.get("region_role") == "content_region":
        return directive is True
    if (
        element.type.casefold() == "image"
        or element.properties.get("collection") == "embedded_images"
    ):
        return directive is not False
    return directive is True


def _proven_visual_owner_output(
    element: ElementRecord,
    *,
    source_document_identity: str,
    page_index: int,
) -> str:
    """Return an exact image-owner value only when its public proof closes."""

    if element.type.casefold() != "image":
        return ""
    legacy = _legacy_item(element)
    try:
        from app.services.layout import _grounded_proven_visual_owner_output

        value, _source, _reason = _grounded_proven_visual_owner_output(
            legacy,
            source_document_identity=source_document_identity,
            page_index=page_index,
        )
    except (MemoryError, TypeError, ValueError):
        return ""
    if (
        not value
        or element.value != value
        or element.markdown != value
    ):
        return ""
    return value


def _independent_visual_native_child_records(
    element: ElementRecord,
    *,
    source_document_identity: str,
    page_index: int,
) -> dict[str, Any]:
    """Return graph-owned native children that a failed owner proof cannot hide."""

    if element.type.casefold() != "image":
        return {"owner_output": "", "owner_source": None, "children": []}
    try:
        from app.services.layout import _independent_visual_native_child_outputs

        return _independent_visual_native_child_outputs(
            _legacy_item(element),
            source_document_identity=source_document_identity,
            page_index=page_index,
        )
    except (MemoryError, TypeError, ValueError):
        return {"owner_output": "", "owner_source": None, "children": []}


def _caption_eligible(
    caption: ElementRecord,
    owner: ElementRecord,
    evidence_by_id: Mapping[str, Any],
) -> bool:
    if caption.presentation.accepted is False:
        return False
    if not any(_element_output(caption)):
        return False
    methods = _evidence_methods(caption, evidence_by_id)
    if methods & _TRUSTED_CAPTION_METHODS:
        return True
    return (
        EvidenceMethod.OCR in methods
        and owner.presentation.include_subordinate_ocr is True
    )


def _relationship_index(edge: _EdgeGroup) -> tuple[float, str]:
    candidates: list[float] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key in {
                    "index",
                    "child_index",
                    "source_child_index",
                    "source_order",
                }:
                    try:
                        candidates.append(float(nested))
                    except (TypeError, ValueError):
                        pass
                elif key == "reference_metadata":
                    collect(nested)
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for nested in value:
                collect(nested)

    for relationship in edge.relationships:
        collect(relationship.metadata)
    return (
        min(candidates) if candidates else math.inf,
        edge.relationship_ids[0],
    )


def _claim_key(claim: _Claim) -> tuple[Any, ...]:
    relation_index, relationship_id = _relationship_index(claim.edge)
    return (
        claim.owner_rank,
        _CLAIM_PRIORITY[claim.kind],
        relation_index,
        relationship_id,
        claim.source_id,
    )


def _assign_claims(claims: Sequence[_Claim]) -> dict[str, _Claim]:
    candidates: dict[str, list[_Claim]] = {}
    for claim in claims:
        candidates.setdefault(claim.source_id, []).append(claim)
    return {
        source_id: min(values, key=_claim_key)
        for source_id, values in candidates.items()
    }


def _assign_stable_claims(
    claims: Sequence[_Claim],
    primary_ids: set[str],
) -> dict[str, _Claim]:
    """Select claims whose owners remain one-level presentation anchors.

    Non-primary sources have no independent PageRecord anchor, so they are
    allocated first. A primary element may then either host contributions or
    contribute to another owner, but never both. This prevents nested and
    cyclic claim graphs from consuming content into a block that is itself
    omitted.
    """

    assignment: dict[str, _Claim] = {}
    owners_with_claims: set[str] = set()
    consumed_primary_ids: set[str] = set()
    ordered = sorted(
        claims,
        key=lambda claim: (
            (
                1
                if (
                    claim.source_id in primary_ids
                    or (
                        claim.bridge_edge is not None
                        and claim.nested_visual_id in primary_ids
                    )
                )
                else 0
            ),
            _claim_key(claim),
        ),
    )
    for claim in ordered:
        if claim.source_id in assignment:
            continue
        if claim.owner_id in consumed_primary_ids:
            continue
        bridge_id = claim.nested_visual_id
        bridge_claim = assignment.get(bridge_id) if bridge_id is not None else None
        if bridge_claim is not None and (
            bridge_claim.owner_id != claim.owner_id
            or bridge_claim.kind not in {"structure", "ocr"}
            or (
                claim.bridge_edge is not None and bridge_claim.edge != claim.bridge_edge
            )
        ):
            continue
        if claim.requires_bridge and bridge_claim is None:
            continue
        if claim.source_id in primary_ids and claim.source_id in owners_with_claims:
            continue
        if (
            bridge_id is not None
            and bridge_id in primary_ids
            and bridge_claim is None
            and bridge_id in owners_with_claims
        ):
            continue
        if (
            bridge_id is not None
            and bridge_claim is None
            and claim.bridge_edge is not None
        ):
            bridge_claim = _Claim(
                "structure",
                claim.owner_id,
                bridge_id,
                claim.bridge_edge,
                claim.owner_rank,
            )
            assignment[bridge_id] = bridge_claim
            owners_with_claims.add(claim.owner_id)
            if bridge_id in primary_ids and claim.owner_id != bridge_id:
                consumed_primary_ids.add(bridge_id)
        assignment[claim.source_id] = claim
        owners_with_claims.add(claim.owner_id)
        if claim.source_id in primary_ids and claim.owner_id != claim.source_id:
            consumed_primary_ids.add(claim.source_id)
    return assignment


def _group_relationships(
    relationships: Sequence[RelationshipRecord],
    elements: Mapping[str, ElementRecord],
) -> list[_EdgeGroup]:
    grouped: dict[
        tuple[RelationshipType, str, str],
        list[RelationshipRecord],
    ] = {}
    for relationship in relationships:
        if relationship.metadata.get("canonical_presentation_inert") is True:
            continue
        source = elements.get(relationship.source_id)
        target = elements.get(relationship.target_id)
        if relationship.metadata.get("canonical_inert") is True and (
            relationship.type in _FORM_SEMANTIC_RELATIONSHIP_TYPES
            or relationship.type in _OUTLINE_RELATIONSHIP_TYPES
            or relationship.metadata.get("outline_policy") == "p03-outline-structure-v1"
            or (
                relationship.type is RelationshipType.CONTAINS
                and (
                    (source is not None and source.form_semantics is not None)
                    or (target is not None and target.form_semantics is not None)
                )
            )
        ):
            continue
        grouped.setdefault(
            (
                relationship.type,
                relationship.source_id,
                relationship.target_id,
            ),
            [],
        ).append(relationship)
    return [
        _EdgeGroup(
            type=relationship_type,
            source_id=source_id,
            target_id=target_id,
            relationships=tuple(sorted(records, key=lambda record: record.id)),
        )
        for (
            relationship_type,
            source_id,
            target_id,
        ), records in grouped.items()
    ]


def _page_box(
    element: ElementRecord,
    boxes: Mapping[str, Any],
    coordinates: Mapping[str, Any],
) -> tuple[float, float, float, float] | None:
    for bbox_id in element.bbox_ids:
        box = boxes.get(bbox_id)
        if box is None:
            continue
        coordinate = coordinates.get(box.coordinate_system_id)
        if coordinate is None or coordinate.transform_to_page is None:
            continue
        a, b, c, d, e, f = coordinate.transform_to_page
        corners = (
            (box.x, box.y),
            (box.x + box.width, box.y),
            (box.x, box.y + box.height),
            (box.x + box.width, box.y + box.height),
        )
        points = [(a * x + c * y + e, b * x + d * y + f) for x, y in corners]
        left = min(x for x, _y in points)
        top = min(y for _x, y in points)
        right = max(x for x, _y in points)
        bottom = max(y for _x, y in points)
        return left, top, right - left, bottom - top
    return None


def _overlap_fraction_of_first(
    first: tuple[float, float, float, float] | None,
    second: tuple[float, float, float, float] | None,
) -> float:
    if first is None or second is None:
        return 0.0
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    left = max(first_x, second_x)
    top = max(first_y, second_y)
    right = min(first_x + first_width, second_x + second_width)
    bottom = min(first_y + first_height, second_y + second_height)
    intersection = max(right - left, 0.0) * max(bottom - top, 0.0)
    first_area = first_width * first_height
    return intersection / first_area if first_area > 0 else 0.0


def _diagnosed_table_suppressors(
    ir: DocumentIR,
    elements: Mapping[str, ElementRecord],
) -> dict[str, str]:
    suppressors: dict[str, str] = {}
    boxes = {box.id: box for box in ir.bboxes}
    coordinates = {coordinate.id: coordinate for coordinate in ir.coordinate_systems}
    page_boxes = {
        element.id: _page_box(element, boxes, coordinates)
        for element in elements.values()
    }
    for page in ir.pages:
        anchor_rank = {
            element_id: index
            for index, element_id in enumerate(page.presentation_element_ids)
        }
        visual_records = [
            _VisualBox(
                anchor_rank=anchor_rank[element_id],
                element=elements[element_id],
                box=page_boxes[element_id],
            )
            for element_id in page.presentation_element_ids
            if elements[element_id].type.casefold() in _VISUAL_TYPES
            and page_boxes[element_id] is not None
        ]
        visual_index = _build_interval_index(visual_records)
        best_visual_tie: ElementRecord | None = None
        for element_id in page.presentation_element_ids:
            element = elements[element_id]
            element_type = element.type.casefold()
            if element_type in _VISUAL_TYPES:
                if best_visual_tie is None or (
                    element.reading_order if element.reading_order is not None else -1,
                    element.id,
                ) > (
                    best_visual_tie.reading_order
                    if best_visual_tie.reading_order is not None
                    else -1,
                    best_visual_tie.id,
                ):
                    best_visual_tie = element
                continue
            if element_type != "table":
                continue
            concerns = _legacy_item(element).get("parse_concerns") or []
            if (
                not isinstance(concerns, Sequence)
                or isinstance(concerns, (str, bytes, bytearray))
                or "contains_empty_visual_rows" not in concerns
            ):
                continue
            table_box = page_boxes[element.id]
            if best_visual_tie is not None and (
                _overlap_fraction_of_first(
                    table_box,
                    page_boxes[best_visual_tie.id],
                )
                >= 1.0
            ):
                suppressors[element.id] = best_visual_tie.id
                continue
            if table_box is None:
                continue
            table_x, table_y, table_width, table_height = table_box
            center_x = table_x + table_width / 2
            center_y = table_y + table_height / 2
            candidates = []
            for record in _query_interval_index(visual_index, center_x):
                if (
                    record.anchor_rank >= anchor_rank[element.id]
                    or center_y < record.top
                    or center_y > record.bottom
                ):
                    continue
                candidates.append(
                    (
                        _overlap_fraction_of_first(
                            table_box,
                            record.box,
                        ),
                        record.element,
                    )
                )
            eligible = [
                (overlap, visual) for overlap, visual in candidates if overlap >= 0.9
            ]
            if eligible:
                _overlap, visual = max(
                    eligible,
                    key=lambda value: (
                        value[0],
                        value[1].reading_order
                        if value[1].reading_order is not None
                        else -1,
                        value[1].id,
                    ),
                )
                suppressors[element.id] = visual.id
    return suppressors


def _add_exclusion(
    values: dict[tuple[str, str], ExcludedContribution],
    *,
    element_id: str,
    reason: str,
    relationship_ids: Sequence[str] = (),
) -> None:
    key = (element_id, reason)
    existing = values.get(key)
    combined = sorted(
        set(existing.relationship_ids if existing is not None else ())
        | set(relationship_ids)
    )
    values[key] = ExcludedContribution(
        element_id=element_id,
        reason=reason,
        relationship_ids=combined,
    )


def _audit_relationship_assertions(
    pages: Sequence[CanonicalPage],
    edge_groups: Sequence[_EdgeGroup],
    elements: Mapping[str, ElementRecord],
) -> None:
    """Retain every presentation/evidence assertion on a relevant block.

    Primary-block auditing cannot see an alternative edge whose endpoints are
    subordinate contributors. First attach alternative assertions to the
    included block that owns an endpoint. Then retain every still-unrecorded
    non-ordering assertion on the earliest block that owns either endpoint, or
    on the earliest endpoint-page block when neither endpoint is presented.
    """

    blocks = [block for page in pages for block in page.blocks]
    if not blocks:
        return
    layout_managed_visual_ids = {
        element.id
        for element in elements.values()
        if element.type.casefold() in _VISUAL_TYPES
        and isinstance(
            element.properties.get("layout_projection"),
            Mapping,
        )
        and element.properties["layout_projection"].get("story") == "P03-US02"
    }
    layout_managed_source_note_owner_ids = {
        element.id
        for element in elements.values()
        if isinstance(
            element.properties.get("source_note_projection"),
            Mapping,
        )
        and element.properties["source_note_projection"].get("story") == "P03-US03"
        and str(_legacy_item(element).get("type") or "").casefold()
        == element.type.casefold()
        and is_source_note_owner_item(_legacy_item(element))
    }
    edge_groups = [
        edge
        for edge in edge_groups
        if not (
            (
                edge.type is RelationshipType.CAPTION_OF
                and edge.target_id in layout_managed_visual_ids
            )
            or (
                edge.type
                in {
                    RelationshipType.SOURCE_NOTE_OF,
                    RelationshipType.FOOTNOTE_OF,
                }
                and edge.target_id in layout_managed_source_note_owner_ids
            )
        )
    ]
    block_rank = {block.id: index for index, block in enumerate(blocks)}
    primary_blocks = {block.primary_element_id: block for block in blocks}
    contribution_blocks = {
        element_id: block
        for block in blocks
        if block.omission_reason is None
        for element_id in block.contributing_element_ids
    }
    page_blocks: dict[str, list[CanonicalBlock]] = {}
    for block in blocks:
        page_blocks.setdefault(block.page_id, []).append(block)

    def add_audit(
        block: CanonicalBlock,
        *,
        related_id: str,
        relationship_ids: Sequence[str],
    ) -> None:
        if not relationship_ids:
            return
        exclusions = {
            (entry.element_id, entry.reason): entry
            for entry in block.excluded_contributions
        }
        _add_exclusion(
            exclusions,
            element_id=related_id,
            reason="evidence_only_relationship",
            relationship_ids=relationship_ids,
        )
        block.relationship_ids = sorted(
            set(block.relationship_ids) | set(relationship_ids)
        )
        block.excluded_contributions = sorted(
            exclusions.values(),
            key=lambda value: (value.element_id, value.reason),
        )

    alternative_edges = sorted(
        (edge for edge in edge_groups if edge.type is RelationshipType.ALTERNATIVE_OF),
        key=lambda edge: (
            _relationship_index(edge),
            edge.source_id,
            edge.target_id,
        ),
    )

    # Included blocks own every direct assertion incident to any of their
    # presented contributors, not only assertions incident to the primary.
    for block in blocks:
        if block.omission_reason is not None:
            continue
        contribution_ids = set(block.contributing_element_ids)
        for edge in alternative_edges:
            if not (
                edge.source_id in contribution_ids or edge.target_id in contribution_ids
            ):
                continue
            missing_ids = sorted(
                set(edge.relationship_ids) - set(block.relationship_ids)
            )
            if not missing_ids:
                continue
            related_id = (
                edge.target_id if edge.source_id in contribution_ids else edge.source_id
            )
            add_audit(
                block,
                related_id=related_id,
                relationship_ids=missing_ids,
            )

    recorded_ids = {
        relationship_id
        for block in blocks
        for relationship_id in block.relationship_ids
    }
    auditable_edges = sorted(
        (
            edge
            for edge in edge_groups
            if edge.type is not RelationshipType.READING_BEFORE
        ),
        key=lambda edge: (
            edge.type.value,
            _relationship_index(edge),
            edge.source_id,
            edge.target_id,
        ),
    )
    for edge in auditable_edges:
        missing_ids = sorted(set(edge.relationship_ids) - recorded_ids)
        if not missing_ids:
            continue
        candidates: dict[str, CanonicalBlock] = {}
        for endpoint_id in (edge.source_id, edge.target_id):
            for block in (
                primary_blocks.get(endpoint_id),
                contribution_blocks.get(endpoint_id),
            ):
                if block is not None:
                    candidates[block.id] = block
        if not candidates:
            endpoint_page_ids = {
                elements[endpoint_id].page_id
                for endpoint_id in (edge.source_id, edge.target_id)
                if endpoint_id in elements
            }
            for page_id in endpoint_page_ids:
                for block in page_blocks.get(page_id, ()):
                    candidates[block.id] = block
        if not candidates:
            candidates[blocks[0].id] = blocks[0]
        block = min(candidates.values(), key=lambda value: block_rank[value.id])
        owned_ids = set(block.contributing_element_ids) | {block.primary_element_id}
        related_id = edge.target_id if edge.source_id in owned_ids else edge.source_id
        add_audit(
            block,
            related_id=related_id,
            relationship_ids=missing_ids,
        )
        recorded_ids.update(missing_ids)


def _alternative_suppressors(
    ir: DocumentIR,
    base: CanonicalPresentation,
    *,
    candidate_source_ids: Sequence[str] = (),
    stable_rank_hints: Mapping[str, tuple[int, int, float, str]] | None = None,
) -> dict[str, str]:
    """Resolve alternatives only through targets that can be presented.

    Strongly connected components make malformed cycles deterministic: the
    earliest anchored member of a terminal cycle remains presented. Chains
    resolve to the final presented representative, while edges to an omitted
    target do not suppress their usable source.
    """

    presented_element_ids = {
        element_id
        for page in base.pages
        for block in page.blocks
        if block.omission_reason is None
        for element_id in block.contributing_element_ids
    }
    included = presented_element_ids | set(candidate_source_ids)
    primary_sequence = [
        element_id
        for page in sorted(ir.pages, key=lambda value: value.page_index)
        for element_id in page.presentation_element_ids
    ]
    primary_rank = {
        element_id: index for index, element_id in enumerate(primary_sequence)
    }
    elements = {element.id: element for element in ir.elements}

    def stable_node_key(
        element_id: str,
    ) -> tuple[int, int, float, str]:
        if stable_rank_hints is not None and element_id in stable_rank_hints:
            return stable_rank_hints[element_id]
        if element_id in primary_rank:
            return primary_rank[element_id], 0, -1.0, element_id
        reading_order = elements[element_id].reading_order
        return (
            len(primary_sequence),
            0,
            (float(reading_order) if reading_order is not None else math.inf),
            element_id,
        )

    ordered_nodes = sorted(included, key=stable_node_key)
    rank = {element_id: index for index, element_id in enumerate(ordered_nodes)}
    adjacency: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    for relationship in ir.relationships:
        if (
            relationship.type is not RelationshipType.ALTERNATIVE_OF
            or relationship.metadata.get("canonical_presentation_inert") is True
            or relationship.source_id not in included
            or relationship.target_id not in included
            or relationship.source_id == relationship.target_id
        ):
            continue
        adjacency.setdefault(relationship.source_id, set()).add(relationship.target_id)
        adjacency.setdefault(relationship.target_id, set())
        reverse.setdefault(relationship.target_id, set()).add(relationship.source_id)
        reverse.setdefault(relationship.source_id, set())
    if not any(adjacency.values()):
        return {}

    def node_key(element_id: str) -> tuple[int, str]:
        return rank[element_id], element_id

    order: list[str] = []
    visited: set[str] = set()
    for start in sorted(adjacency, key=node_key):
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for target in sorted(adjacency[node], key=node_key, reverse=True):
                if target not in visited:
                    stack.append((target, False))

    components: list[list[str]] = []
    component_by_node: dict[str, int] = {}
    visited.clear()
    for start in reversed(order):
        if start in visited:
            continue
        component_id = len(components)
        members: list[str] = []
        stack = [start]
        visited.add(start)
        while stack:
            node = stack.pop()
            members.append(node)
            component_by_node[node] = component_id
            for source in sorted(reverse[node], key=node_key, reverse=True):
                if source not in visited:
                    visited.add(source)
                    stack.append(source)
        members.sort(key=node_key)
        components.append(members)

    component_edges: dict[int, list[tuple[str, int]]] = {
        component_id: [] for component_id in range(len(components))
    }
    outgoing_components: dict[int, set[int]] = {
        component_id: set() for component_id in range(len(components))
    }
    predecessors: dict[int, set[int]] = {
        component_id: set() for component_id in range(len(components))
    }
    for source, targets in adjacency.items():
        source_component = component_by_node[source]
        for target in targets:
            target_component = component_by_node[target]
            if source_component == target_component:
                continue
            component_edges[source_component].append((target, target_component))
            outgoing_components[source_component].add(target_component)
            predecessors[target_component].add(source_component)

    remaining = {
        component_id: len(targets)
        for component_id, targets in outgoing_components.items()
    }
    ready: list[tuple[int, str, int]] = []
    for component_id, count in remaining.items():
        if count == 0:
            first = components[component_id][0]
            heapq.heappush(ready, (rank[first], first, component_id))
    representative: dict[int, str] = {}
    while ready:
        _rank, _first, component_id = heapq.heappop(ready)
        if outgoing_components[component_id]:
            _target, target_component = min(
                component_edges[component_id],
                key=lambda value: (
                    rank[value[0]],
                    value[0],
                    value[1],
                ),
            )
            representative[component_id] = representative[target_component]
        else:
            representative[component_id] = components[component_id][0]
        for predecessor in predecessors[component_id]:
            remaining[predecessor] -= 1
            if remaining[predecessor] == 0:
                first = components[predecessor][0]
                heapq.heappush(ready, (rank[first], first, predecessor))

    suppressors: dict[str, str] = {}
    for node, component_id in component_by_node.items():
        target = representative[component_id]
        if node != target:
            suppressors[node] = target
    return suppressors


def _form_semantic_replacements(
    validated: DocumentIR,
    elements: Mapping[str, ElementRecord],
    unavailable_contributor_ids: set[str],
    predecessor: CanonicalPresentation,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve only complete, disjoint, same-page US06 replacements.

    The form service owns strict sidecar validation and escaping. Canonical
    presentation adds one final custody check against the live PageRecord
    anchors so a partial, conflicting, or already-suppressed contributor set
    falls back to the unchanged predecessor presentation atomically.
    """

    if not any(element.form_semantics is not None for element in validated.elements):
        return {}, {}

    from app.services.form_semantics import render_form_group_semantics

    relationships_by_id = {
        relationship.id: relationship for relationship in validated.relationships
    }
    predecessor_owner_by_contribution = {
        contribution_id: block.primary_element_id
        for page in predecessor.pages
        for block in page.blocks
        if block.omission_reason is None
        for contribution_id in block.contributing_element_ids
    }
    predecessor_blocks_by_primary = {
        block.primary_element_id: block
        for page in predecessor.pages
        for block in page.blocks
    }
    candidates: list[Any] = []
    for page in sorted(validated.pages, key=lambda value: value.page_index):
        page_primary_ids = tuple(page.presentation_element_ids)
        page_primary_set = set(page_primary_ids)
        for anchor_id in page_primary_ids:
            anchor = elements[anchor_id]
            try:
                rendering = render_form_group_semantics(
                    anchor,
                    elements_by_id=elements,
                )
            except Exception:
                rendering = None
            if (
                rendering is None
                or rendering.canonical_mode != "replace"
                or rendering.anchor_element_id != anchor_id
                or not rendering.markdown
                or not rendering.text
            ):
                continue
            contributor_ids = tuple(rendering.contributor_element_ids)
            relationship_ids = tuple(rendering.relationship_ids)
            if (
                not contributor_ids
                or len(contributor_ids) != len(set(contributor_ids))
                or not set(contributor_ids).issubset(page_primary_set)
                or set(contributor_ids) & unavailable_contributor_ids
                or any(
                    (
                        predecessor_blocks_by_primary.get(contributor_id) is None
                        or predecessor_blocks_by_primary[contributor_id].omission_reason
                        is not None
                        or predecessor_blocks_by_primary[
                            contributor_id
                        ].contributing_element_ids
                        != [contributor_id]
                        or predecessor_blocks_by_primary[
                            contributor_id
                        ].suppressed_by_element_id
                        is not None
                        or predecessor_owner_by_contribution.get(contributor_id)
                        != contributor_id
                    )
                    for contributor_id in contributor_ids
                )
                or not relationship_ids
                or len(relationship_ids) != len(set(relationship_ids))
            ):
                continue
            relationships = [
                relationships_by_id.get(relationship_id)
                for relationship_id in relationship_ids
            ]
            if any(
                relationship is None
                or relationship.metadata != {"canonical_inert": True}
                for relationship in relationships
            ):
                continue
            candidates.append(rendering)

    contributor_use = Counter(
        contributor_id
        for rendering in candidates
        for contributor_id in rendering.contributor_element_ids
    )
    replacements_by_anchor: dict[str, Any] = {}
    replacements_by_contributor: dict[str, Any] = {}
    for rendering in candidates:
        if any(
            contributor_use[contributor_id] != 1
            for contributor_id in rendering.contributor_element_ids
        ):
            continue
        replacements_by_anchor[rendering.anchor_element_id] = rendering
        for contributor_id in rendering.contributor_element_ids:
            if contributor_id != rendering.anchor_element_id:
                replacements_by_contributor[contributor_id] = rendering
    return replacements_by_anchor, replacements_by_contributor


def _outline_semantic_replacements(
    validated: DocumentIR,
    elements: Mapping[str, ElementRecord],
    unavailable_primary_ids: set[str],
    predecessor: CanonicalPresentation,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve complete US07 replacements over canonical predecessor blocks."""

    if not any(
        element.outline_group is not None or element.outline_item is not None
        for element in validated.elements
    ):
        return {}, {}

    from app.services.outline_structure import (
        POLICY_ID as OUTLINE_POLICY_ID,
        render_outline_group_semantics,
    )

    relationships_by_id = {
        relationship.id: relationship for relationship in validated.relationships
    }
    blocks_by_primary = {
        block.primary_element_id: block
        for page in predecessor.pages
        for block in page.blocks
    }
    candidates: list[Any] = []
    for page in sorted(validated.pages, key=lambda value: value.page_index):
        page_primary_ids = tuple(page.presentation_element_ids)
        page_primary_set = set(page_primary_ids)
        for anchor_id in page_primary_ids:
            anchor = elements[anchor_id]
            try:
                rendering = render_outline_group_semantics(
                    anchor,
                    elements_by_id=elements,
                    predecessor=predecessor,
                )
            except Exception:
                rendering = None
            if (
                rendering is None
                or rendering.anchor_element_id != anchor_id
                or not rendering.markdown
                or not rendering.text
                or not rendering.predecessor_primary_ids
                or len(rendering.predecessor_primary_ids)
                != len(set(rendering.predecessor_primary_ids))
                or not set(rendering.predecessor_primary_ids).issubset(page_primary_set)
                or set(rendering.predecessor_primary_ids) & unavailable_primary_ids
                or rendering.predecessor_primary_ids[0] != anchor_id
                or not rendering.contributor_element_ids
                or rendering.contributor_element_ids[0] != anchor_id
                or len(rendering.contributor_element_ids)
                != len(set(rendering.contributor_element_ids))
                or not rendering.relationship_ids
                or len(rendering.relationship_ids)
                != len(set(rendering.relationship_ids))
            ):
                continue
            selected_blocks = [
                blocks_by_primary.get(primary_id)
                for primary_id in rendering.predecessor_primary_ids
            ]
            if any(
                block is None
                or block.omission_reason is not None
                or block.suppressed_by_element_id is not None
                for block in selected_blocks
            ):
                continue
            story_relationships = [
                relationships_by_id.get(relationship_id)
                for relationship_id in rendering.relationship_ids
                if relationship_id in relationships_by_id
                and relationships_by_id[relationship_id].metadata.get("outline_policy")
                == OUTLINE_POLICY_ID
            ]
            if not story_relationships or any(
                relationship is None
                or relationship.metadata.get("canonical_inert") is not True
                for relationship in story_relationships
            ):
                continue
            candidates.append(rendering)

    primary_use = Counter(
        primary_id
        for rendering in candidates
        for primary_id in rendering.predecessor_primary_ids
    )
    contributor_use = Counter(
        contributor_id
        for rendering in candidates
        for contributor_id in rendering.contributor_element_ids
    )
    replacements_by_anchor: dict[str, Any] = {}
    replacements_by_contributor: dict[str, Any] = {}
    for rendering in candidates:
        if any(
            primary_use[primary_id] != 1
            for primary_id in rendering.predecessor_primary_ids
        ) or any(
            contributor_use[contributor_id] != 1
            for contributor_id in rendering.contributor_element_ids
        ):
            continue
        replacements_by_anchor[rendering.anchor_element_id] = rendering
        for primary_id in rendering.predecessor_primary_ids:
            if primary_id != rendering.anchor_element_id:
                replacements_by_contributor[primary_id] = rendering
    return replacements_by_anchor, replacements_by_contributor


def _build_canonical_presentation(
    validated: DocumentIR,
    alternative_targets: Mapping[str, str],
    *,
    enable_form_replacements: bool = True,
    enable_outline_replacements: bool = True,
) -> CanonicalPresentation:
    """Build a canonical contract with resolved alternative suppressors."""

    elements = {element.id: element for element in validated.elements}
    page_index_by_id = {
        page.id: page.page_index for page in validated.pages
    }
    evidence_by_id = {evidence.id: evidence for evidence in validated.evidence}
    evidence_by_element = {
        element.id: [
            evidence_by_id[evidence_id]
            for evidence_id in element.evidence_ids
            if evidence_id in evidence_by_id
        ]
        for element in validated.elements
    }
    primary_sequence = [
        element_id
        for page in sorted(validated.pages, key=lambda value: value.page_index)
        for element_id in page.presentation_element_ids
    ]
    primary_set = set(primary_sequence)
    primary_rank = {
        element_id: index for index, element_id in enumerate(primary_sequence)
    }
    structured_visual_outputs = {
        element.id: output
        for element in validated.elements
        if (output := _structured_visual_output(element)) is not None
    }
    public_element_ids = {
        str(legacy_id): element.id
        for element in validated.elements
        if (legacy_id := _legacy_item(element).get("id")) is not None
    }
    layout_caption_source_relationship_ids: set[str] = set()
    structured_layout_caption_owners: dict[str, tuple[str, str]] = {}
    for element in validated.elements:
        projection = element.properties.get("layout_projection")
        if (
            element.type.casefold() != "caption"
            or not isinstance(projection, Mapping)
            or projection.get("story") != "P03-US02"
        ):
            continue
        source_relationship_id = projection.get("source_relationship_id")
        if isinstance(source_relationship_id, str) and source_relationship_id:
            layout_caption_source_relationship_ids.add(source_relationship_id)
        relationship_id = projection.get("relationship_id")
        owner_public_id = _legacy_item(element).get("caption_of")
        owner_id = public_element_ids.get(str(owner_public_id))
        output = structured_visual_outputs.get(owner_id or "")
        caption = _clean(element.value or element.markdown)
        caption_variants = {caption, caption.replace("\n", "<br>")}
        if (
            owner_id is not None
            and output is not None
            and output.caption_occurrences == 1
            and isinstance(relationship_id, str)
            and relationship_id
            and any(value and value in output.markdown for value in caption_variants)
        ):
            structured_layout_caption_owners[element.id] = (
                owner_id,
                relationship_id,
            )
    edge_groups = _group_relationships(validated.relationships, elements)
    incoming: dict[str, list[_EdgeGroup]] = {}
    outgoing: dict[str, list[_EdgeGroup]] = {}
    for edge in edge_groups:
        incoming.setdefault(edge.target_id, []).append(edge)
        outgoing.setdefault(edge.source_id, []).append(edge)
    for values in (*incoming.values(), *outgoing.values()):
        values.sort(
            key=lambda edge: (
                edge.type.value,
                _relationship_index(edge),
                edge.source_id,
                edge.target_id,
            )
        )
    declared_structure_by_owner: dict[str, list[ElementRecord]] = {}
    for owner in validated.elements:
        owner_id = owner.id
        if owner.type.casefold() not in _STRUCTURED_OWNER_TYPES:
            continue
        for edge in outgoing.get(owner_id, []):
            if edge.type is not RelationshipType.CONTAINS:
                continue
            child = elements[edge.target_id]
            if (
                child.presentation_role == "primary"
                and not _structured_child_is_represented(owner, child)
            ):
                continue
            declared_structure_by_owner.setdefault(owner_id, []).append(child)
    for owner_id, children in declared_structure_by_owner.items():
        projection = elements[owner_id].properties.get("relationship_order_projection")
        nested_order = (
            projection.get("nested_element_ids")
            if isinstance(projection, Mapping)
            else None
        )
        excluded_nested = (
            projection.get("excluded_nested_element_ids")
            if isinstance(projection, Mapping)
            else None
        )
        child_ids = {child.id for child in children}
        if (
            isinstance(projection, Mapping)
            and projection.get("story") == "P03-US04"
            and isinstance(nested_order, Sequence)
            and not isinstance(nested_order, (str, bytes, bytearray))
            and all(isinstance(child_id, str) for child_id in nested_order)
            and len(nested_order) == len(set(nested_order))
            and isinstance(excluded_nested, Sequence)
            and not isinstance(
                excluded_nested,
                (str, bytes, bytearray),
            )
            and all(isinstance(child_id, str) for child_id in excluded_nested)
            and len(excluded_nested) == len(set(excluded_nested))
            and not (set(nested_order) & set(excluded_nested))
            and set(nested_order) | set(excluded_nested) == child_ids
        ):
            by_id = {child.id: child for child in children}
            declared_structure_by_owner[owner_id] = [
                by_id[child_id] for child_id in nested_order
            ]

    # Header/footer children are scope-owned by their furniture anchor. Walk
    # direct structure and the presentation-bearing descendants of that
    # structure so an earlier body or furniture anchor cannot steal them.
    furniture_root_ids = [
        element_id
        for element_id in primary_sequence
        if elements[element_id].type.casefold() in {"header", "footer"}
    ]
    scope_owner_by_element: dict[str, str] = {
        root_id: root_id for root_id in furniture_root_ids
    }
    for root_id in furniture_root_ids:
        visited: set[str] = set()
        pending = [root_id]
        while pending:
            current_id = pending.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            related_ids = [
                edge.target_id
                for edge in outgoing.get(current_id, [])
                if edge.type is RelationshipType.CONTAINS
            ]
            related_ids.extend(
                edge.source_id
                for edge in incoming.get(current_id, [])
                if edge.type
                in {
                    RelationshipType.CAPTION_OF,
                    RelationshipType.SOURCE_NOTE_OF,
                    RelationshipType.FOOTNOTE_OF,
                }
            )
            for related_id in reversed(related_ids):
                existing_root = scope_owner_by_element.get(related_id)
                if existing_root is None:
                    scope_owner_by_element[related_id] = root_id
                    pending.append(related_id)
                elif existing_root == root_id:
                    pending.append(related_id)

    def claim_is_in_scope(claim: _Claim) -> bool:
        source_scope = scope_owner_by_element.get(claim.source_id)
        if source_scope is not None and source_scope != claim.owner_id:
            return False
        if claim.nested_visual_id is not None:
            bridge_scope = scope_owner_by_element.get(claim.nested_visual_id)
            if bridge_scope is not None and bridge_scope != claim.owner_id:
                return False
        return True

    table_suppressors = _diagnosed_table_suppressors(validated, elements)
    prelim_omitted = set(table_suppressors) | set(alternative_targets)
    if enable_form_replacements and any(
        element.form_semantics is not None for element in validated.elements
    ):
        predecessor_form_presentation = _build_canonical_presentation(
            validated,
            alternative_targets,
            enable_form_replacements=False,
            enable_outline_replacements=False,
        )
        (
            form_replacements_by_anchor,
            form_replacements_by_contributor,
        ) = _form_semantic_replacements(
            validated,
            elements,
            prelim_omitted,
            predecessor_form_presentation,
        )
    else:
        form_replacements_by_anchor = {}
        form_replacements_by_contributor = {}
    prelim_omitted.update(form_replacements_by_contributor)
    if enable_outline_replacements and any(
        element.outline_group is not None or element.outline_item is not None
        for element in validated.elements
    ):
        predecessor_outline_presentation = _build_canonical_presentation(
            validated,
            alternative_targets,
            enable_outline_replacements=False,
        )
        (
            outline_replacements_by_anchor,
            outline_replacements_by_contributor,
        ) = _outline_semantic_replacements(
            validated,
            elements,
            prelim_omitted,
            predecessor_outline_presentation,
        )
    else:
        outline_replacements_by_anchor = {}
        outline_replacements_by_contributor = {}
    prelim_omitted.update(outline_replacements_by_contributor)

    eligible_caption_edges: dict[str, list[_EdgeGroup]] = {}
    eligible_caption_source_ids: dict[str, set[str]] = {}
    eligible_ocr_edges: dict[str, list[_EdgeGroup]] = {}
    visual_has_content: dict[str, bool] = {}
    proven_visual_outputs: dict[str, str] = {}
    independent_visual_child_specs: dict[
        str, list[tuple[_EdgeGroup, str]]
    ] = {}
    independent_visual_output_sequences: dict[str, list[str]] = {}
    filtered_visual_owner_outputs: dict[str, str] = {}
    for owner_id in primary_sequence:
        owner = elements[owner_id]
        caption_edges = [
            edge
            for edge in incoming.get(owner_id, [])
            if edge.type is RelationshipType.CAPTION_OF
            and _caption_eligible(
                elements[edge.source_id],
                owner,
                evidence_by_id,
            )
        ]
        eligible_caption_edges[owner_id] = caption_edges
        eligible_caption_source_ids[owner_id] = {
            edge.source_id for edge in caption_edges
        }
        if owner.type.casefold() not in _VISUAL_TYPES:
            continue
        ocr_edges = [
            edge
            for edge in outgoing.get(owner_id, [])
            if edge.type is RelationshipType.CONTAINS
            and elements[edge.target_id].presentation_role != "diagnostic"
            and elements[edge.target_id].presentation.accepted is not False
            and _has_ocr(elements[edge.target_id], evidence_by_id)
            and any(_element_output(elements[edge.target_id]))
        ]
        eligible_ocr_edges[owner_id] = ocr_edges
        owner_ocr = any(
            evidence.method is EvidenceMethod.OCR and bool(_plain_value(evidence.value))
            for evidence in evidence_by_element.get(owner_id, ())
        )
        proven_visual_output = _proven_visual_owner_output(
            owner,
            source_document_identity=validated.source_sha256,
            page_index=page_index_by_id[owner.page_id],
        )
        if proven_visual_output:
            proven_visual_outputs[owner_id] = proven_visual_output
        else:
            fallback = _independent_visual_native_child_records(
                owner,
                source_document_identity=validated.source_sha256,
                page_index=page_index_by_id[owner.page_id],
            )
            fallback_owner_output = fallback.get("owner_output")
            if isinstance(fallback_owner_output, str) and fallback_owner_output:
                filtered_visual_owner_outputs[owner_id] = fallback_owner_output
            specs: list[tuple[_EdgeGroup, str]] = []
            outputs: list[str] = []
            records_valid = True
            records = fallback.get("children")
            if not isinstance(records, list):
                records = []
            for record in records:
                if not isinstance(record, Mapping):
                    records_valid = False
                    break
                value = record.get("value")
                if not isinstance(value, str) or not value:
                    records_valid = False
                    break
                outputs.append(value)
                matches = []
                for edge in outgoing.get(owner_id, []):
                    if edge.type is not RelationshipType.CONTAINS:
                        continue
                    child = elements[edge.target_id]
                    child_public_id = str(
                        _legacy_item(child).get("id") or child.id
                    )
                    if (
                        child_public_id == record["id"]
                        and record["relationship_id"] in edge.relationship_ids
                    ):
                        matches.append(edge)
                if len(matches) > 1:
                    records_valid = False
                    break
                if matches:
                    specs.append((matches[0], value))
            if records_valid and outputs:
                independent_visual_output_sequences[owner_id] = outputs
            if records_valid and specs:
                independent_visual_child_specs[owner_id] = specs
        visual_has_content[owner_id] = (
            owner_id in structured_visual_outputs
            or owner.visual_model_evidence is not None
            or bool(caption_edges)
            or bool(proven_visual_output)
            or bool(filtered_visual_owner_outputs.get(owner_id))
            or bool(independent_visual_output_sequences.get(owner_id))
            or (_visual_ocr_allowed(owner) and (bool(ocr_edges) or owner_ocr))
        )

    claims: list[_Claim] = []
    nested_visual_specs: list[_NestedVisualSpec] = []
    nested_visual_specs_by_owner: dict[str, list[_NestedVisualSpec]] = {}
    for owner_id in primary_sequence:
        if owner_id in prelim_omitted:
            continue
        owner = elements[owner_id]
        owner_rank = primary_rank[owner_id]
        owner_type = owner.type.casefold()

        for edge in incoming.get(owner_id, []):
            if edge.type is RelationshipType.CAPTION_OF:
                if edge.source_id in eligible_caption_source_ids.get(owner_id, set()):
                    claims.append(
                        _Claim(
                            "caption",
                            owner_id,
                            edge.source_id,
                            edge,
                            owner_rank,
                        )
                    )
            elif edge.type in {
                RelationshipType.SOURCE_NOTE_OF,
                RelationshipType.FOOTNOTE_OF,
            }:
                if (
                    owner_type not in _VISUAL_TYPES
                    or visual_has_content.get(owner_id, False)
                ) and any(_element_output(elements[edge.source_id])):
                    claims.append(
                        _Claim(
                            (
                                "source_note"
                                if edge.type is RelationshipType.SOURCE_NOTE_OF
                                else "footnote"
                            ),
                            owner_id,
                            edge.source_id,
                            edge,
                            owner_rank,
                        )
                    )

        for edge, output in independent_visual_child_specs.get(owner_id, ()):
            claims.append(
                _Claim(
                    "native_child",
                    owner_id,
                    edge.target_id,
                    edge,
                    owner_rank,
                    output_override=(output, output),
                )
            )

        if owner_type in _STRUCTURED_OWNER_TYPES:
            legacy = _legacy_item(owner)
            represents_structure = bool(declared_structure_by_owner.get(owner_id)) or (
                owner_type in {"header", "footer"}
                and legacy.get("layout_value") is None
            )
            if not represents_structure:
                body_markdown, body_text = _standard_output(owner, ())
                represents_structure = bool(body_markdown or body_text)
            if not represents_structure:
                continue
            visited_containers: set[str] = set()

            def add_structure_claims(container_id: str) -> None:
                if container_id in visited_containers:
                    return
                visited_containers.add(container_id)
                declared_ids = {
                    child.id
                    for child in declared_structure_by_owner.get(container_id, ())
                }
                for edge in outgoing.get(container_id, []):
                    if (
                        edge.type is not RelationshipType.CONTAINS
                        or edge.target_id not in declared_ids
                    ):
                        continue
                    source = elements[edge.target_id]
                    if _is_visual_payload(source):
                        spec = _NestedVisualSpec(
                            owner_id=owner_id,
                            visual_id=source.id,
                            structure_edge=edge,
                            owner_rank=owner_rank,
                        )
                        nested_visual_specs.append(spec)
                        nested_visual_specs_by_owner.setdefault(owner_id, []).append(
                            spec
                        )
                        if (
                            source.presentation_role == "diagnostic"
                            or source.presentation.accepted is False
                        ):
                            continue
                        if source.visual_model_evidence is not None:
                            # The containment assertion gives a model-only
                            # nested visual canonical custody without treating
                            # its generated observation as source OCR/caption.
                            claims.append(
                                _Claim(
                                    "structure",
                                    owner_id,
                                    source.id,
                                    edge,
                                    owner_rank,
                                    nested_visual_id=source.id,
                                    bridge_edge=edge,
                                )
                            )
                        for caption_edge in incoming.get(source.id, []):
                            caption = elements[caption_edge.source_id]
                            if (
                                caption_edge.type is RelationshipType.CAPTION_OF
                                and _caption_eligible(
                                    caption,
                                    source,
                                    evidence_by_id,
                                )
                            ):
                                claims.append(
                                    _Claim(
                                        "caption",
                                        owner_id,
                                        caption.id,
                                        caption_edge,
                                        owner_rank,
                                        nested_visual_id=source.id,
                                        bridge_edge=edge,
                                    )
                                )
                        continue
                    if (
                        source.presentation_role == "diagnostic"
                        or source.presentation.accepted is False
                    ):
                        continue
                    claims.append(
                        _Claim(
                            "structure",
                            owner_id,
                            source.id,
                            edge,
                            owner_rank,
                        )
                    )
                    for presentation_edge in incoming.get(source.id, []):
                        attachment = elements[presentation_edge.source_id]
                        if (
                            presentation_edge.type is RelationshipType.CAPTION_OF
                            and _caption_eligible(
                                attachment,
                                source,
                                evidence_by_id,
                            )
                        ):
                            claims.append(
                                _Claim(
                                    "caption",
                                    owner_id,
                                    attachment.id,
                                    presentation_edge,
                                    owner_rank,
                                    nested_visual_id=source.id,
                                    bridge_edge=edge,
                                )
                            )
                        elif presentation_edge.type in {
                            RelationshipType.SOURCE_NOTE_OF,
                            RelationshipType.FOOTNOTE_OF,
                        } and any(_element_output(attachment)):
                            claims.append(
                                _Claim(
                                    (
                                        "source_note"
                                        if presentation_edge.type
                                        is RelationshipType.SOURCE_NOTE_OF
                                        else "footnote"
                                    ),
                                    owner_id,
                                    attachment.id,
                                    presentation_edge,
                                    owner_rank,
                                    nested_visual_id=source.id,
                                    bridge_edge=edge,
                                    requires_bridge=True,
                                )
                            )
                    if source.type.casefold() in _STRUCTURED_OWNER_TYPES:
                        add_structure_claims(source.id)

            add_structure_claims(owner_id)

    claims = [
        claim
        for claim in claims
        if claim.source_id not in alternative_targets
        and (
            claim.nested_visual_id is None
            or claim.nested_visual_id not in alternative_targets
        )
    ]

    # Allocate non-OCR relationships first. A shared caption belongs to the
    # first eligible anchor; owners that lose that caption may then fall back
    # to their own explicitly eligible subordinate OCR.
    def assignable_claims(
        values: Sequence[_Claim],
    ) -> list[_Claim]:
        return [
            claim
            for claim in values
            if claim.source_id not in table_suppressors
            and (
                claim.nested_visual_id is None
                or claim.nested_visual_id not in table_suppressors
            )
            and claim_is_in_scope(claim)
        ]

    provisional_assignment = _assign_stable_claims(
        assignable_claims(claims),
        primary_set,
    )
    owners_with_caption = {
        claim.owner_id
        for claim in provisional_assignment.values()
        if claim.kind == "caption" and claim.nested_visual_id is None
    }
    for owner_id in primary_sequence:
        if (
            owner_id in prelim_omitted
            or owner_id in owners_with_caption
            or owner_id in structured_visual_outputs
        ):
            continue
        owner = elements[owner_id]
        if owner.type.casefold() not in _VISUAL_TYPES or not _visual_ocr_allowed(owner):
            continue
        for edge in eligible_ocr_edges.get(owner_id, []):
            if edge.target_id in prelim_omitted:
                continue
            claims.append(
                _Claim(
                    "ocr",
                    owner_id,
                    edge.target_id,
                    edge,
                    primary_rank[owner_id],
                )
            )

    provisional_assignment = _assign_stable_claims(
        assignable_claims(claims),
        primary_set,
    )
    nested_caption_paths = {
        (claim.owner_id, claim.nested_visual_id)
        for claim in provisional_assignment.values()
        if claim.kind == "caption" and claim.nested_visual_id is not None
    }
    for spec in nested_visual_specs:
        path = (spec.owner_id, spec.visual_id)
        if (
            spec.owner_id in prelim_omitted
            or spec.visual_id in prelim_omitted
            or path in nested_caption_paths
        ):
            continue
        visual = elements[spec.visual_id]
        if (
            visual.presentation_role == "diagnostic"
            or visual.presentation.accepted is False
            or not _visual_ocr_allowed(visual)
        ):
            continue
        for edge in outgoing.get(spec.visual_id, []):
            if edge.type is not RelationshipType.CONTAINS:
                continue
            source = elements[edge.target_id]
            if (
                source.presentation_role == "diagnostic"
                or source.presentation.accepted is False
                or not _has_ocr(source, evidence_by_id)
                or not any(_element_output(source))
                or source.id in prelim_omitted
            ):
                continue
            claims.append(
                _Claim(
                    "ocr",
                    spec.owner_id,
                    source.id,
                    edge,
                    spec.owner_rank,
                    nested_visual_id=spec.visual_id,
                    bridge_edge=spec.structure_edge,
                )
            )

    assignment = _assign_stable_claims(
        assignable_claims(claims),
        primary_set,
    )
    nested_body_paths = {
        (claim.owner_id, claim.nested_visual_id)
        for claim in assignment.values()
        if claim.kind in {"caption", "ocr"} and claim.nested_visual_id is not None
    }
    for spec in nested_visual_specs:
        path = (spec.owner_id, spec.visual_id)
        if (
            spec.owner_id in prelim_omitted
            or spec.visual_id in prelim_omitted
            or path in nested_body_paths
        ):
            continue
        visual = elements[spec.visual_id]
        if (
            visual.presentation_role == "diagnostic"
            or visual.presentation.accepted is False
            or not _visual_ocr_allowed(visual)
        ):
            continue
        owner_ocr_values = [
            _plain_value(evidence.value)
            for evidence in evidence_by_element.get(spec.visual_id, ())
            if evidence.method is EvidenceMethod.OCR and _plain_value(evidence.value)
        ]
        if not owner_ocr_values:
            continue
        value = owner_ocr_values[0]
        claims.append(
            _Claim(
                "ocr",
                spec.owner_id,
                spec.visual_id,
                spec.structure_edge,
                spec.owner_rank,
                nested_visual_id=spec.visual_id,
                output_override=(value, value),
            )
        )

    assignment = _assign_stable_claims(
        assignable_claims(claims),
        primary_set,
    )
    nested_body_paths = {
        (claim.owner_id, claim.nested_visual_id)
        for claim in assignment.values()
        if claim.kind in {"caption", "ocr"} and claim.nested_visual_id is not None
    }
    for spec in nested_visual_specs:
        if (spec.owner_id, spec.visual_id) not in nested_body_paths:
            continue
        for edge in incoming.get(spec.visual_id, []):
            if edge.type not in {
                RelationshipType.SOURCE_NOTE_OF,
                RelationshipType.FOOTNOTE_OF,
            }:
                continue
            source = elements[edge.source_id]
            if not any(_element_output(source)):
                continue
            claims.append(
                _Claim(
                    (
                        "source_note"
                        if edge.type is RelationshipType.SOURCE_NOTE_OF
                        else "footnote"
                    ),
                    spec.owner_id,
                    source.id,
                    edge,
                    spec.owner_rank,
                    nested_visual_id=spec.visual_id,
                    bridge_edge=spec.structure_edge,
                    requires_bridge=True,
                )
            )

    assignment = _assign_stable_claims(
        assignable_claims(claims),
        primary_set,
    )
    visual_body_owners = {
        claim.owner_id
        for claim in assignment.values()
        if claim.kind in {"caption", "ocr"}
    }
    visual_body_owners.update(
        owner_id
        for owner_id in primary_sequence
        if elements[owner_id].type.casefold() in _VISUAL_TYPES
        and _visual_ocr_allowed(elements[owner_id])
        and any(
            evidence.method is EvidenceMethod.OCR and bool(_plain_value(evidence.value))
            for evidence in evidence_by_element.get(owner_id, ())
        )
    )
    visual_body_owners.update(structured_visual_outputs)
    visual_body_owners.update(
        owner_id
        for owner_id in primary_sequence
        if elements[owner_id].type.casefold() in _VISUAL_TYPES
        and elements[owner_id].visual_model_evidence is not None
    )
    claims = [
        claim
        for claim in claims
        if claim.source_id not in alternative_targets
        and (
            claim.nested_visual_id is None
            or claim.nested_visual_id not in alternative_targets
        )
        and (
            claim.kind not in {"source_note", "footnote"}
            or elements[claim.owner_id].type.casefold() not in _VISUAL_TYPES
            or claim.owner_id in visual_body_owners
        )
    ]

    candidates_by_owner: dict[str, list[_Claim]] = {}
    for claim in claims:
        candidates_by_owner.setdefault(claim.owner_id, []).append(claim)
    assignment = _assign_stable_claims(
        assignable_claims(claims),
        primary_set,
    )
    assigned_by_owner: dict[str, list[_Claim]] = {}
    for claim in assignment.values():
        assigned_by_owner.setdefault(claim.owner_id, []).append(claim)
    for values in assigned_by_owner.values():
        values.sort(key=_claim_key)

    pages: list[CanonicalPage] = []
    for page in sorted(validated.pages, key=lambda value: value.page_index):
        blocks: list[CanonicalBlock] = []
        for primary_id in page.presentation_element_ids:
            primary = elements[primary_id]
            block_id = _stable_id(
                "pb",
                PRESENTATION_SCHEMA_VERSION,
                PRESENTATION_POLICY_ID,
                page.id,
                primary_id,
            )
            scope = _scope_for(primary)
            exclusions: dict[tuple[str, str], ExcludedContribution] = {}
            incident_alternative_edges = [
                edge
                for edge in (
                    *incoming.get(primary_id, []),
                    *outgoing.get(primary_id, []),
                )
                if edge.type is RelationshipType.ALTERNATIVE_OF
            ]
            incident_alternative_relationship_ids = {
                relationship_id
                for edge in incident_alternative_edges
                for relationship_id in edge.relationship_ids
            }

            if primary_id in alternative_targets:
                alternative_relationship_ids = sorted(
                    {
                        relationship_id
                        for edge in outgoing.get(primary_id, [])
                        if edge.type is RelationshipType.ALTERNATIVE_OF
                        for relationship_id in edge.relationship_ids
                    }
                )
                direct_presentation_relationship_ids = sorted(
                    {
                        relationship_id
                        for edge in outgoing.get(primary_id, [])
                        if edge.type
                        in {
                            RelationshipType.CONTAINS,
                            RelationshipType.CAPTION_OF,
                            RelationshipType.SOURCE_NOTE_OF,
                            RelationshipType.FOOTNOTE_OF,
                            RelationshipType.LEGEND_OF,
                            RelationshipType.AXIS_OF,
                            RelationshipType.ALTERNATIVE_OF,
                            RelationshipType.ANNOTATION_OF,
                            RelationshipType.REFERENCES,
                        }
                        for relationship_id in edge.relationship_ids
                    }
                    | incident_alternative_relationship_ids
                )
                suppressor = alternative_targets[primary_id]
                _add_exclusion(
                    exclusions,
                    element_id=suppressor,
                    reason="alternate_representation",
                    relationship_ids=alternative_relationship_ids,
                )
                for edge in incident_alternative_edges:
                    related_id = (
                        edge.source_id
                        if edge.target_id == primary_id
                        else edge.target_id
                    )
                    if edge.source_id == primary_id and related_id == suppressor:
                        continue
                    _add_exclusion(
                        exclusions,
                        element_id=related_id,
                        reason="evidence_only_relationship",
                        relationship_ids=edge.relationship_ids,
                    )
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown="",
                        text="",
                        contributing_element_ids=[],
                        relationship_ids=(direct_presentation_relationship_ids),
                        excluded_contributions=sorted(
                            exclusions.values(),
                            key=lambda value: (
                                value.element_id,
                                value.reason,
                            ),
                        ),
                        omission_reason="alternate_representation",
                        suppressed_by_element_id=suppressor,
                    )
                )
                continue
            if primary_id in table_suppressors:
                suppressor = table_suppressors[primary_id]
                _add_exclusion(
                    exclusions,
                    element_id=suppressor,
                    reason="overlapping_visual_table",
                )
                for edge in incident_alternative_edges:
                    related_id = (
                        edge.source_id
                        if edge.target_id == primary_id
                        else edge.target_id
                    )
                    _add_exclusion(
                        exclusions,
                        element_id=related_id,
                        reason="evidence_only_relationship",
                        relationship_ids=edge.relationship_ids,
                    )
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown="",
                        text="",
                        contributing_element_ids=[],
                        relationship_ids=sorted(incident_alternative_relationship_ids),
                        excluded_contributions=list(exclusions.values()),
                        omission_reason="overlapping_visual_table",
                        suppressed_by_element_id=suppressor,
                    )
                )
                continue

            outline_replacement = outline_replacements_by_contributor.get(primary_id)
            if outline_replacement is not None:
                outline_relationship_ids = list(outline_replacement.relationship_ids)
                _add_exclusion(
                    exclusions,
                    element_id=outline_replacement.anchor_element_id,
                    reason="already_claimed",
                    relationship_ids=outline_relationship_ids,
                )
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown="",
                        text="",
                        contributing_element_ids=[],
                        relationship_ids=outline_relationship_ids,
                        excluded_contributions=sorted(
                            exclusions.values(),
                            key=lambda value: (
                                value.element_id,
                                value.reason,
                            ),
                        ),
                        omission_reason="consumed_by_relationship",
                        suppressed_by_element_id=(
                            outline_replacement.anchor_element_id
                        ),
                    )
                )
                continue

            outline_replacement = outline_replacements_by_anchor.get(primary_id)
            if outline_replacement is not None:
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown=outline_replacement.markdown,
                        text=outline_replacement.text,
                        contributing_element_ids=list(
                            outline_replacement.contributor_element_ids
                        ),
                        relationship_ids=list(outline_replacement.relationship_ids),
                        excluded_contributions=[],
                    )
                )
                continue

            form_replacement = form_replacements_by_contributor.get(primary_id)
            if form_replacement is not None:
                form_relationship_ids = list(form_replacement.relationship_ids)
                _add_exclusion(
                    exclusions,
                    element_id=form_replacement.anchor_element_id,
                    reason="already_claimed",
                    relationship_ids=form_relationship_ids,
                )
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown="",
                        text="",
                        contributing_element_ids=[],
                        relationship_ids=form_relationship_ids,
                        excluded_contributions=sorted(
                            exclusions.values(),
                            key=lambda value: (
                                value.element_id,
                                value.reason,
                            ),
                        ),
                        omission_reason="consumed_by_relationship",
                        suppressed_by_element_id=(form_replacement.anchor_element_id),
                    )
                )
                continue

            form_replacement = form_replacements_by_anchor.get(primary_id)
            if form_replacement is not None:
                ordered_form_contributors = [
                    primary_id,
                    *(
                        contributor_id
                        for contributor_id in (form_replacement.contributor_element_ids)
                        if contributor_id != primary_id
                    ),
                ]
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown=form_replacement.markdown,
                        text=form_replacement.text,
                        contributing_element_ids=ordered_form_contributors,
                        relationship_ids=list(form_replacement.relationship_ids),
                        excluded_contributions=[],
                    )
                )
                continue

            structured_caption_suppressor = structured_layout_caption_owners.get(
                primary_id
            )
            if structured_caption_suppressor is not None:
                suppressor_id, relationship_id = structured_caption_suppressor
                _add_exclusion(
                    exclusions,
                    element_id=suppressor_id,
                    reason="alternate_representation",
                    relationship_ids=[relationship_id],
                )
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown="",
                        text="",
                        contributing_element_ids=[],
                        relationship_ids=[relationship_id],
                        excluded_contributions=sorted(
                            exclusions.values(),
                            key=lambda value: (value.element_id, value.reason),
                        ),
                        omission_reason="alternate_representation",
                        suppressed_by_element_id=suppressor_id,
                    )
                )
                continue

            primary_assignment = assignment.get(primary_id)
            structured_caption_owner = (
                structured_visual_outputs.get(primary_assignment.owner_id)
                if (
                    primary_assignment is not None
                    and primary_assignment.owner_id != primary_id
                    and primary.type.casefold() == "caption"
                )
                else None
            )
            layout_projection = primary.properties.get("layout_projection")
            source_note_projection = primary.properties.get("source_note_projection")
            if (
                isinstance(layout_projection, Mapping)
                and layout_projection.get("story") == "P03-US02"
                and (
                    (
                        primary.type.casefold() == "caption"
                        and not (
                            structured_caption_owner is not None
                            and structured_caption_owner.caption_occurrences == 1
                        )
                    )
                    or (
                        primary.type.casefold() in _VISUAL_TYPES
                        and primary_id not in structured_visual_outputs
                    )
                )
            ) or (
                isinstance(source_note_projection, Mapping)
                and source_note_projection.get("story") == "P03-US03"
                and primary.type.casefold() in {"source_note", "footnote"}
            ):
                markdown, text = _element_output(primary)
                markdown, text = _append_visual_model_evidence(
                    primary,
                    (markdown, text),
                )
                public_relationship_ids: set[str] = set()
                for projection in (
                    layout_projection,
                    source_note_projection,
                ):
                    if not isinstance(projection, Mapping):
                        continue
                    relationship_id = projection.get("relationship_id")
                    if isinstance(relationship_id, str) and relationship_id:
                        public_relationship_ids.add(relationship_id)
                legacy = _legacy_item(primary)
                for descriptor in legacy.get("relationships") or []:
                    if not isinstance(descriptor, Mapping):
                        continue
                    descriptor_id = descriptor.get("id")
                    if isinstance(descriptor_id, str) and descriptor_id.startswith(
                        "layout-rel-"
                    ):
                        public_relationship_ids.add(descriptor_id)
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown=markdown,
                        text=text,
                        contributing_element_ids=[primary_id],
                        relationship_ids=sorted(public_relationship_ids),
                        excluded_contributions=[],
                    )
                )
                continue
            if (
                primary_assignment is not None
                and primary_assignment.owner_id != primary_id
            ):
                consumed_owner_candidates = candidates_by_owner.get(primary_id, [])
                consuming_relationship_ids = sorted(
                    set(primary_assignment.edge.relationship_ids)
                    | {
                        relationship_id
                        for claim in consumed_owner_candidates
                        for relationship_id in claim.edge.relationship_ids
                    }
                    | incident_alternative_relationship_ids
                )
                _add_exclusion(
                    exclusions,
                    element_id=primary_assignment.owner_id,
                    reason="already_claimed",
                    relationship_ids=(primary_assignment.edge.relationship_ids),
                )
                for claim in consumed_owner_candidates:
                    _add_exclusion(
                        exclusions,
                        element_id=claim.source_id,
                        reason="evidence_only_relationship",
                        relationship_ids=claim.edge.relationship_ids,
                    )
                for edge in incident_alternative_edges:
                    related_id = (
                        edge.source_id
                        if edge.target_id == primary_id
                        else edge.target_id
                    )
                    _add_exclusion(
                        exclusions,
                        element_id=related_id,
                        reason="evidence_only_relationship",
                        relationship_ids=edge.relationship_ids,
                    )
                blocks.append(
                    CanonicalBlock(
                        id=block_id,
                        page_id=page.id,
                        primary_element_id=primary_id,
                        primary_element_type=primary.type,
                        scope=scope,
                        markdown="",
                        text="",
                        contributing_element_ids=[],
                        relationship_ids=consuming_relationship_ids,
                        excluded_contributions=sorted(
                            exclusions.values(),
                            key=lambda value: (
                                value.element_id,
                                value.reason,
                            ),
                        ),
                        omission_reason="consumed_by_relationship",
                        suppressed_by_element_id=(primary_assignment.owner_id),
                    )
                )
                continue

            owner_claims = assigned_by_owner.get(primary_id, [])
            owner_candidates = candidates_by_owner.get(primary_id, [])
            audited_candidate_relationship_ids: set[str] = set()
            for claim in owner_candidates:
                selected = assignment.get(claim.source_id)
                if selected is None:
                    _add_exclusion(
                        exclusions,
                        element_id=claim.source_id,
                        reason="evidence_only_relationship",
                        relationship_ids=claim.edge.relationship_ids,
                    )
                    audited_candidate_relationship_ids.update(
                        claim.edge.relationship_ids
                    )
                elif selected.owner_id != primary_id or selected != claim:
                    _add_exclusion(
                        exclusions,
                        element_id=claim.source_id,
                        reason="already_claimed",
                        relationship_ids=claim.edge.relationship_ids,
                    )
                    audited_candidate_relationship_ids.update(
                        claim.edge.relationship_ids
                    )

            element_type = primary.type.casefold()
            direct_caption_claims = [
                claim
                for claim in owner_claims
                if claim.kind == "caption" and claim.nested_visual_id is None
            ]
            direct_ocr_claims = [
                claim
                for claim in owner_claims
                if claim.kind == "ocr" and claim.nested_visual_id is None
            ]
            structure_claims = [
                claim for claim in owner_claims if claim.kind == "structure"
            ]
            direct_note_claims = [
                claim
                for claim in owner_claims
                if claim.kind in {"source_note", "footnote"}
                and claim.nested_visual_id is None
            ]
            nested_claims = [
                claim for claim in owner_claims if claim.nested_visual_id is not None
            ]

            ineligible_caption_relationship_ids: set[str] = set()
            for edge in incoming.get(primary_id, []):
                if edge.type is not RelationshipType.CAPTION_OF:
                    continue
                caption = elements[edge.source_id]
                if _caption_eligible(caption, primary, evidence_by_id):
                    continue
                caption_methods = _evidence_methods(caption, evidence_by_id)
                if caption.presentation.accepted is False:
                    reason = "rejected_caption"
                elif EvidenceMethod.OCR in caption_methods:
                    reason = "unapproved_ocr"
                else:
                    reason = "unapproved_caption"
                _add_exclusion(
                    exclusions,
                    element_id=caption.id,
                    reason=reason,
                    relationship_ids=edge.relationship_ids,
                )
                ineligible_caption_relationship_ids.update(edge.relationship_ids)

            audited_ocr_relationship_ids: set[str] = set()
            if element_type in _VISUAL_TYPES:
                if direct_caption_claims:
                    owner_has_ocr = any(
                        evidence.method is EvidenceMethod.OCR
                        and bool(_plain_value(evidence.value))
                        for evidence in evidence_by_element.get(primary_id, ())
                    )
                    if owner_has_ocr:
                        _add_exclusion(
                            exclusions,
                            element_id=primary_id,
                            reason="caption_precedes_subordinate_ocr",
                        )
                for edge in outgoing.get(primary_id, []):
                    if edge.type is not RelationshipType.CONTAINS:
                        continue
                    child = elements[edge.target_id]
                    if not _has_ocr(child, evidence_by_id):
                        continue
                    if child.id in alternative_targets:
                        continue
                    selected = assignment.get(child.id)
                    if selected is not None and selected.owner_id != primary_id:
                        reason = "already_claimed"
                    elif (
                        child.presentation_role == "diagnostic"
                        or child.presentation.accepted is False
                    ):
                        reason = "rejected_ocr"
                    elif direct_caption_claims:
                        reason = "caption_precedes_subordinate_ocr"
                    elif not _visual_ocr_allowed(primary):
                        reason = "unapproved_ocr"
                    elif selected is None:
                        reason = "empty_contribution"
                    else:
                        continue
                    _add_exclusion(
                        exclusions,
                        element_id=child.id,
                        reason=reason,
                        relationship_ids=edge.relationship_ids,
                    )
                    audited_ocr_relationship_ids.update(edge.relationship_ids)
            evidence_only_relationship_ids: set[str] = set()
            evidence_only_types = {
                RelationshipType.LEGEND_OF,
                RelationshipType.AXIS_OF,
                RelationshipType.ANNOTATION_OF,
                RelationshipType.REFERENCES,
            }
            for edge in (
                *incoming.get(primary_id, []),
                *outgoing.get(primary_id, []),
            ):
                if edge.type not in evidence_only_types:
                    continue
                related_id = (
                    edge.source_id if edge.target_id == primary_id else edge.target_id
                )
                if related_id in primary_set:
                    continue
                _add_exclusion(
                    exclusions,
                    element_id=related_id,
                    reason="evidence_only_relationship",
                    relationship_ids=edge.relationship_ids,
                )
                evidence_only_relationship_ids.update(edge.relationship_ids)
            for edge, related_id in (
                *(
                    (edge, edge.source_id)
                    for edge in incoming.get(primary_id, [])
                    if edge.type
                    in {
                        RelationshipType.CAPTION_OF,
                        RelationshipType.SOURCE_NOTE_OF,
                        RelationshipType.FOOTNOTE_OF,
                    }
                ),
                *(
                    (edge, edge.target_id)
                    for edge in outgoing.get(primary_id, [])
                    if edge.type is RelationshipType.CONTAINS
                ),
            ):
                if related_id not in alternative_targets:
                    continue
                assertion_ids = list(edge.relationship_ids)
                _add_exclusion(
                    exclusions,
                    element_id=related_id,
                    reason="alternate_representation",
                    relationship_ids=assertion_ids,
                )
                evidence_only_relationship_ids.update(assertion_ids)
            for edge in incoming.get(primary_id, []):
                resolved_alternative = alternative_targets.get(edge.source_id)
                if (
                    edge.type is not RelationshipType.ALTERNATIVE_OF
                    or (
                        resolved_alternative is not None
                        and resolved_alternative != primary_id
                    )
                    or (resolved_alternative is None and edge.source_id in primary_set)
                ):
                    continue
                _add_exclusion(
                    exclusions,
                    element_id=edge.source_id,
                    reason="alternate_representation",
                    relationship_ids=edge.relationship_ids,
                )
                evidence_only_relationship_ids.update(edge.relationship_ids)
            for edge in outgoing.get(primary_id, []):
                if (
                    edge.type is not RelationshipType.ALTERNATIVE_OF
                    or alternative_targets.get(edge.target_id) != primary_id
                ):
                    continue
                _add_exclusion(
                    exclusions,
                    element_id=edge.target_id,
                    reason="alternate_representation",
                    relationship_ids=edge.relationship_ids,
                )
                evidence_only_relationship_ids.update(edge.relationship_ids)
            for edge in (
                *incoming.get(primary_id, []),
                *outgoing.get(primary_id, []),
            ):
                if edge.type is not RelationshipType.ALTERNATIVE_OF:
                    continue
                unaudited_ids = [
                    relationship_id
                    for relationship_id in edge.relationship_ids
                    if relationship_id not in evidence_only_relationship_ids
                ]
                if not unaudited_ids:
                    continue
                related_id = (
                    edge.source_id if edge.target_id == primary_id else edge.target_id
                )
                _add_exclusion(
                    exclusions,
                    element_id=related_id,
                    reason="evidence_only_relationship",
                    relationship_ids=unaudited_ids,
                )
                evidence_only_relationship_ids.update(unaudited_ids)
            claimed_source_ids = {claim.source_id for claim in owner_claims}
            for edge in incoming.get(primary_id, []):
                if (
                    edge.type
                    not in {
                        RelationshipType.SOURCE_NOTE_OF,
                        RelationshipType.FOOTNOTE_OF,
                    }
                    or edge.source_id in claimed_source_ids
                ):
                    continue
                _add_exclusion(
                    exclusions,
                    element_id=edge.source_id,
                    reason="evidence_only_relationship",
                    relationship_ids=edge.relationship_ids,
                )
                evidence_only_relationship_ids.update(edge.relationship_ids)
            audited_nested_relationship_ids: set[str] = set()
            selected_nested_edge_keys = {
                (
                    claim.edge.type,
                    claim.edge.source_id,
                    claim.edge.target_id,
                )
                for claim in nested_claims
            }
            for spec in nested_visual_specs_by_owner.get(primary_id, ()):
                visual = elements[spec.visual_id]
                visual_is_rejected = (
                    visual.presentation_role == "diagnostic"
                    or visual.presentation.accepted is False
                )
                path_claims = [
                    claim
                    for claim in nested_claims
                    if claim.nested_visual_id == spec.visual_id
                ]
                path_has_caption = any(claim.kind == "caption" for claim in path_claims)
                if path_has_caption and any(
                    evidence.method is EvidenceMethod.OCR
                    and bool(_plain_value(evidence.value))
                    for evidence in evidence_by_element.get(visual.id, ())
                ):
                    _add_exclusion(
                        exclusions,
                        element_id=visual.id,
                        reason="caption_precedes_subordinate_ocr",
                    )
                for edge in incoming.get(visual.id, []):
                    edge_key = (
                        edge.type,
                        edge.source_id,
                        edge.target_id,
                    )
                    if edge_key in selected_nested_edge_keys:
                        continue
                    source = elements[edge.source_id]
                    if visual_is_rejected and edge.type in {
                        RelationshipType.CAPTION_OF,
                        RelationshipType.SOURCE_NOTE_OF,
                        RelationshipType.FOOTNOTE_OF,
                        *evidence_only_types,
                    }:
                        reason = "evidence_only_relationship"
                    elif edge.type is RelationshipType.CAPTION_OF:
                        if source.id in alternative_targets:
                            reason = "alternate_representation"
                        elif source.presentation.accepted is False:
                            reason = "rejected_caption"
                        elif _caption_eligible(source, visual, evidence_by_id):
                            selected = assignment.get(source.id)
                            reason = (
                                "already_claimed"
                                if selected is not None
                                else "empty_contribution"
                            )
                        elif EvidenceMethod.OCR in _evidence_methods(
                            source, evidence_by_id
                        ):
                            reason = "unapproved_ocr"
                        else:
                            reason = "unapproved_caption"
                    elif edge.type in {
                        RelationshipType.SOURCE_NOTE_OF,
                        RelationshipType.FOOTNOTE_OF,
                    }:
                        selected = assignment.get(source.id)
                        reason = (
                            "already_claimed"
                            if selected is not None
                            else "evidence_only_relationship"
                        )
                    elif edge.type in evidence_only_types:
                        reason = "evidence_only_relationship"
                    else:
                        continue
                    _add_exclusion(
                        exclusions,
                        element_id=source.id,
                        reason=reason,
                        relationship_ids=edge.relationship_ids,
                    )
                    audited_nested_relationship_ids.update(edge.relationship_ids)
                for edge in outgoing.get(visual.id, []):
                    if edge.type in evidence_only_types:
                        _add_exclusion(
                            exclusions,
                            element_id=edge.target_id,
                            reason="evidence_only_relationship",
                            relationship_ids=edge.relationship_ids,
                        )
                        audited_nested_relationship_ids.update(edge.relationship_ids)
                        continue
                    if edge.type is not RelationshipType.CONTAINS:
                        continue
                    child = elements[edge.target_id]
                    if not _has_ocr(child, evidence_by_id):
                        continue
                    edge_key = (
                        edge.type,
                        edge.source_id,
                        edge.target_id,
                    )
                    if edge_key in selected_nested_edge_keys:
                        continue
                    selected = assignment.get(child.id)
                    if child.id in alternative_targets:
                        reason = "alternate_representation"
                    elif visual_is_rejected:
                        reason = "rejected_ocr"
                    elif (
                        child.presentation_role == "diagnostic"
                        or child.presentation.accepted is False
                    ):
                        reason = "rejected_ocr"
                    elif path_has_caption:
                        reason = "caption_precedes_subordinate_ocr"
                    elif not _visual_ocr_allowed(visual):
                        reason = "unapproved_ocr"
                    elif selected is not None:
                        reason = "already_claimed"
                    else:
                        reason = "empty_contribution"
                    _add_exclusion(
                        exclusions,
                        element_id=child.id,
                        reason=reason,
                        relationship_ids=edge.relationship_ids,
                    )
                    audited_nested_relationship_ids.update(edge.relationship_ids)
            candidate_edge_keys = {
                (
                    claim.edge.type,
                    claim.edge.source_id,
                    claim.edge.target_id,
                )
                for claim in owner_candidates
            }
            candidate_edge_keys.update(
                (
                    claim.bridge_edge.type,
                    claim.bridge_edge.source_id,
                    claim.bridge_edge.target_id,
                )
                for claim in owner_claims
                if claim.bridge_edge is not None
            )
            candidate_edge_keys.update(
                (
                    claim.edge.type,
                    claim.edge.source_id,
                    claim.edge.target_id,
                )
                for claim in structure_claims
            )
            if element_type in _STRUCTURED_OWNER_TYPES:
                pending_containers = [primary_id]
                visited_containers: set[str] = set()
                while pending_containers:
                    container_id = pending_containers.pop()
                    if container_id in visited_containers:
                        continue
                    visited_containers.add(container_id)
                    declared_ids = {
                        child.id
                        for child in declared_structure_by_owner.get(container_id, ())
                    }
                    for edge in outgoing.get(container_id, []):
                        if (
                            edge.type is not RelationshipType.CONTAINS
                            or edge.target_id not in declared_ids
                        ):
                            continue
                        child = elements[edge.target_id]
                        if child.type.casefold() in _STRUCTURED_OWNER_TYPES:
                            pending_containers.append(child.id)
                        edge_key = (
                            edge.type,
                            edge.source_id,
                            edge.target_id,
                        )
                        if edge_key in candidate_edge_keys:
                            continue
                        _add_exclusion(
                            exclusions,
                            element_id=child.id,
                            reason=(
                                "alternate_representation"
                                if child.id in alternative_targets
                                else "evidence_only_relationship"
                            ),
                            relationship_ids=edge.relationship_ids,
                        )
                        evidence_only_relationship_ids.update(edge.relationship_ids)
                for edge in outgoing.get(primary_id, []):
                    if edge.type is not RelationshipType.CONTAINS:
                        continue
                    edge_key = (
                        edge.type,
                        edge.source_id,
                        edge.target_id,
                    )
                    if edge_key in candidate_edge_keys or set(
                        edge.relationship_ids
                    ).issubset(evidence_only_relationship_ids):
                        continue
                    child = elements[edge.target_id]
                    _add_exclusion(
                        exclusions,
                        element_id=child.id,
                        reason=(
                            "alternate_representation"
                            if child.id in alternative_targets
                            else "evidence_only_relationship"
                        ),
                        relationship_ids=edge.relationship_ids,
                    )
                    evidence_only_relationship_ids.update(edge.relationship_ids)
            for edge in outgoing.get(primary_id, []):
                if edge.type is not RelationshipType.CONTAINS:
                    continue
                child = elements[edge.target_id]
                if child.presentation_role != "diagnostic" or (
                    element_type in _VISUAL_TYPES and _has_ocr(child, evidence_by_id)
                ):
                    continue
                _add_exclusion(
                    exclusions,
                    element_id=child.id,
                    reason="evidence_only_relationship",
                    relationship_ids=edge.relationship_ids,
                )
                evidence_only_relationship_ids.update(edge.relationship_ids)

            relationship_ids = sorted(
                {
                    relationship_id
                    for claim in owner_claims
                    for relationship_id in claim.edge.relationship_ids
                }
                | audited_candidate_relationship_ids
                | audited_ocr_relationship_ids
                | audited_nested_relationship_ids
                | evidence_only_relationship_ids
                | ineligible_caption_relationship_ids
            )
            contributing_ids = [primary_id]
            for claim in owner_claims:
                if claim.source_id not in contributing_ids:
                    contributing_ids.append(claim.source_id)
            proven_visual_owner_output = proven_visual_outputs.get(
                primary_id, ""
            )
            filtered_visual_owner_output = filtered_visual_owner_outputs.get(
                primary_id, ""
            )
            if proven_visual_owner_output or filtered_visual_owner_output:
                duplicate_ocr_ids = {
                    claim.source_id for claim in direct_ocr_claims
                }
                for claim in direct_ocr_claims:
                    _add_exclusion(
                        exclusions,
                        element_id=claim.source_id,
                        reason="evidence_only_relationship",
                        relationship_ids=claim.edge.relationship_ids,
                    )
                contributing_ids = [
                    element_id
                    for element_id in contributing_ids
                    if element_id not in duplicate_ocr_ids
                ]

            caption_claims = (
                *direct_caption_claims,
                *(
                    claim
                    for claim in nested_claims
                    if claim.kind == "caption"
                    and claim.nested_visual_id is not None
                    and not _is_visual_payload(elements[claim.nested_visual_id])
                ),
            )
            captions = [
                (claim.output_override or _element_output(elements[claim.source_id]))
                for claim in caption_claims
            ]
            notes = [
                (claim.output_override or _element_output(elements[claim.source_id]))
                for claim in (
                    *direct_note_claims,
                    *(
                        claim
                        for claim in nested_claims
                        if claim.kind in {"source_note", "footnote"}
                        and claim.nested_visual_id is not None
                        and not _is_visual_payload(elements[claim.nested_visual_id])
                    ),
                )
            ]
            markdown_parts = [markdown for markdown, _text in captions if markdown]
            text_parts = [text for _markdown, text in captions if text]

            if element_type in _VISUAL_TYPES:
                structured_visual = structured_visual_outputs.get(primary_id)
                if structured_visual is not None:
                    # The closed serialization owns the chart/diagram body and
                    # any caption it declares.  An external canonical caption
                    # is retained only when the serialization explicitly says
                    # that it contains none, so either source renders once.
                    owner_layout_projection = primary.properties.get(
                        "layout_projection"
                    )
                    owner_is_layout_managed = (
                        isinstance(owner_layout_projection, Mapping)
                        and owner_layout_projection.get("story") == "P03-US02"
                    )
                    if owner_is_layout_managed:
                        # P03-US02 projects the caption as its own primary
                        # block.  On terminal re-entry the raw CAPTION_OF edge
                        # can resolve directly to that already-projected
                        # primary element.  The structured visual intentionally
                        # excludes the caption from its inline serialization,
                        # so it must also exclude the caption element from its
                        # contributor ledger; the relationship remains as
                        # evidence on both blocks.
                        external_caption_ids = {
                            claim.source_id for claim in caption_claims
                        }
                        contributing_ids = [
                            element_id
                            for element_id in contributing_ids
                            if element_id not in external_caption_ids
                        ]
                    inline_captions = (
                        []
                        if owner_is_layout_managed
                        else [
                            (
                                claim.output_override
                                or _element_output(elements[claim.source_id])
                            )
                            for claim in caption_claims
                            if not (
                                any(
                                    relationship_id
                                    in layout_caption_source_relationship_ids
                                    for relationship_id in claim.edge.relationship_ids
                                )
                                or (
                                    claim.source_id in primary_set
                                    and isinstance(
                                        elements[
                                            claim.source_id
                                        ].properties.get("layout_projection"),
                                        Mapping,
                                    )
                                    and elements[claim.source_id].properties[
                                        "layout_projection"
                                    ].get("story")
                                    == "P03-US02"
                                )
                            )
                        ]
                    )
                    inline_markdown = [
                        markdown for markdown, _text in inline_captions if markdown
                    ]
                    inline_text = [
                        text for _markdown, text in inline_captions if text
                    ]
                    markdown_parts = [
                        *(
                            inline_markdown
                            if structured_visual.caption_occurrences == 0
                            else []
                        ),
                        structured_visual.markdown,
                    ]
                    text_parts = [
                        *(
                            inline_text
                            if structured_visual.caption_occurrences == 0
                            else []
                        ),
                        structured_visual.text,
                    ]
                elif proven_visual_owner_output:
                    markdown_parts.append(proven_visual_owner_output)
                    text_parts.append(proven_visual_owner_output)
                elif filtered_visual_owner_output or independent_visual_output_sequences.get(
                    primary_id
                ):
                    if filtered_visual_owner_output:
                        markdown_parts.append(filtered_visual_owner_output)
                        text_parts.append(filtered_visual_owner_output)
                    else:
                        fallback_ocr_values = [
                            (
                                claim.output_override
                                or _element_output(elements[claim.source_id])
                            )
                            for claim in direct_ocr_claims
                        ]
                        if not fallback_ocr_values and _visual_ocr_allowed(primary):
                            owner_ocr = [
                                _plain_value(evidence.value)
                                for evidence in evidence_by_element.get(
                                    primary_id, ()
                                )
                                if evidence.method is EvidenceMethod.OCR
                                and _plain_value(evidence.value)
                            ]
                            if owner_ocr:
                                value = owner_ocr[0]
                                fallback_ocr_values = [(value, value)]
                        markdown_parts.extend(
                            value
                            for value, _text in fallback_ocr_values
                            if value
                        )
                        text_parts.extend(
                            value
                            for _markdown, value in fallback_ocr_values
                            if value
                        )
                    native_child_values = independent_visual_output_sequences.get(
                        primary_id, ()
                    )
                    markdown_parts.extend(native_child_values)
                    text_parts.extend(native_child_values)
                elif not direct_caption_claims:
                    ocr_values = [
                        (
                            claim.output_override
                            or _element_output(elements[claim.source_id])
                        )
                        for claim in direct_ocr_claims
                    ]
                    if not ocr_values and _visual_ocr_allowed(primary):
                        owner_ocr = [
                            _plain_value(evidence.value)
                            for evidence in evidence_by_element.get(primary_id, ())
                            if evidence.method is EvidenceMethod.OCR
                            and _plain_value(evidence.value)
                        ]
                        if owner_ocr:
                            value = owner_ocr[0]
                            ocr_values = [(value, value)]
                    markdown_parts.extend(
                        markdown for markdown, _text in ocr_values if markdown
                    )
                    text_parts.extend(text for _markdown, text in ocr_values if text)
                model_markdown, model_text = (
                    project_visual_model_evidence(primary.visual_model_evidence)
                    if primary.visual_model_evidence is not None
                    else ("", "")
                )
                if model_markdown:
                    markdown_parts.append(model_markdown)
                if model_text:
                    text_parts.append(model_text)
                markdown_parts.extend(markdown for markdown, _text in notes if markdown)
                text_parts.extend(text for _markdown, text in notes if text)
                markdown = "\n\n".join(markdown_parts).strip()
                text = "\n\n".join(text_parts).strip()
                if not markdown and not text:
                    has_unapproved_ocr = any(
                        exclusion.reason == "unapproved_ocr"
                        for exclusion in exclusions.values()
                    ) or any(
                        evidence.method is EvidenceMethod.OCR
                        and bool(_plain_value(evidence.value))
                        for evidence in evidence_by_element.get(primary_id, ())
                    )
                    blocks.append(
                        CanonicalBlock(
                            id=block_id,
                            page_id=page.id,
                            primary_element_id=primary_id,
                            primary_element_type=primary.type,
                            scope=scope,
                            markdown="",
                            text="",
                            contributing_element_ids=[],
                            relationship_ids=relationship_ids,
                            excluded_contributions=sorted(
                                exclusions.values(),
                                key=lambda value: (
                                    value.element_id,
                                    value.reason,
                                ),
                            ),
                            omission_reason=(
                                "unsupported_primary_ocr"
                                if has_unapproved_ocr
                                else "empty_visual"
                            ),
                        )
                    )
                    continue
            else:
                visual_outputs: dict[str, tuple[str, str]] = {}
                for spec in nested_visual_specs_by_owner.get(primary_id, ()):
                    path_claims = [
                        claim
                        for claim in nested_claims
                        if claim.nested_visual_id == spec.visual_id
                    ]
                    path_captions = [
                        claim for claim in path_claims if claim.kind == "caption"
                    ]
                    path_ocr = [claim for claim in path_claims if claim.kind == "ocr"]
                    path_notes = [
                        claim
                        for claim in path_claims
                        if claim.kind in {"source_note", "footnote"}
                    ]
                    content_claims = path_captions if path_captions else path_ocr
                    content_claims = [*content_claims, *path_notes]
                    outputs = [
                        (
                            claim.output_override
                            or _element_output(elements[claim.source_id])
                        )
                        for claim in content_claims
                    ]
                    source_output = (
                        "\n\n".join(
                            markdown for markdown, _text in outputs if markdown
                        ).strip(),
                        "\n\n".join(
                            text for _markdown, text in outputs if text
                        ).strip(),
                    )
                    visual_outputs[spec.visual_id] = _append_visual_model_evidence(
                        elements[spec.visual_id],
                        source_output,
                    )
                selected_ids_by_container: dict[str, set[str]] = {}
                for claim in structure_claims:
                    selected_ids_by_container.setdefault(
                        claim.edge.source_id, set()
                    ).add(claim.source_id)
                active_nested_visual_ids = {
                    claim.nested_visual_id
                    for claim in nested_claims
                    if claim.kind in {"caption", "ocr"}
                    and claim.nested_visual_id is not None
                }
                active_nested_visual_ids.update(
                    spec.visual_id
                    for spec in nested_visual_specs_by_owner.get(primary_id, ())
                    if elements[spec.visual_id].visual_model_evidence is not None
                )
                for spec in nested_visual_specs_by_owner.get(primary_id, ()):
                    selected_bridge = assignment.get(spec.visual_id)
                    if (
                        spec.visual_id not in active_nested_visual_ids
                        or selected_bridge is None
                        or selected_bridge.owner_id != primary_id
                        or selected_bridge.edge != spec.structure_edge
                    ):
                        continue
                    selected_ids_by_container.setdefault(
                        spec.structure_edge.source_id, set()
                    ).add(spec.visual_id)
                selected_structure_by_owner = {
                    container_id: [
                        child
                        for child in declared_children
                        if child.id
                        in selected_ids_by_container.get(container_id, set())
                    ]
                    for container_id, declared_children in (
                        declared_structure_by_owner.items()
                    )
                }
                declared_structure_elements = declared_structure_by_owner.get(
                    primary_id, []
                )
                structure_elements = selected_structure_by_owner.get(primary_id, [])
                resolved_structure_outputs = dict(visual_outputs)
                pending_structure: list[tuple[str, bool]] = [(primary_id, False)]
                visited_structure: set[str] = set()
                while pending_structure:
                    container_id, expanded = pending_structure.pop()
                    if expanded:
                        if container_id != primary_id:
                            resolved_structure_outputs[container_id] = _standard_output(
                                elements[container_id],
                                selected_structure_by_owner.get(container_id, ()),
                                declared_structure_elements=(
                                    declared_structure_by_owner.get(container_id, ())
                                ),
                                visual_outputs=(resolved_structure_outputs),
                                selected_structure_by_owner=(
                                    selected_structure_by_owner
                                ),
                                declared_structure_by_owner=(
                                    declared_structure_by_owner
                                ),
                            )
                        continue
                    if container_id in visited_structure:
                        continue
                    visited_structure.add(container_id)
                    pending_structure.append((container_id, True))
                    for child in reversed(
                        selected_structure_by_owner.get(container_id, ())
                    ):
                        if child.type.casefold() in _STRUCTURED_OWNER_TYPES:
                            pending_structure.append((child.id, False))
                body_markdown, body_text = _standard_output(
                    primary,
                    structure_elements,
                    declared_structure_elements=(declared_structure_elements),
                    visual_outputs=resolved_structure_outputs,
                    selected_structure_by_owner=(selected_structure_by_owner),
                    declared_structure_by_owner=(declared_structure_by_owner),
                )
                if body_markdown:
                    markdown_parts.append(body_markdown)
                if body_text:
                    text_parts.append(body_text)
                markdown_parts.extend(markdown for markdown, _text in notes if markdown)
                text_parts.extend(text for _markdown, text in notes if text)
                markdown = "\n\n".join(markdown_parts).strip()
                text = "\n\n".join(text_parts).strip()
                if not markdown and not text:
                    blocks.append(
                        CanonicalBlock(
                            id=block_id,
                            page_id=page.id,
                            primary_element_id=primary_id,
                            primary_element_type=primary.type,
                            scope=scope,
                            markdown="",
                            text="",
                            contributing_element_ids=[],
                            relationship_ids=relationship_ids,
                            excluded_contributions=sorted(
                                exclusions.values(),
                                key=lambda value: (
                                    value.element_id,
                                    value.reason,
                                ),
                            ),
                            omission_reason="empty_content",
                        )
                    )
                    continue

            blocks.append(
                CanonicalBlock(
                    id=block_id,
                    page_id=page.id,
                    primary_element_id=primary_id,
                    primary_element_type=primary.type,
                    scope=scope,
                    markdown=markdown,
                    text=text,
                    contributing_element_ids=contributing_ids,
                    relationship_ids=relationship_ids,
                    excluded_contributions=sorted(
                        exclusions.values(),
                        key=lambda value: (
                            value.element_id,
                            value.reason,
                        ),
                    ),
                )
            )

        pages.append(
            CanonicalPage(
                page_id=page.id,
                page_index=page.page_index,
                page_number=page.page_number,
                page_label=page.page_label,
                blocks=blocks,
                full=_view_for(blocks),
                body=_view_for([block for block in blocks if block.scope == "body"]),
                header=_view_for(
                    [block for block in blocks if block.scope == "header"]
                ),
                footer=_view_for(
                    [block for block in blocks if block.scope == "footer"]
                ),
                page_identity=page.page_identity,
            )
        )

    _audit_relationship_assertions(
        pages,
        edge_groups,
        elements,
    )
    # Layout-managed note assertions are canonical-inert so the note remains
    # a distinct primary block instead of being consumed into its owner.
    # Retain the public assertion IDs on both endpoint blocks directly from
    # the strict compatibility descriptors.
    blocks_by_primary_id = {
        block.primary_element_id: block for page in pages for block in page.blocks
    }
    for element in validated.elements:
        projection = element.properties.get("source_note_projection")
        block = blocks_by_primary_id.get(element.id)
        if (
            block is None
            or not isinstance(projection, Mapping)
            or projection.get("story") != "P03-US03"
        ):
            continue
        relationship_ids: set[str] = set()
        relationship_id = projection.get("relationship_id")
        if isinstance(relationship_id, str) and relationship_id:
            relationship_ids.add(relationship_id)
        legacy = _legacy_item(element)
        for descriptor in legacy.get("relationships") or []:
            if (
                isinstance(descriptor, Mapping)
                and descriptor.get("type")
                in {
                    RelationshipType.SOURCE_NOTE_OF.value,
                    RelationshipType.FOOTNOTE_OF.value,
                }
                and isinstance(descriptor.get("id"), str)
                and str(descriptor["id"]).startswith("layout-rel-")
            ):
                relationship_ids.add(str(descriptor["id"]))
        block.relationship_ids = sorted(set(block.relationship_ids) | relationship_ids)
    document_blocks = [block for page in pages for block in page.blocks]
    return CanonicalPresentation.model_validate(
        {
            "schema_version": PRESENTATION_SCHEMA_VERSION,
            "source_ir_version": validated.ir_version,
            "policy_id": PRESENTATION_POLICY_ID,
            "pages": pages,
            "full": _view_for(document_blocks),
            "body": _view_for(
                [block for block in document_blocks if block.scope == "body"]
            ),
            "header": _view_for(
                [block for block in document_blocks if block.scope == "header"]
            ),
            "footer": _view_for(
                [block for block in document_blocks if block.scope == "footer"]
            ),
        },
        context={"allow_unresolved_suppressors": True},
    )


def _build_canonical_presentation_from_validated(
    validated: DocumentIR,
) -> CanonicalPresentation:
    """Build from an IR whose full public validation already succeeded."""

    base = _build_canonical_presentation(validated, {})
    primary_sequence = [
        element_id
        for page in sorted(validated.pages, key=lambda value: value.page_index)
        for element_id in page.presentation_element_ids
    ]
    primary_rank = {
        element_id: index for index, element_id in enumerate(primary_sequence)
    }
    elements = {element.id: element for element in validated.elements}
    stable_rank_hints: dict[str, tuple[int, int, float, str]] = {
        element_id: (rank, 0, -1.0, element_id)
        for element_id, rank in primary_rank.items()
    }
    for page in base.pages:
        for block in page.blocks:
            if block.omission_reason is not None:
                continue
            owner_rank = primary_rank[block.primary_element_id]
            for contribution_index, element_id in enumerate(
                block.contributing_element_ids
            ):
                if element_id in primary_rank:
                    continue
                reading_order = elements[element_id].reading_order
                candidate = (
                    owner_rank,
                    contribution_index,
                    (float(reading_order) if reading_order is not None else math.inf),
                    element_id,
                )
                current = stable_rank_hints.get(element_id)
                if current is None or candidate < current:
                    stable_rank_hints[element_id] = candidate

    active_targets = _alternative_suppressors(
        validated,
        base,
        stable_rank_hints=stable_rank_hints,
    )
    if not active_targets:
        return CanonicalPresentation.model_validate(base.model_dump(mode="json"))

    def render(
        targets: Mapping[str, str],
    ) -> tuple[CanonicalPresentation, set[str]]:
        presentation = (
            _build_canonical_presentation(validated, targets) if targets else base
        )
        presented = {
            element_id
            for page in presentation.pages
            for block in page.blocks
            if block.omission_reason is None
            for element_id in block.contributing_element_ids
        }
        return presentation, presented

    state_order: list[tuple[tuple[str, str], ...]] = []
    history: dict[
        tuple[tuple[str, str], ...],
        tuple[CanonicalPresentation, bool],
    ] = {}
    while True:
        state = tuple(sorted(active_targets.items()))
        resolved, presented = render(active_targets)
        is_valid = all(target_id in presented for target_id in active_targets.values())
        state_order.append(state)
        history[state] = (resolved, is_valid)

        discovered = _alternative_suppressors(
            validated,
            resolved,
            candidate_source_ids=tuple(active_targets),
            stable_rank_hints=stable_rank_hints,
        )
        next_targets = {
            source_id: target_id
            for source_id, target_id in discovered.items()
            if target_id in presented
        }
        next_state = tuple(sorted(next_targets.items()))
        if next_state == state:
            return CanonicalPresentation.model_validate(
                resolved.model_dump(mode="json")
            )
        if next_state in history:
            cycle_start = state_order.index(next_state)
            valid_states = [
                candidate_state
                for candidate_state in state_order[cycle_start:]
                if history[candidate_state][1]
            ]
            if not valid_states:
                return CanonicalPresentation.model_validate(
                    base.model_dump(mode="json")
                )
            selected = min(
                valid_states,
                key=lambda candidate_state: (
                    -len(candidate_state),
                    candidate_state,
                ),
            )
            return CanonicalPresentation.model_validate(
                history[selected][0].model_dump(mode="json")
            )
        active_targets = next_targets


def build_canonical_presentation(ir: DocumentIR) -> CanonicalPresentation:
    """Build one deterministic presentation contract from a validated IR."""

    validated = DocumentIR.model_validate(ir.model_dump(mode="json"))
    return _build_canonical_presentation_from_validated(validated)
