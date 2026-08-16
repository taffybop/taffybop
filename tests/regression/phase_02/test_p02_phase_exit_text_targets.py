from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

import pytest

from app.services.source_text_alignment import (
    _selection_method,
    align_pages_to_source,
    extract_source_text_evidence,
    text_for_bbox,
)
from tests.benchmarks.corpus_registry import EXPECTED_CASE_IDS
from tests.benchmarks.source_text_alignment_metrics import (
    _canonical_markdown,
    _canonical_text,
    _validate_approved_owner_drift,
    _with_canonical_presentation,
)


WORKSPACE = Path(__file__).resolve().parents[3]
SOURCE_ROOT = WORKSPACE / "benchmark-expertmodeldata"
RETAINED_ROOT = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "p00-us10-corpus-20260729-03"
)

PDF_SHA256 = {
    "catastrophe-recap": (
        "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
    ),
    "clean-energy": (
        "161d513c3ffa53ee3967bac6a7bb420d5d60a2008f79b4f7421b83e9b3a11a7d"
    ),
    "clinical-study": (
        "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2"
    ),
    "component-datasheet": (
        "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4"
    ),
    "egov-survey": (
        "7b6b95d79149c16297c6f7280caed0e14b7dcd53ad5067cb2657885b90562846"
    ),
    "esg-metrics": (
        "6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9"
    ),
    "finance-10k": (
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
    ),
    "health-report": (
        "fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181"
    ),
    "insurance-acord": (
        "85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4"
    ),
    "manufacturing-report": (
        "414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f"
    ),
    "ny-timetable": (
        "f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30"
    ),
    "postal-10k": (
        "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74"
    ),
    "purchase-agreement": (
        "00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14"
    ),
    "settlement-agreement": (
        "adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc"
    ),
    "uber-earnings": (
        "76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5"
    ),
}

APPROVED_ALIGNMENT_CASES = frozenset(
    {
        "clinical-study",
        "esg-metrics",
        "postal-10k",
        "purchase-agreement",
        "settlement-agreement",
    }
)
LEGACY_UNATTRIBUTABLE_OCR_CASES = frozenset({"postal-10k"})
SOURCE_PROVEN_ALIGNMENT_CASES = (
    APPROVED_ALIGNMENT_CASES - LEGACY_UNATTRIBUTABLE_OCR_CASES
)

CLINICAL_METHODS_SENTENCE = (
    "We conducted a 2-arm pragmatic randomized controlled trial."
)
CLINICAL_AUTHOR = (
    "Sebastian Burchert1*, Mhd Salem Alkneme1, Ammar Alsaod1, Pim "
    "Cuijpers2,3, Eva Heim4, Jonas Hessling1, Nadine Hosny4,5, Marit "
    "Sijbrandij2, Edith van’t Hof6, Pieter Ventevogel7, Christine "
    "Knaevelsrud1, on behalf of the STRENGTHS Consortium"
)
CLINICAL_WHODAS_SENTENCE = (
    "of +3% in the HSCL-25 scores (indicating higher psychological "
    "distress) and +2% in the WHODAS scores (indicating lower functioning) "
    "were sufficient to render the results not significant."
)
CLINICAL_TABLE_VALUE = "−0.76 (−2,26, 0.74)"
CLINICAL_FOOTNOTE = (
    "Hedges‘ g effect sizes were derived by combining multiple imputation "
    "estimates using Rubin’s rules."
)
ESG_NOTES = {
    "p1-i8": "3 Energy consumption is in megawatt hours (MWh)",
    "p1-i9": (
        "4 Energy data is revised from prior annual disclosures to reflect "
        "the divestiture of Lehi, Utah, operations."
    ),
    "p1-i10": (
        "5 Beginning with fiscal year 2024, Micron's environmental, health "
        "and safety performance data is reported on a fiscal year basis to "
        "align with emerging regulatory requirements."
    ),
    "p1-i17": (
        "6 Energy consumption in millions of megawatt hours (M MWh)"
    ),
    "p1-i18": (
        "7 Renewable electricity purchased and generated prior to CY22 is "
        "not shown."
    ),
}
PURCHASE_OPENING = (
    "THIS ASSET PURCHASE AGREEMENT (this “Agreement”), dated as of "
    "[June 23_______], 2020 (the “Effective Date”), is by and between The "
    "City of Johnstown, a political subdivision of the Commonwealth of "
    "Pennsylvania operating as a Third Class City under a Home Rule Charter "
    "(the “Seller”), and the Greater Johnstown Water Authority, a body "
    "corporate and politic organized under the Pennsylvania Municipality "
    "Authorities Act (the “Buyer” and together with Seller, the “Parties”)."
)

SUMMARY_KEYS = {
    "schema_version",
    "policy_id",
    "source_sha256",
    "status",
    "considered_count",
    "selected_count",
    "unchanged_count",
    "unresolved_count",
    "selections",
    "concerns",
    "elapsed_ms",
}


@dataclass
class AlignedCase:
    case_id: str
    source_sha256: str
    before_pages: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    public_payload: dict[str, Any]
    evidence: Any
    evidence_dict: dict[str, Any]
    summary: Any
    summary_dict: dict[str, Any]


def _load_retained_payload(case_id: str) -> dict[str, Any]:
    payload = json.loads(
        (RETAINED_ROOT / case_id / "our-output.json").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(payload, dict)
    assert isinstance(payload.get("pages"), list)
    return payload


def _build_aligned_case(case_id: str) -> AlignedCase:
    pdf_bytes = (SOURCE_ROOT / f"{case_id}.pdf").read_bytes()
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    assert source_sha256 == PDF_SHA256[case_id]

    retained_payload = _load_retained_payload(case_id)
    before_pages = deepcopy(retained_payload["pages"])
    pages = deepcopy(before_pages)
    evidence = extract_source_text_evidence(
        pdf_bytes,
        max_pages=len(pages),
    )
    evidence_dict = evidence.to_dict()
    summary = align_pages_to_source(pages, evidence)
    summary_dict = summary.to_dict()

    assert evidence_dict["source_sha256"] == source_sha256
    assert summary_dict["source_sha256"] == source_sha256
    assert set(summary_dict) == SUMMARY_KEYS
    assert summary_dict["selected_count"] == len(
        summary_dict["selections"]
    )
    assert (
        summary_dict["considered_count"]
        == summary_dict["selected_count"]
        + summary_dict["unchanged_count"]
        + summary_dict["unresolved_count"]
    )
    json.dumps(evidence_dict, ensure_ascii=False, sort_keys=True)
    json.dumps(summary_dict, ensure_ascii=False, sort_keys=True)
    public_source = deepcopy(retained_payload)
    public_source["pages"] = deepcopy(pages)
    public_payload = _with_canonical_presentation(
        public_source,
        rebuild=True,
    )

    return AlignedCase(
        case_id=case_id,
        source_sha256=source_sha256,
        before_pages=before_pages,
        pages=pages,
        public_payload=public_payload,
        evidence=evidence,
        evidence_dict=evidence_dict,
        summary=summary,
        summary_dict=summary_dict,
    )


@pytest.fixture(scope="module")
def aligned_corpus() -> dict[str, AlignedCase]:
    assert tuple(PDF_SHA256) == EXPECTED_CASE_IDS
    return {
        case_id: _build_aligned_case(case_id)
        for case_id in EXPECTED_CASE_IDS
    }


def _items(pages: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for page in pages:
        for item in page.get("items") or []:
            if isinstance(item, dict):
                yield item


def _item_by_id(
    pages: list[dict[str, Any]],
    item_id: str,
) -> dict[str, Any]:
    matches = [
        item for item in _items(pages) if item.get("id") == item_id
    ]
    assert len(matches) == 1
    return matches[0]


def _table_rows(item: Mapping[str, Any]) -> list[list[str]]:
    rows = item.get("rows")
    if rows is None:
        rows = item.get("value")
    assert isinstance(rows, list)
    assert all(isinstance(row, list) for row in rows)
    return [
        [str(cell) for cell in row]
        for row in rows
    ]


def _bbox_values(value: Any) -> tuple[float, float, float, float]:
    if isinstance(value, Mapping):
        result = (
            float(value["x"]),
            float(value["y"]),
            float(value.get("width", value.get("w"))),
            float(value.get("height", value.get("h"))),
        )
    else:
        assert isinstance(value, list)
        assert len(value) == 4
        result = tuple(float(part) for part in value)
    assert all(math.isfinite(part) for part in result)
    assert result[2] > 0
    assert result[3] > 0
    return result


def _collect_evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if (
                isinstance(child, str)
                and (key == "id" or key.endswith("_id"))
            ):
                found.add(child)
            found.update(_collect_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_evidence_ids(child))
    return found


def _selection_reference_ids(selection: Mapping[str, Any]) -> set[str]:
    references: set[str] = set()
    for key, value in selection.items():
        if not key.endswith("_ids") or not isinstance(value, list):
            continue
        references.update(
            identifier
            for identifier in value
            if isinstance(identifier, str)
        )
    return references


def _without_elapsed(summary: Mapping[str, Any]) -> dict[str, Any]:
    stable = deepcopy(dict(summary))
    stable.pop("elapsed_ms", None)
    return stable


def _mapping_records(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _mapping_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _mapping_records(child)


def _source_record_id(record: Mapping[str, Any]) -> str:
    for key in ("id", "line_id", "evidence_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    raise AssertionError("source record has no stable evidence identity")


def _reviewed_source_line(
    aligned: AlignedCase,
    exact_text: str,
) -> tuple[Mapping[str, Any], str]:
    matching: dict[str, Mapping[str, Any]] = {}
    for record in _mapping_records(aligned.evidence_dict):
        record_text = record.get("text")
        if not isinstance(record_text, str):
            continue
        prefix = (
            record_text[: -len(exact_text)]
            if record_text.endswith(exact_text)
            else ""
        )
        if record_text != exact_text and not (
            record_text.endswith(exact_text)
            and prefix
            and prefix.isdecimal()
        ):
            continue
        if "bbox" not in record or "page_index" not in record:
            continue
        identifier = _source_record_id(record)
        matching[identifier] = record

    exact = {
        identifier: record
        for identifier, record in matching.items()
        if record.get("text") == exact_text
    }
    assert len(exact) == 1
    identifier, record = next(iter(exact.items()))
    return record, identifier


def _assert_exact_once_or_explicit_unresolved(
    aligned: AlignedCase,
    exact_text: str,
) -> None:
    canonical_count = _canonical_text(aligned.public_payload).count(exact_text)
    markdown_count = _canonical_markdown(aligned.public_payload).count(
        exact_text
    )
    assert canonical_count in {0, 1}
    assert markdown_count == canonical_count
    source_line, source_line_id = _reviewed_source_line(
        aligned,
        exact_text,
    )
    matching_concerns = [
        concern
        for concern in aligned.summary_dict["concerns"]
        if (
            exact_text
            == (
                concern.get("source_text")
                or concern.get("candidate_text")
                or concern.get("target_text")
                or concern.get("selected_text")
            )
            or source_line_id
            in _selection_reference_ids(concern)
        )
    ]

    if canonical_count == 1:
        assert matching_concerns == []
        assert any(
            source_line_id in _selection_reference_ids(selection)
            for selection in aligned.summary_dict["selections"]
        )
        return

    assert len(matching_concerns) == 1
    concern = matching_concerns[0]
    assert concern["status"] == "unresolved"
    assert concern["page_index"] == source_line["page_index"] == 4
    _bbox_values(concern.get("source_bbox") or concern["bbox"])
    assert (
        concern.get("reason") or concern.get("terminal_reason")
    ) == "unrepresented_source_line_near_table"
    references = _selection_reference_ids(concern)
    assert references
    assert source_line_id in references
    assert set(references) <= _collect_evidence_ids(
        aligned.evidence_dict
    )


@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS)
def test_phase_exit_sources_retain_pinned_pdf_hashes(
    case_id: str,
) -> None:
    pdf_bytes = (SOURCE_ROOT / f"{case_id}.pdf").read_bytes()

    assert hashlib.sha256(pdf_bytes).hexdigest() == PDF_SHA256[case_id]


def test_clinical_reviewed_pages_one_and_four_are_source_exact(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["clinical-study"]
    author = str(_item_by_id(aligned.pages, "p1-i16")["value"])
    affiliations = str(
        _item_by_id(aligned.pages, "p1-i17")["value"]
    )
    methods = str(_item_by_id(aligned.pages, "p1-i23")["value"])
    whodas = str(_item_by_id(aligned.pages, "p4-i4")["value"])
    canonical = _canonical_text(aligned.public_payload)

    assert author == CLINICAL_AUTHOR
    assert canonical.count(CLINICAL_AUTHOR) == 1
    author_markdown = _canonical_markdown(aligned.public_payload)
    assert (
        author_markdown.count(CLINICAL_AUTHOR) == 1
        or author_markdown.count(
            CLINICAL_AUTHOR.replace("*", r"\*", 1)
        )
        == 1
    )
    assert "Sebastian BurchertID" not in author
    assert "Pim CuijpersID" not in author
    assert "Nadine HosnyID" not in author
    assert "Edith van’t Hof" in author
    assert "Freie Universität Berlin" in affiliations
    assert "Babeș-Bolyai University" in affiliations
    assert methods.startswith(CLINICAL_METHODS_SENTENCE)
    assert whodas == CLINICAL_WHODAS_SENTENCE
    _assert_exact_once_or_explicit_unresolved(
        aligned,
        CLINICAL_FOOTNOTE,
    )
    assert "Hedges’ g effect sizes" not in canonical
    assert "Weconducted" not in canonical
    assert "WHODASscores" not in canonical
    assert "Universita ¨t" not in canonical
    assert "Babe ș" not in canonical


def test_esg_notes_three_through_seven_are_exact_and_glyph_grounded(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["esg-metrics"]

    for item_id, exact_text in ESG_NOTES.items():
        assert _item_by_id(aligned.pages, item_id)["value"] == exact_text

    canonical = _canonical_text(aligned.public_payload)
    markdown = _canonical_markdown(aligned.public_payload)
    for exact_text in ESG_NOTES.values():
        assert canonical.count(exact_text) == 1
        assert markdown.count(exact_text) == 1
    for damaged in (
        "$ Energy consumption",
        "% Energy data",
        "' Beginning with",
        "( Energy consumption",
        ") Renewable electricity",
        "re&ect",
        "re & ect",
        "#scal",
    ):
        assert damaged not in canonical

    esg_selections = aligned.summary_dict["selections"]
    for item_id, marker in zip(
        ESG_NOTES,
        ("3", "4", "5", "6", "7"),
        strict=True,
    ):
        matching = [
            selection
            for selection in esg_selections
            if str(selection["selected_text"]).startswith(f"{marker} ")
        ]
        assert len(matching) == 1
        selection = matching[0]
        assert selection["method"] == "type1_encoding_differences"
        assert selection["type1_mapping_ids"]
        matching_roles = [
            role
            for role in selection["source_roles"]
            if role["role"] == "superscript" and role["text"] == marker
        ]
        assert len(matching_roles) == 1
        role = matching_roles[0]
        assert set(role) == {
            "role",
            "text",
            "page_index",
            "bbox",
            "source_character_indexes",
            "type1_evidence_ids",
        }
        assert role["page_index"] == 1
        _bbox_values(role["bbox"])
        assert role["source_character_indexes"]
        assert role["type1_evidence_ids"]
        assert (
            role
            in _item_by_id(aligned.pages, item_id)["source_alignment"][
                "source_roles"
            ]
        )

    ligature_roles = [
        role
        for selection in esg_selections
        for role in selection["source_roles"]
        if role["text"] in {"fi", "fl"}
    ]
    assert [role["text"] for role in ligature_roles].count("fl") == 1
    assert [role["text"] for role in ligature_roles].count("fi") == 2
    assert all(
        role["role"] == "ligature" and role["type1_evidence_ids"]
        for role in ligature_roles
    )


def test_purchase_opening_and_date_use_exact_native_characters(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["purchase-agreement"]
    opening = str(_item_by_id(aligned.pages, "p1-i2")["value"])
    canonical = _canonical_text(aligned.public_payload)
    markdown = _canonical_markdown(aligned.public_payload)

    assert opening == PURCHASE_OPENING
    assert canonical.count(PURCHASE_OPENING) == 1
    assert markdown.count(PURCHASE_OPENING) == 1
    assert opening.count("[June 23_______]") == 1
    assert "this ' Agreement '" not in opening
    assert "the ' Effective Date '" not in opening
    assert opening.count("“") == 5
    assert opening.count("”") == 5


def test_purchase_defined_terms_use_exact_paired_source_quotes(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["purchase-agreement"]
    expected_pairs = {"p1-i4": 2, "p1-i5": 3, "p1-i6": 1}
    for owner_id, pair_count in expected_pairs.items():
        value = str(_item_by_id(aligned.pages, owner_id)["value"])
        assert value.count("“") == pair_count
        assert value.count("”") == pair_count
        selection = next(
            selection
            for selection in aligned.summary_dict["selections"]
            if selection["owner_id"] == owner_id
        )
        assert selection["method"] == "pdfium_native_text"
        assert selection["checks"]["paired_source_quotes"] is True
        assert selection["checks"]["unchanged_quote_interiors"] is True


def test_purchase_quote_repair_rejects_unmatched_mixed_and_ambiguous_pairs(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["purchase-agreement"]
    predecessor = _item_by_id(aligned.before_pages, "p1-i6")
    selection = text_for_bbox(
        aligned.evidence,
        1,
        predecessor["bbox"],
    )
    assert selection is not None

    for unsafe in (
        "Defined as ' MS4 System only.",
        "Defined as ' MS4 System \".",
        "Defined as ' MS4 System ' and ' MS4 System ' together.",
        "Defined as ' MS5 System '.",
    ):
        assert _selection_method(aligned.evidence, selection, unsafe) is None


def test_settlement_has_three_semantic_look_back_hyphens(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["settlement-agreement"]
    canonical = _canonical_text(aligned.public_payload)
    markdown = _canonical_markdown(aligned.public_payload)

    assert canonical.count("Look-Back Date") == 3
    assert canonical.count("LookBack Date") == 0
    assert markdown.count("Look-Back Date") == 3
    assert markdown.count("LookBack Date") == 0

    matching = [
        selection
        for selection in aligned.summary_dict["selections"]
        if "Look-Back Date" in str(selection["selected_text"])
    ]
    assert len(matching) == 1
    selection = matching[0]
    assert selection["method"] == "pdfium_semantic_hyphen"
    assert selection["checks"]["pdfium_is_hyphen"] is True
    assert selection["checks"]["same_document_corroboration"] is True
    assert selection["source_character_ids"]


def test_postal_legacy_ocr_without_contributor_fails_closed(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["postal-10k"]
    canonical = _canonical_text(aligned.public_payload)
    markdown = _canonical_markdown(aligned.public_payload)
    table_rows = _table_rows(_item_by_id(aligned.pages, "p1-i3"))

    assert table_rows.count(["CIO", "Chief Information Officer"]) == 1
    assert canonical.count("CIO\tChief Information Officer") == 1
    assert markdown.count("<td>CIO</td>") == 1
    assert markdown.count("<td>Chief Information Officer</td>") == 1
    # The immutable P00 predecessor predates attributable OCR contributors,
    # so source alignment must preserve both legacy items. The dedicated
    # complete-pipeline regression covers contributor-backed ClO removal and
    # table-owned FERS suppression from fresh source bytes.
    assert aligned.pages == aligned.before_pages
    assert aligned.summary_dict["selected_count"] == 0
    assert aligned.summary_dict["selections"] == []
    assert canonical.count("ClO") == 1
    assert markdown.count("ClO") == 1
    assert canonical.count("FERS") == 1
    assert markdown.count("FERS") == 1
    assert table_rows.count(
        ["FERS", "Federal Employees Retirement System"]
    ) == 0
    assert canonical.count("$") == 15
    assert markdown.count("$") == 15


def test_catastrophe_recovery_owner_is_unchanged_by_source_alignment(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["catastrophe-recap"]

    assert aligned.pages == aligned.before_pages
    assert aligned.summary_dict["selected_count"] == 0
    assert aligned.summary_dict["selections"] == []
    assert "É w in Ireland" in _canonical_text(aligned.public_payload)


def test_finance_native_control_has_zero_source_alignment_selections(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus["finance-10k"]

    assert aligned.pages == aligned.before_pages
    assert aligned.summary_dict["selected_count"] == 0
    assert aligned.summary_dict["selections"] == []
    assert "CONSOLIDATED STATEMENTS OF OPERATIONS" in (
        _canonical_text(aligned.public_payload)
    )


def test_clinical_table_repair_updates_every_serialization_atomically(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    table = _item_by_id(
        aligned_corpus["clinical-study"].pages,
        "p4-i2",
    )
    public_payload = aligned_corpus["clinical-study"].public_payload

    assert table["value"][12][6] == CLINICAL_TABLE_VALUE
    assert table["rows"][12][6] == CLINICAL_TABLE_VALUE
    matching_cells = [
        cell
        for cell in table["cells"]
        if cell["row"] == 12 and cell["column"] == 6
    ]
    assert len(matching_cells) == 1
    assert matching_cells[0]["text"] == CLINICAL_TABLE_VALUE

    parsed_csv = list(csv.reader(io.StringIO(table["csv"])))
    assert parsed_csv[12][6] == CLINICAL_TABLE_VALUE
    assert table["html"].count(CLINICAL_TABLE_VALUE) == 1
    assert table["md"].count(CLINICAL_TABLE_VALUE) == 1
    assert _canonical_text(
        public_payload, frozenset({4})
    ).count(CLINICAL_TABLE_VALUE) == 1
    assert _canonical_markdown(
        public_payload, frozenset({4})
    ).count(CLINICAL_TABLE_VALUE) == 1
    for serialization in (
        json.dumps(table["value"], ensure_ascii=False),
        json.dumps(table["rows"], ensure_ascii=False),
        json.dumps(table["cells"], ensure_ascii=False),
        table["csv"],
        table["html"],
        table["md"],
    ):
        assert "- 0.76 ( - 2,26, 0.74)" not in serialization


def test_selected_alignment_trace_is_stable_and_source_provenanced(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    all_selection_ids: set[str] = set()

    for case_id in sorted(SOURCE_PROVEN_ALIGNMENT_CASES):
        aligned = aligned_corpus[case_id]
        evidence_ids = _collect_evidence_ids(aligned.evidence_dict)
        selections = aligned.summary_dict["selections"]
        assert selections

        for selection in selections:
            assert {
                "id",
                "page_index",
                "owner_id",
                "owner_type",
                "owner_bbox",
                "original_text",
                "selected_text",
                "selected_source",
                "source_line_ids",
                "source_character_ids",
                "type1_mapping_ids",
                "method",
                "checks",
                "terminal_reason",
                "rejected_ocr_alternative",
            }.issubset(selection)
            assert selection["id"] not in all_selection_ids
            all_selection_ids.add(selection["id"])
            assert selection["page_index"] >= 1
            assert selection["owner_id"]
            assert selection["owner_type"]
            _bbox_values(selection["owner_bbox"])
            assert selection["original_text"] != selection["selected_text"]
            assert selection["selected_source"]
            assert selection["method"]
            assert selection["terminal_reason"]
            assert selection["checks"]
            assert all(selection["checks"].values())

            references = _selection_reference_ids(selection)
            assert references
            assert references <= evidence_ids


@pytest.mark.parametrize(
    "case_id",
    sorted(APPROVED_ALIGNMENT_CASES),
)
def test_source_alignment_is_deterministic_and_idempotent(
    case_id: str,
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    aligned = aligned_corpus[case_id]

    fresh_pages = deepcopy(aligned.before_pages)
    fresh_summary = align_pages_to_source(
        fresh_pages,
        aligned.evidence,
    ).to_dict()
    assert fresh_pages == aligned.pages
    assert _without_elapsed(fresh_summary) == _without_elapsed(
        aligned.summary_dict
    )

    repeated_pages = deepcopy(aligned.pages)
    repeated_summary = align_pages_to_source(
        repeated_pages,
        aligned.evidence,
    ).to_dict()
    assert repeated_pages == aligned.pages
    assert repeated_summary["selected_count"] == 0
    assert repeated_summary["selections"] == []


def test_all_15_cases_change_only_approved_page_content(
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    assert set(aligned_corpus) == set(EXPECTED_CASE_IDS)

    for case_id in EXPECTED_CASE_IDS:
        aligned = aligned_corpus[case_id]
        assert set(aligned.summary_dict) == SUMMARY_KEYS
        assert _validate_approved_owner_drift(
            case_id,
            aligned.before_pages,
            aligned.pages,
            aligned.summary_dict,
        )["passes"] is True
        if case_id in LEGACY_UNATTRIBUTABLE_OCR_CASES:
            assert aligned.pages == aligned.before_pages
            assert aligned.summary_dict["selected_count"] == 0
            assert aligned.summary_dict["selections"] == []
            continue
        if case_id in APPROVED_ALIGNMENT_CASES:
            assert aligned.summary_dict["selected_count"] > 0
            continue

        assert aligned.pages == aligned.before_pages
        assert aligned.summary_dict["selected_count"] == 0
        assert aligned.summary_dict["selections"] == []


@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS)
def test_public_canonical_and_to_markdown_surfaces_are_the_tested_output(
    case_id: str,
    aligned_corpus: dict[str, AlignedCase],
) -> None:
    from app.services.serializer import to_markdown

    aligned = aligned_corpus[case_id]
    canonical = aligned.public_payload["canonical_presentation"]

    assert to_markdown(aligned.public_payload) == canonical["full"]["markdown"]
    assert _canonical_markdown(aligned.public_payload) == canonical["full"][
        "markdown"
    ]
    assert _canonical_text(aligned.public_payload) == canonical["full"]["text"]
    assert "source_alignment_suppressed" not in json.dumps(
        aligned.public_payload,
        ensure_ascii=False,
    )
