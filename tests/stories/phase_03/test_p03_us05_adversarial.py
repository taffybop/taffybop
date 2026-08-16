"""Adversarial boundedness, security, and rollback contracts for P03-US05."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

import pdfplumber
import pytest
from pydantic import ValidationError

from app.services.ir import DocumentIR, build_document_ir
import app.services.text_run_semantics as semantics


PROJECTOR = getattr(semantics, "project_text_run_semantics", None)
requires_projector = pytest.mark.skipif(
    PROJECTOR is None,
    reason="P03-US05 projector has not landed yet",
)

PAGE_WIDTH = 300.0
PAGE_HEIGHT = 300.0


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pdf_literal(value: str) -> bytes:
    return (
        value.encode("latin-1")
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )


def _color_command(
    color: tuple[float, ...],
    *,
    stroke: bool = False,
) -> bytes:
    if len(color) == 1:
        operator = b"G" if stroke else b"g"
    else:
        operator = b"RG" if stroke else b"rg"
    components = " ".join(f"{value:.15g}" for value in color).encode()
    return components + b" " + operator


def _text_command(
    text: str,
    *,
    x: float,
    baseline_y: float,
    font: str = "F1",
    size: float = 12.0,
    color: tuple[float, ...] = (0.0, 0.0, 0.0),
) -> bytes:
    return b"\n".join(
        (
            _color_command(color),
            (
                f"BT /{font} {size:.8g} Tf "
                f"1 0 0 1 {x:.8g} {baseline_y:.8g} Tm ".encode()
                + b"("
                + _pdf_literal(text)
                + b") Tj ET"
            ),
        )
    )


def _rect_command(
    *,
    x: float,
    bottom_y: float,
    width: float,
    height: float,
    color: tuple[float, ...] = (0.0, 0.0, 0.0),
) -> bytes:
    return b"\n".join(
        (
            _color_command(color),
            (
                f"{x:.15g} {bottom_y:.15g} {width:.15g} "
                f"{height:.15g} re f"
            ).encode(),
        )
    )


def _pdf_bytes(
    commands: Iterable[bytes],
    *,
    width: float = PAGE_WIDTH,
    height: float = PAGE_HEIGHT,
    rotation: int = 0,
) -> bytes:
    content = b"\n".join(commands)
    rotate = f" /Rotate {rotation}" if rotation else ""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {width:.8g} {height:.8g}]{rotate} "
            "/Resources << /Font << "
            "/F1 4 0 R /F2 5 0 R /F3 6 0 R "
            ">> >> /Contents 7 0 R >>"
        ).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        (
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        ),
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, payload in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def _first_word_bbox(pdf_bytes: bytes) -> dict[str, float]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        word = document.pages[0].extract_words()[0]
    return {
        "x": float(word["x0"]),
        "y": float(word["top"]),
        "width": float(word["x1"]) - float(word["x0"]),
        "height": float(word["bottom"]) - float(word["top"]),
    }


def _semantic_pdf(
    *,
    text: str = "M",
    ratio: float = 0.50,
    text_color: tuple[float, ...] = (1.0, 0.0, 0.0),
    rule_color: tuple[float, ...] | None = None,
    coverage: float = 1.0,
    thickness: float = 0.60,
    boundary_touch: bool = False,
) -> bytes:
    text_command = _text_command(
        text,
        x=40.0,
        baseline_y=150.0,
        color=text_color,
    )
    text_only = _pdf_bytes((text_command,))
    bbox = _first_word_bbox(text_only)
    center_top = bbox["y"] + ratio * bbox["height"]
    center_pdf_y = PAGE_HEIGHT - center_top
    rule_width = bbox["width"] * coverage
    rule_x = (
        bbox["x"] + bbox["width"]
        if boundary_touch
        else bbox["x"]
    )
    rule = _rect_command(
        x=rule_x,
        bottom_y=center_pdf_y - thickness / 2.0,
        width=rule_width,
        height=thickness,
        color=rule_color or text_color,
    )
    return _pdf_bytes((text_command, rule))


def _box(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    unit: str = "pt",
) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": unit,
    }


def _padded_box(run: Any, padding: float = 1.0) -> dict[str, Any]:
    return _box(
        run.bbox.x - padding,
        run.bbox.y - padding,
        run.bbox.width + 2 * padding,
        run.bbox.height + 2 * padding,
    )


def _item(
    identifier: str,
    *,
    value: Any,
    box: dict[str, Any],
    item_type: str = "text",
    md: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "type": item_type,
        "reading_order": 0,
        "value": value,
        "md": str(value) if md is None else md,
        "bbox": box,
        "source": "native",
        "confidence": 0.99,
        **extra,
    }


def _document(
    pdf_bytes: bytes,
    items: list[dict[str, Any]],
    *,
    page_width: float = PAGE_WIDTH,
    page_height: float = PAGE_HEIGHT,
) -> dict[str, Any]:
    ordered = []
    for reading_order, item in enumerate(items):
        copied = deepcopy(item)
        copied["reading_order"] = reading_order
        ordered.append(copied)
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "p03-us05-synthetic.pdf",
            "mime_type": "application/pdf",
            "sha256": _sha256(pdf_bytes),
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": page_width,
                "page_height": page_height,
                "unit": "pt",
                "success": True,
                "items": ordered,
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _legacy_item(element: Any) -> dict[str, Any]:
    item = element.properties.get("legacy_item")
    assert isinstance(item, dict)
    return item


def _element_by_public_id(ir: DocumentIR, public_id: str) -> Any:
    matches = [
        element
        for element in ir.elements
        if isinstance(element.properties.get("legacy_item"), dict)
        and element.properties["legacy_item"].get("id") == public_id
    ]
    assert len(matches) == 1
    return matches[0]


def _only_source_run(report: Any, text: str) -> Any:
    matches = [run for run in report.runs if run.text == text]
    assert len(matches) == 1
    return matches[0]


def _semantic_payload(report: Any) -> dict[str, Any]:
    payload = report.model_dump(mode="json")
    payload.pop("elapsed_ms", None)
    return payload


def test_extraction_is_deterministic_and_purchase_denominator_is_exact() -> None:
    workspace = Path(__file__).resolve().parents[3]
    pdf_bytes = (
        workspace
        / "benchmark-expertmodeldata"
        / "purchase-agreement.pdf"
    ).read_bytes()

    first = semantics.extract_text_run_evidence(pdf_bytes, max_pages=1)
    second = semantics.extract_text_run_evidence(pdf_bytes, max_pages=1)
    assert first.usable is True
    assert _semantic_payload(first) == _semantic_payload(second)
    assert first.character_count == 3_338
    assert len(first.rules) == 13

    deleted = [run for run in first.runs if run.change_state == "deleted"]
    assert len({run.change_group_id for run in deleted}) == 6
    assert len(
        {
            (run.change_group_id, rule_id)
            for run in deleted
            for rule_id in run.rule_ids
        }
    ) == 7
    assert sum(len(run.rule_ids) for run in deleted) == 9
    assert len(_only_source_run(first, "EXECUTION VERSION").rule_ids) == 2
    assert len(_only_source_run(first, "_______").rule_ids) == 2

    june = _only_source_run(first, "June")
    following_bracket = [
        run
        for run in first.runs
        if run.page_index == 1
        and run.bbox.x > june.bbox.x
        and run.text.startswith("[")
    ]
    assert following_bracket == []
    assert set(_only_source_run(first, "23").rule_ids).isdisjoint(
        _only_source_run(first, "_______").rule_ids
    )


@pytest.mark.parametrize(
    ("width", "thickness", "expected"),
    [
        (1.999, 0.5, 0),
        (2.0, 0.5, 1),
        (4.499, 1.5, 0),
        (4.5, 1.5, 1),
        (10.0, 1.5001, 0),
    ],
)
def test_candidate_rule_thresholds_are_inclusive(
    width: float,
    thickness: float,
    expected: int,
) -> None:
    pdf_bytes = _pdf_bytes(
        (
            _rect_command(
                x=20.0,
                bottom_y=100.0,
                width=width,
                height=thickness,
            ),
        )
    )
    report = semantics.extract_text_run_evidence(pdf_bytes, max_pages=1)
    assert report.usable is True
    assert report.candidate_rule_count == expected
    assert len(report.rules) == expected


@pytest.mark.parametrize(
    ("ratio", "expected_decoration"),
    [
        (0.3499, None),
        (0.35, "strikethrough"),
        (0.70, "strikethrough"),
        (0.7001, None),
        (0.7499, None),
        (0.75, "underline"),
        (1.10, "underline"),
        (1.1001, None),
    ],
)
def test_vertical_bands_are_inclusive_and_fail_closed_outside(
    ratio: float,
    expected_decoration: str | None,
) -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(ratio=ratio),
        max_pages=1,
    )
    assert report.usable is True
    run = _only_source_run(report, "M")
    if expected_decoration is None:
        assert run.rule_ids == ()
        assert run.decorations == ()
        assert run.change_state == "unknown"
    else:
        assert run.decorations == (expected_decoration,)
        assert len(run.rule_ids) == 1
        assert run.change_state == (
            "deleted" if expected_decoration == "strikethrough"
            else "unchanged"
        )


@pytest.mark.parametrize(
    ("rule_red", "expected_match"),
    [
        (1.0 - semantics.MAX_COLOR_COMPONENT_DELTA, True),
        (1.0 - semantics.MAX_COLOR_COMPONENT_DELTA - 0.0001, False),
    ],
)
def test_color_delta_threshold_is_inclusive(
    rule_red: float,
    expected_match: bool,
) -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(rule_color=(rule_red, 0.0, 0.0)),
        max_pages=1,
    )
    run = _only_source_run(report, "M")
    assert bool(run.rule_ids) is expected_match
    assert (run.change_state == "deleted") is expected_match


@pytest.mark.parametrize(
    ("coverage", "expected_match"),
    [
        (0.7999, False),
        (0.80, True),
        (0.8001, True),
    ],
)
def test_horizontal_coverage_threshold_and_boundary_touch(
    coverage: float,
    expected_match: bool,
) -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(coverage=coverage),
        max_pages=1,
    )
    run = _only_source_run(report, "M")
    assert bool(run.rule_ids) is expected_match

    touching = semantics.extract_text_run_evidence(
        _semantic_pdf(coverage=coverage, boundary_touch=True),
        max_pages=1,
    )
    assert _only_source_run(touching, "M").rule_ids == ()


def test_incompatible_color_spaces_never_associate() -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(
            text_color=(0.0,),
            rule_color=(0.0, 0.0, 0.0),
        ),
        max_pages=1,
    )
    assert report.usable is True
    assert report.runs == ()


def test_whitespace_spatial_line_splits_and_rotation_are_explicit() -> None:
    commands = (
        _text_command(
            "Alpha   Beta",
            x=20.0,
            baseline_y=260.0,
            font="F2",
        ),
        _text_command(
            "Far",
            x=20.0,
            baseline_y=210.0,
            font="F2",
        ),
        _text_command(
            "Apart",
            x=120.0,
            baseline_y=210.0,
            font="F2",
        ),
        _text_command(
            "NextLine",
            x=20.0,
            baseline_y=160.0,
            font="F2",
        ),
    )
    report = semantics.extract_text_run_evidence(
        _pdf_bytes(commands),
        max_pages=1,
    )
    assert report.usable is True
    texts = [run.text for run in report.runs]
    assert "Alpha   Beta" in texts
    assert "Far" in texts
    assert "Apart" in texts
    assert "NextLine" in texts

    rotated = semantics.extract_text_run_evidence(
        _pdf_bytes(commands[:1], rotation=90),
        max_pages=1,
    )
    assert rotated.usable is True
    assert len(rotated.pages) == 1
    assert rotated.pages[0].status == "unavailable"
    assert rotated.pages[0].run_ids == ()
    assert rotated.runs == ()


def test_x_backtracking_splits_without_cross_source_merging() -> None:
    report = semantics.extract_text_run_evidence(
        _pdf_bytes(
            (
                _text_command(
                    "WideWord",
                    x=20.0,
                    baseline_y=160.0,
                    font="F2",
                ),
                _text_command(
                    "Overlap",
                    x=25.0,
                    baseline_y=160.0,
                    font="F2",
                ),
            )
        ),
        max_pages=1,
    )
    assert report.usable is True
    covered_indexes: list[int] = []
    for run in report.runs:
        indexes = run.source_character_indexes
        assert indexes == tuple(range(indexes[0], indexes[-1] + 1))
        assert (
            set(indexes).issubset(range(8))
            or set(indexes).issubset(range(8, 15))
        )
        assert run.rule_ids == ()
        assert run.change_group_id is None
        covered_indexes.extend(indexes)

    assert sorted(covered_indexes) == list(range(15))
    assert len(set(covered_indexes)) == 15
    assert "".join(
        run.text
        for run in sorted(
            report.runs,
            key=lambda value: value.source_character_indexes[0],
        )
    ) == "WideWordOverlap"


def test_rule_per_run_exact_max_and_max_plus_one() -> None:
    text_command = _text_command(
        "M",
        x=40.0,
        baseline_y=150.0,
        color=(1.0, 0.0, 0.0),
    )
    text_only = _pdf_bytes((text_command,))
    bbox = _first_word_bbox(text_only)

    def fixture(count: int) -> bytes:
        rules = []
        for index in range(count):
            ratio = 0.36 + 0.32 * index / max(count - 1, 1)
            center_top = bbox["y"] + ratio * bbox["height"]
            center_pdf_y = PAGE_HEIGHT - center_top
            rules.append(
                _rect_command(
                    x=bbox["x"],
                    bottom_y=center_pdf_y - 0.005,
                    width=bbox["width"],
                    height=0.01,
                    color=(1.0, 0.0, 0.0),
                )
            )
        return _pdf_bytes((text_command, *rules))

    exact = semantics.extract_text_run_evidence(
        fixture(semantics.MAX_RULES_PER_RUN),
        max_pages=1,
    )
    assert exact.usable is True
    assert len(_only_source_run(exact, "M").rule_ids) == (
        semantics.MAX_RULES_PER_RUN
    )

    overflow = semantics.extract_text_run_evidence(
        fixture(semantics.MAX_RULES_PER_RUN + 1),
        max_pages=1,
    )
    assert overflow.usable is True
    assert overflow.refusal_code is None
    assert overflow.runs == ()
    assert overflow.rules == ()
    assert overflow.pages[0].status == "unavailable"
    assert overflow.pages[0].concern_code == "text_run_rule_limit"
    assert overflow.concerns == ()


def test_rule_page_limit_exact_max_and_max_plus_one() -> None:
    def fixture(count: int) -> bytes:
        command = _rect_command(
            x=20.0,
            bottom_y=100.0,
            width=2.0,
            height=0.5,
        )
        return _pdf_bytes([command] * count)

    exact = semantics.extract_text_run_evidence(
        fixture(semantics.MAX_RULES_PER_PAGE),
        max_pages=1,
    )
    assert exact.usable is True
    assert len(exact.rules) == semantics.MAX_RULES_PER_PAGE

    overflow = semantics.extract_text_run_evidence(
        fixture(semantics.MAX_RULES_PER_PAGE + 1),
        max_pages=1,
    )
    assert overflow.usable is True
    assert overflow.refusal_code is None
    assert overflow.rules == ()
    assert overflow.pages[0].status == "unavailable"
    assert overflow.pages[0].concern_code == "text_run_rule_limit"
    assert overflow.concerns == ()


@pytest.mark.parametrize("max_pages", [0, 101, True])
def test_invalid_page_limits_and_malformed_input_are_sanitized(
    max_pages: int,
) -> None:
    report = semantics.extract_text_run_evidence(
        b"%PDF-1.4\nmalformed SECRET_DOCUMENT_TEXT",
        max_pages=max_pages,
    )
    assert report.usable is False
    assert report.refusal_code in {
        "text_run_source_invalid",
        "text_run_source_limit",
    }
    serialized = json.dumps(report.concerns, sort_keys=True)
    assert "SECRET_DOCUMENT_TEXT" not in serialized


def test_strict_report_rejects_dangling_and_duplicate_rule_ids() -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(),
        max_pages=1,
    )
    payload = report.model_dump(mode="json")
    payload["rules"] = []
    with pytest.raises(ValidationError, match="dangling rule"):
        semantics.TextRunEvidence.model_validate(payload)

    payload = report.model_dump(mode="json")
    payload["rules"].append(deepcopy(payload["rules"][0]))
    with pytest.raises(ValidationError, match="repeats a rule ID"):
        semantics.TextRunEvidence.model_validate(payload)


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ("run", "run on an undeclared page"),
        ("rule", "rule on an undeclared page"),
    ],
)
def test_strict_report_rejects_records_on_undeclared_pages(
    record: str,
    expected: str,
) -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(),
        max_pages=1,
    )
    payload = report.model_dump(mode="json")
    payload[f"{record}s"][0]["page_index"] = 2
    with pytest.raises(ValidationError, match=expected):
        semantics.TextRunEvidence.model_validate(payload)


def test_strict_report_rejects_cross_page_links_and_out_of_page_bboxes() -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(),
        max_pages=1,
    )
    cross_page = report.model_dump(mode="json")
    rule_id = cross_page["rules"][0]["id"]
    second_page = deepcopy(cross_page["pages"][0])
    second_page.update(
        {
            "page_index": 2,
            "run_ids": [],
            "rule_ids": [rule_id],
        }
    )
    cross_page["page_count"] = 2
    cross_page["pages"][0]["rule_ids"] = []
    cross_page["pages"].append(second_page)
    cross_page["rules"][0]["page_index"] = 2
    with pytest.raises(ValidationError, match="cross-page rule link"):
        semantics.TextRunEvidence.model_validate(cross_page)

    outside = report.model_dump(mode="json")
    outside["runs"][0]["bbox"]["x"] = outside["pages"][0]["page_width"]
    with pytest.raises(ValidationError, match="out-of-page run bbox"):
        semantics.TextRunEvidence.model_validate(outside)

    outside = report.model_dump(mode="json")
    outside["rules"][0]["bbox"]["y"] = outside["pages"][0]["page_height"]
    with pytest.raises(ValidationError, match="out-of-page rule bbox"):
        semantics.TextRunEvidence.model_validate(outside)


def test_strict_report_binds_source_character_custody() -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(),
        max_pages=1,
    )

    outside = report.model_dump(mode="json")
    outside["runs"][0]["source_character_indexes"][-1] = outside[
        "character_count"
    ]
    with pytest.raises(ValidationError, match="source-character custody"):
        semantics.TextRunEvidence.model_validate(outside)

    duplicate = report.model_dump(mode="json")
    copied = deepcopy(duplicate["runs"][0])
    copied["id"] = "duplicate-source-custody"
    duplicate["runs"].append(copied)
    duplicate["pages"][0]["run_ids"].append(copied["id"])
    with pytest.raises(ValidationError, match="source-character custody"):
        semantics.TextRunEvidence.model_validate(duplicate)


def test_strict_report_enforces_serialized_byte_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(),
        max_pages=1,
    )
    payload = report.model_dump(mode="json")
    monkeypatch.setattr(semantics, "MAX_REPORT_BYTES", 1)

    with pytest.raises(ValidationError, match="byte limit"):
        semantics.TextRunEvidence.model_validate(payload)


def test_source_run_semantics_and_rule_order_are_coherent() -> None:
    report = semantics.extract_text_run_evidence(
        _semantic_pdf(),
        max_pages=1,
    )
    base = report.model_dump(mode="json")

    inconsistent = deepcopy(base)
    inconsistent["runs"][0]["change_state"] = "replacement"
    with pytest.raises(ValidationError, match="midline-rule run"):
        semantics.TextRunEvidence.model_validate(inconsistent)

    inconsistent = deepcopy(base)
    inconsistent["runs"][0]["placeholder"] = True
    with pytest.raises(ValidationError, match="midline-rule run"):
        semantics.TextRunEvidence.model_validate(inconsistent)

    inconsistent = deepcopy(base)
    inconsistent["runs"][0]["decorations"] = [
        "strikethrough",
        "underline",
    ]
    with pytest.raises(ValidationError, match="midline-rule run"):
        semantics.TextRunEvidence.model_validate(inconsistent)

    source_style = deepcopy(base)
    source_style["runs"][0].update(
        {
            "change_group_id": None,
            "change_state": "unknown",
            "decorations": [],
            "rule_ids": [],
            "semantic_derivation": "source_style",
        }
    )
    assert semantics.TextRunEvidence.model_validate(source_style).runs
    source_style["runs"][0]["change_state"] = "unchanged"
    with pytest.raises(ValidationError, match="source-style"):
        semantics.TextRunEvidence.model_validate(source_style)

    inconsistent = deepcopy(base)
    inconsistent["rules"][0]["color"]["components"] = [0.0, 0.0, 1.0]
    with pytest.raises(ValidationError, match="incompatible linked colors"):
        semantics.TextRunEvidence.model_validate(inconsistent)

    out_of_order = deepcopy(base)
    second_rule = deepcopy(out_of_order["rules"][0])
    second_rule["id"] = "rule-sorted-after"
    second_rule["source_object_index"] += 1
    second_rule["bbox"]["y"] += 0.1
    out_of_order["rules"].append(second_rule)
    out_of_order["candidate_rule_count"] = 2
    out_of_order["pages"][0]["rule_ids"].append(second_rule["id"])
    out_of_order["runs"][0]["rule_ids"] = [
        second_rule["id"],
        out_of_order["rules"][0]["id"],
    ]
    with pytest.raises(ValidationError, match="canonical bbox order"):
        semantics.TextRunEvidence.model_validate(out_of_order)


def test_source_page_caps_and_change_group_adjacency_are_validated() -> None:
    with pytest.raises(ValidationError, match="run limit"):
        semantics.SourceSemanticsPage.model_validate(
            {
                "page_index": 1,
                "page_width": PAGE_WIDTH,
                "page_height": PAGE_HEIGHT,
                "status": "projectable",
                "run_ids": [
                    f"run-{index}"
                    for index in range(semantics.MAX_RUNS_PER_PAGE + 1)
                ],
            }
        )

    workspace = Path(__file__).resolve().parents[3]
    report = semantics.extract_text_run_evidence(
        (
            workspace
            / "benchmark-expertmodeldata"
            / "purchase-agreement.pdf"
        ).read_bytes(),
        max_pages=1,
    )
    payload = report.model_dump(mode="json")
    group_counts: dict[str, int] = {}
    for run in payload["runs"]:
        group_id = run.get("change_group_id")
        if isinstance(group_id, str):
            group_counts[group_id] = group_counts.get(group_id, 0) + 1
    [multi_run_group_id] = [
        group_id for group_id, count in group_counts.items() if count == 4
    ]
    grouped = [
        run
        for run in payload["runs"]
        if run.get("change_group_id") == multi_run_group_id
    ]
    assert len(grouped) == 4
    target = next(
        run for run in payload["runs"] if run["id"] == grouped[1]["id"]
    )
    target["source_character_indexes"] = target[
        "source_character_indexes"
    ][1:]
    with pytest.raises(ValidationError, match="change group.*not adjacent"):
        semantics.TextRunEvidence.model_validate(payload)


def test_report_diagnostics_are_allowlisted_bounded_and_content_free() -> None:
    refused = semantics.extract_text_run_evidence(
        b"%PDF-1.4\nmalformed",
        max_pages=1,
    ).model_dump(mode="json")
    refused["concerns"][0]["source_text"] = "sensitive"
    with pytest.raises(ValidationError, match="content-free fixed concern"):
        semantics.TextRunEvidence.model_validate(refused)

    refused = semantics.extract_text_run_evidence(
        b"%PDF-1.4\nmalformed",
        max_pages=1,
    ).model_dump(mode="json")
    refused["refusal_code"] = "arbitrary_error"
    with pytest.raises(ValidationError):
        semantics.TextRunEvidence.model_validate(refused)

    usable = semantics.extract_text_run_evidence(
        _semantic_pdf(),
        max_pages=1,
    ).model_dump(mode="json")
    usable["concerns"] = [
        {
            "code": "text_run_source_invalid",
            "policy_id": semantics.TEXT_RUN_POLICY_ID,
        }
    ]
    with pytest.raises(ValidationError, match="usable evidence"):
        semantics.TextRunEvidence.model_validate(usable)


@requires_projector
def test_scalar_table_cell_and_nested_target_paths_are_exact() -> None:
    pdf_bytes = _pdf_bytes(
        (
            _text_command(
                "OwnerStyle",
                x=30.0,
                baseline_y=250.0,
                font="F2",
            ),
            _text_command(
                "CellStyle",
                x=30.0,
                baseline_y=180.0,
                font="F2",
            ),
            _text_command(
                "NestedStyle",
                x=30.0,
                baseline_y=110.0,
                font="F2",
            ),
        )
    )
    report = semantics.extract_text_run_evidence(pdf_bytes, max_pages=1)
    owner_run = _only_source_run(report, "OwnerStyle")
    cell_run = _only_source_run(report, "CellStyle")
    nested_run = _only_source_run(report, "NestedStyle")
    items = [
        _item(
            "owner",
            value="OwnerStyle",
            box=_padded_box(owner_run),
        ),
        _item(
            "table",
            item_type="table",
            value=[["CellStyle"]],
            md="<table><tr><td>CellStyle</td></tr></table>",
            box=_box(20.0, 100.0, 160.0, 40.0),
            rows=[["CellStyle"]],
            cells=[
                {
                    "row": 0,
                    "column": 0,
                    "row_span": 1,
                    "col_span": 1,
                    "text": "CellStyle",
                    "bbox": _padded_box(cell_run),
                }
            ],
        ),
        _item(
            "nested-owner",
            value="visual container",
            box=_box(20.0, 170.0, 160.0, 50.0),
            items=[
                {
                    "text": "NestedStyle",
                    "bbox": _padded_box(nested_run),
                }
            ],
        ),
    ]
    predecessor = build_document_ir(_document(pdf_bytes, items))
    before = predecessor.model_dump(mode="json")
    projected = PROJECTOR(predecessor, report)
    assert predecessor.model_dump(mode="json") == before
    assert projected is not predecessor

    paths = {
        run.text: tuple(run.target_path) for run in projected.text_runs
    }
    assert paths == {
        "OwnerStyle": ("value",),
        "CellStyle": ("cells", 0, "text"),
        "NestedStyle": ("items", 0, "text"),
    }
    for run in projected.text_runs:
        target = {
            "OwnerStyle": "OwnerStyle",
            "CellStyle": "CellStyle",
            "NestedStyle": "NestedStyle",
        }[run.text]
        assert target[run.start : run.end] == run.text
        assert run.target_text_sha256 == _sha256(target.encode())


@requires_projector
def test_markup_injection_is_escaped_and_heading_envelope_is_preserved() -> None:
    source_text = r"~~<script>alert(1)</script>_[x]\\"
    text_command = _text_command(
        source_text,
        x=20.0,
        baseline_y=150.0,
        color=(1.0, 0.0, 0.0),
    )
    text_only = _pdf_bytes((text_command,))
    bbox = _first_word_bbox(text_only)
    center_top = bbox["y"] + 0.5 * bbox["height"]
    pdf_bytes = _pdf_bytes(
        (
            text_command,
            _rect_command(
                x=bbox["x"],
                bottom_y=PAGE_HEIGHT - center_top - 0.3,
                width=bbox["width"],
                height=0.6,
                color=(1.0, 0.0, 0.0),
            ),
        )
    )
    report = semantics.extract_text_run_evidence(pdf_bytes, max_pages=1)
    run = _only_source_run(report, source_text)
    predecessor = build_document_ir(
        _document(
            pdf_bytes,
            [
                _item(
                    "heading",
                    item_type="heading",
                    value=source_text,
                    md=f"# {source_text}",
                    box=_padded_box(run),
                    level=1,
                )
            ],
        )
    )
    projected = PROJECTOR(predecessor, report)
    item = _legacy_item(_element_by_public_id(projected, "heading"))
    assert item["value"] == source_text
    assert item["md"].startswith("# ~~")
    assert item["redline_markdown"] == item["md"]
    assert "<script>" not in item["md"]
    assert "&lt;script&gt;" in item["md"]
    assert r"\[" in item["md"]
    assert r"\]" in item["md"]
    assert item["md"].count("# ") == 1
    assert item["active_text"] == ""


@requires_projector
def test_complete_deleted_top_right_revision_banner_is_demoted() -> None:
    source_text = "Draft"
    text_command = _text_command(
        source_text,
        x=225.0,
        baseline_y=276.0,
        color=(1.0, 0.0, 0.0),
    )
    text_only = _pdf_bytes((text_command,))
    bbox = _first_word_bbox(text_only)
    center_top = bbox["y"] + 0.5 * bbox["height"]
    pdf_bytes = _pdf_bytes(
        (
            text_command,
            _rect_command(
                x=bbox["x"],
                bottom_y=PAGE_HEIGHT - center_top - 0.3,
                width=bbox["width"],
                height=0.6,
                color=(1.0, 0.0, 0.0),
            ),
        )
    )
    report = semantics.extract_text_run_evidence(pdf_bytes, max_pages=1)
    run = _only_source_run(report, source_text)
    predecessor = build_document_ir(
        _document(
            pdf_bytes,
            [
                _item(
                    "banner",
                    item_type="heading",
                    value=source_text,
                    md=f"# {source_text}",
                    box=_padded_box(run),
                    label="section_header",
                    level=1,
                )
            ],
        )
    )

    projected = PROJECTOR(predecessor, report)
    item = _legacy_item(_element_by_public_id(projected, "banner"))
    assert item["type"] == "text"
    assert "level" not in item
    assert item["md"] == "~~Draft~~"
    assert item["active_text"] == ""


@requires_projector
def test_ambiguous_targets_and_source_mismatch_roll_back_without_mutation() -> None:
    pdf_bytes = _pdf_bytes(
        (
            _text_command(
                "Ambiguous",
                x=30.0,
                baseline_y=150.0,
                font="F2",
            ),
        )
    )
    report = semantics.extract_text_run_evidence(pdf_bytes, max_pages=1)
    run = _only_source_run(report, "Ambiguous")
    shared_box = _padded_box(run)
    predecessor = build_document_ir(
        _document(
            pdf_bytes,
            [
                _item("first", value="Ambiguous", box=shared_box),
                _item("second", value="Ambiguous", box=shared_box),
            ],
        )
    )
    before = predecessor.model_dump(mode="json")
    projected = PROJECTOR(predecessor, report)
    assert predecessor.model_dump(mode="json") == before
    assert projected.text_runs == []
    assert projected.text_rules == []
    assert [
        _legacy_item(element)
        for element in projected.elements
    ] == [
        _legacy_item(element)
        for element in predecessor.elements
    ]
    assert any(
        concern.code == "text_run_alignment_ambiguous"
        for concern in projected.concerns
    )

    other_pdf = _pdf_bytes(
        (
            _text_command(
                "Different",
                x=30.0,
                baseline_y=150.0,
                font="F2",
            ),
        )
    )
    mismatch = semantics.extract_text_run_evidence(other_pdf, max_pages=1)
    mismatch_projection = PROJECTOR(predecessor, mismatch)
    assert mismatch_projection.text_runs == []
    assert mismatch_projection.text_rules == []
    assert all(
        "Ambiguous" not in json.dumps(
            concern.model_dump(mode="json"),
            sort_keys=True,
        )
        for concern in mismatch_projection.concerns
    )


@requires_projector
def test_projection_is_idempotent_and_does_not_double_wrap() -> None:
    pdf_bytes = _semantic_pdf(text="DeleteMe")
    report = semantics.extract_text_run_evidence(pdf_bytes, max_pages=1)
    run = _only_source_run(report, "DeleteMe")
    predecessor = build_document_ir(
        _document(
            pdf_bytes,
            [
                _item(
                    "target",
                    value="DeleteMe",
                    box=_padded_box(run),
                )
            ],
        )
    )
    first = PROJECTOR(predecessor, report)
    second = PROJECTOR(first, report)
    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    item = _legacy_item(_element_by_public_id(second, "target"))
    assert item["md"] == r"~~DeleteMe~~"
    assert item["md"].count("~~") == 2
