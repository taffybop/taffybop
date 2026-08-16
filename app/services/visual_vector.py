"""Bounded chart-owned vector inventory for Phase 05."""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.visual_contracts import (
    ChartPanel,
    VectorInventory,
    VectorPrimitive,
    VisualBoundingBox,
    VisualConcern,
    VisualEvidence,
    VisualProvenance,
    VisualStructure,
    VisualTransform,
    ensure_finite_mapping,
)


_MAX_TRANSFORMS = 16
_MAX_PANELS = 128
_MAX_PRIMITIVES = 2_048
_MAX_PDF_OBJECTS = 8_192
_IDENTITY = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("vector coordinate must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("vector coordinate must be finite")
    return result


def _matrix(value: Any) -> list[float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != 6
    ):
        raise ValueError("vector transform must contain six numbers")
    result = [_number(member) for member in value]
    a, b, c, d, _e, _f = result
    if abs(a * d - b * c) < 1e-12:
        raise ValueError("vector transform must be invertible")
    return result


def compose_affine(parent: Sequence[float], child: Sequence[float]) -> list[float]:
    """Compose ``parent(child(point))`` in PDF affine order."""

    pa, pb, pc, pd, pe, pf = (_number(value) for value in parent)
    ca, cb, cc, cd, ce, cf = (_number(value) for value in child)
    return [
        pa * ca + pc * cb,
        pb * ca + pd * cb,
        pa * cc + pc * cd,
        pb * cc + pd * cd,
        pa * ce + pc * cf + pe,
        pb * ce + pd * cf + pf,
    ]


def _transform_point(matrix: Sequence[float], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _transform_box(
    box: VisualBoundingBox,
    matrix: Sequence[float],
    *,
    unit: str,
) -> VisualBoundingBox:
    points = [
        _transform_point(matrix, box.x, box.y),
        _transform_point(matrix, box.x + box.width, box.y),
        _transform_point(matrix, box.x, box.y + box.height),
        _transform_point(matrix, box.x + box.width, box.y + box.height),
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    if min(left, top) < -1e-6:
        raise ValueError("transformed vector bbox leaves non-negative page space")
    return VisualBoundingBox(
        x=max(left, 0.0),
        y=max(top, 0.0),
        width=right - left,
        height=bottom - top,
        unit=unit,
    )


def _box(value: Any, *, unit: str) -> VisualBoundingBox:
    if not isinstance(value, Mapping):
        raise ValueError("vector bbox must be an object")
    x = _number(value.get("x"))
    y = _number(value.get("y"))
    width = _number(value.get("width", value.get("w")))
    height = _number(value.get("height", value.get("h")))
    if min(x, y, width, height) < 0:
        raise ValueError("vector bbox values must be non-negative")
    raw_unit = str(value.get("unit") or unit)
    if raw_unit != unit:
        raise ValueError("vector bbox unit differs from its coordinate space")
    return VisualBoundingBox(
        x=x,
        y=y,
        width=width,
        height=height,
        unit=unit,
    )


def _contains(outer: VisualBoundingBox, inner: VisualBoundingBox) -> bool:
    epsilon = 1e-6
    return (
        inner.x + epsilon >= outer.x
        and inner.y + epsilon >= outer.y
        and inner.x + inner.width <= outer.x + outer.width + epsilon
        and inner.y + inner.height <= outer.y + outer.height + epsilon
    )


def _overlaps(first: VisualBoundingBox, second: VisualBoundingBox) -> bool:
    return not (
        first.x + first.width <= second.x
        or second.x + second.width <= first.x
        or first.y + first.height <= second.y
        or second.y + second.height <= first.y
    )


def _local_from_page(
    page_box: VisualBoundingBox,
    region_box: VisualBoundingBox,
) -> VisualBoundingBox:
    if not _overlaps(page_box, region_box):
        raise ValueError("vector primitive is outside its chart region")
    x = max(page_box.x, region_box.x)
    y = max(page_box.y, region_box.y)
    right = min(page_box.x + page_box.width, region_box.x + region_box.width)
    bottom = min(page_box.y + page_box.height, region_box.y + region_box.height)
    return VisualBoundingBox(
        x=max(x - region_box.x, 0.0),
        y=max(y - region_box.y, 0.0),
        width=max(right - x, 0.0),
        height=max(bottom - y, 0.0),
        unit=region_box.unit,
    )


def _color(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if not normalized or len(normalized) > 64:
            return None
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not 1 <= len(value) <= 4:
            return None
        components = [_number(component) for component in value]
        if any(component < 0 or component > 1 for component in components):
            return None
        return "[" + ",".join(f"{component:.6g}" for component in components) + "]"
    return None


def _raw_vector_evidence(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = item.get("vector_source_evidence")
    if isinstance(direct, Mapping):
        return direct
    meta = item.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("phase05_vector_evidence")
        if isinstance(value, Mapping):
            return value
    return None


def _pdfplumber_box(value: Mapping[str, Any], *, unit: str) -> dict[str, Any] | None:
    try:
        left = _number(value.get("x0"))
        right = _number(value.get("x1"))
        top = _number(value.get("top"))
        bottom = _number(value.get("bottom"))
    except ValueError:
        return None
    if min(left, top) < 0 or right < left or bottom < top:
        return None
    return {
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
        "unit": unit,
    }


def extract_pdf_vector_evidence(
    source_pdf_bytes: bytes,
    *,
    page_index: int,
    region_box: VisualBoundingBox,
) -> dict[str, Any]:
    """Read a bounded flattened PDF drawing inventory for one chart bbox.

    pdfplumber reports paint attributes and page-space geometry but not a
    trustworthy clip stack.  Such primitives are retained as unsupported with
    an explicit unknown-clipping concern instead of silently treating them as
    measurement-ready.
    """

    if not source_pdf_bytes:
        raise ValueError("source PDF bytes are unavailable")
    import pdfplumber

    primitives: list[dict[str, Any]] = []
    object_count = 0
    with pdfplumber.open(io.BytesIO(source_pdf_bytes)) as document:
        if not 1 <= page_index <= len(document.pages):
            raise ValueError("vector chart page is unavailable")
        page = document.pages[page_index - 1]
        collections = (
            ("rectangle", page.rects),
            ("line", page.lines),
            ("curve", page.curves),
        )
        for kind, values in collections:
            for source_index, value in enumerate(values):
                object_count += 1
                if object_count > _MAX_PDF_OBJECTS:
                    break
                if not isinstance(value, Mapping):
                    continue
                raw_box = _pdfplumber_box(value, unit=region_box.unit)
                if raw_box is None:
                    continue
                try:
                    page_box = _box(raw_box, unit=region_box.unit)
                except ValueError:
                    continue
                if not _overlaps(page_box, region_box):
                    continue
                primitives.append(
                    {
                        "kind": kind,
                        "page_bbox": raw_box,
                        "fill": value.get("non_stroking_color"),
                        "stroke": value.get("stroking_color"),
                        "clipping_known": False,
                        "clipped": False,
                        "supported": False,
                        "source_object_id": (
                            f"pdfplumber:p{page_index}:{kind}:{source_index}"
                        ),
                    }
                )
            if object_count > _MAX_PDF_OBJECTS:
                break
    return {
        "transforms": [],
        "panels": [],
        "primitives": primitives[:_MAX_PRIMITIVES],
        "source_object_limit_reached": object_count > _MAX_PDF_OBJECTS,
        "flattened_pdf_evidence": True,
    }


def _transforms(
    raw_values: Any,
    *,
    region: VisualStructure,
) -> tuple[list[VisualTransform], dict[str, str], str]:
    region_box = region.region.page_bbox
    default_matrix = [
        1.0,
        0.0,
        0.0,
        1.0,
        region_box.x,
        region_box.y,
    ]
    if raw_values in (None, []):
        identifier = _stable_id("visual-transform", region.region.id, "region-origin")
        return (
            [
                VisualTransform(
                    id=identifier,
                    source_space="chart_local",
                    target_space="page",
                    matrix=default_matrix,
                    source_transform_ids=["region-origin"],
                )
            ],
            {"region-origin": identifier},
            identifier,
        )
    if (
        not isinstance(raw_values, Sequence)
        or isinstance(raw_values, (str, bytes, bytearray))
        or len(raw_values) > _MAX_TRANSFORMS
    ):
        raise ValueError("vector transforms exceed their entry limit")
    records: dict[str, tuple[str | None, list[float]]] = {}
    order: list[str] = []
    for index, value in enumerate(raw_values):
        if not isinstance(value, Mapping):
            raise ValueError("vector transform must be an object")
        source_id = str(value.get("id") or f"transform-{index}").strip()
        if not source_id or len(source_id) > 128 or source_id in records:
            raise ValueError("vector transform identity is invalid or repeated")
        parent = value.get("parent_id")
        parent_id = str(parent).strip() if parent is not None else None
        records[source_id] = (parent_id, _matrix(value.get("matrix")))
        order.append(source_id)

    composed: dict[str, tuple[list[float], list[str]]] = {}

    def resolve(source_id: str, stack: tuple[str, ...] = ()) -> tuple[list[float], list[str]]:
        if source_id in composed:
            return composed[source_id]
        if source_id in stack or len(stack) >= _MAX_TRANSFORMS:
            raise ValueError("vector transform hierarchy is cyclic or too deep")
        parent_id, matrix = records[source_id]
        if parent_id is None:
            result = (matrix, [source_id])
        else:
            if parent_id not in records:
                raise ValueError("vector transform parent is unknown")
            parent_matrix, chain = resolve(parent_id, (*stack, source_id))
            result = (compose_affine(parent_matrix, matrix), [*chain, source_id])
        composed[source_id] = result
        return result

    output: list[VisualTransform] = []
    source_to_public: dict[str, str] = {}
    for source_id in order:
        matrix, chain = resolve(source_id)
        identifier = _stable_id(
            "visual-transform",
            region.region.id,
            source_id,
            chain,
            matrix,
        )
        source_to_public[source_id] = identifier
        output.append(
            VisualTransform(
                id=identifier,
                source_space="chart_local",
                target_space="page",
                matrix=matrix,
                source_transform_ids=chain,
            )
        )
    return output, source_to_public, source_to_public[order[-1]]


def inventory_vector_chart(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    source_pdf_bytes: bytes | None,
    page_index: int,
    input_kind: str,
) -> VisualStructure:
    """Return a strictly validated inventory without mutating the input."""

    if structure.region.kind != "chart":
        raise ValueError("vector inventory requires a chart-owned region")
    raw = _raw_vector_evidence(item)
    if raw is None:
        if input_kind != "pdf" or source_pdf_bytes is None:
            raw = {"transforms": [], "panels": [], "primitives": []}
        else:
            raw = extract_pdf_vector_evidence(
                source_pdf_bytes,
                page_index=page_index,
                region_box=structure.region.page_bbox,
            )
    ensure_finite_mapping(raw)

    transforms, transform_map, default_transform_id = _transforms(
        raw.get("transforms"),
        region=structure,
    )
    transform_by_id = {transform.id: transform for transform in transforms}
    region_box = structure.region.page_bbox
    public_item_id = structure.evidence[0].provenance.public_item_id
    evidence = list(structure.evidence)
    concerns = list(structure.concerns)

    raw_panels = raw.get("panels")
    if raw_panels in (None, []):
        raw_panels = [
            {
                "source_object_id": "chart-region-panel",
                "page_bbox": region_box.model_dump(mode="json"),
                "chart_local_bbox": {
                    "x": 0.0,
                    "y": 0.0,
                    "width": region_box.width,
                    "height": region_box.height,
                    "unit": region_box.unit,
                },
            }
        ]
    if (
        not isinstance(raw_panels, Sequence)
        or isinstance(raw_panels, (str, bytes, bytearray))
        or not raw_panels
        or len(raw_panels) > _MAX_PANELS
    ):
        raise ValueError("vector panels exceed their entry limit")
    panels: list[ChartPanel] = []
    panel_source_map: dict[str, str] = {}
    for panel_index, raw_panel in enumerate(raw_panels):
        if not isinstance(raw_panel, Mapping):
            raise ValueError("vector panel must be an object")
        source_id = str(
            raw_panel.get("source_object_id") or f"panel-{panel_index}"
        ).strip()
        if not source_id or len(source_id) > 256 or source_id in panel_source_map:
            raise ValueError("vector panel source identity is invalid or repeated")
        local_box = (
            _box(raw_panel.get("chart_local_bbox"), unit=region_box.unit)
            if raw_panel.get("chart_local_bbox") is not None
            else None
        )
        page_box = (
            _box(raw_panel.get("page_bbox"), unit=region_box.unit)
            if raw_panel.get("page_bbox") is not None
            else None
        )
        if local_box is None and page_box is None:
            raise ValueError("vector panel has no geometry")
        if page_box is None and local_box is not None:
            page_box = _transform_box(
                local_box,
                transform_by_id[default_transform_id].matrix,
                unit=region_box.unit,
            )
        if local_box is None and page_box is not None:
            local_box = _local_from_page(page_box, region_box)
        assert local_box is not None and page_box is not None
        if not _contains(region_box, page_box):
            raise ValueError("vector panel leaves its chart-owned region")
        panel_id = _stable_id(
            "chart-panel",
            structure.region.id,
            source_id,
            local_box.model_dump(mode="json"),
            page_box.model_dump(mode="json"),
        )
        evidence_id = _stable_id("visual-evidence", panel_id, source_id)
        evidence.append(
            VisualEvidence(
                id=evidence_id,
                kind="panel",
                page_bbox=page_box,
                chart_local_bbox=local_box,
                transform_ids=[default_transform_id],
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=(input_kind if input_kind in {"pdf", "image"} else "unknown"),
                    source_object_ids=[source_id],
                    source_token_ids=[],
                    extraction_method="vector",
                ),
            )
        )
        panels.append(
            ChartPanel(
                id=panel_id,
                page_bbox=page_box,
                chart_local_bbox=local_box,
                evidence_ids=[evidence_id],
            )
        )
        panel_source_map[source_id] = panel_id

    raw_primitives = raw.get("primitives") or []
    if (
        not isinstance(raw_primitives, Sequence)
        or isinstance(raw_primitives, (str, bytes, bytearray))
    ):
        raise ValueError("vector primitives must be a sequence")
    primitive_limit_reached = len(raw_primitives) > _MAX_PRIMITIVES
    primitives: list[VectorPrimitive] = []
    seen_source_ids: set[str] = set()
    malformed_count = 0
    unsupported_count = 0
    clipped_count = 0
    for primitive_index, raw_primitive in enumerate(raw_primitives[:_MAX_PRIMITIVES]):
        try:
            if not isinstance(raw_primitive, Mapping):
                raise ValueError("vector primitive must be an object")
            kind = str(raw_primitive.get("kind") or "").strip().casefold()
            if kind not in {"curve", "rectangle", "line", "text_anchor"}:
                unsupported_count += 1
                continue
            source_id = str(
                raw_primitive.get("source_object_id")
                or f"primitive-{primitive_index}"
            ).strip()
            if (
                not source_id
                or len(source_id) > 256
                or source_id in seen_source_ids
            ):
                raise ValueError("vector primitive source identity is invalid or repeated")
            seen_source_ids.add(source_id)
            raw_transform_ids = raw_primitive.get("transform_ids")
            if raw_transform_ids is None:
                public_transform_ids = [default_transform_id]
            else:
                if (
                    not isinstance(raw_transform_ids, Sequence)
                    or isinstance(raw_transform_ids, (str, bytes, bytearray))
                    or not 1 <= len(raw_transform_ids) <= 8
                ):
                    raise ValueError("primitive transform references are invalid")
                public_transform_ids = []
                for source_transform_id in raw_transform_ids:
                    mapped = transform_map.get(str(source_transform_id))
                    if mapped is None:
                        raise ValueError("primitive transform reference is unknown")
                    if mapped not in public_transform_ids:
                        public_transform_ids.append(mapped)
            active_transform = transform_by_id[public_transform_ids[-1]]
            local_box = (
                _box(
                    raw_primitive.get("chart_local_bbox"),
                    unit=region_box.unit,
                )
                if raw_primitive.get("chart_local_bbox") is not None
                else None
            )
            page_box = (
                _box(raw_primitive.get("page_bbox"), unit=region_box.unit)
                if raw_primitive.get("page_bbox") is not None
                else None
            )
            if local_box is None and page_box is None:
                raise ValueError("vector primitive has no geometry")
            if page_box is not None and not _overlaps(region_box, page_box):
                # Final public chart ownership is authoritative; neighboring
                # table, form, logo, or decorative objects are ignored.
                continue
            if page_box is None and local_box is not None:
                page_box = _transform_box(
                    local_box,
                    active_transform.matrix,
                    unit=region_box.unit,
                )
            if local_box is None and page_box is not None:
                local_box = _local_from_page(page_box, region_box)
            assert local_box is not None and page_box is not None
            if not _overlaps(region_box, page_box):
                # Neighboring tables/logos/decorations are not chart-owned.
                continue
            clipping_known = raw_primitive.get("clipping_known")
            if not isinstance(clipping_known, bool):
                clipping_known = isinstance(raw_primitive.get("clipped"), bool)
            clipped = raw_primitive.get("clipped") if clipping_known else False
            if not isinstance(clipped, bool):
                raise ValueError("vector clipping state must be boolean")
            declared_supported = raw_primitive.get("supported")
            supported = (
                declared_supported
                if isinstance(declared_supported, bool)
                else clipping_known and not clipped
            )
            supported = bool(supported and clipping_known and not clipped)
            if clipped:
                clipped_count += 1
            if not supported:
                unsupported_count += 1

            explicit_panel = raw_primitive.get("panel_source_object_id")
            panel_id = (
                panel_source_map.get(str(explicit_panel))
                if explicit_panel is not None
                else None
            )
            if explicit_panel is not None and panel_id is None:
                raise ValueError("primitive panel reference is unknown")
            if panel_id is None:
                containing = [
                    panel
                    for panel in panels
                    if _contains(panel.page_bbox, page_box)
                ]
                if not containing:
                    raise ValueError("primitive is not contained by a chart panel")
                containing.sort(
                    key=lambda panel: (
                        panel.page_bbox.width * panel.page_bbox.height,
                        panel.id,
                    )
                )
                panel_id = containing[0].id
            primitive_id = _stable_id(
                "vector-mark",
                structure.region.id,
                source_id,
                kind,
                page_box.model_dump(mode="json"),
                public_transform_ids,
            )
            evidence_id = _stable_id("visual-evidence", primitive_id, source_id)
            evidence.append(
                VisualEvidence(
                    id=evidence_id,
                    kind=("mark" if kind in {"curve", "rectangle"} else "source_object"),
                    page_bbox=page_box,
                    chart_local_bbox=local_box,
                    transform_ids=public_transform_ids,
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=(
                            input_kind
                            if input_kind in {"pdf", "image"}
                            else "unknown"
                        ),
                        source_object_ids=[source_id],
                        source_token_ids=[],
                        extraction_method="vector",
                    ),
                )
            )
            primitives.append(
                VectorPrimitive(
                    id=primitive_id,
                    kind=kind,
                    panel_id=panel_id,
                    page_bbox=page_box,
                    chart_local_bbox=local_box,
                    transform_ids=public_transform_ids,
                    fill=_color(raw_primitive.get("fill")),
                    stroke=_color(raw_primitive.get("stroke")),
                    clipping_known=clipping_known,
                    clipped=clipped,
                    supported=supported,
                    source_object_id=source_id,
                    evidence_ids=[evidence_id],
                )
            )
        except (TypeError, ValueError):
            malformed_count += 1
            continue

    region_evidence_ids = list(structure.region.evidence_ids)
    if raw.get("flattened_pdf_evidence"):
        concerns.append(
            VisualConcern(
                code="vector_clipping_state_unavailable",
                stage="vector_inventory",
                evidence_ids=region_evidence_ids,
            )
        )
    if clipped_count:
        concerns.append(
            VisualConcern(
                code="vector_geometry_clipped",
                stage="vector_inventory",
                evidence_ids=region_evidence_ids,
            )
        )
    if unsupported_count:
        concerns.append(
            VisualConcern(
                code="vector_geometry_unsupported",
                stage="vector_inventory",
                evidence_ids=region_evidence_ids,
            )
        )
    if malformed_count:
        concerns.append(
            VisualConcern(
                code="vector_primitive_malformed",
                stage="vector_inventory",
                evidence_ids=region_evidence_ids,
            )
        )
    if primitive_limit_reached or raw.get("source_object_limit_reached") is True:
        concerns.append(
            VisualConcern(
                code="vector_primitive_limit_reached",
                stage="vector_inventory",
                evidence_ids=region_evidence_ids,
            )
        )

    payload = structure.model_dump(mode="json", exclude_none=True)
    payload["transforms"] = [
        transform.model_dump(mode="json", exclude_none=True)
        for transform in transforms
    ]
    payload["panels"] = [
        panel.model_dump(mode="json", exclude_none=True) for panel in panels
    ]
    payload["evidence"] = [
        record.model_dump(mode="json", exclude_none=True) for record in evidence
    ]
    payload["concerns"] = [
        concern.model_dump(mode="json", exclude_none=True) for concern in concerns
    ]
    payload["vector_inventory"] = VectorInventory(
        primitives=primitives,
        panel_candidate_ids=[panel.id for panel in panels],
        primitive_limit_reached=(
            primitive_limit_reached
            or raw.get("source_object_limit_reached") is True
        ),
    ).model_dump(mode="json", exclude_none=True)
    return VisualStructure.model_validate(payload)


__all__ = [
    "compose_affine",
    "extract_pdf_vector_evidence",
    "inventory_vector_chart",
]
