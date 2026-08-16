from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


WORKSPACE = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "tools"
    / "functional_fidelity.py"
)
SPEC = importlib.util.spec_from_file_location("functional_fidelity", MODULE_PATH)
assert SPEC and SPEC.loader
functional_fidelity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = functional_fidelity
SPEC.loader.exec_module(functional_fidelity)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _item(item_type: str, value: str, *, md: str | None = None) -> dict[str, object]:
    return {
        "type": item_type,
        "value": value,
        "md": value if md is None else md,
        "bbox": {"x": 1, "y": 1, "w": 10, "h": 10},
        "source": "native",
    }


def _reference_json(items: list[dict[str, object]], markdown: str) -> dict[str, object]:
    return {
        "markdown": {"pages": [{"page_number": 1, "markdown": markdown}]},
        "items": {
            "pages": [
                {
                    "page_number": 1,
                    "page_width": 100,
                    "page_height": 100,
                    "items": items,
                }
            ]
        },
    }


def _candidate_json(items: list[dict[str, object]]) -> dict[str, object]:
    for index, item in enumerate(items):
        item.setdefault("reading_order", index)
    return {
        "pages": [
            {
                "page_number": 1,
                "page_width": 100,
                "page_height": 100,
                "items": items,
            }
        ]
    }


def _dom(page: int, body: str) -> dict[str, object]:
    return {
        "page_number": page,
        "html": f'<div class="markdown-container">{body}</div>',
        "text": functional_fidelity._html_visible_text(body),
    }


def _write_case(
    run: Path,
    case_id: str,
    *,
    reference_md: str,
    candidate_md: str,
    reference_items: list[dict[str, object]],
    candidate_items: list[dict[str, object]],
    reference_dom: str = "<h1>Title</h1><p>Body</p>",
    candidate_dom: str = "<h1>Title</h1><p>Body</p>",
) -> None:
    reference = run / "llamaparse" / case_id
    candidate = run / "service" / case_id
    reference.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    (reference / "reference.md").write_text(reference_md, encoding="utf-8")
    (candidate / "response.md").write_text(candidate_md, encoding="utf-8")
    _write_json(reference / "reference.json", _reference_json(reference_items, reference_md))
    _write_json(candidate / "response.json", _candidate_json(candidate_items))
    _write_json(reference / "pages/page-1/rendered-dom.json", _dom(1, reference_dom))
    _write_json(candidate / "pages/page-1/rendered-dom.json", _dom(1, candidate_dom))


def _story_matrix(path: Path) -> Path:
    path.write_text(
        "| Gap | Primary story | Secondary stories | Story action | Dedicated test anchor | Milestone |\n"
        "|---|---|---|---|---|---|\n"
        "| GAP-TEXT-001 | P02-US04 | P02-US03 | Existing | `test_text.py` | M1 |\n"
        "| GAP-TABLE-002 | P04-US01 | P04-US02 | Existing | `test_table.py` | M3 |\n"
        "| GAP-TABLE-003 | P01-US03 | P01-US04 | Existing | `test_present.py` | M3 |\n"
        "| GAP-SERIALIZATION-001 | P01-US03 | P01-US04 | Existing | `test_json.py` | M3 |\n"
        "| GAP-BENCHMARK-002 | P00-US10 | P00-US03 | Existing | `test_runner.py` | M0 |\n"
        "| GAP-BBOX-001 | P01-US01 | P01-US02 | Existing | `test_bbox.py` | M1 |\n"
        "| GAP-PROVENANCE-001 | P01-US01 | P01-US02 | Existing | `test_prov.py` | M1 |\n",
        encoding="utf-8",
    )
    return path


def test_markdown_profile_preserves_hierarchy_links_tables_and_whitespace() -> None:
    markdown = (
        "# Heading\r\n\r\n"
        "1. Parent\r\n"
        "  - Child\r\n\r\n"
        "[docs](https://example.test) and **bold**  \r\n"
        "next\r\n\r\n"
        "| A | B |\r\n|---|---|\r\n| x | y |\r\n"
    )

    profile = functional_fidelity.markdown_profile(markdown)

    assert profile["headings"] == [{"level": 1, "text": "Heading", "line": 1}]
    assert [(row["ordered"], row["level"]) for row in profile["list_items"]] == [
        (True, 0),
        (False, 1),
    ]
    assert profile["links"] == [
        {"kind": "link", "text": "docs", "target": "https://example.test"}
    ]
    assert profile["tables"][0]["matrix"] == [["A", "B"], ["x", "y"]]
    assert profile["whitespace"]["line_ending"] == "crlf"
    assert profile["feature_counts"]["hard_break_lines"] == 1


def test_html_table_projection_expands_rowspan_and_colspan() -> None:
    html = (
        "<table><thead><tr><th rowspan='2'>A</th><th colspan='2'>B</th></tr>"
        "<tr><th>C</th><th>D</th></tr></thead>"
        "<tbody><tr><td>x</td><td>y</td><td>z</td></tr></tbody></table>"
    )

    table = functional_fidelity._html_tables(html)[0]

    assert table.matrix == [["A", "B", "B"], ["A", "C", "D"], ["x", "y", "z"]]
    assert table.header_row_count == 2
    assert table.spans == [
        {"row": 0, "column": 0, "rowspan": 2, "colspan": 1, "header": True, "text": "A"},
        {"row": 0, "column": 1, "rowspan": 1, "colspan": 2, "header": True, "text": "B"},
    ]


def test_case_evidence_records_exact_table_cell_and_story_owner(tmp_path: Path) -> None:
    run = tmp_path / "run"
    table_reference = {
        **_item("table", "A B x y"),
        "rows": [["A", "B"], ["x", "y"]],
        "html": "<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>x</td><td>y</td></tr></tbody></table>",
    }
    table_candidate = {
        **_item("table", "A B x WRONG"),
        "rows": [["A", "B"], ["x", "WRONG"]],
        "html": "<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>x</td><td>WRONG</td></tr></tbody></table>",
    }
    _write_case(
        run,
        "case-a",
        reference_md="# Title\n\n<table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></table>",
        candidate_md="# Title\n\n<table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>WRONG</td></tr></table>",
        reference_items=[_item("heading", "Title", md="# Title"), table_reference],
        candidate_items=[_item("heading", "Title", md="# Title"), table_candidate],
        reference_dom="<h1>Title</h1><table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></table>",
        candidate_dom="<h1>Title</h1><table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>WRONG</td></tr></table>",
    )
    matrix = _story_matrix(tmp_path / "matrix.md")

    result = functional_fidelity.analyze_case(
        run,
        "case-a",
        stories=functional_fidelity.parse_story_matrix(matrix),
    )

    assert result["status"] == "discrepancy_found"
    table_issues = [row for row in result["discrepancies"] if row["category"] == "table_fidelity"]
    assert len(table_issues) == 1
    assert table_issues[0]["pages"] == [1]
    assert table_issues[0]["story"]["primary_story"] == "P04-US01"
    assert table_issues[0]["evidence"]["cell_differences"] == [
        {"row": 2, "column": 2, "expected": "y", "actual": "WRONG"}
    ]


def test_run_with_missing_service_artifacts_is_pending_not_match(tmp_path: Path) -> None:
    run = tmp_path / "run"
    reference = run / "llamaparse" / "case-a"
    reference.mkdir(parents=True)
    (reference / "reference.md").write_text("hello", encoding="utf-8")
    _write_json(reference / "reference.json", _reference_json([_item("text", "hello")], "hello"))
    _write_json(reference / "pages/page-1/rendered-dom.json", _dom(1, "<p>hello</p>"))
    matrix = _story_matrix(tmp_path / "matrix.md")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"cases": [{"case_id": "case-a", "source": {"page_count": 1}}]})

    summary = functional_fidelity.analyze_run(
        run,
        manifest_path=manifest,
        matrix_path=matrix,
        write=False,
    )

    assert summary["release_ready"] is False
    assert summary["status_counts"]["pending"] == 1
    assert summary["cases"][0]["summary"]["evidence_gaps"] >= 1


def test_semantic_match_with_raw_whitespace_difference_is_harmless(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_case(
        run,
        "case-a",
        reference_md="# Title\n\nBody\n",
        candidate_md="# Title\r\n\r\nBody",
        reference_items=[_item("heading", "Title", md="# Title"), _item("text", "Body")],
        candidate_items=[_item("heading", "Title", md="# Title"), _item("text", "Body")],
    )
    matrix = _story_matrix(tmp_path / "matrix.md")

    result = functional_fidelity.analyze_case(
        run,
        "case-a",
        stories=functional_fidelity.parse_story_matrix(matrix),
    )

    harmless = [row for row in result["discrepancies"] if row["classification"] == "harmless_formatting"]
    assert harmless
    assert result["status"] == "acceptable_difference"


def test_output_cannot_overwrite_parser_artifact_roots(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "llamaparse").mkdir(parents=True)
    (run / "service").mkdir()
    manifest = tmp_path / "manifest.json"
    matrix = _story_matrix(tmp_path / "matrix.md")
    _write_json(manifest, {"cases": []})

    with pytest.raises(ValueError, match="immutable parser artifact roots"):
        functional_fidelity.analyze_run(
            run,
            output_dir=run / "service" / "comparison",
            manifest_path=manifest,
            matrix_path=matrix,
            write=False,
        )


def test_rendered_dom_tag_order_difference_is_page_specific(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_case(
        run,
        "case-a",
        reference_md="# Title\n\nBody",
        candidate_md="# Title\n\nBody",
        reference_items=[_item("heading", "Title", md="# Title"), _item("text", "Body")],
        candidate_items=[_item("heading", "Title", md="# Title"), _item("text", "Body")],
        reference_dom="<h1>Title</h1><p>Body</p>",
        candidate_dom="<p>Title</p><h1>Body</h1>",
    )
    matrix = _story_matrix(tmp_path / "matrix.md")

    result = functional_fidelity.analyze_case(
        run,
        "case-a",
        stories=functional_fidelity.parse_story_matrix(matrix),
    )

    dom_issues = [
        row
        for row in result["discrepancies"]
        if row["output_type"] == "rendered_dom"
        and row["classification"] == "functional_regression"
    ]
    assert len(dom_issues) == 1
    assert dom_issues[0]["pages"] == [1]
    assert dom_issues[0]["evidence"]["expected_tag_sequence"] == ["h1", "p"]
    assert dom_issues[0]["evidence"]["actual_tag_sequence"] == ["p", "h1"]


def test_http_500_is_a_public_api_failure_not_a_text_diff(tmp_path: Path) -> None:
    run = tmp_path / "run"
    reference = run / "llamaparse" / "case-a"
    candidate = run / "service" / "case-a"
    reference.mkdir(parents=True)
    candidate.mkdir(parents=True)
    (reference / "reference.md").write_text("hello", encoding="utf-8")
    _write_json(reference / "reference.json", _reference_json([_item("text", "hello")], "hello"))
    _write_json(reference / "pages/page-1/rendered-dom.json", _dom(1, "<p>hello</p>"))
    error = {"error": {"code": "internal_error", "message": "failed"}}
    _write_json(candidate / "response.json", error)
    _write_json(candidate / "response.md", error)
    _write_json(
        run / "service/run.json",
        {
            "cases": [
                {
                    "case_id": "case-a",
                    "outputs": {
                        "json": {"status_code": 500, "content_type": "application/json"},
                        "markdown": {"status_code": 500, "content_type": "application/json"},
                    },
                }
            ]
        },
    )
    matrix = _story_matrix(tmp_path / "matrix.md")

    result = functional_fidelity.analyze_case(
        run,
        "case-a",
        stories=functional_fidelity.parse_story_matrix(matrix),
        manifest_case={"source": {"page_count": 1}},
    )

    failures = [row for row in result["discrepancies"] if row["category"] == "api_parse_failure"]
    assert len(failures) == 1
    assert failures[0]["pages"] == [1]
    assert failures[0]["story"]["primary_story"] == "P01-US03"
    assert result["status"] == "discrepancy_found"
    assert "markdown" not in result["metrics"]
    assert "json" not in result["metrics"]


def test_written_evidence_is_byte_deterministic(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_case(
        run,
        "case-a",
        reference_md="Body",
        candidate_md="Body",
        reference_items=[_item("text", "Body")],
        candidate_items=[_item("text", "Body")],
    )
    matrix = _story_matrix(tmp_path / "matrix.md")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"cases": [{"case_id": "case-a", "source": {"page_count": 1}}]})
    output = run / "comparison"

    functional_fidelity.analyze_run(
        run, output_dir=output, manifest_path=manifest, matrix_path=matrix
    )
    first = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    functional_fidelity.analyze_run(
        run, output_dir=output, manifest_path=manifest, matrix_path=matrix
    )
    second = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }

    assert first == second


def test_fixed_status_requires_hash_bound_resolution_ledger(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_case(
        run,
        "case-a",
        reference_md="Body",
        candidate_md="Body",
        reference_items=[_item("text", "Body")],
        candidate_items=[_item("text", "Body")],
    )
    matrix = _story_matrix(tmp_path / "matrix.md")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"cases": [{"case_id": "case-a", "source": {"page_count": 1}}]})
    clean = functional_fidelity.analyze_run(
        run, manifest_path=manifest, matrix_path=matrix, write=False
    )
    inventory = clean["cases"][0]["artifact_inventory"]
    hashes = {
        key: inventory[key]["sha256"]
        for key in (
            "reference_markdown",
            "reference_json",
            "candidate_markdown",
            "candidate_json",
        )
    }
    ledger = tmp_path / "ledger.json"
    _write_json(
        ledger,
        {
            "cases": {
                "case-a": {
                    "prior_discrepancy_ids": ["FID-CASE-A-OLD"],
                    "validated_artifact_sha256": hashes,
                    "code_changes": ["app/example.py"],
                    "validation": ["pytest focused"],
                }
            }
        },
    )

    fixed = functional_fidelity.analyze_run(
        run,
        manifest_path=manifest,
        matrix_path=matrix,
        resolution_ledger=ledger,
        write=False,
    )

    assert fixed["cases"][0]["status"] == "fixed"
    assert fixed["resolved_discrepancies"] == 1
    assert fixed["cases"][0]["resolution_evidence"]["code_changes"] == [
        "app/example.py"
    ]


def test_alternate_service_root_is_selected_and_symlink_protected(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_case(
        run,
        "case-a",
        reference_md="Body",
        candidate_md="Body",
        reference_items=[_item("text", "Body")],
        candidate_items=[_item("text", "Body")],
    )
    service_post_fix = run / "service-post-fix"
    (run / "service").rename(service_post_fix)
    matrix = _story_matrix(tmp_path / "matrix.md")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"cases": [{"case_id": "case-a", "source": {"page_count": 1}}]})

    summary = functional_fidelity.analyze_run(
        run,
        service_dir=Path("service-post-fix"),
        manifest_path=manifest,
        matrix_path=matrix,
        write=False,
    )

    assert summary["service_root"] == "service-post-fix"
    assert summary["cases"][0]["artifact_inventory"]["candidate_json"]["present"]
    alias = run / "candidate-alias"
    alias.symlink_to(service_post_fix, target_is_directory=True)
    with pytest.raises(ValueError, match="immutable parser artifact roots"):
        functional_fidelity.analyze_run(
            run,
            service_dir=alias,
            output_dir=service_post_fix / "derived",
            manifest_path=manifest,
            matrix_path=matrix,
            write=False,
        )


def test_reference_selection_uses_immutable_case_rerun(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_case(
        run,
        "case-a",
        reference_md="old baseline",
        candidate_md="fresh baseline",
        reference_items=[_item("text", "old baseline")],
        candidate_items=[_item("text", "fresh baseline")],
    )
    rerun = run / "llamaparse-rerun" / "case-a"
    rerun.parent.mkdir(parents=True)
    (run / "llamaparse" / "case-a").rename(rerun)
    (rerun / "reference.md").write_text("fresh baseline", encoding="utf-8")
    _write_json(
        rerun / "reference.json",
        _reference_json([_item("text", "fresh baseline")], "fresh baseline"),
    )
    _write_json(
        rerun / "pages/page-1/rendered-dom.json",
        _dom(1, "<p>fresh baseline</p>"),
    )
    (run / "llamaparse" / "case-a").mkdir(parents=True)
    (run / "llamaparse" / "case-a" / "reference.md").write_text(
        "old baseline", encoding="utf-8"
    )
    _write_json(
        run / "llamaparse" / "case-a" / "reference.json",
        _reference_json([_item("text", "old baseline")], "old baseline"),
    )
    _write_json(
        run / "llamaparse" / "case-a" / "pages/page-1/rendered-dom.json",
        _dom(1, "<p>old baseline</p>"),
    )
    selection = tmp_path / "selection.json"
    _write_json(selection, {"cases": {"case-a": "llamaparse-rerun"}})
    matrix = _story_matrix(tmp_path / "matrix.md")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"cases": [{"case_id": "case-a", "source": {"page_count": 1}}]})

    summary = functional_fidelity.analyze_run(
        run,
        service_dir=run / "service",
        manifest_path=manifest,
        matrix_path=matrix,
        reference_selection=selection,
        write=False,
    )

    case = summary["cases"][0]
    assert case["reproduce"]["reference_root"] == "llamaparse-rerun/case-a"
    assert "--reference-selection" in case["reproduce"]["command"]
    assert not [
        issue
        for issue in case["discrepancies"]
        if issue["category"] in {"text_integrity", "rendered_text"}
    ]


def test_chart_labelled_llama_table_is_not_double_counted_as_table() -> None:
    chart_table = {
        **_item("table", "2024 10 2025 20"),
        "rows": [["Year", "Value"], ["2024", "10"], ["2025", "20"]],
        "bbox": [{"x": 1, "y": 1, "w": 10, "h": 10, "label": "chart"}],
    }
    pages = _reference_json([chart_table], "2024 10 2025 20")["items"]["pages"]

    assert functional_fidelity._table_profile(pages) == []
    visuals = functional_fidelity._visual_profile(pages)
    assert len(visuals) == 1
    assert visuals[0]["kind"] == "chart"


def test_mixed_chart_and_table_labels_are_still_one_visual() -> None:
    chart_table = {
        **_item("table", "2024 10 2025 20"),
        "rows": [["Year", "Value"], ["2024", "10"], ["2025", "20"]],
        "bbox": [
            {"x": 1, "y": 1, "w": 10, "h": 10, "label": "chart"},
            {"x": 1, "y": 1, "w": 10, "h": 10, "label": "table"},
        ],
    }
    pages = _reference_json([chart_table], "2024 10 2025 20")["items"]["pages"]

    assert functional_fidelity._table_profile(pages) == []
    visuals = functional_fidelity._visual_profile(pages)
    assert len(visuals) == 1
    assert visuals[0]["kind"] == "chart"


def test_physical_page_index_and_schema_taxonomy_are_not_false_regressions() -> None:
    expected = _reference_json([_item("text", "Figure 1")], "Figure 1")
    actual = _candidate_json([_item("caption", "Figure 1")])
    actual_page = actual["pages"][0]
    actual_page["page_index"] = 1
    actual_page["page_number"] = 37
    actual_page["page_label"] = "37"

    _metrics, issues = functional_fidelity._compare_json(
        "case-a", expected, actual, {}, scanned_candidate=False
    )

    assert not [row for row in issues if row["category"] == "page_sequence"]
    taxonomy = [row for row in issues if row["category"] == "json_structure"]
    assert taxonomy
    assert all(row["classification"] == "acceptable_difference" for row in taxonomy)


def test_native_visual_ocr_proxy_requires_review_instead_of_being_accepted() -> None:
    expected = _reference_json([_item("image", "Chart values 10 20")], "Chart values 10 20")
    actual = _candidate_json([_item("image", "Chart values 10 21")])

    _metrics, issues = functional_fidelity._compare_json(
        "case-a", expected, actual, {}, scanned_candidate=False
    )

    ocr = [row for row in issues if row["category"] == "ocr"]
    assert len(ocr) == 1
    assert ocr[0]["classification"] == "review_required"
    assert ocr[0]["evidence"]["automated_proxy"] is True
