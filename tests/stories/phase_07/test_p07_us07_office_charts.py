"""Release-first coverage for native Office chart evidence."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from xml.sax.saxutils import escape

from app.models import ParseResult
from app.services.office_charts import apply_office_charts, extract_office_chart
from app.services.ooxml_intake import intake_ooxml
from app.services.pptx_adapter import parse_pptx
from app.services.serializer import to_markdown, to_text
from app.services.xlsx_adapter import XLSX_MIME_TYPE, parse_xlsx
from tests.stories.phase_07.office_fixture_helpers import (
    DOC_REL_NS,
    pptx_fixture,
    relationships,
    unzip_package,
    xlsx_entries,
    zip_package,
)


def _cache(kind: str, values: list[str]) -> str:
    points = "".join(
        f'<c:pt idx="{index}"><c:v>{escape(value)}</c:v></c:pt>'
        for index, value in enumerate(values)
    )
    return f"<c:{kind}><c:ptCount val=\"{len(values)}\"/>{points}</c:{kind}>"


def _literal(kind: str, values: list[str], *, reverse_nodes: bool = False) -> str:
    indexed = list(enumerate(values))
    if reverse_nodes:
        indexed.reverse()
    points = "".join(
        f'<c:pt idx="{index}"><c:v>{escape(value)}</c:v></c:pt>'
        for index, value in indexed
    )
    return f"<c:{kind}><c:ptCount val=\"{len(values)}\"/>{points}</c:{kind}>"


def _chart_xml(
    *,
    chart_type: str = "barChart",
    value_formula: str = "Summary!$B$2:$B$3",
    value_cache: tuple[str, ...] = ("10", "10"),
    literal_data: bool = False,
) -> bytes:
    categories = ("East", "Total")
    if literal_data:
        # CT_SerTx uses a direct c:v for a literal series name; strLit/numLit
        # are indexed data vectors for category/value sources.
        series_source = "<c:v>Revenue</c:v>"
        category_source = _literal(
            "strLit",
            list(categories),
            reverse_nodes=True,
        )
        value_source = _literal(
            "numLit",
            list(value_cache),
            reverse_nodes=True,
        )
    else:
        series_source = (
            f"<c:strRef><c:f>Summary!$B$1</c:f>"
            f'{_cache("strCache", ["Revenue"])}</c:strRef>'
        )
        category_source = (
            f"<c:strRef><c:f>Summary!$A$2:$A$3</c:f>"
            f'{_cache("strCache", list(categories))}</c:strRef>'
        )
        value_source = (
            f"<c:numRef><c:f>{escape(value_formula)}</c:f>"
            f'{_cache("numCache", list(value_cache))}</c:numRef>'
        )
    return f"""<c:chartSpace xmlns:c="urn:chart" xmlns:a="urn:drawing">
      <c:chart>
        <c:title><c:tx><c:rich><a:p><a:r><a:t>Revenue by region</a:t></a:r></a:p></c:rich></c:tx></c:title>
        <c:plotArea>
          <c:{chart_type}>
            <c:ser>
              <c:idx val="0"/><c:order val="0"/>
              <c:tx>{series_source}</c:tx>
              <c:cat>{category_source}</c:cat>
              <c:val>{value_source}</c:val>
            </c:ser>
          </c:{chart_type}>
          <c:catAx><c:title><c:tx><c:rich><a:p><a:r><a:t>Region</a:t></a:r></a:p></c:rich></c:tx></c:title></c:catAx>
          <c:valAx><c:title><c:tx><c:rich><a:p><a:r><a:t>Revenue</a:t></a:r></a:p></c:rich></c:tx></c:title></c:valAx>
        </c:plotArea>
        <c:legend/>
      </c:chart>
    </c:chartSpace>""".encode()


def _xlsx_chart_entries(
    *,
    chart_type: str = "barChart",
    value_formula: str = "Summary!$B$2:$B$3",
    value_cache: tuple[str, ...] = ("10", "10"),
    external_relationship: bool = False,
) -> dict[str, bytes]:
    entries = xlsx_entries()
    entries["xl/charts/chart1.xml"] = _chart_xml(
        chart_type=chart_type,
        value_formula=value_formula,
        value_cache=value_cache,
    )
    if external_relationship:
        entries["xl/charts/_rels/chart1.xml.rels"] = relationships(
            [
                (
                    "rIdExternal",
                    f"{DOC_REL_NS}/externalLinkPath",
                    "https://must-not-fetch.invalid/external.xlsx",
                    "External",
                )
            ]
        )
    return entries


class _TrackingPackage:
    def __init__(self, entries: Mapping[str, bytes]) -> None:
        self._entries = dict(entries)
        self.part_names = tuple(sorted(self._entries))
        self.reads: list[str] = []

    def read_part(self, name: str) -> bytes:
        self.reads.append(name)
        return self._entries[name]


def test_xlsx_cell_backed_chart_reaches_structured_output_and_markdown() -> None:
    package = zip_package(_xlsx_chart_entries())
    predecessor = parse_xlsx(package, filename="revenue.xlsx")

    output = apply_office_charts(predecessor, package, enabled=True)
    result = ParseResult.model_validate(output)
    item = output["pages"][0]["items"][1]
    chart = item["office_chart"]

    assert item["type"] == "chart"
    assert item["content_type"] == "chart"
    assert item["placeholder"] is False
    assert chart["status"] == "structured"
    assert chart["chart_type"] == "barChart"
    assert chart["title"] == "Revenue by region"
    assert chart["axes"] == ["Region", "Revenue"]
    assert chart["legend"] == ["Revenue"]
    assert chart["categories"] == ["East", "Total"]
    assert chart["series"] == ["Revenue"]
    assert [point["value"] for point in chart["points"]] == [10.0, 10.0]
    assert all(point["method"] == "cell_data" for point in chart["points"])
    assert chart["points"][0]["source_locator"] == "Summary!B2"
    assert "| East | Revenue | 10 | cell_data |" in chart["markdown"]
    assert chart["markdown"] in to_markdown(result)
    assert "East\tRevenue\t10\tcell_data" in to_text(result)
    assert chart["provenance"]["validation_contract"] == (
        "p05-chart-validation-v1"
    )
    assert item["parse_concerns"] == []

    # OPC permits the validated officeDocument target to live outside the
    # conventional xl/ root. Chart traversal and cell precedence must follow
    # relationships from that main part, not infer package prefixes.
    renamed_entries = {
        (f"book/{name.removeprefix('xl/')}" if name.startswith("xl/") else name): value
        for name, value in _xlsx_chart_entries(
            value_cache=("999", "1000")
        ).items()
    }
    renamed_entries["_rels/.rels"] = renamed_entries["_rels/.rels"].replace(
        b"xl/workbook.xml",
        b"book/workbook.xml",
    )
    renamed_entries["[Content_Types].xml"] = renamed_entries[
        "[Content_Types].xml"
    ].replace(b"/xl/", b"/book/")
    renamed_package = intake_ooxml(
        zip_package(renamed_entries),
        "renamed.xlsx",
        XLSX_MIME_TYPE,
    )
    renamed_predecessor = parse_xlsx(renamed_package, filename="renamed.xlsx")
    renamed_output = apply_office_charts(
        renamed_predecessor,
        renamed_package,
        enabled=True,
    )
    renamed_item = renamed_output["pages"][0]["items"][1]
    renamed_chart = renamed_item["office_chart"]
    assert renamed_package.manifest.main_part == "book/workbook.xml"
    assert renamed_output["processing"]["office_charts"]["chart_part_count"] == 1
    assert renamed_item["chart_part"] == "book/charts/chart1.xml"
    assert [point["value"] for point in renamed_chart["points"]] == [10.0, 10.0]
    assert all(point["method"] == "cell_data" for point in renamed_chart["points"])
    assert renamed_item["parse_concerns"] == ["office_chart_cache_conflict"]
    assert ParseResult.model_validate(renamed_output)

    # One worksheet drawing may own several independent chart frames. The
    # native adapter deliberately emits one drawing placeholder, so US07 must
    # expand it into one grounded public item per relationship without loss.
    multi_entries = _xlsx_chart_entries()
    multi_entries["xl/charts/chart2.xml"] = _chart_xml().replace(
        b"Revenue by region",
        b"Revenue copy",
    )
    multi_entries["xl/drawings/_rels/drawing1.xml.rels"] = relationships(
        [
            ("rIdChart1", f"{DOC_REL_NS}/chart", "../charts/chart1.xml", None),
            ("rIdChart2", f"{DOC_REL_NS}/chart", "../charts/chart2.xml", None),
        ]
    )
    multi_package = zip_package(multi_entries)
    multi_output = apply_office_charts(
        parse_xlsx(multi_package),
        multi_package,
        enabled=True,
    )
    multi_charts = [
        item
        for item in multi_output["pages"][0]["items"]
        if item.get("office_chart") is not None
    ]
    assert [item["chart_part"] for item in multi_charts] == [
        "xl/charts/chart1.xml",
        "xl/charts/chart2.xml",
    ]
    assert len({item["id"] for item in multi_charts}) == 2
    assert [
        item["reading_order"] for item in multi_output["pages"][0]["items"]
    ] == list(range(len(multi_output["pages"][0]["items"])))
    assert multi_charts[1]["native_provenance"]["resolved_part"] == (
        "xl/charts/chart2.xml"
    )
    assert multi_output["processing"]["office_charts"] == {
        "schema_version": "1.0",
        "status": "completed",
        "chart_part_count": 2,
        "structured_chart_count": 2,
        "placeholder_chart_count": 0,
        "native_data_preferred": True,
        "formulas_executed": False,
        "external_content_fetched": False,
    }
    assert ParseResult.model_validate(multi_output)


def test_native_cells_outrank_conflicting_chart_cache_with_concern() -> None:
    entries = _xlsx_chart_entries(value_cache=("999", "1000"))
    entries["xl/sharedStrings.xml"] = entries["xl/sharedStrings.xml"].replace(
        b"<si><t>Revenue</t></si>",
        b"<si><t>Native Revenue</t></si>",
    )
    entries["xl/worksheets/sheet1.xml"] = entries[
        "xl/worksheets/sheet1.xml"
    ].replace(b"<t>East</t>", b"<t>Native East</t>").replace(
        b"<t>Total</t>",
        b"<t>Native Total</t>",
    )
    extraction = extract_office_chart(
        entries,
        "xl/charts/chart1.xml",
        input_format="xlsx",
    )

    assert extraction.status == "structured"
    assert extraction.concern_codes == ["office_chart_cache_conflict"]
    assert extraction.structure is not None
    assert extraction.structure.series == ["Native Revenue"]
    assert extraction.structure.legend == ["Native Revenue"]
    assert extraction.structure.categories == ["Native East", "Native Total"]
    assert [point.value for point in extraction.structure.points] == [10.0, 10.0]
    assert [point.cache_value for point in extraction.structure.points] == [999.0, 1000.0]
    assert all(point.method == "cell_data" for point in extraction.structure.points)
    assert all(point.conflict is True for point in extraction.structure.points)
    assert extraction.structure.provenance["source_precedence"][0] == "cell_data"

    duplicate_entries = _xlsx_chart_entries()
    duplicate_entries["xl/worksheets/sheet1.xml"] = duplicate_entries[
        "xl/worksheets/sheet1.xml"
    ].replace(b"<t>Total</t>", b"<t>East</t>")
    duplicate = extract_office_chart(
        duplicate_entries,
        "xl/charts/chart1.xml",
        input_format="xlsx",
    )
    assert duplicate.status == "structured"
    assert duplicate.structure is not None
    assert duplicate.structure.categories == ["East", "East"]
    assert [point.category for point in duplicate.structure.points] == [
        "East",
        "East",
    ]
    assert duplicate.concern_codes == ["office_chart_cache_conflict"]

    literal_entries = {
        "xl/charts/chart1.xml": _chart_xml(
            value_cache=("10", "20"),
            literal_data=True,
        )
    }
    literal = extract_office_chart(
        literal_entries,
        "xl/charts/chart1.xml",
        input_format="xlsx",
    )
    assert literal.status == "structured"
    assert literal.concern_codes == []
    assert literal.structure is not None
    assert literal.structure.series == ["Revenue"]
    assert literal.structure.categories == ["East", "Total"]
    assert [point.value for point in literal.structure.points] == [10.0, 20.0]
    assert all(point.method == "cached_data" for point in literal.structure.points)
    assert all(point.cache_value is None for point in literal.structure.points)
    assert [point.source_locator for point in literal.structure.points] == [
        "xl/charts/chart1.xml#literal[0]",
        "xl/charts/chart1.xml#literal[1]",
    ]
    assert literal.structure.provenance["chart_local_data_sources"] == [
        "literal_data"
    ]

    overlong_literal_entries = dict(literal_entries)
    overlong_literal_entries["xl/charts/chart1.xml"] = literal_entries[
        "xl/charts/chart1.xml"
    ].replace(
        b"<c:tx><c:v>Revenue</c:v></c:tx>",
        b"<c:tx><c:v>" + b"R" * 1_025 + b"</c:v></c:tx>",
        1,
    )
    overlong_literal = extract_office_chart(
        overlong_literal_entries,
        "xl/charts/chart1.xml",
        input_format="xlsx",
    )
    assert overlong_literal.status == "placeholder"
    assert overlong_literal.concern_codes == ["office_chart_data_invalid"]

    invalid_literal_entries = dict(literal_entries)
    invalid_literal_entries["xl/charts/chart1.xml"] = literal_entries[
        "xl/charts/chart1.xml"
    ].replace(
        b'<c:strLit><c:ptCount val="2"/><c:pt idx="1"><c:v>Total</c:v></c:pt><c:pt idx="0"><c:v>East</c:v></c:pt></c:strLit>',
        b'<c:strLit><c:ptCount val="2"/><c:pt idx="1"><c:v>Total</c:v></c:pt><c:pt idx="1"><c:v>East</c:v></c:pt></c:strLit>',
        1,
    )
    invalid_literal = extract_office_chart(
        invalid_literal_entries,
        "xl/charts/chart1.xml",
        input_format="xlsx",
    )
    assert invalid_literal.status == "placeholder"
    assert invalid_literal.concern_codes == ["office_chart_data_invalid"]


def test_external_chart_reference_is_retained_but_never_fetched_or_executed() -> None:
    formula = "[external.xlsx]Summary!$B$2:$B$3"
    package = _TrackingPackage(
        _xlsx_chart_entries(
            value_formula=formula,
            value_cache=("77", "88"),
            external_relationship=True,
        )
    )

    extraction = extract_office_chart(
        package,
        "xl/charts/chart1.xml",
        input_format="xlsx",
    )

    assert extraction.status == "structured"
    assert extraction.concern_codes == ["office_chart_external_reference_not_fetched"]
    assert extraction.structure is not None
    assert [point.value for point in extraction.structure.points] == [77.0, 88.0]
    assert all(point.method == "cached_data" for point in extraction.structure.points)
    assert all(point.formula == formula for point in extraction.structure.points)
    assert extraction.structure.provenance["external_content_fetched"] is False
    assert extraction.structure.provenance["formulas_executed"] is False
    assert "https://must-not-fetch.invalid/external.xlsx" not in package.reads


def test_unsupported_native_chart_remains_a_placeholder() -> None:
    extraction = extract_office_chart(
        _xlsx_chart_entries(chart_type="scatterChart"),
        "xl/charts/chart1.xml",
        input_format="xlsx",
    )

    assert extraction.status == "placeholder"
    assert extraction.structure is None
    assert extraction.chart_part == "xl/charts/chart1.xml"
    assert extraction.concern_codes == ["office_chart_type_unsupported"]

    invalid_entries = _xlsx_chart_entries()
    invalid_entries["xl/charts/chart1.xml"] = invalid_entries[
        "xl/charts/chart1.xml"
    ].replace(b"<c:v>Revenue</c:v>", b"<c:v>" + b"R" * 1_100 + b"</c:v>")
    invalid_entries["xl/sharedStrings.xml"] = invalid_entries[
        "xl/sharedStrings.xml"
    ].replace(b"<si><t>Revenue</t></si>", b"<si><t>" + b"R" * 1_100 + b"</t></si>")
    invalid = extract_office_chart(
        invalid_entries,
        "xl/charts/chart1.xml",
        input_format="xlsx",
    )
    assert invalid.status == "placeholder"
    assert invalid.structure is None
    assert invalid.concern_codes == ["office_chart_data_invalid"]

    # A broken PPTX chart relationship must remain attached to its own frame;
    # it cannot borrow the next valid chart part merely because that part is
    # otherwise unmatched.
    pptx_entries = unzip_package(pptx_fixture())
    marker = (
        b'<p:graphicFrame>\n          <p:nvGraphicFramePr><p:cNvPr id="7" '
        b'name="Chart"'
    )
    broken_frame = b"""<p:graphicFrame>
          <p:nvGraphicFramePr><p:cNvPr id="70" name="Broken Chart"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
          <p:xfrm><a:off x="700000" y="100000"/><a:ext cx="200000" cy="200000"/></p:xfrm>
          <a:graphic><a:graphicData uri="chart"><c:chart r:id="rIdMissing"/></a:graphicData></a:graphic>
        </p:graphicFrame>
        """
    assert marker in pptx_entries["ppt/slides/slide1.xml"]
    pptx_entries["ppt/slides/slide1.xml"] = pptx_entries[
        "ppt/slides/slide1.xml"
    ].replace(marker, broken_frame + marker, 1)
    pptx_entries["ppt/charts/chart1.xml"] = _chart_xml()
    pptx_package = zip_package(pptx_entries)
    pptx_output = apply_office_charts(
        parse_pptx(pptx_package),
        pptx_package,
        enabled=True,
    )
    chart_items = [
        item for item in pptx_output["pages"][0]["items"] if item["type"] == "chart"
    ]
    broken, grounded = chart_items
    assert broken["shape_name"] == "Broken Chart"
    assert broken["placeholder"] is True
    assert "office_chart" not in broken
    assert broken["parse_concerns"] == ["office_chart_relationship_unresolved"]
    assert grounded["shape_name"] == "Chart"
    assert grounded["chart_part"] == "ppt/charts/chart1.xml"
    assert grounded["placeholder"] is False
    assert pptx_output["processing"]["office_charts"]["structured_chart_count"] == 1
    assert pptx_output["processing"]["office_charts"]["placeholder_chart_count"] == 1
    assert ParseResult.model_validate(pptx_output)


def test_flag_off_is_exactly_unchanged_and_does_not_open_the_source() -> None:
    predecessor = {
        "processing": {"input_format": "xlsx"},
        "pages": [
            {
                "items": [
                    {
                        "id": "drawing-1",
                        "type": "image",
                        "content_type": "unsupported_drawing",
                        "placeholder": True,
                        "source_part": "xl/drawings/drawing1.xml",
                        "parse_concerns": ["xlsx_drawing_native_deferred"],
                    }
                ]
            }
        ],
    }
    snapshot = deepcopy(predecessor)

    class _UnreadableSource:
        @property
        def part_names(self) -> tuple[str, ...]:
            raise AssertionError("flag-off path opened the OOXML source")

        def read_part(self, _name: str) -> bytes:
            raise AssertionError("flag-off path read an OOXML part")

    output = apply_office_charts(predecessor, _UnreadableSource(), enabled=False)

    assert output == snapshot
    assert predecessor == snapshot
    assert output is not predecessor
    assert output["pages"] is not predecessor["pages"]
