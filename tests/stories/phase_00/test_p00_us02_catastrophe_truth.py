"""P00-US02 source-truth, geometry, custody, and negative controls."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import (
    Annotation,
    MetricUnit,
    TruthClass,
    canonical_json,
)
from tests.benchmarks.source_truth import (
    ArtifactRole,
    CatastropheSourceTruth,
    ChartSeries,
    ElementType,
    NegativeType,
    RelationshipType,
    load_catastrophe_source_truth,
)


WORKSPACE = Path(__file__).resolve().parents[3]
TRUTH_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US02-catastrophe-truth.json"
)
EXPECTED_HASHES = {
    ArtifactRole.SOURCE: "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e",
    ArtifactRole.EXPERT_MARKDOWN: "5104172e1d81eed0a001efaec7bec6f05d32a95f58dc169aacdc5842082069e8",
    ArtifactRole.EXPERT_JSON: "cf0e1b11bd4e44b9ac20725e2bdf51a8301ea9bde173bbf1224c1280511381db",
}
EXPECTED_TRUTH_SHA256 = (
    "d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac"
)
REQUIRED_VISIBLE_TEXT = {
    "AON",
    "Windstorm Éowyn in Ireland and the UK followed with $690 million (€620 million).",
    "EXHIBIT 7: Top 5 Costliest Insured Loss Events in 1H 2025",
    "EXHIBIT 8: 1H Insured Losses by Region (2025 $B)",
    "Data: Aon Catastrophe Insight",
    "1H 2025 Global Catastrophe Recap",
    "7",
}
EXPECTED_TABLE = [
    ["Date(s)", "Event", "Location", "Fatalities", "Insured Loss ($B)"],
    ["01/07-01/28", "Palisades Fire", "United States", "12", "23.0"],
    ["01/07-01/28", "Eaton Fire", "United States", "18", "17.5"],
    [
        "03/14-03/16",
        "Severe Convective Storm",
        "United States",
        "43",
        "8.0",
    ],
    [
        "05/14-05/16",
        "Severe Convective Storm",
        "United States",
        "30",
        "8.0",
    ],
    [
        "05/17-05/20",
        "Severe Convective Storm",
        "United States",
        "0",
        "4.0",
    ],
]


def _payload() -> dict[str, object]:
    return json.loads(TRUTH_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_truth_bundle_validates_and_round_trips_deterministically() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)

    assert _sha256(TRUTH_PATH) == EXPECTED_TRUTH_SHA256
    serialized = canonical_json(truth)
    reloaded = CatastropheSourceTruth.model_validate_json(serialized)

    assert canonical_json(reloaded) == serialized
    assert reloaded.schema_version == "1.0"
    assert reloaded.fixture.fixture_id == "catastrophe-recap"
    assert reloaded.fixture.custody == "public-redistributable"
    assert reloaded.source_use_decision.record_status == "approved"
    assert reloaded.source_use_decision.evidence_path.endswith(
        "P00-US02-source-rights.md"
    )
    assert set(reloaded.source_use_decision.permitted_uses) == {
        "workspace_retention",
        "repository_commit",
        "benchmark_redistribution",
        "local_validation",
        "private_ci_validation",
        "committed_ci_validation",
    }


def test_narrowed_or_nonportable_source_use_decision_is_rejected() -> None:
    decision = _payload()["source_use_decision"]  # type: ignore[index]
    assert "truth_class" not in decision
    assert "physical_page" not in decision
    assert "include_in_exact_parity" not in decision

    narrowed = _payload()
    narrowed["source_use_decision"]["permitted_uses"] = [  # type: ignore[index]
        "workspace_retention"
    ]
    with pytest.raises(ValidationError, match="every approved use"):
        CatastropheSourceTruth.model_validate(narrowed)

    traversal = _payload()
    traversal["source_use_decision"]["evidence_path"] = (  # type: ignore[index]
        "../../P00-US02-source-rights.md"
    )
    with pytest.raises(ValidationError, match="portable evidence path"):
        CatastropheSourceTruth.model_validate(traversal)

    wrong_fixture = _payload()
    wrong_fixture["source_use_decision"]["fixture_id"] = "other-fixture"  # type: ignore[index]
    with pytest.raises(ValidationError, match="registered fixture"):
        CatastropheSourceTruth.model_validate(wrong_fixture)


def test_registered_triplet_hashes_and_sizes_match_current_immutable_bytes() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)

    assert {artifact.role for artifact in truth.artifacts} == set(ArtifactRole)
    for artifact in truth.artifacts:
        path = WORKSPACE / artifact.path
        assert path.is_file()
        assert path.stat().st_size == artifact.size_bytes
        assert artifact.sha256 == EXPECTED_HASHES[artifact.role]
        assert _sha256(path) == artifact.sha256


def test_altered_artifact_bytes_do_not_match_registered_hash(
    tmp_path: Path,
) -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    source = next(
        artifact
        for artifact in truth.artifacts
        if artifact.role is ArtifactRole.SOURCE
    )
    altered = tmp_path / "catastrophe-recap.pdf"
    altered.write_bytes((WORKSPACE / source.path).read_bytes() + b"altered")

    assert _sha256(altered) != source.sha256


def test_missing_or_colliding_artifacts_are_rejected() -> None:
    missing = _payload()
    missing["artifacts"] = missing["artifacts"][:-1]  # type: ignore[index]
    with pytest.raises(ValidationError, match="at least 3"):
        CatastropheSourceTruth.model_validate(missing)

    collision = _payload()
    artifacts = collision["artifacts"]  # type: ignore[assignment]
    artifacts[1]["sha256"] = artifacts[0]["sha256"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="must not collide"):
        CatastropheSourceTruth.model_validate(collision)


def test_page_identity_visible_truth_bboxes_and_reading_order_are_explicit() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    elements = {element.annotation_id: element for element in truth.elements}

    assert truth.fixture.source_format == "PDF"
    assert truth.page.physical_page == 1
    assert truth.page.printed_page_label == "7"
    assert (truth.page.width_pt, truth.page.height_pt) == (612.0, 792.0)
    assert truth.page.coordinate_origin == "top-left"
    assert truth.page.coordinate_unit == "pt"
    assert [element.reading_order for element in truth.elements] == list(
        range(len(truth.elements))
    )
    assert REQUIRED_VISIBLE_TEXT <= {element.text for element in truth.elements}

    for element in truth.elements:
        assert element.physical_page == 1
        assert element.bbox.unit == "pt"
        assert element.bbox.right <= truth.page.width_pt
        assert element.bbox.bottom <= truth.page.height_pt
        projected = element.annotation_contract()
        assert isinstance(projected, Annotation)

    assert elements["element-logo-aon"].element_type is ElementType.LOGO
    assert elements["element-exhibit-7-title"].element_type is ElementType.CAPTION
    assert elements["element-exhibit-8-title"].element_type is ElementType.CAPTION
    assert (
        elements["element-chart-source-note"].element_type
        is ElementType.SOURCE_NOTE
    )
    assert elements["element-printed-page-label"].text == "7"


def test_changed_source_format_or_page_rotation_is_rejected() -> None:
    wrong_format = _payload()
    wrong_format["fixture"]["source_format"] = "DOCX"  # type: ignore[index]
    with pytest.raises(ValidationError, match="source format must remain PDF"):
        CatastropheSourceTruth.model_validate(wrong_format)

    rotated = _payload()
    rotated["page"]["rotation"] = 90  # type: ignore[index]
    with pytest.raises(ValidationError, match="coordinate space.*reviewed PDF"):
        CatastropheSourceTruth.model_validate(rotated)


def test_changed_element_identity_or_visible_text_is_rejected() -> None:
    swapped_titles = _payload()
    elements = {
        element["element_id"]: element
        for element in swapped_titles["elements"]  # type: ignore[union-attr]
    }
    elements["exhibit-7-title"]["text"], elements["exhibit-8-title"]["text"] = (
        elements["exhibit-8-title"]["text"],
        elements["exhibit-7-title"]["text"],
    )

    with pytest.raises(ValidationError, match="element IDs, types, and text"):
        CatastropheSourceTruth.model_validate(swapped_titles)

    reordered = _payload()
    elements_list = reordered["elements"]  # type: ignore[assignment]
    elements_list.insert(0, elements_list.pop(9))
    for reading_order, element in enumerate(elements_list):
        element["reading_order"] = reading_order
    with pytest.raises(ValidationError, match="reading order must match"):
        CatastropheSourceTruth.model_validate(reordered)


def test_changed_element_geometry_or_definition_link_is_rejected() -> None:
    swapped_title_bboxes = _payload()
    elements = {
        element["element_id"]: element
        for element in swapped_title_bboxes["elements"]  # type: ignore[union-attr]
    }
    (
        elements["exhibit-7-title"]["bbox"],
        elements["exhibit-8-title"]["bbox"],
    ) = (
        elements["exhibit-8-title"]["bbox"],
        elements["exhibit-7-title"]["bbox"],
    )
    with pytest.raises(ValidationError, match="top-to-bottom order"):
        CatastropheSourceTruth.model_validate(swapped_title_bboxes)

    detached_table = _payload()
    table_element = next(
        element
        for element in detached_table["elements"]  # type: ignore[union-attr]
        if element["element_id"] == "exhibit-7-table"
    )
    table_element["bbox"] = [99.71, 231.04, 1, 1]
    with pytest.raises(ValidationError, match="match its table definition"):
        CatastropheSourceTruth.model_validate(detached_table)


def test_required_relationships_and_order_edges_are_cross_referenced() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    relationships = {
        (
            relationship.relationship_type,
            relationship.source_id,
            relationship.target_id,
        )
        for relationship in truth.relationships
    }

    assert relationships == {
        (
            RelationshipType.CONTAINS,
            "intro-paragraph",
            "damaged-sentence",
        ),
        (
            RelationshipType.CAPTION_OF,
            "exhibit-7-title",
            "exhibit-7-table",
        ),
        (
            RelationshipType.CAPTION_OF,
            "exhibit-8-title",
            "exhibit-8-chart",
        ),
        (
            RelationshipType.SOURCE_NOTE_OF,
            "chart-source-note",
            "exhibit-8-chart",
        ),
        (
            RelationshipType.FOOTER_PAIR,
            "footer-title",
            "printed-page-label",
        ),
    }


def test_changed_relationship_semantics_are_rejected() -> None:
    payload = _payload()
    payload["relationships"][0]["relationship_type"] = "caption_for"  # type: ignore[index]

    with pytest.raises(ValidationError, match="five source-reviewed relationships"):
        CatastropheSourceTruth.model_validate(payload)


def test_dangling_relationship_and_out_of_page_bbox_are_rejected() -> None:
    dangling = _payload()
    dangling["relationships"][0]["target_id"] = "missing"  # type: ignore[index]
    with pytest.raises(ValidationError, match="target_id"):
        CatastropheSourceTruth.model_validate(dangling)

    outside = _payload()
    outside["elements"][0]["bbox"][0] = 611  # type: ignore[index]
    outside["elements"][0]["bbox"][2] = 2  # type: ignore[index]
    with pytest.raises(ValidationError, match="outside the page"):
        CatastropheSourceTruth.model_validate(outside)


def test_exhibit7_has_30_explicit_unspanned_source_cells() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    cells = {(cell.row, cell.column): cell for cell in truth.table_cells}
    matrix = [
        [cells[(row, column)].text for column in range(truth.table.columns)]
        for row in range(truth.table.rows)
    ]

    assert len(truth.table_cells) == 30
    assert matrix == EXPECTED_TABLE
    assert all(cell.row_span == cell.column_span == 1 for cell in truth.table_cells)
    assert sum(cell.text == "United States" for cell in truth.table_cells) == 5
    assert all(
        cell.truth_class in {TruthClass.VISIBLE_TEXT, TruthClass.NATIVE_DATA}
        and cell.include_in_exact_parity
        for cell in truth.table_cells
    )


def test_false_row_span_is_rejected() -> None:
    payload = _payload()
    location = next(
        cell
        for cell in payload["table_cells"]  # type: ignore[union-attr]
        if cell["row"] == 1 and cell["column"] == 2
    )
    location["row_span"] = 5

    with pytest.raises(ValidationError, match="overlap|fabricated span"):
        CatastropheSourceTruth.model_validate(payload)


def test_changed_table_cell_grid_association_is_rejected() -> None:
    swapped_cells = _payload()
    first = next(
        cell
        for cell in swapped_cells["table_cells"]  # type: ignore[union-attr]
        if cell["row"] == 0 and cell["column"] == 0
    )
    last = next(
        cell
        for cell in swapped_cells["table_cells"]  # type: ignore[union-attr]
        if cell["row"] == 5 and cell["column"] == 4
    )
    first["bbox"], last["bbox"] = last["bbox"], first["bbox"]

    with pytest.raises(ValidationError, match="declared grid slot"):
        CatastropheSourceTruth.model_validate(swapped_cells)


def test_chart_has_23_literal_labels_and_88_linked_measured_values() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    calibration = truth.chart_calibration
    points = {
        (point.panel, point.year, point.series): point
        for point in truth.chart_measurements
    }

    assert len(truth.chart_labels) == 23
    assert all(
        label.truth_class is TruthClass.VISIBLE_TEXT
        and label.include_in_exact_parity
        for label in truth.chart_labels
    )
    assert len(points) == 88
    assert calibration.unit is MetricUnit.BILLIONS_2025_USD
    assert calibration.tolerance == 1.0
    assert calibration.points_per_usd_billion == pytest.approx(0.822964)
    assert calibration.coordinate_quantization_pt == pytest.approx(0.401614)

    for point in points.values():
        metric = point.metric_contract()
        assert point.truth_class is TruthClass.MEASURED
        assert not point.include_in_exact_parity
        assert metric.fixture_id == truth.fixture.fixture_id
        assert metric.annotation_id == point.annotation_id
        assert metric.measurement_method == calibration.measurement_method
        assert metric.unit is MetricUnit.BILLIONS_2025_USD
        assert metric.tolerance == calibration.tolerance
        geometry_value = (
            calibration.baseline_y_pt - point.source_bbox.y
        ) / calibration.points_per_usd_billion
        assert point.value == pytest.approx(geometry_value, abs=0.5)

    assert points[("Americas", 2017, ChartSeries.ANNUAL_TOTAL)].value == 54.17
    assert points[("USA", 2022, ChartSeries.ANNUAL_TOTAL)].value == 118.10
    assert points[("USA", 2025, ChartSeries.FIRST_HALF)].value == 91.75
    for panel in ("Americas", "APAC", "EMEA", "USA"):
        for year in range(2015, 2026):
            assert (
                points[(panel, year, ChartSeries.ANNUAL_TOTAL)].value
                >= points[(panel, year, ChartSeries.FIRST_HALF)].value
            )


def test_changed_chart_label_value_or_axis_calibration_is_rejected() -> None:
    changed_label = _payload()
    changed_label["chart_labels"][0]["text"] = "WRONG LABEL"  # type: ignore[index]
    with pytest.raises(ValidationError, match="23 printed chart labels"):
        CatastropheSourceTruth.model_validate(changed_label)

    changed_value = _payload()
    changed_value["chart_measurements"][0]["value"] = 123  # type: ignore[index]
    with pytest.raises(ValidationError, match="raw vector geometry"):
        CatastropheSourceTruth.model_validate(changed_value)

    collapsed_ticks = _payload()
    for tick in collapsed_ticks["chart_calibration"]["tick_positions"]:  # type: ignore[index]
        tick["y_pt"] = 500
    with pytest.raises(ValidationError, match="positions must decrease|linear axis"):
        CatastropheSourceTruth.model_validate(collapsed_ticks)


def test_changed_chart_label_geometry_or_measurement_identity_is_rejected() -> None:
    swapped_anchors = _payload()
    anchors = {
        (label["panel"], label["text"]): label
        for label in swapped_anchors["chart_labels"]  # type: ignore[union-attr]
        if label["label_type"] == "year_anchor"
    }
    (
        anchors[("APAC", "2015")]["bbox"],
        anchors[("APAC", "2025")]["bbox"],
    ) = (
        anchors[("APAC", "2025")]["bbox"],
        anchors[("APAC", "2015")]["bbox"],
    )
    with pytest.raises(ValidationError, match="year anchors.*x order"):
        CatastropheSourceTruth.model_validate(swapped_anchors)

    duplicate_ids = _payload()
    for point in duplicate_ids["chart_measurements"]:  # type: ignore[index]
        point["measurement_id"] = "duplicate"
    with pytest.raises(ValidationError, match="measurement IDs must match"):
        CatastropheSourceTruth.model_validate(duplicate_ids)


def test_changed_chart_year_to_x_association_is_rejected() -> None:
    swapped_years = _payload()
    measurements = swapped_years["chart_measurements"]  # type: ignore[assignment]
    for point in measurements:
        if point["panel"] == "APAC" and point["year"] in {2018, 2019}:
            point["year"] = 2019 if point["year"] == 2018 else 2018
            series_slug = (
                "1h" if point["series"] == "1H" else "annual-total"
            )
            suffix = f"apac-{point['year']}-{series_slug}"
            point["measurement_id"] = f"measurement-{suffix}"
            point["annotation_id"] = f"chart-measurement-{suffix}"

    with pytest.raises(ValidationError, match="left-to-right"):
        CatastropheSourceTruth.model_validate(swapped_years)


def test_invalid_tolerance_annual_below_1h_and_exact_promotion_are_rejected() -> None:
    invalid_tolerance = _payload()
    invalid_tolerance["chart_measurements"][0]["tolerance"] = -1  # type: ignore[index]
    with pytest.raises(ValidationError, match="greater than 0"):
        CatastropheSourceTruth.model_validate(invalid_tolerance)

    annual_below = _payload()
    measurements = annual_below["chart_measurements"]  # type: ignore[assignment]
    target = next(
        point
        for point in measurements
        if point["panel"] == "USA"
        and point["year"] == 2025
        and point["series"] == "annual_total"
    )
    target["value"] = 1
    baseline = annual_below["chart_calibration"]["baseline_y_pt"]  # type: ignore[index]
    scale = annual_below["chart_calibration"]["points_per_usd_billion"]  # type: ignore[index]
    target["raw_mark_bbox"][1] = baseline - scale
    target["raw_mark_bbox"][3] = scale
    with pytest.raises(ValidationError, match="annual total cannot be below 1H"):
        CatastropheSourceTruth.model_validate(annual_below)

    exact_measured = _payload()
    exact_measured["chart_measurements"][0]["include_in_exact_parity"] = True  # type: ignore[index]
    with pytest.raises(ValidationError, match="cannot enter exact parity"):
        CatastropheSourceTruth.model_validate(exact_measured)


def test_duplicate_canonical_title_is_rejected() -> None:
    payload = _payload()
    duplicate = deepcopy(
        next(
            element
            for element in payload["elements"]  # type: ignore[union-attr]
            if element["annotation_id"] == "element-exhibit-8-title"
        )
    )
    duplicate["annotation_id"] = "synthetic-duplicate-exhibit8-title"
    duplicate["element_id"] = "synthetic-duplicate-exhibit8-title"
    duplicate["reading_order"] = len(payload["elements"])  # type: ignore[arg-type]
    payload["elements"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(ValidationError, match="titles must not be duplicated"):
        CatastropheSourceTruth.model_validate(payload)


def test_required_negative_annotations_are_explicit_and_never_literal_truth() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)

    assert {
        annotation.negative_type for annotation in truth.negative_annotations
    } == set(NegativeType)
    assert all(
        not annotation.include_in_exact_parity
        for annotation in truth.negative_annotations
    )
    assert any(
        annotation.negative_type is NegativeType.UNSUPPORTED_EXACT_VALUE
        and annotation.truth_class is TruthClass.UNKNOWABLE
        for annotation in truth.negative_annotations
    )


def test_changed_negative_truth_class_or_inferred_year_count_is_rejected() -> None:
    literal_negative = _payload()
    literal_negative["negative_annotations"][0]["truth_class"] = "visible_text"  # type: ignore[index]
    with pytest.raises(ValidationError, match="nonliteral truth classes"):
        CatastropheSourceTruth.model_validate(literal_negative)

    missing_assignments = _payload()
    missing_assignments["chart_calibration"]["intermediate_year_assignments"][  # type: ignore[index]
        "count"
    ] = 0
    with pytest.raises(ValidationError, match="32 inferred intermediate years"):
        CatastropheSourceTruth.model_validate(missing_assignments)

    nonsense_mutations = _payload()
    for annotation in nonsense_mutations["negative_annotations"]:  # type: ignore[index]
        annotation["mutation"] = {"nonsense": True}
    with pytest.raises(ValidationError, match="executable mutation evidence"):
        CatastropheSourceTruth.model_validate(nonsense_mutations)


def test_changed_review_status_or_evidence_classes_are_rejected() -> None:
    unverified = _payload()
    unverified["elements"][0]["review_status"] = "approved"  # type: ignore[index]
    with pytest.raises(ValidationError, match="verified"):
        CatastropheSourceTruth.model_validate(unverified)

    literal_relationships = _payload()
    for relationship in literal_relationships["relationships"]:  # type: ignore[index]
        relationship["truth_class"] = "visible_text"
    with pytest.raises(ValidationError, match="inferred and non-exact"):
        CatastropheSourceTruth.model_validate(literal_relationships)

    native_calibration = _payload()
    native_calibration["chart_calibration"]["truth_class"] = "native_data"  # type: ignore[index]
    with pytest.raises(ValidationError, match="measured and non-exact"):
        CatastropheSourceTruth.model_validate(native_calibration)

    literal_chart = _payload()
    chart = next(
        element
        for element in literal_chart["elements"]  # type: ignore[union-attr]
        if element["element_id"] == "exhibit-8-chart"
    )
    chart["truth_class"] = "visible_text"
    with pytest.raises(ValidationError, match="truth and parity classes"):
        CatastropheSourceTruth.model_validate(literal_chart)
