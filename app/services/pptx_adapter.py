"""Native PPTX slide/shape adapter with deterministic transform handling."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from app.services.office_native import (
    OfficeAdapterDisabledError,
    OfficeNativeLimitError,
    OfficeNativePackageError,
    OfficePackageView,
    OfficeRelationship,
    StableIdFactory,
    attr,
    build_parse_result,
    child,
    children,
    coerce_package,
    content_item,
    descendants,
    finite_number,
    html_table,
    local_name,
    logical_page,
    markdown_table,
    native_provenance,
    normalized_text,
    office_adapter_manifest,
    parse_bool,
    read_relationships,
    read_xml,
)


PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
EMU_PER_POINT = 12_700.0


@dataclass(frozen=True, slots=True)
class _Affine:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def apply(self, x: float, y: float) -> tuple[float, float]:
        if not math.isfinite(x) or not math.isfinite(y):
            raise OfficeNativePackageError(code="pptx_transform_nonfinite")
        point = (
            self.a * x + self.c * y + self.e,
            self.b * x + self.d * y + self.f,
        )
        if not all(math.isfinite(value) for value in point):
            raise OfficeNativePackageError(code="pptx_transform_nonfinite")
        return point

    def then(self, outer: _Affine) -> _Affine:
        """Return ``outer(self(point))``."""

        composed = _Affine(
            a=outer.a * self.a + outer.c * self.b,
            b=outer.b * self.a + outer.d * self.b,
            c=outer.a * self.c + outer.c * self.d,
            d=outer.b * self.c + outer.d * self.d,
            e=outer.a * self.e + outer.c * self.f + outer.e,
            f=outer.b * self.e + outer.d * self.f + outer.f,
        )
        if not all(math.isfinite(value) for value in composed.payload()):
            raise OfficeNativePackageError(code="pptx_transform_nonfinite")
        return composed

    def payload(self) -> list[float]:
        return [self.a, self.b, self.c, self.d, self.e, self.f]


def _translation(x: float, y: float) -> _Affine:
    return _Affine(e=x, f=y)


def _scale(x: float, y: float) -> _Affine:
    return _Affine(a=x, d=y)


def _rotation(degrees: float) -> _Affine:
    radians = math.radians(degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return _Affine(a=cosine, b=sine, c=-sine, d=cosine)


def _around_center(transform: _Affine, cx: float, cy: float) -> _Affine:
    return _translation(-cx, -cy).then(transform).then(_translation(cx, cy))


def _xfrm_values(xfrm: ET.Element | None) -> tuple[float, float, float, float]:
    if xfrm is None:
        raise OfficeNativePackageError(code="pptx_transform_missing")
    off = child(xfrm, "off")
    ext = child(xfrm, "ext")
    if off is None or ext is None:
        raise OfficeNativePackageError(code="pptx_transform_incomplete")
    x = finite_number(attr(off, "x"))
    y = finite_number(attr(off, "y"))
    width = finite_number(attr(ext, "cx"))
    height = finite_number(attr(ext, "cy"))
    if width < 0 or height < 0:
        raise OfficeNativePackageError(code="pptx_transform_extent_invalid")
    return x, y, width, height


def _own_transform(xfrm: ET.Element, x: float, y: float, width: float, height: float) -> _Affine:
    transform = _Affine()
    if parse_bool(attr(xfrm, "flipH"), False):
        transform = transform.then(_around_center(_scale(-1.0, 1.0), x + width / 2, y + height / 2))
    if parse_bool(attr(xfrm, "flipV"), False):
        transform = transform.then(_around_center(_scale(1.0, -1.0), x + width / 2, y + height / 2))
    rotation_raw = attr(xfrm, "rot")
    if rotation_raw is not None:
        degrees = finite_number(rotation_raw) / 60_000.0
        transform = transform.then(
            _around_center(_rotation(degrees), x + width / 2, y + height / 2)
        )
    return transform


def _shape_bbox(
    xfrm: ET.Element | None,
    parent: _Affine,
) -> tuple[dict[str, float | str], _Affine, dict[str, Any]]:
    x, y, width, height = _xfrm_values(xfrm)
    assert xfrm is not None
    own = _own_transform(xfrm, x, y, width, height)
    combined = own.then(parent)
    corners = [
        combined.apply(x, y),
        combined.apply(x + width, y),
        combined.apply(x, y + height),
        combined.apply(x + width, y + height),
    ]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    bbox = {
        "x": min(xs) / EMU_PER_POINT,
        "y": min(ys) / EMU_PER_POINT,
        "width": (max(xs) - min(xs)) / EMU_PER_POINT,
        "height": (max(ys) - min(ys)) / EMU_PER_POINT,
        "unit": "pt",
    }
    if (
        not all(
            math.isfinite(float(bbox[key]))
            for key in ("x", "y", "width", "height")
        )
        or float(bbox["width"]) < 0
        or float(bbox["height"]) < 0
    ):
        raise OfficeNativePackageError(code="pptx_bbox_invalid")
    provenance = {
        "source_transform": combined.payload(),
        "source_transform_unit": "emu",
        "rotation_degrees": finite_number(attr(xfrm, "rot")) / 60_000.0
        if attr(xfrm, "rot") is not None
        else 0.0,
        "flip_h": parse_bool(attr(xfrm, "flipH"), False),
        "flip_v": parse_bool(attr(xfrm, "flipV"), False),
    }
    return bbox, combined, provenance


def _group_transform(xfrm: ET.Element | None, parent: _Affine) -> tuple[_Affine, dict[str, Any]]:
    x, y, width, height = _xfrm_values(xfrm)
    assert xfrm is not None
    child_off = child(xfrm, "chOff")
    child_ext = child(xfrm, "chExt")
    if child_off is None or child_ext is None:
        raise OfficeNativePackageError(code="pptx_group_transform_incomplete")
    child_x = finite_number(attr(child_off, "x"))
    child_y = finite_number(attr(child_off, "y"))
    child_width = finite_number(attr(child_ext, "cx"))
    child_height = finite_number(attr(child_ext, "cy"))
    if child_width <= 0 or child_height <= 0:
        raise OfficeNativePackageError(code="pptx_group_transform_extent_invalid")
    scale_x = width / child_width
    scale_y = height / child_height
    mapping = _translation(-child_x, -child_y).then(_scale(scale_x, scale_y)).then(
        _translation(x, y)
    )
    mapping = mapping.then(_own_transform(xfrm, x, y, width, height)).then(parent)
    return mapping, {
        "source_transform": mapping.payload(),
        "source_transform_unit": "emu",
        "child_offset": [child_x, child_y],
        "child_extent": [child_width, child_height],
    }


def _nonvisual_properties(node: ET.Element) -> ET.Element | None:
    for candidate in node.iter():
        if local_name(candidate.tag) == "cNvPr":
            return candidate
    return None


def _hidden(node: ET.Element) -> bool:
    properties = _nonvisual_properties(node)
    return properties is not None and parse_bool(attr(properties, "hidden"), False)


def _shape_text(node: ET.Element) -> str:
    paragraphs = descendants(node, "p")
    if paragraphs:
        return "\n".join(
            text
            for paragraph in paragraphs
            if (
                text := normalized_text(
                    text_node.text or ""
                    for text_node in descendants(paragraph, "t")
                    if text_node.text
                )
            )
        )
    return normalized_text(
        text_node.text or ""
        for text_node in descendants(node, "t")
        if text_node.text
    )


def _shape_xfrm(node: ET.Element) -> ET.Element | None:
    properties = child(node, "spPr")
    if properties is None:
        properties = child(node, "xfrm")
    if properties is None:
        for candidate in list(node):
            if local_name(candidate.tag) in {"xfrm", "spPr"}:
                properties = candidate
                break
    if properties is not None and local_name(properties.tag) != "xfrm":
        return child(properties, "xfrm")
    return properties


def _placeholder_type(node: ET.Element) -> str | None:
    for properties in descendants(node, "nvPr"):
        placeholder = child(properties, "ph")
        if placeholder is not None:
            return attr(placeholder, "type") or "body"
    return None


def _table_payload(node: ET.Element, *, part: str, xml_path: str) -> dict[str, Any]:
    rows: list[list[str]] = []
    cells_payload: list[dict[str, Any]] = []
    table = next((candidate for candidate in node.iter() if local_name(candidate.tag) == "tbl"), None)
    if table is None:
        raise OfficeNativePackageError(code="pptx_table_missing")
    for row_index, row in enumerate(children(table, "tr")):
        values: list[str] = []
        for column_index, cell_node in enumerate(children(row, "tc")):
            value = _shape_text(cell_node)
            values.append(value)
            try:
                row_span = max(int(attr(cell_node, "rowSpan") or "1"), 1)
                column_span = max(int(attr(cell_node, "gridSpan") or "1"), 1)
            except ValueError:
                row_span = column_span = 1
            cells_payload.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "text": value,
                    "row_span": row_span,
                    "column_span": column_span,
                    "native_provenance": native_provenance(
                        part=part,
                        xml_path=f"{xml_path}/tbl/tr[{row_index + 1}]/tc[{column_index + 1}]",
                        coordinate_state="slide_points",
                    ),
                }
            )
        rows.append(values)
    return {
        "rows": rows,
        "cells": cells_payload,
        "html": html_table(rows),
        "md": markdown_table(rows),
    }


def _relationship_for_node(
    node: ET.Element,
    relationships: Mapping[str, OfficeRelationship],
) -> tuple[str | None, OfficeRelationship | None]:
    relationship_id: str | None = None
    for candidate in node.iter():
        relationship_id = attr(candidate, "embed") or attr(candidate, "link") or attr(candidate, "id")
        if relationship_id and relationship_id.startswith("rId"):
            break
        relationship_id = None
    return relationship_id, relationships.get(relationship_id or "")


class _SlideBuilder:
    def __init__(
        self,
        *,
        package: OfficePackageView,
        part: str,
        relationships: Mapping[str, OfficeRelationship],
        slide_id: str,
        max_shapes: int,
    ) -> None:
        self.package = package
        self.part = part
        self.relationships = relationships
        self.slide_id = slide_id
        self.max_shapes = max_shapes
        self.ids = StableIdFactory(f"pptx-s{slide_id}")
        self.items: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.shape_count = 0

    def append(self, item: dict[str, Any]) -> None:
        self.shape_count += 1
        if self.shape_count > self.max_shapes:
            raise OfficeNativeLimitError(
                code="pptx_shape_limit",
                details={"max_shapes": self.max_shapes},
            )
        item["reading_order"] = len(self.items)
        item["z_order"] = len(self.items)
        item["slide_id"] = self.slide_id
        self.items.append(item)

    def _provenance(
        self,
        *,
        xml_path: str,
        transform: Mapping[str, Any] | None = None,
        relationship: OfficeRelationship | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, Any] = {"slide_id": self.slide_id}
        if transform:
            extra.update(transform)
        return native_provenance(
            part=self.part,
            xml_path=xml_path,
            coordinate_state="slide_points",
            relationship=relationship,
            extra=extra,
        )

    def walk(self, parent: ET.Element, parent_transform: _Affine, path: str) -> None:
        semantic_children = [
            node
            for node in list(parent)
            if local_name(node.tag) not in {"nvGrpSpPr", "grpSpPr"}
        ]
        for index, node in enumerate(semantic_children, 1):
            name = local_name(node.tag)
            node_path = f"{path}/{name}[{index}]"
            if _hidden(node):
                self.warnings.append("pptx_hidden_element_omitted")
                continue
            if name == "grpSp":
                group_properties = child(node, "grpSpPr")
                xfrm = child(group_properties, "xfrm") if group_properties is not None else None
                try:
                    group_transform, transform_payload = _group_transform(xfrm, parent_transform)
                    x, y, width, height = _xfrm_values(xfrm)
                    assert xfrm is not None
                    # The group item describes the transformed outer group
                    # rectangle. Its own rotation/flip therefore participates
                    # in the public bbox just as it does for each descendant.
                    group_outer_transform = _own_transform(
                        xfrm,
                        x,
                        y,
                        width,
                        height,
                    ).then(parent_transform)
                    corners = [
                        group_outer_transform.apply(x, y),
                        group_outer_transform.apply(x + width, y),
                        group_outer_transform.apply(x, y + height),
                        group_outer_transform.apply(x + width, y + height),
                    ]
                    bbox = {
                        "x": min(point[0] for point in corners) / EMU_PER_POINT,
                        "y": min(point[1] for point in corners) / EMU_PER_POINT,
                        "width": (
                            max(point[0] for point in corners)
                            - min(point[0] for point in corners)
                        )
                        / EMU_PER_POINT,
                        "height": (
                            max(point[1] for point in corners)
                            - min(point[1] for point in corners)
                        )
                        / EMU_PER_POINT,
                        "unit": "pt",
                    }
                    if (
                        not all(
                            math.isfinite(float(bbox[key]))
                            for key in ("x", "y", "width", "height")
                        )
                        or float(bbox["width"]) < 0
                        or float(bbox["height"]) < 0
                    ):
                        raise OfficeNativePackageError(code="pptx_bbox_invalid")
                except OfficeNativePackageError:
                    self.append(
                        content_item(
                            self.ids,
                            "group",
                            len(self.items),
                            provenance=self._provenance(xml_path=node_path),
                            placeholder=True,
                            fallback_eligible=True,
                            parse_concerns=["pptx_group_transform_invalid"],
                        )
                    )
                    continue
                nonvisual = _nonvisual_properties(node)
                self.append(
                    content_item(
                        self.ids,
                        "group",
                        len(self.items),
                        provenance=self._provenance(
                            xml_path=node_path,
                            transform=transform_payload,
                        ),
                        bbox=bbox,
                        shape_id=attr(nonvisual, "id") if nonvisual is not None else None,
                        shape_name=attr(nonvisual, "name") if nonvisual is not None else None,
                        group=True,
                    )
                )
                self.walk(node, group_transform, node_path)
                continue

            xfrm = _shape_xfrm(node)
            bbox: dict[str, Any] | None = None
            transform_payload: dict[str, Any] = {}
            try:
                if xfrm is not None:
                    bbox, _combined, transform_payload = _shape_bbox(
                        xfrm,
                        parent_transform,
                    )
            except OfficeNativePackageError:
                self.append(
                    content_item(
                        self.ids,
                        "shape",
                        len(self.items),
                        value="[Unsupported shape transform]",
                        markdown="[Unsupported shape transform]",
                        provenance=self._provenance(xml_path=node_path),
                        placeholder=True,
                        fallback_eligible=True,
                        parse_concerns=["pptx_shape_transform_invalid"],
                    )
                )
                continue

            nonvisual = _nonvisual_properties(node)
            shape_id = attr(nonvisual, "id") if nonvisual is not None else None
            shape_name = attr(nonvisual, "name") if nonvisual is not None else None
            common = {
                "bbox": bbox,
                "shape_id": shape_id,
                "shape_name": shape_name,
            }
            if name == "sp":
                text = _shape_text(node)
                placeholder_type = _placeholder_type(node)
                item_type = (
                    "heading"
                    if placeholder_type in {"title", "ctrTitle", "subTitle"} and text
                    else "text"
                    if text
                    else "shape"
                )
                self.append(
                    content_item(
                        self.ids,
                        item_type,
                        len(self.items),
                        value=text or None,
                        markdown=text or None,
                        provenance=self._provenance(
                            xml_path=node_path,
                            transform=transform_payload,
                        ),
                        level=1 if item_type == "heading" else None,
                        placeholder_type=placeholder_type,
                        runs=[
                            {"text": text, "method": "native_xml"}
                        ]
                        if text
                        else [],
                        **common,
                    )
                )
            elif name in {"cxnSp", "contentPart"}:
                self.append(
                    content_item(
                        self.ids,
                        "shape",
                        len(self.items),
                        provenance=self._provenance(
                            xml_path=node_path,
                            transform=transform_payload,
                        ),
                        shape_type="connector" if name == "cxnSp" else "content_part",
                        **common,
                    )
                )
            elif name == "pic":
                relationship_id, relationship = _relationship_for_node(
                    node,
                    self.relationships,
                )
                available = (
                    relationship is not None
                    and not relationship.external
                    and relationship.resolved_target is not None
                    and self.package.read_part(
                        relationship.resolved_target,
                        required=False,
                    )
                    is not None
                )
                if available:
                    assert relationship is not None
                    self.append(
                        content_item(
                            self.ids,
                            "image",
                            len(self.items),
                            value=f"[Embedded image: {relationship.resolved_target}]",
                            markdown=f"[Embedded image: {relationship.resolved_target}]",
                            provenance=self._provenance(
                                xml_path=node_path,
                                transform=transform_payload,
                                relationship=relationship,
                            ),
                            content_type="image",
                            asset_origin="native_embedded",
                            relationship_id=relationship_id,
                            source_part=relationship.resolved_target,
                            **common,
                        )
                    )
                else:
                    concern = (
                        "pptx_external_media_not_fetched"
                        if relationship is not None and relationship.external
                        else "pptx_media_relationship_broken"
                    )
                    self.append(
                        content_item(
                            self.ids,
                            "image",
                            len(self.items),
                            value="[Unavailable presentation image]",
                            markdown="[Unavailable presentation image]",
                            provenance=self._provenance(
                                xml_path=node_path,
                                transform=transform_payload,
                                relationship=relationship,
                            ),
                            content_type="unsupported_media",
                            relationship_id=relationship_id,
                            placeholder=True,
                            fallback_eligible=True,
                            parse_concerns=[concern],
                            **common,
                        )
                    )
            elif name == "graphicFrame":
                graphic_data = next(
                    (
                        candidate
                        for candidate in node.iter()
                        if local_name(candidate.tag) == "graphicData"
                    ),
                    None,
                )
                uri = (attr(graphic_data, "uri") if graphic_data is not None else "") or ""
                table = next(
                    (candidate for candidate in node.iter() if local_name(candidate.tag) == "tbl"),
                    None,
                )
                chart = next(
                    (candidate for candidate in node.iter() if local_name(candidate.tag) == "chart"),
                    None,
                )
                if table is not None:
                    payload = _table_payload(node, part=self.part, xml_path=node_path)
                    self.append(
                        content_item(
                            self.ids,
                            "table",
                            len(self.items),
                            value=payload["rows"],
                            markdown=payload["md"],
                            provenance=self._provenance(
                                xml_path=node_path,
                                transform=transform_payload,
                            ),
                            rows=payload["rows"],
                            cells=payload["cells"],
                            html=payload["html"],
                            **common,
                        )
                    )
                elif chart is not None or "chart" in uri.casefold():
                    relationship_id = attr(chart, "id") if chart is not None else None
                    relationship = self.relationships.get(relationship_id or "")
                    self.append(
                        content_item(
                            self.ids,
                            "chart",
                            len(self.items),
                            value="[Native Office chart pending extraction]",
                            markdown="[Native Office chart pending extraction]",
                            provenance=self._provenance(
                                xml_path=node_path,
                                transform=transform_payload,
                                relationship=relationship,
                            ),
                            content_type="chart",
                            placeholder=True,
                            native_chart_pending=True,
                            fallback_eligible=False,
                            relationship_id=relationship_id,
                            chart_part=(
                                relationship.resolved_target
                                if relationship is not None
                                else None
                            ),
                            parse_concerns=["office_chart_native_data_deferred"],
                            **common,
                        )
                    )
                else:
                    concern = (
                        "pptx_smartart_unsupported"
                        if "diagram" in uri.casefold()
                        else "pptx_graphic_frame_unsupported"
                    )
                    item_type = "diagram" if "diagram" in uri.casefold() else "image"
                    self.append(
                        content_item(
                            self.ids,
                            item_type,
                            len(self.items),
                            value="[Unsupported presentation drawing]",
                            markdown="[Unsupported presentation drawing]",
                            provenance=self._provenance(
                                xml_path=node_path,
                                transform=transform_payload,
                            ),
                            content_type="unsupported_drawing",
                            placeholder=True,
                            fallback_eligible=True,
                            parse_concerns=[concern],
                            **common,
                        )
                    )
            else:
                self.append(
                    content_item(
                        self.ids,
                        "image",
                        len(self.items),
                        value=f"[Unsupported presentation object: {name}]",
                        markdown=f"[Unsupported presentation object: {name}]",
                        provenance=self._provenance(
                            xml_path=node_path,
                            transform=transform_payload,
                        ),
                        content_type="unsupported_drawing",
                        placeholder=True,
                        fallback_eligible=True,
                        parse_concerns=["pptx_object_unsupported"],
                        **common,
                    )
                )


def _presentation_slide_size(root: ET.Element) -> tuple[float, float]:
    size = child(root, "sldSz")
    if size is None:
        raise OfficeNativePackageError(code="pptx_slide_size_missing")
    width = finite_number(attr(size, "cx")) / EMU_PER_POINT
    height = finite_number(attr(size, "cy")) / EMU_PER_POINT
    if width <= 0 or height <= 0:
        raise OfficeNativePackageError(code="pptx_slide_size_invalid")
    return width, height


def parse_pptx(
    source: Any,
    *,
    filename: str = "presentation.pptx",
    enabled: bool = True,
    max_slides: int = 256,
    max_shapes: int = 10_000,
) -> dict[str, Any]:
    """Extract visible slide-native semantics without rendering or chart data."""

    if not enabled:
        raise OfficeAdapterDisabledError(
            "PPTX native adapter is disabled.",
            details={"extension": ".pptx"},
        )
    if isinstance(max_slides, bool) or max_slides < 1:
        raise ValueError("max_slides must be a positive integer")
    if isinstance(max_shapes, bool) or max_shapes < 1:
        raise ValueError("max_shapes must be a positive integer")
    package = coerce_package(source)
    presentation_part = package.main_part or "ppt/presentation.xml"
    root = read_xml(package, presentation_part)
    if root is None or local_name(root.tag) != "presentation":
        raise OfficeNativePackageError(code="pptx_presentation_root_invalid")
    width, height = _presentation_slide_size(root)
    relationships = read_relationships(package, presentation_part)
    slide_list = child(root, "sldIdLst")
    slide_nodes = children(slide_list, "sldId") if slide_list is not None else []
    if not slide_nodes:
        raise OfficeNativePackageError(code="pptx_slide_list_missing")
    if len(slide_nodes) > max_slides:
        raise OfficeNativeLimitError(
            code="pptx_slide_limit",
            details={"max_slides": max_slides},
        )

    pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    total_shapes = 0
    for slide_index, slide_reference in enumerate(slide_nodes, 1):
        slide_id = (attr(slide_reference, "id") or str(slide_index)).strip()
        relationship_id = attr(slide_reference, "id")
        # Namespace-local lookup above may see the numeric p:id first.  Prefer
        # the relationship value explicitly by selecting the rId-shaped value.
        relationship_id = next(
            (
                value
                for value in slide_reference.attrib.values()
                if isinstance(value, str) and value.startswith("rId")
            ),
            relationship_id,
        )
        relationship = relationships.get(relationship_id or "")
        if (
            relationship is None
            or relationship.external
            or relationship.resolved_target is None
        ):
            raise OfficeNativePackageError(
                code="pptx_slide_relationship_invalid",
                details={"slide_index": slide_index},
            )
        slide_root = read_xml(package, relationship.resolved_target)
        if slide_root is None or local_name(slide_root.tag) != "sld":
            raise OfficeNativePackageError(code="pptx_slide_root_invalid")
        hidden = not parse_bool(attr(slide_root, "show"), True) or not parse_bool(
            attr(slide_reference, "show"),
            True,
        )
        if hidden:
            warning = "pptx_hidden_slide_omitted"
            warnings.append(warning)
            pages.append(
                logical_page(
                    page_index=slide_index,
                    label=f"Slide {slide_index}",
                    items=[],
                    coordinate_state="slide_points",
                    warnings=[warning],
                    width=width,
                    height=height,
                    unit="pt",
                    extra={
                        "slide_id": slide_id,
                        "visibility": "hidden",
                        "source_part": relationship.resolved_target,
                    },
                )
            )
            continue
        slide_relationships = read_relationships(package, relationship.resolved_target)
        builder = _SlideBuilder(
            package=package,
            part=relationship.resolved_target,
            relationships=slide_relationships,
            slide_id=slide_id,
            max_shapes=max_shapes - total_shapes,
        )
        common_slide_data = child(slide_root, "cSld")
        shape_tree = child(common_slide_data, "spTree") if common_slide_data is not None else None
        if shape_tree is None:
            raise OfficeNativePackageError(code="pptx_shape_tree_missing")
        builder.walk(shape_tree, _Affine(), "/sld/cSld/spTree")
        total_shapes += builder.shape_count
        pages.append(
            logical_page(
                page_index=slide_index,
                label=f"Slide {slide_index}",
                items=builder.items,
                coordinate_state="slide_points",
                warnings=builder.warnings,
                width=width,
                height=height,
                unit="pt",
                extra={
                    "slide_id": slide_id,
                    "visibility": "visible",
                    "source_part": relationship.resolved_target,
                    "relationship_id": relationship.relationship_id,
                },
            )
        )
        warnings.extend(builder.warnings)

    return build_parse_result(
        filename=filename,
        mime_type=PPTX_MIME_TYPE,
        source_format="PPTX",
        source_sha256=package.digest([presentation_part]),
        pages=pages,
        warnings=warnings,
    )


parse_pptx_package = parse_pptx


class PptxNativeAdapter:
    adapter_id = "pptx-native"
    adapter_version = "1.0.0"
    extensions = (".pptx",)
    mime_types = (PPTX_MIME_TYPE,)
    source_format = "PPTX"

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings
        self._manifest = office_adapter_manifest(
            adapter_id=self.adapter_id,
            input_kind="pptx",
            extension=".pptx",
            mime_type=PPTX_MIME_TYPE,
            coordinate_unit="pt",
            optional_capabilities=[
                "group_transforms",
                "native_media",
                "native_tables",
                "native_text",
                "slide_order",
                "z_order",
            ],
            settings=settings,
        )

    @property
    def manifest(self) -> Any:
        return self._manifest

    def load(self, data: bytes, filename: str, settings: Any) -> dict[str, Any]:
        from app.services.ooxml_intake import intake_ooxml, limits_from_settings

        package = intake_ooxml(
            data,
            filename,
            PPTX_MIME_TYPE,
            limits=limits_from_settings(settings),
        )
        return parse_pptx(
            package,
            filename=filename,
            enabled=bool(getattr(settings, "adapters_pptx_native_enabled", False)),
            max_slides=int(getattr(settings, "max_pages", 100)),
        )

    def parse(
        self,
        source: Any,
        *,
        filename: str = "presentation.pptx",
        enabled: bool = True,
        max_slides: int = 256,
        max_shapes: int = 10_000,
    ) -> dict[str, Any]:
        return parse_pptx(
            source,
            filename=filename,
            enabled=enabled,
            max_slides=max_slides,
            max_shapes=max_shapes,
        )


PPTXAdapter = PptxNativeAdapter


__all__ = [
    "EMU_PER_POINT",
    "PPTXAdapter",
    "PPTX_MIME_TYPE",
    "PptxNativeAdapter",
    "parse_pptx",
    "parse_pptx_package",
]
