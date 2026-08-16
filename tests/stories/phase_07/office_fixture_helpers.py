"""Small deterministic OOXML fixtures for Phase 07 release-first tests."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import quoteattr


PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CONTENT_TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

RelationshipSpec = tuple[str, str, str, str | None]


def relationships(records: Sequence[RelationshipSpec]) -> bytes:
    members: list[str] = []
    for relationship_id, relationship_type, target, target_mode in records:
        mode = "" if target_mode is None else f" TargetMode={quoteattr(target_mode)}"
        members.append(
            f"<Relationship Id={quoteattr(relationship_id)} "
            f"Type={quoteattr(relationship_type)} "
            f"Target={quoteattr(target)}{mode}/>"
        )
    return (
        f'<Relationships xmlns="{PACKAGE_REL_NS}">'
        + "".join(members)
        + "</Relationships>"
    ).encode()


def content_types(
    overrides: Mapping[str, str],
    *,
    defaults: Mapping[str, str] | None = None,
) -> bytes:
    default_values = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
        **dict(defaults or {}),
    }
    members = [
        f"<Default Extension={quoteattr(extension)} ContentType={quoteattr(value)}/>"
        for extension, value in sorted(default_values.items())
    ]
    members.extend(
        f"<Override PartName={quoteattr('/' + name)} ContentType={quoteattr(value)}/>"
        for name, value in sorted(overrides.items())
    )
    return (
        f'<Types xmlns="{CONTENT_TYPE_NS}">'
        + "".join(members)
        + "</Types>"
    ).encode()


def zip_package(entries: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, value)
    return output.getvalue()


def unzip_package(payload: bytes) -> dict[str, bytes]:
    """Return fixture entries so focused tests can make bounded mutations."""

    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def docx_fixture() -> bytes:
    document = b"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="urn:word" xmlns:r="urn:rel" xmlns:a="urn:drawing">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:rPr><w:b/></w:rPr><w:t>Quarterly Report</w:t></w:r>
    </w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>
      <w:r><w:t>First item</w:t></w:r>
    </w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr></w:pPr>
      <w:r><w:t>Nested item</w:t></w:r>
    </w:p>
    <w:tbl>
      <w:tblPr><w:tblCaption w:val="Revenue table"/></w:tblPr>
      <w:tr><w:trPr><w:tblHeader/></w:trPr>
        <w:tc><w:p><w:r><w:t>Region</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Revenue</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>East</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>10</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p><w:r><w:drawing><a:graphic><a:blip r:embed="rIdImage"/></a:graphic></w:drawing></w:r></w:p>
    <w:p><w:r><w:drawing><a:graphic><a:graphicData/></a:graphic></w:drawing></w:r></w:p>
    <w:sectPr><w:type w:val="nextPage"/><w:pgSz w:orient="landscape"/><w:cols w:num="2"/></w:sectPr>
  </w:body>
</w:document>"""
    styles = b"""<w:styles xmlns:w="urn:word">
      <w:style w:type="paragraph" w:styleId="Heading1">
        <w:name w:val="Heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>
      </w:style>
    </w:styles>"""
    numbering = b"""<w:numbering xmlns:w="urn:word">
      <w:abstractNum w:abstractNumId="7">
        <w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>
        <w:lvl w:ilvl="1"><w:numFmt w:val="lowerLetter"/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="1"><w:abstractNumId w:val="7"/></w:num>
    </w:numbering>"""
    header = b'<w:hdr xmlns:w="urn:word"><w:p><w:r><w:t>Acme Header</w:t></w:r></w:p></w:hdr>'
    footer = b'<w:ftr xmlns:w="urn:word"><w:p><w:r><w:t>Acme Footer</w:t></w:r></w:p></w:ftr>'
    entries = {
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/numbering.xml": numbering,
        "word/header1.xml": header,
        "word/footer1.xml": footer,
        "word/media/image1.png": b"\x89PNG\r\n\x1a\nfixture",
        "word/_rels/document.xml.rels": relationships(
            [
                ("rIdHeader", f"{DOC_REL_NS}/header", "header1.xml", None),
                ("rIdFooter", f"{DOC_REL_NS}/footer", "footer1.xml", None),
                ("rIdImage", f"{DOC_REL_NS}/image", "media/image1.png", None),
            ]
        ),
        "_rels/.rels": relationships(
            [
                (
                    "rIdOffice",
                    f"{DOC_REL_NS}/officeDocument",
                    "word/document.xml",
                    None,
                )
            ]
        ),
    }
    entries["[Content_Types].xml"] = content_types(
        {
            "word/document.xml": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document.main+xml"
            ),
            "word/header1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
            "word/footer1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
        },
        defaults={"png": "image/png"},
    )
    return zip_package(entries)


def _pptx_shape(
    shape_id: int,
    name: str,
    text: str,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    placeholder: str | None = None,
    hidden: bool = False,
) -> str:
    hidden_attr = ' hidden="1"' if hidden else ""
    placeholder_xml = "" if placeholder is None else f'<p:ph type="{placeholder}"/>'
    return f"""<p:sp>
      <p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"{hidden_attr}/><p:cNvSpPr/><p:nvPr>{placeholder_xml}</p:nvPr></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{width}" cy="{height}"/></a:xfrm></p:spPr>
      <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody>
    </p:sp>"""


def pptx_fixture() -> bytes:
    presentation = b"""<p:presentation xmlns:p="urn:ppt" xmlns:r="urn:rel">
      <p:sldSz cx="9144000" cy="6858000"/>
      <p:sldIdLst><p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst>
    </p:presentation>"""
    title = _pptx_shape(
        2,
        "Title",
        "Quarterly Results",
        x=12700,
        y=25400,
        width=127000,
        height=25400,
        placeholder="title",
    )
    grouped_child = _pptx_shape(
        4,
        "Grouped",
        "Grouped text",
        x=12700,
        y=12700,
        width=12700,
        height=25400,
    )
    hidden = _pptx_shape(
        9,
        "Hidden",
        "LEAK ME NOT",
        x=0,
        y=0,
        width=12700,
        height=12700,
        hidden=True,
    )
    slide1 = f"""<p:sld xmlns:p="urn:ppt" xmlns:a="urn:drawing" xmlns:r="urn:rel" xmlns:c="urn:chart">
      <p:cSld><p:spTree>
        <p:nvGrpSpPr><p:cNvPr id="1" name="Root"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
        <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="9144000" cy="6858000"/><a:chOff x="0" y="0"/><a:chExt cx="9144000" cy="6858000"/></a:xfrm></p:grpSpPr>
        {title}
        <p:grpSp>
          <p:nvGrpSpPr><p:cNvPr id="3" name="Group"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
          <p:grpSpPr><a:xfrm><a:off x="127000" y="254000"/><a:ext cx="254000" cy="254000"/><a:chOff x="0" y="0"/><a:chExt cx="127000" cy="127000"/></a:xfrm></p:grpSpPr>
          {grouped_child}
        </p:grpSp>
        <p:pic>
          <p:nvPicPr><p:cNvPr id="5" name="Picture"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
          <p:blipFill><a:blip r:embed="rIdImage"/></p:blipFill>
          <p:spPr><a:xfrm><a:off x="508000" y="254000"/><a:ext cx="127000" cy="127000"/></a:xfrm></p:spPr>
        </p:pic>
        <p:graphicFrame>
          <p:nvGraphicFramePr><p:cNvPr id="6" name="Table"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
          <p:xfrm><a:off x="127000" y="635000"/><a:ext cx="508000" cy="254000"/></p:xfrm>
          <a:graphic><a:graphicData uri="table"><a:tbl>
            <a:tr><a:tc><a:txBody><a:p><a:r><a:t>Region</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Value</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
            <a:tr><a:tc><a:txBody><a:p><a:r><a:t>East</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>10</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
          </a:tbl></a:graphicData></a:graphic>
        </p:graphicFrame>
        <p:graphicFrame>
          <p:nvGraphicFramePr><p:cNvPr id="7" name="Chart"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
          <p:xfrm><a:off x="762000" y="254000"/><a:ext cx="254000" cy="254000"/></p:xfrm>
          <a:graphic><a:graphicData uri="chart"><c:chart r:id="rIdChart"/></a:graphicData></a:graphic>
        </p:graphicFrame>
        <p:graphicFrame>
          <p:nvGraphicFramePr><p:cNvPr id="8" name="SmartArt"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
          <p:xfrm><a:off x="1016000" y="254000"/><a:ext cx="254000" cy="254000"/></p:xfrm>
          <a:graphic><a:graphicData uri="diagram"/></a:graphic>
        </p:graphicFrame>
        {hidden}
      </p:spTree></p:cSld>
    </p:sld>""".encode()
    slide2 = b"""<p:sld xmlns:p="urn:ppt" xmlns:a="urn:drawing" show="0">
      <p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/></p:spTree></p:cSld>
    </p:sld>"""
    entries = {
        "ppt/presentation.xml": presentation,
        "ppt/slides/slide1.xml": slide1,
        "ppt/slides/slide2.xml": slide2,
        "ppt/media/image1.png": b"\x89PNG\r\n\x1a\nfixture",
        "ppt/charts/chart1.xml": b'<c:chartSpace xmlns:c="urn:chart"/>',
        "ppt/_rels/presentation.xml.rels": relationships(
            [
                ("rId1", f"{DOC_REL_NS}/slide", "slides/slide1.xml", None),
                ("rId2", f"{DOC_REL_NS}/slide", "slides/slide2.xml", None),
            ]
        ),
        "ppt/slides/_rels/slide1.xml.rels": relationships(
            [
                ("rIdImage", f"{DOC_REL_NS}/image", "../media/image1.png", None),
                ("rIdChart", f"{DOC_REL_NS}/chart", "../charts/chart1.xml", None),
            ]
        ),
        "_rels/.rels": relationships(
            [("rIdOffice", f"{DOC_REL_NS}/officeDocument", "ppt/presentation.xml", None)]
        ),
    }
    entries["[Content_Types].xml"] = content_types(
        {
            "ppt/presentation.xml": (
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation.main+xml"
            ),
            "ppt/slides/slide1.xml": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
            "ppt/slides/slide2.xml": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
            "ppt/charts/chart1.xml": "application/vnd.openxmlformats-officedocument.drawingml.chart+xml",
        },
        defaults={"png": "image/png"},
    )
    return zip_package(entries)


def xlsx_entries(
    *,
    dimension: str = "A1:D4",
    formula: str = "SUM(B2:B2)",
    include_formula_cache: bool = True,
    numeric_value: str = "10",
) -> dict[str, bytes]:
    workbook = b"""<workbook xmlns="urn:xlsx" xmlns:r="urn:rel">
      <workbookPr date1904="0"/>
      <sheets><sheet name="Summary" sheetId="1" r:id="rId1"/><sheet name="Hidden" sheetId="2" state="hidden" r:id="rId2"/></sheets>
    </workbook>"""
    cached = "<v>10</v>" if include_formula_cache else ""
    worksheet = f"""<worksheet xmlns="urn:xlsx" xmlns:r="urn:rel">
      <dimension ref="{dimension}"/>
      <cols><col min="4" max="4" hidden="1"/></cols>
      <sheetData>
        <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="inlineStr"><is><t>As of</t></is></c></row>
        <row r="2"><c r="A2" t="inlineStr"><is><t>East</t></is></c><c r="B2"><v>{numeric_value}</v></c><c r="C2" s="1"><v>45292</v></c><c r="D2" t="inlineStr"><is><t>HIDDEN COLUMN SECRET</t></is></c></row>
        <row r="3"><c r="A3" t="inlineStr"><is><t>Total</t></is></c><c r="B3"><f>{formula}</f>{cached}</c><c r="C3" t="e"><v>#N/A</v></c></row>
        <row r="4" hidden="1"><c r="A4" t="inlineStr"><is><t>HIDDEN ROW SECRET</t></is></c></row>
      </sheetData>
      <mergeCells count="1"><mergeCell ref="A3:A3"/></mergeCells>
      <tableParts count="1"><tablePart r:id="rIdTable"/></tableParts>
      <drawing r:id="rIdDrawing"/>
    </worksheet>""".encode()
    hidden_sheet = b"""<worksheet xmlns="urn:xlsx"><dimension ref="A1"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>HIDDEN SHEET SECRET</t></is></c></row></sheetData></worksheet>"""
    shared_strings = b"""<sst xmlns="urn:xlsx"><si><t>Name</t></si><si><t>Revenue</t></si></sst>"""
    styles = b"""<styleSheet xmlns="urn:xlsx"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>"""
    table = b"""<table xmlns="urn:xlsx" id="1" name="RevenueTable" displayName="RevenueTable" ref="A1:C3" headerRowCount="1" totalsRowCount="0"><tableColumns count="3"><tableColumn id="1" name="Name"/><tableColumn id="2" name="Revenue"/><tableColumn id="3" name="As of"/></tableColumns></table>"""
    drawing = b"""<xdr:wsDr xmlns:xdr="urn:drawing" xmlns:c="urn:chart" xmlns:r="urn:rel"><xdr:twoCellAnchor><xdr:graphicFrame><c:chart r:id="rIdChart"/></xdr:graphicFrame></xdr:twoCellAnchor></xdr:wsDr>"""
    entries = {
        "xl/workbook.xml": workbook,
        "xl/worksheets/sheet1.xml": worksheet,
        "xl/worksheets/sheet2.xml": hidden_sheet,
        "xl/sharedStrings.xml": shared_strings,
        "xl/styles.xml": styles,
        "xl/tables/table1.xml": table,
        "xl/drawings/drawing1.xml": drawing,
        "xl/charts/chart1.xml": b'<c:chartSpace xmlns:c="urn:chart"/>',
        "xl/_rels/workbook.xml.rels": relationships(
            [
                ("rId1", f"{DOC_REL_NS}/worksheet", "worksheets/sheet1.xml", None),
                ("rId2", f"{DOC_REL_NS}/worksheet", "worksheets/sheet2.xml", None),
            ]
        ),
        "xl/worksheets/_rels/sheet1.xml.rels": relationships(
            [
                ("rIdTable", f"{DOC_REL_NS}/table", "../tables/table1.xml", None),
                ("rIdDrawing", f"{DOC_REL_NS}/drawing", "../drawings/drawing1.xml", None),
            ]
        ),
        "xl/drawings/_rels/drawing1.xml.rels": relationships(
            [("rIdChart", f"{DOC_REL_NS}/chart", "../charts/chart1.xml", None)]
        ),
        "_rels/.rels": relationships(
            [("rIdOffice", f"{DOC_REL_NS}/officeDocument", "xl/workbook.xml", None)]
        ),
    }
    entries["[Content_Types].xml"] = content_types(
        {
            "xl/workbook.xml": (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet.main+xml"
            ),
            "xl/worksheets/sheet1.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
            "xl/worksheets/sheet2.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
            "xl/sharedStrings.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml",
            "xl/styles.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
            "xl/tables/table1.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml",
            "xl/drawings/drawing1.xml": "application/vnd.openxmlformats-officedocument.drawing+xml",
            "xl/charts/chart1.xml": "application/vnd.openxmlformats-officedocument.drawingml.chart+xml",
        }
    )
    return entries


def xlsx_fixture(**kwargs: object) -> bytes:
    return zip_package(xlsx_entries(**kwargs))


__all__ = [
    "DOC_REL_NS",
    "content_types",
    "docx_fixture",
    "pptx_fixture",
    "relationships",
    "xlsx_entries",
    "xlsx_fixture",
    "zip_package",
    "unzip_package",
]
