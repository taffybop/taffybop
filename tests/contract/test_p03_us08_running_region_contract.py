"""Dedicated production contracts for P03-US08 running regions."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import logging
import pickle
from collections.abc import Mapping
from copy import copy, deepcopy
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pdfplumber
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import PageIdentity, ParseResult, RunningRegionDescriptor
from app.services import pipeline as pipeline_service
from app.services import running_regions
from app.services.input_documents import InputKind, LoadedDocument, SourcePage
from app.services.ir import DocumentIR, build_document_ir
from app.services.presentation import build_canonical_presentation
from tests.fixtures.phase_03.running_regions.contract import strict_json_bytes
from tests.fixtures.phase_03.running_regions.oracle import (
    PAGE_IDENTITY_DESCRIPTORS,
    PREDECESSOR_OUTPUT_ROOT,
    RUNNING_REGION_DESCRIPTORS,
    SOURCE_IDENTITIES,
)
from tests.fixtures.phase_03.running_regions.synthetic import (
    _assemble_pdf,
    _rendered_label_visibility_pdf,
    _stream,
    build_synthetic_fixture,
)
from tests.stories.phase_03.test_p03_us08_running_regions import (
    _direct_projected_witness,
)

WORKSPACE = Path(__file__).resolve().parents[2]


def _retained_predecessor(case_id: str) -> dict[str, Any]:
    return json.loads(
        (WORKSPACE / PREDECESSOR_OUTPUT_ROOT / case_id / "our-output.json").read_text()
    )


def _source_bytes(case_id: str) -> bytes:
    return (WORKSPACE / SOURCE_IDENTITIES[case_id]["path"]).read_bytes()


@cache
def _catastrophe_inputs() -> tuple[dict[str, Any], DocumentIR, bytes]:
    public = _retained_predecessor("catastrophe-recap")
    return (
        public,
        build_document_ir(deepcopy(public)),
        _source_bytes("catastrophe-recap"),
    )


@cache
def _manufacturing_inputs() -> tuple[dict[str, Any], DocumentIR, bytes]:
    public = _retained_predecessor("manufacturing-report")
    return (
        public,
        build_document_ir(deepcopy(public)),
        _source_bytes("manufacturing-report"),
    )


def _authority(public: dict[str, Any], ir_document: DocumentIR, source: bytes) -> Any:
    return running_regions.prepare_source_projection_authority(
        {
            "public": public,
            "ir": ir_document.model_dump(mode="json", exclude_none=True),
        },
        source,
    )


def _without_running_timing(value: dict[str, Any]) -> dict[str, Any]:
    stable = deepcopy(value)
    summary = stable.get("processing", {}).get("running_regions")
    if isinstance(summary, dict):
        for name in ("extraction_ms", "projection_ms", "total_ms"):
            summary.pop(name, None)
    return stable


def _without_page_identity(page: Mapping[str, Any]) -> dict[str, Any]:
    stable = deepcopy(dict(page))
    stable.pop("page_identity", None)
    return stable


def _ir_page_closure(ir_payload: Mapping[str, Any], page_index: int) -> dict[str, Any]:
    page = next(
        value for value in ir_payload["pages"] if value["page_index"] == page_index
    )
    page_id = page["id"]
    coordinate_systems = [
        value
        for value in ir_payload["coordinate_systems"]
        if value["page_id"] == page_id
    ]
    coordinate_ids = {value["id"] for value in coordinate_systems}
    regions = [value for value in ir_payload["regions"] if value["page_id"] == page_id]
    elements = [
        value for value in ir_payload["elements"] if value["page_id"] == page_id
    ]
    element_ids = {value["id"] for value in elements}
    region_ids = {value["id"] for value in regions}
    bboxes = [
        value
        for value in ir_payload["bboxes"]
        if value["coordinate_system_id"] in coordinate_ids
    ]
    bbox_ids = {value["id"] for value in bboxes}
    evidence = [
        value
        for value in ir_payload["evidence"]
        if value.get("element_id") in element_ids or value.get("bbox_id") in bbox_ids
    ]
    owned_ids = (
        element_ids | region_ids | bbox_ids | {value["id"] for value in evidence}
    )
    closure: dict[str, Any] = {
        "page": page,
        "coordinate_systems": coordinate_systems,
        "regions": regions,
        "elements": elements,
        "bboxes": bboxes,
        "evidence": evidence,
        "relationships": [
            value
            for value in ir_payload.get("relationships", [])
            if value.get("source_id") in owned_ids
            or value.get("target_id") in owned_ids
        ],
    }
    for collection in ("text_rules", "text_runs"):
        closure[collection] = [
            value
            for value in ir_payload.get(collection, [])
            if value.get("page_id") == page_id
            or value.get("element_id") in element_ids
            or value.get("bbox_id") in bbox_ids
        ]
    return closure


def _has_running_region_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        if {
            "layout_running_region_projected",
            "running_region_policy",
            "running_region",
        } & set(value):
            return True
        return any(_has_running_region_marker(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_running_region_marker(child) for child in value)
    return False


def _rendered_label_source(
    pdf_bytes: bytes,
) -> tuple[dict[str, Any], tuple[Any, ...]]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        characters = [
            character
            for character in document.pages[0].chars
            if character.get("text") == "1"
        ]
        assert len(characters) == 1
        character = characters[0]
        return (
            {
                "x": float(character["x0"]),
                "y": float(character["top"]),
                "width": float(character["x1"] - character["x0"]),
                "height": float(character["bottom"] - character["top"]),
                "unit": "pt",
            },
            (deepcopy(character["non_stroking_color"]),),
        )


def _production_visibility(
    pdf_bytes: bytes,
    *,
    fills: tuple[Any, ...] | None = None,
) -> None:
    bbox, source_fills = _rendered_label_source(pdf_bytes)
    running_regions.validate_rendered_label_visibility(
        pdf_bytes,
        physical_page_index=1,
        candidate_visible_text="1",
        candidate_bbox=bbox,
        non_stroking_fills=source_fills if fills is None else fills,
    )


_MINIMAL_CHARACTER_FIELDS = (
    "text",
    "x0",
    "x1",
    "top",
    "bottom",
    "doctop",
    "upright",
    "size",
    "height",
    "width",
    "non_stroking_color",
)


def _single_page_source_reader_pdf(
    content: bytes,
    *,
    mediabox: bytes = b"[0 0 612 792]",
) -> bytes:
    return _assemble_pdf(
        (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox "
                + mediabox
                + b" /Resources << /Font << /F1 5 0 R >> >> "
                b"/Contents 4 0 R >>"
            ),
            _stream(content),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        )
    )


def _line_predecessor_inputs(
    fixture_id: str,
) -> tuple[dict[str, Any], DocumentIR, bytes]:
    """Build the ordinary one-text-owner-per-native-line predecessor."""

    source = build_synthetic_fixture(fixture_id)["payload"]
    assert isinstance(source, bytes)
    source_sha256 = hashlib.sha256(source).hexdigest()
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(source)) as document:
        for page_index, page in enumerate(document.pages, start=1):
            lines = sorted(
                page.extract_text_lines(),
                key=lambda line: (float(line["top"]), float(line["x0"])),
            )
            items = [
                {
                    "id": f"p{page_index}-i{item_index}",
                    "type": "text",
                    "label": "text",
                    "reading_order": item_index - 1,
                    "value": str(line["text"]),
                    "md": str(line["text"]),
                    "bbox": {
                        "x": float(line["x0"]),
                        "y": float(line["top"]),
                        "width": float(line["x1"]) - float(line["x0"]),
                        "height": float(line["bottom"]) - float(line["top"]),
                        "unit": "pt",
                    },
                    "source": "native",
                    "confidence": 1.0,
                }
                for item_index, line in enumerate(lines, start=1)
            ]
            pages.append(
                {
                    "page_index": page_index,
                    "page_number": page_index,
                    "page_label": str(page_index),
                    "page_width": float(page.width),
                    "page_height": float(page.height),
                    "unit": "pt",
                    "success": True,
                    "items": items,
                    "warnings": [],
                }
            )
    public = {
        "schema_version": "1.0",
        "document": {
            "filename": "running-region-synthetic.pdf",
            "mime_type": "application/pdf",
            "sha256": source_sha256,
            "page_count": len(pages),
        },
        "pages": pages,
        "processing": {
            "engine": "synthetic",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 0,
        },
        "warnings": [],
    }
    ir_document = build_document_ir(deepcopy(public))
    public["canonical_presentation"] = build_canonical_presentation(
        ir_document
    ).model_dump(mode="json", exclude_none=True)
    return public, ir_document, source


def _nested_form_source_reader_pdf(depth: int) -> bytes:
    assert depth in {1, 8, 9}
    font_object_number = 5 + depth
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Fm1 5 0 R >> >> "
            b"/Contents 4 0 R >>"
        ),
        _stream(b"q 1 0 0 1 10 20 cm /Fm1 Do Q"),
    ]
    for level in range(1, depth + 1):
        if level < depth:
            next_object_number = 5 + level
            resources = (
                b"<< /XObject << /Fm"
                + str(level + 1).encode("ascii")
                + b" "
                + str(next_object_number).encode("ascii")
                + b" 0 R >> >>"
            )
            data = b"q 1 0 0 1 3 4 cm /Fm" + str(level + 1).encode("ascii") + b" Do Q"
        else:
            resources = (
                b"<< /Font << /F1 "
                + str(font_object_number).encode("ascii")
                + b" 0 R >> >>"
            )
            data = b"BT /F1 12 Tf 1 0 0 1 45 700 Tm (Nested) Tj ET"
        objects.append(
            b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] "
            b"/Resources "
            + resources
            + b" /Length "
            + str(len(data)).encode("ascii")
            + b" >>\nstream\n"
            + data
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    return _assemble_pdf(objects)


def _vertical_source_reader_pdf() -> bytes:
    return _assemble_pdf(
        (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> "
                b"/Contents 4 0 R >>"
            ),
            _stream(b"BT /F1 12 Tf 1 0 0 1 45 700 Tm <00410042> Tj ET"),
            (
                b"<< /Type /Font /Subtype /Type0 /BaseFont /HeiseiMin-W3 "
                b"/Encoding /UniJIS-UCS2-V /DescendantFonts [6 0 R] >>"
            ),
            (
                b"<< /Type /Font /Subtype /CIDFontType0 "
                b"/BaseFont /HeiseiMin-W3 /CIDSystemInfo "
                b"<< /Registry (Adobe) /Ordering (Japan1) /Supplement 2 >> "
                b"/DW 1000 /FontDescriptor 7 0 R >>"
            ),
            (
                b"<< /Type /FontDescriptor /FontName /HeiseiMin-W3 "
                b"/Flags 6 /FontBBox [0 -200 1000 900] /ItalicAngle 0 "
                b"/Ascent 880 /Descent -120 /CapHeight 700 /StemV 80 >>"
            ),
        )
    )


def _assert_source_reader_matches_pdfplumber(pdf_bytes: bytes) -> None:
    actual_pages = running_regions._read_source_pages(pdf_bytes)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as reference_document:
        reference_pages = reference_document.pages
        assert len(actual_pages) == len(reference_pages) == 1
        actual = actual_pages[0]
        reference = reference_pages[0]
        expected_characters = tuple(
            {field: deepcopy(character[field]) for field in _MINIMAL_CHARACTER_FIELDS}
            for character in reference.chars
        )
        expected_words = tuple(deepcopy(reference.extract_words()))
        assert actual.width == float(reference.width)
        assert actual.height == float(reference.height)
    assert actual.chars == expected_characters
    assert actual.words == expected_words


@pytest.mark.parametrize(
    ("case_id", "pdf_bytes"),
    (
        *(
            (
                f"rotation-{rotation}",
                _rendered_label_visibility_pdf(
                    dark_background=True,
                    rotation=rotation,
                ),
            )
            for rotation in (0, 90, 180, 270)
        ),
        (
            "device-gray",
            _rendered_label_visibility_pdf(
                dark_background=True,
                glyph_gray_byte=127,
            ),
        ),
        (
            "device-rgb",
            _rendered_label_visibility_pdf(dark_background=True),
        ),
        (
            "device-cmyk",
            _rendered_label_visibility_pdf(
                dark_background=True,
                glyph_cmyk=(0.1, 0.2, 0.3, 0.4),
            ),
        ),
        (
            "nonzero-mediabox",
            _single_page_source_reader_pdf(
                b"BT /F1 12 Tf 1 0 0 1 45 55 Tm (Media) Tj ET",
                mediabox=b"[17 23 629 815]",
            ),
        ),
        (
            "undefined-glyph",
            _single_page_source_reader_pdf(b"BT /F1 12 Tf 1 0 0 1 45 55 Tm <00> Tj ET"),
        ),
        (
            "inline-image-seek",
            _single_page_source_reader_pdf(
                b"q BI /W 1 /H 1 /BPC 1 /CS /G ID \x00 EI Q "
                b"BT /F1 12 Tf 1 0 0 1 45 55 Tm (After) Tj ET"
            ),
        ),
        ("vertical-font", _vertical_source_reader_pdf()),
        ("form-depth-1", _nested_form_source_reader_pdf(1)),
        ("form-depth-8", _nested_form_source_reader_pdf(8)),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_minimal_source_reader_is_exactly_pdfplumber_equivalent(
    case_id: str,
    pdf_bytes: bytes,
) -> None:
    assert case_id
    _assert_source_reader_matches_pdfplumber(pdf_bytes)


def test_minimal_source_reader_does_not_mutate_pdfminer_logger_configuration() -> None:
    loggers = tuple(
        logging.getLogger(name)
        for name in (
            "pdfminer.pdfdevice",
            "pdfminer.pdfinterp",
            "pdfminer.psparser",
        )
    )

    def configuration(logger: logging.Logger) -> tuple[Any, ...]:
        return (
            logger.level,
            logger.disabled,
            logger.propagate,
            tuple(logger.handlers),
            tuple(logger.filters),
        )

    before = tuple(configuration(logger) for logger in loggers)
    manager_disable = logging.root.manager.disable
    _assert_source_reader_matches_pdfplumber(
        _single_page_source_reader_pdf(
            b"q BI /W 1 /H 1 /BPC 1 /CS /G ID \x00 EI Q "
            b"BT /F1 12 Tf 1 0 0 1 45 55 Tm (After) Tj ET"
        )
    )
    assert tuple(configuration(logger) for logger in loggers) == before
    assert logging.root.manager.disable == manager_disable


def test_structural_pdf_values_never_reach_inherited_debug_logs() -> None:
    secret = "US08-STRUCTURAL-SECRET"
    source = _assemble_pdf(
        (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Secret ("
                + secret.encode("ascii")
                + b") /Resources << /Font << /F1 5 0 R >> >> "
                b"/Contents 4 0 R >>"
            ),
            _stream(b"BT /F1 12 Tf 72 720 Td (Safe) Tj ET"),
            (
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                b"/Secret (" + secret.encode("ascii") + b") >>"
            ),
        )
    )
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    root_logger = logging.getLogger()
    watched = tuple(
        logging.getLogger(name)
        for name in (
            "pdfminer.psparser",
            "pdfminer.pdfdocument",
            "pdfminer.pdfpage",
            "pdfminer.pdfinterp",
        )
    )

    def configuration(logger: logging.Logger) -> tuple[Any, ...]:
        return (
            logger.level,
            logger.disabled,
            logger.propagate,
            tuple(logger.handlers),
            tuple(logger.filters),
        )

    previous_root_level = root_logger.level
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)
    during = (
        configuration(root_logger),
        tuple(configuration(logger) for logger in watched),
    )
    manager_disable = logging.root.manager.disable
    try:
        pages = running_regions._read_source_pages(source)
        after = (
            configuration(root_logger),
            tuple(configuration(logger) for logger in watched),
        )
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(previous_root_level)
    assert len(pages) == 1
    assert secret not in output.getvalue()
    assert after == during
    assert logging.root.manager.disable == manager_disable


def _single_range_cmap(end: int) -> bytes:
    return (
        b"/CIDInit /ProcSet findresource begin\n"
        b"12 dict begin begincmap\n"
        b"1 beginbfrange\n<000000><"
        + f"{end:06X}".encode("ascii")
        + b"><0000>\nendbfrange\n"
        b"endcmap end end"
    )


def test_cmap_preflight_charges_expanded_ranges_at_exact_and_plus_one() -> None:
    assert (
        running_regions._bounded_cmap_mapping_count(
            _single_range_cmap(running_regions.MAX_CHARACTERS_PER_PAGE - 1)
        )
        == running_regions.MAX_CHARACTERS_PER_PAGE
    )
    with pytest.raises(running_regions.RunningRegionResourceLimitError) as raised:
        running_regions._bounded_cmap_mapping_count(
            _single_range_cmap(running_regions.MAX_CHARACTERS_PER_PAGE)
        )
    assert raised.value.resource_name == "source_characters_per_page"

    two_ranges = b"2 beginbfrange\n<0000><0FFF><0000>\n<1000><1FFF><0000>\nendbfrange"
    assert running_regions._bounded_cmap_mapping_count(two_ranges) == 8192


def test_cmap_budget_charges_distinct_streams_once_and_cumulatively() -> None:
    budget = running_regions._ExtractionBudget.start()
    streams = [running_regions.PDFStream({}, bytes((index,))) for index in range(5)]
    for stream in streams[:4]:
        budget.charge_font_mapping(
            stream,
            running_regions.MAX_CHARACTERS_PER_PAGE,
        )
    budget.charge_font_mapping(
        streams[0],
        running_regions.MAX_CHARACTERS_PER_PAGE,
    )
    assert budget.font_mapping_entries == (running_regions.MAX_CHARACTERS_PER_DOCUMENT)
    with pytest.raises(running_regions.RunningRegionResourceLimitError) as raised:
        budget.charge_font_mapping(streams[4], 1)
    assert raised.value.resource_name == "source_characters_per_document"


def test_source_interpreter_keeps_invalid_secret_operands_out_of_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "US08-SECRET-PAYLOAD"
    caplog.set_level(logging.DEBUG)
    with pytest.raises(running_regions.RunningRegionError):
        running_regions._read_source_pages(
            _single_page_source_reader_pdf(f"({secret}) Tc".encode("ascii"))
        )
    assert secret not in caplog.text


def test_source_interpreter_graphics_and_form_depth_caps_are_inclusive() -> None:
    exact = running_regions._read_source_pages(
        _single_page_source_reader_pdf(b"q " * 64 + b"Q " * 64)
    )
    assert exact[0].concern_codes == ()
    exceeded = running_regions._read_source_pages(
        _single_page_source_reader_pdf(b"q " * 65 + b"Q " * 65)
    )
    assert exceeded[0].concern_codes == ("running_region_source_limit",)
    nested = running_regions._read_source_pages(_nested_form_source_reader_pdf(9))
    assert nested[0].concern_codes == ("running_region_source_limit",)


def test_content_token_cap_is_inclusive_and_rejects_maximum_plus_one() -> None:
    exact = running_regions._SourceContentParser(
        [
            running_regions.PDFStream(
                {},
                b"A" * running_regions.MAX_CANDIDATE_TEXT_BYTES + b" ",
            )
        ]
    )
    _position, token = exact.nexttoken()
    assert len(token.name) == running_regions.MAX_CANDIDATE_TEXT_BYTES

    overflow = running_regions._SourceContentParser(
        [
            running_regions.PDFStream(
                {},
                b"A" * (running_regions.MAX_CANDIDATE_TEXT_BYTES + 1) + b" ",
            )
        ]
    )
    with pytest.raises(running_regions.RunningRegionResourceLimitError) as raised:
        overflow.nexttoken()
    assert raised.value.resource_name == "candidate_text_utf8_bytes"


def test_candidate_comparison_overflow_is_page_local_and_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = _retained_predecessor("manufacturing-report")
    ir_document = build_document_ir(deepcopy(public))
    source = _source_bytes("manufacturing-report")
    original = running_regions._ExtractionBudget.charge_comparisons

    def injected(
        budget: Any,
        page_index: int,
        count: int = 1,
    ) -> None:
        if page_index == 2 and budget.comparisons[page_index] >= 10:
            raise running_regions.RunningRegionResourceLimitError(
                "injected page-local candidate limit",
                resource_name="comparisons_per_page",
            )
        original(budget, page_index, count)

    monkeypatch.setattr(
        running_regions._ExtractionBudget,
        "charge_comparisons",
        injected,
    )
    report = running_regions.extract_running_region_source_projection(
        source,
        public,
        ir_document,
    )["source_report"]
    refused = report["pages"][1]
    assert refused["label_candidates"] == []
    assert refused["boundary_candidates"] == []
    assert refused["concern_codes"] == ["running_region_candidate_limit"]
    assert all(
        page["concern_codes"] != ["running_region_candidate_limit"]
        for page in (report["pages"][0], report["pages"][2])
    )


def test_document_candidate_overflow_is_not_refunded_as_page_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, ir_document, source = _manufacturing_inputs()
    public = deepcopy(public)
    ir_document = deepcopy(ir_document)
    original = running_regions.validate_running_region_resource_count

    def injected(name: str, observed: int) -> int:
        if name == "boundary_candidates_per_document" and observed >= 1:
            raise running_regions.RunningRegionResourceLimitError(
                "injected document-wide candidate limit",
                resource_name=name,
            )
        return original(name, observed)

    monkeypatch.setattr(
        running_regions,
        "validate_running_region_resource_count",
        injected,
    )
    with pytest.raises(running_regions.RunningRegionSourceOutcomeError) as raised:
        _authority(public, ir_document, source)
    assert raised.value.code == "running_region_source_limit"


@pytest.mark.parametrize(
    ("fixture_id", "expected"),
    (
        (
            "synthetic:p03-us08:bottom-bare-v1",
            (("24", "printed_label_boundary"),),
        ),
        (
            "synthetic:p03-us08:single-navigation-v1",
            (
                ("CONTENTS", "boundary_navigation"),
                ("NEXT", "boundary_navigation"),
            ),
        ),
    ),
)
def test_ordinary_text_owners_project_standalone_boundary_methods(
    fixture_id: str,
    expected: tuple[tuple[str, str], ...],
) -> None:
    public, ir_document, source = _line_predecessor_inputs(fixture_id)
    authority = _authority(public, ir_document, source)
    projected, _projected_ir = running_regions.project_running_regions(
        public,
        ir_document,
        authority,
    )
    actual = tuple(
        (str(item["value"]), str(item["running_region"]["source_method"]))
        for item in projected["pages"][0]["items"]
        if isinstance(item.get("running_region"), Mapping)
    )
    assert actual == expected
    if fixture_id.endswith("bottom-bare-v1"):
        identity = projected["pages"][0]["page_identity"]
        assert identity["detected_printed_label"] == "24"
        assert identity["visible_text"] == "24"


@pytest.mark.parametrize(
    "declared",
    ("SEC RET", "S E C R E T", "SE C RET"),
)
def test_structured_scalar_comparator_rejects_intraword_whitespace(
    declared: str,
) -> None:
    assert not running_regions._structured_native_scalar_matches(
        declared,
        ((0, {"text": "SECRET", "upright": True}),),
    )


def test_fused_word_whitespace_requires_each_source_geometry_gap() -> None:
    page = running_regions._read_source_pages(_source_bytes("clinical-study"))[1]
    word_index, word = next(
        (index, value)
        for index, value in enumerate(page.words)
        if value.get("text")
        == "DigitalmentalhealthforSyrianrefugeesinEgypt:ApragmaticRCT"
    )
    native_words = ((word_index, word),)
    legitimate = "Digital mental health for Syrian refugees in Egypt: A pragmatic RCT"
    arbitrary_split = (
        "Digi tal mental health for Syrian refugees in Egypt: A pragmatic RCT"
    )
    assert not running_regions._structured_native_scalar_matches(
        arbitrary_split,
        native_words,
    )
    boundaries = running_regions._native_word_geometry_boundaries(
        page,
        native_words,
        budget=None,
        character_index=running_regions._PageCharacterIndex.build(page),
        boundary_cache={},
    )
    assert running_regions._structured_native_scalar_matches(
        legitimate,
        native_words,
        fused_word_boundaries=boundaries,
    )
    assert not running_regions._structured_native_scalar_matches(
        arbitrary_split,
        native_words,
        fused_word_boundaries=boundaries,
    )


def test_structured_owner_intraword_tamper_is_not_a_source_candidate() -> None:
    public, _ir_document, source = _catastrophe_inputs()
    public = deepcopy(public)
    owner = next(
        item
        for page in public["pages"]
        for item in page["items"]
        if item.get("id") == "p1-i6"
    )
    child = owner["items"][0]
    for target in (owner, child):
        for field in ("value", "md"):
            target[field] = target[field].replace("Global", "Glo bal")
    ir_document = build_document_ir(deepcopy(public))
    public["canonical_presentation"] = build_canonical_presentation(
        ir_document
    ).model_dump(mode="json", exclude_none=True)
    report = running_regions.extract_running_region_source_projection(
        source,
        public,
        ir_document,
    )["source_report"]
    candidates = [
        candidate
        for page in report["pages"]
        for candidate in page["boundary_candidates"]
    ]
    assert all(candidate["public_item_id"] != "p1-i6" for candidate in candidates)


def test_fused_clinical_owner_arbitrary_split_is_not_a_source_candidate() -> None:
    public = deepcopy(_retained_predecessor("clinical-study"))
    owner = next(
        item
        for page in public["pages"]
        for item in page["items"]
        if item.get("id") == "p2-i1"
    )
    child = owner["items"][1]
    for target in (owner, child):
        for field in ("value", "md"):
            target[field] = target[field].replace(
                "Digital mental",
                "Digi tal mental",
            )
    ir_document = build_document_ir(deepcopy(public))
    public["canonical_presentation"] = build_canonical_presentation(
        ir_document
    ).model_dump(mode="json", exclude_none=True)
    source = _source_bytes("clinical-study")
    report = running_regions.extract_running_region_source_projection(
        source,
        public,
        ir_document,
    )["source_report"]
    assert all(
        candidate["public_item_id"] != "p2-i1"
        for page in report["pages"]
        for candidate in page["boundary_candidates"]
    )
    authority = _authority(public, ir_document, source)
    projected, projected_ir = running_regions.project_running_regions(
        public,
        ir_document,
        authority,
    )
    ParseResult.model_validate(projected)
    projected_owner = next(
        item
        for page in projected["pages"]
        for item in page["items"]
        if item.get("id") == "p2-i1"
    )
    assert not _has_running_region_marker(projected_owner)
    assert all(
        element.running_region is None
        or element.running_region.source_public_item_id != "p2-i1"
        for element in projected_ir.elements
    )


def test_authority_rejects_an_unused_method_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, ir_document, source = _catastrophe_inputs()
    public = deepcopy(public)
    ir_document = deepcopy(ir_document)
    extracted = deepcopy(
        running_regions.extract_running_region_source_projection(
            source,
            public,
            ir_document,
        )
    )
    extracted["method_proofs"]["unused-proof"] = {}
    monkeypatch.setattr(
        running_regions,
        "_extract_running_region_source_projection",
        lambda *_args, **_kwargs: deepcopy(extracted),
    )
    with pytest.raises(running_regions.RunningRegionSourceOutcomeError) as raised:
        _authority(public, ir_document, source)
    assert raised.value.code == "running_region_source_evidence_unavailable"


def test_extracted_synthetics_append_with_contiguous_stable_reading_order() -> None:
    predecessor, predecessor_ir, source = _manufacturing_inputs()
    predecessor = deepcopy(predecessor)
    predecessor_ir = deepcopy(predecessor_ir)
    authority = _authority(predecessor, predecessor_ir, source)
    projected, projected_ir = running_regions.project_running_regions(
        predecessor,
        predecessor_ir,
        authority,
    )
    ParseResult.model_validate(projected)
    page_index = 2
    predecessor_items = predecessor["pages"][page_index - 1]["items"]
    projected_items = projected["pages"][page_index - 1]["items"]
    synthetics = [
        item
        for item in projected_items[len(predecessor_items) :]
        if item.get("running_region", {}).get("source_method")
        == "extracted_source_contribution"
    ]
    assert synthetics
    assert [item["reading_order"] for item in synthetics] == list(
        range(
            max(item["reading_order"] for item in predecessor_items) + 1,
            max(item["reading_order"] for item in predecessor_items)
            + 1
            + len(synthetics),
        )
    )
    descriptor_ids = [item["running_region"]["id"] for item in synthetics]
    assert descriptor_ids == sorted(descriptor_ids)
    synthetic_element_ids = [
        item["running_region"]["source_element_id"] for item in synthetics
    ]
    ir_page = next(page for page in projected_ir.pages if page.page_index == page_index)
    assert ir_page.presentation_element_ids[-len(synthetics) :] == (
        synthetic_element_ids
    )
    elements = {
        element.id: element
        for element in projected_ir.elements
        if element.id in synthetic_element_ids
    }
    assert [
        elements[element_id].reading_order for element_id in synthetic_element_ids
    ] == [item["reading_order"] for item in synthetics]


def test_running_regions_flag_defaults_off_and_has_exact_prerequisites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().layout_running_regions_enabled is False
    for name in (
        "PARSER_SHARED_IR_ENABLED",
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "PARSER_CANONICAL_SERIALIZATION_ENABLED",
        "PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED",
        "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    settings = Settings.from_env()
    assert settings.layout_running_regions_enabled is True
    assert settings.layout_text_run_semantics_enabled is False
    assert settings.layout_forms_enabled is False
    assert settings.layout_outline_structure_enabled is False

    prerequisites = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "layout_relationship_order_enabled": True,
        "layout_running_regions_enabled": True,
    }
    assert Settings(**prerequisites).layout_running_regions_enabled is True
    for field in (
        "shared_ir_enabled",
        "shared_ir_normalization_enabled",
        "canonical_serialization_enabled",
        "layout_relationship_order_enabled",
    ):
        invalid = {**prerequisites, field: False}
        with pytest.raises(ValueError):
            Settings(**invalid)


def test_public_identity_and_descriptor_models_are_closed_oracle_contracts() -> None:
    page_identity = next(iter(PAGE_IDENTITY_DESCRIPTORS.values()))
    descriptor = next(iter(RUNNING_REGION_DESCRIPTORS.values()))
    assert PageIdentity.model_validate(page_identity).model_dump(mode="json") == (
        json.loads(json.dumps(page_identity))
    )
    assert RunningRegionDescriptor.model_validate(descriptor).model_dump(
        mode="json"
    ) == json.loads(json.dumps(descriptor))

    for model, value in (
        (PageIdentity, page_identity),
        (RunningRegionDescriptor, descriptor),
    ):
        unknown = {**deepcopy(value), "unsupported": True}
        with pytest.raises(ValidationError):
            model.model_validate(unknown)

    printed = deepcopy(
        next(
            value
            for value in RUNNING_REGION_DESCRIPTORS.values()
            if value["source_method"] == "printed_label_boundary"
        )
    )
    printed["role"] = "navigation_bottom"
    with pytest.raises(ValidationError, match="printed-label"):
        RunningRegionDescriptor.model_validate(printed)

    fallback = deepcopy(
        next(
            value
            for value in PAGE_IDENTITY_DESCRIPTORS.values()
            if value["display_source"] == "legacy_display_fallback"
        )
    )
    fallback["display_source"] = "physical"
    fallback["display_label"] = str(fallback["physical_page_index"])
    fallback["evidence_source"].update(
        {
            "method": "physical_page_index",
            "reader": "configured_predecessor",
            "evidence_ids": [],
            "source_object_ids": [],
        }
    )
    fallback["confidence"]["unavailable_reason"] = (
        "page_identity_display_fallback_physical"
    )
    assert PageIdentity.model_validate(fallback)

    wrong_label = deepcopy(fallback)
    wrong_label["display_label"] = "999"
    with pytest.raises(ValidationError, match="physical page identity label"):
        PageIdentity.model_validate(wrong_label)

    wrong_evidence = deepcopy(fallback)
    wrong_evidence["evidence_source"].update(
        {
            "method": "embedded_pdf_label",
            "reader": "pypdfium2",
            "evidence_ids": ["embedded-label-evidence"],
            "source_object_ids": ["embedded-label-object"],
        }
    )
    with pytest.raises(ValidationError, match="display/evidence"):
        PageIdentity.model_validate(wrong_evidence)


def test_public_and_ir_models_reject_partial_or_unknown_running_sidecars() -> None:
    projected, ir_document, _predecessor, _predecessor_ir = _direct_projected_witness()
    identity = projected["pages"][0]["page_identity"]
    descriptor = projected["pages"][0]["items"][0]["running_region"]
    assert PageIdentity.model_validate(identity)
    assert RunningRegionDescriptor.model_validate(descriptor)

    missing_identity_field = deepcopy(identity)
    missing_identity_field.pop("display_source")
    unknown_descriptor_field = {**deepcopy(descriptor), "proof": {}}
    with pytest.raises(ValidationError):
        PageIdentity.model_validate(missing_identity_field)
    with pytest.raises(ValidationError):
        RunningRegionDescriptor.model_validate(unknown_descriptor_field)

    # The exact same strict models are used on the IR surfaces.
    assert PageIdentity.model_validate(ir_document["pages"][0]["page_identity"])
    assert RunningRegionDescriptor.model_validate(
        ir_document["elements"][0]["running_region"]
    )


def test_production_rendered_visibility_matches_synthetic_rotation_mode_and_threshold_controls() -> (
    None
):
    for rotation in (0, 90, 180, 270):
        visible = _rendered_label_visibility_pdf(
            dark_background=True,
            rotation=rotation,
        )
        assert _production_visibility(visible) is None
        hidden = _rendered_label_visibility_pdf(
            dark_background=False,
            rotation=rotation,
        )
        with pytest.raises(
            running_regions.RunningRegionError,
            match="render/fill contrast",
        ):
            _production_visibility(hidden)

    for render_mode in (0, 2, 4, 6):
        painted = _rendered_label_visibility_pdf(
            dark_background=False,
            split_background=True,
            text_render_mode=render_mode,
        )
        assert _production_visibility(painted) is None
    for render_mode in (1, 3, 5, 7):
        unpainted = _rendered_label_visibility_pdf(
            dark_background=False,
            split_background=True,
            text_render_mode=render_mode,
        )
        with pytest.raises(running_regions.RunningRegionError):
            _production_visibility(unpainted)

    transparent = _rendered_label_visibility_pdf(
        dark_background=False,
        split_background=True,
        transparent_fill=True,
    )
    with pytest.raises(running_regions.RunningRegionError):
        _production_visibility(transparent)

    exact_threshold = _rendered_label_visibility_pdf(
        dark_background=False,
        glyph_gray_byte=239,
    )
    assert _production_visibility(exact_threshold) is None
    below_threshold = _rendered_label_visibility_pdf(
        dark_background=False,
        glyph_gray_byte=240,
    )
    with pytest.raises(
        running_regions.RunningRegionError,
        match="render/fill contrast",
    ):
        _production_visibility(below_threshold)

    retained_cmyk = (0.2, 0.8, 0.5, 0.0)
    cmyk = _rendered_label_visibility_pdf(
        dark_background=False,
        glyph_cmyk=retained_cmyk,
    )
    assert _production_visibility(cmyk) is None
    with pytest.raises(
        running_regions.RunningRegionError,
        match="fill/object custody",
    ):
        _production_visibility(
            cmyk,
            fills=((0.2, 205.0 / 255.0, 0.5, 0.0),),
        )


def test_flag_off_is_the_first_branch_and_returns_exact_input_identities() -> None:
    public = object()
    ir_document = object()
    authority = object()
    metrics: dict[str, Any] = {"preexisting": True}
    actual_public, actual_ir = running_regions.project_running_regions(
        public,  # type: ignore[arg-type]
        ir_document,  # type: ignore[arg-type]
        authority,  # type: ignore[arg-type]
        enabled=False,
        metrics=metrics,
    )
    assert actual_public is public
    assert actual_ir is ir_document
    assert metrics == {"preexisting": True}


def test_factory_runs_fixed_extractor_twice_and_ignores_only_report_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, ir_document, source = _catastrophe_inputs()
    envelope = running_regions.extract_running_region_source_projection(
        source,
        public,
        ir_document,
    )
    calls = 0

    def timing_only(
        source_pdf_bytes: bytes,
        configured_predecessor: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        assert source_pdf_bytes == source
        assert configured_predecessor["public"] == public
        assert configured_predecessor["ir"] == ir_document.model_dump(
            mode="json", exclude_none=True
        )
        value = deepcopy(envelope)
        if calls == 2:
            value["source_report"]["extraction_ms"] += 0.001
        return value

    monkeypatch.setattr(
        running_regions,
        "_extract_running_region_source_projection",
        timing_only,
    )
    authority = _authority(public, ir_document, source)
    assert calls == 2
    projected, projected_ir = running_regions.project_running_regions(
        public,
        ir_document,
        authority,
    )
    assert projected["processing"]["running_regions"]["status"] == "projected"
    assert projected_ir.pages[0].page_identity is not None


def test_factory_rejects_semantic_dual_run_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, ir_document, source = _catastrophe_inputs()
    envelope = running_regions.extract_running_region_source_projection(
        source,
        public,
        ir_document,
    )
    calls = 0

    def drifting(
        _source_pdf_bytes: bytes,
        _configured_predecessor: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        value = deepcopy(envelope)
        if calls == 2:
            value["source_report"]["pages"][0]["source_character_count"] += 1
            value["source_report"]["counts"]["source_character_count"] += 1
        return value

    monkeypatch.setattr(
        running_regions,
        "_extract_running_region_source_projection",
        drifting,
    )
    with pytest.raises(ValueError, match="nondeterministic"):
        _authority(public, ir_document, source)


def test_authority_is_opaque_noncopyable_and_bound_to_bytes_and_predecessor() -> None:
    public, ir_document, source = _catastrophe_inputs()
    authority = _authority(public, ir_document, source)
    for operation in (
        lambda: copy(authority),
        lambda: deepcopy(authority),
        lambda: pickle.dumps(authority),
        lambda: setattr(authority, "source_sha256", "0" * 64),
    ):
        with pytest.raises(ValueError):
            operation()

    with pytest.raises(ValueError):
        running_regions.prepare_source_projection_authority(
            {
                "public": public,
                "ir": ir_document.model_dump(mode="json", exclude_none=True),
            },
            source + b"wrong-source",
        )
    with pytest.raises(ValueError):
        running_regions.project_running_regions(
            public,
            ir_document,
            {"source_report": {"lookalike": True}},  # type: ignore[arg-type]
        )
    diagnostic_envelope = running_regions.extract_running_region_source_projection(
        source,
        public,
        ir_document,
    )
    with pytest.raises(ValueError):
        running_regions.project_running_regions(
            public,
            ir_document,
            diagnostic_envelope,  # type: ignore[arg-type]
        )

    changed_public = deepcopy(public)
    changed_public["authority_drift"] = True
    with pytest.raises(ValueError):
        running_regions.project_running_regions(
            changed_public,
            ir_document,
            authority,
        )
    changed_ir = ir_document.model_copy(
        update={"id": f"{ir_document.id}-authority-drift"}
    )
    with pytest.raises(ValueError):
        running_regions.project_running_regions(
            public,
            changed_ir,
            authority,
        )

    for drift in (True, 1.0):
        typed_public = deepcopy(public)
        typed_public["pages"][0]["page_index"] = drift
        with pytest.raises(ValueError, match="custody"):
            running_regions.project_running_regions(
                typed_public,
                ir_document,
                authority,
            )

        typed_ir = deepcopy(ir_document)
        typed_ir.pages[0].page_index = drift
        with pytest.raises(ValueError, match="custody"):
            running_regions.project_running_regions(
                public,
                typed_ir,
                authority,
            )

    assert not hasattr(authority, "predecessor_template_pickle")
    object.__setattr__(authority, "_registry_token", object())
    with pytest.raises(ValueError, match="factory-issued"):
        running_regions.project_running_regions(
            public,
            ir_document,
            authority,
        )
    object.__delattr__(authority, "_registry_token")
    with pytest.raises(ValueError, match="factory-issued"):
        running_regions.project_running_regions(
            public,
            ir_document,
            authority,
        )


def test_owner_binding_uses_current_presentation_order_not_source_position() -> None:
    public, ir_document, _source = _catastrophe_inputs()
    reordered_public = deepcopy(public)
    reordered_ir = ir_document.model_dump(mode="json", exclude_none=True)
    first_public_page = reordered_public["pages"][0]
    first_ir_page = next(
        page
        for page in reordered_ir["pages"]
        if page["page_index"] == first_public_page["page_index"]
    )
    assert len(first_public_page["items"]) >= 2
    original_presentation_ids = list(first_ir_page["presentation_element_ids"])
    first_public_page["items"].reverse()
    first_ir_page["presentation_element_ids"].reverse()

    by_position, _by_public_id, _canonical = running_regions._owner_indexes(
        reordered_public,
        reordered_ir,
    )

    assert [
        by_position[(first_public_page["page_index"], offset)]["id"]
        for offset in range(len(first_public_page["items"]))
    ] == list(reversed(original_presentation_ids))
    assert [
        by_position[(first_public_page["page_index"], offset)]["properties"][
            "source_position"
        ]
        for offset in range(len(first_public_page["items"]))
    ] != list(range(len(first_public_page["items"])))

    mismatched_ir = ir_document.model_dump(mode="json", exclude_none=True)
    mismatched_page = next(
        page
        for page in mismatched_ir["pages"]
        if page["page_index"] == public["pages"][0]["page_index"]
    )
    mismatched_page["presentation_element_ids"][:2] = reversed(
        mismatched_page["presentation_element_ids"][:2]
    )
    with pytest.raises(
        running_regions.RunningRegionError,
        match="presentation owner binding",
    ):
        running_regions._owner_indexes(public, mismatched_ir)


def test_multi_bbox_owner_requires_one_exact_public_bbox_match() -> None:
    public_item = {
        "bbox": {
            "x": 10.0,
            "y": 20.0,
            "width": 30.0,
            "height": 40.0,
            "unit": "pt",
        }
    }
    element = {"bbox_ids": ["other", "exact"]}
    bboxes = {
        "other": {
            "x": 11.0,
            "y": 20.0,
            "width": 30.0,
            "height": 40.0,
            "unit": "pt",
        },
        "exact": deepcopy(public_item["bbox"]),
    }
    assert running_regions._element_bbox(
        element,
        bboxes,
        public_item,
    ) == ("exact", public_item["bbox"])

    no_match = deepcopy(bboxes)
    no_match["exact"]["x"] = 12.0
    with pytest.raises(
        running_regions.RunningRegionError,
        match="bbox custody",
    ):
        running_regions._element_bbox(element, no_match, public_item)

    ambiguous = deepcopy(bboxes)
    ambiguous["other"] = deepcopy(public_item["bbox"])
    with pytest.raises(
        running_regions.RunningRegionError,
        match="bbox custody",
    ):
        running_regions._element_bbox(element, ambiguous, public_item)


def test_direct_candidate_retains_only_evidence_for_selected_owner_bbox() -> None:
    element = {
        "id": "element-1",
        "evidence_ids": ["primary-evidence", "nested-provenance"],
    }
    evidence = {
        "primary-evidence": {
            "id": "primary-evidence",
            "element_id": "element-1",
            "bbox_id": "primary-box",
        },
        "nested-provenance": {
            "id": "nested-provenance",
            "element_id": "element-1",
            "bbox_id": "nested-box",
        },
    }

    assert running_regions._direct_candidate_evidence_ids(
        element=element,
        bbox_id="primary-box",
        evidence_records=evidence,
    ) == ["primary-evidence"]

    with pytest.raises(
        running_regions.RunningRegionError,
        match="source references",
    ):
        running_regions._direct_candidate_evidence_ids(
            element=element,
            bbox_id="absent-box",
            evidence_records=evidence,
        )


@pytest.mark.parametrize("reading_order", ["0", False])
def test_compact_predecessor_item_rejects_numeric_type_drift(
    reading_order: Any,
) -> None:
    with pytest.raises(
        running_regions.RunningRegionError,
        match="compact public item differs",
    ):
        running_regions._compact_public_item_payload(
            {
                "id": "owner-1",
                "type": "footer",
                "reading_order": reading_order,
                "value": "Footer",
                "confidence": None,
            }
        )


def test_compact_predecessor_item_omits_only_top_level_nulls() -> None:
    item = {
        "id": "owner-1",
        "type": "footer",
        "reading_order": 0,
        "value": "Footer",
        "confidence": None,
        "items": [{"value": "Footer", "confidence": None}],
    }

    assert running_regions._compact_public_item_payload(item) == {
        key: value for key, value in item.items() if key != "confidence"
    }


def test_projection_is_deterministic_idempotent_and_strip_is_exact_inverse() -> None:
    public, ir_document, source = _catastrophe_inputs()
    authority = _authority(public, ir_document, source)
    first_public, first_ir = running_regions.project_running_regions(
        public,
        ir_document,
        authority,
    )
    second_public, second_ir = running_regions.project_running_regions(
        public,
        ir_document,
        authority,
    )
    assert first_ir.validate_graph() is first_ir
    assert second_ir.validate_graph() is second_ir
    assert strict_json_bytes(_without_running_timing(first_public)) == (
        strict_json_bytes(_without_running_timing(second_public))
    )
    assert first_ir.model_dump(mode="json") == second_ir.model_dump(mode="json")

    repeated_public, repeated_ir = running_regions.project_running_regions(
        first_public,
        first_ir,
        authority,
    )
    assert strict_json_bytes(repeated_public) == strict_json_bytes(first_public)
    assert repeated_ir.model_dump(mode="json") == first_ir.model_dump(mode="json")

    projected_public_bytes = strict_json_bytes(first_public)
    projected_ir_bytes = strict_json_bytes(first_ir.model_dump(mode="json"))
    stripped_public, stripped_ir = running_regions.strip_running_regions(
        first_public,
        first_ir,
    )
    assert strict_json_bytes(first_public) == projected_public_bytes
    assert strict_json_bytes(first_ir.model_dump(mode="json")) == (projected_ir_bytes)
    assert strict_json_bytes(stripped_public) == strict_json_bytes(public)
    assert stripped_ir.model_dump(mode="json", exclude_none=True) == (
        ir_document.model_dump(mode="json", exclude_none=True)
    )
    assert running_regions.strip_running_regions(first_public) == public
    assert running_regions.strip_running_regions(stripped_public) == stripped_public

    partial = deepcopy(first_public)
    projected_item = next(
        item
        for page in partial["pages"]
        for item in page["items"]
        if item.get("layout_running_region_projected") is True
    )
    projected_item.pop("running_region_policy")
    with pytest.raises(ValueError):
        running_regions.strip_running_regions(partial)

    second_public_bytes = strict_json_bytes(second_public)
    second_ir_bytes = strict_json_bytes(second_ir.model_dump(mode="json"))
    predecessor_public_bytes = strict_json_bytes(public)
    predecessor_ir_bytes = strict_json_bytes(ir_document.model_dump(mode="json"))
    first_public["pages"][0]["items"][0]["value"] = "alias-probe"
    first_ir.elements[0].properties["alias_probe"] = True
    assert strict_json_bytes(second_public) == second_public_bytes
    assert strict_json_bytes(second_ir.model_dump(mode="json")) == second_ir_bytes
    assert strict_json_bytes(public) == predecessor_public_bytes
    assert strict_json_bytes(ir_document.model_dump(mode="json")) == (
        predecessor_ir_bytes
    )


def test_paired_strip_removes_exact_legacy_running_sidecars() -> None:
    public, ir_document, source = _catastrophe_inputs()
    authority = _authority(public, ir_document, source)
    projected_public, projected_ir = running_regions.project_running_regions(
        public,
        ir_document,
        authority,
    )
    projected_ir = deepcopy(projected_ir)
    element = next(
        value for value in projected_ir.elements if value.running_region is not None
    )
    descriptor = element.running_region
    projected_owner = next(
        item
        for page in projected_public["pages"]
        for item in page["items"]
        if item.get("id") == descriptor.source_public_item_id
    )
    legacy = deepcopy(element.properties["legacy_item"])
    for key in (
        "layout_running_region_projected",
        "running_region_policy",
        "running_region",
    ):
        legacy[key] = deepcopy(projected_owner[key])
    legacy["type"] = projected_owner["type"]
    element.properties["legacy_item"] = legacy

    _stripped_public, stripped_ir = running_regions.strip_running_regions(
        projected_public,
        projected_ir,
    )

    stripped_element = next(
        value for value in stripped_ir.elements if value.id == element.id
    )
    assert stripped_element.properties["legacy_item"]["type"] == (
        descriptor.predecessor_type
    )
    assert not {
        "layout_running_region_projected",
        "running_region_policy",
        "running_region",
    }.intersection(stripped_element.properties["legacy_item"])

    partial_ir = deepcopy(projected_ir)
    partial_element = next(
        value for value in partial_ir.elements if value.id == element.id
    )
    partial_element.properties["legacy_item"].pop("running_region_policy")
    with pytest.raises(
        running_regions.RunningRegionError,
        match="IR legacy owner",
    ):
        running_regions.strip_running_regions(projected_public, partial_ir)


def test_repeat_projection_authenticates_every_derived_surface_and_authority() -> None:
    public, ir_document, source = _catastrophe_inputs()
    authority = _authority(public, ir_document, source)
    projected, projected_ir = running_regions.project_running_regions(
        public,
        ir_document,
        authority,
    )

    summary_tamper = deepcopy(projected)
    summary_tamper["processing"]["running_regions"]["candidate_count"] += 1
    with pytest.raises(
        running_regions.RunningRegionError,
        match="authenticated state",
    ):
        running_regions.project_running_regions(
            summary_tamper,
            projected_ir,
            authority,
        )

    view_tamper = deepcopy(projected)
    view_tamper["canonical_presentation"]["pages"][0]["footer"]["markdown"] += (
        "tampered"
    )
    with pytest.raises(
        running_regions.RunningRegionError,
        match="authenticated state",
    ):
        running_regions.project_running_regions(
            view_tamper,
            projected_ir,
            authority,
        )

    binding_public = deepcopy(projected)
    binding_ir = deepcopy(projected_ir)
    marked_item = next(
        item
        for page in binding_public["pages"]
        for item in page["items"]
        if item.get("layout_running_region_projected") is True
    )
    descriptor_id = marked_item["running_region"]["id"]
    wrong_block_id = next(
        block["id"]
        for page in binding_public["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block["id"] != marked_item["running_region"]["canonical_block_id"]
    )
    marked_item["running_region"]["canonical_block_id"] = wrong_block_id
    matching_element = next(
        element
        for element in binding_ir.elements
        if element.running_region is not None
        and element.running_region.id == descriptor_id
    )
    matching_element.running_region.canonical_block_id = wrong_block_id
    with pytest.raises(running_regions.RunningRegionError):
        running_regions.project_running_regions(
            binding_public,
            binding_ir,
            authority,
        )

    other_public = deepcopy(public)
    other_public["same_source_authority_probe"] = "different-predecessor"
    wrong_authority = _authority(
        other_public,
        build_document_ir(deepcopy(other_public)),
        source,
    )
    with pytest.raises(
        running_regions.RunningRegionError,
        match="predecessor",
    ):
        running_regions.project_running_regions(
            projected,
            projected_ir,
            wrong_authority,
        )


def test_page_commit_failure_rolls_back_only_its_complete_page_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, ir_document, source = _manufacturing_inputs()
    public_before = strict_json_bytes(public)
    ir_before = strict_json_bytes(
        ir_document.model_dump(mode="json", exclude_none=True)
    )
    baseline, baseline_ir = running_regions.project_running_regions(
        public,
        ir_document,
        _authority(public, ir_document, source),
    )
    original_commit = running_regions._commit_projected_page
    calls: list[int] = []
    staged_page_two: dict[str, bool] = {}

    def fail_page_two(
        page_index: int,
        public_page: dict[str, Any],
        ir_page: Any,
    ) -> None:
        calls.append(page_index)
        if page_index == 2:
            staged_page_two.update(
                {
                    "public_identity": "page_identity" in public_page,
                    "public_running": _has_running_region_marker(public_page),
                    "synthetic_item": any(
                        str(item.get("id", "")).startswith("running-region-item-")
                        for item in public_page["items"]
                    ),
                    "ir_identity": ir_page.page_identity is not None,
                }
            )
            raise RuntimeError(
                "must-not-leak /tmp/private.pdf <script>source text</script>"
            )
        original_commit(page_index, public_page, ir_page)

    monkeypatch.setattr(
        running_regions,
        "_commit_projected_page",
        fail_page_two,
    )
    actual, actual_ir = running_regions.project_running_regions(
        public,
        ir_document,
        _authority(public, ir_document, source),
    )

    assert calls == [1, 2, 3]
    assert staged_page_two == {
        "public_identity": True,
        "public_running": True,
        "synthetic_item": True,
        "ir_identity": True,
    }
    assert strict_json_bytes(public) == public_before
    assert (
        strict_json_bytes(ir_document.model_dump(mode="json", exclude_none=True))
        == ir_before
    )
    assert actual["processing"]["running_regions"]["status"] == "projected"
    assert actual["processing"]["running_regions"]["concern_count"] == 1
    assert actual["running_region_concerns"] == [
        {
            "code": "running_region_projection_failed_closed",
            "source_ref": "page:2",
            "count": 1,
            "cap": 64,
            "exception_class": None,
        }
    ]
    assert "must-not-leak" not in json.dumps(actual)
    assert "/tmp/private.pdf" not in json.dumps(actual)
    assert "source text" not in json.dumps(actual)

    actual_pages = {page["page_index"]: page for page in actual["pages"]}
    baseline_pages = {page["page_index"]: page for page in baseline["pages"]}
    predecessor_pages = {page["page_index"]: page for page in public["pages"]}
    failed_identity = actual_pages[2]["page_identity"]
    assert PageIdentity.model_validate(failed_identity)
    assert failed_identity["physical_page_index"] == 2
    assert failed_identity["display_source"] == "legacy_display_fallback"
    assert failed_identity["display_label"] == "2"
    assert failed_identity["concern_codes"] == [
        "running_region_projection_failed_closed"
    ]
    assert _without_page_identity(actual_pages[2]) == predecessor_pages[2]
    assert not _has_running_region_marker(actual_pages[2])
    for page_index in (1, 3):
        assert actual_pages[page_index] == baseline_pages[page_index]

    actual_canonical = {
        page["page_index"]: page for page in actual["canonical_presentation"]["pages"]
    }
    baseline_canonical = {
        page["page_index"]: page for page in baseline["canonical_presentation"]["pages"]
    }
    predecessor_canonical = {
        page["page_index"]: page for page in public["canonical_presentation"]["pages"]
    }
    assert actual_canonical[2]["page_identity"] == failed_identity
    assert _without_page_identity(actual_canonical[2]) == (predecessor_canonical[2])
    for page_index in (1, 3):
        assert actual_canonical[page_index] == baseline_canonical[page_index]
    for view_name in ("body", "header", "footer", "full"):
        page_views = [
            actual_canonical[page_index][view_name]
            for page_index in sorted(actual_canonical)
        ]
        expected_block_ids = [
            block_id for page_view in page_views for block_id in page_view["block_ids"]
        ]
        markdown = "\n\n".join(
            page_view["markdown"].strip()
            for page_view in page_views
            if page_view["markdown"].strip()
        )
        text = "\n\n".join(
            page_view["text"].strip()
            for page_view in page_views
            if page_view["text"].strip()
        )

        assert actual["canonical_presentation"][view_name] == {
            "block_ids": expected_block_ids,
            "markdown": f"{markdown}\n" if markdown else "",
            "text": f"{text}\n" if text else "",
        }
    failed_baseline_block_ids = {
        item["running_region"]["canonical_block_id"]
        for item in baseline_pages[2]["items"]
        if item.get("layout_running_region_projected") is True
        and item["running_region"]["source_method"] == "extracted_source_contribution"
    }
    assert failed_baseline_block_ids
    assert failed_baseline_block_ids.isdisjoint(
        actual["canonical_presentation"]["full"]["block_ids"]
    )

    actual_ir_payload = actual_ir.model_dump(mode="json")
    baseline_ir_payload = baseline_ir.model_dump(mode="json")
    predecessor_ir_payload = ir_document.model_dump(mode="json")
    failed_ir_closure = _ir_page_closure(actual_ir_payload, 2)
    assert failed_ir_closure["page"]["page_identity"] == failed_identity
    failed_ir_closure["page"].pop("page_identity")
    assert strict_json_bytes(failed_ir_closure) == strict_json_bytes(
        _ir_page_closure(predecessor_ir_payload, 2)
    )
    for page_index in (1, 3):
        assert strict_json_bytes(
            _ir_page_closure(actual_ir_payload, page_index)
        ) == strict_json_bytes(_ir_page_closure(baseline_ir_payload, page_index))


def test_projected_concern_ledger_correlates_every_occurrence_exactly() -> None:
    records = running_regions._projected_concern_records(
        {
            "concern_codes": ["running_region_geometry_ambiguous"],
            "pages": [
                {
                    "page_index": 1,
                    "concern_codes": ["page_identity_embedded_label_invalid"],
                    "label_candidates": [
                        {"concern_codes": ["running_region_ownership_conflict"]}
                    ],
                    "boundary_candidates": [
                        {"concern_codes": ["running_region_repetition_ambiguous"]}
                    ],
                }
            ],
        },
        [
            {
                "page_index": 1,
                "page_identity": {
                    "concern_codes": [
                        "page_identity_embedded_label_invalid",
                        "running_region_ownership_conflict",
                    ]
                },
                "items": [
                    {
                        "running_region": {
                            "concern_codes": ["running_region_repetition_ambiguous"]
                        }
                    }
                ],
            }
        ],
    )
    assert records == [
        {
            "code": "running_region_geometry_ambiguous",
            "source_ref": "document",
            "count": 1,
            "cap": 256,
            "exception_class": None,
        },
        {
            "code": "page_identity_embedded_label_invalid",
            "source_ref": "page:1",
            "count": 2,
            "cap": 64,
            "exception_class": None,
        },
        {
            "code": "running_region_ownership_conflict",
            "source_ref": "page:1",
            "count": 2,
            "cap": 64,
            "exception_class": None,
        },
        {
            "code": "running_region_repetition_ambiguous",
            "source_ref": "page:1",
            "count": 2,
            "cap": 64,
            "exception_class": None,
        },
    ]


def test_terminal_replay_succeeds_and_wrong_source_rolls_back_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, ir_document, source = _catastrophe_inputs()
    authority = _authority(public, ir_document, source)
    projected, projected_ir = running_regions.project_running_regions(
        public,
        ir_document,
        authority,
    )
    stripped_public, stripped_ir = running_regions.strip_running_regions(
        projected,
        projected_ir,
    )
    stripped_public_bytes = strict_json_bytes(stripped_public)
    stripped_ir_bytes = strict_json_bytes(stripped_ir.model_dump(mode="json"))
    extraction_calls: list[bytes] = []
    original_extract = running_regions._extract_running_region_source_projection

    def audited_extract(
        source_pdf_bytes: bytes,
        configured_predecessor: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        extraction_calls.append(source_pdf_bytes)
        return original_extract(source_pdf_bytes, configured_predecessor)

    monkeypatch.setattr(
        running_regions,
        "_extract_running_region_source_projection",
        audited_extract,
    )
    replayed, replayed_ir = running_regions.replay_running_regions(
        stripped_public,
        stripped_ir,
        source,
        prior_summary=projected["processing"]["running_regions"],
    )
    assert extraction_calls == [source, source]
    assert strict_json_bytes(stripped_public) == stripped_public_bytes
    assert strict_json_bytes(stripped_ir.model_dump(mode="json")) == (stripped_ir_bytes)
    assert strict_json_bytes(_without_running_timing(replayed)) == (
        strict_json_bytes(_without_running_timing(projected))
    )
    assert replayed_ir.model_dump(mode="json") == projected_ir.model_dump(mode="json")
    prior_summary = projected["processing"]["running_regions"]
    replayed_summary = replayed["processing"]["running_regions"]
    assert replayed_summary["extraction_ms"] == prior_summary["extraction_ms"]
    assert replayed_summary["projection_ms"] >= prior_summary["projection_ms"]
    assert replayed_summary["total_ms"] == round(
        replayed_summary["extraction_ms"] + replayed_summary["projection_ms"],
        3,
    )

    failed, failed_ir = running_regions.replay_running_regions(
        stripped_public,
        stripped_ir,
        source + b"wrong-source",
        prior_summary=projected["processing"]["running_regions"],
    )
    assert extraction_calls == [source, source]
    failed_summary = failed["processing"]["running_regions"]
    assert failed_summary["status"] == "failed_closed"
    assert failed_summary["reason"] == "running_region_projection_failed_closed"
    for field in (
        "source_page_count",
        "identity_count",
        "detected_label_count",
        "embedded_label_count",
        "legacy_fallback_count",
        "candidate_count",
        "comparison_count",
        "running_region_count",
        "header_count",
        "footer_count",
        "top_navigation_count",
        "bottom_navigation_count",
        "extraction_ms",
        "projection_ms",
        "total_ms",
    ):
        assert failed_summary[field] == 0
    assert failed_summary["concern_count"] == 1
    assert failed["running_region_concerns"] == [
        {"code": "running_region_projection_failed_closed"}
    ]
    assert all("page_identity" not in page for page in failed["pages"])
    assert all(
        item.get("layout_running_region_projected") is not True
        for page in failed["pages"]
        for item in page["items"]
    )
    stable_failed = deepcopy(failed)
    stable_failed.pop("running_region_concerns")
    stable_failed.pop("processing")
    stable_predecessor = deepcopy(stripped_public)
    stable_predecessor.pop("processing", None)
    assert strict_json_bytes(stable_failed) == strict_json_bytes(stable_predecessor)
    assert failed_ir.model_dump(mode="json", exclude_none=True) == (
        stripped_ir.model_dump(mode="json", exclude_none=True)
    )


def _identity_locked_three_page_fixture() -> tuple[
    bytes,
    dict[str, Any],
    DocumentIR,
    dict[str, Any],
    DocumentIR,
    dict[str, Any],
    list[dict[str, Any]],
]:
    from app.services.ir import EvidenceMethod, round_trip_document

    source = b"identity-locked-running-region-source-v1"
    source_sha256 = hashlib.sha256(source).hexdigest()
    public: dict[str, Any] = {
        "schema_version": "1.0",
        "document": {
            "filename": "identity-locked.pdf",
            "mime_type": "application/pdf",
            "sha256": source_sha256,
            "page_count": 3,
        },
        "pages": [],
        "processing": {
            "engine": "test",
            "ocr_engine": "none",
            "ocr_languages": ["eng"],
            "duration_ms": 1.0,
        },
        "warnings": [],
    }
    for page_index, (page_label, footer_value) in enumerate(
        zip(
            ("2", "3", "4"),
            ("Page 2 of 28", "Page 3 of 28", "Page 4 of 28"),
            strict=True,
        ),
        start=1,
    ):
        public["pages"].append(
            {
                "page_index": page_index,
                "page_number": page_index,
                "page_label": page_label,
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": f"p{page_index}-duplicate",
                        "type": "text",
                        "reading_order": 0,
                        "value": "table-owned OCR duplicate",
                        "md": "table-owned OCR duplicate",
                        "bbox": {
                            "x": 10.0,
                            "y": 20.0,
                            "width": 180.0,
                            "height": 10.0,
                            "unit": "pt",
                        },
                        "source": "ocr",
                    },
                    {
                        "id": f"p{page_index}-footer",
                        "type": "footer",
                        "reading_order": 1,
                        "value": footer_value,
                        "md": footer_value,
                        "bbox": {
                            "x": 260.0,
                            "y": 760.0,
                            "width": 90.0,
                            "height": 10.0,
                            "unit": "pt",
                        },
                        "source": "native",
                    },
                ],
                "warnings": [],
            }
        )

    ir_document = build_document_ir(deepcopy(public))
    public["canonical_presentation"] = build_canonical_presentation(
        ir_document
    ).model_dump(mode="json", exclude_none=True)
    ir_pages = {value.page_index: value for value in ir_document.pages}
    for page in public["pages"]:
        page_index = page["page_index"]
        ir_page = ir_pages[page_index]
        identity = PageIdentity.model_validate(
            {
                "schema_version": "1.0",
                "policy_id": running_regions.POLICY_ID,
                "page_id": ir_page.id,
                "physical_page_index": page_index,
                "embedded_label": None,
                "detected_printed_label": None,
                "visible_text": None,
                "display_label": page["page_label"],
                "display_source": "legacy_display_fallback",
                "evidence_bbox": None,
                "evidence_source": {
                    "method": "legacy_display_fallback",
                    "reader": "configured_predecessor",
                    "page_index": page_index,
                    "public_item_id": None,
                    "public_path": [],
                    "element_id": None,
                    "bbox_id": None,
                    "evidence_ids": [],
                    "source_object_ids": [
                        (
                            f"configured-predecessor:{source_sha256}:page:"
                            f"{page_index}:page_label"
                        )
                    ],
                },
                "confidence": {
                    "scope": "unavailable",
                    "score": None,
                    "unavailable_reason": "page_identity_source_unavailable",
                },
                "concern_codes": [],
            }
        )
        page["page_identity"] = identity.model_dump(mode="json")
        ir_page.page_identity = identity

    footer_item = public["pages"][0]["items"][1]
    footer_element = next(
        value
        for value in ir_document.elements
        if value.properties.get("legacy_item", {}).get("id") == "p1-footer"
    )
    footer_bbox = next(
        value for value in ir_document.bboxes if value.id == footer_element.bbox_ids[0]
    )
    footer_block = next(
        value
        for value in public["canonical_presentation"]["pages"][0]["blocks"]
        if value["primary_element_id"] == footer_element.id
    )
    descriptor = RunningRegionDescriptor.model_validate(
        {
            "id": running_regions._stable_id(
                "running-region",
                running_regions.POLICY_ID,
                source_sha256,
                1,
                footer_element.id,
                footer_bbox.id,
                "footer",
            ),
            "page_id": ir_pages[1].id,
            "physical_page_index": 1,
            "role": "footer",
            "canonical_scope": "footer",
            "source_public_item_id": "p1-footer",
            "source_public_path": ["pages", 0, "items", 1],
            "source_element_id": footer_element.id,
            "predecessor_type": "footer",
            "predecessor_item_sha256": running_regions._sha256_json(
                running_regions._compact_public_item_payload(footer_item)
            ),
            "bbox_id": footer_bbox.id,
            "bbox": {
                "x": footer_bbox.x,
                "y": footer_bbox.y,
                "width": footer_bbox.width,
                "height": footer_bbox.height,
                "unit": "pt",
            },
            "evidence_ids": list(footer_element.evidence_ids),
            "source_object_ids": ["synthetic:page:1:footer"],
            "source_method": "trusted_layout_role",
            "repetition_group_id": None,
            "repetition_page_indexes": [],
            "confidence": {
                "scope": "deterministic_rule",
                "score": 1.0,
                "unavailable_reason": None,
            },
            "concern_codes": [],
            "canonical_block_id": footer_block["id"],
        }
    )
    footer_native_evidence = next(
        value for value in ir_document.evidence if value.id == descriptor.evidence_ids[0]
    )
    footer_extra_evidence = footer_native_evidence.model_copy(
        deep=True,
        update={
            "id": "ev-identity-locked-raw-footer",
            "method": EvidenceMethod.DERIVED,
            "value": None,
            "metadata": {
                "raw_ref": "#/texts/0",
                "raw_label": "page_footer",
                "provenance_index": 0,
            },
        },
    )
    footer_element.evidence_ids.append(footer_extra_evidence.id)
    ir_document.evidence.append(footer_extra_evidence)
    running_regions._stage_direct_candidate(
        owner=footer_item,
        descriptor=descriptor,
        ir_document=ir_document,
    )
    public["canonical_presentation"] = running_regions._build_projected_canonical(
        ir_document,
        (),
        public["canonical_presentation"],
    )
    public["processing"]["running_regions"] = {
        "policy_id": running_regions.POLICY_ID,
        "status": "projected",
        "reason": None,
        "source_page_count": 3,
        "identity_count": 3,
        "detected_label_count": 0,
        "embedded_label_count": 0,
        "legacy_fallback_count": 3,
        "candidate_count": 1,
        "comparison_count": 3,
        "running_region_count": 1,
        "header_count": 0,
        "footer_count": 1,
        "top_navigation_count": 0,
        "bottom_navigation_count": 0,
        "concern_count": 0,
        "extraction_ms": 1.0,
        "projection_ms": 2.0,
        "total_ms": 3.0,
    }
    projected_ir = ir_document.validate_graph()
    baseline_identity = running_regions.running_region_replay_identity(public)

    stripped_public, _stripped_ir = running_regions.strip_running_regions(
        public,
        projected_ir,
    )
    terminal_source = deepcopy(stripped_public)
    for page in terminal_source["pages"]:
        page["items"] = [
            value
            for value in page["items"]
            if value["id"] != f"p{page['page_index']}-duplicate"
        ]
    terminal_source.pop("canonical_presentation", None)
    terminal_public, terminal_ir = round_trip_document(terminal_source)
    terminal_positions: dict[str, int] = {}
    for page in terminal_public["pages"]:
        for item_position, item in enumerate(page["items"]):
            terminal_positions[item["id"]] = item_position
            item["reading_order"] = item_position
    for element in terminal_ir.elements:
        legacy = element.properties.get("legacy_item")
        legacy_id = legacy.get("id") if isinstance(legacy, dict) else None
        if legacy_id in terminal_positions:
            element.reading_order = terminal_positions[legacy_id]
            element.properties["source_position"] = terminal_positions[legacy_id]
            element.properties["legacy_item"]["reading_order"] = terminal_positions[
                legacy_id
            ]
    terminal_footer_element = next(
        element
        for element in terminal_ir.elements
        if element.properties.get("legacy_item", {}).get("id") == "p1-footer"
    )
    terminal_extra_evidence = footer_extra_evidence.model_copy(
        deep=True,
        update={"element_id": terminal_footer_element.id},
    )
    terminal_footer_element.evidence_ids.append(terminal_extra_evidence.id)
    terminal_ir.evidence.append(terminal_extra_evidence)
    terminal_public["canonical_presentation"] = build_canonical_presentation(
        terminal_ir
    ).model_dump(mode="json", exclude_none=True)
    selections = [
        {
            "owner_id": f"p{page_index}-duplicate",
            "owner_type": "text",
            "page_index": page_index,
            "terminal_reason": (
                "selected_vector_source_owned_table_duplicate"
            ),
            "rejected_ocr_alternative": {
                "owner_snapshot": deepcopy(
                    public["pages"][page_index - 1]["items"][0]
                )
            },
        }
        for page_index in range(1, 4)
    ]
    return (
        source,
        public,
        projected_ir,
        terminal_public,
        terminal_ir,
        baseline_identity,
        selections,
    )


def test_identity_locked_replay_preserves_three_page_identity_and_region_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _identity_locked_three_page_fixture()
    source, projected, projected_ir, terminal, terminal_ir, identity, selections = (
        fixture
    )
    transition_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        pipeline_service,
        "_validate_selected_vector_ir_transition",
        lambda *values: transition_calls.append(values),
    )
    authorization = {
        page_index: (f"p{page_index}-duplicate",)
        for page_index in range(1, 4)
    }

    replayed, replayed_ir = running_regions.replay_running_regions_identity_locked(
        terminal,
        terminal_ir,
        source,
        baseline_projected_public=projected,
        baseline_projected_ir=projected_ir,
        baseline_identity=identity,
        alignment_authorized_owner_ids_by_page=authorization,
        alignment_selections=selections,
        prior_summary=projected["processing"]["running_regions"],
    )

    assert len(transition_calls) == 1
    assert transition_calls[0][2] is selections
    assert [page["page_identity"] for page in replayed["pages"]] == [
        value["page_identity"] for value in identity["pages"]
    ]
    assert [
        [
            item["id"]
            for item in page["items"]
            if item.get("layout_running_region_projected") is True
        ]
        for page in replayed["pages"]
    ] == [["p1-footer"], [], []]
    assert replayed["pages"][0]["items"][0]["running_region"][
        "source_public_path"
    ] == ["pages", 0, "items", 0]
    expected_predecessor_hash = running_regions._sha256_json(
        running_regions._compact_public_item_payload(
            terminal["pages"][0]["items"][0]
        )
    )
    relocated_descriptor = replayed["pages"][0]["items"][0][
        "running_region"
    ]
    assert relocated_descriptor["predecessor_item_sha256"] == (
        expected_predecessor_hash
    )
    assert relocated_descriptor["predecessor_item_sha256"] != (
        identity["regions"][0]["descriptor"]["predecessor_item_sha256"]
    )
    assert [
        replayed["pages"][offset]["items"][0]["value"] for offset in (1, 2)
    ] == ["Page 3 of 28", "Page 4 of 28"]
    assert all(
        not set(page["items"][0]).intersection(
            {
                "layout_running_region_projected",
                "running_region_policy",
                "running_region",
            }
        )
        for page in replayed["pages"][1:]
    )
    assert (
        running_regions.running_region_replay_identity(
            replayed,
            baseline_identity=identity,
            alignment_authorized_owner_ids_by_page=authorization,
        )
        == identity
    )
    assert next(
        value for value in replayed_ir.elements if value.running_region is not None
    ).running_region == RunningRegionDescriptor.model_validate(
        relocated_descriptor
    )
    assert ParseResult.model_validate(replayed).pages[0].items[0].running_region == (
        RunningRegionDescriptor.model_validate(relocated_descriptor)
    )
    with pytest.raises(
        running_regions.RunningRegionError,
        match="authorization",
    ):
        running_regions.running_region_replay_identity(
            replayed,
            baseline_identity=identity,
        )


@pytest.mark.parametrize("tamper", ("descriptor_hash", "public_owner"))
def test_identity_locked_relocated_hash_parse_custody_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    source, projected, projected_ir, terminal, terminal_ir, identity, selections = (
        _identity_locked_three_page_fixture()
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_selected_vector_ir_transition",
        lambda *_values: None,
    )
    authorization = {
        page_index: (f"p{page_index}-duplicate",)
        for page_index in range(1, 4)
    }
    replayed, _replayed_ir = running_regions.replay_running_regions_identity_locked(
        terminal,
        terminal_ir,
        source,
        baseline_projected_public=projected,
        baseline_projected_ir=projected_ir,
        baseline_identity=identity,
        alignment_authorized_owner_ids_by_page=authorization,
        alignment_selections=selections,
        prior_summary=projected["processing"]["running_regions"],
    )
    if tamper == "descriptor_hash":
        replayed["pages"][0]["items"][0]["running_region"][
            "predecessor_item_sha256"
        ] = "0" * 64
    else:
        replayed["pages"][0]["items"][0]["md"] = "tampered footer"

    with pytest.raises(ValidationError, match="direct running-region custody differs"):
        ParseResult.model_validate(replayed)


@pytest.mark.parametrize(
    "tamper",
    (
        "wrong_page",
        "unlisted_deletion",
        "extra_region",
        "identity",
        "evidence",
        "group",
        "footer",
        "surviving_authorization",
        "survivor_payload",
        "canonical",
        "extracted",
        "snapshot_extra_sidecar",
        "snapshot_missing",
        "snapshot_changed",
        "baseline_reading_order",
        "current_reading_order",
        "owner_element_reading_order",
        "owner_source_position",
        "owner_legacy_reading_order",
        "owner_evidence_reordered",
        "owner_extra_evidence_mutated",
        "owner_extra_evidence_added",
    ),
)
def test_identity_locked_replay_rejects_semantic_or_custody_drift(
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    source, projected, projected_ir, terminal, terminal_ir, identity, selections = (
        _identity_locked_three_page_fixture()
    )
    authorization: dict[int, tuple[str, ...]] = {
        page_index: (f"p{page_index}-duplicate",)
        for page_index in range(1, 4)
    }
    monkeypatch.setattr(
        pipeline_service,
        "_validate_selected_vector_ir_transition",
        lambda *_values: None,
    )

    if tamper == "wrong_page":
        authorization = {
            1: ("p2-duplicate",),
            2: ("p1-duplicate",),
            3: ("p3-duplicate",),
        }
    elif tamper == "unlisted_deletion":
        authorization.pop(2)
        selections = [value for value in selections if value["page_index"] != 2]
    elif tamper == "extra_region":
        terminal["pages"][1]["items"][0]["running_region"] = deepcopy(
            projected["pages"][0]["items"][1]["running_region"]
        )
    elif tamper == "identity":
        projected["pages"][1]["page_identity"]["display_label"] = "tampered"
    elif tamper == "evidence":
        evidence_id = identity["regions"][0]["descriptor"]["evidence_ids"][0]
        next(
            value for value in terminal_ir.evidence if value.id == evidence_id
        ).value = "tampered evidence"
    elif tamper == "group":
        projected["pages"][0]["items"][1]["running_region"].update(
            {
                "source_method": "cross_page_repetition",
                "repetition_group_id": "tampered-group",
                "repetition_page_indexes": [1, 2],
            }
        )
    elif tamper == "footer":
        terminal["pages"][0]["items"][0].update(
            {"value": "tampered footer", "md": "tampered footer"}
        )
    elif tamper == "surviving_authorization":
        authorization[1] = ("p1-duplicate", "p1-footer")
        selections.append(
            {
                "owner_id": "p1-footer",
                "owner_type": "footer",
                "page_index": 1,
                "terminal_reason": (
                    "selected_vector_source_owned_table_duplicate"
                ),
                "rejected_ocr_alternative": {
                    "owner_snapshot": deepcopy(
                        projected["pages"][0]["items"][0]
                    )
                },
            }
        )
    elif tamper == "survivor_payload":
        terminal["pages"][1]["items"][0]["value"] = "tampered survivor"
    elif tamper == "canonical":
        terminal["canonical_presentation"]["pages"][0]["blocks"][0][
            "text"
        ] = "tampered canonical"
    elif tamper == "extracted":
        extracted_payload = deepcopy(identity["regions"][0]["descriptor"])
        extracted_payload["source_method"] = "extracted_source_contribution"
        extracted = RunningRegionDescriptor.model_validate(extracted_payload)
        projected["pages"][0]["items"][1]["running_region"] = (
            extracted.model_dump(mode="json")
        )
        identity["regions"][0]["descriptor"] = extracted.model_dump(mode="json")
        next(
            value
            for value in projected_ir.elements
            if value.id == extracted.source_element_id
        ).running_region = extracted
    elif tamper == "snapshot_extra_sidecar":
        projected["pages"][0]["items"][0]["semantic_sidecar_probe"] = True
    elif tamper == "snapshot_missing":
        selections[0].pop("rejected_ocr_alternative")
    elif tamper == "snapshot_changed":
        selections[0]["rejected_ocr_alternative"]["owner_snapshot"]["md"] = (
            "changed snapshot"
        )
    elif tamper == "baseline_reading_order":
        projected["pages"][1]["items"][1]["reading_order"] = 0
    elif tamper == "current_reading_order":
        terminal["pages"][1]["items"][0]["reading_order"] = 1
    elif tamper in {
        "owner_element_reading_order",
        "owner_source_position",
        "owner_legacy_reading_order",
    }:
        owner_element = next(
            element
            for element in terminal_ir.elements
            if element.properties.get("legacy_item", {}).get("id") == "p1-footer"
        )
        if tamper == "owner_element_reading_order":
            owner_element.reading_order = 1
        elif tamper == "owner_source_position":
            owner_element.properties["source_position"] = 1
        else:
            owner_element.properties["legacy_item"]["reading_order"] = 1
    elif tamper in {
        "owner_evidence_reordered",
        "owner_extra_evidence_mutated",
        "owner_extra_evidence_added",
    }:
        owner_element = next(
            element
            for element in terminal_ir.elements
            if element.properties.get("legacy_item", {}).get("id") == "p1-footer"
        )
        if tamper == "owner_evidence_reordered":
            owner_element.evidence_ids.reverse()
        elif tamper == "owner_extra_evidence_mutated":
            extra_evidence = next(
                value
                for value in terminal_ir.evidence
                if value.id == "ev-identity-locked-raw-footer"
            )
            extra_evidence.metadata["provenance_index"] = 1
        else:
            extra_evidence = next(
                value
                for value in terminal_ir.evidence
                if value.id == "ev-identity-locked-raw-footer"
            ).model_copy(
                deep=True,
                update={"id": "ev-identity-locked-extra-probe"},
            )
            terminal_ir.evidence.append(extra_evidence)
            owner_element.evidence_ids.append(extra_evidence.id)

    terminal_bytes = strict_json_bytes(terminal)
    terminal_ir_bytes = strict_json_bytes(terminal_ir.model_dump(mode="json"))
    projected_bytes = strict_json_bytes(projected)
    projected_ir_bytes = strict_json_bytes(projected_ir.model_dump(mode="json"))

    with pytest.raises((running_regions.RunningRegionError, ValueError)):
        running_regions.replay_running_regions_identity_locked(
            terminal,
            terminal_ir,
            source,
            baseline_projected_public=projected,
            baseline_projected_ir=projected_ir,
            baseline_identity=identity,
            alignment_authorized_owner_ids_by_page=authorization,
            alignment_selections=selections,
            prior_summary=projected["processing"]["running_regions"],
        )
    assert strict_json_bytes(terminal) == terminal_bytes
    assert strict_json_bytes(terminal_ir.model_dump(mode="json")) == terminal_ir_bytes
    assert strict_json_bytes(projected) == projected_bytes
    assert strict_json_bytes(projected_ir.model_dump(mode="json")) == (
        projected_ir_bytes
    )


@pytest.mark.parametrize("boundary", ("selection_cap", "deadline"))
def test_identity_locked_replay_fails_closed_at_resource_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    source, projected, projected_ir, terminal, terminal_ir, identity, selections = (
        _identity_locked_three_page_fixture()
    )
    authorization = {
        page_index: (f"p{page_index}-duplicate",)
        for page_index in range(1, 4)
    }
    monkeypatch.setattr(
        pipeline_service,
        "_validate_selected_vector_ir_transition",
        lambda *_values: None,
    )
    if boundary == "selection_cap":
        monkeypatch.setattr(running_regions, "MAX_RUNNING_REGIONS_PER_DOCUMENT", 2)
    else:
        calls = 0

        def refuse_deadline(*_args: Any, **_kwargs: Any) -> float:
            nonlocal calls
            calls += 1
            raise running_regions.RunningRegionResourceLimitError(
                "test deadline",
                resource_name="projection_document_seconds",
            )

        monkeypatch.setattr(
            running_regions,
            "validate_running_region_deadline",
            refuse_deadline,
        )
    terminal_bytes = strict_json_bytes(terminal)
    terminal_ir_bytes = strict_json_bytes(terminal_ir.model_dump(mode="json"))

    with pytest.raises(running_regions.RunningRegionResourceLimitError):
        running_regions.replay_running_regions_identity_locked(
            terminal,
            terminal_ir,
            source,
            baseline_projected_public=projected,
            baseline_projected_ir=projected_ir,
            baseline_identity=identity,
            alignment_authorized_owner_ids_by_page=authorization,
            alignment_selections=selections,
            prior_summary=projected["processing"]["running_regions"],
        )
    if boundary == "deadline":
        assert calls == 1
    assert strict_json_bytes(terminal) == terminal_bytes
    assert strict_json_bytes(terminal_ir.model_dump(mode="json")) == terminal_ir_bytes


class _PipelineIr:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = deepcopy(dict(payload))

    def model_dump(
        self, *, mode: str = "json", exclude_none: bool = False
    ) -> dict[str, Any]:
        del mode, exclude_none
        return deepcopy(self.payload)


class _CanonicalDump:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = deepcopy(dict(payload))

    def model_dump(
        self, *, mode: str = "json", exclude_none: bool = False
    ) -> dict[str, Any]:
        del mode, exclude_none
        return deepcopy(self.payload)


def _pipeline_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "pipeline.pdf",
            "mime_type": "application/pdf",
            "sha256": "a" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": "item-1",
                        "type": "text",
                        "reading_order": 0,
                        "value": "configured predecessor",
                        "md": "configured predecessor",
                    }
                ],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "test",
            "ocr_engine": "none",
            "ocr_languages": ["eng"],
            "duration_ms": 1.0,
        },
        "warnings": [],
    }


def _pipeline_loaded_image() -> LoadedDocument:
    page = SourcePage(
        page_index=1,
        pixel_width=20,
        pixel_height=20,
        png_bytes=b"png",
        original_orientation=None,
        orientation_applied=False,
    )
    return LoadedDocument(
        kind=InputKind.IMAGE,
        original_bytes=b"exact-image-source",
        processing_bytes=b"exact-image-source",
        original_filename="shape.png",
        processing_filename="shape.png",
        mime_type="image/png",
        source_format="PNG",
        pages=(page,),
    )


def _patch_minimal_loaded_image_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_service.shutil, "which", lambda _value: "/ocr")
    monkeypatch.setattr(
        pipeline_service,
        "_convert_with_docling",
        lambda *_args, **_kwargs: ({"body": {"children": []}}, []),
    )
    monkeypatch.setattr(
        pipeline_service,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: []},
    )
    monkeypatch.setattr(
        pipeline_service,
        "extract_vector_tables",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        pipeline_service,
        "_analyze_shared_pages",
        lambda _context: None,
    )


def _canonical_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "source_ir_version": "1.0",
        "policy_id": "canonical-presentation-v1",
        "pages": [],
        "full": {"block_ids": [], "markdown": "", "text": ""},
        "body": {"block_ids": [], "markdown": "", "text": ""},
        "header": {"block_ids": [], "markdown": "", "text": ""},
        "footer": {"block_ids": [], "markdown": "", "text": ""},
    }


def _running_summary(
    *,
    extraction_ms: float = 1.25,
    projection_ms: float = 2.5,
) -> dict[str, Any]:
    return {
        "policy_id": running_regions.POLICY_ID,
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
        "extraction_ms": extraction_ms,
        "projection_ms": projection_ms,
        "total_ms": round(extraction_ms + projection_ms, 3),
    }


def _add_fake_running_projection(payload: dict[str, Any]) -> None:
    payload["processing"]["running_regions"] = _running_summary()
    page = payload["pages"][0]
    page["page_identity"] = {
        "schema_version": "1.0",
        "policy_id": running_regions.POLICY_ID,
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
            "source_object_ids": ["configured-predecessor:page:1"],
        },
        "confidence": {
            "scope": "unavailable",
            "score": None,
            "unavailable_reason": "page_identity_source_unavailable",
        },
        "concern_codes": [],
    }
    item = page["items"][0]
    item["type"] = "footer"
    item.update(
        {
            "layout_running_region_projected": True,
            "running_region_policy": running_regions.POLICY_ID,
            "running_region": {
                "id": "running-region-1",
                "page_id": "page-1",
                "physical_page_index": 1,
                "role": "footer",
                "canonical_scope": "footer",
                "source_public_item_id": "item-1",
                "source_public_path": ["pages", 0, "items", 0],
                "source_element_id": "element-1",
                "predecessor_type": "text",
                "predecessor_item_sha256": "b" * 64,
                "bbox_id": "bbox-1",
                "bbox": {
                    "x": 10.0,
                    "y": 760.0,
                    "width": 100.0,
                    "height": 12.0,
                    "unit": "pt",
                },
                "evidence_ids": ["evidence-1"],
                "source_object_ids": ["source-object-1"],
                "source_method": "trusted_layout_role",
                "repetition_group_id": None,
                "repetition_page_indexes": [],
                "confidence": {
                    "scope": "deterministic_rule",
                    "score": 1.0,
                    "unavailable_reason": None,
                },
                "concern_codes": [],
                "canonical_block_id": "canonical-block-1",
            },
        }
    )


def test_terminal_replay_identity_is_exact_except_authorized_owner_hash() -> None:
    payload = _pipeline_payload()
    _add_fake_running_projection(payload)
    baseline = running_regions.running_region_replay_identity(payload)

    changed_hash = deepcopy(payload)
    changed_hash["pages"][0]["items"][0]["running_region"][
        "predecessor_item_sha256"
    ] = "c" * 64
    assert (
        running_regions.running_region_replay_identity(
            changed_hash,
            baseline_identity=baseline,
            alignment_authorized_owner_ids=("item-1",),
        )
        == baseline
    )
    assert running_regions.running_region_replay_identity(changed_hash) != baseline

    shifted_predecessor = deepcopy(payload)
    shifted_predecessor["pages"][0]["items"].insert(
        0,
        {
            "id": "source-rejected-body-1",
            "type": "text",
            "reading_order": 0,
            "value": "rejected OCR alternative",
            "md": "rejected OCR alternative",
        },
    )
    shifted_predecessor["pages"][0]["items"][1]["running_region"][
        "source_public_path"
    ] = ["pages", 0, "items", 1]
    shifted_predecessor["processing"]["running_regions"][
        "comparison_count"
    ] = 5
    shifted_baseline = running_regions.running_region_replay_identity(
        shifted_predecessor
    )

    shifted_replay = deepcopy(shifted_predecessor)
    shifted_replay["pages"][0]["items"].pop(0)
    shifted_replay["pages"][0]["items"][0]["running_region"][
        "source_public_path"
    ] = ["pages", 0, "items", 0]
    shifted_replay["pages"][0]["items"][0]["running_region"][
        "predecessor_item_sha256"
    ] = "c" * 64
    shifted_replay["processing"]["running_regions"][
        "comparison_count"
    ] = 4

    with pytest.raises(
        running_regions.RunningRegionError,
        match="authorization",
    ):
        running_regions.running_region_replay_identity(
            shifted_replay,
            baseline_identity=shifted_baseline,
        )
    assert (
        running_regions.running_region_replay_identity(
            shifted_replay,
            baseline_identity=shifted_baseline,
            alignment_authorized_owner_ids=("source-rejected-body-1",),
        )
        == shifted_baseline
    )

    shifted_descriptor_drift = deepcopy(shifted_replay)
    shifted_descriptor_drift["pages"][0]["items"][0]["running_region"][
        "evidence_ids"
    ] = ["different-evidence"]
    assert (
        running_regions.running_region_replay_identity(
            shifted_descriptor_drift,
            baseline_identity=shifted_baseline,
            alignment_authorized_owner_ids=("source-rejected-body-1",),
        )
        != shifted_baseline
    )

    changed_descriptor = deepcopy(payload)
    changed_descriptor["pages"][0]["items"][0]["running_region"]["evidence_ids"] = [
        "different-evidence"
    ]
    assert (
        running_regions.running_region_replay_identity(changed_descriptor) != baseline
    )

    fewer = deepcopy(payload)
    for key in (
        "layout_running_region_projected",
        "running_region_policy",
        "running_region",
    ):
        fewer["pages"][0]["items"][0].pop(key)
    with pytest.raises(
        running_regions.RunningRegionError,
        match="replay coverage",
    ):
        running_regions.running_region_replay_identity(fewer)

    nonprojected = deepcopy(payload)
    nonprojected["processing"]["running_regions"]["status"] = "failed_closed"
    nonprojected["processing"]["running_regions"]["reason"] = (
        "running_region_projection_failed_closed"
    )
    for field in (
        "source_page_count",
        "identity_count",
        "detected_label_count",
        "embedded_label_count",
        "legacy_fallback_count",
        "candidate_count",
        "comparison_count",
        "running_region_count",
        "header_count",
        "footer_count",
        "top_navigation_count",
        "bottom_navigation_count",
        "extraction_ms",
        "projection_ms",
        "total_ms",
    ):
        nonprojected["processing"]["running_regions"][field] = 0
    nonprojected["processing"]["running_regions"]["concern_count"] = 1
    with pytest.raises(
        running_regions.RunningRegionError,
        match="not projected",
    ):
        running_regions.running_region_replay_identity(nonprojected)


def test_terminal_replay_identity_scopes_removed_owners_to_their_page() -> None:
    payload = _pipeline_payload()
    _add_fake_running_projection(payload)
    second = deepcopy(payload["pages"][0])
    second["page_index"] = 2
    second["page_number"] = 2
    second["page_label"] = "2"
    second["page_identity"].update(
        {
            "page_id": "page-2",
            "physical_page_index": 2,
            "display_label": "2",
        }
    )
    second["page_identity"]["evidence_source"].update(
        {
            "page_index": 2,
            "source_object_ids": ["configured-predecessor:page:2"],
        }
    )
    second_item = second["items"][0]
    second_item["id"] = "item-2"
    second_descriptor = second_item["running_region"]
    second_descriptor.update(
        {
            "id": "running-region-2",
            "page_id": "page-2",
            "physical_page_index": 2,
            "source_public_item_id": "item-2",
            "source_public_path": ["pages", 1, "items", 0],
            "source_element_id": "element-2",
            "bbox_id": "bbox-2",
            "evidence_ids": ["evidence-2"],
            "source_object_ids": ["source-object-2"],
            "canonical_block_id": "canonical-block-2",
        }
    )
    payload["pages"].append(second)
    payload["document"]["page_count"] = 2
    payload["processing"]["running_regions"].update(
        {
            "source_page_count": 2,
            "identity_count": 2,
            "legacy_fallback_count": 2,
            "candidate_count": 2,
            "running_region_count": 2,
            "footer_count": 2,
        }
    )
    for page_offset, page in enumerate(payload["pages"]):
        page["items"].insert(
            0,
            {
                "id": f"removed-{page_offset + 1}",
                "type": "text",
                "reading_order": 0,
                "value": "source-proven duplicate",
                "md": "source-proven duplicate",
            },
        )
        page["items"][1]["running_region"]["source_public_path"] = [
            "pages",
            page_offset,
            "items",
            1,
        ]
    baseline = running_regions.running_region_replay_identity(payload)

    replayed = deepcopy(payload)
    for page_offset, page in enumerate(replayed["pages"]):
        page["items"].pop(0)
        descriptor = page["items"][0]["running_region"]
        descriptor["source_public_path"] = ["pages", page_offset, "items", 0]
        descriptor["predecessor_item_sha256"] = "c" * 64

    assert (
        running_regions.running_region_replay_identity(
            replayed,
            baseline_identity=baseline,
            alignment_authorized_owner_ids_by_page={
                1: ("removed-1",),
                2: ("removed-2",),
            },
        )
        == baseline
    )
    with pytest.raises(
        running_regions.RunningRegionError,
        match="authorization",
    ):
        running_regions.running_region_replay_identity(
            replayed,
            baseline_identity=baseline,
            alignment_authorized_owner_ids=("removed-1", "removed-2"),
        )


def _running_pipeline_settings() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_relationship_order_enabled=True,
        layout_running_regions_enabled=True,
    )


def _terminal_pipeline_settings() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        text_integrity_font_audit_enabled=True,
        text_integrity_font_recovery_enabled=True,
        text_integrity_selective_span_ocr_enabled=True,
        text_reconciliation_enabled=True,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        text_integrity_source_alignment_enabled=True,
        layout_relationship_order_enabled=True,
        layout_running_regions_enabled=True,
    )


def _patch_pipeline_round_trip_and_canonical(
    monkeypatch: pytest.MonkeyPatch,
    *,
    projected: dict[str, Any],
    ir_document: _PipelineIr,
) -> None:
    from app.services import ir as ir_service
    from app.services import presentation as presentation_service

    monkeypatch.setattr(
        ir_service,
        "round_trip_document",
        lambda _payload, **_kwargs: (projected, ir_document),
    )
    monkeypatch.setattr(
        presentation_service,
        "build_canonical_presentation",
        lambda _ir: _CanonicalDump(_canonical_payload()),
    )


def test_parse_loaded_flag_off_forwards_zero_us08_only_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_minimal_loaded_image_pipeline(monkeypatch)
    calls: list[str] = []

    def strict_compatibility(
        payload: dict[str, Any],
        _settings: Settings,
        *,
        raw_graph: Mapping[str, Any] | None,
        native_texts: Any,
        font_audit: Mapping[str, Any] | None,
        font_recovery: Mapping[str, Any] | None,
        selective_span_ocr: Mapping[str, Any] | None,
        text_run_evidence: Any,
        form_evidence: Any,
        form_extraction_ms: float,
        outline_evidence: Any,
        outline_extraction_ms: float,
    ) -> dict[str, Any]:
        del (
            raw_graph,
            native_texts,
            font_audit,
            font_recovery,
            selective_span_ocr,
            text_run_evidence,
            form_evidence,
            form_extraction_ms,
            outline_evidence,
            outline_extraction_ms,
        )
        calls.append("compatibility")
        return payload

    def strict_terminal(
        payload: dict[str, Any],
        _settings: Settings,
        *,
        source_text_evidence: Any,
        source_sha256: str,
        input_kind: InputKind,
        raw_graph: Mapping[str, Any] | None,
        native_texts: Any,
        text_run_evidence: Any,
        form_evidence: Any,
        outline_evidence: Any,
    ) -> dict[str, Any]:
        del (
            source_text_evidence,
            source_sha256,
            raw_graph,
            native_texts,
            text_run_evidence,
            form_evidence,
            outline_evidence,
        )
        assert input_kind is InputKind.IMAGE
        calls.append("terminal")
        return payload

    monkeypatch.setattr(
        pipeline_service,
        "_apply_shared_ir_compatibility_projection",
        strict_compatibility,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_apply_terminal_source_text_alignment",
        strict_terminal,
    )

    result = pipeline_service._parse_loaded_document(
        _pipeline_loaded_image(),
        Settings(layout_running_regions_enabled=False),
    )

    assert result.document.filename == "shape.png"
    assert calls == ["compatibility", "terminal"]


def test_pipeline_flag_off_does_not_import_or_invoke_us08_and_returns_exact_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _pipeline_payload()
    configured_predecessor = deepcopy(payload)
    ir_document = _PipelineIr({"id": "flag-off-ir"})
    from app.services import ir as ir_service

    monkeypatch.setattr(
        ir_service,
        "round_trip_document",
        lambda candidate, **_kwargs: (candidate, ir_document),
    )
    for name in (
        "prepare_source_projection_authority",
        "project_running_regions",
        "extract_running_region_source_projection",
    ):
        monkeypatch.setattr(
            running_regions,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(
                f"flag-off pipeline invoked {_name}"
            ),
        )

    imported: list[str] = []
    original_import = builtins.__import__

    def audited_import(
        name: str,
        globals: Mapping[str, Any] | None = None,
        locals: Mapping[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "app.services.running_regions":
            imported.append(name)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", audited_import)
    actual = pipeline_service._apply_shared_ir_compatibility_projection(
        payload,
        Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
        ),
        source_pdf_bytes=b"must-not-be-observed",
        input_kind=InputKind.PDF,
    )

    assert actual is payload
    assert strict_json_bytes(actual) == strict_json_bytes(configured_predecessor)
    assert imported == []


def test_pipeline_flag_on_pdf_passes_exact_bytes_and_predecessor_through_factory_and_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _pipeline_payload()
    projected = deepcopy(payload)
    projected["predecessor_stage"] = "round_trip"
    ir_document = _PipelineIr({"id": "pdf-ir", "pages": []})
    _patch_pipeline_round_trip_and_canonical(
        monkeypatch,
        projected=projected,
        ir_document=ir_document,
    )
    source_pdf_bytes = b"%PDF-1.7\nexact-pipeline-bytes\n%%EOF"
    authority = object()
    calls: list[str] = []
    configured_bytes: bytes | None = None

    def factory(configured_predecessor: Mapping[str, Any], source: bytes) -> object:
        nonlocal configured_bytes
        calls.append("factory")
        assert source is source_pdf_bytes
        assert configured_predecessor["public"] is projected
        assert configured_predecessor["ir"] == ir_document.model_dump(
            mode="json", exclude_none=True
        )
        configured_bytes = strict_json_bytes(configured_predecessor["public"])
        return authority

    committed = {"committed": True}

    def project(
        public: dict[str, Any], internal_ir: Any, supplied_authority: object
    ) -> tuple[dict[str, Any], Any]:
        calls.append("project")
        assert public is projected
        assert internal_ir is ir_document
        assert supplied_authority is authority
        assert strict_json_bytes(public) == configured_bytes
        return committed, internal_ir

    monkeypatch.setattr(running_regions, "prepare_source_projection_authority", factory)
    monkeypatch.setattr(running_regions, "project_running_regions", project)

    actual = pipeline_service._apply_shared_ir_compatibility_projection(
        payload,
        _running_pipeline_settings(),
        source_pdf_bytes=source_pdf_bytes,
        input_kind=InputKind.PDF,
    )

    assert actual is committed
    assert calls == ["factory", "project"]


def test_pipeline_flag_on_image_emits_strict_not_applicable_without_pdf_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _pipeline_payload()
    projected = deepcopy(payload)
    ir_document = _PipelineIr({"id": "image-ir", "pages": []})
    _patch_pipeline_round_trip_and_canonical(
        monkeypatch,
        projected=projected,
        ir_document=ir_document,
    )
    for name in (
        "prepare_source_projection_authority",
        "project_running_regions",
    ):
        monkeypatch.setattr(
            running_regions,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(
                f"image pipeline invoked {_name}"
            ),
        )

    actual = pipeline_service._apply_shared_ir_compatibility_projection(
        payload,
        _running_pipeline_settings(),
        source_pdf_bytes=b"raster-source",
        input_kind=InputKind.IMAGE,
    )

    assert actual["processing"]["running_regions"] == {
        "policy_id": running_regions.POLICY_ID,
        "status": "not_applicable",
        "reason": "running_region_input_not_applicable",
        "source_page_count": 0,
        "identity_count": 0,
        "detected_label_count": 0,
        "embedded_label_count": 0,
        "legacy_fallback_count": 0,
        "candidate_count": 0,
        "comparison_count": 0,
        "running_region_count": 0,
        "header_count": 0,
        "footer_count": 0,
        "top_navigation_count": 0,
        "bottom_navigation_count": 0,
        "concern_count": 0,
        "extraction_ms": 0.0,
        "projection_ms": 0.0,
        "total_ms": 0.0,
    }
    assert "running_region_concerns" not in actual


@pytest.mark.parametrize(
    "reason",
    (
        "running_region_source_evidence_unavailable",
        "running_region_source_limit",
    ),
)
def test_pipeline_source_outcomes_are_atomic_code_only_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    payload = _pipeline_payload()
    projected = deepcopy(payload)
    projected["predecessor_stage"] = "round_trip"
    ir_document = _PipelineIr({"id": "source-outcome-ir", "pages": []})
    _patch_pipeline_round_trip_and_canonical(
        monkeypatch,
        projected=projected,
        ir_document=ir_document,
    )

    def refuse_source(
        _configured: Mapping[str, Any],
        _source: bytes,
    ) -> Any:
        raise running_regions.RunningRegionSourceOutcomeError(reason)

    monkeypatch.setattr(
        running_regions,
        "prepare_source_projection_authority",
        refuse_source,
    )
    monkeypatch.setattr(
        running_regions,
        "project_running_regions",
        lambda *_args, **_kwargs: pytest.fail("unavailable source reached projection"),
    )
    predecessor = deepcopy(projected)
    predecessor["canonical_presentation"] = _canonical_payload()

    actual = pipeline_service._apply_shared_ir_compatibility_projection(
        payload,
        _running_pipeline_settings(),
        source_pdf_bytes=b"%PDF-1.7\nsource-outcome\n%%EOF",
        input_kind=InputKind.PDF,
    )

    summary = actual["processing"]["running_regions"]
    assert summary["status"] == "unavailable"
    assert summary["reason"] == reason
    for field in (
        "source_page_count",
        "identity_count",
        "detected_label_count",
        "embedded_label_count",
        "legacy_fallback_count",
        "candidate_count",
        "comparison_count",
        "running_region_count",
        "header_count",
        "footer_count",
        "top_navigation_count",
        "bottom_navigation_count",
        "extraction_ms",
        "projection_ms",
        "total_ms",
    ):
        assert summary[field] == 0
    assert summary["concern_count"] == 1
    assert actual["running_region_concerns"] == [{"code": reason}]
    stable = deepcopy(actual)
    stable["processing"].pop("running_regions")
    stable.pop("running_region_concerns")
    assert strict_json_bytes(stable) == strict_json_bytes(predecessor)


def test_pipeline_projection_exception_returns_atomic_code_only_failed_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _pipeline_payload()
    projected = deepcopy(payload)
    projected["predecessor_stage"] = "round_trip"
    ir_document = _PipelineIr({"id": "failure-ir", "pages": []})
    _patch_pipeline_round_trip_and_canonical(
        monkeypatch,
        projected=projected,
        ir_document=ir_document,
    )
    source_pdf_bytes = b"%PDF-1.7\nprojection-failure\n%%EOF"
    monkeypatch.setattr(
        running_regions,
        "prepare_source_projection_authority",
        lambda _configured, source: (
            object()
            if source is source_pdf_bytes
            else pytest.fail("source bytes changed")
        ),
    )

    def fail_after_mutation(
        candidate: dict[str, Any], _ir: Any, _authority: object
    ) -> tuple[dict[str, Any], Any]:
        candidate["private_source_path"] = "/tmp/do-not-leak.pdf"
        candidate["pages"][0]["items"].append(
            {"source_text": "<script>do not leak</script>"}
        )
        raise RuntimeError("private-source /tmp/do-not-leak.pdf")

    monkeypatch.setattr(running_regions, "project_running_regions", fail_after_mutation)
    predecessor = deepcopy(projected)
    predecessor["canonical_presentation"] = _canonical_payload()

    actual = pipeline_service._apply_shared_ir_compatibility_projection(
        payload,
        _running_pipeline_settings(),
        source_pdf_bytes=source_pdf_bytes,
        input_kind=InputKind.PDF,
    )

    assert actual["processing"]["running_regions"] == {
        "policy_id": running_regions.POLICY_ID,
        "status": "failed_closed",
        "reason": "running_region_projection_failed_closed",
        "source_page_count": 0,
        "identity_count": 0,
        "detected_label_count": 0,
        "embedded_label_count": 0,
        "legacy_fallback_count": 0,
        "candidate_count": 0,
        "comparison_count": 0,
        "running_region_count": 0,
        "header_count": 0,
        "footer_count": 0,
        "top_navigation_count": 0,
        "bottom_navigation_count": 0,
        "concern_count": 1,
        "extraction_ms": 0.0,
        "projection_ms": 0.0,
        "total_ms": 0.0,
    }
    assert actual["running_region_concerns"] == [
        {"code": "running_region_projection_failed_closed"}
    ]
    stable = deepcopy(actual)
    stable["processing"].pop("running_regions")
    stable.pop("running_region_concerns")
    assert strict_json_bytes(stable) == strict_json_bytes(predecessor)
    serialized = json.dumps(actual)
    assert "private-source" not in serialized
    assert "/tmp/do-not-leak.pdf" not in serialized
    assert "<script>" not in serialized


def _install_terminal_pipeline_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: dict[str, Any],
    replay_error: Exception | None = None,
) -> dict[str, Any]:
    from app.services import ir as ir_service
    from app.services import presentation as presentation_service
    from app.services import source_text_alignment as alignment_service

    calls: dict[str, Any] = {
        "strip": [],
        "round_trip": [],
        "replay": [],
    }

    def strip(candidate: dict[str, Any]) -> dict[str, Any]:
        calls["strip_input_is_payload"] = candidate is payload
        calls["strip"].append(deepcopy(candidate))
        clean = deepcopy(candidate)
        clean["processing"].pop("running_regions", None)
        for page in clean["pages"]:
            page.pop("page_identity", None)
            for item in page["items"]:
                item.pop("layout_running_region_projected", None)
                item.pop("running_region_policy", None)
                item.pop("running_region", None)
        return clean

    def align(pages: list[dict[str, Any]], _evidence: Any) -> Any:
        pages[0]["items"][0]["value"] = "terminal aligned"
        pages[0]["items"][0]["md"] = "terminal aligned"
        return SimpleNamespace(
            to_dict=lambda: {
                "status": "projected",
                "selected_count": 1,
                "selections": [
                    {
                        "owner_id": "item-1",
                        "owner_type": "footer",
                    }
                ],
            }
        )

    terminal_ir = _PipelineIr({"id": "terminal-ir", "pages": []})
    terminal_descriptor = deepcopy(
        payload["pages"][0]["items"][0]["running_region"]
    )
    terminal_ir.elements = [
        SimpleNamespace(
            id=terminal_descriptor["source_element_id"],
            evidence_ids=list(terminal_descriptor["evidence_ids"]),
            running_region=SimpleNamespace(
                model_dump=lambda **_kwargs: deepcopy(terminal_descriptor)
            ),
            value="terminal aligned",
        )
    ]
    terminal_ir.evidence = [
        SimpleNamespace(
            id=terminal_descriptor["evidence_ids"][0],
            element_id=terminal_descriptor["source_element_id"],
            bbox_id=terminal_descriptor["bbox_id"],
            value="terminal aligned",
            method=SimpleNamespace(value="native"),
        )
    ]

    def round_trip(
        terminal_source: dict[str, Any], **_kwargs: Any
    ) -> tuple[dict[str, Any], _PipelineIr]:
        calls["round_trip"].append(deepcopy(terminal_source))
        assert "canonical_presentation" not in terminal_source
        assert "running_regions" not in terminal_source["processing"]
        assert terminal_source["pages"][0]["items"][0]["value"] == ("terminal aligned")
        return deepcopy(terminal_source), terminal_ir

    combined_summary = _running_summary(
        extraction_ms=payload["processing"]["running_regions"]["extraction_ms"],
        projection_ms=(
            payload["processing"]["running_regions"]["projection_ms"] + 0.75
        ),
    )

    def replay(
        candidate: dict[str, Any],
        candidate_ir: Any,
        source_pdf_bytes: bytes,
        *,
        prior_summary: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], Any]:
        calls["replay"].append(
            {
                "candidate": deepcopy(candidate),
                "ir": candidate_ir,
                "source": source_pdf_bytes,
                "prior_summary": deepcopy(prior_summary),
            }
        )
        if replay_error is not None:
            raise replay_error
        committed = deepcopy(candidate)
        committed["processing"]["running_regions"] = deepcopy(combined_summary)
        for page_offset, page in enumerate(committed["pages"]):
            source_page = payload["pages"][page_offset]
            page["page_identity"] = deepcopy(source_page["page_identity"])
            source_items = {value["id"]: value for value in source_page["items"]}
            for item in page["items"]:
                source_item = source_items[item["id"]]
                for key in (
                    "layout_running_region_projected",
                    "running_region_policy",
                    "running_region",
                ):
                    if key in source_item:
                        item[key] = deepcopy(source_item[key])
                        item["type"] = source_item["type"]
        return committed, candidate_ir

    monkeypatch.setattr(running_regions, "strip_running_regions", strip)
    monkeypatch.setattr(running_regions, "replay_running_regions", replay)
    monkeypatch.setattr(alignment_service, "align_pages_to_source", align)
    monkeypatch.setattr(ir_service, "round_trip_document", round_trip)
    monkeypatch.setattr(
        presentation_service,
        "build_canonical_presentation",
        lambda _ir: _CanonicalDump(_canonical_payload()),
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_source_alignment_summary",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_terminal_source_alignment",
        lambda *_args, **_kwargs: None,
    )
    calls["combined_summary"] = combined_summary
    return calls


def test_terminal_source_alignment_strips_and_replays_us08_with_prior_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _pipeline_payload()
    _add_fake_running_projection(payload)
    prior_summary = deepcopy(payload["processing"]["running_regions"])
    payload["canonical_presentation"] = _canonical_payload()
    calls = _install_terminal_pipeline_fakes(
        monkeypatch,
        payload=payload,
    )
    source_pdf_bytes = b"%PDF-1.7\nterminal-replay\n%%EOF"

    actual = pipeline_service._apply_terminal_source_text_alignment(
        payload,
        _terminal_pipeline_settings(),
        source_pdf_bytes=source_pdf_bytes,
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
    )

    assert len(calls["strip"]) == 1
    assert calls["strip_input_is_payload"] is True
    assert len(calls["round_trip"]) == 1
    assert len(calls["replay"]) == 1
    replay_call = calls["replay"][0]
    assert replay_call["source"] is source_pdf_bytes
    assert replay_call["prior_summary"] == prior_summary
    assert actual["processing"]["running_regions"] == calls["combined_summary"]
    assert actual["pages"][0]["items"][0]["value"] == "terminal aligned"


def test_mixed_vector_and_generic_alignment_reruns_generic_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ir as ir_service
    from app.services import presentation as presentation_service
    from app.services import source_text_alignment as alignment_service

    payload = _pipeline_payload()
    payload["canonical_presentation"] = _canonical_payload()
    payload["pages"][0]["items"].insert(
        0,
        {
            "id": "vector-owner",
            "type": "text",
            "reading_order": 0,
            "value": "table duplicate",
            "md": "table duplicate",
        },
    )
    payload["pages"][0]["items"][1]["reading_order"] = 1
    calls: list[dict[str, Any]] = []

    def align(
        pages: list[dict[str, Any]],
        _evidence: Any,
        **kwargs: Any,
    ) -> Any:
        calls.append(deepcopy(kwargs))
        if kwargs:
            pages[0]["items"] = [
                item
                for item in pages[0]["items"]
                if item["id"] != "vector-owner"
            ]
            pages[0]["items"][0]["value"] = "discarded mixed pass"
            pages[0]["items"][0]["md"] = "discarded mixed pass"
            selections = [
                {
                    "owner_id": "vector-owner",
                    "owner_type": "text",
                    "page_index": 1,
                    "terminal_reason": (
                        "selected_vector_source_owned_table_duplicate"
                    ),
                },
                {
                    "owner_id": "item-1",
                    "owner_type": "text",
                    "page_index": 1,
                    "terminal_reason": "source_text_selected",
                },
            ]
        else:
            assert any(
                item["id"] == "vector-owner" for item in pages[0]["items"]
            )
            pages[0]["items"][1]["value"] = "generic correction"
            pages[0]["items"][1]["md"] = "generic correction"
            selections = [
                {
                    "owner_id": "item-1",
                    "owner_type": "text",
                    "page_index": 1,
                    "terminal_reason": "source_text_selected",
                }
            ]
        return SimpleNamespace(
            to_dict=lambda: {
                "status": "selected",
                "selected_count": len(selections),
                "selections": selections,
            }
        )

    terminal_ir = _PipelineIr({"id": "terminal-ir", "pages": []})
    monkeypatch.setattr(alignment_service, "align_pages_to_source", align)
    monkeypatch.setattr(
        ir_service,
        "round_trip_document",
        lambda terminal_source, **_kwargs: (
            deepcopy(terminal_source),
            terminal_ir,
        ),
    )
    monkeypatch.setattr(
        presentation_service,
        "build_canonical_presentation",
        lambda _ir: _CanonicalDump(_canonical_payload()),
    )
    monkeypatch.setattr(
        pipeline_service,
        "_bind_selected_vector_terminal_representations",
        lambda *_args, **_kwargs: {1: [{"bound": True}]},
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_source_alignment_summary",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_terminal_source_alignment",
        lambda *_args, **_kwargs: None,
    )
    internal_ir_sink = {"ir": _PipelineIr({"id": "baseline-ir", "pages": []})}

    actual = pipeline_service._apply_terminal_source_text_alignment(
        payload,
        Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            canonical_serialization_enabled=True,
            text_integrity_font_audit_enabled=True,
            text_integrity_font_recovery_enabled=True,
            text_integrity_selective_span_ocr_enabled=True,
            text_reconciliation_enabled=True,
            ocr_numeric_cleanup_v2_enabled=True,
            ocr_spatial_token_preservation_enabled=True,
            layout_relationship_order_enabled=True,
            text_integrity_source_alignment_enabled=True,
        ),
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
        internal_ir_sink=internal_ir_sink,
        selected_vector_representations={1: [{"sealed": True}]},
    )

    assert calls == [
        {"selected_vector_representations": {1: [{"bound": True}]}},
        {},
    ]
    assert [item["id"] for item in actual["pages"][0]["items"]] == [
        "vector-owner",
        "item-1",
    ]
    assert actual["pages"][0]["items"][1]["value"] == "generic correction"
    assert actual["processing"]["source_text_alignment"]["selections"] == [
        {
            "owner_id": "item-1",
            "owner_type": "text",
            "page_index": 1,
            "terminal_reason": "source_text_selected",
        }
    ]


def test_vector_terminal_rebinds_use_prior_bound_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ir as ir_service
    from app.services import presentation as presentation_service
    from app.services import source_text_alignment as alignment_service

    payload = _pipeline_payload()
    payload["canonical_presentation"] = _canonical_payload()
    sealed = {1: [{"sealed": True}]}
    bound = {1: [{"sealed": True, "terminal_binding": {"bound": True}}]}
    binder_arguments: list[dict[int, list[dict[str, Any]]]] = []

    def bind(
        _candidate: Mapping[str, Any],
        _ir: Any,
        representations: Mapping[int, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[int, list[dict[str, Any]]]:
        binder_arguments.append(deepcopy(dict(representations)))
        if len(binder_arguments) == 1:
            assert representations == sealed
        else:
            assert representations == bound
        return deepcopy(bound)

    def align(
        pages: list[dict[str, Any]],
        _evidence: Any,
        **kwargs: Any,
    ) -> Any:
        assert kwargs == {"selected_vector_representations": bound}
        pages[0]["items"] = []
        return SimpleNamespace(
            to_dict=lambda: {
                "status": "selected",
                "selected_count": 1,
                "selections": [
                    {
                        "owner_id": "item-1",
                        "owner_type": "text",
                        "page_index": 1,
                        "terminal_reason": (
                            "selected_vector_source_owned_table_duplicate"
                        ),
                    }
                ],
            }
        )

    baseline_ir = _PipelineIr({"id": "baseline-ir", "pages": []})
    terminal_ir = _PipelineIr({"id": "terminal-ir", "pages": []})
    monkeypatch.setattr(
        ir_service,
        "round_trip_document",
        lambda terminal_source, **_kwargs: (
            deepcopy(terminal_source),
            terminal_ir,
        ),
    )
    monkeypatch.setattr(alignment_service, "align_pages_to_source", align)
    monkeypatch.setattr(
        presentation_service,
        "build_canonical_presentation",
        lambda _ir: _CanonicalDump(_canonical_payload()),
    )
    monkeypatch.setattr(
        pipeline_service,
        "_bind_selected_vector_terminal_representations",
        bind,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_selected_vector_ir_transition",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_source_alignment_summary",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_terminal_source_alignment",
        lambda *_args, **_kwargs: None,
    )

    actual = pipeline_service._apply_terminal_source_text_alignment(
        payload,
        Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            canonical_serialization_enabled=True,
            text_integrity_font_audit_enabled=True,
            text_integrity_font_recovery_enabled=True,
            text_integrity_selective_span_ocr_enabled=True,
            text_reconciliation_enabled=True,
            ocr_numeric_cleanup_v2_enabled=True,
            ocr_spatial_token_preservation_enabled=True,
            layout_relationship_order_enabled=True,
            text_integrity_source_alignment_enabled=True,
        ),
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
        internal_ir_sink={"ir": baseline_ir},
        selected_vector_representations=sealed,
    )

    assert binder_arguments == [sealed, bound, bound]
    assert actual["pages"][0]["items"] == []


def _run_vector_canonical_omission_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[str],
    _PipelineIr,
    dict[str, Any],
]:
    from app.services import canonical_ocr_omission
    from app.services import ir as ir_service
    from app.services import presentation as presentation_service
    from app.services import source_text_alignment as alignment_service

    payload = _pipeline_payload()
    payload["canonical_presentation"] = _canonical_payload()
    payload["pages"][0]["items"] = [
        {
            "id": "vector-owner",
            "type": "text",
            "reading_order": 0,
            "value": "table duplicate",
            "md": "table duplicate",
        },
        {
            "id": "retained-owner",
            "type": "text",
            "reading_order": 1,
            "value": "uncertain OCR",
            "md": "uncertain OCR",
        },
    ]
    predecessor = deepcopy(payload)
    sealed = {1: [{"sealed": True}]}
    bound = {1: [{"sealed": True, "terminal_binding": {"bound": True}}]}
    baseline_ir = _PipelineIr({"id": "baseline-ir", "pages": []})
    terminal_ir = _PipelineIr({"id": "terminal-ir", "pages": []})
    internal_ir_sink = {"ir": baseline_ir}
    events: list[str] = []
    binder_count = 0

    def bind(
        _candidate: Mapping[str, Any],
        _ir: Any,
        representations: Mapping[int, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[int, list[dict[str, Any]]]:
        nonlocal binder_count
        binder_count += 1
        events.append(f"binder_{binder_count}")
        assert representations == (sealed if binder_count == 1 else bound)
        return deepcopy(bound)

    def align(
        pages: list[dict[str, Any]],
        _evidence: Any,
        **kwargs: Any,
    ) -> Any:
        events.append("align")
        assert kwargs == {"selected_vector_representations": bound}
        pages[0]["items"] = [
            item for item in pages[0]["items"] if item["id"] != "vector-owner"
        ]
        pages[0]["items"][0]["reading_order"] = 0
        return SimpleNamespace(
            to_dict=lambda: {
                "status": "selected",
                "considered_count": 2,
                "selected_count": 1,
                "unchanged_count": 1,
                "unresolved_count": 0,
                "selections": [
                    {
                        "owner_id": "vector-owner",
                        "owner_type": "text",
                        "page_index": 1,
                        "terminal_reason": (
                            "selected_vector_source_owned_table_duplicate"
                        ),
                    }
                ],
                "concerns": [],
            }
        )

    def round_trip(
        terminal_source: dict[str, Any], **_kwargs: Any
    ) -> tuple[dict[str, Any], _PipelineIr]:
        events.append("round_trip")
        return deepcopy(terminal_source), terminal_ir

    def terminal_validator(
        _candidate: Mapping[str, Any],
        _summary: Mapping[str, Any],
        **kwargs: Any,
    ) -> None:
        events.append(
            "terminal_omission"
            if "prevalidated_selections" in kwargs
            else "terminal_core"
        )

    def apply(
        candidate: dict[str, Any],
        candidate_ir: Any,
        summary: dict[str, Any],
        _evidence: Any,
        representations: Mapping[int, Any],
        source: bytes,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        events.append("omission_apply")
        assert candidate_ir is terminal_ir
        assert representations == bound
        assert source == b"%PDF-1.7\npipeline-omission\n%%EOF"
        assert [
            item["id"] for item in candidate["pages"][0]["items"]
        ] == ["retained-owner"]
        if mode == "helper_noop":
            return candidate, summary
        if mode == "apply_exception":
            raise RuntimeError("optional apply failure")
        projected = deepcopy(candidate)
        projected_summary = deepcopy(summary)
        retained = projected["pages"][0]["items"][0]
        projected_summary["selections"].append(
            {
                "owner_id": "retained-owner",
                "owner_type": "text",
                "page_index": 1,
                "original_text": "uncertain OCR",
                "selected_text": "",
                "terminal_reason": "source_contradicted_primary_ocr",
                "rejected_ocr_alternative": {
                    "owner_snapshot": deepcopy(retained)
                },
            }
        )
        projected_summary["selected_count"] = 2
        projected_summary["unchanged_count"] = 0
        projected["canonical_presentation"] = {"omitted": True}
        projected["processing"]["source_text_alignment"] = projected_summary
        if mode == "public_mutation":
            retained["value"] = "unauthorized mutation"
        return projected, projected_summary

    def omission_replay(*_args: Any, **_kwargs: Any) -> bool:
        events.append("omission_replay")
        if mode == "validator_exception":
            raise RuntimeError("optional replay failure")
        return mode != "validator_false"

    monkeypatch.setattr(alignment_service, "align_pages_to_source", align)
    monkeypatch.setattr(ir_service, "round_trip_document", round_trip)
    monkeypatch.setattr(
        presentation_service,
        "build_canonical_presentation",
        lambda _ir: _CanonicalDump(_canonical_payload()),
    )
    monkeypatch.setattr(
        pipeline_service,
        "_bind_selected_vector_terminal_representations",
        bind,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_selected_vector_ir_transition",
        lambda *_args, **_kwargs: events.append("transition"),
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_source_alignment_summary",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_terminal_source_alignment",
        terminal_validator,
    )
    monkeypatch.setattr(
        canonical_ocr_omission,
        "apply_source_contradicted_primary_ocr_omissions",
        apply,
    )
    monkeypatch.setattr(
        canonical_ocr_omission,
        "validate_source_contradicted_primary_ocr_omissions",
        omission_replay,
    )

    actual = pipeline_service._apply_terminal_source_text_alignment(
        payload,
        _terminal_pipeline_settings(),
        source_pdf_bytes=b"%PDF-1.7\npipeline-omission\n%%EOF",
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
        internal_ir_sink=internal_ir_sink,
        selected_vector_representations=sealed,
    )
    assert binder_count == 3
    assert internal_ir_sink["ir"] is terminal_ir
    return actual, predecessor, events, terminal_ir, internal_ir_sink


def test_terminal_pipeline_commits_validated_canonical_ocr_omission_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual, predecessor, events, _terminal_ir, _sink = (
        _run_vector_canonical_omission_pipeline(
            monkeypatch,
            mode="success",
        )
    )

    assert events == [
        "binder_1",
        "align",
        "round_trip",
        "binder_2",
        "transition",
        "binder_3",
        "terminal_core",
        "omission_apply",
        "omission_replay",
        "terminal_omission",
    ]
    assert [item["id"] for item in actual["pages"][0]["items"]] == [
        "retained-owner"
    ]
    assert actual["pages"][0]["items"][0]["reading_order"] == 0
    assert actual["canonical_presentation"] == {"omitted": True}
    assert [
        value["terminal_reason"]
        for value in actual["processing"]["source_text_alignment"]["selections"]
    ] == [
        "selected_vector_source_owned_table_duplicate",
        "source_contradicted_primary_ocr",
    ]
    assert [item["id"] for item in predecessor["pages"][0]["items"]] == [
        "vector-owner",
        "retained-owner",
    ]


@pytest.mark.parametrize(
    "mode",
    (
        "helper_noop",
        "apply_exception",
        "validator_false",
        "validator_exception",
        "public_mutation",
    ),
)
def test_terminal_pipeline_optional_omission_failure_keeps_core_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    actual, predecessor, events, _terminal_ir, _sink = (
        _run_vector_canonical_omission_pipeline(
            monkeypatch,
            mode=mode,
        )
    )

    assert [item["id"] for item in actual["pages"][0]["items"]] == [
        "retained-owner"
    ]
    assert actual["pages"][0]["items"][0]["value"] == "uncertain OCR"
    assert actual["canonical_presentation"] == _canonical_payload()
    assert actual["processing"]["source_text_alignment"]["selected_count"] == 1
    assert actual["processing"]["source_text_alignment"]["selections"] == [
        {
            "owner_id": "vector-owner",
            "owner_type": "text",
            "page_index": 1,
            "terminal_reason": (
                "selected_vector_source_owned_table_duplicate"
            ),
        }
    ]
    assert events.index("binder_3") < events.index("terminal_core")
    assert events.index("terminal_core") < events.index("omission_apply")
    assert [item["id"] for item in predecessor["pages"][0]["items"]] == [
        "vector-owner",
        "retained-owner",
    ]


def test_zero_destructive_pipeline_can_commit_canonical_only_omission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import source_text_alignment as alignment_service

    payload = _pipeline_payload()
    payload["canonical_presentation"] = _canonical_payload()
    payload_before = deepcopy(payload)
    sealed = {1: [{"sealed": True}]}
    bound = {1: [{"sealed": True, "terminal_binding": {"bound": True}}]}
    baseline_ir = _PipelineIr({"id": "baseline-ir", "pages": []})
    events: list[str] = []
    bind_count = 0

    def bind(
        _candidate: Mapping[str, Any],
        candidate_ir: Any,
        representations: Mapping[int, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[int, list[dict[str, Any]]]:
        nonlocal bind_count
        bind_count += 1
        events.append(f"binder_{bind_count}")
        assert candidate_ir is baseline_ir
        assert representations == sealed
        return deepcopy(bound)

    zero_summary = {
        "status": "unchanged",
        "considered_count": 1,
        "selected_count": 0,
        "unchanged_count": 1,
        "unresolved_count": 0,
        "selections": [],
        "concerns": [],
    }
    def align(
        _pages: list[dict[str, Any]],
        _evidence: Any,
        **kwargs: Any,
    ) -> Any:
        events.append("align")
        assert kwargs == {"selected_vector_representations": bound}
        return SimpleNamespace(to_dict=lambda: deepcopy(zero_summary))

    monkeypatch.setattr(
        alignment_service,
        "align_pages_to_source",
        align,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_bind_selected_vector_terminal_representations",
        bind,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_source_alignment_summary",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_service,
        "_validate_terminal_source_alignment",
        lambda *_args, **_kwargs: events.append("terminal_core"),
    )

    def omission(
        candidate: dict[str, Any],
        candidate_ir: Any,
        summary: dict[str, Any],
        **kwargs: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        events.append("omission")
        assert candidate_ir is baseline_ir
        assert kwargs["selected_vector_representations"] == bound
        assert kwargs["source_pdf_bytes"] == b"%PDF-1.7\nzero\n%%EOF"
        projected = deepcopy(candidate)
        projected_summary = deepcopy(summary)
        projected_summary["status"] = "selected"
        projected_summary["selected_count"] = 1
        projected_summary["unchanged_count"] = 0
        projected["canonical_presentation"] = {"omitted": True}
        projected["processing"]["source_text_alignment"] = projected_summary
        return projected, projected_summary

    monkeypatch.setattr(
        pipeline_service,
        "_apply_terminal_canonical_ocr_omission",
        omission,
    )

    actual = pipeline_service._apply_terminal_source_text_alignment(
        payload,
        _terminal_pipeline_settings(),
        source_pdf_bytes=b"%PDF-1.7\nzero\n%%EOF",
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
        internal_ir_sink={"ir": baseline_ir},
        selected_vector_representations=sealed,
    )

    assert events == [
        "binder_1",
        "align",
        "binder_2",
        "terminal_core",
        "omission",
    ]
    assert bind_count == 2
    assert actual["pages"] == payload_before["pages"]
    assert actual["canonical_presentation"] == {"omitted": True}
    assert actual["processing"]["source_text_alignment"] == {
        **zero_summary,
        "status": "selected",
        "selected_count": 1,
        "unchanged_count": 0,
    }


def test_terminal_wrong_replay_rolls_back_the_complete_predecessor_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _pipeline_payload()
    _add_fake_running_projection(payload)
    prior_summary = deepcopy(payload["processing"]["running_regions"])
    payload["canonical_presentation"] = _canonical_payload()
    payload_before = deepcopy(payload)
    calls = _install_terminal_pipeline_fakes(
        monkeypatch,
        payload=payload,
        replay_error=RuntimeError(
            "wrong replay /tmp/private-source.pdf <script>secret</script>"
        ),
    )

    actual = pipeline_service._apply_terminal_source_text_alignment(
        payload,
        _terminal_pipeline_settings(),
        source_pdf_bytes=b"%PDF-1.7\nwrong-terminal-replay\n%%EOF",
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
    )

    assert len(calls["strip"]) == 1
    assert len(calls["replay"]) == 1
    assert actual["processing"]["running_regions"] == prior_summary
    source_summary = actual["processing"]["source_text_alignment"]
    assert source_summary["status"] == "unavailable"
    assert source_summary["concerns"] == [
        {
            "status": "unresolved",
            "reason": "source_alignment_failed_closed",
            "error_type": "RuntimeError",
        }
    ]
    stable = deepcopy(actual)
    stable["processing"].pop("source_text_alignment")
    stable["warnings"] = stable["warnings"][:-1]
    assert strict_json_bytes(stable) == strict_json_bytes(payload_before)
    serialized = json.dumps(actual)
    assert "/tmp/private-source.pdf" not in serialized
    assert "<script>" not in serialized
