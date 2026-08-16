"""Deterministic readiness fixtures for P03-US08.

PDF fixtures are assembled directly with stable object numbers, xref offsets,
and optional ``/PageLabels`` number trees.  Non-PDF fixtures are canonical
JSON dictionaries or executable boundary/state witnesses.  No production
module imports this package.
"""

from __future__ import annotations

import gc
import hashlib
import importlib.util
import io
import json
import math
import pickle
import sys
from collections.abc import Callable, Mapping, Sequence
from copy import copy, deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

try:  # Normal package import when a test harness supplies package context.
    from . import contract as _contract
except (ImportError, ValueError):  # Direct SourceFileLoader/module execution.
    _CONTRACT_PATH = Path(__file__).with_name("contract.py")
    _CONTRACT_NAME = "_p03_us08_running_regions_contract"
    _SPEC = importlib.util.spec_from_file_location(_CONTRACT_NAME, _CONTRACT_PATH)
    if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import machinery
        raise RuntimeError("could not load the US08 readiness contract")
    _contract = importlib.util.module_from_spec(_SPEC)
    sys.modules.setdefault(_CONTRACT_NAME, _contract)
    _SPEC.loader.exec_module(_contract)


FixtureKind = Literal["pdf", "contract_spec", "resource_spec", "state_spec"]
ResourceUnit = Literal[
    "items", "bytes", "characters", "utf8_bytes", "json_bytes", "plan_json_bytes"
]

POLICY_ID = _contract.POLICY_ID
SYNTHETIC_THRESHOLDS: Mapping[str, int | float] = MappingProxyType(
    dict(_contract.RESOURCE_LIMITS)
)

_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_DOCUMENT_ID = b"5030335553303852554e4e494e475245"

REQUIRED_SYNTHETIC_COVERAGE = (
    "embedded_only_label",
    "detected_embedded_agreement",
    "detected_embedded_conflict",
    "roman_embedded_label",
    "prefixed_embedded_label",
    "absent_embedded_label",
    "safe_legacy_fallback",
    "empty_legacy_physical_fallback",
    "hostile_legacy_physical_fallback",
    "invalid_physical_index_refusal",
    "page_of_total_positive",
    "fraction_total_positive",
    "page_pipe_positive",
    "composite_footer_suffix_positive",
    "trusted_top_bare_positive",
    "standalone_bottom_bare_positive",
    "repeated_header_footer_positive",
    "varying_page_placeholder_positive",
    "single_page_navigation_positive",
    "body_edge_number_negative",
    "single_page_heading_negative",
    "date_currency_percentage_negative",
    "table_visible_label_negative",
    "chart_visible_label_negative",
    "form_visible_label_negative",
    "outline_visible_label_negative",
    "note_visible_label_negative",
    "prior_owner_negative",
    "multiple_visible_candidate_negative",
    "repeated_body_negative",
    "inconsistent_band_geometry_negative",
    "effective_bottom_cluster_positive",
    "effective_boundary_cluster_member_positive",
    "effective_label_outside_nominal_positive",
    "effective_missing_cue_negative",
    "effective_missing_label_negative",
    "effective_two_item_negative",
    "effective_overlapping_body_negative",
    "effective_claimed_owner_negative",
    "effective_noncontiguous_negative",
    "effective_outer_thirty_percent_negative",
    "effective_ambiguous_cut_negative",
    "extracted_contribution_positive",
    "extracted_canonical_residual_positive",
    "extracted_owner_unchanged_positive",
    "extracted_non_native_negative",
    "extracted_non_repeated_negative",
    "extracted_non_line_negative",
    "extracted_multi_match_negative",
    "extracted_overlap_negative",
    "extracted_table_owner_negative",
    "extracted_form_owner_negative",
    "extracted_outline_owner_negative",
    "extracted_over_limit_negative",
    "extracted_changed_owner_negative",
    "extracted_too_many_intervals_negative",
    "extracted_non_source_order_negative",
    "hostile_markup_label",
    "control_label",
    "bidi_label",
    "oversize_label",
    "outer_whitespace_label",
    "unsupported_punctuation_label",
    "markdown_link_label",
    "markdown_image_label",
    "percent_encoded_label",
    "entity_encoded_label",
    "crlf_label",
    "c1_label",
    "unicode_line_separator_label",
    "unicode_paragraph_separator_label",
    "unpaired_surrogate_label",
    "noncharacter_label",
    "malformed_geometry",
    "cross_unit_bbox_refusal",
    "cross_page_bbox_refusal",
    "nan_bbox_refusal",
    "zero_bbox_refusal",
    "out_of_page_bbox_refusal",
    "malformed_schema",
    "unknown_key_refusal",
    "wrong_version_refusal",
    "wrong_policy_refusal",
    "malformed_count_refusal",
    "duplicate_public_path",
    "ownership_conflict",
    "shared_owner_refusal",
    "canonical_mismatch",
    "public_canonical_identity_mismatch",
    "resource_exact_and_maximum_plus_one",
    "source_deadline",
    "page_deadline",
    "document_deadline",
    "flag_off_zero_work",
    "idempotent_projection",
    "page_transaction_rollback",
    "partial_mutation_refusal",
    "direct_strip_refusal",
    "extracted_strip_refusal",
    "document_transaction_rollback",
    "canonical_transaction_rollback",
    "terminal_replay_success",
    "terminal_replay_identity_mismatch",
    "terminal_replay_failure_rollback",
    "terminal_residual_drift_rollback",
    "ir_binding_validation",
)


class SyntheticFixtureIntegrityError(RuntimeError):
    """Raised when deterministic fixtures, hashes, readers, or witnesses drift."""


@dataclass(frozen=True, slots=True)
class SyntheticFixtureDefinition:
    fixture_id: str
    kind: FixtureKind
    purpose: str
    covers: tuple[str, ...]
    page_count: int | None = None
    expected_page_labels: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class PageLabelSpec:
    """One zero-based PDF page-label number-tree transition."""

    page_index: int
    style: Literal["D", "R", "r", "A", "a"] | None = None
    start: int = 1
    prefix: str = ""


@dataclass(frozen=True, slots=True)
class ResourceBoundaryWitness:
    """One isolated, actually measured inclusive or maximum+1 payload."""

    counter: str
    limit: int
    observed: int
    unit: ResourceUnit
    scope: Literal["record", "group", "page", "document"]
    payload: Any

    def measure(self) -> int:
        if self.unit == "bytes":
            if not isinstance(self.payload, bytes):
                raise SyntheticFixtureIntegrityError("byte payload differs")
            return len(self.payload)
        if self.unit == "characters":
            if not isinstance(self.payload, str):
                raise SyntheticFixtureIntegrityError("character payload differs")
            return len(self.payload)
        if self.unit == "items":
            if not isinstance(self.payload, tuple):
                raise SyntheticFixtureIntegrityError("item payload differs")
            return len(self.payload)
        if self.unit == "utf8_bytes":
            if not isinstance(self.payload, str):
                raise SyntheticFixtureIntegrityError("UTF-8 payload differs")
            return len(self.payload.encode("utf-8"))
        if self.unit == "plan_json_bytes":
            if not isinstance(self.payload, tuple) or not self.payload:
                raise SyntheticFixtureIntegrityError("plan JSON payload differs")
            return sum(
                len(_contract.extracted_plan_json_bytes(plan))
                for plan in self.payload
            )
        if not isinstance(self.payload, bytes):
            raise SyntheticFixtureIntegrityError("JSON payload differs")
        json.loads(self.payload.decode("utf-8"))
        return len(self.payload)

    def execute(self) -> bool:
        measured = self.measure()
        if measured != self.observed:
            raise SyntheticFixtureIntegrityError("resource measurement drifted")
        try:
            authoritative = _contract.validate_resource_payload(
                self.counter, self.payload
            )
        except _contract.ReadinessContractError:
            return False
        if authoritative != measured:
            raise SyntheticFixtureIntegrityError(
                "authoritative resource measurement drifted"
            )
        return True


@dataclass(frozen=True, slots=True)
class DeadlineWitness:
    """Injected monotonic-clock boundary with no wall-clock dependence."""

    name: Literal[
        "source_extraction_deadline",
        "projection_page_deadline",
        "projection_document_deadline",
    ]
    limit_seconds: float
    ticks: tuple[float, float]

    def execute(self) -> bool:
        start, finish = self.ticks
        if any(not math.isfinite(value) for value in self.ticks) or finish < start:
            raise SyntheticFixtureIntegrityError("deadline ticks differ")
        try:
            elapsed = _contract.validate_deadline_window(self.name, start, finish)
        except _contract.ReadinessContractError:
            return False
        if not math.isclose(elapsed, finish - start, rel_tol=0.0, abs_tol=1e-12):
            raise SyntheticFixtureIntegrityError(
                "authoritative deadline measurement drifted"
            )
        return True


@dataclass(frozen=True, slots=True)
class StateMachineWitness:
    """Named wrapper around one full public/IR/canonical contract execution."""

    name: str
    committed: bool
    executor: Callable[[], bool]

    def execute(self) -> bool:
        result = self.executor()
        if not isinstance(result, bool) or result is not self.committed:
            raise SyntheticFixtureIntegrityError(
                f"{self.name} full-state outcome differs"
            )
        return result


def _stream(data: bytes) -> bytes:
    return (
        b"<< /Length "
        + str(len(data)).encode("ascii")
        + b" >>\nstream\n"
        + data
        + b"\nendstream"
    )


def _assemble_pdf(objects: Sequence[bytes]) -> bytes:
    parts = [_PDF_HEADER]
    offsets = [0]
    cursor = len(_PDF_HEADER)
    for number, body in enumerate(objects, start=1):
        serialized = f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
        offsets.append(cursor)
        parts.append(serialized)
        cursor += len(serialized)
    xref = cursor
    parts.extend(
        [
            f"xref\n0 {len(objects) + 1}\n".encode("ascii"),
            b"0000000000 65535 f \n",
            *(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]),
            (
                b"trailer\n<< /Size "
                + str(len(objects) + 1).encode("ascii")
                + b" /Root 1 0 R /ID [<"
                + _DOCUMENT_ID
                + b"><"
                + _DOCUMENT_ID
                + b">] >>\n"
            ),
            b"startxref\n",
            str(xref).encode("ascii"),
            b"\n%%EOF\n",
        ]
    )
    return b"".join(parts)


def _literal_string(value: str) -> bytes:
    encoded = value.encode("latin-1", errors="strict")
    escaped = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    escaped = escaped.replace(b"\r", b"\\r").replace(b"\n", b"\\n").replace(b"\t", b"\\t")
    return b"(" + escaped + b")"


def _pdf_text_string(value: str) -> bytes:
    """Use a literal PDF string when safe, otherwise deterministic UTF-16BE."""

    try:
        if all(ord(character) >= 0x20 for character in value):
            return _literal_string(value)
    except UnicodeEncodeError:
        pass
    encoded = value.encode("utf-16-be", errors="surrogatepass")
    return b"<FEFF" + encoded.hex().upper().encode("ascii") + b">"


def _content_stream(lines: Sequence[tuple[float, float, str]]) -> bytes:
    commands: list[bytes] = [b"BT /F1 12 Tf"]
    for x, y, text in lines:
        commands.append(
            f"1 0 0 1 {x:.3f} {y:.3f} Tm ".encode("ascii")
            + _literal_string(text)
            + b" Tj"
        )
    commands.append(b"ET")
    return _stream(b"\n".join(commands))


def _page_labels_object(specs: Sequence[PageLabelSpec]) -> bytes:
    entries: list[bytes] = []
    indexes: set[int] = set()
    for spec in specs:
        if spec.page_index < 0 or spec.page_index in indexes or spec.start < 1:
            raise SyntheticFixtureIntegrityError("page-label number tree differs")
        indexes.add(spec.page_index)
        dictionary: list[bytes] = [b"<<"]
        if spec.style is not None:
            dictionary.extend(
                [
                    b"/S /" + spec.style.encode("ascii"),
                    b"/St " + str(spec.start).encode("ascii"),
                ]
            )
        if spec.prefix:
            dictionary.append(b"/P " + _pdf_text_string(spec.prefix))
        dictionary.append(b">>")
        entries.extend(
            [str(spec.page_index).encode("ascii"), b" ".join(dictionary)]
        )
    return b"<< /Nums [" + b" ".join(entries) + b"] >>"


def _build_pdf(
    pages: Sequence[Sequence[tuple[float, float, str]]],
    *,
    page_labels: Sequence[PageLabelSpec] = (),
) -> bytes:
    if not pages:
        raise SyntheticFixtureIntegrityError("a PDF requires at least one page")
    page_count = len(pages)
    page_object_numbers = tuple(range(3, 3 + page_count))
    content_object_numbers = tuple(range(3 + page_count, 3 + 2 * page_count))
    font_object_number = 3 + 2 * page_count
    labels_object_number = font_object_number + 1 if page_labels else None
    catalog = b"<< /Type /Catalog /Pages 2 0 R"
    if labels_object_number is not None:
        catalog += f" /PageLabels {labels_object_number} 0 R".encode("ascii")
    catalog += b" >>"
    pages_node = (
        b"<< /Type /Pages /Count "
        + str(page_count).encode("ascii")
        + b" /Kids ["
        + b" ".join(f"{number} 0 R".encode("ascii") for number in page_object_numbers)
        + b"] >>"
    )
    page_objects = [
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 "
            + f"{font_object_number} 0 R".encode("ascii")
            + b" >> >> /Contents "
            + f"{content_number} 0 R".encode("ascii")
            + b" >>"
        )
        for content_number in content_object_numbers
    ]
    content_objects = [_content_stream(lines) for lines in pages]
    objects: list[bytes] = [
        catalog,
        pages_node,
        *page_objects,
        *content_objects,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    if page_labels:
        objects.append(_page_labels_object(page_labels))
    return _assemble_pdf(objects)


def _source_alignment_pdf() -> bytes:
    """Return the real source PDF used by terminal-alignment witnesses."""

    return _build_pdf(
        [
            (
                (72.0, 20.0, "RUN NING FOOTER"),
                (72.0, 660.0, "BODY CONTENT"),
            )
        ]
    )


def _rendered_label_visibility_pdf(
    *,
    dark_background: bool,
    glyph_gray_byte: int | None = None,
    glyph_cmyk: tuple[float, float, float, float] | None = None,
    rotation: int = 0,
    split_background: bool = False,
    text_render_mode: int = 0,
    transparent_fill: bool = False,
) -> bytes:
    """Build a fixed ``1`` over white or black for 4 px/pt checks."""

    if not isinstance(dark_background, bool):
        raise SyntheticFixtureIntegrityError(
            "rendered-label background selection differs"
        )
    if glyph_gray_byte is not None and (
        isinstance(glyph_gray_byte, bool)
        or not isinstance(glyph_gray_byte, int)
        or not 0 <= glyph_gray_byte <= 255
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered-label glyph gray differs"
        )
    if glyph_cmyk is not None and (
        glyph_gray_byte is not None
        or len(glyph_cmyk) != 4
        or any(
            isinstance(component, bool)
            or not isinstance(component, (int, float))
            or not math.isfinite(float(component))
            or not 0.0 <= float(component) <= 1.0
            for component in glyph_cmyk
        )
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered-label glyph CMYK differs"
        )
    if (
        isinstance(rotation, bool)
        or not isinstance(rotation, int)
        or rotation not in {0, 90, 180, 270}
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered-label page rotation differs"
        )
    if not isinstance(split_background, bool) or not isinstance(
        transparent_fill, bool
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered-label graphics-state selection differs"
        )
    if (
        isinstance(text_render_mode, bool)
        or not isinstance(text_render_mode, int)
        or text_render_mode not in range(8)
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered-label text render mode differs"
        )
    if glyph_cmyk is not None:
        glyph_fill = (
            " ".join(f"{float(component):.12f}" for component in glyph_cmyk)
            + " k"
        ).encode("ascii")
    elif glyph_gray_byte is not None:
        glyph_fill = f"{glyph_gray_byte / 255.0:.12f} g".encode("ascii")
    else:
        glyph_fill = b"1 1 1 rg"
    background_commands = (
        (
            b"q",
            b"0 0 0 rg",
            b"294 14 12 18 re f",
            b"1 1 1 rg",
            b"306 14 12 18 re f",
            b"Q",
        )
        if split_background
        else (
            b"q",
            b"0 0 0 rg" if dark_background else b"1 1 1 rg",
            b"294 14 24 18 re f",
            b"Q",
        )
    )
    content = _stream(
        b"\n".join(
            (
                *background_commands,
                *((b"/GS0 gs",) if transparent_fill else ()),
                b"BT /F1 12 Tf",
                glyph_fill,
                *(
                    (f"{text_render_mode} Tr".encode("ascii"),)
                    if text_render_mode
                    else ()
                ),
                b"1 0 0 1 300 20 Tm (1) Tj",
                b"ET",
            )
        )
    )
    ext_gstate = (
        b" /ExtGState << /GS0 << /Type /ExtGState /ca 0 >> >>"
        if transparent_fill
        else b""
    )
    page_object = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >>"
        + ext_gstate
        + b" >> /Contents 4 0 R"
        + (b"" if rotation == 0 else f" /Rotate {rotation}".encode("ascii"))
        + b" >>"
    )
    return _assemble_pdf(
        (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
            page_object,
            content,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        )
    )


def _standard_page(*extra: tuple[float, float, str]) -> tuple[tuple[float, float, str], ...]:
    return ((72.0, 700.0, "Body paragraph unique to this physical page."), *extra)


def _embedded_only_pdf() -> bytes:
    return _build_pdf([_standard_page()], page_labels=[PageLabelSpec(0, "D", 7)])


def _embedded_agreement_pdf() -> bytes:
    return _build_pdf(
        [_standard_page((300.0, 28.0, "7"))],
        page_labels=[PageLabelSpec(0, "D", 7)],
    )


def _embedded_conflict_pdf() -> bytes:
    return _build_pdf(
        [_standard_page((300.0, 28.0, "7"))],
        page_labels=[PageLabelSpec(0, "D", 8)],
    )


def _roman_embedded_pdf() -> bytes:
    return _build_pdf([_standard_page()], page_labels=[PageLabelSpec(0, "r", 4)])


def _prefixed_embedded_pdf() -> bytes:
    return _build_pdf(
        [_standard_page()], page_labels=[PageLabelSpec(0, "D", 3, "A-")]
    )


def _absent_embedded_pdf() -> bytes:
    return _build_pdf([_standard_page((300.0, 28.0, "24"))])


def _page_of_total_pdf() -> bytes:
    return _build_pdf([_standard_page((260.0, 28.0, "Page 2 of 28"))])


def _fraction_total_pdf() -> bytes:
    return _build_pdf([_standard_page((280.0, 28.0, "7 / 21"))])


def _page_pipe_pdf() -> bytes:
    return _build_pdf([_standard_page((282.0, 28.0, "PAGE | 37"))])


def _composite_footer_pdf() -> bytes:
    return _build_pdf([_standard_page((72.0, 28.0, "Quarterly Results | 32"))])


def _trusted_top_bare_pdf() -> bytes:
    return _build_pdf([_standard_page((300.0, 768.0, "11"))])


def _standalone_bottom_bare_pdf() -> bytes:
    return _build_pdf([_standard_page((300.0, 24.0, "24"))])


def _repeated_running_pdf() -> bytes:
    pages = [
        (
            (72.0, 768.0, "ACME ANNUAL REPORT"),
            (72.0, 700.0, f"Unique body paragraph {index}."),
            (72.0, 24.0, "CONFIDENTIAL"),
            (300.0, 24.0, str(index)),
        )
        for index in (1, 2, 3)
    ]
    return _build_pdf(pages)


def _varying_placeholder_pdf() -> bytes:
    return _build_pdf(
        [
            (
                (72.0, 700.0, f"Unique body {page}."),
                (72.0, 24.0, f"ACME REPORT | Page {page} of 28"),
            )
            for page in (2, 3, 4)
        ]
    )


def _single_page_navigation_pdf() -> bytes:
    return _build_pdf([_standard_page((72.0, 768.0, "CONTENTS"), (470.0, 24.0, "NEXT"))])


def _body_edge_number_pdf() -> bytes:
    return _build_pdf(
        [
            (
                (72.0, 700.0, "Body section starts here."),
                (72.0, 666.0, "24 participants completed the trial."),
                (72.0, 650.0, "This number belongs to body prose."),
            )
        ]
    )


def _single_page_heading_pdf() -> bytes:
    return _build_pdf([((72.0, 768.0, "2026 OPERATING REVIEW"), (72.0, 700.0, "Body."))])


def _non_target_tokens_pdf() -> bytes:
    return _build_pdf(
        [
            (
                (72.0, 768.0, "August 1, 2026 | $19.50 | 37%"),
                (72.0, 700.0, "Table cell 28  Chart label 30  Form value 32"),
                (72.0, 680.0, "Outline 1.  Footnote 2  Source note 3"),
            )
        ]
    )


def _multiple_visible_pdf() -> bytes:
    return _build_pdf([_standard_page((250.0, 24.0, "7"), (340.0, 24.0, "8"))])


def _repeated_body_pdf() -> bytes:
    return _build_pdf(
        [
            ((72.0, 700.0, "Repeated body boilerplate."), (72.0, 24.0, str(index)))
            for index in (1, 2)
        ]
    )


def _inconsistent_band_pdf() -> bytes:
    return _build_pdf(
        [
            ((72.0, 768.0, "SAME NAVIGATION"), (72.0, 700.0, "Body one.")),
            ((72.0, 24.0, "SAME NAVIGATION"), (72.0, 700.0, "Body two.")),
        ]
    )


def _metadata_prefix_pdf(value: str) -> bytes:
    return _build_pdf([_standard_page()], page_labels=[PageLabelSpec(0, None, 1, value)])


def _hostile_markup_pdf() -> bytes:
    return _metadata_prefix_pdf("<script>alert(1)</script>")


def _control_label_pdf() -> bytes:
    return _metadata_prefix_pdf("7\x00\t8")


def _bidi_label_pdf() -> bytes:
    return _metadata_prefix_pdf("\u202e7\u2069")


def _oversize_label_pdf() -> bytes:
    return _metadata_prefix_pdf("A" * 257)


def _outer_whitespace_pdf() -> bytes:
    return _metadata_prefix_pdf(" 7 ")


def _unsupported_punctuation_pdf() -> bytes:
    return _metadata_prefix_pdf("[7]#{page}")


def _hostile_matrix_pdf() -> bytes:
    values = (
        "[click](https://example.invalid)",
        "![image](x)",
        "%3Cscript%3E",
        "&lt;script&gt;",
        "7\r\n8",
        "7\x858",
        "7\u20288",
        "7\u20298",
    )
    return _build_pdf(
        [_standard_page() for _ in values],
        page_labels=[PageLabelSpec(index, None, 1, value) for index, value in enumerate(values)],
    )


def _effective_bottom_cluster_pdf() -> bytes:
    return _build_pdf(
        [
            (
                (72.0, 500.0, "Last body paragraph before the footer row."),
                (72.0, 120.0, "HOME"),
                (210.0, 120.0, "SUSTAINABILITY REPORT"),
                (500.0, 120.0, "80"),
            )
        ]
    )


def _extracted_fused_pdf() -> bytes:
    return _build_pdf(
        [
            (
                (72.0, 748.0, "NIST AMS 100-76 February 2026"),
                (72.0, 730.0, f"Manufacturing body contribution {page}."),
            )
            for page in (1, 2)
        ]
    )


def _identity_fallback_spec() -> dict[str, Any]:
    return {
        "safe_legacy": {"page_index": 1, "page_label": "A-3", "display_source": "legacy_display_fallback"},
        "empty_legacy": {"page_index": 1, "page_label": "", "display_label": "1", "display_source": "physical"},
        "hostile_legacy": {
            "page_index": 1,
            "page_label": "<script>",
            "display_label": "1",
            "display_source": "physical",
            "concern": "page_identity_display_unsafe",
        },
        "invalid_physical": {"page_index": 0, "expected": "document_refusal"},
    }


def _effective_cluster_spec() -> dict[str, Any]:
    positive = (
        {
            "id": "nav",
            "presentation_index": 10,
            "bbox": {"x": 72.0, "y": 650.0, "width": 60.0, "height": 12.0, "unit": "pt"},
            "navigation_cue": "HOME",
            "normalized_label": None,
            "claimed": False,
        },
        {
            "id": "middle",
            "presentation_index": 11,
            "bbox": {"x": 180.0, "y": 650.0, "width": 80.0, "height": 12.0, "unit": "pt"},
            "navigation_cue": None,
            "normalized_label": None,
            "claimed": False,
        },
        {
            "id": "label",
            "presentation_index": 12,
            "bbox": {"x": 500.0, "y": 650.0, "width": 20.0, "height": 12.0, "unit": "pt"},
            "navigation_cue": None,
            "normalized_label": "80",
            "claimed": False,
        },
    )
    return {
        "positive": positive,
        "remaining_body_bboxes": (
            {"x": 72.0, "y": 100.0, "width": 468.0, "height": 500.0, "unit": "pt"},
        ),
        "negative_mutations": (
            "missing_cue",
            "missing_label",
            "two_items",
            "overlapping_body",
            "claimed_owner",
            "noncontiguous_order",
            "outer_thirty_percent",
            "ambiguous_cut",
        ),
    }


def _extracted_contribution_spec() -> dict[str, Any]:
    source_text = "NIST AMS 100-76 February 2026"
    fragments = ("NIST AMS 100-76", "February 2026")
    intervening = "CHART CONTENT\n"
    predecessor = fragments[0] + "\n" + intervening + fragments[1] + "\nManufacturing body.\n"
    second_start = len((fragments[0] + "\n" + intervening).encode("utf-8"))
    return {
        "source_text": source_text,
        "presentation_text": fragments[0] + "\n" + fragments[1],
        "presentation_fragments": fragments,
        "delimiters": ("\n", "\n"),
        "predecessor_intervals": (
            (0, len((fragments[0] + "\n").encode("utf-8"))),
            (second_start, second_start + len((fragments[1] + "\n").encode("utf-8"))),
        ),
        "source_span_groups": (((0, 15),), ((16, len(source_text.encode("utf-8"))),)),
        "predecessor_canonical": predecessor,
        "residual_canonical": intervening + "Manufacturing body.\n",
        "repetition_page_indexes": (1, 2),
        "interval_limit_witness": {
            "accepted_actual_interval_count": 8,
            "refused_actual_interval_count": 9,
        },
        "synthetic_evidence_record": {
            "fields": _contract.EXTRACTED_EVIDENCE_FIELDS,
            "metadata_fields": _contract.EXTRACTED_EVIDENCE_METADATA_FIELDS,
            "confidence": dict(_contract.EXTRACTED_EVIDENCE_CONFIDENCE),
            "method": "native",
            "value": "exact_native_source_text",
            "source_object_order": "exact",
            "id_prefix": "running-region-evidence",
        },
        "negative_mutations": (
            "non_native",
            "non_repeated",
            "non_line",
            "multi_match",
            "overlap",
            "table_owner",
            "form_owner",
            "outline_owner",
            "over_limit",
            "changed_owner",
            "non_whitespace_drift",
            "residual_drift",
            "too_many_intervals",
            "non_source_fragment_order",
            "terminal_presentation_delimiter",
        ),
    }


def _strip_replay_adversarial_spec() -> dict[str, Any]:
    return {
        "partial_mutation": {"layout_running_region_projected": True},
        "direct_strip": {"predecessor_hash_matches": False, "expected": "refused"},
        "extracted_strip": {"fused_owner_hash_matches": False, "expected": "refused"},
        "extracted_evidence_strip": {
            "synthetic_evidence": "removed",
            "predecessor_owner_evidence": "byte_identical",
            "synthetic_public_item": "removed",
            "synthetic_ir_element": "removed",
            "synthetic_ir_bbox": "removed",
            "synthetic_page_backlinks": "removed",
            "synthetic_canonical_block_and_memberships": "removed",
            "any_residual_or_predecessor_change": "refused",
        },
        "terminal_residual_drift": {
            "before": "Manufacturing body.\n",
            "after": "Manufacturing  body.\n",
            "expected": "restore_pre_alignment_document",
        },
    }


def _build_ir_binding_witness() -> tuple[dict[str, Any], dict[str, Any]]:
    source_sha256 = hashlib.sha256(_source_alignment_pdf()).hexdigest()
    bbox = {"x": 72.0, "y": 760.0, "width": 120.0, "height": 14.0, "unit": "pt"}
    predecessor_item = {
        "id": "item-1",
        "type": "text",
        "label": "page_footer",
        "reading_order": 0,
        "value": "RUNNING FOOTER",
        "md": "RUNNING FOOTER",
        "bbox": bbox,
        "source": "native",
        "confidence": 1.0,
    }
    descriptor = {
        "id": _contract.stable_id(
            "running-region",
            POLICY_ID,
            source_sha256,
            1,
            "element-1",
            "bbox-1",
            "footer",
        ),
        "page_id": "page-1",
        "physical_page_index": 1,
        "role": "footer",
        "canonical_scope": "footer",
        "source_public_item_id": "item-1",
        "source_public_path": ["pages", 0, "items", 0],
        "source_element_id": "element-1",
        "predecessor_type": "text",
        "predecessor_item_sha256": _contract.sha256_json(predecessor_item),
        "bbox_id": "bbox-1",
        "bbox": bbox,
        "evidence_ids": ["evidence-1"],
        "source_object_ids": ["word-1", "word-2", "word-3"],
        "source_method": "trusted_layout_role",
        "repetition_group_id": None,
        "repetition_page_indexes": [],
        "confidence": {"scope": "deterministic_rule", "score": 1.0, "unavailable_reason": None},
        "concern_codes": [],
        "canonical_block_id": "block-1",
    }
    projected_item = {
        **predecessor_item,
        "type": "footer",
        "layout_running_region_projected": True,
        "running_region_policy": POLICY_ID,
        "running_region": descriptor,
    }
    identity = {
        "schema_version": "1.0",
        "policy_id": POLICY_ID,
        "page_id": "page-1",
        "physical_page_index": 1,
        "embedded_label": None,
        "detected_printed_label": None,
        "visible_text": None,
        "display_label": "1",
        "display_source": "legacy_display_fallback",
        "evidence_bbox": None,
        "evidence_source": {
            "method": "legacy_display_fallback",
            "reader": "configured_predecessor",
            "page_index": 1,
            "public_item_id": None,
            "public_path": [],
            "element_id": None,
            "bbox_id": None,
            "evidence_ids": [],
            "source_object_ids": [
                f"configured-predecessor:{source_sha256}:page:1:page_label"
            ],
        },
        "confidence": {
            "scope": "unavailable",
            "score": None,
            "unavailable_reason": "page_identity_source_unavailable",
        },
        "concern_codes": [],
    }
    block = {
        "id": "block-1",
        "page_id": "page-1",
        "primary_element_id": "element-1",
        "primary_element_type": "footer",
        "scope": "footer",
        "markdown": "RUNNING FOOTER",
        "text": "RUNNING FOOTER",
        "contributing_element_ids": ["element-1"],
        "relationship_ids": [],
        "excluded_contributions": [],
        "omission_reason": None,
        "suppressed_by_element_id": None,
    }
    public = {
        "document": {"sha256": source_sha256},
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "items": [projected_item],
                "page_identity": identity,
            }
        ],
        "canonical_presentation": {
            "pages": [
                {
                    "page_id": "page-1",
                    "page_index": 1,
                    "page_identity": identity,
                    "blocks": [block],
                    "body": {"block_ids": [], "markdown": "", "text": ""},
                    "full": {
                        "block_ids": ["block-1"],
                        "markdown": "RUNNING FOOTER\n",
                        "text": "RUNNING FOOTER\n",
                    },
                    "header": {"block_ids": [], "markdown": "", "text": ""},
                    "footer": {
                        "block_ids": ["block-1"],
                        "markdown": "RUNNING FOOTER\n",
                        "text": "RUNNING FOOTER\n",
                    },
                }
            ]
        },
        "processing": {
            "running_regions": {
                "policy_id": POLICY_ID,
                "status": "projected",
                "reason": None,
                "source_page_count": 1,
                "identity_count": 1,
                "detected_label_count": 0,
                "embedded_label_count": 0,
                "legacy_fallback_count": 1,
                "candidate_count": 1,
                "comparison_count": 0,
                "running_region_count": 1,
                "header_count": 0,
                "footer_count": 1,
                "top_navigation_count": 0,
                "bottom_navigation_count": 0,
                "concern_count": 0,
                "extraction_ms": 1.0,
                "projection_ms": 1.0,
                "total_ms": 2.0,
            }
        },
    }
    ir = {
        "source_sha256": source_sha256,
        "pages": [
            {
                "id": "page-1",
                "page_index": 1,
                "element_ids": ["element-1"],
                "presentation_element_ids": ["element-1"],
                "page_identity": identity,
            }
        ],
        "elements": [
            {
                "id": "element-1",
                "page_id": "page-1",
                "type": "footer",
                "label": "page_footer",
                "bbox_ids": ["bbox-1"],
                "evidence_ids": ["evidence-1"],
                "presentation_role": "primary",
                "properties": {
                    "legacy_item": deepcopy(predecessor_item),
                    "source_position": 0,
                },
                "running_region": descriptor,
            }
        ],
        "bboxes": [
            {
                "id": "bbox-1",
                "coordinate_system_id": "coord-1",
                "x": 72.0,
                "y": 760.0,
                "width": 120.0,
                "height": 14.0,
            }
        ],
        "evidence": [
            {"id": "evidence-1", "element_id": "element-1", "bbox_id": "bbox-1"}
        ],
        "coordinate_systems": [
            {"id": "coord-1", "page_id": "page-1", "unit": "pt", "origin": "top_left"}
        ],
    }
    return public, ir


def _malformed_contract_spec() -> dict[str, Any]:
    return {
        "geometry": {
            "cross_unit": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "unit": "px"},
            "nan": {"x": float("nan"), "y": 0.0, "width": 1.0, "height": 1.0, "unit": "pt"},
            "zero_area": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 1.0, "unit": "pt"},
            "out_of_page": {"x": 611.5, "y": 0.0, "width": 2.0, "height": 1.0, "unit": "pt"},
            "cross_page": {"bbox_page_index": 2, "owner_page_index": 1},
        },
        "schema": {
            "unknown_key": {"schema_version": "1.0", "unknown": True},
            "wrong_version": {"schema_version": "2.0"},
            "wrong_policy": {"policy_id": "p03-running-regions-page-identity-v0"},
            "partial_marker": {"layout_running_region_projected": True},
            "malformed_counts": {"page_count": 2, "actual_pages": 1},
        },
        "unsafe_strings": {
            "unpaired_surrogate_codepoint": "U+D800",
            "noncharacter_codepoint": "U+FDD0",
        },
    }


def _ownership_contract_spec() -> dict[str, Any]:
    return {
        "duplicate_public_path": ["pages", 0, "items", 0],
        "claims": [
            {"region_id": "region-a", "source_element_id": "element-1"},
            {"region_id": "region-b", "source_element_id": "element-1"},
        ],
        "prior_owner": {
            "source_element_id": "element-2",
            "owner_policy": "p03-form-semantics-v1",
            "expected": "running_region_ownership_conflict",
        },
        "source_owner_admission": {
            "trusted_top_bare": "requires_exact_page_header_role_binding",
            "excluded_kinds": (
                "table_value",
                "chart",
                "form_value",
                "outline_item",
                "note_value",
            ),
            "prior_semantic_owner": "refused_before_projection",
        },
        "canonical_mismatch": {
            "region_page_id": "page-1",
            "block_page_id": "page-2",
            "region_scope": "header",
            "block_scope": "footer",
        },
        "public_canonical_identity_mismatch": {
            "public_display_label": "7",
            "canonical_display_label": "8",
        },
        "source_projection_bindings": {
            "source_hash_and_page_count": "exact",
            "label_selection": "one_eligible_promotes_zero_falls_back_many_ambiguous",
            "label_and_boundary_ids": "source_scoped_deterministic",
            "boundary_descriptor_crosslinks": "exact",
            "legacy_fallback_source_object_id": (
                "configured-predecessor:{source_sha256}:"
                "page:{physical_page_index}:page_label"
            ),
            "legacy_public_bbox_aliases": "ignored_during_canonical_comparison",
            "direct_owner_type_and_predecessor_hash": "exact",
        },
        "repetition_bindings": {
            "member_pages": "exact_declared_set_with_two_or_more",
            "group_id": "source_band_signature_stable_id",
            "normalized_vertical_midpoint_drift_maximum": 0.02,
            "reciprocal_horizontal_overlap_minimum": 0.5,
            "eligible_source_groups": "must_be_projected",
        },
    }


def _resource_spec() -> dict[str, Any]:
    return {
        "limits": dict(SYNTHETIC_THRESHOLDS),
        "integer_and_byte_counters": tuple(sorted(_RESOURCE_RULES)),
        "boundaries": {
            key: {
                "exact": int(SYNTHETIC_THRESHOLDS[key]),
                "maximum_plus_one": int(SYNTHETIC_THRESHOLDS[key]) + 1,
            }
            for key in sorted(_RESOURCE_RULES)
        },
        "deadlines": {
            "source_extraction_deadline": 2.0,
            "projection_page_deadline": 0.250,
            "projection_document_deadline": 2.0,
        },
    }


def _state_spec() -> dict[str, Any]:
    return {
        "witnesses": tuple(witness.name for witness in build_state_machine_witnesses()),
        "terminal_order": _contract.terminal_reentry_order(
            forms_enabled=True, outlines_enabled=True
        ),
        "rollback_is_atomic": True,
        "page_failure_keeps_safe_fallback_identity": True,
        "flag_off_zero_work": True,
    }


_BUILDERS: dict[str, Callable[[], Any]] = {
    "synthetic:p03-us08:embedded-only-v1": _embedded_only_pdf,
    "synthetic:p03-us08:embedded-agreement-v1": _embedded_agreement_pdf,
    "synthetic:p03-us08:embedded-conflict-v1": _embedded_conflict_pdf,
    "synthetic:p03-us08:embedded-roman-v1": _roman_embedded_pdf,
    "synthetic:p03-us08:embedded-prefixed-v1": _prefixed_embedded_pdf,
    "synthetic:p03-us08:embedded-absent-v1": _absent_embedded_pdf,
    "synthetic:p03-us08:page-of-total-v1": _page_of_total_pdf,
    "synthetic:p03-us08:fraction-total-v1": _fraction_total_pdf,
    "synthetic:p03-us08:page-pipe-v1": _page_pipe_pdf,
    "synthetic:p03-us08:composite-footer-v1": _composite_footer_pdf,
    "synthetic:p03-us08:trusted-top-bare-v1": _trusted_top_bare_pdf,
    "synthetic:p03-us08:bottom-bare-v1": _standalone_bottom_bare_pdf,
    "synthetic:p03-us08:repeated-running-v1": _repeated_running_pdf,
    "synthetic:p03-us08:varying-placeholder-v1": _varying_placeholder_pdf,
    "synthetic:p03-us08:single-navigation-v1": _single_page_navigation_pdf,
    "synthetic:p03-us08:body-edge-number-v1": _body_edge_number_pdf,
    "synthetic:p03-us08:single-heading-v1": _single_page_heading_pdf,
    "synthetic:p03-us08:non-target-tokens-v1": _non_target_tokens_pdf,
    "synthetic:p03-us08:multiple-visible-v1": _multiple_visible_pdf,
    "synthetic:p03-us08:repeated-body-v1": _repeated_body_pdf,
    "synthetic:p03-us08:inconsistent-band-v1": _inconsistent_band_pdf,
    "synthetic:p03-us08:hostile-markup-label-v1": _hostile_markup_pdf,
    "synthetic:p03-us08:control-label-v1": _control_label_pdf,
    "synthetic:p03-us08:bidi-label-v1": _bidi_label_pdf,
    "synthetic:p03-us08:oversize-label-v1": _oversize_label_pdf,
    "synthetic:p03-us08:outer-whitespace-label-v1": _outer_whitespace_pdf,
    "synthetic:p03-us08:unsupported-punctuation-label-v1": _unsupported_punctuation_pdf,
    "synthetic:p03-us08:hostile-label-matrix-v1": _hostile_matrix_pdf,
    "synthetic:p03-us08:effective-bottom-cluster-v1": _effective_bottom_cluster_pdf,
    "synthetic:p03-us08:extracted-fused-source-v1": _extracted_fused_pdf,
    "synthetic:p03-us08:identity-fallbacks-v1": _identity_fallback_spec,
    "synthetic:p03-us08:effective-cluster-contract-v1": _effective_cluster_spec,
    "synthetic:p03-us08:extracted-contribution-contract-v1": _extracted_contribution_spec,
    "synthetic:p03-us08:strip-replay-adversarial-v1": _strip_replay_adversarial_spec,
    "synthetic:p03-us08:malformed-contracts-v1": _malformed_contract_spec,
    "synthetic:p03-us08:ownership-custody-v1": _ownership_contract_spec,
    "synthetic:p03-us08:resource-boundaries-v1": _resource_spec,
    "synthetic:p03-us08:state-machines-v1": _state_spec,
}


SYNTHETIC_FIXTURES: tuple[SyntheticFixtureDefinition, ...] = (
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:embedded-only-v1", "pdf", "Safe embedded-only decimal label.",
        ("embedded_only_label",), 1, ("7",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:embedded-agreement-v1", "pdf", "Detected/embedded exact agreement.",
        ("detected_embedded_agreement",), 1, ("7",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:embedded-conflict-v1", "pdf", "Detected 7 conflicts with embedded 8.",
        ("detected_embedded_conflict",), 1, ("8",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:embedded-roman-v1", "pdf", "Lower-Roman embedded label metadata.",
        ("roman_embedded_label",), 1, ("iv",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:embedded-prefixed-v1", "pdf", "Prefixed decimal embedded label metadata.",
        ("prefixed_embedded_label",), 1, ("A-3",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:embedded-absent-v1", "pdf", "No /PageLabels tree and visible bottom 24.",
        ("absent_embedded_label",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:page-of-total-v1", "pdf", "Visible Page X of Y positive.",
        ("page_of_total_positive",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:fraction-total-v1", "pdf", "Visible X / Y positive.",
        ("fraction_total_positive",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:page-pipe-v1", "pdf", "Visible PAGE | X positive.",
        ("page_pipe_positive",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:composite-footer-v1", "pdf", "Composite footer final-field label.",
        ("composite_footer_suffix_positive",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:trusted-top-bare-v1", "pdf", "Top-band bare token geometry/source bytes.",
        (), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:bottom-bare-v1", "pdf", "Standalone bottom-band bare token.",
        ("standalone_bottom_bare_positive",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:repeated-running-v1", "pdf", "Repeated header/footer and varying page tokens.",
        ("repeated_header_footer_positive",), 3, ("", "", ""),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:varying-placeholder-v1", "pdf", "Repeated footer after {page} substitution.",
        ("varying_page_placeholder_positive",), 3, ("", "", ""),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:single-navigation-v1", "pdf", "Single-page top/bottom navigation cues.",
        ("single_page_navigation_positive",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:body-edge-number-v1", "pdf", "Body number remains non-target.",
        ("body_edge_number_negative",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:single-heading-v1", "pdf", "Single-page heading near top remains body.",
        ("single_page_heading_negative",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:non-target-tokens-v1", "pdf", "Date/currency/percent source-token negative.",
        ("date_currency_percentage_negative",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:multiple-visible-v1", "pdf", "Two distinct visible labels fail promotion.",
        ("multiple_visible_candidate_negative",), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:repeated-body-v1", "pdf", "Repeated body text is not boundary furniture.",
        ("repeated_body_negative",), 2, ("", ""),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:inconsistent-band-v1", "pdf", "Same text moves top to bottom and is refused.",
        ("inconsistent_band_geometry_negative",), 2, ("", ""),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:hostile-markup-label-v1", "pdf", "Script-like embedded metadata.",
        ("hostile_markup_label",), 1, None,
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:control-label-v1", "pdf", "NUL/tab embedded metadata.",
        ("control_label",), 1, None,
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:bidi-label-v1", "pdf", "Bidi override/isolate embedded metadata.",
        ("bidi_label",), 1, None,
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:oversize-label-v1", "pdf", "257-byte embedded metadata.",
        ("oversize_label",), 1, None,
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:outer-whitespace-label-v1", "pdf", "Outer-whitespace metadata.",
        ("outer_whitespace_label",), 1, None,
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:unsupported-punctuation-label-v1", "pdf", "Unsupported punctuation metadata.",
        ("unsupported_punctuation_label",), 1, None,
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:hostile-label-matrix-v1", "pdf",
        "Markdown, encoding, control, and Unicode line-separator metadata.",
        (
            "markdown_link_label", "markdown_image_label", "percent_encoded_label",
            "entity_encoded_label", "crlf_label", "c1_label",
            "unicode_line_separator_label", "unicode_paragraph_separator_label",
        ), 8, None,
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:effective-bottom-cluster-v1", "pdf",
        "Three disjoint same-baseline lower-row items outside the nominal band.",
        (
            "effective_bottom_cluster_positive",
            "effective_boundary_cluster_member_positive",
            "effective_label_outside_nominal_positive",
        ), 1, ("",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:extracted-fused-source-v1", "pdf",
        "Repeated exact native manufacturing source contribution.",
        ("extracted_contribution_positive",), 2, ("", ""),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:identity-fallbacks-v1", "contract_spec",
        "Safe legacy, physical fallback, hostile legacy, and invalid index.",
        (
            "safe_legacy_fallback", "empty_legacy_physical_fallback",
            "hostile_legacy_physical_fallback", "invalid_physical_index_refusal",
        ),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:effective-cluster-contract-v1", "contract_spec",
        "Executable effective-bottom positive and every closed negative.",
        (
            "effective_missing_cue_negative", "effective_missing_label_negative",
            "effective_two_item_negative", "effective_overlapping_body_negative",
            "effective_claimed_owner_negative", "effective_noncontiguous_negative",
            "effective_outer_thirty_percent_negative", "effective_ambiguous_cut_negative",
        ),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:extracted-contribution-contract-v1", "contract_spec",
        "Source/presentation mapping, canonical residual, unchanged owner, and refusals.",
        (
            "extracted_canonical_residual_positive", "extracted_owner_unchanged_positive",
            "extracted_non_native_negative", "extracted_non_repeated_negative",
            "extracted_non_line_negative", "extracted_multi_match_negative",
            "extracted_overlap_negative", "extracted_table_owner_negative",
            "extracted_form_owner_negative", "extracted_outline_owner_negative",
            "extracted_over_limit_negative", "extracted_changed_owner_negative",
            "extracted_too_many_intervals_negative",
            "extracted_non_source_order_negative",
        ),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:strip-replay-adversarial-v1", "contract_spec",
        "Partial/direct/extracted strip refusal and residual-drift rollback.",
        (
            "partial_mutation_refusal", "direct_strip_refusal",
            "extracted_strip_refusal", "terminal_residual_drift_rollback",
        ),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:malformed-contracts-v1", "contract_spec",
        "Malformed geometry/schema and unrepresentable hostile scalar cases.",
        (
            "malformed_geometry", "cross_unit_bbox_refusal", "cross_page_bbox_refusal",
            "nan_bbox_refusal", "zero_bbox_refusal", "out_of_page_bbox_refusal",
            "malformed_schema", "unknown_key_refusal", "wrong_version_refusal",
            "wrong_policy_refusal", "malformed_count_refusal",
            "unpaired_surrogate_label", "noncharacter_label",
        ),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:ownership-custody-v1", "contract_spec",
        "Source-owner admission plus duplicate and public/canonical custody conflicts.",
        (
            "duplicate_public_path", "ownership_conflict", "shared_owner_refusal",
            "canonical_mismatch", "public_canonical_identity_mismatch",
            "trusted_top_bare_positive", "prior_owner_negative",
            "table_visible_label_negative", "chart_visible_label_negative",
            "form_visible_label_negative", "outline_visible_label_negative",
            "note_visible_label_negative",
        ),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:resource-boundaries-v1", "resource_spec",
        "Every integer/byte cap at exact and maximum+1, plus deadlines.",
        ("resource_exact_and_maximum_plus_one", "source_deadline", "page_deadline", "document_deadline"),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us08:state-machines-v1", "state_spec",
        "Flag-off, idempotence, rollback, canonical failure, and terminal replay.",
        (
            "flag_off_zero_work", "idempotent_projection", "page_transaction_rollback",
            "document_transaction_rollback", "canonical_transaction_rollback",
            "terminal_replay_success", "terminal_replay_identity_mismatch",
            "terminal_replay_failure_rollback", "ir_binding_validation",
        ),
    ),
)

SYNTHETIC_FIXTURES_BY_ID: Mapping[str, SyntheticFixtureDefinition] = MappingProxyType(
    {fixture.fixture_id: fixture for fixture in SYNTHETIC_FIXTURES}
)
SYNTHETIC_FIXTURE_IDS = tuple(fixture.fixture_id for fixture in SYNTHETIC_FIXTURES)


_RESOURCE_RULES: Mapping[
    str, tuple[ResourceUnit, Literal["record", "group", "page", "document"]]
] = MappingProxyType(
    {
        "pages_per_document": ("items", "document"),
        "source_pdf_bytes": ("bytes", "document"),
        "source_characters_per_page": ("characters", "page"),
        "source_characters_per_document": ("characters", "document"),
        "source_words_per_page": ("items", "page"),
        "source_words_per_document": ("items", "document"),
        "label_utf8_bytes": ("utf8_bytes", "record"),
        "visible_text_utf8_bytes": ("utf8_bytes", "record"),
        "candidate_text_utf8_bytes": ("utf8_bytes", "record"),
        "extracted_contribution_utf8_bytes": ("utf8_bytes", "record"),
        "extracted_contributions_per_page": ("items", "page"),
        "extracted_contributions_per_document": ("items", "document"),
        "extracted_intervals_per_contribution": ("items", "record"),
        "extracted_residual_plan_bytes_per_page": ("plan_json_bytes", "page"),
        "extracted_residual_plan_bytes_per_document": (
            "plan_json_bytes",
            "document",
        ),
        "label_candidates_per_page": ("items", "page"),
        "boundary_candidates_per_page": ("items", "page"),
        "boundary_candidates_per_document": ("items", "document"),
        "running_regions_per_page": ("items", "page"),
        "running_regions_per_document": ("items", "document"),
        "repetition_groups_per_document": ("items", "document"),
        "repetition_members": ("items", "group"),
        "evidence_ids_per_record": ("items", "record"),
        "source_object_ids_per_record": ("items", "record"),
        "public_path_segments": ("items", "record"),
        "comparisons_per_page": ("items", "page"),
        "comparisons_per_document": ("items", "document"),
        "page_identity_json_bytes": ("json_bytes", "record"),
        "running_descriptor_json_bytes": ("json_bytes", "record"),
        "report_json_bytes": ("json_bytes", "document"),
        "printed_label_render_dimension_pixels": ("items", "record"),
        "printed_label_render_pixels": ("items", "record"),
        "printed_label_non_stroking_fills": ("items", "record"),
        "printed_label_page_dimension_points": ("items", "page"),
        "printed_label_text_objects": ("items", "record"),
        "printed_label_text_object_scan": ("items", "record"),
        "printed_label_form_depth": ("items", "record"),
        "live_source_projection_authorities": ("items", "document"),
        "concerns_per_page": ("items", "page"),
        "concerns_per_document": ("items", "document"),
    }
)


def _contract_json_boundary_payload(counter: str, observed: int) -> bytes:
    """Build one complete contract-valid object at an exact compact-JSON size."""

    public, _ir = _build_ir_binding_witness()
    candidate: dict[str, Any] | None = None
    if counter == "page_identity_json_bytes":
        value = deepcopy(public["pages"][0]["page_identity"])
        filler_owner = value["evidence_source"]["source_object_ids"]
    elif counter == "running_descriptor_json_bytes":
        value = deepcopy(public["pages"][0]["items"][0]["running_region"])
        filler_owner = value["source_object_ids"]
    elif counter == "report_json_bytes":
        source_sha256 = public["document"]["sha256"]
        bbox = {
            "x": 290.0,
            "y": 760.0,
            "width": 30.0,
            "height": 12.0,
            "unit": "pt",
        }
        candidate = {
            "id": "pending",
            "public_item_id": "item-1",
            "public_path": ["pages", 0, "items", 0],
            "element_id": "element-1",
            "predecessor_type": "text",
            "bbox": bbox,
            "bbox_id": "bbox-1",
            "evidence_ids": ["evidence-1"],
            "source_object_ids": ["x"],
            "raw_layout_role": "page_footer",
            "normalized_signature": "running footer",
            "boundary_band": "bottom",
            "source_method": "trusted_layout_role",
            "confidence": {
                "scope": "deterministic_rule",
                "score": 1.0,
                "unavailable_reason": None,
            },
            "concern_codes": [],
            "disposition": "accepted",
        }
        candidate["id"] = _contract.boundary_candidate_id(
            candidate,
            source_sha256=source_sha256,
            physical_page_index=1,
        )
        value = {
            "report_version": _contract.REPORT_VERSION,
            "policy_id": POLICY_ID,
            "source_sha256": source_sha256,
            "status": "available",
            "pages": [
                {
                    "page_index": 1,
                    "page_width": 612.0,
                    "page_height": 792.0,
                    "unit": "pt",
                    "coordinate_system_id": _contract.COORDINATE_SYSTEM_ID,
                    "source_character_count": 0,
                    "source_word_count": 0,
                    "embedded_label": None,
                    "label_candidates": [],
                    "boundary_candidates": [candidate],
                    "concern_codes": [],
                }
            ],
            "counts": {
                "page_count": 1,
                "source_character_count": 0,
                "source_word_count": 0,
                "embedded_label_count": 0,
                "label_candidate_count": 0,
                "boundary_candidate_count": 1,
                "concern_count": 0,
            },
            "concern_codes": [],
            "extraction_ms": 0.0,
        }
        filler_owner = candidate["source_object_ids"]
    else:
        raise SyntheticFixtureIntegrityError("unknown contract JSON counter")

    filler_owner[0] = "x"
    if candidate is not None:
        candidate["id"] = _contract.boundary_candidate_id(
            candidate,
            source_sha256=value["source_sha256"],
            physical_page_index=1,
        )
    baseline = _contract.strict_json_bytes(value)
    filler_size = observed - len(baseline) + 1
    if filler_size < 1:
        raise SyntheticFixtureIntegrityError("contract JSON boundary is too small")
    filler_owner[0] = "x" * filler_size
    if candidate is not None:
        candidate["id"] = _contract.boundary_candidate_id(
            candidate,
            source_sha256=value["source_sha256"],
            physical_page_index=1,
        )
    payload = _contract.strict_json_bytes(value)
    if len(payload) != observed:
        raise SyntheticFixtureIntegrityError("contract JSON boundary size drifted")
    return payload


def _sized_extracted_plan(
    serialized_size: int, *, page_index: int
) -> _contract.ExtractedContributionPlan:
    """Build one valid plan with an exact compact serialized byte size."""

    def build(filler_size: int, owner_padding: int) -> _contract.ExtractedContributionPlan:
        return _contract.build_extracted_contribution_plan(
            physical_page_index=page_index,
            owner_public_item_id=(f"owner-{page_index}-" + ("o" * owner_padding)),
            owner_sha256="a" * 64,
            predecessor_canonical="HEADER\n" + ("x" * filler_size),
            source_text="HEADER",
            presentation_fragments=("HEADER",),
            delimiters=("\n",),
            predecessor_intervals=((0, 7),),
            source_span_groups=(((0, 6),),),
        )

    baseline = build(1, 0)
    difference = serialized_size - len(_contract.extracted_plan_json_bytes(baseline))
    if difference < 0:
        raise SyntheticFixtureIntegrityError("extracted plan boundary is too small")
    plan = build(1 + difference // 2, difference % 2)
    if len(_contract.extracted_plan_json_bytes(plan)) != serialized_size:
        raise SyntheticFixtureIntegrityError("extracted plan boundary size drifted")
    return plan


def _plan_boundary_payload(counter: str, observed: int) -> tuple[Any, ...]:
    if counter == "extracted_residual_plan_bytes_per_page":
        bounded_size = min(
            observed,
            _contract.MAX_EXTRACTED_RESIDUAL_PLAN_BYTES_PER_PAGE,
        )
        plan = _sized_extracted_plan(bounded_size, page_index=1)
        if observed > bounded_size:
            plan = replace(
                plan,
                owner_public_item_id=(
                    plan.owner_public_item_id + ("o" * (observed - bounded_size))
                ),
            )
        return (plan,)
    if counter != "extracted_residual_plan_bytes_per_document":
        raise SyntheticFixtureIntegrityError("unknown extracted-plan counter")
    plan_count = 17
    quotient, remainder = divmod(observed, plan_count)
    return tuple(
        _sized_extracted_plan(
            quotient + int(offset < remainder),
            page_index=offset + 1,
        )
        for offset in range(plan_count)
    )


def build_resource_boundary_witness(
    counter: str, *, maximum_plus_one: bool = False
) -> ResourceBoundaryWitness:
    """Materialize and measure one isolated real payload at a resource edge."""

    if counter not in _RESOURCE_RULES:
        raise KeyError(f"unknown resource counter: {counter}")
    limit_value = SYNTHETIC_THRESHOLDS[counter]
    if isinstance(limit_value, bool) or not isinstance(limit_value, int):
        raise SyntheticFixtureIntegrityError("resource limit is not integral")
    observed = limit_value + int(maximum_plus_one)
    unit, scope = _RESOURCE_RULES[counter]
    if unit == "bytes":
        payload = b"x" * observed
    elif unit == "characters":
        payload: Any = "x" * observed
    elif unit == "utf8_bytes":
        payload = "x" * observed
    elif unit == "json_bytes":
        payload = _contract_json_boundary_payload(counter, observed)
    elif unit == "plan_json_bytes":
        payload = _plan_boundary_payload(counter, observed)
    else:
        payload = tuple(range(observed))
    return ResourceBoundaryWitness(counter, limit_value, observed, unit, scope, payload)


def build_deadline_witness(
    name: str, *, maximum_plus_one: bool = False
) -> DeadlineWitness:
    """Build exact or one-microsecond-over injected monotonic ticks."""

    key = {
        "source_extraction_deadline": "source_extraction_seconds",
        "projection_page_deadline": "projection_page_seconds",
        "projection_document_deadline": "projection_document_seconds",
    }.get(name)
    if key is None:
        raise KeyError(f"unknown deadline: {name}")
    limit = float(SYNTHETIC_THRESHOLDS[key])
    elapsed = limit + (0.000_001 if maximum_plus_one else 0.0)
    return DeadlineWitness(name, limit, (100.0, 100.0 + elapsed))  # type: ignore[arg-type]


def build_state_machine_witnesses() -> tuple[StateMachineWitness, ...]:
    """Build lifecycle witnesses over a real projected public/IR/canonical bundle."""

    projected_public, projected_ir = _build_ir_binding_witness()
    source_sha256 = projected_public["document"]["sha256"]
    prior_item = {
        "id": "prior-item-2",
        "type": "text",
        "label": "body",
        "reading_order": 0,
        "value": "Prior form and outline content",
        "md": "Prior form and outline content",
        "bbox": {
            "x": 72.0,
            "y": 120.0,
            "width": 240.0,
            "height": 16.0,
            "unit": "pt",
        },
        "layout_forms_projected": True,
        "form_semantics": {
            "group_id": "form-group-2",
            "relationship_ids": ["form-relationship-2"],
        },
        "layout_outline_structure_projected": True,
        "outline_structure": {
            "group_id": "outline-group-2",
            "relationship_ids": ["outline-relationship-2"],
        },
    }
    identity_two = deepcopy(projected_public["pages"][0]["page_identity"])
    identity_two.update(
        {
            "page_id": "page-2",
            "physical_page_index": 2,
            "display_label": "2",
        }
    )
    identity_two["evidence_source"]["page_index"] = 2
    identity_two["evidence_source"]["source_object_ids"] = [
        f"configured-predecessor:{source_sha256}:page:2:page_label"
    ]
    projected_public["pages"].append(
        {
            "page_index": 2,
            "page_number": 2,
            "page_label": "2",
            "page_width": 612.0,
            "page_height": 792.0,
            "unit": "pt",
            "items": [deepcopy(prior_item)],
            "page_identity": deepcopy(identity_two),
        }
    )
    prior_block = {
        "id": "prior-block-2",
        "page_id": "page-2",
        "primary_element_id": "prior-element-2",
        "primary_element_type": "text",
        "scope": "body",
        "markdown": prior_item["md"],
        "text": prior_item["value"],
        "contributing_element_ids": ["prior-element-2"],
        "relationship_ids": [
            "form-relationship-2",
            "outline-relationship-2",
        ],
        "excluded_contributions": [],
        "omission_reason": None,
        "suppressed_by_element_id": None,
    }
    populated_prior_view = {
        "block_ids": [prior_block["id"]],
        "markdown": f"{prior_block['markdown']}\n",
        "text": f"{prior_block['text']}\n",
    }
    empty_prior_view = {"block_ids": [], "markdown": "", "text": ""}
    projected_public["canonical_presentation"]["pages"].append(
        {
            "page_id": "page-2",
            "page_index": 2,
            "page_identity": deepcopy(identity_two),
            "blocks": [prior_block],
            "full": deepcopy(populated_prior_view),
            "body": deepcopy(populated_prior_view),
            "header": deepcopy(empty_prior_view),
            "footer": deepcopy(empty_prior_view),
        }
    )
    projected_summary = projected_public["processing"]["running_regions"]
    projected_summary["source_page_count"] = 2
    projected_summary["identity_count"] = 2
    projected_summary["legacy_fallback_count"] = 2
    projected_ir["pages"].append(
        {
            "id": "page-2",
            "page_index": 2,
            "element_ids": ["prior-element-2"],
            "presentation_element_ids": ["prior-element-2"],
            "page_identity": deepcopy(identity_two),
        }
    )
    projected_ir["elements"].append(
        {
            "id": "prior-element-2",
            "page_id": "page-2",
            "type": "text",
            "label": "body",
            "bbox_ids": ["prior-bbox-2"],
            "evidence_ids": ["prior-evidence-2"],
            "presentation_role": "primary",
            "form_semantics": deepcopy(prior_item["form_semantics"]),
            "outline_structure": deepcopy(prior_item["outline_structure"]),
        }
    )
    projected_ir["bboxes"].append(
        {
            "id": "prior-bbox-2",
            "coordinate_system_id": "coord-2",
            "x": 72.0,
            "y": 120.0,
            "width": 240.0,
            "height": 16.0,
        }
    )
    projected_ir["evidence"].append(
        {
            "id": "prior-evidence-2",
            "element_id": "prior-element-2",
            "bbox_id": "prior-bbox-2",
        }
    )
    projected_ir["coordinate_systems"].append(
        {
            "id": "coord-2",
            "page_id": "page-2",
            "unit": "pt",
            "origin": "top_left",
        }
    )
    _contract.validate_ir_bindings(
        projected_ir, public_document=projected_public
    )
    predecessor_public = deepcopy(projected_public)
    for predecessor_page in predecessor_public["pages"]:
        predecessor_page.pop("page_identity")
    predecessor_page = predecessor_public["pages"][0]
    predecessor_item = predecessor_page["items"][0]
    descriptor = deepcopy(predecessor_item["running_region"])
    for key in _contract.RUNNING_REGION_SIDECAR_FIELDS:
        predecessor_item.pop(key)
    predecessor_item["type"] = descriptor["predecessor_type"]
    for canonical_page in predecessor_public["canonical_presentation"]["pages"]:
        canonical_page.pop("page_identity")
    predecessor_canonical_page = predecessor_public["canonical_presentation"][
        "pages"
    ][0]
    predecessor_block = predecessor_canonical_page["blocks"][0]
    predecessor_block["scope"] = "body"
    predecessor_block["primary_element_type"] = descriptor["predecessor_type"]
    populated_view = {
        "block_ids": [predecessor_block["id"]],
        "markdown": f"{predecessor_block['markdown']}\n",
        "text": f"{predecessor_block['text']}\n",
    }
    empty_view = {"block_ids": [], "markdown": "", "text": ""}
    predecessor_canonical_page["full"] = deepcopy(populated_view)
    predecessor_canonical_page["body"] = deepcopy(populated_view)
    predecessor_canonical_page["header"] = deepcopy(empty_view)
    predecessor_canonical_page["footer"] = deepcopy(empty_view)
    predecessor_public["processing"].pop("running_regions")
    if not predecessor_public["processing"]:
        predecessor_public.pop("processing")
    predecessor_public.pop("running_region_concerns", None)

    predecessor_ir = deepcopy(projected_ir)
    for predecessor_ir_page in predecessor_ir["pages"]:
        predecessor_ir_page.pop("page_identity")
    predecessor_ir_element = predecessor_ir["elements"][0]
    predecessor_ir_element.pop("running_region")
    predecessor_ir_element["type"] = descriptor["predecessor_type"]
    predecessor_state = {
        "public": predecessor_public,
        "ir": predecessor_ir,
    }
    projected_state = {
        "public": projected_public,
        "ir": projected_ir,
    }

    fallback_public = deepcopy(predecessor_public)
    for page_offset, projected_page in enumerate(projected_public["pages"]):
        fallback_identity = deepcopy(projected_page["page_identity"])
        fallback_public["pages"][page_offset]["page_identity"] = deepcopy(
            fallback_identity
        )
        fallback_public["canonical_presentation"]["pages"][page_offset][
            "page_identity"
        ] = deepcopy(fallback_identity)
    fallback_summary = deepcopy(
        projected_public["processing"]["running_regions"]
    )
    fallback_summary["candidate_count"] = 0
    fallback_summary["running_region_count"] = 0
    fallback_summary["footer_count"] = 0
    fallback_public["processing"] = {"running_regions": fallback_summary}
    fallback_ir = deepcopy(predecessor_ir)
    for page_offset, projected_page in enumerate(projected_ir["pages"]):
        fallback_ir["pages"][page_offset]["page_identity"] = deepcopy(
            projected_page["page_identity"]
        )
    fallback_state = {"public": fallback_public, "ir": fallback_ir}
    _contract.validate_ir_bindings(fallback_ir, public_document=fallback_public)

    predecessor_bytes = _contract.strict_json_bytes(predecessor_state)
    projected_bytes = _contract.strict_json_bytes(projected_state)

    def require_payload(
        result: _contract.ProjectionTransactionResult,
        expected: Mapping[str, Any],
        *,
        label: str,
    ) -> None:
        if _contract.strict_json_bytes(result.payload) != _contract.strict_json_bytes(
            expected
        ):
            raise SyntheticFixtureIntegrityError(f"{label} state differs")

    def require_atomic_rollback(
        result: _contract.ProjectionTransactionResult, *, label: str
    ) -> None:
        if result.committed:
            raise SyntheticFixtureIntegrityError(f"{label} unexpectedly committed")
        restored_public = deepcopy(result.payload["public"])
        processing = restored_public.get("processing")
        if isinstance(processing, dict):
            processing.pop("running_regions", None)
            if not processing:
                restored_public.pop("processing")
        restored_public.pop("running_region_concerns", None)
        if (
            _contract.strict_json_bytes(restored_public)
            != _contract.strict_json_bytes(predecessor_public)
            or _contract.strict_json_bytes(result.payload["ir"])
            != _contract.strict_json_bytes(predecessor_ir)
        ):
            raise SyntheticFixtureIntegrityError(
                f"{label} did not restore the full predecessor"
            )

    def execute_flag_off() -> bool:
        calls: list[str] = []

        def forbidden_feature_hook() -> None:
            calls.append("called")

        result = _contract.execute_flag_off_witness(
            _contract.prepare_flag_off_witness(predecessor_state),
            feature_hooks=(
                forbidden_feature_hook,
                forbidden_feature_hook,
                forbidden_feature_hook,
            ),
        )
        if calls:
            raise SyntheticFixtureIntegrityError("flag-off executed a US08 hook")
        require_payload(result, predecessor_state, label="flag-off")
        return result.committed

    def projector(bundle: Mapping[str, Any]) -> Mapping[str, Any]:
        serialized = _contract.strict_json_bytes(bundle)
        if serialized in {predecessor_bytes, projected_bytes}:
            return deepcopy(projected_state)
        raise _contract.ReadinessContractError("fixed-point input differs")

    def execute_idempotence() -> bool:
        first, second = _contract.IdempotenceWitness(
            predecessor=predecessor_state,
            projector=projector,
        ).execute()
        if (
            _contract.strict_json_bytes(first) != projected_bytes
            or _contract.strict_json_bytes(second) != projected_bytes
        ):
            raise SyntheticFixtureIntegrityError(
                "idempotence full-state fixed point differs"
            )
        return True

    def execute_successful_page_fallback() -> bool:
        result = _contract.execute_transaction_witness(
            predecessor_state,
            projected_state=projected_state,
            fallback_state=fallback_state,
            outcome="page_failure",
            physical_page_index=1,
        )
        require_payload(result, fallback_state, label="page fallback")
        _expect_contract_rejection(
            lambda: _contract.execute_transaction_witness(
                predecessor_state,
                projected_state=projected_state,
                fallback_state=fallback_state,
                outcome="page_failure",
                physical_page_index=0,
            ),
            "nonpositive physical page fallback index",
        )
        nonfailed_page_drift = deepcopy(fallback_state)
        nonfailed_page_drift["public"]["pages"][1]["items"][0][
            "form_semantics"
        ]["group_id"] = "forged-unaffected-form-group"
        _expect_contract_rejection(
            lambda: _contract.execute_transaction_witness(
                predecessor_state,
                projected_state=projected_state,
                fallback_state=nonfailed_page_drift,
                outcome="page_failure",
                physical_page_index=1,
            ),
            "page fallback unaffected-page prior-stage drift",
        )
        return result.committed

    def execute_document_failure(
        outcome: Literal["document_failure", "canonical_failure"],
    ) -> bool:
        result = _contract.execute_transaction_witness(
            predecessor_state,
            projected_state=projected_state,
            outcome=outcome,
        )
        require_atomic_rollback(result, label=outcome)
        return result.committed

    terminal_pass_summary = deepcopy(
        projected_public["processing"]["running_regions"]
    )
    terminal_pass_summary.update(
        {"extraction_ms": 0.125, "projection_ms": 0.125, "total_ms": 0.25}
    )
    replayed_state = deepcopy(projected_state)
    replayed_state["public"]["processing"]["running_regions"] = (
        _contract.combine_terminal_processing_summaries(
            projected_public["processing"]["running_regions"],
            terminal_pass_summary,
        )
    )

    def execute_terminal_success() -> bool:
        result = _contract.TerminalReplayWitness(
            configured_predecessor=predecessor_state,
            replay_state_before=projected_state,
            replay_state_after=replayed_state,
            terminal_processing_summary=terminal_pass_summary,
            forms_enabled=False,
            outlines_enabled=False,
        ).execute()
        require_payload(result, replayed_state, label="terminal replay")
        return result.committed

    replay_drift_state = deepcopy(replayed_state)
    replay_drift_state["public"]["canonical_presentation"]["pages"][0]["full"][
        "text"
    ] = "fabricated terminal state\n"

    def require_replay_rollback(
        result: _contract.ProjectionTransactionResult, *, label: str
    ) -> None:
        if result.committed or (
            _contract.strict_json_bytes(result.payload) != projected_bytes
        ):
            raise SyntheticFixtureIntegrityError(
                f"{label} did not restore the pre-alignment snapshot"
            )

    def execute_terminal_rollback(
        *,
        fail_at: Literal[
            "none", "alignment", "running_replay", "identity", "canonical"
        ],
        replay_after: Mapping[str, Any],
    ) -> bool:
        result = _contract.TerminalReplayWitness(
            configured_predecessor=predecessor_state,
            replay_state_before=projected_state,
            replay_state_after=replay_after,
            terminal_processing_summary=terminal_pass_summary,
            forms_enabled=False,
            outlines_enabled=False,
            fail_at=fail_at,
        ).execute()
        require_replay_rollback(result, label=f"terminal {fail_at}")
        return result.committed

    return (
        StateMachineWitness("flag_off", True, execute_flag_off),
        StateMachineWitness("idempotence", True, execute_idempotence),
        StateMachineWitness(
            "page_rollback", True, execute_successful_page_fallback
        ),
        StateMachineWitness(
            "document_rollback",
            False,
            lambda: execute_document_failure("document_failure"),
        ),
        StateMachineWitness(
            "canonical_rollback",
            False,
            lambda: execute_document_failure("canonical_failure"),
        ),
        StateMachineWitness("terminal_replay", True, execute_terminal_success),
        StateMachineWitness(
            "terminal_identity_mismatch",
            False,
            lambda: execute_terminal_rollback(
                fail_at="none", replay_after=replay_drift_state
            ),
        ),
        StateMachineWitness(
            "terminal_replay_failure",
            False,
            lambda: execute_terminal_rollback(
                fail_at="running_replay", replay_after=projected_state
            ),
        ),
    )


def build_synthetic_fixture(fixture_id: str) -> dict[str, Any]:
    """Build one fixture afresh and return metadata plus deterministic payload."""

    definition = SYNTHETIC_FIXTURES_BY_ID.get(fixture_id)
    if definition is None:
        raise KeyError(f"unknown fixture: {fixture_id}")
    payload = _BUILDERS[fixture_id]()
    return {
        "fixture_id": definition.fixture_id,
        "kind": definition.kind,
        "purpose": definition.purpose,
        "covers": definition.covers,
        "payload": payload,
    }


def _payload_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload

    def framed(value: Any) -> Any:
        if isinstance(value, float) and not math.isfinite(value):
            return {"$nonfinite_float": "nan" if math.isnan(value) else "inf" if value > 0 else "-inf"}
        if isinstance(value, Mapping):
            return {str(key): framed(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [framed(item) for item in value]
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return {"$unicode_codepoints": [ord(character) for character in value]}
        return value

    return _contract.strict_json_bytes(framed(payload))


def fixture_hashes() -> dict[str, str]:
    """Return deterministic SHA-256 identities for all registered payloads."""

    return {
        fixture_id: hashlib.sha256(
            _payload_bytes(build_synthetic_fixture(fixture_id)["payload"])
        ).hexdigest()
        for fixture_id in SYNTHETIC_FIXTURE_IDS
    }


def registry_sha256() -> str:
    semantic = [
        {
            "fixture_id": definition.fixture_id,
            "kind": definition.kind,
            "purpose": definition.purpose,
            "covers": definition.covers,
            "page_count": definition.page_count,
            "expected_page_labels": definition.expected_page_labels,
            "payload_sha256": fixture_hashes()[definition.fixture_id],
        }
        for definition in SYNTHETIC_FIXTURES
    ]
    return hashlib.sha256(_contract.strict_json_bytes(semantic)).hexdigest()


# Literal payload identities: any semantic or byte drift requires explicit review.
FROZEN_FIXTURE_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "synthetic:p03-us08:bidi-label-v1": "beee6c955eedef82e7b1d44efd2e4b1bb0b82ce348ee582929885ea7ea357983",
        "synthetic:p03-us08:body-edge-number-v1": "e435d980101644a62220a1c89a7941b0eb4061920213f412a9eaa164ccefcd7d",
        "synthetic:p03-us08:bottom-bare-v1": "b440a142ff533b2d1233307d9cc325cd88fd928731fc4233091bf8abc97e3a6f",
        "synthetic:p03-us08:composite-footer-v1": "28807ebd0536c312418814ca3232c2892d9fcac3f420ba5b42505e6b06c44054",
        "synthetic:p03-us08:control-label-v1": "7125c9fc33cb39f0bb61c7ec61263c3550832adc9648bcfcbace1e244517d8ac",
        "synthetic:p03-us08:effective-bottom-cluster-v1": "8ba78fd0c273151b8feb139a62f7853a79ae1d9b7e52f006fe3aa8a6886ac7e5",
        "synthetic:p03-us08:effective-cluster-contract-v1": "195b06bebbd91e15d71f8a804e9323f570c15af03e564d08543e2f3934ce658f",
        "synthetic:p03-us08:embedded-absent-v1": "cc3b3076339acde60bdef40938c786f10d5937c2119b79dc5652f410adb249e4",
        "synthetic:p03-us08:embedded-agreement-v1": "b75313d3f1042c40313846755c55b755a178649e4feab901279fad96915a5c35",
        "synthetic:p03-us08:embedded-conflict-v1": "cfff99f8ef2cc61e078b7c0fa01a5b05e6ae72e7ecad5c7f028ef8cbaf4c80db",
        "synthetic:p03-us08:embedded-only-v1": "cf8717694086c2c4d127a4c0113c503429e6c9f964e8eed9d960d073040f4ff0",
        "synthetic:p03-us08:embedded-prefixed-v1": "4635b10ae2c82c9a06a944b307b31ee82f883efe501bf2db666793fb344cd25f",
        "synthetic:p03-us08:embedded-roman-v1": "01922654f5fc5f33bf187e4ca76de06d49481fb125ef165660ea42cbda8ba392",
        "synthetic:p03-us08:extracted-contribution-contract-v1": "f0e11c84c87c792827285780713a65f71bafd13dcaa1f8c6a63190a67aaa404d",
        "synthetic:p03-us08:extracted-fused-source-v1": "6d9100f1cf1ceaae886504a60114484d4a529d613b983800a2828e27b5a605aa",
        "synthetic:p03-us08:fraction-total-v1": "9c2b53e1fb7b388ad611a4767f497d352f9cbce2ca488bbc5dce71cf9c976e1d",
        "synthetic:p03-us08:hostile-label-matrix-v1": "54800c392c8d27b91c725f44855db30b73a8738da77228dc30533bced1189a55",
        "synthetic:p03-us08:hostile-markup-label-v1": "7ea5ed876c4a13805ba3d647a963efbe762c1f925593551a3d343f1a94b8d5b0",
        "synthetic:p03-us08:identity-fallbacks-v1": "f5c463808b714bd1a42fab7cec64dc72f33cf2790b0847035d81eb649cceecde",
        "synthetic:p03-us08:inconsistent-band-v1": "a284cd4c82de6c3f996c072f414c3c84f5aa85a32f80f79aba9dfa86e2dcdcc9",
        "synthetic:p03-us08:malformed-contracts-v1": "da0ccd06c096339d08ba8252c4de21ffb7f2b1f009e78225d3a5086b27c34ed1",
        "synthetic:p03-us08:multiple-visible-v1": "221a6c54d576017fd5864822c1971c63158fae4ac89e07acaea23c6dd1c186e6",
        "synthetic:p03-us08:non-target-tokens-v1": "d07c248cd3c71cf84d9e2d0b75df08813c253e9531332eee61a349e0eac80825",
        "synthetic:p03-us08:outer-whitespace-label-v1": "dc82560414dabcaf18e72a824c611efc9bd86488074aa19af4fd0fae6e10b05f",
        "synthetic:p03-us08:oversize-label-v1": "a421d4d54286c5850c59da20d2858a0c736a368f58f99e5ccc6811c3c769a640",
        "synthetic:p03-us08:ownership-custody-v1": "e72a411b30cafffa250a5361dffb2d01c0652d38f08c5b370c2d33d427b71a2a",
        "synthetic:p03-us08:page-of-total-v1": "a148c9352e851ae7885586d05f10fa4a23e6790d7b28ec4e0844bfb6b5d944a1",
        "synthetic:p03-us08:page-pipe-v1": "5c9ccf3b4c091d1b936fa191fc70126f1b151ed32bc95ab19b85749736decfbf",
        "synthetic:p03-us08:repeated-body-v1": "1c57e2f604912cf923edd2f2fe221fd35111e626920e928926b7329858c78c88",
        "synthetic:p03-us08:repeated-running-v1": "1a0ffb47778e13449904dedf8755e7794281f8b7d4a658472d5ddc6fa5d8930a",
        "synthetic:p03-us08:resource-boundaries-v1": "c5f9922118c1a9dd6f8efbb851fa5fa4a493c6bfa9da02edc6585e8b2eb13917",
        "synthetic:p03-us08:single-heading-v1": "36e9f350e6d8e88d4d5a4c726a6619b231a86975a73648c9bee6d96c925fac08",
        "synthetic:p03-us08:single-navigation-v1": "dbeacc5bf873deec80850fa892f6db519b77faaf742ceeb93fb8c9744261efd3",
        "synthetic:p03-us08:state-machines-v1": "8adc4ea88dfe3ad710187ad916cce5a7eab474fe2cf2bbeb6666836e2d2a8849",
        "synthetic:p03-us08:strip-replay-adversarial-v1": "b2d5e80428bdbb8b962f1ccec232ad666f7add5eae27ae0a543a30514d0eff30",
        "synthetic:p03-us08:trusted-top-bare-v1": "f20d5e60eb37eff8e2290078d1a27ca9d6fa2a2ab56dc2f3289e57d48b6b2edf",
        "synthetic:p03-us08:unsupported-punctuation-label-v1": "62d3da33e448a1bb05f5fd0993aa7fef7e7c65801ca7d2b6668d0b327c20ffcb",
        "synthetic:p03-us08:varying-placeholder-v1": "279a6e0283223552b019d54113b88fff075312db66d8603411664449088d801d",
    }
)
FROZEN_REGISTRY_SHA256 = "55a086b4d8d56ea538435c96165fe5571964514ddaec2a4e6986ae89c248133c"


def _expect_contract_rejection(callback: Callable[[], Any], label: str) -> None:
    try:
        callback()
    except _contract.ReadinessContractError:
        return
    raise SyntheticFixtureIntegrityError(f"{label} was not rejected")


def verify_pdf_readers() -> dict[str, str]:
    """Require pdfplumber and pypdfium2 to open/render every registered PDF."""

    import pdfplumber
    import pypdfium2 as pdfium

    verified: dict[str, str] = {}
    for definition in SYNTHETIC_FIXTURES:
        if definition.kind != "pdf":
            continue
        payload = build_synthetic_fixture(definition.fixture_id)["payload"]
        if not isinstance(payload, bytes):
            raise SyntheticFixtureIntegrityError("PDF fixture is not bytes")
        try:
            with pdfplumber.open(io.BytesIO(payload)) as document:
                if len(document.pages) != definition.page_count:
                    raise SyntheticFixtureIntegrityError(
                        f"{definition.fixture_id} pdfplumber page count drifted"
                    )
                for page in document.pages:
                    _ = page.extract_words()
        except SyntheticFixtureIntegrityError:
            raise
        except Exception as exc:  # pragma: no cover - dependency diagnostics vary
            raise SyntheticFixtureIntegrityError(
                f"pdfplumber could not read {definition.fixture_id}: {type(exc).__name__}"
            ) from exc
        try:
            document = pdfium.PdfDocument(payload)
            try:
                if len(document) != definition.page_count:
                    raise SyntheticFixtureIntegrityError(
                        f"{definition.fixture_id} pdfium page count drifted"
                    )
                labels: list[str] = []
                for page_index in range(len(document)):
                    labels.append(document.get_page_label(page_index) or "")
                    page = document[page_index]
                    try:
                        bitmap = page.render(scale=0.20)
                        bitmap.close()
                    finally:
                        page.close()
                if definition.expected_page_labels is not None and tuple(labels) != (
                    definition.expected_page_labels
                ):
                    raise SyntheticFixtureIntegrityError(
                        f"{definition.fixture_id} PDF page labels drifted: {labels!r}"
                    )
            finally:
                document.close()
        except SyntheticFixtureIntegrityError:
            raise
        except Exception as exc:  # pragma: no cover - dependency diagnostics vary
            raise SyntheticFixtureIntegrityError(
                f"pypdfium2 could not read {definition.fixture_id}: {type(exc).__name__}"
            ) from exc
        verified[definition.fixture_id] = hashlib.sha256(payload).hexdigest()
    return verified


def _execute_contract_specs() -> None:
    """Bind every non-PDF registry claim to a real validator or refusal."""

    def fallback_identity(
        *, page_label: str, source: str, display: str, concerns: list[str]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        physical = source == "physical"
        identity = {
            "schema_version": "1.0",
            "policy_id": POLICY_ID,
            "page_id": "page-1",
            "physical_page_index": 1,
            "embedded_label": None,
            "detected_printed_label": None,
            "visible_text": None,
            "display_label": display,
            "display_source": source,
            "evidence_bbox": None,
            "evidence_source": {
                "method": "physical_page_index" if physical else "legacy_display_fallback",
                "reader": "configured_predecessor",
                "page_index": 1,
                "public_item_id": None,
                "public_path": [],
                "element_id": None,
                "bbox_id": None,
                "evidence_ids": [],
                "source_object_ids": [] if physical else ["predecessor-page-1"],
            },
            "confidence": {
                "scope": "unavailable",
                "score": None,
                "unavailable_reason": (
                    "page_identity_display_fallback_physical"
                    if physical
                    else "page_identity_source_unavailable"
                ),
            },
            "concern_codes": concerns,
        }
        page = {"page_index": 1, "page_number": 1, "page_label": page_label}
        return identity, page

    safe_legacy, safe_page = fallback_identity(
        page_label="A-3", source="legacy_display_fallback", display="A-3", concerns=[]
    )
    empty_physical, empty_page = fallback_identity(
        page_label="", source="physical", display="1", concerns=[]
    )
    hostile_physical, hostile_page = fallback_identity(
        page_label="<script>",
        source="physical",
        display="1",
        concerns=["page_identity_display_unsafe"],
    )
    for identity, page in (
        (safe_legacy, safe_page),
        (empty_physical, empty_page),
        (hostile_physical, hostile_page),
    ):
        _contract.validate_page_identity(identity, public_page=page)
    detached_detected = {
        "schema_version": "1.0",
        "policy_id": POLICY_ID,
        "page_id": "page-1",
        "physical_page_index": 1,
        "embedded_label": None,
        "detected_printed_label": "7",
        "visible_text": "PAGE | 7",
        "display_label": "7",
        "display_source": "detected_printed_label",
        "evidence_bbox": {
            "x": 80.0,
            "y": 762.0,
            "width": 8.0,
            "height": 6.0,
            "unit": "pt",
        },
        "evidence_source": {
            "method": "native_printed_label",
            "reader": "pdfplumber",
            "page_index": 1,
            "public_item_id": None,
            "public_path": [],
            "element_id": None,
            "bbox_id": None,
            "evidence_ids": ["source-label-candidate-1"],
            "source_object_ids": ["word-1", "word-2", "word-3"],
        },
        "confidence": {
            "scope": "deterministic_rule",
            "score": 1.0,
            "unavailable_reason": None,
        },
        "concern_codes": [],
    }
    _contract.validate_page_identity(detached_detected, public_page=empty_page)
    detached_without_candidate = deepcopy(detached_detected)
    detached_without_candidate["evidence_source"]["evidence_ids"] = []
    _expect_contract_rejection(
        lambda: _contract.validate_page_identity(
            detached_without_candidate, public_page=empty_page
        ),
        "native-only detected evidence without retained source candidate",
    )
    attached_without_evidence = deepcopy(detached_detected)
    attached_without_evidence["evidence_source"].update(
        {
            "public_item_id": "item-1",
            "public_path": ["pages", 0, "items", 0],
            "element_id": "element-1",
            "bbox_id": "bbox-1",
        }
    )
    attached_without_evidence["evidence_source"]["evidence_ids"] = []
    _expect_contract_rejection(
        lambda: _contract.validate_page_identity(
            attached_without_evidence, public_page=empty_page
        ),
        "public-bound detected evidence without retained candidate",
    )
    partially_bound_detected = deepcopy(detached_detected)
    partially_bound_detected["evidence_source"]["public_item_id"] = "item-1"
    _expect_contract_rejection(
        lambda: _contract.validate_page_identity(
            partially_bound_detected, public_page=empty_page
        ),
        "partially bound detected evidence",
    )
    invalid_physical = deepcopy(empty_physical)
    invalid_physical["physical_page_index"] = 0
    _expect_contract_rejection(
        lambda: _contract.validate_page_identity(invalid_physical, public_page=empty_page),
        "invalid physical page index",
    )

    # Closed schema/version/policy refusals.
    unknown = deepcopy(safe_legacy)
    unknown["unknown"] = True
    wrong_version = {**safe_legacy, "schema_version": "2.0"}
    wrong_policy = {**safe_legacy, "policy_id": "p03-running-regions-page-identity-v0"}
    for label, value in (
        ("unknown identity key", unknown),
        ("wrong identity version", wrong_version),
        ("wrong identity policy", wrong_policy),
    ):
        _expect_contract_rejection(
            lambda value=value: _contract.validate_page_identity(value, public_page=safe_page),
            label,
        )

    # Exact effective-bottom positive and each independent negative.
    cluster_spec = _effective_cluster_spec()
    positive = deepcopy(cluster_spec["positive"])
    body = deepcopy(cluster_spec["remaining_body_bboxes"])
    cluster_top = _contract.validate_effective_bottom_cluster(
        positive,
        remaining_body_bboxes=body,
        page_width=612.0,
        page_height=792.0,
        candidate_cut_count=1,
    )
    if cluster_top != 650.0 or cluster_top >= 792.0 * 0.85:
        raise SyntheticFixtureIntegrityError("effective-bottom positive drifted")
    if "effective_boundary_cluster" not in _contract.SOURCE_METHODS:
        raise SyntheticFixtureIntegrityError("effective-boundary source method is absent")
    cluster_negatives: dict[str, tuple[Any, Any, int]] = {}
    missing_cue = deepcopy(positive)
    missing_cue[0]["navigation_cue"] = None
    cluster_negatives["missing cue"] = (missing_cue, body, 1)
    missing_label = deepcopy(positive)
    missing_label[2]["normalized_label"] = None
    cluster_negatives["missing label"] = (missing_label, body, 1)
    cluster_negatives["two items"] = (deepcopy(positive[:2]), body, 1)
    overlapping_body = deepcopy(body)
    overlapping_body[0]["height"] = 560.0
    cluster_negatives["overlapping body"] = (deepcopy(positive), overlapping_body, 1)
    claimed = deepcopy(positive)
    claimed[1]["claimed"] = True
    cluster_negatives["claimed owner"] = (claimed, body, 1)
    noncontiguous = deepcopy(positive)
    noncontiguous[1]["presentation_index"] = 14
    cluster_negatives["noncontiguous order"] = (noncontiguous, body, 1)
    outside = deepcopy(positive)
    outside[1]["bbox"]["y"] = 500.0
    cluster_negatives["outer thirty percent"] = (outside, body, 1)
    cluster_negatives["ambiguous cut"] = (deepcopy(positive), body, 2)
    for label, (items, body_boxes, cut_count) in cluster_negatives.items():
        _expect_contract_rejection(
            lambda items=items, body_boxes=body_boxes, cut_count=cut_count: (
                _contract.validate_effective_bottom_cluster(
                    items,
                    remaining_body_bboxes=body_boxes,
                    page_width=612.0,
                    page_height=792.0,
                    candidate_cut_count=cut_count,
                )
            ),
            f"effective-bottom {label}",
        )

    # Exact extracted source/presentation whitespace mapping and admission matrix.
    extracted = _extracted_contribution_spec()
    owner_hash = "b" * 64
    eligibility = {
        "contribution_text": extracted["source_text"],
        "native_source": True,
        "evidence_mode": "exact_repetition",
        "repetition_page_indexes": (1, 2),
        "complete_delimiter_line": True,
        "scalar_match_count": 1,
        "intervals_disjoint": True,
        "owner_kind": "visual",
        "owner_sha256_before": owner_hash,
        "owner_sha256_after": owner_hash,
    }
    _contract.validate_extracted_candidate_eligibility(**eligibility)
    trusted_role_eligibility = {
        **eligibility,
        "evidence_mode": "trusted_layout_role",
        "repetition_page_indexes": (),
    }
    _contract.validate_extracted_candidate_eligibility(**trusted_role_eligibility)
    _contract.validate_source_owner_admission(
        owner_kind="text",
        raw_layout_role="page_header",
        source_method="trusted_layout_role",
        prior_semantic_owner=False,
    )
    for owner_kind in (
        "table_value",
        "chart",
        "form_value",
        "outline_item",
        "note_value",
        "label_value",
    ):
        _expect_contract_rejection(
            lambda owner_kind=owner_kind: _contract.validate_source_owner_admission(
                owner_kind=owner_kind,
                raw_layout_role=None,
                source_method="printed_label_boundary",
                prior_semantic_owner=False,
            ),
            f"semantic label owner {owner_kind}",
        )
    _expect_contract_rejection(
        lambda: _contract.validate_source_owner_admission(
            owner_kind="text",
            raw_layout_role="page_header",
            source_method="trusted_layout_role",
            prior_semantic_owner=True,
        ),
        "prior semantic owner",
    )
    _expect_contract_rejection(
        lambda: _contract.validate_source_owner_admission(
            owner_kind="text",
            raw_layout_role=None,
            source_method="trusted_layout_role",
            prior_semantic_owner=False,
        ),
        "trusted layout role absent",
    )
    eligibility_negatives = {
        "non native": {"native_source": False},
        "non repeated": {"repetition_page_indexes": (1,)},
        "unknown evidence mode": {"evidence_mode": "heuristic"},
        "trusted role with repetition": {
            "evidence_mode": "trusted_layout_role",
            "repetition_page_indexes": (1, 2),
        },
        "non line": {"complete_delimiter_line": False},
        "multiple scalar matches": {"scalar_match_count": 2},
        "boolean scalar match count": {"scalar_match_count": True},
        "overlapping intervals": {"intervals_disjoint": False},
        "table owner": {"owner_kind": "table"},
        "form owner": {"owner_kind": "form_value"},
        "outline owner": {"owner_kind": "outline_item"},
        "label owner": {"owner_kind": "label"},
        "label value owner": {"owner_kind": "label_value"},
        "over limit": {
            "contribution_text": "x" * (
                int(SYNTHETIC_THRESHOLDS["extracted_contribution_utf8_bytes"]) + 1
            )
        },
        "changed owner": {"owner_sha256_after": "c" * 64},
    }
    for label, mutation in eligibility_negatives.items():
        arguments = {**eligibility, **mutation}
        _expect_contract_rejection(
            lambda arguments=arguments: _contract.validate_extracted_candidate_eligibility(
                **arguments
            ),
            f"extracted {label}",
        )
    predecessor = extracted["predecessor_canonical"]
    residual = extracted["residual_canonical"]
    plan = _contract.build_extracted_contribution_plan(
        physical_page_index=1,
        owner_public_item_id="owner-1",
        owner_sha256=owner_hash,
        predecessor_canonical=predecessor,
        source_text=extracted["source_text"],
        presentation_fragments=extracted["presentation_fragments"],
        delimiters=extracted["delimiters"],
        predecessor_intervals=extracted["predecessor_intervals"],
        source_span_groups=extracted["source_span_groups"],
    )
    if plan.execute() != residual:
        raise SyntheticFixtureIntegrityError("extracted canonical residual drifted")
    if (
        plan.presentation_text != extracted["presentation_text"]
        or len(plan.presentation_text.encode("utf-8")) != 29
        or plan.presentation_text.endswith("\n")
    ):
        raise SyntheticFixtureIntegrityError(
            "extracted canonical presentation delimiter drifted"
        )
    single_interval_plan = _contract.build_extracted_contribution_plan(
        physical_page_index=1,
        owner_public_item_id="single-owner",
        owner_sha256=owner_hash,
        predecessor_canonical="HEADER\nBody.\n",
        source_text="HEADER",
        presentation_fragments=("HEADER",),
        delimiters=("\n",),
        predecessor_intervals=((0, len(b"HEADER\n")),),
        source_span_groups=(((0, len(b"HEADER")),),),
    )
    if single_interval_plan.presentation_text != "HEADER":
        raise SyntheticFixtureIntegrityError(
            "single-interval presentation retained its terminal delimiter"
        )
    for label, source_text in (
        ("leading", " HEADER"),
        ("trailing", "HEADER "),
        ("both", " HEADER "),
    ):
        _expect_contract_rejection(
            lambda source_text=source_text, label=label: (
                _contract.build_extracted_contribution_plan(
                    physical_page_index=1,
                    owner_public_item_id=f"outer-whitespace-{label}",
                    owner_sha256=owner_hash,
                    predecessor_canonical="HEADER\nBody.\n",
                    source_text=source_text,
                    presentation_fragments=("HEADER",),
                    delimiters=("\n",),
                    predecessor_intervals=((0, len(b"HEADER\n")),),
                    source_span_groups=(
                        ((0, len(source_text.encode("utf-8"))),),
                    ),
                )
            ),
            f"extracted {label} outer whitespace",
        )
    unicode_source_text = "NIST\u00a0AMS\u2003HEADER"
    unicode_presentation_fragment = "NIST\u2002AMS HEADER"
    unicode_predecessor = f"{unicode_presentation_fragment}\nBody\n"
    unicode_plan = _contract.build_extracted_contribution_plan(
        physical_page_index=1,
        owner_public_item_id="unicode-owner",
        owner_sha256=owner_hash,
        predecessor_canonical=unicode_predecessor,
        source_text=unicode_source_text,
        presentation_fragments=(unicode_presentation_fragment,),
        delimiters=("\n",),
        predecessor_intervals=(
            (0, len(f"{unicode_presentation_fragment}\n".encode())),
        ),
        source_span_groups=(((0, len(unicode_source_text.encode("utf-8"))),),),
    )
    if unicode_plan.execute() != "Body\n":
        raise SyntheticFixtureIntegrityError(
            "Unicode-whitespace contribution witness drifted"
        )
    nfd_body = "Cafe\u0301 body.\n"
    nfd_body_plan = _contract.build_extracted_contribution_plan(
        physical_page_index=1,
        owner_public_item_id="nfd-body-owner",
        owner_sha256=owner_hash,
        predecessor_canonical="HEADER\n" + nfd_body,
        source_text="HEADER",
        presentation_fragments=("HEADER",),
        delimiters=("\n",),
        predecessor_intervals=((0, len(b"HEADER\n")),),
        source_span_groups=(((0, len(b"HEADER")),),),
    )
    if nfd_body_plan.execute() != nfd_body:
        raise SyntheticFixtureIntegrityError(
            "unrelated NFD predecessor/residual text was not preserved"
        )
    _expect_contract_rejection(
        lambda: _contract.build_extracted_contribution_plan(
            physical_page_index=1,
            owner_public_item_id="nfd-source-owner",
            owner_sha256=owner_hash,
            predecessor_canonical="Cafe\u0301\nBody\n",
            source_text="Cafe\u0301",
            presentation_fragments=("Cafe\u0301",),
            delimiters=("\n",),
            predecessor_intervals=((0, len("Cafe\u0301\n".encode("utf-8"))),),
            source_span_groups=(((0, len("Cafe\u0301".encode("utf-8"))),),),
        ),
        "extracted non-NFC source/presentation text",
    )
    _expect_contract_rejection(
        lambda: _contract.build_extracted_contribution_plan(
            physical_page_index=1,
            owner_public_item_id="shifted-whitespace-owner",
            owner_sha256=owner_hash,
            predecessor_canonical="AB C D\nBody\n",
            source_text="A B CD",
            presentation_fragments=("AB C D",),
            delimiters=("\n",),
            predecessor_intervals=((0, len(b"AB C D\n")),),
            source_span_groups=(((0, len(b"A B CD")),),),
        ),
        "extracted shifted whitespace boundary",
    )
    _expect_contract_rejection(
        replace(unicode_plan, source_span_groups=(((4, 5),),)).execute,
        "extracted UTF-8-misaligned source span",
    )
    _expect_contract_rejection(
        lambda: _contract.build_extracted_contribution_plan(
            physical_page_index=1,
            owner_public_item_id="touching-owner",
            owner_sha256=owner_hash,
            predecessor_canonical="ALPHA\nBETA\nBody\n",
            source_text="ALPHA BETA",
            presentation_fragments=("ALPHA", "BETA"),
            delimiters=("\n", "\n"),
            predecessor_intervals=((0, len(b"ALPHA\n")), (len(b"ALPHA\n"), len(b"ALPHA\nBETA\n"))),
            source_span_groups=(((0, 5),), ((6, 10),)),
        ),
        "touching predecessor extraction intervals",
    )
    eight_page_plans = tuple(
        replace(plan, owner_public_item_id=f"owner-{index}")
        for index in range(1, _contract.MAX_EXTRACTED_CONTRIBUTIONS_PER_PAGE + 1)
    )
    _contract.validate_extracted_plan_ledger(eight_page_plans)
    _expect_contract_rejection(
        lambda: _contract.validate_extracted_plan_ledger((plan, plan)),
        "duplicate extracted contribution plan",
    )
    overlapping_second_contribution = _contract.build_extracted_contribution_plan(
        physical_page_index=plan.physical_page_index,
        owner_public_item_id=plan.owner_public_item_id,
        owner_sha256=plan.owner_sha256_before,
        predecessor_canonical=plan.predecessor_canonical,
        source_text=plan.presentation_fragments[0],
        presentation_fragments=(plan.presentation_fragments[0],),
        delimiters=(plan.delimiters[0],),
        predecessor_intervals=(plan.predecessor_intervals[0],),
        source_span_groups=(
            ((0, len(plan.presentation_fragments[0].encode("utf-8"))),),
        ),
    )
    _expect_contract_rejection(
        lambda: _contract.validate_extracted_plan_ledger(
            (plan, overlapping_second_contribution)
        ),
        "overlapping extracted plans for one owner",
    )
    ninth_page_plan = replace(plan, owner_public_item_id="owner-9")
    _expect_contract_rejection(
        lambda: _contract.validate_extracted_plan_ledger(
            (*eight_page_plans, ninth_page_plan)
        ),
        "extracted ninth page contribution",
    )
    _expect_contract_rejection(
        lambda: _contract.validate_extracted_plan_ledger(
            tuple(
                replace(
                    plan,
                    physical_page_index=(index // 8) + 1,
                    owner_public_item_id=f"document-owner-{index + 1}",
                )
                for index in range(
                    _contract.MAX_EXTRACTED_CONTRIBUTIONS_PER_DOCUMENT + 1
                )
            )
        ),
        "extracted sixty-fifth document contribution",
    )
    _expect_contract_rejection(
        lambda: _contract.build_extracted_contribution_plan(
            physical_page_index=1,
            owner_public_item_id="owner-1",
            owner_sha256=owner_hash,
            predecessor_canonical=predecessor,
            source_text="NIST AMS 100-XX February 2026",
            presentation_fragments=extracted["presentation_fragments"],
            delimiters=extracted["delimiters"],
            predecessor_intervals=extracted["predecessor_intervals"],
            source_span_groups=extracted["source_span_groups"],
        ),
        "extracted non-whitespace drift",
    )
    residual_drift_plan = replace(
        plan,
        residual_canonical="CHART CONTENT\nManufacturing  body.\n",
        residual_sha256=hashlib.sha256(
            b"CHART CONTENT\nManufacturing  body.\n"
        ).hexdigest(),
    )
    _expect_contract_rejection(residual_drift_plan.execute, "extracted residual drift")
    overlap_plan = replace(
        plan,
        predecessor_intervals=(
            plan.predecessor_intervals[0],
            (
                plan.predecessor_intervals[0][1] - 1,
                plan.predecessor_intervals[1][1],
            ),
        ),
    )
    _expect_contract_rejection(overlap_plan.execute, "extracted predecessor overlap")

    def actual_interval_plan(interval_count: int) -> _contract.ExtractedContributionPlan:
        fragments = tuple(
            f"RUNNING-{index:02d}" for index in range(1, interval_count + 1)
        )
        source_text = " ".join(fragments)
        predecessor_parts: list[str] = []
        predecessor_intervals: list[tuple[int, int]] = []
        predecessor_cursor = 0
        for index, fragment in enumerate(fragments, start=1):
            retained = f"body-{index}\n"
            predecessor_parts.append(retained)
            predecessor_cursor += len(retained.encode("utf-8"))
            removed = f"{fragment}\n"
            start = predecessor_cursor
            predecessor_cursor += len(removed.encode("utf-8"))
            predecessor_intervals.append((start, predecessor_cursor))
            predecessor_parts.append(removed)
        predecessor_parts.append("retained-tail\n")
        source_span_groups: list[tuple[tuple[int, int], ...]] = []
        source_cursor = 0
        for fragment in fragments:
            end = source_cursor + len(fragment.encode("utf-8"))
            source_span_groups.append(((source_cursor, end),))
            source_cursor = end + 1
        return _contract.build_extracted_contribution_plan(
            physical_page_index=1,
            owner_public_item_id=f"interval-owner-{interval_count}",
            owner_sha256=owner_hash,
            predecessor_canonical="".join(predecessor_parts),
            source_text=source_text,
            presentation_fragments=fragments,
            delimiters=("\n",) * interval_count,
            predecessor_intervals=tuple(predecessor_intervals),
            source_span_groups=tuple(source_span_groups),
        )

    eight_interval_plan = actual_interval_plan(
        _contract.MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION
    )
    if (
        len(eight_interval_plan.predecessor_intervals)
        != _contract.MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION
        or not eight_interval_plan.execute()
    ):
        raise SyntheticFixtureIntegrityError(
            "actual eight-interval contribution witness drifted"
        )
    _expect_contract_rejection(
        lambda: actual_interval_plan(
            _contract.MAX_EXTRACTED_INTERVALS_PER_CONTRIBUTION + 1
        ),
        "actual extracted ninth interval",
    )
    reversed_source_plan = replace(
        plan, source_span_groups=tuple(reversed(plan.source_span_groups))
    )
    _expect_contract_rejection(reversed_source_plan.execute, "extracted non-source order")
    trailing_presentation = plan.presentation_text + plan.delimiters[-1]
    trailing_presentation_plan = replace(
        plan,
        presentation_text=trailing_presentation,
        presentation_text_sha256=hashlib.sha256(
            trailing_presentation.encode("utf-8")
        ).hexdigest(),
    )
    _expect_contract_rejection(
        trailing_presentation_plan.execute,
        "extracted terminal presentation delimiter",
    )

    # Complete projected public/IR/canonical binding plus strip/refusal cases.
    public, ir = _build_ir_binding_witness()
    _contract.validate_ir_bindings(ir, public_document=public)
    duplicate_ir_page_before = deepcopy(ir)
    duplicate_before = deepcopy(ir["pages"][0])
    duplicate_before["id"] = "page-duplicate-before"
    duplicate_ir_page_before["pages"].insert(0, duplicate_before)
    duplicate_ir_page_after = deepcopy(ir)
    duplicate_after = deepcopy(ir["pages"][0])
    duplicate_after["id"] = "page-duplicate-after"
    duplicate_ir_page_after["pages"].append(duplicate_after)
    for label, duplicate_ir in (
        ("duplicate physical IR page before valid page", duplicate_ir_page_before),
        ("duplicate physical IR page after valid page", duplicate_ir_page_after),
    ):
        _expect_contract_rejection(
            lambda duplicate_ir=duplicate_ir: _contract.validate_ir_bindings(
                duplicate_ir,
                public_document=public,
            ),
            label,
        )
    extracted_public, extracted_ir = _build_ir_binding_witness()
    extracted_child_items = [
        {
            "id": "nested-header-child-1",
            "type": "visual_text",
            "reading_order": 0,
            "value": extracted["presentation_fragments"][0],
            "md": extracted["presentation_fragments"][0],
            "bbox": {
                "x": 72.0,
                "y": 760.1,
                "width": 120.0,
                "height": 6.0,
                "unit": "pt",
            },
            "source": "native",
            "confidence": None,
            "presentation_role": "subordinate",
            "contained_by": "owner-1",
            "relationship_id": "nested-header-relationship-1",
            "relationship_type": "contains",
            "relationship_basis": "graph_and_geometry",
        },
        {
            "id": "nested-header-child-2",
            "type": "visual_text",
            "reading_order": 0,
            "value": extracted["presentation_fragments"][1],
            "md": extracted["presentation_fragments"][1],
            "bbox": {
                "x": 72.0,
                "y": 766.1,
                "width": 120.0,
                "height": 7.8,
                "unit": "pt",
            },
            "source": "native",
            "confidence": None,
            "presentation_role": "subordinate",
            "contained_by": "owner-1",
            "relationship_id": "nested-header-relationship-2",
            "relationship_type": "contains",
            "relationship_basis": "graph_and_geometry",
        },
    ]
    extracted_relationships = [
        {
            "id": f"nested-header-relationship-{index}",
            "source_id": "owner-1",
            "target_id": child["id"],
            "type": "contains",
        }
        for index, child in enumerate(extracted_child_items, start=1)
    ]
    extracted_owner = {
        "id": "owner-1",
        "type": "visual",
        "reading_order": 0,
        "value": predecessor,
        "md": predecessor,
        "bbox": {
            "x": 72.4,
            "y": 600.0,
            "width": 467.6,
            "height": 180.0,
            "unit": "pt",
        },
        "contained_items": extracted_child_items,
        "relationships": extracted_relationships,
        "raw_layout_role": "page_footer",
        "source": "native",
        "confidence": 1.0,
    }
    extracted_owner_hash = _contract.sha256_json(extracted_owner)
    synthetic_item = extracted_public["pages"][0]["items"][0]
    extracted_descriptor = deepcopy(synthetic_item["running_region"])
    extracted_source_object_ids = [
        *(
            f"pdfplumber:{extracted_public['document']['sha256']}:"
            f"page:1:character:{index}"
            for index in range(len(extracted["source_text"]))
        ),
        *(
            f"pdfplumber:{extracted_public['document']['sha256']}:page:1:word:{index}"
            for index in range(len(extracted["source_text"].split()))
        ),
    ]
    extracted_evidence_id = _contract.extracted_evidence_record_id(
        source_sha256=extracted_public["document"]["sha256"],
        physical_page_index=1,
        source_public_item_id="owner-1",
        source_object_ids=extracted_source_object_ids,
        bbox_id=extracted_descriptor["bbox_id"],
        role=extracted_descriptor["role"],
    )
    extracted_descriptor.update(
        {
            "source_public_item_id": "owner-1",
            "source_public_path": ["pages", 0, "items", 0],
            "predecessor_type": "visual",
            "predecessor_item_sha256": extracted_owner_hash,
            "evidence_ids": [extracted_evidence_id],
            "source_object_ids": extracted_source_object_ids,
            "source_method": "extracted_source_contribution",
        }
    )
    extracted_id_parts = (
        POLICY_ID,
        extracted_public["document"]["sha256"],
        1,
        extracted_descriptor["source_public_item_id"],
        tuple(extracted_descriptor["source_object_ids"]),
        tuple(extracted_descriptor["evidence_ids"]),
        extracted_descriptor["bbox_id"],
        extracted_descriptor["role"],
    )
    extracted_descriptor["id"] = _contract.stable_id(
        "running-region", *extracted_id_parts
    )
    synthetic_item.update(
        {
            "id": _contract.stable_id("running-region-item", *extracted_id_parts),
            "reading_order": 1,
            "value": extracted["source_text"],
            "md": extracted["source_text"],
            "running_region": extracted_descriptor,
        }
    )
    extracted_public["pages"][0]["items"] = [extracted_owner, synthetic_item]
    extracted_block = extracted_public["canonical_presentation"]["pages"][0][
        "blocks"
    ][0]
    extracted_block["markdown"] = extracted["presentation_text"]
    extracted_block["text"] = extracted["presentation_text"]
    owner_block = {
        "id": "owner-block-1",
        "page_id": "page-1",
        "primary_element_id": "owner-element-1",
        "primary_element_type": "visual",
        "scope": "body",
        "markdown": residual,
        "text": residual,
        "contributing_element_ids": ["owner-element-1"],
        "relationship_ids": [],
        "excluded_contributions": [],
        "omission_reason": None,
        "suppressed_by_element_id": None,
    }
    extracted_canonical_page = extracted_public["canonical_presentation"]["pages"][0]
    extracted_canonical_page["blocks"] = [owner_block, extracted_block]
    extracted_canonical_page["body"]["block_ids"] = ["owner-block-1"]
    extracted_canonical_page["full"]["block_ids"] = ["owner-block-1", "block-1"]
    extracted_canonical_page["footer"]["block_ids"] = ["block-1"]
    extracted_canonical_page["body"]["markdown"] = residual
    extracted_canonical_page["body"]["text"] = residual
    extracted_canonical_page["full"]["markdown"] = (
        f"{residual.strip()}\n\n{extracted['presentation_text']}\n"
    )
    extracted_canonical_page["full"]["text"] = (
        f"{residual.strip()}\n\n{extracted['presentation_text']}\n"
    )
    extracted_canonical_page["footer"]["markdown"] = (
        f"{extracted['presentation_text']}\n"
    )
    extracted_canonical_page["footer"]["text"] = (
        f"{extracted['presentation_text']}\n"
    )
    extracted_ir["pages"][0]["element_ids"] = [
        "owner-element-1",
        *(child["id"] for child in extracted_child_items),
        "element-1",
    ]
    extracted_ir["pages"][0]["presentation_element_ids"] = [
        "owner-element-1",
        "element-1",
    ]
    extracted_ir["elements"][0]["running_region"] = deepcopy(extracted_descriptor)
    extracted_ir["elements"][0]["value"] = extracted["source_text"]
    extracted_ir["elements"][0]["evidence_ids"] = [extracted_evidence_id]
    extracted_ir["elements"].insert(
        0,
        {
            "id": "owner-element-1",
            "page_id": "page-1",
            "type": "visual",
            "bbox_ids": ["owner-bbox-1", "owner-native-bbox-1"],
            "evidence_ids": ["owner-evidence-1", "owner-native-evidence-1"],
            "presentation_role": "primary",
            "raw_layout_role": "page_footer",
            "properties": {
                "legacy_item": deepcopy(extracted_owner),
                "source_position": 0,
            },
        },
    )
    extracted_ir["bboxes"].append(
        {
            "id": "owner-bbox-1",
            "coordinate_system_id": "coord-1",
            "x": 72.4,
            "y": 600.0,
            "width": 467.6,
            "height": 180.0,
        }
    )
    extracted_ir["evidence"].insert(
        0,
        {
            "id": "owner-evidence-1",
            "element_id": "owner-element-1",
            "bbox_id": "owner-bbox-1",
        },
    )
    extracted_ir["evidence"][1] = {
        "id": extracted_evidence_id,
        "element_id": "element-1",
        "method": "native",
        "bbox_id": "bbox-1",
        "value": extracted["source_text"],
        "confidence": dict(_contract.EXTRACTED_EVIDENCE_CONFIDENCE),
        "metadata": {
            "policy_id": POLICY_ID,
            "source_object_ids": list(extracted_descriptor["source_object_ids"]),
        },
    }
    extracted_ir["bboxes"].append(
        {
            "id": "owner-native-bbox-1",
            "coordinate_system_id": "coord-1",
            **{
                key: extracted_descriptor["bbox"][key]
                for key in ("x", "y", "width", "height")
            },
        }
    )
    extracted_ir["evidence"].append(
        {
            "id": "owner-native-evidence-1",
            "element_id": "owner-element-1",
            "method": "native",
            "bbox_id": "owner-native-bbox-1",
            "value": extracted["source_text"],
            "metadata": {
                "source_object_ids": list(extracted_source_object_ids),
            },
        }
    )
    for index, child in enumerate(extracted_child_items, start=1):
        child_bbox_id = f"nested-header-bbox-{index}"
        child_evidence_id = f"nested-header-evidence-{index}"
        extracted_ir["elements"].append(
            {
                "id": child["id"],
                "page_id": "page-1",
                "type": child["type"],
                "reading_order": child["reading_order"],
                "value": child["value"],
                "markdown": child["md"],
                "source": "native",
                "bbox_ids": [child_bbox_id],
                "evidence_ids": [child_evidence_id],
                "presentation_role": "subordinate",
                "properties": {
                    "parent_element_id": "owner-element-1",
                    "legacy_item": deepcopy(child),
                },
            }
        )
        extracted_ir["bboxes"].append(
            {
                "id": child_bbox_id,
                "coordinate_system_id": "coord-1",
                **{
                    key: child["bbox"][key]
                    for key in ("x", "y", "width", "height")
                },
            }
        )
        extracted_ir["evidence"].append(
            {
                "id": child_evidence_id,
                "element_id": child["id"],
                "method": "native",
                "bbox_id": child_bbox_id,
                "value": child["value"],
            }
        )
    binding_plan = _contract.build_extracted_contribution_plan(
        physical_page_index=1,
        owner_public_item_id="owner-1",
        owner_sha256=extracted_owner_hash,
        predecessor_canonical=predecessor,
        source_text=extracted["source_text"],
        presentation_fragments=extracted["presentation_fragments"],
        delimiters=extracted["delimiters"],
        predecessor_intervals=extracted["predecessor_intervals"],
        source_span_groups=extracted["source_span_groups"],
    )
    validation_predecessor_owner_block = deepcopy(owner_block)
    validation_predecessor_owner_block["markdown"] = predecessor
    validation_predecessor_owner_block["text"] = predecessor
    validation_predecessor_canonical_page = deepcopy(extracted_canonical_page)
    validation_predecessor_canonical_page.pop("page_identity")
    validation_predecessor_canonical_page["blocks"] = [
        validation_predecessor_owner_block
    ]
    validation_predecessor_canonical_page["body"] = {
        "block_ids": ["owner-block-1"],
        "markdown": predecessor,
        "text": predecessor,
    }
    validation_predecessor_canonical_page["full"] = deepcopy(
        validation_predecessor_canonical_page["body"]
    )
    validation_predecessor_canonical_page["header"] = {
        "block_ids": [],
        "markdown": "",
        "text": "",
    }
    validation_predecessor_canonical_page["footer"] = deepcopy(
        validation_predecessor_canonical_page["header"]
    )
    _contract.validate_extracted_contribution(
        extracted_descriptor,
        synthetic_item=synthetic_item,
        fused_owner=extracted_owner,
        synthetic_block=extracted_block,
        residual_owner_block=owner_block,
        canonical_page=extracted_canonical_page,
        predecessor_owner_block=validation_predecessor_owner_block,
        predecessor_canonical_page=validation_predecessor_canonical_page,
        plan=binding_plan,
    )

    def validate_contribution_mutation(
        *,
        descriptor: Mapping[str, Any] = extracted_descriptor,
        item: Mapping[str, Any] = synthetic_item,
        owner: Mapping[str, Any] = extracted_owner,
        synthetic: Mapping[str, Any] = extracted_block,
        residual_block: Mapping[str, Any] = owner_block,
        current_page: Mapping[str, Any] = extracted_canonical_page,
        predecessor_block: Mapping[str, Any] = validation_predecessor_owner_block,
        predecessor_page: Mapping[str, Any] = validation_predecessor_canonical_page,
        contribution_plan: _contract.ExtractedContributionPlan = binding_plan,
    ) -> None:
        _contract.validate_extracted_contribution(
            descriptor,
            synthetic_item=item,
            fused_owner=owner,
            synthetic_block=synthetic,
            residual_owner_block=residual_block,
            canonical_page=current_page,
            predecessor_owner_block=predecessor_block,
            predecessor_canonical_page=predecessor_page,
            plan=contribution_plan,
        )

    relabeled_page_plan = replace(binding_plan, physical_page_index=2)
    synthetic_markdown_drift = {**deepcopy(synthetic_item), "md": "fabricated"}
    residual_markdown_drift = {**deepcopy(owner_block), "markdown": "fabricated"}
    for label, arguments in (
        ("relabeled extracted plan page", {"contribution_plan": relabeled_page_plan}),
        ("synthetic extracted markdown drift", {"item": synthetic_markdown_drift}),
        ("residual extracted markdown drift", {"residual_block": residual_markdown_drift}),
    ):
        _expect_contract_rejection(
            lambda arguments=arguments: validate_contribution_mutation(**arguments),
            label,
        )

    for label, view_name, member_ids in (
        ("missing residual owner membership", "body", []),
        (
            "duplicate residual owner membership",
            "body",
            ["owner-block-1", "owner-block-1"],
        ),
        ("wrong-scope residual owner membership", "header", ["owner-block-1"]),
    ):
        bad_page = deepcopy(extracted_canonical_page)
        bad_page[view_name]["block_ids"] = member_ids
        bad_residual = next(
            block for block in bad_page["blocks"] if block["id"] == "owner-block-1"
        )
        _expect_contract_rejection(
            lambda bad_page=bad_page, bad_residual=bad_residual: (
                validate_contribution_mutation(
                    residual_block=bad_residual,
                    current_page=bad_page,
                )
            ),
            label,
        )
    _contract.validate_ir_bindings(extracted_ir, public_document=extracted_public)
    synthetic_evidence_record = next(
        record
        for record in extracted_ir["evidence"]
        if record["id"] == extracted_evidence_id
    )
    for label, mutation in (
        ("method", {"method": "ocr"}),
        ("value", {"value": "wrong source text"}),
        (
            "source-object order",
            {
                "metadata": {
                    "policy_id": POLICY_ID,
                    "source_object_ids": list(
                        reversed(extracted_descriptor["source_object_ids"])
                    ),
                }
            },
        ),
        (
            "metadata key",
            {
                "metadata": {
                    "policy_id": POLICY_ID,
                    "source_object_ids": list(
                        extracted_descriptor["source_object_ids"]
                    ),
                    "raw_text": "forbidden",
                }
            },
        ),
    ):
        bad_record = {**deepcopy(synthetic_evidence_record), **mutation}
        _expect_contract_rejection(
            lambda value=bad_record: _contract.validate_extracted_evidence_record(
                value,
                descriptor=extracted_descriptor,
                source_text=extracted["source_text"],
                source_sha256=extracted_public["document"]["sha256"],
            ),
            f"extracted evidence wrong {label}",
        )
    wrong_evidence_id = "running-region-evidence-00000000000000000000"
    wrong_id_descriptor = deepcopy(extracted_descriptor)
    wrong_id_descriptor["evidence_ids"] = [wrong_evidence_id]
    wrong_id_record = {**deepcopy(synthetic_evidence_record), "id": wrong_evidence_id}
    _expect_contract_rejection(
        lambda: _contract.validate_extracted_evidence_record(
            wrong_id_record,
            descriptor=wrong_id_descriptor,
            source_text=extracted["source_text"],
            source_sha256=extracted_public["document"]["sha256"],
        ),
        "extracted evidence wrong deterministic ID",
    )
    wrong_extracted_evidence_owner = deepcopy(extracted_ir)
    next(
        record
        for record in wrong_extracted_evidence_owner["evidence"]
        if record["id"] == extracted_evidence_id
    )["element_id"] = "owner-element-1"
    _expect_contract_rejection(
        lambda: _contract.validate_ir_bindings(
            wrong_extracted_evidence_owner, public_document=extracted_public
        ),
        "extracted evidence owned by fused predecessor",
    )
    predecessor_public = deepcopy(extracted_public)
    predecessor_public_page = predecessor_public["pages"][0]
    predecessor_public_page.pop("page_identity")
    predecessor_public_page["items"] = [deepcopy(extracted_owner)]
    predecessor_canonical_page = predecessor_public["canonical_presentation"][
        "pages"
    ][0]
    predecessor_canonical_page.pop("page_identity")
    predecessor_owner_block = deepcopy(owner_block)
    predecessor_owner_block["markdown"] = predecessor
    predecessor_owner_block["text"] = predecessor
    predecessor_canonical_page["blocks"] = [predecessor_owner_block]
    predecessor_canonical_page["body"]["block_ids"] = ["owner-block-1"]
    predecessor_canonical_page["full"]["block_ids"] = ["owner-block-1"]
    predecessor_canonical_page["header"]["block_ids"] = []
    predecessor_canonical_page["footer"]["block_ids"] = []
    predecessor_canonical_page["body"]["markdown"] = predecessor
    predecessor_canonical_page["body"]["text"] = predecessor
    predecessor_canonical_page["full"]["markdown"] = predecessor
    predecessor_canonical_page["full"]["text"] = predecessor
    predecessor_canonical_page["header"]["markdown"] = ""
    predecessor_canonical_page["header"]["text"] = ""
    predecessor_canonical_page["footer"]["markdown"] = ""
    predecessor_canonical_page["footer"]["text"] = ""
    predecessor_public.pop("processing")
    predecessor_public.pop("running_region_concerns", None)

    predecessor_ir = deepcopy(extracted_ir)
    predecessor_ir_page = predecessor_ir["pages"][0]
    predecessor_ir_page.pop("page_identity")
    predecessor_ir_page["element_ids"] = [
        "owner-element-1",
        *(child["id"] for child in extracted_child_items),
    ]
    predecessor_ir_page["presentation_element_ids"] = ["owner-element-1"]
    predecessor_ir["elements"] = [
        deepcopy(element)
        for element in extracted_ir["elements"]
        if element["id"] != "element-1"
    ]
    predecessor_ir["bboxes"] = [
        deepcopy(bbox)
        for bbox in extracted_ir["bboxes"]
        if bbox["id"] != "bbox-1"
    ]
    predecessor_ir["evidence"] = [
        deepcopy(record)
        for record in extracted_ir["evidence"]
        if record["id"] != extracted_evidence_id
    ]
    stripped_extracted_public = deepcopy(predecessor_public)
    stripped_extracted_ir = deepcopy(predecessor_ir)

    def validate_extracted_strip(
        *,
        stripped_public: Mapping[str, Any] = stripped_extracted_public,
        stripped_ir: Mapping[str, Any] = stripped_extracted_ir,
    ) -> None:
        _contract.validate_extracted_evidence_strip(
            extracted_ir,
            stripped_ir,
            (extracted_descriptor,),
            projected_public=extracted_public,
            stripped_public=stripped_public,
            predecessor_public=predecessor_public,
            predecessor_ir=predecessor_ir,
            plans=(binding_plan,),
        )

    validate_extracted_strip()

    # Page-local rollback validates both extracted contributions, discards the
    # failed page-one plan/closure, and preserves page two byte-for-byte.
    page_two_id_map = {
        "page-1": "page-2",
        "owner-1": "owner-2",
        "owner-element-1": "owner-element-2",
        "owner-bbox-1": "owner-bbox-2",
        "owner-native-bbox-1": "owner-native-bbox-2",
        "owner-evidence-1": "owner-evidence-2",
        "owner-native-evidence-1": "owner-native-evidence-2",
        "owner-block-1": "owner-block-2",
        "nested-header-child-1": "page-two-nested-header-child-1",
        "nested-header-child-2": "page-two-nested-header-child-2",
        "nested-header-relationship-1": (
            "page-two-nested-header-relationship-1"
        ),
        "nested-header-relationship-2": (
            "page-two-nested-header-relationship-2"
        ),
        "nested-header-bbox-1": "page-two-nested-header-bbox-1",
        "nested-header-bbox-2": "page-two-nested-header-bbox-2",
        "nested-header-evidence-1": (
            "page-two-nested-header-evidence-1"
        ),
        "nested-header-evidence-2": (
            "page-two-nested-header-evidence-2"
        ),
        "element-1": "element-2",
        "bbox-1": "bbox-2",
        "evidence-1": "evidence-2",
        "block-1": "block-2",
        "coord-1": "coord-2",
    }

    def remap_page_one(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): remap_page_one(child)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [remap_page_one(child) for child in value]
        if isinstance(value, tuple):
            return tuple(remap_page_one(child) for child in value)
        if isinstance(value, str):
            return page_two_id_map.get(
                value, value.replace(":page:1:", ":page:2:")
            )
        return value

    page_two_form_semantics = {
        "group_id": "unaffected-form-group-2",
        "relationship_ids": ["unaffected-form-relationship-2"],
    }
    page_two_outline_structure = {
        "group_id": "unaffected-outline-group-2",
        "relationship_ids": ["unaffected-outline-relationship-2"],
    }
    page_two_owner = remap_page_one(extracted_owner)
    page_two_owner.update(
        {
            "layout_forms_projected": True,
            "form_semantics": deepcopy(page_two_form_semantics),
            "layout_outline_structure_projected": True,
            "outline_structure": deepcopy(page_two_outline_structure),
        }
    )
    page_two_owner_hash = _contract.sha256_json(page_two_owner)
    page_two_source_object_ids = [
        identifier.replace(":page:1:", ":page:2:")
        for identifier in extracted_source_object_ids
    ]
    page_two_descriptor = remap_page_one(extracted_descriptor)
    page_two_evidence_id = _contract.extracted_evidence_record_id(
        source_sha256=extracted_public["document"]["sha256"],
        physical_page_index=2,
        source_public_item_id="owner-2",
        source_object_ids=page_two_source_object_ids,
        bbox_id="bbox-2",
        role=page_two_descriptor["role"],
    )
    page_two_descriptor.update(
        {
            "page_id": "page-2",
            "physical_page_index": 2,
            "source_public_item_id": "owner-2",
            "source_public_path": ["pages", 1, "items", 0],
            "source_element_id": "element-2",
            "predecessor_item_sha256": page_two_owner_hash,
            "bbox_id": "bbox-2",
            "evidence_ids": [page_two_evidence_id],
            "source_object_ids": page_two_source_object_ids,
            "canonical_block_id": "block-2",
        }
    )
    page_two_id_parts = (
        POLICY_ID,
        extracted_public["document"]["sha256"],
        2,
        "owner-2",
        tuple(page_two_source_object_ids),
        (page_two_evidence_id,),
        "bbox-2",
        page_two_descriptor["role"],
    )
    page_two_descriptor["id"] = _contract.stable_id(
        "running-region", *page_two_id_parts
    )
    page_two_synthetic_item = remap_page_one(synthetic_item)
    page_two_synthetic_item.update(
        {
            "id": _contract.stable_id(
                "running-region-item", *page_two_id_parts
            ),
            "running_region": deepcopy(page_two_descriptor),
        }
    )
    page_two_plan = _contract.build_extracted_contribution_plan(
        physical_page_index=2,
        owner_public_item_id="owner-2",
        owner_sha256=page_two_owner_hash,
        predecessor_canonical=predecessor,
        source_text=extracted["source_text"],
        presentation_fragments=extracted["presentation_fragments"],
        delimiters=extracted["delimiters"],
        predecessor_intervals=extracted["predecessor_intervals"],
        source_span_groups=extracted["source_span_groups"],
    )
    if (
        binding_plan.physical_page_index != 1
        or page_two_plan.physical_page_index != 2
        or not binding_plan.execute()
        or not page_two_plan.execute()
    ):
        raise SyntheticFixtureIntegrityError(
            "two-page extracted plan ledger differs"
        )

    page_two_identity = remap_page_one(
        extracted_public["pages"][0]["page_identity"]
    )
    page_two_identity.update(
        {
            "page_id": "page-2",
            "physical_page_index": 2,
            "embedded_label": None,
            "detected_printed_label": None,
            "visible_text": None,
            "display_label": "2",
            "display_source": "legacy_display_fallback",
            "evidence_bbox": None,
            "confidence": {
                "scope": "unavailable",
                "score": None,
                "unavailable_reason": (
                    "page_identity_source_unavailable"
                ),
            },
            "concern_codes": [],
        }
    )
    page_two_identity["evidence_source"] = {
        "method": "legacy_display_fallback",
        "reader": "configured_predecessor",
        "page_index": 2,
        "public_item_id": None,
        "public_path": [],
        "element_id": None,
        "bbox_id": None,
        "evidence_ids": [],
        "source_object_ids": [
            (
                "configured-predecessor:"
                f"{extracted_public['document']['sha256']}:"
                "page:2:page_label"
            )
        ],
    }

    page_two_predecessor_public_page = remap_page_one(
        predecessor_public["pages"][0]
    )
    page_two_predecessor_public_page.update(
        {
            "page_index": 2,
            "page_number": 2,
            "page_label": "2",
            "items": [deepcopy(page_two_owner)],
        }
    )
    page_two_projected_public_page = remap_page_one(
        extracted_public["pages"][0]
    )
    page_two_projected_public_page.update(
        {
            "page_index": 2,
            "page_number": 2,
            "page_label": "2",
            "items": [
                deepcopy(page_two_owner),
                deepcopy(page_two_synthetic_item),
            ],
            "page_identity": deepcopy(page_two_identity),
        }
    )

    page_two_predecessor_canonical_page = remap_page_one(
        predecessor_public["canonical_presentation"]["pages"][0]
    )
    page_two_predecessor_canonical_page.update(
        {"page_id": "page-2", "page_index": 2}
    )
    page_two_projected_canonical_page = remap_page_one(
        extracted_public["canonical_presentation"]["pages"][0]
    )
    page_two_projected_canonical_page.update(
        {
            "page_id": "page-2",
            "page_index": 2,
            "page_identity": deepcopy(page_two_identity),
        }
    )
    page_two_relationship_ids = [
        "unaffected-form-relationship-2",
        "unaffected-outline-relationship-2",
    ]
    for canonical_page in (
        page_two_predecessor_canonical_page,
        page_two_projected_canonical_page,
    ):
        page_two_owner_block = next(
            block
            for block in canonical_page["blocks"]
            if block["id"] == "owner-block-2"
        )
        page_two_owner_block["relationship_ids"] = list(
            page_two_relationship_ids
        )

    page_two_predecessor_ir_page = remap_page_one(
        predecessor_ir["pages"][0]
    )
    page_two_predecessor_ir_page.update(
        {"id": "page-2", "page_index": 2}
    )
    page_two_projected_ir_page = remap_page_one(
        extracted_ir["pages"][0]
    )
    page_two_projected_ir_page.update(
        {
            "id": "page-2",
            "page_index": 2,
            "page_identity": deepcopy(page_two_identity),
        }
    )
    page_two_predecessor_ir_elements = [
        remap_page_one(element) for element in predecessor_ir["elements"]
    ]
    page_two_projected_ir_elements = [
        remap_page_one(element) for element in extracted_ir["elements"]
    ]
    for elements in (
        page_two_predecessor_ir_elements,
        page_two_projected_ir_elements,
    ):
        page_two_owner_element = next(
            element
            for element in elements
            if element["id"] == "owner-element-2"
        )
        page_two_owner_element.update(
            {
                "properties": {
                    "legacy_item": deepcopy(page_two_owner),
                    "source_position": 0,
                },
                "form_semantics": deepcopy(page_two_form_semantics),
                "outline_structure": deepcopy(
                    page_two_outline_structure
                ),
            }
        )
    page_two_synthetic_element = next(
        element
        for element in page_two_projected_ir_elements
        if element["id"] == "element-2"
    )
    page_two_synthetic_element.update(
        {
            "evidence_ids": [page_two_evidence_id],
            "running_region": deepcopy(page_two_descriptor),
        }
    )
    page_two_predecessor_ir_bboxes = [
        remap_page_one(bbox) for bbox in predecessor_ir["bboxes"]
    ]
    page_two_projected_ir_bboxes = [
        remap_page_one(bbox) for bbox in extracted_ir["bboxes"]
    ]
    page_two_predecessor_ir_evidence = [
        remap_page_one(record) for record in predecessor_ir["evidence"]
    ]
    page_two_projected_ir_evidence = [
        remap_page_one(record) for record in extracted_ir["evidence"]
    ]
    page_two_synthetic_evidence = next(
        record
        for record in page_two_projected_ir_evidence
        if record["id"] == extracted_evidence_id
    )
    page_two_synthetic_evidence.update(
        {
            "id": page_two_evidence_id,
            "element_id": "element-2",
            "bbox_id": "bbox-2",
            "metadata": {
                "policy_id": POLICY_ID,
                "source_object_ids": list(
                    page_two_source_object_ids
                ),
            },
        }
    )
    page_two_predecessor_ir_coordinates = [
        remap_page_one(coordinate)
        for coordinate in predecessor_ir["coordinate_systems"]
    ]
    page_two_projected_ir_coordinates = [
        remap_page_one(coordinate)
        for coordinate in extracted_ir["coordinate_systems"]
    ]

    multi_extracted_predecessor_public = deepcopy(predecessor_public)
    multi_extracted_predecessor_public["pages"].append(
        page_two_predecessor_public_page
    )
    multi_extracted_predecessor_public["canonical_presentation"][
        "pages"
    ].append(page_two_predecessor_canonical_page)
    multi_extracted_predecessor_ir = deepcopy(predecessor_ir)
    multi_extracted_predecessor_ir["pages"].append(
        page_two_predecessor_ir_page
    )
    multi_extracted_predecessor_ir["elements"].extend(
        page_two_predecessor_ir_elements
    )
    multi_extracted_predecessor_ir["bboxes"].extend(
        page_two_predecessor_ir_bboxes
    )
    multi_extracted_predecessor_ir["evidence"].extend(
        page_two_predecessor_ir_evidence
    )
    multi_extracted_predecessor_ir["coordinate_systems"].extend(
        page_two_predecessor_ir_coordinates
    )

    multi_extracted_projected_public = deepcopy(extracted_public)
    multi_extracted_projected_public["pages"].append(
        page_two_projected_public_page
    )
    multi_extracted_projected_public["canonical_presentation"][
        "pages"
    ].append(page_two_projected_canonical_page)
    multi_extracted_summary = multi_extracted_projected_public["processing"][
        "running_regions"
    ]
    multi_extracted_summary.update(
        {
            "source_page_count": 2,
            "identity_count": 2,
            "legacy_fallback_count": 2,
            "candidate_count": 2,
            "running_region_count": 2,
            "footer_count": 2,
        }
    )
    multi_extracted_projected_ir = deepcopy(extracted_ir)
    multi_extracted_projected_ir["pages"].append(
        page_two_projected_ir_page
    )
    multi_extracted_projected_ir["elements"].extend(
        page_two_projected_ir_elements
    )
    multi_extracted_projected_ir["bboxes"].extend(
        page_two_projected_ir_bboxes
    )
    multi_extracted_projected_ir["evidence"].extend(
        page_two_projected_ir_evidence
    )
    multi_extracted_projected_ir["coordinate_systems"].extend(
        page_two_projected_ir_coordinates
    )

    multi_extracted_fallback_public = deepcopy(predecessor_public)
    failed_public_page = deepcopy(
        multi_extracted_fallback_public["pages"][0]
    )
    failed_public_page["page_identity"] = deepcopy(
        extracted_public["pages"][0]["page_identity"]
    )
    multi_extracted_fallback_public["pages"] = [
        failed_public_page,
        deepcopy(page_two_projected_public_page),
    ]
    failed_canonical_page = deepcopy(
        multi_extracted_fallback_public["canonical_presentation"]["pages"][0]
    )
    failed_canonical_page["page_identity"] = deepcopy(
        extracted_public["canonical_presentation"]["pages"][0][
            "page_identity"
        ]
    )
    multi_extracted_fallback_public["canonical_presentation"]["pages"] = [
        failed_canonical_page,
        deepcopy(page_two_projected_canonical_page),
    ]
    multi_extracted_fallback_summary = deepcopy(multi_extracted_summary)
    multi_extracted_fallback_summary.update(
        {
            "candidate_count": 1,
            "running_region_count": 1,
            "footer_count": 1,
        }
    )
    multi_extracted_fallback_public["processing"] = {
        "running_regions": multi_extracted_fallback_summary
    }
    multi_extracted_fallback_public.pop("running_region_concerns", None)

    multi_extracted_fallback_ir = deepcopy(predecessor_ir)
    failed_ir_page = deepcopy(multi_extracted_fallback_ir["pages"][0])
    failed_ir_page["page_identity"] = deepcopy(
        extracted_ir["pages"][0]["page_identity"]
    )
    multi_extracted_fallback_ir["pages"] = [
        failed_ir_page,
        deepcopy(page_two_projected_ir_page),
    ]
    multi_extracted_fallback_ir["elements"].extend(
        deepcopy(page_two_projected_ir_elements)
    )
    multi_extracted_fallback_ir["bboxes"].extend(
        deepcopy(page_two_projected_ir_bboxes)
    )
    multi_extracted_fallback_ir["evidence"].extend(
        deepcopy(page_two_projected_ir_evidence)
    )
    multi_extracted_fallback_ir["coordinate_systems"].extend(
        deepcopy(page_two_projected_ir_coordinates)
    )

    multi_extracted_predecessor_bundle = {
        "public": multi_extracted_predecessor_public,
        "ir": multi_extracted_predecessor_ir,
    }
    multi_extracted_projected_bundle = {
        "public": multi_extracted_projected_public,
        "ir": multi_extracted_projected_ir,
    }
    multi_extracted_fallback_bundle = {
        "public": multi_extracted_fallback_public,
        "ir": multi_extracted_fallback_ir,
    }
    extracted_fallback_result = _contract.execute_transaction_witness(
        multi_extracted_predecessor_bundle,
        projected_state=multi_extracted_projected_bundle,
        outcome="page_failure",
        physical_page_index=1,
        fallback_state=multi_extracted_fallback_bundle,
        plans=(binding_plan, page_two_plan),
    )
    failed_page_items = extracted_fallback_result.payload["public"]["pages"][
        0
    ]["items"]
    surviving_page_items = extracted_fallback_result.payload["public"][
        "pages"
    ][1]["items"]
    if (
        not extracted_fallback_result.committed
        or _contract.strict_json_bytes(extracted_fallback_result.payload)
        != _contract.strict_json_bytes(multi_extracted_fallback_bundle)
        or any(
            item.get("id") == synthetic_item["id"]
            for item in failed_page_items
            if isinstance(item, Mapping)
        )
        or not any(
            item.get("id") == page_two_synthetic_item["id"]
            for item in surviving_page_items
            if isinstance(item, Mapping)
        )
        or _contract.strict_json_bytes(
            extracted_fallback_result.payload["public"]["pages"][1]
        )
        != _contract.strict_json_bytes(
            multi_extracted_projected_bundle["public"]["pages"][1]
        )
        or _contract.strict_json_bytes(
            extracted_fallback_result.payload["public"][
                "canonical_presentation"
            ]["pages"][1]
        )
        != _contract.strict_json_bytes(
            multi_extracted_projected_bundle["public"][
                "canonical_presentation"
            ]["pages"][1]
        )
    ):
        raise SyntheticFixtureIntegrityError(
            "two-page extracted fallback plan/closure custody differs"
        )

    extracted_unaffected_drift = deepcopy(multi_extracted_fallback_bundle)
    extracted_unaffected_drift["public"]["pages"][1]["items"][0][
        "form_semantics"
    ]["group_id"] = "forged-unaffected-form-group"
    _expect_contract_rejection(
        lambda: _contract.execute_transaction_witness(
            multi_extracted_predecessor_bundle,
            projected_state=multi_extracted_projected_bundle,
            outcome="page_failure",
            physical_page_index=1,
            fallback_state=extracted_unaffected_drift,
            plans=(binding_plan, page_two_plan),
        ),
        "extracted fallback unaffected-page closure drift",
    )

    fabricated_predecessor_text = predecessor.replace(
        "Manufacturing body.", "Fabricated body."
    )
    fabricated_projected = deepcopy(extracted_public)
    fabricated_owner = fabricated_projected["pages"][0]["items"][0]
    fabricated_owner["value"] = fabricated_predecessor_text
    fabricated_owner["md"] = fabricated_predecessor_text
    fabricated_owner_hash = _contract.sha256_json(fabricated_owner)
    fabricated_descriptor = fabricated_projected["pages"][0]["items"][1][
        "running_region"
    ]
    fabricated_descriptor["predecessor_item_sha256"] = fabricated_owner_hash
    fabricated_plan = _contract.build_extracted_contribution_plan(
        physical_page_index=1,
        owner_public_item_id="owner-1",
        owner_sha256=fabricated_owner_hash,
        predecessor_canonical=fabricated_predecessor_text,
        source_text=extracted["source_text"],
        presentation_fragments=extracted["presentation_fragments"],
        delimiters=extracted["delimiters"],
        predecessor_intervals=extracted["predecessor_intervals"],
        source_span_groups=extracted["source_span_groups"],
    )
    fabricated_page = fabricated_projected["canonical_presentation"]["pages"][0]
    fabricated_owner_block = fabricated_page["blocks"][0]
    fabricated_owner_block["markdown"] = fabricated_plan.residual_canonical
    fabricated_owner_block["text"] = fabricated_plan.residual_canonical
    fabricated_page["body"]["markdown"] = fabricated_plan.residual_canonical
    fabricated_page["body"]["text"] = fabricated_plan.residual_canonical
    fabricated_full = (
        f"{fabricated_plan.residual_canonical.strip()}\n\n"
        f"{fabricated_plan.presentation_text}\n"
    )
    fabricated_page["full"]["markdown"] = fabricated_full
    fabricated_page["full"]["text"] = fabricated_full
    _contract.validate_projected_document(fabricated_projected)
    _expect_contract_rejection(
        lambda: _contract.strip_complete_running_region_sidecars(
            fabricated_projected,
            predecessor_document=predecessor_public,
            plans=(fabricated_plan,),
        ),
        "coordinated fabricated extracted predecessor/residual plan",
    )

    # A single committed page may mix retained body, direct projection, and an
    # extracted synthetic suffix; the complete inverse must recover both layers.
    mixed_public = deepcopy(extracted_public)
    mixed_ir = deepcopy(extracted_ir)
    mixed_predecessor_public = deepcopy(predecessor_public)
    mixed_predecessor_ir = deepcopy(predecessor_ir)
    mixed_direct_predecessor_item = deepcopy(public["pages"][0]["items"][0])
    mixed_direct_source_descriptor = mixed_direct_predecessor_item["running_region"]
    for key in _contract.RUNNING_REGION_SIDECAR_FIELDS:
        mixed_direct_predecessor_item.pop(key)
    mixed_direct_predecessor_item["type"] = mixed_direct_source_descriptor[
        "predecessor_type"
    ]
    mixed_direct_predecessor_item.update(
        {"id": "mixed-direct-item", "reading_order": 1}
    )
    mixed_direct_descriptor = deepcopy(
        public["pages"][0]["items"][0]["running_region"]
    )
    mixed_direct_descriptor.update(
        {
            "id": _contract.stable_id(
                "running-region",
                POLICY_ID,
                mixed_public["document"]["sha256"],
                1,
                "mixed-direct-element",
                "mixed-direct-bbox",
                "footer",
            ),
            "source_public_item_id": "mixed-direct-item",
            "source_public_path": ["pages", 0, "items", 1],
            "source_element_id": "mixed-direct-element",
            "predecessor_item_sha256": _contract.sha256_json(
                mixed_direct_predecessor_item
            ),
            "bbox_id": "mixed-direct-bbox",
            "evidence_ids": ["mixed-direct-evidence"],
            "source_object_ids": ["mixed-direct-word"],
            "canonical_block_id": "mixed-direct-block",
        }
    )
    mixed_direct_item = {
        **deepcopy(mixed_direct_predecessor_item),
        "type": "footer",
        "layout_running_region_projected": True,
        "running_region_policy": POLICY_ID,
        "running_region": mixed_direct_descriptor,
    }
    mixed_synthetic_item = mixed_public["pages"][0]["items"][1]
    mixed_synthetic_item["reading_order"] = 2
    mixed_public["pages"][0]["items"] = [
        deepcopy(extracted_owner),
        mixed_direct_item,
        mixed_synthetic_item,
    ]
    mixed_direct_block = {
        "id": "mixed-direct-block",
        "page_id": "page-1",
        "primary_element_id": "mixed-direct-element",
        "primary_element_type": "footer",
        "scope": "footer",
        "markdown": "RUNNING FOOTER",
        "text": "RUNNING FOOTER",
        "contributing_element_ids": ["mixed-direct-element"],
        "relationship_ids": [],
        "excluded_contributions": [],
        "omission_reason": None,
        "suppressed_by_element_id": None,
    }
    mixed_canonical_page = mixed_public["canonical_presentation"]["pages"][0]
    mixed_canonical_page["blocks"] = [
        mixed_canonical_page["blocks"][0],
        mixed_direct_block,
        mixed_canonical_page["blocks"][1],
    ]
    mixed_canonical_page["body"] = {
        "block_ids": ["owner-block-1"],
        "markdown": residual,
        "text": residual,
    }
    mixed_footer_text = (
        f"RUNNING FOOTER\n\n{extracted['presentation_text']}\n"
    )
    mixed_canonical_page["footer"] = {
        "block_ids": ["mixed-direct-block", "block-1"],
        "markdown": mixed_footer_text,
        "text": mixed_footer_text,
    }
    mixed_canonical_page["header"] = {
        "block_ids": [],
        "markdown": "",
        "text": "",
    }
    mixed_full_text = (
        f"{residual.strip()}\n\nRUNNING FOOTER\n\n"
        f"{extracted['presentation_text']}\n"
    )
    mixed_canonical_page["full"] = {
        "block_ids": ["owner-block-1", "mixed-direct-block", "block-1"],
        "markdown": mixed_full_text,
        "text": mixed_full_text,
    }
    mixed_summary = mixed_public["processing"]["running_regions"]
    mixed_summary["running_region_count"] = 2
    mixed_summary["footer_count"] = 2

    mixed_direct_element = {
        "id": "mixed-direct-element",
        "page_id": "page-1",
        "type": "footer",
        "bbox_ids": ["mixed-direct-bbox"],
        "evidence_ids": ["mixed-direct-evidence"],
        "presentation_role": "primary",
        "running_region": deepcopy(mixed_direct_descriptor),
    }
    mixed_ir["elements"].insert(1, mixed_direct_element)
    mixed_ir["bboxes"].append(
        {
            "id": "mixed-direct-bbox",
            "coordinate_system_id": "coord-1",
            **{
                key: mixed_direct_descriptor["bbox"][key]
                for key in ("x", "y", "width", "height")
            },
        }
    )
    mixed_ir["evidence"].append(
        {
            "id": "mixed-direct-evidence",
            "element_id": "mixed-direct-element",
            "bbox_id": "mixed-direct-bbox",
        }
    )
    mixed_ir["pages"][0]["element_ids"] = [
        "owner-element-1",
        *(child["id"] for child in extracted_child_items),
        "mixed-direct-element",
        "element-1",
    ]
    mixed_ir["pages"][0]["presentation_element_ids"] = [
        "owner-element-1",
        "mixed-direct-element",
        "element-1",
    ]

    mixed_predecessor_public["pages"][0]["items"].append(
        mixed_direct_predecessor_item
    )
    mixed_predecessor_direct_block = deepcopy(mixed_direct_block)
    mixed_predecessor_direct_block["scope"] = "body"
    mixed_predecessor_direct_block["primary_element_type"] = "text"
    mixed_predecessor_canonical_page = mixed_predecessor_public[
        "canonical_presentation"
    ]["pages"][0]
    mixed_predecessor_canonical_page["blocks"].append(
        mixed_predecessor_direct_block
    )
    mixed_predecessor_text = f"{predecessor.strip()}\n\nRUNNING FOOTER\n"
    mixed_predecessor_canonical_page["body"] = {
        "block_ids": ["owner-block-1", "mixed-direct-block"],
        "markdown": mixed_predecessor_text,
        "text": mixed_predecessor_text,
    }
    mixed_predecessor_canonical_page["full"] = deepcopy(
        mixed_predecessor_canonical_page["body"]
    )
    mixed_predecessor_canonical_page["header"] = {
        "block_ids": [],
        "markdown": "",
        "text": "",
    }
    mixed_predecessor_canonical_page["footer"] = deepcopy(
        mixed_predecessor_canonical_page["header"]
    )
    mixed_predecessor_element = deepcopy(mixed_direct_element)
    mixed_predecessor_element.pop("running_region")
    mixed_predecessor_element["type"] = "text"
    mixed_predecessor_ir["elements"].insert(1, mixed_predecessor_element)
    mixed_predecessor_ir["bboxes"].append(deepcopy(mixed_ir["bboxes"][-1]))
    mixed_predecessor_ir["evidence"].append(deepcopy(mixed_ir["evidence"][-1]))
    mixed_predecessor_ir["pages"][0]["element_ids"].append(
        "mixed-direct-element"
    )
    mixed_predecessor_ir["pages"][0]["presentation_element_ids"].append(
        "mixed-direct-element"
    )
    mixed_stripped = _contract.strip_complete_running_region_sidecars(
        mixed_public,
        predecessor_document=mixed_predecessor_public,
        plans=(binding_plan,),
        ir_document=mixed_ir,
        predecessor_ir=mixed_predecessor_ir,
    )
    if mixed_stripped != mixed_predecessor_public:
        raise SyntheticFixtureIntegrityError("mixed complete inverse drifted")

    residual_public_item = deepcopy(stripped_extracted_public)
    residual_public_item["pages"][0]["items"].append(deepcopy(synthetic_item))
    residual_ir_element = deepcopy(stripped_extracted_ir)
    residual_ir_element["elements"].append(deepcopy(extracted_ir["elements"][1]))
    residual_ir_bbox = deepcopy(stripped_extracted_ir)
    residual_ir_bbox["bboxes"].append(deepcopy(extracted_ir["bboxes"][0]))
    residual_ir_evidence = deepcopy(stripped_extracted_ir)
    residual_ir_evidence["evidence"].append(deepcopy(extracted_ir["evidence"][1]))
    residual_ir_element_backlink = deepcopy(stripped_extracted_ir)
    residual_ir_element_backlink["pages"][0]["element_ids"].append("element-1")
    residual_ir_presentation_backlink = deepcopy(stripped_extracted_ir)
    residual_ir_presentation_backlink["pages"][0][
        "presentation_element_ids"
    ].append("element-1")
    residual_ir_page_identity = deepcopy(stripped_extracted_ir)
    residual_ir_page_identity["pages"][0]["page_identity"] = deepcopy(
        extracted_public["pages"][0]["page_identity"]
    )
    changed_owner_evidence = deepcopy(stripped_extracted_ir)
    changed_owner_evidence["evidence"] = []
    residual_canonical_block = deepcopy(stripped_extracted_public)
    residual_canonical_block["canonical_presentation"]["pages"][0][
        "blocks"
    ].append(deepcopy(extracted_block))
    residual_canonical_membership = deepcopy(stripped_extracted_public)
    residual_canonical_membership["canonical_presentation"]["pages"][0]["full"][
        "block_ids"
    ].append("block-1")
    for label, bad_public, bad_ir in (
        (
            "residual synthetic extracted public item",
            residual_public_item,
            stripped_extracted_ir,
        ),
        (
            "residual synthetic extracted IR element",
            stripped_extracted_public,
            residual_ir_element,
        ),
        (
            "residual synthetic extracted IR bbox",
            stripped_extracted_public,
            residual_ir_bbox,
        ),
        (
            "residual synthetic extracted evidence",
            stripped_extracted_public,
            residual_ir_evidence,
        ),
        (
            "residual synthetic IR element backlink",
            stripped_extracted_public,
            residual_ir_element_backlink,
        ),
        (
            "residual synthetic IR presentation backlink",
            stripped_extracted_public,
            residual_ir_presentation_backlink,
        ),
        (
            "residual synthetic IR page identity",
            stripped_extracted_public,
            residual_ir_page_identity,
        ),
        (
            "changed fused-owner evidence during extracted strip",
            stripped_extracted_public,
            changed_owner_evidence,
        ),
        (
            "residual synthetic canonical block",
            residual_canonical_block,
            stripped_extracted_ir,
        ),
        (
            "residual synthetic canonical membership",
            residual_canonical_membership,
            stripped_extracted_ir,
        ),
    ):
        _expect_contract_rejection(
            lambda bad_public=bad_public, bad_ir=bad_ir: validate_extracted_strip(
                stripped_public=bad_public,
                stripped_ir=bad_ir,
            ),
            label,
        )

    def direct_predecessors_for(
        projected_public: Mapping[str, Any],
        projected_ir: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        predecessor_public = deepcopy(dict(projected_public))
        descriptors_by_page: dict[int, list[Mapping[str, Any]]] = {}
        for page in predecessor_public["pages"]:
            page.pop("page_identity")
            for item in page.get("items", []):
                if not isinstance(item, dict) or not isinstance(
                    item.get("running_region"), Mapping
                ):
                    continue
                descriptor = deepcopy(item["running_region"])
                if descriptor["source_method"] == "extracted_source_contribution":
                    raise SyntheticFixtureIntegrityError(
                        "direct predecessor helper received extraction"
                    )
                descriptors_by_page.setdefault(page["page_index"], []).append(
                    descriptor
                )
                for key in _contract.RUNNING_REGION_SIDECAR_FIELDS:
                    item.pop(key)
                item["type"] = descriptor["predecessor_type"]
        for canonical_page in predecessor_public["canonical_presentation"]["pages"]:
            canonical_page.pop("page_identity")
            descriptors = descriptors_by_page.get(canonical_page["page_index"], [])
            descriptors_by_block = {
                descriptor["canonical_block_id"]: descriptor
                for descriptor in descriptors
            }
            for block in canonical_page["blocks"]:
                descriptor = descriptors_by_block.get(block["id"])
                if descriptor is not None:
                    block["scope"] = "body"
                    block["primary_element_type"] = descriptor["predecessor_type"]
            included = [
                block
                for block in canonical_page["blocks"]
                if block["omission_reason"] is None
            ]
            by_id = {block["id"]: block for block in included}

            def render(
                block_ids: Sequence[str],
                field: str,
                blocks_by_id: Mapping[str, Mapping[str, Any]] = by_id,
            ) -> str:
                values = [
                    str(blocks_by_id[block_id].get(field, "")).strip()
                    for block_id in block_ids
                    if str(blocks_by_id[block_id].get(field, "")).strip()
                ]
                return "\n\n".join(values).rstrip() + "\n" if values else ""

            scoped = {"body": [], "header": [], "footer": []}
            full_ids: list[str] = []
            for block in included:
                full_ids.append(block["id"])
                scoped[block["scope"]].append(block["id"])
            for view_name, block_ids in {"full": full_ids, **scoped}.items():
                canonical_page[view_name] = {
                    "block_ids": block_ids,
                    "markdown": render(block_ids, "markdown"),
                    "text": render(block_ids, "text"),
                }
        predecessor_public["processing"].pop("running_regions")
        if not predecessor_public["processing"]:
            predecessor_public.pop("processing")
        predecessor_public.pop("running_region_concerns", None)

        if projected_ir is None:
            return predecessor_public, None
        predecessor_ir = deepcopy(dict(projected_ir))
        for page in predecessor_ir["pages"]:
            page.pop("page_identity")
        for element in predecessor_ir["elements"]:
            descriptor = element.pop("running_region", None)
            if isinstance(descriptor, Mapping):
                element["type"] = descriptor["predecessor_type"]
        return predecessor_public, predecessor_ir

    def install_document_views(document: dict[str, Any]) -> None:
        canonical = document["canonical_presentation"]
        pages = canonical["pages"]
        for view_name in ("full", "body", "header", "footer"):
            block_ids = [
                block_id
                for page in pages
                for block_id in page[view_name]["block_ids"]
            ]
            markdown_pages = [
                page[view_name]["markdown"].strip()
                for page in pages
                if page[view_name]["markdown"].strip()
            ]
            text_pages = [
                page[view_name]["text"].strip()
                for page in pages
                if page[view_name]["text"].strip()
            ]

            def render(values: Sequence[str]) -> str:
                return "\n\n".join(values).rstrip() + "\n" if values else ""

            canonical[view_name] = {
                "block_ids": block_ids,
                "markdown": render(markdown_pages),
                "text": render(text_pages),
            }

    direct_predecessor, direct_predecessor_ir = direct_predecessors_for(public, ir)
    assert direct_predecessor_ir is not None
    zero_region_public = deepcopy(direct_predecessor)
    zero_region_public["pages"][0]["page_identity"] = deepcopy(
        public["pages"][0]["page_identity"]
    )
    zero_region_public["canonical_presentation"]["pages"][0][
        "page_identity"
    ] = deepcopy(public["pages"][0]["page_identity"])
    zero_region_summary = deepcopy(public["processing"]["running_regions"])
    zero_region_summary["candidate_count"] = 0
    zero_region_summary["running_region_count"] = 0
    zero_region_summary["footer_count"] = 0
    zero_region_public["processing"] = {"running_regions": zero_region_summary}
    zero_region_ir = deepcopy(direct_predecessor_ir)
    zero_region_ir["pages"][0]["page_identity"] = deepcopy(
        public["pages"][0]["page_identity"]
    )
    _contract.validate_projected_document(zero_region_public)
    _contract.validate_ir_bindings(
        zero_region_ir, public_document=zero_region_public
    )
    zero_region_view_drift = deepcopy(zero_region_public)
    zero_region_view_drift["canonical_presentation"]["pages"][0]["full"][
        "text"
    ] = "fabricated\n"
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(zero_region_view_drift),
        "zero-region canonical page view drift",
    )

    def boundary_candidate_for(
        document: Mapping[str, Any],
        *,
        page_offset: int = 0,
        normalized_signature: str | None = None,
    ) -> dict[str, Any]:
        page = document["pages"][page_offset]
        region_item = next(
            item
            for item in page["items"]
            if isinstance(item, Mapping)
            and isinstance(item.get("running_region"), Mapping)
        )
        descriptor = region_item["running_region"]
        candidate = {
            "id": "pending",
            "public_item_id": descriptor["source_public_item_id"],
            "public_path": list(descriptor["source_public_path"]),
            "element_id": descriptor["source_element_id"],
            "predecessor_type": descriptor["predecessor_type"],
            "bbox": dict(descriptor["bbox"]),
            "bbox_id": descriptor["bbox_id"],
            "evidence_ids": list(descriptor["evidence_ids"]),
            "source_object_ids": list(descriptor["source_object_ids"]),
            "raw_layout_role": (
                "page_header"
                if descriptor["canonical_scope"] == "header"
                else "page_footer"
            ),
            "normalized_signature": (
                " ".join(str(region_item["value"]).casefold().split())
                if normalized_signature is None
                else normalized_signature
            ),
            "boundary_band": (
                "top" if descriptor["canonical_scope"] == "header" else "bottom"
            ),
            "source_method": descriptor["source_method"],
            "disposition": "accepted",
            "confidence": deepcopy(descriptor["confidence"]),
            "concern_codes": list(descriptor["concern_codes"]),
        }
        candidate["id"] = _contract.boundary_candidate_id(
            candidate,
            source_sha256=document["document"]["sha256"],
            physical_page_index=page["page_index"],
        )
        return candidate

    def source_report_for(
        document: Mapping[str, Any],
        *,
        label_candidates: Sequence[Sequence[Mapping[str, Any]]] | None = None,
        boundary_candidates: Sequence[Sequence[Mapping[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        for offset, page in enumerate(document["pages"]):
            labels = (
                []
                if label_candidates is None
                else [deepcopy(value) for value in label_candidates[offset]]
            )
            boundaries = (
                [boundary_candidate_for(document, page_offset=offset)]
                if boundary_candidates is None
                else [deepcopy(value) for value in boundary_candidates[offset]]
            )
            pages.append(
                {
                    "page_index": page["page_index"],
                    "page_width": page["page_width"],
                    "page_height": page["page_height"],
                    "unit": page["unit"],
                    "coordinate_system_id": _contract.COORDINATE_SYSTEM_ID,
                    "source_character_count": 0,
                    "source_word_count": 0,
                    "embedded_label": page["page_identity"]["embedded_label"],
                    "label_candidates": labels,
                    "boundary_candidates": boundaries,
                    "concern_codes": [],
                }
            )
        return {
            "report_version": _contract.REPORT_VERSION,
            "policy_id": POLICY_ID,
            "source_sha256": document["document"]["sha256"],
            "status": "available",
            "pages": pages,
            "counts": {
                "page_count": len(pages),
                "source_character_count": 0,
                "source_word_count": 0,
                "embedded_label_count": sum(
                    page["embedded_label"] is not None for page in pages
                ),
                "label_candidate_count": sum(
                    len(page["label_candidates"]) for page in pages
                ),
                "boundary_candidate_count": sum(
                    len(page["boundary_candidates"]) for page in pages
                ),
                "concern_count": sum(
                    len(page["concern_codes"])
                    + sum(
                        len(candidate["concern_codes"])
                        for candidate in (
                            *page["label_candidates"],
                            *page["boundary_candidates"],
                        )
                    )
                    for page in pages
                ),
            },
            "concern_codes": [],
            "extraction_ms": document["processing"]["running_regions"][
                "extraction_ms"
            ],
        }

    def source_projection_envelope(
        source_report: Mapping[str, Any],
        *,
        extracted_plans: Sequence[_contract.ExtractedContributionPlan] = (),
        comparison_ledger: Sequence[Mapping[str, Any]] = (),
        method_proofs: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return the fixed extractor's strict-JSON production envelope."""

        return {
            "source_report": deepcopy(dict(source_report)),
            "extracted_plans": [
                json.loads(_contract.extracted_plan_json_bytes(plan))
                for plan in extracted_plans
            ],
            "comparison_ledger": deepcopy(list(comparison_ledger)),
            "method_proofs": deepcopy(
                {} if method_proofs is None else dict(method_proofs)
            ),
        }

    def issue_source_projection_authority(
        source_report: Mapping[str, Any],
        *,
        predecessor_document: Mapping[str, Any],
        predecessor_ir: Mapping[str, Any] | None = None,
        extracted_plans: Sequence[_contract.ExtractedContributionPlan] = (),
        comparison_ledger: Sequence[Mapping[str, Any]] = (),
        method_proofs: Mapping[str, Mapping[str, Any]] | None = None,
        source_pdf_bytes: bytes | None = None,
    ) -> Any:
        """Issue opaque authority through two deterministic fixed-hook calls."""

        envelope = source_projection_envelope(
            source_report,
            extracted_plans=extracted_plans,
            comparison_ledger=comparison_ledger,
            method_proofs=method_proofs,
        )
        configured_predecessor = {
            "public": predecessor_document,
            "ir": predecessor_ir,
        }
        original_extractor = (
            _contract._extract_running_region_source_projection
        )

        def deterministic_extractor(
            pdf_bytes: bytes, configured: Mapping[str, Any]
        ) -> Mapping[str, Any]:
            if (
                not isinstance(pdf_bytes, bytes)
                or _contract.strict_json_bytes(configured)
                != _contract.strict_json_bytes(configured_predecessor)
            ):
                raise SyntheticFixtureIntegrityError(
                    "fixed source-projection extractor arguments drifted"
                )
            return deepcopy(envelope)

        _contract._extract_running_region_source_projection = (
            deterministic_extractor
        )
        try:
            return _contract.prepare_source_projection_authority(
                configured_predecessor,
                _source_alignment_pdf()
                if source_pdf_bytes is None
                else source_pdf_bytes,
            )
        finally:
            _contract._extract_running_region_source_projection = (
                original_extractor
            )

    def validate_source_projection(
        source_report: Mapping[str, Any],
        public_document: Mapping[str, Any],
        *,
        predecessor_document: Mapping[str, Any],
        ir_document: Mapping[str, Any] | None = None,
        predecessor_ir: Mapping[str, Any] | None = None,
        extracted_plans: Sequence[_contract.ExtractedContributionPlan] = (),
        comparison_ledger: Sequence[Mapping[str, Any]] = (),
        method_proofs: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        """Exercise the public binder only with a factory-issued authority."""

        authority = issue_source_projection_authority(
            source_report,
            predecessor_document=predecessor_document,
            predecessor_ir=predecessor_ir,
            extracted_plans=extracted_plans,
            comparison_ledger=comparison_ledger,
            method_proofs=method_proofs,
        )
        _contract.validate_source_projection_bindings(
            authority,
            public_document,
            predecessor_document=predecessor_document,
            ir_document=ir_document,
            predecessor_ir=predecessor_ir,
            extracted_plans=extracted_plans,
            comparison_ledger=comparison_ledger,
            method_proofs=method_proofs,
        )

    direct_report = source_report_for(public)
    direct_candidate = direct_report["pages"][0]["boundary_candidates"][0]
    if _contract.expected_candidate_role(direct_candidate) != "footer":
        raise SyntheticFixtureIntegrityError("trusted candidate role binding drifted")

    # A source report is data, never authority.  Only the fixed dual-run
    # extractor may mint the opaque capability accepted by the final binder.
    direct_authority = issue_source_projection_authority(
        direct_report,
        predecessor_document=direct_predecessor,
        predecessor_ir=direct_predecessor_ir,
    )
    authority_call = {
        "public_document": public,
        "predecessor_document": direct_predecessor,
        "ir_document": ir,
        "predecessor_ir": direct_predecessor_ir,
    }
    _expect_contract_rejection(
        lambda: _contract.validate_source_projection_bindings(
            direct_report,  # type: ignore[arg-type]
            **authority_call,
        ),
        "ordinary source report used as projection authority",
    )
    authority_lookalike = {
        name: (
            getattr(direct_authority, name).hex()
            if isinstance(getattr(direct_authority, name), bytes)
            else getattr(direct_authority, name)
        )
        for name in (
            "source_sha256",
            "predecessor_sha256",
            "source_report_json",
            "extracted_plans_json",
            "comparison_ledger_json",
            "method_proofs_json",
            "owner_bindings_json",
        )
    }
    for label, lookalike in (
        ("mapping source-projection authority lookalike", authority_lookalike),
        (
            "read-only source-projection authority lookalike",
            MappingProxyType(authority_lookalike),
        ),
        (
            "JSON source-projection authority lookalike",
            json.loads(json.dumps(authority_lookalike)),
        ),
        (
            "pickle source-projection authority lookalike",
            pickle.loads(pickle.dumps(authority_lookalike)),
        ),
    ):
        _expect_contract_rejection(
            lambda lookalike=lookalike: (
                _contract.validate_source_projection_bindings(
                    lookalike,  # type: ignore[arg-type]
                    **authority_call,
                )
            ),
            label,
        )
    _expect_contract_rejection(
        lambda: _contract._ValidatedSourceProjectionAuthority(),
        "direct source-projection authority construction",
    )
    for label, callback in (
        ("copied source-projection authority", lambda: copy(direct_authority)),
        (
            "deep-copied source-projection authority",
            lambda: deepcopy(direct_authority),
        ),
        (
            "JSON-serialized source-projection authority",
            lambda: _contract.strict_json_bytes(direct_authority),
        ),
        (
            "pickled source-projection authority",
            lambda: pickle.dumps(direct_authority),
        ),
    ):
        _expect_contract_rejection(callback, label)

    unregistered_authority = object.__new__(
        _contract._ValidatedSourceProjectionAuthority
    )
    for name in (
        "source_sha256",
        "predecessor_sha256",
        "source_report_json",
        "extracted_plans_json",
        "comparison_ledger_json",
        "method_proofs_json",
        "owner_bindings_json",
    ):
        object.__setattr__(
            unregistered_authority,
            name,
            getattr(direct_authority, name),
        )
    _expect_contract_rejection(
        lambda: _contract.validate_source_projection_bindings(
            unregistered_authority,
            **authority_call,
        ),
        "unregistered source-projection authority lookalike",
    )
    unregistered_authority = None

    original_report_json = direct_authority.source_report_json
    object.__setattr__(direct_authority, "source_report_json", b"{}")
    try:
        _expect_contract_rejection(
            lambda: _contract.validate_source_projection_bindings(
                direct_authority,
                **authority_call,
            ),
            "tampered registered source-projection authority",
        )
    finally:
        object.__setattr__(
            direct_authority,
            "source_report_json",
            original_report_json,
        )

    source_projection_pdf = _source_alignment_pdf()
    authority_referents = gc.get_referents(direct_authority)
    if (
        source_projection_pdf in authority_referents
        or any(
            getattr(direct_authority, name) == source_projection_pdf
            for name in (
                "source_report_json",
                "extracted_plans_json",
                "comparison_ledger_json",
                "method_proofs_json",
                "owner_bindings_json",
            )
        )
        or hasattr(direct_authority, "source_pdf_bytes")
    ):
        raise SyntheticFixtureIntegrityError(
            "source-projection authority retained raw PDF bytes"
        )

    _expect_contract_rejection(
        lambda: issue_source_projection_authority(
            direct_report,
            predecessor_document=direct_predecessor,
            predecessor_ir=direct_predecessor_ir,
            source_pdf_bytes=source_projection_pdf + b"wrong-source",
        ),
        "source-projection authority wrong source PDF bytes",
    )
    wrong_hash_predecessor = deepcopy(direct_predecessor)
    wrong_hash_predecessor["document"]["sha256"] = "0" * 64
    _expect_contract_rejection(
        lambda: issue_source_projection_authority(
            direct_report,
            predecessor_document=wrong_hash_predecessor,
            predecessor_ir=direct_predecessor_ir,
        ),
        "source-projection authority wrong configured source hash",
    )
    wrong_public_owner_ir = deepcopy(direct_predecessor_ir)
    wrong_public_owner_element = next(
        element
        for element in wrong_public_owner_ir["elements"]
        if element["id"] == direct_candidate["element_id"]
    )
    wrong_public_owner_element["properties"]["legacy_item"][
        "id"
    ] = "wrong-public-owner"
    _expect_contract_rejection(
        lambda: issue_source_projection_authority(
            direct_report,
            predecessor_document=direct_predecessor,
            predecessor_ir=wrong_public_owner_ir,
        ),
        "source-projection direct candidate wrong public-owner backlink",
    )

    def reject_authority_binding(
        label: str,
        *,
        predecessor_document: Mapping[str, Any] = direct_predecessor,
        predecessor_ir: Mapping[str, Any] = direct_predecessor_ir,
        extracted_plans: Sequence[_contract.ExtractedContributionPlan] = (),
        comparison_ledger: Sequence[Mapping[str, Any]] = (),
        method_proofs: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        _expect_contract_rejection(
            lambda: _contract.validate_source_projection_bindings(
                direct_authority,
                public,
                predecessor_document=predecessor_document,
                ir_document=ir,
                predecessor_ir=predecessor_ir,
                extracted_plans=extracted_plans,
                comparison_ledger=comparison_ledger,
                method_proofs=method_proofs,
            ),
            label,
        )

    wrong_public_predecessor = deepcopy(direct_predecessor)
    wrong_public_predecessor["authority_drift"] = True
    wrong_ir_predecessor = deepcopy(direct_predecessor_ir)
    wrong_ir_predecessor["authority_drift"] = True
    wrong_canonical_predecessor = deepcopy(direct_predecessor)
    wrong_canonical_predecessor["canonical_presentation"][
        "authority_drift"
    ] = True
    reject_authority_binding(
        "source-projection authority wrong configured predecessor",
        predecessor_document=wrong_public_predecessor,
    )
    reject_authority_binding(
        "source-projection authority wrong configured predecessor IR",
        predecessor_ir=wrong_ir_predecessor,
    )
    reject_authority_binding(
        "source-projection authority wrong public-owner backlink",
        predecessor_ir=wrong_public_owner_ir,
    )
    reject_authority_binding(
        "source-projection authority wrong configured canonical graph",
        predecessor_document=wrong_canonical_predecessor,
    )
    reject_authority_binding(
        "source-projection authority wrong extracted plans",
        extracted_plans=(binding_plan,),
    )
    reject_authority_binding(
        "source-projection authority wrong comparison ledger",
        comparison_ledger=({"page_index": 1, "comparison_count": 1},),
    )
    reject_authority_binding(
        "source-projection authority wrong method proofs",
        method_proofs={direct_candidate["id"]: {"navigation_cue": "HOME"}},
    )

    configured_direct_predecessor = {
        "public": direct_predecessor,
        "ir": direct_predecessor_ir,
    }
    direct_envelope = source_projection_envelope(direct_report)
    original_projection_extractor = (
        _contract._extract_running_region_source_projection
    )
    dual_run = 0

    def timing_only_extractor(
        pdf_bytes: bytes, configured: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        nonlocal dual_run
        dual_run += 1
        if (
            pdf_bytes != source_projection_pdf
            or _contract.strict_json_bytes(configured)
            != _contract.strict_json_bytes(configured_direct_predecessor)
        ):
            raise SyntheticFixtureIntegrityError(
                "timing-only source-projection extractor arguments drifted"
            )
        value = deepcopy(direct_envelope)
        if dual_run == 2:
            value["source_report"]["extraction_ms"] += 0.001
        return value

    _contract._extract_running_region_source_projection = timing_only_extractor
    try:
        timing_only_authority = _contract.prepare_source_projection_authority(
            configured_direct_predecessor,
            source_projection_pdf,
        )
    finally:
        _contract._extract_running_region_source_projection = (
            original_projection_extractor
        )
    _contract.validate_source_projection_bindings(
        timing_only_authority,
        public,
        predecessor_document=direct_predecessor,
        ir_document=ir,
        predecessor_ir=direct_predecessor_ir,
    )
    timing_only_authority = None
    gc.collect()

    dual_run = 0

    def semantic_drift_extractor(
        pdf_bytes: bytes, configured: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        nonlocal dual_run
        dual_run += 1
        if (
            pdf_bytes != source_projection_pdf
            or _contract.strict_json_bytes(configured)
            != _contract.strict_json_bytes(configured_direct_predecessor)
        ):
            raise SyntheticFixtureIntegrityError(
                "semantic-drift source-projection extractor arguments drifted"
            )
        value = deepcopy(direct_envelope)
        if dual_run == 2:
            value["source_report"]["pages"][0][
                "source_character_count"
            ] = 1
            value["source_report"]["counts"][
                "source_character_count"
            ] = 1
        return value

    _contract._extract_running_region_source_projection = (
        semantic_drift_extractor
    )
    try:
        _expect_contract_rejection(
            lambda: _contract.prepare_source_projection_authority(
                configured_direct_predecessor,
                source_projection_pdf,
            ),
            "nondeterministic semantic source projection",
        )
    finally:
        _contract._extract_running_region_source_projection = (
            original_projection_extractor
        )

    extra_projection_authorities = [
        issue_source_projection_authority(
            direct_report,
            predecessor_document=direct_predecessor,
            predecessor_ir=direct_predecessor_ir,
        )
        for _index in range(
            _contract.MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES - 1
        )
    ]
    if len(_contract._ISSUED_SOURCE_PROJECTION_AUTHORITIES) != (
        _contract.MAX_LIVE_SOURCE_PROJECTION_AUTHORITIES
    ):
        raise SyntheticFixtureIntegrityError(
            "source-projection live-authority exact maximum drifted"
        )
    _expect_contract_rejection(
        lambda: issue_source_projection_authority(
            direct_report,
            predecessor_document=direct_predecessor,
            predecessor_ir=direct_predecessor_ir,
        ),
        "source-projection live-authority maximum plus one",
    )
    extra_projection_authorities.clear()
    gc.collect()
    if len(_contract._ISSUED_SOURCE_PROJECTION_AUTHORITIES) != 1:
        raise SyntheticFixtureIntegrityError(
            "temporary source-projection authorities were not weakly revoked"
        )
    direct_authority = None
    gc.collect()
    if _contract._ISSUED_SOURCE_PROJECTION_AUTHORITIES:
        raise SyntheticFixtureIntegrityError(
            "source-projection authority registry retained dead authorities"
        )

    for owner_kind in ("body", "table", "chart", "form", "outline", "note"):
        excluded_report = deepcopy(direct_report)
        excluded_candidate = excluded_report["pages"][0][
            "boundary_candidates"
        ][0]
        excluded_candidate["predecessor_type"] = owner_kind
        excluded_candidate["id"] = _contract.boundary_candidate_id(
            excluded_candidate,
            source_sha256=public["document"]["sha256"],
            physical_page_index=1,
        )
        _expect_contract_rejection(
            lambda excluded_report=excluded_report: (
                _contract.validate_source_report(
                    excluded_report, public_document=public
                )
            ),
            f"coordinated projected source owner {owner_kind}",
        )
    prior_owned_public = deepcopy(public)
    prior_owned_public["pages"][0]["items"][0]["form_semantics"] = {}
    _expect_contract_rejection(
        lambda: _contract.validate_source_report(
            direct_report, public_document=prior_owned_public
        ),
        "coordinated prior semantic source owner",
    )
    fabricated_signature = {
        **deepcopy(direct_candidate),
        "normalized_signature": "fabricated footer",
    }
    _expect_contract_rejection(
        lambda: _contract._validate_repetition_signature_binding(
            fabricated_signature,
            direct_predecessor["pages"][0]["items"][0],
            label_candidates=(),
            required=True,
        ),
        "fabricated accepted-candidate repetition signature",
    )
    navigation_candidate = {
        **deepcopy(direct_candidate),
        "source_method": "boundary_navigation",
        "boundary_band": "top",
        "raw_layout_role": "page_header",
        "bbox": {"x": 72.0, "y": 20.0, "width": 80.0, "height": 12.0, "unit": "pt"},
        "normalized_signature": "next",
    }
    if _contract.expected_candidate_role(navigation_candidate) != "navigation_top":
        raise SyntheticFixtureIntegrityError("navigation role binding drifted")
    _contract.validate_boundary_method_proof(
        navigation_candidate,
        {"navigation_cue": "NEXT"},
        page_width=612.0,
        page_height=792.0,
        label_candidate_ids=(),
    )
    _expect_contract_rejection(
        lambda: _contract.validate_boundary_method_proof(
            navigation_candidate,
            {"navigation_cue": "CONTINUE"},
            page_width=612.0,
            page_height=792.0,
            label_candidate_ids=(),
        ),
        "navigation arbitrary safe-text cue",
    )
    _expect_contract_rejection(
        lambda: _contract._validate_navigation_source_text(
            navigation_candidate,
            {"navigation_cue": "NEXT"},
            {"value": "SAFE NAVIGATION TEXT"},
        ),
        "navigation cue absent from actual source owner",
    )
    printed_candidate = {
        **deepcopy(direct_candidate),
        "source_method": "printed_label_boundary",
    }
    printed_label_candidate = {
        "id": "label-proof-1",
        "visible_text": "7",
        "normalized_label": "7",
        "bbox": {"x": 80.0, "y": 762.0, "width": 8.0, "height": 6.0, "unit": "pt"},
        "source_object_ids": list(printed_candidate["source_object_ids"]),
        "source_method": "native_printed_label",
        "confidence": {
            "scope": "deterministic_rule",
            "score": 1.0,
            "unavailable_reason": None,
        },
        "concern_codes": [],
    }
    _contract.validate_boundary_method_proof(
        printed_candidate,
        {"label_candidate_id": "label-proof-1"},
        page_width=612.0,
        page_height=792.0,
        label_candidate_ids=("label-proof-1",),
        label_candidates=(printed_label_candidate,),
    )

    # Detached native labels may use the narrowly bounded source-geometry
    # reconciliation only when exact word custody resolves one owner.  The
    # same geometry remains invalid for an attached exact-public binding.
    native_label_owner = {
        **deepcopy(printed_candidate),
        "bbox": {
            "x": 72.0,
            "y": 760.0,
            "width": 80.0,
            "height": 12.0,
            "unit": "pt",
        },
        "source_object_ids": ["word-1"],
        "disposition": "accepted",
    }

    def native_label_candidate(
        bbox: Mapping[str, Any],
        source_object_ids: Sequence[str] = ("word-1",),
    ) -> dict[str, Any]:
        value = {
            **deepcopy(printed_label_candidate),
            "bbox": dict(bbox),
            "source_object_ids": list(source_object_ids),
        }
        value["id"] = _contract.label_candidate_id(
            source_sha256=public["document"]["sha256"],
            physical_page_index=1,
            source_object_ids=value["source_object_ids"],
            bbox=value["bbox"],
        )
        return value

    native_reconciled_label = native_label_candidate(
        {"x": 70.0, "y": 763.0, "width": 10.0, "height": 6.0, "unit": "pt"}
    )
    _contract._validate_label_candidate(
        native_reconciled_label,
        source_sha256=public["document"]["sha256"],
        page_index=1,
        page_width=612.0,
        page_height=792.0,
        boundary_candidates=(native_label_owner,),
        method_proofs={},
        exact_public_binding=False,
    )
    _expect_contract_rejection(
        lambda: _contract._validate_label_candidate(
            native_reconciled_label,
            source_sha256=public["document"]["sha256"],
            page_index=1,
            page_width=612.0,
            page_height=792.0,
            boundary_candidates=(native_label_owner,),
            method_proofs={},
            exact_public_binding=True,
        ),
        "exact-public label outside strict 0.001 containment",
    )
    native_label_adversaries = (
        (
            "native label sliver overlap",
            native_label_candidate(
                {
                    "x": 151.5,
                    "y": 763.0,
                    "width": 2.0,
                    "height": 6.0,
                    "unit": "pt",
                }
            ),
            (native_label_owner,),
        ),
        (
            "native label duplicate owner",
            native_reconciled_label,
            (native_label_owner, deepcopy(native_label_owner)),
        ),
        (
            "native label disjoint source words",
            native_label_candidate(
                native_reconciled_label["bbox"], ("word-unlinked",)
            ),
            (native_label_owner,),
        ),
        (
            "native label partial source words",
            native_label_candidate(
                native_reconciled_label["bbox"], ("word-1", "word-unlinked")
            ),
            (native_label_owner,),
        ),
        (
            "native label below 0.80 candidate-area coverage",
            native_label_candidate(
                {
                    "x": 69.99,
                    "y": 763.0,
                    "width": 10.0,
                    "height": 6.0,
                    "unit": "pt",
                }
            ),
            (native_label_owner,),
        ),
        (
            "native label over 0.2-percent page-height center delta",
            native_label_candidate(
                {"x": 70.0, "y": 760.0, "width": 10.0, "height": 6.0, "unit": "pt"}
            ),
            (native_label_owner,),
        ),
    )
    for label, candidate_value, owners in native_label_adversaries:
        _expect_contract_rejection(
            lambda candidate_value=candidate_value, owners=owners: (
                _contract._validate_label_candidate(
                    candidate_value,
                    source_sha256=public["document"]["sha256"],
                    page_index=1,
                    page_width=612.0,
                    page_height=792.0,
                    boundary_candidates=owners,
                    method_proofs={},
                    exact_public_binding=False,
                )
            ),
            label,
        )

    # Exact landscape-page geometry observed in the ESG source: the native
    # label slightly exceeds its detached owner while satisfying the closed
    # 0.80 area / 0.002-page-height reconciliation rule.
    esg_owner_bbox = {
        "x": 653.834,
        "y": 453.648,
        "width": 4.366,
        "height": 3.493,
        "unit": "pt",
    }
    esg_label_bbox = {
        "x": 653.834,
        "y": 454.102,
        "width": 4.366,
        "height": 3.15,
        "unit": "pt",
    }
    esg_source_word_id = "esg-source-word-1"
    esg_candidate = {
        **deepcopy(printed_candidate),
        "public_item_id": "esg-label-owner",
        "bbox": esg_owner_bbox,
        "source_object_ids": [esg_source_word_id],
        "boundary_band": "bottom",
        "raw_layout_role": "page_footer",
    }
    esg_label_candidate = native_label_candidate(
        esg_label_bbox, (esg_source_word_id,)
    )
    esg_label_candidate.update(
        {"visible_text": "4", "normalized_label": "4"}
    )
    esg_label_candidate["id"] = _contract.label_candidate_id(
        source_sha256=public["document"]["sha256"],
        physical_page_index=1,
        source_object_ids=esg_label_candidate["source_object_ids"],
        bbox=esg_label_bbox,
    )
    esg_effective_cluster = {
        "items": [
            {
                "id": "esg-navigation",
                "presentation_index": 20,
                "bbox": {
                    "x": 590.0,
                    "y": 453.7,
                    "width": 20.0,
                    "height": 3.4,
                    "unit": "pt",
                },
                "navigation_cue": "HOME",
                "normalized_label": None,
                "claimed": False,
            },
            {
                "id": "esg-furniture",
                "presentation_index": 21,
                "bbox": {
                    "x": 620.0,
                    "y": 453.7,
                    "width": 20.0,
                    "height": 3.4,
                    "unit": "pt",
                },
                "navigation_cue": None,
                "normalized_label": None,
                "claimed": False,
            },
            {
                "id": "esg-label-owner",
                "presentation_index": 22,
                "bbox": deepcopy(esg_owner_bbox),
                "navigation_cue": None,
                "normalized_label": "4",
                "claimed": False,
            },
        ],
        "remaining_body_bboxes": [
            {
                "x": 72.0,
                "y": 72.0,
                "width": 648.0,
                "height": 360.0,
                "unit": "pt",
            }
        ],
        "candidate_cut_count": 1,
    }
    esg_method_proof = {
        "label_candidate_id": esg_label_candidate["id"],
        "effective_cluster": esg_effective_cluster,
    }
    _contract._validate_effective_extension_binding(
        esg_candidate,
        esg_method_proof,
        label_candidates=(esg_label_candidate,),
        page_width=792.0,
        page_height=612.0,
    )
    _contract.validate_boundary_method_proof(
        esg_candidate,
        esg_method_proof,
        page_width=792.0,
        page_height=612.0,
        label_candidate_ids=(esg_label_candidate["id"],),
        label_candidates=(esg_label_candidate,),
    )
    esg_label_adversaries = (
        (
            "ESG label overlap just below 0.80",
            {
                "x": 655.0004,
                "y": 453.8,
                "width": 4.0,
                "height": 3.0,
                "unit": "pt",
            },
        ),
        (
            "ESG label center delta just above 0.002 page height",
            {
                "x": 654.6,
                "y": 456.1186,
                "width": 4.0,
                "height": 1.0,
                "unit": "pt",
            },
        ),
    )
    for label, bad_bbox in esg_label_adversaries:
        bad_esg_label = native_label_candidate(
            bad_bbox, (esg_source_word_id,)
        )
        bad_esg_label.update(
            {"visible_text": "4", "normalized_label": "4"}
        )
        bad_esg_label["id"] = _contract.label_candidate_id(
            source_sha256=public["document"]["sha256"],
            physical_page_index=1,
            source_object_ids=bad_esg_label["source_object_ids"],
            bbox=bad_bbox,
        )
        bad_esg_proof = {
            "label_candidate_id": bad_esg_label["id"],
            "effective_cluster": esg_effective_cluster,
        }
        _expect_contract_rejection(
            lambda bad_esg_label=bad_esg_label,
            bad_esg_proof=bad_esg_proof: (
                _contract._validate_effective_extension_binding(
                    esg_candidate,
                    bad_esg_proof,
                    label_candidates=(bad_esg_label,),
                    page_width=792.0,
                    page_height=612.0,
                )
            ),
            f"{label} effective-extension binding",
        )
        _expect_contract_rejection(
            lambda bad_esg_label=bad_esg_label,
            bad_esg_proof=bad_esg_proof: (
                _contract.validate_boundary_method_proof(
                    esg_candidate,
                    bad_esg_proof,
                    page_width=792.0,
                    page_height=612.0,
                    label_candidate_ids=(bad_esg_label["id"],),
                    label_candidates=(bad_esg_label,),
                )
            ),
            f"{label} boundary method proof",
        )
    for label, bad_bbox in (
        (
            "printed-label below 0.80 candidate coverage",
            {
                "x": 191.999,
                "y": 762.0,
                "width": 2.0,
                "height": 6.0,
                "unit": "pt",
            },
        ),
        (
            "printed-label high coverage over 0.002 page-height center delta",
            {
                "x": 191.002,
                "y": 762.0,
                "width": 1.0,
                "height": 6.0,
                "unit": "pt",
            },
        ),
    ):
        bad_label = {**deepcopy(printed_label_candidate), "bbox": bad_bbox}
        _expect_contract_rejection(
            lambda bad_label=bad_label: _contract.validate_boundary_method_proof(
                printed_candidate,
                {"label_candidate_id": bad_label["id"]},
                page_width=612.0,
                page_height=792.0,
                label_candidate_ids=(bad_label["id"],),
                label_candidates=(bad_label,),
            ),
            label,
        )

    # Rendered visibility is bound to real PDF bytes, exact pdfplumber source
    # geometry/fills, and the contract's fixed four-pixels-per-point crop.
    import pdfplumber

    def rendered_label_source(
        pdf_bytes: bytes,
    ) -> tuple[dict[str, Any], tuple[Any, ...]]:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
            if len(document.pages) != 1:
                raise SyntheticFixtureIntegrityError(
                    "rendered-label PDF page count differs"
                )
            characters = [
                character
                for character in document.pages[0].chars
                if character.get("text") == "1"
            ]
            if len(characters) != 1:
                raise SyntheticFixtureIntegrityError(
                    "rendered-label source character differs"
                )
            character = characters[0]
            fill = character.get("non_stroking_color")
            if fill is None:
                raise SyntheticFixtureIntegrityError(
                    "rendered-label source fill is absent"
                )
            return (
                {
                    "x": float(character["x0"]),
                    "y": float(character["top"]),
                    "width": float(character["x1"] - character["x0"]),
                    "height": float(
                        character["bottom"] - character["top"]
                    ),
                    "unit": "pt",
                },
                (deepcopy(fill),),
            )

    white_label_pdf = _rendered_label_visibility_pdf(
        dark_background=False
    )
    white_label_bbox, white_label_fills = rendered_label_source(
        white_label_pdf
    )
    _expect_contract_rejection(
        lambda: _contract.validate_rendered_label_visibility(
            white_label_pdf,
            physical_page_index=1,
            candidate_visible_text="1",
            candidate_bbox=white_label_bbox,
            non_stroking_fills=white_label_fills,
        ),
        "rendered white-on-white printed label",
    )

    dark_label_pdf = _rendered_label_visibility_pdf(
        dark_background=True
    )
    dark_label_bbox, dark_label_fills = rendered_label_source(
        dark_label_pdf
    )
    dark_visibility = _contract.validate_rendered_label_visibility(
        dark_label_pdf,
        physical_page_index=1,
        candidate_visible_text="1",
        candidate_bbox=dark_label_bbox,
        non_stroking_fills=dark_label_fills,
    )
    if (
        dark_visibility is not None
        or _contract.PRINTED_LABEL_RENDER_SCALE_PX_PER_PT != 4.0
        or _contract.PRINTED_LABEL_MIN_RGB_CHANNEL_DELTA != 16
        or _contract.MAX_PRINTED_LABEL_RENDER_DIMENSION_PX != 2_048
        or _contract.MAX_PRINTED_LABEL_RENDER_PIXELS != 262_144
        or _contract.MAX_PRINTED_LABEL_NON_STROKING_FILLS != 256
        or tuple(_contract.PRINTED_LABEL_PAINTED_FILL_RENDER_MODES)
        != (0, 2, 4, 6)
        or _contract.PRINTED_LABEL_MAX_FORM_DEPTH != 8
        or _contract.MAX_PRINTED_LABEL_TEXT_OBJECTS != 256
        or _contract.MAX_PRINTED_LABEL_TEXT_OBJECT_SCAN != 10_000
        or _contract.MAX_PRINTED_LABEL_CMYK_CUSTODY_CHANNEL_DELTA != 36
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered visible printed-label gate/constants differ"
        )
    if (
        hashlib.sha256(white_label_pdf).hexdigest()
        != "beedddf908ade6d6a07f9e42fec52705e23a5c897576044efe72ec08d67ad9db"
        or hashlib.sha256(dark_label_pdf).hexdigest()
        != "ed4c8503cc0174731b990b25d297a55bd18079b6d92f9636d5c227efe3f010fb"
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered-label source PDF identity differs"
        )
    for rotation in (90, 180, 270):
        rotated_white_pdf = _rendered_label_visibility_pdf(
            dark_background=False, rotation=rotation
        )
        rotated_white_bbox, rotated_white_fills = rendered_label_source(
            rotated_white_pdf
        )
        _expect_contract_rejection(
            lambda rotated_white_pdf=rotated_white_pdf,
            rotated_white_bbox=rotated_white_bbox,
            rotated_white_fills=rotated_white_fills: (
                _contract.validate_rendered_label_visibility(
                    rotated_white_pdf,
                    physical_page_index=1,
                    candidate_visible_text="1",
                    candidate_bbox=rotated_white_bbox,
                    non_stroking_fills=rotated_white_fills,
                )
            ),
            f"rendered white-on-white label at {rotation} degrees",
        )
        rotated_dark_pdf = _rendered_label_visibility_pdf(
            dark_background=True, rotation=rotation
        )
        rotated_dark_bbox, rotated_dark_fills = rendered_label_source(
            rotated_dark_pdf
        )
        if (
            _contract.validate_rendered_label_visibility(
                rotated_dark_pdf,
                physical_page_index=1,
                candidate_visible_text="1",
                candidate_bbox=rotated_dark_bbox,
                non_stroking_fills=rotated_dark_fills,
            )
            is not None
        ):
            raise SyntheticFixtureIntegrityError(
                f"rendered rotated visible label {rotation} gate differs"
            )

    for render_mode in _contract.PRINTED_LABEL_PAINTED_FILL_RENDER_MODES:
        painted_mode_pdf = _rendered_label_visibility_pdf(
            dark_background=False,
            split_background=True,
            text_render_mode=render_mode,
        )
        painted_mode_bbox, painted_mode_fills = rendered_label_source(
            painted_mode_pdf
        )
        if (
            _contract.validate_rendered_label_visibility(
                painted_mode_pdf,
                physical_page_index=1,
                candidate_visible_text="1",
                candidate_bbox=painted_mode_bbox,
                non_stroking_fills=painted_mode_fills,
            )
            is not None
        ):
            raise SyntheticFixtureIntegrityError(
                f"rendered painted text mode {render_mode} gate differs"
            )

    for render_mode, mode_name in (
        (1, "stroke-only"),
        (3, "invisible"),
        (5, "stroke-and-clip-only"),
        (7, "clip-only"),
    ):
        unpainted_mode_pdf = _rendered_label_visibility_pdf(
            dark_background=False,
            split_background=True,
            text_render_mode=render_mode,
        )
        unpainted_mode_bbox, unpainted_mode_fills = rendered_label_source(
            unpainted_mode_pdf
        )
        _expect_contract_rejection(
            lambda unpainted_mode_pdf=unpainted_mode_pdf,
            unpainted_mode_bbox=unpainted_mode_bbox,
            unpainted_mode_fills=unpainted_mode_fills: (
                _contract.validate_rendered_label_visibility(
                    unpainted_mode_pdf,
                    physical_page_index=1,
                    candidate_visible_text="1",
                    candidate_bbox=unpainted_mode_bbox,
                    non_stroking_fills=unpainted_mode_fills,
                )
            ),
            f"rendered {mode_name} text mode {render_mode}",
        )

    transparent_label_pdf = _rendered_label_visibility_pdf(
        dark_background=False,
        split_background=True,
        transparent_fill=True,
    )
    transparent_label_bbox, transparent_label_fills = rendered_label_source(
        transparent_label_pdf
    )
    _expect_contract_rejection(
        lambda: _contract.validate_rendered_label_visibility(
            transparent_label_pdf,
            physical_page_index=1,
            candidate_visible_text="1",
            candidate_bbox=transparent_label_bbox,
            non_stroking_fills=transparent_label_fills,
        ),
        "rendered zero-alpha text-object fill",
    )

    custody_pdf = _rendered_label_visibility_pdf(
        dark_background=False, split_background=True
    )
    custody_bbox, custody_fills = rendered_label_source(custody_pdf)
    if (
        _contract.validate_rendered_label_visibility(
            custody_pdf,
            physical_page_index=1,
            candidate_visible_text="1",
            candidate_bbox=custody_bbox,
            non_stroking_fills=custody_fills,
        )
        is not None
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered split-backdrop custody positive differs"
        )
    _expect_contract_rejection(
        lambda: _contract.validate_rendered_label_visibility(
            custody_pdf,
            physical_page_index=1,
            candidate_visible_text="1",
            candidate_bbox=custody_bbox,
            non_stroking_fills=((1.0, 0.0, 0.0),),
        ),
        "rendered forged source-fill/object custody",
    )
    _expect_contract_rejection(
        lambda: _contract.validate_rendered_label_visibility(
            custody_pdf,
            physical_page_index=1,
            candidate_visible_text="2",
            candidate_bbox=custody_bbox,
            non_stroking_fills=custody_fills,
        ),
        "contrast-bearing crop without candidate-local matching text",
    )
    for malformed_visible_text, label in (
        ("", "empty candidate visible text"),
        (" 1", "untrimmed candidate visible text"),
        ("1\n", "multiline candidate visible text"),
        (
            "1" * (_contract.MAX_VISIBLE_TEXT_UTF8_BYTES + 1),
            "maximum-plus-one candidate visible text",
        ),
    ):
        _expect_contract_rejection(
            lambda malformed_visible_text=malformed_visible_text: (
                _contract.validate_rendered_label_visibility(
                    custody_pdf,
                    physical_page_index=1,
                    candidate_visible_text=malformed_visible_text,
                    candidate_bbox=custody_bbox,
                    non_stroking_fills=custody_fills,
                )
            ),
            f"rendered-label {label}",
        )

    retained_cmyk = (0.2, 0.8, 0.5, 0.0)
    cmyk_pdf = _rendered_label_visibility_pdf(
        dark_background=False,
        glyph_cmyk=retained_cmyk,
    )
    cmyk_bbox, cmyk_fills = rendered_label_source(cmyk_pdf)
    if (
        cmyk_fills != (retained_cmyk,)
        or _contract.normalize_pdf_non_stroking_fill(retained_cmyk)
        != (204, 51, 128)
        or _contract.validate_rendered_label_visibility(
            cmyk_pdf,
            physical_page_index=1,
            candidate_visible_text="1",
            candidate_bbox=cmyk_bbox,
            non_stroking_fills=cmyk_fills,
        )
        is not None
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered DeviceCMYK custody-at-36 witness differs"
        )
    cmyk_delta_37 = (0.2, 205.0 / 255.0, 0.5, 0.0)
    if _contract.normalize_pdf_non_stroking_fill(cmyk_delta_37) != (
        204,
        50,
        128,
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered DeviceCMYK custody-at-37 source differs"
        )
    for forged_cmyk, label in (
        (cmyk_delta_37, "maximum-plus-one CMYK custody delta"),
        ((0.0, 0.0, 0.0, 0.0), "gross forged CMYK custody"),
    ):
        _expect_contract_rejection(
            lambda forged_cmyk=forged_cmyk: (
                _contract.validate_rendered_label_visibility(
                    cmyk_pdf,
                    physical_page_index=1,
                    candidate_visible_text="1",
                    candidate_bbox=cmyk_bbox,
                    non_stroking_fills=(forged_cmyk,),
                )
            ),
            f"rendered {label}",
        )

    gray_239_pdf = _rendered_label_visibility_pdf(
        dark_background=False, glyph_gray_byte=239
    )
    gray_239_bbox, gray_239_fills = rendered_label_source(gray_239_pdf)
    gray_239_visibility = _contract.validate_rendered_label_visibility(
        gray_239_pdf,
        physical_page_index=1,
        candidate_visible_text="1",
        candidate_bbox=gray_239_bbox,
        non_stroking_fills=gray_239_fills,
    )
    if (
        gray_239_visibility is not None
        or _contract.normalize_pdf_non_stroking_fill(gray_239_fills[0])
        != (239, 239, 239)
    ):
        raise SyntheticFixtureIntegrityError(
            "rendered gray-239 closed-threshold gate differs"
        )
    gray_240_pdf = _rendered_label_visibility_pdf(
        dark_background=False, glyph_gray_byte=240
    )
    gray_240_bbox, gray_240_fills = rendered_label_source(gray_240_pdf)
    if _contract.normalize_pdf_non_stroking_fill(
        gray_240_fills[0]
    ) != (240, 240, 240):
        raise SyntheticFixtureIntegrityError(
            "rendered gray-240 source fill differs"
        )
    _expect_contract_rejection(
        lambda: _contract.validate_rendered_label_visibility(
            gray_240_pdf,
            physical_page_index=1,
            candidate_visible_text="1",
            candidate_bbox=gray_240_bbox,
            non_stroking_fills=gray_240_fills,
        ),
        "rendered gray-240 below-threshold printed label",
    )

    for label, fill, expected_rgb in (
        ("DeviceGray", 0.5, (128, 128, 128)),
        ("DeviceRGB", (1.0, 0.5, 0.0), (255, 128, 0)),
        ("DeviceCMYK", (0.0, 1.0, 1.0, 0.0), (255, 0, 0)),
    ):
        if _contract.normalize_pdf_non_stroking_fill(fill) != expected_rgb:
            raise SyntheticFixtureIntegrityError(
                f"rendered-label {label} normalization differs"
            )
    malformed_pdf_fills = (
        ("boolean", True),
        ("null", None),
        ("string", "1.0"),
        ("arity two", (0.0, 1.0)),
        ("arity five", (0.0, 0.0, 0.0, 0.0, 0.0)),
        ("NaN", (float("nan"),)),
        ("positive infinity", (float("inf"),)),
        ("negative component", (-0.001,)),
        ("component above one", (1.001,)),
    )
    for label, malformed_fill in malformed_pdf_fills:
        _expect_contract_rejection(
            lambda malformed_fill=malformed_fill: (
                _contract.normalize_pdf_non_stroking_fill(malformed_fill)
            ),
            f"rendered-label malformed {label} fill",
        )

    for label, arguments in (
        (
            "empty fill list",
            {
                "source_pdf_bytes": dark_label_pdf,
                "physical_page_index": 1,
                "candidate_visible_text": "1",
                "candidate_bbox": dark_label_bbox,
                "non_stroking_fills": (),
            },
        ),
        (
            "maximum-plus-one fill list",
            {
                "source_pdf_bytes": dark_label_pdf,
                "physical_page_index": 1,
                "candidate_visible_text": "1",
                "candidate_bbox": dark_label_bbox,
                "non_stroking_fills": (
                    (1.0, 1.0, 1.0),
                )
                * (_contract.MAX_PRINTED_LABEL_NON_STROKING_FILLS + 1),
            },
        ),
        (
            "malformed PDF bytes",
            {
                "source_pdf_bytes": b"%PDF-1.7\nnot-a-document",
                "physical_page_index": 1,
                "candidate_visible_text": "1",
                "candidate_bbox": dark_label_bbox,
                "non_stroking_fills": dark_label_fills,
            },
        ),
        (
            "unavailable physical page",
            {
                "source_pdf_bytes": dark_label_pdf,
                "physical_page_index": 2,
                "candidate_visible_text": "1",
                "candidate_bbox": dark_label_bbox,
                "non_stroking_fills": dark_label_fills,
            },
        ),
        (
            "out-of-page bbox",
            {
                "source_pdf_bytes": dark_label_pdf,
                "physical_page_index": 1,
                "candidate_visible_text": "1",
                "candidate_bbox": {
                    "x": 611.0,
                    "y": 0.0,
                    "width": 2.0,
                    "height": 1.0,
                    "unit": "pt",
                },
                "non_stroking_fills": dark_label_fills,
            },
        ),
        (
            "nonfinite bbox",
            {
                "source_pdf_bytes": dark_label_pdf,
                "physical_page_index": 1,
                "candidate_visible_text": "1",
                "candidate_bbox": {
                    "x": 0.0,
                    "y": 0.0,
                    "width": float("nan"),
                    "height": 1.0,
                    "unit": "pt",
                },
                "non_stroking_fills": dark_label_fills,
            },
        ),
        (
            "render width above 2048 pixels",
            {
                "source_pdf_bytes": dark_label_pdf,
                "physical_page_index": 1,
                "candidate_visible_text": "1",
                "candidate_bbox": {
                    "x": 0.0,
                    "y": 0.0,
                    "width": 512.25,
                    "height": 1.0,
                    "unit": "pt",
                },
                "non_stroking_fills": dark_label_fills,
            },
        ),
        (
            "render pixel product above 262144",
            {
                "source_pdf_bytes": dark_label_pdf,
                "physical_page_index": 1,
                "candidate_visible_text": "1",
                "candidate_bbox": {
                    "x": 0.0,
                    "y": 0.0,
                    "width": 257.0,
                    "height": 257.0,
                    "unit": "pt",
                },
                "non_stroking_fills": dark_label_fills,
            },
        ),
    ):
        _expect_contract_rejection(
            lambda arguments=arguments: (
                _contract.validate_rendered_label_visibility(**arguments)
            ),
            f"rendered-label {label}",
        )
    effective_candidate = {
        **deepcopy(direct_candidate),
        "public_item_id": "middle",
        "bbox": deepcopy(positive[1]["bbox"]),
        "source_method": "effective_boundary_cluster",
    }
    effective_proof = {
        "items": deepcopy(positive),
        "remaining_body_bboxes": deepcopy(body),
        "candidate_cut_count": 1,
    }
    _contract.validate_boundary_method_proof(
        effective_candidate,
        effective_proof,
        page_width=612.0,
        page_height=792.0,
        label_candidate_ids=(),
    )
    invoice_cluster = deepcopy(effective_proof)
    invoice_cluster["items"][2]["normalized_label"] = "INVOICE"
    _expect_contract_rejection(
        lambda: _contract.validate_effective_bottom_cluster(
            invoice_cluster["items"],
            remaining_body_bboxes=invoice_cluster["remaining_body_bboxes"],
            page_width=612.0,
            page_height=792.0,
            candidate_cut_count=invoice_cluster["candidate_cut_count"],
        ),
        "effective cluster arbitrary normalized label",
    )
    _expect_contract_rejection(
        lambda: _contract.validate_boundary_method_proof(
            effective_candidate,
            None,
            page_width=612.0,
            page_height=792.0,
            label_candidate_ids=(),
        ),
        "outer-thirty candidate without effective proof",
    )
    y600_printed = {
        **deepcopy(printed_candidate),
        "bbox": {
            "x": 72.0,
            "y": 600.0,
            "width": 80.0,
            "height": 12.0,
            "unit": "pt",
        },
    }
    y600_label = {
        **deepcopy(printed_label_candidate),
        "bbox": {
            "x": 80.0,
            "y": 602.0,
            "width": 8.0,
            "height": 6.0,
            "unit": "pt",
        },
    }
    _expect_contract_rejection(
        lambda: _contract.validate_boundary_method_proof(
            y600_printed,
            {"label_candidate_id": y600_label["id"]},
            page_width=612.0,
            page_height=792.0,
            label_candidate_ids=(y600_label["id"],),
            label_candidates=(y600_label,),
        ),
        "effective-y label without cluster proof",
    )
    center_label = {
        **deepcopy(printed_label_candidate),
        "bbox": {
            "x": 300.0,
            "y": 400.0,
            "width": 8.0,
            "height": 6.0,
            "unit": "pt",
        },
    }
    _expect_contract_rejection(
        lambda: _contract._validate_label_candidate(
            center_label,
            source_sha256=public["document"]["sha256"],
            page_index=1,
            page_width=612.0,
            page_height=792.0,
            boundary_candidates=(printed_candidate,),
            method_proofs={},
        ),
        "center-body printed label",
    )
    wrong_effective_member = {
        **deepcopy(effective_candidate),
        "public_item_id": "not-a-cluster-member",
    }
    empty_effective_proof = {**deepcopy(effective_proof), "items": []}
    malformed_effective_proof = {**deepcopy(effective_proof), "items": None}
    cue_effective_candidate = {
        **deepcopy(effective_candidate),
        "public_item_id": "nav",
        "bbox": deepcopy(positive[0]["bbox"]),
    }
    for label, candidate_value, proof_value in (
        (
            "effective-cluster wrong selected member",
            wrong_effective_member,
            effective_proof,
        ),
        ("effective-cluster empty selection", effective_candidate, empty_effective_proof),
        (
            "effective-cluster malformed selection type",
            effective_candidate,
            malformed_effective_proof,
        ),
        ("effective-cluster cue selected as furniture", cue_effective_candidate, effective_proof),
    ):
        _expect_contract_rejection(
            lambda candidate_value=candidate_value, proof_value=proof_value: (
                _contract.validate_boundary_method_proof(
                    candidate_value,
                    proof_value,
                    page_width=612.0,
                    page_height=792.0,
                    label_candidate_ids=(),
                )
            ),
            label,
        )
    top_printed_candidate = {
        **deepcopy(printed_candidate),
        "boundary_band": "top",
        "raw_layout_role": None,
        "bbox": {"x": 72.0, "y": 20.0, "width": 80.0, "height": 12.0, "unit": "pt"},
    }
    top_composite_label = {
        **deepcopy(printed_label_candidate),
        "id": "label-proof-top-composite",
        "visible_text": "Page 7 of 10",
        "normalized_label": "7 of 10",
        "bbox": {"x": 80.0, "y": 22.0, "width": 50.0, "height": 6.0, "unit": "pt"},
    }
    if _contract.expected_candidate_role(top_printed_candidate) != "header":
        raise SyntheticFixtureIntegrityError("top printed-label role drifted")
    _contract.validate_boundary_method_proof(
        top_printed_candidate,
        {"label_candidate_id": top_composite_label["id"]},
        page_width=612.0,
        page_height=792.0,
        label_candidate_ids=(top_composite_label["id"],),
        label_candidates=(top_composite_label,),
    )
    trusted_top_candidate = {
        **top_printed_candidate,
        "raw_layout_role": "page_header",
    }
    trusted_top_owner = {
        "id": trusted_top_candidate["public_item_id"],
        "type": "text",
        "label": "page_header",
        "value": top_composite_label["visible_text"],
    }
    _contract._validate_raw_layout_role_binding(
        trusted_top_candidate,
        trusted_top_owner,
        predecessor_ir={
            "elements": [
                {
                    "id": trusted_top_candidate["element_id"],
                    "type": "text",
                    "label": "page_header",
                }
            ]
        },
    )
    _expect_contract_rejection(
        lambda: _contract._validate_raw_layout_role_binding(
            trusted_top_candidate,
            {
                "id": trusted_top_candidate["public_item_id"],
                "type": "text",
                "value": top_composite_label["visible_text"],
            },
            predecessor_ir={
                "elements": [
                    {
                        "id": trusted_top_candidate["element_id"],
                        "type": "text",
                    }
                ]
            },
        ),
        "raw layout role asserted over plain text owner",
    )
    untrusted_top_bare = {
        **deepcopy(top_composite_label),
        "id": "label-proof-top-bare",
        "visible_text": "7",
        "normalized_label": "7",
    }
    _expect_contract_rejection(
        lambda: _contract.validate_boundary_method_proof(
            top_printed_candidate,
            {"label_candidate_id": untrusted_top_bare["id"]},
            page_width=612.0,
            page_height=792.0,
            label_candidate_ids=(untrusted_top_bare["id"],),
            label_candidates=(untrusted_top_bare,),
        ),
        "untrusted bare top printed label",
    )
    for label, bad_candidate in (
        (
            "trusted cross-band role",
            {**deepcopy(direct_candidate), "boundary_band": "top"},
        ),
        (
            "effective-cluster top role",
            {
                **deepcopy(direct_candidate),
                "source_method": "effective_boundary_cluster",
                "boundary_band": "top",
                "raw_layout_role": "page_header",
            },
        ),
    ):
        _expect_contract_rejection(
            lambda bad_candidate=bad_candidate: _contract.expected_candidate_role(
                bad_candidate
            ),
            label,
        )

    def install_canonical_page_views(page: dict[str, Any]) -> None:
        included = [
            block
            for block in page["blocks"]
            if block["omission_reason"] is None
        ]
        by_id = {block["id"]: block for block in included}

        def render(block_ids: Sequence[str], field: str) -> str:
            values = [
                str(by_id[block_id][field]).strip()
                for block_id in block_ids
                if str(by_id[block_id][field]).strip()
            ]
            return "\n\n".join(values).rstrip() + "\n" if values else ""

        scoped = {scope: [] for scope in ("body", "header", "footer")}
        full_ids: list[str] = []
        for block in included:
            full_ids.append(block["id"])
            scoped[block["scope"]].append(block["id"])
        for view_name, block_ids in {"full": full_ids, **scoped}.items():
            page[view_name] = {
                "block_ids": block_ids,
                "markdown": render(block_ids, "markdown"),
                "text": render(block_ids, "text"),
            }

    # Full effective-cut commitment: body + cue/furniture/label cluster are
    # contiguous and identical across public, predecessor, IR, and canonical
    # surfaces.  Each proof member has its own accepted method/candidate.
    effective_public = deepcopy(public)
    effective_ir = deepcopy(ir)
    effective_source_sha256 = effective_public["document"]["sha256"]
    effective_cluster = deepcopy(effective_proof)
    effective_body_item = {
        "id": "effective-body",
        "type": "text",
        "reading_order": 0,
        "value": "BODY",
        "md": "BODY",
        "bbox": deepcopy(body[0]),
        "source": "native",
        "confidence": 1.0,
    }
    effective_values = {
        "nav": "HOME",
        "middle": "LEGAL FOOTER",
        "label": "80",
    }
    effective_methods = {
        "nav": "boundary_navigation",
        "middle": "effective_boundary_cluster",
        "label": "printed_label_boundary",
    }
    effective_roles = {
        "nav": "navigation_bottom",
        "middle": "footer",
        "label": "footer",
    }
    predecessor_effective_items: list[dict[str, Any]] = [
        deepcopy(effective_body_item)
    ]
    projected_effective_items: list[dict[str, Any]] = [
        deepcopy(effective_body_item)
    ]
    effective_candidates: list[dict[str, Any]] = []
    effective_elements: list[dict[str, Any]] = [
        {
            "id": "effective-body-element",
            "page_id": "page-1",
            "type": "text",
            "reading_order": 0,
            "value": "BODY",
            "markdown": "BODY",
            "bbox_ids": ["effective-body-bbox"],
            "evidence_ids": ["effective-body-evidence"],
            "presentation_role": "primary",
        }
    ]
    effective_bboxes: list[dict[str, Any]] = [
        {
            "id": "effective-body-bbox",
            "coordinate_system_id": "coord-1",
            **{
                key: effective_body_item["bbox"][key]
                for key in ("x", "y", "width", "height")
            },
        }
    ]
    effective_evidence: list[dict[str, Any]] = [
        {
            "id": "effective-body-evidence",
            "element_id": "effective-body-element",
            "bbox_id": "effective-body-bbox",
        }
    ]
    effective_blocks: list[dict[str, Any]] = [
        {
            "id": "effective-body-block",
            "page_id": "page-1",
            "primary_element_id": "effective-body-element",
            "primary_element_type": "text",
            "scope": "body",
            "markdown": "BODY",
            "text": "BODY",
            "contributing_element_ids": ["effective-body-element"],
            "relationship_ids": [],
            "excluded_contributions": [],
            "omission_reason": None,
            "suppressed_by_element_id": None,
        }
    ]
    for item_offset, proof_item in enumerate(positive, start=1):
        item_id = proof_item["id"]
        element_id = f"effective-{item_id}-element"
        bbox_id = f"effective-{item_id}-bbox"
        evidence_id = f"effective-{item_id}-evidence"
        block_id = f"effective-{item_id}-block"
        predecessor_item = {
            "id": item_id,
            "type": "text",
            "reading_order": proof_item["presentation_index"],
            "value": effective_values[item_id],
            "md": effective_values[item_id],
            "bbox": deepcopy(proof_item["bbox"]),
            "source": "native",
            "confidence": 1.0,
        }
        role = effective_roles[item_id]
        descriptor = {
            "id": _contract.stable_id(
                "running-region",
                POLICY_ID,
                effective_source_sha256,
                1,
                element_id,
                bbox_id,
                role,
            ),
            "page_id": "page-1",
            "physical_page_index": 1,
            "role": role,
            "canonical_scope": "footer",
            "source_public_item_id": item_id,
            "source_public_path": ["pages", 0, "items", item_offset],
            "source_element_id": element_id,
            "predecessor_type": "text",
            "predecessor_item_sha256": _contract.sha256_json(
                predecessor_item
            ),
            "bbox_id": bbox_id,
            "bbox": deepcopy(proof_item["bbox"]),
            "evidence_ids": [evidence_id],
            "source_object_ids": [f"effective-{item_id}-word-1"],
            "source_method": effective_methods[item_id],
            "repetition_group_id": None,
            "repetition_page_indexes": [],
            "confidence": {
                "scope": "deterministic_rule",
                "score": 1.0,
                "unavailable_reason": None,
            },
            "concern_codes": [],
            "canonical_block_id": block_id,
        }
        projected_item = {
            **deepcopy(predecessor_item),
            "type": _contract.ROLE_TYPE_SCOPE[role][0],
            "layout_running_region_projected": True,
            "running_region_policy": POLICY_ID,
            "running_region": descriptor,
        }
        candidate = {
            "id": "pending",
            "public_item_id": item_id,
            "public_path": ["pages", 0, "items", item_offset],
            "element_id": element_id,
            "predecessor_type": "text",
            "bbox": deepcopy(proof_item["bbox"]),
            "bbox_id": bbox_id,
            "evidence_ids": [evidence_id],
            "source_object_ids": [f"effective-{item_id}-word-1"],
            "raw_layout_role": None,
            "normalized_signature": " ".join(
                effective_values[item_id].casefold().split()
            ),
            "boundary_band": "bottom",
            "source_method": effective_methods[item_id],
            "confidence": deepcopy(descriptor["confidence"]),
            "concern_codes": [],
            "disposition": "accepted",
        }
        candidate["id"] = _contract.boundary_candidate_id(
            candidate,
            source_sha256=effective_source_sha256,
            physical_page_index=1,
        )
        predecessor_effective_items.append(predecessor_item)
        projected_effective_items.append(projected_item)
        effective_candidates.append(candidate)
        effective_elements.append(
            {
                "id": element_id,
                "page_id": "page-1",
                "source_public_item_id": item_id,
                "type": projected_item["type"],
                "reading_order": proof_item["presentation_index"],
                "value": effective_values[item_id],
                "markdown": effective_values[item_id],
                "bbox_ids": [bbox_id],
                "evidence_ids": [evidence_id],
                "presentation_role": "primary",
                "running_region": deepcopy(descriptor),
            }
        )
        effective_bboxes.append(
            {
                "id": bbox_id,
                "coordinate_system_id": "coord-1",
                **{
                    key: proof_item["bbox"][key]
                    for key in ("x", "y", "width", "height")
                },
            }
        )
        effective_evidence.append(
            {
                "id": evidence_id,
                "element_id": element_id,
                "bbox_id": bbox_id,
            }
        )
        effective_blocks.append(
            {
                "id": block_id,
                "page_id": "page-1",
                "primary_element_id": element_id,
                "primary_element_type": projected_item["type"],
                "scope": "footer",
                "markdown": effective_values[item_id],
                "text": effective_values[item_id],
                "contributing_element_ids": [element_id],
                "relationship_ids": [],
                "excluded_contributions": [],
                "omission_reason": None,
                "suppressed_by_element_id": None,
            }
        )
    effective_label_bbox = {
        "x": 505.0,
        "y": 652.0,
        "width": 6.0,
        "height": 6.0,
        "unit": "pt",
    }
    effective_label_id = _contract.label_candidate_id(
        source_sha256=effective_source_sha256,
        physical_page_index=1,
        source_object_ids=["effective-label-word-1"],
        bbox=effective_label_bbox,
    )
    effective_label = {
        "id": effective_label_id,
        "visible_text": "80",
        "normalized_label": "80",
        "bbox": effective_label_bbox,
        "source_object_ids": ["effective-label-word-1"],
        "source_method": "native_printed_label",
        "confidence": {
            "scope": "deterministic_rule",
            "score": 1.0,
            "unavailable_reason": None,
        },
        "concern_codes": [],
    }
    effective_identity = deepcopy(detached_detected)
    effective_identity.update(
        {
            "detected_printed_label": "80",
            "visible_text": "80",
            "display_label": "80",
            "evidence_bbox": deepcopy(effective_label_bbox),
        }
    )
    effective_identity["evidence_source"]["evidence_ids"] = [
        effective_label_id
    ]
    effective_identity["evidence_source"]["source_object_ids"] = [
        "effective-label-word-1"
    ]
    effective_public["pages"][0]["items"] = projected_effective_items
    effective_public["pages"][0]["page_identity"] = deepcopy(
        effective_identity
    )
    effective_canonical_page = effective_public["canonical_presentation"][
        "pages"
    ][0]
    effective_canonical_page["page_identity"] = deepcopy(effective_identity)
    effective_canonical_page["blocks"] = effective_blocks
    install_canonical_page_views(effective_canonical_page)
    effective_summary = effective_public["processing"]["running_regions"]
    effective_summary.update(
        {
            "detected_label_count": 1,
            "legacy_fallback_count": 0,
            "candidate_count": 3,
            "running_region_count": 3,
            "header_count": 0,
            "footer_count": 2,
            "top_navigation_count": 0,
            "bottom_navigation_count": 1,
        }
    )
    effective_ir.update(
        {
            "pages": [
                {
                    "id": "page-1",
                    "page_index": 1,
                    "element_ids": [
                        element["id"] for element in effective_elements
                    ],
                    "presentation_element_ids": [
                        element["id"] for element in effective_elements
                    ],
                    "page_identity": deepcopy(effective_identity),
                }
            ],
            "elements": effective_elements,
            "bboxes": effective_bboxes,
            "evidence": effective_evidence,
        }
    )
    effective_predecessor, effective_predecessor_ir = direct_predecessors_for(
        effective_public, effective_ir
    )
    assert effective_predecessor_ir is not None
    if effective_predecessor["pages"][0]["items"] != predecessor_effective_items:
        raise SyntheticFixtureIntegrityError(
            "effective predecessor public sequence drifted"
        )
    effective_report = source_report_for(
        effective_public,
        label_candidates=((effective_label,),),
        boundary_candidates=(tuple(effective_candidates),),
    )
    candidate_by_owner = {
        candidate["public_item_id"]: candidate
        for candidate in effective_candidates
    }
    effective_method_proofs = {
        candidate_by_owner["nav"]["id"]: {
            "navigation_cue": "HOME",
            "effective_cluster": deepcopy(effective_cluster),
        },
        candidate_by_owner["middle"]["id"]: deepcopy(effective_cluster),
        candidate_by_owner["label"]["id"]: {
            "label_candidate_id": effective_label_id,
            "effective_cluster": deepcopy(effective_cluster),
        },
    }
    validate_source_projection(
        effective_report,
        effective_public,
        predecessor_document=effective_predecessor,
        ir_document=effective_ir,
        predecessor_ir=effective_predecessor_ir,
        method_proofs=effective_method_proofs,
    )

    unresolved_cluster_public = deepcopy(effective_public)
    unresolved_cluster_ir = deepcopy(effective_ir)
    for item_id in ("nav", "label"):
        item = next(
            value
            for value in unresolved_cluster_public["pages"][0]["items"]
            if value["id"] == item_id
        )
        descriptor = item["running_region"]
        for key in _contract.RUNNING_REGION_SIDECAR_FIELDS:
            item.pop(key)
        item["type"] = descriptor["predecessor_type"]
        ir_element = next(
            value
            for value in unresolved_cluster_ir["elements"]
            if value["id"] == descriptor["source_element_id"]
        )
        ir_element.pop("running_region")
        ir_element["type"] = descriptor["predecessor_type"]
        block = next(
            value
            for value in unresolved_cluster_public[
                "canonical_presentation"
            ]["pages"][0]["blocks"]
            if value["id"] == descriptor["canonical_block_id"]
        )
        block["primary_element_type"] = descriptor["predecessor_type"]
        block["scope"] = "body"
    fallback_identity = deepcopy(public["pages"][0]["page_identity"])
    unresolved_cluster_public["pages"][0]["page_identity"] = deepcopy(
        fallback_identity
    )
    unresolved_canonical_page = unresolved_cluster_public[
        "canonical_presentation"
    ]["pages"][0]
    unresolved_canonical_page["page_identity"] = deepcopy(fallback_identity)
    install_canonical_page_views(unresolved_canonical_page)
    unresolved_cluster_ir["pages"][0]["page_identity"] = deepcopy(
        fallback_identity
    )
    unresolved_summary = unresolved_cluster_public["processing"][
        "running_regions"
    ]
    unresolved_summary.update(
        {
            "detected_label_count": 0,
            "legacy_fallback_count": 1,
            "candidate_count": 1,
            "running_region_count": 1,
            "footer_count": 1,
            "bottom_navigation_count": 0,
        }
    )
    unresolved_report = source_report_for(
        unresolved_cluster_public,
        label_candidates=((),),
        boundary_candidates=((candidate_by_owner["middle"],),),
    )
    _expect_contract_rejection(
        lambda: validate_source_projection(
            unresolved_report,
            unresolved_cluster_public,
            predecessor_document=effective_predecessor,
            ir_document=unresolved_cluster_ir,
            predecessor_ir=effective_predecessor_ir,
            method_proofs={
                candidate_by_owner["middle"]["id"]: deepcopy(
                    effective_cluster
                )
            },
        ),
        "effective cluster unresolved cue and label members",
    )

    validate_source_projection(
        direct_report,
        public,
        predecessor_document=direct_predecessor,
        ir_document=ir,
        predecessor_ir=direct_predecessor_ir,
    )

    # Execute state/replay semantics over the complete committed public + IR +
    # canonical witness, rather than only over transition-name toy payloads.
    actual_predecessor_bundle = {
        "public": deepcopy(direct_predecessor),
        "ir": deepcopy(direct_predecessor_ir),
    }
    actual_projected_bundle = {
        "public": deepcopy(public),
        "ir": deepcopy(ir),
    }
    actual_fallback_bundle = {
        "public": deepcopy(zero_region_public),
        "ir": deepcopy(zero_region_ir),
    }
    initial_form_processing = {
        "extraction_ms": 0.25,
        "projection_ms": 0.5,
        "total_ms": 0.75,
    }
    terminal_form_processing = {
        "extraction_ms": 0.125,
        "projection_ms": 0.25,
        "total_ms": 0.375,
    }
    initial_outline_processing = {
        "policy_id": _contract.OUTLINE_POLICY_ID,
        "status": "projected",
        "reason": None,
        "group_count": 1,
        "node_count": 2,
        "relationship_count": 2,
        "concern_count": 0,
        "extraction_ms": 0.375,
        "projection_ms": 0.625,
        "total_ms": 1.0,
    }
    terminal_outline_processing = {
        **{
            field: initial_outline_processing[field]
            for field in (
                "policy_id",
                "status",
                "reason",
                "group_count",
                "node_count",
                "relationship_count",
                "concern_count",
            )
        },
        "extraction_ms": 0.125,
        "projection_ms": 0.25,
        "total_ms": 0.375,
    }
    prior_stage_public_state = {
        "layout_forms_projected": True,
        "form_semantics": {
            "group_id": "form-group-1",
            "field_element_ids": ["element-1"],
            "relationship_ids": ["form-relationship-1"],
        },
        "layout_outline_structure_projected": True,
        "outline_structure": {
            "group_id": "outline-group-1",
            "member_element_ids": ["element-1", "outline-child-1"],
            "relationship_ids": [
                "outline-relationship-1",
                "outline-relationship-2",
            ],
        },
    }
    prior_stage_ir_state = {
        "form_semantics": deepcopy(prior_stage_public_state["form_semantics"]),
        "outline_structure": deepcopy(
            prior_stage_public_state["outline_structure"]
        ),
    }
    for state in (
        actual_predecessor_bundle,
        actual_projected_bundle,
        actual_fallback_bundle,
    ):
        state["public"]["pages"][0]["items"][0].update(
            deepcopy(prior_stage_public_state)
        )
        state["ir"]["elements"][0].update(deepcopy(prior_stage_ir_state))
        processing = state["public"].setdefault("processing", {})
        processing["form_semantics"] = deepcopy(initial_form_processing)
        processing["outline_structure"] = deepcopy(initial_outline_processing)
    stage_bound_predecessor_owner = actual_predecessor_bundle["public"]["pages"][
        0
    ]["items"][0]
    stage_bound_predecessor_hash = _contract.predecessor_item_sha256(
        stage_bound_predecessor_owner, "text"
    )
    stage_bound_descriptor = actual_projected_bundle["public"]["pages"][0][
        "items"
    ][0]["running_region"]
    stage_bound_descriptor["predecessor_item_sha256"] = (
        stage_bound_predecessor_hash
    )
    actual_projected_bundle["ir"]["elements"][0]["running_region"] = deepcopy(
        stage_bound_descriptor
    )
    for state in (
        actual_predecessor_bundle,
        actual_projected_bundle,
        actual_fallback_bundle,
    ):
        state["ir"]["elements"][0]["properties"] = {
            "legacy_item": deepcopy(stage_bound_predecessor_owner),
            "source_position": 0,
        }
    body_owner = {
        "id": "body-item-1",
        "type": "text",
        "label": "body",
        "reading_order": 1,
        "value": "BODYCONTENT",
        "md": "BODYCONTENT",
        "source": "native",
        "bbox": {
            "x": 72.0,
            "y": 120.0,
            "width": 120.0,
            "height": 14.0,
            "unit": "pt",
        },
        **deepcopy(prior_stage_public_state),
    }
    body_block = {
        "id": "body-block-1",
        "page_id": "page-1",
        "primary_element_id": "body-element-1",
        "primary_element_type": "text",
        "scope": "body",
        "markdown": body_owner["md"],
        "text": body_owner["value"],
        "contributing_element_ids": ["body-element-1"],
        "relationship_ids": [
            "form-relationship-1",
            "outline-relationship-1",
            "outline-relationship-2",
        ],
        "excluded_contributions": [],
        "omission_reason": None,
        "suppressed_by_element_id": None,
    }
    body_element = {
        "id": "body-element-1",
        "page_id": "page-1",
        "type": "text",
        "label": "body",
        "value": body_owner["value"],
        "markdown": body_owner["md"],
        "bbox_ids": ["body-bbox-1"],
        "evidence_ids": ["body-evidence-1"],
        "presentation_role": "primary",
        "properties": {
            "legacy_item": deepcopy(body_owner),
            "source_position": 1,
        },
        **deepcopy(prior_stage_ir_state),
    }
    body_bbox = {
        "id": "body-bbox-1",
        "coordinate_system_id": "coord-1",
        "x": 72.0,
        "y": 120.0,
        "width": 120.0,
        "height": 14.0,
    }
    body_evidence = {
        "id": "body-evidence-1",
        "element_id": "body-element-1",
        "bbox_id": "body-bbox-1",
    }
    duplicate_body_owner = deepcopy(body_owner)
    duplicate_body_owner.update(
        {
            "id": "body-item-duplicate-1",
            "reading_order": 2,
            "bbox": {
                "x": 240.0,
                "y": 120.0,
                "width": 120.0,
                "height": 14.0,
                "unit": "pt",
            },
        }
    )
    for prior_stage_key in (
        "layout_forms_projected",
        "form_semantics",
        "layout_outline_structure_projected",
        "outline_structure",
    ):
        duplicate_body_owner.pop(prior_stage_key, None)
    duplicate_body_block = deepcopy(body_block)
    duplicate_body_block.update(
        {
            "id": "body-block-duplicate-1",
            "primary_element_id": "body-element-duplicate-1",
            "contributing_element_ids": ["body-element-duplicate-1"],
            "relationship_ids": [],
        }
    )
    duplicate_body_element = {
        "id": "body-element-duplicate-1",
        "page_id": "page-1",
        "type": "text",
        "label": "body",
        "value": duplicate_body_owner["value"],
        "markdown": duplicate_body_owner["md"],
        "bbox_ids": ["body-bbox-duplicate-1"],
        "evidence_ids": ["body-evidence-duplicate-1"],
        "presentation_role": "primary",
        "properties": {
            "legacy_item": deepcopy(duplicate_body_owner),
            "source_position": 2,
        },
    }
    duplicate_body_bbox = {
        "id": "body-bbox-duplicate-1",
        "coordinate_system_id": "coord-1",
        "x": 240.0,
        "y": 120.0,
        "width": 120.0,
        "height": 14.0,
    }
    duplicate_body_evidence = {
        "id": "body-evidence-duplicate-1",
        "element_id": "body-element-duplicate-1",
        "bbox_id": "body-bbox-duplicate-1",
    }
    for state in (
        actual_predecessor_bundle,
        actual_projected_bundle,
        actual_fallback_bundle,
    ):
        state["public"]["pages"][0]["items"].extend(
            (deepcopy(body_owner), deepcopy(duplicate_body_owner))
        )
        canonical_page = state["public"]["canonical_presentation"]["pages"][0]
        canonical_page["blocks"].extend(
            (deepcopy(body_block), deepcopy(duplicate_body_block))
        )
        install_canonical_page_views(canonical_page)
        state["ir"]["elements"].extend(
            (deepcopy(body_element), deepcopy(duplicate_body_element))
        )
        state["ir"]["bboxes"].extend(
            (deepcopy(body_bbox), deepcopy(duplicate_body_bbox))
        )
        state["ir"]["evidence"].extend(
            (deepcopy(body_evidence), deepcopy(duplicate_body_evidence))
        )
        state["ir"]["pages"][0]["element_ids"].extend(
            ("body-element-1", "body-element-duplicate-1")
        )
        state["ir"]["pages"][0]["presentation_element_ids"].extend(
            ("body-element-1", "body-element-duplicate-1")
        )
    flag_off_hook_calls: list[str] = []

    def forbidden_flag_off_hook() -> None:
        flag_off_hook_calls.append("called")

    flag_off_result = _contract.execute_flag_off_witness(
        _contract.prepare_flag_off_witness(actual_predecessor_bundle),
        feature_hooks=(
            forbidden_flag_off_hook,
            forbidden_flag_off_hook,
            forbidden_flag_off_hook,
        ),
    )
    if (
        flag_off_result.committed is not True
        or flag_off_hook_calls
        or flag_off_result.events != ("flag_off", "return_predecessor")
        or _contract.strict_json_bytes(flag_off_result.payload)
        != _contract.strict_json_bytes(actual_predecessor_bundle)
    ):
        raise SyntheticFixtureIntegrityError(
            "actual public/IR flag-off identity drifted"
        )
    _expect_contract_rejection(
        lambda: _contract.execute_flag_off_witness(
            {"pages": [deepcopy(empty_page)]}
        ),
        "marker-only flag-off state",
    )

    predecessor_bundle_bytes = _contract.strict_json_bytes(
        actual_predecessor_bundle
    )
    projected_bundle_bytes = _contract.strict_json_bytes(
        actual_projected_bundle
    )

    def actual_projector(bundle: Mapping[str, Any]) -> Mapping[str, Any]:
        serialized = _contract.strict_json_bytes(bundle)
        if serialized == predecessor_bundle_bytes:
            return deepcopy(actual_projected_bundle)
        if serialized == projected_bundle_bytes:
            projected_public = bundle.get("public")
            projected_ir = bundle.get("ir")
            if not isinstance(projected_public, Mapping) or not isinstance(
                projected_ir, Mapping
            ):
                raise _contract.ReadinessContractError(
                    "idempotent projected bundle differs"
                )
            _contract.validate_ir_bindings(
                projected_ir, public_document=projected_public
            )
            return deepcopy(actual_projected_bundle)
        raise _contract.ReadinessContractError(
            "idempotent input is outside the predecessor/fixed point"
        )

    first_projection, second_projection = _contract.IdempotenceWitness(
        predecessor=actual_predecessor_bundle,
        projector=actual_projector,
    ).execute()
    if (
        _contract.strict_json_bytes(first_projection) != projected_bundle_bytes
        or _contract.strict_json_bytes(second_projection)
        != projected_bundle_bytes
    ):
        raise SyntheticFixtureIntegrityError(
            "actual public/IR idempotent fixed point drifted"
        )

    replay_drift_bundle = deepcopy(actual_projected_bundle)
    replay_drift_summary = replay_drift_bundle["public"]["processing"][
        "running_regions"
    ]
    replay_drift_summary["projection_ms"] = round(
        replay_drift_summary["projection_ms"] + 0.001, 3
    )
    replay_drift_summary["total_ms"] = round(
        replay_drift_summary["extraction_ms"]
        + replay_drift_summary["projection_ms"],
        3,
    )
    _contract.validate_ir_bindings(
        replay_drift_bundle["ir"],
        public_document=replay_drift_bundle["public"],
    )

    def non_idempotent_actual_projector(
        bundle: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if _contract.strict_json_bytes(bundle) == predecessor_bundle_bytes:
            return deepcopy(actual_projected_bundle)
        return deepcopy(replay_drift_bundle)

    _expect_contract_rejection(
        lambda: _contract.IdempotenceWitness(
            predecessor=actual_predecessor_bundle,
            projector=non_idempotent_actual_projector,
        ).execute(),
        "non-idempotent full public/IR/canonical projection",
    )

    successful_transaction = _contract.execute_transaction_witness(
        actual_predecessor_bundle,
        projected_state=actual_projected_bundle,
        outcome="success",
    )
    if (
        successful_transaction.committed is not True
        or successful_transaction.events[-1] != "commit"
        or _contract.strict_json_bytes(successful_transaction.payload)
        != projected_bundle_bytes
    ):
        raise SyntheticFixtureIntegrityError(
            "actual public/IR/canonical transaction commit drifted"
        )

    extra_surface_projection = {
        **actual_projected_bundle,
        "identity_hashes": {"public": "0" * 64},
    }
    _expect_contract_rejection(
        lambda: _contract.execute_transaction_witness(
            actual_predecessor_bundle,
            projected_state=extra_surface_projection,
            outcome="success",
        ),
        "transaction arbitrary identity side surface",
    )

    page_rollback = _contract.execute_transaction_witness(
        actual_predecessor_bundle,
        projected_state=actual_projected_bundle,
        outcome="page_failure",
        fallback_state=actual_fallback_bundle,
    )
    if (
        page_rollback.committed is not True
        or _contract.strict_json_bytes(page_rollback.payload)
        != _contract.strict_json_bytes(actual_fallback_bundle)
        or page_rollback.events[-2:]
        != ("discard_page_projection", "commit_fallback_state")
    ):
        raise SyntheticFixtureIntegrityError(
            "actual page fallback public/IR/canonical custody drifted"
        )
    fallback_ir_drift = deepcopy(actual_fallback_bundle)
    fallback_ir_drift["ir"]["elements"][0]["label"] = "fabricated fallback"
    _expect_contract_rejection(
        lambda: _contract.execute_transaction_witness(
            actual_predecessor_bundle,
            projected_state=actual_projected_bundle,
            outcome="page_failure",
            fallback_state=fallback_ir_drift,
        ),
        "page fallback IR closure drift",
    )

    def require_actual_atomic_rollback(
        malformed_staged_bundle: Mapping[str, Any],
        *,
        outcome: Literal["document_failure", "canonical_failure"],
        label: str,
    ) -> None:
        rollback = _contract.execute_transaction_witness(
            actual_predecessor_bundle,
            projected_state=malformed_staged_bundle,
            outcome=outcome,
        )
        expected_public = deepcopy(actual_predecessor_bundle["public"])
        expected_public.setdefault("processing", {})["running_regions"] = {
            "policy_id": POLICY_ID,
            "status": "failed_closed",
            "reason": "running_region_projection_failed_closed",
            **{
                key: 0
                for key in _contract.PROCESSING_SUMMARY_FIELDS[3:16]
            },
            "concern_count": 1,
            "extraction_ms": 0.0,
            "projection_ms": 0.0,
            "total_ms": 0.0,
        }
        expected_public["running_region_concerns"] = [
            {
                "code": (
                    "running_region_canonical_custody_invalid"
                    if outcome == "canonical_failure"
                    else "running_region_projection_failed_closed"
                )
            }
        ]
        expected_payload = {
            "public": expected_public,
            "ir": deepcopy(actual_predecessor_bundle["ir"]),
        }
        if (
            rollback.committed is not False
            or rollback.events
            != (
                "snapshot_document",
                "snapshot_page",
                "stage_detached_projection",
                (
                    "canonical_dry_run"
                    if outcome == "canonical_failure"
                    else "validate_document"
                ),
                "restore_document",
                "emit_content_free_concern",
            )
            or _contract.strict_json_bytes(rollback.payload)
            != _contract.strict_json_bytes(expected_payload)
        ):
            raise SyntheticFixtureIntegrityError(
                f"actual {label} did not restore the exact document snapshot"
            )

    failure_envelopes: list[
        tuple[
            str,
            Literal["document_failure", "canonical_failure"],
            dict[str, Any],
        ]
    ] = []
    missing_running_summary = deepcopy(actual_projected_bundle)
    missing_running_summary["public"]["processing"].pop("running_regions")
    failure_envelopes.append(
        ("missing running summary", "document_failure", missing_running_summary)
    )
    missing_canonical_block_id = deepcopy(actual_projected_bundle)
    missing_canonical_block_id["public"]["canonical_presentation"]["pages"][
        0
    ]["blocks"][0].pop("id")
    failure_envelopes.append(
        (
            "missing canonical block key",
            "canonical_failure",
            missing_canonical_block_id,
        )
    )
    for surface, outcome in (
        ("public", "document_failure"),
        ("canonical", "canonical_failure"),
        ("IR", "document_failure"),
    ):
        non_object = deepcopy(actual_projected_bundle)
        missing = deepcopy(actual_projected_bundle)
        if surface == "public":
            non_object["public"]["pages"][0] = None
            missing["public"].pop("pages")
        elif surface == "canonical":
            non_object["public"]["canonical_presentation"]["pages"][0] = None
            missing["public"]["canonical_presentation"].pop("pages")
        else:
            non_object["ir"]["pages"][0] = None
            missing["ir"].pop("pages")
        failure_envelopes.extend(
            (
                (f"non-object {surface} page envelope", outcome, non_object),
                (f"missing {surface} page envelope", outcome, missing),
            )
        )
    for label, outcome, malformed_staged_bundle in failure_envelopes:
        require_actual_atomic_rollback(
            malformed_staged_bundle,
            outcome=outcome,
            label=label,
        )

    stripped_actual = _contract.strip_complete_running_region_sidecars(
        public,
        predecessor_document=direct_predecessor,
        ir_document=ir,
        predecessor_ir=direct_predecessor_ir,
    )
    if _contract.strict_json_bytes(stripped_actual) != _contract.strict_json_bytes(
        direct_predecessor
    ):
        raise SyntheticFixtureIntegrityError(
            "actual terminal strip predecessor identity drifted"
        )
    # The replay itself re-runs the complete source/public/IR/canonical binder.
    validate_source_projection(
        direct_report,
        public,
        predecessor_document=direct_predecessor,
        ir_document=ir,
        predecessor_ir=direct_predecessor_ir,
    )
    terminal_pass_summary = deepcopy(public["processing"]["running_regions"])
    terminal_pass_summary.update(
        {"extraction_ms": 0.25, "projection_ms": 0.5, "total_ms": 0.75}
    )
    replayed_actual_bundle = deepcopy(actual_projected_bundle)
    replayed_actual_bundle["public"]["processing"]["running_regions"] = (
        _contract.combine_terminal_processing_summaries(
            public["processing"]["running_regions"], terminal_pass_summary
        )
    )
    replayed_bundle_bytes = _contract.strict_json_bytes(replayed_actual_bundle)
    replay_success = _contract.TerminalReplayWitness(
        configured_predecessor=actual_predecessor_bundle,
        replay_state_before=actual_projected_bundle,
        replay_state_after=replayed_actual_bundle,
        terminal_processing_summary=terminal_pass_summary,
        forms_enabled=False,
        outlines_enabled=False,
    ).execute()
    if (
        replay_success.committed is not True
        or replay_success.events
        != _contract.terminal_reentry_order(
            forms_enabled=False, outlines_enabled=False
        )
        or _contract.strict_json_bytes(replay_success.payload)
        != replayed_bundle_bytes
    ):
        raise SyntheticFixtureIntegrityError(
            "actual terminal replay success drifted"
        )
    doubled_extraction_replay = deepcopy(replayed_actual_bundle)
    doubled_extraction_summary = doubled_extraction_replay["public"][
        "processing"
    ]["running_regions"]
    doubled_extraction_summary["extraction_ms"] = round(
        doubled_extraction_summary["extraction_ms"] * 2, 3
    )
    doubled_extraction_summary["total_ms"] = round(
        doubled_extraction_summary["extraction_ms"]
        + doubled_extraction_summary["projection_ms"],
        3,
    )
    wrong_projection_replay = deepcopy(replayed_actual_bundle)
    wrong_projection_summary = wrong_projection_replay["public"]["processing"][
        "running_regions"
    ]
    wrong_projection_summary["projection_ms"] = round(
        wrong_projection_summary["projection_ms"] + 0.001, 3
    )
    wrong_projection_summary["total_ms"] = round(
        wrong_projection_summary["extraction_ms"]
        + wrong_projection_summary["projection_ms"],
        3,
    )
    wrong_total_replay = deepcopy(replayed_actual_bundle)
    wrong_total_replay["public"]["processing"]["running_regions"][
        "total_ms"
    ] = round(
        wrong_total_replay["public"]["processing"]["running_regions"][
            "total_ms"
        ]
        + 0.001,
        3,
    )
    for label, invalid_timing_state in (
        ("doubled extraction", doubled_extraction_replay),
        ("wrong accumulated projection", wrong_projection_replay),
        ("wrong total algebra", wrong_total_replay),
    ):
        timing_rollback = _contract.TerminalReplayWitness(
            configured_predecessor=actual_predecessor_bundle,
            replay_state_before=actual_projected_bundle,
            replay_state_after=invalid_timing_state,
            terminal_processing_summary=terminal_pass_summary,
            forms_enabled=False,
            outlines_enabled=False,
        ).execute()
        if (
            timing_rollback.committed
            or _contract.strict_json_bytes(timing_rollback.payload)
            != projected_bundle_bytes
        ):
            raise SyntheticFixtureIntegrityError(
                f"terminal {label} did not restore the full snapshot"
            )

    original_owner = direct_predecessor["pages"][0]["items"][0]
    original_text = original_owner["value"]
    body_original_text = body_owner["value"]
    selected_text = "RUN NING FOOTER"
    body_selected_text = "BODY CONTENT"
    source_pdf_bytes = _source_alignment_pdf()
    source_sha256 = hashlib.sha256(source_pdf_bytes).hexdigest()
    if source_sha256 != public["document"]["sha256"]:
        raise SyntheticFixtureIntegrityError(
            "source-alignment PDF hash differs from the state witness"
        )
    alignment_evidence_authority = (
        _contract.prepare_source_alignment_evidence(
            actual_predecessor_bundle, source_pdf_bytes
        )
    )
    source_alignment_evidence = json.loads(
        alignment_evidence_authority.evidence_json
    )
    _expect_contract_rejection(
        lambda: _contract.prepare_source_alignment_evidence(
            actual_predecessor_bundle, source_alignment_evidence
        ),
        "arbitrary mapping source-alignment authority",
    )
    _expect_contract_rejection(
        lambda: _contract._ValidatedSourceAlignmentEvidence(),
        "direct source-alignment authority construction",
    )
    _expect_contract_rejection(
        lambda: copy(alignment_evidence_authority),
        "copied source-alignment authority",
    )
    _expect_contract_rejection(
        lambda: _contract.prepare_source_alignment_evidence(
            actual_predecessor_bundle, source_pdf_bytes + b"wrong-source"
        ),
        "wrong source-alignment PDF hash",
    )

    original_source_extractor = (
        _contract._extract_phase02_source_text_evidence
    )
    extraction_run = 0

    class _SyntheticSourceReport:
        def __init__(self, payload: Mapping[str, Any]) -> None:
            self._payload = deepcopy(dict(payload))

        def to_dict(self) -> dict[str, Any]:
            return deepcopy(self._payload)

    def alternating_source_extractor(pdf_bytes: bytes) -> Any:
        nonlocal extraction_run
        extraction_run += 1
        payload = original_source_extractor(pdf_bytes).to_dict()
        if extraction_run % 2 == 0:
            payload["diagnostics"] = [
                {"code": "synthetic_nondeterministic_extraction"}
            ]
        return _SyntheticSourceReport(payload)

    _contract._extract_phase02_source_text_evidence = (
        alternating_source_extractor
    )
    try:
        _expect_contract_rejection(
            lambda: _contract.prepare_source_alignment_evidence(
                actual_predecessor_bundle, source_pdf_bytes
            ),
            "nondeterministic fixed source extraction",
        )
    finally:
        _contract._extract_phase02_source_text_evidence = (
            original_source_extractor
        )

    extra_authorities = [
        _contract.prepare_source_alignment_evidence(
            actual_predecessor_bundle, source_pdf_bytes
        )
        for _index in range(
            _contract.MAX_LIVE_SOURCE_ALIGNMENT_AUTHORITIES - 1
        )
    ]
    _expect_contract_rejection(
        lambda: _contract.prepare_source_alignment_evidence(
            actual_predecessor_bundle, source_pdf_bytes
        ),
        "source-alignment live-authority registry cap",
    )
    extra_authorities.clear()
    gc.collect()
    if len(_contract._ISSUED_SOURCE_ALIGNMENT_AUTHORITIES) != 1:
        raise SyntheticFixtureIntegrityError(
            "temporary source-alignment authorities were not revoked"
        )
    source_pages = source_alignment_evidence.get("pages")
    if (
        not isinstance(source_pages, list)
        or len(source_pages) != 1
        or not isinstance(source_pages[0], Mapping)
    ):
        raise SyntheticFixtureIntegrityError(
            "production source-alignment page evidence differs"
        )
    source_page = source_pages[0]
    source_page_lines = source_page.get("lines")
    source_page_characters = source_page.get("characters")
    if not isinstance(source_page_lines, list) or not isinstance(
        source_page_characters, list
    ):
        raise SyntheticFixtureIntegrityError(
            "production source-alignment line/character evidence differs"
        )

    def exact_source_line(text: str) -> Mapping[str, Any]:
        matches = [
            line
            for line in source_page_lines
            if isinstance(line, Mapping) and line.get("text") == text
        ]
        if len(matches) != 1:
            raise SyntheticFixtureIntegrityError(
                f"production source-alignment line {text!r} differs"
            )
        return matches[0]

    source_line = exact_source_line(selected_text)
    body_source_line = exact_source_line(body_selected_text)
    source_characters_by_id = {
        character["id"]: character
        for character in source_page_characters
        if isinstance(character, Mapping)
        and isinstance(character.get("id"), str)
    }
    running_source_character_ids = list(
        source_line["source_character_ids"]
    )
    body_source_character_ids = list(
        body_source_line["source_character_ids"]
    )
    if (
        any(
            identifier not in source_characters_by_id
            for identifier in (
                *running_source_character_ids,
                *body_source_character_ids,
            )
        )
        or source_line["type1_evidence_ids"]
        or body_source_line["type1_evidence_ids"]
    ):
        raise SyntheticFixtureIntegrityError(
            "production source-alignment character custody differs"
        )
    body_source_characters = [
        source_characters_by_id[identifier]
        for identifier in body_source_character_ids
    ]
    source_line_id = source_line["id"]
    body_source_line_id = body_source_line["id"]
    body_owner_bbox = body_owner["bbox"]
    alignment_selection = {
        "id": _contract.source_alignment_selection_id(
            source_sha256=public["document"]["sha256"],
            page_index=1,
            owner_id=original_owner["id"],
            original_text=original_text,
            selected_text=selected_text,
        ),
        "page_index": 1,
        "owner_id": original_owner["id"],
        "owner_type": original_owner["type"],
        "owner_bbox": deepcopy(original_owner["bbox"]),
        "original_text": original_text,
        "selected_text": selected_text,
        "selected_source": "pdf_source_text",
        "source_line_ids": [source_line_id],
        "source_character_ids": running_source_character_ids,
        "type1_mapping_ids": [],
        "source_roles": [],
        "method": "pdfium_source_space",
        "checks": {
            "finite_geometry": True,
            "single_page": True,
            "printable_unicode": True,
            "bounded_candidate": True,
            "source_hash_bound": True,
            "encoded_u0020": True,
            "space_geometry": True,
        },
        "terminal_reason": "selected_source_safe_candidate",
        "rejected_ocr_alternative": None,
    }
    body_alignment_selection = {
        "id": _contract.source_alignment_selection_id(
            source_sha256=public["document"]["sha256"],
            page_index=1,
            owner_id=body_owner["id"],
            original_text=body_original_text,
            selected_text=body_selected_text,
        ),
        "page_index": 1,
        "owner_id": body_owner["id"],
        "owner_type": body_owner["type"],
        "owner_bbox": deepcopy(body_owner_bbox),
        "original_text": body_original_text,
        "selected_text": body_selected_text,
        "selected_source": "pdf_source_text",
        "source_line_ids": [body_source_line_id],
        "source_character_ids": [
            character["id"] for character in body_source_characters
        ],
        "type1_mapping_ids": [],
        "source_roles": [],
        "method": "pdfium_source_space",
        "checks": {
            "finite_geometry": True,
            "single_page": True,
            "printable_unicode": True,
            "bounded_candidate": True,
            "source_hash_bound": True,
            "encoded_u0020": True,
            "space_geometry": True,
        },
        "terminal_reason": "selected_source_safe_candidate",
        "rejected_ocr_alternative": None,
    }
    alignment_summary = {
        "schema_version": "1.0",
        "policy_id": _contract.SOURCE_ALIGNMENT_POLICY_ID,
        "source_sha256": public["document"]["sha256"],
        "status": "selected",
        "considered_count": 2,
        "selected_count": 2,
        "unchanged_count": 0,
        "unresolved_count": 0,
        "selections": [
            deepcopy(alignment_selection),
            deepcopy(body_alignment_selection),
        ],
        "concerns": [],
        "elapsed_ms": 0.125,
    }
    alignment_trace = {
        "schema_version": "1.0",
        "policy_id": _contract.SOURCE_ALIGNMENT_POLICY_ID,
        "source_sha256": public["document"]["sha256"],
        "selection_id": alignment_selection["id"],
        **{
            field: deepcopy(alignment_selection[field])
            for field in (
                "original_text",
                "selected_text",
                "selected_source",
                "source_line_ids",
                "source_character_ids",
                "type1_mapping_ids",
                "source_roles",
                "method",
                "checks",
                "terminal_reason",
                "rejected_ocr_alternative",
            )
        },
    }
    body_alignment_trace = {
        "schema_version": "1.0",
        "policy_id": _contract.SOURCE_ALIGNMENT_POLICY_ID,
        "source_sha256": public["document"]["sha256"],
        "selection_id": body_alignment_selection["id"],
        **{
            field: deepcopy(body_alignment_selection[field])
            for field in (
                "original_text",
                "selected_text",
                "selected_source",
                "source_line_ids",
                "source_character_ids",
                "type1_mapping_ids",
                "source_roles",
                "method",
                "checks",
                "terminal_reason",
                "rejected_ocr_alternative",
            )
        },
    }
    aligned_predecessor_bundle = deepcopy(actual_predecessor_bundle)
    aligned_predecessor_public = aligned_predecessor_bundle["public"]
    aligned_predecessor_owner = aligned_predecessor_public["pages"][0]["items"][0]
    aligned_predecessor_owner["value"] = selected_text
    aligned_predecessor_owner["md"] = selected_text
    aligned_predecessor_owner["source_alignment"] = deepcopy(alignment_trace)
    aligned_predecessor_body = aligned_predecessor_public["pages"][0]["items"][1]
    aligned_predecessor_body["value"] = body_selected_text
    aligned_predecessor_body["md"] = body_selected_text
    aligned_predecessor_body["source"] = "native"
    aligned_predecessor_body["source_alignment"] = deepcopy(
        body_alignment_trace
    )
    aligned_predecessor_processing = aligned_predecessor_public.setdefault(
        "processing", {}
    )
    aligned_predecessor_processing["source_text_alignment"] = deepcopy(
        alignment_summary
    )
    aligned_predecessor_processing["form_semantics"] = (
        _contract.combine_terminal_form_processing_summaries(
            initial_form_processing, terminal_form_processing
        )
    )
    aligned_predecessor_processing["outline_structure"] = (
        _contract.combine_terminal_outline_processing_summaries(
            initial_outline_processing, terminal_outline_processing
        )
    )
    aligned_predecessor_block = aligned_predecessor_public[
        "canonical_presentation"
    ]["pages"][0]["blocks"][0]
    aligned_predecessor_block["text"] = selected_text
    aligned_predecessor_block["markdown"] = selected_text
    aligned_predecessor_body_block = aligned_predecessor_public[
        "canonical_presentation"
    ]["pages"][0]["blocks"][1]
    aligned_predecessor_body_block["text"] = body_selected_text
    aligned_predecessor_body_block["markdown"] = body_selected_text
    install_canonical_page_views(
        aligned_predecessor_public["canonical_presentation"]["pages"][0]
    )
    aligned_predecessor_body_element = next(
        element
        for element in aligned_predecessor_bundle["ir"]["elements"]
        if element["id"] == "body-element-1"
    )
    aligned_predecessor_body_element["value"] = body_selected_text
    aligned_predecessor_body_element["markdown"] = body_selected_text
    aligned_predecessor_body_element["properties"]["legacy_item"] = deepcopy(
        aligned_predecessor_body
    )
    aligned_predecessor_direct_element = next(
        element
        for element in aligned_predecessor_bundle["ir"]["elements"]
        if element["id"] == "element-1"
    )
    aligned_predecessor_direct_element["properties"][
        "legacy_item"
    ] = deepcopy(aligned_predecessor_owner)

    aligned_replay_bundle = deepcopy(replayed_actual_bundle)
    aligned_replay_public = aligned_replay_bundle["public"]
    aligned_replay_owner = aligned_replay_public["pages"][0]["items"][0]
    aligned_replay_owner["value"] = selected_text
    aligned_replay_owner["md"] = selected_text
    aligned_replay_owner["source_alignment"] = deepcopy(alignment_trace)
    aligned_replay_body = aligned_replay_public["pages"][0]["items"][1]
    aligned_replay_body["value"] = body_selected_text
    aligned_replay_body["md"] = body_selected_text
    aligned_replay_body["source"] = "native"
    aligned_replay_body["source_alignment"] = deepcopy(body_alignment_trace)
    aligned_descriptor = aligned_replay_owner["running_region"]
    aligned_descriptor["predecessor_item_sha256"] = (
        _contract.predecessor_item_sha256(
            aligned_replay_owner, aligned_descriptor["predecessor_type"]
        )
    )
    aligned_replay_public["processing"]["source_text_alignment"] = deepcopy(
        alignment_summary
    )
    aligned_replay_public["processing"]["form_semantics"] = deepcopy(
        aligned_predecessor_processing["form_semantics"]
    )
    aligned_replay_public["processing"]["outline_structure"] = deepcopy(
        aligned_predecessor_processing["outline_structure"]
    )
    aligned_replay_block = aligned_replay_public["canonical_presentation"][
        "pages"
    ][0]["blocks"][0]
    aligned_replay_block["text"] = selected_text
    aligned_replay_block["markdown"] = selected_text
    aligned_replay_body_block = aligned_replay_public[
        "canonical_presentation"
    ]["pages"][0]["blocks"][1]
    aligned_replay_body_block["text"] = body_selected_text
    aligned_replay_body_block["markdown"] = body_selected_text
    install_canonical_page_views(
        aligned_replay_public["canonical_presentation"]["pages"][0]
    )
    aligned_replay_bundle["ir"]["elements"][0]["running_region"] = deepcopy(
        aligned_descriptor
    )
    aligned_replay_body_element = next(
        element
        for element in aligned_replay_bundle["ir"]["elements"]
        if element["id"] == "body-element-1"
    )
    aligned_replay_body_element["value"] = body_selected_text
    aligned_replay_body_element["markdown"] = body_selected_text
    aligned_replay_body_element["properties"]["legacy_item"] = deepcopy(
        aligned_replay_body
    )
    aligned_replay_bundle["ir"]["elements"][0]["properties"][
        "legacy_item"
    ] = deepcopy(aligned_predecessor_owner)
    if (
        aligned_descriptor["predecessor_item_sha256"]
        == public["pages"][0]["items"][0]["running_region"][
            "predecessor_item_sha256"
        ]
    ):
        raise SyntheticFixtureIntegrityError(
            "alignment-authorized owner hash did not establish a new witness"
        )
    aligned_replay_success = _contract.TerminalReplayWitness(
        configured_predecessor=actual_predecessor_bundle,
        replay_state_before=actual_projected_bundle,
        aligned_predecessor=aligned_predecessor_bundle,
        alignment_summary=alignment_summary,
        alignment_evidence=alignment_evidence_authority,
        replay_state_after=aligned_replay_bundle,
        terminal_processing_summary=terminal_pass_summary,
        forms_enabled=True,
        outlines_enabled=True,
        terminal_form_processing_summary=terminal_form_processing,
        terminal_outline_processing_summary=terminal_outline_processing,
    ).execute()
    if (
        not aligned_replay_success.committed
        or aligned_replay_success.events
        != _contract.terminal_reentry_order(
            forms_enabled=True, outlines_enabled=True
        )
        or _contract.strict_json_bytes(aligned_replay_success.payload)
        != _contract.strict_json_bytes(aligned_replay_bundle)
    ):
        raise SyntheticFixtureIntegrityError(
            "alignment-authorized full-state replay did not commit"
        )
    configured_duplicate_surfaces = (
        actual_predecessor_bundle["public"]["pages"][0]["items"][2],
        actual_predecessor_bundle["public"]["canonical_presentation"][
            "pages"
        ][0]["blocks"][2],
        next(
            element
            for element in actual_predecessor_bundle["ir"]["elements"]
            if element["id"] == "body-element-duplicate-1"
        ),
    )
    aligned_duplicate_surfaces = (
        aligned_replay_success.payload["public"]["pages"][0]["items"][2],
        aligned_replay_success.payload["public"]["canonical_presentation"][
            "pages"
        ][0]["blocks"][2],
        next(
            element
            for element in aligned_replay_success.payload["ir"]["elements"]
            if element["id"] == "body-element-duplicate-1"
        ),
    )
    if _contract.strict_json_bytes(
        aligned_duplicate_surfaces
    ) != _contract.strict_json_bytes(configured_duplicate_surfaces):
        raise SyntheticFixtureIntegrityError(
            "identical unselected owner changed during ID-bound alignment"
        )

    def require_alignment_rollback(
        label: str,
        *,
        aligned_predecessor: Mapping[str, Any] = aligned_predecessor_bundle,
        summary: Mapping[str, Any] = alignment_summary,
        replay_after: Mapping[str, Any] = aligned_replay_bundle,
    ) -> None:
        rejected = _contract.TerminalReplayWitness(
            configured_predecessor=actual_predecessor_bundle,
            replay_state_before=actual_projected_bundle,
            aligned_predecessor=aligned_predecessor,
            alignment_summary=summary,
            alignment_evidence=alignment_evidence_authority,
            replay_state_after=replay_after,
            terminal_processing_summary=terminal_pass_summary,
            forms_enabled=True,
            outlines_enabled=True,
            terminal_form_processing_summary=terminal_form_processing,
            terminal_outline_processing_summary=terminal_outline_processing,
        ).execute()
        if (
            rejected.committed
            or _contract.strict_json_bytes(rejected.payload)
            != projected_bundle_bytes
        ):
            raise SyntheticFixtureIntegrityError(
                f"terminal alignment {label} did not restore the snapshot"
            )

    forged_selected_text = "B ODYCONTENT"
    forged_summary = deepcopy(alignment_summary)
    forged_selection = forged_summary["selections"][1]
    forged_selection["selected_text"] = forged_selected_text
    forged_selection["id"] = _contract.source_alignment_selection_id(
        source_sha256=public["document"]["sha256"],
        page_index=1,
        owner_id=body_owner["id"],
        original_text=body_original_text,
        selected_text=forged_selected_text,
    )
    forged_trace = {
        "schema_version": "1.0",
        "policy_id": _contract.SOURCE_ALIGNMENT_POLICY_ID,
        "source_sha256": public["document"]["sha256"],
        "selection_id": forged_selection["id"],
        **{
            field: deepcopy(forged_selection[field])
            for field in (
                "original_text",
                "selected_text",
                "selected_source",
                "source_line_ids",
                "source_character_ids",
                "type1_mapping_ids",
                "source_roles",
                "method",
                "checks",
                "terminal_reason",
                "rejected_ocr_alternative",
            )
        },
    }
    forged_predecessor = deepcopy(aligned_predecessor_bundle)
    forged_predecessor_public = forged_predecessor["public"]
    forged_predecessor_public["processing"]["source_text_alignment"] = deepcopy(
        forged_summary
    )
    forged_body = forged_predecessor_public["pages"][0]["items"][1]
    forged_body["value"] = forged_selected_text
    forged_body["md"] = forged_selected_text
    forged_body["source_alignment"] = deepcopy(forged_trace)
    forged_body_block = forged_predecessor_public["canonical_presentation"][
        "pages"
    ][0]["blocks"][1]
    forged_body_block["text"] = forged_selected_text
    forged_body_block["markdown"] = forged_selected_text
    install_canonical_page_views(
        forged_predecessor_public["canonical_presentation"]["pages"][0]
    )
    forged_body_element = next(
        element
        for element in forged_predecessor["ir"]["elements"]
        if element["id"] == "body-element-1"
    )
    forged_body_element["value"] = forged_selected_text
    forged_body_element["markdown"] = forged_selected_text
    forged_body_element["properties"]["legacy_item"] = deepcopy(
        forged_body
    )
    forged_replay = deepcopy(aligned_replay_bundle)
    forged_replay_public = forged_replay["public"]
    forged_replay_public["processing"]["source_text_alignment"] = deepcopy(
        forged_summary
    )
    forged_replay_body = forged_replay_public["pages"][0]["items"][1]
    forged_replay_body["value"] = forged_selected_text
    forged_replay_body["md"] = forged_selected_text
    forged_replay_body["source_alignment"] = deepcopy(forged_trace)
    forged_replay_block = forged_replay_public["canonical_presentation"]["pages"][
        0
    ]["blocks"][1]
    forged_replay_block["text"] = forged_selected_text
    forged_replay_block["markdown"] = forged_selected_text
    install_canonical_page_views(
        forged_replay_public["canonical_presentation"]["pages"][0]
    )
    forged_replay_element = next(
        element
        for element in forged_replay["ir"]["elements"]
        if element["id"] == "body-element-1"
    )
    forged_replay_element["value"] = forged_selected_text
    forged_replay_element["markdown"] = forged_selected_text
    forged_replay_element["properties"]["legacy_item"] = deepcopy(
        forged_replay_body
    )
    require_alignment_rollback(
        "internally consistent content absent from frozen evidence",
        aligned_predecessor=forged_predecessor,
        summary=forged_summary,
        replay_after=forged_replay,
    )

    for label, mutate in (
        (
            "fabricated selected source",
            lambda selection: selection.__setitem__(
                "selected_source", "fabricated-source"
            ),
        ),
        (
            "fabricated method",
            lambda selection: selection.update(
                {"method": "trust-me", "checks": {"invented": True}}
            ),
        ),
        (
            "fabricated terminal reason",
            lambda selection: selection.__setitem__(
                "terminal_reason", "because"
            ),
        ),
        (
            "nonexistent line evidence",
            lambda selection: selection.__setitem__(
                "source_line_ids", ["missing-source-line"]
            ),
        ),
        (
            "fabricated source role",
            lambda selection: selection.__setitem__("source_roles", [{}]),
        ),
        (
            "invented checks",
            lambda selection: selection.__setitem__(
                "checks", {**selection["checks"], "invented": True}
            ),
        ),
        (
            "fabricated rejected OCR",
            lambda selection: selection.__setitem__(
                "rejected_ocr_alternative",
                {
                    "text": "fake",
                    "source": "ocr",
                    "bbox": deepcopy(selection["owner_bbox"]),
                    "confidence": 1.0,
                    "reason": "strict_source_subrange",
                },
            ),
        ),
    ):
        forged_metadata_summary = deepcopy(alignment_summary)
        mutate(forged_metadata_summary["selections"][0])
        require_alignment_rollback(
            label, summary=forged_metadata_summary
        )

    replay_adversaries: list[tuple[str, dict[str, Any]]] = []
    page_label_drift = deepcopy(aligned_replay_bundle)
    page_label_drift["public"]["pages"][0]["page_identity"][
        "display_label"
    ] = "forged"
    replay_adversaries.append(("page identity drift", page_label_drift))
    source_evidence_drift = deepcopy(aligned_replay_bundle)
    source_evidence_drift["public"]["pages"][0]["page_identity"][
        "evidence_source"
    ]["source_object_ids"] = ["forged-source-object"]
    replay_adversaries.append(
        ("page identity source evidence drift", source_evidence_drift)
    )
    prior_form_drift = deepcopy(aligned_replay_bundle)
    prior_form_drift["public"]["pages"][0]["items"][1]["form_semantics"][
        "group_id"
    ] = "forged-form-group"
    replay_adversaries.append(("form graph drift", prior_form_drift))
    prior_outline_drift = deepcopy(aligned_replay_bundle)
    prior_outline_drift["ir"]["elements"][1]["outline_structure"][
        "group_id"
    ] = "forged-outline-group"
    replay_adversaries.append(("outline graph drift", prior_outline_drift))
    form_timing_drift = deepcopy(aligned_replay_bundle)
    form_timing_drift["public"]["processing"]["form_semantics"][
        "projection_ms"
    ] += 0.001
    form_timing_drift["public"]["processing"]["form_semantics"][
        "total_ms"
    ] += 0.001
    replay_adversaries.append(("form timing drift", form_timing_drift))
    outline_timing_drift = deepcopy(aligned_replay_bundle)
    outline_timing_drift["public"]["processing"]["outline_structure"][
        "projection_ms"
    ] += 0.001
    outline_timing_drift["public"]["processing"]["outline_structure"][
        "total_ms"
    ] += 0.001
    replay_adversaries.append(("outline timing drift", outline_timing_drift))
    malformed_replay_key = deepcopy(aligned_replay_bundle)
    malformed_replay_key["public"]["canonical_presentation"]["pages"][0][
        "blocks"
    ][0].pop("id")
    replay_adversaries.append(("missing canonical key", malformed_replay_key))
    malformed_replay_unicode = deepcopy(aligned_replay_bundle)
    malformed_replay_unicode["public"]["pages"][0]["items"][1][
        "value"
    ] = "\ud800"
    replay_adversaries.append(
        ("unpaired-surrogate replay", malformed_replay_unicode)
    )
    for label, adversarial_replay in replay_adversaries:
        require_alignment_rollback(label, replay_after=adversarial_replay)

    unauthorized_alignment = _contract.TerminalReplayWitness(
        configured_predecessor=actual_predecessor_bundle,
        replay_state_before=actual_projected_bundle,
        replay_state_after=aligned_replay_bundle,
        terminal_processing_summary=terminal_pass_summary,
        forms_enabled=False,
        outlines_enabled=False,
    ).execute()
    mismatched_alignment_summary = deepcopy(alignment_summary)
    mismatched_alignment_summary["selections"][0]["owner_id"] = "missing-owner"
    mismatched_alignment = _contract.TerminalReplayWitness(
        configured_predecessor=actual_predecessor_bundle,
        replay_state_before=actual_projected_bundle,
        aligned_predecessor=aligned_predecessor_bundle,
        alignment_summary=mismatched_alignment_summary,
        alignment_evidence=alignment_evidence_authority,
        replay_state_after=aligned_replay_bundle,
        terminal_processing_summary=terminal_pass_summary,
        forms_enabled=True,
        outlines_enabled=True,
        terminal_form_processing_summary=terminal_form_processing,
        terminal_outline_processing_summary=terminal_outline_processing,
    ).execute()
    for label, rejected_alignment in (
        ("missing authorization", unauthorized_alignment),
        ("mismatched authorization", mismatched_alignment),
    ):
        if (
            rejected_alignment.committed
            or _contract.strict_json_bytes(rejected_alignment.payload)
            != projected_bundle_bytes
        ):
            raise SyntheticFixtureIntegrityError(
                f"terminal alignment {label} did not restore the snapshot"
            )

    for label, fail_at, replay_after in (
        ("wrong accumulated timing", "none", replay_drift_bundle),
        ("alignment failure", "alignment", replayed_actual_bundle),
        ("running replay failure", "running_replay", replayed_actual_bundle),
        ("identity failure", "identity", replayed_actual_bundle),
        ("canonical failure", "canonical", replayed_actual_bundle),
    ):
        replay_failure = _contract.TerminalReplayWitness(
            configured_predecessor=actual_predecessor_bundle,
            replay_state_before=actual_projected_bundle,
            replay_state_after=replay_after,
            terminal_processing_summary=terminal_pass_summary,
            forms_enabled=False,
            outlines_enabled=False,
            fail_at=fail_at,
        ).execute()
        if (
            replay_failure.committed is not False
            or replay_failure.events[-1]
            != "restore_pre_alignment_document"
            or _contract.strict_json_bytes(replay_failure.payload)
            != projected_bundle_bytes
        ):
            raise SyntheticFixtureIntegrityError(
                f"actual terminal replay {label} rollback drifted"
            )

    malformed_canonical_replay = deepcopy(replayed_actual_bundle)
    malformed_canonical_replay["public"]["canonical_presentation"]["pages"][0][
        "full"
    ]["text"] = "fabricated canonical replay\n"
    canonical_validation_rollback = _contract.TerminalReplayWitness(
        configured_predecessor=actual_predecessor_bundle,
        replay_state_before=actual_projected_bundle,
        replay_state_after=malformed_canonical_replay,
        terminal_processing_summary=terminal_pass_summary,
        forms_enabled=False,
        outlines_enabled=False,
    ).execute()
    if (
        canonical_validation_rollback.committed is not False
        or _contract.strict_json_bytes(canonical_validation_rollback.payload)
        != projected_bundle_bytes
    ):
        raise SyntheticFixtureIntegrityError(
            "malformed canonical replay was not atomically restored"
        )

    timing_mismatch_report = deepcopy(direct_report)
    timing_mismatch_report["extraction_ms"] = 1.001
    _expect_contract_rejection(
        lambda: validate_source_projection(
            timing_mismatch_report,
            public,
            predecessor_document=direct_predecessor,
            ir_document=ir,
            predecessor_ir=direct_predecessor_ir,
        ),
        "source/processing extraction timing mismatch",
    )
    missing_predecessor_authority = issue_source_projection_authority(
        direct_report,
        predecessor_document=direct_predecessor,
        predecessor_ir=direct_predecessor_ir,
    )
    _expect_contract_rejection(
        lambda: _contract.validate_source_projection_bindings(
            missing_predecessor_authority,
            public,
            predecessor_document=None,  # type: ignore[arg-type]
            ir_document=ir,
            predecessor_ir=direct_predecessor_ir,
        ),
        "authoritative projection missing configured predecessor",
    )
    missing_predecessor_authority = None
    wrong_configured_predecessor = deepcopy(direct_predecessor)
    wrong_configured_predecessor["unrelated"] = "drift"
    _expect_contract_rejection(
        lambda: validate_source_projection(
            direct_report,
            public,
            predecessor_document=wrong_configured_predecessor,
            ir_document=ir,
            predecessor_ir=direct_predecessor_ir,
        ),
        "authoritative projection wrong configured predecessor",
    )
    accepted_candidate_omitted_public = deepcopy(direct_predecessor)
    accepted_candidate_omitted_public["pages"][0]["page_identity"] = deepcopy(
        public["pages"][0]["page_identity"]
    )
    accepted_candidate_omitted_public["canonical_presentation"]["pages"][0][
        "page_identity"
    ] = deepcopy(public["pages"][0]["page_identity"])
    omitted_summary = deepcopy(public["processing"]["running_regions"])
    omitted_summary["running_region_count"] = 0
    omitted_summary["footer_count"] = 0
    accepted_candidate_omitted_public["processing"] = {
        "running_regions": omitted_summary
    }
    _expect_contract_rejection(
        lambda: validate_source_projection(
            direct_report,
            accepted_candidate_omitted_public,
            predecessor_document=direct_predecessor,
            ir_document=zero_region_ir,
            predecessor_ir=direct_predecessor_ir,
        ),
        "accepted singleton boundary candidate omitted",
    )
    expected_legacy_source_object_id = (
        f"configured-predecessor:{public['document']['sha256']}:page:1:page_label"
    )
    if public["pages"][0]["page_identity"]["evidence_source"][
        "source_object_ids"
    ] != [expected_legacy_source_object_id]:
        raise SyntheticFixtureIntegrityError(
            "source-scoped legacy fallback evidence witness drifted"
        )

    def coordinated_fallback_source_mutation(
        source_object_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        mutated_public = deepcopy(public)
        mutated_ir = deepcopy(ir)
        for identity in (
            mutated_public["pages"][0]["page_identity"],
            mutated_public["canonical_presentation"]["pages"][0]["page_identity"],
            mutated_ir["pages"][0]["page_identity"],
        ):
            identity["evidence_source"]["source_object_ids"] = [source_object_id]
        return mutated_public, mutated_ir

    fabricated_fallback_public, fabricated_fallback_ir = (
        coordinated_fallback_source_mutation(
            f"{expected_legacy_source_object_id}:fabricated"
        )
    )
    case_named_fallback_public, case_named_fallback_ir = (
        coordinated_fallback_source_mutation(
            "configured-predecessor:synthetic-case-name:page:1:page_label"
        )
    )
    for label, bad_public, bad_ir in (
        (
            "fabricated legacy fallback source object",
            fabricated_fallback_public,
            fabricated_fallback_ir,
        ),
        (
            "case-named legacy fallback source object",
            case_named_fallback_public,
            case_named_fallback_ir,
        ),
    ):
        _expect_contract_rejection(
            lambda bad_public=bad_public, bad_ir=bad_ir: (
                validate_source_projection(
                    direct_report,
                    bad_public,
                    predecessor_document=direct_predecessor,
                    ir_document=bad_ir,
                    predecessor_ir=direct_predecessor_ir,
                )
            ),
            label,
        )

    legacy_bbox_alias_public = deepcopy(public)
    legacy_bbox_alias_ir = deepcopy(ir)
    alias_item = legacy_bbox_alias_public["pages"][0]["items"][0]
    canonical_alias_bbox = dict(alias_item["bbox"])
    alias_item["bbox"] = {
        **canonical_alias_bbox,
        "w": canonical_alias_bbox["width"],
        "h": canonical_alias_bbox["height"],
    }
    alias_descriptor = alias_item["running_region"]
    alias_descriptor["predecessor_item_sha256"] = (
        _contract.predecessor_item_sha256(
            alias_item,
            alias_descriptor["predecessor_type"],
        )
    )
    legacy_bbox_alias_ir["elements"][0]["running_region"] = deepcopy(
        alias_descriptor
    )
    alias_predecessor, alias_predecessor_ir = direct_predecessors_for(
        legacy_bbox_alias_public,
        legacy_bbox_alias_ir,
    )
    assert alias_predecessor_ir is not None
    alias_report = source_report_for(legacy_bbox_alias_public)
    validate_source_projection(
        alias_report,
        legacy_bbox_alias_public,
        predecessor_document=alias_predecessor,
        ir_document=legacy_bbox_alias_ir,
        predecessor_ir=alias_predecessor_ir,
    )
    canonical_bbox_mismatch = deepcopy(legacy_bbox_alias_public)
    mismatch_item = canonical_bbox_mismatch["pages"][0]["items"][0]
    mismatch_item["bbox"]["width"] += 1.0
    mismatch_item["running_region"]["predecessor_item_sha256"] = (
        _contract.predecessor_item_sha256(
            mismatch_item,
            mismatch_item["running_region"]["predecessor_type"],
        )
    )
    _expect_contract_rejection(
        lambda: validate_source_projection(
            alias_report,
            canonical_bbox_mismatch,
            predecessor_document=alias_predecessor,
            ir_document=legacy_bbox_alias_ir,
            predecessor_ir=alias_predecessor_ir,
        ),
        "canonical bbox coordinate mismatch behind legacy aliases",
    )

    wrong_direct_type = deepcopy(public)
    wrong_direct_type["pages"][0]["items"][0]["type"] = "text"
    wrong_direct_hash = deepcopy(public)
    wrong_direct_hash["pages"][0]["items"][0]["running_region"][
        "predecessor_item_sha256"
    ] = "c" * 64
    arbitrary_boundary_id = deepcopy(direct_report)
    arbitrary_boundary_id["pages"][0]["boundary_candidates"][0]["id"] = (
        "boundary-candidate-00000000000000000000"
    )
    fabricated_boundary_path = deepcopy(direct_report)
    fabricated_candidate = fabricated_boundary_path["pages"][0][
        "boundary_candidates"
    ][0]
    fabricated_candidate["public_path"] = ["pages", 0, "items", 9]
    fabricated_candidate["id"] = _contract.boundary_candidate_id(
        fabricated_candidate,
        source_sha256=public["document"]["sha256"],
        physical_page_index=1,
    )
    wrong_boundary_source = deepcopy(direct_report)
    wrong_source_candidate = wrong_boundary_source["pages"][0][
        "boundary_candidates"
    ][0]
    wrong_source_candidate["source_object_ids"] = ["word-fabricated"]
    wrong_source_candidate["id"] = _contract.boundary_candidate_id(
        wrong_source_candidate,
        source_sha256=public["document"]["sha256"],
        physical_page_index=1,
    )
    for label, bad_report, bad_public in (
        ("projected direct current type", direct_report, wrong_direct_type),
        ("projected direct predecessor hash", direct_report, wrong_direct_hash),
        ("arbitrary boundary candidate ID", arbitrary_boundary_id, public),
        ("fabricated boundary public path", fabricated_boundary_path, public),
        ("wrong boundary source objects", wrong_boundary_source, public),
    ):
        _expect_contract_rejection(
            lambda bad_report=bad_report, bad_public=bad_public: (
                validate_source_projection(
                    bad_report,
                    bad_public,
                    predecessor_document=direct_predecessor,
                    ir_document=ir,
                    predecessor_ir=direct_predecessor_ir,
                )
            ),
            label,
        )

    extracted_report = source_report_for(extracted_public)
    extracted_report["pages"][0]["source_character_count"] = len(
        extracted["source_text"]
    )
    extracted_report["pages"][0]["source_word_count"] = len(
        extracted["source_text"].split()
    )
    extracted_report["counts"]["source_character_count"] = len(
        extracted["source_text"]
    )
    extracted_report["counts"]["source_word_count"] = len(
        extracted["source_text"].split()
    )
    extracted_candidate_id = extracted_report["pages"][0]["boundary_candidates"][
        0
    ]["id"]
    extracted_method_proofs = {
        extracted_candidate_id: {
            "native_source": True,
            "evidence_mode": "trusted_layout_role",
            "repetition_page_indexes": (),
            "complete_delimiter_line": True,
            "scalar_match_count": 1,
            "intervals_disjoint": True,
            "owner_kind": "visual",
        }
    }
    validate_source_projection(
        extracted_report,
        extracted_public,
        predecessor_document=predecessor_public,
        ir_document=extracted_ir,
        predecessor_ir=predecessor_ir,
        extracted_plans=(binding_plan,),
        method_proofs=extracted_method_proofs,
    )
    extracted_source_candidate = extracted_report["pages"][0][
        "boundary_candidates"
    ][0]
    trusted_extracted_proof = extracted_method_proofs[
        extracted_candidate_id
    ]
    _contract.validate_boundary_method_proof(
        extracted_source_candidate,
        trusted_extracted_proof,
        page_width=612.0,
        page_height=792.0,
        label_candidate_ids=(),
        extracted_plan=binding_plan,
    )
    expected_exact_repetition_pages = (1, 2, 3)
    standalone_exact_repetition_proof = {
        **deepcopy(trusted_extracted_proof),
        "evidence_mode": "exact_repetition",
        "repetition_page_indexes": expected_exact_repetition_pages,
    }
    _contract.validate_boundary_method_proof(
        extracted_source_candidate,
        standalone_exact_repetition_proof,
        page_width=612.0,
        page_height=792.0,
        label_candidate_ids=(),
        extracted_plan=binding_plan,
        expected_repetition_page_indexes=expected_exact_repetition_pages,
    )
    _expect_contract_rejection(
        lambda: _contract.validate_boundary_method_proof(
            extracted_source_candidate,
            standalone_exact_repetition_proof,
            page_width=612.0,
            page_height=792.0,
            label_candidate_ids=(),
            extracted_plan=binding_plan,
        ),
        "standalone extracted repetition missing expected membership",
    )
    for label, fabricated_pages in (
        ("subset", (1, 2)),
        ("foreign member", (1, 2, 4)),
    ):
        fabricated_standalone_proof = {
            **deepcopy(standalone_exact_repetition_proof),
            "repetition_page_indexes": fabricated_pages,
        }
        _expect_contract_rejection(
            lambda fabricated_standalone_proof=(
                fabricated_standalone_proof
            ): _contract.validate_boundary_method_proof(
                extracted_source_candidate,
                fabricated_standalone_proof,
                page_width=612.0,
                page_height=792.0,
                label_candidate_ids=(),
                extracted_plan=binding_plan,
                expected_repetition_page_indexes=(1, 2, 3),
            ),
            f"standalone extracted repetition {label}",
        )

    def validate_nested_extracted_binding(
        *,
        owner: Mapping[str, Any] = extracted_owner,
        owner_ir: Mapping[str, Any] = predecessor_ir,
        contribution_plan: _contract.ExtractedContributionPlan = binding_plan,
    ) -> None:
        _contract._validate_extracted_method_evidence_binding(
            extracted_source_candidate,
            extracted_method_proofs[extracted_candidate_id],
            extracted_descriptor,
            owner,
            predecessor_ir=owner_ir,
            source_sha256=extracted_public["document"]["sha256"],
            extracted_plan=contribution_plan,
            page_height=792.0,
            source_character_count=len(extracted["source_text"]),
            source_word_count=len(extracted["source_text"].split()),
        )

    def coordinated_nested_owner(
        owner: Mapping[str, Any], owner_ir: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], _contract.ExtractedContributionPlan]:
        mutated_owner = deepcopy(owner)
        mutated_ir = deepcopy(owner_ir)
        owner_element = next(
            element
            for element in mutated_ir["elements"]
            if element["id"] == "owner-element-1"
        )
        owner_element["properties"]["legacy_item"] = deepcopy(mutated_owner)
        owner_hash = _contract.sha256_json(mutated_owner)
        mutated_plan = replace(
            binding_plan,
            owner_sha256_before=owner_hash,
            owner_sha256_after=owner_hash,
        )
        return mutated_owner, mutated_ir, mutated_plan

    low_owner_coverage = deepcopy(extracted_owner)
    low_owner_coverage["bbox"].update({"x": 73.3, "width": 466.7})
    low_owner_coverage, low_owner_ir, low_owner_plan = coordinated_nested_owner(
        low_owner_coverage, predecessor_ir
    )
    next(
        bbox for bbox in low_owner_ir["bboxes"] if bbox["id"] == "owner-bbox-1"
    ).update({"x": 73.3, "width": 466.7})

    low_child_coverage = deepcopy(extracted_owner)
    for child in low_child_coverage["contained_items"]:
        child["bbox"]["width"] = 70.0
    low_child_coverage, low_child_ir, low_child_plan = coordinated_nested_owner(
        low_child_coverage, predecessor_ir
    )
    for index, child in enumerate(low_child_coverage["contained_items"], start=1):
        next(
            element
            for element in low_child_ir["elements"]
            if element["id"] == child["id"]
        )["properties"]["legacy_item"] = deepcopy(child)
        next(
            bbox
            for bbox in low_child_ir["bboxes"]
            if bbox["id"] == f"nested-header-bbox-{index}"
        )["width"] = 70.0

    shifted_child_center = deepcopy(extracted_owner)
    shifted_child_center["contained_items"][0]["bbox"].update(
        {"y": 758.0, "height": 9.0}
    )
    shifted_child_center["contained_items"][1]["bbox"].update(
        {"y": 770.0, "height": 12.0}
    )
    shifted_child_center, shifted_child_ir, shifted_child_plan = (
        coordinated_nested_owner(shifted_child_center, predecessor_ir)
    )
    for index, child in enumerate(shifted_child_center["contained_items"], start=1):
        next(
            element
            for element in shifted_child_ir["elements"]
            if element["id"] == child["id"]
        )["properties"]["legacy_item"] = deepcopy(child)
        next(
            bbox
            for bbox in shifted_child_ir["bboxes"]
            if bbox["id"] == f"nested-header-bbox-{index}"
        ).update(
            {
                "y": child["bbox"]["y"],
                "height": child["bbox"]["height"],
            }
        )

    broken_graph_owner = deepcopy(extracted_owner)
    broken_graph_owner["relationships"][0]["target_id"] = "unlinked-child"
    broken_graph_owner, broken_graph_ir, broken_graph_plan = coordinated_nested_owner(
        broken_graph_owner, predecessor_ir
    )

    wrong_child_value = deepcopy(extracted_owner)
    wrong_child_value["contained_items"][0].update(
        {"value": "FABRICATED", "md": "FABRICATED"}
    )
    wrong_child_value, wrong_value_ir, wrong_value_plan = coordinated_nested_owner(
        wrong_child_value, predecessor_ir
    )

    reversed_child_order = deepcopy(extracted_owner)
    reversed_child_order["contained_items"].reverse()
    reversed_child_order, reversed_order_ir, reversed_order_plan = (
        coordinated_nested_owner(reversed_child_order, predecessor_ir)
    )

    wrong_native_bbox_ir = deepcopy(predecessor_ir)
    next(
        bbox
        for bbox in wrong_native_bbox_ir["bboxes"]
        if bbox["id"] == "owner-native-bbox-1"
    )["x"] += 1.0

    for label, owner, owner_ir, contribution_plan in (
        (
            "extracted coarse owner below 0.99 candidate coverage",
            low_owner_coverage,
            low_owner_ir,
            low_owner_plan,
        ),
        (
            "extracted nested children below 0.90 candidate coverage",
            low_child_coverage,
            low_child_ir,
            low_child_plan,
        ),
        (
            "extracted nested children over 0.2-percent center delta",
            shifted_child_center,
            shifted_child_ir,
            shifted_child_plan,
        ),
        (
            "extracted nested graph link",
            broken_graph_owner,
            broken_graph_ir,
            broken_graph_plan,
        ),
        (
            "extracted nested child value",
            wrong_child_value,
            wrong_value_ir,
            wrong_value_plan,
        ),
        (
            "extracted nested child order",
            reversed_child_order,
            reversed_order_ir,
            reversed_order_plan,
        ),
        (
            "extracted native evidence bbox",
            extracted_owner,
            wrong_native_bbox_ir,
            binding_plan,
        ),
    ):
        _expect_contract_rejection(
            lambda owner=owner, owner_ir=owner_ir, contribution_plan=contribution_plan: (
                validate_nested_extracted_binding(
                    owner=owner,
                    owner_ir=owner_ir,
                    contribution_plan=contribution_plan,
                )
            ),
            label,
        )
    untrusted_predecessor_ir = deepcopy(predecessor_ir)
    untrusted_owner_element = untrusted_predecessor_ir["elements"][0]
    untrusted_owner_element.pop("raw_layout_role")
    untrusted_owner_element["properties"]["legacy_item"].pop(
        "raw_layout_role"
    )
    _expect_contract_rejection(
        lambda: validate_source_projection(
            extracted_report,
            extracted_public,
            predecessor_document=predecessor_public,
            ir_document=extracted_ir,
            predecessor_ir=untrusted_predecessor_ir,
            extracted_plans=(binding_plan,),
            method_proofs=extracted_method_proofs,
        ),
        "extracted trusted role absent from predecessor IR owner",
    )
    _expect_contract_rejection(
        lambda: validate_source_projection(
            extracted_report,
            extracted_public,
            predecessor_document=predecessor_public,
            ir_document=extracted_ir,
            predecessor_ir=predecessor_ir,
            extracted_plans=(binding_plan,),
        ),
        "accepted extracted candidate missing its method proof",
    )

    detected_public = deepcopy(public)
    detected_ir = deepcopy(ir)
    detected_identity = deepcopy(detached_detected)
    detected_source_objects = list(
        detected_identity["evidence_source"]["source_object_ids"]
    )
    detected_candidate_id = _contract.label_candidate_id(
        source_sha256=detected_public["document"]["sha256"],
        physical_page_index=1,
        source_object_ids=detected_source_objects,
        bbox=detected_identity["evidence_bbox"],
    )
    detected_identity["evidence_source"]["evidence_ids"] = [
        detected_candidate_id
    ]
    detected_candidate = {
        "id": detected_candidate_id,
        "visible_text": detected_identity["visible_text"],
        "normalized_label": detected_identity["detected_printed_label"],
        "bbox": deepcopy(detected_identity["evidence_bbox"]),
        "source_object_ids": detected_source_objects,
        "source_method": detected_identity["evidence_source"]["method"],
        "confidence": deepcopy(detected_identity["confidence"]),
        "concern_codes": [],
    }
    detected_public["pages"][0]["page_identity"] = deepcopy(detected_identity)
    detected_public["canonical_presentation"]["pages"][0]["page_identity"] = (
        deepcopy(detected_identity)
    )
    detected_public["processing"]["running_regions"]["detected_label_count"] = 1
    detected_public["processing"]["running_regions"]["legacy_fallback_count"] = 0
    detected_ir["pages"][0]["page_identity"] = deepcopy(detected_identity)
    detected_report = source_report_for(
        detected_public,
        label_candidates=((detected_candidate,),),
    )
    validate_source_projection(
        detected_report,
        detected_public,
        predecessor_document=direct_predecessor,
        ir_document=detected_ir,
        predecessor_ir=direct_predecessor_ir,
    )
    missing_visible_word_report = deepcopy(detected_report)
    missing_visible_word_public = deepcopy(detected_public)
    missing_visible_word_ir = deepcopy(detected_ir)
    missing_word_candidate = missing_visible_word_report["pages"][0][
        "label_candidates"
    ][0]
    missing_word_candidate["source_object_ids"] = ["word-1", "word-2"]
    missing_word_candidate["id"] = _contract.label_candidate_id(
        source_sha256=detected_public["document"]["sha256"],
        physical_page_index=1,
        source_object_ids=missing_word_candidate["source_object_ids"],
        bbox=missing_word_candidate["bbox"],
    )
    for identity in (
        missing_visible_word_public["pages"][0]["page_identity"],
        missing_visible_word_public["canonical_presentation"]["pages"][0][
            "page_identity"
        ],
        missing_visible_word_ir["pages"][0]["page_identity"],
    ):
        identity["evidence_source"]["evidence_ids"] = [
            missing_word_candidate["id"]
        ]
        identity["evidence_source"]["source_object_ids"] = ["word-1", "word-2"]
    _expect_contract_rejection(
        lambda: validate_source_projection(
            missing_visible_word_report,
            missing_visible_word_public,
            predecessor_document=direct_predecessor,
            ir_document=missing_visible_word_ir,
            predecessor_ir=direct_predecessor_ir,
        ),
        "coordinated visible label missing one source word",
    )

    # Exact-public detected identity resolves the complete public source item
    # and that item's unique primary IR element, not merely coincident text or
    # same-page geometry.
    exact_public = deepcopy(detected_public)
    exact_ir = deepcopy(detected_ir)
    exact_owner = {
        "id": "label-owner",
        "type": "text",
        "reading_order": 1,
        "value": "PAGE | 7",
        "md": "PAGE | 7",
        "bbox": deepcopy(detected_identity["evidence_bbox"]),
        "source": "native",
        "confidence": 1.0,
    }
    exact_public["pages"][0]["items"].append(exact_owner)
    exact_block = {
        "id": "label-owner-block",
        "page_id": "page-1",
        "primary_element_id": "label-owner-element",
        "primary_element_type": "text",
        "scope": "body",
        "markdown": "PAGE | 7",
        "text": "PAGE | 7",
        "contributing_element_ids": ["label-owner-element"],
        "relationship_ids": [],
        "excluded_contributions": [],
        "omission_reason": None,
        "suppressed_by_element_id": None,
    }
    exact_canonical_page = exact_public["canonical_presentation"]["pages"][0]
    exact_canonical_page["blocks"].append(exact_block)
    exact_canonical_page["body"] = {
        "block_ids": ["label-owner-block"],
        "markdown": "PAGE | 7\n",
        "text": "PAGE | 7\n",
    }
    exact_canonical_page["full"] = {
        "block_ids": ["block-1", "label-owner-block"],
        "markdown": "RUNNING FOOTER\n\nPAGE | 7\n",
        "text": "RUNNING FOOTER\n\nPAGE | 7\n",
    }
    exact_identity = deepcopy(detected_identity)
    exact_identity["evidence_source"].update(
        {
            "public_item_id": "label-owner",
            "public_path": ["pages", 0, "items", 1],
            "element_id": "label-owner-element",
            "bbox_id": "label-owner-bbox",
        }
    )
    exact_public["pages"][0]["page_identity"] = deepcopy(exact_identity)
    exact_canonical_page["page_identity"] = deepcopy(exact_identity)
    exact_ir["pages"][0]["page_identity"] = deepcopy(exact_identity)
    exact_ir["pages"][0]["element_ids"].append("label-owner-element")
    exact_ir["pages"][0]["presentation_element_ids"].append(
        "label-owner-element"
    )
    exact_ir["elements"].append(
        {
            "id": "label-owner-element",
            "page_id": "page-1",
            "type": "text",
            "reading_order": 1,
            "value": "PAGE | 7",
            "markdown": "PAGE | 7",
            "bbox_ids": ["label-owner-bbox"],
            "evidence_ids": ["label-owner-evidence"],
            "presentation_role": "primary",
            "properties": {
                "legacy_item": deepcopy(exact_owner),
                "source_position": 1,
            },
        }
    )
    exact_ir["bboxes"].append(
        {
            "id": "label-owner-bbox",
            "coordinate_system_id": "coord-1",
            **{
                key: exact_identity["evidence_bbox"][key]
                for key in ("x", "y", "width", "height")
            },
        }
    )
    exact_ir["evidence"].append(
        {
            "id": "label-owner-evidence",
            "element_id": "label-owner-element",
            "bbox_id": "label-owner-bbox",
        }
    )
    _contract.validate_ir_bindings(exact_ir, public_document=exact_public)

    partial_span_public = deepcopy(exact_public)
    partial_span_ir = deepcopy(exact_ir)
    partial_owner = partial_span_public["pages"][0]["items"][1]
    partial_owner["value"] = partial_owner["md"] = "17"
    partial_span_ir["elements"][1]["properties"]["legacy_item"] = deepcopy(
        partial_owner
    )
    _expect_contract_rejection(
        lambda: _contract.validate_ir_bindings(
            partial_span_ir, public_document=partial_span_public
        ),
        "exact-public partial visible-text span",
    )

    wrong_primary_public = deepcopy(exact_public)
    wrong_primary_ir = deepcopy(exact_ir)
    wrong_primary_ir["pages"][0]["element_ids"].append("label-decoy-element")
    wrong_primary_ir["pages"][0]["presentation_element_ids"].append(
        "label-decoy-element"
    )
    wrong_primary_ir["elements"].append(
        {
            "id": "label-decoy-element",
            "page_id": "page-1",
            "type": "text",
            "reading_order": 2,
            "value": "PAGE | 7",
            "markdown": "PAGE | 7",
            "bbox_ids": ["label-decoy-bbox"],
            "evidence_ids": ["label-decoy-evidence"],
            "presentation_role": "primary",
            "properties": {
                "legacy_item": {
                    **deepcopy(exact_owner),
                    "id": "label-decoy-owner",
                    "reading_order": 2,
                },
                "source_position": 2,
            },
        }
    )
    wrong_primary_ir["bboxes"].append(
        {
            "id": "label-decoy-bbox",
            "coordinate_system_id": "coord-1",
            **{
                key: exact_identity["evidence_bbox"][key]
                for key in ("x", "y", "width", "height")
            },
        }
    )
    wrong_primary_ir["evidence"].append(
        {
            "id": "label-decoy-evidence",
            "element_id": "label-decoy-element",
            "bbox_id": "label-decoy-bbox",
        }
    )
    for value in (
        wrong_primary_public["pages"][0]["page_identity"],
        wrong_primary_public["canonical_presentation"]["pages"][0][
            "page_identity"
        ],
        wrong_primary_ir["pages"][0]["page_identity"],
    ):
        value["evidence_source"].update(
            {
                "element_id": "label-decoy-element",
                "bbox_id": "label-decoy-bbox",
            }
        )
    _expect_contract_rejection(
        lambda: _contract.validate_ir_bindings(
            wrong_primary_ir, public_document=wrong_primary_public
        ),
        "exact-public same-page wrong primary IR element",
    )

    coordinated_arbitrary_label_report = deepcopy(detected_report)
    coordinated_arbitrary_label_public = deepcopy(detected_public)
    coordinated_arbitrary_label_ir = deepcopy(detected_ir)
    arbitrary_label_id = "label-candidate-00000000000000000000"
    coordinated_arbitrary_label_report["pages"][0]["label_candidates"][0][
        "id"
    ] = arbitrary_label_id
    for value in (
        coordinated_arbitrary_label_public["pages"][0]["page_identity"],
        coordinated_arbitrary_label_public["canonical_presentation"]["pages"][0][
            "page_identity"
        ],
        coordinated_arbitrary_label_ir["pages"][0]["page_identity"],
    ):
        value["evidence_source"]["evidence_ids"] = [arbitrary_label_id]
    _expect_contract_rejection(
        lambda: validate_source_projection(
            coordinated_arbitrary_label_report,
            coordinated_arbitrary_label_public,
            predecessor_document=direct_predecessor,
            ir_document=coordinated_arbitrary_label_ir,
            predecessor_ir=direct_predecessor_ir,
        ),
        "coordinated arbitrary label candidate ID",
    )
    wrong_label_text = deepcopy(detected_report)
    wrong_label_text["pages"][0]["label_candidates"][0].update(
        {"visible_text": "PAGE | 8", "normalized_label": "8"}
    )
    wrong_label_source = deepcopy(detected_report)
    wrong_label_source_candidate = wrong_label_source["pages"][0][
        "label_candidates"
    ][0]
    wrong_label_source_candidate["source_object_ids"] = ["word-fabricated"]
    wrong_label_source_candidate["id"] = _contract.label_candidate_id(
        source_sha256=detected_public["document"]["sha256"],
        physical_page_index=1,
        source_object_ids=wrong_label_source_candidate["source_object_ids"],
        bbox=wrong_label_source_candidate["bbox"],
    )
    for label, bad_report in (
        ("wrong detected candidate text", wrong_label_text),
        ("wrong detected candidate source objects", wrong_label_source),
    ):
        _expect_contract_rejection(
            lambda bad_report=bad_report: (
                validate_source_projection(
                    bad_report,
                    detected_public,
                    predecessor_document=direct_predecessor,
                    ir_document=detected_ir,
                    predecessor_ir=direct_predecessor_ir,
                )
            ),
            label,
        )

    _expect_contract_rejection(
        lambda: validate_source_projection(
            detected_report,
            public,
            predecessor_document=direct_predecessor,
            ir_document=ir,
            predecessor_ir=direct_predecessor_ir,
        ),
        "unique eligible label candidate silently downgraded",
    )
    rejected_candidate = deepcopy(detected_candidate)
    rejected_candidate["confidence"] = {
        "scope": "deterministic_rule",
        "score": 0.5,
        "unavailable_reason": None,
    }
    rejected_candidate["concern_codes"] = ["page_identity_source_conflict"]
    rejected_only_report = source_report_for(
        public,
        label_candidates=((rejected_candidate,),),
    )
    rejected_only_public = deepcopy(public)
    rejected_only_public["processing"]["running_regions"]["concern_count"] = 1
    rejected_only_public["running_region_concerns"] = [
        {
            "code": "page_identity_source_conflict",
            "source_ref": "page:1",
            "count": 1,
            "cap": _contract.MAX_CONCERNS_PER_PAGE,
            "exception_class": None,
        }
    ]
    validate_source_projection(
        rejected_only_report,
        rejected_only_public,
        predecessor_document=direct_predecessor,
        ir_document=ir,
        predecessor_ir=direct_predecessor_ir,
    )

    second_detected_candidate = deepcopy(detected_candidate)
    second_detected_candidate["bbox"] = {
        "x": 100.0,
        "y": 762.0,
        "width": 8.0,
        "height": 6.0,
        "unit": "pt",
    }
    second_detected_candidate["source_object_ids"] = ["word-1", "word-2", "word-3"]
    second_detected_candidate["id"] = _contract.label_candidate_id(
        source_sha256=public["document"]["sha256"],
        physical_page_index=1,
        source_object_ids=second_detected_candidate["source_object_ids"],
        bbox=second_detected_candidate["bbox"],
    )
    ambiguous_public = deepcopy(public)
    ambiguous_ir = deepcopy(ir)
    for value in (
        ambiguous_public["pages"][0]["page_identity"],
        ambiguous_public["canonical_presentation"]["pages"][0]["page_identity"],
        ambiguous_ir["pages"][0]["page_identity"],
    ):
        value["concern_codes"] = ["page_identity_detected_label_ambiguous"]
    ambiguous_public["processing"]["running_regions"]["concern_count"] = 1
    ambiguous_public["running_region_concerns"] = [
        {
            "code": "page_identity_detected_label_ambiguous",
            "source_ref": "page:1",
            "count": 1,
            "cap": _contract.MAX_CONCERNS_PER_PAGE,
            "exception_class": None,
        }
    ]
    ambiguous_report = source_report_for(
        ambiguous_public,
        label_candidates=((detected_candidate, second_detected_candidate),),
    )
    validate_source_projection(
        ambiguous_report,
        ambiguous_public,
        predecessor_document=direct_predecessor,
        ir_document=ambiguous_ir,
        predecessor_ir=direct_predecessor_ir,
    )

    repetition_source_sha256 = public["document"]["sha256"]
    repetition_signature = "running footer"
    repetition_group_id = _contract.stable_id(
        "running-repeat",
        POLICY_ID,
        repetition_source_sha256,
        "bottom",
        repetition_signature,
    )

    def repetition_binding(
        physical_page_index: int,
    ) -> tuple[dict[str, Any], dict[str, Any], float]:
        descriptor = deepcopy(public["pages"][0]["items"][0]["running_region"])
        descriptor.update(
            {
                "id": _contract.stable_id(
                    "running-region",
                    POLICY_ID,
                    repetition_source_sha256,
                    physical_page_index,
                    f"element-{physical_page_index}",
                    f"bbox-{physical_page_index}",
                    "footer",
                ),
                "page_id": f"page-{physical_page_index}",
                "physical_page_index": physical_page_index,
                "source_public_item_id": f"item-{physical_page_index}",
                "source_public_path": [
                    "pages",
                    physical_page_index - 1,
                    "items",
                    0,
                ],
                "source_element_id": f"element-{physical_page_index}",
                "bbox_id": f"bbox-{physical_page_index}",
                "evidence_ids": [f"evidence-{physical_page_index}"],
                "source_object_ids": [f"word-{physical_page_index}"],
                "source_method": "cross_page_repetition",
                "repetition_group_id": repetition_group_id,
                "repetition_page_indexes": [1, 2],
                "canonical_block_id": f"block-{physical_page_index}",
            }
        )
        candidate = {
            "id": "pending",
            "public_item_id": descriptor["source_public_item_id"],
            "public_path": list(descriptor["source_public_path"]),
            "element_id": descriptor["source_element_id"],
            "predecessor_type": descriptor["predecessor_type"],
            "bbox": dict(descriptor["bbox"]),
            "bbox_id": descriptor["bbox_id"],
            "evidence_ids": list(descriptor["evidence_ids"]),
            "source_object_ids": list(descriptor["source_object_ids"]),
            "raw_layout_role": "page_footer",
            "normalized_signature": repetition_signature,
            "boundary_band": "bottom",
            "source_method": descriptor["source_method"],
            "disposition": "accepted",
            "confidence": deepcopy(descriptor["confidence"]),
            "concern_codes": [],
        }
        candidate["id"] = _contract.boundary_candidate_id(
            candidate,
            source_sha256=repetition_source_sha256,
            physical_page_index=physical_page_index,
        )
        return descriptor, candidate, 792.0

    repetition_bindings = (repetition_binding(1), repetition_binding(2))
    _contract.validate_repetition_group_bindings(
        repetition_bindings,
        source_sha256=repetition_source_sha256,
    )
    mismatched_declared = deepcopy(repetition_bindings)
    mismatched_declared[1][0]["repetition_page_indexes"] = [1, 2, 3]
    mixed_signature = deepcopy(repetition_bindings)
    mixed_signature[1][1]["normalized_signature"] = "different footer"
    mixed_band = deepcopy(repetition_bindings)
    mixed_band[1][1]["boundary_band"] = "top"
    wrong_repetition_id = deepcopy(repetition_bindings)
    for descriptor, _, _ in wrong_repetition_id:
        descriptor["repetition_group_id"] = "running-repeat-00000000000000000000"
    vertical_drift = deepcopy(repetition_bindings)
    vertical_drift[1][0]["bbox"]["y"] = 700.0
    vertical_drift[1][1]["bbox"]["y"] = 700.0
    horizontal_disagreement = deepcopy(repetition_bindings)
    horizontal_disagreement[1][0]["bbox"]["x"] = 300.0
    horizontal_disagreement[1][1]["bbox"]["x"] = 300.0
    duplicate_page = deepcopy(repetition_bindings)
    duplicate_page[1][0]["physical_page_index"] = 1
    for label, bad_bindings in (
        ("singleton repetition group", repetition_bindings[:1]),
        ("undeclared repetition member", mismatched_declared),
        ("mixed repetition signature", mixed_signature),
        ("mixed repetition band", mixed_band),
        ("wrong repetition stable ID", wrong_repetition_id),
        ("repetition vertical drift", vertical_drift),
        ("repetition horizontal disagreement", horizontal_disagreement),
        ("duplicate repetition source page", duplicate_page),
    ):
        _expect_contract_rejection(
            lambda bad_bindings=bad_bindings: (
                _contract.validate_repetition_group_bindings(
                    bad_bindings,
                    source_sha256=repetition_source_sha256,
                )
            ),
            label,
        )

    exact_repetition_descriptor = deepcopy(extracted_descriptor)
    exact_repetition_candidate = deepcopy(
        extracted_report["pages"][0]["boundary_candidates"][0]
    )
    exact_repetition_group_id = _contract.stable_id(
        "running-repeat",
        POLICY_ID,
        extracted_public["document"]["sha256"],
        exact_repetition_candidate["boundary_band"],
        exact_repetition_candidate["normalized_signature"],
    )
    exact_repetition_descriptor["repetition_group_id"] = (
        exact_repetition_group_id
    )
    exact_repetition_descriptor["repetition_page_indexes"] = [1, 2]
    exact_repetition_proof = {
        "evidence_mode": "exact_repetition",
        "repetition_page_indexes": (1, 2),
    }
    _contract._validate_extracted_method_evidence_binding(
        exact_repetition_candidate,
        exact_repetition_proof,
        exact_repetition_descriptor,
        extracted_owner,
        predecessor_ir=predecessor_ir,
        source_sha256=extracted_public["document"]["sha256"],
        extracted_plan=binding_plan,
        page_height=792.0,
        source_character_count=len(extracted["source_text"]),
        source_word_count=len(extracted["source_text"].split()),
    )
    fabricated_exact_pages = {
        **exact_repetition_proof,
        "repetition_page_indexes": (999, 1000),
    }
    null_exact_group = deepcopy(exact_repetition_descriptor)
    null_exact_group["repetition_group_id"] = None
    null_exact_group["repetition_page_indexes"] = []
    for label, descriptor_value, proof_value in (
        (
            "extracted fabricated exact-repetition pages",
            exact_repetition_descriptor,
            fabricated_exact_pages,
        ),
        (
            "extracted exact-repetition null descriptor group",
            null_exact_group,
            exact_repetition_proof,
        ),
    ):
        _expect_contract_rejection(
            lambda descriptor_value=descriptor_value, proof_value=proof_value: (
                _contract._validate_extracted_method_evidence_binding(
                    exact_repetition_candidate,
                    proof_value,
                    descriptor_value,
                    extracted_owner,
                    predecessor_ir=predecessor_ir,
                    source_sha256=extracted_public["document"]["sha256"],
                    extracted_plan=binding_plan,
                    page_height=792.0,
                    source_character_count=len(extracted["source_text"]),
                    source_word_count=len(extracted["source_text"].split()),
                )
            ),
            label,
        )

    repetition_public_pages: list[dict[str, Any]] = []
    repetition_canonical_pages: list[dict[str, Any]] = []
    repetition_ir_pages: list[dict[str, Any]] = []
    repetition_ir_elements: list[dict[str, Any]] = []
    repetition_ir_bboxes: list[dict[str, Any]] = []
    repetition_ir_evidence: list[dict[str, Any]] = []
    repetition_ir_coordinates: list[dict[str, Any]] = []
    for physical_page_index in (1, 2):
        descriptor, _, _ = repetition_binding(physical_page_index)
        predecessor_item = {
            "id": f"item-{physical_page_index}",
            "type": "text",
            "label": "page_footer",
            "reading_order": 0,
            "value": "RUNNING FOOTER",
            "md": "RUNNING FOOTER",
            "bbox": dict(descriptor["bbox"]),
            "source": "native",
            "confidence": 1.0,
        }
        descriptor["predecessor_item_sha256"] = _contract.sha256_json(
            predecessor_item
        )
        projected_item = {
            **predecessor_item,
            "type": "footer",
            "layout_running_region_projected": True,
            "running_region_policy": POLICY_ID,
            "running_region": descriptor,
        }
        identity = deepcopy(public["pages"][0]["page_identity"])
        identity.update(
            {
                "page_id": f"page-{physical_page_index}",
                "physical_page_index": physical_page_index,
                "display_label": str(physical_page_index),
            }
        )
        identity["evidence_source"]["page_index"] = physical_page_index
        identity["evidence_source"]["source_object_ids"] = [
            (
                f"configured-predecessor:{repetition_source_sha256}:"
                f"page:{physical_page_index}:page_label"
            )
        ]
        block = deepcopy(public["canonical_presentation"]["pages"][0]["blocks"][0])
        block.update(
            {
                "id": descriptor["canonical_block_id"],
                "page_id": descriptor["page_id"],
                "primary_element_id": descriptor["source_element_id"],
                "contributing_element_ids": [descriptor["source_element_id"]],
            }
        )
        repetition_public_pages.append(
            {
                "page_index": physical_page_index,
                "page_number": physical_page_index,
                "page_label": str(physical_page_index),
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "items": [projected_item],
                "page_identity": identity,
            }
        )
        repetition_canonical_pages.append(
            {
                "page_id": descriptor["page_id"],
                "page_index": physical_page_index,
                "page_identity": deepcopy(identity),
                "blocks": [block],
                "body": {"block_ids": [], "markdown": "", "text": ""},
                "full": {
                    "block_ids": [descriptor["canonical_block_id"]],
                    "markdown": "RUNNING FOOTER\n",
                    "text": "RUNNING FOOTER\n",
                },
                "header": {"block_ids": [], "markdown": "", "text": ""},
                "footer": {
                    "block_ids": [descriptor["canonical_block_id"]],
                    "markdown": "RUNNING FOOTER\n",
                    "text": "RUNNING FOOTER\n",
                },
            }
        )
        repetition_ir_pages.append(
            {
                "id": descriptor["page_id"],
                "page_index": physical_page_index,
                "element_ids": [descriptor["source_element_id"]],
                "presentation_element_ids": [descriptor["source_element_id"]],
                "page_identity": deepcopy(identity),
            }
        )
        repetition_ir_elements.append(
            {
                "id": descriptor["source_element_id"],
                "page_id": descriptor["page_id"],
                "source_public_item_id": descriptor[
                    "source_public_item_id"
                ],
                "type": "footer",
                "label": "page_footer",
                "bbox_ids": [descriptor["bbox_id"]],
                "evidence_ids": list(descriptor["evidence_ids"]),
                "presentation_role": "primary",
                "running_region": deepcopy(descriptor),
            }
        )
        repetition_ir_bboxes.append(
            {
                "id": descriptor["bbox_id"],
                "coordinate_system_id": f"coord-{physical_page_index}",
                "x": descriptor["bbox"]["x"],
                "y": descriptor["bbox"]["y"],
                "width": descriptor["bbox"]["width"],
                "height": descriptor["bbox"]["height"],
            }
        )
        repetition_ir_evidence.append(
            {
                "id": descriptor["evidence_ids"][0],
                "element_id": descriptor["source_element_id"],
                "bbox_id": descriptor["bbox_id"],
            }
        )
        repetition_ir_coordinates.append(
            {
                "id": f"coord-{physical_page_index}",
                "page_id": descriptor["page_id"],
                "unit": "pt",
                "origin": "top_left",
            }
        )
    repetition_public = {
        "document": {"sha256": repetition_source_sha256},
        "pages": repetition_public_pages,
        "canonical_presentation": {"pages": repetition_canonical_pages},
        "processing": {
            "running_regions": {
                "policy_id": POLICY_ID,
                "status": "projected",
                "reason": None,
                "source_page_count": 2,
                "identity_count": 2,
                "detected_label_count": 0,
                "embedded_label_count": 0,
                "legacy_fallback_count": 2,
                "candidate_count": 2,
                "comparison_count": 1,
                "running_region_count": 2,
                "header_count": 0,
                "footer_count": 2,
                "top_navigation_count": 0,
                "bottom_navigation_count": 0,
                "concern_count": 0,
                "extraction_ms": 1.0,
                "projection_ms": 1.0,
                "total_ms": 2.0,
            }
        },
    }
    repetition_ir = {
        "source_sha256": repetition_source_sha256,
        "pages": repetition_ir_pages,
        "elements": repetition_ir_elements,
        "bboxes": repetition_ir_bboxes,
        "evidence": repetition_ir_evidence,
        "coordinate_systems": repetition_ir_coordinates,
    }
    repetition_predecessor, repetition_predecessor_ir = direct_predecessors_for(
        repetition_public,
        repetition_ir,
    )
    assert repetition_predecessor_ir is not None
    document_view_public = deepcopy(repetition_public)
    install_document_views(document_view_public)
    document_view_predecessor, document_view_predecessor_ir = direct_predecessors_for(
        document_view_public,
        repetition_ir,
    )
    assert document_view_predecessor_ir is not None
    install_document_views(document_view_predecessor)
    expected_two_page_scalar = "RUNNING FOOTER\n\nRUNNING FOOTER\n"
    if (
        document_view_public["canonical_presentation"]["full"]["markdown"]
        != expected_two_page_scalar
        or document_view_public["canonical_presentation"]["footer"]["text"]
        != expected_two_page_scalar
        or document_view_predecessor["canonical_presentation"]["body"]["text"]
        != expected_two_page_scalar
    ):
        raise SyntheticFixtureIntegrityError(
            "canonical document page delimiter/order witness drifted"
        )
    document_view_stripped = _contract.strip_complete_running_region_sidecars(
        document_view_public,
        predecessor_document=document_view_predecessor,
        ir_document=repetition_ir,
        predecessor_ir=document_view_predecessor_ir,
    )
    if document_view_stripped != document_view_predecessor:
        raise SyntheticFixtureIntegrityError(
            "canonical document-view complete inverse drifted"
        )
    tampered_document_view = deepcopy(document_view_public)
    tampered_document_view["canonical_presentation"]["full"]["text"] = (
        "fabricated\n"
    )
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(tampered_document_view),
        "canonical document full text drift",
    )
    repetition_comparison_ledger = (
        {"page_index": 2, "comparison_count": 1},
    )
    repetition_report = source_report_for(repetition_public)
    validate_source_projection(
        repetition_report,
        repetition_public,
        predecessor_document=repetition_predecessor,
        ir_document=repetition_ir,
        predecessor_ir=repetition_predecessor_ir,
        comparison_ledger=repetition_comparison_ledger,
    )
    silent_null_repetition_public = deepcopy(repetition_public)
    silent_null_repetition_ir = deepcopy(repetition_ir)
    silent_null_descriptor = silent_null_repetition_public["pages"][1]["items"][0][
        "running_region"
    ]
    silent_null_descriptor["repetition_group_id"] = None
    silent_null_descriptor["repetition_page_indexes"] = []
    silent_null_repetition_ir["elements"][1]["running_region"] = deepcopy(
        silent_null_descriptor
    )
    _expect_contract_rejection(
        lambda: validate_source_projection(
            repetition_report,
            silent_null_repetition_public,
            predecessor_document=repetition_predecessor,
            ir_document=silent_null_repetition_ir,
            predecessor_ir=repetition_predecessor_ir,
            comparison_ledger=repetition_comparison_ledger,
        ),
        "eligible repeated report group silently null",
    )
    disagreeing_repetition_public = deepcopy(repetition_public)
    disagreeing_repetition_ir = deepcopy(repetition_ir)
    disagreeing_descriptor = disagreeing_repetition_public["pages"][1]["items"][0][
        "running_region"
    ]
    disagreeing_descriptor["repetition_group_id"] = _contract.stable_id(
        "running-repeat",
        POLICY_ID,
        repetition_source_sha256,
        "bottom",
        "different footer",
    )
    disagreeing_repetition_ir["elements"][1]["running_region"] = deepcopy(
        disagreeing_descriptor
    )
    _expect_contract_rejection(
        lambda: validate_source_projection(
            repetition_report,
            disagreeing_repetition_public,
            predecessor_document=repetition_predecessor,
            ir_document=disagreeing_repetition_ir,
            predecessor_ir=repetition_predecessor_ir,
            comparison_ledger=repetition_comparison_ledger,
        ),
        "eligible repeated report group disagrees",
    )
    detached_public = deepcopy(public)
    detached_public["pages"][0]["page_identity"] = deepcopy(detached_detected)
    detached_public["canonical_presentation"]["pages"][0]["page_identity"] = deepcopy(
        detached_detected
    )
    detached_summary = detached_public["processing"]["running_regions"]
    detached_summary["detected_label_count"] = 1
    detached_summary["legacy_fallback_count"] = 0
    _contract.validate_projected_document(detached_public)

    def nonprojecting_witness(status: str, reason: str) -> dict[str, Any]:
        witness = deepcopy(public)
        item = witness["pages"][0]["items"][0]
        descriptor = item["running_region"]
        for key in _contract.PUBLIC_RUNNING_REGION_KEYS:
            item.pop(key)
        item["type"] = descriptor["predecessor_type"]
        witness["pages"][0].pop("page_identity")
        canonical_page = witness["canonical_presentation"]["pages"][0]
        canonical_page.pop("page_identity")
        canonical_page["blocks"] = []
        for view_name in ("body", "full", "header", "footer"):
            canonical_page[view_name]["block_ids"] = []
            canonical_page[view_name]["markdown"] = ""
            canonical_page[view_name]["text"] = ""
        summary = witness["processing"]["running_regions"]
        summary["status"] = status
        summary["reason"] = reason
        for key in _contract.PROCESSING_SUMMARY_FIELDS[3:16]:
            summary[key] = 0
        summary["extraction_ms"] = 0.0
        summary["projection_ms"] = 0.0
        summary["total_ms"] = 0.0
        concern_code = (
            reason
            if status == "unavailable"
            else "running_region_projection_failed_closed"
            if status == "failed_closed"
            else None
        )
        if concern_code is not None:
            summary["concern_count"] = 1
            witness["running_region_concerns"] = [{"code": concern_code}]
        return witness

    nonprojecting_states = (
        (
            "failed_closed",
            "running_region_projection_failed_closed",
        ),
        (
            "unavailable",
            "running_region_source_evidence_unavailable",
        ),
        (
            "not_applicable",
            "running_region_input_not_applicable",
        ),
    )
    for status, reason in nonprojecting_states:
        clean_nonprojecting = nonprojecting_witness(status, reason)
        _contract.validate_projected_document(clean_nonprojecting)

        complete_remnant = deepcopy(clean_nonprojecting)
        complete_remnant["pages"][0]["items"][0] = deepcopy(
            public["pages"][0]["items"][0]
        )
        _expect_contract_rejection(
            lambda value=complete_remnant: _contract.validate_projected_document(value),
            f"{status} complete running-item remnant",
        )

        partial_remnant = deepcopy(clean_nonprojecting)
        partial_remnant["pages"][0]["items"][0][
            "layout_running_region_projected"
        ] = True
        _expect_contract_rejection(
            lambda value=partial_remnant: _contract.validate_projected_document(value),
            f"{status} partial running-item remnant",
        )

        canonical_remnant = deepcopy(clean_nonprojecting)
        canonical_page = canonical_remnant["canonical_presentation"]["pages"][0]
        canonical_page["blocks"] = [
            deepcopy(public["canonical_presentation"]["pages"][0]["blocks"][0])
        ]
        canonical_page["blocks"][0]["running_region"] = deepcopy(
            public["pages"][0]["items"][0]["running_region"]
        )
        canonical_page["full"]["block_ids"] = ["block-1"]
        canonical_page["footer"]["block_ids"] = ["block-1"]
        _expect_contract_rejection(
            lambda value=canonical_remnant: _contract.validate_projected_document(value),
            f"{status} running canonical remnant",
        )

    public_identity_remnant = nonprojecting_witness(
        "unavailable", "running_region_source_evidence_unavailable"
    )
    public_identity_remnant["pages"][0]["page_identity"] = deepcopy(
        public["pages"][0]["page_identity"]
    )
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(public_identity_remnant),
        "non-projecting public identity remnant",
    )
    canonical_identity_remnant = nonprojecting_witness(
        "failed_closed", "running_region_projection_failed_closed"
    )
    canonical_identity_remnant["canonical_presentation"]["pages"][0][
        "page_identity"
    ] = deepcopy(public["pages"][0]["page_identity"])
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(canonical_identity_remnant),
        "non-projecting canonical identity remnant",
    )
    extra_processing = nonprojecting_witness(
        "not_applicable", "running_region_input_not_applicable"
    )
    extra_processing["processing"]["running_region_private_ledger"] = {}
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(extra_processing),
        "non-projecting extra US08 processing",
    )
    excess_concerns = nonprojecting_witness(
        "failed_closed", "running_region_projection_failed_closed"
    )
    excess_concerns["running_region_concerns"].append(
        {"code": "running_region_canonical_custody_invalid"}
    )
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(excess_concerns),
        "non-projecting excess US08 concerns",
    )
    unsanitized_concern = nonprojecting_witness(
        "unavailable", "running_region_source_evidence_unavailable"
    )
    unsanitized_concern["running_region_concerns"][0]["message"] = "source text"
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(unsanitized_concern),
        "non-projecting unsanitized concern",
    )
    stripped = _contract.strip_complete_running_region_sidecars(
        public,
        predecessor_document=direct_predecessor,
        ir_document=ir,
        predecessor_ir=direct_predecessor_ir,
    )
    if stripped["pages"][0]["items"][0].get("type") != "text" or any(
        key in stripped["pages"][0]["items"][0]
        for key in _contract.RUNNING_REGION_SIDECAR_FIELDS
    ):
        raise SyntheticFixtureIntegrityError("direct strict strip drifted")
    partial = deepcopy(public)
    partial["pages"][0]["items"][0].pop("running_region")
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(partial), "partial mutation"
    )
    bad_direct = deepcopy(public)
    bad_direct["pages"][0]["items"][0]["running_region"][
        "predecessor_item_sha256"
    ] = "0" * 64
    _expect_contract_rejection(
        lambda: _contract.strip_complete_running_region_sidecars(
            bad_direct,
            predecessor_document=direct_predecessor,
        ),
        "direct strip hash mismatch",
    )
    bad_extracted = deepcopy(public)
    bad_extracted["pages"][0]["items"][0]["running_region"][
        "source_method"
    ] = "extracted_source_contribution"
    _expect_contract_rejection(
        lambda: _contract.strip_complete_running_region_sidecars(
            bad_extracted,
            predecessor_document=direct_predecessor,
        ),
        "extracted strip owner alias",
    )
    canonical_mismatch = deepcopy(public)
    canonical_mismatch["canonical_presentation"]["pages"][0]["blocks"][0][
        "scope"
    ] = "header"
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(canonical_mismatch),
        "canonical scope mismatch",
    )
    omitted_block_coexistence = deepcopy(public)
    omitted_block_coexistence["canonical_presentation"]["pages"][0]["blocks"].append(
        {
            "id": "omitted-block-1",
            "page_id": "page-1",
            "primary_element_id": "omitted-element-1",
            "primary_element_type": "text",
            "scope": "body",
            "markdown": "ignored",
            "text": "ignored",
            "contributing_element_ids": ["omitted-element-1"],
            "relationship_ids": [],
            "excluded_contributions": [],
            "omission_reason": "empty_content",
            "suppressed_by_element_id": None,
        }
    )
    _contract.validate_projected_document(omitted_block_coexistence)
    body_running_membership = deepcopy(public)
    body_running_membership["canonical_presentation"]["pages"][0]["body"][
        "block_ids"
    ] = ["block-1"]
    full_scalar_drift = deepcopy(public)
    full_scalar_drift["canonical_presentation"]["pages"][0]["full"][
        "markdown"
    ] = "fabricated\n"
    footer_scalar_drift = deepcopy(public)
    footer_scalar_drift["canonical_presentation"]["pages"][0]["footer"][
        "text"
    ] = "fabricated\n"
    for label, bad_document in (
        ("running block retained in body view", body_running_membership),
        ("canonical full markdown drift", full_scalar_drift),
        ("canonical footer text drift", footer_scalar_drift),
    ):
        _expect_contract_rejection(
            lambda bad_document=bad_document: _contract.validate_projected_document(
                bad_document
            ),
            label,
        )
    duplicate_canonical_membership = deepcopy(public)
    duplicate_canonical_membership["canonical_presentation"]["pages"][0][
        "footer"
    ]["block_ids"].append("block-1")
    opposite_canonical_membership = deepcopy(public)
    opposite_canonical_membership["canonical_presentation"]["pages"][0][
        "header"
    ]["block_ids"].append("block-1")
    unresolved_canonical_membership = deepcopy(public)
    unresolved_canonical_membership["canonical_presentation"]["pages"][0][
        "full"
    ]["block_ids"].append("missing-block")
    for label, bad_document in (
        ("duplicate canonical membership", duplicate_canonical_membership),
        ("opposite canonical scope membership", opposite_canonical_membership),
        ("unresolved canonical membership", unresolved_canonical_membership),
    ):
        _expect_contract_rejection(
            lambda bad_document=bad_document: (
                _contract.validate_projected_document(bad_document)
            ),
            label,
        )
    reversed_canonical_pages = deepcopy(repetition_public)
    reversed_canonical_pages["canonical_presentation"]["pages"].reverse()
    duplicate_canonical_page_id = deepcopy(repetition_public)
    duplicate_canonical_page_id["canonical_presentation"]["pages"][1]["page_id"] = (
        duplicate_canonical_page_id["canonical_presentation"]["pages"][0]["page_id"]
    )
    for label, bad_document in (
        ("reversed canonical physical page order", reversed_canonical_pages),
        ("duplicate canonical page ID", duplicate_canonical_page_id),
    ):
        _expect_contract_rejection(
            lambda bad_document=bad_document: _contract.validate_projected_document(
                bad_document
            ),
            label,
        )
    identity_mismatch = deepcopy(public)
    identity_mismatch["canonical_presentation"]["pages"][0]["page_identity"] = deepcopy(
        empty_physical
    )
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(identity_mismatch),
        "public/canonical identity mismatch",
    )
    duplicate_owner = deepcopy(public)
    duplicate_owner["pages"][0]["items"].append(
        deepcopy(duplicate_owner["pages"][0]["items"][0])
    )
    duplicate_owner["processing"]["running_regions"]["running_region_count"] = 2
    duplicate_owner["processing"]["running_regions"]["footer_count"] = 2
    _expect_contract_rejection(
        lambda: _contract.validate_projected_document(duplicate_owner),
        "duplicate public path/shared owner",
    )
    cross_page_ir = deepcopy(ir)
    cross_page_ir["coordinate_systems"][0]["page_id"] = "page-2"
    _expect_contract_rejection(
        lambda: _contract.validate_ir_bindings(cross_page_ir, public_document=public),
        "cross-page IR bbox",
    )
    malformed_counts = deepcopy(public["processing"]["running_regions"])
    malformed_counts["detected_label_count"] = 1
    _expect_contract_rejection(
        lambda: _contract.validate_processing_summary(malformed_counts),
        "malformed processing counts",
    )
    _contract.validate_comparison_ledger(
        ({"page_index": 1, "comparison_count": _contract.MAX_COMPARISONS_PER_PAGE},),
        source_page_count=1,
        expected_comparison_count=_contract.MAX_COMPARISONS_PER_PAGE,
    )
    _expect_contract_rejection(
        lambda: _contract.validate_comparison_ledger(
            (
                {
                    "page_index": 1,
                    "comparison_count": _contract.MAX_COMPARISONS_PER_PAGE + 1,
                },
            ),
            source_page_count=1,
            expected_comparison_count=_contract.MAX_COMPARISONS_PER_PAGE + 1,
        ),
        "comparison ledger per-page maximum plus one",
    )
    _expect_contract_rejection(
        lambda: _contract.validate_comparison_ledger(
            ({"page_index": 1, "comparison_count": 1},),
            source_page_count=1,
            expected_comparison_count=2,
        ),
        "comparison ledger arbitrary total",
    )
    projected_concern = deepcopy(public)
    projected_concern["processing"]["running_regions"]["concern_count"] = 1
    projected_concern["running_region_concerns"] = [
        {
            "code": "running_region_geometry_ambiguous",
            "source_ref": "page:1",
            "count": 1,
            "cap": _contract.MAX_CONCERNS_PER_PAGE,
            "exception_class": None,
        }
    ]
    _contract.validate_projected_document(projected_concern)
    hostile_projected_concern = deepcopy(projected_concern)
    hostile_projected_concern["running_region_concerns"][0]["message"] = (
        "forbidden source text"
    )
    wrong_projected_concern_count = deepcopy(projected_concern)
    wrong_projected_concern_count["running_region_concerns"][0]["count"] = 2
    wrong_projected_concern_count["running_region_concerns"][0]["cap"] = 1
    for label, bad_document in (
        ("hostile projected concern payload", hostile_projected_concern),
        ("projected concern count exceeds cap", wrong_projected_concern_count),
    ):
        _expect_contract_rejection(
            lambda bad_document=bad_document: _contract.validate_projected_document(
                bad_document
            ),
            label,
        )

    valid_report = {
        "report_version": "1.0",
        "policy_id": POLICY_ID,
        "source_sha256": "d" * 64,
        "status": "available",
        "pages": [
            {
                "page_index": 1,
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "coordinate_system_id": _contract.COORDINATE_SYSTEM_ID,
                "source_character_count": 0,
                "source_word_count": 0,
                "embedded_label": None,
                "label_candidates": [],
                "boundary_candidates": [],
                "concern_codes": [],
            }
        ],
        "counts": {
            "page_count": 1,
            "source_character_count": 0,
            "source_word_count": 0,
            "embedded_label_count": 0,
            "label_candidate_count": 0,
            "boundary_candidate_count": 0,
            "concern_count": 0,
        },
        "concern_codes": [],
        "extraction_ms": 0.0,
    }
    _contract.validate_source_report(valid_report)
    for status, code in (
        ("unavailable", "running_region_source_evidence_unavailable"),
        ("refused", "running_region_source_limit"),
    ):
        refusal_report = deepcopy(valid_report)
        refusal_report["status"] = status
        refusal_report["pages"] = []
        refusal_report["concern_codes"] = [code]
        refusal_report["counts"] = {
            key: 0 for key in _contract.SOURCE_COUNT_FIELDS
        }
        refusal_report["counts"]["concern_count"] = 1
        _contract.validate_source_report(refusal_report)

        retained_content = deepcopy(refusal_report)
        retained_content["pages"] = deepcopy(valid_report["pages"])
        retained_content["counts"]["page_count"] = 1
        _expect_contract_rejection(
            lambda retained_content=retained_content: (
                _contract.validate_source_report(retained_content)
            ),
            f"{status} source report retained page content",
        )
    refused_page_extra_concern = deepcopy(valid_report)
    refused_page_extra_concern["pages"][0]["concern_codes"] = [
        "running_region_geometry_ambiguous",
        "running_region_source_limit",
    ]
    refused_page_extra_concern["counts"]["concern_count"] = 2
    _expect_contract_rejection(
        lambda: _contract.validate_source_report(refused_page_extra_concern),
        "page refusal retained an extra concern",
    )
    unknown_report = deepcopy(valid_report)
    unknown_report["unknown"] = True
    wrong_report_version = {**valid_report, "report_version": "2.0"}
    wrong_report_policy = {**valid_report, "policy_id": "wrong"}
    wrong_report_count = deepcopy(valid_report)
    wrong_report_count["counts"]["page_count"] = 2
    for label, report in (
        ("unknown report key", unknown_report),
        ("wrong report version", wrong_report_version),
        ("wrong report policy", wrong_report_policy),
        ("wrong report count", wrong_report_count),
    ):
        _expect_contract_rejection(
            lambda report=report: _contract.validate_source_report(report), label
        )

    worker_plan = _contract.paired_worker_plan()
    expected_state_order = tuple(
        state
        for _target_id in _contract.PERFORMANCE_TARGETS
        for states in _contract.PAIRED_STATE_ORDER
        for state in states
    )
    if (
        len(worker_plan) != 20
        or tuple(record["worker_index"] for record in worker_plan) != tuple(range(20))
        or tuple(record["state"] for record in worker_plan) != expected_state_order
    ):
        raise SyntheticFixtureIntegrityError("paired worker plan drifted")
    observed_worker_plan: list[dict[str, Any]] = []

    def passing_worker(work: Mapping[str, Any]) -> Mapping[str, Any]:
        observed_worker_plan.append(deepcopy(dict(work)))
        baseline = 29.15 if work["target_id"] == "uber-earnings" else 46.76
        enabled = work["state"] == "on"
        return {
            "wall_seconds": baseline + (0.10 if enabled else 0.0),
            "raw_ru_maxrss": 10_000_000
            + (_contract.PEAK_MEMORY_DELTA_CEILING_BYTES if enabled else 0),
            "platform": "darwin",
            "exit_code": 0,
            "source_match": True,
            "code_match": True,
            "custody_match": True,
        }

    paired_summary = _contract.execute_paired_performance_harness(passing_worker)
    if (
        tuple(observed_worker_plan) != worker_plan
        or set(paired_summary) != set(_contract.PERFORMANCE_TARGETS)
        or any(not value["passed"] for value in paired_summary.values())
        or any(
            value["peak_rss_delta_bytes"]
            != _contract.PEAK_MEMORY_DELTA_CEILING_BYTES
            for value in paired_summary.values()
        )
    ):
        raise SyntheticFixtureIntegrityError("paired performance summary drifted")
    if _contract.inclusive_nearest_rank((5.0, 1.0, 4.0, 2.0, 3.0)) != 5.0:
        raise SyntheticFixtureIntegrityError("inclusive nearest-rank p95 drifted")
    clipped_summary = _contract.summarize_paired_performance(
        "uber-earnings",
        off_seconds=(10.0,) * 5,
        on_seconds=(9.0, 10.1, 10.2, 10.3, 10.4),
        off_rss_bytes=(100,) * 5,
        on_rss_bytes=(90, 101, 102, 103, 104),
    )
    if clipped_summary["clipped_seconds"][0] != 0.0:
        raise SyntheticFixtureIntegrityError("clipped paired overhead drifted")
    relative_failure = _contract.summarize_paired_performance(
        "uber-earnings",
        off_seconds=(10.0,) * 5,
        on_seconds=(10.6,) * 5,
        off_rss_bytes=(0,) * 5,
        on_rss_bytes=(0,) * 5,
    )
    fixed_failure = _contract.summarize_paired_performance(
        "uber-earnings",
        off_seconds=(100.0,) * 5,
        on_seconds=(101.5,) * 5,
        off_rss_bytes=(0,) * 5,
        on_rss_bytes=(0,) * 5,
    )
    rss_failure = _contract.summarize_paired_performance(
        "uber-earnings",
        off_seconds=(29.15,) * 5,
        on_seconds=(29.15,) * 5,
        off_rss_bytes=(0,) * 5,
        on_rss_bytes=(_contract.PEAK_MEMORY_DELTA_CEILING_BYTES + 1,) * 5,
    )
    if any(value["passed"] for value in (relative_failure, fixed_failure, rss_failure)):
        raise SyntheticFixtureIntegrityError("paired dual ceiling refusal drifted")
    if (
        _contract.normalize_ru_maxrss(67_108_864, "darwin") != 67_108_864
        or _contract.normalize_ru_maxrss(65_536, "linux") != 67_108_864
    ):
        raise SyntheticFixtureIntegrityError("ru_maxrss normalization drifted")
    _expect_contract_rejection(
        lambda: _contract.normalize_ru_maxrss(1, "win32"),
        "unsupported ru_maxrss platform",
    )

    def assert_worker_failure(mutation: str) -> None:
        calls: list[int] = []

        def worker(work: Mapping[str, Any]) -> Mapping[str, Any]:
            calls.append(work["worker_index"])
            if mutation == "raise":
                raise TimeoutError("injected timeout")
            result = dict(passing_worker(work))
            if mutation == "exit":
                result["exit_code"] = 1
            elif mutation == "bool_exit":
                result["exit_code"] = False
            elif mutation == "nonfinite":
                result["wall_seconds"] = math.inf
            else:
                result[mutation] = False
            return result

        _expect_contract_rejection(
            lambda: _contract.execute_paired_performance_harness(worker),
            f"paired worker {mutation}",
        )
        if calls != [0]:
            raise SyntheticFixtureIntegrityError(
                f"paired worker {mutation} was retried or not fail-fast"
            )

    for mutation in (
        "raise",
        "exit",
        "bool_exit",
        "nonfinite",
        "source_match",
        "code_match",
        "custody_match",
    ):
        assert_worker_failure(mutation)

    for stage in ("source_extraction", "running_region_projection"):
        for target_id in _contract.PERFORMANCE_TARGETS:
            protocol = _contract.isolated_measurement_protocol(stage, target_id)
            _contract.validate_isolated_measurement_protocol(protocol)
            bad_protocol = {**protocol, "latency_samples": 19}
            _expect_contract_rejection(
                lambda bad_protocol=bad_protocol: (
                    _contract.validate_isolated_measurement_protocol(bad_protocol)
                ),
                f"isolated {stage} sample count",
            )
            traced_latency = {**protocol, "tracemalloc_during_latency": True}
            _expect_contract_rejection(
                lambda traced_latency=traced_latency: (
                    _contract.validate_isolated_measurement_protocol(traced_latency)
                ),
                f"isolated {stage} traced latency",
            )
            missing_reset = {
                **protocol,
                "allocation_reset_peak_each_sample": False,
            }
            _expect_contract_rejection(
                lambda missing_reset=missing_reset: (
                    _contract.validate_isolated_measurement_protocol(missing_reset)
                ),
                f"isolated {stage} allocation reset",
            )
            latency_value = (
                _contract.ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
                if stage == "source_extraction"
                else _contract.ISOLATED_PROJECTION_P95_SECONDS
            )
            isolated_summary = _contract.summarize_isolated_measurement(
                stage,
                target_id,
                latency_seconds=(latency_value,) * 20,
                allocation_bytes=(
                    _contract.PEAK_MEMORY_DELTA_CEILING_BYTES,
                )
                * 5,
                warmup_successes=(True,) * 3,
                measured_output_successes=(True,) * 25,
                report_sizes=(
                    (_contract.MAX_REPORT_BYTES,) * 20
                    if stage == "source_extraction"
                    else ()
                ),
            )
            if not isolated_summary["passed"]:
                raise SyntheticFixtureIntegrityError(
                    f"isolated {stage} exact ceiling drifted"
                )
            _expect_contract_rejection(
                lambda stage=stage, target_id=target_id, latency_value=latency_value: (
                    _contract.summarize_isolated_measurement(
                        stage,
                        target_id,
                        latency_seconds=(latency_value,) * 20,
                        allocation_bytes=(1,) * 5,
                        warmup_successes=(True,) * 3,
                        measured_output_successes=(False,) + (True,) * 24,
                        report_sizes=((1,) * 20 if stage == "source_extraction" else ()),
                    )
                ),
                f"isolated {stage} output failure scope",
            )

    timed_output = {
        "processing": {
            "duration_ms": 99.0,
            "form_semantics": {
                "extraction_ms": 1.0,
                "projection_ms": 2.0,
                "total_ms": 3.0,
                "kept": "form",
            },
            "outline_structure": {
                "extraction_ms": 4.0,
                "projection_ms": 5.0,
                "total_ms": 9.0,
                "kept": "outline",
            },
            "running_regions": {
                "extraction_ms": 6.0,
                "projection_ms": 7.0,
                "total_ms": 13.0,
                "kept": "running",
            },
        },
        "unrelated_timing_ms": 123.0,
    }
    semantic_output = _contract.whole_output_semantic_payload(timed_output)
    if (
        semantic_output["unrelated_timing_ms"] != 123.0
        or semantic_output["processing"]["form_semantics"] != {"kept": "form"}
        or semantic_output["processing"]["outline_structure"]
        != {"kept": "outline"}
        or semantic_output["processing"]["running_regions"]
        != {"kept": "running"}
    ):
        raise SyntheticFixtureIntegrityError("whole-output timing paths drifted")
    semantic_report = _contract.source_report_semantic_payload(
        {"extraction_ms": 1.0, "projection_ms": 2.0}
    )
    if semantic_report != {"projection_ms": 2.0}:
        raise SyntheticFixtureIntegrityError("source-report timing path drifted")

    dependency_custody = {
        "manifests": {
            path: {"path": path, "size_bytes": 1, "sha256": "b" * 64}
            for path in _contract.DEPENDENCY_MANIFEST_PATHS
        },
        "python_packages": {
            distribution: {"distribution": distribution, "version": "1.0"}
            for distribution in _contract.DEPENDENCY_REQUIRED_PYTHON_PACKAGES
        },
        "local_tools": {
            name: {"name": name, "version": "1.0"}
            for name in _contract.DEPENDENCY_REQUIRED_LOCAL_TOOLS
        },
        "runtime": {"python_version": "3.13.5", "platform": "darwin"},
        "offline_environment": dict(_contract.OFFLINE_ENVIRONMENT),
    }

    def output_identity(marker: str) -> dict[str, Any]:
        return {"size_bytes": 1, "sha256": marker * 64}

    paired_outputs: dict[str, list[dict[str, Any]]] = {
        target_id: [] for target_id in _contract.PERFORMANCE_TARGETS
    }
    for target_id, pair_index, state in _contract.PAIRED_CASES:
        paired_outputs[target_id].append(
            {
                "target_id": target_id,
                "pair_index": pair_index,
                "state": state,
                "variants": {
                    variant: output_identity("c")
                    for variant in _contract.OUTPUT_VARIANTS
                },
            }
        )
    output_sizes = {
        "paired_samples": paired_outputs,
        "source_reports": {
            target_id: output_identity("d")
            for target_id in _contract.PERFORMANCE_TARGETS
        },
        "isolated_projection_outputs": {
            target_id: output_identity("e")
            for target_id in _contract.PERFORMANCE_TARGETS
        },
        "maximum_page_identity_json_bytes": 1,
        "maximum_running_descriptor_json_bytes": 1,
        "maximum_source_report_json_bytes": 1,
        "all_within_limits": True,
    }
    artifact = {key: {} for key in _contract.METRICS_ARTIFACT_FIELDS}
    artifact.update(
        {
            "schema_version": "1.0",
            "record_kind": "p03_us08_running_region_metrics",
            "story": "P03-US08",
            "status": "final_measurement_candidate",
            "generated_at": "2026-08-01T00:00:00Z",
            "retained_path": _contract.FINAL_METRICS_ARTIFACT_PATH,
            "semantic_sha256": "0" * 64,
            "measurement": {
                "maximum_page_workload": dict(_contract.MAXIMUM_PAGE_WORKLOAD)
            },
            "code_sha256": {
                "manifest_sha256": "0" * 64,
                "pre": {
                    "app/services/pipeline.py": {
                        "path": "app/services/pipeline.py",
                        "size_bytes": 1,
                        "sha256": "a" * 64,
                    }
                },
                "post": {
                    "app/services/pipeline.py": {
                        "path": "app/services/pipeline.py",
                        "size_bytes": 1,
                        "sha256": "a" * 64,
                    }
                },
                "pre_post_match": True,
            },
            "dependency_custody": dependency_custody,
            "output_sizes": output_sizes,
            "prior_failed_candidates": [],
            "failures": [],
            "aggregate": {"all_gates": True},
            "hosted_requests": 0,
            "hosted_tokens": 0,
            "hosted_cost_usd": 0,
        }
    )
    artifact["code_sha256"]["manifest_sha256"] = hashlib.sha256(
        _contract.strict_json_bytes(artifact["code_sha256"]["post"])
    ).hexdigest()
    artifact["semantic_sha256"] = hashlib.sha256(
        _contract.strict_json_bytes(
            _contract.metrics_artifact_semantic_payload(artifact)
        )
    ).hexdigest()
    _contract.validate_metrics_artifact_custody(artifact)
    mismatched_code_path = deepcopy(artifact)
    mismatched_code_path["code_sha256"]["post"]["app/services/pipeline.py"][
        "path"
    ] = "app/services/layout.py"
    mismatched_code_path["semantic_sha256"] = hashlib.sha256(
        _contract.strict_json_bytes(
            _contract.metrics_artifact_semantic_payload(mismatched_code_path)
        )
    ).hexdigest()
    _expect_contract_rejection(
        lambda: _contract.validate_metrics_artifact_custody(mismatched_code_path),
        "metrics code custody path mismatch",
    )
    dependency_drift = deepcopy(artifact)
    dependency_drift["dependency_custody"]["offline_environment"][
        "HF_HUB_OFFLINE"
    ] = "0"
    reversed_output_order = deepcopy(artifact)
    reversed_output_order["output_sizes"]["paired_samples"]["uber-earnings"].reverse()
    maximum_page_drift = deepcopy(artifact)
    maximum_page_drift["measurement"]["maximum_page_workload"][
        "indexed_comparison_count"
    ] -= 1
    final_output_over_cap = deepcopy(artifact)
    final_output_over_cap["output_sizes"]["maximum_page_identity_json_bytes"] = (
        _contract.MAX_PAGE_IDENTITY_BYTES + 1
    )
    final_output_over_cap["output_sizes"]["all_within_limits"] = False
    for label, mutated_artifact in (
        ("metrics dependency offline drift", dependency_drift),
        ("metrics output sample order drift", reversed_output_order),
        ("metrics maximum-page workload drift", maximum_page_drift),
        ("final metrics output over cap", final_output_over_cap),
    ):
        mutated_artifact["semantic_sha256"] = hashlib.sha256(
            _contract.strict_json_bytes(
                _contract.metrics_artifact_semantic_payload(mutated_artifact)
            )
        ).hexdigest()
        _expect_contract_rejection(
            lambda value=mutated_artifact: (
                _contract.validate_metrics_artifact_custody(value)
            ),
            label,
        )
    _expect_contract_rejection(
        lambda: _contract.validate_metrics_artifact_custody(
            artifact,
            existing_paths=([],),  # type: ignore[arg-type]
        ),
        "metrics artifact malformed existing path",
    )
    bool_hosted_usage = deepcopy(artifact)
    bool_hosted_usage["hosted_requests"] = False
    bool_hosted_usage["semantic_sha256"] = hashlib.sha256(
        _contract.strict_json_bytes(
            _contract.metrics_artifact_semantic_payload(bool_hosted_usage)
        )
    ).hexdigest()
    _expect_contract_rejection(
        lambda: _contract.validate_metrics_artifact_custody(bool_hosted_usage),
        "metrics artifact Boolean hosted usage",
    )
    _expect_contract_rejection(
        lambda: _contract.validate_metrics_artifact_custody(
            artifact,
            existing_paths=(_contract.FINAL_METRICS_ARTIFACT_PATH,),
        ),
        "final metrics artifact overwrite",
    )
    failed_artifact = deepcopy(artifact)
    failed_artifact.update(
        {
            "status": "failed_measurement_candidate",
            "retained_path": (
                "tracker/phase-03-layout/evidence/"
                "P03-US08-running-region-metrics-attempt-01-failed.json"
            ),
            "failures": [
                {
                    "type": "worker_timeout",
                    "stage": "paired_parser",
                    "target_id": "uber-earnings",
                    "pair_index": 0,
                    "state": "off",
                }
            ],
            "aggregate": {"all_gates": False},
        }
    )
    failed_artifact["semantic_sha256"] = hashlib.sha256(
        _contract.strict_json_bytes(
            _contract.metrics_artifact_semantic_payload(failed_artifact)
        )
    ).hexdigest()
    _contract.validate_metrics_artifact_custody(failed_artifact)
    _expect_contract_rejection(
        lambda: _contract.validate_metrics_artifact_custody(
            failed_artifact,
            existing_paths=(failed_artifact["retained_path"],),
        ),
        "failed metrics artifact overwrite",
    )
    skipped_attempt = deepcopy(failed_artifact)
    skipped_attempt["retained_path"] = skipped_attempt["retained_path"].replace(
        "attempt-01", "attempt-03"
    )
    skipped_attempt["semantic_sha256"] = hashlib.sha256(
        _contract.strict_json_bytes(
            _contract.metrics_artifact_semantic_payload(skipped_attempt)
        )
    ).hexdigest()
    _expect_contract_rejection(
        lambda: _contract.validate_metrics_artifact_custody(
            skipped_attempt,
            existing_paths=(failed_artifact["retained_path"],),
        ),
        "failed metrics artifact skipped attempt",
    )


def synthetic_self_check(*, verify_readers: bool = False) -> dict[str, str]:
    """Validate registry, hashes, contract negatives, all caps, and all states."""

    if len(SYNTHETIC_FIXTURE_IDS) != len(set(SYNTHETIC_FIXTURE_IDS)):
        raise SyntheticFixtureIntegrityError("fixture IDs are not unique")
    if set(SYNTHETIC_FIXTURE_IDS) != set(_BUILDERS):
        raise SyntheticFixtureIntegrityError("fixture registry/builders differ")
    covered = {
        capability for definition in SYNTHETIC_FIXTURES for capability in definition.covers
    }
    if covered != set(REQUIRED_SYNTHETIC_COVERAGE):
        missing = set(REQUIRED_SYNTHETIC_COVERAGE) - covered
        extra = covered - set(REQUIRED_SYNTHETIC_COVERAGE)
        raise SyntheticFixtureIntegrityError(
            f"required coverage differs; missing={sorted(missing)!r}; extra={sorted(extra)!r}"
        )
    first = fixture_hashes()
    second = fixture_hashes()
    if first != second:
        raise SyntheticFixtureIntegrityError("fixture rebuilding is not deterministic")
    if FROZEN_FIXTURE_SHA256 and dict(FROZEN_FIXTURE_SHA256) != first:
        raise SyntheticFixtureIntegrityError("frozen fixture hash drifted")
    if FROZEN_REGISTRY_SHA256 and registry_sha256() != FROZEN_REGISTRY_SHA256:
        raise SyntheticFixtureIntegrityError("frozen registry hash drifted")

    malformed = _malformed_contract_spec()["geometry"]
    for key in ("cross_unit", "nan", "zero_area", "out_of_page"):
        _expect_contract_rejection(
            lambda key=key: _contract.validate_bbox(
                malformed[key], page_width=612.0, page_height=792.0
            ),
            f"malformed bbox {key}",
        )
    hostile_values = (
        "<script>alert(1)</script>",
        "[7]#{page}",
        "[click](https://example.invalid)",
        "![image](x)",
        "%3Cscript%3E",
        "&lt;script&gt;",
        "7\r\n8",
        "7\x00\t8",
        "7\x858",
        "\u202e7\u2069",
        "7\u20288",
        "7\u20298",
        "A" * 257,
        "\ufdd0",
        "\ud800",
        "\n\t7\r",
        "\x007",
        "\x857",
        "\u20287",
    )
    for index, value in enumerate(hostile_values):
        _expect_contract_rejection(
            lambda value=value: _contract.normalize_embedded_label(value),
            f"hostile label {index}",
        )
    if _contract.normalize_embedded_label(" 7 ") != "7":
        raise SyntheticFixtureIntegrityError("embedded edge-whitespace normalization drifted")
    if _contract.normalize_embedded_label("\u20037\u00a0") != "7":
        raise SyntheticFixtureIntegrityError(
            "safe Unicode edge-whitespace normalization drifted"
        )
    for counter in _RESOURCE_RULES:
        exact = build_resource_boundary_witness(counter)
        over = build_resource_boundary_witness(counter, maximum_plus_one=True)
        if exact.execute() is not True or over.execute() is not False:
            raise SyntheticFixtureIntegrityError(f"resource boundary {counter} drifted")
    for name in (
        "source_extraction_deadline",
        "projection_page_deadline",
        "projection_document_deadline",
    ):
        if not build_deadline_witness(name).execute() or build_deadline_witness(
            name, maximum_plus_one=True
        ).execute():
            raise SyntheticFixtureIntegrityError(f"deadline boundary {name} drifted")
    for witness in build_state_machine_witnesses():
        result = witness.execute()
        if result != witness.committed:
            raise SyntheticFixtureIntegrityError(f"state witness {witness.name} drifted")
    _execute_contract_specs()
    _contract.contract_self_check()
    if verify_readers:
        verify_pdf_readers()
    return first


__all__ = [
    "FROZEN_FIXTURE_SHA256",
    "FROZEN_REGISTRY_SHA256",
    "REQUIRED_SYNTHETIC_COVERAGE",
    "SYNTHETIC_FIXTURES",
    "SYNTHETIC_FIXTURES_BY_ID",
    "SYNTHETIC_FIXTURE_IDS",
    "SYNTHETIC_THRESHOLDS",
    "DeadlineWitness",
    "PageLabelSpec",
    "ResourceBoundaryWitness",
    "StateMachineWitness",
    "SyntheticFixtureDefinition",
    "SyntheticFixtureIntegrityError",
    "build_deadline_witness",
    "build_resource_boundary_witness",
    "build_state_machine_witnesses",
    "build_synthetic_fixture",
    "fixture_hashes",
    "registry_sha256",
    "synthetic_self_check",
    "verify_pdf_readers",
]


if __name__ == "__main__":  # pragma: no cover - local readiness convenience
    for fixture_id, digest in synthetic_self_check(verify_readers=True).items():
        print(f"{fixture_id} {digest}")
    print(f"registry {registry_sha256()}")
