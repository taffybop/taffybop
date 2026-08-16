"""Real-pipeline regressions for P03-US05 text-run semantics."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pytest

from app.config import Settings
from app.services.input_documents import (
    InputKind,
    LoadedDocument,
    SourcePage,
)
from app.services.ir import build_document_ir
import app.services.ir as ir_module
import app.services.pipeline as pipeline
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
import app.services.text_run_semantics as text_run_semantics
from tests.benchmarks.text_run_semantics_metrics import (
    PURCHASE_SOURCE_SEQUENCE,
    _purchase_source_sequence_metrics,
)
from tests.regression.phase_03.test_p03_us04_real_reading_order import (
    CLEAN_SECTION,
    CLEAN_TITLE,
    CORPUS_SHA256 as ORDER_CORPUS_SHA256,
    REVIEWED_PAIR_SLICES,
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"

SOURCE_IDENTITIES = {
    "purchase-agreement": (
        152_828,
        "00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14",
    ),
    "postal-10k": (
        83_589,
        "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74",
    ),
    "finance-10k": (
        87_105,
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086",
    ),
}

PUBLIC_TEXT_RUN_FIELDS = {
    "text_run_policy",
    "text_runs",
    "text_rules",
    "redline_markdown",
    "active_text",
    "active_text_omitted_run_ids",
    "active_text_policy",
}

PUBLIC_RUN_KEYS = {
    "id",
    "element_id",
    "target_path",
    "text",
    "source_text",
    "start",
    "end",
    "bbox",
    "font_name",
    "font_size",
    "bold",
    "italic",
    "color",
    "change_state",
    "decorations",
    "placeholder",
    "rule_ids",
    "evidence_method",
    "semantic_derivation",
    "extraction_policy_id",
    "association_policy_id",
}

PUBLIC_RULE_KEYS = {
    "id",
    "bbox",
    "source_object_kind",
    "source_object_index",
    "color",
    "width",
    "thickness",
    "evidence_method",
    "extraction_policy_id",
}

DELETED_SOURCE_GROUPS = {
    "Draft of 6/1/20",
    (
        "This is a draft document. Certain updates will be needed prior to "
        "finalizing this."
    ),
    (
        "In particular, bracketed items with '[ ]' indicate a known "
        "open/non-final item."
    ),
    "This is Confidential to The City of Johnstown",
    "June",
    "23",
}

POSTAL_ITALIC_TARGETS = {
    "CARES Act": ("cells", 20, "text"),
    "Coronavirus Aid, Relief, and Economic Security Act": (
        "cells",
        21,
        "text",
    ),
    "Exchange Act": ("cells", 66, "text"),
    "Securities and Exchange Act of 1934": (
        "cells",
        67,
        "text",
    ),
}


def _settings(enabled: bool) -> Settings:
    return Settings(
        # The deterministic local-fidelity profile deliberately omits the
        # optional picture-classifier snapshot. Passing the absolute artifact
        # root makes Docling skip only that unavailable model without probing
        # a user cache or network during this real-corpus text regression.
        docling_artifacts_path=str(WORKSPACE / ".models" / "docling"),
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=enabled,
    )


def _predecessor_settings() -> Settings:
    """Return the accepted P03-US04 configuration with no US05 argument."""

    return Settings(
        docling_artifacts_path=str(WORKSPACE / ".models" / "docling"),
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
    )


@lru_cache(maxsize=None)
def _source(case: str) -> bytes:
    source = (CORPUS / f"{case}.pdf").read_bytes()
    expected_size, expected_sha256 = SOURCE_IDENTITIES[case]
    assert len(source) == expected_size
    assert hashlib.sha256(source).hexdigest() == expected_sha256
    return source


@lru_cache(maxsize=None)
def _enabled_parse(case: str) -> dict[str, Any]:
    result = parse_document(
        _source(case),
        f"{case}.pdf",
        _settings(True),
    )
    return result.model_dump(mode="json", exclude_none=False)


@lru_cache(maxsize=None)
def _enabled_us05_order_parse(case: str) -> dict[str, Any]:
    if case in SOURCE_IDENTITIES:
        return _enabled_parse(case)
    source = (CORPUS / f"{case}.pdf").read_bytes()
    assert hashlib.sha256(source).hexdigest() == ORDER_CORPUS_SHA256[case]
    return parse_document(
        source,
        f"{case}.pdf",
        _settings(True),
    ).model_dump(mode="json", exclude_none=False)


@lru_cache(maxsize=None)
def _source_evidence(case: str) -> Any:
    report = text_run_semantics.extract_text_run_evidence(
        _source(case),
        max_pages=100,
    )
    assert report.usable is True
    return report


def _semantic_bytes(payload: Mapping[str, Any]) -> bytes:
    stable = deepcopy(dict(payload))
    stable.get("processing", {}).pop("duration_ms", None)
    return json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _assert_no_public_text_run_fields(payload: Mapping[str, Any]) -> None:
    for value in _walk(payload):
        if isinstance(value, Mapping):
            assert PUBLIC_TEXT_RUN_FIELDS.isdisjoint(value)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert "p03-text-run-semantics-v1" not in serialized
    assert "text_run_source_" not in serialized
    assert "text_run_projection_" not in serialized


def _pages(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pages = payload.get("pages")
    assert isinstance(pages, list)
    return pages


def _page(
    payload: Mapping[str, Any],
    page_index: int,
) -> Mapping[str, Any]:
    matches = [
        page
        for page in _pages(payload)
        if page.get("page_index") == page_index
    ]
    assert len(matches) == 1
    return matches[0]


def _items(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for page in _pages(payload):
        raw_items = page.get("items")
        assert isinstance(raw_items, list)
        yield from raw_items


def _item(
    payload: Mapping[str, Any],
    page_index: int,
    item_id: str,
) -> Mapping[str, Any]:
    raw_items = _page(payload, page_index).get("items")
    assert isinstance(raw_items, list)
    matches = [item for item in raw_items if item.get("id") == item_id]
    assert len(matches) == 1
    return matches[0]


def _semantic_items(
    payload: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    return [item for item in _items(payload) if "text_runs" in item]


def _runs(
    payload: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    for item in _semantic_items(payload):
        raw_runs = item["text_runs"]
        assert isinstance(raw_runs, list)
        output.extend(raw_runs)
    return output


def _resolve_target(
    item: Mapping[str, Any],
    path: Iterable[str | int],
) -> str:
    target: Any = item
    for component in path:
        if isinstance(component, int):
            assert isinstance(target, list)
            target = target[component]
        else:
            assert isinstance(target, Mapping)
            target = target[component]
    assert isinstance(target, str)
    return target


def _assert_public_run_graph(payload: Mapping[str, Any]) -> None:
    for item in _semantic_items(payload):
        runs = item["text_runs"]
        rules = item["text_rules"]
        assert isinstance(runs, list)
        assert isinstance(rules, list)
        assert item["text_run_policy"] == "p03-text-run-semantics-v1"
        assert len({run["id"] for run in runs}) == len(runs)
        assert len({rule["id"] for rule in rules}) == len(rules)
        linked_rule_ids = {
            rule_id for run in runs for rule_id in run["rule_ids"]
        }
        assert {rule["id"] for rule in rules} == linked_rule_ids

        prior_by_path: dict[tuple[str | int, ...], int] = {}
        for run in runs:
            expected_keys = set(PUBLIC_RUN_KEYS)
            if "change_group_id" in run:
                expected_keys.add("change_group_id")
            assert set(run) == expected_keys
            assert set(run["bbox"]) == {
                "x",
                "y",
                "width",
                "height",
                "unit",
            }
            assert run["bbox"]["unit"] == "pt"
            assert set(run["color"]) == {"space", "components"}
            target_path = tuple(run["target_path"])
            target = _resolve_target(item, target_path)
            start = run["start"]
            end = run["end"]
            assert 0 <= start < end <= len(target)
            assert target[start:end] == run["text"]
            assert start >= prior_by_path.get(target_path, 0)
            prior_by_path[target_path] = end

        for rule in rules:
            assert set(rule) == PUBLIC_RULE_KEYS
            assert set(rule["bbox"]) == {
                "x",
                "y",
                "width",
                "height",
                "unit",
            }
            assert rule["bbox"]["unit"] == "pt"
            assert set(rule["color"]) == {"space", "components"}


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _deleted_group_texts(
    payload: Mapping[str, Any],
    deleted: Iterable[Mapping[str, Any]],
) -> set[str]:
    owner_by_run_id = {
        run["id"]: item
        for item in _semantic_items(payload)
        for run in item["text_runs"]
    }
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for run in deleted:
        group_id = run["change_group_id"]
        assert isinstance(group_id, str)
        grouped.setdefault(group_id, []).append(run)

    output: set[str] = set()
    for group_runs in grouped.values():
        owners = {id(owner_by_run_id[run["id"]]) for run in group_runs}
        paths = {tuple(run["target_path"]) for run in group_runs}
        assert len(owners) == len(paths) == 1
        owner = owner_by_run_id[group_runs[0]["id"]]
        target = _resolve_target(owner, group_runs[0]["target_path"])
        start = min(run["start"] for run in group_runs)
        end = max(run["end"] for run in group_runs)
        output.add(_normalized(target[start:end]))
    return output


def _canonical_block_for_item(
    payload: Mapping[str, Any],
    page_index: int,
    item_id: str,
) -> Mapping[str, Any]:
    public_page = _page(payload, page_index)
    public_items = public_page["items"]
    assert isinstance(public_items, list)
    position = [item["id"] for item in public_items].index(item_id)
    canonical_pages = payload["canonical_presentation"]["pages"]
    matches = [
        page
        for page in canonical_pages
        if page["page_index"] == page_index
    ]
    assert len(matches) == 1
    blocks = matches[0]["blocks"]
    assert len(blocks) == len(public_items)
    return blocks[position]


@pytest.fixture(scope="module")
def purchase_flag_off_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    def forbidden_extractor(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("flag-off parse invoked the US05 extractor")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            text_run_semantics,
            "extract_text_run_evidence",
            forbidden_extractor,
        )
        explicit_false = parse_document(
            _source("purchase-agreement"),
            "purchase-agreement.pdf",
            _settings(False),
        ).model_dump(mode="json", exclude_none=False)
        predecessor = parse_document(
            _source("purchase-agreement"),
            "purchase-agreement.pdf",
            _predecessor_settings(),
        ).model_dump(mode="json", exclude_none=False)
    return explicit_false, predecessor


def test_real_text_run_fixture_custody_is_exact() -> None:
    assert set(SOURCE_IDENTITIES) == {
        "purchase-agreement",
        "postal-10k",
        "finance-10k",
    }
    for case in SOURCE_IDENTITIES:
        _source(case)


@pytest.mark.integration
def test_flag_off_is_byte_stable_and_never_extracts_or_leaks_us05_fields(
    purchase_flag_off_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    explicit_false, predecessor = purchase_flag_off_pair

    assert _semantic_bytes(explicit_false) == _semantic_bytes(predecessor)
    assert explicit_false["schema_version"] == "1.0"
    assert (
        explicit_false["canonical_presentation"]["schema_version"]
        == "1.0"
    )
    assert (
        explicit_false["canonical_presentation"]["policy_id"]
        == "canonical-presentation-v1"
    )
    _assert_no_public_text_run_fields(explicit_false)


@pytest.mark.integration
def test_purchase_full_pipeline_has_exact_redline_denominators_and_views() -> None:
    payload = _enabled_parse("purchase-agreement")
    runs = _runs(payload)
    deleted = [run for run in runs if run["change_state"] == "deleted"]

    assert payload["schema_version"] == "1.0"
    assert len(runs) == 28
    assert len(deleted) == 9
    assert len({run["change_group_id"] for run in deleted}) == 6
    assert _deleted_group_texts(payload, deleted) == DELETED_SOURCE_GROUPS
    assert len(
        {
            (run["change_group_id"], rule_id)
            for run in deleted
            for rule_id in run["rule_ids"]
        }
    ) == 7
    assert sum(len(run["rule_ids"]) for run in deleted) == 9
    assert len(
        {
            rule["id"]
            for item in _semantic_items(payload)
            for rule in item["text_rules"]
        }
    ) == 13
    assert sum(len(run["rule_ids"]) for run in runs) == 15
    assert all(
        run["change_state"] not in {"inserted", "replacement"}
        for run in runs
    )

    by_text = {
        run["text"]: run
        for run in runs
        if run["text"]
        in {"EXECUTION VERSION", "_______", "Background", "Exhibit A"}
    }
    assert set(by_text) == {
        "EXECUTION VERSION",
        "_______",
        "Background",
        "Exhibit A",
    }
    assert by_text["EXECUTION VERSION"]["change_state"] == "unchanged"
    assert by_text["EXECUTION VERSION"]["decorations"] == ["underline"]
    assert len(by_text["EXECUTION VERSION"]["rule_ids"]) == 2
    assert by_text["_______"]["change_state"] == "unknown"
    assert by_text["_______"]["placeholder"] is True
    assert by_text["_______"]["decorations"] == ["underline"]
    assert len(by_text["_______"]["rule_ids"]) == 2
    assert by_text["Background"]["change_state"] == "unchanged"
    assert by_text["Exhibit A"]["change_state"] == "unchanged"

    draft = _item(payload, 1, "p1-i9")
    assert draft["value"] == "Draft of 6/1/20"
    assert draft["type"] == "text"
    assert draft.get("level") is None
    assert draft["md"] == "~~Draft of 6/1/20~~"
    assert draft["redline_markdown"] == draft["md"]
    assert draft["active_text"] == ""
    assert len(draft["active_text_omitted_run_ids"]) == 1

    title = _item(payload, 1, "p1-i1")
    background = _item(payload, 1, "p1-i3")
    assert (title["type"], title["level"], title["md"]) == (
        "heading",
        1,
        "# ASSET PURCHASE AGREEMENT",
    )
    assert (background["type"], background["level"], background["md"]) == (
        "heading",
        2,
        "## <u>Background</u>",
    )

    warning = _item(payload, 1, "p1-i10")
    assert warning["value"].startswith("This is a draft document.")
    assert warning["redline_markdown"] == warning["md"]
    assert "~~This is a draft document." in warning["md"]
    assert r"'\[ \]'" in warning["md"]
    assert warning["active_text"].strip() == ""

    opening = _item(payload, 1, "p1-i2")
    assert "[June 23_______]" in opening["value"]
    assert r"\[~~June~~ ~~23~~<u>_______</u>\]" in opening["md"]
    for defined_term in (
        "Agreement",
        "Effective Date",
        "Seller",
        "Buyer",
        "Parties",
    ):
        assert f"**{defined_term}**" in opening["md"]
    assert "June" not in opening["active_text"]
    assert "23" not in opening["active_text"]
    assert "_______" in opening["active_text"]
    assert opening["active_text_policy"] == "omit-proven-deletions-v1"

    _assert_public_run_graph(payload)


@pytest.mark.integration
def test_purchase_source_composition_sequence_is_exact_under_us05() -> None:
    measured = _purchase_source_sequence_metrics(
        _enabled_parse("purchase-agreement")
    )

    assert measured["expected"] == PURCHASE_SOURCE_SEQUENCE
    assert measured["observed"] == PURCHASE_SOURCE_SEQUENCE
    assert measured["expected_count"] == 7
    assert measured["observed_count"] == 7
    assert measured["strictly_ordered"] is True
    assert measured["exact"] is True


@pytest.mark.integration
def test_full_p03_us04_order_denominator_remains_41_of_41_under_us05(
) -> None:
    assert set(ORDER_CORPUS_SHA256) == {
        case for case, _page_index, _pairs in REVIEWED_PAIR_SLICES
    }
    matched = 0
    expected = 0
    for case, page_index, pairs in REVIEWED_PAIR_SLICES:
        payload = _enabled_us05_order_parse(case)
        items = _page(payload, page_index)["items"]
        assert isinstance(items, list)
        positions = {
            str(item["id"]): position
            for position, item in enumerate(items)
        }
        assert len(positions) == len(items)
        for before_id, after_id in pairs:
            expected += 1
            assert before_id in positions
            assert after_id in positions
            assert positions[before_id] < positions[after_id]
            matched += 1

    clean = _enabled_us05_order_parse("clean-energy")
    owner = _item(clean, 1, "p1-i1")
    child_values = [child["value"] for child in owner["items"]]
    assert child_values.count(CLEAN_TITLE) == 1
    assert child_values.count(CLEAN_SECTION) == 1
    assert child_values.index(CLEAN_TITLE) < child_values.index(CLEAN_SECTION)
    canonical = _canonical_block_for_item(clean, 1, "p1-i1")
    for field in ("markdown", "text"):
        assert canonical[field].count(CLEAN_TITLE) == 1
        assert canonical[field].count(CLEAN_SECTION) == 1
        assert canonical[field].index(CLEAN_TITLE) < canonical[field].index(
            CLEAN_SECTION
        )

    expected += 1
    matched += 1
    assert expected == 41
    assert matched == expected


@pytest.mark.integration
def test_enabled_canonical_and_markdown_default_to_complete_source_redline() -> None:
    payload = _enabled_parse("purchase-agreement")

    for item_id in ("p1-i9", "p1-i10", "p1-i2"):
        item = _item(payload, 1, item_id)
        canonical = _canonical_block_for_item(payload, 1, item_id)
        assert canonical["text"] == item["value"]
        assert canonical["markdown"] == item["redline_markdown"]
        assert canonical["markdown"] == item["md"]
        assert canonical["text"] != item["active_text"]

    rendered = to_markdown(payload)
    assert "~~Draft of 6/1/20~~" in rendered
    assert "# ~~Draft of 6/1/20~~" not in rendered
    assert "## <u>Background</u>" in rendered
    assert "~~This is a draft document." in rendered
    assert r"\[~~June~~ ~~23~~<u>_______</u>\]" in rendered
    assert "**Agreement**" in rendered
    assert "**Parties**" in rendered


@pytest.mark.integration
def test_postal_full_pipeline_maps_only_reviewed_italics_to_table_cells() -> None:
    payload = _enabled_parse("postal-10k")
    table = _item(payload, 1, "p1-i3")
    table_runs = table["text_runs"]

    assert len(_runs(payload)) == 8
    assert len(table_runs) == 6
    assert "redline_markdown" not in table
    assert "active_text" not in table
    assert all(
        run["change_state"] == "unchanged" for run in _runs(payload)
    )
    for text, expected_path in POSTAL_ITALIC_TARGETS.items():
        matches = [run for run in table_runs if run["text"] == text]
        assert len(matches) == 1
        run = matches[0]
        assert tuple(run["target_path"]) == expected_path
        assert run["italic"] is True
        assert run["bold"] is False
        assert run["decorations"] == []
        target = _resolve_target(table, expected_path)
        assert target[run["start"] : run["end"]] == text

    assert {
        run["text"] for run in table_runs if run["italic"]
    } == set(POSTAL_ITALIC_TARGETS)
    _assert_public_run_graph(payload)


@pytest.mark.integration
def test_finance_full_pipeline_keeps_bold_controls_without_redlines() -> None:
    payload = _enabled_parse("finance-10k")
    runs = _runs(payload)

    assert len(runs) == 26
    assert all(run["change_state"] == "unchanged" for run in runs)
    assert all(run["decorations"] == [] for run in runs)
    assert all(run["placeholder"] is False for run in runs)
    assert all(not run["rule_ids"] for run in runs)
    assert all(run["bold"] is True for run in runs)

    page_one_runs = [
        run
        for item in _page(payload, 1)["items"]
        for run in item.get("text_runs", [])
    ]
    for text in ("Apple Inc.", "CONSOLIDATED STATEMENTS OF OPERATIONS"):
        matches = [run for run in page_one_runs if run["text"] == text]
        assert len(matches) == 1
        assert matches[0]["bold"] is True
    assert _item(payload, 1, "p1-i3")["value"] == (
        "(In millions, except number of shares, which are reflected in "
        "thousands, and per-share amounts)"
    )
    _assert_public_run_graph(payload)


def _loaded_raster() -> LoadedDocument:
    return LoadedDocument(
        kind=InputKind.IMAGE,
        original_bytes=b"source-raster",
        processing_bytes=b"normalized-raster",
        original_filename="source.png",
        processing_filename="source.png",
        mime_type="image/png",
        source_format="PNG",
        pages=(
            SourcePage(
                page_index=1,
                pixel_width=100,
                pixel_height=80,
                png_bytes=b"png",
                original_orientation=None,
                orientation_applied=False,
            ),
        ),
    )


def test_image_only_pipeline_fails_closed_with_content_free_internal_concern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: ({"body": {"children": []}}, []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        pipeline,
        "extract_vector_tables",
        lambda *_args, **_kwargs: {},
    )

    def analyze(context: pipeline.SharedAnalysisContext) -> None:
        context.pages[0]["items"] = [
            {
                "id": "p1-i1",
                "type": "text",
                "reading_order": 0,
                "value": "Visible raster source",
                "md": "Visible raster source",
                "bbox": {
                    "x": 5.0,
                    "y": 5.0,
                    "width": 80.0,
                    "height": 12.0,
                    "unit": "px",
                },
                "source": "ocr",
                "confidence": 0.99,
            }
        ]

    monkeypatch.setattr(pipeline, "_analyze_shared_pages", analyze)

    def forbidden_extractor(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("image input invoked the native-PDF extractor")

    monkeypatch.setattr(
        text_run_semantics,
        "extract_text_run_evidence",
        forbidden_extractor,
    )

    captured_ir: list[Any] = []
    original_round_trip = ir_module.round_trip_document

    def observed_round_trip(*args: Any, **kwargs: Any) -> Any:
        public, internal = original_round_trip(*args, **kwargs)
        captured_ir.append(internal)
        return public, internal

    monkeypatch.setattr(
        ir_module,
        "round_trip_document",
        observed_round_trip,
    )
    payload = pipeline._parse_loaded_document(
        _loaded_raster(),
        _settings(True),
    ).model_dump(mode="json", exclude_none=False)

    assert len(captured_ir) == 1
    internal = captured_ir[0]
    assert internal.text_runs == []
    assert internal.text_rules == []
    text_run_concerns = [
        concern
        for concern in internal.concerns
        if concern.code.startswith("text_run_")
    ]
    assert [concern.code for concern in text_run_concerns] == [
        "text_run_source_unsupported"
    ]
    concern_json = json.dumps(
        text_run_concerns[0].model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "Visible raster source" not in concern_json
    assert "source-raster" not in concern_json
    _assert_no_public_text_run_fields(payload)


@pytest.mark.integration
def test_real_purchase_projection_is_idempotent_and_mismatch_rolls_back(
    purchase_flag_off_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    predecessor_payload, _equivalent = purchase_flag_off_pair
    predecessor = build_document_ir(deepcopy(predecessor_payload))
    before = predecessor.model_dump(mode="json")

    first = text_run_semantics.project_text_run_semantics(
        predecessor,
        _source_evidence("purchase-agreement"),
    )
    second = text_run_semantics.project_text_run_semantics(
        first,
        _source_evidence("purchase-agreement"),
    )
    assert predecessor.model_dump(mode="json") == before
    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert len(first.text_runs) == 28
    assert len(first.text_rules) == 13

    mismatch = text_run_semantics.project_text_run_semantics(
        predecessor,
        _source_evidence("finance-10k"),
    )
    assert mismatch.text_runs == []
    assert mismatch.text_rules == []
    assert [
        element.properties.get("legacy_item")
        for element in mismatch.elements
    ] == [
        element.properties.get("legacy_item")
        for element in predecessor.elements
    ]
    mismatch_concerns = [
        concern
        for concern in mismatch.concerns
        if concern.code.startswith("text_run_")
    ]
    assert [concern.code for concern in mismatch_concerns] == [
        "text_run_source_invalid"
    ]
    serialized_concerns = json.dumps(
        [
            concern.model_dump(mode="json")
            for concern in mismatch_concerns
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "Apple Inc." not in serialized_concerns
    assert "Draft of 6/1/20" not in serialized_concerns
