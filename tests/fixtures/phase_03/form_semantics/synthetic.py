"""Deterministic readiness fixtures for P03-US06 form semantics.

The fixtures in this module are test inputs, not production policy.  Small PDF
documents are assembled directly so their bytes contain no timestamps, random
IDs, or generator-specific metadata.  Geometry, transform, key-value, and
resource-boundary cases use low-level source-evidence dictionaries so tests can
exercise one policy boundary without first reverse engineering PDF drawing
operators.

Every builder returns a fresh payload.  Production modules must not import this
test-only package.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


FixtureKind = Literal[
    "pdf",
    "acroform_graph_spec",
    "geometry_spec",
    "key_value_spec",
    "semantic_graph_spec",
    "transform_spec",
]

_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_DOCUMENT_ID = b"50303355533036464f524d464958545552"
_PAGE_WIDTH = 300.0
_PAGE_HEIGHT = 300.0
_BOUNDARY_EPSILON = 0.001


SYNTHETIC_THRESHOLDS: Mapping[str, int | float] = MappingProxyType(
    {
        "axis_alignment_pt": 0.15,
        "endpoint_snap_pt": 0.15,
        "closure_gap_pt": 0.15,
        "control_min_side_pt": 6.0,
        "control_max_side_pt": 24.0,
        "control_min_aspect_ratio": 0.65,
        "control_max_aspect_ratio": 1.55,
        "control_min_edge_coverage": 0.95,
        "control_interior_inset_pt": 1.0,
        "control_label_min_gap_pt": 0.5,
        "control_label_max_gap_pt": 96.0,
        "control_label_tie_pt": 0.5,
        "control_label_max_below_pt": 4.0,
        "control_mark_min_combined_length": 0.35,
        "control_mark_min_horizontal_span": 0.35,
        "control_mark_min_vertical_span": 0.35,
        "control_mark_max_fill_coverage": 0.50,
        "unlabeled_control_min_labeled_peers": 3,
        "unlabeled_control_size_tolerance_pt": 0.15,
        "unlabeled_control_max_pitch_pt": 24.0,
        "field_label_max_above_pt": 12.0,
        "field_inline_top_tolerance_pt": 1.25,
        "field_inline_min_height_pt": 6.0,
        "field_inline_max_height_pt": 24.0,
        "field_inline_min_width_pt": 24.0,
        "kv_min_gap_pt": 2.0,
        "kv_max_gap_absolute_pt": 160.0,
        "kv_max_gap_page_fraction": 0.35,
        "kv_top_tolerance_pt": 1.25,
        "kv_height_tolerance_pt": 2.0,
        "kv_anchor_tolerance_pt": 2.0,
        "kv_min_cadence_pt": 4.0,
        "kv_max_cadence_pt": 30.0,
        "kv_min_rows": 3,
        "acroform_max_depth": 32,
        "acroform_max_nodes": 10_000,
        "acroform_max_kids_per_node": 256,
        "acroform_max_dictionary_entries": 256,
        "acroform_max_visited_references": 32_768,
        "acroform_max_resolution_steps": 65_536,
        "acroform_max_object_bytes": 256 * 1024,
        "acroform_max_tree_bytes": 8 * 1024 * 1024,
        "acroform_max_name_bytes": 256,
        "acroform_max_string_bytes": 16 * 1024,
        "max_annotations_widgets_per_page": 2_048,
        "max_annotations_widgets_per_document": 10_000,
        "max_source_identities_per_semantic_record": 64,
        "max_groups_per_page": 256,
        "max_groups_per_document": 2_048,
        "max_fields_per_group": 128,
        "max_value_regions_per_group": 128,
        "max_controls_per_group": 256,
        "max_labels_per_group": 256,
        "max_key_value_pairs_per_group": 32,
        "max_fields_controls_pairs_per_page": 2_048,
        "max_fields_controls_pairs_per_document": 10_000,
        "max_semantic_records_per_page": 8_192,
        "max_semantic_records_per_document": 32_768,
        "max_relationships_per_page": 32_768,
        "max_relationships_per_document": 65_536,
    }
)


REQUIRED_SYNTHETIC_COVERAGE = (
    "static_checked_control",
    "static_unchecked_control",
    "selected_checkbox",
    "unselected_checkbox",
    "selected_radio",
    "unselected_radio",
    "pushbutton_exclusion",
    "explicit_not_applicable",
    "present_field",
    "ambiguous_field",
    "inherited_widget_kids",
    "mixed_static_interactive",
    "orphan_widget",
    "cyclic_acroform",
    "deep_acroform",
    "over_limit_acroform",
    "semantic_record_page_limit",
    "semantic_record_document_limit",
    "relationship_page_limit",
    "relationship_document_limit",
    "endpoint_threshold",
    "closure_threshold",
    "aspect_threshold",
    "label_distance_threshold",
    "mark_threshold",
    "shared_edge_phantom",
    "duplicate_geometry",
    "rotated_crop",
    "invalid_transform",
    "kv_min_gap",
    "kv_max_gap",
    "kv_anchor",
    "kv_cadence",
    "kv_tie",
    "kv_two_row",
    "kv_borderless_table",
    "kv_cross_page",
)


def key_value_max_gap(page_width: float) -> float:
    """Return the accepted dynamic horizontal key/value gap ceiling."""

    if not math.isfinite(page_width) or page_width <= 0:
        raise ValueError("page_width must be finite and positive")
    return min(
        float(SYNTHETIC_THRESHOLDS["kv_max_gap_absolute_pt"]),
        float(SYNTHETIC_THRESHOLDS["kv_max_gap_page_fraction"]) * page_width,
    )


@dataclass(frozen=True, slots=True)
class SyntheticFixtureDefinition:
    """Registry metadata for one deterministic readiness fixture."""

    fixture_id: str
    kind: FixtureKind
    purpose: str
    covers: tuple[str, ...]


class SyntheticFixtureIntegrityError(RuntimeError):
    """Raised when registry coverage or deterministic fixture bytes drift."""


def _stream(data: bytes, *, entries: bytes = b"") -> bytes:
    dictionary = b"<<"
    if entries:
        dictionary += b" " + entries.strip()
    dictionary += b" /Length " + str(len(data)).encode("ascii") + b" >>"
    return dictionary + b"\nstream\n" + data + b"\nendstream"


def _appearance_stream(commands: bytes) -> bytes:
    return _stream(
        commands,
        entries=(
            b"/Type /XObject /Subtype /Form /FormType 1 "
            b"/BBox [0 0 12 12] /Resources << >>"
        ),
    )


def _assemble_pdf(objects: Sequence[bytes]) -> bytes:
    """Serialize fixed indirect objects with a deterministic classic xref."""

    parts = [_PDF_HEADER]
    offsets = [0]
    cursor = len(_PDF_HEADER)
    for object_number, body in enumerate(objects, start=1):
        serialized = (
            f"{object_number} 0 obj\n".encode("ascii")
            + body
            + b"\nendobj\n"
        )
        offsets.append(cursor)
        parts.append(serialized)
        cursor += len(serialized)

    xref_offset = cursor
    parts.extend(
        [
            f"xref\n0 {len(objects) + 1}\n".encode("ascii"),
            b"0000000000 65535 f \n",
            *(
                f"{offset:010d} 00000 n \n".encode("ascii")
                for offset in offsets[1:]
            ),
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
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        ]
    )
    return b"".join(parts)


def _font() -> bytes:
    return b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def _base_page(
    *,
    content_object: int,
    font_object: int,
    annotations: Sequence[int] = (),
) -> bytes:
    body = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
        b"/Resources << /Font << /F1 "
        + str(font_object).encode("ascii")
        + b" 0 R >> >> /Contents "
        + str(content_object).encode("ascii")
        + b" 0 R"
    )
    if annotations:
        body += b" /Annots [" + b" ".join(
            f"{number} 0 R".encode("ascii") for number in annotations
        ) + b"]"
    return body + b" >>"


def _static_controls_pdf() -> bytes:
    content = b"\n".join(
        (
            b"q 1 w 0 G",
            b"72 230 12 12 re S",
            b"72 190 12 12 re S",
            b"73 191 m 83 201 l S",
            b"73 201 m 83 191 l S",
            b"Q",
            b"BT /F1 10 Tf 90 233 Td (Unchecked source control) Tj ET",
            b"BT /F1 10 Tf 90 193 Td (Checked source control) Tj ET",
        )
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _base_page(content_object=4, font_object=5),
        _stream(content),
        _font(),
    )
    return _assemble_pdf(objects)


def _static_fields_pdf() -> bytes:
    content = b"\n".join(
        (
            b"q 1 w 0 G",
            b"130 230 100 20 re S",
            b"130 180 100 20 re S",
            b"Q",
            b"BT /F1 10 Tf 72 236 Td (Name:) Tj ET",
            b"BT /F1 10 Tf 136 236 Td (ALPHA) Tj ET",
            b"BT /F1 10 Tf 72 186 Td (Account:) Tj ET",
            b"BT /F1 10 Tf 72 174 Td (Reference:) Tj ET",
        )
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _base_page(content_object=4, font_object=5),
        _stream(content),
        _font(),
    )
    return _assemble_pdf(objects)


def _interactive_controls_pdf() -> bytes:
    content = b"\n".join(
        (
            b"BT /F1 9 Tf 70 258 Td (Selected checkbox) Tj ET",
            b"BT /F1 9 Tf 70 223 Td (Unselected checkbox) Tj ET",
            b"BT /F1 9 Tf 70 188 Td (Selected radio) Tj ET",
            b"BT /F1 9 Tf 70 153 Td (Unselected radio) Tj ET",
            b"BT /F1 9 Tf 70 118 Td (Pushbutton excluded) Tj ET",
            b"BT /F1 9 Tf 70 83 Td (Explicit not applicable) Tj ET",
        )
    )
    off = _appearance_stream(b"q 1 w 0 G 0.5 0.5 11 11 re S Q")
    checked = _appearance_stream(
        b"q 1 w 0 G 0.5 0.5 11 11 re S 2 2 m 10 10 l S "
        b"2 10 m 10 2 l S Q"
    )
    radio_off = _appearance_stream(
        b"q 1 w 0 G 6 11 m 8.761 11 11 8.761 11 6 c "
        b"11 3.239 8.761 1 6 1 c 3.239 1 1 3.239 1 6 c "
        b"1 8.761 3.239 11 6 11 c S Q"
    )
    radio_on = _appearance_stream(
        b"q 1 w 0 G 6 11 m 8.761 11 11 8.761 11 6 c "
        b"11 3.239 8.761 1 6 1 c 3.239 1 1 3.239 1 6 c "
        b"1 8.761 3.239 11 6 11 c S 6 8 m 7.105 8 8 7.105 8 6 c "
        b"8 4.895 7.105 4 6 4 c 4.895 4 4 4.895 4 6 c "
        b"4 7.105 4.895 8 6 8 c f Q"
    )
    push = _appearance_stream(
        b"q 0.9 g 0 0 12 12 re f 0 G 0.5 0.5 11 11 re S Q"
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 6 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _base_page(
            content_object=4,
            font_object=5,
            annotations=(7, 8, 10, 11, 12, 13),
        ),
        _stream(content),
        _font(),
        (
            b"<< /Fields [7 0 R 8 0 R 9 0 R 12 0 R 13 0 R] "
            b"/NeedAppearances false /DA (/F1 9 Tf 0 g) "
            b"/DR << /Font << /F1 5 0 R >> >> >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (selected-checkbox) "
            b"/Rect [50 250 62 262] /P 3 0 R /F 4 /V /Yes /AS /Yes "
            b"/AP << /N << /Off 14 0 R /Yes 15 0 R >> >> >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn "
            b"/T (unselected-checkbox) /Rect [50 215 62 227] /P 3 0 R /F 4 "
            b"/V /Off /AS /Off "
            b"/AP << /N << /Off 14 0 R /Yes 15 0 R >> >> >>"
        ),
        (
            b"<< /FT /Btn /Ff 32768 /T (inherited-radio) /V /ChoiceA "
            b"/Kids [10 0 R 11 0 R] >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 9 0 R "
            b"/Rect [50 180 62 192] /P 3 0 R /F 4 /AS /ChoiceA "
            b"/AP << /N << /Off 16 0 R /ChoiceA 17 0 R >> >> >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 9 0 R "
            b"/Rect [50 145 62 157] /P 3 0 R /F 4 /AS /Off "
            b"/AP << /N << /Off 16 0 R /ChoiceB 17 0 R >> >> >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn /Ff 65536 "
            b"/T (excluded-pushbutton) /Rect [50 110 62 122] /P 3 0 R /F 4 "
            b"/AP << /N 18 0 R >> >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn "
            b"/T (explicit-not-applicable) /Rect [50 75 62 87] /P 3 0 R /F 4 "
            b"/V /not_applicable /AS /not_applicable "
            b"/AP << /N << /Off 14 0 R /not_applicable 15 0 R >> >> >>"
        ),
        off,
        checked,
        radio_off,
        radio_on,
        push,
    )
    return _assemble_pdf(objects)


def _mixed_form_pdf() -> bytes:
    content = b"\n".join(
        (
            b"q 1 w 0 G 50 230 12 12 re S Q",
            b"BT /F1 9 Tf 70 233 Td (Static unchecked) Tj ET",
            b"BT /F1 9 Tf 70 193 Td (Interactive checked) Tj ET",
        )
    )
    off = _appearance_stream(b"q 1 w 0 G 0.5 0.5 11 11 re S Q")
    checked = _appearance_stream(
        b"q 1 w 0 G 0.5 0.5 11 11 re S 2 2 m 10 10 l S Q"
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 6 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _base_page(content_object=4, font_object=5, annotations=(7,)),
        _stream(content),
        _font(),
        b"<< /Fields [7 0 R] /DA (/F1 9 Tf 0 g) >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (mixed-widget) "
            b"/Rect [50 190 62 202] /P 3 0 R /V /Yes /AS /Yes "
            b"/AP << /N << /Off 8 0 R /Yes 9 0 R >> >> >>"
        ),
        off,
        checked,
    )
    return _assemble_pdf(objects)


def _orphan_widget_pdf() -> bytes:
    content = b"BT /F1 9 Tf 70 233 Td (Orphan widget) Tj ET"
    off = _appearance_stream(b"q 1 w 0 G 0.5 0.5 11 11 re S Q")
    checked = _appearance_stream(
        b"q 1 w 0 G 0.5 0.5 11 11 re S 2 2 m 10 10 l S Q"
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _base_page(content_object=4, font_object=5, annotations=(6,)),
        _stream(content),
        _font(),
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (orphan-widget) "
            b"/Rect [50 230 62 242] /P 3 0 R /V /Off /AS /Off "
            b"/AP << /N << /Off 7 0 R /Yes 8 0 R >> >> >>"
        ),
        off,
        checked,
    )
    return _assemble_pdf(objects)


def _cyclic_acroform_pdf() -> bytes:
    content = b"BT /F1 9 Tf 70 233 Td (Cyclic field tree) Tj ET"
    off = _appearance_stream(b"q 1 w 0 G 0.5 0.5 11 11 re S Q")
    checked = _appearance_stream(
        b"q 1 w 0 G 0.5 0.5 11 11 re S 2 2 m 10 10 l S Q"
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 6 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _base_page(content_object=4, font_object=5, annotations=(8,)),
        _stream(content),
        _font(),
        b"<< /Fields [7 0 R] /DA (/F1 9 Tf 0 g) >>",
        (
            b"<< /FT /Btn /T (cycle-parent) /Kids [8 0 R] "
            b"/Parent 8 0 R /V /Off >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 7 0 R /Kids [7 0 R] "
            b"/Rect [50 230 62 242] /P 3 0 R /AS /Off "
            b"/AP << /N << /Off 9 0 R /Yes 10 0 R >> >> >>"
        ),
        off,
        checked,
    )
    return _assemble_pdf(objects)


def _pdf_fixture_payload(
    pdf_bytes: bytes,
    *,
    expected_interactivity: str,
    records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "pdf_bytes": pdf_bytes,
        "page_count": 1,
        "page_size": (_PAGE_WIDTH, _PAGE_HEIGHT),
        "expected_interactivity": expected_interactivity,
        "expected_records": tuple(dict(record) for record in records),
    }


def _build_static_controls() -> dict[str, object]:
    return _pdf_fixture_payload(
        _static_controls_pdf(),
        expected_interactivity="static",
        records=(
            {
                "record_key": "static-unchecked",
                "bbox": (72.0, 58.0, 12.0, 12.0),
                "control_type": "checkbox",
                "origin": "static_vector",
                "state": "unchecked",
                "label": "Unchecked source control",
            },
            {
                "record_key": "static-checked",
                "bbox": (72.0, 98.0, 12.0, 12.0),
                "control_type": "checkbox",
                "origin": "static_vector",
                "state": "checked",
                "label": "Checked source control",
                "interior_mark": "two-diagonal-x",
            },
        ),
    )


def _build_static_fields() -> dict[str, object]:
    return _pdf_fixture_payload(
        _static_fields_pdf(),
        expected_interactivity="static",
        records=(
            {
                "record_key": "present-name",
                "field_bbox": (130.0, 50.0, 100.0, 20.0),
                "value_bbox": (130.0, 50.0, 100.0, 20.0),
                "excluded_label_text": ("Name:",),
                "value": "ALPHA",
                "value_state": "present",
            },
            {
                "record_key": "ambiguous-reference",
                "field_bbox": (130.0, 100.0, 100.0, 20.0),
                "value_bbox": (130.0, 100.0, 100.0, 20.0),
                "competing_labels": ("Account:", "Reference:"),
                "value": None,
                "value_state": "ambiguous",
                "concern_code": "form_value_state_ambiguous",
            },
        ),
    )


def _interactive_expected_records() -> tuple[dict[str, object], ...]:
    return (
        {
            "record_key": "selected-checkbox",
            "object_ref": "7 0 R",
            "control_type": "checkbox",
            "state": "checked",
            "field_value": "Yes",
            "appearance_state": "Yes",
        },
        {
            "record_key": "unselected-checkbox",
            "object_ref": "8 0 R",
            "control_type": "checkbox",
            "state": "unchecked",
            "field_value": "Off",
            "appearance_state": "Off",
        },
        {
            "record_key": "selected-radio",
            "parent_object_ref": "9 0 R",
            "object_ref": "10 0 R",
            "control_type": "radio",
            "state": "checked",
            "inherited_field_type": True,
        },
        {
            "record_key": "unselected-radio",
            "parent_object_ref": "9 0 R",
            "object_ref": "11 0 R",
            "control_type": "radio",
            "state": "unchecked",
            "inherited_field_type": True,
        },
        {
            "record_key": "excluded-pushbutton",
            "object_ref": "12 0 R",
            "button_flags": 65_536,
            "expected_action": "exclude",
        },
        {
            "record_key": "explicit-not-applicable",
            "object_ref": "13 0 R",
            "control_type": "checkbox",
            "state": "not_applicable",
            "field_value": "not_applicable",
            "appearance_state": "not_applicable",
        },
    )


def _build_interactive_controls() -> dict[str, object]:
    return _pdf_fixture_payload(
        _interactive_controls_pdf(),
        expected_interactivity="interactive",
        records=_interactive_expected_records(),
    )


def _build_inherited_widget_kids() -> dict[str, object]:
    return {
        **_pdf_fixture_payload(
            _interactive_controls_pdf(),
            expected_interactivity="interactive",
            records=_interactive_expected_records()[2:4],
        ),
        "field_tree": {
            "parent_object_ref": "9 0 R",
            "parent_field_type": "Btn",
            "parent_button_flags": 32_768,
            "parent_value": "ChoiceA",
            "kid_object_refs": ("10 0 R", "11 0 R"),
            "kids_omit_field_type": True,
        },
    }


def _build_mixed_form() -> dict[str, object]:
    return _pdf_fixture_payload(
        _mixed_form_pdf(),
        expected_interactivity="mixed",
        records=(
            {
                "record_key": "mixed-static",
                "origin": "static_vector",
                "state": "unchecked",
            },
            {
                "record_key": "mixed-widget",
                "object_ref": "7 0 R",
                "origin": "interactive_widget",
                "state": "checked",
            },
        ),
    )


def _build_orphan_widget() -> dict[str, object]:
    return _pdf_fixture_payload(
        _orphan_widget_pdf(),
        expected_interactivity="unknown",
        records=(
            {
                "record_key": "orphan-widget",
                "object_ref": "6 0 R",
                "in_page_annotations": True,
                "in_acroform_fields": False,
                "expected_action": "fail_closed",
            },
        ),
    )


def _build_cyclic_acroform() -> dict[str, object]:
    payload = _pdf_fixture_payload(
        _cyclic_acroform_pdf(),
        expected_interactivity="unknown",
        records=(
            {
                "record_key": "cyclic-field-tree",
                "cycle_object_refs": ("7 0 R", "8 0 R", "7 0 R"),
                "expected_action": "fail_closed",
                "concern_code": "form_source_evidence_unavailable",
            },
        ),
    )
    payload["reader_check"] = "catalog_and_page_only"
    return payload


_ACROFORM_RESOURCE_LIMITS = (
    ("dictionary-entries", "acroform_max_dictionary_entries"),
    ("visited-references", "acroform_max_visited_references"),
    ("resolution-steps", "acroform_max_resolution_steps"),
    ("object-bytes", "acroform_max_object_bytes"),
    ("tree-bytes", "acroform_max_tree_bytes"),
    ("name-bytes", "acroform_max_name_bytes"),
    ("string-bytes", "acroform_max_string_bytes"),
)


def _acroform_resource_case_definitions() -> dict[str, Mapping[str, object]]:
    cases: dict[str, Mapping[str, object]] = {}
    for resource_name, threshold_name in _ACROFORM_RESOURCE_LIMITS:
        limit = int(SYNTHETIC_THRESHOLDS[threshold_name])
        cases[f"{resource_name}-exact"] = MappingProxyType(
            {
                "topology": "accounting_probe",
                "counter": resource_name.replace("-", "_"),
                "observed": limit,
                "expected": "accepted",
            }
        )
        cases[f"{resource_name}-over-limit"] = MappingProxyType(
            {
                "topology": "accounting_probe",
                "counter": resource_name.replace("-", "_"),
                "observed": limit + 1,
                "expected": "over_limit",
                "violated_limit": threshold_name,
            }
        )
    return cases


ACROFORM_GRAPH_CASES: Mapping[str, Mapping[str, object]] = MappingProxyType(
    {
        "depth-exact": MappingProxyType(
            {
                "topology": "chain",
                "observed_depth": 32,
                "root_depth": 0,
                "depth_unit": "kids_edges",
                "expected": "accepted",
            }
        ),
        "depth-over-limit": MappingProxyType(
            {
                "topology": "chain",
                "observed_depth": 33,
                "root_depth": 0,
                "depth_unit": "kids_edges",
                "expected": "over_limit",
                "violated_limit": "acroform_max_depth",
            }
        ),
        "nodes-exact": MappingProxyType(
            {
                "topology": "independent_roots",
                "node_count": 10_000,
                "expected": "accepted",
            }
        ),
        "nodes-over-limit": MappingProxyType(
            {
                "topology": "independent_roots",
                "node_count": 10_001,
                "expected": "over_limit",
                "violated_limit": "acroform_max_nodes",
            }
        ),
        "kids-exact": MappingProxyType(
            {
                "topology": "wide_parent",
                "kid_count": 256,
                "expected": "accepted",
            }
        ),
        "kids-over-limit": MappingProxyType(
            {
                "topology": "wide_parent",
                "kid_count": 257,
                "expected": "over_limit",
                "violated_limit": "acroform_max_kids_per_node",
            }
        ),
        **_acroform_resource_case_definitions(),
    }
)


def _excluded_pushbutton_node(
    object_id: str,
    *,
    parent_id: str | None = None,
    kid_ids: tuple[str, ...] = (),
    inherits_type: bool = False,
) -> dict[str, object]:
    return {
        "object_id": object_id,
        "parent_id": parent_id,
        "kid_ids": kid_ids,
        "field_type": None if inherits_type else "Btn",
        "field_flags": None if inherits_type else 1 << 16,
        "is_widget": False,
        "expected_action": "exclude_pushbutton",
    }


def _split_accounted_bytes(total: int, object_count: int) -> tuple[int, ...]:
    """Split a tree byte target without colliding with the object byte cap."""

    base, remainder = divmod(total, object_count)
    sizes = tuple(
        base + (1 if index < remainder else 0)
        for index in range(object_count)
    )
    if sum(sizes) != total:
        raise SyntheticFixtureIntegrityError("tree byte split drifted")
    if max(sizes) >= int(SYNTHETIC_THRESHOLDS["acroform_max_object_bytes"]):
        raise SyntheticFixtureIntegrityError(
            "tree byte probe collides with the per-object byte limit"
        )
    return sizes


def _stream_accounting_object(
    object_id: str,
    accounted_bytes: int,
) -> dict[str, object]:
    """Build an opaque stream whose AFOB-v1 local size is exact."""

    dictionary_cost = 2
    if accounted_bytes < dictionary_cost:
        raise ValueError("accounted stream size is smaller than its dictionary")
    return {
        "object_id": object_id,
        "pdf_type": "stream",
        "dictionary_entries": (),
        "encoded_stream_bytes": b"X" * (accounted_bytes - dictionary_cost),
        "accounted_bytes": accounted_bytes,
    }


def _dictionary_accounted_bytes(
    entries: Sequence[tuple[str, int]],
) -> int:
    """Return AFOB-v1 bytes for a dictionary of name/integer entries."""

    return 2 + len(entries) + sum(
        1 + len(key.encode("utf-8")) + len(str(value).encode("ascii"))
        for key, value in entries
    )


def _build_acroform_accounting_probe(
    counter: str,
    observed: int,
) -> dict[str, object]:
    """Build a typed, isolated AcroForm accounting input."""

    max_object_bytes = int(SYNTHETIC_THRESHOLDS["acroform_max_object_bytes"])
    widget_count = 0
    if counter == "dictionary_entries":
        entries = tuple(
            (f"K{index:05d}", index) for index in range(observed)
        )
        accounted_bytes = _dictionary_accounted_bytes(entries)
        objects: tuple[dict[str, object], ...] = (
            {
                "object_id": "probe-dictionary",
                "pdf_type": "dictionary",
                "entries": entries,
                "accounted_bytes": accounted_bytes,
            },
        )
        traversal = {
            "distinct_visited_references": 1,
            "resolution_steps": 1,
            "field_nodes": 1,
        }
        tree_bytes = accounted_bytes
    elif counter == "visited_references":
        field_nodes = 8_192
        property_references = observed - field_nodes
        if property_references < 0:
            raise SyntheticFixtureIntegrityError(
                "visited-reference probe has fewer references than fields"
            )
        objects = ()
        traversal = {
            "kind": "unique_pushbutton_fields",
            "field_nodes": field_nodes,
            "field_reference_count": field_nodes,
            "unique_property_reference_count": property_references,
            "base_property_slots": ("FT", "Ff", "T"),
            "extra_unique_property_references": (
                property_references - field_nodes * 3
            ),
            "extra_property_slot": "V",
            "property_identity": "unique",
            "distinct_visited_references": observed,
            "resolution_steps": observed,
            "all_widgets": False,
            "field_flags": 1 << 16,
        }
        tree_bytes = 2 * 1024 * 1024
    elif counter == "resolution_steps":
        field_nodes = 8_192
        unique_properties = 7
        extra_cached_dereferences = observed - field_nodes * 8
        widget_count = extra_cached_dereferences
        objects = ()
        traversal = {
            "kind": "shared_pushbutton_property_references",
            "field_nodes": field_nodes,
            "field_reference_count": field_nodes,
            "followed_property_slots": (
                "FT",
                "Ff",
                "V",
                "T",
                "AS",
                "AP",
                "AP/N",
            ),
            "property_identity": "one_shared_target_per_slot",
            "distinct_visited_references": field_nodes + unique_properties,
            "resolution_steps": observed,
            "extra_cached_dereferences": extra_cached_dereferences,
            "extra_dereference_reason": "page_annotation_alias",
            "widget_count": widget_count,
            "page_annotation_reference_count": widget_count,
            "field_flags": 1 << 16,
        }
        tree_bytes = 1024 * 1024
    elif counter == "object_bytes":
        objects = (_stream_accounting_object("probe-stream", observed),)
        traversal = {
            "distinct_visited_references": 1,
            "resolution_steps": 1,
            "field_nodes": 1,
        }
        tree_bytes = observed
    elif counter == "tree_bytes":
        sizes = _split_accounted_bytes(observed, 33)
        objects = tuple(
            _stream_accounting_object(f"probe-stream-{index:02d}", size)
            for index, size in enumerate(sizes)
        )
        traversal = {
            "distinct_visited_references": len(objects),
            "resolution_steps": len(objects),
            "field_nodes": 1,
        }
        tree_bytes = observed
    elif counter == "name_bytes":
        raw_bytes = b"N" * observed
        objects = (
            {
                "object_id": "probe-name",
                "pdf_type": "name",
                "raw_bytes": raw_bytes,
                "payload_bytes": len(raw_bytes),
                "accounted_bytes": 1 + len(raw_bytes),
            },
        )
        traversal = {
            "distinct_visited_references": 1,
            "resolution_steps": 1,
            "field_nodes": 1,
        }
        tree_bytes = 1 + observed
    elif counter == "string_bytes":
        raw_bytes = b"S" * observed
        objects = (
            {
                "object_id": "probe-string",
                "pdf_type": "string",
                "raw_bytes": raw_bytes,
                "payload_bytes": len(raw_bytes),
                "accounted_bytes": 2 + len(raw_bytes),
            },
        )
        traversal = {
            "distinct_visited_references": 1,
            "resolution_steps": 1,
            "field_nodes": 1,
        }
        tree_bytes = 2 + observed
    else:  # pragma: no cover - registry is closed and self-checked
        raise SyntheticFixtureIntegrityError(
            f"unsupported AcroForm resource counter {counter!r}"
        )

    object_sizes = tuple(int(item["accounted_bytes"]) for item in objects)
    return {
        "accounting_policy": "afob-v1",
        "counter": counter,
        "observed": observed,
        "objects": objects,
        "traversal": traversal,
        "non_target_counts": {
            "max_dictionary_entries": (
                observed if counter == "dictionary_entries" else 4
            ),
            "distinct_visited_references": traversal[
                "distinct_visited_references"
            ],
            "resolution_steps": traversal["resolution_steps"],
            "field_nodes": traversal["field_nodes"],
            "widgets": widget_count,
            "max_object_bytes": max(object_sizes, default=128),
            "tree_bytes": tree_bytes,
            "max_name_bytes": observed if counter == "name_bytes" else 8,
            "max_string_bytes": (
                observed if counter == "string_bytes" else 16
            ),
        },
        "per_object_limit": max_object_bytes,
    }


def build_acroform_graph(case_id: str) -> dict[str, object]:
    """Materialize one exact/max+1 AcroForm graph on demand."""

    if case_id not in ACROFORM_GRAPH_CASES:
        raise KeyError(
            f"unknown AcroForm graph case {case_id!r}; expected one of "
            f"{tuple(ACROFORM_GRAPH_CASES)}"
        )
    case = ACROFORM_GRAPH_CASES[case_id]
    topology = str(case["topology"])
    nodes: list[dict[str, object]] = []
    root_ids: tuple[str, ...]
    resource_probe: dict[str, object] | None = None

    if topology == "chain":
        observed_depth = int(case["observed_depth"])
        node_count = observed_depth + 1
        for index in range(node_count):
            node_id = f"field-{index:05d}"
            child_id = (
                f"field-{index + 1:05d}" if index + 1 < node_count else None
            )
            nodes.append(
                _excluded_pushbutton_node(
                    node_id,
                    parent_id=(
                        f"field-{index - 1:05d}" if index > 0 else None
                    ),
                    kid_ids=(child_id,) if child_id is not None else (),
                    inherits_type=index > 0,
                )
            )
        root_ids = ("field-00000",)
    elif topology == "independent_roots":
        node_count = int(case["node_count"])
        nodes = [
            _excluded_pushbutton_node(f"field-{index:05d}")
            for index in range(node_count)
        ]
        root_ids = tuple(str(node["object_id"]) for node in nodes)
    elif topology == "wide_parent":
        kid_count = int(case["kid_count"])
        kid_ids = tuple(f"widget-{index:05d}" for index in range(kid_count))
        nodes.append(_excluded_pushbutton_node("field-root", kid_ids=kid_ids))
        nodes.extend(
            _excluded_pushbutton_node(
                kid_id,
                parent_id="field-root",
                inherits_type=True,
            )
            for kid_id in kid_ids
        )
        root_ids = ("field-root",)
    elif topology == "accounting_probe":
        counter = str(case["counter"])
        observed = int(case["observed"])
        resource_probe = _build_acroform_accounting_probe(counter, observed)
        nodes = [_excluded_pushbutton_node("field-root")]
        root_ids = ("field-root",)
    else:  # pragma: no cover - registry is closed and self-checked
        raise SyntheticFixtureIntegrityError(
            f"unsupported AcroForm graph topology {topology!r}"
        )

    result: dict[str, object] = {
        "case_id": case_id,
        "limits": dict(SYNTHETIC_THRESHOLDS),
        "root_ids": root_ids,
        "nodes": tuple(nodes),
        "expected": case["expected"],
        "violated_limit": case.get("violated_limit"),
        "accounting_summary": {
            "field_nodes": len(nodes),
            "distinct_visited_references": len(nodes),
            "resolution_steps": (
                len(nodes) if topology != "chain" else len(nodes) * 2 - 1
            ),
            "widgets": 0,
        },
    }
    if topology == "chain":
        result["root_depth"] = case["root_depth"]
        result["depth_unit"] = case["depth_unit"]
        result["observed_depth"] = case["observed_depth"]
    if resource_probe is not None:
        result["resource_probe"] = resource_probe
        result["accounting_summary"] = dict(
            resource_probe["non_target_counts"]
        )
    return result


SEMANTIC_GRAPH_CASES: Mapping[str, Mapping[str, object]] = MappingProxyType(
    {
        "semantic-records-page-exact": MappingProxyType(
            {
                "topology": "field_control_units",
                "counter": "max_semantic_records_per_page",
                "scope": "page",
                "page_layout": ((128, 1_600, 1_632),),
                "extra_group_role_labels": (0,),
                "observed": 8_192,
                "expected": "accepted",
            }
        ),
        "semantic-records-page-over-limit": MappingProxyType(
            {
                "topology": "field_control_units",
                "counter": "max_semantic_records_per_page",
                "scope": "page",
                "page_layout": ((128, 1_600, 1_632),),
                "extra_group_role_labels": (1,),
                "observed": 8_193,
                "expected": "over_limit",
                "violated_limit": "max_semantic_records_per_page",
            }
        ),
        "semantic-records-document-exact": MappingProxyType(
            {
                "topology": "field_control_units",
                "counter": "max_semantic_records_per_document",
                "scope": "document",
                "page_layout": ((128, 1_000, 484),) * 8,
                "extra_group_role_labels": (0,) * 8,
                "observed": 32_768,
                "expected": "accepted",
            }
        ),
        "semantic-records-document-over-limit": MappingProxyType(
            {
                "topology": "field_control_units",
                "counter": "max_semantic_records_per_document",
                "scope": "document",
                "page_layout": ((128, 1_000, 484),) * 8,
                "extra_group_role_labels": (1,) + (0,) * 7,
                "observed": 32_769,
                "expected": "over_limit",
                "violated_limit": "max_semantic_records_per_document",
            }
        ),
        "relationships-page-exact": MappingProxyType(
            {
                "topology": "label_fanout",
                "counter": "max_relationships_per_page",
                "scope": "page",
                "page_layout": ((104, 8),),
                "extra_relationships": (0,),
                "observed": 32_768,
                "expected": "accepted",
            }
        ),
        "relationships-page-over-limit": MappingProxyType(
            {
                "topology": "label_fanout",
                "counter": "max_relationships_per_page",
                "scope": "page",
                "page_layout": ((104, 8),),
                "extra_relationships": (1,),
                "observed": 32_769,
                "expected": "over_limit",
                "violated_limit": "max_relationships_per_page",
            }
        ),
        "relationships-document-exact": MappingProxyType(
            {
                "topology": "label_fanout",
                "counter": "max_relationships_per_document",
                "scope": "document",
                "page_layout": ((52, 4),) * 4,
                "extra_relationships": (0,) * 4,
                "observed": 65_536,
                "expected": "accepted",
            }
        ),
        "relationships-document-over-limit": MappingProxyType(
            {
                "topology": "label_fanout",
                "counter": "max_relationships_per_document",
                "scope": "document",
                "page_layout": ((52, 4),) * 4,
                "extra_relationships": (1,) + (0,) * 3,
                "observed": 65_537,
                "expected": "over_limit",
                "violated_limit": "max_relationships_per_document",
            }
        ),
    }
)


def _allocate_evenly(total: int, bucket_count: int) -> tuple[int, ...]:
    if total < 0 or bucket_count <= 0:
        raise ValueError("allocation requires a nonnegative total and buckets")
    quotient, remainder = divmod(total, bucket_count)
    return tuple(
        quotient + (1 if index < remainder else 0)
        for index in range(bucket_count)
    )


def _append_relationship(
    relationships: list[dict[str, object]],
    *,
    page_index: int,
    relationship_type: str,
    source_id: str,
    target_id: str,
) -> None:
    relationships.append(
        {
            "id": f"rel-{len(relationships) + 1:06d}",
            "page_index": page_index,
            "type": relationship_type,
            "source_id": source_id,
            "target_id": target_id,
        }
    )


def _append_owned_node(
    nodes: list[dict[str, object]],
    *,
    node_id: str,
    page_index: int,
    role: str,
    owner_id: str | None,
    label_role: str | None = None,
) -> None:
    node: dict[str, object] = {
        "id": node_id,
        "page_index": page_index,
        "role": role,
        "owner_id": owner_id,
    }
    if label_role is not None:
        node["label_role"] = label_role
    nodes.append(node)


def _build_field_control_unit_graph(
    page_layout: Sequence[tuple[int, int, int]],
    extra_group_role_labels: Sequence[int],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    global_group_index = 0
    for page_index, (layout, extra_labels) in enumerate(
        zip(page_layout, extra_group_role_labels, strict=True),
        start=1,
    ):
        group_count, field_count, control_count = layout
        fields_by_group = _allocate_evenly(field_count, group_count)
        controls_by_group = _allocate_evenly(control_count, group_count)
        page_group_ids: list[str] = []
        for local_group_index in range(group_count):
            global_group_index += 1
            group_id = f"p{page_index}-g{global_group_index:04d}"
            page_group_ids.append(group_id)
            _append_owned_node(
                nodes,
                node_id=group_id,
                page_index=page_index,
                role="group",
                owner_id=None,
            )
            for field_index in range(fields_by_group[local_group_index]):
                stem = f"{group_id}-f{field_index:03d}"
                field_id = stem
                label_id = f"{stem}-label"
                value_id = f"{stem}-value"
                _append_owned_node(
                    nodes,
                    node_id=field_id,
                    page_index=page_index,
                    role="field",
                    owner_id=group_id,
                )
                _append_owned_node(
                    nodes,
                    node_id=label_id,
                    page_index=page_index,
                    role="label",
                    owner_id=group_id,
                    label_role="field",
                )
                _append_owned_node(
                    nodes,
                    node_id=value_id,
                    page_index=page_index,
                    role="value_region",
                    owner_id=field_id,
                )
                for source_id, target_id in (
                    (group_id, field_id),
                    (group_id, label_id),
                    (field_id, value_id),
                ):
                    _append_relationship(
                        relationships,
                        page_index=page_index,
                        relationship_type="contains",
                        source_id=source_id,
                        target_id=target_id,
                    )
                _append_relationship(
                    relationships,
                    page_index=page_index,
                    relationship_type="label_of",
                    source_id=label_id,
                    target_id=field_id,
                )
                _append_relationship(
                    relationships,
                    page_index=page_index,
                    relationship_type="value_of",
                    source_id=value_id,
                    target_id=field_id,
                )
            for control_index in range(controls_by_group[local_group_index]):
                stem = f"{group_id}-c{control_index:03d}"
                control_id = stem
                label_id = f"{stem}-label"
                _append_owned_node(
                    nodes,
                    node_id=control_id,
                    page_index=page_index,
                    role="control",
                    owner_id=group_id,
                )
                _append_owned_node(
                    nodes,
                    node_id=label_id,
                    page_index=page_index,
                    role="label",
                    owner_id=group_id,
                    label_role="control",
                )
                for target_id in (control_id, label_id):
                    _append_relationship(
                        relationships,
                        page_index=page_index,
                        relationship_type="contains",
                        source_id=group_id,
                        target_id=target_id,
                    )
                _append_relationship(
                    relationships,
                    page_index=page_index,
                    relationship_type="label_of",
                    source_id=label_id,
                    target_id=control_id,
                )
                _append_relationship(
                    relationships,
                    page_index=page_index,
                    relationship_type="control_of",
                    source_id=control_id,
                    target_id=group_id,
                )
        for extra_index in range(extra_labels):
            group_id = page_group_ids[extra_index % len(page_group_ids)]
            label_id = f"{group_id}-group-label-{extra_index}"
            _append_owned_node(
                nodes,
                node_id=label_id,
                page_index=page_index,
                role="label",
                owner_id=group_id,
                label_role="group",
            )
            _append_relationship(
                relationships,
                page_index=page_index,
                relationship_type="contains",
                source_id=group_id,
                target_id=label_id,
            )
            _append_relationship(
                relationships,
                page_index=page_index,
                relationship_type="label_of",
                source_id=label_id,
                target_id=group_id,
            )
    return nodes, relationships


def _append_fanout_group(
    nodes: list[dict[str, object]],
    relationships: list[dict[str, object]],
    *,
    page_index: int,
    group_id: str,
    label_count: int,
    complete_fanout: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    _append_owned_node(
        nodes,
        node_id=group_id,
        page_index=page_index,
        role="group",
        owner_id=None,
    )
    field_ids: list[str] = []
    label_ids: list[str] = []
    for index in range(8):
        field_id = f"{group_id}-f{index}"
        value_id = f"{field_id}-value"
        field_ids.append(field_id)
        _append_owned_node(
            nodes,
            node_id=field_id,
            page_index=page_index,
            role="field",
            owner_id=group_id,
        )
        _append_owned_node(
            nodes,
            node_id=value_id,
            page_index=page_index,
            role="value_region",
            owner_id=field_id,
        )
        for source_id, target_id, relationship_type in (
            (group_id, field_id, "contains"),
            (field_id, value_id, "contains"),
            (value_id, field_id, "value_of"),
        ):
            _append_relationship(
                relationships,
                page_index=page_index,
                relationship_type=relationship_type,
                source_id=source_id,
                target_id=target_id,
            )
    for index in range(label_count):
        label_id = f"{group_id}-label{index:02d}"
        label_ids.append(label_id)
        _append_owned_node(
            nodes,
            node_id=label_id,
            page_index=page_index,
            role="label",
            owner_id=group_id,
            label_role="field",
        )
        _append_relationship(
            relationships,
            page_index=page_index,
            relationship_type="contains",
            source_id=group_id,
            target_id=label_id,
        )
        targets = field_ids if complete_fanout else (field_ids[index],)
        for field_id in targets:
            _append_relationship(
                relationships,
                page_index=page_index,
                relationship_type="label_of",
                source_id=label_id,
                target_id=field_id,
            )
    return tuple(field_ids), tuple(label_ids)


def _build_label_fanout_graph(
    page_layout: Sequence[tuple[int, int]],
    extra_relationships: Sequence[int],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    global_group_index = 0
    for page_index, (layout, extras) in enumerate(
        zip(page_layout, extra_relationships, strict=True),
        start=1,
    ):
        large_group_count, small_group_count = layout
        for _ in range(large_group_count):
            global_group_index += 1
            _append_fanout_group(
                nodes,
                relationships,
                page_index=page_index,
                group_id=f"p{page_index}-g{global_group_index:04d}-large",
                label_count=32,
                complete_fanout=True,
            )
        unused_edges: list[tuple[str, str]] = []
        for _ in range(small_group_count):
            global_group_index += 1
            field_ids, label_ids = _append_fanout_group(
                nodes,
                relationships,
                page_index=page_index,
                group_id=f"p{page_index}-g{global_group_index:04d}-small",
                label_count=8,
                complete_fanout=False,
            )
            unused_edges.extend(
                (label_ids[index], field_ids[(index + 1) % len(field_ids)])
                for index in range(len(field_ids))
            )
        if extras > len(unused_edges):
            raise SyntheticFixtureIntegrityError(
                "relationship over-limit witness lacks unused semantic edges"
            )
        for label_id, field_id in unused_edges[:extras]:
            _append_relationship(
                relationships,
                page_index=page_index,
                relationship_type="label_of",
                source_id=label_id,
                target_id=field_id,
            )
    return nodes, relationships


def _semantic_graph_counts(
    nodes: Sequence[Mapping[str, object]],
    relationships: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    page_indexes = sorted(
        {
            int(record["page_index"])
            for record in (*nodes, *relationships)
        }
    )
    roles = {
        role: sum(1 for node in nodes if node["role"] == role)
        for role in (
            "group",
            "field",
            "label",
            "value_region",
            "control",
            "key_value_pair",
        )
    }
    return {
        "semantic_records_document": len(nodes),
        "relationships_document": len(relationships),
        "roles_document": roles,
        "pages": tuple(
            {
                "page_index": page_index,
                "semantic_records": sum(
                    1 for node in nodes if node["page_index"] == page_index
                ),
                "relationships": sum(
                    1
                    for relationship in relationships
                    if relationship["page_index"] == page_index
                ),
            }
            for page_index in page_indexes
        ),
    }


def build_semantic_limit_graph(case_id: str) -> dict[str, object]:
    """Materialize one valid single-owner semantic limit witness."""

    if case_id not in SEMANTIC_GRAPH_CASES:
        raise KeyError(
            f"unknown semantic graph case {case_id!r}; expected one of "
            f"{tuple(SEMANTIC_GRAPH_CASES)}"
        )
    case = SEMANTIC_GRAPH_CASES[case_id]
    topology = str(case["topology"])
    if topology == "field_control_units":
        nodes, relationships = _build_field_control_unit_graph(
            case["page_layout"],  # type: ignore[arg-type]
            case["extra_group_role_labels"],  # type: ignore[arg-type]
        )
    elif topology == "label_fanout":
        nodes, relationships = _build_label_fanout_graph(
            case["page_layout"],  # type: ignore[arg-type]
            case["extra_relationships"],  # type: ignore[arg-type]
        )
    else:  # pragma: no cover - registry is closed and self-checked
        raise SyntheticFixtureIntegrityError(
            f"unsupported semantic graph topology {topology!r}"
        )
    counts = _semantic_graph_counts(nodes, relationships)
    observed_key = (
        "semantic_records_document"
        if str(case["counter"]).startswith("max_semantic")
        else "relationships_document"
    )
    if case["scope"] == "page":
        observed = int(counts["pages"][0][observed_key.removesuffix("_document")])  # type: ignore[index]
    else:
        observed = int(counts[observed_key])
    if observed != int(case["observed"]):
        raise SyntheticFixtureIntegrityError(
            f"{case_id} observed {observed}, expected {case['observed']}"
        )
    return {
        "case_id": case_id,
        "topology": topology,
        "scope": case["scope"],
        "counter": case["counter"],
        "expected": case["expected"],
        "violated_limit": case.get("violated_limit"),
        "limits": dict(SYNTHETIC_THRESHOLDS),
        "nodes": tuple(nodes),
        "relationships": tuple(relationships),
        "counts": counts,
    }


def _build_semantic_relationship_limits() -> dict[str, object]:
    return {
        "materializer": "build_semantic_limit_graph",
        "limits": {
            "semantic_records_per_page": SYNTHETIC_THRESHOLDS[
                "max_semantic_records_per_page"
            ],
            "semantic_records_per_document": SYNTHETIC_THRESHOLDS[
                "max_semantic_records_per_document"
            ],
            "relationships_per_page": SYNTHETIC_THRESHOLDS[
                "max_relationships_per_page"
            ],
            "relationships_per_document": SYNTHETIC_THRESHOLDS[
                "max_relationships_per_document"
            ],
        },
        "case_ids": tuple(SEMANTIC_GRAPH_CASES),
        "cases": tuple(
            {"case_id": case_id, **dict(case)}
            for case_id, case in SEMANTIC_GRAPH_CASES.items()
        ),
    }


def _build_acroform_limits() -> dict[str, object]:
    return {
        "materializer": "build_acroform_graph",
        "limits": {
            "max_depth": SYNTHETIC_THRESHOLDS["acroform_max_depth"],
            "max_nodes": SYNTHETIC_THRESHOLDS["acroform_max_nodes"],
            "max_kids_per_node": SYNTHETIC_THRESHOLDS[
                "acroform_max_kids_per_node"
            ],
            "max_dictionary_entries": SYNTHETIC_THRESHOLDS[
                "acroform_max_dictionary_entries"
            ],
            "max_visited_references": SYNTHETIC_THRESHOLDS[
                "acroform_max_visited_references"
            ],
            "max_resolution_steps": SYNTHETIC_THRESHOLDS[
                "acroform_max_resolution_steps"
            ],
            "max_object_bytes": SYNTHETIC_THRESHOLDS[
                "acroform_max_object_bytes"
            ],
            "max_tree_bytes": SYNTHETIC_THRESHOLDS[
                "acroform_max_tree_bytes"
            ],
            "max_name_bytes": SYNTHETIC_THRESHOLDS[
                "acroform_max_name_bytes"
            ],
            "max_string_bytes": SYNTHETIC_THRESHOLDS[
                "acroform_max_string_bytes"
            ],
        },
        "case_ids": tuple(ACROFORM_GRAPH_CASES),
        "cases": tuple(
            {"case_id": case_id, **dict(case)}
            for case_id, case in ACROFORM_GRAPH_CASES.items()
        ),
        "downstream_record_limits": {
            "source_identities_per_record": SYNTHETIC_THRESHOLDS[
                "max_source_identities_per_semantic_record"
            ],
            "semantic_records_per_page": SYNTHETIC_THRESHOLDS[
                "max_semantic_records_per_page"
            ],
            "semantic_records_per_document": SYNTHETIC_THRESHOLDS[
                "max_semantic_records_per_document"
            ],
            "relationships_per_page": SYNTHETIC_THRESHOLDS[
                "max_relationships_per_page"
            ],
            "relationships_per_document": SYNTHETIC_THRESHOLDS[
                "max_relationships_per_document"
            ],
        },
    }


def _line(
    source_index: int,
    x0: float,
    top: float,
    x1: float,
    bottom: float,
) -> dict[str, object]:
    return {
        "source_index": source_index,
        "x0": x0,
        "top": top,
        "x1": x1,
        "bottom": bottom,
    }


def _rect(
    source_index: int,
    x: float,
    top: float,
    width: float,
    height: float,
) -> dict[str, object]:
    return {
        "source_index": source_index,
        "x": x,
        "top": top,
        "width": width,
        "height": height,
    }


def _box_lines(*, delta: float = 0.0, gap: float = 0.0) -> tuple[dict[str, object], ...]:
    return (
        _line(0, 100.0, 100.0, 112.0, 100.0),
        _line(1, 112.0 + delta, 100.0, 112.0 + delta, 112.0),
        _line(2, 100.0, 112.0, 112.0 - gap, 112.0),
        _line(3, 100.0, 100.0, 100.0, 112.0),
    )


def _threshold_cases(
    *,
    threshold_name: str,
    threshold: float,
    accepted_at_threshold: bool = True,
) -> tuple[dict[str, object], ...]:
    return (
        {
            "case_id": "just-below",
            "value": threshold - _BOUNDARY_EPSILON,
            "expected_accept": True,
        },
        {
            "case_id": "exact",
            "value": threshold,
            "expected_accept": accepted_at_threshold,
        },
        {
            "case_id": "just-above",
            "value": threshold + _BOUNDARY_EPSILON,
            "expected_accept": False,
        },
    )


def _build_endpoint_threshold() -> dict[str, object]:
    threshold = float(SYNTHETIC_THRESHOLDS["endpoint_snap_pt"])
    cases = []
    for case in _threshold_cases(
        threshold_name="endpoint_snap_pt",
        threshold=threshold,
    ):
        delta = float(case["value"])
        cases.append({**case, "lines": _box_lines(delta=delta)})
    return {
        "page": {"page_index": 1, "width": 300.0, "height": 300.0},
        "threshold_name": "endpoint_snap_pt",
        "threshold": threshold,
        "inclusive": True,
        "cases": tuple(cases),
        "axis_alignment_cases": tuple(
            {
                "case_id": case_id,
                "orthogonal_delta": value,
                "expected_axis_aligned": accepted,
            }
            for case_id, value, accepted in (
                ("just-below", threshold - _BOUNDARY_EPSILON, True),
                ("exact", threshold, True),
                ("just-above", threshold + _BOUNDARY_EPSILON, False),
            )
        ),
        "rounding_pt": 0.001,
        "snap_tie_break": "lowest_coordinate_then_source_index",
    }


def _build_closure_threshold() -> dict[str, object]:
    threshold = float(SYNTHETIC_THRESHOLDS["closure_gap_pt"])
    cases = []
    for case in _threshold_cases(
        threshold_name="closure_gap_pt",
        threshold=threshold,
    ):
        gap = float(case["value"])
        cases.append(
            {
                **case,
                "endpoint_snap_applied": False,
                "lines": _box_lines(gap=gap),
            }
        )
    return {
        "threshold_name": "closure_gap_pt",
        "threshold": threshold,
        "inclusive": True,
        "cases": tuple(cases),
        "edge_coverage_cases": tuple(
            {
                "case_id": case_id,
                "coverage": coverage,
                "expected_accept": accepted,
            }
            for case_id, coverage, accepted in (
                ("just-below", 0.95 - _BOUNDARY_EPSILON, False),
                ("exact", 0.95, True),
                ("just-above", 0.95 + _BOUNDARY_EPSILON, True),
            )
        ),
    }


def _build_aspect_threshold() -> dict[str, object]:
    minimum = float(SYNTHETIC_THRESHOLDS["control_min_aspect_ratio"])
    maximum = float(SYNTHETIC_THRESHOLDS["control_max_aspect_ratio"])
    height = 12.0
    ratios = (
        ("below-min", minimum - _BOUNDARY_EPSILON, False),
        ("at-min", minimum, True),
        ("inside", 1.0, True),
        ("at-max", maximum, True),
        ("above-max", maximum + _BOUNDARY_EPSILON, False),
    )
    return {
        "thresholds": {
            "minimum": minimum,
            "maximum": maximum,
            "minimum_side_pt": SYNTHETIC_THRESHOLDS[
                "control_min_side_pt"
            ],
            "maximum_side_pt": SYNTHETIC_THRESHOLDS[
                "control_max_side_pt"
            ],
        },
        "inclusive": True,
        "cases": tuple(
            {
                "case_id": case_id,
                "rect": _rect(0, 100.0, 100.0, ratio * height, height),
                "aspect_ratio": ratio,
                "expected_accept": accepted,
            }
            for case_id, ratio, accepted in ratios
        ),
        "side_cases": tuple(
            {
                "case_id": case_id,
                "rect": _rect(0, 100.0, 100.0, side, side),
                "expected_accept": accepted,
            }
            for case_id, side, accepted in (
                ("below-min", 6.0 - _BOUNDARY_EPSILON, False),
                ("at-min", 6.0, True),
                ("inside", 12.0, True),
                ("at-max", 24.0, True),
                ("above-max", 24.0 + _BOUNDARY_EPSILON, False),
            )
        ),
    }


def _build_label_distance_threshold() -> dict[str, object]:
    minimum = float(SYNTHETIC_THRESHOLDS["control_label_min_gap_pt"])
    maximum = float(SYNTHETIC_THRESHOLDS["control_label_max_gap_pt"])
    cases = []
    for case_id, gap, accepted in (
        ("below-min", minimum - _BOUNDARY_EPSILON, False),
        ("at-min", minimum, True),
        ("inside", 12.0, True),
        ("at-max", maximum, True),
        ("above-max", maximum + _BOUNDARY_EPSILON, False),
    ):
        cases.append(
            {
                "case_id": case_id,
                "value": gap,
                "expected_accept": accepted,
                "control_bbox": (100.0, 100.0, 12.0, 12.0),
                "label": {
                    "text": "Choice",
                    "bbox": (112.0 + gap, 101.0, 30.0, 10.0),
                },
                "expected_state": "unchecked" if accepted else "ambiguous",
            }
        )
    cases.append(
        {
            "case_id": "competing-labels-within-tie-window",
            "control_bbox": (100.0, 100.0, 12.0, 12.0),
            "labels": (
                {"text": "First", "bbox": (122.0, 101.0, 30.0, 10.0)},
                {"text": "Second", "bbox": (122.5, 101.0, 30.0, 10.0)},
            ),
            "expected_accept": False,
            "expected_state": "ambiguous",
            "reason": "competing_labels",
        }
    )
    return {
        "thresholds": {
            "minimum_gap_pt": minimum,
            "maximum_gap_pt": maximum,
            "tie_pt": SYNTHETIC_THRESHOLDS["control_label_tie_pt"],
            "maximum_below_pt": SYNTHETIC_THRESHOLDS[
                "control_label_max_below_pt"
            ],
        },
        "inclusive": True,
        "cases": tuple(cases),
    }


def _build_mark_threshold() -> dict[str, object]:
    minimum_length = float(
        SYNTHETIC_THRESHOLDS["control_mark_min_combined_length"]
    )
    minimum_horizontal = float(
        SYNTHETIC_THRESHOLDS["control_mark_min_horizontal_span"]
    )
    minimum_vertical = float(
        SYNTHETIC_THRESHOLDS["control_mark_min_vertical_span"]
    )
    maximum_fill = float(
        SYNTHETIC_THRESHOLDS["control_mark_max_fill_coverage"]
    )
    minimum_by_dimension = {
        "combined-length": minimum_length,
        "horizontal-span": minimum_horizontal,
        "vertical-span": minimum_vertical,
    }
    cases = [
        {
            "case_id": f"{dimension}-{boundary}",
            "dimension": dimension,
            "value": value,
            "control_bbox": (100.0, 100.0, 12.0, 12.0),
            "mark": {
                "kind": "vector_x",
                "segment_count": 2,
                "combined_length_ratio": (
                    value
                    if dimension == "combined-length"
                    else minimum_length
                ),
                "horizontal_span_ratio": (
                    value
                    if dimension == "horizontal-span"
                    else minimum_horizontal
                ),
                "vertical_span_ratio": (
                    value
                    if dimension == "vertical-span"
                    else minimum_vertical
                ),
                "fill_coverage": 0.0,
                "fully_inside_inset": True,
            },
            "expected_accept": accepted,
            "expected_state": "checked" if accepted else "ambiguous",
        }
        for dimension in (
            "combined-length",
            "horizontal-span",
            "vertical-span",
        )
        for boundary, value, accepted in (
            (
                "just-below",
                minimum_by_dimension[dimension] - _BOUNDARY_EPSILON,
                False,
            ),
            ("exact", minimum_by_dimension[dimension], True),
            (
                "just-above",
                minimum_by_dimension[dimension] + _BOUNDARY_EPSILON,
                True,
            ),
        )
    ]
    cases.extend(
        (
            {
                "case_id": "fill-at-max",
                "control_bbox": (100.0, 100.0, 12.0, 12.0),
                "mark": {
                    "kind": "vector_x",
                    "segment_count": 2,
                    "combined_length_ratio": minimum_length,
                    "horizontal_span_ratio": minimum_horizontal,
                    "vertical_span_ratio": minimum_vertical,
                    "fill_coverage": maximum_fill,
                    "fully_inside_inset": True,
                },
                "expected_accept": True,
                "expected_state": "checked",
            },
            {
                "case_id": "fill-above-max",
                "control_bbox": (100.0, 100.0, 12.0, 12.0),
                "mark": {
                    "kind": "vector_x",
                    "segment_count": 2,
                    "combined_length_ratio": minimum_length,
                    "horizontal_span_ratio": minimum_horizontal,
                    "vertical_span_ratio": minimum_vertical,
                    "fill_coverage": maximum_fill + _BOUNDARY_EPSILON,
                    "fully_inside_inset": True,
                },
                "expected_accept": False,
                "expected_state": "ambiguous",
            },
        )
    )
    cases.append(
        {
            "case_id": "filled-icon-negative",
            "control_bbox": (100.0, 100.0, 12.0, 12.0),
            "mark": {
                "kind": "filled_icon",
                "coverage_ratio": 0.80,
                "fully_inside_inset": True,
            },
            "expected_accept": False,
            "expected_state": "ambiguous",
        }
    )
    return {
        "thresholds": {
            "minimum_combined_length_of_interior_diagonal": minimum_length,
            "minimum_horizontal_span": minimum_horizontal,
            "minimum_vertical_span": minimum_vertical,
            "maximum_fill_coverage": maximum_fill,
            "minimum_segments": 2,
            "maximum_segments": 4,
            "interior_inset_pt": SYNTHETIC_THRESHOLDS[
                "control_interior_inset_pt"
            ],
        },
        "inclusive": True,
        "cases": tuple(cases),
    }


def _build_shared_edge() -> dict[str, object]:
    lines = (
        _line(0, 100.0, 100.0, 124.0, 100.0),
        _line(1, 100.0, 112.0, 124.0, 112.0),
        _line(2, 100.0, 100.0, 100.0, 112.0),
        _line(3, 112.0, 100.0, 112.0, 112.0),
        _line(4, 124.0, 100.0, 124.0, 112.0),
        *_box_lines_for_region(source_index=5, x=100.0, top=130.0),
    )
    return {
        "lines": lines,
        "labels": (
            {"text": "Owned choice", "bbox": (128.0, 101.0, 60.0, 10.0)},
        ),
        "validated_group_context": {
            "labeled_peer_count": 3,
            "peer_size_delta_pt": 0.0,
            "nearest_pitch_pt": 24.0,
            "minimum_labeled_peers": SYNTHETIC_THRESHOLDS[
                "unlabeled_control_min_labeled_peers"
            ],
            "size_tolerance_pt": SYNTHETIC_THRESHOLDS[
                "unlabeled_control_size_tolerance_pt"
            ],
            "maximum_pitch_pt": SYNTHETIC_THRESHOLDS[
                "unlabeled_control_max_pitch_pt"
            ],
        },
        "expected_controls": (
            {
                "bbox": (112.0, 100.0, 12.0, 12.0),
                "state": "unchecked",
                "label": "Owned choice",
            },
            {
                "bbox": (100.0, 130.0, 12.0, 12.0),
                "state": "ambiguous",
                "label": None,
            },
        ),
        "rejected_candidates": (
            {
                "bbox": (100.0, 100.0, 12.0, 12.0),
                "reason": "shared_boundary_phantom",
            },
        ),
    }


def _box_lines_for_region(
    *,
    source_index: int,
    x: float,
    top: float,
    width: float = 12.0,
    height: float = 12.0,
) -> tuple[dict[str, object], ...]:
    return (
        _line(source_index, x, top, x + width, top),
        _line(source_index + 1, x + width, top, x + width, top + height),
        _line(
            source_index + 2,
            x,
            top + height,
            x + width,
            top + height,
        ),
        _line(source_index + 3, x, top, x, top + height),
    )


def _build_duplicate_geometry() -> dict[str, object]:
    return {
        "rects": (_rect(0, 100.0, 100.0, 12.0, 12.0),),
        "lines": _box_lines_for_region(source_index=0, x=100.0, top=100.0),
        "expected_controls": (
            {
                "bbox": (100.0, 100.0, 12.0, 12.0),
                "source_objects": (
                    "rect:0",
                    "line:0",
                    "line:1",
                    "line:2",
                    "line:3",
                ),
                "deduplicated_geometry_count": 1,
            },
        ),
    }


def _affine_bbox(
    bbox: tuple[float, float, float, float],
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float]:
    x, y, width, height = bbox
    a, b, c, d, e, f = matrix
    points = (
        (a * px + c * py + e, b * px + d * py + f)
        for px, py in (
            (x, y),
            (x + width, y),
            (x, y + height),
            (x + width, y + height),
        )
    )
    transformed = tuple(points)
    xs = tuple(point[0] for point in transformed)
    ys = tuple(point[1] for point in transformed)
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    return (left, top, right - left, bottom - top)


def _build_valid_transforms() -> dict[str, object]:
    raw_bbox = (10.0, 20.0, 30.0, 10.0)
    cases = (
        (
            "cropped-identity",
            0,
            (5.0, 10.0, 205.0, 310.0),
            (1.0, 0.0, 0.0, 1.0, -5.0, -10.0),
        ),
        (
            "rotated-90",
            90,
            (0.0, 0.0, 200.0, 300.0),
            (0.0, 1.0, -1.0, 0.0, 200.0, 0.0),
        ),
        (
            "rotated-180",
            180,
            (0.0, 0.0, 200.0, 300.0),
            (-1.0, 0.0, 0.0, -1.0, 200.0, 300.0),
        ),
        (
            "rotated-270",
            270,
            (0.0, 0.0, 200.0, 300.0),
            (0.0, -1.0, 1.0, 0.0, 0.0, 300.0),
        ),
    )
    return {
        "raw_bbox": raw_bbox,
        "cases": tuple(
            {
                "case_id": case_id,
                "rotation": rotation,
                "crop_box": crop_box,
                "transform_to_page": matrix,
                "expected_bbox": _affine_bbox(raw_bbox, matrix),
                "expected_accept": True,
            }
            for case_id, rotation, crop_box, matrix in cases
        ),
    }


def _build_invalid_transforms() -> dict[str, object]:
    return {
        "raw_bbox": (10.0, 20.0, 30.0, 10.0),
        "cases": (
            {
                "case_id": "missing-transform",
                "transform_to_page": None,
                "expected_accept": False,
                "reason": "missing",
            },
            {
                "case_id": "non-finite-transform",
                "transform_to_page": (1.0, 0.0, 0.0, 1.0, "NaN", 0.0),
                "expected_accept": False,
                "reason": "non_finite",
            },
            {
                "case_id": "singular-transform",
                "transform_to_page": (1.0, 2.0, 2.0, 4.0, 0.0, 0.0),
                "expected_accept": False,
                "reason": "singular",
            },
            {
                "case_id": "wrong-arity",
                "transform_to_page": (1.0, 0.0, 0.0, 1.0, 0.0),
                "expected_accept": False,
                "reason": "wrong_arity",
            },
            {
                "case_id": "cross-unit",
                "transform_to_page": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
                "source_unit": "px",
                "target_unit": "pt",
                "expected_accept": False,
                "reason": "unit_mismatch",
            },
        ),
    }


def _kv_rows(
    *,
    row_count: int = 3,
    page_indexes: Sequence[int] | None = None,
    key_x: float = 100.0,
    key_width: float = 50.0,
    value_x: float = 170.0,
    first_top: float = 100.0,
    cadence: float = 18.0,
    key_anchor_drift: float = 0.0,
    value_anchor_drift: float = 0.0,
    value_top_offset: float = 0.0,
    value_height_offset: float = 0.0,
    table_candidate_id: str | None = None,
) -> tuple[dict[str, object], ...]:
    pages = tuple(page_indexes or (1,) * row_count)
    if len(pages) != row_count:
        raise ValueError("page_indexes length must equal row_count")
    rows = []
    for index in range(row_count):
        top = first_top + cadence * index
        key_left = key_x + (key_anchor_drift if index + 1 == row_count else 0.0)
        value_left = value_x + (
            value_anchor_drift if index + 1 == row_count else 0.0
        )
        membership = (
            {"table_candidate_id": table_candidate_id}
            if table_candidate_id is not None
            else {}
        )
        rows.append(
            {
                "row_index": index,
                "page_index": pages[index],
                "key": {
                    "source_index": index * 2,
                    "text": f"Key {index + 1}",
                    "bbox": (key_left, top, key_width, 8.0),
                    "bold": True,
                    **membership,
                },
                "value": {
                    "source_index": index * 2 + 1,
                    "text": f"Value {index + 1}",
                    "bbox": (
                        value_left,
                        top + value_top_offset,
                        60.0,
                        8.0 + value_height_offset,
                    ),
                    "bold": False,
                    **membership,
                },
            }
        )
    return tuple(rows)


def _build_kv_gap() -> dict[str, object]:
    minimum = float(SYNTHETIC_THRESHOLDS["kv_min_gap_pt"])
    page_width = 600.0
    maximum = key_value_max_gap(page_width)
    key_right = 150.0
    cases = (
        ("below-min", minimum - _BOUNDARY_EPSILON, False),
        ("at-min", minimum, True),
        ("inside", 20.0, True),
        ("at-max", maximum, True),
        ("above-max", maximum + _BOUNDARY_EPSILON, False),
    )
    narrow_page_width = 300.0
    narrow_maximum = key_value_max_gap(narrow_page_width)
    return {
        "page_width": page_width,
        "gap_formula": "value.left - key.right",
        "maximum_formula": "min(160, 0.35 * page_width)",
        "thresholds": {
            "minimum": minimum,
            "maximum": maximum,
            "absolute_maximum": SYNTHETIC_THRESHOLDS[
                "kv_max_gap_absolute_pt"
            ],
            "page_width_fraction": SYNTHETIC_THRESHOLDS[
                "kv_max_gap_page_fraction"
            ],
        },
        "inclusive": True,
        "cases": tuple(
            {
                "case_id": case_id,
                "gap": gap,
                "rows": _kv_rows(value_x=key_right + gap),
                "expected_group": accepted,
            }
            for case_id, gap, accepted in cases
        ),
        "narrow_page_cases": (
            {
                "case_id": "narrow-page-at-dynamic-max",
                "page_width": narrow_page_width,
                "gap": narrow_maximum,
                "rows": _kv_rows(value_x=key_right + narrow_maximum),
                "expected_group": True,
            },
            {
                "case_id": "narrow-page-above-dynamic-max",
                "page_width": narrow_page_width,
                "gap": narrow_maximum + _BOUNDARY_EPSILON,
                "rows": _kv_rows(
                    value_x=key_right + narrow_maximum + _BOUNDARY_EPSILON
                ),
                "expected_group": False,
            },
        ),
    }


def _build_kv_anchor() -> dict[str, object]:
    anchor = float(SYNTHETIC_THRESHOLDS["kv_anchor_tolerance_pt"])
    top = float(SYNTHETIC_THRESHOLDS["kv_top_tolerance_pt"])
    height = float(SYNTHETIC_THRESHOLDS["kv_height_tolerance_pt"])
    cases: list[dict[str, object]] = []
    for name, keyword, threshold in (
        ("key-anchor", "key_anchor_drift", anchor),
        ("value-anchor", "value_anchor_drift", anchor),
        ("top-alignment", "value_top_offset", top),
        ("height-alignment", "value_height_offset", height),
    ):
        for suffix, value, accepted in (
            ("just-below", threshold - _BOUNDARY_EPSILON, True),
            ("exact", threshold, True),
            ("just-above", threshold + _BOUNDARY_EPSILON, False),
        ):
            cases.append(
                {
                    "case_id": f"{name}-{suffix}",
                    "dimension": name,
                    "value": value,
                    "rows": _kv_rows(**{keyword: value}),
                    "expected_group": accepted,
                }
            )
    return {
        "thresholds": {
            "anchor": anchor,
            "top": top,
            "height": height,
        },
        "inclusive": True,
        "cases": tuple(cases),
    }


def _build_kv_cadence() -> dict[str, object]:
    minimum = float(SYNTHETIC_THRESHOLDS["kv_min_cadence_pt"])
    maximum = float(SYNTHETIC_THRESHOLDS["kv_max_cadence_pt"])
    cases = (
        ("below-min", minimum - _BOUNDARY_EPSILON, False),
        ("at-min", minimum, True),
        ("inside", 18.0, True),
        ("at-max", maximum, True),
        ("above-max", maximum + _BOUNDARY_EPSILON, False),
    )
    return {
        "thresholds": {"minimum": minimum, "maximum": maximum},
        "inclusive": True,
        "cases": tuple(
            {
                "case_id": case_id,
                "cadence": cadence,
                "rows": _kv_rows(cadence=cadence),
                "expected_group": accepted,
            }
            for case_id, cadence, accepted in cases
        ),
    }


def _build_kv_tie() -> dict[str, object]:
    rows = []
    for row in _kv_rows():
        competing = dict(row["value"])
        competing["source_index"] = int(competing["source_index"]) + 100
        competing["text"] = f"Competing {int(row['row_index']) + 1}"
        rows.append({**row, "competing_values": (row["value"], competing)})
    return {
        "rows": tuple(rows),
        "expected_group": False,
        "expected_reason": "competing_match",
        "tie_break": "reject_not_lexical_choice",
    }


def _build_kv_two_row() -> dict[str, object]:
    return {
        "rows": _kv_rows(row_count=2),
        "minimum_rows": SYNTHETIC_THRESHOLDS["kv_min_rows"],
        "expected_group": False,
        "expected_reason": "insufficient_rows",
    }


def _build_kv_borderless_table() -> dict[str, object]:
    return {
        "rows": _kv_rows(table_candidate_id="table-borderless-1"),
        "source_has_ruling": False,
        "table_membership_is_authoritative": True,
        "expected_group": False,
        "expected_reason": "table_membership",
    }


def _build_kv_cross_page() -> dict[str, object]:
    return {
        "rows": _kv_rows(page_indexes=(1, 1, 2)),
        "expected_group": False,
        "expected_reason": "cross_page_continuation",
    }


SYNTHETIC_FIXTURES = (
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:static-controls-v1",
        kind="pdf",
        purpose="Static vector checked and unchecked controls.",
        covers=("static_checked_control", "static_unchecked_control"),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:interactive-controls-v1",
        kind="pdf",
        purpose=(
            "Selected/unselected checkbox and radio widgets, pushbutton "
            "exclusion, and an explicit not-applicable export state."
        ),
        covers=(
            "selected_checkbox",
            "unselected_checkbox",
            "selected_radio",
            "unselected_radio",
            "pushbutton_exclusion",
            "explicit_not_applicable",
        ),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:field-values-v1",
        kind="pdf",
        purpose="One source-present field and one competing-label ambiguity.",
        covers=("present_field", "ambiguous_field"),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:inherited-widget-kids-v1",
        kind="pdf",
        purpose="Radio widget kids inheriting FT, Ff, and V from their parent.",
        covers=("inherited_widget_kids",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:mixed-static-interactive-v1",
        kind="pdf",
        purpose="One static vector control and one validated widget on a page.",
        covers=("mixed_static_interactive",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:orphan-widget-v1",
        kind="pdf",
        purpose="Page widget absent from the catalog AcroForm field tree.",
        covers=("orphan_widget",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:cyclic-acroform-v1",
        kind="pdf",
        purpose="Indirect Parent/Kids cycle that must fail closed.",
        covers=("cyclic_acroform",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:acroform-limits-v1",
        kind="acroform_graph_spec",
        purpose=(
            "Isolated exact/max+1 AcroForm traversal and accounting graphs."
        ),
        covers=("deep_acroform", "over_limit_acroform"),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:semantic-relationship-limits-v1",
        kind="semantic_graph_spec",
        purpose=(
            "Valid single-owner exact/max+1 page and document graph caps."
        ),
        covers=(
            "semantic_record_page_limit",
            "semantic_record_document_limit",
            "relationship_page_limit",
            "relationship_document_limit",
        ),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:endpoint-thresholds-v1",
        kind="geometry_spec",
        purpose="Just-below/exact/just-above endpoint snapping.",
        covers=("endpoint_threshold",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:closure-thresholds-v1",
        kind="geometry_spec",
        purpose="Just-below/exact/just-above closed-outline gaps.",
        covers=("closure_threshold",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:aspect-thresholds-v1",
        kind="geometry_spec",
        purpose="Inclusive minimum and maximum control aspect ratios.",
        covers=("aspect_threshold",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:label-distance-thresholds-v1",
        kind="geometry_spec",
        purpose="Label distance boundary and an equal competing-label tie.",
        covers=("label_distance_threshold",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:mark-thresholds-v1",
        kind="geometry_spec",
        purpose="Interior mark coverage boundary and filled-icon negative.",
        covers=("mark_threshold",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:shared-edge-phantom-v1",
        kind="geometry_spec",
        purpose="Labeled shared-edge winner, phantom rejection, and unlabeled box.",
        covers=("shared_edge_phantom",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:duplicate-geometry-v1",
        kind="geometry_spec",
        purpose="A native rectangle duplicated by four source line objects.",
        covers=("duplicate_geometry",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:rotated-cropped-transforms-v1",
        kind="transform_spec",
        purpose="Finite crop and 0/90/180/270-degree page transforms.",
        covers=("rotated_crop",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:invalid-transforms-v1",
        kind="transform_spec",
        purpose="Missing, non-finite, singular, wrong-arity, and cross-unit transforms.",
        covers=("invalid_transform",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:kv-gap-thresholds-v1",
        kind="key_value_spec",
        purpose="Inclusive key-right/value-left minimum and maximum gaps.",
        covers=("kv_min_gap", "kv_max_gap"),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:kv-anchor-thresholds-v1",
        kind="key_value_spec",
        purpose="Key/value anchor, top, and height alignment boundaries.",
        covers=("kv_anchor",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:kv-cadence-thresholds-v1",
        kind="key_value_spec",
        purpose="Inclusive minimum and maximum row cadence.",
        covers=("kv_cadence",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:kv-tie-v1",
        kind="key_value_spec",
        purpose="Two equal value candidates per key require deterministic refusal.",
        covers=("kv_tie",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:kv-two-row-v1",
        kind="key_value_spec",
        purpose="Two aligned rows remain below the three-row threshold.",
        covers=("kv_two_row",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:kv-borderless-table-v1",
        kind="key_value_spec",
        purpose="Stable bold-left columns retain authoritative table ownership.",
        covers=("kv_borderless_table",),
    ),
    SyntheticFixtureDefinition(
        fixture_id="synthetic:p03-us06:kv-cross-page-v1",
        kind="key_value_spec",
        purpose="A visually continuing group is split across physical pages.",
        covers=("kv_cross_page",),
    ),
)


SYNTHETIC_FIXTURES_BY_ID: Mapping[str, SyntheticFixtureDefinition] = (
    MappingProxyType(
        {fixture.fixture_id: fixture for fixture in SYNTHETIC_FIXTURES}
    )
)
SYNTHETIC_FIXTURE_IDS = tuple(
    fixture.fixture_id for fixture in SYNTHETIC_FIXTURES
)


_BUILDERS: Mapping[str, Callable[[], dict[str, object]]] = MappingProxyType(
    {
        "synthetic:p03-us06:static-controls-v1": _build_static_controls,
        "synthetic:p03-us06:interactive-controls-v1": (
            _build_interactive_controls
        ),
        "synthetic:p03-us06:field-values-v1": _build_static_fields,
        "synthetic:p03-us06:inherited-widget-kids-v1": (
            _build_inherited_widget_kids
        ),
        "synthetic:p03-us06:mixed-static-interactive-v1": _build_mixed_form,
        "synthetic:p03-us06:orphan-widget-v1": _build_orphan_widget,
        "synthetic:p03-us06:cyclic-acroform-v1": _build_cyclic_acroform,
        "synthetic:p03-us06:acroform-limits-v1": _build_acroform_limits,
        "synthetic:p03-us06:semantic-relationship-limits-v1": (
            _build_semantic_relationship_limits
        ),
        "synthetic:p03-us06:endpoint-thresholds-v1": (
            _build_endpoint_threshold
        ),
        "synthetic:p03-us06:closure-thresholds-v1": (
            _build_closure_threshold
        ),
        "synthetic:p03-us06:aspect-thresholds-v1": _build_aspect_threshold,
        "synthetic:p03-us06:label-distance-thresholds-v1": (
            _build_label_distance_threshold
        ),
        "synthetic:p03-us06:mark-thresholds-v1": _build_mark_threshold,
        "synthetic:p03-us06:shared-edge-phantom-v1": _build_shared_edge,
        "synthetic:p03-us06:duplicate-geometry-v1": _build_duplicate_geometry,
        "synthetic:p03-us06:rotated-cropped-transforms-v1": (
            _build_valid_transforms
        ),
        "synthetic:p03-us06:invalid-transforms-v1": _build_invalid_transforms,
        "synthetic:p03-us06:kv-gap-thresholds-v1": _build_kv_gap,
        "synthetic:p03-us06:kv-anchor-thresholds-v1": _build_kv_anchor,
        "synthetic:p03-us06:kv-cadence-thresholds-v1": _build_kv_cadence,
        "synthetic:p03-us06:kv-tie-v1": _build_kv_tie,
        "synthetic:p03-us06:kv-two-row-v1": _build_kv_two_row,
        "synthetic:p03-us06:kv-borderless-table-v1": (
            _build_kv_borderless_table
        ),
        "synthetic:p03-us06:kv-cross-page-v1": _build_kv_cross_page,
    }
)


def build_synthetic_fixture(fixture_id: str) -> dict[str, object]:
    """Build one registered readiness fixture as a fresh dictionary."""

    definition = SYNTHETIC_FIXTURES_BY_ID.get(fixture_id)
    if definition is None:
        raise KeyError(
            f"unknown P03-US06 synthetic fixture {fixture_id!r}; expected one "
            f"of {SYNTHETIC_FIXTURE_IDS}"
        )
    return {
        "fixture_id": definition.fixture_id,
        "kind": definition.kind,
        "purpose": definition.purpose,
        "covers": definition.covers,
        "payload": _BUILDERS[fixture_id](),
    }


def build_all_synthetic_fixtures() -> dict[str, dict[str, object]]:
    """Build every fixture in stable registry order."""

    return {
        fixture_id: build_synthetic_fixture(fixture_id)
        for fixture_id in SYNTHETIC_FIXTURE_IDS
    }


def _digestable(value: object) -> object:
    if isinstance(value, bytes):
        return {
            "bytes_sha256": hashlib.sha256(value).hexdigest(),
            "size_bytes": len(value),
        }
    if isinstance(value, Mapping):
        return {
            str(key): _digestable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_digestable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite": repr(value)}
    return value


def synthetic_fixture_hashes() -> dict[str, str]:
    """Hash canonical fixture payloads, substituting byte hashes for PDFs."""

    hashes: dict[str, str] = {}
    for fixture_id, fixture in build_all_synthetic_fixtures().items():
        canonical = json.dumps(
            _digestable(fixture),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        hashes[fixture_id] = hashlib.sha256(canonical).hexdigest()
    return hashes


def _verify_pdf_payload(fixture_id: str, payload: Mapping[str, object]) -> None:
    import pdfplumber
    import pypdfium2 as pdfium

    pdf_bytes = payload.get("pdf_bytes")
    if not isinstance(pdf_bytes, bytes):
        raise SyntheticFixtureIntegrityError(
            f"{fixture_id} is registered as PDF but has no PDF bytes"
        )
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
            if len(document.pages) != int(payload["page_count"]):
                raise SyntheticFixtureIntegrityError(
                    f"{fixture_id} page count drifted"
                )
            for page in document.pages:
                _ = page.objects
                if payload.get("reader_check") != "catalog_and_page_only":
                    _ = page.annots
    except SyntheticFixtureIntegrityError:
        raise
    except Exception as exc:  # pragma: no cover - dependency detail varies
        raise SyntheticFixtureIntegrityError(
            f"pdfplumber could not open {fixture_id}: {type(exc).__name__}"
        ) from exc

    try:
        document = pdfium.PdfDocument(pdf_bytes)
        try:
            if len(document) != int(payload["page_count"]):
                raise SyntheticFixtureIntegrityError(
                    f"{fixture_id} pdfium page count drifted"
                )
            for page_index in range(len(document)):
                page = document[page_index]
                try:
                    bitmap = page.render(scale=0.25)
                    bitmap.close()
                finally:
                    page.close()
        finally:
            document.close()
    except SyntheticFixtureIntegrityError:
        raise
    except Exception as exc:  # pragma: no cover - dependency detail varies
        raise SyntheticFixtureIntegrityError(
            f"pypdfium2 could not render {fixture_id}: {type(exc).__name__}"
        ) from exc


def _validate_acroform_limit_cases() -> None:
    resource_limits = {
        "dictionary_entries": (
            "max_dictionary_entries",
            "acroform_max_dictionary_entries",
        ),
        "visited_references": (
            "distinct_visited_references",
            "acroform_max_visited_references",
        ),
        "resolution_steps": (
            "resolution_steps",
            "acroform_max_resolution_steps",
        ),
        "object_bytes": ("max_object_bytes", "acroform_max_object_bytes"),
        "tree_bytes": ("tree_bytes", "acroform_max_tree_bytes"),
        "name_bytes": ("max_name_bytes", "acroform_max_name_bytes"),
        "string_bytes": ("max_string_bytes", "acroform_max_string_bytes"),
    }
    for case_id, case in ACROFORM_GRAPH_CASES.items():
        graph = build_acroform_graph(case_id)
        nodes = graph["nodes"]
        root_ids = graph["root_ids"]
        node_by_id = {str(node["object_id"]): node for node in nodes}
        if len(node_by_id) != len(nodes):
            raise SyntheticFixtureIntegrityError(
                f"{case_id} repeats an AcroForm node identity"
            )
        if any(root_id not in node_by_id for root_id in root_ids):
            raise SyntheticFixtureIntegrityError(
                f"{case_id} has an unresolved AcroForm root"
            )
        for node in nodes:
            parent_id = node["parent_id"]
            if parent_id is not None:
                parent = node_by_id.get(str(parent_id))
                if parent is None or node["object_id"] not in parent["kid_ids"]:
                    raise SyntheticFixtureIntegrityError(
                        f"{case_id} has inconsistent Parent/Kids ownership"
                    )
            if node["is_widget"]:
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} collides with the widget counter"
                )

        topology = str(case["topology"])
        expected = str(case["expected"])
        if topology == "chain":
            observed = len(nodes) - 1
            limit = int(SYNTHETIC_THRESHOLDS["acroform_max_depth"])
            if graph["root_depth"] != 0 or graph["depth_unit"] != "kids_edges":
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} has ambiguous depth semantics"
                )
        elif topology == "independent_roots":
            observed = len(nodes)
            limit = int(SYNTHETIC_THRESHOLDS["acroform_max_nodes"])
            if len(root_ids) != observed:
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} root/node count drifted"
                )
        elif topology == "wide_parent":
            observed = max(len(node["kid_ids"]) for node in nodes)
            limit = int(
                SYNTHETIC_THRESHOLDS["acroform_max_kids_per_node"]
            )
        elif topology == "accounting_probe":
            probe = graph.get("resource_probe")
            if not isinstance(probe, Mapping):
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} lacks a typed accounting probe"
                )
            counter = str(probe["counter"])
            count_key, threshold_key = resource_limits[counter]
            counts = probe["non_target_counts"]
            if not isinstance(counts, Mapping):
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} lacks accounting counts"
                )
            observed = int(counts[count_key])
            limit = int(SYNTHETIC_THRESHOLDS[threshold_key])
            if observed != int(probe["observed"]):
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} probe count drifted"
                )
            for other_counter, (other_key, other_threshold) in (
                item for item in resource_limits.items() if item[0] != counter
            ):
                if int(counts[other_key]) >= int(
                    SYNTHETIC_THRESHOLDS[other_threshold]
                ):
                    raise SyntheticFixtureIntegrityError(
                        f"{case_id} collides with {other_counter}"
                    )
            objects = probe["objects"]
            if not isinstance(objects, tuple):
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} accounting objects are not immutable"
                )
            for item in objects:
                if item["pdf_type"] == "stream":
                    if len(item["encoded_stream_bytes"]) + 2 != int(
                        item["accounted_bytes"]
                    ):
                        raise SyntheticFixtureIntegrityError(
                            f"{case_id} stream accounting drifted"
                        )
                elif item["pdf_type"] in {"name", "string"}:
                    if len(item["raw_bytes"]) != int(item["payload_bytes"]):
                        raise SyntheticFixtureIntegrityError(
                            f"{case_id} leaf byte accounting drifted"
                        )
        else:  # pragma: no cover - registry is closed
            raise SyntheticFixtureIntegrityError(
                f"unsupported AcroForm case topology {topology!r}"
            )

        expected_observed = limit if expected == "accepted" else limit + 1
        if observed != expected_observed:
            raise SyntheticFixtureIntegrityError(
                f"{case_id} observed {observed}, expected {expected_observed}"
            )
        summary = graph["accounting_summary"]
        if not isinstance(summary, Mapping):
            raise SyntheticFixtureIntegrityError(
                f"{case_id} lacks an accounting summary"
            )
        if topology != "independent_roots" and int(summary["field_nodes"]) >= int(
            SYNTHETIC_THRESHOLDS["acroform_max_nodes"]
        ):
            raise SyntheticFixtureIntegrityError(
                f"{case_id} collides with the field-node cap"
            )
        if topology != "accounting_probe" or case.get("counter") != (
            "visited_references"
        ):
            if int(summary["distinct_visited_references"]) >= int(
                SYNTHETIC_THRESHOLDS["acroform_max_visited_references"]
            ):
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} collides with the visited-reference cap"
                )
        if topology != "accounting_probe" or case.get("counter") != (
            "resolution_steps"
        ):
            if int(summary["resolution_steps"]) >= int(
                SYNTHETIC_THRESHOLDS["acroform_max_resolution_steps"]
            ):
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} collides with the resolution-step cap"
                )
        if int(summary.get("widgets", 0)) >= int(
            SYNTHETIC_THRESHOLDS["max_annotations_widgets_per_page"]
        ):
            raise SyntheticFixtureIntegrityError(
                f"{case_id} collides with the page widget cap"
            )


def _validate_semantic_limit_graph(case_id: str) -> None:
    graph = build_semantic_limit_graph(case_id)
    nodes = graph["nodes"]
    relationships = graph["relationships"]
    node_by_id = {str(node["id"]): node for node in nodes}
    if len(node_by_id) != len(nodes):
        raise SyntheticFixtureIntegrityError(
            f"{case_id} repeats a semantic node identity"
        )
    relationship_ids = {str(item["id"]) for item in relationships}
    if len(relationship_ids) != len(relationships):
        raise SyntheticFixtureIntegrityError(
            f"{case_id} repeats a relationship identity"
        )
    relationship_keys: set[tuple[str, str, str]] = set()
    label_relationships: list[tuple[str, str]] = []
    structural_parent_count = {
        node_id: 0
        for node_id, node in node_by_id.items()
        if node["role"] != "group"
    }
    role_compatibility = {
        "label_of": ({"label"}, {"field", "control", "group"}),
        "value_of": ({"value_region"}, {"field", "key_value_pair"}),
        "control_of": ({"control"}, {"field", "group"}),
    }
    populated_groups = {
        node_id: False
        for node_id, node in node_by_id.items()
        if node["role"] == "group"
    }
    for node in nodes:
        if node["role"] == "label" and node.get("label_role") not in {
            "field",
            "control",
            "group",
        }:
            raise SyntheticFixtureIntegrityError(
                f"{case_id} has a label without an exact label role"
            )
    for relationship in relationships:
        source_id = str(relationship["source_id"])
        target_id = str(relationship["target_id"])
        source = node_by_id.get(source_id)
        target = node_by_id.get(target_id)
        if source is None or target is None:
            raise SyntheticFixtureIntegrityError(
                f"{case_id} has an unresolved relationship endpoint"
            )
        if source["page_index"] != target["page_index"]:
            raise SyntheticFixtureIntegrityError(
                f"{case_id} has a cross-page relationship"
            )
        relationship_type = str(relationship["type"])
        key = (relationship_type, source_id, target_id)
        if key in relationship_keys:
            raise SyntheticFixtureIntegrityError(
                f"{case_id} repeats a typed relationship endpoint pair"
            )
        relationship_keys.add(key)
        if relationship_type == "contains":
            if target_id not in structural_parent_count:
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} structurally parents a group"
                )
            if target["owner_id"] != source_id:
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} contains edge disagrees with node ownership"
                )
            structural_parent_count[target_id] += 1
            if source["role"] == "group" and target["role"] in {
                "field",
                "control",
                "key_value_pair",
            }:
                populated_groups[source_id] = True
        else:
            source_roles, target_roles = role_compatibility[relationship_type]
            if (
                source["role"] not in source_roles
                or target["role"] not in target_roles
            ):
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} has role-incompatible semantic endpoints"
                )
            if relationship_type == "label_of":
                label_relationships.append((source_id, target_id))
    if any(count != 1 for count in structural_parent_count.values()):
        raise SyntheticFixtureIntegrityError(
            f"{case_id} is not a single-owner graph"
        )
    if not all(populated_groups.values()):
        raise SyntheticFixtureIntegrityError(
            f"{case_id} contains a group without a field, control, or pair"
        )
    expected_label_role = {
        "field": "field",
        "control": "control",
        "group": "group",
    }
    for label_id, target_id in label_relationships:
        label = node_by_id[label_id]
        target = node_by_id[target_id]
        owner_group_id = (
            target_id if target["role"] == "group" else str(target["owner_id"])
        )
        if (
            label["label_role"] != expected_label_role[target["role"]]
            or label["owner_id"] != owner_group_id
            or ("contains", owner_group_id, label_id) not in relationship_keys
        ):
            raise SyntheticFixtureIntegrityError(
                f"{case_id} has an invalid role-specific label edge"
            )

    counts = graph["counts"]
    case = SEMANTIC_GRAPH_CASES[case_id]
    target_counter = str(case["counter"])
    target_limit = int(SYNTHETIC_THRESHOLDS[target_counter])
    expected_observed = target_limit + (
        1 if case["expected"] == "over_limit" else 0
    )
    if int(case["observed"]) != expected_observed:
        raise SyntheticFixtureIntegrityError(
            f"{case_id} does not isolate exact/max+1 target arithmetic"
        )

    page_limits = {
        "semantic_records": int(
            SYNTHETIC_THRESHOLDS["max_semantic_records_per_page"]
        ),
        "relationships": int(
            SYNTHETIC_THRESHOLDS["max_relationships_per_page"]
        ),
    }
    document_limits = {
        "semantic_records_document": int(
            SYNTHETIC_THRESHOLDS["max_semantic_records_per_document"]
        ),
        "relationships_document": int(
            SYNTHETIC_THRESHOLDS["max_relationships_per_document"]
        ),
    }
    target_family = (
        "semantic_records" if target_counter.startswith("max_semantic")
        else "relationships"
    )
    for page in counts["pages"]:
        for family, limit in page_limits.items():
            is_target = case["scope"] == "page" and family == target_family
            if not is_target and int(page[family]) >= limit:
                raise SyntheticFixtureIntegrityError(
                    f"{case_id} collides with the {family} page cap"
                )
    for family, limit in document_limits.items():
        is_target = (
            case["scope"] == "document"
            and family.startswith(target_family)
        )
        if not is_target and int(counts[family]) >= limit:
            raise SyntheticFixtureIntegrityError(
                f"{case_id} collides with the {family} cap"
            )

    groups_by_page: dict[int, int] = {}
    class_by_page: dict[tuple[int, str], int] = {}
    class_by_group: dict[tuple[str, str], int] = {}
    per_group_limits = {
        "field": int(SYNTHETIC_THRESHOLDS["max_fields_per_group"]),
        "value_region": int(
            SYNTHETIC_THRESHOLDS["max_value_regions_per_group"]
        ),
        "control": int(SYNTHETIC_THRESHOLDS["max_controls_per_group"]),
        "label": int(SYNTHETIC_THRESHOLDS["max_labels_per_group"]),
        "key_value_pair": int(
            SYNTHETIC_THRESHOLDS["max_key_value_pairs_per_group"]
        ),
    }
    nodes_by_id = {str(node["id"]): node for node in nodes}
    class_document = {"field": 0, "control": 0, "key_value_pair": 0}
    for node in nodes:
        page_index = int(node["page_index"])
        role = str(node["role"])
        if role == "group":
            groups_by_page[page_index] = groups_by_page.get(page_index, 0) + 1
        if role != "group":
            owner_id = str(node["owner_id"])
            if role == "value_region":
                owner = nodes_by_id.get(owner_id)
                if owner is not None:
                    owner_id = str(owner["owner_id"])
            class_by_group[(owner_id, role)] = (
                class_by_group.get((owner_id, role), 0) + 1
            )
        if role in class_document:
            class_document[role] += 1
            class_by_page[(page_index, role)] = (
                class_by_page.get((page_index, role), 0) + 1
            )
    if any(
        count >= int(SYNTHETIC_THRESHOLDS["max_groups_per_page"])
        for count in groups_by_page.values()
    ) or sum(groups_by_page.values()) >= int(
        SYNTHETIC_THRESHOLDS["max_groups_per_document"]
    ):
        raise SyntheticFixtureIntegrityError(
            f"{case_id} collides with a candidate-group cap"
        )
    if any(
        count >= per_group_limits[role]
        for (_owner_id, role), count in class_by_group.items()
    ):
        raise SyntheticFixtureIntegrityError(
            f"{case_id} collides with a per-group class cap"
        )
    if any(
        count >= int(
            SYNTHETIC_THRESHOLDS[
                "max_fields_controls_pairs_per_page"
            ]
        )
        for count in class_by_page.values()
    ) or any(
        count >= int(
            SYNTHETIC_THRESHOLDS[
                "max_fields_controls_pairs_per_document"
            ]
        )
        for count in class_document.values()
    ):
        raise SyntheticFixtureIntegrityError(
            f"{case_id} collides with a field/control/pair class cap"
        )


def synthetic_self_check(*, verify_pdf_readers: bool = False) -> dict[str, str]:
    """Validate coverage, registry/builders, determinism, and optional PDFs."""

    if len(SYNTHETIC_FIXTURE_IDS) != len(set(SYNTHETIC_FIXTURE_IDS)):
        raise SyntheticFixtureIntegrityError("duplicate synthetic fixture ID")
    if tuple(_BUILDERS) != SYNTHETIC_FIXTURE_IDS:
        raise SyntheticFixtureIntegrityError(
            "synthetic fixture registry and builder order differ"
        )

    coverage: dict[str, list[str]] = {
        capability: [] for capability in REQUIRED_SYNTHETIC_COVERAGE
    }
    for fixture in SYNTHETIC_FIXTURES:
        for capability in fixture.covers:
            if capability not in coverage:
                raise SyntheticFixtureIntegrityError(
                    f"unregistered fixture capability {capability!r}"
                )
            coverage[capability].append(fixture.fixture_id)
    missing = tuple(
        capability for capability, fixture_ids in coverage.items() if not fixture_ids
    )
    if missing:
        raise SyntheticFixtureIntegrityError(
            f"missing required synthetic coverage: {missing}"
        )

    _validate_acroform_limit_cases()
    for case_id in SEMANTIC_GRAPH_CASES:
        _validate_semantic_limit_graph(case_id)

    for fixture_id in SYNTHETIC_FIXTURE_IDS:
        first = build_synthetic_fixture(fixture_id)
        second = build_synthetic_fixture(fixture_id)
        if first != second:
            raise SyntheticFixtureIntegrityError(
                f"{fixture_id} did not rebuild deterministically"
            )
        if first["kind"] == "pdf":
            payload = first["payload"]
            if not isinstance(payload, Mapping):
                raise SyntheticFixtureIntegrityError(
                    f"{fixture_id} PDF payload is not a mapping"
                )
            pdf_bytes = payload.get("pdf_bytes")
            if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(
                _PDF_HEADER
            ):
                raise SyntheticFixtureIntegrityError(
                    f"{fixture_id} did not build a PDF-1.7 document"
                )
            if verify_pdf_readers:
                _verify_pdf_payload(fixture_id, payload)

    return synthetic_fixture_hashes()


if __name__ == "__main__":
    for name, digest in synthetic_self_check(verify_pdf_readers=True).items():
        print(f"{name} {digest}")
