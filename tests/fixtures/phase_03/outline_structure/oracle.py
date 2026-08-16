"""Immutable source-grounded oracle for P03-US07.

Coordinates use top-left PDF points. ``value_sha256`` binds the exact
predecessor item value; the outline overlay must never rewrite that value.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


POLICY_ID = "p03-outline-structure-v1"

SOURCE_IDENTITIES: dict[str, dict[str, Any]] = {
    "component-datasheet": {
        "path": "benchmark-expertmodeldata/component-datasheet.pdf",
        "size_bytes": 329_199,
        "sha256": ("5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4"),
        "page_count": 3,
        "reviewed_page_index": 1,
    },
    "settlement-agreement": {
        "path": "benchmark-expertmodeldata/settlement-agreement.pdf",
        "size_bytes": 164_483,
        "sha256": ("adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc"),
        "page_count": 1,
        "reviewed_page_index": 1,
    },
}


def _box(
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict[str, float | str]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }


COMPONENT_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "oracle_id": "component-features",
        "kind": "unordered",
        "ordered": False,
        "page_index": 1,
        "nodes": (
            {
                "marker": "•",
                "level": 0,
                "ordinal": 1,
                "parent_index": None,
                "value_sha256": "b55e126d230979a3008a78d5109b5d89f26385bab6e27dfb942e9d0ce6685471",
                "marker_bbox": _box(124.336, 459.206, 4.704, 14.0),
                "item_bbox": _box(124.336, 459.206, 149.32, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 2,
                "parent_index": None,
                "value_sha256": "c284fcaef506dc131e75c78b8e9032e00cea79167b988f94223188c57cc9a799",
                "marker_bbox": _box(124.336, 477.598, 4.704, 14.0),
                "item_bbox": _box(124.336, 477.598, 262.624, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 3,
                "parent_index": None,
                "value_sha256": "21d4d826208b6a8b494db6c71e75c145593fefe605a78f471325d5fae8ee5d2a",
                "marker_bbox": _box(124.336, 495.99, 4.704, 14.0),
                "item_bbox": _box(124.336, 495.99, 344.272, 14.0),
            },
            {
                "marker": "◦",
                "level": 1,
                "ordinal": 1,
                "parent_index": 2,
                "value_sha256": "cc95904fef44a12df67a40a3e0783a44153ace1107db943da98c93db4a8d0c55",
                "marker_bbox": _box(140.502, 514.382, 6.538, 14.0),
                "item_bbox": _box(140.502, 514.382, 220.354, 14.0),
            },
            {
                "marker": "◦",
                "level": 1,
                "ordinal": 2,
                "parent_index": 2,
                "value_sha256": "ab786c1e0bcc5b66ac5dc3ce9022f9051ee8a0442a7233e9f4a92097927c842d",
                "marker_bbox": _box(140.502, 532.774, 6.538, 14.0),
                "item_bbox": _box(140.502, 532.774, 176.05, 14.0),
            },
            {
                "marker": "◦",
                "level": 1,
                "ordinal": 3,
                "parent_index": 2,
                "value_sha256": "dbf4088fad56acf75bd564714d67c2d5f662b3abc09be2410daec79c0157ad3b",
                "marker_bbox": _box(140.502, 551.166, 6.538, 14.0),
                "item_bbox": _box(140.502, 551.166, 142.978, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 4,
                "parent_index": None,
                "value_sha256": "9a66687d60287ab642138f16dcae9f9f00ca2efdb85a898f73dcc35e59d143fc",
                "marker_bbox": _box(124.336, 569.558, 4.704, 14.0),
                "item_bbox": _box(124.336, 569.558, 150.824, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 5,
                "parent_index": None,
                "value_sha256": "9285b4b23049847ab1dc190dc5b0f2dfff9458c9df74b24af4721a97dc1179f3",
                "marker_bbox": _box(124.336, 587.95, 4.704, 14.0),
                "item_bbox": _box(124.336, 587.95, 189.688, 14.0),
            },
            {
                "marker": "◦",
                "level": 1,
                "ordinal": 1,
                "parent_index": 7,
                "value_sha256": "e44ed040691e4d7188c99d2f8ea2717029afc417dd72f788bca27b23888008f5",
                "marker_bbox": _box(140.502, 606.342, 6.538, 14.0),
                "item_bbox": _box(140.502, 606.342, 328.666, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 6,
                "parent_index": None,
                "value_sha256": "5226ded6df14ce71d16547d69ab32fd4c51453fb69faa6f090a09d20dece77af",
                "marker_bbox": _box(124.336, 624.734, 4.704, 14.0),
                "item_bbox": _box(124.336, 624.734, 142.424, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 7,
                "parent_index": None,
                "value_sha256": "1d66b782bd33deececf9a1f25f2ed7774f9f9bb84f1df2f4cab05eecfa846aa7",
                "marker_bbox": _box(124.336, 643.126, 4.704, 14.0),
                "item_bbox": _box(124.336, 643.126, 223.192, 14.0),
            },
        ),
    },
    {
        "oracle_id": "component-headline-features",
        "kind": "unordered",
        "ordered": False,
        "page_index": 1,
        "nodes": (
            {
                "marker": "•",
                "level": 0,
                "ordinal": 1,
                "parent_index": None,
                "value_sha256": "62a5e0cb64e083f1210afa3d9e8375b02d563405d0b010c309f12c83a199c10f",
                "marker_bbox": _box(124.336, 679.91, 4.704, 14.0),
                "item_bbox": _box(124.336, 679.91, 145.696, 14.0),
            },
            {
                "marker": "◦",
                "level": 1,
                "ordinal": 1,
                "parent_index": 0,
                "value_sha256": "c82ea213c8dc8f9eb98e8045fe1dc417020803e35329a034c3c8a7aaebe58dce",
                "marker_bbox": _box(140.502, 698.302, 6.538, 14.0),
                "item_bbox": _box(140.502, 698.302, 162.85, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 2,
                "parent_index": None,
                "value_sha256": "ea4191e9a02f36e38fe2a0dbfb584adf5b73b31308d257cbc41bdefb6a416fdc",
                "marker_bbox": _box(124.336, 716.694, 4.704, 14.0),
                "item_bbox": _box(124.336, 716.694, 159.168, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 3,
                "parent_index": None,
                "value_sha256": "624b7bdb5951def578d644b294332a6808849b0f99134e24bb034f52aa39a2b4",
                "marker_bbox": _box(124.336, 735.086, 4.704, 14.0),
                "item_bbox": _box(124.336, 735.086, 277.92, 14.0),
            },
            {
                "marker": "•",
                "level": 0,
                "ordinal": 4,
                "parent_index": None,
                "value_sha256": "f2afd8e5e87956f298b4be59d8c5103399ee058b8ec892456777da57f7039dd1",
                "marker_bbox": _box(124.336, 753.478, 4.704, 14.0),
                "item_bbox": _box(124.336, 753.478, 156.656, 14.0),
            },
        ),
    },
)

SETTLEMENT_GROUP: dict[str, Any] = {
    "oracle_id": "settlement-lettered-clauses",
    "kind": "legal",
    "ordered": True,
    "page_index": 1,
    "nodes": (
        {
            "marker": "a.",
            "level": 0,
            "ordinal": 1,
            "parent_index": None,
            "value_sha256": "343abd45d8ed98988bfd294a72285829cd98299484d5deddc5526830edc68840",
            "marker_bbox": _box(180.0, 169.644, 8.28, 12.0),
            "item_bbox": _box(144.0, 170.016, 399.0, 134.528),
        },
        {
            "marker": "b.",
            "level": 0,
            "ordinal": 2,
            "parent_index": None,
            "value_sha256": "76ecca150c2376f296f7b24dd4c3bd09cfd1be40482052e9a2180e2bb8b79018",
            "marker_bbox": _box(180.0, 319.644, 9.0, 12.0),
            "item_bbox": _box(144.0, 320.016, 402.0, 65.489),
        },
        {
            "marker": "c.",
            "level": 0,
            "ordinal": 3,
            "parent_index": None,
            "value_sha256": "29c9ebde6676c9b77d24cb60e3c6122d1e518466b4fd226332c5ddb265ce3903",
            "marker_bbox": _box(180.0, 598.524, 8.28, 12.0),
            "item_bbox": _box(144.0, 598.896, 399.0, 106.889),
        },
    ),
    "continuations": (
        {
            "source_type": "table",
            "target_node_index": 1,
            "bbox": _box(144.988, 398.141, 402.656, 172.63),
        },
    ),
}

COMPONENT_BODY_TEXTS: tuple[str, ...] = (
    "RP2040 microcontroller with 2MB Flash",
    "Micro-USB B port for power and data (and for reprogramming the Flash)",
    "40 pin 21 × 51 'DIP' style 1mm thick PCB with 0.1\" through-hole pins also with edge castellations",
    "Exposes 26 multi-function 3.3V General Purpose I/O (GPIO)",
    "23 GPIO are digital-only and 3 are ADC capable",
    "Can be surface mounted as a module",
    "3-pin ARM Serial Wire Debug (SWD) port",
    "Simple yet highly flexible power supply architecture",
    "Various options for easily powering the unit from micro-USB, external supplies or batteries",
    "High quality, low cost, high availability",
    "Comprehensive SDK, software examples and documentation",
    "Dual-core cortex M0+ at up to 133MHz",
    "On-chip PLL allows variable core frequency",
    "264kB multi-bank high performance SRAM",
    "External Quad-SPI Flash with eXecute In Place (XIP) and 16kB on-chip cache",
    "High performance full-crossbar bus fabric",
)

SETTLEMENT_PREDECESSOR_VALUES: tuple[str, ...] = (
    "a. A Settling State is eligible for Incentive Payment D if there has been no Later Litigating Subdivision (for purposes of Incentive Payment D, Later Litigating Subdivisions are limited to (i) a Primary Subdivision; (ii) a school district with a K-12 student enrollment of at least 25,000 or 0.10% of the State's population, whichever is greater; (iii) a health district or hospital district that has at least one hundred twenty-five (125) hospital beds in one or more hospitals rendering services in that district; and (iv) Primary Fire Districts) in that State that has had a Claim against a Released Entity survive more than six (6) months after denial in whole or in part of a Threshold Motion as of July 15 of Payment Years 3 to 6 (each, an ' Incentive Payment D Look-Back Date ').",
    "b. To the extent a Settling State achieves a Percentage of Incentive BC Subdivision Population of 95% or above as of the Third Subdivision Participation Date, the level of Incentive Payment D is reduced according to the schedule below. The following portions of Incentive Payment D are paid in equal installments in Payment Years 3 through 6:",
    "c. The Settlement Fund Administrator shall determine a Settling State's eligibility for Incentive Payment D as of the Incentive Payment D LookBack Date in Payment Years 3 through 6. If a Later Litigating Subdivision's lawsuit in that Settling State survives more than six (6) months after denial in whole or in part of a Threshold Motion, that State shall not be eligible for Incentive Payment D for the Payment Year in which that occurs and any subsequent Payment Year. Prior to the Incentive Payment D Look-Back Date in Payment Years 3 through 6, Walmart may provide the Settlement Fund Administrator and the",
)

_COMPONENT_GROUP_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "page_id": "page-56fbfad4aaa8ae5e00b9",
        "coordinate_system_id": "coords-c9b421b45c07b39c22a2",
        "anchor_public_item_id": "p1-i7",
        "anchor_public_path": ("pages", 0, "items", 6),
        "anchor_element_id": "el-1289edf5af4563b83dac",
        "anchor_bbox_id": "box-12c3641948c99ef22fab",
        "anchor_evidence_ids": ("ev-0cc60c0a640b40d29f59",),
        "group_bbox": _box(124.336, 459.206, 344.832, 197.92),
        "element_ids": (
            "el-185f6e1b729c3bee9602",
            "el-62c781dd61fcab1d9620",
            "el-ff26737553490f5d42ce",
            "el-dd0e09c88dd5b0382270",
            "el-e536df13a4e6d515c06d",
            "el-179576f1b747fc5e5665",
            "el-c7301dcb552f6aab4891",
            "el-0571a31b821d530c4332",
            "el-082b5296d08c634c7002",
            "el-ec2ffcbf5ceb358478ab",
            "el-b8753984f7ef4145da04",
        ),
        "bbox_ids": (
            "box-104cd2e7419dfce29171",
            "box-e5521f3a662bf4c5bee4",
            "box-ac62393075bf6bcd3613",
            "box-253515d89e9665932860",
            "box-5825f9172b599adaaca5",
            "box-53bd09a2d5e46a22d924",
            "box-22b88a962ff7cfe88d2f",
            "box-80d1e9b58be9794c1180",
            "box-8386abfb77ea6575d9d6",
            "box-0b982e6fc36a08af5220",
            "box-d4ec5f208bacf596a01c",
        ),
        "evidence_ids": (
            "ev-8345c8efa0bf077404e8",
            "ev-70fbf6507e8d77c221f9",
            "ev-181de217091b68c00a99",
            "ev-da944057a4e07ffb49ec",
            "ev-6ed9d10b943979e55d4e",
            "ev-9f77edc0531740ae90a2",
            "ev-ce647d902b271f1f7f76",
            "ev-27c28e1faf2fba764c54",
            "ev-2261600df333df1af21c",
            "ev-0642d296231afdae66a9",
            "ev-19d70c13383cc8d72118",
        ),
        "marker_word_indexes": (55, 61, 74, 91, 100, 110, 118, 126, 134, 148, 155),
    },
    {
        "page_id": "page-56fbfad4aaa8ae5e00b9",
        "coordinate_system_id": "coords-c9b421b45c07b39c22a2",
        "anchor_public_item_id": "p1-i9",
        "anchor_public_path": ("pages", 0, "items", 8),
        "anchor_element_id": "el-8a484763409f048c97ec",
        "anchor_bbox_id": "box-a47a986072224a2fbe4b",
        "anchor_evidence_ids": ("ev-352a79cb10336ea02e08",),
        "group_bbox": _box(124.336, 679.91, 277.92, 87.568),
        "element_ids": (
            "el-932b700666547882290c",
            "el-00f71346e5007ce0cee1",
            "el-5654992cf8f85a3c9e7b",
            "el-0ad7eb3ecc6b32171483",
            "el-e5c552e0ca8298ce0d49",
        ),
        "bbox_ids": (
            "box-b9726eae90a9c955846b",
            "box-6ad930b8c6892514f756",
            "box-4e6f77ab1a611b800eb9",
            "box-767cd496f9f81060abc7",
            "box-0972bb615cd07e3c1b77",
        ),
        "evidence_ids": (
            "ev-67b7fb7d5a51a0a06b97",
            "ev-09ce4c31e824e30915ee",
            "ev-be883ee7c9ee688466f3",
            "ev-93f2f8b9178a1d893d6c",
            "ev-0a1a0b71bbbc1fa60a76",
        ),
        "marker_word_indexes": (179, 187, 194, 200, 213),
    },
)

_SETTLEMENT_SOURCE: dict[str, Any] = {
    "page_id": "page-a04cad0ab8f1a940efb1",
    "coordinate_system_id": "coords-f6bdfb6e5958b1c5241b",
    "anchor_public_item_id": "p1-i2",
    "anchor_public_path": ("pages", 0, "items", 1),
    "anchor_element_id": "el-dcfe62aad69afbe4fda8",
    "anchor_bbox_id": "box-00c7494200ddfd028056",
    "anchor_evidence_ids": ("ev-f51d0fac64522c75224a",),
    "group_bbox": _box(144.0, 169.644, 403.644, 536.141),
    "public_item_ids": ("p1-i2", "p1-i3", "p1-i5"),
    "public_paths": (
        ("pages", 0, "items", 1),
        ("pages", 0, "items", 2),
        ("pages", 0, "items", 4),
    ),
    "element_ids": (
        "el-dcfe62aad69afbe4fda8",
        "el-e4e770871be0000fc23d",
        "el-6c344f85277044c09915",
    ),
    "bbox_ids": (
        "box-00c7494200ddfd028056",
        "box-9a70e25adddf8008bc5f",
        "box-e1cd03ac950ba3628a04",
    ),
    "evidence_ids": (
        "ev-f51d0fac64522c75224a",
        "ev-dc259502bc8e7683c814",
        "ev-a54269601923c8a799bd",
    ),
    "marker_word_indexes": (69, 203, 340),
    "continuation_public_item_id": "p1-i4",
    "continuation_public_path": ("pages", 0, "items", 3),
    "continuation_element_id": "el-881f2919b5021bb5ee27",
    "continuation_bbox_id": "box-d033aa11daa38dd59bbe",
    "continuation_evidence_ids": ("ev-2d050685475ab551ef9b",),
}


def _stable_id(prefix: str, *parts: object) -> str:
    encoded = json.dumps(
        parts,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _enrich_group(
    group: dict[str, Any],
    *,
    case_id: str,
    source: dict[str, Any],
    predecessor_values: tuple[str, ...],
    value_offset: int = 0,
) -> None:
    source_sha256 = SOURCE_IDENTITIES[case_id]["sha256"]
    group_id = _stable_id(
        "outline-group",
        POLICY_ID,
        source_sha256,
        group["page_index"],
        source["anchor_element_id"],
        tuple(source["element_ids"]),
        (
            (source["continuation_element_id"],)
            if source.get("continuation_element_id") is not None
            else ()
        ),
    )
    group_element_id = _stable_id("outline-element", group_id)
    group_bbox_id = _stable_id("outline-bbox", group_id, "group")
    group_evidence_id = _stable_id("outline-evidence", group_id, "group")
    group.update(
        {
            "id": group_id,
            "element_id": group_element_id,
            "sequence_kind": group["kind"],
            "marker_style": (
                "bullet" if group["kind"] == "unordered" else "lower_alpha"
            ),
            "page_id": source["page_id"],
            "coordinate_system_id": source["coordinate_system_id"],
            "anchor_element_id": source["anchor_element_id"],
            "anchor_public_item_id": source["anchor_public_item_id"],
            "anchor_public_path": source["anchor_public_path"],
            "anchor_bbox_id": source["anchor_bbox_id"],
            "anchor_evidence_ids": source["anchor_evidence_ids"],
            "group_bbox": source["group_bbox"],
            "group_bbox_id": group_bbox_id,
            "evidence_id": group_evidence_id,
            "bbox_record": {
                "id": group_bbox_id,
                "coordinate_system_id": source["coordinate_system_id"],
                "x": source["group_bbox"]["x"],
                "y": source["group_bbox"]["y"],
                "width": source["group_bbox"]["width"],
                "height": source["group_bbox"]["height"],
                "role": "region",
            },
            "evidence_record": {
                "id": group_evidence_id,
                "element_id": group_element_id,
                "method": "derived",
                "bbox_id": group_bbox_id,
                "value": {"policy_id": POLICY_ID, "group_id": group_id},
                "confidence": {
                    "scope": "evidence",
                    "score": None,
                    "unavailable_reason": "not_calibrated",
                },
                "metadata": {
                    "derivation": "validated_outline_group_union",
                    "policy_id": POLICY_ID,
                    "group_id": group_id,
                    "source_element_id": source["anchor_element_id"],
                },
            },
            "source_method": "native",
            "confidence": {
                "scope": "evidence",
                "score": None,
                "unavailable_reason": "not_calibrated",
            },
            "concern_codes": (),
        }
    )

    nodes = list(group["nodes"])
    public_item_ids = source.get("public_item_ids")
    public_paths = source.get("public_paths")
    for index, node in enumerate(nodes):
        raw_marker = node.pop("marker")
        predecessor_value = predecessor_values[value_offset + index]
        ownership = "separate" if case_id == "component-datasheet" else "value_prefix"
        separator = "" if ownership == "separate" else " "
        body_text = (
            predecessor_value
            if ownership == "separate"
            else predecessor_value.removeprefix(raw_marker + separator)
        )
        assert (
            hashlib.sha256(predecessor_value.encode()).hexdigest()
            == node["value_sha256"]
        )
        assert (
            predecessor_value == body_text
            if ownership == "separate"
            else raw_marker + separator + body_text == predecessor_value
        )
        element_id = source["element_ids"][index]
        item_id = _stable_id("outline-item", group_id, element_id)
        marker_evidence_id = _stable_id(
            "outline-evidence",
            group_id,
            element_id,
            "marker",
            source["marker_word_indexes"][index],
        )
        marker_bbox_id = _stable_id(
            "outline-bbox",
            group_id,
            element_id,
            "marker",
            source["marker_word_indexes"][index],
        )
        public_item_id = (
            source["anchor_public_item_id"]
            if public_item_ids is None
            else public_item_ids[index]
        )
        public_path = (
            (*source["anchor_public_path"], "items", index)
            if public_paths is None
            else public_paths[index]
        )
        node.update(
            {
                "id": item_id,
                "element_id": element_id,
                "group_id": group_id,
                "page_id": source["page_id"],
                "source_public_item_id": public_item_id,
                "source_public_path": public_path,
                "source_bbox_id": source["bbox_ids"][index],
                "source_evidence_ids": (source["evidence_ids"][index],),
                "source_object": {
                    "reader": "pdfplumber",
                    "page_index": group["page_index"],
                    "word_index": source["marker_word_indexes"][index],
                },
                "sequence_kind": group["kind"],
                "marker_style": (
                    "bullet" if group["kind"] == "unordered" else "lower_alpha"
                ),
                "raw_marker": raw_marker,
                "legacy_marker": predecessor_value if ownership == "separate" else None,
                "marker_ownership": ownership,
                "marker_separator": separator,
                "body_text": body_text,
                "predecessor_value": predecessor_value,
                "parent_id": None,
                "marker_evidence_id": marker_evidence_id,
                "marker_bbox_id": marker_bbox_id,
                "marker_bbox_record": {
                    "id": marker_bbox_id,
                    "coordinate_system_id": source["coordinate_system_id"],
                    "x": node["marker_bbox"]["x"],
                    "y": node["marker_bbox"]["y"],
                    "width": node["marker_bbox"]["width"],
                    "height": node["marker_bbox"]["height"],
                    "role": "annotation",
                },
                "marker_evidence_record": {
                    "id": marker_evidence_id,
                    "element_id": element_id,
                    "method": "native",
                    "bbox_id": marker_bbox_id,
                    "value": raw_marker,
                    "confidence": {
                        "scope": "evidence",
                        "score": None,
                        "unavailable_reason": "not_calibrated",
                    },
                    "metadata": {
                        "policy_id": POLICY_ID,
                        "group_id": group_id,
                        "item_id": item_id,
                        "reader": "pdfplumber",
                        "page_index": group["page_index"],
                        "word_index": source["marker_word_indexes"][index],
                    },
                },
                "source_method": "native",
                "confidence": {
                    "scope": "evidence",
                    "score": None,
                    "unavailable_reason": "not_calibrated",
                },
                "concern_codes": (),
                "relationship_ids": [],
            }
        )

    for node in nodes:
        parent_index = node["parent_index"]
        node["parent_id"] = None if parent_index is None else nodes[parent_index]["id"]

    relationships: list[dict[str, Any]] = []

    def add_relationship(
        relationship_type: str,
        source_id: str,
        target_id: str,
        evidence_ids: tuple[str, ...],
        **metadata: Any,
    ) -> str:
        relationship_id = _stable_id(
            "outline-relationship",
            POLICY_ID,
            group_id,
            relationship_type,
            source_id,
            target_id,
        )
        relationships.append(
            {
                "id": relationship_id,
                "type": relationship_type,
                "source_id": source_id,
                "target_id": target_id,
                "evidence_ids": evidence_ids,
                "metadata": {
                    "canonical_inert": True,
                    "outline_group_id": group_id,
                    "outline_policy": POLICY_ID,
                    **metadata,
                },
            }
        )
        for node in nodes:
            if node["element_id"] in {source_id, target_id}:
                node["relationship_ids"].append(relationship_id)
        return relationship_id

    for node in nodes:
        add_relationship(
            "contains",
            group_element_id,
            node["element_id"],
            (group_evidence_id, node["marker_evidence_id"]),
        )
    for node in nodes:
        if node["parent_index"] is not None:
            parent = nodes[node["parent_index"]]
            add_relationship(
                "outline_parent_of",
                parent["element_id"],
                node["element_id"],
                (parent["marker_evidence_id"], node["marker_evidence_id"]),
            )
    sibling_indexes: dict[int | None, list[int]] = {}
    for index, node in enumerate(nodes):
        sibling_indexes.setdefault(node["parent_index"], []).append(index)
    continuation_by_target = {
        entry["target_node_index"]: entry for entry in group.get("continuations") or ()
    }
    for indexes in sibling_indexes.values():
        for first_index, second_index in zip(indexes, indexes[1:], strict=False):
            first = nodes[first_index]
            second = nodes[second_index]
            continuation = continuation_by_target.get(first_index)
            intervening_ids = (
                [source["continuation_element_id"]] if continuation is not None else []
            )
            add_relationship(
                "outline_next",
                first["element_id"],
                second["element_id"],
                (first["marker_evidence_id"], second["marker_evidence_id"]),
                intervening_element_ids=intervening_ids,
            )
    for continuation in group.get("continuations") or ():
        target = nodes[continuation["target_node_index"]]
        continuation_id = _stable_id(
            "outline-continuation",
            group_id,
            source["continuation_element_id"],
            target["id"],
        )
        continuation.update(
            {
                "id": continuation_id,
                "group_id": group_id,
                "source_public_item_id": source["continuation_public_item_id"],
                "source_public_path": source["continuation_public_path"],
                "element_id": source["continuation_element_id"],
                "bbox_id": source["continuation_bbox_id"],
                "source_evidence_ids": source["continuation_evidence_ids"],
                "target_node_id": target["id"],
                "source_method": "native",
                "confidence": {
                    "scope": "evidence",
                    "score": None,
                    "unavailable_reason": "not_calibrated",
                },
                "concern_codes": (),
                "relationship_ids": [],
            }
        )
        relationship_id = add_relationship(
            "outline_continuation_of",
            source["continuation_element_id"],
            target["element_id"],
            (*source["continuation_evidence_ids"], target["marker_evidence_id"]),
            interstitial_kind=continuation["source_type"],
        )
        continuation["relationship_ids"].append(relationship_id)
        continuation["relationship_ids"] = tuple(continuation["relationship_ids"])

    for node in nodes:
        node["relationship_ids"] = tuple(node["relationship_ids"])
        node["incident_relationship_count"] = len(node["relationship_ids"])
    group["nodes"] = tuple(nodes)
    group["relationships"] = tuple(relationships)
    group["relationship_ids"] = tuple(
        relationship["id"] for relationship in relationships
    )
    group["member_item_ids"] = tuple(node["id"] for node in nodes)
    group["member_element_ids"] = tuple(node["element_id"] for node in nodes)
    group["continuation_element_ids"] = tuple(
        entry["element_id"] for entry in group.get("continuations") or ()
    )
    group["continuation_ids"] = tuple(
        entry["id"] for entry in group.get("continuations") or ()
    )
    group["relationship_cardinality"] = {
        relationship_type: sum(
            relationship["type"] == relationship_type for relationship in relationships
        )
        for relationship_type in (
            "contains",
            "outline_parent_of",
            "outline_next",
            "outline_continuation_of",
        )
    }


_component_value_offset = 0
for _group, _source in zip(COMPONENT_GROUPS, _COMPONENT_GROUP_SOURCES, strict=True):
    _enrich_group(
        _group,
        case_id="component-datasheet",
        source=_source,
        predecessor_values=COMPONENT_BODY_TEXTS,
        value_offset=_component_value_offset,
    )
    _component_value_offset += len(_group["nodes"])
_enrich_group(
    SETTLEMENT_GROUP,
    case_id="settlement-agreement",
    source=_SETTLEMENT_SOURCE,
    predecessor_values=SETTLEMENT_PREDECESSOR_VALUES,
)


def _source_report(
    *,
    case_id: str,
    groups: tuple[dict[str, Any], ...],
    page_width: float,
    page_height: float,
    source_character_count: int,
    source_word_count: int,
) -> dict[str, Any]:
    nodes = tuple(node for group in groups for node in group["nodes"])
    coordinate_system_ids = {group["coordinate_system_id"] for group in groups}
    assert len(coordinate_system_ids) == 1
    [coordinate_system_id] = coordinate_system_ids
    return {
        "report_version": "1.0",
        "policy_id": POLICY_ID,
        "source_sha256": SOURCE_IDENTITIES[case_id]["sha256"],
        "status": "available",
        "pages": (
            {
                "page_index": 1,
                "page_width": page_width,
                "page_height": page_height,
                "unit": "pt",
                "coordinate_system_id": coordinate_system_id,
                "source_character_count": source_character_count,
                "source_word_count": source_word_count,
                "markers": tuple(
                    {
                        "raw_marker": node["raw_marker"],
                        "marker_style": node["marker_style"],
                        "ordinal": node["ordinal"],
                        "bbox": node["marker_bbox"],
                        "source_object": node["source_object"],
                    }
                    for node in nodes
                ),
                "concern_codes": (),
            },
        ),
        "counts": {
            "pages": 1,
            "source_characters": source_character_count,
            "source_words": source_word_count,
            "marker_candidates": len(nodes),
            "concerns": 0,
        },
        "concern_codes": (),
        "extraction_ms": 0.0,
    }


SOURCE_REPORTS: dict[str, dict[str, Any]] = {
    "component-datasheet": _source_report(
        case_id="component-datasheet",
        groups=COMPONENT_GROUPS,
        page_width=595.280029296875,
        page_height=841.8900146484375,
        source_character_count=1_341,
        source_word_count=226,
    ),
    "settlement-agreement": _source_report(
        case_id="settlement-agreement",
        groups=(SETTLEMENT_GROUP,),
        page_width=612.0,
        page_height=792.0,
        source_character_count=2_699,
        source_word_count=444,
    ),
}

PREDECESSOR_IDENTITIES: dict[str, dict[str, Any]] = {
    "component-datasheet": {
        "path": (
            "tracker/benchmarks/llamaparse-15/runs/"
            "baseline-20260728-current/component-datasheet/our-output.json"
        ),
        "size_bytes": 262_956,
        "sha256": "210ee7c7c9016aaba61f758e2cff42829e816c928b5a69e3cb6d7e55cadb8cbd",
    },
    "settlement-agreement": {
        "path": (
            "tracker/benchmarks/llamaparse-15/runs/"
            "baseline-20260728-current/settlement-agreement/our-output.json"
        ),
        "size_bytes": 23_135,
        "sha256": "617cb996ee2820bb9264a861c538964121ad706c195703f19f4855bcbc8eb07c",
    },
}

_COMPONENT_PREDECESSOR_RELATIONSHIPS: tuple[tuple[str, ...], ...] = (
    (
        "rel-1146db4be64655e28eb4",
        "rel-2c938424ca41aed42301",
        "rel-2de7021b01048bae31cb",
        "rel-2e85123d09e98d95ce1e",
        "rel-61d953dcde5686017b4b",
        "rel-6e86c9257ba6454fed23",
        "rel-774393e6332575ca9a4f",
        "rel-79f98b6391f8d1b9d12b",
        "rel-7a5e9c03d60a5f239f1f",
        "rel-a049d97198045c3c07f4",
        "rel-e5ea7f53c06065e77875",
    ),
    (
        "rel-06b3c1f1ad831916f2ba",
        "rel-52adb6d06535624b2d38",
        "rel-5a0c041461cc377946c7",
        "rel-905ba0712252062d5d6b",
        "rel-a0fef757875260a49b3f",
    ),
)

_SETTLEMENT_TABLE_CONTRIBUTORS: tuple[str, ...] = (
    "el-881f2919b5021bb5ee27",
    "el-b093383e01057e3498b6",
    "el-dc33c41cf2fb4032b971",
    "el-28e3fb972714aba866b8",
    "el-14dc03838defdebf2da6",
    "el-309aab3bd095c221b4d2",
    "el-4c395a1dcbcea03468ac",
    "el-19acfa45b008efaa6ad7",
    "el-02fcb88cbce899692349",
    "el-48dda77663cc55225947",
    "el-0eafcaab3801f9547bbc",
    "el-4483080d0e485a9ee9a8",
    "el-92ff25bc4f0079495d5e",
    "el-c7faf5101623f80e0c73",
    "el-eb22a8a8b9ceaeee0ca2",
    "el-1ade342a8addfa7a7348",
    "el-ba64e83b12e696a4832e",
)

_SETTLEMENT_PREDECESSOR_RELATIONSHIPS: tuple[str, ...] = (
    "rel-0590ee785b793514b116",
    "rel-05cb7da389d7b82c5ec5",
    "rel-0868a5e5f6aecbd8f414",
    "rel-1be46fe51dd9823a9b90",
    "rel-2b4e40cd5bc084d02bbb",
    "rel-35c92dc209f9dc826ace",
    "rel-47b67465137dac8999fd",
    "rel-6de67e945c12827e48b1",
    "rel-7f2ec4df35417dfc18f0",
    "rel-a5a662d75d94daf73cf8",
    "rel-a79af443e751461011a3",
    "rel-d9e89b7bb8def0382815",
    "rel-e432dff6f3f1769cee4b",
    "rel-ef2f3e4d7362ed054ead",
    "rel-f668670f6fcacf411742",
    "rel-fdee84cb6f53d1c75462",
)


def _canonical_expectation(
    group: dict[str, Any],
    *,
    block_id: str,
    primary_element_type: str,
    predecessor_primary_ids: tuple[str, ...],
    contributing_element_ids: tuple[str, ...],
    predecessor_relationship_ids: tuple[str, ...],
    markdown_bytes: int,
    markdown_sha256: str,
    text_bytes: int,
    text_sha256: str,
) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "page_id": group["page_id"],
        "primary_element_id": group["anchor_element_id"],
        "primary_element_type": primary_element_type,
        "scope": "body",
        "predecessor_primary_ids": predecessor_primary_ids,
        "contributing_element_ids": contributing_element_ids,
        "predecessor_relationship_ids": predecessor_relationship_ids,
        "relationship_ids": tuple(
            sorted({*predecessor_relationship_ids, *group["relationship_ids"]})
        ),
        "markdown_bytes": markdown_bytes,
        "markdown_sha256": markdown_sha256,
        "text_bytes": text_bytes,
        "text_sha256": text_sha256,
    }


CANONICAL_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "component-features": _canonical_expectation(
        COMPONENT_GROUPS[0],
        block_id="pb-affd1cf290d1f2ac4895",
        primary_element_type="list",
        predecessor_primary_ids=(COMPONENT_GROUPS[0]["anchor_element_id"],),
        contributing_element_ids=(
            COMPONENT_GROUPS[0]["anchor_element_id"],
            *COMPONENT_GROUPS[0]["member_element_ids"],
        ),
        predecessor_relationship_ids=_COMPONENT_PREDECESSOR_RELATIONSHIPS[0],
        markdown_bytes=1_775,
        markdown_sha256=(
            "9f46d5dac065435c565a9e7f4b513fd621a0ae46bab47330d9ee9c8291d4c00e"
        ),
        text_bytes=679,
        text_sha256=(
            "8c9162860ca971aa0bdbdac2077062d884ba00d2198b29355afe1d4f8c3b8a47"
        ),
    ),
    "component-headline-features": _canonical_expectation(
        COMPONENT_GROUPS[1],
        block_id="pb-d1d227e3b36e3b112d8f",
        primary_element_type="list",
        predecessor_primary_ids=(COMPONENT_GROUPS[1]["anchor_element_id"],),
        contributing_element_ids=(
            COMPONENT_GROUPS[1]["anchor_element_id"],
            *COMPONENT_GROUPS[1]["member_element_ids"],
        ),
        predecessor_relationship_ids=_COMPONENT_PREDECESSOR_RELATIONSHIPS[1],
        markdown_bytes=819,
        markdown_sha256=(
            "27075ecdf92053c9d6bdc284877298063edc1905f982ef94e1f343138c1596e3"
        ),
        text_bytes=257,
        text_sha256=(
            "cfec0c3353985a762b757acf2120ed112d6686e086ce5b83675334e2f14093a2"
        ),
    ),
    "settlement-lettered-clauses": _canonical_expectation(
        SETTLEMENT_GROUP,
        block_id="pb-e18051f5eef5bc054ce5",
        primary_element_type="text",
        predecessor_primary_ids=(
            "el-dcfe62aad69afbe4fda8",
            "el-e4e770871be0000fc23d",
            "el-881f2919b5021bb5ee27",
            "el-6c344f85277044c09915",
        ),
        contributing_element_ids=(
            "el-dcfe62aad69afbe4fda8",
            "el-e4e770871be0000fc23d",
            *_SETTLEMENT_TABLE_CONTRIBUTORS,
            "el-6c344f85277044c09915",
        ),
        predecessor_relationship_ids=_SETTLEMENT_PREDECESSOR_RELATIONSHIPS,
        markdown_bytes=3_120,
        markdown_sha256=(
            "0200934cea3005ead47a31a18fbd16fc954777ba0fdb9c2dae337ed5718d0841"
        ),
        text_bytes=2_256,
        text_sha256=(
            "22d3279000f21f444759b9530f360527bfbc1aac9220b64bb52df10921689912"
        ),
    ),
}

SETTLEMENT_CONTINUATION_CANONICAL: dict[str, Any] = {
    "block_id": "pb-6c4c64c7d2b1e2d5826d",
    "primary_element_id": "el-881f2919b5021bb5ee27",
    "primary_element_type": "table",
    "scope": "body",
    "contributing_element_ids": _SETTLEMENT_TABLE_CONTRIBUTORS,
    "relationship_ids": _SETTLEMENT_PREDECESSOR_RELATIONSHIPS,
    "markdown_bytes": 955,
    "markdown_sha256": (
        "6d94c6c6a1c34fd2dfac81a1324af392f4a3673f575aa0ed293c57ad4fcd96fb"
    ),
    "text_bytes": 499,
    "text_sha256": ("ecd671902644356bf7f12302b268c64073075f60a51704017593b834764e4aa4"),
}

REVIEWED_COUNTS: dict[str, dict[str, int]] = {
    "component-datasheet": {
        "group_count": 2,
        "node_count": 16,
        "level_zero_count": 11,
        "level_one_count": 5,
        "parent_relationship_count": 5,
        "next_relationship_count": 11,
        "continuation_relationship_count": 0,
        "contains_relationship_count": 16,
        "total_relationship_count": 32,
    },
    "settlement-agreement": {
        "group_count": 1,
        "node_count": 3,
        "level_zero_count": 3,
        "level_one_count": 0,
        "parent_relationship_count": 0,
        "next_relationship_count": 2,
        "continuation_relationship_count": 1,
        "contains_relationship_count": 3,
        "total_relationship_count": 6,
    },
}


def oracle_payload() -> dict[str, Any]:
    """Return the deterministic semantic oracle payload."""

    return {
        "policy_id": POLICY_ID,
        "source_identities": SOURCE_IDENTITIES,
        "component_groups": COMPONENT_GROUPS,
        "settlement_group": SETTLEMENT_GROUP,
        "source_reports": SOURCE_REPORTS,
        "predecessor_identities": PREDECESSOR_IDENTITIES,
        "canonical_expectations": CANONICAL_EXPECTATIONS,
        "settlement_continuation_canonical": SETTLEMENT_CONTINUATION_CANONICAL,
        "reviewed_counts": REVIEWED_COUNTS,
    }


def oracle_sha256() -> str:
    """Return the stable semantic hash of the reviewed oracle."""

    payload = json.dumps(
        oracle_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "COMPONENT_GROUPS",
    "CANONICAL_EXPECTATIONS",
    "POLICY_ID",
    "PREDECESSOR_IDENTITIES",
    "REVIEWED_COUNTS",
    "SETTLEMENT_GROUP",
    "SETTLEMENT_CONTINUATION_CANONICAL",
    "SOURCE_IDENTITIES",
    "SOURCE_REPORTS",
    "oracle_payload",
    "oracle_sha256",
]
