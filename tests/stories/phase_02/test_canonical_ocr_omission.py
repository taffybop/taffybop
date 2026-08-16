from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pypdfium2 as pdfium
import pytest

from app.services import canonical_ocr_omission as omission
from app.services.source_text_alignment import SourceBBox


_NY_PDF = Path("benchmark-expertmodeldata/ny-timetable.pdf")


def _cell(
    bbox: SourceBBox,
    *,
    text: str,
    key: str,
) -> dict[str, Any]:
    return {
        "bbox": bbox,
        "row_bbox": bbox,
        "table_bbox": SourceBBox(24.0, 24.25, 351.49, 742.78),
        "row_index": 0,
        "column_index": 0,
        "text": text,
        "source_text": text,
        "source_closed": True,
        "row_source_closed": True,
        "row_key_sha256": "d" * 64,
        "row_source_text_sha256": "e" * 64,
        "row_source_character_ids_sha256": "f" * 64,
        "key_sha256": key,
    }


def test_pdf_name_preflight_rejects_hidden_text_and_paint_features() -> None:
    omission._preflight_pdf_names(
        _NY_PDF.read_bytes(), deadline=time.perf_counter() + 1.0
    )
    for value in (
        b"/ToUnicode 1 0 R",
        b"/#54oUnicode 1 0 R",
        b"/Differences []",
        b"/ObjStm",
        b"/Pattern",
        b"/ActualText (spoof)",
        b"/OCProperties",
        b"/Type0",
        b"/CIDFontType0",
        b"/CIDFontType2",
        b"/TrueType",
        b"/FontFile",
        b"/FontFile2",
        b"/FontFile3",
    ):
        with pytest.raises(omission.CanonicalOcrOmissionRefusal):
            omission._preflight_pdf_names(
                value, deadline=time.perf_counter() + 1.0
            )


def test_pdfium_standard_font_text_fragments_close_one_source_cell() -> None:
    document = pdfium.PdfDocument(str(_NY_PDF))
    page = document[0]
    text_page = page.get_textpage()
    objects = list(page.get_objects(max_depth=8, textpage=text_page))
    try:
        cell = _cell(
            SourceBBox(105.58, 49.48, 27.22, 111.15),
            text="Times Sq 42 St",
            key="times-square",
        )
        manifests = [
            omission._text_manifest(
                objects[index],
                object_index=index,
                object_box=omission._top_left_box(
                    objects[index].get_bounds(), page_height=792.0
                ),
                cells=[cell],
            )
            for index in (11, 13)
        ]
        assert omission._normalized(
            "".join(value["text"] for value in manifests)
        ) == cell["text"]
        assert [value["font"] for value in manifests] == [
            "Helvetica-Bold",
            "Helvetica-Bold",
        ]
    finally:
        for obj in objects:
            obj.close()
        text_page.close()
        page.close()
        document.close()


def test_pdfium_fill_and_dashed_grid_are_owned_only_by_cell_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = pdfium.PdfDocument(str(_NY_PDF))
    page = document[0]
    text_page = page.get_textpage()
    objects = list(page.get_objects(max_depth=8, textpage=text_page))
    try:
        fill_cell = _cell(
            SourceBBox(105.58, 49.48, 27.22, 111.15),
            text="Times Sq 42 St",
            key="fill",
        )
        fill = omission._path_manifest(
            objects[10],
            object_index=10,
            object_box=omission._top_left_box(
                objects[10].get_bounds(), page_height=792.0
            ),
            cells=[fill_cell],
            page_height=792.0,
        )
        assert fill["kind"] == "cell_fill"
        assert fill["cell_insets"] == pytest.approx(
            [0.25, 0.5, 0.5, 0.35], abs=1e-4
        )
        assert fill["cell_area_ratio"] == pytest.approx(0.96501, abs=1e-5)

        row_box = SourceBBox(24.0, 24.25, 135.51, 25.48)
        cell_width = row_box.width / 5
        merged_row_cells: list[dict[str, Any]] = []
        for column_index in range(5):
            value = _cell(
                SourceBBox(
                    row_box.x + column_index * cell_width,
                    row_box.y,
                    cell_width,
                    row_box.height,
                ),
                text="Weekdays to The Bronx" if column_index == 0 else "",
                key=f"{column_index:064x}",
            )
            value.update(
                {
                    "source_closed": False,
                    "row_index": 0,
                    "column_index": column_index,
                    "row_bbox": row_box,
                    "row_source_closed": True,
                    "row_key_sha256": "a" * 64,
                    "row_source_line_id": "line-1",
                    "row_source_text_sha256": "b" * 64,
                    "row_source_character_ids_sha256": "c" * 64,
                    "row_boxed_character_ids_sha256": "d" * 64,
                    "row_source_character_indexes_sha256": "e" * 64,
                    "row_source_character_index_span": [0, 20],
                }
            )
            merged_row_cells.append(value)
        merged_fill = omission._path_manifest(
            objects[0],
            object_index=0,
            object_box=omission._top_left_box(
                objects[0].get_bounds(), page_height=792.0
            ),
            cells=merged_row_cells,
            page_height=792.0,
        )
        assert merged_fill["kind"] == "cell_union_fill"
        assert merged_fill["cell_span"] == [0, 0, 4]
        assert merged_fill["cell_insets"] == pytest.approx(
            [0.5, 0.25, 0.000005, 0.250019], abs=1e-4
        )
        assert merged_fill["cell_area_ratio"] == pytest.approx(
            0.976759, abs=1e-5
        )

        for mutate in (
            lambda values: values[2].update({"column_index": 7}),
            lambda values: values[2].update(
                {"row_bbox": SourceBBox(24.0, 24.25, 135.51, 50.0)}
            ),
            lambda values: values[2].update({"row_source_closed": False}),
            lambda values: values[2].update(
                {"row_source_character_ids_sha256": "9" * 64}
            ),
            lambda values: values[2].update(
                {"row_boxed_character_ids_sha256": "8" * 64}
            ),
            lambda values: values[2].update(
                {"row_source_character_index_span": [0, 19]}
            ),
            lambda values: values[2].update({"row_source_line_id": "line-2"}),
            lambda values: values[2].update(
                {
                    "bbox": SourceBBox(
                        values[2]["bbox"].x,
                        values[2]["bbox"].y,
                        values[2]["bbox"].width,
                        40.0,
                    )
                }
            ),
        ):
            hostile_cells = [dict(value) for value in merged_row_cells]
            mutate(hostile_cells)
            with pytest.raises(omission.CanonicalOcrOmissionRefusal):
                omission._path_manifest(
                    objects[0],
                    object_index=0,
                    object_box=omission._top_left_box(
                        objects[0].get_bounds(), page_height=792.0
                    ),
                    cells=hostile_cells,
                    page_height=792.0,
                )
        upper = _cell(
            SourceBBox(186.73, 196.94, 26.47, 11.99),
            text="12:48",
            key="upper",
        )
        lower = _cell(
            SourceBBox(186.73, 208.93, 26.47, 11.99),
            text="12:58",
            key="lower",
        )
        dashed = omission._path_manifest(
            objects[1353],
            object_index=1353,
            object_box=omission._top_left_box(
                objects[1353].get_bounds(), page_height=792.0
            ),
            cells=[upper, lower],
            page_height=792.0,
        )
        assert dashed["kind"] == "grid_stroke"
        assert dashed["dash"] == [0.7, 1.02]
        assert dashed["dash_phase"] == 1.21

        original_matrix = objects[1353].get_matrix()
        scaled = SimpleNamespace(
            raw=objects[1353].raw,
            get_matrix=lambda: SimpleNamespace(
                a=2.0,
                b=0.0,
                c=0.0,
                d=1.0,
                e=0.0,
                f=0.0,
            ),
        )
        with pytest.raises(omission.CanonicalOcrOmissionRefusal):
            omission._path_manifest(
                scaled,
                object_index=1353,
                object_box=omission._top_left_box(
                    objects[1353].get_bounds(), page_height=792.0
                ),
                cells=[upper, lower],
                page_height=792.0,
            )
        assert original_matrix.a == 1.0
        for getter in ("FPDFPageObj_GetLineCap", "FPDFPageObj_GetLineJoin"):
            with monkeypatch.context() as scoped:
                scoped.setattr(omission.pdfium_raw, getter, lambda _raw: 1)
                with pytest.raises(omission.CanonicalOcrOmissionRefusal):
                    omission._path_manifest(
                        objects[1353],
                        object_index=1353,
                        object_box=omission._top_left_box(
                            objects[1353].get_bounds(), page_height=792.0
                        ),
                        cells=[upper, lower],
                        page_height=792.0,
                    )
        with monkeypatch.context() as scoped:
            scoped.setattr(
                omission,
                "_path_segments",
                lambda *_a, **_k: (
                    (omission.pdfium_raw.FPDF_SEGMENT_MOVETO, False, 1.0, 1.0),
                    (omission.pdfium_raw.FPDF_SEGMENT_LINETO, False, 1.0, 1.0),
                ),
            )
            with pytest.raises(omission.CanonicalOcrOmissionRefusal):
                omission._path_manifest(
                    objects[1353],
                    object_index=1353,
                    object_box=omission._top_left_box(
                        objects[1353].get_bounds(), page_height=792.0
                    ),
                    cells=[upper, lower],
                    page_height=792.0,
                )

        hostile = dict(lower)
        hostile["bbox"] = SourceBBox(190.0, 300.0, 20.0, 10.0)
        with pytest.raises(omission.CanonicalOcrOmissionRefusal):
            omission._path_manifest(
                objects[1353],
                object_index=1353,
                object_box=omission._top_left_box(
                    objects[1353].get_bounds(), page_height=792.0
                ),
                cells=[hostile],
                page_height=792.0,
            )
    finally:
        for obj in objects:
            obj.close()
        text_page.close()
        page.close()
        document.close()


def test_row_source_sequence_allows_only_unrepresented_whitespace() -> None:
    assert omission._row_source_sequence_matches(
        "Weekdaysto The Bronx", "Weekdays to The Bronx"
    )
    for source in (
        "WeekdaysTo The Bronx",
        "Weekdays!to The Bronx",
        "Weekdaysto The Bron",
        "WeekdaysThe to Bronx",
    ):
        assert not omission._row_source_sequence_matches(
            source, "Weekdays to The Bronx"
        )


def test_candidate_requires_exact_geometric_source_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_box = SourceBBox(0.0, 0.0, 20.0, 10.0)
    first = SimpleNamespace(
        id="char-1",
        character_index=1,
        bbox=SourceBBox(1.0, 1.0, 2.0, 2.0),
        excluded_reason=None,
        text="T",
    )
    second = SimpleNamespace(
        id="char-2",
        character_index=2,
        bbox=SourceBBox(5.0, 1.0, 2.0, 2.0),
        excluded_reason=None,
        text="4",
    )
    page = SimpleNamespace(page_index=1, characters=(first, second))
    evidence = SimpleNamespace(pages=(page,))
    selection = SimpleNamespace(
        text="T4",
        raw_text="T4",
        bbox=SourceBBox(1.0, 1.0, 6.0, 2.0),
        source_line_ids=("line-1",),
        source_character_ids=("char-1", "char-2"),
        source_character_indexes=(1, 2),
        type1_evidence_ids=(),
        source_roles=(),
    )
    monkeypatch.setattr(omission, "text_for_bbox", lambda *_a, **_k: selection)
    cell = {
        **_cell(owner_box, text="T4", key="a" * 64),
        "source_character_ids": ("char-1", "char-2"),
        "table_id": "table-1",
        "representation_sha256": "c" * 64,
    }
    contradiction = omission._candidate_source_contradiction(
        evidence=evidence,
        page_index=1,
        owner_box=owner_box,
        owner_text="ew",
        cells=[cell],
        expected_owner_cell_keys=["a" * 64],
        expected_table_id="table-1",
        expected_representation_sha256="c" * 64,
        deadline=time.perf_counter() + 1.0,
    )
    assert contradiction is not None
    assert contradiction["text"] == "T4"
    assert contradiction["source_character_indexes"] == [1, 2]
    selection.source_line_ids = ("line-1", "line-2")
    assert omission._candidate_source_contradiction(
        evidence=evidence,
        page_index=1,
        owner_box=owner_box,
        owner_text="ew",
        cells=[cell],
        expected_owner_cell_keys=["a" * 64],
        expected_table_id="table-1",
        expected_representation_sha256="c" * 64,
        deadline=time.perf_counter() + 1.0,
    ) is not None
    for line_ids in (("line-1", "line-1"), tuple(f"line-{i}" for i in range(65))):
        selection.source_line_ids = line_ids
        assert omission._candidate_source_contradiction(
            evidence=evidence,
            page_index=1,
            owner_box=owner_box,
            owner_text="ew",
            cells=[cell],
            expected_owner_cell_keys=["a" * 64],
            expected_table_id="table-1",
            expected_representation_sha256="c" * 64,
            deadline=time.perf_counter() + 1.0,
        ) is None
    selection.source_line_ids = ("line-1",)

    for owner_text in ("T4", "T", "T4 suffix"):
        assert omission._candidate_source_contradiction(
            evidence=evidence,
            page_index=1,
            owner_box=owner_box,
            owner_text=owner_text,
            cells=[cell],
            expected_owner_cell_keys=["a" * 64],
            expected_table_id="table-1",
            expected_representation_sha256="c" * 64,
            deadline=time.perf_counter() + 1.0,
        ) is None

    ambiguous = [cell, {**cell, "key_sha256": "b" * 64}]
    assert omission._candidate_source_contradiction(
        evidence=evidence,
        page_index=1,
        owner_box=owner_box,
        owner_text="ew",
        cells=ambiguous,
        expected_owner_cell_keys=["a" * 64, "b" * 64],
        expected_table_id="table-1",
        expected_representation_sha256="c" * 64,
        deadline=time.perf_counter() + 1.0,
    ) is None
    foreign = {
        **cell,
        "key_sha256": "d" * 64,
        "table_id": "table-foreign",
        "representation_sha256": "e" * 64,
        "source_closed": False,
    }
    assert omission._candidate_source_contradiction(
        evidence=evidence,
        page_index=1,
        owner_box=owner_box,
        owner_text="ew",
        cells=[cell, foreign],
        expected_owner_cell_keys=["a" * 64],
        expected_table_id="table-1",
        expected_representation_sha256="c" * 64,
        deadline=time.perf_counter() + 1.0,
    ) is None
    extra_cell = {
        **_cell(
            SourceBBox(10.0, 0.0, 10.0, 10.0),
            text="extra",
            key="b" * 64,
        ),
        "source_character_ids": (),
    }
    extra_contradiction = omission._candidate_source_contradiction(
        evidence=evidence,
        page_index=1,
        owner_box=owner_box,
        owner_text="ew",
        cells=[cell, extra_cell],
        expected_owner_cell_keys=["a" * 64, "b" * 64],
        expected_table_id="table-1",
        expected_representation_sha256="c" * 64,
        deadline=time.perf_counter() + 1.0,
    )
    assert extra_contradiction is not None
    assert extra_contradiction["cell_keys"] == ["a" * 64]
    outside = SimpleNamespace(**{**vars(second), "bbox": SourceBBox(30, 1, 2, 2)})
    page.characters = (first, outside)
    assert omission._candidate_source_contradiction(
        evidence=evidence,
        page_index=1,
        owner_box=owner_box,
        owner_text="ew",
        cells=[cell],
        expected_owner_cell_keys=["a" * 64],
        expected_table_id="table-1",
        expected_representation_sha256="c" * 64,
        deadline=time.perf_counter() + 1.0,
    ) is None


def test_candidate_retains_foreign_overlapping_table_without_source_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_box = SourceBBox(0.0, 0.0, 10.0, 10.0)
    item = {
        "id": "p1-i1",
        "type": "text",
        "value": "ew",
        "md": "ew",
        "reading_order": 0,
        "confidence": 0.9,
        "ocr_contributor": {
            "region_origin": "pdf_page_render",
            "region_role": "page_source",
        },
    }
    pages = [
        {
            "page_index": 1,
            "page_width": 100.0,
            "page_height": 100.0,
            "items": [item],
        }
    ]
    source_page = SimpleNamespace(
        page_index=1,
        page_width=100.0,
        page_height=100.0,
        characters=(),
    )
    evidence = SimpleNamespace(source_sha256="f" * 64, pages=(source_page,))
    primary = {
        **_cell(owner_box, text="T4", key="a" * 64),
        "table_id": "table-1",
        "representation_sha256": "b" * 64,
        "source_character_ids": (),
    }
    foreign = {
        **primary,
        "key_sha256": "c" * 64,
        "table_id": "table-2",
        "representation_sha256": "d" * 64,
        "source_closed": False,
    }
    monkeypatch.setattr(
        omission,
        "_selected_vector_owner_shape",
        lambda *_a, **_k: (owner_box, False),
    )
    monkeypatch.setattr(
        omission,
        "_selected_vector_page_reference_counts",
        lambda *_a, **_k: {"p1-i1": 1},
    )
    assert omission._build_candidates(
        pages,
        SimpleNamespace(),
        SimpleNamespace(),
        evidence,
        {1: (primary, foreign)},
        deadline=time.perf_counter() + 1.0,
        comparison_budget=[0],
    ) == []


def test_candidate_scan_keeps_safe_owner_when_other_owners_have_no_or_ambiguous_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    safe_box = SourceBBox(0.0, 0.0, 10.0, 10.0)
    outside_box = SourceBBox(50.0, 50.0, 10.0, 10.0)
    ambiguous_box = SourceBBox(20.0, 20.0, 10.0, 10.0)

    def item(identifier: str) -> dict[str, Any]:
        return {
            "id": identifier,
            "type": "text",
            "value": "ocr",
            "md": "ocr",
            "reading_order": 0,
            "confidence": 0.9,
            "ocr_contributor": {
                "region_origin": "pdf_page_render",
                "region_role": "page_source",
            },
        }

    pages = [
        {
            "page_index": 1,
            "page_width": 100.0,
            "page_height": 100.0,
            "items": [item("safe"), item("outside"), item("ambiguous")],
        }
    ]
    evidence = SimpleNamespace(
        source_sha256="f" * 64,
        pages=(
            SimpleNamespace(
                page_index=1,
                page_width=100.0,
                page_height=100.0,
                characters=(),
            ),
        ),
    )

    def cell(box: SourceBBox, table: str, authority: str, key: str) -> dict[str, Any]:
        return {
            **_cell(box, text="source", key=key),
            "table_id": table,
            "representation_sha256": authority,
            "source_character_ids": (),
            "source_character_ids_sha256": "9" * 64,
        }

    cells = (
        cell(safe_box, "safe-table", "a" * 64, "1" * 64),
        cell(ambiguous_box, "first-table", "b" * 64, "2" * 64),
        cell(ambiguous_box, "second-table", "c" * 64, "3" * 64),
    )
    boxes = {
        "safe": safe_box,
        "outside": outside_box,
        "ambiguous": ambiguous_box,
    }
    monkeypatch.setattr(
        omission,
        "_selected_vector_owner_shape",
        lambda raw, **_kwargs: (boxes[raw["id"]], False),
    )
    monkeypatch.setattr(
        omission,
        "_selected_vector_page_reference_counts",
        lambda *_a, **_k: {value: 1 for value in boxes},
    )
    monkeypatch.setattr(
        omission,
        "_candidate_source_contradiction",
        lambda **kwargs: {
            "cell_keys": list(kwargs["expected_owner_cell_keys"]),
        },
    )
    monkeypatch.setattr(
        omission,
        "_candidate_ir_and_canonical_custody",
        lambda **_kwargs: ("element-safe", "block-safe", "d" * 64),
    )
    candidates = omission._build_candidates(
        pages,
        SimpleNamespace(),
        SimpleNamespace(),
        evidence,
        {1: cells},
        deadline=time.perf_counter() + 1.0,
        comparison_budget=[0],
    )
    assert [value["owner_id"] for value in candidates] == ["safe"]


def test_bboxless_source_separator_is_exactly_bracketed_and_sealed() -> None:
    visible_left = SimpleNamespace(
        id="left",
        character_index=529,
        text="4",
        bbox=SourceBBox(1.0, 1.0, 1.0, 1.0),
        excluded_reason=None,
    )
    separator = SimpleNamespace(
        id="space",
        character_index=530,
        text=" ",
        bbox=None,
        excluded_reason=None,
    )
    visible_right = SimpleNamespace(
        id="right",
        character_index=531,
        text="1",
        bbox=SourceBBox(3.0, 1.0, 1.0, 1.0),
        excluded_reason=None,
    )
    characters = {
        value.id: value for value in (visible_left, separator, visible_right)
    }
    manifest = omission._source_separator_manifest(
        contradiction_pairs=(("left", 529), ("space", 530), ("right", 531)),
        observed_pairs=(("left", 529), ("right", 531)),
        source_characters_by_id=characters,
    )
    assert manifest is not None
    assert manifest["source_character_ids"] == ["space"]
    assert manifest["source_character_indexes"] == [530]

    hostile_mutations = (
        {"bbox": SourceBBox(2.0, 1.0, 1.0, 1.0)},
        {"text": "x"},
        {"excluded_reason": "unsafe"},
        {"character_index": 777},
    )
    for mutation in hostile_mutations:
        hostile_separator = SimpleNamespace(**{**vars(separator), **mutation})
        with pytest.raises(
            omission.CanonicalOcrOmissionRefusal,
            match="source separator differs",
        ):
            omission._source_separator_manifest(
                contradiction_pairs=(
                    ("left", 529),
                    ("space", 530),
                    ("right", 531),
                ),
                observed_pairs=(("left", 529), ("right", 531)),
                source_characters_by_id={**characters, "space": hostile_separator},
            )

    with pytest.raises(
        omission.CanonicalOcrOmissionRefusal,
        match="source separator differs",
    ):
        omission._source_separator_manifest(
            contradiction_pairs=(("space", 530), ("right", 531)),
            observed_pairs=(("right", 531),),
            source_characters_by_id=characters,
        )


def test_source_separator_is_sealed_separately_from_physical_pdf_objects() -> None:
    candidate = {
        "owner": {
            "id": "p1-i1",
            "type": "heading",
            "value": "12:58 | 1:04",
            "confidence": 0.9,
            "ocr_contributor": {"region_origin": "pdf_page_render"},
        },
        "source_contradiction": {
            "source_line_ids": ["line-1"],
            "source_character_ids": ["left", "space", "right"],
            "type1_mapping_ids": [],
            "source_roles": [],
        },
        "page_index": 1,
        "item_position": 2,
        "owner_bbox": SourceBBox(1.0, 1.0, 10.0, 4.0),
        "crop_bbox": SourceBBox(0.0, 0.0, 14.0, 8.0),
        "table_id": "table-1",
        "representation_sha256": "a" * 64,
        "owner_cell_keys": ("b" * 64, "c" * 64),
        "owner_cell_source_sha256": "d" * 64,
        "element_id": "element-1",
        "canonical_block_id": "block-1",
        "canonical_block_sha256": "e" * 64,
        "canonical_predecessor_explicit_null_paths": [],
    }
    physical = [
        {"kind": "text", "index": 1},
        {"kind": "grid_stroke", "index": 2},
    ]
    separator = {
        "kind": "source_whitespace_separators",
        "source_character_ids": ["space"],
        "source_character_indexes": [530],
        "text_sha256": "f" * 64,
    }
    selection = omission._selection(
        candidate,
        [*physical, separator],
        SimpleNamespace(source_sha256="9" * 64),
    )
    authority = selection["rejected_ocr_alternative"]["canonical_owner"]
    assert authority["pdf_object_count"] == 2
    assert authority["pdf_object_manifest_sha256"] == omission._digest(physical)
    assert authority["source_separator_count"] == 1
    assert authority["source_separator_manifest_sha256"] == omission._digest(
        [separator]
    )
    tampered = omission._selection(
        candidate,
        [*physical, {**separator, "source_character_indexes": [531]}],
        SimpleNamespace(source_sha256="9" * 64),
    )
    assert tampered["id"] != selection["id"]


def test_canonical_owner_ir_bbox_and_evidence_cannot_be_shared() -> None:
    class Model(SimpleNamespace):
        def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
            return dict(vars(self))

    owner_box = SourceBBox(1.0, 2.0, 3.0, 4.0)
    item = {
        "id": "p1-i1",
        "type": "text",
        "value": "ew",
        "md": "ew",
        "reading_order": 0,
        "confidence": 0.9,
    }
    presentation = SimpleNamespace(
        accepted=True,
        include_subordinate_ocr=None,
    )
    element = SimpleNamespace(
        id="element-1",
        page_id="page-1",
        type="text",
        reading_order=0,
        value="ew",
        markdown="ew",
        presentation_role="primary",
        presentation=presentation,
        text_run_ids=[],
        form_semantics=None,
        outline_group=None,
        outline_item=None,
        running_region=None,
        visual_model_evidence=None,
        bbox_ids=["bbox-1"],
        evidence_ids=["evidence-1"],
        properties={
            "legacy_item": dict(item),
            "generated": False,
            "region_role": None,
            "content_type": None,
            "source_position": 0,
        },
    )
    bbox = SimpleNamespace(
        id="bbox-1",
        coordinate_system_id="coords-1",
        role="element",
        x=1.0,
        y=2.0,
        width=3.0,
        height=4.0,
    )
    coordinate = SimpleNamespace(
        id="coords-1",
        page_id="page-1",
        unit="pt",
        origin="top_left",
        transform_to_page=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    )
    evidence_record = SimpleNamespace(
        id="evidence-1",
        element_id="element-1",
        method=omission.EvidenceMethod.OCR,
        bbox_id="bbox-1",
        value="ew",
        confidence=SimpleNamespace(
            scope="evidence",
            score=0.9,
            unavailable_reason=None,
        ),
        metadata={"source": "ocr", "engine": None},
    )
    page = SimpleNamespace(
        id="page-1",
        page_index=1,
        element_ids=["element-1"],
        presentation_element_ids=["element-1"],
    )
    region = SimpleNamespace(page_id="page-1", element_ids=["element-1"])
    ir = SimpleNamespace(
        elements=[element],
        pages=[page],
        bboxes=[bbox],
        coordinate_systems=[coordinate],
        evidence=[evidence_record],
        regions=[region],
        relationships=[],
        concerns=[],
    )
    block = Model(
        id="block-1",
        primary_element_id="element-1",
        primary_element_type="text",
        omission_reason=None,
        contributing_element_ids=["element-1"],
        relationship_ids=[],
        excluded_contributions=[],
        suppressed_by_element_id=None,
        text="ew",
        markdown="ew",
    )
    canonical = SimpleNamespace(
        pages=[SimpleNamespace(page_id="page-1", page_index=1, blocks=[block])]
    )
    assert omission._candidate_ir_and_canonical_custody(
        ir=ir,
        canonical=canonical,
        page_index=1,
        item_position=0,
        item=item,
        owner_box=owner_box,
    )[:2] == ("element-1", "block-1")

    for shared in (
        SimpleNamespace(
            id="other",
            properties={},
            bbox_ids=["bbox-1"],
            evidence_ids=[],
        ),
        SimpleNamespace(
            id="other",
            properties={},
            bbox_ids=[],
            evidence_ids=["evidence-1"],
        ),
    ):
        ir.elements.append(shared)
        with pytest.raises(omission.CanonicalOcrOmissionRefusal):
            omission._candidate_ir_and_canonical_custody(
                ir=ir,
                canonical=canonical,
                page_index=1,
                item_position=0,
                item=item,
                owner_box=owner_box,
            )
        ir.elements.pop()


def test_omission_summary_moves_existing_unchanged_owners_to_selected() -> None:
    summary = {
        "status": "selected",
        "considered_count": 3,
        "selected_count": 1,
        "unchanged_count": 2,
        "unresolved_count": 0,
        "selections": [
            {"id": "selection-old", "owner_id": "owner-old"}
        ],
        "concerns": [],
    }
    additions = [
        {"id": "selection-1", "owner_id": "owner-1"},
        {"id": "selection-2", "owner_id": "owner-2"},
    ]
    moved = omission._append_omission_selections(summary, additions)
    assert moved["considered_count"] == 3
    assert moved["selected_count"] == 3
    assert moved["unchanged_count"] == 0
    assert summary["selected_count"] == 1
    assert [value["id"] for value in moved["selections"]] == [
        "selection-old",
        "selection-1",
        "selection-2",
    ]

    for hostile in (
        {**summary, "unchanged_count": 1},
        {
            **summary,
            "concerns": [{"owner_id": "owner-1", "status": "unresolved"}],
            "unresolved_count": 1,
            "considered_count": 4,
        },
        {
            **summary,
            "selections": [
                {"id": "selection-old", "owner_id": "owner-1"}
            ],
        },
    ):
        with pytest.raises(omission.CanonicalOcrOmissionRefusal):
            omission._append_omission_selections(hostile, additions)


def test_grid_segment_cannot_bridge_an_unowned_or_merged_cell_gap() -> None:
    assert omission._interval_is_covered(
        0.0,
        20.0,
        [(0.0, 10.0), (10.0, 20.0)],
        tolerance=0.05,
    )


def test_retraced_five_segment_fill_is_not_a_cell_rectangle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = pdfium.PdfDocument(str(_NY_PDF))
    page = document[0]
    text_page = page.get_textpage()
    objects = list(page.get_objects(max_depth=8, textpage=text_page))
    try:
        cell = _cell(
            SourceBBox(105.58, 49.48, 27.22, 111.15),
            text="Times Sq 42 St",
            key="fill",
        )
        original_segments = omission._path_segments(
            objects[10].raw,
            omission._matrix_values(objects[10].get_matrix()),
        )
        monkeypatch.setattr(
            omission,
            "_path_segments",
            lambda *_args, **_kwargs: (
                (2, False, 105.83, 631.72),
                (0, False, 132.30, 631.72),
                (0, False, 105.83, 631.72),
                (0, False, 105.83, 742.02),
                (0, True, 105.83, 631.72),
            ),
        )
        with pytest.raises(omission.CanonicalOcrOmissionRefusal):
            omission._path_manifest(
                objects[10],
                object_index=10,
                object_box=omission._top_left_box(
                    objects[10].get_bounds(), page_height=792.0
                ),
                cells=[cell],
                page_height=792.0,
            )
        early_close = list(original_segments)
        early_close[1] = (
            early_close[1][0],
            True,
            early_close[1][2],
            early_close[1][3],
        )
        monkeypatch.setattr(
            omission,
            "_path_segments",
            lambda *_args, **_kwargs: tuple(early_close),
        )
        with pytest.raises(omission.CanonicalOcrOmissionRefusal):
            omission._path_manifest(
                objects[10],
                object_index=10,
                object_box=omission._top_left_box(
                    objects[10].get_bounds(), page_height=792.0
                ),
                cells=[cell],
                page_height=792.0,
            )
    finally:
        for obj in objects:
            obj.close()
        text_page.close()
        page.close()
        document.close()
    assert not omission._interval_is_covered(
        0.0,
        20.0,
        [(0.0, 9.0), (11.0, 20.0)],
        tolerance=0.05,
    )


def test_quantized_single_cell_fill_cannot_enter_neighbor_interior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = {
        **_cell(SourceBBox(0.0, 0.0, 10.0, 10.0), text="X", key="a" * 64),
        "table_bbox": SourceBBox(-1.0, -1.0, 30.0, 30.0),
    }
    accepted = SourceBBox(0.0, -0.1, 9.8, 9.7)
    owning, _box, insets, metrics = omission._filled_path_owner(
        accepted, [owner]
    )
    assert owning == (owner,)
    assert insets == pytest.approx((0.0, -0.1, 0.2, 0.4))
    assert metrics["owner_area_ratio"] == pytest.approx(0.9506)
    assert metrics["outside_owner_area_ratio"] == pytest.approx(0.0098)

    hostile_boxes = (
        SourceBBox(-0.1, -0.1, 9.7, 9.7),
        SourceBBox(0.0, -0.13, 9.8, 9.6),
        SourceBBox(0.0, -0.12, 9.9, 9.6),
        SourceBBox(-0.1, 0.0, 9.5, 9.8947368),
    )
    for hostile in hostile_boxes:
        with pytest.raises(omission.CanonicalOcrOmissionRefusal):
            omission._filled_path_owner(hostile, [owner])

    overlapping_neighbor = {
        **_cell(
            SourceBBox(9.7, 0.0, 10.0, 10.0),
            text="Y",
            key="b" * 64,
        ),
        "source_closed": False,
        "table_bbox": owner["table_bbox"],
    }
    with pytest.raises(omission.CanonicalOcrOmissionRefusal):
        omission._filled_path_owner(
            SourceBBox(0.0, 0.0, 9.9, 9.6),
            [owner, overlapping_neighbor],
        )
    tiny_neighbor = {
        **_cell(
            SourceBBox(9.7, 0.0, 0.2, 10.0),
            text="tiny",
            key="c" * 64,
        ),
        "source_closed": False,
        "table_bbox": owner["table_bbox"],
    }
    with pytest.raises(omission.CanonicalOcrOmissionRefusal):
        omission._filled_path_owner(
            SourceBBox(0.0, 0.0, 9.8, 9.6),
            [owner, tiny_neighbor],
        )
    monkeypatch.setattr(omission, "MAX_OMISSION_COMPARISONS", 0)
    with pytest.raises(
        omission.CanonicalOcrOmissionRefusal,
        match="comparison limit",
    ):
        omission._filled_path_owner(accepted, [owner])


def test_optional_omission_failure_is_an_identity_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"pages": [], "canonical_presentation": {}}
    summary = {"selections": []}

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise MemoryError

    monkeypatch.setattr(omission, "_apply_transaction", fail)
    projected, projected_summary = (
        omission.apply_source_contradicted_primary_ocr_omissions(
            payload,
            object(),  # type: ignore[arg-type]
            summary,
            object(),  # type: ignore[arg-type]
            {1: [{}]},
            b"pdf",
        )
    )
    assert projected is payload
    assert projected_summary is summary


def test_omission_apply_deadline_is_independently_bounded_at_two_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"pages": [], "canonical_presentation": {}}
    summary = {"selections": []}
    observed_windows: list[float] = []

    def capture(
        raw_payload: Any,
        _ir: Any,
        raw_summary: Any,
        _evidence: Any,
        _representations: Any,
        _source_pdf_bytes: Any,
        *,
        started: float,
        deadline: float,
    ) -> tuple[Any, Any]:
        observed_windows.append(deadline - started)
        return raw_payload, raw_summary

    monkeypatch.setattr(omission, "_apply_transaction", capture)
    assert omission.MAX_OMISSION_SECONDS == 2.0
    projected = omission.apply_source_contradicted_primary_ocr_omissions(
        payload,
        object(),  # type: ignore[arg-type]
        summary,
        object(),  # type: ignore[arg-type]
        {1: [{}]},
        b"pdf",
        timeout_seconds=2.0,
    )
    assert projected == (payload, summary)
    assert observed_windows == pytest.approx([2.0])

    observed_windows.clear()
    projected = omission.apply_source_contradicted_primary_ocr_omissions(
        payload,
        object(),  # type: ignore[arg-type]
        summary,
        object(),  # type: ignore[arg-type]
        {1: [{}]},
        b"pdf",
        timeout_seconds=2.000001,
    )
    assert projected == (payload, summary)
    assert observed_windows == []


def test_validator_closes_processing_summary_and_zero_omission_bijection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = {"selections": [], "elapsed_ms": 1.0}
    empty_view = {"block_ids": [], "markdown": "", "text": ""}
    canonical = {
        "schema_version": "1.0",
        "source_ir_version": "1.0",
        "policy_id": "canonical-presentation-v1",
        "pages": [],
        "full": empty_view,
        "body": empty_view,
        "header": empty_view,
        "footer": empty_view,
    }
    payload = {
        "pages": [],
        "canonical_presentation": canonical,
        "processing": {"source_text_alignment": summary, "engine": "fixture"},
    }
    reference = omission.CanonicalPresentation.model_validate(
        canonical, strict=True
    )
    monkeypatch.setattr(
        omission,
        "build_canonical_presentation",
        lambda _ir: reference,
    )
    assert omission.validate_source_contradicted_primary_ocr_omissions(
        payload,
        object(),  # type: ignore[arg-type]
        summary,
        object(),  # type: ignore[arg-type]
        None,
        None,
    )

    processing_tamper = {
        **payload,
        "processing": {
            **payload["processing"],
            "source_text_alignment": {**summary, "elapsed_ms": 2.0},
        },
    }
    assert not omission.validate_source_contradicted_primary_ocr_omissions(
        processing_tamper,
        object(),  # type: ignore[arg-type]
        summary,
        object(),  # type: ignore[arg-type]
        None,
        None,
    )

    stray = {
        **payload,
        "canonical_presentation": {
            "pages": [
                {
                    "blocks": [
                        {
                            "primary_element_id": "element-stray",
                            "omission_reason": (
                                omission.SOURCE_CONTRADICTED_PRIMARY_OCR_REASON
                            ),
                        }
                    ]
                }
            ]
        },
    }
    assert not omission.validate_source_contradicted_primary_ocr_omissions(
        stray,
        object(),  # type: ignore[arg-type]
        summary,
        object(),  # type: ignore[arg-type]
        None,
        None,
    )


def test_clip_probe_never_destroys_page_owned_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        omission.pdfium_raw,
        "FPDFPageObj_GetClipPath",
        lambda _raw: object(),
    )
    monkeypatch.setattr(
        omission.pdfium_raw,
        "FPDFClipPath_CountPaths",
        lambda _clip: -1,
    )
    destroyed = False

    def destroy(_clip: Any) -> None:
        nonlocal destroyed
        destroyed = True

    monkeypatch.setattr(
        omission.pdfium_raw,
        "FPDF_DestroyClipPath",
        destroy,
    )
    assert omission._clip_is_empty(object())
    assert destroyed is False


def test_pdf_object_enumeration_does_not_close_borrowed_wrapper_before_recursion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeObject:
        def __init__(self, raw: object, bounds: tuple[float, ...]) -> None:
            self.raw = raw
            self._bounds = bounds
            self.closed = False

        def get_bounds(self) -> tuple[float, ...]:
            return self._bounds

        def close(self) -> None:
            self.closed = True
            self.raw = None

    first_raw = object()
    form_raw = object()
    first = FakeObject(first_raw, (50.0, 50.0, 60.0, 60.0))
    nested_form = FakeObject(form_raw, (0.0, 90.0, 10.0, 100.0))
    text_page = SimpleNamespace(close=lambda: None)

    class FakePage:
        raw = object()

        def get_size(self) -> tuple[float, float]:
            return (100.0, 100.0)

        def get_mediabox(self) -> tuple[float, float, float, float]:
            return (0.0, 0.0, 100.0, 100.0)

        def get_cropbox(self) -> tuple[float, float, float, float]:
            return self.get_mediabox()

        def get_textpage(self) -> Any:
            return text_page

        def get_objects(self, **_kwargs: Any) -> Any:
            yield first
            if not first.closed:
                yield nested_form

        def close(self) -> None:
            return None

    page = FakePage()

    class FakeDocument:
        raw = object()

        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> FakePage:
            assert index == 0
            return page

        def close(self) -> None:
            return None

    seen_form = False

    def object_type(raw: object) -> int:
        nonlocal seen_form
        assert raw is form_raw
        seen_form = True
        return omission.pdfium_raw.FPDF_PAGEOBJ_FORM

    monkeypatch.setattr(omission, "_preflight_pdf_names", lambda *_a, **_k: None)
    monkeypatch.setattr(omission.pdfium, "PdfDocument", lambda _data: FakeDocument())
    monkeypatch.setattr(omission.pdfium_raw, "FPDF_GetFormType", lambda _raw: 0)
    monkeypatch.setattr(omission.pdfium_raw, "FPDFPage_GetRotation", lambda _raw: 0)
    monkeypatch.setattr(omission.pdfium_raw, "FPDFPage_GetAnnotCount", lambda _raw: 0)
    monkeypatch.setattr(
        omission.pdfium_raw, "FPDFPage_HasTransparency", lambda _raw: 0
    )
    monkeypatch.setattr(omission, "_object_is_active", lambda _raw: True)
    monkeypatch.setattr(omission.pdfium_raw, "FPDFPageObj_CountMarks", lambda _raw: 0)
    monkeypatch.setattr(omission.pdfium_raw, "FPDFPageObj_GetType", object_type)

    candidate = {
        "page_index": 1,
        "owner_id": "p1-i1",
        "table_id": "table-1",
        "representation_sha256": "a" * 64,
        "crop_bbox": SourceBBox(0.0, 0.0, 10.0, 10.0),
    }
    cell = {
        **_cell(SourceBBox(0.0, 0.0, 10.0, 10.0), text="X", key="cell"),
        "table_id": "table-1",
        "representation_sha256": "a" * 64,
    }
    with pytest.raises(
        omission.CanonicalOcrOmissionRefusal,
        match="unsupported page object",
    ):
        omission._pdf_crop_manifests(
            b"%PDF fake",
            [candidate],
            {1: [cell]},
            {
                1: SimpleNamespace(
                    page_width=100.0,
                    page_height=100.0,
                    characters=(),
                )
            },
            SimpleNamespace(pages=()),
            deadline=time.perf_counter() + 1.0,
        )
    assert first.closed is False
    assert seen_form is True
