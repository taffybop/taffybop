"""Real-corpus regression coverage for P03-US03."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.config import Settings
from app.models import ParseResult
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
from app.services.source_note_contracts import is_source_note_owner_item


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"

CORPUS_SHA256 = {
    "catastrophe-recap": (
        "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
    ),
    "clinical-study": (
        "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2"
    ),
    "health-report": (
        "fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181"
    ),
    "finance-10k": (
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
    ),
}

AON_NOTE = "Data: Aon Catastrophe Insight"
CLINICAL_REVIEWED_NOTES = {
    "1 At least 4 out of 5 SbS sessions completed.",
    "2 Less than 4 SbS sessions completed.",
    "3 Highest education level started.",
    "1 Pooled descriptive statistics across all imputed datasets.",
    (
        "2 As covariates the models included: baseline score, gender, age, "
        "marital status, education, occupation, and postmigration living "
        "difficulties."
    ),
    (
        "3 Treatment effects were pooled based on multiple imputations (100), "
        "assuming missing at random, using progressive mean matching (PMM)."
    ),
    (
        "4 Hedges' g effect sizes were derived by combining multiple "
        "imputation estimates using Rubin's rules."
    ),
}
CLINICAL_TABLE_LINKS = {
    "https://doi.org/10.1371/journal.pmed.1004460.t001",
    "https://doi.org/10.1371/journal.pmed.1004460.t002",
}
CLINICAL_TABLE_ONE_NOTES = (
    "1 At least 4 out of 5 SbS sessions completed.",
    "2 Less than 4 SbS sessions completed.",
    "3 Highest education level started.",
    "https://doi.org/10.1371/journal.pmed.1004460.t001",
)
CLINICAL_TABLE_ONE_CAPTION = (
    "Table 1. Demographic and baseline characteristics."
)
HEALTH_UPPER_NOTE = (
    "Note: The EU average is weighted. Data for the United Kingdom refer to "
    "2020 and have been calculated by the OECD. Source: Eurostat "
    "(hlth_cd_asdr2)."
)
HEALTH_STATLINKS = {
    "https://stat.link/hufsd5",
    "https://stat.link/styxji",
}


def _settings(source_notes: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=source_notes,
    )


@lru_cache(maxsize=None)
def _parse(case: str, source_notes: bool) -> dict[str, Any]:
    path = CORPUS / f"{case}.pdf"
    return parse_document(
        path.read_bytes(),
        path.name,
        _settings(source_notes),
    ).model_dump(mode="json", exclude_none=False)


def _items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for page in payload["pages"]
        for item in page["items"]
    ]


def _notes(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in _items(payload)
        if item.get("type") in {"source_note", "footnote"}
    ]


def _semantic(payload: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    detached.get("processing", {}).pop("duration_ms", None)
    return detached


def _intersection_area(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    left = max(float(first["x"]), float(second["x"]))
    top = max(float(first["y"]), float(second["y"]))
    right = min(
        float(first["x"]) + float(first["width"]),
        float(second["x"]) + float(second["width"]),
    )
    bottom = min(
        float(first["y"]) + float(first["height"]),
        float(second["y"]) + float(second["height"]),
    )
    return max(right - left, 0.0) * max(bottom - top, 0.0)


def _box_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "x": value["x"],
        "y": value["y"],
        "width": value["width"],
        "height": value["height"],
        "unit": value["unit"],
    }


def _assert_note_contract(payload: Mapping[str, Any]) -> None:
    for page in payload["pages"]:
        page_items = page["items"]
        positions = {
            item["id"]: index for index, item in enumerate(page_items)
        }
        by_id = {item["id"]: item for item in page_items}
        relationship_ids: set[str] = set()
        for note in (
            item
            for item in page_items
            if item.get("type") in {"source_note", "footnote"}
        ):
            owner_field = (
                "source_note_of"
                if note["type"] == "source_note"
                else "footnote_of"
            )
            backlink_field = (
                "source_note_ids"
                if note["type"] == "source_note"
                else "footnote_ids"
            )
            owner = by_id[note[owner_field]]
            assert is_source_note_owner_item(owner)
            assert positions[owner["id"]] < positions[note["id"]]
            assert note["id"] in owner[backlink_field]
            descriptor = [
                relationship
                for relationship in owner["relationships"]
                if relationship.get("id") == note["relationship_id"]
            ]
            assert descriptor == [
                {
                    "id": note["relationship_id"],
                    "type": note["relationship_type"],
                    "source_id": note["id"],
                    "target_id": owner["id"],
                }
            ]
            assert note["relationship_id"] not in relationship_ids
            relationship_ids.add(note["relationship_id"])
            assert note["bbox"]["unit"] == owner["bbox"]["unit"]
            assert _intersection_area(note["bbox"], owner["bbox"]) == 0
            assert float(note["bbox"]["y"]) >= (
                float(owner["bbox"]["y"])
                + float(owner["bbox"]["height"])
            )
            for link in note.get("links") or []:
                assert link["target"].startswith(("http://", "https://"))
                assert link["target"] in note["value"]


def test_real_source_note_fixture_custody_is_unchanged() -> None:
    for case, expected_sha256 in CORPUS_SHA256.items():
        assert (
            hashlib.sha256(
                (CORPUS / f"{case}.pdf").read_bytes()
            ).hexdigest()
            == expected_sha256
        )


@pytest.mark.integration
def test_catastrophe_aon_note_is_exact_external_and_once() -> None:
    payload = _parse("catastrophe-recap", True)
    notes = _notes(payload)
    assert [(note["type"], note["value"]) for note in notes] == [
        ("source_note", AON_NOTE)
    ]
    [note] = notes
    assert note["source_note_of"] == "p1-i5"
    assert note["bbox"] == {
        "x": 101.221,
        "y": 592.567,
        "width": 73.8,
        "height": 5.0,
        "unit": "pt",
    }
    owner = next(
        item for item in _items(payload) if item["id"] == "p1-i5"
    )
    assert _box_identity(owner["bbox"]) == {
        "x": 100.221,
        "y": 437.31,
        "width": 444.032,
        "height": 149.057,
        "unit": "pt",
    }
    assert to_markdown(payload).count(AON_NOTE) == 1
    assert payload["canonical_presentation"]["full"]["text"].count(
        AON_NOTE
    ) == 1
    _assert_note_contract(payload)


@pytest.mark.integration
def test_clinical_has_all_seven_reviewed_notes_and_grounded_table_links() -> None:
    payload = _parse("clinical-study", True)
    notes = _notes(payload)
    actual_reviewed = {
        note["value"]
        for note in notes
        if note["value"] in CLINICAL_REVIEWED_NOTES
    }
    assert actual_reviewed == CLINICAL_REVIEWED_NOTES
    assert sum(
        note["value"] in CLINICAL_REVIEWED_NOTES for note in notes
    ) == 7

    table_1 = next(
        item for item in _items(payload) if item["id"] == "p2-i2"
    )
    table_2 = next(
        item for item in _items(payload) if item["id"] == "p4-i2"
    )
    assert _box_identity(table_1["bbox"]) == {
        "x": 35.237,
        "y": 86.521,
        "width": 541.581,
        "height": 411.516,
        "unit": "pt",
    }
    assert _box_identity(table_2["bbox"]) == {
        "x": 35.164,
        "y": 88.276,
        "width": 541.436,
        "height": 200.702,
        "unit": "pt",
    }
    table_link_targets = {
        link["target"]
        for note in notes
        if note.get("footnote_of") in {"p2-i2", "p4-i2"}
        for link in note.get("links") or []
    }
    assert table_link_targets == CLINICAL_TABLE_LINKS
    for value in CLINICAL_REVIEWED_NOTES:
        assert to_markdown(payload).count(value) == 1
        assert payload["canonical_presentation"]["full"]["text"].count(
            value
        ) == 1
    _assert_note_contract(payload)


@pytest.mark.integration
def test_clinical_table_one_candidate_release_composition_is_complete() -> None:
    from tests.regression.phase_03.test_p03_us02_real_visual_benchmarks import (
        _parse_local_fidelity,
    )

    payload = _parse_local_fidelity("clinical-study")
    ParseResult.model_validate(payload)
    page = payload["pages"][1]
    captions = [
        item
        for item in page["items"]
        if item.get("type") == "caption"
        and item.get("value") == CLINICAL_TABLE_ONE_CAPTION
    ]
    assert len(captions) == 1
    owner_id = captions[0].get("caption_of")
    assert isinstance(owner_id, str) and owner_id
    owners = [item for item in page["items"] if item.get("id") == owner_id]
    assert len(owners) == 1
    owner = owners[0]
    assert owner["type"] == "table_candidate"
    assert owner["table_candidate_gate"]["outcome"] == "unresolved"
    assert (
        owner["row_count"],
        owner["column_count"],
        len(owner["cells"]),
    ) == (32, 6, 166)
    assert owner["table_candidate_gate"]["feature_scores"][
        "cell_coverage"
    ] == 0.864583

    assert [caption["value"] for caption in captions] == [
        CLINICAL_TABLE_ONE_CAPTION
    ]
    caption = captions[0]
    caption_descriptor = next(
        relationship
        for relationship in owner["relationships"]
        if relationship["id"] == caption["relationship_id"]
    )
    assert caption_descriptor == {
        "id": caption["relationship_id"],
        "type": caption["relationship_type"],
        "source_id": caption["id"],
        "target_id": owner["id"],
    }

    notes = [
        item
        for item in page["items"]
        if item.get("source_note_of") == owner["id"]
        or item.get("footnote_of") == owner["id"]
    ]
    assert tuple(note["value"] for note in notes) == CLINICAL_TABLE_ONE_NOTES
    positions = {
        item["id"]: index for index, item in enumerate(page["items"])
    }
    assert positions[captions[0]["id"]] < positions[owner["id"]]
    assert all(positions[owner["id"]] < positions[note["id"]] for note in notes)
    assert [positions[note["id"]] for note in notes] == sorted(
        positions[note["id"]] for note in notes
    )
    assert owner.get("source_note_ids", []) + owner.get(
        "footnote_ids", []
    ) == [note["id"] for note in notes]
    for note in notes:
        descriptor = next(
            relationship
            for relationship in owner["relationships"]
            if relationship["id"] == note["relationship_id"]
        )
        assert descriptor == {
            "id": note["relationship_id"],
            "type": note["relationship_type"],
            "source_id": note["id"],
            "target_id": owner["id"],
        }

    raw_markdown = to_markdown(payload)
    canonical_text = payload["canonical_presentation"]["full"]["text"]
    for value in (CLINICAL_TABLE_ONE_CAPTION, *CLINICAL_TABLE_ONE_NOTES):
        assert raw_markdown.count(value) == 1
        assert canonical_text.count(value) == 1

    table_one_link = CLINICAL_TABLE_ONE_NOTES[-1]
    assert all(
        table_one_link not in str(item.get("value") or "")
        and table_one_link not in str(item.get("md") or "")
        for item in payload["pages"][0]["items"]
    )

    canonical_page = payload["canonical_presentation"]["pages"][1]
    candidate_blocks = [
        block
        for block in canonical_page["blocks"]
        if block["primary_element_type"] == "table_candidate"
    ]
    assert len(candidate_blocks) == 1
    assert not any(
        block["primary_element_type"] == "table"
        for block in canonical_page["blocks"]
    )
    candidate_block = candidate_blocks[0]
    candidate_position = canonical_page["blocks"].index(candidate_block)
    for serialized in (candidate_block["text"], candidate_block["markdown"]):
        assert serialized.startswith(CLINICAL_TABLE_ONE_CAPTION)
        assert serialized.count(CLINICAL_TABLE_ONE_CAPTION) == 1
    consumed_caption_blocks = [
        (index, block)
        for index, block in enumerate(canonical_page["blocks"])
        if block["primary_element_type"] == "caption"
        and block["omission_reason"] == "consumed_by_relationship"
        and block["text"] == ""
        and block["markdown"] == ""
    ]
    assert len(consumed_caption_blocks) == 1
    assert consumed_caption_blocks[0][1]["suppressed_by_element_id"] == (
        candidate_block["primary_element_id"]
    )
    assert consumed_caption_blocks[0][1]["contributing_element_ids"] == []
    assert consumed_caption_blocks[0][0] < candidate_position
    note_positions = []
    for value in CLINICAL_TABLE_ONE_NOTES:
        matching = [
            (index, block)
            for index, block in enumerate(canonical_page["blocks"])
            if block["primary_element_type"] == "footnote"
            and block["text"] == value
            and block["markdown"] == value
        ]
        assert len(matching) == 1
        assert matching[0][0] > candidate_position
        note_positions.append(matching[0][0])
    assert note_positions == sorted(note_positions)
    assert json.loads(
        ParseResult.model_validate(payload).model_dump_json(
            exclude_none=False
        )
    ) == payload


@pytest.mark.integration
def test_health_notes_and_statlinks_are_visible_grounded_controls() -> None:
    payload = _parse("health-report", True)
    notes = _notes(payload)
    assert sum(note["value"] == HEALTH_UPPER_NOTE for note in notes) == 1
    statlink_targets = {
        link["target"]
        for note in notes
        for link in note.get("links") or []
        if link["target"] in HEALTH_STATLINKS
    }
    assert statlink_targets == HEALTH_STATLINKS
    for target in HEALTH_STATLINKS:
        assert to_markdown(payload).count(target) == 1
        assert payload["canonical_presentation"]["full"]["text"].count(
            target
        ) == 1
    _assert_note_contract(payload)


@pytest.mark.integration
def test_finance_proximity_negative_is_exact_flag_on_and_off() -> None:
    enabled = _parse("finance-10k", True)
    disabled = _parse("finance-10k", False)
    assert _semantic(enabled) == _semantic(disabled)
    assert to_markdown(enabled) == to_markdown(disabled)
    assert not _notes(enabled)
    assert all(
        "source_note_ids" not in item and "footnote_ids" not in item
        for item in _items(enabled)
    )
