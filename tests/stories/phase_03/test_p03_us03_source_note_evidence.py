"""Bounded evidence-extraction coverage for P03-US03."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping

import pdfplumber
import pytest

from app.config import Settings
from app.services.layout_source_notes import (
    MAX_PDF_ANNOTATIONS_PER_DOCUMENT,
    MAX_PDF_ANNOTATIONS_PER_PAGE,
    MAX_SOURCE_NOTE_ZONE_HEIGHT,
    MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE,
    SOURCE_NOTE_ANNOTATION_MARKER,
    SOURCE_NOTE_EVIDENCE_LEDGER,
    SOURCE_NOTE_OCR_MARKER,
    SOURCE_NOTE_OWNER_BBOX,
    SOURCE_NOTE_OWNER_REF,
    SOURCE_NOTE_ZONE_CONTENT_TYPE,
    SOURCE_NOTE_ZONE_MARKER,
    _annotation_nodes,
    augment_source_note_evidence,
    plan_source_note_zone_requests,
    safe_http_annotation_target,
)
from app.services.ocr import ImageRegion, OCRLine
from app.services.pipeline import _select_pdf_render_requests


def _prov(
    left: float,
    top: float,
    right: float,
    bottom: float,
    *,
    page_index: int = 1,
) -> list[dict[str, Any]]:
    return [
        {
            "page_no": page_index,
            "bbox": {
                "l": left,
                "t": top,
                "r": right,
                "b": bottom,
                "coord_origin": "TOPLEFT",
            },
            "charspan": [0, 1],
        }
    ]


def _caption(reference: str = "#/texts/caption") -> dict[str, Any]:
    return {
        "self_ref": reference,
        "label": "caption",
        "text": "Figure title",
        "prov": _prov(10, 2, 80, 8),
    }


def _visual(
    index: int = 0,
    *,
    top: float = 10,
    bottom: float = 50,
) -> dict[str, Any]:
    return {
        "self_ref": f"#/pictures/{index}",
        "label": "picture",
        "prov": _prov(10, top, 90, bottom),
        "captions": [{"$ref": "#/texts/caption"}],
        "children": [{"$ref": "#/texts/caption"}],
    }


def _raw_graph(
    *pictures: dict[str, Any],
    texts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "body": {"self_ref": "#/body", "children": []},
        "furniture": {"self_ref": "#/furniture", "children": []},
        "groups": [],
        "texts": [_caption(), *(texts or [])],
        "pictures": list(pictures),
        "tables": [],
        "key_value_items": [],
        "form_items": [],
        "field_regions": [],
        "field_items": [],
    }


def _pages(*, height: float = 200) -> list[dict[str, Any]]:
    return [
        {
            "page_index": 1,
            "page_width": 100.0,
            "page_height": height,
        }
    ]


def _marked_region(
    *,
    text: str = "Data: Aon Catastrophe Insight",
    accepted_confidence: float = 0.96,
    region_y: float = 50.0,
    line_y: float = 56.0,
) -> ImageRegion:
    return ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 10.0, "y": region_y, "w": 80.0, "h": 36.0},
        pixel_width=400,
        pixel_height=180,
        area_ratio=0.1,
        content_type=SOURCE_NOTE_ZONE_CONTENT_TYPE,
        metadata={
            SOURCE_NOTE_ZONE_MARKER: True,
            SOURCE_NOTE_OWNER_REF: "#/pictures/0",
            SOURCE_NOTE_OWNER_BBOX: {
                "x": 10.0,
                "y": 10.0,
                "width": 80.0,
                "height": 40.0,
                "unit": "pt",
            },
        },
        region_role="content_region",
        region_origin="pdf_page_render",
        coordinate_unit="pt",
        lines=[
            OCRLine(
                text=text,
                bbox={"x": 11.0, "y": line_y, "w": 70.0, "h": 6.0},
                confidence=accepted_confidence,
                word_count=4,
            )
        ],
    )


def test_note_zone_starts_at_owner_bottom_and_is_bounded() -> None:
    plan = plan_source_note_zone_requests(
        _pages(),
        _raw_graph(_visual()),
    )

    assert plan.concerns == ()
    assert len(plan.requests) == 1
    request = plan.requests[0]
    assert request.page_index == 1
    assert request.content_type == SOURCE_NOTE_ZONE_CONTENT_TYPE
    assert request.bbox == {
        "x": 10.0,
        "y": 50.0,
        "width": 80.0,
        "height": MAX_SOURCE_NOTE_ZONE_HEIGHT,
    }
    assert request.metadata[SOURCE_NOTE_ZONE_MARKER] is True
    assert request.metadata[SOURCE_NOTE_OWNER_REF] == "#/pictures/0"


def test_multipage_visible_url_provenance_avoids_redundant_note_band() -> None:
    target = "https://example.com/figure"
    visual = _visual()
    visual["prov"] = _prov(10, 10, 90, 50, page_index=2)
    merged_text = {
        "self_ref": "#/texts/merged",
        "label": "text",
        "text": f"preceding page prose {target}",
        "prov": [
            {
                **_prov(
                    10,
                    100,
                    90,
                    110,
                    page_index=1,
                )[0],
                "charspan": [0, 20],
            },
            {
                **_prov(
                    10,
                    55,
                    70,
                    60,
                    page_index=2,
                )[0],
                "charspan": [20, 46],
            },
        ],
    }
    pages = [
        *_pages(),
        {
            "page_index": 2,
            "page_width": 100.0,
            "page_height": 200.0,
        },
    ]

    plan = plan_source_note_zone_requests(
        pages,
        _raw_graph(visual, texts=[merged_text]),
    )

    assert plan.requests == ()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda raw: raw["pictures"][0].update(
            {"source_notes": [{"$ref": "#/texts/note"}]}
        ),
        lambda raw: raw["texts"].append(
            {
                "self_ref": "#/texts/note",
                "label": "text",
                "text": "Note: already visible",
                "prov": _prov(10, 54, 70, 61),
            }
        ),
        lambda raw: raw["pictures"][0].pop("captions"),
    ],
)
def test_declared_visible_or_uncaptioned_visual_does_not_render_note_zone(
    mutator: Any,
) -> None:
    raw = _raw_graph(_visual())
    mutator(raw)

    plan = plan_source_note_zone_requests(_pages(), raw)

    assert plan.requests == ()


def test_note_zone_requests_are_capped_at_sixteen_per_page() -> None:
    pictures = tuple(
        _visual(index, top=10 + index * 2, bottom=11 + index * 2)
        for index in range(MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE + 3)
    )

    plan = plan_source_note_zone_requests(
        _pages(height=1000),
        _raw_graph(*pictures),
    )

    assert len(plan.requests) == MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE
    assert plan.concerns == (
        {
            "code": "layout_source_note_zone_request_limit",
            "page_index": 1,
            "candidate_count": MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE + 3,
            "limit": MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE,
        },
    )


def test_flag_off_render_selection_is_exact_and_does_not_touch_raw_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_graph(_visual())
    before = deepcopy(raw)

    def unexpected_plan(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("flag-off path called source-note planning")

    monkeypatch.setattr(
        "app.services.layout_source_notes.plan_source_note_zone_requests",
        unexpected_plan,
    )
    requests = _select_pdf_render_requests(
        _pages(),
        ("ordinary native page text",),
        raw,
        {},
        Settings(),
    )

    assert raw == before
    assert all(
        request.content_type != SOURCE_NOTE_ZONE_CONTENT_TYPE
        for request in requests
    )


def test_marked_accepted_data_line_becomes_exact_raw_note_and_never_leaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.layout_source_notes._annotation_nodes",
        lambda _pdf_bytes, _raw_graph=None: ([], []),
    )
    raw = _raw_graph(_visual())
    region = _marked_region()
    image_regions = {1: [region]}

    result = augment_source_note_evidence(
        raw,
        image_regions,
        pdf_bytes=b"",
        accept_ocr_line=lambda _line: True,
    )

    assert image_regions == {1: []}
    assert len(result.source_note_refs) == 1
    reference = result.source_note_refs[0]
    note = next(
        item for item in raw["texts"] if item.get("self_ref") == reference
    )
    assert note["label"] == "source_note"
    assert note["text"] == "Data: Aon Catastrophe Insight"
    assert note["source"] == "ocr"
    assert note["evidence_methods"] == ["ocr"]
    assert note["confidence"] == 0.96
    assert note["prov"] == [
        {
            "page_no": 1,
            "bbox": {
                "l": 11.0,
                "t": 56.0,
                "r": 81.0,
                "b": 62.0,
                "coord_origin": "TOPLEFT",
            },
            "charspan": [0, 29],
        }
    ]
    assert note["meta"][SOURCE_NOTE_OCR_MARKER] == {
        "owner_ref": "#/pictures/0",
        "source_visible": True,
    }
    assert raw["pictures"][0]["source_notes"] == [{"$ref": reference}]
    assert raw[SOURCE_NOTE_EVIDENCE_LEDGER]["source_note_refs"] == [
        reference
    ]


@pytest.mark.parametrize(
    ("region", "accept"),
    [
        (_marked_region(text="ordinary nearby prose"), True),
        (_marked_region(), False),
        (_marked_region(region_y=49.0), True),
        (_marked_region(line_y=49.0), True),
    ],
)
def test_unaccepted_unmarked_or_misaligned_ocr_never_synthesizes_note(
    monkeypatch: pytest.MonkeyPatch,
    region: ImageRegion,
    accept: bool,
) -> None:
    monkeypatch.setattr(
        "app.services.layout_source_notes._annotation_nodes",
        lambda _pdf_bytes, _raw_graph=None: ([], []),
    )
    raw = _raw_graph(_visual())
    image_regions = {1: [region]}

    result = augment_source_note_evidence(
        raw,
        image_regions,
        pdf_bytes=b"",
        accept_ocr_line=lambda _line: accept,
    )

    assert image_regions == {1: []}
    assert result.source_note_refs == ()
    assert not raw["pictures"][0].get("source_notes")


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("content_type", "image"),
        ("region_origin", "embedded_pdf_image"),
        ("coordinate_unit", "px"),
        ("region_role", "page_source"),
        ("page_index", 2),
    ],
)
def test_forged_or_cross_page_marked_regions_are_evidence_only(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    field_value: Any,
) -> None:
    monkeypatch.setattr(
        "app.services.layout_source_notes._annotation_nodes",
        lambda _pdf_bytes, _raw_graph=None: ([], []),
    )
    region = _marked_region()
    setattr(region, field_name, field_value)
    raw = _raw_graph(_visual())
    image_regions = {region.page_index: [region]}

    result = augment_source_note_evidence(
        raw,
        image_regions,
        pdf_bytes=b"",
        accept_ocr_line=lambda _line: True,
    )

    assert image_regions == {region.page_index: []}
    assert result.source_note_refs == ()
    assert not raw["pictures"][0].get("source_notes")


def test_ocr_line_outside_marked_zone_never_synthesizes_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.layout_source_notes._annotation_nodes",
        lambda _pdf_bytes, _raw_graph=None: ([], []),
    )
    region = _marked_region()
    region.lines[0].bbox = {
        "x": -100.0,
        "y": 56.0,
        "w": 115.0,
        "h": 6.0,
    }
    raw = _raw_graph(_visual())
    image_regions = {1: [region]}

    result = augment_source_note_evidence(
        raw,
        image_regions,
        pdf_bytes=b"",
        accept_ocr_line=lambda _line: True,
    )

    assert image_regions == {1: []}
    assert result.source_note_refs == ()


def test_private_zone_is_removed_before_later_annotation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_annotations(
        _pdf_bytes: bytes,
        _raw_graph: Mapping[str, Any] | None = None,
    ) -> Any:
        raise RuntimeError("annotation adapter failed")

    monkeypatch.setattr(
        "app.services.layout_source_notes._annotation_nodes",
        fail_annotations,
    )
    raw = _raw_graph(_visual())
    image_regions = {1: [_marked_region()]}

    with pytest.raises(RuntimeError, match="annotation adapter failed"):
        augment_source_note_evidence(
            raw,
            image_regions,
            pdf_bytes=b"",
            accept_ocr_line=lambda _line: True,
        )

    assert image_regions == {1: []}
    assert [item["label"] for item in raw["texts"]] == ["caption"]
    assert not raw["pictures"][0].get("source_notes")


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        "data:text/html,unsafe",
        "file:///etc/passwd",
        "https://user:secret@example.com/path",
        "https://example.com/path\ninjected",
        "https://example.com\n",
        " https://example.com",
        "https://example.com\\@attacker.invalid/path",
        "https://example.com/path\\evil",
        "mailto:auditor@example.com",
    ],
)
def test_unsafe_or_credentialed_annotation_targets_are_rejected(
    target: str,
) -> None:
    assert safe_http_annotation_target(target) is None


@pytest.mark.parametrize(
    "target",
    [
        "http://example.com",
        "https://stat.link/hufsd5",
        "https://example.com:8443/path?query=value#fragment",
    ],
)
def test_bounded_http_annotation_targets_are_accepted(target: str) -> None:
    assert safe_http_annotation_target(target) == target


class _FakeCrop:
    def __init__(self, visible_text: str) -> None:
        self.visible_text = visible_text

    def extract_text(self, **_kwargs: Any) -> str:
        return self.visible_text


class _FakePage:
    width = 200.0
    height = 300.0

    def __init__(
        self,
        annotations: list[dict[str, Any]],
        visible_text: str,
    ) -> None:
        self.hyperlinks = annotations
        self.visible_text = visible_text
        self.crop_count = 0

    def crop(self, _bbox: Any) -> _FakeCrop:
        self.crop_count += 1
        return _FakeCrop(self.visible_text)


class _FakeDocument:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakeDocument:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def _annotation(target: str) -> dict[str, Any]:
    return {
        "x0": 20.0,
        "top": 100.0,
        "x1": 160.0,
        "bottom": 112.0,
        "uri": target,
    }


def test_source_visible_pdf_annotation_synthesizes_bounded_native_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "https://stat.link/hufsd5"
    document = _FakeDocument(
        [_FakePage([_annotation(target)], f"StatLink 2 {target}")]
    )
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _stream: document,
    )

    nodes, concerns = _annotation_nodes(b"%PDF-fake")

    assert concerns == []
    assert len(nodes) == 1
    node = nodes[0]
    assert node["label"] == "annotation"
    assert node["text"] == f"StatLink 2 {target}"
    assert node["hyperlink"] == target
    assert node["source"] == "native"
    assert node["evidence_methods"] == ["native"]
    assert node["prov"][0]["bbox"] == {
        "l": 20.0,
        "t": 100.0,
        "r": 160.0,
        "b": 112.0,
        "coord_origin": "TOPLEFT",
    }
    assert node["meta"][SOURCE_NOTE_ANNOTATION_MARKER][
        "source_visible"
    ] is True


def test_annotation_text_is_extracted_only_near_a_structured_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "https://example.com/source"
    far_annotation = {
        **_annotation(target),
        "top": 200.0,
        "bottom": 212.0,
    }
    page = _FakePage([far_annotation], target)
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _stream: _FakeDocument([page]),
    )

    nodes, concerns = _annotation_nodes(
        b"%PDF-fake",
        _raw_graph(_visual()),
    )

    assert nodes == []
    assert page.crop_count == 0
    assert any(
        concern["code"] == "layout_source_note_annotation_rejected"
        and concern["reason"] == "not_near_structured_owner"
        for concern in concerns
    )


def test_unsafe_annotation_concerns_never_echo_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = [
        "javascript:alert(document.cookie)",
        "https://user:secret@example.com/private",
        "https://safe.example/not-visible",
    ]
    document = _FakeDocument(
        [
            _FakePage(
                [_annotation(target) for target in targets],
                "ordinary source-visible label",
            )
        ]
    )
    monkeypatch.setattr(pdfplumber, "open", lambda _stream: document)

    nodes, concerns = _annotation_nodes(b"%PDF-fake")
    serialized = json.dumps(concerns, sort_keys=True)

    assert nodes == []
    assert concerns
    assert all(target not in serialized for target in targets)
    assert "secret" not in serialized
    assert "document.cookie" not in serialized


def test_annotation_page_and_document_caps_are_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "https://example.com/source"
    pages = [
        _FakePage(
            [_annotation(target) for _ in range(300)],
            target,
        )
        for _ in range(5)
    ]
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _stream: _FakeDocument(pages),
    )

    nodes, concerns = _annotation_nodes(b"%PDF-fake")

    assert len(nodes) == MAX_PDF_ANNOTATIONS_PER_DOCUMENT
    assert any(
        concern["code"] == "layout_source_note_annotation_page_limit"
        and concern["limit"] == MAX_PDF_ANNOTATIONS_PER_PAGE
        for concern in concerns
    )
    assert any(
        concern["code"] == "layout_source_note_annotation_document_limit"
        and concern["limit"] == MAX_PDF_ANNOTATIONS_PER_DOCUMENT
        for concern in concerns
    )


def test_rejected_annotations_still_consume_document_scan_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        _FakePage(
            [
                _annotation("javascript:never-retained")
                for _ in range(300)
            ],
            "visible label",
        )
        for _ in range(5)
    ]
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _stream: _FakeDocument(pages),
    )

    nodes, concerns = _annotation_nodes(b"%PDF-fake")

    assert nodes == []
    document_limit = next(
        concern
        for concern in concerns
        if concern["code"]
        == "layout_source_note_annotation_document_limit"
    )
    assert document_limit["examined_count"] == (
        MAX_PDF_ANNOTATIONS_PER_DOCUMENT
    )
    assert document_limit["retained_count"] == 0


def test_annotation_augmentation_records_refs_without_public_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "https://doi.org/10.1371/example.t001"
    document = _FakeDocument([_FakePage([_annotation(target)], target)])
    monkeypatch.setattr(pdfplumber, "open", lambda _stream: document)
    raw = _raw_graph(_visual())
    image_regions: dict[int, list[ImageRegion]] = {1: []}

    result = augment_source_note_evidence(
        raw,
        image_regions,
        pdf_bytes=b"%PDF-fake",
        accept_ocr_line=lambda _line: True,
    )

    assert len(result.annotation_refs) == 1
    reference = result.annotation_refs[0]
    node = next(
        item for item in raw["texts"] if item.get("self_ref") == reference
    )
    assert node["hyperlink"] == target
    assert raw[SOURCE_NOTE_EVIDENCE_LEDGER]["annotation_refs"] == [
        reference
    ]
    assert image_regions == {1: []}
