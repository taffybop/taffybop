"""Source-reviewed immutable oracle for P03-US06.

Coordinates are top-left PDF points.  This module is data only: production
code must derive these records from source evidence and must not import it.
"""

from __future__ import annotations

from typing import Final


SOURCE_IDENTITIES: Final = {
    "insurance-acord": {
        "path": "benchmark-expertmodeldata/insurance-acord.pdf",
        "size_bytes": 17_086,
        "sha256": (
            "85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4"
        ),
        "page_count": 1,
    },
    "component-datasheet": {
        "path": "benchmark-expertmodeldata/component-datasheet.pdf",
        "size_bytes": 329_199,
        "sha256": (
            "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4"
        ),
        "page_count": 3,
    },
}


ACORD_GROUP_ORACLE: Final = (
    {
        "group_key": "date",
        "page_index": 1,
        "bbox": (507.6, 24.0, 86.4, 24.0),
        "status": "resolved",
        "interactivity": "static",
        "anchor_public_item_id": "p1-i2",
        "anchor_element_id": "el-36192d2a72910bbf090c",
        "contributor_public_item_ids": ("p1-i2",),
        "contributor_element_ids": ("el-36192d2a72910bbf090c",),
        "canonical_mode": "inert",
        "source_objects": (("rect", 2),),
        "field_keys": ("date",),
        "label_keys": ("date",),
        "control_keys": (),
        "concern_codes": (),
    },
    {
        "group_key": "parties-and-insurers",
        "page_index": 1,
        "bbox": (18.0, 120.0, 576.0, 120.0),
        "status": "resolved",
        "interactivity": "static",
        "anchor_public_item_id": "p1-i7",
        "anchor_element_id": "el-d48558bc276571415f1c",
        "contributor_public_item_ids": (
            "p1-i6",
            "p1-i8",
            "p1-i7",
            "p1-i19",
            "p1-i20",
        ),
        "contributor_element_ids": (
            "el-e0de889b136d65c3c52b",
            "el-26bc8c4dab67baf06f03",
            "el-d48558bc276571415f1c",
            "el-c9a29e338f912f93eafb",
            "el-daab85252ff4d534f4d3",
        ),
        "canonical_mode": "replace",
        "source_objects": (("rect", 17),),
        "field_keys": (
            "producer",
            "insured",
            "contact-name",
            "phone",
            "fax",
            "email-address",
            "insurer-a-name",
            "insurer-a-naic",
            "insurer-b-name",
            "insurer-b-naic",
            "insurer-c-name",
            "insurer-c-naic",
            "insurer-d-name",
            "insurer-d-naic",
            "insurer-e-name",
            "insurer-e-naic",
            "insurer-f-name",
            "insurer-f-naic",
        ),
        "label_keys": (
            "producer",
            "insured",
            "contact-name",
            "phone",
            "fax",
            "email-address",
            "insurers-affording-coverage",
            "naic-number",
            "insurer-a",
            "insurer-b",
            "insurer-c",
            "insurer-d",
            "insurer-e",
            "insurer-f",
        ),
        "control_keys": (),
        "concern_codes": (),
    },
    {
        "group_key": "coverages",
        "page_index": 1,
        "bbox": (18.0, 240.0, 576.0, 324.0),
        "status": "unresolved",
        "interactivity": "static",
        "anchor_public_item_id": "p1-i13",
        "anchor_element_id": "el-2300235f191fabb4bfc4",
        "contributor_public_item_ids": (
            "p1-i9",
            "p1-i10",
            "p1-i11",
            "p1-i13",
        ),
        "contributor_element_ids": (
            "el-4d2be7c46173fc783231",
            "el-da7dd9f1ace6b7a2ac6f",
            "el-133f0b79942b1f372fcf",
            "el-2300235f191fabb4bfc4",
        ),
        "canonical_mode": "inert",
        "source_objects": (
            ("line", 6),
            ("line", 100),
            ("line", 120),
            ("rect", 3),
        ),
        "field_keys": ("certificate-number", "revision-number"),
        "label_keys": (
            "coverages",
            "certificate-number",
            "revision-number",
            "commercial-general-liability",
            "claims-made-general",
            "occur-general",
            "policy",
            "project",
            "loc",
            "any-auto",
            "all-owned-autos",
            "scheduled-autos",
            "hired-autos",
            "non-owned-autos",
            "umbrella-liability",
            "occur-umbrella",
            "excess-liability",
            "claims-made-excess",
            "ded",
            "retention",
            "wc-statutory-limits",
            "other",
            "yn-response",
        ),
        "control_keys": (
            "commercial-general-liability",
            "claims-made-general",
            "occur-general",
            "unlabeled-general-1",
            "unlabeled-general-2",
            "policy",
            "project",
            "loc",
            "any-auto",
            "all-owned-autos",
            "scheduled-autos",
            "hired-autos",
            "non-owned-autos",
            "unlabeled-auto-1",
            "unlabeled-auto-2",
            "umbrella-liability",
            "occur-umbrella",
            "excess-liability",
            "claims-made-excess",
            "ded",
            "retention",
            "wc-statutory-limits",
            "other",
            "yn-response",
        ),
        "preserved_table_bbox": (18.0, 288.0, 576.0, 276.0),
        "concern_codes": ("form_table_ownership_ambiguous",),
    },
    {
        "group_key": "description-of-operations",
        "page_index": 1,
        "bbox": (18.0, 564.0, 576.0, 84.0),
        "status": "resolved",
        "interactivity": "static",
        "anchor_public_item_id": "p1-i14",
        "anchor_element_id": "el-636510e72b2f31953b81",
        "contributor_public_item_ids": ("p1-i14",),
        "contributor_element_ids": ("el-636510e72b2f31953b81",),
        "canonical_mode": "inert",
        "source_objects": (("line", 6), ("rect", 3)),
        "field_keys": ("description-of-operations",),
        "label_keys": ("description-of-operations",),
        "control_keys": (),
        "concern_codes": (),
    },
    {
        "group_key": "certificate-holder",
        "page_index": 1,
        "bbox": (18.0, 660.0, 288.0, 84.0),
        "status": "resolved",
        "interactivity": "static",
        "anchor_public_item_id": "p1-i15",
        "anchor_element_id": "el-96fba9a30f3c839ddebb",
        "contributor_public_item_ids": ("p1-i15",),
        "contributor_element_ids": ("el-96fba9a30f3c839ddebb",),
        "canonical_mode": "inert",
        "source_objects": (("rect", 0),),
        "field_keys": ("certificate-holder",),
        "label_keys": ("certificate-holder",),
        "control_keys": (),
        "concern_codes": (),
    },
    {
        "group_key": "cancellation",
        "page_index": 1,
        "bbox": (306.0, 660.0, 288.0, 84.0),
        "status": "resolved",
        "interactivity": "static",
        "anchor_public_item_id": "p1-i16",
        "anchor_element_id": "el-e3a29666d249609f5506",
        "contributor_public_item_ids": (
            "p1-i16",
            "p1-i17",
            "p1-i18",
        ),
        "contributor_element_ids": (
            "el-e3a29666d249609f5506",
            "el-e3b49c8acd7f7f8c035d",
            "el-a23e88135e2cd8aa8273",
        ),
        "canonical_mode": "inert",
        "source_objects": (("rect", 1),),
        "field_keys": ("authorized-representative",),
        "label_keys": ("cancellation", "authorized-representative"),
        "control_keys": (),
        "concern_codes": (),
    },
)


def _label(
    key: str,
    text: str,
    bbox: tuple[float, float, float, float],
    source_character_ranges: tuple[tuple[int, int], ...],
    group_key: str,
    label_role: str,
    label_of_keys: tuple[str, ...],
) -> dict[str, object]:
    raw_text = {
        "project": "PRO- JECT",
        "wc-statutory-limits": "WC STATU- TORY LIMITS",
        "other": "OTH- ER",
    }.get(key, text)
    return {
        "label_key": key,
        "page_index": 1,
        "text": text,
        "raw_text": raw_text,
        "bbox": bbox,
        # Half-open pdfplumber page-character indexes. Some visually
        # contiguous labels have multiple ranges because of source draw order.
        "source_character_ranges": source_character_ranges,
        "group_key": group_key,
        "label_role": label_role,
        "label_of_keys": label_of_keys,
    }


ACORD_LABEL_ORACLE: Final = (
    _label(
        "date",
        "DATE (MM/DD/YYYY)",
        (521.28, 27.241, 59.004, 5.9),
        ((125, 142),),
        "date",
        "field",
        ("date",),
    ),
    _label(
        "producer",
        "PRODUCER",
        (21.6, 123.241, 33.762, 5.9),
        ((2539, 2547),),
        "parties-and-insurers",
        "field",
        ("producer",),
    ),
    _label(
        "insured",
        "INSURED",
        (21.6, 183.241, 26.552, 5.9),
        ((2512, 2519),),
        "parties-and-insurers",
        "field",
        ("insured",),
    ),
    _label(
        "contact-name",
        "CONTACT NAME:",
        (309.6, 120.721, 28.841, 11.42),
        ((2574, 2586),),
        "parties-and-insurers",
        "field",
        ("contact-name",),
    ),
    _label(
        "phone",
        "PHONE (A/C, No, Ext):",
        (309.6, 133.201, 39.662, 11.42),
        ((2519, 2539),),
        "parties-and-insurers",
        "field",
        ("phone",),
    ),
    _label(
        "fax",
        "FAX (A/C, No):",
        (486.0, 132.721, 27.201, 11.42),
        ((2561, 2574),),
        "parties-and-insurers",
        "field",
        ("fax",),
    ),
    _label(
        "email-address",
        "E-MAIL ADDRESS:",
        (309.6, 144.841, 30.812, 11.42),
        ((2547, 2561),),
        "parties-and-insurers",
        "field",
        ("email-address",),
    ),
    _label(
        "insurers-affording-coverage",
        "INSURER(S) AFFORDING COVERAGE",
        (368.76, 161.562, 108.336, 6.0),
        ((2658, 2687),),
        "parties-and-insurers",
        "group",
        ("parties-and-insurers",),
    ),
    _label(
        "naic-number",
        "NAIC #",
        (557.16, 161.562, 19.668, 6.0),
        ((2586, 2592),),
        "parties-and-insurers",
        "field",
        tuple(f"insurer-{letter}-naic" for letter in "abcdef"),
    ),
    *tuple(
        _label(
            f"insurer-{letter.casefold()}",
            f"INSURER {letter} :",
            (
                309.6,
                173.761 + 12.0 * row_offset,
                {
                    "A": 36.057,
                    "B": 36.057,
                    "C": 36.057,
                    "D": 36.057,
                    "E": 35.733,
                    "F": 35.402,
                }[letter],
                5.9,
            ),
            ((2592 + 11 * row_offset, 2603 + 11 * row_offset),),
            "parties-and-insurers",
            "field",
            (
                f"insurer-{letter.casefold()}-name",
                f"insurer-{letter.casefold()}-naic",
            ),
        )
        for row_offset, letter in enumerate("ABCDEF")
    ),
    _label(
        "coverages",
        "COVERAGES",
        (21.6, 242.939, 53.676, 8.4),
        ((2468, 2477),),
        "coverages",
        "group",
        ("coverages",),
    ),
    _label(
        "certificate-number",
        "CERTIFICATE NUMBER:",
        (158.4, 242.939, 97.524, 8.4),
        ((2477, 2496),),
        "coverages",
        "field",
        ("certificate-number",),
    ),
    _label(
        "revision-number",
        "REVISION NUMBER:",
        (424.8, 242.939, 82.135, 8.4),
        ((2496, 2512),),
        "coverages",
        "field",
        ("revision-number",),
    ),
    _label(
        "description-of-operations",
        (
            "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES "
            "(Attach ACORD 101, Additional Remarks Schedule, if more "
            "space is required)"
        ),
        (21.6, 567.241, 384.924, 5.9),
        ((513, 637),),
        "description-of-operations",
        "field",
        ("description-of-operations",),
    ),
    _label(
        "certificate-holder",
        "CERTIFICATE HOLDER",
        (21.6, 651.299, 93.332, 8.4),
        ((0, 18),),
        "certificate-holder",
        "field",
        ("certificate-holder",),
    ),
    _label(
        "cancellation",
        "CANCELLATION",
        (309.6, 651.299, 66.259, 8.4),
        ((113, 125),),
        "cancellation",
        "group",
        ("cancellation",),
    ),
    _label(
        "authorized-representative",
        "AUTHORIZED REPRESENTATIVE",
        (309.6, 711.241, 93.757, 5.9),
        ((88, 113),),
        "cancellation",
        "field",
        ("authorized-representative",),
    ),
    _label(
        "commercial-general-liability",
        "COMMERCIAL GENERAL LIABILITY",
        (54.0, 317.202, 100.026, 6.0),
        ((243, 271),),
        "coverages",
        "control",
        ("commercial-general-liability",),
    ),
    _label(
        "claims-made-general",
        "CLAIMS-MADE",
        (68.4, 329.202, 41.67, 6.0),
        ((232, 243),),
        "coverages",
        "control",
        ("claims-made-general",),
    ),
    _label(
        "occur-general",
        "OCCUR",
        (133.2, 329.202, 21.996, 6.0),
        ((227, 232),),
        "coverages",
        "control",
        ("occur-general",),
    ),
    _label(
        "policy",
        "POLICY",
        (54.0, 377.202, 22.008, 6.0),
        ((187, 193),),
        "coverages",
        "control",
        ("policy",),
    ),
    _label(
        "project",
        "PROJECT",
        (97.2, 373.242, 15.0, 11.4),
        ((179, 187),),
        "coverages",
        "control",
        ("project",),
    ),
    _label(
        "loc",
        "LOC",
        (140.4, 377.202, 12.336, 6.0),
        ((176, 179),),
        "coverages",
        "control",
        ("loc",),
    ),
    _label(
        "any-auto",
        "ANY AUTO",
        (54.0, 401.202, 30.672, 6.0),
        ((1019, 1027),),
        "coverages",
        "control",
        ("any-auto",),
    ),
    _label(
        "all-owned-autos",
        "ALL OWNED AUTOS",
        (54.0, 408.762, 35.34, 12.0),
        ((1027, 1036), (1065, 1070)),
        "coverages",
        "control",
        ("all-owned-autos",),
    ),
    _label(
        "scheduled-autos",
        "SCHEDULED AUTOS",
        (122.4, 408.762, 37.002, 12.0),
        ((1036, 1045), (1070, 1075)),
        "coverages",
        "control",
        ("scheduled-autos",),
    ),
    _label(
        "hired-autos",
        "HIRED AUTOS",
        (54.0, 425.682, 41.004, 6.0),
        ((1045, 1056),),
        "coverages",
        "control",
        ("hired-autos",),
    ),
    _label(
        "non-owned-autos",
        "NON-OWNED AUTOS",
        (122.4, 420.642, 38.328, 12.12),
        ((1056, 1065), (1075, 1080)),
        "coverages",
        "control",
        ("non-owned-autos",),
    ),
    _label(
        "umbrella-liability",
        "UMBRELLA LIAB",
        (54.0, 447.241, 48.507, 5.9),
        ((489, 502),),
        "coverages",
        "control",
        ("umbrella-liability",),
    ),
    _label(
        "occur-umbrella",
        "OCCUR",
        (133.2, 449.682, 21.996, 6.0),
        ((457, 462),),
        "coverages",
        "control",
        ("occur-umbrella",),
    ),
    _label(
        "excess-liability",
        "EXCESS LIAB",
        (54.0, 459.241, 39.344, 5.9),
        ((502, 513),),
        "coverages",
        "control",
        ("excess-liability",),
    ),
    _label(
        "claims-made-excess",
        "CLAIMS-MADE",
        (133.2, 461.202, 41.67, 6.0),
        ((446, 457),),
        "coverages",
        "control",
        ("claims-made-excess",),
    ),
    _label(
        "ded",
        "DED",
        (54.0, 473.682, 12.666, 6.0),
        ((443, 446),),
        "coverages",
        "control",
        ("ded",),
    ),
    _label(
        "retention",
        "RETENTION",
        (90.0, 473.682, 34.668, 6.0),
        ((434, 443),),
        "coverages",
        "control",
        ("retention",),
    ),
    _label(
        "wc-statutory-limits",
        "WC STATUTORY LIMITS",
        (441.96, 481.122, 37.674, 11.64),
        ((724, 744),),
        "coverages",
        "control",
        ("wc-statutory-limits",),
    ),
    _label(
        "other",
        "OTHER",
        (498.36, 481.122, 14.664, 11.64),
        ((744, 750),),
        "coverages",
        "control",
        ("other",),
    ),
    _label(
        "yn-response",
        "Y / N",
        (159.36, 491.562, 13.338, 6.0),
        ((994, 999),),
        "coverages",
        "control",
        ("yn-response",),
    ),
)


ACORD_EMPTY_FIELD_ORACLE: Final = (
    {
        "field_key": "date",
        "group_key": "date",
        "label_keys": ("date",),
        "labels": ("DATE (MM/DD/YYYY)",),
        "bbox": (507.6, 24.0, 86.4, 24.0),
        "value_region_bbox": (507.6, 24.0, 86.4, 24.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    {
        "field_key": "producer",
        "group_key": "parties-and-insurers",
        "label_keys": ("producer",),
        "labels": ("PRODUCER",),
        "bbox": (18.0, 120.0, 288.0, 60.0),
        "value_region_bbox": (18.0, 120.0, 288.0, 60.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    {
        "field_key": "insured",
        "group_key": "parties-and-insurers",
        "label_keys": ("insured",),
        "labels": ("INSURED",),
        "bbox": (18.0, 180.0, 288.0, 60.0),
        "value_region_bbox": (18.0, 180.0, 288.0, 60.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    {
        "field_key": "contact-name",
        "group_key": "parties-and-insurers",
        "label_keys": ("contact-name",),
        "labels": ("CONTACT NAME:",),
        "bbox": (306.0, 120.0, 288.0, 12.0),
        "value_region_bbox": (306.0, 120.0, 288.0, 12.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    {
        "field_key": "phone",
        "group_key": "parties-and-insurers",
        "label_keys": ("phone",),
        "labels": ("PHONE (A/C, No, Ext):",),
        "bbox": (306.0, 132.0, 176.4, 12.0),
        "value_region_bbox": (306.0, 132.0, 176.4, 12.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    {
        "field_key": "fax",
        "group_key": "parties-and-insurers",
        "label_keys": ("fax",),
        "labels": ("FAX (A/C, No):",),
        "bbox": (482.4, 132.0, 111.6, 12.0),
        "value_region_bbox": (482.4, 132.0, 111.6, 12.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    {
        "field_key": "email-address",
        "group_key": "parties-and-insurers",
        "label_keys": ("email-address",),
        "labels": ("E-MAIL ADDRESS:",),
        "bbox": (306.0, 144.0, 288.0, 12.0),
        "value_region_bbox": (306.0, 144.0, 288.0, 12.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    *tuple(
        record
        for row_offset, insurer in enumerate("ABCDEF")
        for record in (
            {
                "field_key": f"insurer-{insurer.casefold()}-name",
                "group_key": "parties-and-insurers",
                "label_keys": (f"insurer-{insurer.casefold()}",),
                "labels": (f"INSURER {insurer} :",),
                "bbox": (
                    306.0,
                    168.0 + 12.0 * row_offset,
                    234.0,
                    12.0,
                ),
                "value_region_bbox": (
                    306.0,
                    168.0 + 12.0 * row_offset,
                    234.0,
                    12.0,
                ),
                "value": None,
                "value_state": "empty",
                "boundary": "ruled",
                "concern_codes": (),
            },
            {
                "field_key": f"insurer-{insurer.casefold()}-naic",
                "group_key": "parties-and-insurers",
                "label_keys": (
                    f"insurer-{insurer.casefold()}",
                    "naic-number",
                ),
                "labels": (f"INSURER {insurer} :", "NAIC #"),
                "bbox": (
                    540.0,
                    168.0 + 12.0 * row_offset,
                    54.0,
                    12.0,
                ),
                "value_region_bbox": (
                    540.0,
                    168.0 + 12.0 * row_offset,
                    54.0,
                    12.0,
                ),
                "value": None,
                "value_state": "empty",
                "boundary": "ruled",
                "concern_codes": (),
            },
        )
    ),
    {
        "field_key": "certificate-number",
        "group_key": "coverages",
        "label_keys": ("certificate-number",),
        "labels": ("CERTIFICATE NUMBER:",),
        "bbox": (255.924, 240.0, 168.876, 12.0),
        "value_region_bbox": (255.924, 240.0, 168.876, 12.0),
        "value": None,
        "value_state": "empty",
        "boundary": "implicit_aligned",
        "concern_codes": ("form_value_boundary_implicit",),
    },
    {
        "field_key": "revision-number",
        "group_key": "coverages",
        "label_keys": ("revision-number",),
        "labels": ("REVISION NUMBER:",),
        "bbox": (506.935, 240.0, 87.065, 12.0),
        "value_region_bbox": (506.935, 240.0, 87.065, 12.0),
        "value": None,
        "value_state": "empty",
        "boundary": "implicit_aligned",
        "concern_codes": ("form_value_boundary_implicit",),
    },
    {
        "field_key": "description-of-operations",
        "group_key": "description-of-operations",
        "label_keys": ("description-of-operations",),
        "labels": (
            "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES "
            "(Attach ACORD 101, Additional Remarks Schedule, if more "
            "space is required)",
        ),
        "bbox": (18.0, 564.0, 576.0, 84.0),
        "value_region_bbox": (18.0, 564.0, 576.0, 84.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    {
        "field_key": "certificate-holder",
        "group_key": "certificate-holder",
        "label_keys": ("certificate-holder",),
        "labels": ("CERTIFICATE HOLDER",),
        "bbox": (18.0, 660.0, 288.0, 84.0),
        "value_region_bbox": (18.0, 660.0, 288.0, 84.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
    {
        "field_key": "authorized-representative",
        "group_key": "cancellation",
        "label_keys": ("authorized-representative",),
        "labels": ("AUTHORIZED REPRESENTATIVE",),
        "bbox": (306.0, 708.0, 288.0, 36.0),
        "value_region_bbox": (306.0, 708.0, 288.0, 36.0),
        "value": None,
        "value_state": "empty",
        "boundary": "ruled",
        "concern_codes": (),
    },
)


ACORD_VALUE_REGION_ORACLE: Final = tuple(
    {
        "value_region_key": field["field_key"],
        "group_key": field["group_key"],
        "owner_field_key": field["field_key"],
        "page_index": 1,
        "bbox": field["value_region_bbox"],
        "excluded_label_keys": field["label_keys"],
        "value": field["value"],
        "value_state": field["value_state"],
        "boundary": field["boundary"],
        "concern_codes": field["concern_codes"],
    }
    for field in ACORD_EMPTY_FIELD_ORACLE
)


ACORD_FIELD_BOUNDARY_SOURCE_OBJECTS: Final = {
    "date": (("rect", 2),),
    "producer": (
        ("rect", 17),
        ("line", 107),
        ("line", 111),
        ("line", 118),
        ("line", 122),
    ),
    "insured": (
        ("rect", 17),
        ("line", 107),
        ("line", 111),
        ("line", 122),
    ),
    "contact-name": (
        ("line", 107),
        ("line", 110),
        ("line", 114),
        ("line", 119),
    ),
    "phone": (
        ("line", 108),
        ("line", 109),
        ("line", 114),
        ("line", 121),
    ),
    "fax": (
        ("line", 109),
        ("line", 114),
        ("line", 119),
        ("line", 121),
    ),
    "email-address": (("rect", 18), ("rect", 19)),
    **{
        f"insurer-{letter}-name": (
            ("line", left_right[0]),
            ("line", left_right[1]),
            ("line", 107),
            ("line", 123),
        )
        for letter, left_right in zip(
            "abcdef",
            (
                (124, 112),
                (112, 113),
                (113, 115),
                (115, 116),
                (116, 117),
                (117, 120),
            ),
            strict=True,
        )
    },
    **{
        f"insurer-{letter}-naic": (
            ("line", left_right[0]),
            ("line", left_right[1]),
            ("line", 119),
            ("line", 123),
        )
        for letter, left_right in zip(
            "abcdef",
            (
                (124, 112),
                (112, 113),
                (113, 115),
                (115, 116),
                (116, 117),
                (117, 120),
            ),
            strict=True,
        )
    },
    "certificate-number": (("line", 120), ("rect", 3)),
    "revision-number": (("line", 120), ("rect", 3)),
    "description-of-operations": (("line", 6), ("rect", 3)),
    "certificate-holder": (("rect", 0),),
    "authorized-representative": (("line", 2), ("rect", 1)),
}


_ACORD_CONTROL_SOURCE_OBJECTS: Final = {
    "commercial-general-liability": (
        ("line", 9),
        ("line", 11),
        ("line", 12),
        ("line", 26),
        ("line", 35),
    ),
    "claims-made-general": (
        ("line", 12),
        ("line", 14),
        ("line", 26),
        ("line", 32),
    ),
    "occur-general": (
        ("line", 13),
        ("line", 15),
        ("line", 33),
        ("line", 34),
    ),
    "unlabeled-general-1": (
        ("line", 9),
        ("line", 14),
        ("line", 16),
        ("line", 26),
        ("line", 35),
    ),
    "unlabeled-general-2": (
        ("line", 9),
        ("line", 16),
        ("line", 18),
        ("line", 26),
        ("line", 35),
    ),
    "policy": (
        ("line", 9),
        ("line", 10),
        ("line", 20),
        ("line", 23),
        ("line", 27),
        ("line", 35),
    ),
    "project": (
        ("line", 10),
        ("line", 21),
        ("line", 24),
        ("line", 28),
        ("line", 29),
    ),
    "loc": (
        ("line", 10),
        ("line", 22),
        ("line", 25),
        ("line", 30),
        ("line", 31),
    ),
    "any-auto": (("rect", 8),),
    "all-owned-autos": (("rect", 9),),
    "scheduled-autos": (("rect", 10),),
    "hired-autos": (("rect", 11),),
    "non-owned-autos": (("rect", 12),),
    "unlabeled-auto-1": (("rect", 13),),
    "unlabeled-auto-2": (("rect", 14),),
    "umbrella-liability": (
        ("line", 59),
        ("line", 61),
        ("line", 62),
        ("line", 88),
        ("line", 90),
    ),
    "occur-umbrella": (("rect", 6),),
    "excess-liability": (
        ("line", 59),
        ("line", 60),
        ("line", 61),
        ("line", 62),
        ("line", 88),
    ),
    "claims-made-excess": (("rect", 4),),
    "ded": (("rect", 5),),
    "retention": (("rect", 15),),
    "wc-statutory-limits": (
        ("line", 58),
        ("line", 65),
        ("line", 79),
        ("line", 82),
        ("line", 84),
    ),
    "other": (
        ("line", 58),
        ("line", 65),
        ("line", 77),
        ("line", 78),
        ("line", 82),
    ),
    "yn-response": (("rect", 7),),
}


def _control(
    key: str,
    x: float,
    y: float,
    label: str | None,
    state: str,
    source_object_kind: str,
) -> dict[str, object]:
    return {
        "control_key": key,
        "group_key": "coverages",
        "owner_field_key": None,
        "page_index": 1,
        "bbox": (x, y, 14.4, 12.0),
        "control_type": "checkbox",
        "origin": "static_vector",
        "label_key": key if label is not None else None,
        "label": label,
        "state": state,
        "source_object_kind": source_object_kind,
        "source_objects": _ACORD_CONTROL_SOURCE_OBJECTS[key],
        "concern_codes": (
            ("form_control_state_ambiguous",)
            if state == "ambiguous"
            else ()
        ),
    }


ACORD_CONTROL_ORACLE: Final = (
    _control(
        "commercial-general-liability",
        36.0,
        312.0,
        "COMMERCIAL GENERAL LIABILITY",
        "unchecked",
        "lines",
    ),
    _control(
        "claims-made-general",
        50.4,
        324.0,
        "CLAIMS-MADE",
        "unchecked",
        "lines",
    ),
    _control(
        "occur-general",
        115.2,
        324.0,
        "OCCUR",
        "unchecked",
        "lines",
    ),
    _control(
        "unlabeled-general-1",
        36.0,
        336.0,
        None,
        "ambiguous",
        "lines",
    ),
    _control(
        "unlabeled-general-2",
        36.0,
        348.0,
        None,
        "ambiguous",
        "lines",
    ),
    _control("policy", 36.0, 372.0, "POLICY", "unchecked", "lines"),
    _control("project", 79.2, 372.0, "PROJECT", "unchecked", "lines"),
    _control("loc", 122.4, 372.0, "LOC", "unchecked", "lines"),
    _control("any-auto", 36.0, 396.0, "ANY AUTO", "unchecked", "rect"),
    _control(
        "all-owned-autos",
        36.0,
        408.0,
        "ALL OWNED AUTOS",
        "unchecked",
        "rect",
    ),
    _control(
        "scheduled-autos",
        104.4,
        408.0,
        "SCHEDULED AUTOS",
        "unchecked",
        "rect",
    ),
    _control(
        "hired-autos",
        36.0,
        420.0,
        "HIRED AUTOS",
        "unchecked",
        "rect",
    ),
    _control(
        "non-owned-autos",
        104.4,
        420.0,
        "NON-OWNED AUTOS",
        "unchecked",
        "rect",
    ),
    _control(
        "unlabeled-auto-1",
        36.0,
        432.0,
        None,
        "ambiguous",
        "rect",
    ),
    _control(
        "unlabeled-auto-2",
        104.4,
        432.0,
        None,
        "ambiguous",
        "rect",
    ),
    _control(
        "umbrella-liability",
        36.0,
        444.0,
        "UMBRELLA LIAB",
        "unchecked",
        "lines",
    ),
    _control(
        "occur-umbrella",
        115.2,
        444.0,
        "OCCUR",
        "unchecked",
        "rect",
    ),
    _control(
        "excess-liability",
        36.0,
        456.0,
        "EXCESS LIAB",
        "unchecked",
        "lines",
    ),
    _control(
        "claims-made-excess",
        115.2,
        456.0,
        "CLAIMS-MADE",
        "unchecked",
        "rect",
    ),
    _control("ded", 36.0, 468.0, "DED", "unchecked", "rect"),
    _control(
        "retention",
        72.0,
        468.0,
        "RETENTION",
        "unchecked",
        "rect",
    ),
    _control(
        "wc-statutory-limits",
        424.8,
        480.0,
        "WC STATUTORY LIMITS",
        "unchecked",
        "lines",
    ),
    _control(
        "other",
        482.4,
        480.0,
        "OTHER",
        "unchecked",
        "lines",
    ),
    _control(
        "yn-response",
        158.4,
        498.0,
        "Y / N",
        "ambiguous",
        "rect",
    ),
)


COMPONENT_KEY_VALUE_ORACLE: Final = (
    {
        "group_key": "gpio-functions",
        "page_index": 2,
        "printed_page": "7",
        "status": "resolved",
        "interactivity": "none",
        "anchor_public_item_id": "p2-i8",
        "anchor_element_id": "el-70d056d4a15b5143497a",
        "contributor_public_item_ids": tuple(
            f"p2-i{index}" for index in range(8, 16)
        ),
        "contributor_element_ids": (
            "el-70d056d4a15b5143497a",
            "el-6049a2c82a0acd74199c",
            "el-15fe2bfa8f3b0fab034a",
            "el-c990b93b5d66dbc37c9a",
            "el-6763021f4c866aac06af",
            "el-90d9c3699ee3113f8bb7",
            "el-0113e0feca8013457925",
            "el-61cb7b46f4cb2a8fd27f",
        ),
        "canonical_mode": "replace",
        "bbox": (125.0, 471.013, 264.384, 63.176),
        "key_x": 125.0,
        "value_x": 172.624,
        "row_cadence": 18.392,
        "pairs": (
            ("GPIO29", "IP Used in ADC mode (ADC3) to measure VSYS/3"),
            ("GPIO25", "OP Connected to user LED"),
            ("GPIO24", "IP VBUS sense - high if VBUS is present, else low"),
            (
                "GPIO23",
                "OP Controls the on-board SMPS Power Save pin (Section 4.4)",
            ),
        ),
    },
    {
        "group_key": "interface-pins",
        "page_index": 2,
        "printed_page": "7",
        "status": "resolved",
        "interactivity": "none",
        "anchor_public_item_id": "p2-i17",
        "anchor_element_id": "el-78a1ad6893ccdfd64691",
        "contributor_public_item_ids": tuple(
            f"p2-i{index}" for index in range(17, 31)
        ),
        "contributor_element_ids": (
            "el-78a1ad6893ccdfd64691",
            "el-9b72d6b0beace96fac21",
            "el-4a78f4ef3a2f90d41037",
            "el-f75c6ef63adadfa4c08a",
            "el-0bf8f92842872ba3fe80",
            "el-0134b0937bc5d2751df7",
            "el-ad8a1baa4a9a753694df",
            "el-4571ceff2af6c638a29c",
            "el-572643be27a4fab45b8c",
            "el-a037cd02067e3f26c4cd",
            "el-71eef1253aed2a5951fc",
            "el-890d26a2c0eb344e71d9",
            "el-4637813b7c6d29a5baeb",
            "el-7d38877d4754e9d5b2c7",
        ),
        "canonical_mode": "replace",
        "bbox": (125.0, 563.365, 80.536, 118.352),
        "key_x": 125.0,
        "value_x": 167.304,
        "row_cadence": 18.392,
        "pairs": (
            ("PIN40", "VBUS"),
            ("PIN39", "VSYS"),
            ("PIN37", "3V3_EN"),
            ("PIN36", "3V3"),
            ("PIN35", "ADC_VREF"),
            ("PIN33", "AGND"),
            ("PIN30", "RUN"),
        ),
    },
    {
        "group_key": "operating-conditions",
        "page_index": 3,
        "printed_page": "11",
        "status": "resolved",
        "interactivity": "none",
        "anchor_public_item_id": "p3-i4",
        "anchor_element_id": "el-972af7e91a63058873da",
        "contributor_public_item_ids": tuple(
            f"p3-i{index}" for index in range(4, 14)
        ),
        "contributor_element_ids": (
            "el-972af7e91a63058873da",
            "el-a7dcffe538b6247dbc1a",
            "el-1efbaac715c919769cd7",
            "el-ebd050f46dbe94be45a3",
            "el-d3bebaa0183ebc00de12",
            "el-acccccb1468968c69ac3",
            "el-8c611b850b4c5a7cf4f0",
            "el-bb04b7c5d369e54e36d8",
            "el-cc298b7f1c5e2b74bc95",
            "el-4ce058b3aadfe80f9d85",
        ),
        "canonical_mode": "replace",
        "bbox": (125.0, 142.96, 195.912, 81.568),
        "key_x": 125.0,
        "value_x": 220.408,
        "row_cadence": 18.392,
        "pairs": (
            (
                "Operating Temp Max",
                "85°C (including self-heating)",
            ),
            ("Operating Temp Min", "-20°C"),
            ("VBUS", "5V ± 10%."),
            ("VSYS Min", "1.8V"),
            ("VSYS Max", "5.5V"),
        ),
    },
)


def _pair(
    *,
    pair_key: str,
    group_key: str,
    page_index: int,
    key: str,
    value: str,
    key_bbox: tuple[float, float, float, float],
    value_bbox: tuple[float, float, float, float],
    key_character_range: tuple[int, int],
    value_character_range: tuple[int, int],
    key_public_item_id: str,
    value_public_item_id: str,
    key_element_id: str,
    value_element_id: str,
) -> dict[str, object]:
    return {
        "pair_key": pair_key,
        "group_key": group_key,
        "page_index": page_index,
        "key": key,
        "value": value,
        "value_state": "present",
        "key_bbox": key_bbox,
        "value_bbox": value_bbox,
        "key_character_range": key_character_range,
        "value_character_range": value_character_range,
        "key_public_item_id": key_public_item_id,
        "value_public_item_id": value_public_item_id,
        "key_element_id": key_element_id,
        "value_element_id": value_element_id,
    }


COMPONENT_KEY_VALUE_PAIR_ORACLE: Final = (
    _pair(
        pair_key="gpio-functions:gpio29",
        group_key="gpio-functions",
        page_index=2,
        key="GPIO29",
        value="IP Used in ADC mode (ADC3) to measure VSYS/3",
        key_bbox=(125.0, 471.0129, 27.624, 8.0),
        value_bbox=(172.624, 471.0129, 174.384, 8.0),
        key_character_range=(277, 283),
        value_character_range=(283, 327),
        key_public_item_id="p2-i8",
        value_public_item_id="p2-i9",
        key_element_id="el-70d056d4a15b5143497a",
        value_element_id="el-6049a2c82a0acd74199c",
    ),
    _pair(
        pair_key="gpio-functions:gpio25",
        group_key="gpio-functions",
        page_index=2,
        key="GPIO25",
        value="OP Connected to user LED",
        key_bbox=(125.0, 489.4049, 27.624, 8.0),
        value_bbox=(172.624, 489.4049, 93.496, 8.0),
        key_character_range=(327, 333),
        value_character_range=(333, 357),
        key_public_item_id="p2-i10",
        value_public_item_id="p2-i11",
        key_element_id="el-15fe2bfa8f3b0fab034a",
        value_element_id="el-c990b93b5d66dbc37c9a",
    ),
    _pair(
        pair_key="gpio-functions:gpio24",
        group_key="gpio-functions",
        page_index=2,
        key="GPIO24",
        value="IP VBUS sense - high if VBUS is present, else low",
        key_bbox=(125.0, 507.7969, 27.624, 8.0),
        value_bbox=(172.624, 507.7969, 171.64, 8.0),
        key_character_range=(357, 363),
        value_character_range=(363, 412),
        key_public_item_id="p2-i12",
        value_public_item_id="p2-i13",
        key_element_id="el-6763021f4c866aac06af",
        value_element_id="el-90d9c3699ee3113f8bb7",
    ),
    _pair(
        pair_key="gpio-functions:gpio23",
        group_key="gpio-functions",
        page_index=2,
        key="GPIO23",
        value=(
            "OP Controls the on-board SMPS Power Save pin (Section 4.4)"
        ),
        key_bbox=(125.0, 526.1889, 27.624, 8.0),
        value_bbox=(172.624, 526.1889, 216.76, 8.0),
        key_character_range=(412, 418),
        value_character_range=(418, 476),
        key_public_item_id="p2-i14",
        value_public_item_id="p2-i15",
        key_element_id="el-0113e0feca8013457925",
        value_element_id="el-61cb7b46f4cb2a8fd27f",
    ),
    _pair(
        pair_key="interface-pins:pin40",
        group_key="interface-pins",
        page_index=2,
        key="PIN40",
        value="VBUS",
        key_bbox=(125.0, 563.36487, 22.304, 8.0),
        value_bbox=(167.304, 563.36487, 19.992, 8.0),
        key_character_range=(561, 566),
        value_character_range=(566, 570),
        key_public_item_id="p2-i17",
        value_public_item_id="p2-i18",
        key_element_id="el-78a1ad6893ccdfd64691",
        value_element_id="el-9b72d6b0beace96fac21",
    ),
    _pair(
        pair_key="interface-pins:pin39",
        group_key="interface-pins",
        page_index=2,
        key="PIN39",
        value="VSYS",
        key_bbox=(125.0, 581.7569, 22.304, 8.0),
        value_bbox=(167.304, 581.7569, 19.376, 8.0),
        key_character_range=(570, 575),
        value_character_range=(575, 579),
        key_public_item_id="p2-i19",
        value_public_item_id="p2-i20",
        key_element_id="el-4a78f4ef3a2f90d41037",
        value_element_id="el-f75c6ef63adadfa4c08a",
    ),
    _pair(
        pair_key="interface-pins:pin37",
        group_key="interface-pins",
        page_index=2,
        key="PIN37",
        value="3V3_EN",
        key_bbox=(125.0, 600.1489, 22.304, 8.0),
        value_bbox=(167.304, 600.1489, 27.912, 8.0),
        key_character_range=(579, 584),
        value_character_range=(584, 590),
        key_public_item_id="p2-i21",
        value_public_item_id="p2-i22",
        key_element_id="el-0bf8f92842872ba3fe80",
        value_element_id="el-0134b0937bc5d2751df7",
    ),
    _pair(
        pair_key="interface-pins:pin36",
        group_key="interface-pins",
        page_index=2,
        key="PIN36",
        value="3V3",
        key_bbox=(125.0, 618.5409, 22.304, 8.0),
        value_bbox=(167.304, 618.5409, 14.064, 8.0),
        key_character_range=(590, 595),
        value_character_range=(595, 598),
        key_public_item_id="p2-i23",
        value_public_item_id="p2-i24",
        key_element_id="el-ad8a1baa4a9a753694df",
        value_element_id="el-4571ceff2af6c638a29c",
    ),
    _pair(
        pair_key="interface-pins:pin35",
        group_key="interface-pins",
        page_index=2,
        key="PIN35",
        value="ADC_VREF",
        key_bbox=(125.0, 636.9329, 22.304, 8.0),
        value_bbox=(167.304, 636.9329, 38.232, 8.0),
        key_character_range=(598, 603),
        value_character_range=(603, 611),
        key_public_item_id="p2-i25",
        value_public_item_id="p2-i26",
        key_element_id="el-572643be27a4fab45b8c",
        value_element_id="el-a037cd02067e3f26c4cd",
    ),
    _pair(
        pair_key="interface-pins:pin33",
        group_key="interface-pins",
        page_index=2,
        key="PIN33",
        value="AGND",
        key_bbox=(125.0, 655.32489, 22.304, 8.0),
        value_bbox=(167.304, 655.32489, 21.6, 8.0),
        key_character_range=(611, 616),
        value_character_range=(616, 620),
        key_public_item_id="p2-i27",
        value_public_item_id="p2-i28",
        key_element_id="el-71eef1253aed2a5951fc",
        value_element_id="el-890d26a2c0eb344e71d9",
    ),
    _pair(
        pair_key="interface-pins:pin30",
        group_key="interface-pins",
        page_index=2,
        key="PIN30",
        value="RUN",
        key_bbox=(125.0, 673.71689, 22.304, 8.0),
        value_bbox=(167.304, 673.71689, 15.8, 8.0),
        key_character_range=(620, 625),
        value_character_range=(625, 628),
        key_public_item_id="p2-i29",
        value_public_item_id="p2-i30",
        key_element_id="el-4637813b7c6d29a5baeb",
        value_element_id="el-7d38877d4754e9d5b2c7",
    ),
    _pair(
        pair_key="operating-conditions:operating-temp-max",
        group_key="operating-conditions",
        page_index=3,
        key="Operating Temp Max",
        value="85°C (including self-heating)",
        key_bbox=(125.0, 142.96, 75.408, 8.0),
        value_bbox=(220.408, 142.96, 100.504, 8.0),
        key_character_range=(162, 180),
        value_character_range=(180, 209),
        key_public_item_id="p3-i4",
        value_public_item_id="p3-i5",
        key_element_id="el-972af7e91a63058873da",
        value_element_id="el-a7dcffe538b6247dbc1a",
    ),
    _pair(
        pair_key="operating-conditions:operating-temp-min",
        group_key="operating-conditions",
        page_index=3,
        key="Operating Temp Min",
        value="-20°C",
        key_bbox=(125.0, 161.352, 73.656, 8.0),
        value_bbox=(220.408, 161.352, 19.36, 8.0),
        key_character_range=(209, 227),
        value_character_range=(227, 232),
        key_public_item_id="p3-i6",
        value_public_item_id="p3-i7",
        key_element_id="el-1efbaac715c919769cd7",
        value_element_id="el-ebd050f46dbe94be45a3",
    ),
    _pair(
        pair_key="operating-conditions:vbus",
        group_key="operating-conditions",
        page_index=3,
        key="VBUS",
        value="5V ± 10%.",
        key_bbox=(125.0, 179.744, 20.504, 8.0),
        value_bbox=(220.408, 179.744, 34.736, 8.0),
        key_character_range=(232, 236),
        value_character_range=(236, 245),
        key_public_item_id="p3-i8",
        value_public_item_id="p3-i9",
        key_element_id="el-d3bebaa0183ebc00de12",
        value_element_id="el-acccccb1468968c69ac3",
    ),
    _pair(
        pair_key="operating-conditions:vsys-min",
        group_key="operating-conditions",
        page_index=3,
        key="VSYS Min",
        value="1.8V",
        key_bbox=(125.0, 198.136, 35.584, 8.0),
        value_bbox=(220.408, 198.136, 16.168, 8.0),
        key_character_range=(245, 253),
        value_character_range=(253, 257),
        key_public_item_id="p3-i10",
        value_public_item_id="p3-i11",
        key_element_id="el-8c611b850b4c5a7cf4f0",
        value_element_id="el-bb04b7c5d369e54e36d8",
    ),
    _pair(
        pair_key="operating-conditions:vsys-max",
        group_key="operating-conditions",
        page_index=3,
        key="VSYS Max",
        value="5.5V",
        key_bbox=(125.0, 216.528, 37.336, 8.0),
        value_bbox=(220.408, 216.528, 16.168, 8.0),
        key_character_range=(257, 265),
        value_character_range=(265, 269),
        key_public_item_id="p3-i12",
        value_public_item_id="p3-i13",
        key_element_id="el-cc298b7f1c5e2b74bc95",
        value_element_id="el-4ce058b3aadfe80f9d85",
    ),
)


ACORD_RELATIONSHIP_ORACLE: Final = (
    *tuple(
        ("contains", f"group:{field['group_key']}", f"field:{field['field_key']}")
        for field in ACORD_EMPTY_FIELD_ORACLE
    ),
    *tuple(
        ("contains", f"group:{label['group_key']}", f"label:{label['label_key']}")
        for label in ACORD_LABEL_ORACLE
    ),
    *tuple(
        ("contains", "group:coverages", f"control:{control['control_key']}")
        for control in ACORD_CONTROL_ORACLE
    ),
    *tuple(
        (
            "contains",
            f"field:{field['field_key']}",
            f"value-region:{field['field_key']}",
        )
        for field in ACORD_EMPTY_FIELD_ORACLE
    ),
    *tuple(
        (
            "label_of",
            f"label:{label['label_key']}",
            f"{label['label_role']}:{target_key}",
        )
        for label in ACORD_LABEL_ORACLE
        for target_key in label["label_of_keys"]
    ),
    *tuple(
        (
            "value_of",
            f"value-region:{field['field_key']}",
            f"field:{field['field_key']}",
        )
        for field in ACORD_EMPTY_FIELD_ORACLE
    ),
    *tuple(
        (
            "control_of",
            f"control:{control['control_key']}",
            "group:coverages",
        )
        for control in ACORD_CONTROL_ORACLE
    ),
    (
        "form_overlay_of",
        "group:parties-and-insurers",
        "anchor-element:el-d48558bc276571415f1c",
    ),
    (
        "form_overlay_of",
        "group:coverages",
        "anchor-element:el-2300235f191fabb4bfc4",
    ),
)


COMPONENT_RELATIONSHIP_ORACLE: Final = (
    *tuple(
        (
            "contains",
            f"group:{pair['group_key']}",
            f"pair:{pair['pair_key']}",
        )
        for pair in COMPONENT_KEY_VALUE_PAIR_ORACLE
    ),
    *tuple(
        (
            "contains",
            f"pair:{pair['pair_key']}",
            f"label:{pair['pair_key']}",
        )
        for pair in COMPONENT_KEY_VALUE_PAIR_ORACLE
    ),
    *tuple(
        (
            "contains",
            f"pair:{pair['pair_key']}",
            f"value-region:{pair['pair_key']}",
        )
        for pair in COMPONENT_KEY_VALUE_PAIR_ORACLE
    ),
    *tuple(
        (
            "key_of",
            f"label:{pair['pair_key']}",
            f"pair:{pair['pair_key']}",
        )
        for pair in COMPONENT_KEY_VALUE_PAIR_ORACLE
    ),
    *tuple(
        (
            "value_of",
            f"value-region:{pair['pair_key']}",
            f"pair:{pair['pair_key']}",
        )
        for pair in COMPONENT_KEY_VALUE_PAIR_ORACLE
    ),
)


ACORD_CANONICAL_INERT_ORACLE: Final = {
    # All other static groups remain inert.  The complete resolved
    # parties/insurers group is the sole source-reviewed replacement.
    "body_markdown_utf8_bytes": 4_965,
    "body_markdown_sha256": (
        "6cdfa104f231d2352b6601cc5eaf4772f1ca47d76b25fa58736a921c60737c85"
    ),
    "body_text_utf8_bytes": 2_863,
    "body_text_sha256": (
        "d87874de46c6043510359d07a2b4e320a9cc8c8f32df2428580dc080eb47ad42"
    ),
    "full_markdown_utf8_bytes": 5_094,
    "full_markdown_sha256": (
        "0457321777c49fef2cc7b230c431a30490203bed5f5f260e45b7195fe444832d"
    ),
    "full_text_utf8_bytes": 2_992,
    "full_text_sha256": (
        "7e4af01b8ec9c45d32e6142a06f976a9291cd57e0fe6b387cf98c10306a1c423"
    ),
}


COMPONENT_CANONICAL_ORACLE: Final = {
    "gpio-functions": {
        "markdown": (
            "- **GPIO29:** IP Used in ADC mode (ADC3) to measure VSYS/3\n"
            "- **GPIO25:** OP Connected to user LED\n"
            "- **GPIO24:** IP VBUS sense - high if VBUS is present, else low\n"
            "- **GPIO23:** OP Controls the on-board SMPS Power Save pin "
            "(Section 4.4)"
        ),
        "text": (
            "GPIO29: IP Used in ADC mode (ADC3) to measure VSYS/3\n"
            "GPIO25: OP Connected to user LED\n"
            "GPIO24: IP VBUS sense - high if VBUS is present, else low\n"
            "GPIO23: OP Controls the on-board SMPS Power Save pin "
            "(Section 4.4)"
        ),
        "markdown_sha256": (
            "a31c828ad7b2a05f443a2f218f45974fe5f20770ff7efeda8f9a97bcbb41f142"
        ),
        "text_sha256": (
            "3597c25f555ec1ef3546ac789c2b7b366cb1a0e3416344859ee1fc683ca599a8"
        ),
    },
    "interface-pins": {
        "markdown": (
            "- **PIN40:** VBUS\n"
            "- **PIN39:** VSYS\n"
            "- **PIN37:** 3V3_EN\n"
            "- **PIN36:** 3V3\n"
            "- **PIN35:** ADC_VREF\n"
            "- **PIN33:** AGND\n"
            "- **PIN30:** RUN"
        ),
        "text": (
            "PIN40: VBUS\n"
            "PIN39: VSYS\n"
            "PIN37: 3V3_EN\n"
            "PIN36: 3V3\n"
            "PIN35: ADC_VREF\n"
            "PIN33: AGND\n"
            "PIN30: RUN"
        ),
        "markdown_sha256": (
            "9fc90f06bcadd8551017509f3040b0a9077daa773a4054ec2c2427de56b144c2"
        ),
        "text_sha256": (
            "c22c26249d6715002cb9e422e5563f6ec9768a1dcadb908f922dc81906a9ea97"
        ),
    },
    "operating-conditions": {
        "markdown": (
            "- **Operating Temp Max:** 85°C (including self-heating)\n"
            "- **Operating Temp Min:** -20°C\n"
            "- **VBUS:** 5V ± 10%.\n"
            "- **VSYS Min:** 1.8V\n"
            "- **VSYS Max:** 5.5V"
        ),
        "text": (
            "Operating Temp Max: 85°C (including self-heating)\n"
            "Operating Temp Min: -20°C\n"
            "VBUS: 5V ± 10%.\n"
            "VSYS Min: 1.8V\n"
            "VSYS Max: 5.5V"
        ),
        "markdown_sha256": (
            "402fe494bff445edc8d06dcf9672b3f0ea9d3945e97869363cb9aecc0ba7adbe"
        ),
        "text_sha256": (
            "255ecbdc4171647cadc5ec162fc5082dc87f592adce44742847354667b018667"
        ),
    },
}


ACORD_REVIEWED_COUNTS: Final = {
    "group_count": 6,
    "field_group_label_header_count": 22,
    "field_bearing_label_header_count": 19,
    "group_only_heading_count": 3,
    "control_label_count": 20,
    "total_label_count": 42,
    "empty_field_count": 24,
    "label_field_relationship_count": 30,
    "label_group_relationship_count": 3,
    "label_control_relationship_count": 20,
    "total_label_relationship_count": 53,
    "control_count": 24,
    "unchecked_control_count": 19,
    "ambiguous_control_count": 5,
    "checked_control_count": 0,
    "contains_relationship_count": 114,
    "value_relationship_count": 24,
    "control_relationship_count": 24,
    "form_overlay_relationship_count": 2,
    "total_relationship_count": 217,
    "fabricated_value_count": 0,
    "fabricated_signature_count": 0,
}


COMPONENT_REVIEWED_COUNTS: Final = {
    "group_count": 3,
    "pair_count": 16,
    "key_label_count": 16,
    "present_value_region_count": 16,
    "contains_relationship_count": 48,
    "key_relationship_count": 16,
    "value_relationship_count": 16,
    "total_relationship_count": 80,
}
