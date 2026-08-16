"""Versioned internal evidence and relationship intermediate representation.

The public v1 response remains the compatibility contract.  This module gives
the parser a strict internal graph that can retain source evidence and typed
relationships without asking existing clients to understand it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from copy import deepcopy
from enum import Enum
from typing import Annotated, Any, Iterable, Literal, Mapping, MutableMapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import PageIdentity, RunningRegionDescriptor
from app.services.source_note_contracts import (
    is_eligible_unresolved_table_candidate,
)
from app.services.visual_model_contracts import VisualModelEvidenceBundle


IR_VERSION = "1.0"
IDENTITY_TRANSFORM = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
RAW_GENERATION_PROVENANCE_PROPERTY = "raw_generation_or_model_provenance"
_MAX_PROVENANCE_DEPTH = 4
_MAX_PROVENANCE_MAPPING_ENTRIES = 64
_MAX_PROVENANCE_SEQUENCE_ENTRIES = 64
_MAX_PROVENANCE_NODE_BUDGET = 256
_MAX_EXPLICIT_EVIDENCE_METHODS = 16
_MAX_PROVENANCE_NAME_BYTES = 32
_MAX_TEXT_RUN_TEXT_BYTES = 16 * 1024
_MAX_TEXT_RUN_FONT_NAME_BYTES = 256
_MAX_TEXT_RUNS_PER_PAGE = 4_096
_MAX_TEXT_RUNS_PER_DOCUMENT = 10_000
_MAX_TEXT_RULES_PER_PAGE = 4_096
_MAX_TEXT_RULES_PER_DOCUMENT = 10_000
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_MAX_TEXT_COLOR_COMPONENT_DELTA = 1.0 / 255.0
MAX_FORM_SEMANTIC_RECORDS_PER_PAGE = 8_192
MAX_FORM_SEMANTIC_RECORDS_PER_DOCUMENT = 32_768
MAX_FORM_RELATIONSHIPS_PER_PAGE = 32_768
MAX_FORM_RELATIONSHIPS_PER_DOCUMENT = 65_536
MAX_FORM_GROUPS_PER_PAGE = 256
MAX_FORM_GROUPS_PER_DOCUMENT = 2_048
MAX_FORM_FIELDS_PER_GROUP = 128
MAX_FORM_VALUE_REGIONS_PER_GROUP = 128
MAX_FORM_CONTROLS_PER_GROUP = 256
MAX_FORM_LABELS_PER_GROUP = 256
MAX_FORM_KEY_VALUE_PAIRS_PER_GROUP = 32
MAX_FORM_CONCERNS_PER_GROUP = 13
# Compatibility ceiling for callers that still need the largest per-role
# bound. Production group validation uses the role-specific limits above.
MAX_FORM_CLASS_RECORDS_PER_GROUP = MAX_FORM_CONTROLS_PER_GROUP
MAX_FORM_CLASS_RECORDS_PER_PAGE = 2_048
MAX_FORM_CLASS_RECORDS_PER_DOCUMENT = 10_000
_MAX_FORM_SOURCE_IDENTITIES_PER_RECORD = 64
_MAX_FORM_TEXT_BYTES = 16 * 1024
_MAX_FORM_ID_BYTES = 256
MAX_OUTLINE_GROUPS_PER_PAGE = 256
MAX_OUTLINE_GROUPS_PER_DOCUMENT = 2_048
MAX_OUTLINE_NODES_PER_GROUP = 256
MAX_OUTLINE_NODES_PER_PAGE = 4_096
MAX_OUTLINE_NODES_PER_DOCUMENT = 32_768
MAX_OUTLINE_INTERSTITIALS_PER_GROUP = 64
MAX_OUTLINE_RELATIONSHIPS_PER_PAGE = 16_384
MAX_OUTLINE_RELATIONSHIPS_PER_DOCUMENT = 65_536
_MAX_OUTLINE_DEPTH = 8
_MAX_OUTLINE_MARKER_BYTES = 64
_MAX_OUTLINE_TEXT_BYTES = 16 * 1024
_MAX_OUTLINE_ID_BYTES = 256
_OUTLINE_BULLET_MARKERS = frozenset({"•", "◦", "-", "*", "▪", "‣"})
_OUTLINE_DECIMAL_MARKER = re.compile(r"^([1-9][0-9]{0,3})[.)]$")
_OUTLINE_ALPHA_MARKER = re.compile(r"^(?:([a-z])[.)]|\(([a-z])\))$")
_NonNegativeStrictInt = Annotated[int, Field(strict=True, ge=0)]
_TRUSTED_RAW_SOURCE_NAMES = frozenset(
    {
        "native",
        "ocr",
        "mixed",
        "recovered",
        "embedded",
        "vector",
    }
)
_TRUSTED_RAW_EVIDENCE_METHOD_NAMES = frozenset(
    {
        "native",
        "ocr",
        "vector",
        "embedded",
        "recovered",
    }
)


def _exclude_empty_list(value: list[Any]) -> bool:
    """Keep additive US05 collections absent on predecessor IR payloads."""

    return not value


def _exclude_none(value: Any | None) -> bool:
    """Keep additive optional contracts absent from predecessor IR payloads."""

    return value is None


def _require_bounded_form_string(
    value: str,
    *,
    label: str,
    maximum_bytes: int = _MAX_FORM_ID_BYTES,
) -> None:
    if not value or not value.strip():
        raise ValueError(f"{label} must be nonempty and non-whitespace")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{label} exceeds {maximum_bytes} UTF-8 bytes")


def _require_unique_form_ids(values: Sequence[str], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} repeats an ID")
    for value in values:
        _require_bounded_form_string(value, label=label)


class IRModel(BaseModel):
    """Strict base model for internal contracts."""

    model_config = ConfigDict(extra="forbid")


class EvidenceMethod(str, Enum):
    NATIVE = "native"
    OCR = "ocr"
    VECTOR = "vector"
    EMBEDDED = "embedded"
    RECOVERED = "recovered"
    MODEL = "model"
    DERIVED = "derived"


class RelationshipType(str, Enum):
    CONTAINS = "contains"
    CAPTION_OF = "caption_of"
    SOURCE_NOTE_OF = "source_note_of"
    FOOTNOTE_OF = "footnote_of"
    LEGEND_OF = "legend_of"
    AXIS_OF = "axis_of"
    READING_BEFORE = "reading_before"
    ALTERNATIVE_OF = "alternative_of"
    ANNOTATION_OF = "annotation_of"
    REFERENCES = "references"
    LABEL_OF = "label_of"
    VALUE_OF = "value_of"
    CONTROL_OF = "control_of"
    KEY_OF = "key_of"
    FORM_OVERLAY_OF = "form_overlay_of"
    OUTLINE_PARENT_OF = "outline_parent_of"
    OUTLINE_NEXT = "outline_next"
    OUTLINE_CONTINUATION_OF = "outline_continuation_of"


class CoordinateSystem(IRModel):
    id: str
    page_id: str
    unit: Literal["pt", "px"]
    origin: Literal["top_left", "bottom_left"] = "top_left"
    transform_to_page: tuple[float, float, float, float, float, float] | None = (
        IDENTITY_TRANSFORM
    )
    transform_unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_transform(self) -> "CoordinateSystem":
        if self.transform_to_page is None:
            if not self.transform_unavailable_reason:
                raise ValueError(
                    "an unavailable coordinate transform requires a reason"
                )
            return self
        if self.transform_unavailable_reason is not None:
            raise ValueError(
                "an available coordinate transform cannot have an unavailable reason"
            )
        if not all(math.isfinite(value) for value in self.transform_to_page):
            raise ValueError("coordinate transform values must be finite")
        a, b, c, d, _e, _f = self.transform_to_page
        if abs(a * d - b * c) <= 1e-12:
            raise ValueError("coordinate transform must be invertible")
        return self


class IRBoundingBox(IRModel):
    id: str
    coordinate_system_id: str
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)
    role: Literal[
        "page",
        "region",
        "element",
        "child",
        "field",
        "annotation",
    ] = "element"

    @model_validator(mode="after")
    def validate_finite(self) -> "IRBoundingBox":
        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("bounding box values must be finite")
        return self


class ConfidenceRecord(IRModel):
    scope: Literal["element", "evidence", "field"]
    score: float | None = Field(default=None, ge=0, le=1)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def require_score_or_reason(self) -> "ConfidenceRecord":
        if self.score is None and not self.unavailable_reason:
            raise ValueError("confidence must include a score or an unavailable reason")
        return self


class EvidenceRecord(IRModel):
    id: str
    element_id: str
    method: EvidenceMethod
    bbox_id: str | None = None
    value: Any | None = None
    confidence: ConfidenceRecord
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextColorRecord(IRModel):
    """Bounded normalized and source color evidence for text semantics."""

    space: Literal["gray", "rgb", "cmyk", "unknown"]
    components: tuple[float, ...] = ()
    raw_value: float | tuple[float, ...] | Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def validate_components(self) -> "TextColorRecord":
        expected_arity = {
            "gray": 1,
            "rgb": 3,
            "cmyk": 4,
            "unknown": 0,
        }[self.space]
        if len(self.components) != expected_arity:
            raise ValueError(f"{self.space} color requires {expected_arity} components")
        if not all(
            math.isfinite(component) and 0.0 <= component <= 1.0
            for component in self.components
        ):
            raise ValueError(
                "normalized color components must be finite values in [0, 1]"
            )

        if self.raw_value == "unknown":
            return self
        raw_components = (
            self.raw_value if isinstance(self.raw_value, tuple) else (self.raw_value,)
        )
        if not 1 <= len(raw_components) <= 4:
            raise ValueError("raw color must contain between one and four values")
        if not all(math.isfinite(component) for component in raw_components):
            raise ValueError("raw color values must be finite")
        return self


def _text_color_is_black(color: TextColorRecord) -> bool:
    if color.space in {"gray", "rgb"}:
        return all(
            abs(component) <= _MAX_TEXT_COLOR_COMPONENT_DELTA
            for component in color.components
        )
    if color.space == "cmyk":
        cyan, magenta, yellow, black = color.components
        return (
            abs(cyan) <= _MAX_TEXT_COLOR_COMPONENT_DELTA
            and abs(magenta) <= _MAX_TEXT_COLOR_COMPONENT_DELTA
            and abs(yellow) <= _MAX_TEXT_COLOR_COMPONENT_DELTA
            and abs(1.0 - black) <= _MAX_TEXT_COLOR_COMPONENT_DELTA
        )
    return False


class TextRuleRecord(IRModel):
    """One source-grounded horizontal vector rule."""

    id: str = Field(min_length=1, max_length=256)
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    page_id: str = Field(min_length=1, max_length=256)
    bbox_id: str = Field(min_length=1, max_length=256)
    source_object_kind: Literal["line", "rect"]
    source_object_index: _NonNegativeStrictInt
    color: TextColorRecord
    width: float = Field(gt=0)
    thickness: float = Field(gt=0)
    evidence_method: Literal[EvidenceMethod.VECTOR] = EvidenceMethod.VECTOR
    extraction_policy_id: Literal["p03-text-run-extraction-v1"]

    @model_validator(mode="after")
    def validate_geometry(self) -> "TextRuleRecord":
        if not math.isfinite(self.width) or not math.isfinite(self.thickness):
            raise ValueError("text rule dimensions must be finite")
        if (
            self.width < 2.0
            or self.thickness > 1.5
            or self.width / self.thickness < 3.0
        ):
            raise ValueError("text rule dimensions violate extraction bounds")
        return self


class TextRunRecord(IRModel):
    """One sparse source-grounded style or redline span."""

    id: str = Field(min_length=1, max_length=256)
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    page_id: str = Field(min_length=1, max_length=256)
    element_id: str = Field(min_length=1, max_length=256)
    target_path: (
        tuple[Literal["value"]]
        | tuple[Literal["cells"], _NonNegativeStrictInt, Literal["text"]]
        | tuple[
            Literal["items"],
            _NonNegativeStrictInt,
            Literal["value", "text"],
        ]
    )
    target_text_sha256: str = Field(pattern=_SHA256_PATTERN)
    change_group_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    text: str
    source_text: str
    start: _NonNegativeStrictInt
    end: Annotated[int, Field(strict=True, ge=1)]
    bbox_id: str = Field(min_length=1, max_length=256)
    font_size: float = Field(gt=0)
    font_name: str = Field(min_length=1)
    bold: bool
    italic: bool
    color: TextColorRecord
    source_character_indexes: list[_NonNegativeStrictInt] = Field(
        min_length=1,
        max_length=_MAX_TEXT_RUN_TEXT_BYTES,
    )
    change_state: Literal[
        "deleted",
        "inserted",
        "replacement",
        "unknown",
        "unchanged",
    ]
    decorations: list[Literal["strikethrough", "underline"]] = Field(
        default_factory=list
    )
    placeholder: bool
    rule_ids: list[str] = Field(default_factory=list, max_length=64)
    evidence_ids: list[str] = Field(min_length=1, max_length=64)
    evidence_method: EvidenceMethod
    semantic_derivation: Literal[
        "source_style",
        "same_color_midline_rule",
        "same_color_underline_rule",
        "same_color_underlined_placeholder",
        "native_tracked_change",
    ]
    extraction_policy_id: Literal["p03-text-run-extraction-v1"]
    association_policy_id: Literal["p03-text-run-association-v1"]

    @model_validator(mode="after")
    def validate_run(self) -> "TextRunRecord":
        if self.end <= self.start:
            raise ValueError("text run end must be greater than start")
        if not math.isfinite(self.font_size):
            raise ValueError("text run font size must be finite")
        if len(self.font_name.encode("utf-8")) > _MAX_TEXT_RUN_FONT_NAME_BYTES:
            raise ValueError("text run font name exceeds 256 UTF-8 bytes")
        if len(self.text.encode("utf-8")) > _MAX_TEXT_RUN_TEXT_BYTES:
            raise ValueError("text run text exceeds 16 KiB")
        if len(self.source_text.encode("utf-8")) > _MAX_TEXT_RUN_TEXT_BYTES:
            raise ValueError("text run source text exceeds 16 KiB")
        if any(index < 0 for index in self.source_character_indexes):
            raise ValueError("source character indexes must be nonnegative")
        if any(
            current <= previous
            for previous, current in zip(
                self.source_character_indexes,
                self.source_character_indexes[1:],
            )
        ):
            raise ValueError("source character indexes must be strictly increasing")
        if len(self.decorations) != len(set(self.decorations)):
            raise ValueError("text run repeats a decoration")
        decoration_order = {"strikethrough": 0, "underline": 1}
        if self.decorations != sorted(
            self.decorations,
            key=decoration_order.__getitem__,
        ):
            raise ValueError("text run decorations are out of canonical order")
        for label, identifiers in (
            ("rule", self.rule_ids),
            ("evidence", self.evidence_ids),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"text run repeats a {label} id")
            if any(
                not identifier or len(identifier) > 256 for identifier in identifiers
            ):
                raise ValueError(f"text run has an invalid {label} id")

        if not self.text or not self.source_text.strip():
            raise ValueError("text run text evidence cannot be empty")
        if self.semantic_derivation == "source_style":
            expected_state = (
                "unknown"
                if self.color.space != "unknown"
                and not _text_color_is_black(self.color)
                else "unchanged"
            )
            if (
                self.change_state != expected_state
                or self.decorations
                or self.placeholder
                or self.rule_ids
                or self.change_group_id is not None
                or self.evidence_method is not EvidenceMethod.NATIVE
            ):
                raise ValueError("source-style text run is inconsistent")
        elif self.semantic_derivation == "same_color_midline_rule":
            if (
                self.change_state != "deleted"
                or self.decorations != ["strikethrough"]
                or self.placeholder
                or not self.rule_ids
                or self.change_group_id is None
                or self.evidence_method is not EvidenceMethod.VECTOR
            ):
                raise ValueError("midline-rule text run is inconsistent")
        elif self.semantic_derivation == "same_color_underline_rule":
            if (
                self.change_state != "unchanged"
                or self.decorations != ["underline"]
                or self.placeholder
                or not self.rule_ids
                or self.change_group_id is None
                or self.evidence_method is not EvidenceMethod.VECTOR
            ):
                raise ValueError("underline-rule text run is inconsistent")
        elif self.semantic_derivation == "same_color_underlined_placeholder":
            if (
                self.change_state != "unknown"
                or self.decorations != ["underline"]
                or not self.placeholder
                or not self.rule_ids
                or self.change_group_id is None
                or self.evidence_method is not EvidenceMethod.VECTOR
                or not 3 <= len(self.text) <= 128
                or set(self.text) != {"_"}
                or self.source_text != self.text
            ):
                raise ValueError("underlined-placeholder text run is inconsistent")
        elif (
            self.change_state not in {"deleted", "inserted", "replacement"}
            or self.placeholder
            or self.rule_ids
            or self.change_group_id is not None
            or self.evidence_method is not EvidenceMethod.NATIVE
        ):
            raise ValueError("native tracked-change text run is inconsistent")
        return self


_FORM_LABEL_REPAIRS = frozenset(
    {
        ("PRO- JECT", "PROJECT"),
        ("WC STATU- TORY LIMITS", "WC STATUTORY LIMITS"),
        ("OTH- ER", "OTHER"),
    }
)


class _FormSemanticDescriptorBase(IRModel):
    """Fields shared by every strict P03-US06 semantic descriptor."""

    model_config = ConfigDict(extra="forbid", strict=True)

    policy_id: Literal["p03-form-semantics-v1"]
    role: str
    record_id: str
    group_element_id: str
    public_anchor_element_id: str

    @model_validator(mode="after")
    def validate_common_form_fields(self) -> "_FormSemanticDescriptorBase":
        for label, value in (
            ("form semantic record ID", self.record_id),
            ("form semantic group element ID", self.group_element_id),
            ("form semantic public anchor element ID", self.public_anchor_element_id),
        ):
            _require_bounded_form_string(value, label=label)
        return self


class FormGroupSemanticDescriptor(_FormSemanticDescriptorBase):
    role: Literal["group"]
    group_key: str
    status: Literal["resolved", "unresolved"]
    interactivity: Literal[
        "none",
        "static",
        "interactive",
        "mixed",
        "unknown",
    ]
    canonical_mode: Literal["inert", "replace"]
    anchor_public_item_id: str
    anchor_relationship_ids: list[str] = Field(max_length=1)
    contributor_public_item_ids: list[str] = Field(min_length=1, max_length=64)
    contributor_element_ids: list[str] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_group_fields(self) -> "FormGroupSemanticDescriptor":
        _require_bounded_form_string(self.group_key, label="form group key")
        _require_bounded_form_string(
            self.anchor_public_item_id,
            label="form group anchor public item ID",
        )
        _require_unique_form_ids(
            self.anchor_relationship_ids,
            label="form group anchor relationship IDs",
        )
        _require_unique_form_ids(
            self.contributor_public_item_ids,
            label="form group contributor public item IDs",
        )
        _require_unique_form_ids(
            self.contributor_element_ids,
            label="form group contributor element IDs",
        )
        if len(self.contributor_public_item_ids) != len(self.contributor_element_ids):
            raise ValueError("form group contributor arrays must have equal lengths")
        if self.anchor_public_item_id not in self.contributor_public_item_ids:
            raise ValueError("form group contributors must contain the public anchor")
        if self.public_anchor_element_id not in self.contributor_element_ids:
            raise ValueError("form group contributors must contain the element anchor")
        if self.contributor_public_item_ids.index(self.anchor_public_item_id) != (
            self.contributor_element_ids.index(self.public_anchor_element_id)
        ):
            raise ValueError("form group contributor anchors must map pairwise")
        return self


class FormFieldSemanticDescriptor(_FormSemanticDescriptorBase):
    role: Literal["field"]
    field_key: str
    label_element_ids: list[str] = Field(min_length=1, max_length=64)
    value_region_element_id: str
    control_element_ids: list[str] = Field(max_length=256)
    value: str | None
    value_state: Literal["empty", "present", "ambiguous", "not_applicable"]

    @model_validator(mode="after")
    def validate_field_fields(self) -> "FormFieldSemanticDescriptor":
        _require_bounded_form_string(self.field_key, label="form field key")
        _require_unique_form_ids(
            self.label_element_ids,
            label="form field label element IDs",
        )
        _require_bounded_form_string(
            self.value_region_element_id,
            label="form field value-region element ID",
        )
        _require_unique_form_ids(
            self.control_element_ids,
            label="form field control element IDs",
        )
        _validate_form_value(self.value, self.value_state, label="form field value")
        return self


class FormLabelSemanticDescriptor(_FormSemanticDescriptorBase):
    role: Literal["label"]
    label_role: Literal["field", "group", "control", "key"]
    text: str
    raw_text: str
    label_of_element_ids: list[str] = Field(max_length=256)
    key_of_element_ids: list[str] = Field(max_length=1)

    @model_validator(mode="after")
    def validate_label_fields(self) -> "FormLabelSemanticDescriptor":
        _require_bounded_form_string(
            self.text,
            label="form label text",
            maximum_bytes=_MAX_FORM_TEXT_BYTES,
        )
        _require_bounded_form_string(
            self.raw_text,
            label="form label raw text",
            maximum_bytes=_MAX_FORM_TEXT_BYTES,
        )
        _require_unique_form_ids(
            self.label_of_element_ids,
            label="form label-of element IDs",
        )
        _require_unique_form_ids(
            self.key_of_element_ids,
            label="form key-of element IDs",
        )
        if self.raw_text != self.text and (self.raw_text, self.text) not in (
            _FORM_LABEL_REPAIRS
        ):
            raise ValueError("form label uses an unauthorized text repair")
        if self.label_role == "field":
            if not 1 <= len(self.label_of_element_ids) <= 256:
                raise ValueError("field labels require 1-256 label-of targets")
            if self.key_of_element_ids:
                raise ValueError("field labels cannot have key-of targets")
        elif self.label_role in {"group", "control"}:
            if len(self.label_of_element_ids) != 1 or self.key_of_element_ids:
                raise ValueError(
                    "group/control labels require exactly one label-of target"
                )
        elif self.label_of_element_ids or len(self.key_of_element_ids) != 1:
            raise ValueError("key labels require exactly one key-of target")
        return self


class FormValueRegionSemanticDescriptor(_FormSemanticDescriptorBase):
    role: Literal["value_region"]
    owner_element_id: str
    excluded_label_element_ids: list[str] = Field(max_length=64)
    value: str | None
    value_state: Literal["empty", "present", "ambiguous", "not_applicable"]

    @model_validator(mode="after")
    def validate_value_region_fields(self) -> "FormValueRegionSemanticDescriptor":
        _require_bounded_form_string(
            self.owner_element_id,
            label="form value-region owner element ID",
        )
        _require_unique_form_ids(
            self.excluded_label_element_ids,
            label="form value-region excluded label element IDs",
        )
        _validate_form_value(
            self.value,
            self.value_state,
            label="form value-region value",
        )
        return self


class FormControlSemanticDescriptor(_FormSemanticDescriptorBase):
    role: Literal["control"]
    owner_field_element_id: str | None
    label_element_id: str | None
    control_type: Literal["checkbox", "radio"]
    state: Literal["checked", "unchecked", "ambiguous", "not_applicable"]
    origin: Literal["static_vector", "interactive_widget"]

    @model_validator(mode="after")
    def validate_control_fields(self) -> "FormControlSemanticDescriptor":
        if self.owner_field_element_id is not None:
            _require_bounded_form_string(
                self.owner_field_element_id,
                label="form control owner field element ID",
            )
        if self.label_element_id is not None:
            _require_bounded_form_string(
                self.label_element_id,
                label="form control label element ID",
            )
        return self


class FormKeyValuePairSemanticDescriptor(_FormSemanticDescriptorBase):
    role: Literal["key_value_pair"]
    pair_key: str
    key_label_element_id: str
    value_region_element_id: str
    key: str
    value: str
    value_state: Literal["present"]
    key_source_item_id: str
    value_source_item_id: str
    key_source_element_id: str
    value_source_element_id: str

    @model_validator(mode="after")
    def validate_key_value_fields(self) -> "FormKeyValuePairSemanticDescriptor":
        for label, value in (
            ("form key-value pair key", self.pair_key),
            ("form key-label element ID", self.key_label_element_id),
            ("form pair value-region element ID", self.value_region_element_id),
            ("form pair key source item ID", self.key_source_item_id),
            ("form pair value source item ID", self.value_source_item_id),
            ("form pair key source element ID", self.key_source_element_id),
            ("form pair value source element ID", self.value_source_element_id),
        ):
            _require_bounded_form_string(value, label=label)
        for label, value in (
            ("form pair key", self.key),
            ("form pair value", self.value),
        ):
            _require_bounded_form_string(
                value,
                label=label,
                maximum_bytes=_MAX_FORM_TEXT_BYTES,
            )
        if self.key_source_item_id == self.value_source_item_id:
            raise ValueError("form pair source item IDs must differ")
        if self.key_source_element_id == self.value_source_element_id:
            raise ValueError("form pair source element IDs must differ")
        return self


FormSemanticDescriptor = Annotated[
    FormGroupSemanticDescriptor
    | FormFieldSemanticDescriptor
    | FormLabelSemanticDescriptor
    | FormValueRegionSemanticDescriptor
    | FormControlSemanticDescriptor
    | FormKeyValuePairSemanticDescriptor,
    Field(discriminator="role"),
]


def _require_bounded_outline_string(
    value: str,
    *,
    label: str,
    maximum_bytes: int = _MAX_OUTLINE_ID_BYTES,
) -> None:
    if not value or not value.strip():
        raise ValueError(f"{label} must be nonempty and non-whitespace")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8") from exc
    if len(encoded) > maximum_bytes:
        raise ValueError(f"{label} exceeds {maximum_bytes} UTF-8 bytes")


def _require_unique_outline_ids(
    values: Sequence[str],
    *,
    label: str,
) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} repeats an ID")
    for value in values:
        _require_bounded_outline_string(value, label=label)


OutlinePublicPath = list[str | int]


class OutlineGroupSemanticDescriptor(IRModel):
    """Closed internal descriptor for one validated P03-US07 outline group."""

    model_config = ConfigDict(extra="forbid", strict=True)

    policy_id: Literal["p03-outline-structure-v1"]
    role: Literal["group"]
    record_id: str
    sequence_kind: Literal["unordered", "ordered", "legal"]
    marker_style: Literal["bullet", "decimal", "lower_alpha"]
    anchor_element_id: str
    anchor_public_item_id: str
    member_item_ids: list[str] = Field(
        min_length=2, max_length=MAX_OUTLINE_NODES_PER_GROUP
    )
    member_element_ids: list[str] = Field(
        min_length=2,
        max_length=MAX_OUTLINE_NODES_PER_GROUP,
    )
    continuation_element_ids: list[str] = Field(
        max_length=MAX_OUTLINE_INTERSTITIALS_PER_GROUP
    )
    relationship_ids: list[str] = Field(
        min_length=2,
        max_length=MAX_OUTLINE_RELATIONSHIPS_PER_PAGE,
    )
    canonical_contributor_element_ids: list[str] = Field(
        min_length=2,
        max_length=MAX_OUTLINE_NODES_PER_DOCUMENT,
    )
    canonical_relationship_ids: list[str] = Field(
        max_length=MAX_OUTLINE_RELATIONSHIPS_PER_DOCUMENT
    )

    @model_validator(mode="after")
    def validate_outline_group_fields(self) -> "OutlineGroupSemanticDescriptor":
        for label, value in (
            ("outline group record ID", self.record_id),
            ("outline anchor element ID", self.anchor_element_id),
            ("outline anchor public item ID", self.anchor_public_item_id),
        ):
            _require_bounded_outline_string(value, label=label)
        for label, values in (
            ("outline member item IDs", self.member_item_ids),
            ("outline member element IDs", self.member_element_ids),
            ("outline continuation element IDs", self.continuation_element_ids),
            ("outline relationship IDs", self.relationship_ids),
            (
                "outline canonical contributor element IDs",
                self.canonical_contributor_element_ids,
            ),
            (
                "outline canonical relationship IDs",
                self.canonical_relationship_ids,
            ),
        ):
            _require_unique_outline_ids(values, label=label)
        if len(self.member_item_ids) != len(self.member_element_ids):
            raise ValueError("outline member item/element arrays differ in length")
        if not set(self.relationship_ids).issubset(self.canonical_relationship_ids):
            raise ValueError(
                "outline canonical relationships omit a story relationship"
            )
        if self.anchor_element_id not in self.canonical_contributor_element_ids:
            raise ValueError("outline canonical contributors omit the anchor")
        if not set(self.member_element_ids).issubset(
            self.canonical_contributor_element_ids
        ) or not set(self.continuation_element_ids).issubset(
            self.canonical_contributor_element_ids
        ):
            raise ValueError("outline canonical contributors omit group custody")
        if (self.sequence_kind, self.marker_style) not in {
            ("unordered", "bullet"),
            ("ordered", "decimal"),
            ("legal", "lower_alpha"),
        }:
            raise ValueError("outline sequence kind/marker style differs")
        return self


class OutlineItemSemanticDescriptor(IRModel):
    """Closed internal descriptor attached to an existing source element."""

    model_config = ConfigDict(extra="forbid", strict=True)

    policy_id: Literal["p03-outline-structure-v1"]
    role: Literal["item"]
    record_id: str
    group_element_id: str
    public_anchor_element_id: str
    source_public_item_id: str
    source_public_path: OutlinePublicPath
    sequence_kind: Literal["unordered", "ordered", "legal"]
    marker_style: Literal["bullet", "decimal", "lower_alpha"]
    raw_marker: str
    marker_ownership: Literal["separate", "value_prefix"]
    marker_separator: str
    body_text: str
    level: Annotated[int, Field(strict=True, ge=0, lt=_MAX_OUTLINE_DEPTH)]
    ordinal: Annotated[int, Field(strict=True, ge=1)]
    parent_element_id: str | None
    marker_bbox_id: str
    marker_evidence_id: str
    relationship_ids: list[str] = Field(
        min_length=1,
        max_length=323,
    )

    @model_validator(mode="after")
    def validate_outline_item_fields(self) -> "OutlineItemSemanticDescriptor":
        path = self.source_public_path
        path_shape_is_valid = (
            len(path) in {4, 6}
            and path[0] == "pages"
            and path[2] == "items"
            and (len(path) == 4 or path[4] == "items")
            and all(
                type(path[index]) is int and int(path[index]) >= 0
                for index in ((1, 3) if len(path) == 4 else (1, 3, 5))
            )
        )
        if not path_shape_is_valid:
            raise ValueError("outline source public path differs")
        if self.sequence_kind == "legal" and len(path) != 4:
            raise ValueError("legal outline requires top-level source items")
        for label, value in (
            ("outline item record ID", self.record_id),
            ("outline group element ID", self.group_element_id),
            ("outline public anchor element ID", self.public_anchor_element_id),
            ("outline source public item ID", self.source_public_item_id),
            ("outline marker bbox ID", self.marker_bbox_id),
            ("outline marker evidence ID", self.marker_evidence_id),
        ):
            _require_bounded_outline_string(value, label=label)
        if self.parent_element_id is not None:
            _require_bounded_outline_string(
                self.parent_element_id,
                label="outline parent element ID",
            )
        _require_bounded_outline_string(
            self.raw_marker,
            label="outline raw marker",
            maximum_bytes=_MAX_OUTLINE_MARKER_BYTES,
        )
        _require_bounded_outline_string(
            self.body_text,
            label="outline body text",
            maximum_bytes=_MAX_OUTLINE_TEXT_BYTES,
        )
        _require_unique_outline_ids(
            self.relationship_ids,
            label="outline item relationship IDs",
        )
        if self.marker_ownership == "separate":
            if self.marker_separator != "":
                raise ValueError("separate outline markers require an empty separator")
        elif self.marker_separator != " ":
            raise ValueError("value-prefix outline markers require one ASCII space")
        if (self.sequence_kind, self.marker_style) not in {
            ("unordered", "bullet"),
            ("ordered", "decimal"),
            ("legal", "lower_alpha"),
        }:
            raise ValueError("outline item sequence kind/marker style differs")
        if self.marker_style == "bullet":
            marker_ordinal = 1 if self.raw_marker in _OUTLINE_BULLET_MARKERS else None
        elif self.marker_style == "decimal":
            match = _OUTLINE_DECIMAL_MARKER.fullmatch(self.raw_marker)
            marker_ordinal = int(match.group(1)) if match is not None else None
        else:
            match = _OUTLINE_ALPHA_MARKER.fullmatch(self.raw_marker)
            letter = (match.group(1) or match.group(2)) if match is not None else None
            marker_ordinal = ord(letter) - ord("a") + 1 if letter is not None else None
        if marker_ordinal is None or (
            self.marker_style != "bullet" and marker_ordinal != self.ordinal
        ):
            raise ValueError("outline item raw marker syntax differs")
        return self


def _validate_form_value(
    value: str | None,
    state: str,
    *,
    label: str,
) -> None:
    if state == "present":
        if value is None:
            raise ValueError(f"{label} must be present when state is present")
        _require_bounded_form_string(
            value,
            label=label,
            maximum_bytes=_MAX_FORM_TEXT_BYTES,
        )
    elif value is not None:
        raise ValueError(f"{label} must be null when state is {state}")


class ElementPresentationDirective(IRModel):
    """Typed inputs used by canonical presentation policy."""

    include_subordinate_ocr: bool | None = None
    accepted: bool | None = None


class ElementRecord(IRModel):
    id: str
    page_id: str
    type: str
    reading_order: int | None = Field(default=None, ge=0)
    value: Any | None = None
    markdown: str | None = None
    bbox_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    text_run_ids: list[str] = Field(
        default_factory=list,
        exclude_if=_exclude_empty_list,
    )
    form_semantics: FormSemanticDescriptor | None = Field(
        default=None,
        exclude_if=_exclude_none,
    )
    outline_group: OutlineGroupSemanticDescriptor | None = Field(
        default=None,
        exclude_if=_exclude_none,
    )
    outline_item: OutlineItemSemanticDescriptor | None = Field(
        default=None,
        exclude_if=_exclude_none,
    )
    running_region: RunningRegionDescriptor | None = Field(
        default=None,
        exclude_if=_exclude_none,
    )
    visual_model_evidence: VisualModelEvidenceBundle | None = Field(
        default=None,
        exclude_if=_exclude_none,
    )
    presentation_role: Literal[
        "primary",
        "subordinate",
        "alternate",
        "diagnostic",
    ] = "primary"
    presentation: ElementPresentationDirective = Field(
        default_factory=ElementPresentationDirective
    )
    properties: dict[str, Any] = Field(default_factory=dict)


class RelationshipRecord(IRModel):
    id: str
    type: RelationshipType
    source_id: str
    target_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegionRecord(IRModel):
    id: str
    page_id: str
    role: str
    bbox_id: str
    element_ids: list[str] = Field(default_factory=list)


class PageRecord(IRModel):
    id: str
    page_index: int = Field(ge=1)
    page_number: int | str
    page_label: str
    coordinate_system_id: str
    region_ids: list[str] = Field(default_factory=list)
    element_ids: list[str] = Field(default_factory=list)
    presentation_element_ids: list[str] = Field(default_factory=list)
    page_identity: PageIdentity | None = Field(
        default=None,
        exclude_if=_exclude_none,
    )


class IRConcern(IRModel):
    code: str
    message: str
    source_ref: str | None = None
    target_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


_ACYCLIC_RELATIONSHIPS = frozenset(
    {
        RelationshipType.CONTAINS,
        RelationshipType.CAPTION_OF,
        RelationshipType.SOURCE_NOTE_OF,
        RelationshipType.FOOTNOTE_OF,
        RelationshipType.LEGEND_OF,
        RelationshipType.AXIS_OF,
        RelationshipType.READING_BEFORE,
        RelationshipType.LABEL_OF,
        RelationshipType.VALUE_OF,
        RelationshipType.CONTROL_OF,
        RelationshipType.KEY_OF,
        RelationshipType.FORM_OVERLAY_OF,
        RelationshipType.OUTLINE_PARENT_OF,
        RelationshipType.OUTLINE_NEXT,
        RelationshipType.OUTLINE_CONTINUATION_OF,
    }
)


class DocumentIR(IRModel):
    ir_version: Literal["1.0"] = IR_VERSION
    id: str
    source_sha256: str
    coordinate_systems: list[CoordinateSystem]
    bboxes: list[IRBoundingBox]
    pages: list[PageRecord]
    regions: list[RegionRecord]
    elements: list[ElementRecord]
    evidence: list[EvidenceRecord]
    text_rules: list[TextRuleRecord] = Field(
        default_factory=list,
        max_length=_MAX_TEXT_RULES_PER_DOCUMENT,
        exclude_if=_exclude_empty_list,
    )
    text_runs: list[TextRunRecord] = Field(
        default_factory=list,
        max_length=_MAX_TEXT_RUNS_PER_DOCUMENT,
        exclude_if=_exclude_empty_list,
    )
    relationships: list[RelationshipRecord] = Field(default_factory=list)
    concerns: list[IRConcern] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "DocumentIR":
        _unique_ids(self.coordinate_systems, "coordinate system")
        _unique_ids(self.bboxes, "bounding box")
        _unique_ids(self.pages, "page")
        _unique_ids(self.regions, "region")
        _unique_ids(self.elements, "element")
        _unique_ids(self.evidence, "evidence")
        _unique_ids(self.text_rules, "text rule")
        _unique_ids(self.text_runs, "text run")
        _unique_ids(self.relationships, "relationship")
        _unique_graph_record_ids(self)

        coordinates = {record.id: record for record in self.coordinate_systems}
        bboxes = {record.id: record for record in self.bboxes}
        pages = {record.id: record for record in self.pages}
        regions = {record.id: record for record in self.regions}
        elements = {record.id: record for record in self.elements}
        evidence = {record.id: record for record in self.evidence}
        text_rules = {record.id: record for record in self.text_rules}
        text_runs = {record.id: record for record in self.text_runs}
        coordinate_ids = set(coordinates)
        bbox_ids = set(bboxes)
        page_ids = set(pages)
        region_ids = set(regions)
        element_ids = set(elements)
        evidence_ids = set(evidence)
        text_rule_ids = set(text_rules)
        text_run_ids = set(text_runs)

        page_indexes = [page.page_index for page in self.pages]
        if len(page_indexes) != len(set(page_indexes)):
            raise ValueError("document repeats a page index")

        for coordinate in self.coordinate_systems:
            _require_reference(
                coordinate.page_id,
                page_ids,
                f"coordinate system {coordinate.id} page",
            )
        for bbox in self.bboxes:
            _require_reference(
                bbox.coordinate_system_id,
                coordinate_ids,
                f"bbox {bbox.id} coordinate system",
            )
        page_element_membership: dict[str, str] = {}
        for page in self.pages:
            if len(page.region_ids) != len(set(page.region_ids)):
                raise ValueError(f"page {page.id} repeats a region")
            if len(page.element_ids) != len(set(page.element_ids)):
                raise ValueError(f"page {page.id} repeats an element")
            if len(page.presentation_element_ids) != len(
                set(page.presentation_element_ids)
            ):
                raise ValueError(f"page {page.id} repeats a presentation element")
            _require_reference(
                page.coordinate_system_id,
                coordinate_ids,
                f"page {page.id} coordinate system",
            )
            if coordinates[page.coordinate_system_id].page_id != page.id:
                raise ValueError(
                    f"page {page.id} uses another page's coordinate system"
                )
            for region_id in page.region_ids:
                _require_reference(region_id, region_ids, f"page {page.id} region")
                if regions[region_id].page_id != page.id:
                    raise ValueError(
                        f"page {page.id} lists a region owned by another page"
                    )
            for element_id in page.element_ids:
                _require_reference(element_id, element_ids, f"page {page.id} element")
                if elements[element_id].page_id != page.id:
                    raise ValueError(
                        f"page {page.id} lists an element owned by another page"
                    )
                prior_page = page_element_membership.setdefault(element_id, page.id)
                if prior_page != page.id:
                    raise ValueError(
                        f"element {element_id} is listed by multiple pages"
                    )
            for element_id in page.presentation_element_ids:
                if element_id not in page.element_ids:
                    raise ValueError(
                        f"page {page.id} presentation element is not a member"
                    )
                if elements[element_id].presentation_role != "primary":
                    raise ValueError(f"page {page.id} presents a non-primary element")
        if set(page_element_membership) != element_ids:
            missing = sorted(element_ids - set(page_element_membership))
            raise ValueError(f"elements missing from page membership: {missing}")

        for region in self.regions:
            if len(region.element_ids) != len(set(region.element_ids)):
                raise ValueError(f"region {region.id} repeats an element")
            _require_reference(region.page_id, page_ids, f"region {region.id} page")
            _require_reference(region.bbox_id, bbox_ids, f"region {region.id} bbox")
            if (
                coordinates[bboxes[region.bbox_id].coordinate_system_id].page_id
                != region.page_id
            ):
                raise ValueError(f"region {region.id} bbox belongs to another page")
            for element_id in region.element_ids:
                _require_reference(
                    element_id,
                    element_ids,
                    f"region {region.id} element",
                )
                if elements[element_id].page_id != region.page_id:
                    raise ValueError(f"region {region.id} lists a cross-page element")
        for element in self.elements:
            _require_reference(element.page_id, page_ids, f"element {element.id} page")
            for bbox_id in element.bbox_ids:
                _require_reference(bbox_id, bbox_ids, f"element {element.id} bbox")
                coordinate_id = bboxes[bbox_id].coordinate_system_id
                if coordinates[coordinate_id].page_id != element.page_id:
                    raise ValueError(
                        f"element {element.id} bbox belongs to another page"
                    )
            for evidence_id in element.evidence_ids:
                _require_reference(
                    evidence_id,
                    evidence_ids,
                    f"element {element.id} evidence",
                )
                if evidence[evidence_id].element_id != element.id:
                    raise ValueError(
                        f"element {element.id} points to another element's evidence"
                    )
            if len(element.text_run_ids) != len(set(element.text_run_ids)):
                raise ValueError(f"element {element.id} repeats a text run")
            for text_run_id in element.text_run_ids:
                _require_reference(
                    text_run_id,
                    text_run_ids,
                    f"element {element.id} text run",
                )
                if text_runs[text_run_id].element_id != element.id:
                    raise ValueError(
                        f"element {element.id} points to another element's text run"
                    )
        for record in self.evidence:
            _require_reference(
                record.element_id,
                element_ids,
                f"evidence {record.id} element",
            )
            if record.bbox_id is not None:
                _require_reference(
                    record.bbox_id,
                    bbox_ids,
                    f"evidence {record.id} bbox",
                )
                coordinate_id = bboxes[record.bbox_id].coordinate_system_id
                element_page_id = elements[record.element_id].page_id
                if coordinates[coordinate_id].page_id != element_page_id:
                    raise ValueError(
                        f"evidence {record.id} bbox belongs to another page"
                    )
            if record.id not in elements[record.element_id].evidence_ids:
                raise ValueError(f"evidence {record.id} is not listed by its element")
        _validate_text_semantics_graph(
            self,
            coordinates=coordinates,
            bboxes=bboxes,
            pages=pages,
            elements=elements,
            evidence=evidence,
            text_rules=text_rules,
            text_runs=text_runs,
            page_ids=page_ids,
            bbox_ids=bbox_ids,
            element_ids=element_ids,
            evidence_ids=evidence_ids,
            text_rule_ids=text_rule_ids,
        )
        region_membership = {
            element_id for region in self.regions for element_id in region.element_ids
        }
        if region_membership != element_ids:
            missing = sorted(element_ids - region_membership)
            extra = sorted(region_membership - element_ids)
            raise ValueError(
                f"region element membership mismatch: missing={missing}, extra={extra}"
            )
        for relationship in self.relationships:
            _require_reference(
                relationship.source_id,
                element_ids,
                f"relationship {relationship.id} source",
            )
            _require_reference(
                relationship.target_id,
                element_ids,
                f"relationship {relationship.id} target",
            )
            if relationship.source_id == relationship.target_id:
                raise ValueError(
                    f"relationship {relationship.id} cannot reference itself"
                )
            for evidence_id in relationship.evidence_ids:
                _require_reference(
                    evidence_id,
                    evidence_ids,
                    f"relationship {relationship.id} evidence",
                )
                if evidence[evidence_id].element_id not in {
                    relationship.source_id,
                    relationship.target_id,
                }:
                    raise ValueError(
                        f"relationship {relationship.id} uses unrelated evidence"
                    )

        page_identity_count = sum(
            page.page_identity is not None for page in self.pages
        )
        if page_identity_count not in {0, len(self.pages)}:
            raise ValueError("running-region page identity coverage is partial")
        for page in self.pages:
            identity = page.page_identity
            if identity is not None and (
                identity.page_id != page.id
                or identity.physical_page_index != page.page_index
            ):
                raise ValueError("running-region page identity binding differs")

        running_region_ids: set[str] = set()
        for element in self.elements:
            descriptor = element.running_region
            if descriptor is None:
                continue
            if descriptor.id in running_region_ids:
                raise ValueError("running-region descriptor ID repeats")
            running_region_ids.add(descriptor.id)
            page = pages[element.page_id]
            if (
                descriptor.page_id != element.page_id
                or descriptor.physical_page_index != page.page_index
                or descriptor.source_element_id != element.id
                or descriptor.bbox_id not in element.bbox_ids
                or not set(descriptor.evidence_ids).issubset(element.evidence_ids)
            ):
                raise ValueError("running-region descriptor graph binding differs")
            expected_type = (
                "header"
                if descriptor.role in {"header", "navigation_top"}
                else "footer"
            )
            if element.type != expected_type:
                raise ValueError("running-region element type differs")
            # ``legacy_item`` is deliberately the exact pre-US08 public item.
            # Public running-region markers live on the projected API surface,
            # while the typed descriptor is carried directly by ElementRecord.
            # Keeping the predecessor snapshot untouched makes strip/replay an
            # exact inverse instead of trusting feature-authored rollback data.

        _validate_form_semantics_graph(
            self,
            coordinates=coordinates,
            bboxes=bboxes,
            pages=pages,
            elements=elements,
            evidence=evidence,
        )
        _validate_outline_structure_graph(
            self,
            coordinates=coordinates,
            bboxes=bboxes,
            pages=pages,
            elements=elements,
            evidence=evidence,
        )
        _reject_forbidden_cycles(self.relationships)
        self._reject_false_native_generated_evidence()
        return self

    def _reject_false_native_generated_evidence(self) -> None:
        by_element: dict[str, list[EvidenceRecord]] = {}
        for record in self.evidence:
            by_element.setdefault(record.element_id, []).append(record)
        for element in self.elements:
            if not bool(element.properties.get("generated")):
                continue
            if any(
                record.method is EvidenceMethod.NATIVE
                for record in by_element.get(element.id, [])
            ):
                raise ValueError(
                    f"generated element {element.id} cannot be labeled native"
                )


def _unique_ids(records: Iterable[Any], kind: str) -> set[str]:
    identifiers: set[str] = set()
    for record in records:
        identifier = str(record.id)
        if identifier in identifiers:
            raise ValueError(f"duplicate {kind} id: {identifier}")
        identifiers.add(identifier)
    return identifiers


def _require_reference(value: str, identifiers: set[str], label: str) -> None:
    if value not in identifiers:
        raise ValueError(f"dangling {label}: {value}")


def _unique_graph_record_ids(ir: DocumentIR) -> None:
    identifiers: dict[str, str] = {ir.id: "document"}
    collections: tuple[tuple[str, Iterable[Any]], ...] = (
        ("coordinate system", ir.coordinate_systems),
        ("bounding box", ir.bboxes),
        ("page", ir.pages),
        ("region", ir.regions),
        ("element", ir.elements),
        ("evidence", ir.evidence),
        ("text rule", ir.text_rules),
        ("text run", ir.text_runs),
        ("relationship", ir.relationships),
    )
    for kind, records in collections:
        for record in records:
            prior_kind = identifiers.get(record.id)
            if prior_kind is not None:
                raise ValueError(
                    f"duplicate graph record id {record.id}: {prior_kind} and {kind}"
                )
            identifiers[record.id] = kind


def _text_target_path_sort_key(
    target_path: tuple[str] | tuple[str, int, str],
) -> tuple[str, int, str]:
    if target_path == ("value",):
        return ("value", -1, "")
    collection, index, terminal = target_path
    return (collection, index, terminal)


def _require_page_space_bbox(
    *,
    bbox_id: str,
    page_id: str,
    label: str,
    coordinates: Mapping[str, CoordinateSystem],
    bboxes: Mapping[str, IRBoundingBox],
    bbox_ids: set[str],
) -> None:
    _require_reference(bbox_id, bbox_ids, f"{label} bbox")
    bbox = bboxes[bbox_id]
    coordinate = coordinates[bbox.coordinate_system_id]
    if coordinate.page_id != page_id:
        raise ValueError(f"{label} bbox belongs to another page")
    if (
        coordinate.unit != "pt"
        or coordinate.origin != "top_left"
        or coordinate.transform_to_page != IDENTITY_TRANSFORM
    ):
        raise ValueError(f"{label} bbox must use top-left page-space points")
    if bbox.width <= 0 or bbox.height <= 0:
        raise ValueError(f"{label} bbox must have positive dimensions")


def _semantic_page_extent(
    *,
    page: PageRecord,
    coordinates: Mapping[str, CoordinateSystem],
    bboxes: Mapping[str, IRBoundingBox],
) -> IRBoundingBox:
    candidates = [
        bbox
        for bbox in bboxes.values()
        if bbox.role == "page"
        and bbox.coordinate_system_id == page.coordinate_system_id
        and coordinates[bbox.coordinate_system_id].page_id == page.id
    ]
    if len(candidates) != 1:
        raise ValueError(f"text semantics page {page.id} has no unique page extent")
    [extent] = candidates
    coordinate = coordinates[extent.coordinate_system_id]
    if (
        coordinate.unit != "pt"
        or coordinate.origin != "top_left"
        or coordinate.transform_to_page != IDENTITY_TRANSFORM
        or not math.isclose(extent.x, 0.0, rel_tol=0.0, abs_tol=1e-9)
        or not math.isclose(extent.y, 0.0, rel_tol=0.0, abs_tol=1e-9)
        or extent.width <= 0
        or extent.height <= 0
    ):
        raise ValueError(f"text semantics page {page.id} has an invalid page extent")
    return extent


def _require_bbox_inside_page(
    *,
    bbox: IRBoundingBox,
    extent: IRBoundingBox,
    label: str,
) -> None:
    if (
        bbox.x < extent.x
        or bbox.y < extent.y
        or bbox.x + bbox.width > extent.x + extent.width + 1e-6
        or bbox.y + bbox.height > extent.y + extent.height + 1e-6
    ):
        raise ValueError(f"{label} bbox lies outside its page extent")


_FORM_RELATIONSHIP_TYPES = frozenset(
    {
        RelationshipType.LABEL_OF,
        RelationshipType.VALUE_OF,
        RelationshipType.CONTROL_OF,
        RelationshipType.KEY_OF,
        RelationshipType.FORM_OVERLAY_OF,
    }
)
_FORM_INCIDENT_BOUNDS: Mapping[str, tuple[int, int]] = {
    "group": (1, 2_816),
    "field": (4, 323),
    "label": (2, 257),
    "value_region": (2, 2),
    "control": (2, 3),
    "key_value_pair": (5, 5),
}


def _validate_form_semantics_graph(
    ir: DocumentIR,
    *,
    coordinates: Mapping[str, CoordinateSystem],
    bboxes: Mapping[str, IRBoundingBox],
    pages: Mapping[str, PageRecord],
    elements: Mapping[str, ElementRecord],
    evidence: Mapping[str, EvidenceRecord],
) -> None:
    semantic_elements = {
        element.id: element
        for element in ir.elements
        if element.form_semantics is not None
    }
    has_form_relationship = any(
        relationship.type in _FORM_RELATIONSHIP_TYPES
        for relationship in ir.relationships
    )
    if not semantic_elements and not has_form_relationship:
        return
    if not semantic_elements:
        raise ValueError("form relationships require form semantic elements")

    descriptors = {
        element_id: element.form_semantics
        for element_id, element in semantic_elements.items()
    }
    groups = {
        element_id: descriptor
        for element_id, descriptor in descriptors.items()
        if isinstance(descriptor, FormGroupSemanticDescriptor)
    }
    if not groups:
        raise ValueError("form semantic elements require a group")

    record_ids: set[str] = set()
    presented_ids = {
        element_id for page in ir.pages for element_id in page.presentation_element_ids
    }
    semantic_counts_by_page: dict[str, int] = {}
    page_extents: dict[str, IRBoundingBox] = {}
    for element_id, element in semantic_elements.items():
        descriptor = descriptors[element_id]
        assert descriptor is not None
        _require_bounded_form_string(element_id, label="form semantic element ID")
        if descriptor.record_id in record_ids:
            raise ValueError(
                f"duplicate form semantic record ID: {descriptor.record_id}"
            )
        record_ids.add(descriptor.record_id)
        if element_id in presented_ids:
            raise ValueError(f"form semantic element {element_id} cannot be presented")
        if len(element.bbox_ids) != 1:
            raise ValueError(
                f"form semantic element {element_id} requires exactly one bbox"
            )
        if (
            not 1
            <= len(element.evidence_ids)
            <= (_MAX_FORM_SOURCE_IDENTITIES_PER_RECORD)
        ):
            raise ValueError(
                f"form semantic element {element_id} requires 1-64 evidence IDs"
            )
        _require_unique_form_ids(
            element.bbox_ids,
            label=f"form semantic element {element_id} bbox IDs",
        )
        _require_unique_form_ids(
            element.evidence_ids,
            label=f"form semantic element {element_id} evidence IDs",
        )
        page = pages[element.page_id]
        extent = page_extents.get(page.id)
        if extent is None:
            extent = _semantic_page_extent(
                page=page,
                coordinates=coordinates,
                bboxes=bboxes,
            )
            page_extents[page.id] = extent
        [bbox_id] = element.bbox_ids
        _require_page_space_bbox(
            bbox_id=bbox_id,
            page_id=page.id,
            label=f"form semantic element {element_id}",
            coordinates=coordinates,
            bboxes=bboxes,
            bbox_ids=set(bboxes),
        )
        _require_bbox_inside_page(
            bbox=bboxes[bbox_id],
            extent=extent,
            label=f"form semantic element {element_id}",
        )
        semantic_counts_by_page[page.id] = semantic_counts_by_page.get(page.id, 0) + 1
        if descriptor.role == "label":
            assert isinstance(descriptor, FormLabelSemanticDescriptor)
            if element.value != descriptor.text:
                raise ValueError(
                    f"form label element {element_id} value must equal its text"
                )
        elif descriptor.role in {"field", "value_region", "key_value_pair"}:
            if element.value != descriptor.value:
                raise ValueError(
                    f"form semantic element {element_id} value disagrees with "
                    "its descriptor"
                )

    if len(semantic_elements) > MAX_FORM_SEMANTIC_RECORDS_PER_DOCUMENT:
        raise ValueError("document exceeds the form semantic record limit")
    if any(
        count > MAX_FORM_SEMANTIC_RECORDS_PER_PAGE
        for count in semantic_counts_by_page.values()
    ):
        raise ValueError("page exceeds the form semantic record limit")

    replacement_contributors: set[str] = set()
    anchor_element_ids: set[str] = set()
    for group_element_id, descriptor in groups.items():
        group_element = semantic_elements[group_element_id]
        group_page = pages[group_element.page_id]
        if descriptor.group_element_id != group_element_id:
            raise ValueError("form group descriptor must identify its own element")
        if group_element_id in descriptor.contributor_element_ids or (
            group_element_id == descriptor.public_anchor_element_id
        ):
            raise ValueError(
                "form group element must be dedicated and non-contributing"
            )
        if descriptor.public_anchor_element_id in anchor_element_ids:
            raise ValueError("form groups cannot share a public anchor element")
        anchor_element_ids.add(descriptor.public_anchor_element_id)
        for public_item_id, contributor_element_id in zip(
            descriptor.contributor_public_item_ids,
            descriptor.contributor_element_ids,
            strict=True,
        ):
            contributor = elements.get(contributor_element_id)
            if contributor is None:
                raise ValueError(
                    f"form group {group_element_id} has a dangling contributor"
                )
            if contributor.form_semantics is not None:
                raise ValueError("form contributors must be predecessor elements")
            if contributor.page_id != group_element.page_id:
                raise ValueError("form contributors must be on the group page")
            if contributor_element_id not in group_page.presentation_element_ids:
                raise ValueError("form contributors must be public page elements")
            legacy_item = contributor.properties.get("legacy_item")
            if not isinstance(legacy_item, Mapping) or (
                legacy_item.get("id") != public_item_id
            ):
                raise ValueError(
                    "form contributor public/internal IDs must map pairwise"
                )
        anchor = elements.get(descriptor.public_anchor_element_id)
        if anchor is None or anchor.form_semantics is not None:
            raise ValueError("form group has no predecessor public anchor")
        if anchor.page_id != group_element.page_id:
            raise ValueError("form group anchor must be on the group page")
        if descriptor.public_anchor_element_id not in (
            group_page.presentation_element_ids
        ):
            raise ValueError("form group anchor must be a public page element")
        anchor_legacy_item = anchor.properties.get("legacy_item")
        if not isinstance(anchor_legacy_item, Mapping) or (
            anchor_legacy_item.get("id") != descriptor.anchor_public_item_id
        ):
            raise ValueError("form group public anchor IDs disagree")
        if descriptor.canonical_mode == "replace":
            overlap = replacement_contributors.intersection(
                descriptor.contributor_element_ids
            )
            if overlap:
                raise ValueError("canonical form replacements share contributors")
            replacement_contributors.update(descriptor.contributor_element_ids)

    for element_id, descriptor in descriptors.items():
        assert descriptor is not None
        group = groups.get(descriptor.group_element_id)
        if group is None:
            raise ValueError(
                f"form semantic element {element_id} has no typed group owner"
            )
        group_element = semantic_elements[descriptor.group_element_id]
        if semantic_elements[element_id].page_id != group_element.page_id:
            raise ValueError("form semantic group ownership cannot cross pages")
        if descriptor.public_anchor_element_id != group.public_anchor_element_id:
            raise ValueError("form semantic element disagrees with its group anchor")

    incident_relationship_ids: dict[str, list[str]] = {
        element_id: [] for element_id in semantic_elements
    }
    incoming: dict[tuple[RelationshipType, str], list[str]] = {}
    outgoing: dict[tuple[RelationshipType, str], list[str]] = {}
    form_relationships: list[RelationshipRecord] = []
    relationship_tuples: set[tuple[RelationshipType, str, str]] = set()
    relationships_by_page: dict[str, int] = {}

    def role_of(element_id: str) -> str | None:
        descriptor = descriptors.get(element_id)
        return descriptor.role if descriptor is not None else None

    for relationship in ir.relationships:
        is_form_relationship = (
            relationship.type in _FORM_RELATIONSHIP_TYPES
            or relationship.source_id in semantic_elements
            or relationship.target_id in semantic_elements
        )
        if not is_form_relationship:
            continue
        if relationship.type not in (
            _FORM_RELATIONSHIP_TYPES | {RelationshipType.CONTAINS}
        ):
            raise ValueError("form semantic elements use an unsupported relationship")
        if relationship.metadata != {"canonical_inert": True}:
            raise ValueError(
                "form semantic relationships require exact canonical-inert metadata"
            )
        _require_bounded_form_string(
            relationship.id,
            label="form semantic relationship ID",
        )
        _require_bounded_form_string(
            relationship.source_id,
            label="form semantic relationship source ID",
        )
        _require_bounded_form_string(
            relationship.target_id,
            label="form semantic relationship target ID",
        )
        if len(relationship.evidence_ids) > (_MAX_FORM_SOURCE_IDENTITIES_PER_RECORD):
            raise ValueError("form semantic relationship has too much evidence")
        _require_unique_form_ids(
            relationship.evidence_ids,
            label=f"form relationship {relationship.id} evidence IDs",
        )
        source = elements[relationship.source_id]
        target = elements[relationship.target_id]
        if source.page_id != target.page_id:
            raise ValueError("form semantic relationships must be same-page")
        relationship_tuple = (
            relationship.type,
            relationship.source_id,
            relationship.target_id,
        )
        if relationship_tuple in relationship_tuples:
            raise ValueError("form semantic graph repeats a typed endpoint pair")
        relationship_tuples.add(relationship_tuple)
        source_role = role_of(relationship.source_id)
        target_role = role_of(relationship.target_id)
        if source_role is not None and target_role is not None:
            source_descriptor = descriptors[relationship.source_id]
            target_descriptor = descriptors[relationship.target_id]
            assert source_descriptor is not None
            assert target_descriptor is not None
            if source_descriptor.group_element_id != target_descriptor.group_element_id:
                raise ValueError("form semantic relationships cannot cross groups")
        if relationship.type is RelationshipType.CONTAINS:
            compatible = (
                (
                    source_role == "group"
                    and target_role in {"field", "label", "control", "key_value_pair"}
                )
                or (
                    source_role in {"field", "key_value_pair"}
                    and target_role == "value_region"
                )
                or (source_role == "key_value_pair" and target_role == "label")
            )
        elif relationship.type is RelationshipType.LABEL_OF:
            compatible = source_role == "label" and target_role in {
                "field",
                "control",
                "group",
            }
        elif relationship.type is RelationshipType.VALUE_OF:
            compatible = source_role == "value_region" and target_role in {
                "field",
                "key_value_pair",
            }
        elif relationship.type is RelationshipType.CONTROL_OF:
            compatible = source_role == "control" and target_role in {
                "field",
                "group",
            }
        elif relationship.type is RelationshipType.KEY_OF:
            compatible = source_role == "label" and target_role == "key_value_pair"
        else:
            compatible = source_role == "group" and target_role is None
        if not compatible:
            raise ValueError("form semantic relationship has incompatible roles")
        form_relationships.append(relationship)
        outgoing.setdefault((relationship.type, relationship.source_id), []).append(
            relationship.target_id
        )
        incoming.setdefault((relationship.type, relationship.target_id), []).append(
            relationship.source_id
        )
        for endpoint_id in (relationship.source_id, relationship.target_id):
            if endpoint_id in incident_relationship_ids:
                incident_relationship_ids[endpoint_id].append(relationship.id)
        relationships_by_page[source.page_id] = (
            relationships_by_page.get(source.page_id, 0) + 1
        )

    if len(form_relationships) > MAX_FORM_RELATIONSHIPS_PER_DOCUMENT:
        raise ValueError("document exceeds the form relationship limit")
    if any(
        count > MAX_FORM_RELATIONSHIPS_PER_PAGE
        for count in relationships_by_page.values()
    ):
        raise ValueError("page exceeds the form relationship limit")

    def exact_ids(actual: Sequence[str], expected: Sequence[str], label: str) -> None:
        if len(actual) != len(expected) or set(actual) != set(expected):
            raise ValueError(f"{label} disagrees with relationship endpoints")

    for element_id, descriptor in descriptors.items():
        assert descriptor is not None
        bounds = _FORM_INCIDENT_BOUNDS[descriptor.role]
        incident_count = len(incident_relationship_ids[element_id])
        if not bounds[0] <= incident_count <= bounds[1]:
            raise ValueError(
                f"form {descriptor.role} element {element_id} has an invalid "
                "relationship cardinality"
            )
        structural_parents = incoming.get((RelationshipType.CONTAINS, element_id), [])
        if descriptor.role == "group":
            if structural_parents:
                raise ValueError("form groups cannot have a structural parent")
            assert isinstance(descriptor, FormGroupSemanticDescriptor)
            overlay_relationships = [
                relationship
                for relationship in form_relationships
                if relationship.type is RelationshipType.FORM_OVERLAY_OF
                and relationship.source_id == element_id
            ]
            if any(
                relationship.target_id != descriptor.public_anchor_element_id
                for relationship in overlay_relationships
            ):
                raise ValueError("form overlay must target the group public anchor")
            exact_ids(
                descriptor.anchor_relationship_ids,
                [relationship.id for relationship in overlay_relationships],
                "form group anchor backlinks",
            )
        elif len(structural_parents) != 1:
            raise ValueError(
                f"form semantic element {element_id} requires one structural parent"
            )

        if isinstance(descriptor, FormFieldSemanticDescriptor):
            exact_ids(
                descriptor.label_element_ids,
                incoming.get((RelationshipType.LABEL_OF, element_id), []),
                "form field labels",
            )
            exact_ids(
                [descriptor.value_region_element_id],
                incoming.get((RelationshipType.VALUE_OF, element_id), []),
                "form field value region",
            )
            exact_ids(
                descriptor.control_element_ids,
                incoming.get((RelationshipType.CONTROL_OF, element_id), []),
                "form field controls",
            )
            if structural_parents != [descriptor.group_element_id]:
                raise ValueError("form field structural owner disagrees")
        elif isinstance(descriptor, FormLabelSemanticDescriptor):
            exact_ids(
                descriptor.label_of_element_ids,
                outgoing.get((RelationshipType.LABEL_OF, element_id), []),
                "form label targets",
            )
            exact_ids(
                descriptor.key_of_element_ids,
                outgoing.get((RelationshipType.KEY_OF, element_id), []),
                "form key-label targets",
            )
            target_ids = (
                descriptor.key_of_element_ids
                if descriptor.label_role == "key"
                else descriptor.label_of_element_ids
            )
            expected_target_role = {
                "field": "field",
                "group": "group",
                "control": "control",
                "key": "key_value_pair",
            }[descriptor.label_role]
            if any(
                role_of(target_id) != expected_target_role for target_id in target_ids
            ):
                raise ValueError("form label role disagrees with its target role")
            if descriptor.label_role == "key":
                owner_id = descriptor.key_of_element_ids[0]
                if structural_parents != [owner_id]:
                    raise ValueError("form key label must be owned by its pair")
            elif structural_parents != [descriptor.group_element_id]:
                raise ValueError("form non-key labels must be group-owned")
        elif isinstance(descriptor, FormValueRegionSemanticDescriptor):
            exact_ids(
                [descriptor.owner_element_id],
                outgoing.get((RelationshipType.VALUE_OF, element_id), []),
                "form value-region owner",
            )
            if structural_parents != [descriptor.owner_element_id]:
                raise ValueError("form value-region structural owner disagrees")
            owner = descriptors.get(descriptor.owner_element_id)
            if isinstance(owner, FormFieldSemanticDescriptor):
                if not descriptor.excluded_label_element_ids:
                    raise ValueError(
                        "field-owned value regions require an excluded label"
                    )
                for label_element_id in descriptor.excluded_label_element_ids:
                    label_descriptor = descriptors.get(label_element_id)
                    if not isinstance(
                        label_descriptor, FormLabelSemanticDescriptor
                    ) or (
                        descriptor.owner_element_id
                        not in label_descriptor.label_of_element_ids
                    ):
                        raise ValueError(
                            "value-region excluded labels must label their owner"
                        )
                if (
                    descriptor.value != owner.value
                    or descriptor.value_state != owner.value_state
                ):
                    raise ValueError("field and value-region values must agree")
            elif isinstance(owner, FormKeyValuePairSemanticDescriptor):
                if descriptor.excluded_label_element_ids:
                    raise ValueError("present pair value regions cannot exclude labels")
                if (
                    descriptor.value != owner.value
                    or descriptor.value_state != owner.value_state
                ):
                    raise ValueError("pair and value-region values must agree")
            else:
                raise ValueError("form value region has an invalid owner role")
        elif isinstance(descriptor, FormControlSemanticDescriptor):
            expected_owner = (
                descriptor.owner_field_element_id or descriptor.group_element_id
            )
            exact_ids(
                [expected_owner],
                outgoing.get((RelationshipType.CONTROL_OF, element_id), []),
                "form control owner",
            )
            expected_labels = (
                []
                if descriptor.label_element_id is None
                else [descriptor.label_element_id]
            )
            exact_ids(
                expected_labels,
                incoming.get((RelationshipType.LABEL_OF, element_id), []),
                "form control label",
            )
            if structural_parents != [descriptor.group_element_id]:
                raise ValueError("form controls must be group-owned")
            if descriptor.owner_field_element_id is not None:
                owner = descriptors.get(descriptor.owner_field_element_id)
                if not isinstance(owner, FormFieldSemanticDescriptor) or (
                    descriptor.group_element_id != owner.group_element_id
                ):
                    raise ValueError("form control has an invalid field owner")
        elif isinstance(descriptor, FormKeyValuePairSemanticDescriptor):
            if structural_parents != [descriptor.group_element_id]:
                raise ValueError("form key-value pairs must be group-owned")
            exact_ids(
                [descriptor.key_label_element_id, descriptor.value_region_element_id],
                outgoing.get((RelationshipType.CONTAINS, element_id), []),
                "form key-value pair children",
            )
            exact_ids(
                [descriptor.key_label_element_id],
                incoming.get((RelationshipType.KEY_OF, element_id), []),
                "form key-value pair key",
            )
            exact_ids(
                [descriptor.value_region_element_id],
                incoming.get((RelationshipType.VALUE_OF, element_id), []),
                "form key-value pair value",
            )
            key_label = descriptors.get(descriptor.key_label_element_id)
            value_region = descriptors.get(descriptor.value_region_element_id)
            if not isinstance(key_label, FormLabelSemanticDescriptor) or (
                key_label.label_role != "key" or key_label.text != descriptor.key
            ):
                raise ValueError("form pair key label disagrees with its key")
            if not isinstance(value_region, FormValueRegionSemanticDescriptor):
                raise ValueError("form pair has no typed value region")
            group = groups[descriptor.group_element_id]
            for item_id, source_element_id in (
                (descriptor.key_source_item_id, descriptor.key_source_element_id),
                (descriptor.value_source_item_id, descriptor.value_source_element_id),
            ):
                source_element = elements.get(source_element_id)
                if source_element is None or source_element.form_semantics is not None:
                    raise ValueError("form pair source must be a predecessor element")
                if source_element_id not in group.contributor_element_ids:
                    raise ValueError("form pair source is outside group custody")
                legacy_item = source_element.properties.get("legacy_item")
                if not isinstance(legacy_item, Mapping) or (
                    legacy_item.get("id") != item_id
                ):
                    raise ValueError("form pair source public/internal IDs disagree")

    members_by_group: dict[str, dict[str, int]] = {
        group_element_id: {
            "field": 0,
            "label": 0,
            "value_region": 0,
            "control": 0,
            "key_value_pair": 0,
        }
        for group_element_id in groups
    }
    class_counts_by_page: dict[tuple[str, str], int] = {}
    class_counts_document = {
        "field": 0,
        "control": 0,
        "key_value_pair": 0,
    }
    group_counts_by_page: dict[str, int] = {}
    for element_id, descriptor in descriptors.items():
        assert descriptor is not None
        page_id = semantic_elements[element_id].page_id
        if descriptor.role == "group":
            group_counts_by_page[page_id] = group_counts_by_page.get(page_id, 0) + 1
            continue
        members_by_group[descriptor.group_element_id][descriptor.role] += 1
        if descriptor.role in class_counts_document:
            class_counts_document[descriptor.role] += 1
            key = (page_id, descriptor.role)
            class_counts_by_page[key] = class_counts_by_page.get(key, 0) + 1

    if len(groups) > MAX_FORM_GROUPS_PER_DOCUMENT or any(
        count > MAX_FORM_GROUPS_PER_PAGE for count in group_counts_by_page.values()
    ):
        raise ValueError("form semantic graph exceeds the group limit")
    if any(
        count > MAX_FORM_CLASS_RECORDS_PER_PAGE
        for count in class_counts_by_page.values()
    ) or any(
        count > MAX_FORM_CLASS_RECORDS_PER_DOCUMENT
        for count in class_counts_document.values()
    ):
        raise ValueError("form semantic graph exceeds a page/document class limit")
    for group_element_id, counts in members_by_group.items():
        if not (counts["field"] or counts["control"] or counts["key_value_pair"]):
            raise ValueError("form groups require a field, control, or pair")
        if counts["key_value_pair"] and (counts["field"] or counts["control"]):
            raise ValueError("form groups cannot mix pairs with fields or controls")
        role_limits = {
            "field": MAX_FORM_FIELDS_PER_GROUP,
            "label": MAX_FORM_LABELS_PER_GROUP,
            "value_region": MAX_FORM_VALUE_REGIONS_PER_GROUP,
            "control": MAX_FORM_CONTROLS_PER_GROUP,
            "key_value_pair": MAX_FORM_KEY_VALUE_PAIRS_PER_GROUP,
        }
        if any(counts[role] > limit for role, limit in role_limits.items()):
            raise ValueError(
                f"form group {group_element_id} exceeds a role cardinality"
            )
        if counts["value_region"] != (counts["field"] + counts["key_value_pair"]):
            raise ValueError("form group value-region cardinality is incomplete")


_OUTLINE_RELATIONSHIP_TYPES = frozenset(
    {
        RelationshipType.OUTLINE_PARENT_OF,
        RelationshipType.OUTLINE_NEXT,
        RelationshipType.OUTLINE_CONTINUATION_OF,
    }
)


def _outline_source_value(
    element: ElementRecord,
    descriptor: OutlineItemSemanticDescriptor,
    *,
    elements: Mapping[str, ElementRecord],
) -> Any:
    path = descriptor.source_public_path
    if len(path) == 4:
        legacy = element.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            raise ValueError("outline source path has no top-level legacy item")
        if legacy.get("id") != descriptor.source_public_item_id:
            raise ValueError("outline source public/internal IDs disagree")
        return legacy.get("value")
    anchor = elements.get(descriptor.public_anchor_element_id)
    legacy_anchor = anchor.properties.get("legacy_item") if anchor is not None else None
    if not isinstance(legacy_anchor, Mapping) or (
        legacy_anchor.get("id") != descriptor.source_public_item_id
    ):
        raise ValueError("outline nested source anchor differs")
    raw_items = legacy_anchor.get("items")
    nested_index = path[-1]
    if (
        not isinstance(raw_items, Sequence)
        or isinstance(raw_items, (str, bytes, bytearray))
        or nested_index >= len(raw_items)
        or not isinstance(raw_items[nested_index], Mapping)
    ):
        raise ValueError("outline nested source path does not resolve")
    legacy_child = element.properties.get("legacy_child")
    if not isinstance(legacy_child, Mapping) or dict(legacy_child) != dict(
        raw_items[nested_index]
    ):
        raise ValueError("outline nested source custody differs")
    return raw_items[nested_index].get("value")


def _validate_outline_structure_graph(
    ir: DocumentIR,
    *,
    coordinates: Mapping[str, CoordinateSystem],
    bboxes: Mapping[str, IRBoundingBox],
    pages: Mapping[str, PageRecord],
    elements: Mapping[str, ElementRecord],
    evidence: Mapping[str, EvidenceRecord],
) -> None:
    groups = {
        element.id: element
        for element in ir.elements
        if element.outline_group is not None
    }
    items = {
        element.id: element
        for element in ir.elements
        if element.outline_item is not None
    }
    has_outline_relationship = any(
        relationship.type in _OUTLINE_RELATIONSHIP_TYPES
        or relationship.metadata.get("outline_policy") == "p03-outline-structure-v1"
        for relationship in ir.relationships
    )
    if not groups and not items and not has_outline_relationship:
        return
    if not groups or not items:
        raise ValueError("outline relationships require complete semantic elements")
    if any(
        element.outline_group is not None and element.outline_item is not None
        for element in ir.elements
    ):
        raise ValueError("an element cannot be both an outline group and item")

    group_counts: dict[str, int] = {}
    item_counts: dict[str, int] = {}
    for element in groups.values():
        group_counts[element.page_id] = group_counts.get(element.page_id, 0) + 1
    for element in items.values():
        item_counts[element.page_id] = item_counts.get(element.page_id, 0) + 1
    if len(groups) > MAX_OUTLINE_GROUPS_PER_DOCUMENT or any(
        count > MAX_OUTLINE_GROUPS_PER_PAGE for count in group_counts.values()
    ):
        raise ValueError("outline graph exceeds the group limit")
    if len(items) > MAX_OUTLINE_NODES_PER_DOCUMENT or any(
        count > MAX_OUTLINE_NODES_PER_PAGE for count in item_counts.values()
    ):
        raise ValueError("outline graph exceeds the node limit")

    form_owned_element_ids = {
        element.id for element in ir.elements if element.form_semantics is not None
    }
    for element in ir.elements:
        descriptor = element.form_semantics
        if isinstance(descriptor, FormGroupSemanticDescriptor):
            form_owned_element_ids.update(descriptor.contributor_element_ids)

    group_by_record_id: dict[
        str, tuple[ElementRecord, OutlineGroupSemanticDescriptor]
    ] = {}
    for group_element in groups.values():
        descriptor = group_element.outline_group
        assert descriptor is not None
        if descriptor.record_id in group_by_record_id:
            raise ValueError("outline graph repeats a group record ID")
        group_by_record_id[descriptor.record_id] = (group_element, descriptor)
        if (
            group_element.type != "outline_group"
            or group_element.reading_order is not None
            or group_element.value is not None
            or group_element.markdown is not None
            or group_element.presentation_role != "subordinate"
            or group_element.properties
            != {
                "outline_policy": "p03-outline-structure-v1",
                "public_anchor_element_id": descriptor.anchor_element_id,
            }
            or len(group_element.bbox_ids) != 1
            or len(group_element.evidence_ids) != 1
        ):
            raise ValueError("outline group element contract differs")
        page = pages[group_element.page_id]
        if group_element.id in page.presentation_element_ids:
            raise ValueError("outline group elements cannot be presented directly")
        anchor = elements.get(descriptor.anchor_element_id)
        if anchor is None or anchor.page_id != group_element.page_id:
            raise ValueError("outline group anchor is unavailable")
        anchor_legacy = anchor.properties.get("legacy_item")
        if not isinstance(anchor_legacy, Mapping) or (
            anchor_legacy.get("id") != descriptor.anchor_public_item_id
        ):
            raise ValueError("outline group anchor public/internal IDs disagree")
        if set(descriptor.canonical_contributor_element_ids) & form_owned_element_ids:
            raise ValueError("outline canonical custody overlaps form ownership")
        if any(
            element_id not in elements
            or elements[element_id].page_id != group_element.page_id
            for element_id in descriptor.canonical_contributor_element_ids
        ):
            raise ValueError("outline canonical contributor custody differs")

        [group_bbox_id] = group_element.bbox_ids
        group_bbox = bboxes[group_bbox_id]
        if group_bbox.role != "region":
            raise ValueError("outline group bbox must have region role")
        _require_page_space_bbox(
            bbox_id=group_bbox_id,
            page_id=group_element.page_id,
            label="outline group",
            coordinates=coordinates,
            bboxes=bboxes,
            bbox_ids=set(bboxes),
        )
        [group_evidence_id] = group_element.evidence_ids
        group_evidence = evidence[group_evidence_id]
        if (
            group_evidence.method is not EvidenceMethod.DERIVED
            or group_evidence.bbox_id != group_bbox_id
            or group_evidence.value
            != {
                "policy_id": "p03-outline-structure-v1",
                "group_id": descriptor.record_id,
            }
            or group_evidence.confidence.scope != "evidence"
            or group_evidence.confidence.score is not None
            or group_evidence.confidence.unavailable_reason != "not_calibrated"
            or group_evidence.metadata
            != {
                "derivation": "validated_outline_group_union",
                "policy_id": "p03-outline-structure-v1",
                "group_id": descriptor.record_id,
                "source_element_id": descriptor.anchor_element_id,
            }
        ):
            raise ValueError("outline group evidence contract differs")

    item_by_record_id: dict[
        str, tuple[ElementRecord, OutlineItemSemanticDescriptor]
    ] = {}
    members_by_group: dict[str, list[str]] = {value: [] for value in groups}
    for item_element in items.values():
        descriptor = item_element.outline_item
        assert descriptor is not None
        if descriptor.record_id in item_by_record_id:
            raise ValueError("outline graph repeats an item record ID")
        item_by_record_id[descriptor.record_id] = (item_element, descriptor)
        group_pair = groups.get(descriptor.group_element_id)
        if group_pair is None or group_pair.page_id != item_element.page_id:
            raise ValueError("outline item group is unavailable")
        group_descriptor = group_pair.outline_group
        assert group_descriptor is not None
        if (
            descriptor.public_anchor_element_id != group_descriptor.anchor_element_id
            or descriptor.sequence_kind != group_descriptor.sequence_kind
            or descriptor.marker_style != group_descriptor.marker_style
        ):
            raise ValueError("outline item disagrees with its group")
        source_value = _outline_source_value(
            item_element,
            descriptor,
            elements=elements,
        )
        if not isinstance(source_value, str) or (
            source_value
            != (
                descriptor.body_text
                if descriptor.marker_ownership == "separate"
                else descriptor.raw_marker
                + descriptor.marker_separator
                + descriptor.body_text
            )
        ):
            raise ValueError("outline item body differs from predecessor value")
        if descriptor.marker_bbox_id not in item_element.bbox_ids or (
            descriptor.marker_evidence_id not in item_element.evidence_ids
        ):
            raise ValueError("outline marker bbox/evidence backlink differs")
        marker_bbox = bboxes[descriptor.marker_bbox_id]
        if marker_bbox.role != "annotation":
            raise ValueError("outline marker bbox must have annotation role")
        _require_page_space_bbox(
            bbox_id=descriptor.marker_bbox_id,
            page_id=item_element.page_id,
            label="outline marker",
            coordinates=coordinates,
            bboxes=bboxes,
            bbox_ids=set(bboxes),
        )
        marker_evidence = evidence[descriptor.marker_evidence_id]
        marker_word_index = marker_evidence.metadata.get("word_index")
        expected_marker_metadata = {
            "policy_id": "p03-outline-structure-v1",
            "group_id": group_descriptor.record_id,
            "item_id": descriptor.record_id,
            "reader": "pdfplumber",
            "page_index": pages[item_element.page_id].page_index,
            "word_index": marker_word_index,
        }
        if (
            marker_evidence.method is not EvidenceMethod.NATIVE
            or marker_evidence.bbox_id != descriptor.marker_bbox_id
            or marker_evidence.value != descriptor.raw_marker
            or marker_evidence.confidence.scope != "evidence"
            or marker_evidence.confidence.score is not None
            or marker_evidence.confidence.unavailable_reason != "not_calibrated"
            or isinstance(marker_word_index, bool)
            or not isinstance(marker_word_index, int)
            or marker_word_index < 0
            or marker_evidence.metadata != expected_marker_metadata
        ):
            raise ValueError("outline marker evidence contract differs")
        if (
            not item_element.bbox_ids
            or item_element.bbox_ids[0] == descriptor.marker_bbox_id
        ):
            raise ValueError(
                "outline item requires a designated predecessor source bbox"
            )
        source_bbox = bboxes[item_element.bbox_ids[0]]
        vertical_overlap = min(
            marker_bbox.y + marker_bbox.height,
            source_bbox.y + source_bbox.height,
        ) - max(marker_bbox.y, source_bbox.y)
        if not (
            marker_bbox.x >= source_bbox.x - 1.0
            and marker_bbox.x + marker_bbox.width
            <= source_bbox.x + source_bbox.width + 1.0
            and vertical_overlap >= 0.5 * min(marker_bbox.height, source_bbox.height)
        ):
            raise ValueError("outline marker bbox differs from its source bbox")
        members_by_group[descriptor.group_element_id].append(item_element.id)

    outline_relationships_by_group: dict[str, list[RelationshipRecord]] = {
        value: [] for value in groups
    }
    incident_by_group: dict[tuple[str, str], list[str]] = {}
    relationships_by_page: dict[str, int] = {}
    for relationship in ir.relationships:
        is_outline = relationship.type in _OUTLINE_RELATIONSHIP_TYPES or (
            relationship.metadata.get("outline_policy") == "p03-outline-structure-v1"
        )
        if not is_outline:
            continue
        group_record_id = relationship.metadata.get("outline_group_id")
        group_pair = group_by_record_id.get(group_record_id)
        if group_pair is None:
            raise ValueError("outline relationship has no declared group")
        group_element, group_descriptor = group_pair
        expected_metadata: dict[str, Any] = {
            "canonical_inert": True,
            "outline_group_id": group_descriptor.record_id,
            "outline_policy": "p03-outline-structure-v1",
        }
        if relationship.type is RelationshipType.OUTLINE_NEXT:
            intervening = relationship.metadata.get("intervening_element_ids")
            if (
                not isinstance(intervening, list)
                or len(intervening) != len(set(intervening))
                or any(
                    not isinstance(value, str)
                    or value not in group_descriptor.continuation_element_ids
                    for value in intervening
                )
            ):
                raise ValueError("outline-next intervening elements differ")
            expected_metadata["intervening_element_ids"] = intervening
        elif relationship.type is RelationshipType.OUTLINE_CONTINUATION_OF:
            expected_metadata["interstitial_kind"] = "table"
        elif relationship.type not in {
            RelationshipType.CONTAINS,
            RelationshipType.OUTLINE_PARENT_OF,
        }:
            raise ValueError("outline relationship type is unsupported")
        if relationship.metadata != expected_metadata:
            raise ValueError("outline relationship metadata differs")
        source = elements[relationship.source_id]
        target = elements[relationship.target_id]
        if source.page_id != group_element.page_id or target.page_id != source.page_id:
            raise ValueError("outline relationships must be same-page")
        if relationship.type is RelationshipType.CONTAINS:
            compatible = relationship.source_id == group_element.id and (
                relationship.target_id in group_descriptor.member_element_ids
            )
        elif relationship.type is RelationshipType.OUTLINE_PARENT_OF:
            compatible = (
                relationship.source_id in group_descriptor.member_element_ids
                and relationship.target_id in group_descriptor.member_element_ids
            )
        elif relationship.type is RelationshipType.OUTLINE_NEXT:
            compatible = (
                relationship.source_id in group_descriptor.member_element_ids
                and relationship.target_id in group_descriptor.member_element_ids
            )
        else:
            compatible = (
                relationship.source_id in group_descriptor.continuation_element_ids
                and relationship.target_id in group_descriptor.member_element_ids
                and source.type.casefold() == "table"
            )
        if not compatible:
            raise ValueError("outline relationship endpoints are incompatible")
        outline_relationships_by_group[group_element.id].append(relationship)
        for endpoint in (relationship.source_id, relationship.target_id):
            incident_by_group.setdefault((group_element.id, endpoint), []).append(
                relationship.id
            )
        relationships_by_page[source.page_id] = (
            relationships_by_page.get(source.page_id, 0) + 1
        )

    if sum(len(value) for value in outline_relationships_by_group.values()) > (
        MAX_OUTLINE_RELATIONSHIPS_PER_DOCUMENT
    ) or any(
        count > MAX_OUTLINE_RELATIONSHIPS_PER_PAGE
        for count in relationships_by_page.values()
    ):
        raise ValueError("outline graph exceeds the relationship limit")

    for group_element_id, (group_element, descriptor) in (
        (element_id, (element, element.outline_group))
        for element_id, element in groups.items()
    ):
        assert descriptor is not None
        if members_by_group[group_element_id] != descriptor.member_element_ids:
            raise ValueError("outline group member order differs")
        group_items = [items[value] for value in descriptor.member_element_ids]
        item_descriptors = [value.outline_item for value in group_items]
        assert all(value is not None for value in item_descriptors)
        typed_items = [value for value in item_descriptors if value is not None]
        if [value.record_id for value in typed_items] != descriptor.member_item_ids:
            raise ValueError("outline group member record order differs")
        if len(typed_items) > MAX_OUTLINE_NODES_PER_GROUP:
            raise ValueError("outline group exceeds its node limit")

        relationship_records = outline_relationships_by_group[group_element_id]
        if [value.id for value in relationship_records] != descriptor.relationship_ids:
            raise ValueError("outline group relationship order differs")
        if not set(descriptor.canonical_relationship_ids).issubset(
            {value.id for value in ir.relationships}
        ):
            raise ValueError("outline canonical relationship custody differs")

        by_parent: dict[str | None, list[OutlineItemSemanticDescriptor]] = {}
        member_ids = set(descriptor.member_element_ids)
        index_by_element = {
            value: index for index, value in enumerate(descriptor.member_element_ids)
        }
        hierarchy_stack: list[str] = []
        for element, item_descriptor in zip(
            group_items,
            typed_items,
            strict=True,
        ):
            if item_descriptor.level > len(hierarchy_stack):
                raise ValueError("outline hierarchy skips a level")
            expected_parent = (
                None
                if item_descriptor.level == 0
                else hierarchy_stack[item_descriptor.level - 1]
            )
            if item_descriptor.parent_element_id != expected_parent:
                raise ValueError("outline parent differs from preorder stack")
            hierarchy_stack[item_descriptor.level :] = [element.id]
            if item_descriptor.parent_element_id is not None and (
                item_descriptor.parent_element_id not in member_ids
                or index_by_element[item_descriptor.parent_element_id]
                >= index_by_element[element.id]
            ):
                raise ValueError("outline parent must precede its child")
            by_parent.setdefault(item_descriptor.parent_element_id, []).append(
                item_descriptor
            )
            expected_incident = incident_by_group.get(
                (group_element_id, element.id), []
            )
            if item_descriptor.relationship_ids != expected_incident:
                raise ValueError("outline item relationship backlinks differ")
        roots = by_parent.get(None, [])
        minimum_root_count = 3 if descriptor.sequence_kind == "legal" else 2
        if len(roots) < minimum_root_count or any(value.level != 0 for value in roots):
            raise ValueError("outline group has too few level-zero roots")
        for parent_id, siblings in by_parent.items():
            if [value.ordinal for value in siblings] != list(
                range(1, len(siblings) + 1)
            ):
                raise ValueError("outline sibling ordinals are not contiguous")
            if parent_id is None:
                continue
            parent = items[parent_id].outline_item
            assert parent is not None
            if any(value.level != parent.level + 1 for value in siblings):
                raise ValueError("outline item level differs from its parent")

        contains = [
            value
            for value in relationship_records
            if value.type is RelationshipType.CONTAINS
        ]
        parents = [
            value
            for value in relationship_records
            if value.type is RelationshipType.OUTLINE_PARENT_OF
        ]
        next_edges = [
            value
            for value in relationship_records
            if value.type is RelationshipType.OUTLINE_NEXT
        ]
        continuations = [
            value
            for value in relationship_records
            if value.type is RelationshipType.OUTLINE_CONTINUATION_OF
        ]
        if [value.target_id for value in contains] != descriptor.member_element_ids:
            raise ValueError("outline contains cardinality differs")
        expected_parents = [
            (value.parent_element_id, element_id)
            for element_id, value in zip(
                descriptor.member_element_ids,
                typed_items,
                strict=True,
            )
            if value.parent_element_id is not None
        ]
        if [(value.source_id, value.target_id) for value in parents] != (
            expected_parents
        ):
            raise ValueError("outline parent cardinality differs")
        expected_next = [
            (first_element.id, second_element.id)
            for siblings in by_parent.values()
            for first_descriptor, second_descriptor in zip(
                siblings,
                siblings[1:],
                strict=False,
            )
            for first_element, second_element in [
                (
                    item_by_record_id[first_descriptor.record_id][0],
                    item_by_record_id[second_descriptor.record_id][0],
                )
            ]
        ]
        if [
            (value.source_id, value.target_id) for value in next_edges
        ] != expected_next:
            raise ValueError("outline-next cardinality differs")
        if [value.source_id for value in continuations] != (
            descriptor.continuation_element_ids
        ) or any(
            value.target_id not in descriptor.member_element_ids
            for value in continuations
        ):
            raise ValueError("outline continuation cardinality differs")

        group_source_bbox_ids: list[str] = []
        for item_element, item_descriptor in zip(
            group_items,
            typed_items,
            strict=True,
        ):
            if (
                not item_element.bbox_ids
                or item_element.bbox_ids[0] == item_descriptor.marker_bbox_id
            ):
                raise ValueError(
                    "outline item requires a designated predecessor source bbox"
                )
            group_source_bbox_ids.append(item_element.bbox_ids[0])
        for continuation_id in descriptor.continuation_element_ids:
            continuation = elements[continuation_id]
            if not continuation.bbox_ids:
                raise ValueError(
                    "outline continuation requires a designated source bbox"
                )
            group_source_bbox_ids.append(continuation.bbox_ids[0])
        source_boxes = [bboxes[value] for value in group_source_bbox_ids]
        group_bbox = bboxes[group_element.bbox_ids[0]]
        expected_box = (
            min(value.x for value in source_boxes),
            min(value.y for value in source_boxes),
            max(value.x + value.width for value in source_boxes),
            max(value.y + value.height for value in source_boxes),
        )
        if any(
            not math.isclose(actual, expected, rel_tol=0.0, abs_tol=0.001)
            for actual, expected in zip(
                (
                    group_bbox.x,
                    group_bbox.y,
                    group_bbox.x + group_bbox.width,
                    group_bbox.y + group_bbox.height,
                ),
                expected_box,
                strict=True,
            )
        ):
            raise ValueError("outline group bbox differs from its source union")


def _require_legacy_child_bbox(
    *,
    child: Mapping[str, Any],
    run: TextRunRecord,
    page: PageRecord,
    extent: IRBoundingBox,
) -> tuple[float, float, float, float]:
    raw_bbox = child.get("bbox")
    if not isinstance(raw_bbox, Mapping):
        raise ValueError(f"text run {run.id} target child has no bbox")
    try:
        values = tuple(float(raw_bbox[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"text run {run.id} target child has an invalid bbox") from exc
    if (
        not all(math.isfinite(value) for value in values)
        or values[2] <= 0
        or values[3] <= 0
    ):
        raise ValueError(f"text run {run.id} target child has an invalid bbox")
    if raw_bbox.get("unit") not in (None, "pt"):
        raise ValueError(
            f"text run {run.id} target child bbox is not in page-space points"
        )
    if raw_bbox.get("page_id") not in (None, run.page_id):
        raise ValueError(f"text run {run.id} target child bbox belongs to another page")
    if raw_bbox.get("page_index") not in (None, page.page_index):
        raise ValueError(f"text run {run.id} target child bbox belongs to another page")
    if (
        values[0] < extent.x
        or values[1] < extent.y
        or values[0] + values[2] > extent.x + extent.width + 1e-6
        or values[1] + values[3] > extent.y + extent.height + 1e-6
    ):
        raise ValueError(f"text run {run.id} target child bbox lies outside its page")
    return values


def _resolve_text_run_target(
    run: TextRunRecord,
    *,
    owner: ElementRecord,
    page: PageRecord,
    coordinates: Mapping[str, CoordinateSystem],
    bboxes: Mapping[str, IRBoundingBox],
    bbox_ids: set[str],
    elements: Mapping[str, ElementRecord],
    extent: IRBoundingBox,
) -> str:
    def has_matching_page_space_bbox(
        candidate_bbox_ids: Sequence[str],
        legacy_geometry: tuple[float, float, float, float],
    ) -> bool:
        for candidate_bbox_id in candidate_bbox_ids:
            if candidate_bbox_id not in bbox_ids:
                continue
            candidate_bbox = bboxes[candidate_bbox_id]
            coordinate = coordinates.get(candidate_bbox.coordinate_system_id)
            if (
                coordinate is None
                or coordinate.page_id != run.page_id
                or coordinate.unit != "pt"
                or coordinate.origin != "top_left"
                or coordinate.transform_to_page != IDENTITY_TRANSFORM
                or candidate_bbox.width <= 0
                or candidate_bbox.height <= 0
                or candidate_bbox.x < extent.x
                or candidate_bbox.y < extent.y
                or candidate_bbox.x + candidate_bbox.width
                > extent.x + extent.width + 1e-6
                or candidate_bbox.y + candidate_bbox.height
                > extent.y + extent.height + 1e-6
            ):
                continue
            if all(
                math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-6)
                for actual, expected in zip(
                    (
                        candidate_bbox.x,
                        candidate_bbox.y,
                        candidate_bbox.width,
                        candidate_bbox.height,
                    ),
                    legacy_geometry,
                    strict=True,
                )
            ):
                return True
        return False

    legacy_item = owner.properties.get("legacy_item")
    if not isinstance(legacy_item, Mapping):
        raise ValueError(f"text run {run.id} owner has no public legacy item")
    if run.target_path == ("value",):
        target = legacy_item.get("value")
        if not isinstance(target, str):
            raise ValueError(f"text run {run.id} target does not resolve to a string")
        legacy_geometry = _require_legacy_child_bbox(
            child=legacy_item,
            run=run,
            page=page,
            extent=extent,
        )
        if not owner.bbox_ids:
            raise ValueError(f"text run {run.id} target owner has no same-page bbox")
        if not has_matching_page_space_bbox(
            owner.bbox_ids,
            legacy_geometry,
        ):
            raise ValueError(
                f"text run {run.id} target owner bbox disagrees with the IR"
            )
        return target

    collection, index, terminal = run.target_path
    if type(index) is not int or index < 0:
        raise ValueError(f"text run {run.id} target index is invalid")
    children = legacy_item.get(collection)
    if (
        not isinstance(children, Sequence)
        or isinstance(children, (str, bytes, bytearray))
        or index >= len(children)
    ):
        raise ValueError(f"text run {run.id} target child does not exist")
    child = children[index]
    if not isinstance(child, Mapping):
        raise ValueError(f"text run {run.id} target child is not an object")
    target = child.get(terminal)
    if not isinstance(target, str):
        raise ValueError(f"text run {run.id} target does not resolve to a string")
    legacy_geometry = _require_legacy_child_bbox(
        child=child,
        run=run,
        page=page,
        extent=extent,
    )

    matching_children = [
        candidate
        for candidate in elements.values()
        if candidate.properties.get("parent_element_id") == owner.id
        and candidate.properties.get("collection") == collection
        and candidate.properties.get("index") == index
    ]
    if len(matching_children) != 1:
        raise ValueError(f"text run {run.id} target child has no unique IR owner")
    [child_element] = matching_children
    if child_element.page_id != run.page_id or not child_element.bbox_ids:
        raise ValueError(f"text run {run.id} target child has no same-page bbox")
    if not has_matching_page_space_bbox(
        child_element.bbox_ids,
        legacy_geometry,
    ):
        raise ValueError(f"text run {run.id} target child bbox disagrees with the IR")
    return target


def _text_colors_match(
    left: TextColorRecord,
    right: TextColorRecord,
) -> bool:
    return (
        left.space != "unknown"
        and left.space == right.space
        and len(left.components) == len(right.components)
        and all(
            abs(left_component - right_component) <= _MAX_TEXT_COLOR_COMPONENT_DELTA
            for left_component, right_component in zip(
                left.components,
                right.components,
                strict=True,
            )
        )
    )


def _validate_text_semantics_graph(
    ir: DocumentIR,
    *,
    coordinates: Mapping[str, CoordinateSystem],
    bboxes: Mapping[str, IRBoundingBox],
    pages: Mapping[str, PageRecord],
    elements: Mapping[str, ElementRecord],
    evidence: Mapping[str, EvidenceRecord],
    text_rules: Mapping[str, TextRuleRecord],
    text_runs: Mapping[str, TextRunRecord],
    page_ids: set[str],
    bbox_ids: set[str],
    element_ids: set[str],
    evidence_ids: set[str],
    text_rule_ids: set[str],
) -> None:
    page_extents: dict[str, IRBoundingBox] = {}

    def page_extent(page_id: str) -> IRBoundingBox:
        extent = page_extents.get(page_id)
        if extent is None:
            extent = _semantic_page_extent(
                page=pages[page_id],
                coordinates=coordinates,
                bboxes=bboxes,
            )
            page_extents[page_id] = extent
        return extent

    rule_counts_by_page: dict[str, int] = {}
    for rule in ir.text_rules:
        if rule.source_sha256 != ir.source_sha256:
            raise ValueError(f"text rule {rule.id} source SHA-256 mismatch")
        _require_reference(rule.page_id, page_ids, f"text rule {rule.id} page")
        rule_counts_by_page[rule.page_id] = rule_counts_by_page.get(rule.page_id, 0) + 1
        if rule_counts_by_page[rule.page_id] > _MAX_TEXT_RULES_PER_PAGE:
            raise ValueError(
                f"text semantics page {rule.page_id} exceeds its rule limit"
            )
        _require_page_space_bbox(
            bbox_id=rule.bbox_id,
            page_id=rule.page_id,
            label=f"text rule {rule.id}",
            coordinates=coordinates,
            bboxes=bboxes,
            bbox_ids=bbox_ids,
        )
        rule_bbox = bboxes[rule.bbox_id]
        _require_bbox_inside_page(
            bbox=rule_bbox,
            extent=page_extent(rule.page_id),
            label=f"text rule {rule.id}",
        )
        if not math.isclose(
            rule.width,
            rule_bbox.width,
            rel_tol=0.0,
            abs_tol=1e-9,
        ) or not math.isclose(
            rule.thickness,
            rule_bbox.height,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError(f"text rule {rule.id} dimensions disagree with its bbox")

    listed_run_ids = [
        run_id for element in ir.elements for run_id in element.text_run_ids
    ]
    if set(listed_run_ids) != set(text_runs):
        missing = sorted(set(text_runs) - set(listed_run_ids))
        extra = sorted(set(listed_run_ids) - set(text_runs))
        raise ValueError(
            f"element text-run membership mismatch: missing={missing}, extra={extra}"
        )

    prior_intervals: dict[tuple[str, tuple[Any, ...]], tuple[int, str]] = {}
    rule_use_counts: dict[str, int] = {}
    grouped_runs: dict[str, list[TextRunRecord]] = {}
    run_counts_by_page: dict[str, int] = {}
    for run in ir.text_runs:
        if run.source_sha256 != ir.source_sha256:
            raise ValueError(f"text run {run.id} source SHA-256 mismatch")
        _require_reference(run.page_id, page_ids, f"text run {run.id} page")
        run_counts_by_page[run.page_id] = run_counts_by_page.get(run.page_id, 0) + 1
        if run_counts_by_page[run.page_id] > _MAX_TEXT_RUNS_PER_PAGE:
            raise ValueError(f"text semantics page {run.page_id} exceeds its run limit")
        _require_reference(
            run.element_id,
            element_ids,
            f"text run {run.id} element",
        )
        owner = elements[run.element_id]
        if owner.page_id != run.page_id:
            raise ValueError(f"text run {run.id} owner belongs to another page")
        _require_page_space_bbox(
            bbox_id=run.bbox_id,
            page_id=run.page_id,
            label=f"text run {run.id}",
            coordinates=coordinates,
            bboxes=bboxes,
            bbox_ids=bbox_ids,
        )
        run_bbox = bboxes[run.bbox_id]
        _require_bbox_inside_page(
            bbox=run_bbox,
            extent=page_extent(run.page_id),
            label=f"text run {run.id}",
        )

        target = _resolve_text_run_target(
            run,
            owner=owner,
            page=pages[run.page_id],
            coordinates=coordinates,
            bboxes=bboxes,
            bbox_ids=bbox_ids,
            elements=elements,
            extent=page_extent(run.page_id),
        )
        target_sha256 = hashlib.sha256(target.encode("utf-8")).hexdigest()
        if run.target_text_sha256 != target_sha256:
            raise ValueError(f"text run {run.id} target SHA-256 mismatch")
        if not 0 <= run.start < run.end <= len(target):
            raise ValueError(f"text run {run.id} interval is out of bounds")
        if target[run.start : run.end] != run.text:
            raise ValueError(f"text run {run.id} text is not the target slice")

        target_key = (run.element_id, tuple(run.target_path))
        prior = prior_intervals.get(target_key)
        if prior is not None and run.start < prior[0]:
            raise ValueError(
                f"text run {run.id} overlaps or precedes text run {prior[1]}"
            )
        prior_intervals[target_key] = (run.end, run.id)

        for evidence_id in run.evidence_ids:
            _require_reference(
                evidence_id,
                evidence_ids,
                f"text run {run.id} evidence",
            )
            run_evidence = evidence[evidence_id]
            if run_evidence.element_id != run.element_id:
                raise ValueError(
                    f"text run {run.id} evidence belongs to another element"
                )
            evidence_owner = elements[run_evidence.element_id]
            if evidence_owner.page_id != run.page_id:
                raise ValueError(f"text run {run.id} evidence belongs to another page")
            if run_evidence.bbox_id != run.bbox_id:
                raise ValueError(
                    f"text run {run.id} evidence bbox does not match the run"
                )
            if run_evidence.method is not run.evidence_method:
                raise ValueError(
                    f"text run {run.id} evidence method does not match the run"
                )
        expected_rule_ids = sorted(
            run.rule_ids,
            key=lambda rule_id: (
                bboxes[text_rules[rule_id].bbox_id].y
                if rule_id in text_rules
                else math.inf,
                bboxes[text_rules[rule_id].bbox_id].x
                if rule_id in text_rules
                else math.inf,
                bboxes[text_rules[rule_id].bbox_id].width
                if rule_id in text_rules
                else math.inf,
                bboxes[text_rules[rule_id].bbox_id].height
                if rule_id in text_rules
                else math.inf,
                rule_id,
            ),
        )
        if run.rule_ids != expected_rule_ids:
            raise ValueError(f"text run {run.id} rules are out of canonical bbox order")
        for rule_id in run.rule_ids:
            _require_reference(
                rule_id,
                text_rule_ids,
                f"text run {run.id} rule",
            )
            if text_rules[rule_id].page_id != run.page_id:
                raise ValueError(f"text run {run.id} rule belongs to another page")
            if not _text_colors_match(run.color, text_rules[rule_id].color):
                raise ValueError(
                    f"text run {run.id} rule has incompatible color evidence"
                )
            rule_use_counts[rule_id] = rule_use_counts.get(rule_id, 0) + 1
            if rule_use_counts[rule_id] > 64:
                raise ValueError(f"text rule {rule_id} exceeds 64 linked runs")

        if run.change_group_id is not None:
            grouped_runs.setdefault(run.change_group_id, []).append(run)

    unlinked_rule_ids = sorted(text_rule_ids - set(rule_use_counts))
    if unlinked_rule_ids:
        raise ValueError(
            f"text rules are not linked by any text run: {unlinked_rule_ids}"
        )

    for group_id, group_runs in grouped_runs.items():
        ordered_group = sorted(
            group_runs,
            key=lambda run: (
                run.element_id,
                _text_target_path_sort_key(run.target_path),
                run.start,
                run.end,
                run.id,
            ),
        )
        first = ordered_group[0]
        semantic_key = (
            first.page_id,
            first.element_id,
            tuple(first.target_path),
            first.change_state,
            tuple(first.decorations),
            first.placeholder,
            first.semantic_derivation,
            first.evidence_method,
        )
        prior_end: int | None = None
        for run in ordered_group:
            if (
                run.page_id,
                run.element_id,
                tuple(run.target_path),
                run.change_state,
                tuple(run.decorations),
                run.placeholder,
                run.semantic_derivation,
                run.evidence_method,
            ) != semantic_key:
                raise ValueError(f"change group {group_id} is incoherent")
            if prior_end is not None and run.start != prior_end:
                raise ValueError(f"change group {group_id} is not adjacent")
            prior_end = run.end

    for element in ir.elements:
        owned_runs = [text_runs[run_id] for run_id in element.text_run_ids]
        expected_ids = [
            run.id
            for run in sorted(
                owned_runs,
                key=lambda run: (
                    _text_target_path_sort_key(run.target_path),
                    run.start,
                    run.end,
                    run.id,
                ),
            )
        ]
        if element.text_run_ids != expected_ids:
            raise ValueError(
                f"element {element.id} text runs are out of canonical order"
            )


def _reject_forbidden_cycles(
    relationships: Sequence[RelationshipRecord],
) -> None:
    by_type: dict[RelationshipType, list[RelationshipRecord]] = {}
    for relationship in relationships:
        if relationship.type in _ACYCLIC_RELATIONSHIPS:
            by_type.setdefault(relationship.type, []).append(relationship)

    for relationship_type, typed_relationships in by_type.items():
        adjacency: dict[str, list[str]] = {}
        indegree: dict[str, int] = {}
        for relationship in typed_relationships:
            adjacency.setdefault(relationship.source_id, []).append(
                relationship.target_id
            )
            indegree.setdefault(relationship.source_id, 0)
            indegree[relationship.target_id] = (
                indegree.get(relationship.target_id, 0) + 1
            )

        ready = deque(
            identifier for identifier, degree in indegree.items() if degree == 0
        )
        visited_count = 0
        while ready:
            identifier = ready.popleft()
            visited_count += 1
            for target in adjacency.get(identifier, []):
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        if visited_count != len(indegree):
            raise ValueError(f"forbidden {relationship_type.value} relationship cycle")


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError("document must be a mapping or Pydantic model")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = _canonical_json(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:20]}"


def _normalized_box(
    value: Any,
    *,
    coordinate_system_id: str,
    role: str,
    identity_parts: Sequence[Any],
) -> IRBoundingBox | None:
    if not isinstance(value, Mapping):
        return None
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value.get("width", value.get("w")))
        height = float(value.get("height", value.get("h")))
    except (KeyError, TypeError, ValueError):
        return None
    return IRBoundingBox(
        id=_stable_id("box", *identity_parts, x, y, width, height, role),
        coordinate_system_id=coordinate_system_id,
        x=x,
        y=y,
        width=width,
        height=height,
        role=role,
    )


def _confidence(value: Any, *, scope: str = "evidence") -> ConfidenceRecord:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        score = float(value)
        if math.isfinite(score) and 0 <= score <= 1:
            return ConfidenceRecord(scope=scope, score=score)
    return ConfidenceRecord(
        scope=scope,
        unavailable_reason="not_reported_by_source",
    )


def has_untrusted_generation_provenance(
    value: Any,
    *,
    depth: int = 0,
    include_derived_source: bool = True,
    _remaining_nodes: list[int] | None = None,
    _scan_all_values: bool = False,
) -> bool:
    """Fail closed on generated, model, malformed, or unscannable provenance."""

    if not isinstance(value, Mapping):
        return False
    if depth > _MAX_PROVENANCE_DEPTH:
        return True
    if _remaining_nodes is None:
        _remaining_nodes = [_MAX_PROVENANCE_NODE_BUDGET]
    if _remaining_nodes[0] <= 0:
        return True
    _remaining_nodes[0] -= 1

    def marker_is_absent(marker: Any) -> bool:
        return (
            marker is None
            or marker is False
            or (isinstance(marker, str) and marker == "")
        )

    def scan_nested(
        nested: Any,
        *,
        nested_depth: int,
        strict_scalars: bool = True,
    ) -> bool:
        if isinstance(nested, Mapping):
            return has_untrusted_generation_provenance(
                nested,
                depth=nested_depth,
                include_derived_source=include_derived_source,
                _remaining_nodes=_remaining_nodes,
                _scan_all_values=True,
            )
        if isinstance(nested, Sequence) and not isinstance(
            nested,
            (str, bytes, bytearray),
        ):
            if (
                nested_depth > _MAX_PROVENANCE_DEPTH
                or len(nested) > _MAX_PROVENANCE_SEQUENCE_ENTRIES
                or _remaining_nodes[0] <= 0
            ):
                return True
            _remaining_nodes[0] -= 1
            for item in nested:
                if isinstance(item, Mapping) or (
                    isinstance(item, Sequence)
                    and not isinstance(item, (str, bytes, bytearray))
                ):
                    if scan_nested(
                        item,
                        nested_depth=nested_depth + 1,
                        strict_scalars=strict_scalars,
                    ):
                        return True
                    continue
                if strict_scalars and not marker_is_absent(item):
                    return True
            return False
        return not marker_is_absent(nested)

    for marker_name in ("generated", "caption_generated"):
        if marker_name in value and not marker_is_absent(value.get(marker_name)):
            return True

    source = value.get("source")
    if source not in (None, ""):
        if not isinstance(source, str) or len(source) > 32:
            return True
        normalized_source = source.strip().casefold()
        if normalized_source == "model":
            return True
        if include_derived_source and (
            normalized_source == "derived"
            or normalized_source not in _TRUSTED_RAW_SOURCE_NAMES
        ):
            return True

    if "evidence_methods" in value:
        explicit_methods = value.get("evidence_methods")
        if (
            not isinstance(explicit_methods, Sequence)
            or isinstance(explicit_methods, (str, bytes, bytearray))
            or not explicit_methods
            or len(explicit_methods) > _MAX_EXPLICIT_EVIDENCE_METHODS
        ):
            return True
        for method in explicit_methods:
            try:
                method_byte_count = (
                    len(method.encode("utf-8")) if isinstance(method, str) else 0
                )
            except UnicodeEncodeError:
                return True
            if (
                not isinstance(method, str)
                or len(method) > _MAX_PROVENANCE_NAME_BYTES
                or method_byte_count > _MAX_PROVENANCE_NAME_BYTES
                or method.strip().casefold() not in _TRUSTED_RAW_EVIDENCE_METHOD_NAMES
            ):
                return True

    if any(
        not marker_is_absent(value.get(field_name))
        for field_name in (
            "created_by",
            "generator",
            "generation",
            "ai_model",
            "llm",
        )
    ):
        return True
    if any(
        not marker_is_absent(value.get(field_name))
        for field_name in (
            "model",
            "model_id",
            "model_name",
            "model_version",
        )
    ):
        return True
    for field_name in (
        "meta",
        "metadata",
        "description",
        "annotations",
        "provenance",
    ):
        nested = value.get(field_name)
        if marker_is_absent(nested):
            continue
        if scan_nested(nested, nested_depth=depth + 1):
            return True

    if _scan_all_values:
        if len(value) > _MAX_PROVENANCE_MAPPING_ENTRIES:
            return True
        inspected_fields = {
            "generated",
            "caption_generated",
            "source",
            "evidence_methods",
            "created_by",
            "generator",
            "generation",
            "ai_model",
            "llm",
            "model",
            "model_id",
            "model_name",
            "model_version",
            "meta",
            "metadata",
            "description",
            "annotations",
            "provenance",
        }
        for field_name, nested in value.items():
            if field_name in inspected_fields:
                continue
            if isinstance(nested, Mapping) or (
                isinstance(nested, Sequence)
                and not isinstance(nested, (str, bytes, bytearray))
            ):
                if scan_nested(
                    nested,
                    nested_depth=depth + 1,
                    strict_scalars=False,
                ):
                    return True
    return False


def _source_methods(item: Mapping[str, Any]) -> list[EvidenceMethod]:
    explicit = item.get("evidence_methods")
    methods: list[EvidenceMethod] = []
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        for index, value in enumerate(explicit):
            if index >= _MAX_EXPLICIT_EVIDENCE_METHODS:
                break
            try:
                value_byte_count = (
                    len(value.encode("utf-8")) if isinstance(value, str) else 0
                )
            except UnicodeEncodeError:
                continue
            if (
                not isinstance(value, str)
                or len(value) > _MAX_PROVENANCE_NAME_BYTES
                or value_byte_count > _MAX_PROVENANCE_NAME_BYTES
            ):
                continue
            try:
                method = EvidenceMethod(value.strip().casefold())
            except ValueError:
                continue
            if method not in methods:
                methods.append(method)

    source = str(item.get("source") or "").casefold()
    source_map = {
        "native": [EvidenceMethod.NATIVE],
        "ocr": [EvidenceMethod.OCR],
        "mixed": [EvidenceMethod.NATIVE, EvidenceMethod.OCR],
        "derived": [EvidenceMethod.DERIVED],
        "recovered": [EvidenceMethod.RECOVERED],
        "model": [EvidenceMethod.MODEL],
        "embedded": [EvidenceMethod.EMBEDDED],
        "vector": [EvidenceMethod.VECTOR],
    }
    if source:
        for method in source_map.get(source, [EvidenceMethod.DERIVED]):
            if method not in methods:
                methods.append(method)
    elif "evidence_methods" not in item:
        methods.append(EvidenceMethod.DERIVED)

    if str(item.get("engine") or "").casefold() == "pdfplumber":
        if EvidenceMethod.VECTOR not in methods:
            methods.append(EvidenceMethod.VECTOR)
    if item.get("embedded_images") and EvidenceMethod.EMBEDDED not in methods:
        methods.append(EvidenceMethod.EMBEDDED)
    if (
        str(item.get("ocr_text") or "").strip()
        or str(item.get("raw_ocr_text") or "").strip()
        or any(
            isinstance(child, Mapping)
            and str(child.get("source") or "").casefold() == "ocr"
            for child in (item.get("items") or [])
        )
    ) and EvidenceMethod.OCR not in methods:
        methods.append(EvidenceMethod.OCR)
    if item.get("caption_generated"):
        methods = [method for method in methods if method is not EvidenceMethod.DERIVED]
        if EvidenceMethod.MODEL not in methods:
            methods.append(EvidenceMethod.MODEL)
    return methods or [EvidenceMethod.DERIVED]


def _evidence_value(
    item: Mapping[str, Any],
    method: EvidenceMethod,
) -> Any:
    if method is EvidenceMethod.OCR:
        return item.get("ocr_text") or item.get("raw_ocr_text") or item.get("value")
    if method is EvidenceMethod.MODEL:
        return item.get("caption") or item.get("description") or item.get("value")
    if method is EvidenceMethod.VECTOR:
        return item.get("rows") or item.get("cells") or item.get("value")
    if method is EvidenceMethod.EMBEDDED:
        return item.get("embedded_images") or item.get("value")
    if method is EvidenceMethod.NATIVE and item.get("caption_source") == (
        "document_caption"
    ):
        return item.get("caption") or item.get("value")
    return item.get("value")


def _child_collections(
    item: Mapping[str, Any],
) -> Iterable[tuple[str, int, Mapping[str, Any]]]:
    for collection_name in (
        "items",
        "cells",
        "fields",
        "embedded_images",
        "rejected_ocr_candidates",
    ):
        values = item.get(collection_name)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            continue
        for index, child in enumerate(values):
            if isinstance(child, Mapping):
                yield collection_name, index, child


def _child_type(parent_type: str, collection_name: str) -> str:
    names = {
        "items": "child",
        "cells": "cell",
        "fields": "field",
        "embedded_images": "embedded_image",
        "rejected_ocr_candidates": "ocr_candidate",
    }
    return f"{parent_type}_{names[collection_name]}"


def _child_value(child: Mapping[str, Any]) -> Any:
    for key in ("value", "text", "ocr_text", "key"):
        if child.get(key) not in (None, ""):
            if key == "key" and child.get("value") not in (None, ""):
                return {
                    "key": child.get("key"),
                    "value": child.get("value"),
                }
            return child.get(key)
    return None


_SEMANTIC_RELATION_FIELDS: tuple[tuple[tuple[str, ...], RelationshipType, str], ...] = (
    (("caption", "captions"), RelationshipType.CAPTION_OF, "caption"),
    (
        ("source_note", "source_notes"),
        RelationshipType.SOURCE_NOTE_OF,
        "source_note",
    ),
    (("footnote", "footnotes"), RelationshipType.FOOTNOTE_OF, "footnote"),
    (("legend", "legends"), RelationshipType.LEGEND_OF, "legend"),
    (("axis", "axes"), RelationshipType.AXIS_OF, "axis"),
    (
        ("alternative", "alternatives"),
        RelationshipType.ALTERNATIVE_OF,
        "alternative",
    ),
    (
        ("annotation", "annotations"),
        RelationshipType.ANNOTATION_OF,
        "annotation",
    ),
)


def _as_semantic_values(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if item not in (None, "")]
    return [value]


def _semantic_children(
    item: Mapping[str, Any],
) -> Iterable[tuple[str, int, RelationshipType, str, Mapping[str, Any]]]:
    seen_keys: set[str] = set()
    for keys, relationship_type, element_type in _SEMANTIC_RELATION_FIELDS:
        for key in keys:
            if key in seen_keys or key not in item:
                continue
            seen_keys.add(key)
            for index, value in enumerate(_as_semantic_values(item.get(key))):
                if isinstance(value, Mapping):
                    child = dict(value)
                    if _child_value(child) is None:
                        child["value"] = deepcopy(value)
                else:
                    child = {"value": deepcopy(value)}
                if key.startswith("caption"):
                    child.setdefault("bbox", item.get("caption_bbox"))
                    child.setdefault("confidence", item.get("caption_confidence"))
                    if item.get("caption_generated"):
                        child["source"] = "model"
                        child["generated"] = True
                    else:
                        child.setdefault("source", item.get("source"))
                else:
                    singular = key[:-1] if key.endswith("s") else key
                    child.setdefault("bbox", item.get(f"{singular}_bbox"))
                    child.setdefault(
                        "source",
                        item.get(f"{singular}_source") or item.get("source"),
                    )
                yield key, index, relationship_type, element_type, child


def build_document_ir(
    document: Any,
    *,
    raw_graph: Mapping[str, Any] | None = None,
    native_texts: Sequence[str] = (),
    font_audit: Mapping[str, Any] | None = None,
    font_recovery: Mapping[str, Any] | None = None,
    selective_span_ocr: Mapping[str, Any] | None = None,
    text_run_evidence: Mapping[str, Any] | None = None,
) -> DocumentIR:
    """Adapt a normalized v1 document into the strict internal IR."""

    source = _as_mapping(document)
    document_metadata = source.get("document")
    if not isinstance(document_metadata, Mapping):
        raise ValueError("document metadata is required")
    source_sha256 = str(document_metadata.get("sha256") or "")
    if not source_sha256:
        source_sha256 = hashlib.sha256(
            _canonical_json(source).encode("utf-8")
        ).hexdigest()
    document_id = _stable_id("doc", source_sha256)

    coordinate_systems: list[CoordinateSystem] = []
    boxes: list[IRBoundingBox] = []
    pages: list[PageRecord] = []
    regions: list[RegionRecord] = []
    elements: list[ElementRecord] = []
    evidence: list[EvidenceRecord] = []
    relationships: list[RelationshipRecord] = []
    coordinate_ids: set[str] = set()

    def ensure_coordinate_system(
        *,
        page_id: str,
        page_unit: str,
        raw_box: Any,
    ) -> str:
        declared_unit = page_unit
        transform: tuple[float, float, float, float, float, float] | None = (
            IDENTITY_TRANSFORM
        )
        unavailable_reason: str | None = None
        if isinstance(raw_box, Mapping):
            declared_unit = str(raw_box.get("unit") or page_unit)
            if declared_unit not in {"pt", "px"}:
                raise ValueError(f"unsupported bounding-box unit: {declared_unit}")
            raw_transform = raw_box.get("transform_to_page", raw_box.get("transform"))
            if raw_transform is not None:
                if (
                    not isinstance(raw_transform, Sequence)
                    or isinstance(raw_transform, (str, bytes))
                    or len(raw_transform) != 6
                ):
                    raise ValueError("coordinate transform must contain six values")
                try:
                    transform = tuple(float(value) for value in raw_transform)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "coordinate transform values must be numeric"
                    ) from exc
            elif declared_unit != page_unit:
                transform = None
                unavailable_reason = "cross_unit_transform_not_declared_by_source"
        coordinate_id = _stable_id(
            "coords",
            page_id,
            declared_unit,
            transform,
            unavailable_reason,
        )
        if coordinate_id not in coordinate_ids:
            coordinate_systems.append(
                CoordinateSystem(
                    id=coordinate_id,
                    page_id=page_id,
                    unit=declared_unit,
                    transform_to_page=transform,
                    transform_unavailable_reason=unavailable_reason,
                )
            )
            coordinate_ids.add(coordinate_id)
        return coordinate_id

    def add_box(
        raw_box: Any,
        *,
        page_id: str,
        page_unit: str,
        role: str,
        identity_parts: Sequence[Any],
    ) -> IRBoundingBox | None:
        coordinate_id = ensure_coordinate_system(
            page_id=page_id,
            page_unit=page_unit,
            raw_box=raw_box,
        )
        box = _normalized_box(
            raw_box,
            coordinate_system_id=coordinate_id,
            role=role,
            identity_parts=identity_parts,
        )
        if box is not None:
            boxes.append(box)
        return box

    def add_evidence(
        *,
        element_id: str,
        item: Mapping[str, Any],
        box: IRBoundingBox | None,
        scope: str = "evidence",
        metadata: Mapping[str, Any] | None = None,
    ) -> list[str]:
        identifiers: list[str] = []
        for method in _source_methods(item):
            value = _evidence_value(item, method)
            evidence_id = _stable_id(
                "ev",
                element_id,
                method.value,
                box.id if box else None,
                value,
            )
            identifiers.append(evidence_id)
            evidence.append(
                EvidenceRecord(
                    id=evidence_id,
                    element_id=element_id,
                    method=method,
                    bbox_id=box.id if box else None,
                    value=deepcopy(value),
                    confidence=_confidence(
                        item.get("confidence"),
                        scope=scope,
                    ),
                    metadata={
                        "source": item.get("source"),
                        "engine": item.get("engine"),
                        **dict(metadata or {}),
                    },
                )
            )
        return identifiers

    raw_pages = source.get("pages") or []
    if not isinstance(raw_pages, Sequence):
        raise ValueError("pages must be a sequence")

    for page_offset, raw_page in enumerate(raw_pages):
        if not isinstance(raw_page, Mapping):
            raise ValueError(f"page {page_offset} must be an object")
        page_index = int(raw_page.get("page_index") or page_offset + 1)
        page_id = _stable_id("page", document_id, page_index)
        unit = "px" if str(raw_page.get("unit")) == "px" else "pt"
        coordinate_id = ensure_coordinate_system(
            page_id=page_id,
            page_unit=unit,
            raw_box=None,
        )
        page_box = IRBoundingBox(
            id=_stable_id(
                "box",
                page_id,
                0,
                0,
                raw_page.get("page_width"),
                raw_page.get("page_height"),
                "page",
            ),
            coordinate_system_id=coordinate_id,
            x=0,
            y=0,
            width=float(raw_page["page_width"]),
            height=float(raw_page["page_height"]),
            role="page",
        )
        boxes.append(page_box)
        region_id = _stable_id("region", page_id, "page")
        page_element_ids: list[str] = []
        presentation_element_ids: list[str] = []
        primary_orders: list[tuple[int, int, str]] = []

        raw_items = raw_page.get("items") or []
        if not isinstance(raw_items, Sequence):
            raise ValueError(f"page {page_index} items must be a sequence")

        def add_child_element(
            *,
            owner_id: str,
            child: Mapping[str, Any],
            child_id: str,
            child_type: str,
            collection: str,
            child_index: int,
            relationship_type: RelationshipType,
            presentation_role: str,
            relation_source_is_child: bool,
        ) -> None:
            child_box = add_box(
                child.get("bbox"),
                page_id=page_id,
                page_unit=unit,
                role=(
                    "field"
                    if collection in {"cells", "fields"}
                    else (
                        "annotation"
                        if relationship_type is RelationshipType.ANNOTATION_OF
                        else "child"
                    )
                ),
                identity_parts=(child_id,),
            )
            child_evidence_ids = add_evidence(
                element_id=child_id,
                item=child,
                box=child_box,
                scope=("field" if collection in {"cells", "fields"} else "evidence"),
                metadata={
                    "collection": collection,
                    "index": child_index,
                },
            )
            elements.append(
                ElementRecord(
                    id=child_id,
                    page_id=page_id,
                    type=child_type,
                    value=deepcopy(_child_value(child)),
                    markdown=(
                        str(child["md"]) if child.get("md") is not None else None
                    ),
                    bbox_ids=[child_box.id] if child_box else [],
                    evidence_ids=child_evidence_ids,
                    presentation_role=(
                        "diagnostic"
                        if child.get("accepted") is False
                        else presentation_role
                    ),
                    presentation=ElementPresentationDirective(
                        accepted=(
                            child.get("accepted")
                            if isinstance(child.get("accepted"), bool)
                            else None
                        )
                    ),
                    properties={
                        "parent_element_id": owner_id,
                        "collection": collection,
                        "index": child_index,
                        "legacy_child": deepcopy(dict(child)),
                        "generated": bool(child.get("generated")),
                    },
                )
            )
            page_element_ids.append(child_id)
            source_id = child_id if relation_source_is_child else owner_id
            target_id = owner_id if relation_source_is_child else child_id
            relationships.append(
                RelationshipRecord(
                    id=_stable_id(
                        "rel",
                        relationship_type.value,
                        source_id,
                        target_id,
                        collection,
                        child_index,
                    ),
                    type=relationship_type,
                    source_id=source_id,
                    target_id=target_id,
                    evidence_ids=child_evidence_ids,
                    metadata={
                        "collection": collection,
                        "index": child_index,
                    },
                )
            )

        for item_offset, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                raise ValueError(
                    f"page {page_index} item {item_offset} must be an object"
                )
            legacy_id = str(raw_item.get("id") or "").strip()
            item_identity = (
                ("legacy_id", legacy_id)
                if legacy_id
                else (
                    "fallback",
                    item_offset,
                    raw_item.get("type"),
                    raw_item.get("reading_order", item_offset),
                    raw_item.get("value"),
                    raw_item.get("bbox"),
                )
            )
            element_id = _stable_id("el", document_id, page_index, item_identity)
            page_element_ids.append(element_id)
            presentation_element_ids.append(element_id)
            reading_order = int(raw_item.get("reading_order", item_offset))
            primary_orders.append((reading_order, item_offset, element_id))
            item_box = add_box(
                raw_item.get("bbox"),
                page_id=page_id,
                page_unit=unit,
                role="element",
                identity_parts=(element_id,),
            )
            item_evidence_ids = add_evidence(
                element_id=element_id,
                item=raw_item,
                box=item_box,
            )

            raw_visual_model_evidence = raw_item.get("visual_model_evidence")
            visual_model_evidence = (
                VisualModelEvidenceBundle.model_validate(
                    raw_visual_model_evidence,
                    strict=True,
                )
                if raw_visual_model_evidence is not None
                else None
            )
            legacy_projection = deepcopy(dict(raw_item))
            # Keep model output outside the source/predecessor snapshot. Layout
            # provenance scanners must continue to evaluate the exact Phase 05
            # item, while the typed IR field carries the additive observation.
            legacy_projection.pop("visual_model_evidence", None)

            elements.append(
                ElementRecord(
                    id=element_id,
                    page_id=page_id,
                    type=str(raw_item.get("type") or "unknown"),
                    reading_order=reading_order,
                    value=deepcopy(raw_item.get("value")),
                    markdown=(
                        str(
                            raw_item.get("html")
                            if (
                                str(raw_item.get("type") or "").casefold() == "table"
                                and raw_item.get("html") is not None
                            )
                            else raw_item["md"]
                        )
                        if (
                            raw_item.get("md") is not None
                            or (
                                str(raw_item.get("type") or "").casefold() == "table"
                                and raw_item.get("html") is not None
                            )
                        )
                        else None
                    ),
                    bbox_ids=[item_box.id] if item_box else [],
                    evidence_ids=item_evidence_ids,
                    running_region=(
                        RunningRegionDescriptor.model_validate(
                            raw_item["running_region"]
                        )
                        if raw_item.get("running_region") is not None
                        else None
                    ),
                    visual_model_evidence=visual_model_evidence,
                    presentation_role="primary",
                    presentation=ElementPresentationDirective(
                        include_subordinate_ocr=(
                            raw_item.get("include_ocr_in_primary")
                            if isinstance(
                                raw_item.get("include_ocr_in_primary"),
                                bool,
                            )
                            else None
                        ),
                        accepted=True,
                    ),
                    properties={
                        "legacy_item": legacy_projection,
                        "generated": bool(raw_item.get("caption_generated")),
                        "region_role": raw_item.get("region_role"),
                        "content_type": raw_item.get("content_type"),
                        "source_position": item_offset,
                    },
                )
            )

            for collection_name, child_index, child in _child_collections(raw_item):
                child_id = _stable_id(
                    "el",
                    element_id,
                    collection_name,
                    child_index,
                    child,
                )
                relationship_type = (
                    RelationshipType.ALTERNATIVE_OF
                    if collection_name == "rejected_ocr_candidates"
                    else RelationshipType.CONTAINS
                )
                add_child_element(
                    owner_id=element_id,
                    child=child,
                    child_id=child_id,
                    child_type=_child_type(
                        str(raw_item.get("type") or "unknown"),
                        collection_name,
                    ),
                    collection=collection_name,
                    child_index=child_index,
                    relationship_type=relationship_type,
                    presentation_role=(
                        "diagnostic"
                        if collection_name == "rejected_ocr_candidates"
                        else "subordinate"
                    ),
                    relation_source_is_child=(
                        relationship_type is RelationshipType.ALTERNATIVE_OF
                    ),
                )

            for (
                field_name,
                child_index,
                relationship_type,
                semantic_type,
                child,
            ) in _semantic_children(raw_item):
                child_id = _stable_id(
                    "el",
                    element_id,
                    field_name,
                    child_index,
                    child,
                )
                add_child_element(
                    owner_id=element_id,
                    child=child,
                    child_id=child_id,
                    child_type=semantic_type,
                    collection=field_name,
                    child_index=child_index,
                    relationship_type=relationship_type,
                    presentation_role=(
                        "alternate"
                        if relationship_type is RelationshipType.ALTERNATIVE_OF
                        else "subordinate"
                    ),
                    relation_source_is_child=True,
                )

        ordered_primary = sorted(primary_orders)
        for (_order, _position, source_id), (
            _next_order,
            _next_position,
            target_id,
        ) in zip(ordered_primary, ordered_primary[1:]):
            relationships.append(
                RelationshipRecord(
                    id=_stable_id(
                        "rel",
                        RelationshipType.READING_BEFORE.value,
                        source_id,
                        target_id,
                    ),
                    type=RelationshipType.READING_BEFORE,
                    source_id=source_id,
                    target_id=target_id,
                    metadata={"basis": "legacy_reading_order"},
                )
            )

        region = RegionRecord(
            id=region_id,
            page_id=page_id,
            role="page",
            bbox_id=page_box.id,
            element_ids=list(page_element_ids),
        )
        regions.append(region)
        pages.append(
            PageRecord(
                id=page_id,
                page_index=page_index,
                page_number=raw_page.get("page_number", page_index),
                page_label=str(raw_page.get("page_label", page_index)),
                coordinate_system_id=coordinate_id,
                region_ids=[region_id],
                element_ids=list(page_element_ids),
                presentation_element_ids=list(presentation_element_ids),
                page_identity=(
                    PageIdentity.model_validate(raw_page["page_identity"])
                    if raw_page.get("page_identity") is not None
                    else None
                ),
            )
        )

    ir = DocumentIR(
        id=document_id,
        source_sha256=source_sha256,
        coordinate_systems=coordinate_systems,
        bboxes=boxes,
        pages=pages,
        regions=regions,
        elements=elements,
        evidence=evidence,
        relationships=relationships,
    )
    if raw_graph is not None:
        ir = _normalize_raw_reference_graph(
            ir,
            raw_graph,
            native_texts=native_texts,
        )
        from app.services.layout_source_notes import (
            attach_source_note_evidence_concerns,
        )

        ir = attach_source_note_evidence_concerns(ir, raw_graph)
    if font_audit is not None:
        ir = _attach_font_audit_concerns(ir, font_audit)
    if font_recovery is not None:
        ir = _attach_font_recovery(ir, font_recovery)
    if selective_span_ocr is not None:
        ir = _attach_selective_span_ocr(ir, selective_span_ocr)
    return ir


def _attach_font_audit_concerns(
    ir: DocumentIR,
    report: Mapping[str, Any],
) -> DocumentIR:
    """Attach bounded PDF font diagnostics without changing public content."""

    if (
        report.get("status") == "complete"
        and not report.get("findings")
        and not report.get("diagnostics")
    ):
        # Healthy audits have no IR delta. Preserve the existing immutable
        # model instead of deep-copying and revalidating the complete graph.
        return ir

    working = ir.model_copy(deep=True)
    pages_by_index = {page.page_index: page.id for page in working.pages}
    findings = report.get("findings") or []
    if not isinstance(findings, Sequence) or isinstance(
        findings,
        (str, bytes, bytearray),
    ):
        findings = []

    for position, raw_finding in enumerate(findings):
        if not isinstance(raw_finding, Mapping):
            continue
        finding = deepcopy(dict(raw_finding))
        reason_values = finding.get("reason_codes") or []
        if not isinstance(reason_values, Sequence) or isinstance(
            reason_values,
            (str, bytes, bytearray),
        ):
            reason_values = []
        reason_codes = [str(value) for value in reason_values if str(value).strip()]
        health = str(finding.get("health") or "unresolved")
        object_id = finding.get("font_object_id", finding.get("object_id"))
        font_ref = finding.get("font_ref")
        page_indexes = finding.get("page_indexes") or []
        if not page_indexes and finding.get("page_index") is not None:
            page_indexes = [finding.get("page_index")]
        if not isinstance(page_indexes, Sequence) or isinstance(
            page_indexes,
            (str, bytes, bytearray),
        ):
            page_indexes = []
        target_page_id = None
        for value in page_indexes:
            try:
                target_page_id = pages_by_index.get(int(value))
            except (TypeError, ValueError):
                continue
            if target_page_id is not None:
                break

        working.concerns.append(
            IRConcern(
                code=(
                    "pdf_font_mapping_suspicious"
                    if health == "suspicious"
                    else "pdf_font_mapping_unresolved"
                ),
                message=(
                    (
                        "PDF font mapping is suspicious"
                        if health == "suspicious"
                        else "PDF font mapping could not be fully audited"
                    )
                    + (f": {', '.join(reason_codes)}" if reason_codes else "")
                ),
                source_ref=(
                    f"pdf-font-object:{object_id}"
                    if object_id is not None
                    else (
                        f"pdf-font-{font_ref}"
                        if font_ref is not None
                        else f"pdf-font-finding:{position}"
                    )
                ),
                target_ref=target_page_id,
                metadata={
                    "font_audit_schema_version": report.get("schema_version"),
                    "source_sha256": report.get("source_sha256"),
                    "finding": finding,
                },
            )
        )

    status = str(report.get("status") or "")
    if status in {"partial", "unavailable"}:
        diagnostics = report.get("diagnostics") or []
        if not isinstance(diagnostics, Sequence) or isinstance(
            diagnostics,
            (str, bytes, bytearray),
        ):
            diagnostics = []
        working.concerns.append(
            IRConcern(
                code=f"pdf_font_audit_{status}",
                message=(
                    "PDF font audit completed with incomplete diagnostics"
                    if status == "partial"
                    else "PDF font audit was unavailable"
                ),
                metadata={
                    "font_audit_schema_version": report.get("schema_version"),
                    "diagnostics": [deepcopy(value) for value in diagnostics[:20]],
                },
            )
        )

    return DocumentIR.model_validate(working.model_dump(mode="json"))


def _recovery_text_replacement(
    value: str,
    *,
    original: str,
    recovered: str,
) -> str | None:
    """Replace one whitespace-equivalent damaged run without semantic edits."""

    original_core = " ".join(original.split())
    recovered_core = recovered.strip()
    if not original_core or not recovered_core:
        return None
    tokens = original_core.split(" ")
    pattern = re.compile(r"\s+".join(re.escape(token) for token in tokens))
    matches = list(pattern.finditer(value))
    if len(matches) != 1:
        return None
    start, end = matches[0].span()

    # Normalizers can insert a space between a font run and adjacent
    # punctuation. Consume only whitespace immediately inside paired
    # punctuation; this is source-layout cleanup, not language inference.
    left = start
    while left > 0 and value[left - 1].isspace():
        left -= 1
    if left > 0 and value[left - 1] in "([{":
        start = left
    right = end
    while right < len(value) and value[right].isspace():
        right += 1
    if right < len(value) and value[right] in ")]}":
        end = right

    replaced = value[:start] + recovered_core + value[end:]
    return replaced if replaced != value else None


def _attach_font_recovery(
    ir: DocumentIR,
    report: Mapping[str, Any],
) -> DocumentIR:
    """Attach glyph evidence and select only uniquely owned native prose."""

    from app.services.font_recovery import FontRecoveryReport

    validated_report = FontRecoveryReport.model_validate(dict(report))
    payload = validated_report.model_dump(mode="json", exclude_none=True)
    report_source_sha256 = payload.get("source_sha256")
    if report_source_sha256 is not None and report_source_sha256 != ir.source_sha256:
        working = ir.model_copy(deep=True)
        working.concerns.append(
            IRConcern(
                code="font_recovery_source_mismatch",
                message=(
                    "Font recovery evidence was refused because its source "
                    "identity does not match the document."
                ),
                metadata={
                    "document_source_sha256": ir.source_sha256,
                    "recovery_source_sha256": report_source_sha256,
                },
            )
        )
        return DocumentIR.model_validate(working.model_dump(mode="json"))
    if (
        payload.get("status") == "complete"
        and not payload.get("runs")
        and not payload.get("refusals")
        and not payload.get("diagnostics")
    ):
        return ir

    working = ir.model_copy(deep=True)
    pages_by_index = {page.page_index: page for page in working.pages}
    elements_by_id = {element.id: element for element in working.elements}
    boxes_by_id = {box.id: box for box in working.bboxes}
    coordinates_by_id = {
        coordinate.id: coordinate for coordinate in working.coordinate_systems
    }

    def element_page_box(
        element: ElementRecord,
    ) -> tuple[float, float, float, float] | None:
        if not element.bbox_ids:
            return None
        box = boxes_by_id.get(element.bbox_ids[0])
        if box is None:
            return None
        coordinate = coordinates_by_id.get(box.coordinate_system_id)
        if coordinate is None:
            return None
        return _page_box_coordinates(box, coordinate)

    def owner_for_run(
        raw_run: Mapping[str, Any],
    ) -> ElementRecord | None:
        try:
            page_index = int(raw_run["page_index"])
            raw_box = raw_run["bbox"]
            run_box = (
                float(raw_box["x"]),
                float(raw_box["y"]),
                float(raw_box["width"]),
                float(raw_box["height"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        page = pages_by_index.get(page_index)
        if page is None:
            return None
        candidates: list[tuple[float, ElementRecord]] = []
        for element_id in page.presentation_element_ids:
            element = elements_by_id[element_id]
            overlap = _box_overlap_of_smaller(
                run_box,
                element_page_box(element),
            )
            if overlap >= 0.8:
                candidates.append((overlap, element))
        if not candidates:
            return None
        candidates.sort(key=lambda entry: (-entry[0], entry[1].id))
        best_overlap = candidates[0][0]
        best = [
            element
            for overlap, element in candidates
            if abs(overlap - best_overlap) <= 1e-9
        ]
        return best[0] if len(best) == 1 else None

    def append_alternative_element(
        *,
        raw_run: Mapping[str, Any],
        owner: ElementRecord | None,
        page: PageRecord,
    ) -> ElementRecord:
        run_evidence_id = str(raw_run.get("evidence_id") or "")
        alternate_id = _stable_id(
            "el",
            working.id,
            "font_recovery_alternative",
            run_evidence_id,
        )
        raw_box = raw_run.get("bbox")
        alternate_box = _normalized_box(
            raw_box,
            coordinate_system_id=page.coordinate_system_id,
            role="annotation",
            identity_parts=(alternate_id, "font_recovery"),
        )
        bbox_ids: list[str] = []
        if alternate_box is not None:
            working.bboxes.append(alternate_box)
            boxes_by_id[alternate_box.id] = alternate_box
            bbox_ids.append(alternate_box.id)
        alternate = ElementRecord(
            id=alternate_id,
            page_id=page.id,
            type="text",
            value=str(raw_run.get("recovered_text") or ""),
            markdown=str(raw_run.get("recovered_text") or ""),
            bbox_ids=bbox_ids,
            presentation_role="alternate",
            presentation=ElementPresentationDirective(accepted=True),
            properties={
                "font_recovery": {
                    "source_sha256": report_source_sha256,
                    "method": raw_run.get("method"),
                    "font_ref": raw_run.get("font_ref"),
                    "font_object_id": raw_run.get("font_object_id"),
                    "run_evidence_id": run_evidence_id,
                    "original_text": raw_run.get("original_text"),
                },
                "owner_element_id": owner.id if owner is not None else None,
            },
        )
        working.elements.append(alternate)
        elements_by_id[alternate.id] = alternate
        page.element_ids.append(alternate.id)
        page_regions = [
            region for region in working.regions if region.page_id == page.id
        ]
        if page_regions:
            page_regions[0].element_ids.append(alternate.id)
        if owner is not None:
            working.relationships.append(
                RelationshipRecord(
                    id=_stable_id(
                        "rel",
                        RelationshipType.ALTERNATIVE_OF.value,
                        alternate.id,
                        owner.id,
                        run_evidence_id,
                    ),
                    type=RelationshipType.ALTERNATIVE_OF,
                    source_id=alternate.id,
                    target_id=owner.id,
                    metadata={
                        "method": raw_run.get("method"),
                        "selected": False,
                    },
                )
            )
        return alternate

    def attach_glyph_evidence(
        *,
        raw_run: Mapping[str, Any],
        element: ElementRecord,
        page: PageRecord,
    ) -> list[str]:
        recovered_ids: list[str] = []
        raw_glyphs = raw_run.get("glyphs") or []
        if not isinstance(raw_glyphs, Sequence) or isinstance(
            raw_glyphs,
            (str, bytes, bytearray),
        ):
            return recovered_ids
        for raw_glyph in raw_glyphs:
            if not isinstance(raw_glyph, Mapping):
                continue
            source_evidence_id = str(raw_glyph.get("evidence_id") or "")
            glyph_box = _normalized_box(
                raw_glyph.get("bbox"),
                coordinate_system_id=page.coordinate_system_id,
                role="annotation",
                identity_parts=(
                    working.id,
                    source_evidence_id,
                    "glyph",
                ),
            )
            if glyph_box is None:
                continue
            working.bboxes.append(glyph_box)
            boxes_by_id[glyph_box.id] = glyph_box
            native_id = _stable_id(
                "ev",
                working.id,
                source_evidence_id,
                "native",
            )
            recovered_id = _stable_id(
                "ev",
                working.id,
                source_evidence_id,
                "recovered",
            )
            shared_metadata = {
                "source_sha256": report_source_sha256,
                "font_ref": raw_glyph.get("font_ref"),
                "font_object_id": raw_glyph.get("font_object_id"),
                "page_index": raw_glyph.get("page_index"),
                "run_index": raw_glyph.get("run_index"),
                "glyph_index": raw_glyph.get("glyph_index"),
                "cid": raw_glyph.get("cid"),
                "glyph_id": raw_glyph.get("glyph_id"),
                "unicode_code_point": raw_glyph.get("unicode_code_point"),
                "page_advance": raw_glyph.get("page_advance"),
                "pdf_width_em": raw_glyph.get("pdf_width_em"),
                "embedded_advance_width": raw_glyph.get("embedded_advance_width"),
                "units_per_em": raw_glyph.get("units_per_em"),
                "width_delta_em": raw_glyph.get("width_delta_em"),
                "method": raw_glyph.get("method"),
            }
            confidence = ConfidenceRecord(
                scope="evidence",
                unavailable_reason=("deterministic_font_rule_not_probability"),
            )
            working.evidence.append(
                EvidenceRecord(
                    id=native_id,
                    element_id=element.id,
                    method=EvidenceMethod.NATIVE,
                    bbox_id=glyph_box.id,
                    value=raw_glyph.get("original_text"),
                    confidence=confidence,
                    metadata={
                        **shared_metadata,
                        "alternative_role": "original",
                    },
                )
            )
            working.evidence.append(
                EvidenceRecord(
                    id=recovered_id,
                    element_id=element.id,
                    method=EvidenceMethod.RECOVERED,
                    bbox_id=glyph_box.id,
                    value=raw_glyph.get("recovered_text"),
                    confidence=confidence.model_copy(deep=True),
                    metadata={
                        **shared_metadata,
                        "alternative_role": "recovered",
                        "original_evidence_id": native_id,
                    },
                )
            )
            element.evidence_ids.extend((native_id, recovered_id))
            recovered_ids.append(recovered_id)
        return recovered_ids

    raw_runs = payload.get("runs") or []
    for raw_run in raw_runs:
        if not isinstance(raw_run, Mapping):
            continue
        try:
            page = pages_by_index[int(raw_run["page_index"])]
        except (KeyError, TypeError, ValueError):
            continue
        owner = owner_for_run(raw_run)
        selected = False
        legacy_item: dict[str, Any] | None = None
        if owner is not None:
            raw_legacy = owner.properties.get("legacy_item")
            if isinstance(raw_legacy, Mapping):
                legacy_item = deepcopy(dict(raw_legacy))
                is_native_prose = str(
                    legacy_item.get("source") or ""
                ) == "native" and owner.type.casefold() not in {
                    "chart",
                    "diagram",
                    "image",
                    "table",
                }
                if is_native_prose:
                    replacements: dict[str, str] = {}
                    for field_name, raw_value in (
                        ("value", owner.value),
                        ("markdown", owner.markdown),
                        ("legacy_value", legacy_item.get("value")),
                        ("legacy_text", legacy_item.get("text")),
                        ("legacy_md", legacy_item.get("md")),
                    ):
                        if not isinstance(raw_value, str):
                            continue
                        replacement = _recovery_text_replacement(
                            raw_value,
                            original=str(raw_run.get("original_text") or ""),
                            recovered=str(raw_run.get("recovered_text") or ""),
                        )
                        if replacement is not None:
                            replacements[field_name] = replacement
                    if "value" in replacements or "markdown" in replacements:
                        if "value" in replacements:
                            owner.value = replacements["value"]
                        if "markdown" in replacements:
                            owner.markdown = replacements["markdown"]
                        if "legacy_value" in replacements:
                            legacy_item["value"] = replacements["legacy_value"]
                        if "legacy_text" in replacements:
                            legacy_item["text"] = replacements["legacy_text"]
                        if "legacy_md" in replacements:
                            legacy_item["md"] = replacements["legacy_md"]
                        selected = True

        evidence_element = (
            owner
            if selected and owner is not None
            else append_alternative_element(
                raw_run=raw_run,
                owner=owner,
                page=page,
            )
        )
        recovered_ids = attach_glyph_evidence(
            raw_run=raw_run,
            element=evidence_element,
            page=page,
        )
        summary = {
            "source_sha256": report_source_sha256,
            "run_evidence_id": raw_run.get("evidence_id"),
            "font_ref": raw_run.get("font_ref"),
            "font_object_id": raw_run.get("font_object_id"),
            "bbox": deepcopy(raw_run.get("bbox")),
            "original_text": raw_run.get("original_text"),
            "recovered_text": raw_run.get("recovered_text"),
            "method": raw_run.get("method"),
            "selected": selected,
            "glyph_evidence_ids": recovered_ids,
        }
        if owner is not None and legacy_item is not None:
            if "font_recovery_original_value" not in legacy_item:
                legacy_item["font_recovery_original_value"] = deepcopy(
                    owner.properties.get("legacy_item", {}).get("value")
                    if isinstance(
                        owner.properties.get("legacy_item"),
                        Mapping,
                    )
                    else None
                )
            alternatives = legacy_item.get("font_recovery_alternatives")
            if not isinstance(alternatives, list):
                alternatives = []
            alternatives.append(summary)
            legacy_item["font_recovery_alternatives"] = alternatives
            owner.properties["legacy_item"] = legacy_item
        working.concerns.append(
            IRConcern(
                code=(
                    "pdf_font_text_recovered"
                    if selected
                    else "pdf_font_recovery_alternative"
                ),
                message=(
                    "Deterministic embedded-font recovery selected for "
                    "uniquely owned native text."
                    if selected
                    else (
                        "Deterministic embedded-font recovery retained as "
                        "an unselected alternative."
                    )
                ),
                source_ref=f"pdf-font-{raw_run.get('font_ref')}",
                target_ref=(owner.id if owner is not None else evidence_element.id),
                metadata=summary,
            )
        )

    for raw_refusal in payload.get("refusals") or []:
        if not isinstance(raw_refusal, Mapping):
            continue
        target_page_id = None
        for page_index in raw_refusal.get("page_indexes") or []:
            try:
                page = pages_by_index.get(int(page_index))
            except (TypeError, ValueError):
                continue
            if page is not None:
                target_page_id = page.id
                break
        working.concerns.append(
            IRConcern(
                code="pdf_font_recovery_unresolved",
                message=(
                    "PDF font recovery was refused: "
                    + str(raw_refusal.get("reason_code") or "unknown")
                ),
                source_ref=(
                    f"pdf-font-{raw_refusal.get('font_ref')}"
                    if raw_refusal.get("font_ref")
                    else None
                ),
                target_ref=target_page_id,
                metadata={"refusal": deepcopy(dict(raw_refusal))},
            )
        )

    if payload.get("status") in {"partial", "unavailable"}:
        working.concerns.append(
            IRConcern(
                code=f"pdf_font_recovery_{payload.get('status')}",
                message=("PDF font recovery did not complete for all bounded work."),
                metadata={
                    "font_recovery_schema_version": payload.get("schema_version"),
                    "diagnostics": deepcopy(
                        list(payload.get("diagnostics") or [])[:20]
                    ),
                },
            )
        )

    return DocumentIR.model_validate(working.model_dump(mode="json"))


def _attach_selective_span_ocr(
    ir: DocumentIR,
    report: Mapping[str, Any],
) -> DocumentIR:
    """Retain selective OCR as unselected evidence without changing prose."""

    from app.services.selective_span_ocr import (
        MAX_SELECTIVE_CONCERNS,
        SelectiveSpanOCRReport,
    )

    validated = SelectiveSpanOCRReport.model_validate(dict(report))
    payload = validated.model_dump(mode="json", exclude_none=True)
    if payload.get("source_sha256") != ir.source_sha256:
        working = ir.model_copy(deep=True)
        working.concerns.append(
            IRConcern(
                code="selective_ocr_source_mismatch",
                message=(
                    "Selective OCR evidence was refused because its source "
                    "identity does not match the document."
                ),
            )
        )
        return DocumentIR.model_validate(working.model_dump(mode="json"))
    if not payload.get("outcomes") and not payload.get("concerns"):
        return ir

    working = ir.model_copy(deep=True)
    selective_concern_count = 0
    selective_concerns_truncated = False

    def append_selective_concern(concern: IRConcern) -> None:
        nonlocal selective_concern_count, selective_concerns_truncated
        if selective_concern_count >= MAX_SELECTIVE_CONCERNS - 1:
            selective_concerns_truncated = True
            return
        working.concerns.append(concern)
        selective_concern_count += 1

    pages_by_index = {page.page_index: page for page in working.pages}
    elements_by_id = {element.id: element for element in working.elements}
    boxes_by_id = {box.id: box for box in working.bboxes}
    coordinates_by_id = {
        coordinate.id: coordinate for coordinate in working.coordinate_systems
    }

    def element_page_box(
        element: ElementRecord,
    ) -> tuple[float, float, float, float] | None:
        if not element.bbox_ids:
            return None
        box = boxes_by_id.get(element.bbox_ids[0])
        if box is None:
            return None
        coordinate = coordinates_by_id.get(box.coordinate_system_id)
        if coordinate is None:
            return None
        return _page_box_coordinates(box, coordinate)

    def owner_for_outcome(
        raw_outcome: Mapping[str, Any],
        page: PageRecord,
    ) -> ElementRecord | None:
        raw_box = raw_outcome.get("source_bbox")
        if not isinstance(raw_box, Mapping):
            return None
        try:
            run_box = (
                float(raw_box["x"]),
                float(raw_box["y"]),
                float(raw_box.get("width", raw_box.get("w"))),
                float(raw_box.get("height", raw_box.get("h"))),
            )
        except (KeyError, TypeError, ValueError):
            return None
        matches: list[tuple[float, ElementRecord]] = []
        for element_id in page.presentation_element_ids:
            element = elements_by_id[element_id]
            overlap = _box_overlap_of_smaller(
                run_box,
                element_page_box(element),
            )
            if overlap >= 0.8:
                matches.append((overlap, element))
        if not matches:
            return None
        matches.sort(key=lambda entry: (-entry[0], entry[1].id))
        best_overlap = matches[0][0]
        best = [
            element
            for overlap, element in matches
            if abs(overlap - best_overlap) <= 1e-9
        ]
        return best[0] if len(best) == 1 else None

    for raw_outcome in payload.get("outcomes") or []:
        if not isinstance(raw_outcome, Mapping):
            continue
        try:
            page = pages_by_index[int(raw_outcome["page_index"])]
        except (KeyError, TypeError, ValueError):
            continue
        span_id = str(raw_outcome.get("span_id") or "")
        owner = owner_for_outcome(raw_outcome, page)
        cost = raw_outcome.get("cost")
        selective_outcome_id = _stable_id(
            "selective-outcome",
            working.id,
            span_id,
            raw_outcome.get("page_index"),
            raw_outcome.get("font_ref"),
            raw_outcome.get("audit_run_index"),
        )
        lineage = {
            "source_sha256": payload.get("source_sha256"),
            "audit_source_sha256": payload.get("source_sha256"),
            "recovery_source_sha256": payload.get("source_sha256"),
            "selective_ocr_source_sha256": payload.get("source_sha256"),
            "audit_finding_id": _stable_id(
                "audit-finding",
                working.id,
                raw_outcome.get("font_ref"),
                raw_outcome.get("audit_run_index"),
            ),
            "audit_run_index": raw_outcome.get("audit_run_index"),
            "font_ref": raw_outcome.get("font_ref"),
            "font_object_id": raw_outcome.get("font_object_id"),
            "selective_span_id": span_id,
            "selective_outcome_id": selective_outcome_id,
            "recovery_refusal_reason_code": raw_outcome.get("refusal_reason_code"),
            "status": raw_outcome.get("status"),
            "source_bbox": deepcopy(raw_outcome.get("source_bbox")),
            "attempt": deepcopy(raw_outcome.get("attempt")),
        }
        crop_region: RegionRecord | None = None
        if isinstance(cost, Mapping):
            try:
                transform = tuple(
                    float(value) for value in cost["crop_to_page_transform"]
                )
                pixel_width = float(cost["pixel_width"])
                pixel_height = float(cost["pixel_height"])
            except (KeyError, OverflowError, TypeError, ValueError):
                transform = ()
                pixel_width = 0
                pixel_height = 0
            if len(transform) == 6 and pixel_width > 0 and pixel_height > 0:
                crop_coordinate_id = _stable_id(
                    "coord",
                    working.id,
                    span_id,
                    "selective_ocr_crop",
                )
                crop_coordinate = CoordinateSystem(
                    id=crop_coordinate_id,
                    page_id=page.id,
                    unit="px",
                    origin="top_left",
                    transform_to_page=transform,
                )
                working.coordinate_systems.append(crop_coordinate)
                coordinates_by_id[crop_coordinate.id] = crop_coordinate
                crop_box = IRBoundingBox(
                    id=_stable_id("box", span_id, "selective_ocr_crop"),
                    coordinate_system_id=crop_coordinate.id,
                    x=0.0,
                    y=0.0,
                    width=pixel_width,
                    height=pixel_height,
                    role="region",
                )
                working.bboxes.append(crop_box)
                boxes_by_id[crop_box.id] = crop_box
                crop_region = RegionRecord(
                    id=_stable_id("region", span_id, "selective_ocr_crop"),
                    page_id=page.id,
                    role="selective_ocr_crop",
                    bbox_id=crop_box.id,
                    element_ids=[],
                )
                working.regions.append(crop_region)
                page.region_ids.append(crop_region.id)

        legacy_summaries: list[dict[str, Any]] = []
        for raw_candidate in raw_outcome.get("candidates") or []:
            if not isinstance(raw_candidate, Mapping):
                continue
            candidate_source_id = str(raw_candidate.get("evidence_id") or "")
            candidate_id = _stable_id(
                "el",
                working.id,
                candidate_source_id,
                "selective_ocr_candidate",
            )
            candidate_box = _normalized_box(
                raw_candidate.get("bbox"),
                coordinate_system_id=page.coordinate_system_id,
                role="annotation",
                identity_parts=(candidate_id, "selective_ocr"),
            )
            bbox_ids: list[str] = []
            if candidate_box is not None:
                working.bboxes.append(candidate_box)
                boxes_by_id[candidate_box.id] = candidate_box
                bbox_ids.append(candidate_box.id)
            candidate = ElementRecord(
                id=candidate_id,
                page_id=page.id,
                type="ocr_candidate",
                value=raw_candidate.get("text"),
                markdown=raw_candidate.get("text"),
                bbox_ids=bbox_ids,
                presentation_role="alternate",
                presentation=ElementPresentationDirective(accepted=True),
                properties={
                    "selective_span_ocr": {
                        **deepcopy(lineage),
                        "span_id": span_id,
                        "selected": False,
                        "method": raw_candidate.get("method"),
                        "ocr_pass": raw_candidate.get("ocr_pass"),
                        "word_count": raw_candidate.get("word_count"),
                        "cost": deepcopy(cost),
                        "owner_element_id": (owner.id if owner is not None else None),
                    }
                },
            )
            evidence_id = _stable_id(
                "ev",
                working.id,
                candidate_source_id,
                "selective_ocr",
            )
            working.evidence.append(
                EvidenceRecord(
                    id=evidence_id,
                    element_id=candidate.id,
                    method=EvidenceMethod.OCR,
                    bbox_id=(candidate_box.id if candidate_box is not None else None),
                    value=raw_candidate.get("text"),
                    confidence=_confidence(raw_candidate.get("confidence")),
                    metadata={
                        **deepcopy(lineage),
                        "span_id": span_id,
                        "ocr_pass": raw_candidate.get("ocr_pass"),
                        "word_count": raw_candidate.get("word_count"),
                        "method": raw_candidate.get("method"),
                        "crop_pixel_bbox": deepcopy(
                            raw_candidate.get("crop_pixel_bbox")
                        ),
                        "tokens": deepcopy(
                            list(raw_candidate.get("tokens") or [])[:2048]
                        ),
                        "cost": deepcopy(cost),
                        "selected": False,
                    },
                )
            )
            candidate.evidence_ids.append(evidence_id)
            working.elements.append(candidate)
            elements_by_id[candidate.id] = candidate
            page.element_ids.append(candidate.id)
            if crop_region is not None:
                crop_region.element_ids.append(candidate.id)
            if owner is not None:
                working.relationships.append(
                    RelationshipRecord(
                        id=_stable_id(
                            "rel",
                            RelationshipType.ALTERNATIVE_OF.value,
                            candidate.id,
                            owner.id,
                            span_id,
                        ),
                        type=RelationshipType.ALTERNATIVE_OF,
                        source_id=candidate.id,
                        target_id=owner.id,
                        evidence_ids=[evidence_id],
                        metadata={
                            "selected": False,
                            "method": raw_candidate.get("method"),
                            "canonical_presentation_inert": True,
                        },
                    )
                )
            summary = {
                "evidence_id": candidate_source_id,
                "span_id": span_id,
                "text": raw_candidate.get("text"),
                "bbox": deepcopy(raw_candidate.get("bbox")),
                "confidence": raw_candidate.get("confidence"),
                "ocr_pass": raw_candidate.get("ocr_pass"),
                "method": raw_candidate.get("method"),
                "selected": False,
                "tokens": deepcopy(list(raw_candidate.get("tokens") or [])[:2048]),
                "cost": deepcopy(cost),
            }
            legacy_summaries.append(summary)
            append_selective_concern(
                IRConcern(
                    code="pdf_selective_ocr_alternative",
                    message=(
                        "Selective OCR candidate retained as an unselected "
                        "alternative pending text reconciliation."
                    ),
                    source_ref=span_id,
                    target_ref=(owner.id if owner is not None else candidate.id),
                    metadata={
                        "evidence_id": candidate_source_id,
                        "candidate_element_id": candidate.id,
                        "span_id": span_id,
                        "selected": False,
                    },
                )
            )

        if owner is not None and legacy_summaries:
            legacy_item = owner.properties.get("legacy_item")
            if isinstance(legacy_item, Mapping):
                updated = deepcopy(dict(legacy_item))
                existing = updated.get("selective_ocr_candidates")
                if not isinstance(existing, list):
                    existing = []
                existing.extend(legacy_summaries)
                updated["selective_ocr_candidates"] = existing
                owner.properties["legacy_item"] = updated

        if not raw_outcome.get("candidates"):
            append_selective_concern(
                IRConcern(
                    code=(
                        "pdf_selective_ocr_"
                        + str(
                            raw_outcome.get("reason_code")
                            or raw_outcome.get("status")
                            or "unresolved"
                        )
                    ),
                    message=(
                        str(raw_outcome.get("reason_message") or "")
                        or "Selective OCR retained no candidate."
                    ),
                    source_ref=span_id,
                    target_ref=owner.id if owner is not None else page.id,
                    metadata={"outcome": deepcopy(dict(raw_outcome))},
                )
            )

    for raw_concern in payload.get("concerns") or []:
        if not isinstance(raw_concern, Mapping):
            continue
        append_selective_concern(
            IRConcern(
                code="pdf_selective_ocr_"
                + str(raw_concern.get("code") or "unresolved"),
                message=str(raw_concern.get("message") or "Selective OCR concern."),
                source_ref=(
                    str(raw_concern.get("span_id"))
                    if raw_concern.get("span_id")
                    else None
                ),
                metadata={"selective_ocr": deepcopy(dict(raw_concern))},
            )
        )

    if selective_concerns_truncated:
        working.concerns.append(
            IRConcern(
                code="pdf_selective_ocr_diagnostics_truncated",
                message=(
                    "Selective OCR concerns exceeded the retained diagnostic "
                    "bound; candidate evidence remains available by identity."
                ),
                metadata={
                    "retained_selective_concern_count": (selective_concern_count),
                    "selective_concern_limit": MAX_SELECTIVE_CONCERNS,
                },
            )
        )

    return DocumentIR.model_validate(working.model_dump(mode="json"))


_RAW_GRAPH_COLLECTIONS = (
    "groups",
    "texts",
    "pictures",
    "tables",
    "key_value_items",
    "form_items",
    "field_regions",
    "field_items",
)

_RAW_TABLE_CANDIDATE_SOURCE_OBJECT_LIMIT = 4_096
_RAW_TABLE_CANDIDATE_BBOX_EPSILON_PT = 0.1
_ANNOTATION_BACKED_TABLE_NOTE_PARTITION_POLICY = (
    "annotation_backed_cross_page_table_note_partition_v1"
)
_ANNOTATION_BACKED_VISUAL_NOTE_PARTITION_POLICY = (
    "annotation_backed_cross_page_visual_note_partition_v1"
)
_ANNOTATION_BACKED_OWNER_MAX_GAP_PT = 72.0
_ANNOTATION_BACKED_SOURCE_NOTE_MAX_CODEPOINTS = 16_384
_ANNOTATION_BACKED_SOURCE_NOTE_MAX_RAW_REFERENCES = 512
_RAW_TABLE_GRID_MAX_ROWS = 4_096
_RAW_TABLE_GRID_MAX_COLUMNS = 256
_RAW_TABLE_GRID_MAX_SLOTS = 65_536
_RAW_TABLE_GRID_MIN_COVERAGE_NUMERATOR = 3
_RAW_TABLE_GRID_MIN_COVERAGE_DENOMINATOR = 4


def _validated_raw_table_grid_topology(
    raw_item: Mapping[str, Any],
) -> tuple[int, int, int, int] | None:
    """Return one bounded, nonoverlapping Docling grid topology.

    A cell may span multiple slots, so cell-count equality is insufficient.
    Offset rectangles must be valid and mutually disjoint.  Sparse grids are
    admitted only at the established P04 75% support floor; exact public-gate
    coverage and source authority are checked separately at the claiming
    candidate seam.  The cumulative-area guard bounds occupancy work by the
    maximum slot count even for adversarial overlapping rectangles.
    """

    data = raw_item.get("data")
    if not isinstance(data, Mapping):
        return None
    rows = data.get("num_rows")
    columns = data.get("num_cols")
    cells = data.get("table_cells")
    if (
        type(rows) is not int
        or type(columns) is not int
        or not 1 <= rows <= _RAW_TABLE_GRID_MAX_ROWS
        or not 1 <= columns <= _RAW_TABLE_GRID_MAX_COLUMNS
        or rows * columns > _RAW_TABLE_GRID_MAX_SLOTS
        or type(cells) is not list
        or not cells
        or len(cells) > rows * columns
    ):
        return None

    slot_count = rows * columns
    occupied = bytearray(slot_count)
    covered_count = 0
    for cell in cells:
        if not isinstance(cell, Mapping) or not isinstance(cell.get("text"), str):
            return None
        start_row = cell.get("start_row_offset_idx")
        end_row = cell.get("end_row_offset_idx")
        start_column = cell.get("start_col_offset_idx")
        end_column = cell.get("end_col_offset_idx")
        if (
            type(start_row) is not int
            or type(end_row) is not int
            or type(start_column) is not int
            or type(end_column) is not int
            or not 0 <= start_row < end_row <= rows
            or not 0 <= start_column < end_column <= columns
        ):
            return None
        row_span = end_row - start_row
        column_span = end_column - start_column
        if "row_span" in cell and (
            type(cell.get("row_span")) is not int
            or cell.get("row_span") != row_span
        ):
            return None
        if "col_span" in cell and (
            type(cell.get("col_span")) is not int
            or cell.get("col_span") != column_span
        ):
            return None
        cell_area = row_span * column_span
        covered_count += cell_area
        if covered_count > slot_count:
            return None
        for row in range(start_row, end_row):
            row_offset = row * columns
            for column in range(start_column, end_column):
                slot_index = row_offset + column
                if occupied[slot_index]:
                    return None
                occupied[slot_index] = 1
    if (
        covered_count * _RAW_TABLE_GRID_MIN_COVERAGE_DENOMINATOR
        < slot_count * _RAW_TABLE_GRID_MIN_COVERAGE_NUMERATOR
    ):
        return None
    return rows, columns, covered_count, slot_count


def _raw_table_grid_coverage_matches_gate(
    topology: tuple[int, int, int, int],
    gate: Any,
) -> bool:
    if type(gate) is not dict:
        return False
    feature_scores = gate.get("feature_scores")
    if type(feature_scores) is not dict:
        return False
    cell_coverage = feature_scores.get("cell_coverage")
    if (
        type(cell_coverage) not in {int, float}
        or type(cell_coverage) is bool
        or not 0.0 <= cell_coverage <= 1.0
        or not math.isfinite(cell_coverage)
    ):
        return False
    _rows, _columns, covered_slots, total_slots = topology
    expected = round(covered_slots / total_slots, 6)
    return cell_coverage == expected


def _validated_raw_docling_grid_source_identity(
    raw_item: Mapping[str, Any],
    source_sha256: str,
    *,
    topology: tuple[int, int, int, int] | None = None,
) -> tuple[str, str] | None:
    """Replay the bounded P04 identity for one current Docling raw grid."""

    raw_grid_topology = (
        topology
        if topology is not None
        else _validated_raw_table_grid_topology(raw_item)
    )
    if raw_grid_topology is None:
        return None
    try:
        from app.services.table_semantics import (
            _canonical_table_sha256,
            _canonical_table_sha256_and_size,
            _docling_table_page,
            _normalized_docling_cells,
            _resolve_table_page_deadline,
            _table_required_reference,
            _table_structure_source_content,
        )

        deadline = _resolve_table_page_deadline(None)
        page_index = _docling_table_page(raw_item, deadline)
        table_reference = _table_required_reference(
            raw_item.get("self_ref"),
            deadline,
        )
        records = _normalized_docling_cells(raw_item, deadline)
        row_count, column_count, _covered_slots, _total_slots = (
            raw_grid_topology
        )
        structure_content = _table_structure_source_content(
            table_reference,
            row_count,
            column_count,
            records,
            deadline,
        )
        content_sha256, _content_size = _canonical_table_sha256_and_size(
            structure_content,
            67_108_864,
            deadline,
        )
        source_id = _canonical_table_sha256(
            [
                "p04-structure-source-id-v1",
                source_sha256,
                page_index,
                "docling",
                table_reference,
                row_count,
                column_count,
            ],
            8_388_608,
            deadline,
        )
    except (
        AttributeError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
        TimeoutError,
    ):
        return None
    return source_id, content_sha256


_RAW_RELATION_FIELDS: dict[str, tuple[RelationshipType, bool]] = {
    "children": (RelationshipType.CONTAINS, False),
    "captions": (RelationshipType.CAPTION_OF, True),
    "caption": (RelationshipType.CAPTION_OF, True),
    "source_notes": (RelationshipType.SOURCE_NOTE_OF, True),
    "source_note": (RelationshipType.SOURCE_NOTE_OF, True),
    "footnotes": (RelationshipType.FOOTNOTE_OF, True),
    "footnote": (RelationshipType.FOOTNOTE_OF, True),
    "legends": (RelationshipType.LEGEND_OF, True),
    "legend": (RelationshipType.LEGEND_OF, True),
    "axes": (RelationshipType.AXIS_OF, True),
    "axis": (RelationshipType.AXIS_OF, True),
    "alternatives": (RelationshipType.ALTERNATIVE_OF, True),
    "alternative": (RelationshipType.ALTERNATIVE_OF, True),
    "annotations": (RelationshipType.ANNOTATION_OF, True),
    "comments": (RelationshipType.ANNOTATION_OF, True),
    "references": (RelationshipType.REFERENCES, False),
}


def _raw_reference(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return str(value.get("$ref") or value.get("cref") or "").strip()


def _raw_reference_values(value: Any) -> list[str]:
    return [reference for reference, _metadata in _raw_reference_entries(value)]


def _raw_reference_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _raw_reference_entries(
    value: Any,
) -> list[tuple[str, dict[str, Any]]]:
    output: list[tuple[str, dict[str, Any]]] = []
    for item in _raw_reference_items(value):
        reference = _raw_reference(item)
        if not reference:
            continue
        metadata: dict[str, Any] = {}
        if isinstance(item, Mapping) and item.get("range") is not None:
            metadata["range"] = deepcopy(item.get("range"))
        output.append((reference, metadata))
    return output


def _nested_raw_reference_entries(
    raw_item: Mapping[str, Any],
) -> Iterable[
    tuple[
        str,
        RelationshipType,
        bool,
        str,
        dict[str, Any],
    ]
]:
    def table_data_entries(
        data: Any,
        *,
        path_prefix: str,
    ) -> Iterable[
        tuple[
            str,
            RelationshipType,
            bool,
            str,
            dict[str, Any],
        ]
    ]:
        if not isinstance(data, Mapping):
            return
        table_cells = data.get("table_cells") or []
        if not isinstance(table_cells, Sequence) or isinstance(
            table_cells, (str, bytes, bytearray)
        ):
            return
        for index, cell in enumerate(table_cells):
            if not isinstance(cell, Mapping):
                continue
            for reference, reference_metadata in _raw_reference_entries(
                cell.get("ref")
            ):
                yield (
                    reference,
                    RelationshipType.CONTAINS,
                    False,
                    f"{path_prefix}.table_cells[{index}].ref",
                    {
                        "cell_index": index,
                        "start_row_offset_idx": cell.get("start_row_offset_idx"),
                        "end_row_offset_idx": cell.get("end_row_offset_idx"),
                        "start_col_offset_idx": cell.get("start_col_offset_idx"),
                        "end_col_offset_idx": cell.get("end_col_offset_idx"),
                        **reference_metadata,
                    },
                )

    graph = raw_item.get("graph")
    if isinstance(graph, Mapping):
        cells = graph.get("cells") or []
        if isinstance(cells, Sequence) and not isinstance(
            cells, (str, bytes, bytearray)
        ):
            for index, cell in enumerate(cells):
                if not isinstance(cell, Mapping):
                    continue
                for reference, reference_metadata in _raw_reference_entries(
                    cell.get("item_ref")
                ):
                    yield (
                        reference,
                        RelationshipType.CONTAINS,
                        False,
                        f"graph.cells[{index}].item_ref",
                        {
                            "cell_index": index,
                            "cell_id": cell.get("cell_id"),
                            "cell_label": cell.get("label"),
                            **reference_metadata,
                        },
                    )

    yield from table_data_entries(
        raw_item.get("data"),
        path_prefix="data",
    )

    annotations = raw_item.get("annotations") or []
    if isinstance(annotations, Sequence) and not isinstance(
        annotations, (str, bytes, bytearray)
    ):
        for index, annotation in enumerate(annotations):
            if not isinstance(annotation, Mapping):
                continue
            yield from table_data_entries(
                annotation.get("chart_data"),
                path_prefix=f"annotations[{index}].chart_data",
            )

    meta = raw_item.get("meta")
    if isinstance(meta, Mapping):
        tabular_chart = meta.get("tabular_chart")
        if isinstance(tabular_chart, Mapping):
            yield from table_data_entries(
                tabular_chart.get("chart_data"),
                path_prefix="meta.tabular_chart.chart_data",
            )


def _raw_reference_map(
    raw_graph: Mapping[str, Any],
) -> tuple[
    dict[str, Mapping[str, Any]],
    list[tuple[str, str, int]],
]:
    references: dict[str, Mapping[str, Any]] = {}
    duplicate_definitions: list[tuple[str, str, int]] = []
    for collection in _RAW_GRAPH_COLLECTIONS:
        values = raw_graph.get(collection) or []
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            continue
        for index, value in enumerate(values):
            if not isinstance(value, Mapping):
                continue
            reference = str(value.get("self_ref") or "").strip()
            if reference:
                if reference in references:
                    duplicate_definitions.append((reference, collection, index))
                    continue
                references[reference] = value
    return references, duplicate_definitions


def _normalized_text(value: Any) -> str:
    casefolded = str(value or "").casefold()
    return " ".join(
        "".join(
            character if character.isalnum() else " " for character in casefolded
        ).split()
    )


def _raw_value(raw_item: Mapping[str, Any]) -> Any:
    for key in ("text", "orig", "value"):
        if raw_item.get(key) not in (None, ""):
            return raw_item.get(key)
    # ``label`` is a structural Docling class (picture, table, group, ...),
    # not extracted content. Treating it as text creates false OCR evidence.
    return None


def _raw_page_index(raw_item: Mapping[str, Any]) -> int | None:
    provenance = raw_item.get("prov") or []
    if not isinstance(provenance, Sequence) or isinstance(provenance, (str, bytes)):
        return None
    for record in provenance:
        if not isinstance(record, Mapping):
            continue
        try:
            return int(record.get("page_no"))
        except (TypeError, ValueError):
            continue
    return None


def _page_box_coordinates(
    box: IRBoundingBox,
    coordinate: CoordinateSystem,
) -> tuple[float, float, float, float] | None:
    transform = coordinate.transform_to_page
    if transform is None:
        return None
    a, b, c, d, e, f = transform
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


def _box_overlap_of_smaller(
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
    smaller = min(
        max(first_width, 0.0) * max(first_height, 0.0),
        max(second_width, 0.0) * max(second_height, 0.0),
    )
    return intersection / smaller if smaller else 0.0


def _raw_element_type(raw_item: Mapping[str, Any], reference: str) -> str:
    label = str(raw_item.get("label") or "").casefold()
    if reference.startswith("#/field_regions/") or label == "field_region":
        return "field_region"
    if reference.startswith("#/field_items/") or label == "field_item":
        return "field"
    if label in {"code", "formula"}:
        return label
    if label in {
        "caption",
        "source_note",
        "footnote",
        "legend",
        "axis",
        "alternative",
        "annotation",
        "page_header",
        "page_footer",
    }:
        return {
            "page_header": "header",
            "page_footer": "footer",
        }.get(label, label)
    if reference.startswith("#/tables/") or label == "table":
        return "table"
    if reference.startswith("#/pictures/") or label in {
        "picture",
        "chart",
        "diagram",
    }:
        return "image" if label == "picture" else label
    if reference.startswith("#/groups/"):
        return "list" if "list" in label else "group"
    if reference.startswith("#/form_items/"):
        return "form"
    if reference.startswith("#/key_value_items/"):
        return "key_value"
    if label in {"section_header", "title"}:
        return "heading"
    if label in {"field_heading", "field_value"}:
        # The current legacy adapter emits these TextItem subclasses as text.
        # Preserve the richer raw label in properties without duplicating the
        # canonical element solely because the adapters name the type
        # differently.
        return "text"
    return "text"


def _compatible_raw_type(raw_type: str, element_type: str) -> bool:
    if raw_type in {"image", "chart", "diagram"}:
        return element_type in {"image", "chart", "diagram"}
    if raw_type == "text":
        return element_type.endswith("_cell") or element_type in {
            "text",
            "heading",
            "header",
            "footer",
            "caption",
            "source_note",
            "footnote",
            "list_child",
            "image_child",
            "chart_child",
            "diagram_child",
        }
    if raw_type == "field":
        return element_type == "field" or element_type.endswith("_field")
    if raw_type in {
        "caption",
        "source_note",
        "footnote",
        "legend",
        "axis",
        "alternative",
        "annotation",
    }:
        return element_type in {raw_type, "text"}
    return raw_type == element_type


def _normalize_raw_reference_graph(
    ir: DocumentIR,
    raw_graph: Mapping[str, Any],
    *,
    native_texts: Sequence[str],
) -> DocumentIR:
    """Retain raw Docling references without changing primary presentation."""

    working = ir.model_copy(deep=True)
    references, duplicate_definitions = _raw_reference_map(raw_graph)
    root_containers: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for container_name in ("body", "furniture"):
        container = raw_graph.get(container_name)
        if not isinstance(container, Mapping):
            continue
        container_ref = str(container.get("self_ref") or f"#/{container_name}").strip()
        root_containers[container_ref] = (container_name, container)
    pages_by_index = {page.page_index: page for page in working.pages}
    pages_by_id = {page.id: page for page in working.pages}
    elements = {element.id: element for element in working.elements}
    evidence = {record.id: record for record in working.evidence}
    boxes = {box.id: box for box in working.bboxes}
    coordinates = {
        coordinate.id: coordinate for coordinate in working.coordinate_systems
    }
    regions = {region.id: region for region in working.regions}
    page_region = {
        page.id: regions[page.region_ids[0]]
        for page in working.pages
        if page.region_ids
    }
    page_heights = {
        page.id: boxes[page_region[page.id].bbox_id].height
        for page in working.pages
        if page.id in page_region
    }
    # Match only against the fixed legacy/base graph. Raw nodes appended during
    # normalization are not candidates for another self_ref, and excluding
    # them keeps traversal linear in the number of raw nodes when the legacy
    # page contains few matching elements.
    match_candidates_by_page_id = {
        page.id: tuple(page.element_ids) for page in working.pages
    }
    ref_to_element: dict[str, str] = {}
    claimed_element_ids: set[str] = set()
    table_candidate_authority_by_element_id: dict[str, bool] = {}

    def concern(
        code: str,
        message: str,
        *,
        source_ref: str | None = None,
        target_ref: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        working.concerns.append(
            IRConcern(
                code=code,
                message=message,
                source_ref=source_ref,
                target_ref=target_ref,
                metadata=dict(metadata or {}),
            )
        )

    def table_candidate_has_valid_authority(
        element: ElementRecord,
        legacy: Mapping[str, Any],
    ) -> bool:
        """Replay one candidate's P04 evidence before it may own raw edges.

        Candidate eligibility is a presentation decision, not source
        authority.  Reusing the table-semantic validator after an isolated
        candidate-to-table projection proves the sidecar's hashes, custody,
        topology, and source-document binding.  Cache by stable IR element ID
        because a malformed candidate may claim more than one raw reference.
        """

        cached = table_candidate_authority_by_element_id.get(element.id)
        if cached is not None:
            return cached
        is_valid = False
        try:
            candidate_view = deepcopy(dict(legacy))
            conflicting_table_evidence = "table_evidence" in candidate_view
            private_p04_state = any(
                type(key) is str and key.startswith("_p04_")
                for key in candidate_view
            )
            candidate_evidence = candidate_view.pop(
                "candidate_table_evidence",
                None,
            )
            candidate_gate = candidate_view.pop(
                "table_candidate_gate",
                None,
            )
            candidate_gate_reasons = candidate_view.pop(
                "table_candidate_gate_reasons",
                None,
            )
            candidate_gate_sources = candidate_view.pop(
                "table_candidate_gate_sources",
                None,
            )
            gate_concerns = (
                candidate_gate.get("concern_codes")
                if type(candidate_gate) is dict
                else None
            )
            sidecar_concerns = (
                candidate_evidence.get("concerns")
                if type(candidate_evidence) is dict
                else None
            )
            if (
                conflicting_table_evidence
                or private_p04_state
                or type(candidate_evidence) is not dict
                or candidate_evidence.get("gate") is not None
                or candidate_evidence.get("scope")
                != ["P04-US01", "P04-US02"]
                or candidate_gate_reasons
                != ["upstream_reconciliation_unresolved"]
                or candidate_gate_sources != []
                or type(gate_concerns) is not list
                or len(gate_concerns) > 64
                or any(type(value) is not str for value in gate_concerns)
                or type(sidecar_concerns) is not list
                or len(sidecar_concerns) > 64
                or any(type(value) is not str for value in sidecar_concerns)
            ):
                table_candidate_authority_by_element_id[element.id] = False
                return False
            candidate_evidence["scope"] = [
                "P04-US01",
                "P04-US02",
                "P04-US04",
            ]
            candidate_evidence["gate"] = candidate_gate
            candidate_evidence["concerns"] = sorted(
                set(sidecar_concerns) | set(gate_concerns)
            )
            candidate_view["type"] = "table"
            candidate_view["table_evidence"] = candidate_evidence
            from app.services.table_semantics import validate_table_semantics

            is_valid = (
                validate_table_semantics(
                    candidate_view,
                    working.source_sha256,
                )
                is True
            )
        except (
            MemoryError,
            OverflowError,
            RecursionError,
            TypeError,
            ValueError,
            TimeoutError,
        ):
            is_valid = False
        table_candidate_authority_by_element_id[element.id] = is_valid
        return is_valid

    for reference, collection, index in duplicate_definitions:
        concern(
            "duplicate_reference",
            "A raw graph self_ref is defined more than once; the first "
            "definition was retained deterministically.",
            source_ref=reference,
            metadata={
                "kind": "duplicate_node_definition",
                "collection": collection,
                "duplicate_index": index,
            },
        )

    def report_malformed_reference_values(
        value: Any,
        *,
        source_ref: str,
        field_name: str,
    ) -> None:
        for index, item in enumerate(_raw_reference_items(value)):
            if _raw_reference(item):
                continue
            if (
                field_name == "annotations"
                and isinstance(item, Mapping)
                and item.get("kind")
            ):
                # Table/picture annotations are also allowed to be embedded
                # typed payloads rather than RefItems.
                continue
            concern(
                "malformed_reference",
                "A raw relationship entry is not a valid nonempty $ref/cref "
                "mapping and was not treated as an edge.",
                source_ref=source_ref,
                metadata={
                    "field": field_name,
                    "index": index,
                    "value_type": type(item).__name__,
                },
            )

    def report_malformed_nested_references(
        raw_item: Mapping[str, Any],
        *,
        source_ref: str,
    ) -> None:
        graph = raw_item.get("graph")
        if isinstance(graph, Mapping):
            cells = graph.get("cells") or []
            if isinstance(cells, Sequence) and not isinstance(
                cells, (str, bytes, bytearray)
            ):
                for index, cell in enumerate(cells):
                    if (
                        isinstance(cell, Mapping)
                        and "item_ref" in cell
                        and cell.get("item_ref") is not None
                        and not _raw_reference(cell.get("item_ref"))
                    ):
                        report_malformed_reference_values(
                            cell.get("item_ref"),
                            source_ref=source_ref,
                            field_name=f"graph.cells[{index}].item_ref",
                        )

        def validate_table_data(
            data: Any,
            *,
            path_prefix: str,
        ) -> None:
            if not isinstance(data, Mapping):
                return
            table_cells = data.get("table_cells") or []
            if not isinstance(table_cells, Sequence) or isinstance(
                table_cells, (str, bytes, bytearray)
            ):
                return
            for index, cell in enumerate(table_cells):
                if (
                    isinstance(cell, Mapping)
                    and "ref" in cell
                    and cell.get("ref") is not None
                    and not _raw_reference(cell.get("ref"))
                ):
                    report_malformed_reference_values(
                        cell.get("ref"),
                        source_ref=source_ref,
                        field_name=(f"{path_prefix}.table_cells[{index}].ref"),
                    )

        validate_table_data(raw_item.get("data"), path_prefix="data")
        annotations = raw_item.get("annotations") or []
        if isinstance(annotations, Sequence) and not isinstance(
            annotations, (str, bytes, bytearray)
        ):
            for index, annotation in enumerate(annotations):
                if isinstance(annotation, Mapping):
                    validate_table_data(
                        annotation.get("chart_data"),
                        path_prefix=(f"annotations[{index}].chart_data"),
                    )
        meta = raw_item.get("meta")
        if isinstance(meta, Mapping):
            tabular_chart = meta.get("tabular_chart")
            if isinstance(tabular_chart, Mapping):
                validate_table_data(
                    tabular_chart.get("chart_data"),
                    path_prefix="meta.tabular_chart.chart_data",
                )

    raw_reference_adjacency: dict[str, set[str]] = {
        reference: set() for reference in references
    }
    for owner_ref, raw_item in references.items():
        for field_name in _RAW_RELATION_FIELDS:
            if field_name not in raw_item:
                continue
            report_malformed_reference_values(
                raw_item.get(field_name),
                source_ref=owner_ref,
                field_name=field_name,
            )
            raw_reference_adjacency[owner_ref].update(
                _raw_reference_values(raw_item.get(field_name))
            )
        report_malformed_nested_references(
            raw_item,
            source_ref=owner_ref,
        )
        raw_reference_adjacency[owner_ref].update(
            target_ref
            for (
                target_ref,
                _relationship_type,
                _child_is_source,
                _field_path,
                _metadata,
            ) in _nested_raw_reference_entries(raw_item)
        )
        parent_ref = _raw_reference(raw_item.get("parent"))
        if (
            "parent" in raw_item
            and raw_item.get("parent") is not None
            and not parent_ref
        ):
            report_malformed_reference_values(
                raw_item.get("parent"),
                source_ref=owner_ref,
                field_name="parent",
            )
        if parent_ref in references:
            raw_reference_adjacency[parent_ref].add(owner_ref)

    # Propagate grounded descendant pages to provenance-free owners with a
    # depth-safe reverse work queue. Child-like leaf nodes inherit the
    # preferred page when their owner is materialized; keeping this pass
    # directional avoids flooding a multi-page tree's local groups with every
    # page in the connected component.
    inferred_page_sets: dict[str, set[int]] = {
        reference: (
            {page_index}
            if (page_index := _raw_page_index(raw_item)) is not None
            else set()
        )
        for reference, raw_item in references.items()
    }
    reverse_reference_adjacency: dict[str, set[str]] = {}
    for owner_ref, target_refs in raw_reference_adjacency.items():
        for target_ref in target_refs:
            if target_ref in references:
                reverse_reference_adjacency.setdefault(target_ref, set()).add(owner_ref)
    page_queue = deque(
        reference
        for reference, page_indexes in inferred_page_sets.items()
        if page_indexes
    )
    while page_queue:
        target_ref = page_queue.popleft()
        target_pages = inferred_page_sets[target_ref]
        for owner_ref in reverse_reference_adjacency.get(target_ref, set()):
            owner_pages = inferred_page_sets[owner_ref]
            before = len(owner_pages)
            owner_pages.update(target_pages)
            if len(owner_pages) != before:
                page_queue.append(owner_ref)
    inferred_page_cache = {
        reference: frozenset(page_indexes)
        for reference, page_indexes in inferred_page_sets.items()
    }

    def page_for_raw(
        raw_item: Mapping[str, Any],
        *,
        preferred_page: int | None = None,
        reference: str,
    ) -> PageRecord:
        page_index = _raw_page_index(raw_item)
        inferred_pages = (
            inferred_page_cache.get(reference, frozenset())
            if page_index is None
            else frozenset()
        )
        if page_index is None and len(inferred_pages) == 1:
            page_index = next(iter(inferred_pages))
        elif page_index is None and len(inferred_pages) > 1:
            concern(
                "ambiguous_page_reference",
                "A provenance-free raw node spans multiple referenced pages; "
                "it was retained on one page and cross-page edges remain "
                "explicit concerns.",
                source_ref=reference,
                metadata={"candidate_pages": sorted(inferred_pages)},
            )
            if preferred_page in inferred_pages:
                page_index = preferred_page
            else:
                page_index = min(inferred_pages)
        if page_index is None:
            page_index = preferred_page
        if page_index in pages_by_index:
            return pages_by_index[int(page_index)]
        fallback = working.pages[0]
        concern(
            "invalid_page_reference",
            "Raw graph node does not reference a known page; retained on the "
            "first page as diagnostic evidence.",
            source_ref=reference,
            metadata={"page_index": page_index},
        )
        return fallback

    def raw_top_left_box(
        raw_item: Mapping[str, Any],
        page: PageRecord,
    ) -> tuple[float, float, float, float] | None:
        provenance = raw_item.get("prov") or []
        if not isinstance(provenance, Sequence) or isinstance(provenance, (str, bytes)):
            return None
        for record in provenance:
            if not isinstance(record, Mapping):
                continue
            raw_box = record.get("bbox")
            if not isinstance(raw_box, Mapping):
                continue
            try:
                left = float(raw_box["l"])
                top = float(raw_box["t"])
                right = float(raw_box["r"])
                bottom = float(raw_box["b"])
            except (KeyError, OverflowError, TypeError, ValueError):
                continue
            if not all(math.isfinite(value) for value in (left, top, right, bottom)):
                continue
            origin = str(raw_box.get("coord_origin", "BOTTOMLEFT")).upper()
            if origin not in {"TOPLEFT", "BOTTOMLEFT"}:
                continue
            width = right - left
            height = bottom - top if origin == "TOPLEFT" else top - bottom
            if width < 0 or height < 0:
                continue
            if origin == "TOPLEFT":
                return left, top, width, height
            page_height = page_heights[page.id]
            return left, page_height - top, width, height
        return None

    def element_top_left_box(
        element: ElementRecord,
    ) -> tuple[float, float, float, float] | None:
        for bbox_id in element.bbox_ids:
            box = boxes[bbox_id]
            projected = _page_box_coordinates(
                box, coordinates[box.coordinate_system_id]
            )
            if projected is not None:
                return projected
        return None

    def find_match(
        reference: str,
        raw_item: Mapping[str, Any],
        page: PageRecord,
    ) -> ElementRecord | None:
        raw_type = _raw_element_type(raw_item, reference)
        raw_text = _normalized_text(_raw_value(raw_item))
        raw_box = raw_top_left_box(raw_item, page)

        annotation_assertions: list[
            tuple[ElementRecord, Mapping[str, Any]]
        ] = []
        for element_id in page.presentation_element_ids:
            element = elements[element_id]
            legacy = element.properties.get("legacy_item")
            partition = (
                legacy.get("source_partition")
                if isinstance(legacy, Mapping)
                else None
            )
            if (
                isinstance(partition, Mapping)
                and partition.get("annotation_raw_ref") == reference
            ):
                annotation_assertions.append((element, partition))
        if len(annotation_assertions) > 1:
            concern(
                "raw_annotation_partition_binding_ambiguous",
                "More than one presented source-note partition claimed the "
                "same PDF annotation; the raw annotation remained separate.",
                source_ref=reference,
                metadata={"candidate_count": len(annotation_assertions)},
            )
            return None
        annotation_claims: list[ElementRecord] = []
        if annotation_assertions:
            asserted_element, asserted_partition = annotation_assertions[0]
            expected_role = {
                _ANNOTATION_BACKED_TABLE_NOTE_PARTITION_POLICY: (
                    "detached_table_note"
                ),
                _ANNOTATION_BACKED_VISUAL_NOTE_PARTITION_POLICY: (
                    "detached_visual_note"
                ),
            }.get(asserted_partition.get("policy"))
            if (
                asserted_element.id in claimed_element_ids
                or asserted_element.type.casefold() != "footnote"
                or expected_role is None
                or asserted_partition.get("role") != expected_role
            ):
                concern(
                    "raw_annotation_partition_binding_rejected",
                    "A malformed presented source-note partition claimed a "
                    "raw annotation; generic matching was not permitted.",
                    source_ref=reference,
                    metadata={
                        "identity_valid": False,
                        "geometry_valid": False,
                        "element_type": asserted_element.type,
                    },
                )
                return None
            annotation_claims.append(asserted_element)
        if annotation_claims and raw_type != "annotation":
            concern(
                "raw_annotation_partition_binding_rejected",
                "A presented source-note partition claimed a raw reference "
                "that no longer identifies an annotation.",
                source_ref=reference,
                metadata={
                    "identity_valid": False,
                    "geometry_valid": False,
                    "raw_type": raw_type,
                },
            )
            return None

        # A gated table candidate deliberately remains a ``table_candidate``
        # in the public contract, while Docling's relationship graph calls the
        # same physical object a ``table``.  Bridge those names only through
        # the candidate's exact, bounded table-grid source identity.  Text or
        # geometry alone is not authority for this cross-layer binding.
        if raw_type == "table" and reference.startswith("#/tables/"):
            raw_page_index = _raw_page_index(raw_item)
            raw_provenance = raw_item.get("prov")
            raw_page_identity_is_strict = bool(
                isinstance(raw_provenance, Sequence)
                and not isinstance(raw_provenance, (str, bytes, bytearray))
                and raw_provenance
                and isinstance(raw_provenance[0], Mapping)
                and type(raw_provenance[0].get("page_no")) is int
            )
            claiming_candidates: list[tuple[ElementRecord, int]] = []
            oversized_candidate_ids: list[str] = []
            malformed_candidate_ids: list[str] = []
            for element_id in page.presentation_element_ids:
                element = elements[element_id]
                if (
                    element_id in claimed_element_ids
                    or element.type.casefold() != "table_candidate"
                ):
                    continue
                legacy = element.properties.get("legacy_item")
                sidecar = (
                    legacy.get("candidate_table_evidence")
                    if isinstance(legacy, Mapping)
                    else None
                )
                if not isinstance(sidecar, Mapping):
                    continue
                source_objects = sidecar.get("source_objects")
                if type(source_objects) is not list:
                    malformed_candidate_ids.append(element.id)
                    continue
                if len(source_objects) > _RAW_TABLE_CANDIDATE_SOURCE_OBJECT_LIMIT:
                    oversized_candidate_ids.append(element.id)
                    continue
                if any(not isinstance(source, Mapping) for source in source_objects):
                    malformed_candidate_ids.append(element.id)
                    continue
                matching_source_count = sum(
                    source.get("engine") == "docling"
                    and source.get("object_type") == "table_grid"
                    and source.get("raw_ref") == reference
                    for source in source_objects
                )
                if matching_source_count:
                    claiming_candidates.append((element, matching_source_count))

            if oversized_candidate_ids:
                concern(
                    "raw_table_candidate_binding_limit",
                    "A table-candidate source-object collection exceeded the "
                    "bounded raw-reference binding limit and was not traversed.",
                    source_ref=reference,
                    metadata={
                        "candidate_count": len(oversized_candidate_ids),
                        "limit": _RAW_TABLE_CANDIDATE_SOURCE_OBJECT_LIMIT,
                    },
                )
                return None
            if malformed_candidate_ids:
                concern(
                    "raw_table_candidate_binding_malformed",
                    "One or more table candidates had malformed source-object "
                    "evidence and were not raw-table binding candidates.",
                    source_ref=reference,
                    metadata={"candidate_count": len(malformed_candidate_ids)},
                )
                return None
            if len(claiming_candidates) > 1:
                concern(
                    "raw_table_candidate_binding_ambiguous",
                    "More than one presented table candidate claimed the same "
                    "Docling table-grid reference; the raw owner remained "
                    "separate.",
                    source_ref=reference,
                    metadata={"candidate_count": len(claiming_candidates)},
                )
                return None
            if claiming_candidates:
                candidate, matching_source_count = claiming_candidates[0]
                legacy = candidate.properties.get("legacy_item")
                assert isinstance(legacy, Mapping)
                sidecar = legacy.get("candidate_table_evidence")
                assert isinstance(sidecar, Mapping)
                gate = legacy.get("table_candidate_gate")
                raw_grid_topology = _validated_raw_table_grid_topology(
                    raw_item
                )
                if raw_grid_topology is None:
                    concern(
                        "raw_table_candidate_grid_rejected",
                        "A claimed Docling table did not contain one bounded, "
                        "nonoverlapping grid at the minimum coverage; the raw "
                        "owner remained separate.",
                        source_ref=reference,
                    )
                    return None
                source_objects = sidecar.get("source_objects")
                assert isinstance(source_objects, list)
                matching_source = next(
                    source
                    for source in source_objects
                    if isinstance(source, Mapping)
                    and source.get("engine") == "docling"
                    and source.get("object_type") == "table_grid"
                    and source.get("raw_ref") == reference
                )
                candidate_box = element_top_left_box(candidate)
                page_coordinate = coordinates[page.coordinate_system_id]
                authority_valid = table_candidate_has_valid_authority(
                    candidate,
                    legacy,
                )
                raw_grid_source_identity = (
                    _validated_raw_docling_grid_source_identity(
                        raw_item,
                        working.source_sha256,
                        topology=raw_grid_topology,
                    )
                )
                raw_grid_source_valid = bool(
                    raw_grid_source_identity is not None
                    and raw_grid_source_identity
                    == (
                        matching_source.get("id"),
                        matching_source.get("content_sha256"),
                    )
                )
                raw_grid_coverage_valid = (
                    _raw_table_grid_coverage_matches_gate(
                        raw_grid_topology,
                        gate,
                    )
                )
                (
                    raw_grid_rows,
                    raw_grid_columns,
                    raw_grid_covered_slots,
                    raw_grid_total_slots,
                ) = raw_grid_topology
                identity_valid = bool(
                    matching_source_count == 1
                    and authority_valid
                    and raw_grid_source_valid
                    and raw_grid_coverage_valid
                    and is_eligible_unresolved_table_candidate(legacy)
                    and isinstance(gate, Mapping)
                    and gate.get("candidate_id") == sidecar.get("candidate_id")
                    and sidecar.get("status") == "unresolved"
                    and isinstance(sidecar.get("candidate_id"), str)
                    and re.fullmatch(
                        _SHA256_PATTERN,
                        str(sidecar.get("candidate_id")),
                    )
                    is not None
                    and type(sidecar.get("page_index")) is int
                    and sidecar.get("page_index") == page.page_index
                    and type(matching_source.get("page_index")) is int
                    and matching_source.get("page_index") == page.page_index
                    and raw_page_identity_is_strict
                    and raw_page_index == page.page_index
                    and (raw_grid_rows, raw_grid_columns)
                    == (
                        legacy.get("row_count"),
                        legacy.get("column_count"),
                    )
                    and page_coordinate.unit == "pt"
                    and isinstance(matching_source.get("id"), str)
                    and re.fullmatch(
                        _SHA256_PATTERN,
                        str(matching_source.get("id")),
                    )
                    is not None
                    and isinstance(
                        matching_source.get("content_sha256"),
                        str,
                    )
                    and re.fullmatch(
                        _SHA256_PATTERN,
                        str(matching_source.get("content_sha256")),
                    )
                    is not None
                )
                geometry_valid = bool(
                    raw_box is not None
                    and candidate_box is not None
                    and all(
                        abs(float(raw_value) - float(candidate_value))
                        <= _RAW_TABLE_CANDIDATE_BBOX_EPSILON_PT
                        for raw_value, candidate_value in zip(
                            raw_box,
                            candidate_box,
                            strict=True,
                        )
                    )
                )
                if identity_valid and geometry_valid:
                    return candidate
                concern(
                    "raw_table_candidate_binding_rejected",
                    "A table candidate claimed the Docling table-grid "
                    "reference without complete same-page identity and "
                    "geometry agreement; the raw owner remained separate.",
                    source_ref=reference,
                    metadata={
                        "identity_valid": identity_valid,
                        "geometry_valid": geometry_valid,
                        "authority_valid": authority_valid,
                        "raw_grid_source_valid": raw_grid_source_valid,
                        "raw_grid_coverage_valid": raw_grid_coverage_valid,
                        "raw_grid_covered_slots": raw_grid_covered_slots,
                        "raw_grid_total_slots": raw_grid_total_slots,
                    },
                )
                return None

        # The pipeline may preserve one cross-page contribution as an
        # independently presented footnote after proving that it is the exact
        # source-visible text beneath a raw structured owner and one native
        # PDF annotation. Bind that annotation back to the presented footnote
        # so link metadata is delegated without creating a duplicate raw node.
        if raw_type == "annotation":
            if annotation_claims:
                candidate = annotation_claims[0]
                legacy = candidate.properties.get("legacy_item")
                assert isinstance(legacy, Mapping)
                partition = legacy.get("source_partition")
                assert isinstance(partition, Mapping)
                partition_policy = partition.get("policy")
                is_table_partition = (
                    partition_policy
                    == _ANNOTATION_BACKED_TABLE_NOTE_PARTITION_POLICY
                )
                is_visual_partition = (
                    partition_policy
                    == _ANNOTATION_BACKED_VISUAL_NOTE_PARTITION_POLICY
                )
                owner_ref = partition.get(
                    "table_raw_ref"
                    if is_table_partition
                    else "visual_raw_ref"
                )
                fused_ref = partition.get("raw_ref")
                fused_record = references.get(fused_ref)
                candidate_box = element_top_left_box(candidate)

                def bounds_for_page(
                    candidate_page: PageRecord | None,
                ) -> tuple[float, float, float, float] | None:
                    if candidate_page is None:
                        return None
                    candidate_region = page_region.get(candidate_page.id)
                    if candidate_region is None:
                        return None
                    candidate_page_box = boxes.get(candidate_region.bbox_id)
                    candidate_coordinate = (
                        coordinates.get(candidate_page_box.coordinate_system_id)
                        if candidate_page_box is not None
                        else None
                    )
                    if (
                        candidate_page_box is None
                        or candidate_coordinate is None
                        or candidate_coordinate.unit != "pt"
                    ):
                        return None
                    return _page_box_coordinates(
                        candidate_page_box,
                        candidate_coordinate,
                    )

                page_bounds = bounds_for_page(page)

                def box_is_within_bounds(
                    raw_candidate_box: tuple[float, float, float, float] | None,
                    candidate_bounds: tuple[
                        float,
                        float,
                        float,
                        float,
                    ]
                    | None,
                ) -> bool:
                    if raw_candidate_box is None or candidate_bounds is None:
                        return False
                    x, y, width, height = raw_candidate_box
                    page_x, page_y, page_width, page_height = candidate_bounds
                    epsilon = _RAW_TABLE_CANDIDATE_BBOX_EPSILON_PT
                    return bool(
                        all(
                            math.isfinite(value)
                            for value in (
                                x,
                                y,
                                width,
                                height,
                                page_x,
                                page_y,
                                page_width,
                                page_height,
                            )
                        )
                        and width > 0
                        and height > 0
                        and page_width > 0
                        and page_height > 0
                        and x >= page_x - epsilon
                        and y >= page_y - epsilon
                        and x + width <= page_x + page_width + epsilon
                        and y + height <= page_y + page_height + epsilon
                    )

                def box_is_on_page(
                    raw_candidate_box: tuple[float, float, float, float] | None,
                ) -> bool:
                    return box_is_within_bounds(
                        raw_candidate_box,
                        page_bounds,
                    )

                def comparable_area_ratio(
                    first: tuple[float, float, float, float] | None,
                    second: tuple[float, float, float, float] | None,
                ) -> float:
                    if first is None or second is None:
                        return 0.0
                    first_area = first[2] * first[3]
                    second_area = second[2] * second[3]
                    if first_area <= 0 or second_area <= 0:
                        return 0.0
                    return min(first_area, second_area) / max(
                        first_area,
                        second_area,
                    )

                def boxes_mutually_overlap(
                    first: tuple[float, float, float, float] | None,
                    second: tuple[float, float, float, float] | None,
                    *,
                    minimum: float,
                ) -> bool:
                    if first is None or second is None:
                        return False
                    first_x, first_y, first_width, first_height = first
                    second_x, second_y, second_width, second_height = second
                    first_area = first_width * first_height
                    second_area = second_width * second_height
                    if first_area <= 0 or second_area <= 0:
                        return False
                    intersection_width = max(
                        min(first_x + first_width, second_x + second_width)
                        - max(first_x, second_x),
                        0.0,
                    )
                    intersection_height = max(
                        min(first_y + first_height, second_y + second_height)
                        - max(first_y, second_y),
                        0.0,
                    )
                    intersection = intersection_width * intersection_height
                    return bool(
                        intersection / first_area >= minimum
                        and intersection / second_area >= minimum
                    )

                def provenance_origin_is_explicit(
                    record: Mapping[str, Any],
                ) -> bool:
                    raw_provenance_box = record.get("bbox")
                    return bool(
                        isinstance(raw_provenance_box, Mapping)
                        and type(raw_provenance_box.get("coord_origin")) is str
                        and raw_provenance_box["coord_origin"].upper()
                        in {"TOPLEFT", "BOTTOMLEFT"}
                    )

                fused_contribution_valid = False
                fused_owner_box: tuple[float, float, float, float] | None = None
                fused_detached_box: tuple[float, float, float, float] | None = None
                fused_provenance = (
                    fused_record.get("prov")
                    if isinstance(fused_record, Mapping)
                    else None
                )
                if (
                    isinstance(fused_ref, str)
                    and fused_ref.startswith("#/texts/")
                    and isinstance(fused_record, Mapping)
                    and fused_record.get("self_ref") == fused_ref
                    and type(partition.get("provenance_index")) is int
                    and partition.get("provenance_index") == 1
                    and type(partition.get("charspan")) is list
                    and type(fused_provenance) is list
                    and len(fused_provenance) == 2
                    and all(
                        isinstance(record, Mapping)
                        for record in fused_provenance
                    )
                    and isinstance(fused_record.get("text"), str)
                    and len(fused_record["text"])
                    <= _ANNOTATION_BACKED_SOURCE_NOTE_MAX_CODEPOINTS
                ):
                    first_record, second_record = fused_provenance
                    first_span = first_record.get("charspan")
                    second_span = second_record.get("charspan")
                    fused_text = str(fused_record["text"])
                    if (
                        type(first_span) is list
                        and type(second_span) is list
                        and len(first_span) == 2
                        and len(second_span) == 2
                        and all(
                            type(offset) is int
                            for offset in (*first_span, *second_span)
                        )
                        and provenance_origin_is_explicit(first_record)
                        and provenance_origin_is_explicit(second_record)
                        and partition["charspan"] == second_span
                        and type(first_record.get("page_no")) is int
                        and type(second_record.get("page_no")) is int
                        and second_record.get("page_no") == page.page_index
                        and second_record.get("page_no")
                        == first_record.get("page_no") + 1
                    ):
                        first_start, first_end = first_span
                        second_start, second_end = second_span
                        prior_page = pages_by_index.get(
                            first_record.get("page_no")
                        )
                        fused_owner_box = raw_top_left_box(
                            {"prov": [first_record]},
                            prior_page,
                        ) if prior_page is not None else None
                        fused_detached_box = raw_top_left_box(
                            {"prov": [second_record]},
                            page,
                        )
                        fused_contribution_valid = bool(
                            first_start == 0
                            and 0 < first_end <= second_start < second_end
                            <= len(fused_text)
                            and not fused_text[first_end:second_start].strip()
                            and not fused_text[second_end:].strip()
                            and fused_text[second_start:second_end].strip()
                            == candidate.value
                            and box_is_within_bounds(
                                fused_owner_box,
                                bounds_for_page(prior_page),
                            )
                            and box_is_on_page(fused_detached_box)
                            and boxes_mutually_overlap(
                                raw_box,
                                fused_detached_box,
                                minimum=0.80,
                            )
                            and _box_overlap_of_smaller(
                                fused_detached_box,
                                candidate_box,
                            )
                            >= 0.75
                            and comparable_area_ratio(
                                fused_detached_box,
                                candidate_box,
                            )
                            >= 0.75
                        )
                def annotation_marker_box(
                    annotation_record: Mapping[str, Any],
                ) -> tuple[float, float, float, float] | None:
                    marker_meta = annotation_record.get("meta")
                    marker = (
                        marker_meta.get("layout_source_note_pdf_annotation")
                        if isinstance(marker_meta, Mapping)
                        else None
                    )
                    marker_payload = (
                        marker.get("bbox")
                        if isinstance(marker, Mapping)
                        and marker.get("source_visible") is True
                        else None
                    )
                    if not isinstance(marker_payload, Mapping):
                        return None
                    marker_values = tuple(
                        marker_payload.get(field)
                        for field in ("x", "y", "width", "height")
                    )
                    if not (
                        marker_payload.get("unit") == "pt"
                        and all(
                            type(value) in {int, float}
                            and type(value) is not bool
                            for value in marker_values
                        )
                    ):
                        return None
                    try:
                        normalized_marker_values = tuple(
                            float(value) for value in marker_values
                        )
                    except (OverflowError, TypeError, ValueError):
                        return None
                    if (
                        len(normalized_marker_values) != 4
                        or not all(
                            math.isfinite(value)
                            for value in normalized_marker_values
                        )
                        or normalized_marker_values[2] <= 0
                        or normalized_marker_values[3] <= 0
                    ):
                        return None
                    return normalized_marker_values

                marker_meta = raw_item.get("meta")
                marker = (
                    marker_meta.get("layout_source_note_pdf_annotation")
                    if isinstance(marker_meta, Mapping)
                    else None
                )
                annotation_provenance = raw_item.get("prov")
                annotation_text = raw_item.get("text")
                annotation_provenance_valid = False
                if (
                    isinstance(annotation_text, str)
                    and type(annotation_provenance) is list
                    and len(annotation_provenance) == 1
                    and isinstance(annotation_provenance[0], Mapping)
                ):
                    annotation_span = annotation_provenance[0].get("charspan")
                    annotation_provenance_valid = bool(
                        type(annotation_provenance[0].get("page_no")) is int
                        and annotation_provenance[0].get("page_no")
                        == page.page_index
                        and provenance_origin_is_explicit(
                            annotation_provenance[0]
                        )
                        and type(annotation_span) is list
                        and len(annotation_span) == 2
                        and all(type(offset) is int for offset in annotation_span)
                        and annotation_span == [0, len(annotation_text)]
                    )

                marker_box = annotation_marker_box(raw_item)
                marker_geometry_valid = bool(
                    marker_box is not None
                    and raw_box is not None
                    and box_is_on_page(marker_box)
                    and box_is_on_page(raw_box)
                    and all(
                        abs(marker_box[index] - raw_box[index])
                        <= _RAW_TABLE_CANDIDATE_BBOX_EPSILON_PT
                        for index in range(4)
                    )
                )
                source_line_ids = partition.get("source_line_ids")
                source_character_ids = partition.get("source_character_ids")
                partition_lineage_valid = bool(
                    type(source_line_ids) is list
                    and len(source_line_ids) == 1
                    and isinstance(source_line_ids[0], str)
                    and bool(source_line_ids[0])
                    and type(source_character_ids) is list
                    and 1
                    <= len(source_character_ids)
                    <= _ANNOTATION_BACKED_SOURCE_NOTE_MAX_CODEPOINTS
                    and all(
                        isinstance(character_id, str) and bool(character_id)
                        for character_id in source_character_ids
                    )
                    and len(set(source_character_ids))
                    == len(source_character_ids)
                )
                try:
                    from app.services.layout_source_notes import (
                        safe_http_annotation_target,
                    )
                except ImportError:
                    safe_target_validator = None
                    safe_annotation_target = None
                else:
                    safe_target_validator = safe_http_annotation_target
                    safe_annotation_target = safe_http_annotation_target(
                        raw_item.get("hyperlink")
                    )
                matching_annotation_refs: list[str] = []
                if (
                    safe_target_validator is not None
                    and len(references)
                    <= _ANNOTATION_BACKED_SOURCE_NOTE_MAX_RAW_REFERENCES
                ):
                    for candidate_ref, annotation_candidate in references.items():
                        if not isinstance(annotation_candidate, Mapping):
                            matching_annotation_refs = []
                            break
                        candidate_text = annotation_candidate.get("text")
                        candidate_provenance = annotation_candidate.get("prov")
                        candidate_span = (
                            candidate_provenance[0].get("charspan")
                            if type(candidate_provenance) is list
                            and len(candidate_provenance) == 1
                            and isinstance(candidate_provenance[0], Mapping)
                            else None
                        )
                        if (
                            annotation_candidate.get("self_ref") != candidate_ref
                            or str(
                                annotation_candidate.get("label") or ""
                            ).casefold()
                            != "annotation"
                            or annotation_candidate.get("source") != "native"
                            or annotation_candidate.get("evidence_methods")
                            != ["native"]
                            or not isinstance(candidate_text, str)
                            or candidate_text != candidate.value
                            or annotation_candidate.get("hyperlink")
                            != candidate.value
                            or safe_target_validator(
                                annotation_candidate.get("hyperlink")
                            )
                            != candidate.value
                            or type(candidate_provenance) is not list
                            or len(candidate_provenance) != 1
                            or not isinstance(candidate_provenance[0], Mapping)
                            or not provenance_origin_is_explicit(
                                candidate_provenance[0]
                            )
                            or type(
                                candidate_provenance[0].get("page_no")
                            )
                            is not int
                            or candidate_provenance[0].get("page_no")
                            != page.page_index
                            or type(candidate_span) is not list
                            or len(candidate_span) != 2
                            or any(
                                type(offset) is not int
                                for offset in candidate_span
                            )
                            or candidate_span != [0, len(candidate_text)]
                        ):
                            continue
                        candidate_raw_box = raw_top_left_box(
                            annotation_candidate,
                            page,
                        )
                        candidate_marker_box = annotation_marker_box(
                            annotation_candidate
                        )
                        if (
                            candidate_raw_box is not None
                            and candidate_marker_box is not None
                            and box_is_on_page(candidate_raw_box)
                            and box_is_on_page(candidate_marker_box)
                            and all(
                                abs(
                                    candidate_marker_box[index]
                                    - candidate_raw_box[index]
                                )
                                <= _RAW_TABLE_CANDIDATE_BBOX_EPSILON_PT
                                for index in range(4)
                            )
                            and _box_overlap_of_smaller(
                                candidate_raw_box,
                                candidate_box,
                            )
                            >= 0.80
                            and boxes_mutually_overlap(
                                candidate_raw_box,
                                candidate_box,
                                minimum=0.80,
                            )
                            and comparable_area_ratio(
                                candidate_raw_box,
                                candidate_box,
                            )
                            >= 0.75
                            and boxes_mutually_overlap(
                                candidate_raw_box,
                                fused_detached_box,
                                minimum=0.80,
                            )
                        ):
                            matching_annotation_refs.append(candidate_ref)
                annotation_identity_is_unique = matching_annotation_refs == [
                    reference
                ]
                owner_identity_valid = False
                if is_table_partition or is_visual_partition:
                    structured_owner_claims: list[
                        tuple[str, str, str | None]
                    ] = []
                    owner_scan_valid = True

                    def external_below(
                        note_box: tuple[float, float, float, float] | None,
                        owner_box: tuple[float, float, float, float] | None,
                    ) -> bool:
                        if note_box is None or owner_box is None:
                            return False
                        note_x, note_y, note_width, note_height = note_box
                        owner_x, owner_y, owner_width, owner_height = owner_box
                        overlap_width = max(
                            min(note_x + note_width, owner_x + owner_width)
                            - max(note_x, owner_x),
                            0.0,
                        )
                        gap = note_y - (owner_y + owner_height)
                        return bool(
                            gap >= 0
                            and gap <= _ANNOTATION_BACKED_OWNER_MAX_GAP_PT
                            and overlap_width
                            / max(min(note_width, owner_width), 1e-9)
                            >= 0.20
                        )

                    def external_caption(
                        caption_box: tuple[float, float, float, float] | None,
                        owner_box: tuple[float, float, float, float] | None,
                    ) -> bool:
                        if caption_box is None or owner_box is None:
                            return False
                        caption_x, caption_y, caption_width, caption_height = (
                            caption_box
                        )
                        owner_x, owner_y, owner_width, owner_height = owner_box
                        overlap_width = max(
                            min(
                                caption_x + caption_width,
                                owner_x + owner_width,
                            )
                            - max(caption_x, owner_x),
                            0.0,
                        )
                        above_gap = owner_y - (caption_y + caption_height)
                        below_gap = caption_y - (owner_y + owner_height)
                        separated_gap = max(above_gap, below_gap)
                        return bool(
                            separated_gap >= 0
                            and separated_gap
                            <= _ANNOTATION_BACKED_OWNER_MAX_GAP_PT
                            and overlap_width
                            / max(min(caption_width, owner_width), 1e-9)
                            >= 0.20
                        )

                    try:
                        raw_owner_entries = list(references.items())
                    except (MemoryError, RuntimeError, TypeError, ValueError):
                        raw_owner_entries = []
                        owner_scan_valid = False
                    if (
                        len(raw_owner_entries)
                        > _ANNOTATION_BACKED_SOURCE_NOTE_MAX_RAW_REFERENCES
                    ):
                        owner_scan_valid = False
                    if owner_scan_valid:
                        for raw_owner_ref, raw_owner in raw_owner_entries:
                            if not isinstance(raw_owner, Mapping):
                                owner_scan_valid = False
                                break
                            raw_owner_provenance = raw_owner.get("prov")
                            raw_owner_label = str(
                                raw_owner.get("label") or ""
                            ).casefold()
                            if (
                                raw_owner_ref.startswith("#/tables/")
                                and raw_owner.get("self_ref") == raw_owner_ref
                                and raw_owner_label == "table"
                            ):
                                if (
                                    type(raw_owner_provenance) is not list
                                    or len(raw_owner_provenance) != 1
                                    or not isinstance(
                                        raw_owner_provenance[0], Mapping
                                    )
                                    or not provenance_origin_is_explicit(
                                        raw_owner_provenance[0]
                                    )
                                    or type(
                                        raw_owner_provenance[0].get("page_no")
                                    )
                                    is not int
                                    or raw_owner_provenance[0].get("page_no")
                                    != page.page_index
                                    or _validated_raw_table_grid_topology(
                                        raw_owner
                                    )
                                    is None
                                ):
                                    continue
                                table_box = raw_top_left_box(raw_owner, page)
                                if (
                                    box_is_on_page(table_box)
                                    and external_below(raw_box, table_box)
                                ):
                                    structured_owner_claims.append(
                                        ("table", raw_owner_ref, None)
                                    )
                                continue
                            if not (
                                raw_owner_ref.startswith("#/pictures/")
                                and raw_owner.get("self_ref") == raw_owner_ref
                                and raw_owner_label
                                in {"picture", "image", "chart", "diagram"}
                            ):
                                continue
                            caption_claims = raw_owner.get("captions")
                            if (
                                type(raw_owner_provenance) is not list
                                or len(raw_owner_provenance) != 1
                                or not isinstance(
                                    raw_owner_provenance[0], Mapping
                                )
                                or not provenance_origin_is_explicit(
                                    raw_owner_provenance[0]
                                )
                                or type(
                                    raw_owner_provenance[0].get("page_no")
                                )
                                is not int
                                or raw_owner_provenance[0].get("page_no")
                                != page.page_index
                                or type(caption_claims) is not list
                                or len(caption_claims) != 1
                                or not isinstance(caption_claims[0], Mapping)
                            ):
                                continue
                            raw_caption_ref = caption_claims[0].get("$ref")
                            raw_caption = references.get(raw_caption_ref)
                            raw_caption_provenance = (
                                raw_caption.get("prov")
                                if isinstance(raw_caption, Mapping)
                                else None
                            )
                            if (
                                not isinstance(raw_caption_ref, str)
                                or not raw_caption_ref.startswith("#/texts/")
                                or not isinstance(raw_caption, Mapping)
                                or raw_caption.get("self_ref")
                                != raw_caption_ref
                                or str(
                                    raw_caption.get("label") or ""
                                ).casefold()
                                != "caption"
                                or type(raw_caption_provenance) is not list
                                or len(raw_caption_provenance) != 1
                                or not isinstance(
                                    raw_caption_provenance[0], Mapping
                                )
                                or not provenance_origin_is_explicit(
                                    raw_caption_provenance[0]
                                )
                                or type(
                                    raw_caption_provenance[0].get("page_no")
                                )
                                is not int
                                or raw_caption_provenance[0].get("page_no")
                                != page.page_index
                                or not isinstance(raw_caption.get("text"), str)
                                or not str(raw_caption.get("text")).strip()
                                or len(str(raw_caption.get("text"))) > 2_048
                            ):
                                continue
                            picture_box = raw_top_left_box(raw_owner, page)
                            caption_box = raw_top_left_box(raw_caption, page)
                            if (
                                box_is_on_page(picture_box)
                                and box_is_on_page(caption_box)
                                and external_below(raw_box, picture_box)
                                and external_caption(caption_box, picture_box)
                                and _box_overlap_of_smaller(caption_box, raw_box)
                                == 0
                            ):
                                structured_owner_claims.append(
                                    (
                                        "visual",
                                        raw_owner_ref,
                                        raw_caption_ref,
                                    )
                                )
                    expected_owner_claim = (
                        (
                            "table",
                            owner_ref,
                            None,
                        )
                        if is_table_partition
                        else (
                            "visual",
                            owner_ref,
                            partition.get("caption_raw_ref"),
                        )
                    )
                    owner_identity_valid = bool(
                        owner_scan_valid
                        and structured_owner_claims == [expected_owner_claim]
                    )
                identity_valid = bool(
                    owner_identity_valid
                    and fused_contribution_valid
                    and partition.get("source_sha256") == working.source_sha256
                    and isinstance(candidate.value, str)
                    and raw_item.get("source") == "native"
                    and raw_item.get("evidence_methods") == ["native"]
                    and isinstance(marker, Mapping)
                    and marker.get("source_visible") is True
                    and annotation_provenance_valid
                    and marker_geometry_valid
                    and annotation_identity_is_unique
                    and partition_lineage_valid
                    and raw_item.get("self_ref") == reference
                    and isinstance(raw_item.get("text"), str)
                    and raw_item.get("text") == candidate.value
                    and raw_item.get("hyperlink") == candidate.value
                    and safe_annotation_target == candidate.value
                )
                geometry_valid = bool(
                    raw_box is not None
                    and candidate_box is not None
                    and box_is_on_page(candidate_box)
                    and boxes_mutually_overlap(
                        raw_box,
                        candidate_box,
                        minimum=0.80,
                    )
                )
                if identity_valid and geometry_valid:
                    return candidate
                concern(
                    "raw_annotation_partition_binding_rejected",
                    "A presented source-note partition claimed an annotation "
                    "without complete native identity and geometry agreement.",
                    source_ref=reference,
                    metadata={
                        "identity_valid": identity_valid,
                        "geometry_valid": geometry_valid,
                        "owner_kind": (
                            "table" if is_table_partition else "visual"
                        ),
                    },
                )
                return None

        best: tuple[float, ElementRecord] | None = None
        for element_id in match_candidates_by_page_id[page.id]:
            element = elements[element_id]
            # A Docling self_ref identifies one graph node. Once an element is
            # claimed, a second self_ref must not collapse onto it merely
            # because two raw nodes share a generic label such as "group".
            if element_id in claimed_element_ids:
                continue
            legacy = element.properties.get("legacy_item")
            source_partition = (
                legacy.get("source_partition")
                if isinstance(legacy, Mapping)
                else None
            )
            if (
                isinstance(source_partition, Mapping)
                and isinstance(
                    source_partition.get("annotation_raw_ref"),
                    str,
                )
            ):
                # An annotation-backed partition is reserved for its exact
                # special-contract replay. A preceding same-text raw node may
                # not steal the presented footnote through generic matching.
                continue
            if not _compatible_raw_type(raw_type, element.type):
                continue
            score = 1.0
            if element.type == raw_type:
                score += 1.0
            candidate_text = _normalized_text(element.value)
            if raw_text and candidate_text:
                if raw_text == candidate_text:
                    score += 3.0
                elif raw_text in candidate_text or candidate_text in raw_text:
                    score += 1.0
            overlap = _box_overlap_of_smaller(raw_box, element_top_left_box(element))
            score += overlap * 3.0
            if (
                raw_text
                and candidate_text
                and raw_text != candidate_text
                and overlap < 0.5
            ):
                continue
            if raw_box is not None and overlap == 0 and not raw_text:
                continue
            if best is None or score > best[0]:
                best = score, element
        return best[1] if best is not None and best[0] >= 2.0 else None

    def raw_boxes(
        reference: str,
        raw_item: Mapping[str, Any],
        page: PageRecord,
    ) -> list[IRBoundingBox]:
        output: list[IRBoundingBox] = []
        provenance = raw_item.get("prov") or []
        if not isinstance(provenance, Sequence) or isinstance(provenance, (str, bytes)):
            provenance = []
        for index, record in enumerate(provenance):
            if not isinstance(record, Mapping):
                continue
            try:
                record_page = int(record.get("page_no"))
            except (TypeError, ValueError):
                record_page = page.page_index
            if record_page != page.page_index:
                concern(
                    "cross_page_provenance",
                    "A raw node has provenance on more than one page; the "
                    "cross-page box was retained as a concern, not attached.",
                    source_ref=reference,
                    metadata={
                        "owner_page": page.page_index,
                        "bbox_page": record_page,
                    },
                )
                continue
            raw_box = record.get("bbox")
            if not isinstance(raw_box, Mapping):
                continue
            try:
                left = float(raw_box["l"])
                top = float(raw_box["t"])
                right = float(raw_box["r"])
                bottom = float(raw_box["b"])
            except (KeyError, OverflowError, TypeError, ValueError):
                concern(
                    "invalid_bbox",
                    "A raw provenance bbox is invalid and was not attached.",
                    source_ref=reference,
                    metadata={"provenance_index": index},
                )
                continue
            if not all(math.isfinite(value) for value in (left, top, right, bottom)):
                concern(
                    "invalid_bbox",
                    "A raw provenance bbox contains a non-finite coordinate "
                    "and was not attached.",
                    source_ref=reference,
                    metadata={"provenance_index": index},
                )
                continue
            origin = str(raw_box.get("coord_origin", "BOTTOMLEFT")).upper()
            if origin not in {"TOPLEFT", "BOTTOMLEFT"}:
                concern(
                    "invalid_bbox",
                    "A raw provenance bbox declares an unsupported coordinate "
                    "origin and was not attached.",
                    source_ref=reference,
                    metadata={
                        "provenance_index": index,
                        "coord_origin": origin,
                    },
                )
                continue
            if origin == "TOPLEFT":
                x, y = left, top
                width, height = right - left, bottom - top
                coordinate_origin = "top_left"
                transform = IDENTITY_TRANSFORM
            else:
                x, y = left, bottom
                width, height = right - left, top - bottom
                coordinate_origin = "bottom_left"
                transform = (
                    1.0,
                    0.0,
                    0.0,
                    -1.0,
                    0.0,
                    float(page_heights[page.id]),
                )
            if width < 0 or height < 0:
                concern(
                    "invalid_bbox",
                    "A raw provenance bbox has inverted coordinates and was "
                    "not attached.",
                    source_ref=reference,
                    metadata={
                        "provenance_index": index,
                        "coord_origin": origin,
                    },
                )
                continue
            page_coordinate = coordinates[page.coordinate_system_id]
            coordinate_id = _stable_id(
                "coords",
                page.id,
                page_coordinate.unit,
                coordinate_origin,
                transform,
            )
            if coordinate_id not in coordinates:
                coordinate = CoordinateSystem(
                    id=coordinate_id,
                    page_id=page.id,
                    unit=page_coordinate.unit,
                    origin=coordinate_origin,
                    transform_to_page=transform,
                )
                working.coordinate_systems.append(coordinate)
                coordinates[coordinate.id] = coordinate
            box_id = _stable_id("box", working.id, reference, index, raw_box)
            if box_id in boxes:
                output.append(boxes[box_id])
                continue
            label = str(raw_item.get("label") or "").casefold()
            role = (
                "annotation"
                if "annotation" in label
                else ("field" if label in {"key", "value"} else "child")
            )
            box = IRBoundingBox(
                id=box_id,
                coordinate_system_id=coordinate_id,
                x=x,
                y=y,
                width=width,
                height=height,
                role=role,
            )
            working.bboxes.append(box)
            boxes[box.id] = box
            output.append(box)
        return output

    def raw_methods(
        raw_item: Mapping[str, Any],
        page: PageRecord,
    ) -> list[EvidenceMethod]:
        if has_untrusted_generation_provenance(raw_item):
            return [EvidenceMethod.DERIVED]
        explicit_source = str(raw_item.get("source") or "").casefold()
        if explicit_source or "evidence_methods" in raw_item:
            return _source_methods(raw_item)
        text = _normalized_text(_raw_value(raw_item))
        native = (
            _normalized_text(native_texts[page.page_index - 1])
            if 0 < page.page_index <= len(native_texts)
            else ""
        )
        if text:
            compact_text = text.replace(" ", "")
            compact_native = native.replace(" ", "")
            tokens = text.split()
            native_tokens = native.split()
            short_ambiguous = len(tokens) == 1 and (
                len(compact_text) < 3
                or (compact_text.isdigit() and len(compact_text) < 4)
            )
            boundary_match = not short_ambiguous and (
                (len(tokens) == 1 and tokens[0] in native_tokens)
                or f" {text} " in f" {native} "
            )
            compact_match = len(compact_text) >= 8 and compact_text in compact_native
            if boundary_match or compact_match:
                return [EvidenceMethod.NATIVE]
            return [EvidenceMethod.OCR]
        return [EvidenceMethod.DERIVED]

    def add_raw_evidence(
        element: ElementRecord,
        reference: str,
        raw_item: Mapping[str, Any],
        page: PageRecord,
        node_boxes: Sequence[IRBoundingBox],
    ) -> None:
        value = _raw_value(raw_item)
        provenance_by_box_id: dict[str, tuple[int, Mapping[str, Any]]] = {}
        provenance = raw_item.get("prov") or []
        if isinstance(provenance, Sequence) and not isinstance(
            provenance,
            (str, bytes, bytearray),
        ):
            for provenance_index, provenance_record in enumerate(provenance):
                if not isinstance(provenance_record, Mapping):
                    continue
                raw_box = provenance_record.get("bbox")
                if not isinstance(raw_box, Mapping):
                    continue
                try:
                    box_id = _stable_id(
                        "box",
                        working.id,
                        reference,
                        provenance_index,
                        raw_box,
                    )
                except (OverflowError, TypeError, ValueError):
                    continue
                provenance_by_box_id[box_id] = (
                    provenance_index,
                    provenance_record,
                )
        attachment_boxes: Sequence[IRBoundingBox | None] = (
            node_boxes if node_boxes else [None]
        )
        for method in raw_methods(raw_item, page):
            for box in attachment_boxes:
                evidence_id = _stable_id(
                    "ev",
                    element.id,
                    method.value,
                    box.id if box else None,
                    value,
                    "raw_ref",
                    reference,
                )
                if evidence_id in evidence:
                    continue
                metadata: dict[str, Any] = {
                    "raw_ref": reference,
                    "raw_label": raw_item.get("label"),
                }
                provenance_match = (
                    provenance_by_box_id.get(box.id) if box is not None else None
                )
                if provenance_match is not None:
                    provenance_index, provenance_record = provenance_match
                    metadata["provenance_index"] = provenance_index
                    charspan = provenance_record.get("charspan")
                    value_length = len(value) if isinstance(value, str) else 0
                    if (
                        isinstance(charspan, Sequence)
                        and not isinstance(
                            charspan,
                            (str, bytes, bytearray),
                        )
                        and len(charspan) == 2
                        and all(
                            isinstance(offset, int) and not isinstance(offset, bool)
                            for offset in charspan
                        )
                    ):
                        start, end = charspan
                        if 0 <= start < end <= value_length:
                            metadata["charspan"] = [start, end]
                record = EvidenceRecord(
                    id=evidence_id,
                    element_id=element.id,
                    method=method,
                    bbox_id=box.id if box else None,
                    value=deepcopy(value),
                    confidence=_confidence(raw_item.get("confidence")),
                    metadata=metadata,
                )
                working.evidence.append(record)
                evidence[record.id] = record
                element.evidence_ids.append(record.id)
                if box is not None and box.id not in element.bbox_ids:
                    element.bbox_ids.append(box.id)

    def remove_inherited_semantic_evidence(
        element: ElementRecord,
        raw_item: Mapping[str, Any],
    ) -> None:
        collection = str(element.properties.get("collection") or "")
        semantic_fields = {
            field_name
            for field_names, _relationship_type, _element_type in (
                _SEMANTIC_RELATION_FIELDS
            )
            for field_name in field_names
        }
        if collection not in semantic_fields:
            return
        removable = {
            evidence_id
            for evidence_id in element.evidence_ids
            if evidence_id in evidence
            and "raw_ref" not in evidence[evidence_id].metadata
            and evidence[evidence_id].metadata.get("collection") == collection
        }
        if not removable:
            return
        element.evidence_ids = [
            evidence_id
            for evidence_id in element.evidence_ids
            if evidence_id not in removable
        ]
        working.evidence = [
            record for record in working.evidence if record.id not in removable
        ]
        for evidence_id in removable:
            evidence.pop(evidence_id, None)
        for relationship in working.relationships:
            relationship.evidence_ids = [
                evidence_id
                for evidence_id in relationship.evidence_ids
                if evidence_id not in removable
            ]

    def ensure_raw_element(
        reference: str,
        *,
        preferred_page: int | None = None,
    ) -> ElementRecord | None:
        if reference in ref_to_element:
            return elements[ref_to_element[reference]]
        raw_item = references.get(reference)
        if raw_item is None:
            concern(
                "dangling_reference",
                "A raw graph reference has no registered target.",
                target_ref=reference,
            )
            return None
        page = page_for_raw(
            raw_item,
            preferred_page=preferred_page,
            reference=reference,
        )
        element = find_match(reference, raw_item, page)
        if element is None:
            element = ElementRecord(
                id=_stable_id("el", working.id, "raw_ref", reference),
                page_id=page.id,
                type=_raw_element_type(raw_item, reference),
                value=deepcopy(_raw_value(raw_item)),
                presentation_role="subordinate",
                properties={
                    "raw_refs": [reference],
                    "raw_label": raw_item.get("label"),
                    "raw_record": deepcopy(dict(raw_item)),
                    "normalization_origin": "docling_reference_graph",
                    "generated": False,
                },
            )
            working.elements.append(element)
            elements[element.id] = element
            page.element_ids.append(element.id)
            page_region[page.id].element_ids.append(element.id)
        else:
            raw_refs = element.properties.setdefault("raw_refs", [])
            if reference not in raw_refs:
                raw_refs.append(reference)
            remove_inherited_semantic_evidence(element, raw_item)
        if has_untrusted_generation_provenance(raw_item):
            element.properties[RAW_GENERATION_PROVENANCE_PROPERTY] = True
        element.properties.setdefault("raw_label", raw_item.get("label"))
        if raw_item.get("hyperlink") is not None:
            links = element.properties.setdefault("links", [])
            link = {
                "kind": "hyperlink",
                "target": deepcopy(raw_item.get("hyperlink")),
                "raw_ref": reference,
            }
            if link not in links:
                links.append(link)
        source_metadata = {
            key: deepcopy(raw_item[key])
            for key in ("annotations", "meta")
            if raw_item.get(key) is not None
        }
        if source_metadata:
            element.properties.setdefault("raw_metadata", {})[reference] = (
                source_metadata
            )
        ref_to_element[reference] = element.id
        claimed_element_ids.add(element.id)
        node_boxes = raw_boxes(reference, raw_item, page)
        add_raw_evidence(element, reference, raw_item, page, node_boxes)
        if not node_boxes:
            concern(
                "missing_node_geometry",
                "Raw graph node has no usable provenance bbox.",
                source_ref=reference,
            )
        return element

    # Nodes with explicit page provenance can be normalized eagerly. Defer
    # provenance-free children until their owner supplies a preferred page.
    for reference, raw_item in references.items():
        if _raw_page_index(raw_item) is not None:
            ensure_raw_element(reference)

    relationships_by_edge = {
        (
            relationship.type,
            relationship.source_id,
            relationship.target_id,
        ): relationship
        for relationship in working.relationships
    }
    existing_edges = set(relationships_by_edge)
    typed_adjacency: dict[RelationshipType, dict[str, set[str]]] = {}
    for relationship in working.relationships:
        typed_adjacency.setdefault(relationship.type, {}).setdefault(
            relationship.source_id, set()
        ).add(relationship.target_id)
    raw_edge_occurrences: set[tuple[str, str, str, str]] = set()
    contains_parents: dict[str, set[str]] = {}
    for relationship in working.relationships:
        if relationship.type is RelationshipType.CONTAINS:
            contains_parents.setdefault(relationship.target_id, set()).add(
                relationship.source_id
            )

    def typed_path_exists(
        relationship_type: RelationshipType,
        source_id: str,
        target_id: str,
    ) -> bool:
        adjacency = typed_adjacency.get(relationship_type, {})
        pending = [source_id]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(adjacency.get(current, set()))
        return False

    def merge_reference_metadata(
        relationship: RelationshipRecord,
        reference_metadata: Mapping[str, Any] | None,
    ) -> None:
        if not reference_metadata:
            return
        associations = relationship.metadata.setdefault("reference_metadata", [])
        association = deepcopy(dict(reference_metadata))
        if association not in associations:
            associations.append(association)

    def relation_for(
        field_name: str,
        target_item: Mapping[str, Any] | None,
    ) -> tuple[RelationshipType, bool]:
        relationship_type, child_is_source = _RAW_RELATION_FIELDS[field_name]
        if field_name != "children" or target_item is None:
            return relationship_type, child_is_source
        target_label = str(target_item.get("label") or "").casefold()
        if "caption" in target_label:
            return RelationshipType.CAPTION_OF, True
        if "footnote" in target_label:
            return RelationshipType.FOOTNOTE_OF, True
        if "source" in target_label and "note" in target_label:
            return RelationshipType.SOURCE_NOTE_OF, True
        return relationship_type, child_is_source

    def add_relationship(
        *,
        owner_ref: str,
        target_ref: str,
        field_name: str,
        relationship_type: RelationshipType,
        child_is_source: bool,
        reference_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        owner = ensure_raw_element(owner_ref)
        owner_page = (
            pages_by_id[owner.page_id].page_index if owner is not None else None
        )
        target = ensure_raw_element(
            target_ref,
            preferred_page=owner_page,
        )
        if owner is None or target is None:
            if target is None:
                concern(
                    "unresolved_relationship",
                    "A relationship target could not be resolved.",
                    source_ref=owner_ref,
                    target_ref=target_ref,
                    metadata={"field": field_name},
                )
            return
        occurrence = (
            owner_ref,
            field_name,
            target_ref,
            _canonical_json(reference_metadata or {}),
        )
        if occurrence in raw_edge_occurrences:
            concern(
                "duplicate_reference",
                "A raw owner repeats the same reference; one typed edge was retained.",
                source_ref=owner_ref,
                target_ref=target_ref,
                metadata={"field": field_name},
            )
            return
        raw_edge_occurrences.add(occurrence)
        source = target if child_is_source else owner
        destination = owner if child_is_source else target
        cross_page = source.page_id != destination.page_id
        cross_page_metadata = {
            "cross_page": True,
            "source_page": pages_by_id[source.page_id].page_index,
            "target_page": pages_by_id[destination.page_id].page_index,
        }
        if cross_page and relationship_type is not RelationshipType.REFERENCES:
            concern(
                "cross_page_relationship",
                "Cross-page ownership was not asserted; both nodes remain "
                "retained with a concern.",
                source_ref=owner_ref,
                target_ref=target_ref,
                metadata={
                    "field": field_name,
                    "source_page": pages_by_id[source.page_id].page_index,
                    "target_page": pages_by_id[destination.page_id].page_index,
                },
            )
            return
        edge = (relationship_type, source.id, destination.id)
        if edge in existing_edges:
            relationship = relationships_by_edge[edge]
            if cross_page:
                relationship.metadata.update(cross_page_metadata)
            relation_evidence = (
                source.evidence_ids if child_is_source else destination.evidence_ids
            )
            for evidence_id in relation_evidence:
                if evidence_id not in relationship.evidence_ids:
                    relationship.evidence_ids.append(evidence_id)
            merge_reference_metadata(
                relationship,
                reference_metadata,
            )
            return
        if source.id == destination.id:
            concern(
                "cyclic_reference",
                "A raw self-relationship was retained as a concern instead "
                "of an invalid graph edge.",
                source_ref=owner_ref,
                target_ref=target_ref,
                metadata={
                    "field": field_name,
                    "relationship_type": relationship_type.value,
                    "self_reference": True,
                },
            )
            return
        if relationship_type in _ACYCLIC_RELATIONSHIPS and typed_path_exists(
            relationship_type,
            destination.id,
            source.id,
        ):
            concern(
                "cyclic_reference",
                "A cyclic raw relationship was retained as a concern instead "
                "of an invalid graph edge.",
                source_ref=owner_ref,
                target_ref=target_ref,
                metadata={
                    "field": field_name,
                    "relationship_type": relationship_type.value,
                },
            )
            return
        if relationship_type is RelationshipType.CONTAINS:
            parents = contains_parents.setdefault(destination.id, set())
            if parents and source.id not in parents:
                concern(
                    "shared_child_reference",
                    "A child is referenced by multiple owners; all grounded "
                    "owners remain explicit.",
                    source_ref=owner_ref,
                    target_ref=target_ref,
                    metadata={"owner_count": len(parents) + 1},
                )
            parents.add(source.id)
        relation_evidence = (
            source.evidence_ids if child_is_source else destination.evidence_ids
        )
        relationship = RelationshipRecord(
            id=_stable_id(
                "rel",
                relationship_type.value,
                source.id,
                destination.id,
                field_name,
            ),
            type=relationship_type,
            source_id=source.id,
            target_id=destination.id,
            evidence_ids=list(relation_evidence),
            metadata={
                "field": field_name,
                "source_ref": owner_ref,
                "target_ref": target_ref,
                "normalization_origin": "docling_reference_graph",
                **(cross_page_metadata if cross_page else {}),
            },
        )
        merge_reference_metadata(relationship, reference_metadata)
        working.relationships.append(relationship)
        existing_edges.add(edge)
        relationships_by_edge[edge] = relationship
        typed_adjacency.setdefault(relationship_type, {}).setdefault(
            source.id, set()
        ).add(destination.id)

    def attach_to_root(
        element: ElementRecord,
        *,
        container_name: str,
        container_ref: str,
        child_index: int | None = None,
    ) -> None:
        roots = element.properties.setdefault("root_containers", [])
        for descriptor in roots:
            if descriptor.get("ref") != container_ref:
                continue
            if child_index is not None:
                descriptor["child_index"] = child_index
            return
        descriptor: dict[str, Any] = {
            "name": container_name,
            "ref": container_ref,
        }
        if child_index is not None:
            descriptor["child_index"] = child_index
        roots.append(descriptor)

    deferred_root_memberships: list[tuple[str, str, str]] = []
    for owner_ref, raw_item in references.items():
        for field_name in _RAW_RELATION_FIELDS:
            if field_name not in raw_item:
                continue
            for target_ref, reference_metadata in _raw_reference_entries(
                raw_item.get(field_name)
            ):
                relationship_type, child_is_source = relation_for(
                    field_name, references.get(target_ref)
                )
                add_relationship(
                    owner_ref=owner_ref,
                    target_ref=target_ref,
                    field_name=field_name,
                    relationship_type=relationship_type,
                    child_is_source=child_is_source,
                    reference_metadata=reference_metadata,
                )

        for (
            target_ref,
            relationship_type,
            child_is_source,
            field_path,
            reference_metadata,
        ) in _nested_raw_reference_entries(raw_item):
            add_relationship(
                owner_ref=owner_ref,
                target_ref=target_ref,
                field_name=field_path,
                relationship_type=relationship_type,
                child_is_source=child_is_source,
                reference_metadata=reference_metadata,
            )

        parent_ref = _raw_reference(raw_item.get("parent"))
        if parent_ref:
            root_container = root_containers.get(parent_ref)
            if root_container is not None:
                deferred_root_memberships.append(
                    (owner_ref, parent_ref, root_container[0])
                )
            else:
                add_relationship(
                    owner_ref=parent_ref,
                    target_ref=owner_ref,
                    field_name="parent",
                    relationship_type=RelationshipType.CONTAINS,
                    child_is_source=False,
                )

    # Root parent declarations are applied after all typed owner relationships
    # have supplied page context to provenance-free leaves.
    for owner_ref, container_ref, container_name in deferred_root_memberships:
        child = ensure_raw_element(owner_ref)
        if child is not None:
            attach_to_root(
                child,
                container_name=container_name,
                container_ref=container_ref,
            )

    # Docling's body and furniture containers are document roots rather than
    # page elements. Traverse their references explicitly so top-level nodes
    # cannot disappear merely because no collection node owns them.
    for container_ref, (container_name, container) in root_containers.items():
        if "children" in container:
            report_malformed_reference_values(
                container.get("children"),
                source_ref=container_ref,
                field_name="children",
            )
        seen_root_targets: set[str] = set()
        ordered_root_targets: list[tuple[str, ElementRecord]] = []
        for child_index, (
            target_ref,
            _reference_metadata,
        ) in enumerate(_raw_reference_entries(container.get("children"))):
            if target_ref in seen_root_targets:
                concern(
                    "duplicate_reference",
                    "A raw root container repeats the same child reference; "
                    "the association was retained once.",
                    source_ref=container_ref,
                    target_ref=target_ref,
                    metadata={
                        "field": "children",
                        "container": container_name,
                    },
                )
                continue
            seen_root_targets.add(target_ref)
            target = ensure_raw_element(target_ref)
            if target is None:
                concern(
                    "unresolved_relationship",
                    "A root-container child reference could not be resolved.",
                    source_ref=container_ref,
                    target_ref=target_ref,
                    metadata={
                        "field": "children",
                        "container": container_name,
                    },
                )
                continue
            attach_to_root(
                target,
                container_name=container_name,
                container_ref=container_ref,
                child_index=child_index,
            )
            ordered_root_targets.append((target_ref, target))

        for (
            source_ref,
            source_element,
        ), (
            target_ref,
            target_element,
        ) in zip(ordered_root_targets, ordered_root_targets[1:]):
            if source_element.page_id != target_element.page_id:
                continue
            add_relationship(
                owner_ref=source_ref,
                target_ref=target_ref,
                field_name=f"{container_name}.children.reading_order",
                relationship_type=RelationshipType.READING_BEFORE,
                child_is_source=False,
                reference_metadata={
                    "root_container": container_ref,
                    "source_child_index": next(
                        descriptor["child_index"]
                        for descriptor in source_element.properties["root_containers"]
                        if descriptor.get("ref") == container_ref
                    ),
                    "target_child_index": next(
                        descriptor["child_index"]
                        for descriptor in target_element.properties["root_containers"]
                        if descriptor.get("ref") == container_ref
                    ),
                },
            )

    return DocumentIR.model_validate(working.model_dump(mode="json"))


def project_legacy_pages(
    ir: DocumentIR,
    original_pages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Losslessly project primary IR elements back to public v1 pages."""

    elements = {element.id: element for element in ir.elements}
    projected: list[dict[str, Any]] = []
    page_records = ir.pages
    if len(page_records) != len(original_pages):
        raise ValueError("IR page count differs from the compatibility source")
    for page_record, original_page in zip(page_records, original_pages, strict=True):
        page = deepcopy(dict(original_page))
        primary: list[dict[str, Any]] = []
        for element_id in page_record.presentation_element_ids:
            element = elements[element_id]
            legacy_item = element.properties.get("legacy_item")
            if not isinstance(legacy_item, Mapping):
                raise ValueError(
                    f"primary element {element_id} has no legacy projection"
                )
            projected_item = deepcopy(dict(legacy_item))
            if element.visual_model_evidence is not None:
                projected_item["visual_model_evidence"] = (
                    element.visual_model_evidence.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                )
            primary.append(projected_item)
        page["items"] = primary
        projected.append(page)
    return projected


def round_trip_document(
    document: Any,
    *,
    raw_graph: Mapping[str, Any] | None = None,
    native_texts: Sequence[str] = (),
    font_audit: Mapping[str, Any] | None = None,
    font_recovery: Mapping[str, Any] | None = None,
    selective_span_ocr: Mapping[str, Any] | None = None,
    text_run_evidence: Mapping[str, Any] | None = None,
    form_evidence: Any | None = None,
    form_metrics: MutableMapping[str, float] | None = None,
    outline_evidence: Any | None = None,
    outline_metrics: MutableMapping[str, Any] | None = None,
    text_reconciliation_enabled: bool = False,
    layout_settings: Any | None = None,
    table_span_fidelity_enabled: bool = False,
    table_custody_runner: Any | None = None,
) -> tuple[dict[str, Any], DocumentIR]:
    """Build the IR and return its unchanged public-v1 compatibility view."""

    source = _as_mapping(document)
    output = deepcopy(dict(source))
    ir = build_document_ir(
        source,
        raw_graph=raw_graph,
        native_texts=native_texts,
        font_audit=font_audit,
        font_recovery=font_recovery,
        selective_span_ocr=selective_span_ocr,
    )
    detached_group_custody: Any | None = None
    if text_reconciliation_enabled:
        from app.services.text_reconciliation import reconcile_document_ir

        ir = reconcile_document_ir(ir)
    if table_span_fidelity_enabled and raw_graph is not None:
        from app.services.opaque_group_custody import (
            detach_opaque_group_edges,
            has_literal_table_marker,
        )

        if has_literal_table_marker(source):
            if table_custody_runner is None:
                ir, detached_group_custody = detach_opaque_group_edges(
                    ir,
                    raw_graph,
                )
            else:
                ir, detached_group_custody = table_custody_runner(
                    lambda deadline: detach_opaque_group_edges(
                        ir,
                        raw_graph,
                        deadline=deadline,
                    )
                )
    if layout_settings is not None:
        from app.services.layout import apply_layout_projection

        form_kwargs: dict[str, Any] = {}
        if form_evidence is not None or bool(
            getattr(layout_settings, "layout_forms_enabled", False)
        ):
            form_kwargs["form_evidence"] = form_evidence
            if form_metrics is not None:
                form_kwargs["form_metrics"] = form_metrics
        outline_kwargs: dict[str, Any] = {}
        if outline_evidence is not None or bool(
            getattr(
                layout_settings,
                "layout_outline_structure_enabled",
                False,
            )
        ):
            outline_kwargs["outline_evidence"] = outline_evidence
            if outline_metrics is not None:
                outline_kwargs["outline_metrics"] = outline_metrics
        ir = apply_layout_projection(
            ir,
            layout_settings,
            text_run_evidence=text_run_evidence,
            **form_kwargs,
            **outline_kwargs,
        )
    if detached_group_custody is not None and detached_group_custody.detached:
        from app.services.opaque_group_custody import (
            restore_diagnostic_group_edges,
        )

        if table_custody_runner is None:
            ir = restore_diagnostic_group_edges(ir, detached_group_custody)
        else:
            ir = table_custody_runner(
                lambda deadline: restore_diagnostic_group_edges(
                    ir,
                    detached_group_custody,
                    deadline=deadline,
                )
            )
    raw_pages = source.get("pages") or []
    output["pages"] = project_legacy_pages(ir, raw_pages)
    return output, ir
