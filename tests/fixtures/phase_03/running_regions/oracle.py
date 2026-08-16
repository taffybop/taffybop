"""Immutable source-reviewed oracle for P03-US08.

All coordinates are ``[x, y, width, height]`` in top-left PDF points in the
displayed page space after source rotation.  The data is deliberately static:
production code must derive these facts from the PDF/IR and must not import
this fixture.

The accepted running-region denominator is 47 records.  It consists of the
41 frozen Phase-00 predecessor header/footer anchors plus six reviewed
corrections.  Manufacturing page 2 has no standalone predecessor header item;
the repeated report header is native text fused into chart ``p2-i1`` and is
therefore represented as an extracted contribution of that exact item.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from typing import Any, Final, Literal

POLICY_ID: Final = "p03-running-regions-page-identity-v1"
COORDINATE_CONTRACT: Final = {
    "bbox_format": "[x,y,width,height]",
    "origin": "top_left",
    "page_space": "displayed_after_source_rotation",
    "unit": "pt",
}

CORPUS_REGISTRY_CUSTODY: Final = {
    "path": "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json",
    "size_bytes": 20_744,
    "sha256": "f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb",
    "case_count": 15,
    "page_count": 30,
    "source_files_immutable": True,
}

SOURCE_IDENTITIES: Final = {
    "catastrophe-recap": {
        "path": "benchmark-expertmodeldata/catastrophe-recap.pdf",
        "size_bytes": 58_779,
        "sha256": "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e",
        "page_count": 1,
    },
    "clean-energy": {
        "path": "benchmark-expertmodeldata/clean-energy.pdf",
        "size_bytes": 122_014,
        "sha256": "161d513c3ffa53ee3967bac6a7bb420d5d60a2008f79b4f7421b83e9b3a11a7d",
        "page_count": 1,
    },
    "clinical-study": {
        "path": "benchmark-expertmodeldata/clinical-study.pdf",
        "size_bytes": 750_004,
        "sha256": "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2",
        "page_count": 4,
    },
    "component-datasheet": {
        "path": "benchmark-expertmodeldata/component-datasheet.pdf",
        "size_bytes": 329_199,
        "sha256": "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4",
        "page_count": 3,
    },
    "egov-survey": {
        "path": "benchmark-expertmodeldata/egov-survey.pdf",
        "size_bytes": 82_800,
        "sha256": "7b6b95d79149c16297c6f7280caed0e14b7dcd53ad5067cb2657885b90562846",
        "page_count": 1,
    },
    "esg-metrics": {
        "path": "benchmark-expertmodeldata/esg-metrics.pdf",
        "size_bytes": 60_516,
        "sha256": "6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9",
        "page_count": 1,
    },
    "finance-10k": {
        "path": "benchmark-expertmodeldata/finance-10k.pdf",
        "size_bytes": 87_105,
        "sha256": "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086",
        "page_count": 3,
    },
    "health-report": {
        "path": "benchmark-expertmodeldata/health-report.pdf",
        "size_bytes": 222_282,
        "sha256": "fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181",
        "page_count": 1,
    },
    "insurance-acord": {
        "path": "benchmark-expertmodeldata/insurance-acord.pdf",
        "size_bytes": 17_086,
        "sha256": "85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4",
        "page_count": 1,
    },
    "manufacturing-report": {
        "path": "benchmark-expertmodeldata/manufacturing-report.pdf",
        "size_bytes": 380_274,
        "sha256": "414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f",
        "page_count": 3,
    },
    "ny-timetable": {
        "path": "benchmark-expertmodeldata/ny-timetable.pdf",
        "size_bytes": 26_109,
        "sha256": "f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30",
        "page_count": 3,
    },
    "postal-10k": {
        "path": "benchmark-expertmodeldata/postal-10k.pdf",
        "size_bytes": 83_589,
        "sha256": "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74",
        "page_count": 3,
    },
    "purchase-agreement": {
        "path": "benchmark-expertmodeldata/purchase-agreement.pdf",
        "size_bytes": 152_828,
        "sha256": "00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14",
        "page_count": 1,
    },
    "settlement-agreement": {
        "path": "benchmark-expertmodeldata/settlement-agreement.pdf",
        "size_bytes": 164_483,
        "sha256": "adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc",
        "page_count": 1,
    },
    "uber-earnings": {
        "path": "benchmark-expertmodeldata/uber-earnings.pdf",
        "size_bytes": 7_584_019,
        "sha256": "76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5",
        "page_count": 3,
    },
}

PREDECESSOR_OUTPUT_IDENTITIES: Final = {
    "catastrophe-recap": {
        "size_bytes": 69_758,
        "sha256": "f9db554d1975d498a6f9e3d53c0058716847335ee661c3fb3cd6c0c0acc8a4a3",
    },
    "clean-energy": {
        "size_bytes": 111_243,
        "sha256": "21050d7af267019ba6720093651074c1931552907246a3a154c102181d5df0ca",
    },
    "clinical-study": {
        "size_bytes": 451_585,
        "sha256": "3ec1d78b593407c9812b0ac76178eb104f655320f3a70b4ee30a733e4ba35187",
    },
    "component-datasheet": {
        "size_bytes": 369_155,
        "sha256": "00fcf0dfbaa2f8f1da24750b2b5918e781d2a71d05dd0e1b387bcc3951b97e94",
    },
    "egov-survey": {
        "size_bytes": 96_709,
        "sha256": "c402d688e7f7511aaf4a59fdb091402f63009dd8eb14ce397f7f777f8f6b8044",
    },
    "esg-metrics": {
        "size_bytes": 119_728,
        "sha256": "36136da8e64cdd476491c9ca9953e5df1171d252836f456a7f5af55580871086",
    },
    "finance-10k": {
        "size_bytes": 428_370,
        "sha256": "66f03479bbcd4f5529c0b1b411676930c383782c3628fc0f6a9ad8fb8bdf34ca",
    },
    "health-report": {
        "size_bytes": 112_320,
        "sha256": "e483d0a060041bf80c3324cc4c8479fd9fa1096b4972d851d2b5cf8bfb6e6f08",
    },
    "insurance-acord": {
        "size_bytes": 217_546,
        "sha256": "406abe4b9c103f1eff0d4d0dcc6d66a5a12a09b7df1c9ce5c3c8d41c17607d01",
    },
    "manufacturing-report": {
        "size_bytes": 468_065,
        "sha256": "bd64984f748aab212a8e17d6a871bcd0dde45ca782d76467a7545c126d4cdfd4",
    },
    "ny-timetable": {
        "size_bytes": 1_445_395,
        "sha256": "e722f937a1dc5cf878640b6cecaa3faf259d290653aeb3b669d0c60956b8b824",
    },
    "postal-10k": {
        "size_bytes": 387_747,
        "sha256": "85d9f0719879e0cf2647bd717a88e5227489673730ebbf8961238497849fab6e",
    },
    "purchase-agreement": {
        "size_bytes": 82_756,
        "sha256": "c39203bd6ba6ff60d4eb38927e770cfe51629c90ea756e3f0510e359f9ec210f",
    },
    "settlement-agreement": {
        "size_bytes": 66_341,
        "sha256": "e3ef50fcad4f7212c5354cb29bc2ff85dfa50794fc063f90fa317874abdb0405",
    },
    "uber-earnings": {
        "size_bytes": 187_317,
        "sha256": "66fe7588ba8cbe1f1284d60be4241e462b984ffeb82cc659fa236a61192849f3",
    },
}

PREDECESSOR_OUTPUT_ROOT: Final = (
    "tracker/phase-03-layout/evidence/"
    "P03-US08-post-US07-predecessor-20260801"
)

PREDECESSOR_CONFIGURATION: Final = {
    "shared_ir_enabled": True,
    "shared_ir_normalization_enabled": True,
    "canonical_serialization_enabled": True,
    "layout_table_captions_enabled": True,
    "layout_visual_relationships_enabled": True,
    "layout_source_notes_enabled": True,
    "layout_relationship_order_enabled": True,
    "layout_text_run_semantics_enabled": True,
    "layout_forms_enabled": True,
    "layout_outline_structure_enabled": True,
}

RegionKind = Literal[
    "header",
    "footer",
    "navigation_top",
    "navigation_bottom",
]
CanonicalScope = Literal["header", "footer"]

PAGE_IDENTITY_CONTRACT_FIELDS: Final = (
    "schema_version",
    "policy_id",
    "page_id",
    "physical_page_index",
    "embedded_label",
    "detected_printed_label",
    "visible_text",
    "display_label",
    "display_source",
    "evidence_bbox",
    "evidence_source",
    "confidence",
    "concern_codes",
)
RUNNING_REGION_CONTRACT_FIELDS: Final = (
    "id",
    "page_id",
    "physical_page_index",
    "role",
    "canonical_scope",
    "source_public_item_id",
    "source_public_path",
    "source_element_id",
    "predecessor_type",
    "predecessor_item_sha256",
    "bbox_id",
    "bbox",
    "evidence_ids",
    "source_object_ids",
    "source_method",
    "repetition_group_id",
    "repetition_page_indexes",
    "confidence",
    "concern_codes",
    "canonical_block_id",
)


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


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(
        parts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:20]}"


PAGE_BINDING_ROWS: Final = (
    ("catastrophe-recap", 1, "page-fde30c3085d82c083f0c", 1, "1", 36, 36, 202, 202),
    ("clean-energy", 1, "page-8231b070a759c6fcd265", 1, "1", 43, 51, 8, 10),
    ("clinical-study", 1, "page-b9e7790196e72022cd22", 1, "1", 2531, 2534, 103, 103),
    ("clinical-study", 2, "page-db99270eff97469b23a7", 2, "2", 2576, 2579, 192, 192),
    ("clinical-study", 3, "page-5df69e1430d1a1e5fccd", 3, "3", 206, 210, 7, 7),
    ("clinical-study", 4, "page-24bd0d79e1e2fa1161ff", 4, "4", 3375, 3379, 142, 142),
    ("component-datasheet", 1, "page-56fbfad4aaa8ae5e00b9", 1, "1", 1340, 1340, 225, 225),
    ("component-datasheet", 2, "page-f0d21be79b4d7536997c", 2, "2", 1170, 1170, 223, 223),
    ("component-datasheet", 3, "page-34482fe7de7796bd8d4a", 3, "3", 495, 496, 77, 77),
    ("egov-survey", 1, "page-f7b70136975497351c9b", 1, "1", 0, 1, 0, 0),
    ("esg-metrics", 1, "page-25daba85834d92b02658", 1, "1", 1598, 1599, 366, 366),
    ("finance-10k", 1, "page-5025f5d032cf94d185f0", 1, "1", 1212, 1213, 175, 175),
    ("finance-10k", 2, "page-9d6574ad9f1cc18033ed", 2, "2", 1615, 1616, 211, 211),
    ("finance-10k", 3, "page-8f5c917be11ca7225d20", 3, "3", 2244, 2245, 305, 305),
    ("health-report", 1, "page-4e0e1db43cc2c7a3638b", 1, "1", 4, 6, 1, 1),
    ("insurance-acord", 1, "page-75c247935b2563aa89c9", 1, "1", None, None, None, None),
    ("manufacturing-report", 1, "page-23f4c7d81b5e66299f72", 1, "1", 30, 31, 138, 138),
    ("manufacturing-report", 2, "page-f8667899ba1ad11e7e5d", 2, "2", 30, 31, 57, 57),
    ("manufacturing-report", 3, "page-6cfea76c2f8b69a3e3b3", 3, "3", 30, 31, 270, 270),
    ("ny-timetable", 1, "page-0f91a5af229835b4f531", 2, "2", 2588, 2599, 630, 633),
    ("ny-timetable", 2, "page-9e8ff8f45474c58f7f85", 3, "3", 2947, 2958, 632, 635),
    ("ny-timetable", 3, "page-c6444b6601c75245d18d", 4, "4", 2597, 2608, 640, 643),
    ("postal-10k", 1, "page-815f8d6f4ad27cb9f42e", 1, "1", 1823, 1823, 273, 273),
    ("postal-10k", 2, "page-4c09811eb0443e421ff2", 2, "2", 770, 771, 111, 111),
    ("postal-10k", 3, "page-a46c9cb33289b9186ef6", 3, "3", 2132, 2133, 316, 316),
    ("purchase-agreement", 1, "page-d5aad0dbe770b22455af", 1, "1", None, None, None, None),
    ("settlement-agreement", 1, "page-a04cad0ab8f1a940efb1", 1, "1", 0, 1, 443, 443),
    ("uber-earnings", 1, "page-a41a0a068c6dd96a00c5", 1, "1", None, None, None, None),
    ("uber-earnings", 2, "page-760c95e4fbe054f8526e", 2, "2", 80, 80, 113, 113),
    ("uber-earnings", 3, "page-077e504865913fa1e19b", 3, "3", 0, 0, 58, 58),
)

SOURCE_PAGE_COUNT_ROWS: Final = (
    ("catastrophe-recap", 1, 1_414, 203),
    ("clean-energy", 1, 611, 122),
    ("clinical-study", 1, 3_636, 104),
    ("clinical-study", 2, 2_580, 193),
    ("clinical-study", 3, 211, 8),
    ("clinical-study", 4, 3_380, 143),
    ("component-datasheet", 1, 1_341, 226),
    ("component-datasheet", 2, 1_171, 224),
    ("component-datasheet", 3, 497, 78),
    ("egov-survey", 1, 2_756, 469),
    ("esg-metrics", 1, 1_685, 367),
    ("finance-10k", 1, 1_214, 176),
    ("finance-10k", 2, 1_617, 212),
    ("finance-10k", 3, 2_246, 306),
    ("health-report", 1, 1_154, 246),
    ("insurance-acord", 1, 2_843, 495),
    ("manufacturing-report", 1, 990, 139),
    ("manufacturing-report", 2, 1_650, 333),
    ("manufacturing-report", 3, 1_841, 301),
    ("ny-timetable", 1, 2_600, 634),
    ("ny-timetable", 2, 2_959, 636),
    ("ny-timetable", 3, 2_609, 644),
    ("postal-10k", 1, 1_824, 274),
    ("postal-10k", 2, 772, 112),
    ("postal-10k", 3, 2_134, 317),
    ("purchase-agreement", 1, 3_338, 489),
    ("settlement-agreement", 1, 2_699, 444),
    ("uber-earnings", 1, 70, 12),
    ("uber-earnings", 2, 626, 114),
    ("uber-earnings", 3, 393, 59),
)

SOURCE_PAGE_COUNTS: Final = {
    (case_id, physical_page): {
        "source_character_count": character_count,
        "source_word_count": word_count,
    }
    for case_id, physical_page, character_count, word_count in (
        SOURCE_PAGE_COUNT_ROWS
    )
}

PAGE_BINDINGS: Final = {
    (case_id, physical_page): {
        "page_id": page_id,
        "legacy_page_index": physical_page,
        "legacy_page_number": legacy_page_number,
        "legacy_page_label": legacy_page_label,
        "source_character_indexes": (
            tuple(range(char_start, char_end + 1))
            if char_start is not None and char_end is not None
            else ()
        ),
        "source_word_indexes": (
            tuple(range(word_start, word_end + 1))
            if word_start is not None and word_end is not None
            else ()
        ),
    }
    for (
        case_id,
        physical_page,
        page_id,
        legacy_page_number,
        legacy_page_label,
        char_start,
        char_end,
        word_start,
        word_end,
    ) in PAGE_BINDING_ROWS
}


ITEM_BINDING_ROWS: Final = (('catastrophe-recap',
  1,
  'p1-i6',
  8,
  'el-00cd3edf6b7133d53720',
  'box-be16d5f34f335b0bbca6',
  'ev-d3ec6cd4d33be7451770',
  'pb-b9f2172e582c6c44098a',
  '567a62d91b4b8200c6b893a2100986f29abf79d3e664b2f30412fb611d959c21',
  197,
  202,
  'layout-note-af58a03da292b26ce13f',
  None),
 ('clean-energy',
  1,
  'p1-i1',
  0,
  'el-d3789c2dcf4fcb5ccf77',
  'box-bce218ddc96b5ee76877',
  'ev-f2072be09807987334d8',
  'pb-84ae7c3995c46c338a17',
  'bd9c34890ffad86709e7f8fbc8da95afdb550890134818f318fbe356f7035549',
  0,
  7,
  None,
  'p1-i2'),
 ('clean-energy',
  1,
  'p1-i8',
  8,
  'el-450645d79f88d0a11312',
  'box-da5027daf767a41644d7',
  'ev-0c8fbb8ac06979f8fe5f',
  'pb-cbe689944354e79cc018',
  '0f0a89b5c771a6b0cc0b88d9de123331098923d5f45515f0584c7e384348db4f',
  8,
  14,
  'p1-i6',
  None),
 ('clinical-study',
  1,
  'p1-i1',
  0,
  'el-89df66d96e241dcd8460',
  'box-8bd53e4ad42b46288615',
  'ev-150875b7b7307bc04f3e',
  'pb-dbe8bd325322fddd3cca',
  'b1d1700be69c8ddcf8f991aae4b5af7927930b2f602dde3c15dc57f28e10c2f8',
  0,
  1,
  None,
  'p1-i15'),
 ('clinical-study',
  1,
  'p1-i24',
  23,
  'el-ca8f25e61065cfd0f154',
  'box-dd863037b18b293ec6a9',
  'ev-5cd69b846dd6c1107ccc',
  'pb-4426296fb99984dfeca5',
  'a3e7603798e14b7347124be4ac80ae8e1c1abaea93c5872cbb6855972618dc64',
  101,
  103,
  'p1-i23',
  None),
 ('clinical-study',
  2,
  'p2-i1',
  0,
  'el-3dd56894bd9db7b5b0f9',
  'box-585c11151cc90a9e1821',
  'ev-93407205a33a2c617ff7',
  'pb-de82e60489aa0847cf3b',
  '0e6f89489c2042cbb32a2c8dba671be59811ab8ad128bafeb65fec09a742f42d',
  0,
  2,
  None,
  'el-f677de07d0e5a8ccb05b'),
 ('clinical-study',
  2,
  'p2-i5',
  9,
  'el-c3e33de52dd45906af02',
  'box-6cac8595c6d9f3814ee6',
  'ev-d0d750f9c187683104fa',
  'pb-4ea9303418cf94915963',
  '36b0f4076209c6c25303a4a2518b8403e74c25aaa6f85ae5b7b2fc347dcbecf9',
  190,
  192,
  'p2-i4',
  None),
 ('clinical-study',
  3,
  'p3-i1',
  0,
  'el-68bc18f0cc29abb893ab',
  'box-41b2407962f1741fb26f',
  'ev-a0ce479eea2587efdfe4',
  'pb-7e3920e26ce8619dd4be',
  '0c09c61a870f07c02daad09f1237a5e3bca978ee266877c9ff69e6df0d7049d7',
  0,
  2,
  None,
  'p3-i2'),
 ('clinical-study',
  3,
  'p3-i3',
  4,
  'el-7692050573c6fe65f93e',
  'box-cc8275307ce986c17a44',
  'ev-d3c4da09a77ee18d1a60',
  'pb-c9df56bc4d0ad67196ef',
  '8782d291c60dc1d308f6d90d361a489bbc67592b85e4255570a5cb10e0577919',
  5,
  7,
  'layout-caption-1c49cc0c4d0076181d81',
  None),
 ('clinical-study',
  4,
  'p4-i1',
  0,
  'el-a40148e7a394dbed414e',
  'box-6bf9aed8d3f9c1e1c5f7',
  'ev-525a507d470cef3908f3',
  'pb-8a56ec9b620017e0597b',
  '4197f1710cac0627611ed827c87fce458432e109e05db94f4f076b96cb041333',
  0,
  2,
  None,
  'el-b9994d3665bd4a257785'),
 ('clinical-study',
  4,
  'p4-i7',
  11,
  'el-f1c736fbbc0e065c82b9',
  'box-8182c168cc15b41bfdc8',
  'ev-37115ea48038332ced3f',
  'pb-eb43c9325778dc1f8332',
  '82022fb23c0b1384e195e77fb2cda66124891c90b339518718409aa3998757f6',
  140,
  142,
  'p4-i6',
  None),
 ('component-datasheet',
  1,
  'p1-i1',
  0,
  'el-c9bdb5a9a5d514ea2a2e',
  'box-1801461381e2786ed029',
  'ev-d2fcadd7bf797f01712f',
  'pb-34de8495d675c1e8ca4b',
  'b37c302ea40121622f51a91f7f0bd972e20994ac6206d8fc524ade526353163e',
  0,
  3,
  None,
  'p1-i3'),
 ('component-datasheet',
  1,
  'p1-i10',
  9,
  'el-d8478728fdb41403d575',
  'box-b7e703e0243a10e01e39',
  'ev-6cdcb8f3de261154d7cb',
  'pb-5c9ff552f05aeb1c4fbd',
  '1f0bcdcf674b3270032cca25e8d3bbea5683f6c3dd60eb7a45912c4a7f19f5cd',
  219,
  225,
  'p1-i9',
  None),
 ('component-datasheet',
  2,
  'p2-i1',
  0,
  'el-7d936fa98c9b65ec108d',
  'box-5b551f245e88a5c9e9ee',
  'ev-0032b655ffe36a069172',
  'pb-dba0ce053a7d4983f55f',
  'f43ae0c1e3ff2d3ce76f6004143df3cdd15aa844948fb27f00c3081d0706932b',
  0,
  3,
  None,
  'p2-i2'),
 ('component-datasheet',
  2,
  'p2-i34',
  33,
  'el-33b8904c20e73886735d',
  'box-c74dd6d38efee2674332',
  'ev-c0038221a4cdd267aa38',
  'pb-c5002098a19ad86a4088',
  'e17216bdcb85eb03d177fbc595d4fa0252084d063b37468ead436f9fb3b7abac',
  218,
  223,
  'p2-i33',
  None),
 ('component-datasheet',
  3,
  'p3-i1',
  0,
  'el-9d81ae468abe35d4b299',
  'box-4ca202634e9b6c9226d6',
  'ev-68307f49aa6c47010344',
  'pb-24d69ba1d635c3ce18ab',
  '7fd9a14286a1fb8ebfbd65a91a50b7bc01200033fb0f49759faed218dab3d1bf',
  0,
  3,
  None,
  'p3-i2'),
 ('component-datasheet',
  3,
  'p3-i16',
  15,
  'el-ff1b5fa13b8a725c903e',
  'box-78ae64fc9abb2a76db74',
  'ev-9be2f414841acca34b13',
  'pb-e37057a197a48eac79c1',
  '811c36f899cadc0b734f64668c042f478e276641ecaeb2e2c8b032067f3f1aa8',
  73,
  77,
  'p3-i15',
  None),
 ('egov-survey',
  1,
  'p1-i1',
  0,
  'el-4612a8d5f8494b9321c2',
  'box-baad0e5dabd937f42b67',
  'ev-b21f645e7e92f5ba6101',
  'pb-0f38680cd7de33d1bc97',
  'e14e14f3e7ff8561a66be9e5b50ebc799d1884ee51f7181ea567e32302e758c3',
  1,
  9,
  None,
  'p1-i2'),
 ('egov-survey',
  1,
  'p1-i8',
  8,
  'el-38e834f289526f75daf7',
  'box-e0ac61c8b9b0afc8bac5',
  'ev-0cdc4d118a3a467559a0',
  'pb-b71a5a25177d026c7d09',
  '8106de90f7d247bfbfd1930d89966c38e2ae0e2f533484fc5cc0010db499c393',
  0,
  0,
  'p1-i7',
  None),
 ('finance-10k',
  1,
  'p1-i1',
  0,
  'el-3c3326239e444637c52e',
  'box-a36328b8b9aa78cdb83c',
  'ev-c00e91fdf48b1d2bae49',
  'pb-512fdbbc3962d03dfeb9',
  '2a03b9993db39b8f0e3a4e9cb564997bd5e07ca7f0ad24c2b8dd953b8231be4f',
  0,
  1,
  None,
  'p1-i2'),
 ('finance-10k',
  1,
  'p1-i6',
  5,
  'el-4f9b777d2d482e979a8e',
  'box-edae245b82f8fd69502b',
  'ev-d8cb16c570a3d4c1be78',
  'pb-5cd4b2fea71ca6e8b75d',
  '06ba629cbcb666e1904295be2c85c3b3cfbacbb8b459df77d25e6cb22ad25da3',
  168,
  175,
  'p1-i5',
  None),
 ('finance-10k',
  2,
  'p2-i6',
  5,
  'el-431de6238d83267cd1ed',
  'box-31aefd4f758f1df54498',
  'ev-ade03115d01792cb6e38',
  'pb-a9952e036d1089c00d40',
  'c85ad8ba8f9a7d74d57b2ef01566e61d79c2a28fc659e01a3358868246c23a9d',
  204,
  211,
  'p2-i5',
  None),
 ('finance-10k',
  3,
  'p3-i6',
  5,
  'el-61c322e596af0bc21c31',
  'box-fb2f77964f76d8c83946',
  'ev-bbb75439cb8d524786cf',
  'pb-e506a14af032507812fe',
  '40577b708931a694260eeb52d96b223cdd1da55ee8bbdd71b936ba4e94ee3d40',
  298,
  305,
  'p3-i5',
  None),
 ('health-report',
  1,
  'p1-i1',
  0,
  'el-9cc89e7b1e7a5901f56d',
  'box-04ca58357ead952a7144',
  'ev-fee07c132578d17b33ad',
  'pb-02ab0fe415dc7af725f1',
  '377a281c3c52fd4f32a4e6e35424ab8e0e7b65caeca1fd6cdee6f38a47e7dbd1',
  0,
  1,
  None,
  'layout-caption-fc93bc7268829b0bfd30'),
 ('health-report',
  1,
  'p1-i10',
  11,
  'el-fec6b8723b7dda268e0c',
  'box-6f8943d778da54197e27',
  'ev-9bd083b543a732ac03a1',
  'pb-d51cc1efa687386b7d58',
  '8d0a4a37b2824529bfd133d17602494d0f6010936a669ba2688529f71ea00bea',
  120,
  129,
  'p1-i8',
  None),
 ('insurance-acord',
  1,
  'p1-i21',
  20,
  'el-16d94523f365642fcb70',
  'box-b400567aa8ecd49de466',
  'ev-ab1f6215ef737ce8ce0e',
  'pb-4c6cfec05bb3d54bd940',
  '1658d206ca894c54bcacf358d6cf02cc4276597562d76c0149c7bbc3d2b9a93f',
  475,
  494,
  'p1-i18',
  None),
 ('manufacturing-report',
  1,
  'p1-i1',
  0,
  'el-f21c777f143ca02c409d',
  'box-b7972cd1bff8ec9c1e84',
  'ev-fc2ff6e3b4f3a7f627e5',
  'pb-4e5ceae7ccbbfcd11bc0',
  '03c3e120f03cffb6fc1bdbff43750fb689bba5ac9293217546bc831104ff57fa',
  0,
  4,
  None,
  'p1-i2'),
 ('manufacturing-report',
  1,
  'p1-i8',
  8,
  'el-6838889334fea6bd7784',
  'box-8bb1b8977c807e836840',
  'ev-c032482535813a5cddaa',
  'pb-e8b857728ada248ec9b6',
  '34f9c4bbbbf05895bdf3141c2110a20200a2eb7d4868a6a3ca380f553381f81d',
  138,
  138,
  'p1-i7',
  None),
 ('manufacturing-report',
  2,
  'p2-i5',
  6,
  'el-ce03fe4c71bf574975a8',
  'box-3fef5257a02c0e0bf544',
  'ev-34d108230ba90c3b6925',
  'pb-c29d7b88aee2b6280eab',
  '569d7ac13e97ab35e7d7c9bcd034597b1347a949e8ee176862e9882470edf78c',
  57,
  57,
  'p2-i4',
  None),
 ('manufacturing-report',
  3,
  'p3-i1',
  0,
  'el-8022d7187d609481212c',
  'box-06988b362fa4f02ee4bd',
  'ev-0292259afd385c17aeda',
  'pb-95c0530c26b659d40209',
  '61032ef6b97faa253759f4a8d408f622c6a71c23b6febbcbdb698cef76af50c6',
  0,
  4,
  None,
  'p3-i2'),
 ('manufacturing-report',
  3,
  'p3-i9',
  9,
  'el-3e662b2db1b1e667317d',
  'box-ceecc5240de9aa92dc64',
  'ev-162f218450748257ab48',
  'pb-adecd749278529a76d2f',
  '86aed8dc74d13e0e37d2bee3fda2acf2b540064c39cd0398a20f9e13964a8c5b',
  270,
  270,
  'p3-i8',
  None),
 ('ny-timetable',
  1,
  'p1-i4',
  3,
  'el-3beb12164adc0d84bd43',
  'box-ea74ce35ac565c9ca093',
  'ev-2d4cd7f15b6da359b9c9',
  'pb-3239abc971d67459c099',
  '7b09c2e9f1f244b34f57ba2572acdc82f356c104d4d73270e4c92521ece9022a',
  630,
  633,
  'p1-i3',
  None),
 ('ny-timetable',
  2,
  'p2-i5',
  4,
  'el-61a56a467060a4231e2c',
  'box-e440425c27efaa6fc194',
  'ev-effbceb703a656a33892',
  'pb-96ee91bffb4e44466fd8',
  '765c7b8b440ef3bc73f84f1f3b1e81c9bbb2a08c8e16527cf3ed1585f70ce8d6',
  632,
  635,
  'p2-i3',
  None),
 ('ny-timetable',
  3,
  'p3-i2',
  1,
  'el-7340d170199894439023',
  'box-8236935cf63974723071',
  'ev-910a8825b1cc62f8f7ac',
  'pb-1aa8af7b95418153e574',
  '9839830b4581b006521c362d02bbd3e9431d3fa9549dd1252f87973ce35c1d43',
  640,
  643,
  'p3-i1',
  None),
 ('postal-10k',
  1,
  'p1-i6',
  5,
  'el-8a980e004ae8cfd496e4',
  'box-888585f5a0b7a23926f6',
  'ev-d49756c31fe7b6b0abe8',
  'pb-71033405dd9dc71c30ea',
  'ef67e338a1b14dbec5f58c1cade1064113f2f283c603329179b4a507db86f4c8',
  264,
  273,
  'p1-i5',
  None),
 ('postal-10k',
  2,
  'p2-i4',
  3,
  'el-ba91c524dae2a50b2c3d',
  'box-24e66166fc2c6cadac58',
  'ev-dfbded5037b468418d73',
  'pb-f3cdab2c297acd456a61',
  'd6028aee9102c1e2f89170aa44fa1adefa40befb24c0fbb545ef0d12fbc1a00c',
  102,
  111,
  'p2-i3',
  None),
 ('postal-10k',
  3,
  'p3-i4',
  3,
  'el-645e31b36aa8bfe5d23c',
  'box-285078c3c0c8c8a21a35',
  'ev-b0d8e78ffbd5fa740fb8',
  'pb-dfcfe562cc3e73c95854',
  'c61da07ad75f7d291834a916fb7eb24f4ca731fcb9f2afbcc796bb3f013ba180',
  307,
  316,
  'p3-i3',
  None),
 ('purchase-agreement',
  1,
  'p1-i12',
  11,
  'el-69cecee782b23ff07b2d',
  'box-6020256f63d4d4f53475',
  'ev-a56cad90fa88503041b1',
  'pb-5b5e9087c4e909ece48f',
  'c5d0cb018660c9ef02d8532d6ebfecb31837092ea3e798e0f31614ce3e4f157a',
  488,
  488,
  'p1-i8',
  None),
 ('settlement-agreement',
  1,
  'p1-i6',
  5,
  'el-fe2dd650273eaec517bc',
  'box-604701a8c45ec412094b',
  'ev-b35d99794613cf2c4a5f',
  'pb-6eb4d8a6bb40e8c7f614',
  '7008e89349572840f217a38a1d2f84329faa8f57fc2dfa219d26ce46c14bc20f',
  443,
  443,
  'p1-i5',
  None),
 ('uber-earnings',
  2,
  'p2-i23',
  22,
  'el-8928fff2a45b5be1964c',
  'box-c5c40e9fb718db539f7f',
  'ev-0dac7fe8793f7a8b3e96',
  'pb-a1088edf28e84a9c74aa',
  'e52c974ff15b46e1f055d1bcd6c51ef8459644b6fe5caf5413094053205c833b',
  85,
  113,
  'p2-i22',
  None),
 ('uber-earnings',
  3,
  'p3-i9',
  8,
  'el-fc80c9619bb0c5a37a16',
  'box-6a05d6802fffbdea31b1',
  'ev-1db51494876e924e8b07',
  'pb-76db85460eaaedc8b03e',
  '170c401e96290252d398f06878f44b7ca3583b5c9e7870c85bde0d177776b656',
  55,
  58,
  'p3-i8',
  None),
 ('finance-10k',
  2,
  'p2-i1',
  0,
  'el-5ac4471c3adf2add2850',
  'box-8395852c5b34f4c8f3a8',
  'ev-13bcf88cad9bc799a1c2',
  'pb-d45993b53299f9f8fc68',
  '78f6593a2b53ba269dcc545f12a3eaed5e1dff96e69498273aae7e9fa7d5cdac',
  0,
  1,
  None,
  'p2-i2'),
 ('finance-10k',
  3,
  'p3-i1',
  0,
  'el-7ccdad6a603c6a9d8002',
  'box-393d5f428d0abc91d7e6',
  'ev-1bbed1c5c885bffc7b55',
  'pb-48ac46a24dde8cc66227',
  'f419cc1bf64154b19b5c21094eb26df1b163ded2c2e6ca2f2babdfe476041e69',
  0,
  1,
  None,
  'p3-i2'),
 ('manufacturing-report',
  2,
  'p2-i1',
  0,
  'el-fdde3468a30c4c79051a',
  'box-2797936da9fcc2d0a5d6',
  'ev-dae696ea8306201c821c',
  'pb-aeeac8d2e28fa3e33e18',
  '7ff091ed6cfcddccea0cac2e20b83c13acb49f945dbe03f2842db93212e73c94',
  0,
  4,
  None,
  'p2-i1'),
 ('esg-metrics',
  1,
  'p1-i11',
  17,
  'el-2ae628c0eed35e55a16a',
  'box-ef7caaeafa3c2ca75781',
  'ev-ac766df210b2a6c1d83d',
  'pb-f36464af4ee3e87eb3a9',
  'fd45ff69f67546fc41433622f38eb4d4d3de7e4b3ad4cb081a00ebef05689c53',
  359,
  361,
  'p1-i18',
  'p1-i19'),
 ('esg-metrics',
  1,
  'p1-i19',
  18,
  'el-44305dd96e0fca902ebd',
  'box-df3d8728bbc95716db03',
  'ev-92ec9def449eaf7ed091',
  'pb-c6ebb82aa33c2019364e',
  '6f586bc3716b4f75a8aee6b748dfe153937b9324d88b2e19d4da994a22a936f7',
  362,
  365,
  'p1-i11',
  'p1-i20'),
 ('esg-metrics',
  1,
  'p1-i20',
  19,
  'el-e203399d7bf7d3bf12dc',
  'box-b4087476df97867d4338',
  'ev-f60318436decf25e3df9',
  'pb-de4757d78ada1bcbb4a4',
  '1a6262531d2d23e09102fe47d4b77666d3433a8bbed751e56f8ab98999546840',
  366,
  366,
  'p1-i19',
  None),
)

ITEM_BINDINGS: Final = {
    (case_id, physical_page, item_id): {
        "public_path": ("pages", physical_page - 1, "items", item_offset),
        "owner_element_id": element_id,
        "owner_bbox_id": bbox_id,
        "evidence_ids": (evidence_id,),
        "owner_canonical_block_id": canonical_block_id,
        "predecessor_item_sha256": predecessor_item_sha256,
        "source_word_indexes": tuple(range(word_start, word_end + 1)),
        "order_neighbors": {
            "before_item_id": before_item_id,
            "after_item_id": after_item_id,
        },
    }
    for (
        case_id,
        physical_page,
        item_id,
        item_offset,
        element_id,
        bbox_id,
        evidence_id,
        canonical_block_id,
        predecessor_item_sha256,
        word_start,
        word_end,
        before_item_id,
        after_item_id,
    ) in ITEM_BINDING_ROWS
}


def _source_object_id(
    case_id: str,
    physical_page: int,
    object_kind: Literal["character", "word"],
    index: int,
) -> str:
    return (
        f"pdfplumber:{SOURCE_IDENTITIES[case_id]['sha256']}:"
        f"page:{physical_page}:{object_kind}:{index}"
    )


def _configured_page_label_source_id(
    case_id: str,
    physical_page: int,
) -> str:
    return "configured-predecessor:{}:page:{}:page_label".format(
        SOURCE_IDENTITIES[case_id]["sha256"],
        physical_page,
    )


def _page(
    case_id: str,
    physical_page: int,
    detected_printed_label: str | None,
    width_pt: float,
    height_pt: float,
    source_rotation_deg: int,
    *,
    visible_text: str | None,
    label_bbox: dict[str, float | str] | None,
    predecessor_item_id: str | None,
    predecessor_page_number: int | str,
    label_region_role: Literal["header", "footer"] = "footer",
    null_control_item_id: str | None = None,
) -> dict[str, Any]:
    binding = PAGE_BINDINGS[(case_id, physical_page)]
    display_label = (
        detected_printed_label
        if detected_printed_label is not None
        else str(binding["legacy_page_label"] or physical_page)
    )
    character_indexes = binding["source_character_indexes"]
    word_indexes = binding["source_word_indexes"]
    source_object_ids = tuple(
        _source_object_id(case_id, physical_page, "character", index)
        for index in character_indexes
    ) + tuple(
        _source_object_id(case_id, physical_page, "word", index)
        for index in word_indexes
    )
    label_candidate_id = (
        _stable_id(
            "label-candidate",
            POLICY_ID,
            SOURCE_IDENTITIES[case_id]["sha256"],
            physical_page,
            source_object_ids,
            label_bbox,
        )
        if detected_printed_label is not None
        else None
    )
    return {
        "case_id": case_id,
        "physical_page": physical_page,
        "page_id": binding["page_id"],
        "width_pt": width_pt,
        "height_pt": height_pt,
        "source_rotation_deg": source_rotation_deg,
        "legacy_page_index": binding["legacy_page_index"],
        "legacy_page_number": binding["legacy_page_number"],
        "legacy_page_label": binding["legacy_page_label"],
        "embedded_label": None,
        "detected_printed_label": detected_printed_label,
        "is_detected_printed_label": detected_printed_label is not None,
        "display_label": display_label,
        "display_source": (
            "detected_printed_label"
            if detected_printed_label is not None
            else "legacy_display_fallback"
        ),
        "label_region_role": (
            label_region_role if detected_printed_label is not None else None
        ),
        "visible_text": visible_text,
        "visible_text_sha256": (
            _text_sha256(visible_text) if visible_text is not None else None
        ),
        "label_bbox": label_bbox,
        "bbox_scope": "visible_text" if visible_text is not None else None,
        "source_character_indexes": character_indexes,
        "source_word_indexes": word_indexes,
        "source_object_ids": source_object_ids,
        "label_candidate_id": label_candidate_id,
        "evidence_source": {
            "method": (
                "native_printed_label"
                if detected_printed_label is not None
                else "legacy_display_fallback"
            ),
            "reader": (
                "pdfplumber"
                if detected_printed_label is not None
                else "configured_predecessor"
            ),
            "page_index": physical_page,
            "public_item_id": None,
            "public_path": (),
            "element_id": None,
            "bbox_id": None,
            "evidence_ids": (
                (label_candidate_id,)
                if label_candidate_id is not None
                else ()
            ),
            "source_object_ids": (
                source_object_ids
                if detected_printed_label is not None
                else (_configured_page_label_source_id(case_id, physical_page),)
            ),
        },
        "confidence": (
            {
                "scope": "deterministic_rule",
                "score": 1.0,
                "unavailable_reason": None,
            }
            if detected_printed_label is not None
            else {
                "scope": "unavailable",
                "score": None,
                "unavailable_reason": "page_identity_source_unavailable",
            }
        ),
        "concern_codes": (),
        "predecessor_item_id": predecessor_item_id,
        "predecessor_page_number": predecessor_page_number,
        "legacy_navigation_conflict": predecessor_page_number != physical_page,
        "null_control_item_id": null_control_item_id,
        "source_sha256": SOURCE_IDENTITIES[case_id]["sha256"],
    }


PAGE_IDENTITIES: Final = (
    _page(
        "catastrophe-recap",
        1,
        "7",
        612.0,
        792.0,
        0,
        visible_text="7",
        label_bbox=_box(537.94, 742.368, 3.84, 6.0),
        predecessor_item_id="p1-i6",
        predecessor_page_number=1,
    ),
    _page(
        "clean-energy",
        1,
        "11",
        841.92,
        595.32,
        0,
        visible_text="PAGE | 11",
        label_bbox=_box(404.764, 558.929, 33.624, 8.044),
        predecessor_item_id="p1-i8",
        predecessor_page_number=1,
    ),
    _page(
        "clinical-study",
        1,
        "1/21",
        612.0,
        792.0,
        0,
        visible_text="1/21",
        label_bbox=_box(557.118, 749.656, 18.947, 8.0),
        predecessor_item_id="p1-i24",
        predecessor_page_number=1,
    ),
    _page(
        "clinical-study",
        2,
        "7/21",
        612.0,
        792.0,
        0,
        visible_text="7/21",
        label_bbox=_box(557.118, 749.656, 18.947, 8.0),
        predecessor_item_id="p2-i5",
        predecessor_page_number=2,
    ),
    _page(
        "clinical-study",
        3,
        "10/21",
        612.0,
        792.0,
        0,
        visible_text="10/21",
        label_bbox=_box(552.81, 749.656, 23.256, 8.0),
        predecessor_item_id="p3-i3",
        predecessor_page_number=3,
    ),
    _page(
        "clinical-study",
        4,
        "11/21",
        612.0,
        792.0,
        0,
        visible_text="11/21",
        label_bbox=_box(552.81, 749.656, 23.256, 8.0),
        predecessor_item_id="p4-i7",
        predecessor_page_number=4,
    ),
    _page(
        "component-datasheet",
        1,
        "3",
        595.28,
        841.89,
        0,
        visible_text="3",
        label_bbox=_box(534.944, 799.41, 4.336, 8.0),
        predecessor_item_id="p1-i10",
        predecessor_page_number=1,
    ),
    _page(
        "component-datasheet",
        2,
        "7",
        595.28,
        841.89,
        0,
        visible_text="7",
        label_bbox=_box(534.96, 799.41, 4.32, 8.0),
        predecessor_item_id="p2-i34",
        predecessor_page_number=2,
    ),
    _page(
        "component-datasheet",
        3,
        "11",
        595.28,
        841.89,
        0,
        visible_text="11",
        label_bbox=_box(532.224, 799.41, 7.056, 8.0),
        predecessor_item_id="p3-i16",
        predecessor_page_number=3,
    ),
    _page(
        "egov-survey",
        1,
        "37",
        612.0,
        792.0,
        0,
        visible_text="37",
        label_bbox=_box(535.421, 746.646, 10.008, 9.0),
        predecessor_item_id="p1-i8",
        predecessor_page_number=1,
    ),
    _page(
        "esg-metrics",
        1,
        "80",
        792.0,
        612.0,
        90,
        visible_text="80",
        label_bbox=_box(653.834, 454.102, 4.366, 3.15),
        predecessor_item_id="p1-i20",
        predecessor_page_number=1,
    ),
    _page(
        "finance-10k",
        1,
        "28",
        612.0,
        792.0,
        0,
        visible_text="28",
        label_bbox=_box(356.974, 766.006, 8.888, 8.0),
        predecessor_item_id="p1-i6",
        predecessor_page_number=1,
    ),
    _page(
        "finance-10k",
        2,
        "30",
        612.0,
        792.0,
        0,
        visible_text="30",
        label_bbox=_box(356.974, 766.006, 8.888, 8.0),
        predecessor_item_id="p2-i6",
        predecessor_page_number=2,
    ),
    _page(
        "finance-10k",
        3,
        "32",
        612.0,
        792.0,
        0,
        visible_text="32",
        label_bbox=_box(356.974, 766.006, 8.888, 8.0),
        predecessor_item_id="p3-i6",
        predecessor_page_number=3,
    ),
    _page(
        "health-report",
        1,
        "103",
        595.276,
        793.701,
        0,
        visible_text="103",
        label_bbox=_box(534.656, 30.672, 18.378, 11.04),
        predecessor_item_id="p1-i1",
        predecessor_page_number=1,
        label_region_role="header",
    ),
    _page(
        "insurance-acord",
        1,
        None,
        612.0,
        792.0,
        0,
        visible_text=None,
        label_bbox=None,
        predecessor_item_id=None,
        predecessor_page_number=1,
        null_control_item_id="p1-i21",
    ),
    _page(
        "manufacturing-report",
        1,
        "11",
        612.0,
        792.0,
        0,
        visible_text="11",
        label_bbox=_box(300.953, 746.943, 10.02, 9.96),
        predecessor_item_id="p1-i8",
        predecessor_page_number=1,
    ),
    _page(
        "manufacturing-report",
        2,
        "15",
        612.0,
        792.0,
        0,
        visible_text="15",
        label_bbox=_box(300.953, 746.943, 10.02, 9.96),
        predecessor_item_id="p2-i5",
        predecessor_page_number=2,
    ),
    _page(
        "manufacturing-report",
        3,
        "38",
        612.0,
        792.0,
        0,
        visible_text="38",
        label_bbox=_box(300.951, 733.139, 10.02, 9.96),
        predecessor_item_id="p3-i9",
        predecessor_page_number=3,
    ),
    _page(
        "ny-timetable",
        1,
        "2 of 28",
        612.0,
        792.0,
        0,
        visible_text="Page 2 of 28",
        label_bbox=_box(531.29, 775.14, 56.71, 10.0),
        predecessor_item_id="p1-i4",
        predecessor_page_number=2,
    ),
    _page(
        "ny-timetable",
        2,
        "3 of 28",
        612.0,
        792.0,
        0,
        visible_text="Page 3 of 28",
        label_bbox=_box(531.29, 775.14, 56.71, 10.0),
        predecessor_item_id="p2-i5",
        predecessor_page_number=3,
    ),
    _page(
        "ny-timetable",
        3,
        "4 of 28",
        612.0,
        792.0,
        0,
        visible_text="Page 4 of 28",
        label_bbox=_box(531.29, 775.14, 56.71, 10.0),
        predecessor_item_id="p3-i2",
        predecessor_page_number=4,
    ),
    _page(
        "postal-10k",
        1,
        "2",
        612.0,
        792.0,
        0,
        visible_text="2",
        label_bbox=_box(549.142, 770.515, 4.448, 8.0),
        predecessor_item_id="p1-i6",
        predecessor_page_number=1,
    ),
    _page(
        "postal-10k",
        2,
        "46",
        612.0,
        792.0,
        0,
        visible_text="46",
        label_bbox=_box(544.702, 770.515, 8.888, 8.0),
        predecessor_item_id="p2-i4",
        predecessor_page_number=2,
    ),
    _page(
        "postal-10k",
        3,
        "49",
        612.0,
        792.0,
        0,
        visible_text="49",
        label_bbox=_box(544.702, 770.515, 8.888, 8.0),
        predecessor_item_id="p3-i4",
        predecessor_page_number=3,
    ),
    _page(
        "purchase-agreement",
        1,
        None,
        612.0,
        792.0,
        0,
        visible_text=None,
        label_bbox=None,
        predecessor_item_id=None,
        predecessor_page_number=1,
        null_control_item_id="p1-i12",
    ),
    _page(
        "settlement-agreement",
        1,
        "24",
        612.0,
        792.0,
        0,
        visible_text="24",
        label_bbox=_box(300.0, 733.044, 12.0, 12.0),
        predecessor_item_id="p1-i6",
        predecessor_page_number=1,
    ),
    _page(
        "uber-earnings",
        1,
        None,
        1920.0,
        1080.0,
        0,
        visible_text=None,
        label_bbox=None,
        predecessor_item_id=None,
        predecessor_page_number=1,
        null_control_item_id="p1-i4",
    ),
    _page(
        "uber-earnings",
        2,
        "5",
        1920.0,
        1080.0,
        0,
        visible_text="5",
        label_bbox=_box(1840.147, 1037.407, 7.686, 14.0),
        predecessor_item_id="p2-i23",
        predecessor_page_number=2,
    ),
    _page(
        "uber-earnings",
        3,
        "6",
        1920.0,
        1080.0,
        0,
        visible_text="6",
        label_bbox=_box(1839.531, 1037.407, 8.302, 14.0),
        predecessor_item_id="p3-i9",
        predecessor_page_number=3,
    ),
)


VALID_REPETITION_GROUPS: Final = {
    "clinical-study:journal-header": {
        "page_indexes": (2, 3, 4),
        "boundary_band": "top",
        "normalized_signature": (
            "plos medicine digital mental health for syrian refugees in "
            "egypt: a pragmatic rct"
        ),
    },
    "clinical-study:journal-footer": {
        "page_indexes": (1, 2, 3, 4),
        "boundary_band": "bottom",
        "normalized_signature": (
            "plosmedicine | https://doi.org/10.1371/journal.pmed.1004460 "
            "september 9, 2024 {page}"
        ),
    },
    "component-datasheet:report-header": {
        "page_indexes": (1, 2, 3),
        "boundary_band": "top",
        "normalized_signature": "raspberry pi pico datasheet",
    },
    "finance-10k:company-header": {
        "page_indexes": (1, 2, 3),
        "boundary_band": "top",
        "normalized_signature": "apple inc.",
    },
    "finance-10k:form-page-footer": {
        "page_indexes": (1, 2, 3),
        "boundary_band": "bottom",
        "normalized_signature": "apple inc. | 2023 form 10-k | {page}",
    },
    "manufacturing-report:report-header": {
        "page_indexes": (1, 2, 3),
        "boundary_band": "top",
        "normalized_signature": "nist ams 100-76 february 2026",
    },
    "manufacturing-report:printed-page-label": {
        "page_indexes": (1, 2, 3),
        "boundary_band": "bottom",
        "normalized_signature": "{page}",
    },
    "ny-timetable:printed-page-label": {
        "page_indexes": (1, 2, 3),
        "boundary_band": "bottom",
        "normalized_signature": "{page}",
    },
    "postal-10k:report-page-footer": {
        "page_indexes": (1, 2, 3),
        "boundary_band": "bottom",
        "normalized_signature": (
            "2025 report on form 10-k united states postal service {page}"
        ),
    },
}


def _normalized_signature(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


MANUFACTURING_P2_SOURCE_TEXT: Final = "NIST AMS 100-76 February 2026"
MANUFACTURING_P2_PRESENTATION_TEXT: Final = "NIST AMS 100-76\nFebruary 2026"
MANUFACTURING_P2_CONTRIBUTION_BBOX: Final = _box(
    89.99004,
    38.74752,
    72.56856,
    22.08132,
)
MANUFACTURING_P2_SOURCE_OBJECT_IDS: Final = tuple(
    _source_object_id("manufacturing-report", 2, "character", index)
    for index in range(29)
) + tuple(
    _source_object_id("manufacturing-report", 2, "word", index)
    for index in range(5)
)
_MANUFACTURING_P2_OWNER_BINDING: Final = ITEM_BINDINGS[
    ("manufacturing-report", 2, "p2-i1")
]
MANUFACTURING_P2_CONTRIBUTION_BBOX_ID: Final = _stable_id(
    "running-bbox",
    POLICY_ID,
    SOURCE_IDENTITIES["manufacturing-report"]["sha256"],
    2,
    "p2-i1",
    MANUFACTURING_P2_SOURCE_OBJECT_IDS,
    MANUFACTURING_P2_CONTRIBUTION_BBOX,
    "header",
)
MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID: Final = _stable_id(
    "running-element",
    POLICY_ID,
    SOURCE_IDENTITIES["manufacturing-report"]["sha256"],
    2,
    "p2-i1",
    MANUFACTURING_P2_SOURCE_OBJECT_IDS,
    MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
    "header",
)
MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID: Final = _stable_id(
    "running-region-evidence",
    POLICY_ID,
    SOURCE_IDENTITIES["manufacturing-report"]["sha256"],
    2,
    "p2-i1",
    MANUFACTURING_P2_SOURCE_OBJECT_IDS,
    MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
    "header",
)
MANUFACTURING_P2_SYNTHETIC_PUBLIC_ITEM_ID: Final = _stable_id(
    "running-region-item",
    POLICY_ID,
    SOURCE_IDENTITIES["manufacturing-report"]["sha256"],
    2,
    "p2-i1",
    MANUFACTURING_P2_SOURCE_OBJECT_IDS,
    (MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID,),
    MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
    "header",
)
MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID: Final = _stable_id(
    "pb",
    "1.0",
    "canonical-presentation-v1",
    PAGE_BINDINGS[("manufacturing-report", 2)]["page_id"],
    MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID,
)
MANUFACTURING_P2_CONTRIBUTION_EVIDENCE: Final = {
    "id": MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID,
    "element_id": MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID,
    "method": "native",
    "bbox_id": MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
    "value": MANUFACTURING_P2_SOURCE_TEXT,
    "confidence": {
        "scope": "evidence",
        "score": None,
        "unavailable_reason": "not_calibrated",
    },
    "metadata": {
        "policy_id": POLICY_ID,
        "source_object_ids": list(MANUFACTURING_P2_SOURCE_OBJECT_IDS),
    },
}

MANUFACTURING_P2_EXTRACTION_PLAN: Final = {'physical_page_index': 2,
 'owner_public_item_id': 'p2-i1',
 'owner_sha256_before': '7ff091ed6cfcddccea0cac2e20b83c13acb49f945dbe03f2842db93212e73c94',
 'owner_sha256_after': '7ff091ed6cfcddccea0cac2e20b83c13acb49f945dbe03f2842db93212e73c94',
 'predecessor_canonical': 'NIST AMS 100-76\n'
                          '40.0%\n'
                          'o 6 8 8\n'
                          'xs Ss SX &\n'
                          '+r MO N A\n'
                          'Germany\n'
                          '= 2\n'
                          'February 2026\n'
                          '@ & 30.0%\n'
                          'JO aes ddd\n'
                          '20.0%\n'
                          'es Current Prices, National Currency\n'
                          'O\n'
                          '2\n'
                          'a\n'
                          'oO\n'
                          'c\n'
                          '5\n'
                          '10.0%\n'
                          '25.0%\n'
                          'e==== Constant U.S. Dollars\n'
                          '0.0%\n'
                          'vL6T\n'
                          '8Z6T\n'
                          '986T\n'
                          'O66T\n'
                          'v66T\n'
                          '866T\n'
                          'fo) wn oO wn\n'
                          'xs SX SX &\n'
                          'N a a\n'
                          'Oo G6 o 6\n'
                          '15.0%\n'
                          'ee Current Dollars\n'
                          '5 £\n'
                          'oa\n'
                          '2 6\n'
                          '5.0%\n'
                          'e==—= Constant Dollars\n'
                          'v86T\n'
                          't\n'
                          'OL6T\n'
                          '9L6T\n'
                          'O86T\n'
                          'No}\n'
                          '886T\n'
                          '966T\n'
                          'foe)\n'
                          '0002\n'
                          'jo)\n'
                          '9002\n'
                          '8002\n'
                          '0202\n'
                          'N\n'
                          'c66T\n'
                          'ioe)',
 'source_text': 'NIST AMS 100-76 February 2026',
 'presentation_text': 'NIST AMS 100-76\nFebruary 2026',
 'presentation_fragments': ('NIST AMS 100-76', 'February 2026'),
 'delimiters': ('\n', '\n'),
 'predecessor_intervals': ((0, 16), (63, 77)),
 'residual_insertion_offsets': (0, 47),
 'source_span_groups': (((0, 15),), ((16, 29),)),
 'whitespace_mappings': ((4, 5, 4, 5),
                         (8, 9, 8, 9),
                         (15, 16, 15, 16),
                         (24, 25, 24, 25)),
 'residual_canonical': '40.0%\n'
                       'o 6 8 8\n'
                       'xs Ss SX &\n'
                       '+r MO N A\n'
                       'Germany\n'
                       '= 2\n'
                       '@ & 30.0%\n'
                       'JO aes ddd\n'
                       '20.0%\n'
                       'es Current Prices, National Currency\n'
                       'O\n'
                       '2\n'
                       'a\n'
                       'oO\n'
                       'c\n'
                       '5\n'
                       '10.0%\n'
                       '25.0%\n'
                       'e==== Constant U.S. Dollars\n'
                       '0.0%\n'
                       'vL6T\n'
                       '8Z6T\n'
                       '986T\n'
                       'O66T\n'
                       'v66T\n'
                       '866T\n'
                       'fo) wn oO wn\n'
                       'xs SX SX &\n'
                       'N a a\n'
                       'Oo G6 o 6\n'
                       '15.0%\n'
                       'ee Current Dollars\n'
                       '5 £\n'
                       'oa\n'
                       '2 6\n'
                       '5.0%\n'
                       'e==—= Constant Dollars\n'
                       'v86T\n'
                       't\n'
                       'OL6T\n'
                       '9L6T\n'
                       'O86T\n'
                       'No}\n'
                       '886T\n'
                       '966T\n'
                       'foe)\n'
                       '0002\n'
                       'jo)\n'
                       '9002\n'
                       '8002\n'
                       '0202\n'
                       'N\n'
                       'c66T\n'
                       'ioe)',
 'source_text_sha256': 'b2f8b47d578208f60561dfc3933ae4605219eebbc7c25266ed6eab6d44db103a',
 'presentation_text_sha256': '73e62bab37811c65369b4bef892b698e7f8871cc4d1b498544bbd4463535379a',
 'predecessor_sha256': '215207bae26281781c882588d9b7e18329fcb0bbd4a99e02f27fe3b174323263',
 'presentation_fragment_sha256': ('700e7492119b7756d7881eca6542a52c62ab3a00562af73a77189e7591d215a0',
                                  'fc437294ca9e51d4f75277fe74dc3b0aa18e23f3e70f3339279a2109738eb968'),
 'removed_interval_sha256': ('2ab6661f56cd2e26d77bdcbfa6c56d0755622ac3460d934236882af897a5010e',
                             '6fa0b94f87f7a333692ae4c9256a6dc156404e7c88c47c13f355ea31dcdb7bd4'),
 'delimiter_sha256': ('01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b',
                      '01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b'),
 'ordered_plan_sha256': '910589a170b03838c5d9249e7e79f3a1233e5b45a2387b3b555ab431272deb1b',
 'residual_sha256': 'b2d1d1a36c36ced44ee18bb70265c4edf038469619861bbba227dbe7855f7ef4'}


CORRECTION_SOURCE_METHODS: Final = {
    ("finance-10k", 2, "p2-i1"): "cross_page_repetition",
    ("finance-10k", 3, "p3-i1"): "cross_page_repetition",
    ("manufacturing-report", 2, "p2-i1"): "extracted_source_contribution",
    ("esg-metrics", 1, "p1-i11"): "boundary_navigation",
    ("esg-metrics", 1, "p1-i19"): "effective_boundary_cluster",
    ("esg-metrics", 1, "p1-i20"): "printed_label_boundary",
}


def _region(
    case_id: str,
    physical_page: int,
    oracle_key: str,
    predecessor_item_id: str,
    predecessor_type: str,
    text: str,
    bbox: dict[str, float | str],
    kind: RegionKind,
    canonical_scope: CanonicalScope,
    repetition_group: str,
    before_item_id: str | None,
    after_item_id: str | None,
    *,
    before_inventory_type: Literal["header", "footer"] | None = None,
    source_item_id: str | None = None,
    origin: str = "predecessor_anchor",
    correction_reason: str | None = None,
) -> dict[str, Any]:
    binding = ITEM_BINDINGS[(case_id, physical_page, predecessor_item_id)]
    extraction = origin == "extracted_predecessor_contribution"
    source_method = CORRECTION_SOURCE_METHODS.get(
        (case_id, physical_page, predecessor_item_id),
        "trusted_layout_role",
    )
    source_element_id = (
        MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID
        if extraction
        else binding["owner_element_id"]
    )
    bbox_id = (
        MANUFACTURING_P2_CONTRIBUTION_BBOX_ID
        if extraction
        else binding["owner_bbox_id"]
    )
    canonical_block_id = (
        MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID
        if extraction
        else binding["owner_canonical_block_id"]
    )
    source_word_indexes = binding["source_word_indexes"]
    source_character_indexes = tuple(range(29)) if extraction else ()
    source_object_ids = (
        MANUFACTURING_P2_SOURCE_OBJECT_IDS
        if extraction
        else tuple(
            _source_object_id(case_id, physical_page, "word", index)
            for index in source_word_indexes
        )
    )
    evidence_ids = (
        (MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID,)
        if extraction
        else binding["evidence_ids"]
    )
    group_spec = VALID_REPETITION_GROUPS.get(repetition_group)
    if (
        group_spec is not None
        and physical_page in group_spec["page_indexes"]
    ):
        repetition_page_indexes = group_spec["page_indexes"]
        normalized_signature = group_spec["normalized_signature"]
        repetition_group_id = _stable_id(
            "running-repeat",
            POLICY_ID,
            SOURCE_IDENTITIES[case_id]["sha256"],
            group_spec["boundary_band"],
            normalized_signature,
        )
        repetition_group_key: str | None = repetition_group
    else:
        repetition_page_indexes = ()
        normalized_signature = _normalized_signature(text)
        repetition_group_id = None
        repetition_group_key = None
    if extraction:
        region_id = _stable_id(
            "running-region",
            POLICY_ID,
            SOURCE_IDENTITIES[case_id]["sha256"],
            physical_page,
            predecessor_item_id,
            source_object_ids,
            evidence_ids,
            bbox_id,
            kind,
        )
    else:
        region_id = _stable_id(
            "running-region",
            POLICY_ID,
            SOURCE_IDENTITIES[case_id]["sha256"],
            physical_page,
            source_element_id,
            bbox_id,
            kind,
        )
    return {
        "region_id": region_id,
        "oracle_key": oracle_key,
        "case_id": case_id,
        "physical_page": physical_page,
        "page_id": PAGE_BINDINGS[(case_id, physical_page)]["page_id"],
        "source_sha256": SOURCE_IDENTITIES[case_id]["sha256"],
        "public_item_id": (
            MANUFACTURING_P2_SYNTHETIC_PUBLIC_ITEM_ID
            if extraction
            else predecessor_item_id
        ),
        "source_item_id": predecessor_item_id,
        "source_public_item_id": predecessor_item_id,
        "source_public_path": binding["public_path"],
        "source_element_id": source_element_id,
        "owner_element_id": binding["owner_element_id"],
        "predecessor_item_id": predecessor_item_id,
        "predecessor_type": predecessor_type,
        "predecessor_item_sha256": binding["predecessor_item_sha256"],
        "before_inventory_type": before_inventory_type,
        "origin": origin,
        "correction_reason": correction_reason,
        "text": text,
        "text_sha256": _text_sha256(text),
        "bbox": bbox,
        "bbox_id": bbox_id,
        "owner_bbox_id": binding["owner_bbox_id"],
        "evidence_ids": evidence_ids,
        "owner_evidence_ids": binding["evidence_ids"],
        "source_character_indexes": source_character_indexes,
        "source_word_indexes": source_word_indexes,
        "source_object_ids": source_object_ids,
        "source_method": source_method,
        "confidence": {
            "scope": "deterministic_rule",
            "score": 1.0,
            "unavailable_reason": None,
        },
        "concern_codes": (),
        "kind": kind,
        "role": kind,
        "canonical_scope": canonical_scope,
        "canonical_block_id": canonical_block_id,
        "owner_canonical_block_id": binding["owner_canonical_block_id"],
        "normalized_signature": normalized_signature,
        "repetition_group": repetition_group_id,
        "repetition_group_id": repetition_group_id,
        "repetition_group_key": repetition_group_key,
        "repetition_page_indexes": repetition_page_indexes,
        "extraction_plan": (
            MANUFACTURING_P2_EXTRACTION_PLAN if extraction else None
        ),
        "expected_body_count": 0,
        "expected_full_count": 1,
        "scope_membership": {
            "body": (),
            "header": (
                (canonical_block_id,) if canonical_scope == "header" else ()
            ),
            "footer": (
                (canonical_block_id,) if canonical_scope == "footer" else ()
            ),
            "full": (canonical_block_id,),
        },
        "order_neighbors": binding["order_neighbors"],
        "reviewed_call_neighbors": {
            "before_item_id": before_item_id,
            "after_item_id": after_item_id,
        },
    }


BEFORE_RUNNING_REGIONS: Final = (
    _region(
        "catastrophe-recap",
        1,
        "footer",
        "p1-i6",
        "footer",
        "1H 2025 Global Catastrophe Recap\n7",
        _box(100.7, 741.87, 442.7, 6.234),
        "footer",
        "footer",
        "catastrophe-recap:report-footer",
        "layout-note-af58a03da292b26ce13f",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "clean-energy",
        1,
        "header",
        "p1-i1",
        "header",
        "Clean Energy Market Monitor - March 2024\nOverview",
        _box(56.64, 48.909, 723.129, 11.45),
        "header",
        "header",
        "clean-energy:report-header",
        None,
        "p1-i2",
        before_inventory_type="header",
    ),
    _region(
        "clean-energy",
        1,
        "footer",
        "p1-i8",
        "footer",
        "IEA. CC BY 4.0.\nPAGE | 11",
        _box(404.764, 536.434, 416.199, 37.281),
        "footer",
        "footer",
        "clean-energy:license-page-footer",
        "p1-i6",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "clinical-study",
        1,
        "header",
        "p1-i1",
        "header",
        "PLOS MEDICINE",
        _box(34.696, 34.467, 160.228, 17.286),
        "header",
        "header",
        "clinical-study:journal-header",
        None,
        "p1-i15",
        before_inventory_type="header",
    ),
    _region(
        "clinical-study",
        1,
        "footer",
        "p1-i24",
        "footer",
        (
            "PLOSMedicine | https://doi.org/10.1371/journal.pmed.1004460 "
            "September 9, 2024\n1 / 21"
        ),
        _box(36.0, 750.64, 540.001, 6.7),
        "footer",
        "footer",
        "clinical-study:journal-footer",
        "p1-i23",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "clinical-study",
        2,
        "header",
        "p2-i1",
        "header",
        "PLOS MEDICINE\nDigital mental health for Syrian refugees in Egypt: A pragmatic RCT",
        _box(34.98, 38.486, 541.067, 9.355),
        "header",
        "header",
        "clinical-study:journal-header",
        None,
        "el-f677de07d0e5a8ccb05b",
        before_inventory_type="header",
    ),
    _region(
        "clinical-study",
        2,
        "footer",
        "p2-i5",
        "footer",
        (
            "PLOSMedicine | https://doi.org/10.1371/journal.pmed.1004460 "
            "September 9, 2024\n7 / 21"
        ),
        _box(36.0, 750.64, 540.001, 6.7),
        "footer",
        "footer",
        "clinical-study:journal-footer",
        "p2-i4",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "clinical-study",
        3,
        "header",
        "p3-i1",
        "header",
        "PLOS MEDICINE\nDigital mental health for Syrian refugees in Egypt: A pragmatic RCT",
        _box(34.98, 38.486, 541.067, 9.355),
        "header",
        "header",
        "clinical-study:journal-header",
        None,
        "p3-i2",
        before_inventory_type="header",
    ),
    _region(
        "clinical-study",
        3,
        "footer",
        "p3-i3",
        "footer",
        (
            "PLOSMedicine | https://doi.org/10.1371/journal.pmed.1004460 "
            "September 9, 2024\n10 / 21"
        ),
        _box(36.0, 750.64, 540.001, 6.7),
        "footer",
        "footer",
        "clinical-study:journal-footer",
        "layout-caption-1c49cc0c4d0076181d81",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "clinical-study",
        4,
        "header",
        "p4-i1",
        "header",
        "PLOS MEDICINE\nDigital mental health for Syrian refugees in Egypt: A pragmatic RCT",
        _box(34.98, 38.486, 541.067, 9.355),
        "header",
        "header",
        "clinical-study:journal-header",
        None,
        "el-b9994d3665bd4a257785",
        before_inventory_type="header",
    ),
    _region(
        "clinical-study",
        4,
        "footer",
        "p4-i7",
        "footer",
        (
            "PLOSMedicine | https://doi.org/10.1371/journal.pmed.1004460 "
            "September 9, 2024\n11 / 21"
        ),
        _box(36.0, 750.64, 540.001, 6.7),
        "footer",
        "footer",
        "clinical-study:journal-footer",
        "p4-i6",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "component-datasheet",
        1,
        "header",
        "p1-i1",
        "header",
        "Raspberry Pi Pico Datasheet",
        _box(56.0, 28.088, 105.344, 10.536),
        "header",
        "header",
        "component-datasheet:report-header",
        None,
        "p1-i3",
        before_inventory_type="header",
    ),
    _region(
        "component-datasheet",
        1,
        "footer",
        "p1-i10",
        "footer",
        "Chapter 1. About Raspberry Pi Pico\n3",
        _box(56.0, 796.874, 483.28, 10.536),
        "footer",
        "footer",
        "component-datasheet:section-page-footer",
        "p1-i9",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "component-datasheet",
        2,
        "header",
        "p2-i1",
        "header",
        "Raspberry Pi Pico Datasheet",
        _box(56.0, 28.088, 105.344, 10.536),
        "header",
        "header",
        "component-datasheet:report-header",
        None,
        "p2-i2",
        before_inventory_type="header",
    ),
    _region(
        "component-datasheet",
        2,
        "footer",
        "p2-i34",
        "footer",
        "2.1. Raspberry Pi Pico pinout\n7",
        _box(56.0, 796.874, 483.28, 10.536),
        "footer",
        "footer",
        "component-datasheet:section-page-footer",
        "p2-i33",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "component-datasheet",
        3,
        "header",
        "p3-i1",
        "header",
        "Raspberry Pi Pico Datasheet",
        _box(56.0, 28.088, 105.344, 10.536),
        "header",
        "header",
        "component-datasheet:report-header",
        None,
        "p3-i2",
        before_inventory_type="header",
    ),
    _region(
        "component-datasheet",
        3,
        "footer",
        "p3-i16",
        "footer",
        "2.3. Recommended operating conditions\n11",
        _box(56.0, 796.874, 483.28, 10.536),
        "footer",
        "footer",
        "component-datasheet:section-page-footer",
        "p3-i15",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "egov-survey",
        1,
        "header",
        "p1-i1",
        "header",
        "Chapter 2\nChapter 2 · Global trends in e-Government",
        _box(317.087, 24.095, 285.658, 40.536),
        "header",
        "header",
        "egov-survey:chapter-header",
        None,
        "p1-i2",
        before_inventory_type="header",
    ),
    _region(
        "egov-survey",
        1,
        "printed-page-label",
        "p1-i8",
        "footer",
        "37",
        _box(535.421, 747.114, 10.008, 8.006),
        "footer",
        "footer",
        "egov-survey:printed-page-label",
        "p1-i7",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "finance-10k",
        1,
        "header",
        "p1-i1",
        "header",
        "Apple Inc.",
        _box(284.52, 42.748, 43.011, 9.0),
        "header",
        "header",
        "finance-10k:company-header",
        None,
        "p1-i2",
        before_inventory_type="header",
    ),
    _region(
        "finance-10k",
        1,
        "footer",
        "p1-i6",
        "footer",
        "Apple Inc. | 2023 Form 10-K | 28",
        _box(250.67, 766.006, 115.192, 8.0),
        "footer",
        "footer",
        "finance-10k:form-page-footer",
        "p1-i5",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "finance-10k",
        2,
        "footer",
        "p2-i6",
        "footer",
        "Apple Inc. | 2023 Form 10-K | 30",
        _box(250.67, 766.006, 115.192, 8.0),
        "footer",
        "footer",
        "finance-10k:form-page-footer",
        "p2-i5",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "finance-10k",
        3,
        "footer",
        "p3-i6",
        "footer",
        "Apple Inc. | 2023 Form 10-K | 32",
        _box(250.67, 766.006, 115.192, 8.0),
        "footer",
        "footer",
        "finance-10k:form-page-footer",
        "p3-i5",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "health-report",
        1,
        "printed-page-label",
        "p1-i1",
        "header",
        "\uf07c 103",
        _box(529.256, 31.357, 23.778, 9.902),
        "header",
        "header",
        "health-report:printed-page-label",
        None,
        "layout-caption-fc93bc7268829b0bfd30",
        before_inventory_type="header",
    ),
    _region(
        "health-report",
        1,
        "footer",
        "p1-i10",
        "footer",
        "HEALTH AT A GLANCE: EUROPE 2024 © OECD/EUROPEAN UNION 2024",
        _box(42.556, 740.197, 275.905, 7.211),
        "footer",
        "footer",
        "health-report:report-footer",
        "p1-i8",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "insurance-acord",
        1,
        "footer",
        "p1-i21",
        "footer",
        (
            "© 1988-2010 ACORD CORPORATION. All rights reserved.\n"
            "ACORD 25 (2010/05)\n"
            "The ACORD name and logo are registered marks of ACORD"
        ),
        _box(21.6, 746.867, 568.778, 19.421),
        "footer",
        "footer",
        "insurance-acord:legal-footer",
        "p1-i18",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "manufacturing-report",
        1,
        "header",
        "p1-i1",
        "header",
        "NIST AMS 100-76 February 2026",
        _box(89.99, 39.305, 72.569, 20.331),
        "header",
        "header",
        "manufacturing-report:report-header",
        None,
        "p1-i2",
        before_inventory_type="header",
    ),
    _region(
        "manufacturing-report",
        1,
        "printed-page-label",
        "p1-i8",
        "footer",
        "11",
        _box(300.953, 747.252, 12.45, 8.54),
        "footer",
        "footer",
        "manufacturing-report:printed-page-label",
        "p1-i7",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "manufacturing-report",
        2,
        "printed-page-label",
        "p2-i5",
        "footer",
        "15",
        _box(300.953, 747.252, 12.45, 8.54),
        "footer",
        "footer",
        "manufacturing-report:printed-page-label",
        "p2-i4",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "manufacturing-report",
        3,
        "header",
        "p3-i1",
        "header",
        "NIST AMS 100-76 February 2026",
        _box(71.99, 39.305, 72.569, 20.331),
        "header",
        "header",
        "manufacturing-report:report-header",
        None,
        "p3-i2",
        before_inventory_type="header",
    ),
    _region(
        "manufacturing-report",
        3,
        "printed-page-label",
        "p3-i9",
        "footer",
        "38",
        _box(300.951, 733.448, 12.45, 8.539),
        "footer",
        "footer",
        "manufacturing-report:printed-page-label",
        "p3-i8",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "ny-timetable",
        1,
        "printed-page-label",
        "p1-i4",
        "footer",
        "Page 2 of 28",
        _box(531.29, 775.89, 56.71, 9.25),
        "footer",
        "footer",
        "ny-timetable:printed-page-label",
        "p1-i3",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "ny-timetable",
        2,
        "printed-page-label",
        "p2-i5",
        "footer",
        "Page 3 of 28",
        _box(531.29, 775.89, 56.71, 9.25),
        "footer",
        "footer",
        "ny-timetable:printed-page-label",
        "p2-i3",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "ny-timetable",
        3,
        "printed-page-label",
        "p3-i2",
        "footer",
        "Page 4 of 28",
        _box(531.29, 775.89, 56.71, 9.25),
        "footer",
        "footer",
        "ny-timetable:printed-page-label",
        "p3-i1",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "postal-10k",
        1,
        "footer",
        "p1-i6",
        "footer",
        "2025 Report on Form 10-K United States Postal Service 2",
        _box(343.96, 771.093, 209.63, 7.068),
        "footer",
        "footer",
        "postal-10k:report-page-footer",
        "p1-i5",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "postal-10k",
        2,
        "footer",
        "p2-i4",
        "footer",
        "2025 Report on Form 10-K United States Postal Service 46",
        _box(339.52, 771.093, 214.07, 7.068),
        "footer",
        "footer",
        "postal-10k:report-page-footer",
        "p2-i3",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "postal-10k",
        3,
        "footer",
        "p3-i4",
        "footer",
        "2025 Report on Form 10-K United States Postal Service 49",
        _box(339.52, 771.093, 214.07, 7.068),
        "footer",
        "footer",
        "postal-10k:report-page-footer",
        "p3-i3",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "purchase-agreement",
        1,
        "footer",
        "p1-i12",
        "footer",
        "A7310832",
        _box(72.0, 747.011, 36.475, 9.081),
        "footer",
        "footer",
        "purchase-agreement:document-control-footer",
        "p1-i8",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "settlement-agreement",
        1,
        "printed-page-label",
        "p1-i6",
        "footer",
        "24",
        _box(300.0, 733.416, 15.0, 10.289),
        "footer",
        "footer",
        "settlement-agreement:printed-page-label",
        "p1-i5",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "uber-earnings",
        2,
        "footer",
        "p2-i23",
        "footer",
        (
            "Note 1: Annual run rate. Note 2: Growth rate shown on a constant "
            "currency basis.\nQ1 2025 Earnings\n5\n"
            "Note 3: Adjusted EBITDA as a % of Gross Bookings."
        ),
        _box(133.079, 1004.825, 1714.754, 46.843),
        "footer",
        "footer",
        "uber-earnings:earnings-footer",
        "p2-i22",
        None,
        before_inventory_type="footer",
    ),
    _region(
        "uber-earnings",
        3,
        "footer",
        "p3-i9",
        "footer",
        "Q1 2025 Earnings\n6\nUber",
        _box(72.0, 1036.13, 1775.833, 14.902),
        "footer",
        "footer",
        "uber-earnings:earnings-footer",
        "p3-i8",
        None,
        before_inventory_type="footer",
    ),
)

REQUIRED_CORRECTIONS: Final = (
    _region(
        "finance-10k",
        2,
        "company-header-correction",
        "p2-i1",
        "heading",
        "Apple Inc.",
        _box(284.52, 42.748, 43.011, 9.0),
        "header",
        "header",
        "finance-10k:company-header",
        None,
        "p2-i2",
        origin="retyped_predecessor_item",
        correction_reason="repeated_company_text_was_heading",
    ),
    _region(
        "finance-10k",
        3,
        "company-header-correction",
        "p3-i1",
        "heading",
        "Apple Inc.",
        _box(284.52, 42.748, 43.011, 9.0),
        "header",
        "header",
        "finance-10k:company-header",
        None,
        "p3-i2",
        origin="retyped_predecessor_item",
        correction_reason="repeated_company_text_was_heading",
    ),
    _region(
        "manufacturing-report",
        2,
        "report-header-extracted-contribution",
        "p2-i1",
        "chart",
        MANUFACTURING_P2_SOURCE_TEXT,
        MANUFACTURING_P2_CONTRIBUTION_BBOX,
        "header",
        "header",
        "manufacturing-report:report-header",
        None,
        "p2-i1",
        source_item_id="p2-i1::native-running-header-contribution",
        origin="extracted_predecessor_contribution",
        correction_reason="repeated_report_header_was_fused_into_chart",
    ),
    _region(
        "esg-metrics",
        1,
        "navigation-correction",
        "p1-i11",
        "text",
        "TABLE OF CONTENTS",
        _box(133.8, 453.883, 36.833, 3.44),
        "navigation_bottom",
        "footer",
        "esg-metrics:bottom-navigation",
        "p1-i18",
        "p1-i19",
        origin="retyped_predecessor_item",
        correction_reason="bottom_navigation_was_body_text",
    ),
    _region(
        "esg-metrics",
        1,
        "report-footer-correction",
        "p1-i19",
        "text",
        "MICRON SUSTAINABILITY REPORT 2025",
        _box(572.252, 453.648, 66.036, 3.44),
        "footer",
        "footer",
        "esg-metrics:report-footer",
        "p1-i11",
        "p1-i20",
        origin="retyped_predecessor_item",
        correction_reason="report_footer_was_body_text",
    ),
    _region(
        "esg-metrics",
        1,
        "printed-page-label-correction",
        "p1-i20",
        "text",
        "80",
        _box(653.834, 453.648, 4.366, 3.493),
        "footer",
        "footer",
        "esg-metrics:printed-page-label",
        "p1-i19",
        None,
        origin="retyped_predecessor_item",
        correction_reason="printed_page_label_was_body_text",
    ),
)

ACCEPTED_RUNNING_REGIONS: Final = BEFORE_RUNNING_REGIONS + REQUIRED_CORRECTIONS


def _page_identity_descriptor(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "policy_id": POLICY_ID,
        "page_id": entry["page_id"],
        "physical_page_index": entry["physical_page"],
        "embedded_label": entry["embedded_label"],
        "detected_printed_label": entry["detected_printed_label"],
        "visible_text": entry["visible_text"],
        "display_label": entry["display_label"],
        "display_source": entry["display_source"],
        "evidence_bbox": entry["label_bbox"],
        "evidence_source": entry["evidence_source"],
        "confidence": entry["confidence"],
        "concern_codes": entry["concern_codes"],
    }


PAGE_IDENTITY_DESCRIPTORS: Final = {
    (entry["case_id"], entry["physical_page"]): (
        _page_identity_descriptor(entry)
    )
    for entry in PAGE_IDENTITIES
}


def _running_region_descriptor(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["region_id"],
        "page_id": entry["page_id"],
        "physical_page_index": entry["physical_page"],
        "role": entry["role"],
        "canonical_scope": entry["canonical_scope"],
        "source_public_item_id": entry["source_public_item_id"],
        "source_public_path": entry["source_public_path"],
        "source_element_id": entry["source_element_id"],
        "predecessor_type": entry["predecessor_type"],
        "predecessor_item_sha256": entry["predecessor_item_sha256"],
        "bbox_id": entry["bbox_id"],
        "bbox": entry["bbox"],
        "evidence_ids": entry["evidence_ids"],
        "source_object_ids": entry["source_object_ids"],
        "source_method": entry["source_method"],
        "repetition_group_id": entry["repetition_group_id"],
        "repetition_page_indexes": entry["repetition_page_indexes"],
        "confidence": entry["confidence"],
        "concern_codes": entry["concern_codes"],
        "canonical_block_id": entry["canonical_block_id"],
    }


RUNNING_REGION_DESCRIPTORS: Final = {
    entry["region_id"]: _running_region_descriptor(entry)
    for entry in ACCEPTED_RUNNING_REGIONS
}


def _label_candidate(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["label_candidate_id"],
        "visible_text": entry["visible_text"],
        "normalized_label": entry["detected_printed_label"],
        "bbox": entry["label_bbox"],
        "source_object_ids": entry["source_object_ids"],
        "source_method": "native_printed_label",
        "confidence": entry["confidence"],
        "concern_codes": entry["concern_codes"],
    }


def _boundary_candidate(entry: dict[str, Any]) -> dict[str, Any]:
    boundary_band = (
        "top" if entry["canonical_scope"] == "header" else "bottom"
    )
    candidate_id = _stable_id(
        "boundary-candidate",
        POLICY_ID,
        entry["source_sha256"],
        entry["physical_page"],
        entry["source_public_item_id"],
        entry["source_public_path"],
        entry["source_element_id"],
        entry["bbox_id"],
        entry["evidence_ids"],
        entry["source_object_ids"],
        boundary_band,
        entry["source_method"],
    )
    return {
        "id": candidate_id,
        "public_item_id": entry["source_public_item_id"],
        "public_path": entry["source_public_path"],
        "element_id": entry["source_element_id"],
        "predecessor_type": entry["predecessor_type"],
        "bbox": entry["bbox"],
        "bbox_id": entry["bbox_id"],
        "evidence_ids": entry["evidence_ids"],
        "source_object_ids": entry["source_object_ids"],
        "raw_layout_role": (
            {
                "header": "page_header",
                "footer": "page_footer",
            }.get(entry["before_inventory_type"])
        ),
        "normalized_signature": entry["normalized_signature"],
        "boundary_band": boundary_band,
        "source_method": entry["source_method"],
        "confidence": entry["confidence"],
        "concern_codes": entry["concern_codes"],
        "disposition": "accepted",
    }


def _source_report(case_id: str) -> dict[str, Any]:
    source_pages = tuple(
        entry for entry in PAGE_IDENTITIES if entry["case_id"] == case_id
    )
    pages = []
    for identity in source_pages:
        physical_page = identity["physical_page"]
        counts = SOURCE_PAGE_COUNTS[(case_id, physical_page)]
        page_regions = tuple(
            entry
            for entry in ACCEPTED_RUNNING_REGIONS
            if entry["case_id"] == case_id
            and entry["physical_page"] == physical_page
        )
        pages.append(
            {
                "page_index": physical_page,
                "page_width": identity["width_pt"],
                "page_height": identity["height_pt"],
                "unit": "pt",
                "coordinate_system_id": "pdf-top-left-pt-v1",
                **counts,
                "embedded_label": identity["embedded_label"],
                "label_candidates": (
                    (_label_candidate(identity),)
                    if identity["is_detected_printed_label"]
                    else ()
                ),
                "boundary_candidates": tuple(
                    _boundary_candidate(entry) for entry in page_regions
                ),
                "concern_codes": (),
            }
        )
    source_character_count = sum(
        page["source_character_count"] for page in pages
    )
    source_word_count = sum(page["source_word_count"] for page in pages)
    label_candidate_count = sum(len(page["label_candidates"]) for page in pages)
    boundary_candidate_count = sum(
        len(page["boundary_candidates"]) for page in pages
    )
    return {
        "report_version": "1.0",
        "policy_id": POLICY_ID,
        "source_sha256": SOURCE_IDENTITIES[case_id]["sha256"],
        "status": "available",
        "pages": tuple(pages),
        "counts": {
            "page_count": len(pages),
            "source_character_count": source_character_count,
            "source_word_count": source_word_count,
            "embedded_label_count": sum(
                page["embedded_label"] is not None for page in pages
            ),
            "label_candidate_count": label_candidate_count,
            "boundary_candidate_count": boundary_candidate_count,
            "concern_count": 0,
        },
        "concern_codes": (),
        "extraction_ms": 0.0,
    }


SOURCE_REPORTS: Final = {
    case_id: _source_report(case_id) for case_id in SOURCE_IDENTITIES
}

PRINTED_LABEL_VISIBILITY_CONTRACT: Final = {
    "method": "pdfium_candidate_bbox_modal_rgb_v1",
    "render_scale_pixels_per_point": 4.0,
    "render_background_rgb": (255, 255, 255),
    "forms_rendered": False,
    "annotations_rendered": False,
    "minimum_channel_delta": 16,
    "maximum_render_dimension_pixels": 2_048,
    "maximum_render_pixels": 262_144,
    "maximum_non_stroking_fills": 256,
    "painted_fill_render_modes": (0, 2, 4, 6),
    "minimum_non_stroking_fill_alpha": 1,
    "fill_custody": (
        "gray_rgb_exact_cmyk_bidirectional_max_channel_delta"
    ),
    "maximum_cmyk_custody_channel_delta": 36,
    "candidate_object_binding": (
        "unique_compacted_sequence_or_delimiter_bounded_exact_suffix"
    ),
    "candidate_object_suffix_delimiters": ("whitespace", "|", ":", "/", "-"),
    "selected_pdfium_rgb_is_contrast_authority": True,
    "maximum_text_objects": 256,
    "maximum_text_object_scan": 10_000,
    "maximum_form_depth": 8,
    "degenerate_finite_text_objects": "skipped",
    "nonfinite_text_object_bounds": "rejected",
    "minimum_intersecting_painted_text_objects": 1,
    "maximum_page_dimension_points": 20_000.0,
    "modal_tie_break": "highest_count_then_lexicographically_smallest_rgb",
    "candidate_pixel_edges": "nearest_integer_ties_to_even",
    "retention": "ephemeral_gate_only",
}

SOURCE_VISIBILITY_CONTROLS: Final = (
    {
        "case_id": "uber-earnings",
        "physical_page": 1,
        "public_item_id": "p1-i4",
        "text_layer_text": "1",
        "bbox": _box(1841.616, 1025.407, 7.884, 18.0),
        "raw_non_stroking_fill": (0.9999966, 1.0, 1.0),
        "normalized_non_stroking_fill_rgb": (255, 255, 255),
        "width_pixels": 32,
        "height_pixels": 72,
        "pixel_count": 2_304,
        "render_rgb_sha256": (
            "82eec5ad244bc79d0380bffcca90f9121334b8494ad52e593baff095a42b9583"
        ),
        "modal_rgb": (255, 255, 255),
        "modal_pixel_count": 2_304,
        "render_max_channel_delta": 0,
        "minimum_fill_modal_channel_delta": 0,
        "visible": False,
        "disposition": "rejected_hidden_glyph",
    },
    {
        "case_id": "uber-earnings",
        "physical_page": 2,
        "public_item_id": "p2-i23",
        "text_layer_text": "5",
        "bbox": _box(1840.147, 1037.407, 7.686, 14.0),
        "raw_non_stroking_fill": (0.0, 0.0, 0.0),
        "normalized_non_stroking_fill_rgb": (0, 0, 0),
        "width_pixels": 30,
        "height_pixels": 56,
        "pixel_count": 1_680,
        "render_rgb_sha256": (
            "ee7fe7ae6a4d68ffefc3d74d13de35174ebf96159d1ac771074603e80c92ecbe"
        ),
        "modal_rgb": (255, 255, 255),
        "modal_pixel_count": 1_202,
        "render_max_channel_delta": 255,
        "minimum_fill_modal_channel_delta": 255,
        "visible": True,
        "disposition": "accepted_visible_glyph",
    },
    {
        "case_id": "uber-earnings",
        "physical_page": 3,
        "public_item_id": "p3-i9",
        "text_layer_text": "6",
        "bbox": _box(1839.531, 1037.407, 8.302, 14.0),
        "raw_non_stroking_fill": (0.0, 0.0, 0.0),
        "normalized_non_stroking_fill_rgb": (0, 0, 0),
        "width_pixels": 33,
        "height_pixels": 56,
        "pixel_count": 1_848,
        "render_rgb_sha256": (
            "db6ae38101a90722259df345a2885bcc9a9b4bef974f5aad3fd6c1c3ca2f67c0"
        ),
        "modal_rgb": (255, 255, 255),
        "modal_pixel_count": 1_310,
        "render_max_channel_delta": 255,
        "minimum_fill_modal_channel_delta": 255,
        "visible": True,
        "disposition": "accepted_visible_glyph",
    },
)

ESG_EFFECTIVE_BOTTOM_CLUSTER: Final = {
    "items": (
        {
            "id": "p1-i11",
            "presentation_index": 17,
            "bbox": _box(133.8, 453.883, 36.833, 3.44),
            "navigation_cue": "TABLE OF CONTENTS",
            "normalized_label": None,
            "claimed": False,
        },
        {
            "id": "p1-i19",
            "presentation_index": 18,
            "bbox": _box(572.252, 453.648, 66.036, 3.44),
            "navigation_cue": None,
            "normalized_label": None,
            "claimed": False,
        },
        {
            "id": "p1-i20",
            "presentation_index": 19,
            "bbox": _box(653.834, 453.648, 4.366, 3.493),
            "navigation_cue": None,
            "normalized_label": "80",
            "claimed": False,
        },
    ),
    "remaining_body_bboxes": (
        _box(133.8, 157.013, 107.534, 5.243),
        _box(133.8, 186.354, 186.446, 17.966),
        _box(133.8, 205.326, 42.416, 8.38),
        _box(135.0, 224.277, 32.15, 8.983),
        _box(132.959, 233.609, 229.521, 129.228),
        _box(133.8, 373.532, 83.13, 3.546),
        _box(133.8, 380.132, 221.865, 7.446),
        _box(133.8, 390.633, 75.573, 3.545),
        _box(133.8, 397.233, 153.625, 3.545),
        _box(133.8, 403.833, 222.327, 7.446),
        _box(389.55, 203.418, 73.267, 5.989),
        _box(387.858, 219.534, 114.637, 83.933),
        _box(389.55, 335.891, 56.073, 5.989),
        _box(391.085, 343.803, 186.675, 3.932),
        _box(387.261, 356.814, 270.819, 55.363),
        _box(389.55, 424.318, 91.977, 3.545),
        _box(389.55, 430.918, 114.83, 3.545),
    ),
    "candidate_cut_count": 1,
}

BOUNDARY_METHOD_PROOFS: Final = {
    "boundary-candidate-08250274384c8509de06": {
        "navigation_cue": "TABLE OF CONTENTS",
        "effective_cluster": ESG_EFFECTIVE_BOTTOM_CLUSTER,
    },
    "boundary-candidate-f4411d4d8df4bc40188a": (
        ESG_EFFECTIVE_BOTTOM_CLUSTER
    ),
    "boundary-candidate-b1588836d411b6d58339": {
        "label_candidate_id": "label-candidate-7bd19e5695b807870699",
        "effective_cluster": ESG_EFFECTIVE_BOTTOM_CLUSTER,
    },
    "boundary-candidate-6990811cba6136a6f381": {
        "native_source": True,
        "evidence_mode": "exact_repetition",
        "repetition_page_indexes": (1, 2, 3),
        "complete_delimiter_line": True,
        "scalar_match_count": 1,
        "intervals_disjoint": True,
        "owner_kind": "chart",
    },
}

_REGION_BY_SOURCE_ITEM: Final = {
    (
        entry["case_id"],
        entry["physical_page"],
        entry["source_public_item_id"],
    ): entry
    for entry in ACCEPTED_RUNNING_REGIONS
}


def _reviewed_non_target(
    case_id: str,
    physical_page: int,
    public_item_id: str,
    reason: str,
) -> dict[str, Any]:
    binding = ITEM_BINDINGS[(case_id, physical_page, public_item_id)]
    region = _REGION_BY_SOURCE_ITEM[(case_id, physical_page, public_item_id)]
    source_word_indexes = binding["source_word_indexes"]
    return {
        "id": _stable_id(
            "running-negative",
            POLICY_ID,
            SOURCE_IDENTITIES[case_id]["sha256"],
            physical_page,
            public_item_id,
            "printed_page_identity",
        ),
        "case_id": case_id,
        "physical_page": physical_page,
        "reviewed_outcome": "non_target",
        "negative_for": "printed_page_identity",
        "reason": reason,
        "public_item_id": public_item_id,
        "public_path": binding["public_path"],
        "element_id": binding["owner_element_id"],
        "bbox_id": binding["owner_bbox_id"],
        "bbox": region["bbox"],
        "evidence_ids": binding["evidence_ids"],
        "source_word_indexes": source_word_indexes,
        "source_object_ids": tuple(
            _source_object_id(case_id, physical_page, "word", index)
            for index in source_word_indexes
        ),
        "predecessor_item_sha256": binding["predecessor_item_sha256"],
        "accepted_running_region_id": region["region_id"],
    }


REVIEWED_NON_TARGETS: Final = (
    _reviewed_non_target(
        "insurance-acord",
        1,
        "p1-i21",
        "form_and_legal_identifiers_are_not_printed_page_identity",
    ),
    _reviewed_non_target(
        "purchase-agreement",
        1,
        "p1-i12",
        "document_control_identifier_is_not_printed_page_identity",
    ),
)

PREDECESSOR_CANONICAL_BLOCK_IDS: Final = {('catastrophe-recap', 1): ('pb-74d21e3c123ceea2c60c',
                            'pb-d50be4a29a601bb822b9',
                            'pb-ec34cd9fc34b9ecd3dad',
                            'pb-8b76613dbce4f5e7fc01',
                            'pb-b02f105a44cd27f6180c',
                            'pb-4d32019fb97fd230b4f0',
                            'pb-b9f2172e582c6c44098a'),
 ('clean-energy', 1): ('pb-84ae7c3995c46c338a17',
                       'pb-d45e08a50b65edd2d31a',
                       'pb-228609bcc881c54c5209',
                       'pb-291eddff1e614cf23d39',
                       'pb-00a9b30dbd279dc825bb',
                       'pb-d68659af649b40b2a47e',
                       'pb-cbe689944354e79cc018'),
 ('clinical-study', 1): ('pb-dbe8bd325322fddd3cca',
                         'pb-7bbb22776c5a5453d640',
                         'pb-6553d5273f373c2da65e',
                         'pb-386b0cad9102aadbe2cb',
                         'pb-a963bf87006471c4bb3c',
                         'pb-f58781e6ceb510cab723',
                         'pb-390846bcbcb2c1ea2198',
                         'pb-334b77cdd2307fe26d7e',
                         'pb-3becb7fb51c4b4ee8485',
                         'pb-8ee80575b09955efbbb0',
                         'pb-1f1406c626aeab710dba',
                         'pb-fbca12df69276fb3c732',
                         'pb-a65eea4b728ae926ac7f',
                         'pb-565d42744456e22f96dc',
                         'pb-718284fff53f9216d25e',
                         'pb-ce782da6100fed98fc8a',
                         'pb-7c1c218cc33193a69d25',
                         'pb-518fe9c9461a3fd9e821',
                         'pb-6c6c65798c16f5e16d34',
                         'pb-72996c7ed8c94a70277f',
                         'pb-3587bb9dd3f299c7998e',
                         'pb-013ecfe7eda0c0b1e4c1',
                         'pb-b489c9f7a3460d082c93',
                         'pb-4426296fb99984dfeca5'),
 ('clinical-study', 2): ('pb-de82e60489aa0847cf3b',
                         'pb-4513d85e1d2c11b54dc6',
                         'pb-30e39e1e13d1b01223d6',
                         'pb-dd378507430bb7b5a5d4',
                         'pb-8bf056b4e47d1946165e',
                         'pb-d7b9e8c6fd9e81453d8b',
                         'pb-6125b217d249eb1d912a',
                         'pb-a741ea2093ca06425191',
                         'pb-4ea9303418cf94915963'),
 ('clinical-study', 3): ('pb-7e3920e26ce8619dd4be',
                         'pb-914cfe79d7231ca50f25',
                         'pb-e13bcad75eff69a5c8f8',
                         'pb-ac381f71d3591652c161',
                         'pb-c9df56bc4d0ad67196ef'),
 ('clinical-study', 4): ('pb-8a56ec9b620017e0597b',
                         'pb-6df04ab78e94022fc6f4',
                         'pb-de18208841395fb6c341',
                         'pb-0107049ba391e985f6c8',
                         'pb-4a37b6464fd420146177',
                         'pb-5317423ec163bf0e44a6',
                         'pb-d3104af61ec59ef53584',
                         'pb-d73347f11614958b20e4',
                         'pb-f3a71a7642e511f81613',
                         'pb-313bced6321553f7c498',
                         'pb-eb43c9325778dc1f8332'),
 ('component-datasheet', 1): ('pb-34de8495d675c1e8ca4b',
                              'pb-e78f810d0862066862b3',
                              'pb-82fa5404e925708c51ca',
                              'pb-92f1abce13f7b9927ce5',
                              'pb-2ac5a66d7d0a4dbe3473',
                              'pb-3dbf9558178027fc79b0',
                              'pb-affd1cf290d1f2ac4895',
                              'pb-a1bc39ede4fac02ab32a',
                              'pb-d1d227e3b36e3b112d8f',
                              'pb-5c9ff552f05aeb1c4fbd'),
 ('component-datasheet', 2): ('pb-dba0ce053a7d4983f55f',
                              'pb-365b499b9c0800642c62',
                              'pb-2b6d11dfc97673dfcb06',
                              'pb-285ce69b54e5cc73b5a2',
                              'pb-730473b9ee3c4476deca',
                              'pb-135346316a2015a6ec83',
                              'pb-97671295077fa80c9553',
                              'pb-b6ddd40e33ae5321d903',
                              'pb-9d68b3a8ad61f82736b5',
                              'pb-df4acc1e4752f95720f1',
                              'pb-5bd4c17609195b3ee256',
                              'pb-6d40a792fa9f138048d7',
                              'pb-c5002098a19ad86a4088'),
 ('component-datasheet', 3): ('pb-24d69ba1d635c3ce18ab',
                              'pb-52a295e18f94ae6929b2',
                              'pb-6a39eafebaa3a4e9b6b1',
                              'pb-8f5cab02f575e50fc431',
                              'pb-c3714786ea56293eff3d',
                              'pb-579024afbbe5cb665e48',
                              'pb-e37057a197a48eac79c1'),
 ('egov-survey', 1): ('pb-0f38680cd7de33d1bc97',
                      'pb-d8e1036469c07111c84e',
                      'pb-9acb37c6f40539382227',
                      'pb-7a552715ebbb305245fc',
                      'pb-131de849636c7c15aa6a',
                      'pb-5092432bd7e2ca88687e',
                      'pb-40d3a54465f64e22e383',
                      'pb-0d1d5d2daeb9add11600',
                      'pb-b71a5a25177d026c7d09'),
 ('esg-metrics', 1): ('pb-8c89eb62fd4bcf45fd0f',
                      'pb-a393eebbff18f3c7dd28',
                      'pb-a1275e30b683561e2b6b',
                      'pb-03782ac48c20ec1e51d2',
                      'pb-9c12bf16b038cb77c096',
                      'pb-3bdbdabef6e92911a64e',
                      'pb-2f25dda534ea61e5ad8d',
                      'pb-310ce616db5e00dff717',
                      'pb-6dbf9cd2d1fe178e0812',
                      'pb-f26939c9e4d8d8100784',
                      'pb-053807ba81f6dc721c41',
                      'pb-93cf3008e5691fcbb4af',
                      'pb-fd263c63c1d837cf1377',
                      'pb-748b0f4f13e8e93c61ac',
                      'pb-4a5c5d9cc8a4ef46904b',
                      'pb-9643119e3915672edf2c',
                      'pb-94feffc834962814a398',
                      'pb-f36464af4ee3e87eb3a9',
                      'pb-c6ebb82aa33c2019364e',
                      'pb-de4757d78ada1bcbb4a4'),
 ('finance-10k', 1): ('pb-512fdbbc3962d03dfeb9',
                      'pb-808bba02b272d45b29da',
                      'pb-9edc000ee20df5720309',
                      'pb-a1fa5e4200015f1d7a69',
                      'pb-cba5bfb8a322e4d78349',
                      'pb-5cd4b2fea71ca6e8b75d'),
 ('finance-10k', 2): ('pb-d45993b53299f9f8fc68',
                      'pb-3b92e2d6ee005c83568b',
                      'pb-d4eff082d8934451d9ba',
                      'pb-7a23b51ff72898231429',
                      'pb-abcd1a8df4c1ceff848c',
                      'pb-a9952e036d1089c00d40'),
 ('finance-10k', 3): ('pb-48ac46a24dde8cc66227',
                      'pb-c2506d36cb693f733020',
                      'pb-468d9159726b18f385f0',
                      'pb-3ef4f8fd505db686e38b',
                      'pb-ef910b1b8406ef90239b',
                      'pb-e506a14af032507812fe'),
 ('health-report', 1): ('pb-02ab0fe415dc7af725f1',
                        'pb-9c357abbfecb838674ee',
                        'pb-13cbe2ca3284f749f0b7',
                        'pb-a4d69d4ba048e2d0ff7b',
                        'pb-1b56f72d93024feaf731',
                        'pb-b868f2bf2562350d7a41',
                        'pb-589a5bd48cdbd532658b',
                        'pb-937f0cc8907faf1c078c',
                        'pb-15a57acaa1bb7b7aea3a',
                        'pb-a8c04dac3829ac0b7db6',
                        'pb-d51cc1efa687386b7d58'),
 ('insurance-acord', 1): ('pb-baab8b08ab4343c75c68',
                          'pb-2ce0689a873304ad42e5',
                          'pb-7fd90c46ff2e7a229bac',
                          'pb-a8abc53d5fe3350eaa62',
                          'pb-eec7995924381a407b44',
                          'pb-1cfeb382a8d048078912',
                          'pb-8d2b31e5295d08fb3545',
                          'pb-815c5b3881ed4129f051',
                          'pb-5be6870fc89b993d7ce8',
                          'pb-72806132bc3d490d7624',
                          'pb-f806aade4df380b3185e',
                          'pb-588d2b20b2a8db5f5ad9',
                          'pb-71791473cb132b5ee184',
                          'pb-89255f9611f8fd1b3c15',
                          'pb-7ff8e54959e130d47932',
                          'pb-fadb64edf7c11d3d3a3b',
                          'pb-73b56c5e1cb1dcf376ac',
                          'pb-47a88d3ab4637959fc48',
                          'pb-89ced484e24a8069e42e',
                          'pb-4c6cfec05bb3d54bd940'),
 ('manufacturing-report', 1): ('pb-4e5ceae7ccbbfcd11bc0',
                               'pb-5c9c7e99da77c05dec61',
                               'pb-99550d705703e6b6d4ee',
                               'pb-15fae19157cb1538dc69',
                               'pb-a6a1b971af5f52befa36',
                               'pb-e189db509f9b2e0f2f59',
                               'pb-70543eb0a812cefec886',
                               'pb-c74384e594f591d645eb',
                               'pb-e8b857728ada248ec9b6'),
 ('manufacturing-report', 2): ('pb-aeeac8d2e28fa3e33e18',
                               'pb-bf629206ab781349b497',
                               'pb-7b3a2ba428d37a888935',
                               'pb-5277e43642da2bd92057',
                               'pb-d6655261641b9fe110cb',
                               'pb-8c09fc0b21d7cf3d433a',
                               'pb-c29d7b88aee2b6280eab'),
 ('manufacturing-report', 3): ('pb-95c0530c26b659d40209',
                               'pb-58d92ac90caab44a9a61',
                               'pb-d461f795e4b8a3ffe6de',
                               'pb-07d5f60849f5c5e4c152',
                               'pb-fb934001bc25b8d1e46e',
                               'pb-f98040473fb867a70b3a',
                               'pb-c7edf58127ee563d8038',
                               'pb-249fa908166dcd5eec61',
                               'pb-adecd749278529a76d2f'),
 ('ny-timetable', 1): ('pb-8742bba06caf1a5764c5',
                       'pb-94a459a720262f4a1efb',
                       'pb-3f4f0799380b182d0faf',
                       'pb-3239abc971d67459c099'),
 ('ny-timetable', 2): ('pb-55fb065600275fe1ecfa',
                       'pb-f9b354886c79d82a0605',
                       'pb-81ead226fc576d8fefb2',
                       'pb-cd2034a092cd7f812d2f',
                       'pb-96ee91bffb4e44466fd8'),
 ('ny-timetable', 3): ('pb-53413c24f699b7f49273', 'pb-1aa8af7b95418153e574'),
 ('postal-10k', 1): ('pb-8cdb2593cdb14ace8485',
                     'pb-91695e1d82231e723716',
                     'pb-af450dc6acaa15b2944e',
                     'pb-4cb04809a5eabcea4c47',
                     'pb-dbad8a0215c77e456b4e',
                     'pb-71033405dd9dc71c30ea'),
 ('postal-10k', 2): ('pb-3351eacd89cdb85d1ddf',
                     'pb-175e0b994a8a88d840f5',
                     'pb-7367839852204e55d7ef',
                     'pb-f3cdab2c297acd456a61'),
 ('postal-10k', 3): ('pb-21af2c02e3ff048e3b78',
                     'pb-3c7b59cafab9a4f758b8',
                     'pb-2ee6eaf14c557aa82cbb',
                     'pb-dfcfe562cc3e73c95854'),
 ('purchase-agreement', 1): ('pb-976df8da47b8dbd2e903',
                             'pb-8d3e117221b3dac564f6',
                             'pb-10f341df16f0c11a6309',
                             'pb-4869aad4369aff817507',
                             'pb-6162411b80c9b5387e88',
                             'pb-cca3fcdd7414b161fd1e',
                             'pb-a4aa01eb3e7bf31bc578',
                             'pb-a0661cdd597e5fae7786',
                             'pb-55cf105ffa4a81d213a8',
                             'pb-c328aa01c32e6df83988',
                             'pb-c2c8ed37ddd6c5d3e6d9',
                             'pb-5b5e9087c4e909ece48f'),
 ('settlement-agreement', 1): ('pb-4af6221c6fdcf4b56ff4',
                               'pb-e18051f5eef5bc054ce5',
                               'pb-6eb4d8a6bb40e8c7f614'),
 ('uber-earnings', 1): ('pb-555d00cb38a5888883a8',
                        'pb-3421dd079f3bac2c7af9',
                        'pb-c0c0f0f90f35a6ed01e3',
                        'pb-4f121851d9cd40f5f987'),
 ('uber-earnings', 2): ('pb-9472690828fe183ae5ea',
                        'pb-daf5bb3f281837372557',
                        'pb-6a89ba9ef55370d9c246',
                        'pb-146b89517300d0194152',
                        'pb-7cf5cf1cae80d0749641',
                        'pb-ae1f6d441d42d227e914',
                        'pb-596b1aef569fe4edc6f2',
                        'pb-1c7609778bce988d1f7e',
                        'pb-64ad190710723a026ccc',
                        'pb-a0683884ab5dccca3ae8',
                        'pb-df5636bf1044f5efa549',
                        'pb-f46fe4ea474690c2b369',
                        'pb-85fdea45bbaf1bec8227',
                        'pb-6cf822ac1d23d56b395f',
                        'pb-a149e3e6e9c354028517',
                        'pb-e1c3eb0ed93d41fa28c8',
                        'pb-284cd66b451f12558b70',
                        'pb-c57a9301bd36658f8fd0',
                        'pb-80066955ff04f646b227',
                        'pb-69b07349bcd80a907794',
                        'pb-a1088edf28e84a9c74aa'),
 ('uber-earnings', 3): ('pb-0e4ca2643200a096a35d',
                        'pb-68e89e17a22750900e32',
                        'pb-130a0065e4f372442a2e',
                        'pb-462d05661739167a349b',
                        'pb-e86eeec9b37fa89d9d37',
                        'pb-bda92c72dbe7e3a5afc1',
                        'pb-b5ea24240a525af72a79',
                        'pb-76db85460eaaedc8b03e')}


def _canonical_page_membership(
    case_id: str,
    physical_page: int,
) -> dict[str, tuple[str, ...]]:
    predecessor_full = PREDECESSOR_CANONICAL_BLOCK_IDS[
        (case_id, physical_page)
    ]
    full = list(predecessor_full)
    if (case_id, physical_page) == ("manufacturing-report", 2):
        owner_block_id = _MANUFACTURING_P2_OWNER_BINDING[
            "owner_canonical_block_id"
        ]
        full.insert(
            full.index(owner_block_id),
            MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID,
        )

    page_regions = tuple(
        entry
        for entry in ACCEPTED_RUNNING_REGIONS
        if entry["case_id"] == case_id
        and entry["physical_page"] == physical_page
    )
    scope_by_block_id = {
        entry["canonical_block_id"]: entry["canonical_scope"]
        for entry in page_regions
    }
    assert len(scope_by_block_id) == len(page_regions)
    accepted_block_ids = set(scope_by_block_id)
    return {
        "predecessor_full_block_ids": predecessor_full,
        "body_block_ids": tuple(
            block_id for block_id in full if block_id not in accepted_block_ids
        ),
        "header_block_ids": tuple(
            block_id
            for block_id in full
            if scope_by_block_id.get(block_id) == "header"
        ),
        "footer_block_ids": tuple(
            block_id
            for block_id in full
            if scope_by_block_id.get(block_id) == "footer"
        ),
        "full_block_ids": tuple(full),
    }


CANONICAL_PAGE_MEMBERSHIP: Final = {
    key: _canonical_page_membership(*key)
    for key in PREDECESSOR_CANONICAL_BLOCK_IDS
}

FROZEN_AGGREGATES: Final = {
    "source_case_count": 15,
    "physical_page_count": 30,
    "page_binding_count": 30,
    "predecessor_output_count": 15,
    "predecessor_output_total_size_bytes": 4_614_035,
    "predecessor_configuration_flag_count": 10,
    "source_report_count": 15,
    "source_report_page_count": 30,
    "source_report_character_count": 52_861,
    "source_report_word_count": 8_080,
    "source_report_label_candidate_count": 27,
    "source_report_boundary_candidate_count": 47,
    "boundary_method_proof_count": 4,
    "source_visibility_control_count": 3,
    "source_visibility_positive_count": 2,
    "source_visibility_negative_count": 1,
    "embedded_label_null_count": 30,
    "detected_printed_label_positive_count": 27,
    "detected_printed_label_null_control_count": 3,
    "source_only_detected_label_count": 27,
    "source_only_candidate_evidence_count": 27,
    "exact_native_source_range_count": 27,
    "mismatched_physical_printed_label_count": 27,
    "exact_visible_label_text_count": 27,
    "exact_visible_label_bbox_count": 27,
    "before_distinct_detected_label_count": 0,
    "before_legacy_page_label_exact_display_count": 0,
    "before_physical_page_number_count": 27,
    "before_navigation_conflict_count": 3,
    "after_distinct_detected_label_count": 27,
    "before_header_anchor_count": 13,
    "before_footer_anchor_count": 28,
    "before_running_region_anchor_count": 41,
    "required_correction_count": 6,
    "accepted_running_region_count": 47,
    "running_item_binding_count": 47,
    "canonical_header_scope_count": 16,
    "canonical_footer_scope_count": 31,
    "role_header_count": 16,
    "role_footer_count": 30,
    "role_navigation_top_count": 0,
    "role_navigation_bottom_count": 1,
    "repetition_group_count": 9,
    "repeated_region_count": 28,
    "non_repetition_region_count": 19,
    "source_method_trusted_layout_role_count": 41,
    "source_method_cross_page_repetition_count": 2,
    "source_method_extracted_source_contribution_count": 1,
    "source_method_boundary_navigation_count": 1,
    "source_method_effective_boundary_cluster_count": 1,
    "source_method_printed_label_boundary_count": 1,
    "reviewed_non_target_count": 2,
    "canonical_page_membership_count": 30,
    "predecessor_canonical_block_count": 269,
    "canonical_body_block_count": 223,
    "canonical_header_block_count": 16,
    "canonical_footer_block_count": 31,
    "canonical_full_block_count": 270,
    "manufacturing_extraction_interval_count": 2,
    "manufacturing_extraction_source_span_count": 2,
    "manufacturing_synthetic_evidence_count": 1,
    "expected_body_inclusion_count": 0,
    "expected_full_inclusion_count": 47,
    "exact_order_neighbor_record_count": 47,
}


def oracle_payload() -> dict[str, Any]:
    """Return the deterministic semantic oracle payload."""

    predecessor_canonical_full_order = tuple(
        {
            "case_id": case_id,
            "physical_page": physical_page,
            "block_ids": block_ids,
        }
        for (case_id, physical_page), block_ids in (
            PREDECESSOR_CANONICAL_BLOCK_IDS.items()
        )
    )
    canonical_page_membership = tuple(
        {
            "case_id": case_id,
            "physical_page": physical_page,
            **membership,
        }
        for (case_id, physical_page), membership in (
            CANONICAL_PAGE_MEMBERSHIP.items()
        )
    )
    return {
        "policy_id": POLICY_ID,
        "coordinate_contract": COORDINATE_CONTRACT,
        "corpus_registry_custody": CORPUS_REGISTRY_CUSTODY,
        "source_identities": SOURCE_IDENTITIES,
        "predecessor_output_root": PREDECESSOR_OUTPUT_ROOT,
        "predecessor_output_identities": PREDECESSOR_OUTPUT_IDENTITIES,
        "predecessor_configuration": PREDECESSOR_CONFIGURATION,
        "page_identity_contract_fields": PAGE_IDENTITY_CONTRACT_FIELDS,
        "running_region_contract_fields": RUNNING_REGION_CONTRACT_FIELDS,
        "page_binding_rows": PAGE_BINDING_ROWS,
        "source_page_count_rows": SOURCE_PAGE_COUNT_ROWS,
        "item_binding_rows": ITEM_BINDING_ROWS,
        "page_identities": PAGE_IDENTITIES,
        "page_identity_descriptors": tuple(
            {
                "case_id": case_id,
                "physical_page": physical_page,
                "descriptor": descriptor,
            }
            for (case_id, physical_page), descriptor in (
                PAGE_IDENTITY_DESCRIPTORS.items()
            )
        ),
        "source_reports": SOURCE_REPORTS,
        "printed_label_visibility_contract": (
            PRINTED_LABEL_VISIBILITY_CONTRACT
        ),
        "source_visibility_controls": SOURCE_VISIBILITY_CONTROLS,
        "boundary_method_proofs": BOUNDARY_METHOD_PROOFS,
        "valid_repetition_groups": VALID_REPETITION_GROUPS,
        "before_running_regions": BEFORE_RUNNING_REGIONS,
        "required_corrections": REQUIRED_CORRECTIONS,
        "accepted_running_regions": ACCEPTED_RUNNING_REGIONS,
        "running_region_descriptors": tuple(
            RUNNING_REGION_DESCRIPTORS[entry["region_id"]]
            for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "reviewed_non_targets": REVIEWED_NON_TARGETS,
        "predecessor_canonical_full_order": predecessor_canonical_full_order,
        "canonical_page_membership": canonical_page_membership,
        "manufacturing_p2": {
            "source_text": MANUFACTURING_P2_SOURCE_TEXT,
            "presentation_text": MANUFACTURING_P2_PRESENTATION_TEXT,
            "contribution_bbox": MANUFACTURING_P2_CONTRIBUTION_BBOX,
            "source_object_ids": MANUFACTURING_P2_SOURCE_OBJECT_IDS,
            "contribution_bbox_id": MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
            "synthetic_element_id": MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID,
            "contribution_evidence_id": (
                MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID
            ),
            "synthetic_public_item_id": (
                MANUFACTURING_P2_SYNTHETIC_PUBLIC_ITEM_ID
            ),
            "synthetic_canonical_block_id": (
                MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID
            ),
            "contribution_evidence": (
                MANUFACTURING_P2_CONTRIBUTION_EVIDENCE
            ),
            "extraction_plan": MANUFACTURING_P2_EXTRACTION_PLAN,
        },
        "frozen_aggregates": FROZEN_AGGREGATES,
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


# Sealed after constructing and independently validating the static payload.
EXPECTED_ORACLE_SHA256: Final = (
    "ab7ce318bf390da82306c627ef1eee0352ded574245c4cdb901422e67bf26d7f"
)


def validate_oracle() -> None:
    """Validate every sealed source, projection, and canonical ledger."""

    def assert_hash(value: Any) -> None:
        assert (
            isinstance(value, str)
            and len(value) == 64
            and set(value) <= set("0123456789abcdef")
        )

    def json_sha256(value: Any) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    assert set(SOURCE_IDENTITIES) == set(PREDECESSOR_OUTPUT_IDENTITIES)
    assert set(SOURCE_IDENTITIES) == set(SOURCE_REPORTS)
    assert len(PREDECESSOR_CONFIGURATION) == 10
    assert set(PREDECESSOR_CONFIGURATION.values()) == {True}
    assert PREDECESSOR_OUTPUT_ROOT.endswith(
        "P03-US08-post-US07-predecessor-20260801"
    )
    for case_id, source in SOURCE_IDENTITIES.items():
        assert set(source) == {"path", "size_bytes", "sha256", "page_count"}
        assert source["path"].endswith(f"/{case_id}.pdf")
        assert source["size_bytes"] > 0 and source["page_count"] > 0
        assert_hash(source["sha256"])
        predecessor = PREDECESSOR_OUTPUT_IDENTITIES[case_id]
        assert set(predecessor) == {"size_bytes", "sha256"}
        assert predecessor["size_bytes"] > 0
        assert_hash(predecessor["sha256"])

    page_keys = tuple(
        (entry["case_id"], entry["physical_page"]) for entry in PAGE_IDENTITIES
    )
    assert page_keys == tuple(PAGE_BINDINGS)
    assert set(page_keys) == set(SOURCE_PAGE_COUNTS)
    assert len(page_keys) == len(set(page_keys)) == 30
    assert sum(value["page_count"] for value in SOURCE_IDENTITIES.values()) == 30
    assert len(PAGE_BINDING_ROWS) == len(PAGE_BINDINGS) == 30
    assert len(SOURCE_PAGE_COUNT_ROWS) == len(SOURCE_PAGE_COUNTS) == 30
    positives = tuple(
        entry
        for entry in PAGE_IDENTITIES
        if entry["detected_printed_label"] is not None
    )
    nulls = tuple(
        entry
        for entry in PAGE_IDENTITIES
        if entry["detected_printed_label"] is None
    )
    assert len(positives) == 27
    assert {(entry["case_id"], entry["physical_page"]) for entry in nulls} == {
        ("insurance-acord", 1),
        ("purchase-agreement", 1),
        ("uber-earnings", 1),
    }
    page_by_key = {
        (entry["case_id"], entry["physical_page"]): entry
        for entry in PAGE_IDENTITIES
    }
    for key, entry in page_by_key.items():
        case_id, physical_page = key
        binding = PAGE_BINDINGS[key]
        for field in (
            "page_id",
            "legacy_page_index",
            "legacy_page_number",
            "legacy_page_label",
            "source_character_indexes",
            "source_word_indexes",
        ):
            assert entry[field] == binding[field]
        expected_objects = tuple(
            _source_object_id(case_id, physical_page, "character", index)
            for index in binding["source_character_indexes"]
        ) + tuple(
            _source_object_id(case_id, physical_page, "word", index)
            for index in binding["source_word_indexes"]
        )
        assert entry["source_object_ids"] == expected_objects
        source_counts = SOURCE_PAGE_COUNTS[key]
        assert all(
            index < source_counts["source_character_count"]
            for index in binding["source_character_indexes"]
        )
        assert all(
            index < source_counts["source_word_count"]
            for index in binding["source_word_indexes"]
        )
        assert entry["source_sha256"] == SOURCE_IDENTITIES[case_id]["sha256"]
        assert entry["embedded_label"] is None
        assert entry["predecessor_page_number"] == binding["legacy_page_number"]
        assert entry["legacy_navigation_conflict"] == (
            entry["predecessor_page_number"] != physical_page
        )
        descriptor = PAGE_IDENTITY_DESCRIPTORS[key]
        assert tuple(descriptor) == PAGE_IDENTITY_CONTRACT_FIELDS
        assert descriptor == _page_identity_descriptor(entry)
        assert entry["concern_codes"] == ()
        evidence = entry["evidence_source"]
        assert set(evidence) == {
            "method",
            "reader",
            "page_index",
            "public_item_id",
            "public_path",
            "element_id",
            "bbox_id",
            "evidence_ids",
            "source_object_ids",
        }
        if entry["is_detected_printed_label"]:
            assert entry["visible_text"] and entry["label_bbox"] is not None
            assert entry["visible_text_sha256"] == _text_sha256(
                entry["visible_text"]
            )
            assert entry["display_label"] == entry["detected_printed_label"]
            assert entry["display_source"] == "detected_printed_label"
            assert binding["source_character_indexes"]
            assert binding["source_word_indexes"]
            expected_candidate_id = _stable_id(
                "label-candidate",
                POLICY_ID,
                SOURCE_IDENTITIES[case_id]["sha256"],
                physical_page,
                expected_objects,
                entry["label_bbox"],
            )
            assert entry["label_candidate_id"] == expected_candidate_id
            assert evidence == {
                "method": "native_printed_label",
                "reader": "pdfplumber",
                "page_index": physical_page,
                "public_item_id": None,
                "public_path": (),
                "element_id": None,
                "bbox_id": None,
                "evidence_ids": (expected_candidate_id,),
                "source_object_ids": expected_objects,
            }
            assert entry["confidence"] == {
                "scope": "deterministic_rule",
                "score": 1.0,
                "unavailable_reason": None,
            }
        else:
            assert entry["visible_text"] is None and entry["label_bbox"] is None
            assert entry["visible_text_sha256"] is None
            assert entry["label_candidate_id"] is None
            assert entry["display_source"] == "legacy_display_fallback"
            assert evidence == {
                "method": "legacy_display_fallback",
                "reader": "configured_predecessor",
                "page_index": physical_page,
                "public_item_id": None,
                "public_path": (),
                "element_id": None,
                "bbox_id": None,
                "evidence_ids": (),
                "source_object_ids": (
                    _configured_page_label_source_id(case_id, physical_page),
                ),
            }
            assert entry["confidence"] == {
                "scope": "unavailable",
                "score": None,
                "unavailable_reason": "page_identity_source_unavailable",
            }

    region_keys = tuple(
        (
            entry["case_id"],
            entry["physical_page"],
            entry["source_public_item_id"],
        )
        for entry in ACCEPTED_RUNNING_REGIONS
    )
    assert len(ITEM_BINDING_ROWS) == len(ITEM_BINDINGS) == 47
    assert len(region_keys) == len(set(region_keys)) == 47
    assert set(region_keys) == set(ITEM_BINDINGS)
    assert len({entry["region_id"] for entry in ACCEPTED_RUNNING_REGIONS}) == 47
    assert set(RUNNING_REGION_DESCRIPTORS) == {
        entry["region_id"] for entry in ACCEPTED_RUNNING_REGIONS
    }
    source_method_counts = Counter()
    nonnull_group_ids: set[str] = set()
    repeated_region_count = 0
    for entry in ACCEPTED_RUNNING_REGIONS:
        key = (
            entry["case_id"],
            entry["physical_page"],
            entry["source_public_item_id"],
        )
        case_id, physical_page, source_public_item_id = key
        binding = ITEM_BINDINGS[key]
        extraction = (
            entry["source_method"] == "extracted_source_contribution"
        )
        assert entry["source_public_path"] == binding["public_path"]
        assert entry["owner_element_id"] == binding["owner_element_id"]
        assert entry["owner_bbox_id"] == binding["owner_bbox_id"]
        assert entry["owner_evidence_ids"] == binding["evidence_ids"]
        assert entry["owner_canonical_block_id"] == binding[
            "owner_canonical_block_id"
        ]
        assert entry["predecessor_item_sha256"] == binding[
            "predecessor_item_sha256"
        ]
        assert entry["source_word_indexes"] == binding["source_word_indexes"]
        assert all(
            index
            < SOURCE_PAGE_COUNTS[(case_id, physical_page)][
                "source_word_count"
            ]
            for index in binding["source_word_indexes"]
        )
        assert entry["order_neighbors"] == binding["order_neighbors"]
        assert entry["reviewed_call_neighbors"] == binding["order_neighbors"]
        assert entry["text_sha256"] == _text_sha256(entry["text"])
        assert entry["bbox"]["unit"] == "pt"
        assert entry["kind"] == entry["role"]
        assert entry["canonical_scope"] == (
            "header"
            if entry["role"] in {"header", "navigation_top"}
            else "footer"
        )
        assert entry["confidence"] == {
            "scope": "deterministic_rule",
            "score": 1.0,
            "unavailable_reason": None,
        }
        assert entry["concern_codes"] == ()
        descriptor = RUNNING_REGION_DESCRIPTORS[entry["region_id"]]
        assert tuple(descriptor) == RUNNING_REGION_CONTRACT_FIELDS
        assert descriptor == _running_region_descriptor(entry)
        source_method_counts[entry["source_method"]] += 1
        if extraction:
            assert key == ("manufacturing-report", 2, "p2-i1")
            assert entry["origin"] == "extracted_predecessor_contribution"
            assert entry["source_element_id"] == (
                MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID
            )
            assert entry["bbox_id"] == MANUFACTURING_P2_CONTRIBUTION_BBOX_ID
            assert entry["bbox"] == MANUFACTURING_P2_CONTRIBUTION_BBOX
            assert entry["evidence_ids"] == (
                MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID,
            )
            assert entry["canonical_block_id"] == (
                MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID
            )
            assert entry["source_character_indexes"] == tuple(range(29))
            assert entry["source_object_ids"] == (
                MANUFACTURING_P2_SOURCE_OBJECT_IDS
            )
            assert entry["extraction_plan"] == MANUFACTURING_P2_EXTRACTION_PLAN
            id_parts = (
                POLICY_ID,
                SOURCE_IDENTITIES[case_id]["sha256"],
                physical_page,
                source_public_item_id,
                entry["source_object_ids"],
                entry["evidence_ids"],
                entry["bbox_id"],
                entry["role"],
            )
            assert entry["region_id"] == _stable_id(
                "running-region", *id_parts
            )
            assert entry["public_item_id"] == _stable_id(
                "running-region-item", *id_parts
            )
        else:
            assert entry["public_item_id"] == source_public_item_id
            assert entry["source_element_id"] == binding["owner_element_id"]
            assert entry["bbox_id"] == binding["owner_bbox_id"]
            assert entry["evidence_ids"] == binding["evidence_ids"]
            assert entry["canonical_block_id"] == binding[
                "owner_canonical_block_id"
            ]
            assert entry["source_character_indexes"] == ()
            assert entry["source_object_ids"] == tuple(
                _source_object_id(case_id, physical_page, "word", index)
                for index in binding["source_word_indexes"]
            )
            assert entry["extraction_plan"] is None
            assert entry["region_id"] == _stable_id(
                "running-region",
                POLICY_ID,
                SOURCE_IDENTITIES[case_id]["sha256"],
                physical_page,
                entry["source_element_id"],
                entry["bbox_id"],
                entry["role"],
            )
        expected_scope = {
            "body": (),
            "header": (
                (entry["canonical_block_id"],)
                if entry["canonical_scope"] == "header"
                else ()
            ),
            "footer": (
                (entry["canonical_block_id"],)
                if entry["canonical_scope"] == "footer"
                else ()
            ),
            "full": (entry["canonical_block_id"],),
        }
        assert entry["scope_membership"] == expected_scope
        assert entry["expected_body_count"] == 0
        assert entry["expected_full_count"] == 1
        group_key = entry["repetition_group_key"]
        if group_key is None:
            assert entry["repetition_group_id"] is None
            assert entry["repetition_group"] is None
            assert entry["repetition_page_indexes"] == ()
            assert entry["normalized_signature"] == _normalized_signature(
                entry["text"]
            )
        else:
            spec = VALID_REPETITION_GROUPS[group_key]
            assert physical_page in spec["page_indexes"]
            assert len(spec["page_indexes"]) >= 2
            expected_group_id = _stable_id(
                "running-repeat",
                POLICY_ID,
                SOURCE_IDENTITIES[case_id]["sha256"],
                spec["boundary_band"],
                spec["normalized_signature"],
            )
            assert entry["repetition_group_id"] == expected_group_id
            assert entry["repetition_group"] == expected_group_id
            assert entry["repetition_page_indexes"] == spec["page_indexes"]
            assert entry["normalized_signature"] == spec[
                "normalized_signature"
            ]
            nonnull_group_ids.add(expected_group_id)
            repeated_region_count += 1

    before_counts = Counter(
        entry["before_inventory_type"] for entry in BEFORE_RUNNING_REGIONS
    )
    assert len(BEFORE_RUNNING_REGIONS) == 41
    assert before_counts == Counter({"footer": 28, "header": 13})
    assert len(REQUIRED_CORRECTIONS) == 6
    assert {
        (
            entry["case_id"],
            entry["physical_page"],
            entry["source_public_item_id"],
        )
        for entry in REQUIRED_CORRECTIONS
    } == set(CORRECTION_SOURCE_METHODS)
    assert len(nonnull_group_ids) == len(VALID_REPETITION_GROUPS) == 9
    assert repeated_region_count == 28
    for group_key, spec in VALID_REPETITION_GROUPS.items():
        members = tuple(
            entry
            for entry in ACCEPTED_RUNNING_REGIONS
            if entry["repetition_group_key"] == group_key
        )
        assert tuple(
            sorted(entry["physical_page"] for entry in members)
        ) == spec["page_indexes"]
        assert len(members) == len(spec["page_indexes"])
        assert {
            entry["normalized_signature"] for entry in members
        } == {spec["normalized_signature"]}
        assert {
            _boundary_candidate(entry)["boundary_band"] for entry in members
        } == {spec["boundary_band"]}
        vertical_positions = []
        for entry in members:
            identity = page_by_key[
                (entry["case_id"], entry["physical_page"])
            ]
            vertical_positions.append(
                entry["bbox"]["y"] / identity["height_pt"]
            )
        assert max(vertical_positions) - min(vertical_positions) <= 0.02
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                overlap = max(
                    0.0,
                    min(
                        left["bbox"]["x"] + left["bbox"]["width"],
                        right["bbox"]["x"] + right["bbox"]["width"],
                    )
                    - max(left["bbox"]["x"], right["bbox"]["x"]),
                )
                assert overlap / left["bbox"]["width"] >= 0.50
                assert overlap / right["bbox"]["width"] >= 0.50

    source_report_fields = {
        "report_version",
        "policy_id",
        "source_sha256",
        "status",
        "pages",
        "counts",
        "concern_codes",
        "extraction_ms",
    }
    source_page_fields = {
        "page_index",
        "page_width",
        "page_height",
        "unit",
        "coordinate_system_id",
        "source_character_count",
        "source_word_count",
        "embedded_label",
        "label_candidates",
        "boundary_candidates",
        "concern_codes",
    }
    label_fields = {
        "id",
        "visible_text",
        "normalized_label",
        "bbox",
        "source_object_ids",
        "source_method",
        "confidence",
        "concern_codes",
    }
    boundary_fields = {
        "id",
        "public_item_id",
        "public_path",
        "element_id",
        "predecessor_type",
        "bbox",
        "bbox_id",
        "evidence_ids",
        "source_object_ids",
        "raw_layout_role",
        "normalized_signature",
        "boundary_band",
        "source_method",
        "confidence",
        "concern_codes",
        "disposition",
    }
    count_fields = {
        "page_count",
        "source_character_count",
        "source_word_count",
        "embedded_label_count",
        "label_candidate_count",
        "boundary_candidate_count",
        "concern_count",
    }
    boundary_candidate_ids: set[str] = set()
    for case_id, report in SOURCE_REPORTS.items():
        assert set(report) == source_report_fields
        assert report["report_version"] == "1.0"
        assert report["policy_id"] == POLICY_ID
        assert report["source_sha256"] == SOURCE_IDENTITIES[case_id]["sha256"]
        assert report["status"] == "available"
        assert report["concern_codes"] == ()
        assert report["extraction_ms"] == 0.0
        assert set(report["counts"]) == count_fields
        assert tuple(page["page_index"] for page in report["pages"]) == tuple(
            range(1, SOURCE_IDENTITIES[case_id]["page_count"] + 1)
        )
        totals = Counter()
        report_region_ids: set[str] = set()
        for source_page in report["pages"]:
            assert set(source_page) == source_page_fields
            key = (case_id, source_page["page_index"])
            identity = page_by_key[key]
            assert source_page["page_width"] == identity["width_pt"]
            assert source_page["page_height"] == identity["height_pt"]
            assert source_page["unit"] == "pt"
            assert source_page["coordinate_system_id"] == (
                "pdf-top-left-pt-v1"
            )
            assert {
                "source_character_count": source_page[
                    "source_character_count"
                ],
                "source_word_count": source_page["source_word_count"],
            } == SOURCE_PAGE_COUNTS[key]
            assert source_page["embedded_label"] is None
            assert source_page["concern_codes"] == ()
            labels = source_page["label_candidates"]
            if identity["is_detected_printed_label"]:
                assert len(labels) == 1
                label = labels[0]
                assert set(label) == label_fields
                assert label == _label_candidate(identity)
                assert label["id"] == identity["evidence_source"][
                    "evidence_ids"
                ][0]
            else:
                assert labels == ()
            expected_regions = tuple(
                entry
                for entry in ACCEPTED_RUNNING_REGIONS
                if entry["case_id"] == case_id
                and entry["physical_page"] == source_page["page_index"]
            )
            boundaries = source_page["boundary_candidates"]
            assert len(boundaries) == len(expected_regions)
            for region, candidate in zip(expected_regions, boundaries):
                assert set(candidate) == boundary_fields
                assert candidate == _boundary_candidate(region)
                assert candidate["id"] == _stable_id(
                    "boundary-candidate",
                    POLICY_ID,
                    SOURCE_IDENTITIES[case_id]["sha256"],
                    source_page["page_index"],
                    candidate["public_item_id"],
                    candidate["public_path"],
                    candidate["element_id"],
                    candidate["bbox_id"],
                    candidate["evidence_ids"],
                    candidate["source_object_ids"],
                    candidate["boundary_band"],
                    candidate["source_method"],
                )
                assert candidate["id"] not in boundary_candidate_ids
                boundary_candidate_ids.add(candidate["id"])
                assert candidate["disposition"] == "accepted"
                descriptor = RUNNING_REGION_DESCRIPTORS[
                    region["region_id"]
                ]
                assert (
                    candidate["public_item_id"],
                    candidate["public_path"],
                    candidate["element_id"],
                    candidate["predecessor_type"],
                    candidate["bbox"],
                    candidate["bbox_id"],
                    candidate["evidence_ids"],
                    candidate["source_object_ids"],
                    candidate["source_method"],
                ) == (
                    descriptor["source_public_item_id"],
                    descriptor["source_public_path"],
                    descriptor["source_element_id"],
                    descriptor["predecessor_type"],
                    descriptor["bbox"],
                    descriptor["bbox_id"],
                    descriptor["evidence_ids"],
                    descriptor["source_object_ids"],
                    descriptor["source_method"],
                )
                report_region_ids.add(region["region_id"])
            totals["page_count"] += 1
            totals["source_character_count"] += source_page[
                "source_character_count"
            ]
            totals["source_word_count"] += source_page["source_word_count"]
            totals["embedded_label_count"] += int(
                source_page["embedded_label"] is not None
            )
            totals["label_candidate_count"] += len(labels)
            totals["boundary_candidate_count"] += len(boundaries)
            totals["concern_count"] += len(source_page["concern_codes"])
        totals["concern_count"] += len(report["concern_codes"])
        assert dict(totals) == report["counts"]
        assert report_region_ids == {
            entry["region_id"]
            for entry in ACCEPTED_RUNNING_REGIONS
            if entry["case_id"] == case_id
        }
    assert len(boundary_candidate_ids) == 47

    assert PRINTED_LABEL_VISIBILITY_CONTRACT == {
        "method": "pdfium_candidate_bbox_modal_rgb_v1",
        "render_scale_pixels_per_point": 4.0,
        "render_background_rgb": (255, 255, 255),
        "forms_rendered": False,
        "annotations_rendered": False,
        "minimum_channel_delta": 16,
        "maximum_render_dimension_pixels": 2_048,
        "maximum_render_pixels": 262_144,
        "maximum_non_stroking_fills": 256,
        "painted_fill_render_modes": (0, 2, 4, 6),
        "minimum_non_stroking_fill_alpha": 1,
        "fill_custody": (
            "gray_rgb_exact_cmyk_bidirectional_max_channel_delta"
        ),
        "maximum_cmyk_custody_channel_delta": 36,
        "candidate_object_binding": (
            "unique_compacted_sequence_or_delimiter_bounded_exact_suffix"
        ),
        "candidate_object_suffix_delimiters": (
            "whitespace",
            "|",
            ":",
            "/",
            "-",
        ),
        "selected_pdfium_rgb_is_contrast_authority": True,
        "maximum_text_objects": 256,
        "maximum_text_object_scan": 10_000,
        "maximum_form_depth": 8,
        "degenerate_finite_text_objects": "skipped",
        "nonfinite_text_object_bounds": "rejected",
        "minimum_intersecting_painted_text_objects": 1,
        "maximum_page_dimension_points": 20_000.0,
        "modal_tie_break": (
            "highest_count_then_lexicographically_smallest_rgb"
        ),
        "candidate_pixel_edges": "nearest_integer_ties_to_even",
        "retention": "ephemeral_gate_only",
    }
    assert len(SOURCE_VISIBILITY_CONTROLS) == 3
    assert tuple(
        (control["physical_page"], control["visible"])
        for control in SOURCE_VISIBILITY_CONTROLS
    ) == ((1, False), (2, True), (3, True))
    assert all(
        control["case_id"] == "uber-earnings"
        and control["pixel_count"]
        == control["width_pixels"] * control["height_pixels"]
        and control["modal_pixel_count"] <= control["pixel_count"]
        and len(control["render_rgb_sha256"]) == 64
        for control in SOURCE_VISIBILITY_CONTROLS
    )
    assert SOURCE_VISIBILITY_CONTROLS[0]["public_item_id"] == "p1-i4"
    assert SOURCE_VISIBILITY_CONTROLS[0]["render_max_channel_delta"] == 0
    assert SOURCE_VISIBILITY_CONTROLS[0][
        "minimum_fill_modal_channel_delta"
    ] == 0
    assert SOURCE_VISIBILITY_CONTROLS[0]["disposition"] == (
        "rejected_hidden_glyph"
    )
    assert all(
        control["render_max_channel_delta"] >= 16
        and control["minimum_fill_modal_channel_delta"] >= 16
        and control["disposition"] == "accepted_visible_glyph"
        for control in SOURCE_VISIBILITY_CONTROLS[1:]
    )

    boundary_candidates_by_id = {
        candidate["id"]: candidate
        for report in SOURCE_REPORTS.values()
        for page in report["pages"]
        for candidate in page["boundary_candidates"]
    }
    expected_proof_methods = {
        "boundary-candidate-08250274384c8509de06": "boundary_navigation",
        "boundary-candidate-f4411d4d8df4bc40188a": (
            "effective_boundary_cluster"
        ),
        "boundary-candidate-b1588836d411b6d58339": (
            "printed_label_boundary"
        ),
        "boundary-candidate-6990811cba6136a6f381": (
            "extracted_source_contribution"
        ),
    }
    assert set(BOUNDARY_METHOD_PROOFS) == set(expected_proof_methods)
    assert {
        candidate_id: boundary_candidates_by_id[candidate_id][
            "source_method"
        ]
        for candidate_id in BOUNDARY_METHOD_PROOFS
    } == expected_proof_methods
    assert BOUNDARY_METHOD_PROOFS[
        "boundary-candidate-08250274384c8509de06"
    ] == {
        "navigation_cue": "TABLE OF CONTENTS",
        "effective_cluster": ESG_EFFECTIVE_BOTTOM_CLUSTER,
    }
    assert BOUNDARY_METHOD_PROOFS[
        "boundary-candidate-f4411d4d8df4bc40188a"
    ] == ESG_EFFECTIVE_BOTTOM_CLUSTER
    assert BOUNDARY_METHOD_PROOFS[
        "boundary-candidate-b1588836d411b6d58339"
    ] == {
        "label_candidate_id": "label-candidate-7bd19e5695b807870699",
        "effective_cluster": ESG_EFFECTIVE_BOTTOM_CLUSTER,
    }
    assert BOUNDARY_METHOD_PROOFS[
        "boundary-candidate-6990811cba6136a6f381"
    ] == {
        "native_source": True,
        "evidence_mode": "exact_repetition",
        "repetition_page_indexes": (1, 2, 3),
        "complete_delimiter_line": True,
        "scalar_match_count": 1,
        "intervals_disjoint": True,
        "owner_kind": "chart",
    }
    assert tuple(
        item["id"] for item in ESG_EFFECTIVE_BOTTOM_CLUSTER["items"]
    ) == ("p1-i11", "p1-i19", "p1-i20")
    assert tuple(
        item["presentation_index"]
        for item in ESG_EFFECTIVE_BOTTOM_CLUSTER["items"]
    ) == (17, 18, 19)
    assert len(ESG_EFFECTIVE_BOTTOM_CLUSTER["remaining_body_bboxes"]) == 17
    cluster_top = min(
        float(item["bbox"]["y"])
        for item in ESG_EFFECTIVE_BOTTOM_CLUSTER["items"]
    )
    assert all(
        float(bbox["y"]) + float(bbox["height"]) < cluster_top
        for bbox in ESG_EFFECTIVE_BOTTOM_CLUSTER[
            "remaining_body_bboxes"
        ]
    )

    plan = MANUFACTURING_P2_EXTRACTION_PLAN
    assert set(plan) == {
        "physical_page_index",
        "owner_public_item_id",
        "owner_sha256_before",
        "owner_sha256_after",
        "predecessor_canonical",
        "source_text",
        "presentation_text",
        "presentation_fragments",
        "delimiters",
        "predecessor_intervals",
        "residual_insertion_offsets",
        "source_span_groups",
        "whitespace_mappings",
        "residual_canonical",
        "source_text_sha256",
        "presentation_text_sha256",
        "predecessor_sha256",
        "presentation_fragment_sha256",
        "removed_interval_sha256",
        "delimiter_sha256",
        "ordered_plan_sha256",
        "residual_sha256",
    }
    assert plan["owner_sha256_before"] == plan["owner_sha256_after"]
    assert plan["owner_sha256_before"] == ITEM_BINDINGS[
        ("manufacturing-report", 2, "p2-i1")
    ]["predecessor_item_sha256"]
    assert plan["source_text"] == MANUFACTURING_P2_SOURCE_TEXT
    assert plan["presentation_text"] == MANUFACTURING_P2_PRESENTATION_TEXT
    assert len(plan["source_text"].encode("utf-8")) == 29
    assert len(plan["presentation_text"].encode("utf-8")) == 29
    assert len(plan["predecessor_canonical"].encode("utf-8")) == 412
    assert len(plan["residual_canonical"].encode("utf-8")) == 382
    assert plan["predecessor_intervals"] == ((0, 16), (63, 77))
    assert plan["residual_insertion_offsets"] == (0, 47)
    assert plan["source_span_groups"] == (((0, 15),), ((16, 29),))
    assert plan["presentation_fragments"] == (
        "NIST AMS 100-76",
        "February 2026",
    )
    assert plan["delimiters"] == ("\n", "\n")
    assert plan["presentation_text"] == (
        plan["presentation_fragments"][0]
        + plan["delimiters"][0]
        + plan["presentation_fragments"][1]
    )
    assert plan["source_text"] == plan["source_text"].strip()
    assert plan["presentation_text"] == plan["presentation_text"].strip()
    assert plan["source_text"].split() == plan["presentation_text"].split()
    assert plan["whitespace_mappings"] == (
        (4, 5, 4, 5),
        (8, 9, 8, 9),
        (15, 16, 15, 16),
        (24, 25, 24, 25),
    )
    predecessor = plan["predecessor_canonical"].encode("utf-8")
    residual = plan["residual_canonical"].encode("utf-8")
    removed = []
    residual_parts = []
    cursor = 0
    for index, ((start, end), fragment, delimiter) in enumerate(
        zip(
            plan["predecessor_intervals"],
            plan["presentation_fragments"],
            plan["delimiters"],
        )
    ):
        current = predecessor[start:end]
        assert current == (fragment + delimiter).encode("utf-8")
        assert predecessor.count(current) == 1
        assert _text_sha256(fragment) == plan[
            "presentation_fragment_sha256"
        ][index]
        assert hashlib.sha256(current).hexdigest() == plan[
            "removed_interval_sha256"
        ][index]
        assert _text_sha256(delimiter) == plan["delimiter_sha256"][index]
        residual_parts.append(predecessor[cursor:start])
        removed.append(current)
        cursor = end
    residual_parts.append(predecessor[cursor:])
    assert b"".join(residual_parts) == residual
    reconstructed = []
    cursor = 0
    for offset, current in zip(plan["residual_insertion_offsets"], removed):
        reconstructed.extend((residual[cursor:offset], current))
        cursor = offset
    reconstructed.append(residual[cursor:])
    assert b"".join(reconstructed) == predecessor
    assert _text_sha256(plan["source_text"]) == plan["source_text_sha256"]
    assert _text_sha256(plan["presentation_text"]) == plan[
        "presentation_text_sha256"
    ]
    assert hashlib.sha256(predecessor).hexdigest() == plan[
        "predecessor_sha256"
    ]
    assert hashlib.sha256(residual).hexdigest() == plan["residual_sha256"]
    assert plan["predecessor_sha256"] == (
        "215207bae26281781c882588d9b7e18329fcb0bbd4a99e02f27fe3b174323263"
    )
    assert plan["presentation_text_sha256"] == (
        "73e62bab37811c65369b4bef892b698e7f8871cc4d1b498544bbd4463535379a"
    )
    assert plan["residual_sha256"] == (
        "b2d1d1a36c36ced44ee18bb70265c4edf038469619861bbba227dbe7855f7ef4"
    )
    ordered_plan = {
        key: plan[key]
        for key in (
            "presentation_fragments",
            "delimiters",
            "predecessor_intervals",
            "residual_insertion_offsets",
            "source_span_groups",
            "whitespace_mappings",
        )
    }
    assert json_sha256(ordered_plan) == plan["ordered_plan_sha256"]
    assert plan["ordered_plan_sha256"] == (
        "910589a170b03838c5d9249e7e79f3a1233e5b45a2387b3b555ab431272deb1b"
    )

    assert MANUFACTURING_P2_CONTRIBUTION_BBOX_ID == _stable_id(
        "running-bbox",
        POLICY_ID,
        SOURCE_IDENTITIES["manufacturing-report"]["sha256"],
        2,
        "p2-i1",
        MANUFACTURING_P2_SOURCE_OBJECT_IDS,
        MANUFACTURING_P2_CONTRIBUTION_BBOX,
        "header",
    )
    assert MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID == _stable_id(
        "running-element",
        POLICY_ID,
        SOURCE_IDENTITIES["manufacturing-report"]["sha256"],
        2,
        "p2-i1",
        MANUFACTURING_P2_SOURCE_OBJECT_IDS,
        MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
        "header",
    )
    assert MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID == _stable_id(
        "running-region-evidence",
        POLICY_ID,
        SOURCE_IDENTITIES["manufacturing-report"]["sha256"],
        2,
        "p2-i1",
        MANUFACTURING_P2_SOURCE_OBJECT_IDS,
        MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
        "header",
    )
    assert MANUFACTURING_P2_SYNTHETIC_PUBLIC_ITEM_ID == _stable_id(
        "running-region-item",
        POLICY_ID,
        SOURCE_IDENTITIES["manufacturing-report"]["sha256"],
        2,
        "p2-i1",
        MANUFACTURING_P2_SOURCE_OBJECT_IDS,
        (MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID,),
        MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
        "header",
    )
    assert MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID == _stable_id(
        "pb",
        "1.0",
        "canonical-presentation-v1",
        PAGE_BINDINGS[("manufacturing-report", 2)]["page_id"],
        MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID,
    )
    assert MANUFACTURING_P2_CONTRIBUTION_EVIDENCE == {
        "id": MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID,
        "element_id": MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID,
        "method": "native",
        "bbox_id": MANUFACTURING_P2_CONTRIBUTION_BBOX_ID,
        "value": MANUFACTURING_P2_SOURCE_TEXT,
        "confidence": {
            "scope": "evidence",
            "score": None,
            "unavailable_reason": "not_calibrated",
        },
        "metadata": {
            "policy_id": POLICY_ID,
            "source_object_ids": list(MANUFACTURING_P2_SOURCE_OBJECT_IDS),
        },
    }

    assert set(PREDECESSOR_CANONICAL_BLOCK_IDS) == set(page_keys)
    assert set(CANONICAL_PAGE_MEMBERSHIP) == set(page_keys)
    for key, membership in CANONICAL_PAGE_MEMBERSHIP.items():
        predecessor_full = PREDECESSOR_CANONICAL_BLOCK_IDS[key]
        assert membership["predecessor_full_block_ids"] == predecessor_full
        assert len(predecessor_full) == len(set(predecessor_full))
        full = list(predecessor_full)
        if key == ("manufacturing-report", 2):
            owner = _MANUFACTURING_P2_OWNER_BINDING[
                "owner_canonical_block_id"
            ]
            full.insert(
                full.index(owner),
                MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID,
            )
            assert full.index(MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID) + 1 == (
                full.index(owner)
            )
        page_regions = tuple(
            entry
            for entry in ACCEPTED_RUNNING_REGIONS
            if (entry["case_id"], entry["physical_page"]) == key
        )
        scope_by_id = {
            entry["canonical_block_id"]: entry["canonical_scope"]
            for entry in page_regions
        }
        expected_full = tuple(full)
        expected_body = tuple(
            block_id for block_id in full if block_id not in scope_by_id
        )
        expected_header = tuple(
            block_id
            for block_id in full
            if scope_by_id.get(block_id) == "header"
        )
        expected_footer = tuple(
            block_id
            for block_id in full
            if scope_by_id.get(block_id) == "footer"
        )
        assert membership == {
            "predecessor_full_block_ids": predecessor_full,
            "body_block_ids": expected_body,
            "header_block_ids": expected_header,
            "footer_block_ids": expected_footer,
            "full_block_ids": expected_full,
        }
        assert not set(expected_body) & set(expected_header)
        assert not set(expected_body) & set(expected_footer)
        assert not set(expected_header) & set(expected_footer)
        assert set(expected_body) | set(expected_header) | set(
            expected_footer
        ) == set(expected_full)

    assert len(REVIEWED_NON_TARGETS) == 2
    negative_ids: set[str] = set()
    for negative in REVIEWED_NON_TARGETS:
        key = (
            negative["case_id"],
            negative["physical_page"],
            negative["public_item_id"],
        )
        binding = ITEM_BINDINGS[key]
        region = _REGION_BY_SOURCE_ITEM[key]
        expected_id = _stable_id(
            "running-negative",
            POLICY_ID,
            SOURCE_IDENTITIES[negative["case_id"]]["sha256"],
            negative["physical_page"],
            negative["public_item_id"],
            "printed_page_identity",
        )
        assert negative["id"] == expected_id
        assert expected_id not in negative_ids
        negative_ids.add(expected_id)
        assert negative["public_path"] == binding["public_path"]
        assert negative["element_id"] == binding["owner_element_id"]
        assert negative["bbox_id"] == binding["owner_bbox_id"]
        assert negative["bbox"] == region["bbox"]
        assert negative["evidence_ids"] == binding["evidence_ids"]
        assert negative["accepted_running_region_id"] == region["region_id"]
        assert page_by_key[
            (negative["case_id"], negative["physical_page"])
        ]["detected_printed_label"] is None

    derived = {
        "source_case_count": len(SOURCE_IDENTITIES),
        "physical_page_count": len(PAGE_IDENTITIES),
        "page_binding_count": len(PAGE_BINDINGS),
        "predecessor_output_count": len(PREDECESSOR_OUTPUT_IDENTITIES),
        "predecessor_output_total_size_bytes": sum(
            entry["size_bytes"]
            for entry in PREDECESSOR_OUTPUT_IDENTITIES.values()
        ),
        "predecessor_configuration_flag_count": len(
            PREDECESSOR_CONFIGURATION
        ),
        "source_report_count": len(SOURCE_REPORTS),
        "source_report_page_count": sum(
            report["counts"]["page_count"] for report in SOURCE_REPORTS.values()
        ),
        "source_report_character_count": sum(
            report["counts"]["source_character_count"]
            for report in SOURCE_REPORTS.values()
        ),
        "source_report_word_count": sum(
            report["counts"]["source_word_count"]
            for report in SOURCE_REPORTS.values()
        ),
        "source_report_label_candidate_count": sum(
            report["counts"]["label_candidate_count"]
            for report in SOURCE_REPORTS.values()
        ),
        "source_report_boundary_candidate_count": sum(
            report["counts"]["boundary_candidate_count"]
            for report in SOURCE_REPORTS.values()
        ),
        "boundary_method_proof_count": len(BOUNDARY_METHOD_PROOFS),
        "source_visibility_control_count": len(
            SOURCE_VISIBILITY_CONTROLS
        ),
        "source_visibility_positive_count": sum(
            control["visible"] for control in SOURCE_VISIBILITY_CONTROLS
        ),
        "source_visibility_negative_count": sum(
            not control["visible"]
            for control in SOURCE_VISIBILITY_CONTROLS
        ),
        "embedded_label_null_count": sum(
            entry["embedded_label"] is None for entry in PAGE_IDENTITIES
        ),
        "detected_printed_label_positive_count": len(positives),
        "detected_printed_label_null_control_count": len(nulls),
        "source_only_detected_label_count": sum(
            entry["evidence_source"]["method"] == "native_printed_label"
            and entry["evidence_source"]["public_item_id"] is None
            for entry in PAGE_IDENTITIES
        ),
        "source_only_candidate_evidence_count": sum(
            len(entry["evidence_source"]["evidence_ids"])
            for entry in positives
        ),
        "exact_native_source_range_count": sum(
            bool(entry["source_character_indexes"])
            and bool(entry["source_word_indexes"])
            for entry in positives
        ),
        "mismatched_physical_printed_label_count": sum(
            entry["detected_printed_label"] != str(entry["physical_page"])
            for entry in positives
        ),
        "exact_visible_label_text_count": sum(
            entry["visible_text"] is not None for entry in positives
        ),
        "exact_visible_label_bbox_count": sum(
            entry["label_bbox"] is not None for entry in positives
        ),
        "before_distinct_detected_label_count": 0,
        "before_legacy_page_label_exact_display_count": sum(
            str(entry["legacy_page_label"])
            == entry["detected_printed_label"]
            for entry in positives
        ),
        "before_physical_page_number_count": sum(
            entry["predecessor_page_number"] == entry["physical_page"]
            for entry in PAGE_IDENTITIES
        ),
        "before_navigation_conflict_count": sum(
            bool(entry["legacy_navigation_conflict"])
            for entry in PAGE_IDENTITIES
        ),
        "after_distinct_detected_label_count": len(positives),
        "before_header_anchor_count": before_counts["header"],
        "before_footer_anchor_count": before_counts["footer"],
        "before_running_region_anchor_count": len(BEFORE_RUNNING_REGIONS),
        "required_correction_count": len(REQUIRED_CORRECTIONS),
        "accepted_running_region_count": len(ACCEPTED_RUNNING_REGIONS),
        "running_item_binding_count": len(ITEM_BINDINGS),
        "canonical_header_scope_count": sum(
            entry["canonical_scope"] == "header"
            for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "canonical_footer_scope_count": sum(
            entry["canonical_scope"] == "footer"
            for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "role_header_count": sum(
            entry["role"] == "header" for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "role_footer_count": sum(
            entry["role"] == "footer" for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "role_navigation_top_count": sum(
            entry["role"] == "navigation_top"
            for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "role_navigation_bottom_count": sum(
            entry["role"] == "navigation_bottom"
            for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "repetition_group_count": len(nonnull_group_ids),
        "repeated_region_count": repeated_region_count,
        "non_repetition_region_count": sum(
            entry["repetition_group_id"] is None
            for entry in ACCEPTED_RUNNING_REGIONS
        ),
        **{
            f"source_method_{method}_count": count
            for method, count in source_method_counts.items()
        },
        "reviewed_non_target_count": len(REVIEWED_NON_TARGETS),
        "canonical_page_membership_count": len(
            CANONICAL_PAGE_MEMBERSHIP
        ),
        "predecessor_canonical_block_count": sum(
            len(value) for value in PREDECESSOR_CANONICAL_BLOCK_IDS.values()
        ),
        "canonical_body_block_count": sum(
            len(value["body_block_ids"])
            for value in CANONICAL_PAGE_MEMBERSHIP.values()
        ),
        "canonical_header_block_count": sum(
            len(value["header_block_ids"])
            for value in CANONICAL_PAGE_MEMBERSHIP.values()
        ),
        "canonical_footer_block_count": sum(
            len(value["footer_block_ids"])
            for value in CANONICAL_PAGE_MEMBERSHIP.values()
        ),
        "canonical_full_block_count": sum(
            len(value["full_block_ids"])
            for value in CANONICAL_PAGE_MEMBERSHIP.values()
        ),
        "manufacturing_extraction_interval_count": len(
            plan["predecessor_intervals"]
        ),
        "manufacturing_extraction_source_span_count": sum(
            len(group) for group in plan["source_span_groups"]
        ),
        "manufacturing_synthetic_evidence_count": 1,
        "expected_body_inclusion_count": sum(
            entry["expected_body_count"] for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "expected_full_inclusion_count": sum(
            entry["expected_full_count"] for entry in ACCEPTED_RUNNING_REGIONS
        ),
        "exact_order_neighbor_record_count": sum(
            "order_neighbors" in entry for entry in ACCEPTED_RUNNING_REGIONS
        ),
    }
    assert set(derived) == set(FROZEN_AGGREGATES)
    assert derived == FROZEN_AGGREGATES


def assert_oracle_integrity() -> None:
    """Validate structural invariants and the sealed semantic digest."""

    validate_oracle()
    assert oracle_sha256() == EXPECTED_ORACLE_SHA256


__all__ = [
    "ACCEPTED_RUNNING_REGIONS",
    "BEFORE_RUNNING_REGIONS",
    "BOUNDARY_METHOD_PROOFS",
    "CANONICAL_PAGE_MEMBERSHIP",
    "COORDINATE_CONTRACT",
    "CORPUS_REGISTRY_CUSTODY",
    "CORRECTION_SOURCE_METHODS",
    "ESG_EFFECTIVE_BOTTOM_CLUSTER",
    "EXPECTED_ORACLE_SHA256",
    "FROZEN_AGGREGATES",
    "ITEM_BINDINGS",
    "ITEM_BINDING_ROWS",
    "MANUFACTURING_P2_CONTRIBUTION_BBOX",
    "MANUFACTURING_P2_CONTRIBUTION_BBOX_ID",
    "MANUFACTURING_P2_CONTRIBUTION_EVIDENCE",
    "MANUFACTURING_P2_CONTRIBUTION_EVIDENCE_ID",
    "MANUFACTURING_P2_EXTRACTION_PLAN",
    "MANUFACTURING_P2_PRESENTATION_TEXT",
    "MANUFACTURING_P2_SOURCE_OBJECT_IDS",
    "MANUFACTURING_P2_SOURCE_TEXT",
    "MANUFACTURING_P2_SYNTHETIC_CANONICAL_BLOCK_ID",
    "MANUFACTURING_P2_SYNTHETIC_ELEMENT_ID",
    "MANUFACTURING_P2_SYNTHETIC_PUBLIC_ITEM_ID",
    "PAGE_BINDINGS",
    "PAGE_BINDING_ROWS",
    "PAGE_IDENTITIES",
    "PAGE_IDENTITY_CONTRACT_FIELDS",
    "PAGE_IDENTITY_DESCRIPTORS",
    "POLICY_ID",
    "PREDECESSOR_CANONICAL_BLOCK_IDS",
    "PREDECESSOR_CONFIGURATION",
    "PREDECESSOR_OUTPUT_IDENTITIES",
    "PREDECESSOR_OUTPUT_ROOT",
    "PRINTED_LABEL_VISIBILITY_CONTRACT",
    "REQUIRED_CORRECTIONS",
    "REVIEWED_NON_TARGETS",
    "RUNNING_REGION_CONTRACT_FIELDS",
    "RUNNING_REGION_DESCRIPTORS",
    "SOURCE_IDENTITIES",
    "SOURCE_PAGE_COUNTS",
    "SOURCE_PAGE_COUNT_ROWS",
    "SOURCE_REPORTS",
    "SOURCE_VISIBILITY_CONTROLS",
    "VALID_REPETITION_GROUPS",
    "assert_oracle_integrity",
    "oracle_payload",
    "oracle_sha256",
    "validate_oracle",
]
