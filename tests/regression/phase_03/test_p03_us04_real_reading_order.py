"""Real-document regression coverage for P03-US04."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.config import Settings
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"

CORPUS_SHA256 = {
    "catastrophe-recap": (
        "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
    ),
    "clinical-study": (
        "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2"
    ),
    "component-datasheet": (
        "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4"
    ),
    "esg-metrics": (
        "6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9"
    ),
    "manufacturing-report": (
        "414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f"
    ),
    "purchase-agreement": (
        "00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14"
    ),
    "ny-timetable": (
        "f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30"
    ),
    "clean-energy": (
        "161d513c3ffa53ee3967bac6a7bb420d5d60a2008f79b4f7421b83e9b3a11a7d"
    ),
    "finance-10k": (
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
    ),
}

REVIEWED_CASES = tuple(CORPUS_SHA256)

# The accepted denominator contains 40 page-item pairs here and one nested
# clean-energy source-fragment pair below. These are deliberately explicit:
# geometry or text similarity must never silently expand the denominator.
REVIEWED_PAIR_SLICES = (
    (
        "catastrophe-recap",
        1,
        (
            ("p1-i2", "el-91373a72a9c9e4e6f91d"),
            ("el-91373a72a9c9e4e6f91d", "p1-i3"),
            ("p1-i3", "p1-i4"),
            ("p1-i4", "layout-caption-5a6f8b41401544adeb2a"),
            ("layout-caption-5a6f8b41401544adeb2a", "p1-i5"),
            ("p1-i5", "layout-note-af58a03da292b26ce13f"),
            ("layout-note-af58a03da292b26ce13f", "p1-i6"),
        ),
    ),
    (
        "clinical-study",
        1,
        (
            ("p1-i15", "p1-i4"),
            ("p1-i18", "p1-i4"),
            ("p1-i14", "p1-i19"),
        ),
    ),
    (
        "component-datasheet",
        1,
        (
            ("p1-i3", "p1-i4"),
            ("p1-i4", "p1-i2"),
            ("p1-i2", "p1-i5"),
            ("p1-i5", "p1-i6"),
        ),
    ),
    (
        "esg-metrics",
        1,
        (
            ("p1-i10", "p1-i12"),
            ("p1-i18", "p1-i11"),
            ("p1-i11", "p1-i19"),
            ("p1-i19", "p1-i20"),
        ),
    ),
    (
        "manufacturing-report",
        2,
        (
            ("p2-i1", "layout-caption-c89f2384aa740f5d02ce"),
            ("layout-caption-c89f2384aa740f5d02ce", "p2-i2"),
            ("p2-i2", "p2-i3"),
            ("p2-i3", "layout-caption-daceff6ae2f2ee83c6d0"),
            ("layout-caption-daceff6ae2f2ee83c6d0", "p2-i4"),
            ("p2-i4", "p2-i5"),
        ),
    ),
    (
        "purchase-agreement",
        1,
        (
            ("p1-i9", "p1-i10"),
            ("p1-i10", "p1-i11"),
            ("p1-i11", "p1-i1"),
        ),
    ),
    (
        "clinical-study",
        2,
        (
            ("p2-i3", "p2-i4"),
            ("p2-i4", "p2-i5"),
        ),
    ),
    (
        "ny-timetable",
        2,
        (
            ("p2-i2", "p2-i4"),
            ("p2-i4", "p2-i1"),
        ),
    ),
    (
        "clean-energy",
        1,
        (
            ("p1-i1", "p1-i2"),
            ("p1-i2", "p1-i3"),
            ("p1-i3", "p1-i7"),
            ("p1-i7", "p1-i8"),
        ),
    ),
    (
        "finance-10k",
        1,
        (
            ("p1-i1", "p1-i2"),
            ("p1-i2", "p1-i3"),
            ("p1-i3", "p1-i4"),
            ("p1-i4", "p1-i5"),
            ("p1-i5", "p1-i6"),
        ),
    ),
)

CLEAN_TITLE = "Clean Energy Market Monitor - March 2024"
CLEAN_SECTION = "Overview"
CLEAN_PARENT_BBOX = (56.64, 48.909, 723.129, 11.45)
CLEAN_CHILD_BBOXES = {
    CLEAN_TITLE: (56.64, 52.803, 159.674, 7.556),
    CLEAN_SECTION: (735.36, 48.909, 44.409, 9.36),
}

CLINICAL_OWNED_VALUE = (
    "Data Availability Statement: The data collected for this study involves "
    "sensitive information obtained"
)
CLINICAL_PREDECESSOR_VALUE = f"{CLINICAL_OWNED_VALUE} RESEARCHARTICLE"
CLINICAL_OWNER_BBOX = (36.001, 692.642, 151.206, 17.698)

MANUFACTURING_PAGE_2 = (
    ("p2-i1", (90.325, 37.601, 408.357, 179.583)),
    (
        "layout-caption-c89f2384aa740f5d02ce",
        (139.8, 236.829, 335.154, 9.36),
    ),
    ("p2-i2", (90.0, 257.238, 341.64, 16.907)),
    ("p2-i3", (98.456, 286.447, 417.317, 370.763)),
    (
        "layout-caption-daceff6ae2f2ee83c6d0",
        (117.36, 670.509, 382.912, 9.36),
    ),
    ("p2-i4", (90.0, 691.038, 315.924, 6.893)),
    ("p2-i5", (300.953, 747.252, 12.45, 8.54)),
)

NY_PAGE_2_BBOXES = {
    "p2-i1": (23.432, 22.959, 352.598, 744.924),
    "p2-i2": (32.6, 31.2, 67.8, 13.0),
    "p2-i3": (108.0, 151.2, 19.8, 5.8),
    "p2-i4": (280.8, 31.2, 86.0, 10.2),
}


def _settings(enabled: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=enabled,
    )


def _predecessor_settings() -> Settings:
    """P03-US03 configuration, intentionally omitting the US04 flag."""

    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
    )


@lru_cache(maxsize=None)
def _parse_with_settings(
    case: str,
    settings: Settings,
) -> dict[str, Any]:
    path = CORPUS / f"{case}.pdf"
    return parse_document(
        path.read_bytes(),
        path.name,
        settings,
    ).model_dump(mode="json", exclude_none=False)


def _parse(case: str, enabled: bool) -> dict[str, Any]:
    return _parse_with_settings(case, _settings(enabled))


def _predecessor_parse(case: str) -> dict[str, Any]:
    return _parse_with_settings(case, _predecessor_settings())


def _page(
    payload: Mapping[str, Any],
    page_index: int,
) -> dict[str, Any]:
    matches = [
        page
        for page in payload["pages"]
        if page["page_index"] == page_index
    ]
    assert len(matches) == 1
    return matches[0]


def _item(
    payload: Mapping[str, Any],
    page_index: int,
    item_id: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in _page(payload, page_index)["items"]
        if item["id"] == item_id
    ]
    assert len(matches) == 1
    return matches[0]


def _box_tuple(
    value: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    return (
        float(value["x"]),
        float(value["y"]),
        float(value["width"]),
        float(value["height"]),
    )


def _semantic(payload: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    detached.get("processing", {}).pop("duration_ms", None)
    return detached


def _detached(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _canonical_page(
    payload: Mapping[str, Any],
    page_index: int,
) -> dict[str, Any]:
    matches = [
        page
        for page in payload["canonical_presentation"]["pages"]
        if page["page_index"] == page_index
    ]
    assert len(matches) == 1
    return matches[0]


def _canonical_block(
    payload: Mapping[str, Any],
    page_index: int,
    item_id: str,
) -> dict[str, Any]:
    public_page = _page(payload, page_index)
    canonical_page = _canonical_page(payload, page_index)
    public_ids = [item["id"] for item in public_page["items"]]
    assert len(public_ids) == len(canonical_page["blocks"])
    assert public_ids.count(item_id) == 1
    return canonical_page["blocks"][public_ids.index(item_id)]


def _canonical_blocks_by_key(
    payload: Mapping[str, Any],
) -> dict[tuple[int, str], dict[str, Any]]:
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for public_page in payload["pages"]:
        page_index = public_page["page_index"]
        canonical_page = _canonical_page(payload, page_index)
        public_ids = [item["id"] for item in public_page["items"]]
        assert len(public_ids) == len(canonical_page["blocks"])
        for public_id, block in zip(
            public_ids,
            canonical_page["blocks"],
            strict=True,
        ):
            by_key[(page_index, public_id)] = block
    return by_key


def _comparable_item(
    case: str,
    page_index: int,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    comparable = _detached(item)
    comparable.pop("reading_order", None)
    if (
        case == "clinical-study"
        and page_index == 1
        and item["id"] == "p1-i14"
    ):
        comparable.pop("value", None)
        comparable.pop("md", None)
    if (
        case == "clean-energy"
        and page_index == 1
        and item["id"] == "p1-i1"
    ):
        comparable.pop("value", None)
        comparable.pop("md", None)
        comparable.pop("items", None)
    return comparable


def _comparable_block(
    key: tuple[int, str],
    case: str,
    block: Mapping[str, Any],
) -> dict[str, Any]:
    comparable = _detached(block)
    if (
        case == "clinical-study"
        and key == (1, "p1-i14")
    ) or (
        case == "clean-energy"
        and key == (1, "p1-i1")
    ):
        comparable.pop("markdown", None)
        comparable.pop("text", None)
    if case == "clean-energy" and key == (1, "p1-i1"):
        for field in ("contributing_element_ids", "relationship_ids"):
            comparable[field] = sorted(comparable[field])
    return comparable


def test_real_relationship_order_fixture_custody_is_unchanged() -> None:
    assert len(CORPUS_SHA256) == 9
    for case, expected_sha256 in CORPUS_SHA256.items():
        source = (CORPUS / f"{case}.pdf").read_bytes()
        assert hashlib.sha256(source).hexdigest() == expected_sha256


def test_reviewed_denominator_is_exactly_41_pairs_in_ten_slices() -> None:
    top_level_count = sum(
        len(pairs)
        for _case, _page_index, pairs in REVIEWED_PAIR_SLICES
    )

    assert len(REVIEWED_PAIR_SLICES) == 10
    assert len({case for case, _page, _pairs in REVIEWED_PAIR_SLICES}) == 9
    assert top_level_count == 40
    assert top_level_count + 1 == 41


@pytest.mark.integration
@pytest.mark.parametrize(
    ("case", "page_index", "pairs"),
    REVIEWED_PAIR_SLICES,
    ids=[
        f"{case}-p{page_index}"
        for case, page_index, _pairs in REVIEWED_PAIR_SLICES
    ],
)
def test_fixed_reviewed_page_pair_oracle_passes(
    case: str,
    page_index: int,
    pairs: tuple[tuple[str, str], ...],
) -> None:
    page = _page(_parse(case, True), page_index)
    positions = {
        item["id"]: position
        for position, item in enumerate(page["items"])
    }

    assert len(positions) == len(page["items"])
    for before_id, after_id in pairs:
        assert before_id in positions
        assert after_id in positions
        assert positions[before_id] < positions[after_id]


@pytest.mark.integration
def test_manufacturing_below_captions_keep_side_aware_atomic_order() -> None:
    page = _page(_parse("manufacturing-report", True), 2)
    expected_ids = [item_id for item_id, _bbox in MANUFACTURING_PAGE_2]
    by_id = {item["id"]: item for item in page["items"]}
    positions = {
        item["id"]: position
        for position, item in enumerate(page["items"])
    }

    assert [item["id"] for item in page["items"]] == expected_ids
    for item_id, expected_bbox in MANUFACTURING_PAGE_2:
        assert _box_tuple(by_id[item_id]["bbox"]) == expected_bbox

    for owner_id, caption_id, source_id in (
        (
            "p2-i1",
            "layout-caption-c89f2384aa740f5d02ce",
            "p2-i2",
        ),
        (
            "p2-i3",
            "layout-caption-daceff6ae2f2ee83c6d0",
            "p2-i4",
        ),
    ):
        owner = by_id[owner_id]
        caption = by_id[caption_id]
        owner_box = _box_tuple(owner["bbox"])
        caption_box = _box_tuple(caption["bbox"])

        assert caption["type"] == "caption"
        assert caption["caption_of"] == owner_id
        assert caption_id in (owner.get("caption_ids") or [])
        assert caption_id in (owner.get("caption_of") or [])
        assert caption_box[1] >= owner_box[1] + owner_box[3]
        assert positions[caption_id] == positions[owner_id] + 1
        assert positions[source_id] == positions[caption_id] + 1


@pytest.mark.integration
def test_clinical_owner_fails_closed_without_source_partition_evidence() -> None:
    enabled_payload = _parse("clinical-study", True)
    disabled_payload = _parse("clinical-study", False)
    enabled = _item(enabled_payload, 1, "p1-i14")
    disabled = _item(disabled_payload, 1, "p1-i14")
    canonical = _canonical_block(enabled_payload, 1, "p1-i14")

    assert disabled["value"] == CLINICAL_PREDECESSOR_VALUE
    assert disabled["md"] == CLINICAL_PREDECESSOR_VALUE
    assert enabled["value"] == CLINICAL_PREDECESSOR_VALUE
    assert enabled["md"] == CLINICAL_PREDECESSOR_VALUE
    assert _box_tuple(enabled["bbox"]) == CLINICAL_OWNER_BBOX
    assert enabled["bbox"] == disabled["bbox"]
    assert enabled["source"] == disabled["source"] == "ocr"
    assert enabled["confidence"] == disabled["confidence"]
    assert "RESEARCHARTICLE" in canonical["markdown"]
    assert "RESEARCHARTICLE" in canonical["text"]
    assert CLINICAL_OWNED_VALUE in canonical["markdown"]
    assert CLINICAL_OWNED_VALUE in canonical["text"]


@pytest.mark.integration
def test_clean_energy_nested_source_order_rebuilds_parent_and_canonical() -> None:
    enabled_payload = _parse("clean-energy", True)
    disabled_payload = _parse("clean-energy", False)
    enabled = _item(enabled_payload, 1, "p1-i1")
    disabled = _item(disabled_payload, 1, "p1-i1")
    canonical = _canonical_block(enabled_payload, 1, "p1-i1")

    assert [child["value"] for child in disabled["items"]] == [
        CLEAN_SECTION,
        CLEAN_TITLE,
    ]
    assert [child["value"] for child in enabled["items"]] == [
        CLEAN_TITLE,
        CLEAN_SECTION,
    ]
    assert _box_tuple(enabled["bbox"]) == CLEAN_PARENT_BBOX
    assert enabled["value"] == f"{CLEAN_TITLE}\n{CLEAN_SECTION}"
    assert enabled["md"] == f"{CLEAN_TITLE}\n\n{CLEAN_SECTION}"
    for child in enabled["items"]:
        assert _box_tuple(child["bbox"]) == CLEAN_CHILD_BBOXES[
            child["value"]
        ]

    # The same two records survive byte-for-byte; only their array order moves.
    assert sorted(
        (_detached(child) for child in enabled["items"]),
        key=lambda child: child["value"],
    ) == sorted(
        (_detached(child) for child in disabled["items"]),
        key=lambda child: child["value"],
    )
    for field in ("markdown", "text"):
        assert canonical[field].count(CLEAN_TITLE) == 1
        assert canonical[field].count(CLEAN_SECTION) == 1
        assert canonical[field].index(CLEAN_TITLE) < canonical[field].index(
            CLEAN_SECTION
        )


@pytest.mark.integration
def test_timetable_prefix_is_bounded_and_page_three_is_unchanged() -> None:
    enabled_payload = _parse("ny-timetable", True)
    disabled_payload = _parse("ny-timetable", False)
    enabled_page_2 = _page(enabled_payload, 2)
    enabled_page_3 = _page(enabled_payload, 3)
    disabled_page_3 = _page(disabled_payload, 3)
    page_2_ids = [item["id"] for item in enabled_page_2["items"]]
    page_2_by_id = {
        item["id"]: item
        for item in enabled_page_2["items"]
    }

    assert page_2_ids == ["p2-i2", "p2-i4", "p2-i1", "p2-i3", "p2-i5"]
    assert page_2_by_id["p2-i2"]["value"] == "Weekdays"
    assert page_2_by_id["p2-i4"]["value"] == "to The Bronx"
    assert page_2_by_id["p2-i3"]["value"] == "ew"
    assert page_2_by_id["p2-i3"]["confidence"] < 0.80
    for item_id, expected_bbox in NY_PAGE_2_BBOXES.items():
        assert _box_tuple(page_2_by_id[item_id]["bbox"]) == expected_bbox

    assert enabled_page_3 == disabled_page_3
    assert _item(enabled_payload, 3, "p3-i1") == _item(
        disabled_payload,
        3,
        "p3-i1",
    )
    assert _canonical_page(enabled_payload, 3) == _canonical_page(
        disabled_payload,
        3,
    )


@pytest.mark.integration
@pytest.mark.parametrize("case", REVIEWED_CASES)
def test_ids_geometry_and_evidence_are_keyed_immutable_except_two_corrections(
    case: str,
) -> None:
    enabled = _parse(case, True)
    disabled = _parse(case, False)

    enabled_document = _detached(enabled)
    disabled_document = _detached(disabled)
    for payload in (enabled_document, disabled_document):
        payload.pop("pages", None)
        payload.pop("canonical_presentation", None)
        payload.get("processing", {}).pop("duration_ms", None)
    assert enabled_document == disabled_document

    enabled_pages = {
        page["page_index"]: page
        for page in enabled["pages"]
    }
    disabled_pages = {
        page["page_index"]: page
        for page in disabled["pages"]
    }
    assert set(enabled_pages) == set(disabled_pages)
    for page_index, enabled_page in enabled_pages.items():
        disabled_page = disabled_pages[page_index]
        assert {
            key: value
            for key, value in enabled_page.items()
            if key != "items"
        } == {
            key: value
            for key, value in disabled_page.items()
            if key != "items"
        }

        enabled_items = {
            item["id"]: item
            for item in enabled_page["items"]
        }
        disabled_items = {
            item["id"]: item
            for item in disabled_page["items"]
        }
        assert len(enabled_items) == len(enabled_page["items"])
        assert len(disabled_items) == len(disabled_page["items"])
        assert set(enabled_items) == set(disabled_items)
        for item_id, enabled_item in enabled_items.items():
            disabled_item = disabled_items[item_id]
            assert _comparable_item(
                case,
                page_index,
                enabled_item,
            ) == _comparable_item(
                case,
                page_index,
                disabled_item,
            )

    enabled_blocks = _canonical_blocks_by_key(enabled)
    disabled_blocks = _canonical_blocks_by_key(disabled)
    assert set(enabled_blocks) == set(disabled_blocks)
    for key, enabled_block in enabled_blocks.items():
        assert _comparable_block(
            key,
            case,
            enabled_block,
        ) == _comparable_block(
            key,
            case,
            disabled_blocks[key],
        )


@pytest.mark.integration
def test_finance_is_exact_flag_on_and_off_content_control() -> None:
    enabled = _parse("finance-10k", True)
    disabled = _parse("finance-10k", False)

    assert _semantic(enabled) == _semantic(disabled)
    assert to_markdown(enabled) == to_markdown(disabled)


@pytest.mark.integration
@pytest.mark.parametrize("case", REVIEWED_CASES)
def test_reading_order_is_contiguous_unique_and_matches_canonical_markdown(
    case: str,
) -> None:
    payload = _parse(case, True)
    predecessor = _parse(case, False)
    all_item_ids: list[str] = []

    for page in payload["pages"]:
        items = page["items"]
        item_ids = [item["id"] for item in items]
        all_item_ids.extend(item_ids)
        assert [item["reading_order"] for item in items] == list(
            range(len(items))
        )
        assert len(item_ids) == len(set(item_ids))

        canonical_page = _canonical_page(payload, page["page_index"])
        predecessor_page = _page(predecessor, page["page_index"])
        predecessor_canonical = _canonical_page(
            predecessor,
            page["page_index"],
        )
        predecessor_ids = [
            item["id"]
            for item in predecessor_page["items"]
        ]
        assert len(predecessor_ids) == len(predecessor_canonical["blocks"])
        primary_id_by_public_id = {
            public_id: block["primary_element_id"]
            for public_id, block in zip(
                predecessor_ids,
                predecessor_canonical["blocks"],
                strict=True,
            )
        }
        assert [
            block["primary_element_id"]
            for block in canonical_page["blocks"]
        ] == [
            primary_id_by_public_id[item_id]
            for item_id in item_ids
        ]

    assert len(all_item_ids) == len(set(all_item_ids))
    assert to_markdown(payload) == payload["canonical_presentation"]["full"][
        "markdown"
    ]


@pytest.mark.integration
@pytest.mark.parametrize("case", REVIEWED_CASES)
def test_flag_off_is_the_exact_us03_predecessor(case: str) -> None:
    disabled_settings = _settings(False)
    predecessor_settings = _predecessor_settings()
    disabled = _parse(case, False)
    predecessor = _predecessor_parse(case)

    assert Settings().layout_relationship_order_enabled is False
    assert disabled_settings == predecessor_settings
    assert _semantic(disabled) == _semantic(predecessor)
    assert to_markdown(disabled) == to_markdown(predecessor)
    assert "relationship_order_" not in json.dumps(
        disabled,
        ensure_ascii=False,
        sort_keys=True,
    )
