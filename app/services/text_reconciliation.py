"""Bounded, source-attributable text-candidate reconciliation.

The policy in this module is intentionally conservative.  It can select only
an exact retained candidate string, treats extraction engines that consume one
asset as one observation, and returns a complete terminal trace for every
considered group.  Input validation and resource exhaustion are transactional:
callers must never apply a partial report.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


TEXT_RECONCILIATION_SCHEMA_VERSION = "1.0"
TEXT_RECONCILIATION_POLICY_ID = "text-reconciliation-v1"

MAX_RECONCILIATION_GROUPS = 512
MAX_CANDIDATES_PER_GROUP = 16
MAX_RECONCILIATION_CANDIDATES = 4_096
MAX_EVIDENCE_REFS_PER_CANDIDATE = 64
MAX_RECONCILIATION_TEXT_CODEPOINTS = 4_096
MAX_RECONCILIATION_CONCERNS = 512
MAX_RECONCILIATION_REPORT_BYTES = 8 * 1024 * 1024
MAX_RECONCILIATION_SECONDS = 2.0

MIN_OCR_CONFIDENCE = 0.90
MIN_RECIPROCAL_OVERLAP = 0.80
MIN_OWNER_TARGET_OVERLAP = 0.90
MIN_SELECTION_MARGIN = 0.10

# Compatibility names retained for early P02-US04 callers.
MAX_RECONCILIATION_CANDIDATES_PER_GROUP = MAX_CANDIDATES_PER_GROUP
MAX_RECONCILIATION_EVIDENCE_IDS = MAX_EVIDENCE_REFS_PER_CANDIDATE
OCR_CONFIDENCE_FLOOR = MIN_OCR_CONFIDENCE
CANDIDATE_TARGET_RECIPROCAL_OVERLAP = MIN_RECIPROCAL_OVERLAP
OWNER_TARGET_RECIPROCAL_OVERLAP = MIN_OWNER_TARGET_OVERLAP
MINIMUM_SELECTION_MARGIN = MIN_SELECTION_MARGIN

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SAFE_FONT_METHOD = "embedded_truetype_cmap_identity"
_OCR_METHOD = "selective_pdf_tesseract_tsv"
_UNSAFE_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_STRONG_SCRIPT_PREFIXES = (
    ("LATIN", "Latn"),
    ("GREEK", "Grek"),
    ("CYRILLIC", "Cyrl"),
    ("HEBREW", "Hebr"),
    ("ARABIC", "Arab"),
    ("DEVANAGARI", "Deva"),
    ("BENGALI", "Beng"),
    ("GURMUKHI", "Guru"),
    ("GUJARATI", "Gujr"),
    ("ORIYA", "Orya"),
    ("TAMIL", "Taml"),
    ("TELUGU", "Telu"),
    ("KANNADA", "Knda"),
    ("MALAYALAM", "Mlym"),
    ("THAI", "Thai"),
    ("LAO", "Laoo"),
    ("GEORGIAN", "Geor"),
    ("ARMENIAN", "Armn"),
    ("HANGUL", "Hang"),
    ("HIRAGANA", "Hira"),
    ("KATAKANA", "Kana"),
    ("CJK", "Hani"),
    ("IDEOGRAPH", "Hani"),
)
_LANGUAGE_SCRIPT_PREFIXES = {
    "Latn": ("eng", "fra", "deu", "spa", "ita", "por", "nld"),
    "Grek": ("ell",),
    "Cyrl": ("rus", "ukr", "bul", "srp"),
    "Hebr": ("heb",),
    "Arab": ("ara", "fas", "urd"),
    "Deva": ("hin", "mar", "nep", "san"),
    "Beng": ("ben",),
    "Guru": ("pan",),
    "Gujr": ("guj",),
    "Orya": ("ori",),
    "Taml": ("tam",),
    "Telu": ("tel",),
    "Knda": ("kan",),
    "Mlym": ("mal",),
    "Thai": ("tha",),
    "Laoo": ("lao",),
    "Geor": ("kat",),
    "Armn": ("hye",),
    "Hang": ("kor",),
    "Hira": ("jpn",),
    "Kana": ("jpn",),
    "Hani": ("chi", "jpn"),
}


class _IRAdapterLimit(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _IRAdapterBudget:
    """One aggregate resource budget for IR discovery, decision, and apply."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.clock = clock
        self.started = clock()
        self.deadline = self.started + MAX_RECONCILIATION_SECONDS
        self.group_count = 0
        self.candidate_count = 0

    def check(self) -> None:
        if self.clock() > self.deadline:
            raise _IRAdapterLimit("text_reconciliation_deadline")

    def reserve_group(self) -> None:
        self.check()
        self.group_count += 1
        if self.group_count > MAX_RECONCILIATION_GROUPS:
            raise _IRAdapterLimit("text_reconciliation_group_limit")

    def reserve_candidates(
        self,
        count: int,
        evidence_counts: Sequence[int],
    ) -> None:
        self.check()
        if count > MAX_CANDIDATES_PER_GROUP:
            raise _IRAdapterLimit(
                "text_reconciliation_candidate_per_group_limit"
            )
        if any(
            count > MAX_EVIDENCE_REFS_PER_CANDIDATE
            for count in evidence_counts
        ):
            raise _IRAdapterLimit(
                "text_reconciliation_evidence_reference_limit"
            )
        self.candidate_count += count
        if self.candidate_count > MAX_RECONCILIATION_CANDIDATES:
            raise _IRAdapterLimit("text_reconciliation_candidate_limit")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReconciliationBBox(_StrictModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"] = "pt"

    @model_validator(mode="after")
    def validate_finite(self) -> "ReconciliationBBox":
        if not all(
            math.isfinite(value)
            for value in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("reconciliation bbox values must be finite")
        return self


class TextCandidateProvenance(_StrictModel):
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    audit_source_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    recovery_source_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    selective_ocr_source_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    lineage_family: Literal[
        "pdf_text_layer",
        "embedded_font_program",
        "rendered_pixels",
    ]
    origin_asset_id: str = Field(min_length=1, max_length=256)
    method: str = Field(min_length=1, max_length=128)
    audit_finding_id: str | None = Field(default=None, max_length=256)
    audit_run_index: int | None = Field(default=None, ge=1)
    font_ref: str | None = Field(default=None, max_length=256)
    font_object_id: int | None = Field(default=None, ge=1)
    run_evidence_id: str | None = Field(default=None, max_length=256)
    selective_span_id: str | None = Field(default=None, max_length=256)
    selective_outcome_id: str | None = Field(default=None, max_length=256)
    recovery_refusal_reason_code: str | None = Field(
        default=None,
        max_length=256,
    )
    transform_valid: bool | None = None
    pass_completed: bool | None = None
    candidate_complete: bool | None = None
    word_count: int | None = Field(default=None, ge=0, le=2_048)
    retained_token_count: int | None = Field(
        default=None,
        ge=0,
        le=2_048,
    )
    candidate_truncated: bool = False
    token_truncated: bool = False
    malformed_output_concern: bool = False
    languages: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_lineage_shape(self) -> "TextCandidateProvenance":
        if len(self.languages) != len(set(self.languages)):
            raise ValueError("candidate provenance repeats a language")
        if any(not value or len(value) > 32 for value in self.languages):
            raise ValueError("candidate provenance language is invalid")

        font_fields = {
            "audit_source_sha256": self.audit_source_sha256,
            "recovery_source_sha256": self.recovery_source_sha256,
            "audit_finding_id": self.audit_finding_id,
            "audit_run_index": self.audit_run_index,
            "font_ref": self.font_ref,
            "font_object_id": self.font_object_id,
        }
        if self.lineage_family == "embedded_font_program":
            missing = [
                name for name, value in font_fields.items() if value is None
            ]
            if self.run_evidence_id is None:
                missing.append("run_evidence_id")
            if missing:
                raise ValueError(
                    "font provenance is incomplete: " + ", ".join(missing)
                )

        if self.lineage_family == "rendered_pixels":
            selective_fields = {
                **font_fields,
                "selective_ocr_source_sha256": (
                    self.selective_ocr_source_sha256
                ),
                "selective_span_id": self.selective_span_id,
                "selective_outcome_id": self.selective_outcome_id,
                "recovery_refusal_reason_code": (
                    self.recovery_refusal_reason_code
                ),
            }
            missing = [
                name
                for name, value in selective_fields.items()
                if value is None or value == ""
            ]
            if missing:
                raise ValueError(
                    "OCR provenance is incomplete: " + ", ".join(missing)
                )
            if not self.languages:
                raise ValueError("OCR provenance requires configured languages")
        return self


class TextCandidate(_StrictModel):
    candidate_id: str = Field(min_length=1, max_length=256)
    span_id: str = Field(min_length=1, max_length=256)
    page_index: int = Field(ge=1)
    # Pydantic's core ``str`` parser rejects a lone surrogate before policy
    # code can retain and mark it unsafe.  ``Any`` plus the strict validator
    # below keeps that evidence attributable without granting it authority.
    text: Any
    bbox: ReconciliationBBox
    source_kind: Literal[
        "native",
        "layout",
        "font_recovery",
        "selective_ocr",
    ]
    mapping_safety: Literal["healthy", "safe", "unsafe", "not_applicable"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(
        min_length=1,
        max_length=MAX_EVIDENCE_REFS_PER_CANDIDATE,
    )
    provenance: TextCandidateProvenance
    is_primary: bool = False

    @model_validator(mode="after")
    def validate_candidate(self) -> "TextCandidate":
        _require_text_value(self.text, allow_empty=False)
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("candidate repeats an evidence identity")
        if any(not value or len(value) > 256 for value in self.evidence_ids):
            raise ValueError("candidate evidence identity is invalid")
        expected_lineage = {
            "native": "pdf_text_layer",
            "layout": "pdf_text_layer",
            "font_recovery": "embedded_font_program",
            "selective_ocr": "rendered_pixels",
        }[self.source_kind]
        if self.provenance.lineage_family != expected_lineage:
            raise ValueError("candidate source kind contradicts its lineage")
        if (
            self.source_kind == "selective_ocr"
            and self.provenance.selective_span_id != self.span_id
        ):
            raise ValueError(
                "OCR selective span identity differs from candidate span"
            )
        return self


class TextCandidateGroup(_StrictModel):
    group_id: str = Field(min_length=1, max_length=256)
    span_id: str = Field(min_length=1, max_length=256)
    page_index: int = Field(ge=1)
    page_width_points: float = Field(gt=0)
    page_height_points: float = Field(gt=0)
    owner_element_id: str = Field(min_length=1, max_length=256)
    owner_text: Any
    owner_markdown: Any
    target_bbox: ReconciliationBBox
    owner_bbox: ReconciliationBBox
    replacement_original_text: Any
    expected_scripts: list[str] = Field(default_factory=list, max_length=16)
    candidates: list[TextCandidate] = Field(
        min_length=1,
        max_length=MAX_CANDIDATES_PER_GROUP,
    )

    @model_validator(mode="after")
    def validate_group(self) -> "TextCandidateGroup":
        _require_text_value(self.owner_text, allow_empty=True)
        _require_text_value(self.owner_markdown, allow_empty=True)
        _require_text_value(self.replacement_original_text, allow_empty=True)
        if not all(
            math.isfinite(value)
            for value in (self.page_width_points, self.page_height_points)
        ):
            raise ValueError("page dimensions must be finite")
        if len(self.expected_scripts) != len(set(self.expected_scripts)):
            raise ValueError("reconciliation group repeats an expected script")
        if any(not value or len(value) > 16 for value in self.expected_scripts):
            raise ValueError("reconciliation expected script is invalid")

        for bbox in (self.target_bbox, self.owner_bbox):
            _require_bbox_on_page(
                bbox,
                self.page_width_points,
                self.page_height_points,
            )
        candidate_ids = [row.candidate_id for row in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("reconciliation group repeats a candidate id")
        if sum(row.is_primary for row in self.candidates) > 1:
            raise ValueError("reconciliation group has multiple primaries")
        for candidate in self.candidates:
            if (
                candidate.span_id != self.span_id
                or candidate.page_index != self.page_index
            ):
                raise ValueError(
                    "candidate span/page identity differs from its group"
                )
            if (
                candidate.source_kind == "font_recovery"
                and candidate.provenance.run_evidence_id
                not in candidate.evidence_ids
                and self.group_id
                != f"font-group:{candidate.provenance.run_evidence_id}"
            ):
                raise ValueError(
                    "font run identity is neither retained evidence nor the "
                    "exact group identity"
                )
            _require_bbox_on_page(
                candidate.bbox,
                self.page_width_points,
                self.page_height_points,
            )
        return self


class TextCandidateComponentScores(_StrictModel):
    authority: float = Field(ge=0, le=1)
    independence: float = Field(ge=0, le=1)
    mapping_safety: float = Field(ge=0, le=1)
    geometry: float = Field(ge=0, le=1)
    replacement_scope: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    script: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_finite(self) -> "TextCandidateComponentScores":
        if not all(
            math.isfinite(value)
            for value in (
                self.authority,
                self.independence,
                self.mapping_safety,
                self.geometry,
                self.replacement_scope,
                self.completeness,
                self.script,
                self.confidence,
            )
        ):
            raise ValueError("component scores must be finite")
        return self


class TextCandidateDecision(_StrictModel):
    candidate_id: str = Field(min_length=1, max_length=256)
    text: Any
    bbox: ReconciliationBBox
    source_kind: Literal[
        "native",
        "layout",
        "font_recovery",
        "selective_ocr",
    ]
    mapping_safety: Literal["healthy", "safe", "unsafe", "not_applicable"]
    method: str = Field(min_length=1, max_length=128)
    lineage_family: Literal[
        "pdf_text_layer",
        "embedded_font_program",
        "rendered_pixels",
    ]
    origin_asset_id: str = Field(min_length=1, max_length=256)
    evidence_ids: list[str] = Field(
        min_length=1,
        max_length=MAX_EVIDENCE_REFS_PER_CANDIDATE,
    )
    confidence: float | None = Field(default=None, ge=0, le=1)
    eligible: bool
    selected: bool
    component_scores: TextCandidateComponentScores
    total_score: float | None = Field(default=None, ge=0, le=1)
    candidate_target_overlap: float = Field(ge=0, le=1)
    target_candidate_overlap: float = Field(ge=0, le=1)
    owner_target_overlap: float = Field(ge=0, le=1)
    target_owner_overlap: float = Field(ge=0, le=1)
    observed_scripts: list[str] = Field(max_length=16)
    independent_support_count: int = Field(ge=1, le=MAX_CANDIDATES_PER_GROUP)
    reason_codes: list[str] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_decision(self) -> "TextCandidateDecision":
        _require_text_value(self.text, allow_empty=False)
        if self.selected and not self.eligible:
            raise ValueError("an ineligible candidate cannot be selected")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("candidate decision repeats evidence")
        if self.reason_codes != sorted(set(self.reason_codes)):
            raise ValueError("candidate reason codes must be sorted and unique")
        if self.observed_scripts != sorted(set(self.observed_scripts)):
            raise ValueError("observed scripts must be sorted and unique")
        values = (
            self.total_score,
            self.candidate_target_overlap,
            self.target_candidate_overlap,
            self.owner_target_overlap,
            self.target_owner_overlap,
        )
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("candidate decision scores must be finite")
        return self


class TextReconciliationOutcome(_StrictModel):
    group_id: str = Field(min_length=1, max_length=256)
    span_id: str = Field(min_length=1, max_length=256)
    owner_element_id: str = Field(min_length=1, max_length=256)
    page_index: int = Field(ge=1)
    target_bbox: ReconciliationBBox
    rule_version: Literal["1.0"] = TEXT_RECONCILIATION_SCHEMA_VERSION
    status: Literal["selected", "unchanged", "unresolved"]
    reason_code: str = Field(min_length=1, max_length=256)
    selected_text: Any = None
    selected_candidate_ids: list[str] = Field(default_factory=list, max_length=1)
    margin: float | None = None
    replacement_mode: Literal["none", "whole_owner", "unique_substring"]
    decisions: list[TextCandidateDecision] = Field(
        min_length=1,
        max_length=MAX_CANDIDATES_PER_GROUP,
    )

    @model_validator(mode="after")
    def validate_outcome(self) -> "TextReconciliationOutcome":
        if self.selected_text is not None:
            _require_text_value(self.selected_text, allow_empty=False)
        candidate_ids = [row.candidate_id for row in self.decisions]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("outcome repeats a candidate decision")
        seen_evidence: set[str] = set()
        for decision in self.decisions:
            overlap = seen_evidence.intersection(decision.evidence_ids)
            if overlap:
                raise ValueError(
                    "outcome reuses evidence across candidate decisions"
                )
            seen_evidence.update(decision.evidence_ids)
        selected = [row for row in self.decisions if row.selected]
        if self.status == "unresolved":
            if (
                selected
                or self.selected_candidate_ids
                or self.selected_text is not None
                or self.replacement_mode != "none"
            ):
                raise ValueError(
                    "unresolved outcome cannot contain a selected candidate"
                )
        else:
            if len(selected) != 1:
                raise ValueError(
                    "selected outcome requires exactly one selected decision"
                )
            decision = selected[0]
            if (
                self.selected_candidate_ids != [decision.candidate_id]
                or self.selected_text != decision.text
            ):
                raise ValueError(
                    "selected outcome does not match its selected decision"
                )
            if self.status == "unchanged":
                if self.replacement_mode != "none":
                    raise ValueError(
                        "unchanged outcome cannot request replacement"
                    )
            elif self.replacement_mode == "none":
                raise ValueError(
                    "selected outcome requires a bounded replacement mode"
                )
        if self.margin is not None and not math.isfinite(self.margin):
            raise ValueError("outcome margin must be finite")
        return self


class TextReconciliationConcern(_StrictModel):
    code: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=500)
    group_id: str | None = Field(default=None, max_length=256)
    span_id: str | None = Field(default=None, max_length=256)
    owner_element_id: str | None = Field(default=None, max_length=256)
    page_index: int | None = Field(default=None, ge=1)
    candidate_ids: list[str] = Field(default_factory=list, max_length=16)


class TextReconciliationReport(_StrictModel):
    schema_version: Literal["1.0"] = TEXT_RECONCILIATION_SCHEMA_VERSION
    policy_id: Literal["text-reconciliation-v1"] = (
        TEXT_RECONCILIATION_POLICY_ID
    )
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    status: Literal["complete", "partial", "unavailable"]
    candidate_count: int = Field(ge=0, le=MAX_RECONCILIATION_CANDIDATES)
    group_count: int = Field(ge=0, le=MAX_RECONCILIATION_GROUPS)
    selected_count: int = Field(ge=0, le=MAX_RECONCILIATION_GROUPS)
    unresolved_count: int = Field(ge=0, le=MAX_RECONCILIATION_GROUPS)
    unchanged_count: int = Field(ge=0, le=MAX_RECONCILIATION_GROUPS)
    elapsed_ms: float = Field(ge=0)
    outcomes: list[TextReconciliationOutcome] = Field(
        max_length=MAX_RECONCILIATION_GROUPS
    )
    concerns: list[TextReconciliationConcern] = Field(
        max_length=MAX_RECONCILIATION_CONCERNS
    )

    @model_validator(mode="after")
    def validate_report(self) -> "TextReconciliationReport":
        if not math.isfinite(self.elapsed_ms):
            raise ValueError("report elapsed time must be finite")
        if len(self.outcomes) != self.group_count:
            raise ValueError("group_count differs from retained outcomes")
        if sum(len(row.decisions) for row in self.outcomes) != self.candidate_count:
            raise ValueError("candidate_count differs from retained decisions")
        counts = Counter(row.status for row in self.outcomes)
        if self.selected_count != counts["selected"]:
            raise ValueError("selected_count differs from outcomes")
        if self.unresolved_count != counts["unresolved"]:
            raise ValueError("unresolved_count differs from outcomes")
        if self.unchanged_count != counts["unchanged"]:
            raise ValueError("unchanged_count differs from outcomes")
        group_ids = [row.group_id for row in self.outcomes]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("report repeats a group identity")
        candidate_ids = [
            decision.candidate_id
            for outcome in self.outcomes
            for decision in outcome.decisions
        ]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("report replays a candidate identity")
        evidence_ids = [
            evidence_id
            for outcome in self.outcomes
            for decision in outcome.decisions
            for evidence_id in decision.evidence_ids
        ]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("report replays an evidence identity")
        if self.status != "complete" and self.outcomes:
            raise ValueError("non-complete report cannot expose decisions")
        return self


def _require_bbox_on_page(
    bbox: ReconciliationBBox,
    page_width: float,
    page_height: float,
) -> None:
    if (
        bbox.x < 0
        or bbox.y < 0
        or bbox.x + bbox.width > page_width + 1e-6
        or bbox.y + bbox.height > page_height + 1e-6
    ):
        raise ValueError("reconciliation bbox is outside its page")


def _require_text_value(value: Any, *, allow_empty: bool) -> None:
    if not isinstance(value, str):
        raise ValueError("reconciliation text must be a string")
    if (not allow_empty and not value) or (
        len(value) > MAX_RECONCILIATION_TEXT_CODEPOINTS
    ):
        raise ValueError("reconciliation text exceeds its strict bounds")


def _comparison_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _is_noncharacter(codepoint: int) -> bool:
    return (
        0xFDD0 <= codepoint <= 0xFDEF
        or codepoint & 0xFFFF in {0xFFFE, 0xFFFF}
    )


def _safe_text(value: str) -> bool:
    if not value or len(value) > MAX_RECONCILIATION_TEXT_CODEPOINTS:
        return False
    for character in value:
        if character in {"\n", "\r", "\t"}:
            return False
        if (
            unicodedata.category(character) in _UNSAFE_UNICODE_CATEGORIES
            or _is_noncharacter(ord(character))
        ):
            return False
    return True


def _strong_scripts(value: str) -> set[str]:
    scripts: set[str] = set()
    for character in unicodedata.normalize("NFC", value):
        if not character.isalpha():
            continue
        name = unicodedata.name(character, "")
        for prefix, script in _STRONG_SCRIPT_PREFIXES:
            if name.startswith(prefix):
                scripts.add(script)
                break
    return scripts


def _intersection_area(
    first: ReconciliationBBox,
    second: ReconciliationBBox,
) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    return max(right - left, 0.0) * max(bottom - top, 0.0)


def _directed_overlaps(
    first: ReconciliationBBox,
    second: ReconciliationBBox,
) -> tuple[float, float]:
    intersection = _intersection_area(first, second)
    return (
        min(
            max(intersection / (first.width * first.height), 0.0),
            1.0,
        ),
        min(
            max(intersection / (second.width * second.height), 0.0),
            1.0,
        ),
    )


def _lineage_key(candidate: TextCandidate) -> tuple[str, str]:
    return (
        candidate.provenance.lineage_family,
        candidate.provenance.origin_asset_id,
    )


def _source_bound(candidate: TextCandidate, source_sha256: str) -> bool:
    provenance = candidate.provenance
    identities = [
        provenance.source_sha256,
        provenance.audit_source_sha256,
        provenance.recovery_source_sha256,
        provenance.selective_ocr_source_sha256,
    ]
    return all(
        identity is None or identity == source_sha256 for identity in identities
    )


def _replacement_mode(
    group: TextCandidateGroup,
) -> Literal["whole_owner", "unique_substring"] | None:
    owner_target, target_owner = _directed_overlaps(
        group.owner_bbox,
        group.target_bbox,
    )
    if (
        owner_target + 1e-12 >= MIN_OWNER_TARGET_OVERLAP
        and target_owner + 1e-12 >= MIN_OWNER_TARGET_OVERLAP
    ):
        return "whole_owner"
    original = group.replacement_original_text
    if (
        original
        and original != group.owner_text
        and original != group.owner_markdown
        and group.owner_text.count(original) == 1
        and group.owner_markdown.count(original) == 1
    ):
        return "unique_substring"
    return None


def _script_supported(
    candidate: TextCandidate,
    group: TextCandidateGroup,
    observed: set[str],
) -> bool:
    if candidate.source_kind != "selective_ocr":
        return True
    expected = set(group.expected_scripts)
    if not expected or len(observed) > 1 or not observed.issubset(expected):
        return False
    languages = {
        value.casefold() for value in candidate.provenance.languages
    }
    scripts_to_check = observed or expected
    for script in scripts_to_check:
        prefixes = _LANGUAGE_SCRIPT_PREFIXES.get(script)
        if prefixes is None:
            return False
        if not any(
            language.startswith(prefix)
            for language in languages
            for prefix in prefixes
        ):
            return False
    return True


def _ocr_completeness_reasons(candidate: TextCandidate) -> list[str]:
    provenance = candidate.provenance
    reasons: list[str] = []
    if provenance.transform_valid is not True:
        reasons.append("transform_invalid")
    if provenance.pass_completed is not True:
        reasons.append("ocr_pass_incomplete")
    if provenance.candidate_complete is not True:
        reasons.append("ocr_candidate_incomplete")
    if provenance.candidate_truncated:
        reasons.append("ocr_candidate_truncated")
    if provenance.token_truncated:
        reasons.append("ocr_token_truncated")
    if provenance.malformed_output_concern:
        reasons.append("ocr_malformed_output_concern")
    if (
        provenance.word_count is None
        or provenance.word_count <= 0
        or provenance.retained_token_count != provenance.word_count
    ):
        reasons.append("ocr_token_count_mismatch")
    return reasons


def _support_counts(
    group: TextCandidateGroup,
) -> dict[str, int]:
    lineages_by_value: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for candidate in group.candidates:
        lineages_by_value[_comparison_text(candidate.text)].add(
            _lineage_key(candidate)
        )
    return {
        candidate.candidate_id: len(
            lineages_by_value[_comparison_text(candidate.text)]
        )
        for candidate in group.candidates
    }


def _candidate_trace(
    candidate: TextCandidate,
    group: TextCandidateGroup,
    source_sha256: str,
    support_count: int,
) -> TextCandidateDecision:
    candidate_target, target_candidate = _directed_overlaps(
        candidate.bbox,
        group.target_bbox,
    )
    owner_target, target_owner = _directed_overlaps(
        group.owner_bbox,
        group.target_bbox,
    )
    observed = _strong_scripts(candidate.text)
    source_ok = _source_bound(candidate, source_sha256)
    unicode_ok = _safe_text(candidate.text)
    geometry_ok = (
        candidate_target + 1e-12 >= MIN_RECIPROCAL_OVERLAP
        and target_candidate + 1e-12 >= MIN_RECIPROCAL_OVERLAP
    )
    mode = _replacement_mode(group)
    authoritative_native = bool(
        candidate.source_kind == "native"
        and candidate.is_primary
        and candidate.mapping_safety in {"healthy", "safe"}
    )
    replacement_ok = mode is not None or authoritative_native
    script_ok = _script_supported(candidate, group, observed)
    same_origin_count = sum(
        _lineage_key(row) == _lineage_key(candidate)
        for row in group.candidates
    )

    reasons: list[str] = []
    if not source_ok:
        reasons.append("source_mismatch")
    if not unicode_ok:
        reasons.append("unsafe_unicode")
    if not geometry_ok:
        reasons.append("reciprocal_overlap_below_minimum")
    if not replacement_ok:
        reasons.append("replacement_range_ambiguous")
    if not script_ok:
        reasons.append("script_unsupported")

    type_ok = False
    completeness = 1.0
    authority = 0.0
    confidence_score = candidate.confidence or 0.0
    mapping_score = {
        "healthy": 1.0,
        "safe": 1.0,
        "unsafe": 0.25,
        "not_applicable": 0.5,
    }[candidate.mapping_safety]

    if candidate.source_kind == "font_recovery":
        authority = 1.0
        confidence_score = 1.0
        type_ok = bool(
            candidate.mapping_safety == "safe"
            and candidate.provenance.method == _SAFE_FONT_METHOD
        )
        if candidate.mapping_safety != "safe":
            reasons.append("font_mapping_unsafe")
        if candidate.provenance.method != _SAFE_FONT_METHOD:
            reasons.append("font_method_unsupported")
    elif candidate.source_kind == "native":
        authority = 0.95 if authoritative_native else 0.20
        confidence_score = (
            candidate.confidence
            if candidate.confidence is not None
            else (1.0 if authoritative_native else 0.0)
        )
        type_ok = authoritative_native
        if not type_ok:
            reasons.append("native_mapping_unsafe")
    elif candidate.source_kind == "layout":
        authority = 0.10
        reasons.append("dependent_text_layer")
    else:
        authority = 0.80
        completeness_reasons = _ocr_completeness_reasons(candidate)
        reasons.extend(completeness_reasons)
        completeness = 0.0 if completeness_reasons else 1.0
        if candidate.provenance.method != _OCR_METHOD:
            reasons.append("ocr_method_unsupported")
        if candidate.mapping_safety not in {"unsafe", "not_applicable"}:
            reasons.append("ocr_mapping_contradictory")
        if candidate.confidence is None:
            reasons.append("ocr_confidence_missing")
        elif candidate.confidence + 1e-12 < MIN_OCR_CONFIDENCE:
            reasons.append("ocr_confidence_below_minimum")
        type_ok = bool(
            candidate.provenance.method == _OCR_METHOD
            and candidate.mapping_safety in {"unsafe", "not_applicable"}
            and candidate.confidence is not None
            and candidate.confidence + 1e-12 >= MIN_OCR_CONFIDENCE
            and not completeness_reasons
        )

    eligible = bool(
        source_ok
        and unicode_ok
        and geometry_ok
        and replacement_ok
        and script_ok
        and type_ok
    )
    if eligible:
        reasons.append(
            {
                "font_recovery": "deterministic_font_safe",
                "native": "healthy_native_authoritative",
                "selective_ocr": "eligible_independent_ocr",
            }[candidate.source_kind]
        )
    total_score = (
        1.0
        if eligible and candidate.source_kind == "font_recovery"
        else (
            0.95
            if eligible and candidate.source_kind == "native"
            else (
                float(candidate.confidence or 0.0)
                if eligible and candidate.source_kind == "selective_ocr"
                else 0.0
            )
        )
    )
    return TextCandidateDecision(
        candidate_id=candidate.candidate_id,
        text=candidate.text,
        bbox=candidate.bbox,
        source_kind=candidate.source_kind,
        mapping_safety=candidate.mapping_safety,
        method=candidate.provenance.method,
        lineage_family=candidate.provenance.lineage_family,
        origin_asset_id=candidate.provenance.origin_asset_id,
        evidence_ids=list(candidate.evidence_ids),
        confidence=candidate.confidence,
        eligible=eligible,
        selected=False,
        component_scores=TextCandidateComponentScores(
            authority=authority,
            independence=1.0 / same_origin_count,
            mapping_safety=mapping_score,
            geometry=min(candidate_target, target_candidate),
            replacement_scope=1.0 if replacement_ok else 0.0,
            completeness=completeness,
            script=1.0 if script_ok else 0.0,
            confidence=confidence_score,
        ),
        total_score=total_score,
        candidate_target_overlap=_bounded_round(candidate_target),
        target_candidate_overlap=_bounded_round(target_candidate),
        owner_target_overlap=_bounded_round(owner_target),
        target_owner_overlap=_bounded_round(target_owner),
        observed_scripts=sorted(observed),
        independent_support_count=support_count,
        reason_codes=sorted(set(reasons or ["ineligible_candidate"])),
    )


def _bounded_round(value: float) -> float:
    return min(max(round(value, 12), 0.0), 1.0)


def _concern(
    code: str,
    message: str,
    group: TextCandidateGroup | None = None,
    *,
    candidate_ids: Sequence[str] = (),
) -> TextReconciliationConcern:
    return TextReconciliationConcern(
        code=code,
        message=message,
        group_id=group.group_id if group is not None else None,
        span_id=group.span_id if group is not None else None,
        owner_element_id=(
            group.owner_element_id if group is not None else None
        ),
        page_index=group.page_index if group is not None else None,
        candidate_ids=sorted(set(candidate_ids))[
            :MAX_CANDIDATES_PER_GROUP
        ],
    )


def _group_concern(
    group: TextCandidateGroup,
    reason_code: str,
) -> TextReconciliationConcern:
    messages = {
        "source_mismatch": (
            "Candidate source identities differ from the document SHA-256."
        ),
        "contradictory_provenance": (
            "One span claims both successful deterministic font recovery and "
            "an upstream recovery refusal."
        ),
        "dependent_source_agreement": (
            "Multiple engines consumed one source asset and do not provide "
            "independent agreement."
        ),
        "low_margin_conflict": (
            "Competing candidates did not clear the required score margin."
        ),
        "partial_overlap_conflict": (
            "Candidate and target boxes did not clear reciprocal overlap."
        ),
        "mixed_script_conflict": (
            "Candidate script was mixed, unknown, or unsupported."
        ),
        "replacement_range_ambiguous": (
            "The owning replacement range was not uniquely attributable."
        ),
        "replacement_range_conflict": (
            "Multiple spans claimed one owner replacement range."
        ),
        "incomplete_evidence": (
            "Candidate extraction evidence was incomplete or truncated."
        ),
        "unsafe_unicode": (
            "Candidate text contains prohibited Unicode scalars."
        ),
        "ambiguous_conflict": (
            "Candidates remained ambiguous under the fixed policy."
        ),
    }
    return _concern(
        "text_reconciliation_" + reason_code,
        messages.get(reason_code, messages["ambiguous_conflict"]),
        group,
        candidate_ids=[row.candidate_id for row in group.candidates],
    )


def _terminal_outcome(
    group: TextCandidateGroup,
    traces: Sequence[TextCandidateDecision],
    *,
    status: Literal["selected", "unchanged", "unresolved"],
    reason_code: str,
    selected_candidate_id: str | None = None,
    margin: float | None = None,
) -> TextReconciliationOutcome:
    decisions = [
        trace.model_copy(
            update={
                "selected": trace.candidate_id == selected_candidate_id,
            }
        )
        for trace in traces
    ]
    selected = next(
        (
            trace
            for trace in decisions
            if trace.candidate_id == selected_candidate_id
        ),
        None,
    )
    if status != "unresolved" and selected is None:
        raise ValueError("terminal selection is absent from its group")
    mode = _replacement_mode(group)
    return TextReconciliationOutcome(
        group_id=group.group_id,
        span_id=group.span_id,
        owner_element_id=group.owner_element_id,
        page_index=group.page_index,
        target_bbox=group.target_bbox,
        status=status,
        reason_code=reason_code,
        selected_text=selected.text if selected is not None else None,
        selected_candidate_ids=(
            [selected.candidate_id] if selected is not None else []
        ),
        margin=margin,
        replacement_mode=(
            "none"
            if status in {"unchanged", "unresolved"}
            else (mode or "whole_owner")
        ),
        decisions=decisions,
    )


def _unique_best(
    candidates: Sequence[TextCandidate],
    traces: Mapping[str, TextCandidateDecision],
) -> TextCandidate | None:
    if not candidates:
        return None
    primaries = [row for row in candidates if row.is_primary]
    if len(primaries) == 1:
        return primaries[0]
    best_score = max(
        float(traces[row.candidate_id].total_score or 0.0)
        for row in candidates
    )
    best = [
        row
        for row in candidates
        if abs(
            float(traces[row.candidate_id].total_score or 0.0) - best_score
        )
        <= 1e-12
    ]
    if len(best) == 1:
        return best[0]
    exact_values = {row.text for row in best}
    return best[0] if len(best) == 1 and len(exact_values) == 1 else None


def _evaluate_group(
    group: TextCandidateGroup,
    source_sha256: str,
    *,
    replacement_range_conflict: bool,
) -> tuple[TextReconciliationOutcome, TextReconciliationConcern | None]:
    candidates = sorted(
        group.candidates,
        key=lambda row: row.candidate_id,
    )
    support_counts = _support_counts(group)
    decisions = [
        _candidate_trace(
            candidate,
            group,
            source_sha256,
            support_counts[candidate.candidate_id],
        )
        for candidate in candidates
    ]
    trace_by_id = {row.candidate_id: row for row in decisions}

    if any(not _source_bound(row, source_sha256) for row in candidates):
        reason = "source_mismatch"
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unresolved",
                reason_code=reason,
            ),
            _group_concern(group, reason),
        )

    if replacement_range_conflict:
        reason = "replacement_range_conflict"
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unresolved",
                reason_code=reason,
            ),
            _group_concern(group, reason),
        )

    safe_fonts = [
        row
        for row in candidates
        if row.source_kind == "font_recovery"
        and trace_by_id[row.candidate_id].eligible
    ]
    explicit_refused_ocr = [
        row
        for row in candidates
        if row.source_kind == "selective_ocr"
        and row.provenance.recovery_refusal_reason_code
    ]
    if safe_fonts and explicit_refused_ocr:
        reason = "contradictory_provenance"
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unresolved",
                reason_code=reason,
            ),
            _group_concern(group, reason),
        )

    safe_font_values = {
        _comparison_text(row.text) for row in safe_fonts
    }
    if len(safe_font_values) == 1 and safe_fonts:
        selected = _unique_best(safe_fonts, trace_by_id)
        if selected is not None:
            status: Literal["selected", "unchanged"] = (
                "unchanged"
                if selected.is_primary
                else "selected"
            )
            return (
                _terminal_outcome(
                    group,
                    decisions,
                    status=status,
                    reason_code="deterministic_font_evidence",
                    selected_candidate_id=selected.candidate_id,
                ),
                None,
            )
    if len(safe_font_values) > 1 or safe_fonts:
        reason = "ambiguous_conflict"
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unresolved",
                reason_code=reason,
            ),
            _group_concern(group, reason),
        )

    healthy_native = [
        row
        for row in candidates
        if row.source_kind == "native"
        and row.is_primary
        and trace_by_id[row.candidate_id].eligible
    ]
    if len(healthy_native) == 1:
        selected = healthy_native[0]
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unchanged",
                reason_code="healthy_native_authoritative",
                selected_candidate_id=selected.candidate_id,
            ),
            None,
        )
    if healthy_native:
        reason = "ambiguous_conflict"
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unresolved",
                reason_code=reason,
            ),
            _group_concern(group, reason),
        )

    eligible = [
        row for row in candidates if trace_by_id[row.candidate_id].eligible
    ]
    eligible_values_by_lineage: dict[tuple[str, str], set[str]] = defaultdict(
        set
    )
    for candidate in eligible:
        eligible_values_by_lineage[_lineage_key(candidate)].add(
            _comparison_text(candidate.text)
        )
    if any(
        len(values) > 1 for values in eligible_values_by_lineage.values()
    ):
        reason = "dependent_source_agreement"
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unresolved",
                reason_code=reason,
            ),
            _group_concern(group, reason),
        )

    agreement: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for candidate in eligible:
        agreement[_comparison_text(candidate.text)].add(
            _lineage_key(candidate)
        )
    independently_agreed = [
        value for value, sources in agreement.items() if len(sources) >= 2
    ]
    if len(independently_agreed) == 1:
        matches = [
            row
            for row in eligible
            if _comparison_text(row.text) == independently_agreed[0]
        ]
        selected = _unique_best(matches, trace_by_id)
        if selected is not None:
            return (
                _terminal_outcome(
                    group,
                    decisions,
                    status=(
                        "unchanged" if selected.is_primary else "selected"
                    ),
                    reason_code="independent_exact_agreement",
                    selected_candidate_id=selected.candidate_id,
                ),
                None,
            )
    if len(independently_agreed) > 1 or independently_agreed:
        reason = "ambiguous_conflict"
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unresolved",
                reason_code=reason,
            ),
            _group_concern(group, reason),
        )

    eligible_ocr = [
        row for row in eligible if row.source_kind == "selective_ocr"
    ]
    observations: dict[tuple[str, str, str], TextCandidate] = {}
    for candidate in eligible_ocr:
        key = (*_lineage_key(candidate), _comparison_text(candidate.text))
        current = observations.get(key)
        current_score = (
            float(trace_by_id[current.candidate_id].total_score or 0.0)
            if current is not None
            else -1.0
        )
        candidate_score = float(
            trace_by_id[candidate.candidate_id].total_score or 0.0
        )
        if candidate_score > current_score + 1e-12:
            observations[key] = candidate
        elif (
            abs(candidate_score - current_score) <= 1e-12
            and current is not None
            and candidate.candidate_id < current.candidate_id
        ):
            # Equal text from the same retained source asset is one
            # observation.  Keep one stable representative so adding another
            # engine/pass duplicate cannot toggle the terminal outcome.
            observations[key] = candidate

    ranked = sorted(
        observations.values(),
        key=lambda row: -float(
            trace_by_id[row.candidate_id].total_score or 0.0
        ),
    )
    if ranked:
        top = ranked[0]
        top_score = float(trace_by_id[top.candidate_id].total_score or 0.0)
        runner_score = (
            float(trace_by_id[ranked[1].candidate_id].total_score or 0.0)
            if len(ranked) > 1
            else 0.0
        )
        margin = top_score - runner_score
        tied_values = {
            _comparison_text(row.text)
            for row in ranked
            if abs(
                float(trace_by_id[row.candidate_id].total_score or 0.0)
                - top_score
            )
            <= 1e-12
        }
        if (
            len(tied_values) == 1
            and margin + 1e-12 >= MIN_SELECTION_MARGIN
        ):
            return (
                _terminal_outcome(
                    group,
                    decisions,
                    status="selected",
                    reason_code="independent_high_confidence_ocr",
                    selected_candidate_id=top.candidate_id,
                    margin=round(margin, 12),
                ),
                None,
            )
        reason = "low_margin_conflict"
        return (
            _terminal_outcome(
                group,
                decisions,
                status="unresolved",
                reason_code=reason,
                margin=round(margin, 12),
            ),
            _group_concern(group, reason),
        )

    decision_reasons = {
        reason
        for decision in decisions
        for reason in decision.reason_codes
    }
    if "replacement_range_ambiguous" in decision_reasons:
        reason = "replacement_range_ambiguous"
    elif "reciprocal_overlap_below_minimum" in decision_reasons:
        reason = "partial_overlap_conflict"
    elif "script_unsupported" in decision_reasons:
        reason = "mixed_script_conflict"
    elif "unsafe_unicode" in decision_reasons:
        reason = "unsafe_unicode"
    elif any(
        value.startswith(("ocr_", "transform_"))
        for value in decision_reasons
        if value
        not in {
            "ocr_confidence_below_minimum",
            "ocr_confidence_missing",
            "ocr_method_unsupported",
            "ocr_mapping_contradictory",
        }
    ):
        reason = "incomplete_evidence"
    elif _dependent_origins(group):
        reason = "dependent_source_agreement"
    else:
        reason = "ambiguous_conflict"
    return (
        _terminal_outcome(
            group,
            decisions,
            status="unresolved",
            reason_code=reason,
        ),
        _group_concern(group, reason),
    )


def _dependent_origins(group: TextCandidateGroup) -> list[str]:
    counts = Counter(
        row.provenance.origin_asset_id for row in group.candidates
    )
    return sorted(value for value, count in counts.items() if count > 1)


def _raw_identity_concern(
    code: str,
    message: str,
    raw_group: Any = None,
) -> TextReconciliationConcern:
    group_id = span_id = owner_element_id = None
    page_index = None
    candidate_ids: list[str] = []
    if isinstance(raw_group, Mapping):
        group_id = str(raw_group.get("group_id") or "") or None
        span_id = str(raw_group.get("span_id") or "") or None
        owner_element_id = (
            str(raw_group.get("owner_element_id") or "") or None
        )
        raw_page = raw_group.get("page_index")
        if (
            isinstance(raw_page, int)
            and not isinstance(raw_page, bool)
            and raw_page >= 1
        ):
            page_index = raw_page
        rows = raw_group.get("candidates")
        if isinstance(rows, Sequence) and not isinstance(
            rows,
            (str, bytes, bytearray),
        ):
            candidate_ids = [
                str(row.get("candidate_id"))
                for row in rows
                if isinstance(row, Mapping) and row.get("candidate_id")
            ][:MAX_CANDIDATES_PER_GROUP]
    return TextReconciliationConcern(
        code=code,
        message=message,
        group_id=group_id,
        span_id=span_id,
        owner_element_id=owner_element_id,
        page_index=page_index,
        candidate_ids=candidate_ids,
    )


def _report(
    *,
    source_sha256: str,
    status: Literal["complete", "partial", "unavailable"],
    started: float,
    clock: Callable[[], float],
    outcomes: Sequence[TextReconciliationOutcome] = (),
    concerns: Sequence[TextReconciliationConcern] = (),
) -> TextReconciliationReport:
    counts = Counter(row.status for row in outcomes)
    return TextReconciliationReport(
        source_sha256=source_sha256,
        status=status,
        candidate_count=sum(len(row.decisions) for row in outcomes),
        group_count=len(outcomes),
        selected_count=counts["selected"],
        unresolved_count=counts["unresolved"],
        unchanged_count=counts["unchanged"],
        elapsed_ms=max((clock() - started) * 1_000.0, 0.0),
        outcomes=list(outcomes),
        concerns=list(concerns)[:MAX_RECONCILIATION_CONCERNS],
    )


def _raw_cross_page(raw_group: Any) -> bool:
    if not isinstance(raw_group, Mapping):
        return False
    page_index = raw_group.get("page_index")
    rows = raw_group.get("candidates")
    if not isinstance(rows, Sequence) or isinstance(
        rows,
        (str, bytes, bytearray),
    ):
        return False
    return any(
        isinstance(row, Mapping) and row.get("page_index") != page_index
        for row in rows
    )


def _replacement_range_conflicts(
    groups: Sequence[TextCandidateGroup],
) -> set[str]:
    claims: dict[
        str,
        list[tuple[int, int, TextCandidateGroup]],
    ] = defaultdict(list)
    for group in groups:
        if any(
            candidate.is_primary
            and (
                (
                    candidate.source_kind == "native"
                    and candidate.mapping_safety in {"healthy", "safe"}
                )
                or (
                    candidate.source_kind == "font_recovery"
                    and candidate.mapping_safety == "safe"
                    and candidate.provenance.method == _SAFE_FONT_METHOD
                )
            )
            for candidate in group.candidates
        ):
            # The authoritative value is already primary; evaluating this
            # group can only yield ``unchanged`` and cannot claim a mutation
            # range against another span on the same owner.
            continue
        mode = _replacement_mode(group)
        if mode == "whole_owner":
            claims[group.owner_element_id].append(
                (0, max(len(group.owner_text), 1), group)
            )
        elif mode == "unique_substring":
            start = group.owner_text.index(group.replacement_original_text)
            claims[group.owner_element_id].append(
                (
                    start,
                    start + len(group.replacement_original_text),
                    group,
                )
            )

    conflicts: set[str] = set()
    for owner_claims in claims.values():
        owner_values = {claim[2].owner_text for claim in owner_claims}
        if len(owner_values) != 1:
            conflicts.update(claim[2].group_id for claim in owner_claims)
            continue
        ordered = sorted(
            owner_claims,
            key=lambda claim: (claim[0], claim[1], claim[2].group_id),
        )
        active: list[tuple[int, int, TextCandidateGroup]] = []
        for claim in ordered:
            start, end, group = claim
            active = [row for row in active if row[1] > start]
            for _other_start, _other_end, other_group in active:
                conflicts.add(group.group_id)
                conflicts.add(other_group.group_id)
            active.append((start, end, group))
    return conflicts


def reconcile_text_candidates(
    groups: Sequence[TextCandidateGroup | Mapping[str, Any]],
    *,
    source_sha256: str,
    clock: Callable[[], float] = time.perf_counter,
    _started: float | None = None,
) -> TextReconciliationReport:
    """Return strict terminal decisions without mutating caller input."""

    started = clock() if _started is None else _started
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(value not in "0123456789abcdef" for value in source_sha256)
    ):
        raise ValueError("source_sha256 must be a lowercase SHA-256 identity")
    if not isinstance(groups, Sequence) or isinstance(
        groups,
        (str, bytes, bytearray),
    ):
        return _report(
            source_sha256=source_sha256,
            status="unavailable",
            started=started,
            clock=clock,
            concerns=[
                _raw_identity_concern(
                    "text_reconciliation_invalid_input",
                    "Reconciliation groups must be a bounded sequence.",
                )
            ],
        )

    raw_groups = list(groups)
    if len(raw_groups) > MAX_RECONCILIATION_GROUPS:
        return _report(
            source_sha256=source_sha256,
            status="partial",
            started=started,
            clock=clock,
            concerns=[
                _raw_identity_concern(
                    "text_reconciliation_group_limit",
                    "Reconciliation groups exceeded the document bound.",
                )
            ],
        )

    concerns: list[TextReconciliationConcern] = []
    validated: list[TextCandidateGroup] = []
    for raw_group in raw_groups:
        if clock() - started > MAX_RECONCILIATION_SECONDS:
            return _report(
                source_sha256=source_sha256,
                status="partial",
                started=started,
                clock=clock,
                concerns=[
                    _raw_identity_concern(
                        "text_reconciliation_deadline",
                        "Reconciliation exceeded its document deadline.",
                    )
                ],
            )
        if _raw_cross_page(raw_group):
            concerns.append(
                _raw_identity_concern(
                    "text_reconciliation_cross_page_candidate",
                    "A candidate page differs from its owning group.",
                    raw_group,
                )
            )
            continue
        try:
            group = (
                raw_group
                if isinstance(raw_group, TextCandidateGroup)
                else TextCandidateGroup.model_validate(dict(raw_group))
            )
        except (TypeError, ValueError, ValidationError) as exc:
            concerns.append(
                _raw_identity_concern(
                    "text_reconciliation_invalid_group",
                    "Reconciliation group failed strict validation: "
                    f"{type(exc).__name__}.",
                    raw_group,
                )
            )
            continue
        validated.append(group)

    group_ids: set[str] = set()
    candidate_ids: set[str] = set()
    evidence_ids: set[str] = set()
    total_candidates = 0
    for group in validated:
        if group.group_id in group_ids:
            concerns.append(
                _concern(
                    "text_reconciliation_duplicate_group_id",
                    "A reconciliation group identity was repeated.",
                    group,
                )
            )
        group_ids.add(group.group_id)
        total_candidates += len(group.candidates)
        for candidate in group.candidates:
            if candidate.candidate_id in candidate_ids:
                concerns.append(
                    _concern(
                        "text_reconciliation_replayed_candidate_id",
                        "A candidate identity was replayed across groups.",
                        group,
                        candidate_ids=[candidate.candidate_id],
                    )
                )
            candidate_ids.add(candidate.candidate_id)
            for evidence_id in candidate.evidence_ids:
                if evidence_id in evidence_ids:
                    concerns.append(
                        _concern(
                            "text_reconciliation_replayed_evidence_id",
                            "An evidence identity was replayed across candidates.",
                            group,
                            candidate_ids=[candidate.candidate_id],
                        )
                    )
                evidence_ids.add(evidence_id)
    if total_candidates > MAX_RECONCILIATION_CANDIDATES:
        concerns.append(
            _raw_identity_concern(
                "text_reconciliation_candidate_limit",
                "Reconciliation candidates exceeded the document bound.",
            )
        )

    try:
        input_size = len(
            json.dumps(
                [
                    group.model_dump(mode="json", exclude_none=True)
                    for group in validated
                ],
                # Escaping here lets prohibited lone surrogates remain
                # attributable alternatives instead of turning a safe
                # unresolved decision into an input-serialization failure.
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        input_size = MAX_RECONCILIATION_REPORT_BYTES + 1
    if input_size > MAX_RECONCILIATION_REPORT_BYTES:
        return _report(
            source_sha256=source_sha256,
            status="partial",
            started=started,
            clock=clock,
            concerns=[
                _raw_identity_concern(
                    "text_reconciliation_output_limit",
                    "Reconciliation input exceeds the report-size budget.",
                )
            ],
        )
    source_mismatches = [
        group
        for group in validated
        if any(
            not _source_bound(candidate, source_sha256)
            for candidate in group.candidates
        )
    ]
    for group in source_mismatches:
        concerns.append(
            _concern(
                "text_reconciliation_source_mismatch",
                "Candidate lineage is bound to a different source PDF.",
                group,
                candidate_ids=[
                    candidate.candidate_id
                    for candidate in group.candidates
                    if not _source_bound(candidate, source_sha256)
                ],
            )
        )
    if concerns:
        return _report(
            source_sha256=source_sha256,
            status="partial",
            started=started,
            clock=clock,
            concerns=concerns,
        )

    range_conflicts = _replacement_range_conflicts(validated)
    outcomes: list[TextReconciliationOutcome] = []
    outcome_concerns: list[TextReconciliationConcern] = []
    for group in sorted(
        validated,
        key=lambda row: (row.page_index, row.group_id),
    ):
        if clock() - started > MAX_RECONCILIATION_SECONDS:
            return _report(
                source_sha256=source_sha256,
                status="partial",
                started=started,
                clock=clock,
                concerns=[
                    _raw_identity_concern(
                        "text_reconciliation_deadline",
                        "Reconciliation exceeded its document deadline.",
                    )
                ],
            )
        outcome, concern = _evaluate_group(
            group,
            source_sha256,
            replacement_range_conflict=group.group_id in range_conflicts,
        )
        outcomes.append(outcome)
        if concern is not None:
            outcome_concerns.append(concern)

    report = _report(
        source_sha256=source_sha256,
        status="complete",
        started=started,
        clock=clock,
        outcomes=outcomes,
        concerns=outcome_concerns,
    )
    serialized_report = json.dumps(
        report.model_dump(mode="json", exclude_none=True),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(serialized_report) > MAX_RECONCILIATION_REPORT_BYTES:
        return _report(
            source_sha256=source_sha256,
            status="partial",
            started=started,
            clock=clock,
            concerns=[
                _raw_identity_concern(
                    "text_reconciliation_output_limit",
                    "Reconciliation report exceeded its serialized bound.",
                )
            ],
        )
    return report


def stable_reconciliation_sha256(
    report: TextReconciliationReport,
) -> str:
    """Hash a reconciliation report without its measured elapsed time."""

    payload = report.model_dump(mode="json", exclude_none=True)
    payload["elapsed_ms"] = 0.0
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ir_stable_id(prefix: str, *parts: Any) -> str:
    encoded = json.dumps(
        parts,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _retained_ir_stable_id(prefix: str, *parts: Any) -> str:
    """Reproduce the identity scheme used by the retained v1 IR."""

    encoded = json.dumps(
        parts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _ir_raw_bbox(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        width = float(value.get("width", value.get("w")))
        height = float(value.get("height", value.get("h")))
        result = {
            "x": float(value["x"]),
            "y": float(value["y"]),
            "width": width,
            "height": height,
            "unit": "pt",
        }
        ReconciliationBBox.model_validate(result)
    except (KeyError, TypeError, ValueError, ValidationError):
        return None
    return result


def _ir_element_bbox(
    element: Any,
    boxes: Mapping[str, Any],
    coordinates: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not element.bbox_ids:
        return None
    box = boxes.get(element.bbox_ids[0])
    if box is None:
        return None
    coordinate = coordinates.get(box.coordinate_system_id)
    if coordinate is None or coordinate.transform_to_page is None:
        return None
    a, b, c, d, e, f = coordinate.transform_to_page
    corners = (
        (box.x, box.y),
        (box.x + box.width, box.y),
        (box.x, box.y + box.height),
        (box.x + box.width, box.y + box.height),
    )
    transformed = [
        (a * x + c * y + e, b * x + d * y + f)
        for x, y in corners
    ]
    xs = [value[0] for value in transformed]
    ys = [value[1] for value in transformed]
    return _ir_raw_bbox(
        {
            "x": min(xs),
            "y": min(ys),
            "width": max(xs) - min(xs),
            "height": max(ys) - min(ys),
        }
    )


def _ir_evidence_bbox(
    evidence: Any,
    boxes: Mapping[str, Any],
    coordinates: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not evidence.bbox_id:
        return None
    shell = type("_EvidenceBox", (), {"bbox_ids": [evidence.bbox_id]})()
    return _ir_element_bbox(shell, boxes, coordinates)


def _ir_page_geometry(
    ir: Any,
    page: Any,
    boxes: Mapping[str, Any],
    coordinates: Mapping[str, Any],
    regions: Mapping[str, Any] | None = None,
) -> tuple[float, float, dict[str, Any]] | None:
    region_index = (
        regions
        if regions is not None
        else {region.id: region for region in ir.regions}
    )
    for region_id in page.region_ids:
        region = region_index.get(region_id)
        if region is None or region.role != "page":
            continue
        box = boxes.get(region.bbox_id)
        if box is None:
            continue
        shell = type("_PageBox", (), {"bbox_ids": [box.id]})()
        payload = _ir_element_bbox(shell, boxes, coordinates)
        if payload is not None:
            return (
                float(payload["width"]),
                float(payload["height"]),
                payload,
            )
    return None


def _ir_same_bbox(first: Any, second: Any) -> bool:
    left = _ir_raw_bbox(first)
    right = _ir_raw_bbox(second)
    if left is None or right is None:
        return False
    return all(
        abs(float(left[key]) - float(right[key])) <= 1e-6
        for key in ("x", "y", "width", "height")
    )


def _ir_bbox_key(value: Any) -> tuple[float, float, float, float] | None:
    bbox = _ir_raw_bbox(value)
    if bbox is None:
        return None
    return tuple(
        round(float(bbox[field]), 6)
        for field in ("x", "y", "width", "height")
    )


def _ir_ocr_geometry_valid(
    cost: Mapping[str, Any],
    attempt: Mapping[str, Any],
    *,
    source_bbox: Mapping[str, Any],
    page_width: float,
    page_height: float,
) -> bool:
    try:
        crop_to_page = tuple(
            float(value) for value in cost["crop_to_page_transform"]
        )
        page_to_crop = tuple(
            float(value) for value in cost["page_to_crop_transform"]
        )
        pixel_width = int(cost["pixel_width"])
        pixel_height = int(cost["pixel_height"])
        pixel_count = int(cost["pixel_count"])
        padding = float(cost["padding_points"])
        cost_page_width = float(cost["page_width_points"])
        cost_page_height = float(cost["page_height_points"])
        attempt_pixel_width = int(attempt["actual_pixel_width"])
        attempt_pixel_height = int(attempt["actual_pixel_height"])
        attempt_pixel_count = int(attempt["actual_pixel_count"])
        attempt_page_width = float(attempt["page_width_points"])
        attempt_page_height = float(attempt["page_height_points"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if (
        len(crop_to_page) != 6
        or len(page_to_crop) != 6
        or not all(
            math.isfinite(value)
            for value in (*crop_to_page, *page_to_crop)
        )
        or pixel_width <= 0
        or pixel_height <= 0
        or pixel_count != pixel_width * pixel_height
        or not math.isfinite(padding)
        or padding < 0
        or abs(cost_page_width - page_width) > 1e-6
        or abs(cost_page_height - page_height) > 1e-6
    ):
        return False

    def compose(
        outer: tuple[float, ...],
        inner: tuple[float, ...],
    ) -> tuple[float, ...]:
        a, b, c, d, e, f = outer
        g, h, i, j, k, l = inner
        return (
            a * g + c * h,
            b * g + d * h,
            a * i + c * j,
            b * i + d * j,
            a * k + c * l + e,
            b * k + d * l + f,
        )

    identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if any(
        abs(value - expected) > 1e-6
        for value, expected in zip(
            compose(crop_to_page, page_to_crop),
            identity,
            strict=True,
        )
    ) or any(
        abs(value - expected) > 1e-6
        for value, expected in zip(
            compose(page_to_crop, crop_to_page),
            identity,
            strict=True,
        )
    ):
        return False

    a, b, c, d, e, f = crop_to_page
    corners = (
        (0.0, 0.0),
        (float(pixel_width), 0.0),
        (0.0, float(pixel_height)),
        (float(pixel_width), float(pixel_height)),
    )
    mapped = [
        (a * x + c * y + e, b * x + d * y + f)
        for x, y in corners
    ]
    mapped_x = [value[0] for value in mapped]
    mapped_y = [value[1] for value in mapped]
    realized = {
        "x": min(mapped_x),
        "y": min(mapped_y),
        "width": max(mapped_x) - min(mapped_x),
        "height": max(mapped_y) - min(mapped_y),
        "unit": "pt",
    }
    retained_realized = _ir_raw_bbox(cost.get("realized_crop_bbox"))
    if (
        retained_realized is None
        or not _ir_same_bbox(realized, retained_realized)
        or not _ir_same_bbox(
            retained_realized,
            attempt.get("realized_crop_bbox"),
        )
    ):
        return False
    source = _ir_raw_bbox(source_bbox)
    if source is None:
        return False
    source_covered, _crop_covered = _directed_overlaps(
        ReconciliationBBox.model_validate(source),
        ReconciliationBBox.model_validate(retained_realized),
    )
    return bool(
        source_covered + 1e-12 >= 1.0
        and attempt_pixel_width == pixel_width
        and attempt_pixel_height == pixel_height
        and attempt_pixel_count == pixel_count
        and abs(attempt_page_width - page_width) <= 1e-6
        and abs(attempt_page_height - page_height) <= 1e-6
    )


def _ir_pixel_bbox_matches_page(
    pixel_bbox: Any,
    page_bbox: Any,
    cost: Mapping[str, Any],
) -> bool:
    if not isinstance(pixel_bbox, Mapping):
        return False
    page = _ir_raw_bbox(page_bbox)
    if page is None:
        return False
    try:
        x = float(pixel_bbox["x"])
        y = float(pixel_bbox["y"])
        width = float(pixel_bbox.get("w", pixel_bbox.get("width")))
        height = float(pixel_bbox.get("h", pixel_bbox.get("height")))
        pixel_width = float(cost["pixel_width"])
        pixel_height = float(cost["pixel_height"])
        a, b, c, d, e, f = tuple(
            float(value) for value in cost["crop_to_page_transform"]
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if (
        not all(
            math.isfinite(value)
            for value in (
                x,
                y,
                width,
                height,
                pixel_width,
                pixel_height,
                a,
                b,
                c,
                d,
                e,
                f,
            )
        )
        or width <= 0
        or height <= 0
        or x < -0.01
        or y < -0.01
        or x + width > pixel_width + 0.01
        or y + height > pixel_height + 0.01
    ):
        return False
    corners = (
        (x, y),
        (x + width, y),
        (x, y + height),
        (x + width, y + height),
    )
    mapped = [
        (a * px + c * py + e, b * px + d * py + f)
        for px, py in corners
    ]
    expected = {
        "x": min(value[0] for value in mapped),
        "y": min(value[1] for value in mapped),
        "width": max(value[0] for value in mapped)
        - min(value[0] for value in mapped),
        "height": max(value[1] for value in mapped)
        - min(value[1] for value in mapped),
    }
    return all(
        abs(float(expected[field]) - float(page[field])) <= 0.01
        for field in ("x", "y", "width", "height")
    )


def _ir_build_lineage_index(
    ir: Any,
    budget: _IRAdapterBudget,
) -> dict[str, Any]:
    audit_exact: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(
        list
    )
    audit_by_font: dict[
        tuple[int, str, int],
        list[tuple[dict[str, Any], dict[str, Any]]],
    ] = defaultdict(list)
    refusals: set[tuple[int, str, int, str]] = set()
    candidate_registry: dict[str, list[Any]] = defaultdict(list)
    malformed_spans: set[str] = set()
    global_selective_malformed = False
    audit_run_count = 0

    for concern in ir.concerns:
        budget.check()
        if concern.code in {
            "pdf_font_mapping_suspicious",
            "pdf_font_mapping_unresolved",
        }:
            finding = concern.metadata.get("finding")
            if not isinstance(finding, Mapping):
                continue
            font_ref = str(finding.get("font_ref") or "")
            font_object_id = finding.get("font_object_id")
            raw_runs = finding.get("runs") or []
            if (
                not font_ref
                or isinstance(font_object_id, bool)
                or not isinstance(font_object_id, int)
                or not isinstance(raw_runs, Sequence)
                or isinstance(raw_runs, (str, bytes, bytearray))
            ):
                continue
            for run_index, raw_run in enumerate(raw_runs, 1):
                budget.check()
                audit_run_count += 1
                if audit_run_count > MAX_RECONCILIATION_GROUPS:
                    raise _IRAdapterLimit(
                        "text_reconciliation_audit_run_limit"
                    )
                if not isinstance(raw_run, Mapping):
                    continue
                page_index = raw_run.get("page_index")
                bbox = _ir_raw_bbox(raw_run.get("bbox"))
                bbox_key = _ir_bbox_key(bbox)
                if (
                    isinstance(page_index, bool)
                    or not isinstance(page_index, int)
                    or bbox is None
                    or bbox_key is None
                ):
                    continue
                identity = {
                    "source_sha256": concern.metadata.get(
                        "source_sha256"
                    ),
                    "audit_finding_id": _ir_stable_id(
                        "audit-finding",
                        ir.source_sha256,
                        concern.source_ref,
                        run_index,
                    ),
                    "audit_run_index": run_index,
                }
                key = (
                    page_index,
                    font_ref,
                    font_object_id,
                    bbox_key,
                )
                audit_exact[key].append(identity)
                audit_by_font[
                    (page_index, font_ref, font_object_id)
                ].append((bbox, identity))
            continue

        if concern.code == "pdf_font_recovery_unresolved":
            refusal = concern.metadata.get("refusal")
            if not isinstance(refusal, Mapping):
                continue
            font_ref = str(refusal.get("font_ref") or "")
            font_object_id = refusal.get("font_object_id")
            reason_code = str(refusal.get("reason_code") or "")
            page_indexes = refusal.get("page_indexes") or []
            if (
                not font_ref
                or isinstance(font_object_id, bool)
                or not isinstance(font_object_id, int)
                or not reason_code
                or not isinstance(page_indexes, Sequence)
                or isinstance(page_indexes, (str, bytes, bytearray))
            ):
                continue
            for page_index in page_indexes:
                budget.check()
                if isinstance(page_index, int) and not isinstance(
                    page_index,
                    bool,
                ):
                    refusals.add(
                        (
                            page_index,
                            font_ref,
                            font_object_id,
                            reason_code,
                        )
                    )
                    if len(refusals) > MAX_RECONCILIATION_GROUPS:
                        raise _IRAdapterLimit(
                            "text_reconciliation_refusal_limit"
                        )
            continue

        if concern.code.startswith("pdf_selective_ocr_"):
            if concern.code == "pdf_selective_ocr_alternative":
                candidate_id = concern.metadata.get(
                    "candidate_element_id"
                )
                if isinstance(candidate_id, str) and candidate_id:
                    rows = candidate_registry[candidate_id]
                    if len(rows) < 2:
                        rows.append(concern)
            elif concern.source_ref:
                malformed_spans.add(str(concern.source_ref))
                if len(malformed_spans) > MAX_RECONCILIATION_CONCERNS:
                    raise _IRAdapterLimit(
                        "text_reconciliation_concern_limit"
                    )
            else:
                global_selective_malformed = True

    return {
        "audit_exact": audit_exact,
        "audit_by_font": audit_by_font,
        "refusals": refusals,
        "candidate_registry": candidate_registry,
        "malformed_spans": malformed_spans,
        "global_selective_malformed": global_selective_malformed,
    }


def _ir_audit_identity(
    ir: Any,
    *,
    page_index: int,
    font_ref: str,
    font_object_id: int,
    bbox: Mapping[str, Any],
    lineage_index: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve only an exact retained audit run.

    Selective OCR is authorized for the exact audited/refused span.  It must
    never inherit the wider font-recovery geometry accommodation below.
    """

    if lineage_index is not None:
        bbox_key = _ir_bbox_key(bbox)
        if bbox_key is None:
            return None
        matches = lineage_index["audit_exact"].get(
            (page_index, font_ref, font_object_id, bbox_key),
            [],
        )
        return dict(matches[0]) if len(matches) == 1 else None

    for concern in ir.concerns:
        if concern.code not in {
            "pdf_font_mapping_suspicious",
            "pdf_font_mapping_unresolved",
        }:
            continue
        finding = concern.metadata.get("finding")
        if not isinstance(finding, Mapping):
            continue
        if (
            str(finding.get("font_ref") or "") != font_ref
            or finding.get("font_object_id") != font_object_id
        ):
            continue
        raw_runs = finding.get("runs") or []
        if not isinstance(raw_runs, Sequence) or isinstance(
            raw_runs,
            (str, bytes, bytearray),
        ):
            continue
        for run_index, raw_run in enumerate(raw_runs, 1):
            if (
                isinstance(raw_run, Mapping)
                and raw_run.get("page_index") == page_index
                and _ir_same_bbox(raw_run.get("bbox"), bbox)
            ):
                return {
                    "source_sha256": concern.metadata.get("source_sha256"),
                    "audit_finding_id": _ir_stable_id(
                        "audit-finding",
                        ir.source_sha256,
                        concern.source_ref,
                        run_index,
                    ),
                    "audit_run_index": run_index,
                }
    return None


def _ir_font_audit_identity(
    ir: Any,
    *,
    page_index: int,
    font_ref: str,
    font_object_id: int,
    bbox: Mapping[str, Any],
    lineage_index: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Bind a recovered font run to one unique audit run.

    P02-US02 may coalesce adjacent glyph boxes into a recovery run whose
    bounds are wider than the diagnostic audit run.  That accommodation is
    deliberately font-only and requires one unique reciprocal match.
    """

    exact = _ir_audit_identity(
        ir,
        page_index=page_index,
        font_ref=font_ref,
        font_object_id=font_object_id,
        bbox=bbox,
        lineage_index=lineage_index,
    )
    if exact is not None:
        return exact

    if lineage_index is not None:
        recovery_bbox = _ir_raw_bbox(bbox)
        if recovery_bbox is None:
            return None
        recovery_box = ReconciliationBBox.model_validate(recovery_bbox)
        indexed_matches: list[tuple[float, dict[str, Any]]] = []
        for audit_bbox, identity in lineage_index["audit_by_font"].get(
            (page_index, font_ref, font_object_id),
            [],
        ):
            audit_box = ReconciliationBBox.model_validate(audit_bbox)
            audit_covered, recovery_covered = _directed_overlaps(
                audit_box,
                recovery_box,
            )
            if (
                audit_covered + 1e-12 >= MIN_RECIPROCAL_OVERLAP
                and recovery_covered + 1e-12 >= 0.50
            ):
                indexed_matches.append(
                    (
                        min(audit_covered, recovery_covered),
                        identity,
                    )
                )
        indexed_matches.sort(
            key=lambda row: (
                -row[0],
                int(row[1]["audit_run_index"]),
            )
        )
        if indexed_matches:
            best_score = indexed_matches[0][0]
            best = [
                row
                for row in indexed_matches
                if abs(row[0] - best_score) <= 1e-12
            ]
            if len(best) == 1:
                return dict(best[0][1])
        return None

    overlap_matches: list[tuple[float, int, Any, Any]] = []
    for concern in ir.concerns:
        if concern.code not in {
            "pdf_font_mapping_suspicious",
            "pdf_font_mapping_unresolved",
        }:
            continue
        finding = concern.metadata.get("finding")
        if not isinstance(finding, Mapping):
            continue
        if (
            str(finding.get("font_ref") or "") != font_ref
            or finding.get("font_object_id") != font_object_id
        ):
            continue
        raw_runs = finding.get("runs") or []
        if not isinstance(raw_runs, Sequence) or isinstance(
            raw_runs,
            (str, bytes, bytearray),
        ):
            continue
        for run_index, raw_run in enumerate(raw_runs, 1):
            if not isinstance(raw_run, Mapping):
                continue
            if raw_run.get("page_index") != page_index:
                continue
            audit_bbox = _ir_raw_bbox(raw_run.get("bbox"))
            recovery_bbox = _ir_raw_bbox(bbox)
            if audit_bbox is None or recovery_bbox is None:
                continue
            audit_box = ReconciliationBBox.model_validate(audit_bbox)
            recovery_box = ReconciliationBBox.model_validate(recovery_bbox)
            audit_covered, recovery_covered = _directed_overlaps(
                audit_box,
                recovery_box,
            )
            if (
                audit_covered + 1e-12 >= MIN_RECIPROCAL_OVERLAP
                and recovery_covered + 1e-12 >= 0.50
            ):
                overlap_matches.append(
                    (
                        min(audit_covered, recovery_covered),
                        run_index,
                        concern,
                        raw_run,
                    )
                )
    overlap_matches.sort(key=lambda row: (-row[0], row[1]))
    if overlap_matches:
        best_score = overlap_matches[0][0]
        best = [
            row
            for row in overlap_matches
            if abs(row[0] - best_score) <= 1e-12
        ]
        if len(best) == 1:
            _score, run_index, concern, _raw_run = best[0]
            return {
                "source_sha256": concern.metadata.get("source_sha256"),
                "audit_finding_id": _ir_stable_id(
                    "audit-finding",
                    ir.source_sha256,
                    concern.source_ref,
                    run_index,
                ),
                "audit_run_index": run_index,
            }
    return None


def _ir_matching_refusal(
    ir: Any,
    *,
    page_index: int,
    font_ref: str,
    font_object_id: int,
    reason_code: str,
    lineage_index: Mapping[str, Any] | None = None,
) -> bool:
    if lineage_index is not None:
        return (
            page_index,
            font_ref,
            font_object_id,
            reason_code,
        ) in lineage_index["refusals"]
    for concern in ir.concerns:
        if concern.code != "pdf_font_recovery_unresolved":
            continue
        refusal = concern.metadata.get("refusal")
        if not isinstance(refusal, Mapping):
            continue
        if (
            str(refusal.get("font_ref") or "") == font_ref
            and refusal.get("font_object_id") == font_object_id
            and str(refusal.get("reason_code") or "") == reason_code
            and page_index in set(refusal.get("page_indexes") or [])
        ):
            return True
    return False


def _ir_expected_scripts(
    values: Sequence[str],
    languages: Sequence[str],
) -> list[str]:
    scripts: set[str] = set()
    for value in values:
        scripts.update(_strong_scripts(value))
    if scripts:
        return sorted(scripts)
    lowered = [value.casefold() for value in languages]
    for script, prefixes in _LANGUAGE_SCRIPT_PREFIXES.items():
        if any(
            language.startswith(prefix)
            for language in lowered
            for prefix in prefixes
        ):
            scripts.add(script)
    return sorted(scripts)


def _ir_text_value(element: Any) -> str | None:
    if isinstance(element.value, str):
        return element.value
    legacy = element.properties.get("legacy_item")
    if isinstance(legacy, Mapping):
        for key in ("value", "text", "md"):
            value = legacy.get(key)
            if isinstance(value, str):
                return value
    return None


def _ir_font_groups(
    ir: Any,
    *,
    budget: _IRAdapterBudget | None = None,
    lineage_index: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    active_budget = budget or _IRAdapterBudget()
    active_lineage_index = (
        lineage_index
        if lineage_index is not None
        else _ir_build_lineage_index(ir, active_budget)
    )
    elements: dict[str, Any] = {}
    for element in ir.elements:
        active_budget.check()
        elements[element.id] = element
    evidence_by_id: dict[str, Any] = {}
    for evidence in ir.evidence:
        active_budget.check()
        evidence_by_id[evidence.id] = evidence
    relationships_by_source: dict[str, list[Any]] = defaultdict(list)
    for relationship in ir.relationships:
        active_budget.check()
        if str(relationship.type.value) == "alternative_of":
            relationships_by_source[relationship.source_id].append(
                relationship
            )
    boxes: dict[str, Any] = {}
    for box in ir.bboxes:
        active_budget.check()
        boxes[box.id] = box
    coordinates: dict[str, Any] = {}
    for coordinate in ir.coordinate_systems:
        active_budget.check()
        coordinates[coordinate.id] = coordinate
    regions: dict[str, Any] = {}
    for region in ir.regions:
        active_budget.check()
        regions[region.id] = region
    pages: dict[str, Any] = {}
    page_indexes: dict[str, int] = {}
    page_geometry: dict[str, Any] = {}
    for page in ir.pages:
        active_budget.check()
        pages[page.id] = page
        page_indexes[page.id] = page.page_index
        page_geometry[page.id] = _ir_page_geometry(
            ir,
            page,
            boxes,
            coordinates,
            regions,
        )

    registry: dict[str, dict[str, Any]] = {}
    registry_issues: list[str] = []
    for owner in ir.elements:
        active_budget.check()
        legacy = owner.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            continue
        rows = legacy.get("font_recovery_alternatives") or []
        if not isinstance(rows, Sequence) or isinstance(
            rows,
            (str, bytes, bytearray),
        ):
            continue
        for raw_summary in rows:
            active_budget.check()
            if not isinstance(raw_summary, Mapping):
                continue
            run_id = str(raw_summary.get("run_evidence_id") or "")
            if not run_id or len(run_id) > 200:
                registry_issues.append("font_run_identity_invalid")
                continue
            entry = registry.setdefault(run_id, {"run_id": run_id})
            if (
                "summary" in entry
                or (
                    entry.get("owner_id") is not None
                    and entry.get("owner_id") != owner.id
                )
            ):
                registry_issues.append(
                    "font_run_registry_duplicate"
                )
                continue
            entry["summary"] = dict(raw_summary)
            entry["owner_id"] = owner.id
            if len(registry) > MAX_RECONCILIATION_GROUPS:
                raise _IRAdapterLimit(
                    "text_reconciliation_group_limit"
                )

    for alternate in ir.elements:
        active_budget.check()
        raw_font = alternate.properties.get("font_recovery")
        if not isinstance(raw_font, Mapping):
            continue
        run_id = str(raw_font.get("run_evidence_id") or "")
        if not run_id or len(run_id) > 200:
            registry_issues.append("font_run_identity_invalid")
            continue
        entry = registry.setdefault(run_id, {"run_id": run_id})
        if "font_properties" in entry or "alternate_id" in entry:
            registry_issues.append("font_run_registry_duplicate")
            continue
        entry["font_properties"] = dict(raw_font)
        entry["alternate_id"] = alternate.id
        owner_id = alternate.properties.get("owner_element_id")
        if isinstance(owner_id, str) and owner_id:
            if (
                entry.get("owner_id") is not None
                and entry.get("owner_id") != owner_id
            ):
                registry_issues.append(
                    "font_run_owner_identity_mismatch"
                )
                continue
            entry.setdefault("owner_id", owner_id)
        if len(registry) > MAX_RECONCILIATION_GROUPS:
            raise _IRAdapterLimit("text_reconciliation_group_limit")

    groups: list[dict[str, Any]] = []
    contexts: dict[str, dict[str, Any]] = {}
    issues: list[str] = registry_issues
    for run_id in sorted(registry):
        active_budget.check()
        entry = registry[run_id]
        summary = entry.get("summary")
        font_properties = entry.get("font_properties")
        source = summary if isinstance(summary, Mapping) else font_properties
        if not isinstance(source, Mapping):
            issues.append(f"{run_id}:font_metadata_missing")
            continue
        owner = elements.get(str(entry.get("owner_id") or ""))
        alternate = elements.get(str(entry.get("alternate_id") or ""))
        anchor = alternate or owner
        if anchor is None:
            issues.append(f"{run_id}:font_anchor_missing")
            continue
        if owner is not None and owner.page_id != anchor.page_id:
            issues.append(f"{run_id}:font_owner_page_mismatch")
            continue
        if alternate is not None:
            relationships = relationships_by_source.get(alternate.id, [])
            relationship_valid = (
                not relationships
                if owner is None
                else bool(
                    len(relationships) == 1
                    and relationships[0].target_id == owner.id
                    and relationships[0].metadata.get("method")
                    == source.get("method")
                )
            )
            if not relationship_valid:
                issues.append(f"{run_id}:font_relationship_mismatch")
                continue
        page = pages.get(anchor.page_id)
        geometry = page_geometry.get(anchor.page_id)
        if page is None or geometry is None:
            issues.append(f"{run_id}:page_geometry_missing")
            continue
        page_width, page_height, page_box = geometry
        page_index = page_indexes[anchor.page_id]

        raw_bbox = (
            source.get("bbox")
            if isinstance(source.get("bbox"), Mapping)
            else _ir_element_bbox(anchor, boxes, coordinates)
        )
        target_bbox = _ir_raw_bbox(raw_bbox)
        if target_bbox is None:
            issues.append(f"{run_id}:font_bbox_missing")
            continue
        font_ref = str(source.get("font_ref") or "")
        font_object_id = source.get("font_object_id")
        if (
            not font_ref
            or isinstance(font_object_id, bool)
            or not isinstance(font_object_id, int)
        ):
            issues.append(f"{run_id}:font_identity_missing")
            continue
        original = str(
            (
                summary.get("original_text")
                if isinstance(summary, Mapping)
                else font_properties.get("original_text")
            )
            or ""
        )
        recovered = str(
            (
                summary.get("recovered_text")
                if isinstance(summary, Mapping)
                else anchor.value
            )
            or ""
        )
        if not recovered:
            issues.append(f"{run_id}:font_recovered_text_missing")
            continue

        if (
            alternate is not None
            and (
                alternate.value != recovered
                or (
                    isinstance(alternate.markdown, str)
                    and alternate.markdown != recovered
                )
            )
        ):
            issues.append(f"{run_id}:font_element_value_mismatch")
            continue
        if (
            isinstance(summary, Mapping)
            and isinstance(font_properties, Mapping)
            and any(
                summary.get(field) != font_properties.get(field)
                for field in (
                    "source_sha256",
                    "method",
                    "font_ref",
                    "font_object_id",
                    "run_evidence_id",
                    "original_text",
                )
            )
        ):
            issues.append(f"{run_id}:font_summary_lineage_mismatch")
            continue

        if (
            alternate is not None
            and len(alternate.evidence_ids)
            > 2 * MAX_EVIDENCE_REFS_PER_CANDIDATE
        ):
            raise _IRAdapterLimit(
                "text_reconciliation_evidence_reference_limit"
            )
        raw_recovered_ids = (
            summary.get("glyph_evidence_ids")
            if isinstance(summary, Mapping)
            else (
                [
                    evidence_id
                    for evidence_id in alternate.evidence_ids
                    if (
                        evidence_id in evidence_by_id
                        and str(
                            evidence_by_id[evidence_id].method.value
                        )
                        == "recovered"
                    )
                ]
                if alternate is not None
                else []
            )
        )
        if not isinstance(raw_recovered_ids, Sequence) or isinstance(
            raw_recovered_ids,
            (str, bytes, bytearray),
        ):
            issues.append(f"{run_id}:font_evidence_registry_invalid")
            continue
        if len(raw_recovered_ids) > MAX_EVIDENCE_REFS_PER_CANDIDATE:
            raise _IRAdapterLimit(
                "text_reconciliation_evidence_reference_limit"
            )
        recovered_evidence = [str(value) for value in raw_recovered_ids]
        if (
            not recovered_evidence
            or len(recovered_evidence) != len(set(recovered_evidence))
        ):
            issues.append(f"{run_id}:font_evidence_registry_invalid")
            continue
        recovered_rows = [
            evidence_by_id.get(evidence_id)
            for evidence_id in recovered_evidence
        ]
        if any(row is None for row in recovered_rows):
            issues.append(f"{run_id}:font_evidence_dangling")
            continue
        if any(
            row.element_id != anchor.id
            or str(row.method.value) != "recovered"
            or row.metadata.get("source_sha256") != ir.source_sha256
            or row.metadata.get("font_ref") != font_ref
            or row.metadata.get("font_object_id") != font_object_id
            or not row.bbox_id
            or row.bbox_id not in boxes
            or boxes[row.bbox_id].coordinate_system_id
            not in coordinates
            or coordinates[
                boxes[row.bbox_id].coordinate_system_id
            ].page_id
            != anchor.page_id
            for row in recovered_rows
        ):
            issues.append(f"{run_id}:font_evidence_lineage_mismatch")
            continue
        if "".join(str(row.value or "") for row in recovered_rows) != recovered:
            issues.append(f"{run_id}:font_evidence_value_mismatch")
            continue
        recovered_boxes = [
            _ir_evidence_bbox(row, boxes, coordinates)
            for row in recovered_rows
        ]
        if any(value is None for value in recovered_boxes):
            issues.append(f"{run_id}:font_evidence_bbox_missing")
            continue
        recovered_x = [float(value["x"]) for value in recovered_boxes]
        recovered_y = [float(value["y"]) for value in recovered_boxes]
        recovered_x2 = [
            float(value["x"]) + float(value["width"])
            for value in recovered_boxes
        ]
        recovered_y2 = [
            float(value["y"]) + float(value["height"])
            for value in recovered_boxes
        ]
        recovered_union = {
            "x": min(recovered_x),
            "y": min(recovered_y),
            "width": max(recovered_x2) - min(recovered_x),
            "height": max(recovered_y2) - min(recovered_y),
            "unit": "pt",
        }
        if any(
            abs(float(recovered_union[field]) - float(target_bbox[field]))
            > 0.002
            for field in ("x", "y", "width", "height")
        ):
            issues.append(f"{run_id}:font_evidence_bbox_mismatch")
            continue

        native_rows: list[Any] = []
        native_evidence: list[str] = []
        paired_evidence_invalid = False
        for recovered_row in recovered_rows:
            active_budget.check()
            original_id = recovered_row.metadata.get("original_evidence_id")
            original_row = (
                evidence_by_id.get(str(original_id))
                if isinstance(original_id, str) and original_id
                else None
            )
            if (
                original_row is None
                or str(original_row.method.value) != "native"
                or original_row.element_id != recovered_row.element_id
                or original_row.bbox_id != recovered_row.bbox_id
                or original_row.metadata.get("source_sha256")
                != ir.source_sha256
                or original_row.metadata.get("font_ref") != font_ref
                or original_row.metadata.get("font_object_id")
                != font_object_id
                or original_row.metadata.get("run_index")
                != recovered_row.metadata.get("run_index")
                or original_row.metadata.get("glyph_index")
                != recovered_row.metadata.get("glyph_index")
            ):
                paired_evidence_invalid = True
                break
            native_rows.append(original_row)
            native_evidence.append(original_row.id)
        if paired_evidence_invalid:
            issues.append(f"{run_id}:font_native_pair_mismatch")
            continue
        if (
            not isinstance(summary, Mapping)
            and alternate is not None
            and (
                len(alternate.evidence_ids)
                != len(recovered_evidence) + len(native_evidence)
                or set(alternate.evidence_ids)
                != set(recovered_evidence).union(native_evidence)
            )
        ):
            issues.append(f"{run_id}:font_evidence_registry_mismatch")
            continue
        if original and "".join(
            str(row.value or "") for row in native_rows
        ) != original:
            issues.append(f"{run_id}:font_native_value_mismatch")
            continue

        source_identities = {
            str(value)
            for value in (
                source.get("source_sha256"),
                *(
                    row.metadata.get("source_sha256")
                    for row in [*recovered_rows, *native_rows]
                ),
            )
            if value is not None
        }
        if source_identities != {ir.source_sha256}:
            issues.append(f"{run_id}:source_mismatch")
            continue
        audit = _ir_font_audit_identity(
            ir,
            page_index=page_index,
            font_ref=font_ref,
            font_object_id=font_object_id,
            bbox=target_bbox,
            lineage_index=active_lineage_index,
        )
        if (
            audit is None
            or audit.get("source_sha256") != ir.source_sha256
        ):
            issues.append(f"{run_id}:audit_lineage_missing")
            continue

        prior_selected = bool(
            summary.get("selected") if isinstance(summary, Mapping) else False
        )
        span_owner_text = recovered if prior_selected else (original or recovered)
        candidates: list[dict[str, Any]] = []
        if original:
            candidates.append(
                {
                    "candidate_id": f"native:{run_id}",
                    "span_id": f"font-span:{run_id}",
                    "page_index": page_index,
                    "text": original,
                    "bbox": target_bbox,
                    "source_kind": "native",
                    "mapping_safety": "unsafe",
                    "confidence": None,
                    "evidence_ids": native_evidence,
                    "provenance": {
                        "source_sha256": ir.source_sha256,
                        "audit_source_sha256": ir.source_sha256,
                        "lineage_family": "pdf_text_layer",
                        "origin_asset_id": (
                            f"pdf-text-layer:{page_index}:{font_ref}:{run_id}"
                        ),
                        "method": "pdf_text_layer",
                        "candidate_truncated": False,
                        "token_truncated": False,
                        "malformed_output_concern": False,
                        "languages": [],
                    },
                    "is_primary": not prior_selected,
                }
            )
        font_candidate_id = f"font:{run_id}"
        candidates.append(
            {
                "candidate_id": font_candidate_id,
                "span_id": f"font-span:{run_id}",
                "page_index": page_index,
                "text": recovered,
                "bbox": target_bbox,
                "source_kind": "font_recovery",
                "mapping_safety": "safe",
                "confidence": None,
                "evidence_ids": recovered_evidence,
                "provenance": {
                    "source_sha256": ir.source_sha256,
                    "audit_source_sha256": ir.source_sha256,
                    "recovery_source_sha256": ir.source_sha256,
                    "lineage_family": "embedded_font_program",
                    "origin_asset_id": f"embedded-font:{font_ref}:{run_id}",
                    "method": str(source.get("method") or _SAFE_FONT_METHOD),
                    "audit_finding_id": audit["audit_finding_id"],
                    "audit_run_index": audit["audit_run_index"],
                    "font_ref": font_ref,
                    "font_object_id": font_object_id,
                    "run_evidence_id": run_id,
                    "candidate_truncated": False,
                    "token_truncated": False,
                    "malformed_output_concern": False,
                    "languages": [],
                },
                "is_primary": prior_selected,
            }
        )
        group_id = f"font-group:{run_id}"
        owner_id = (
            owner.id if owner is not None else anchor.id
        )
        group_owner_text = (
            _ir_text_value(owner) if owner is not None else None
        )
        if group_owner_text is None:
            group_owner_text = span_owner_text
        group_owner_markdown = (
            str(owner.markdown)
            if owner is not None and isinstance(owner.markdown, str)
            else group_owner_text
        )
        group_owner_bbox = (
            _ir_element_bbox(owner, boxes, coordinates)
            if owner is not None
            else page_box
        )
        if group_owner_bbox is None:
            group_owner_bbox = page_box
        if any(
            len(str(candidate.get("text") or ""))
            > MAX_RECONCILIATION_TEXT_CODEPOINTS
            for candidate in candidates
        ):
            raise _IRAdapterLimit(
                "text_reconciliation_candidate_text_limit"
            )
        active_budget.reserve_group()
        active_budget.reserve_candidates(
            len(candidates),
            [
                len(candidate.get("evidence_ids") or [])
                for candidate in candidates
            ],
        )
        groups.append(
            {
                "group_id": group_id,
                "span_id": f"font-span:{run_id}",
                "page_index": page_index,
                "page_width_points": page_width,
                "page_height_points": page_height,
                "owner_element_id": owner_id,
                "owner_text": group_owner_text,
                "owner_markdown": group_owner_markdown,
                "target_bbox": target_bbox,
                "owner_bbox": group_owner_bbox,
                "replacement_original_text": (
                    recovered if prior_selected else original
                ),
                "expected_scripts": [],
                "candidates": candidates,
            }
        )
        contexts[group_id] = {
            "kind": "font",
            "owner_id": owner.id if owner is not None else None,
            "anchor_id": anchor.id,
            "alternate_ids": (
                [alternate.id] if alternate is not None else []
            ),
            "candidate_elements": (
                {font_candidate_id: alternate.id}
                if alternate is not None
                else {}
            ),
            "candidate_evidence": {
                font_candidate_id: recovered_evidence,
                f"native:{run_id}": native_evidence,
            },
            "run_id": run_id,
            "prior_selected": prior_selected,
            "replacement_original_text": (
                recovered if prior_selected else original
            ),
        }
    return groups, contexts, issues


def _ir_ocr_groups(
    ir: Any,
    *,
    budget: _IRAdapterBudget | None = None,
    lineage_index: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    active_budget = budget or _IRAdapterBudget()
    active_lineage_index = (
        lineage_index
        if lineage_index is not None
        else _ir_build_lineage_index(ir, active_budget)
    )
    elements: dict[str, Any] = {}
    for element in ir.elements:
        active_budget.check()
        elements[element.id] = element
    evidence_by_id: dict[str, Any] = {}
    evidence_by_element: dict[str, list[Any]] = defaultdict(list)
    for evidence in ir.evidence:
        active_budget.check()
        evidence_by_id[evidence.id] = evidence
        evidence_by_element[evidence.element_id].append(evidence)
    relationships_by_source: dict[str, list[Any]] = defaultdict(list)
    for relationship in ir.relationships:
        active_budget.check()
        if str(relationship.type.value) == "alternative_of":
            relationships_by_source[relationship.source_id].append(
                relationship
            )
    candidate_registry = active_lineage_index["candidate_registry"]
    malformed_spans = active_lineage_index["malformed_spans"]
    global_selective_malformed = active_lineage_index[
        "global_selective_malformed"
    ]
    boxes: dict[str, Any] = {}
    for box in ir.bboxes:
        active_budget.check()
        boxes[box.id] = box
    coordinates: dict[str, Any] = {}
    for coordinate in ir.coordinate_systems:
        active_budget.check()
        coordinates[coordinate.id] = coordinate
    regions: dict[str, Any] = {}
    for region in ir.regions:
        active_budget.check()
        regions[region.id] = region
    pages: dict[str, Any] = {}
    page_geometry: dict[str, Any] = {}
    for page in ir.pages:
        active_budget.check()
        pages[page.id] = page
        page_geometry[page.id] = _ir_page_geometry(
            ir,
            page,
            boxes,
            coordinates,
            regions,
        )

    by_span: dict[str, list[Any]] = defaultdict(list)
    for element in ir.elements:
        active_budget.check()
        raw = element.properties.get("selective_span_ocr")
        if isinstance(raw, Mapping) and raw.get("span_id"):
            span_id = str(raw["span_id"])
            if not span_id or len(span_id) > 200:
                raise _IRAdapterLimit(
                    "text_reconciliation_span_identity_limit"
                )
            by_span[span_id].append(element)
            if len(by_span) > MAX_RECONCILIATION_GROUPS:
                raise _IRAdapterLimit(
                    "text_reconciliation_group_limit"
                )
            if len(by_span[span_id]) > MAX_CANDIDATES_PER_GROUP:
                raise _IRAdapterLimit(
                    "text_reconciliation_candidate_per_group_limit"
                )

    groups: list[dict[str, Any]] = []
    contexts: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for span_id in sorted(by_span):
        active_budget.check()
        alternates = sorted(by_span[span_id], key=lambda row: row.id)
        first = alternates[0]
        lineage = first.properties["selective_span_ocr"]
        if any(alternate.page_id != first.page_id for alternate in alternates):
            issues.append(f"{span_id}:candidate_page_mismatch")
            continue
        page = pages.get(first.page_id)
        geometry = page_geometry.get(first.page_id)
        if page is None or geometry is None:
            issues.append(f"{span_id}:page_geometry_missing")
            continue
        page_width, page_height, page_bbox = geometry
        page_index = page.page_index
        source_bbox = _ir_raw_bbox(lineage.get("source_bbox"))
        if source_bbox is None:
            issues.append(f"{span_id}:source_bbox_missing")
            continue
        if str(lineage.get("span_id") or "") != span_id or str(
            lineage.get("selective_span_id") or ""
        ) != span_id:
            issues.append(f"{span_id}:span_identity_mismatch")
            continue
        source_sha256 = lineage.get("source_sha256")
        identity_fields = (
            "audit_source_sha256",
            "recovery_source_sha256",
            "selective_ocr_source_sha256",
        )
        if source_sha256 != ir.source_sha256 or any(
            lineage.get(field) != ir.source_sha256
            for field in identity_fields
        ):
            issues.append(f"{span_id}:source_mismatch")
            continue
        font_ref = str(lineage.get("font_ref") or "")
        font_object_id = lineage.get("font_object_id")
        audit_run_index = lineage.get("audit_run_index")
        refusal_reason = str(
            lineage.get("recovery_refusal_reason_code") or ""
        )
        if (
            not font_ref
            or isinstance(font_object_id, bool)
            or not isinstance(font_object_id, int)
            or isinstance(audit_run_index, bool)
            or not isinstance(audit_run_index, int)
            or not refusal_reason
        ):
            issues.append(f"{span_id}:selective_lineage_missing")
            continue
        expected_audit_finding_id = _retained_ir_stable_id(
            "audit-finding",
            ir.id,
            font_ref,
            audit_run_index,
        )
        expected_outcome_id = _retained_ir_stable_id(
            "selective-outcome",
            ir.id,
            span_id,
            page_index,
            font_ref,
            audit_run_index,
        )
        if (
            lineage.get("audit_finding_id")
            != expected_audit_finding_id
            or lineage.get("selective_outcome_id")
            != expected_outcome_id
        ):
            issues.append(f"{span_id}:retained_lineage_identity_mismatch")
            continue
        audit = _ir_audit_identity(
            ir,
            page_index=page_index,
            font_ref=font_ref,
            font_object_id=font_object_id,
            bbox=source_bbox,
            lineage_index=active_lineage_index,
        )
        if (
            audit is None
            or audit.get("source_sha256") != ir.source_sha256
            or audit.get("audit_run_index") != audit_run_index
            or not _ir_matching_refusal(
                ir,
                page_index=page_index,
                font_ref=font_ref,
                font_object_id=font_object_id,
                reason_code=refusal_reason,
                lineage_index=active_lineage_index,
            )
        ):
            issues.append(f"{span_id}:audit_or_refusal_lineage_missing")
            continue

        owner_identities = {
            str(
                alternate.properties["selective_span_ocr"].get(
                    "owner_element_id"
                )
                or ""
            )
            for alternate in alternates
        }
        if len(owner_identities) != 1:
            issues.append(f"{span_id}:multiple_owner_identity")
            continue
        owner_id = next(iter(owner_identities))
        owner = elements.get(owner_id) if owner_id else None
        if owner_id and owner is None:
            issues.append(f"{span_id}:owner_identity_missing")
            continue
        if owner is not None and owner.page_id != first.page_id:
            issues.append(f"{span_id}:owner_page_mismatch")
            continue
        owner_matches: list[str] = []
        for presentation_element_id in page.presentation_element_ids:
            active_budget.check()
            possible_owner = elements.get(presentation_element_id)
            if possible_owner is None:
                continue
            possible_bbox = _ir_element_bbox(
                possible_owner,
                boxes,
                coordinates,
            )
            if possible_bbox is None:
                continue
            target_covered, owner_covered = _directed_overlaps(
                ReconciliationBBox.model_validate(source_bbox),
                ReconciliationBBox.model_validate(possible_bbox),
            )
            if (
                max(target_covered, owner_covered) + 1e-12
                >= MIN_RECIPROCAL_OVERLAP
            ):
                owner_matches.append(possible_owner.id)
                if len(owner_matches) > 1:
                    break
        if (
            (owner is None and owner_matches)
            or (
                owner is not None
                and (
                    len(owner_matches) != 1
                    or owner_matches[0] != owner.id
                )
            )
        ):
            issues.append(f"{span_id}:owner_geometry_ambiguous")
            continue
        owner_text = _ir_text_value(owner) if owner is not None else None
        owner_bbox = (
            _ir_element_bbox(owner, boxes, coordinates)
            if owner is not None
            else page_bbox
        )
        if owner_bbox is None:
            owner_bbox = page_bbox
        candidates: list[dict[str, Any]] = []
        candidate_elements: dict[str, str] = {}
        candidate_evidence: dict[str, list[str]] = {}
        candidate_source_evidence: dict[str, str] = {}
        if owner is not None and owner_text is not None:
            native_id = f"native:{owner.id}:{span_id}"
            if (
                len(owner.evidence_ids)
                > 2 * MAX_EVIDENCE_REFS_PER_CANDIDATE
            ):
                raise _IRAdapterLimit(
                    "text_reconciliation_evidence_reference_limit"
                )
            native_refs = [
                evidence_id
                for evidence_id in owner.evidence_ids
                if (
                    evidence_id in evidence_by_id
                    and evidence_by_id[evidence_id].element_id == owner.id
                    and str(evidence_by_id[evidence_id].method.value)
                    == "native"
                    and evidence_by_id[evidence_id].value == owner_text
                    and evidence_by_id[evidence_id].bbox_id in boxes
                    and boxes[
                        evidence_by_id[evidence_id].bbox_id
                    ].coordinate_system_id
                    in coordinates
                    and coordinates[
                        boxes[
                            evidence_by_id[evidence_id].bbox_id
                        ].coordinate_system_id
                    ].page_id
                    == owner.page_id
                    and _ir_same_bbox(
                        _ir_evidence_bbox(
                            evidence_by_id[evidence_id],
                            boxes,
                            coordinates,
                        ),
                        source_bbox,
                    )
                )
            ]
            if not native_refs:
                issues.append(f"{span_id}:owner_native_evidence_missing")
                continue
            candidates.append(
                {
                    "candidate_id": native_id,
                    "span_id": span_id,
                    "page_index": page_index,
                    "text": owner_text,
                    "bbox": source_bbox,
                    "source_kind": "native",
                    "mapping_safety": "unsafe",
                    "confidence": None,
                    "evidence_ids": native_refs,
                    "provenance": {
                        "source_sha256": ir.source_sha256,
                        "audit_source_sha256": ir.source_sha256,
                        "lineage_family": "pdf_text_layer",
                        "origin_asset_id": (
                            f"pdf-text-layer:{owner.id}:{span_id}"
                        ),
                        "method": "pdf_text_layer",
                        "candidate_truncated": False,
                        "token_truncated": False,
                        "malformed_output_concern": False,
                        "languages": [],
                    },
                    "is_primary": True,
                }
            )
            candidate_evidence[native_id] = native_refs

        for alternate in alternates:
            active_budget.check()
            raw = alternate.properties["selective_span_ocr"]
            raw_source_bbox = _ir_raw_bbox(raw.get("source_bbox"))
            if (
                str(raw.get("span_id") or "") != span_id
                or str(raw.get("selective_span_id") or "") != span_id
                or any(
                    raw.get(field) != ir.source_sha256
                    for field in (
                        "source_sha256",
                        "audit_source_sha256",
                        "recovery_source_sha256",
                        "selective_ocr_source_sha256",
                    )
                )
                or raw.get("audit_finding_id")
                != expected_audit_finding_id
                or raw.get("selective_outcome_id") != expected_outcome_id
                or raw.get("audit_run_index") != audit_run_index
                or raw.get("font_ref") != font_ref
                or raw.get("font_object_id") != font_object_id
                or raw.get("recovery_refusal_reason_code")
                != refusal_reason
                or raw_source_bbox is None
                or not _ir_same_bbox(raw_source_bbox, source_bbox)
                or str(raw.get("owner_element_id") or "") != owner_id
            ):
                issues.append(
                    f"{span_id}:{alternate.id}:lineage_mismatch"
                )
                continue
            candidate_bbox = _ir_element_bbox(
                alternate,
                boxes,
                coordinates,
            )
            if candidate_bbox is None:
                issues.append(f"{span_id}:{alternate.id}:bbox_missing")
                continue
            if (
                not isinstance(alternate.value, str)
                or alternate.markdown != alternate.value
            ):
                issues.append(
                    f"{span_id}:{alternate.id}:element_value_mismatch"
                )
                continue
            records = evidence_by_element.get(alternate.id, [])
            ocr_records = [
                row for row in records if str(row.method.value) == "ocr"
            ]
            if (
                len(ocr_records) != 1
                or alternate.evidence_ids != [ocr_records[0].id]
                or len(alternate.bbox_ids) != 1
                or ocr_records[0].bbox_id != alternate.bbox_ids[0]
                or alternate.bbox_ids[0] not in boxes
                or boxes[
                    alternate.bbox_ids[0]
                ].coordinate_system_id
                not in coordinates
                or coordinates[
                    boxes[
                        alternate.bbox_ids[0]
                    ].coordinate_system_id
                ].page_id
                != alternate.page_id
            ):
                issues.append(
                    f"{span_id}:{alternate.id}:ocr_evidence_cardinality"
                )
                continue
            record = ocr_records[0]
            if record.value != alternate.value:
                issues.append(
                    f"{span_id}:{alternate.id}:value_mismatch"
                )
                continue
            metadata = record.metadata
            raw_tokens = metadata.get("tokens") or []
            if (
                not isinstance(raw_tokens, Sequence)
                or isinstance(raw_tokens, (str, bytes, bytearray))
            ):
                issues.append(
                    f"{span_id}:{alternate.id}:token_registry_invalid"
                )
                continue
            if (
                len(raw_tokens)
                > MAX_EVIDENCE_REFS_PER_CANDIDATE - 1
            ):
                raise _IRAdapterLimit(
                    "text_reconciliation_evidence_reference_limit"
                )
            if (
                any(
                    metadata.get(field) != raw.get(field)
                    for field in (
                        "source_sha256",
                        "audit_source_sha256",
                        "recovery_source_sha256",
                        "selective_ocr_source_sha256",
                        "audit_finding_id",
                        "audit_run_index",
                        "font_ref",
                        "font_object_id",
                        "selective_span_id",
                        "selective_outcome_id",
                        "recovery_refusal_reason_code",
                        "status",
                        "attempt",
                        "cost",
                        "method",
                        "ocr_pass",
                        "word_count",
                    )
                )
                or metadata.get("span_id") != span_id
                or not _ir_same_bbox(
                    metadata.get("source_bbox"),
                    source_bbox,
                )
            ):
                issues.append(
                    f"{span_id}:{alternate.id}:evidence_lineage_mismatch"
                )
                continue

            registry = candidate_registry.get(alternate.id, [])
            if len(registry) != 1:
                issues.append(
                    f"{span_id}:{alternate.id}:candidate_registry_missing"
                )
                continue
            registry_row = registry[0]
            source_evidence_id = registry_row.metadata.get("evidence_id")
            expected_registry_target = (
                owner.id if owner is not None else alternate.id
            )
            if (
                not isinstance(source_evidence_id, str)
                or not source_evidence_id
                or registry_row.source_ref != span_id
                or registry_row.target_ref != expected_registry_target
                or registry_row.metadata.get("span_id") != span_id
                or registry_row.metadata.get("candidate_element_id")
                != alternate.id
                or alternate.id
                != _retained_ir_stable_id(
                    "el",
                    ir.id,
                    source_evidence_id,
                    "selective_ocr_candidate",
                )
                or record.id
                != _retained_ir_stable_id(
                    "ev",
                    ir.id,
                    source_evidence_id,
                    "selective_ocr",
                )
            ):
                issues.append(
                    f"{span_id}:{alternate.id}:candidate_registry_mismatch"
                )
                continue

            relationships = relationships_by_source.get(alternate.id, [])
            if owner is None:
                relationship_valid = not relationships
            else:
                relationship_valid = bool(
                    len(relationships) == 1
                    and relationships[0].target_id == owner.id
                    and relationships[0].evidence_ids == [record.id]
                    and relationships[0].metadata.get("method")
                    == raw.get("method")
                    and relationships[0].metadata.get(
                        "canonical_presentation_inert"
                    )
                    is True
                )
            if not relationship_valid:
                issues.append(
                    f"{span_id}:{alternate.id}:relationship_mismatch"
                )
                continue

            tokens = [
                dict(token)
                for token in raw_tokens
                if isinstance(token, Mapping)
            ]
            word_count = metadata.get(
                "word_count",
                raw.get("word_count", len(tokens)),
            )
            cost = raw.get("cost")
            attempt = raw.get("attempt")
            cost = cost if isinstance(cost, Mapping) else {}
            attempt = attempt if isinstance(attempt, Mapping) else {}
            bounded_sequences = {
                field: cost.get(field) or []
                for field in (
                    "languages",
                    "passes_attempted",
                    "passes_completed",
                )
            }
            bounded_sequences["attempt_passes"] = (
                attempt.get("passes") or []
            )
            if any(
                not isinstance(value, Sequence)
                or isinstance(value, (str, bytes, bytearray))
                or len(value) > 16
                for value in bounded_sequences.values()
            ):
                issues.append(
                    f"{span_id}:{alternate.id}:cost_registry_invalid"
                )
                continue
            languages = list(bounded_sequences["languages"])
            passes_attempted = list(
                bounded_sequences["passes_attempted"]
            )
            passes_completed = list(
                bounded_sequences["passes_completed"]
            )
            attempt_passes = [
                value
                for value in bounded_sequences["attempt_passes"]
                if isinstance(value, Mapping)
            ]
            attempt_pass_names = [
                str(value.get("ocr_pass") or "")
                for value in attempt_passes
            ]
            pass_completed = bool(
                passes_attempted
                and passes_attempted == passes_completed
                and passes_attempted == attempt_pass_names
                and len(attempt_pass_names)
                == len(set(attempt_pass_names))
                and all(
                    value.get("status") == "completed"
                    for value in attempt_passes
                )
                and attempt.get("status") == "completed"
            )
            transform_valid = bool(
                cost.get("transform_valid") is True
                and attempt.get("transform_valid") is True
                and _ir_ocr_geometry_valid(
                    cost,
                    attempt,
                    source_bbox=source_bbox,
                    page_width=page_width,
                    page_height=page_height,
                )
            )
            tokens_within_target = True
            token_registry_valid = True
            for token in tokens:
                active_budget.check()
                token_bbox = _ir_raw_bbox(token.get("bbox"))
                if token_bbox is None:
                    tokens_within_target = False
                    break
                token_covered, _target_covered = _directed_overlaps(
                    ReconciliationBBox.model_validate(token_bbox),
                    ReconciliationBBox.model_validate(source_bbox),
                )
                if token_covered + 1e-12 < 1.0:
                    tokens_within_target = False
                    break
                word_index = token.get("word_index")
                if (
                    isinstance(word_index, bool)
                    or not isinstance(word_index, int)
                    or not _ir_pixel_bbox_matches_page(
                        token.get("crop_pixel_bbox"),
                        token_bbox,
                        cost,
                    )
                ):
                    token_registry_valid = False
                    break
            candidate_complete = bool(
                record.id
                and isinstance(word_count, int)
                and not isinstance(word_count, bool)
                and word_count > 0
                and len(tokens) == word_count
                and [token.get("word_index") for token in tokens]
                == list(range(word_count))
                and len(
                    {
                        str(token.get("evidence_id") or "")
                        for token in tokens
                    }
                )
                == word_count
                and all(
                    token.get("evidence_id")
                    and isinstance(token.get("text"), str)
                    and isinstance(token.get("bbox"), Mapping)
                    and token.get("method") == "tesseract_tsv"
                    and token.get("ocr_pass") == raw.get("ocr_pass")
                    for token in tokens
                )
                and _comparison_text(
                    " ".join(str(token["text"]) for token in tokens)
                )
                == _comparison_text(alternate.value)
                and tokens_within_target
                and token_registry_valid
                and _ir_pixel_bbox_matches_page(
                    metadata.get("crop_pixel_bbox"),
                    candidate_bbox,
                    cost,
                )
            )

            if owner is not None:
                legacy = owner.properties.get("legacy_item")
                summaries = (
                    legacy.get("selective_ocr_candidates") or []
                    if isinstance(legacy, Mapping)
                    else []
                )
                if (
                    not isinstance(summaries, Sequence)
                    or isinstance(summaries, (str, bytes, bytearray))
                    or len(summaries) > MAX_CANDIDATES_PER_GROUP
                ):
                    raise _IRAdapterLimit(
                        "text_reconciliation_candidate_per_group_limit"
                    )
                matching_summaries = [
                    summary
                    for summary in summaries
                    if isinstance(summary, Mapping)
                    and summary.get("evidence_id") == source_evidence_id
                    and summary.get("span_id") == span_id
                ]
                if (
                    len(matching_summaries) != 1
                    or matching_summaries[0].get("text")
                    != alternate.value
                    or not _ir_same_bbox(
                        matching_summaries[0].get("bbox"),
                        candidate_bbox,
                    )
                    or matching_summaries[0].get("confidence")
                    != record.confidence.score
                    or matching_summaries[0].get("method")
                    != raw.get("method")
                    or matching_summaries[0].get("ocr_pass")
                    != raw.get("ocr_pass")
                    or matching_summaries[0].get("tokens")
                    != metadata.get("tokens")
                    or matching_summaries[0].get("cost") != cost
                ):
                    issues.append(
                        f"{span_id}:{alternate.id}:legacy_registry_mismatch"
                    )
                    continue

            evidence_ids = [
                record.id,
                *[
                    str(token["evidence_id"])
                    for token in tokens
                    if token.get("evidence_id")
                ],
            ]
            candidate_id = f"ocr:{alternate.id}:{span_id}"
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "span_id": span_id,
                    "page_index": page_index,
                    "text": alternate.value,
                    "bbox": candidate_bbox,
                    "source_kind": "selective_ocr",
                    "mapping_safety": "not_applicable",
                    "confidence": record.confidence.score,
                    "evidence_ids": evidence_ids,
                    "provenance": {
                        "source_sha256": ir.source_sha256,
                        "audit_source_sha256": ir.source_sha256,
                        "recovery_source_sha256": ir.source_sha256,
                        "selective_ocr_source_sha256": ir.source_sha256,
                        "lineage_family": "rendered_pixels",
                        "origin_asset_id": f"rendered-crop:{span_id}",
                        "method": str(raw.get("method") or ""),
                        "audit_finding_id": expected_audit_finding_id,
                        "audit_run_index": audit_run_index,
                        "font_ref": font_ref,
                        "font_object_id": font_object_id,
                        "selective_span_id": span_id,
                        "selective_outcome_id": expected_outcome_id,
                        "recovery_refusal_reason_code": refusal_reason,
                        "transform_valid": transform_valid,
                        "pass_completed": pass_completed,
                        "candidate_complete": candidate_complete,
                        "word_count": (
                            word_count
                            if isinstance(word_count, int)
                            and not isinstance(word_count, bool)
                            else 0
                        ),
                        "retained_token_count": len(tokens),
                        "candidate_truncated": False,
                        "token_truncated": False,
                        "malformed_output_concern": bool(
                            global_selective_malformed
                            or span_id in malformed_spans
                        ),
                        "languages": languages,
                    },
                    "is_primary": False,
                }
            )
            candidate_elements[candidate_id] = alternate.id
            candidate_evidence[candidate_id] = evidence_ids
            candidate_source_evidence[candidate_id] = source_evidence_id
        if issues and any(value.startswith(f"{span_id}:") for value in issues):
            continue
        if not candidates:
            continue
        if any(
            len(str(candidate.get("text") or ""))
            > MAX_RECONCILIATION_TEXT_CODEPOINTS
            for candidate in candidates
        ):
            raise _IRAdapterLimit(
                "text_reconciliation_candidate_text_limit"
            )
        active_budget.reserve_group()
        active_budget.reserve_candidates(
            len(candidates),
            [
                len(candidate.get("evidence_ids") or [])
                for candidate in candidates
            ],
        )
        group_id = f"ocr-group:{span_id}"
        group_owner_text = (
            owner_text
            if owner_text is not None
            else str(first.value or "")
        )
        groups.append(
            {
                "group_id": group_id,
                "span_id": span_id,
                "page_index": page_index,
                "page_width_points": page_width,
                "page_height_points": page_height,
                "owner_element_id": (
                    owner.id if owner is not None else first.id
                ),
                "owner_text": group_owner_text,
                "owner_markdown": (
                    str(owner.markdown)
                    if owner is not None
                    and isinstance(owner.markdown, str)
                    else group_owner_text
                ),
                "target_bbox": source_bbox,
                "owner_bbox": owner_bbox,
                "replacement_original_text": group_owner_text,
                "expected_scripts": _ir_expected_scripts(
                    [owner_text] if isinstance(owner_text, str) else [],
                    [],
                ),
                "candidates": candidates,
            }
        )
        contexts[group_id] = {
            "kind": "ocr",
            "owner_id": owner.id if owner is not None else None,
            "anchor_id": first.id,
            "alternate_ids": [row.id for row in alternates],
            "candidate_elements": candidate_elements,
            "candidate_evidence": candidate_evidence,
            "candidate_source_evidence": candidate_source_evidence,
            "span_id": span_id,
            "replacement_original_text": group_owner_text,
        }
    return groups, contexts, issues


def _ir_append_failure(ir: Any, issues: Sequence[str]) -> Any:
    from app.services.ir import DocumentIR, IRConcern

    reason_codes = list(
        dict.fromkeys(str(issue)[:256] for issue in issues if str(issue))
    )[:MAX_RECONCILIATION_CONCERNS]
    if not reason_codes:
        reason_codes = ["text_reconciliation_adapter_failure"]
    for concern in ir.concerns:
        if (
            concern.code == "pdf_text_reconciliation_unresolved"
            and concern.metadata.get("transactional") is True
            and concern.metadata.get("reason_codes") == reason_codes
        ):
            return ir
    working = ir.model_copy(deep=True)
    working.concerns.append(
        IRConcern(
            code="pdf_text_reconciliation_unresolved",
            message=(
                "Text reconciliation failed closed before primary mutation."
            ),
            metadata={
                "reason_codes": reason_codes,
                "transactional": True,
            },
        )
    )
    return DocumentIR.model_validate(working.model_dump(mode="json"))


def _ir_quarantine_incoherent_reconciliation(ir: Any) -> Any:
    """Remove untrusted partial reconciliation markers, never source evidence."""

    from app.services.ir import DocumentIR

    working = ir.model_copy(deep=True)
    for element in working.elements:
        element.properties.pop("text_reconciliation", None)
        legacy = element.properties.get("legacy_item")
        if isinstance(legacy, Mapping):
            updated = dict(legacy)
            updated.pop("text_reconciliation", None)
            element.properties["legacy_item"] = updated
    for evidence in working.evidence:
        evidence.metadata.pop("text_reconciliation", None)
    for relationship in working.relationships:
        relationship.metadata.pop("text_reconciliation", None)
    retained_concerns = []
    for concern in working.concerns:
        if concern.code in {
            "pdf_text_reconciliation_complete",
            "pdf_text_reconciliation_selected",
        }:
            continue
        if (
            concern.code == "pdf_text_reconciliation_unresolved"
            and concern.metadata.get("transactional") is not True
        ):
            continue
        concern.metadata.pop("text_reconciliation", None)
        retained_concerns.append(concern)
    working.concerns = retained_concerns
    cleaned = DocumentIR.model_validate(working.model_dump(mode="json"))
    return _ir_append_failure(
        cleaned,
        ["existing_reconciliation_incoherent"],
    )


def _ir_store_property_trace(
    element: Any,
    trace: Mapping[str, Any],
    *,
    selected: bool,
) -> None:
    value = {**dict(trace), "selected": selected}
    existing = element.properties.get("text_reconciliation")
    if not existing:
        element.properties["text_reconciliation"] = value
        return
    rows = (
        [dict(existing)]
        if isinstance(existing, Mapping)
        else [
            dict(row)
            for row in existing
            if isinstance(row, Mapping)
        ]
    )
    replaced = False
    for index, row in enumerate(rows):
        if row.get("group_id") == value.get("group_id"):
            rows[index] = value
            replaced = True
            break
    if not replaced:
        rows.append(value)
    element.properties["text_reconciliation"] = (
        rows[0] if len(rows) == 1 else rows
    )


def _ir_store_legacy_trace(
    element: Any,
    trace: Mapping[str, Any],
) -> dict[str, Any] | None:
    legacy = element.properties.get("legacy_item")
    if not isinstance(legacy, Mapping):
        return None
    updated = dict(legacy)
    existing = updated.get("text_reconciliation")
    rows = [
        dict(row)
        for row in (
            existing
            if isinstance(existing, list)
            else ([existing] if isinstance(existing, Mapping) else [])
        )
        if isinstance(row, Mapping)
    ]
    rows = [
        row for row in rows if row.get("group_id") != trace.get("group_id")
    ]
    rows.append(dict(trace))
    rows.sort(
        key=lambda row: (
            int(row.get("page_index") or 0),
            str(row.get("span_id") or ""),
            str(row.get("group_id") or ""),
        )
    )
    updated["text_reconciliation"] = rows
    element.properties["legacy_item"] = updated
    return updated


def _ir_replace_owner_text(
    owner: Any,
    *,
    selected_text: str,
    replacement_mode: str,
    original_text: str,
) -> None:
    legacy = owner.properties.get("legacy_item")
    if isinstance(legacy, Mapping) and isinstance(
        legacy.get("table_evidence"), Mapping
    ):
        from app.services.table_semantics import replace_marked_table_text

        replace_marked_table_text(
            owner,
            selected_text=selected_text,
            replacement_mode=replacement_mode,
            original_text=original_text,
        )
        return
    def replace(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if replacement_mode == "whole_owner":
            return selected_text
        if replacement_mode == "unique_substring":
            if value.count(original_text) != 1:
                raise ValueError("owner replacement range changed")
            return value.replace(original_text, selected_text, 1)
        raise ValueError("selected outcome has no replacement mode")

    owner.value = replace(owner.value)
    owner.markdown = replace(owner.markdown)
    legacy = owner.properties.get("legacy_item")
    if isinstance(legacy, Mapping):
        updated = dict(legacy)
        for key in ("value", "text", "md"):
            if key in updated:
                updated[key] = replace(updated[key])
        owner.properties["legacy_item"] = updated


def _ir_apply_report(
    ir: Any,
    report: TextReconciliationReport,
    contexts: Mapping[str, Mapping[str, Any]],
    *,
    budget: _IRAdapterBudget | None = None,
) -> Any:
    from app.services.ir import DocumentIR, IRConcern

    active_budget = budget or _IRAdapterBudget()
    active_budget.check()
    working = ir.model_copy(deep=True)
    active_budget.check()
    elements: dict[str, Any] = {}
    for element in working.elements:
        active_budget.check()
        elements[element.id] = element
    evidence: dict[str, Any] = {}
    for row in working.evidence:
        active_budget.check()
        evidence[row.id] = row
    relationships_by_source: dict[str, list[Any]] = defaultdict(list)
    for relationship in working.relationships:
        active_budget.check()
        relationships_by_source[relationship.source_id].append(
            relationship
        )
    concerns_by_ocr_span: dict[str, list[Any]] = defaultdict(list)
    concerns_by_font_run: dict[str, list[Any]] = defaultdict(list)
    for concern in working.concerns:
        active_budget.check()
        if (
            concern.source_ref
            and concern.code.startswith("pdf_selective_ocr_")
        ):
            concerns_by_ocr_span[str(concern.source_ref)].append(concern)
        run_id = concern.metadata.get("run_evidence_id")
        if isinstance(run_id, str) and run_id:
            concerns_by_font_run[run_id].append(concern)
    for outcome in report.outcomes:
        active_budget.check()
        context = contexts[outcome.group_id]
        trace = outcome.model_dump(mode="json", exclude_none=False)
        selected_id = (
            outcome.selected_candidate_ids[0]
            if outcome.selected_candidate_ids
            else None
        )
        owner_id = context.get("owner_id")
        owner = elements.get(str(owner_id or ""))
        anchor = elements.get(str(context.get("anchor_id") or ""))
        selected_element_id = (
            context.get("candidate_elements", {}).get(selected_id)
            if selected_id is not None
            else None
        )
        selected_element = elements.get(str(selected_element_id or ""))

        if (
            outcome.status == "selected"
            and owner is not None
            and isinstance(outcome.selected_text, str)
        ):
            _ir_replace_owner_text(
                owner,
                selected_text=outcome.selected_text,
                replacement_mode=outcome.replacement_mode,
                original_text=str(
                    context.get("replacement_original_text") or ""
                ),
            )

        trace_targets = {
            value
            for value in (
                owner.id if owner is not None else None,
                anchor.id if anchor is not None else None,
                *context.get("alternate_ids", []),
            )
            if value is not None
        }
        for element_id in sorted(trace_targets):
            active_budget.check()
            element = elements[element_id]
            element_selected = bool(
                outcome.status in {"selected", "unchanged"}
                and (
                    element_id == selected_element_id
                    or element_id == owner_id
                    or (
                        context["kind"] == "font"
                        and element_id == context.get("anchor_id")
                    )
                )
            )
            _ir_store_property_trace(
                element,
                trace,
                selected=element_selected,
            )
        if owner is not None:
            legacy = _ir_store_legacy_trace(owner, trace)
            if legacy is not None:
                if context["kind"] == "ocr":
                    rows = legacy.get("selective_ocr_candidates") or []
                    selected_source_evidence_id = context.get(
                        "candidate_source_evidence",
                        {},
                    ).get(selected_id)
                    for row in rows:
                        active_budget.check()
                        if not isinstance(row, dict):
                            continue
                        row["selected"] = bool(
                            outcome.status in {"selected", "unchanged"}
                            and selected_source_evidence_id is not None
                            and row.get("evidence_id")
                            == selected_source_evidence_id
                        )
                else:
                    rows = legacy.get("font_recovery_alternatives") or []
                    for row in rows:
                        active_budget.check()
                        if (
                            isinstance(row, dict)
                            and row.get("run_evidence_id")
                            == context.get("run_id")
                        ):
                            row["selected"] = bool(
                                outcome.status in {"selected", "unchanged"}
                            )
                owner.properties["legacy_item"] = legacy

        for candidate_id, element_id in context.get(
            "candidate_elements",
            {},
        ).items():
            active_budget.check()
            candidate_element = elements.get(element_id)
            if candidate_element is None:
                continue
            selected = candidate_id == selected_id
            if context["kind"] == "ocr":
                raw = candidate_element.properties.get("selective_span_ocr")
                if isinstance(raw, Mapping):
                    updated = dict(raw)
                    updated["selected"] = selected
                    candidate_element.properties[
                        "selective_span_ocr"
                    ] = updated
            elif context["kind"] == "font":
                raw = candidate_element.properties.get("font_recovery")
                if isinstance(raw, Mapping):
                    updated = dict(raw)
                    updated["selected"] = selected
                    candidate_element.properties["font_recovery"] = updated

        selected_evidence_ids = set(
            context.get("candidate_evidence", {}).get(selected_id, [])
        )
        all_context_evidence = {
            value
            for values in context.get("candidate_evidence", {}).values()
            for value in values
        }
        for evidence_id in all_context_evidence:
            active_budget.check()
            record = evidence.get(evidence_id)
            if record is None:
                continue
            selected = evidence_id in selected_evidence_ids
            record.metadata["selected"] = selected
            record.metadata["text_reconciliation"] = {
                "group_id": outcome.group_id,
                "selected": selected,
                "status": outcome.status,
                "reason_code": outcome.reason_code,
            }

        for alternate_id in context.get("alternate_ids", []):
            active_budget.check()
            for relationship in relationships_by_source.get(
                alternate_id,
                [],
            ):
                active_budget.check()
                if str(relationship.type.value) != "alternative_of":
                    continue
                selected = relationship.source_id == selected_element_id
                if context["kind"] == "font" and outcome.status in {
                    "selected",
                    "unchanged",
                }:
                    selected = True
                relationship.metadata["selected"] = selected
                relationship.metadata["text_reconciliation"] = {
                    "group_id": outcome.group_id,
                    "selected": selected,
                    "status": outcome.status,
                    "reason_code": outcome.reason_code,
                }

        matching_concerns = (
            concerns_by_ocr_span.get(
                str(context.get("span_id") or ""),
                [],
            )
            if context["kind"] == "ocr"
            else concerns_by_font_run.get(
                str(context.get("run_id") or ""),
                [],
            )
        )
        for concern in matching_concerns:
            active_budget.check()
            concern.metadata["selected"] = bool(
                outcome.status in {"selected", "unchanged"}
                and (
                    context["kind"] == "font"
                    or concern.metadata.get("candidate_element_id")
                    == selected_element_id
                )
            )
            concern.metadata["text_reconciliation"] = {
                "group_id": outcome.group_id,
                "status": outcome.status,
                "reason_code": outcome.reason_code,
            }

        working.concerns.append(
            IRConcern(
                code=(
                    "pdf_text_reconciliation_selected"
                    if outcome.status in {"selected", "unchanged"}
                    else "pdf_text_reconciliation_unresolved"
                ),
                message=(
                    "A source-attributable text candidate was selected."
                    if outcome.status in {"selected", "unchanged"}
                    else (
                        "Text candidates remained unresolved; prior primary "
                        "bytes were preserved."
                    )
                ),
                source_ref=outcome.span_id,
                target_ref=outcome.owner_element_id,
                metadata={"outcome": trace},
            )
        )
    active_budget.check()
    normalized_report = report.model_dump(mode="json", exclude_none=True)
    normalized_report["elapsed_ms"] = 0.0
    working.concerns.append(
        IRConcern(
            code="pdf_text_reconciliation_complete",
            message=(
                "Text reconciliation completed with a source-bound "
                "transactional report."
            ),
            source_ref=ir.source_sha256,
            metadata={
                "schema_version": TEXT_RECONCILIATION_SCHEMA_VERSION,
                "policy_id": TEXT_RECONCILIATION_POLICY_ID,
                "source_sha256": ir.source_sha256,
                "report_sha256": stable_reconciliation_sha256(report),
                "report": normalized_report,
            },
        )
    )
    result = DocumentIR.model_validate(working.model_dump(mode="json"))
    active_budget.check()
    return result


def _ir_recompute_retained_report(
    ir: Any,
    report: TextReconciliationReport,
    budget: _IRAdapterBudget,
) -> TextReconciliationReport | None:
    """Rebuild decisions from retained evidence for manifest authentication."""

    from app.services.ir import DocumentIR

    budget.check()
    working = ir.model_copy(deep=True)
    budget.check()
    elements = {element.id: element for element in working.elements}

    for outcome in report.outcomes:
        budget.check()
        if outcome.status != "selected":
            continue
        native_decisions = [
            decision
            for decision in outcome.decisions
            if decision.source_kind == "native"
        ]
        if len(native_decisions) != 1:
            return None
        owner = elements.get(outcome.owner_element_id)
        native_text = native_decisions[0].text
        if (
            owner is None
            or not isinstance(native_text, str)
            or not isinstance(outcome.selected_text, str)
            or outcome.replacement_mode
            not in {"whole_owner", "unique_substring"}
        ):
            return None
        try:
            _ir_replace_owner_text(
                owner,
                selected_text=native_text,
                replacement_mode=outcome.replacement_mode,
                original_text=outcome.selected_text,
            )
        except (TypeError, ValueError):
            return None

        if outcome.group_id.startswith("font-group:"):
            run_id = outcome.group_id[len("font-group:") :]
            legacy = owner.properties.get("legacy_item")
            if not isinstance(legacy, Mapping):
                return None
            updated_legacy = dict(legacy)
            rows = updated_legacy.get("font_recovery_alternatives") or []
            if not isinstance(rows, list):
                return None
            matches = 0
            for row in rows:
                budget.check()
                if (
                    isinstance(row, dict)
                    and row.get("run_evidence_id") == run_id
                ):
                    row["selected"] = False
                    matches += 1
            if matches != 1:
                return None
            owner.properties["legacy_item"] = updated_legacy

    for element in working.elements:
        budget.check()
        element.properties.pop("text_reconciliation", None)
        legacy = element.properties.get("legacy_item")
        if isinstance(legacy, Mapping):
            updated = dict(legacy)
            updated.pop("text_reconciliation", None)
            for row in updated.get("selective_ocr_candidates") or []:
                if isinstance(row, dict):
                    row["selected"] = False
            element.properties["legacy_item"] = updated
        raw_ocr = element.properties.get("selective_span_ocr")
        if isinstance(raw_ocr, Mapping):
            updated_ocr = dict(raw_ocr)
            updated_ocr["selected"] = False
            element.properties["selective_span_ocr"] = updated_ocr
        raw_font = element.properties.get("font_recovery")
        if isinstance(raw_font, Mapping):
            updated_font = dict(raw_font)
            updated_font["selected"] = False
            element.properties["font_recovery"] = updated_font
    for evidence in working.evidence:
        budget.check()
        evidence.metadata.pop("text_reconciliation", None)
        if str(evidence.method.value) == "ocr":
            evidence.metadata["selected"] = False
    for relationship in working.relationships:
        budget.check()
        relationship.metadata.pop("text_reconciliation", None)
        if str(relationship.type.value) == "alternative_of":
            relationship.metadata["selected"] = False
    retained_concerns = []
    for concern in working.concerns:
        budget.check()
        if concern.code in {
            "pdf_text_reconciliation_complete",
            "pdf_text_reconciliation_selected",
            "pdf_text_reconciliation_unresolved",
        }:
            continue
        concern.metadata.pop("text_reconciliation", None)
        retained_concerns.append(concern)
    working.concerns = retained_concerns

    try:
        prior = DocumentIR.model_validate(working.model_dump(mode="json"))
        budget.check()
        lineage_index = _ir_build_lineage_index(prior, budget)
        font_groups, _font_contexts, font_issues = _ir_font_groups(
            prior,
            budget=budget,
            lineage_index=lineage_index,
        )
        ocr_groups, _ocr_contexts, ocr_issues = _ir_ocr_groups(
            prior,
            budget=budget,
            lineage_index=lineage_index,
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        return None
    groups = [*font_groups, *ocr_groups]
    if (
        font_issues
        or ocr_issues
        or len(groups) != report.group_count
    ):
        return None
    recomputed = reconcile_text_candidates(
        groups,
        source_sha256=prior.source_sha256,
        clock=budget.clock,
        _started=budget.started,
    )
    budget.check()
    return recomputed if recomputed.status == "complete" else None


def _ir_existing_reconciliation_state(
    ir: Any,
    *,
    budget: _IRAdapterBudget | None = None,
) -> Literal[
    "absent",
    "complete",
    "incoherent",
]:
    """Classify previously applied reconciliation artifacts.

    A lone surface marker must never suppress reconciliation.  Re-entry is
    accepted only when one source-bound manifest and every copied trace agree
    with the same strict complete report.
    """

    active_budget = budget or _IRAdapterBudget()
    manifests: list[Any] = []
    terminal_concerns: list[Any] = []
    for concern in ir.concerns:
        active_budget.check()
        if concern.code == "pdf_text_reconciliation_complete":
            manifests.append(concern)
        if concern.code in {
            "pdf_text_reconciliation_selected",
            "pdf_text_reconciliation_unresolved",
        }:
            terminal_concerns.append(concern)
    surface_artifact = False
    for element in ir.elements:
        active_budget.check()
        if "text_reconciliation" in element.properties:
            surface_artifact = True
        legacy = element.properties.get("legacy_item")
        if (
            isinstance(legacy, Mapping)
            and "text_reconciliation" in legacy
        ):
            surface_artifact = True
    for evidence in ir.evidence:
        active_budget.check()
        surface_artifact = surface_artifact or (
            "text_reconciliation" in evidence.metadata
        )
    for relationship in ir.relationships:
        active_budget.check()
        surface_artifact = surface_artifact or (
            "text_reconciliation" in relationship.metadata
        )
    has_artifact = bool(
        manifests or terminal_concerns or surface_artifact
    )
    if not has_artifact:
        return "absent"

    # A prior transactional refusal is already fail-closed and may be
    # returned byte-for-byte on retry.
    if (
        not manifests
        and not surface_artifact
        and terminal_concerns
        and all(
            concern.code == "pdf_text_reconciliation_unresolved"
            and concern.metadata.get("transactional") is True
            for concern in terminal_concerns
        )
    ):
        return "complete"
    if len(manifests) != 1:
        return "incoherent"

    manifest = manifests[0]
    metadata = manifest.metadata
    raw_report = metadata.get("report")
    if (
        metadata.get("schema_version")
        != TEXT_RECONCILIATION_SCHEMA_VERSION
        or metadata.get("policy_id") != TEXT_RECONCILIATION_POLICY_ID
        or metadata.get("source_sha256") != ir.source_sha256
        or not isinstance(raw_report, Mapping)
    ):
        return "incoherent"
    raw_outcomes = raw_report.get("outcomes")
    raw_concerns = raw_report.get("concerns")
    if (
        not isinstance(raw_outcomes, Sequence)
        or isinstance(raw_outcomes, (str, bytes, bytearray))
        or len(raw_outcomes) > MAX_RECONCILIATION_GROUPS
        or not isinstance(raw_concerns, Sequence)
        or isinstance(raw_concerns, (str, bytes, bytearray))
        or len(raw_concerns) > MAX_RECONCILIATION_CONCERNS
    ):
        return "incoherent"
    raw_candidate_count = 0
    for raw_outcome in raw_outcomes:
        active_budget.check()
        if not isinstance(raw_outcome, Mapping):
            return "incoherent"
        raw_decisions = raw_outcome.get("decisions")
        if (
            not isinstance(raw_decisions, Sequence)
            or isinstance(raw_decisions, (str, bytes, bytearray))
            or len(raw_decisions) > MAX_CANDIDATES_PER_GROUP
        ):
            return "incoherent"
        raw_candidate_count += len(raw_decisions)
        if raw_candidate_count > MAX_RECONCILIATION_CANDIDATES:
            return "incoherent"
    try:
        report = TextReconciliationReport.model_validate(dict(raw_report))
    except (TypeError, ValueError, ValidationError):
        return "incoherent"
    if (
        report.status != "complete"
        or report.source_sha256 != ir.source_sha256
        or metadata.get("report_sha256")
        != stable_reconciliation_sha256(report)
    ):
        return "incoherent"

    outcomes = {row.group_id: row for row in report.outcomes}
    if len(outcomes) != len(report.outcomes):
        return "incoherent"
    canonical = {
        group_id: outcome.model_dump(mode="json", exclude_none=False)
        for group_id, outcome in outcomes.items()
    }

    discovered_groups: set[str] = set()
    for element in ir.elements:
        active_budget.check()
        raw_font = element.properties.get("font_recovery")
        if isinstance(raw_font, Mapping) and raw_font.get(
            "run_evidence_id"
        ):
            discovered_groups.add(
                f"font-group:{raw_font['run_evidence_id']}"
            )
        raw_ocr = element.properties.get("selective_span_ocr")
        if isinstance(raw_ocr, Mapping) and raw_ocr.get("span_id"):
            discovered_groups.add(f"ocr-group:{raw_ocr['span_id']}")
        legacy = element.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            continue
        for row in legacy.get("font_recovery_alternatives") or []:
            if isinstance(row, Mapping) and row.get("run_evidence_id"):
                discovered_groups.add(
                    f"font-group:{row['run_evidence_id']}"
                )
    if (
        len(discovered_groups) > MAX_RECONCILIATION_GROUPS
        or discovered_groups != set(outcomes)
    ):
        return "incoherent"

    terminal_by_group: dict[str, list[Any]] = defaultdict(list)
    for concern in terminal_concerns:
        active_budget.check()
        raw_outcome = concern.metadata.get("outcome")
        if not isinstance(raw_outcome, Mapping):
            return "incoherent"
        try:
            parsed = TextReconciliationOutcome.model_validate(
                dict(raw_outcome)
            )
        except (TypeError, ValueError, ValidationError):
            return "incoherent"
        if raw_outcome != canonical.get(parsed.group_id):
            return "incoherent"
        expected_code = (
            "pdf_text_reconciliation_unresolved"
            if parsed.status == "unresolved"
            else "pdf_text_reconciliation_selected"
        )
        if concern.code != expected_code:
            return "incoherent"
        terminal_by_group[parsed.group_id].append(concern)
    if (
        set(terminal_by_group) != set(outcomes)
        or any(len(rows) != 1 for rows in terminal_by_group.values())
    ):
        return "incoherent"

    evidence_by_id: dict[str, Any] = {}
    for row in ir.evidence:
        active_budget.check()
        evidence_by_id[row.id] = row
    elements_by_id: dict[str, Any] = {}
    for element in ir.elements:
        active_budget.check()
        elements_by_id[element.id] = element
    selected_evidence_elements: dict[str, set[str]] = defaultdict(set)
    expected_evidence: dict[str, tuple[str, bool, str, str]] = {}
    for outcome in report.outcomes:
        active_budget.check()
        for decision in outcome.decisions:
            active_budget.check()
            for evidence_id in decision.evidence_ids:
                active_budget.check()
                record = evidence_by_id.get(evidence_id)
                if record is None:
                    continue
                if evidence_id in expected_evidence:
                    return "incoherent"
                expected_evidence[evidence_id] = (
                    outcome.group_id,
                    decision.selected,
                    outcome.status,
                    outcome.reason_code,
                )
                if decision.selected:
                    selected_evidence_elements[outcome.group_id].add(
                        record.element_id
                    )

    element_trace_groups: dict[str, set[str]] = defaultdict(set)

    def validate_trace_rows(
        raw_value: Any,
        *,
        element_id: str | None,
        surface_selected: bool,
    ) -> bool:
        rows = (
            [raw_value]
            if isinstance(raw_value, Mapping)
            else (
                list(raw_value)
                if isinstance(raw_value, Sequence)
                and not isinstance(
                    raw_value,
                    (str, bytes, bytearray),
                )
                else []
            )
        )
        if not rows:
            return False
        for raw_row in rows:
            active_budget.check()
            if not isinstance(raw_row, Mapping):
                return False
            row = dict(raw_row)
            selected = row.pop("selected", None) if surface_selected else None
            group_id = str(row.get("group_id") or "")
            if row != canonical.get(group_id):
                return False
            outcome = outcomes[group_id]
            if surface_selected:
                expected_selected = bool(
                    outcome.status in {"selected", "unchanged"}
                    and element_id is not None
                    and (
                        element_id == outcome.owner_element_id
                        or element_id
                        in selected_evidence_elements[group_id]
                    )
                )
                if selected is not expected_selected:
                    return False
                element_trace_groups[str(element_id)].add(group_id)
        return True

    for element in ir.elements:
        active_budget.check()
        if "text_reconciliation" in element.properties and not (
            validate_trace_rows(
                element.properties.get("text_reconciliation"),
                element_id=element.id,
                surface_selected=True,
            )
        ):
            return "incoherent"
        legacy = element.properties.get("legacy_item")
        if (
            isinstance(legacy, Mapping)
            and "text_reconciliation" in legacy
            and not validate_trace_rows(
                legacy.get("text_reconciliation"),
                element_id=None,
                surface_selected=False,
            )
        ):
            return "incoherent"
    if any(
        outcome.group_id
        not in element_trace_groups.get(outcome.owner_element_id, set())
        for outcome in report.outcomes
    ):
        return "incoherent"

    for evidence in ir.evidence:
        active_budget.check()
        state = evidence.metadata.get("text_reconciliation")
        expected = expected_evidence.get(evidence.id)
        if state is None:
            if expected is not None:
                return "incoherent"
            continue
        if expected is None or not isinstance(state, Mapping):
            return "incoherent"
        group_id, selected, status, reason_code = expected
        if dict(state) != {
            "group_id": group_id,
            "selected": selected,
            "status": status,
            "reason_code": reason_code,
        }:
            return "incoherent"

    for relationship in ir.relationships:
        active_budget.check()
        state = relationship.metadata.get("text_reconciliation")
        if str(relationship.type.value) != "alternative_of":
            if state is not None:
                return "incoherent"
            continue
        source_groups = element_trace_groups.get(
            relationship.source_id,
            set(),
        )
        if not source_groups:
            if state is not None:
                return "incoherent"
            continue
        if len(source_groups) != 1 or not isinstance(state, Mapping):
            return "incoherent"
        group_id = next(iter(source_groups))
        outcome = outcomes[group_id]
        expected_selected = bool(
            outcome.status in {"selected", "unchanged"}
            and relationship.source_id
            in selected_evidence_elements[group_id]
        )
        if dict(state) != {
            "group_id": group_id,
            "selected": expected_selected,
            "status": outcome.status,
            "reason_code": outcome.reason_code,
        }:
            return "incoherent"

    for outcome in report.outcomes:
        active_budget.check()
        if (
            outcome.group_id.startswith("ocr-group:")
            and outcome.status in {"selected", "unchanged"}
        ):
            owner = elements_by_id.get(outcome.owner_element_id)
            if (
                owner is None
                or _ir_text_value(owner) != outcome.selected_text
                or (
                    isinstance(owner.markdown, str)
                    and owner.markdown != outcome.selected_text
                )
            ):
                return "incoherent"
    recomputed = _ir_recompute_retained_report(
        ir,
        report,
        active_budget,
    )
    if (
        recomputed is None
        or stable_reconciliation_sha256(recomputed)
        != stable_reconciliation_sha256(report)
    ):
        return "incoherent"
    return "complete"


def reconcile_document_ir(ir: Any) -> Any:
    """Reconcile IR alternatives transactionally and preserve caller state."""

    from app.services.ir import DocumentIR

    if not isinstance(ir, DocumentIR):
        raise TypeError("reconcile_document_ir requires a DocumentIR")
    budget = _IRAdapterBudget()
    try:
        existing_state = _ir_existing_reconciliation_state(
            ir,
            budget=budget,
        )
    except _IRAdapterLimit as exc:
        return _ir_append_failure(ir, [exc.code])
    if existing_state == "complete":
        return ir
    if existing_state == "incoherent":
        return _ir_quarantine_incoherent_reconciliation(ir)
    try:
        lineage_index = _ir_build_lineage_index(ir, budget)
        font_groups, font_contexts, font_issues = _ir_font_groups(
            ir,
            budget=budget,
            lineage_index=lineage_index,
        )
        ocr_groups, ocr_contexts, ocr_issues = _ir_ocr_groups(
            ir,
            budget=budget,
            lineage_index=lineage_index,
        )
        groups = [*font_groups, *ocr_groups]
        contexts = {**font_contexts, **ocr_contexts}
        issues = [*font_issues, *ocr_issues]
        if not groups and not issues:
            return ir
        if issues:
            return _ir_append_failure(ir, issues)

        report = reconcile_text_candidates(
            groups,
            source_sha256=ir.source_sha256,
            clock=budget.clock,
            _started=budget.started,
        )
        budget.check()
        if report.status != "complete" or len(report.outcomes) != len(
            groups
        ):
            return _ir_append_failure(
                ir,
                [
                    "report_not_complete",
                    *[concern.code for concern in report.concerns],
                ],
            )
        return _ir_apply_report(ir, report, contexts, budget=budget)
    except _IRAdapterLimit as exc:
        return _ir_append_failure(ir, [exc.code])
    except Exception as exc:
        return _ir_append_failure(
            ir,
            [f"adapter_failure:{type(exc).__name__}"],
        )
