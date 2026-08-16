"""Serialize the normalized extraction result to deterministic Markdown."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.visual_contracts import VisualStructure
from app.services.visual_model_contracts import VisualModelEvidenceBundle


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError("The extraction result must be a mapping or Pydantic model.")


def _as_primitive(value: Any) -> Any:
    """Recursively detach Pydantic instances before strict revalidation."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _as_primitive(model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {
            str(key): _as_primitive(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_as_primitive(nested) for nested in value]
    return value


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _list_markdown(item: Mapping[str, Any]) -> str:
    ordered = bool(item.get("ordered"))
    lines: list[str] = []
    for index, entry in enumerate(item.get("items") or [], start=1):
        if isinstance(entry, Mapping):
            value = _text(entry.get("value") or entry.get("text"))
            level = max(int(entry.get("level") or 0), 0)
        else:
            value = _text(entry)
            level = 0
        if not value:
            continue
        marker = f"{index}." if ordered and level == 0 else "-"
        lines.append(f"{'  ' * level}{marker} {value}")
    return "\n".join(lines)


def _structured_visual_markdown(item: Mapping[str, Any]) -> str | None:
    """Return an authoritative closed visual projection, when one exists.

    The legacy serializer deliberately fails closed here.  A malformed,
    fallback, or owner-mismatched sidecar must continue through the exact
    predecessor item branch below.
    """

    item_type = _text(item.get("type")).lower()
    if item_type not in {"chart", "diagram"}:
        return None
    raw_structure = item.get("visual_structure")
    model_dump = getattr(raw_structure, "model_dump", None)
    if callable(model_dump):
        raw_structure = model_dump(mode="json")
    if not isinstance(raw_structure, Mapping):
        return None
    try:
        structure = VisualStructure.model_validate(raw_structure, strict=True)
    except (TypeError, ValueError):
        return None
    serialization = structure.serialization
    expected_status = (
        "structured_chart" if item_type == "chart" else "diagram_topology"
    )
    if (
        structure.region.kind != item_type
        or structure.fallback.active
        or serialization is None
        or serialization.status != expected_status
    ):
        return None
    markdown = _text(serialization.markdown)
    if not markdown:
        return None
    # When the owning public item carries its caption directly, the closed
    # projection must attest that it already owns that caption.  This prevents
    # the serializer from accepting a partial projection that would require a
    # second, ad-hoc caption pass.
    if _text(item.get("caption")) and serialization.caption_occurrences != 1:
        return None
    return markdown


def _source_item_markdown(item: Mapping[str, Any]) -> str:
    item_type = _text(item.get("type")).lower()

    structured_visual = _structured_visual_markdown(item)
    if structured_visual is not None:
        return structured_visual

    if item_type == "heading":
        value = _text(item.get("value"))
        if not value:
            return ""
        level = min(max(int(item.get("level") or 1), 1), 6)
        return f"{'#' * level} {value}"

    if item_type == "list":
        return _list_markdown(item)

    if item_type == "table":
        # HTML is intentional: unlike pipe tables, it can retain row/column
        # spans and line breaks from the source document.
        return _text(item.get("html") or item.get("md"))

    if item_type == "code":
        value = _text(item.get("value"))
        language = _text(item.get("language"))
        return f"```{language}\n{value}\n```" if value else ""

    if item_type == "formula":
        value = _text(item.get("value"))
        return f"$$\n{value}\n$$" if value else ""

    if item_type == "image":
        # A layout-detected visual can carry subordinate OCR that should not
        # become document prose (for example, branding inside a photograph).
        # Prefer a source/model caption or the visual's explicit presentation;
        # legacy embedded-image items still fall back to recognized content.
        if item.get("region_role") == "content_region":
            return _text(
                item.get("caption")
                or item.get("md")
                or (
                    item.get("ocr_text")
                    if item.get("include_ocr_in_primary")
                    else None
                )
            )
        return _text(item.get("ocr_text") or item.get("value") or item.get("md"))

    if item_type in {"header", "footer"}:
        # Image reconciliation may replace a near-identical layout/OCR value
        # while retaining the original child nodes as provenance.
        if item.get("layout_value") is not None:
            return _text(item.get("value"))
        children = item.get("items") or []
        values = [
            _text(child.get("value"))
            for child in children
            if isinstance(child, Mapping) and _text(child.get("value"))
        ]
        if values:
            return "\n\n".join(values)

    return _text(item.get("md") or item.get("value"))


def _visual_model_markdown(
    item: Mapping[str, Any],
    *,
    page_index: int | None,
) -> str:
    """Fail closed around the additive model sidecar in legacy projection."""

    if _text(item.get("type")).lower() not in {"image", "chart", "diagram"}:
        return ""
    raw_bundle = item.get("visual_model_evidence")
    if raw_bundle is None:
        return ""
    try:
        bundle = VisualModelEvidenceBundle.model_validate(
            _as_primitive(raw_bundle),
            strict=True,
        )
        if _text(item.get("id")) != bundle.public_item_id:
            return ""
        if page_index is not None and page_index != bundle.page_index:
            return ""
        from app.services.presentation import project_visual_model_evidence

        markdown, _text_output = project_visual_model_evidence(bundle)
        return markdown
    except Exception:
        # A malformed additive channel must not make predecessor serialization
        # unavailable.  The source item is rendered byte-for-byte as before.
        return ""


def _office_fallback_projection(
    item: Mapping[str, Any],
    *,
    field: str,
) -> str:
    raw = item.get("office_visual_fallback")
    if not isinstance(raw, Mapping) or raw.get("status") != "merged":
        return ""
    values: list[str] = []
    for observed in raw.get("items") or []:
        if not isinstance(observed, Mapping) or observed.get("origin") != "rendered":
            continue
        value = _text(observed.get("text"))
        if not value:
            continue
        if field == "markdown" and observed.get("type") == "heading":
            value = f"## {value}"
        values.append(value)
    return "\n\n".join(values)


def _item_markdown(
    item: Mapping[str, Any],
    *,
    page_index: int | None = None,
) -> str:
    source_markdown = _source_item_markdown(item)
    model_markdown = _visual_model_markdown(item, page_index=page_index)
    office_markdown = _office_fallback_projection(item, field="markdown")
    return "\n\n".join(
        value
        for value in (source_markdown, model_markdown, office_markdown)
        if value
    )


def to_markdown(result: Any) -> str:
    """Render pages from the same normalized items returned by the JSON API.

    This deliberately does not add synthetic page comments or image links:
    the supplied reference Markdown concatenates page content directly, while
    page boundaries and image geometry are available in the JSON response.
    """

    document = _as_mapping(result)
    if "canonical_presentation" in document:
        from app.services.presentation import CanonicalPresentation

        canonical = CanonicalPresentation.model_validate(
            _as_primitive(document["canonical_presentation"])
        )
        return canonical.full.markdown

    blocks: list[str] = []
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            page_index = page.get("page_index")
            block = _item_markdown(
                item,
                page_index=(
                    page_index
                    if isinstance(page_index, int) and not isinstance(page_index, bool)
                    else None
                ),
            ).strip()
            if block:
                blocks.append(block)
    return "\n\n".join(blocks).rstrip() + "\n"


def _source_item_text(item: Mapping[str, Any]) -> str:
    item_type = _text(item.get("type")).lower()
    if item_type == "chart" and item.get("office_chart") is not None:
        try:
            from app.services.office_charts import OfficeChartStructure

            raw = _as_primitive(item["office_chart"])
            chart = OfficeChartStructure.model_validate(raw, strict=True)
            lines = [chart.title] if chart.title else []
            lines.extend(
                "\t".join(
                    (point.category, point.series, point.display_value, point.method)
                )
                for point in chart.points
            )
            return "\n".join(lines)
        except (TypeError, ValueError):
            # Additive native-chart data cannot make predecessor text
            # serialization unavailable.
            pass
    if item_type == "list":
        values: list[str] = []
        for entry in item.get("items") or []:
            if isinstance(entry, Mapping):
                value = _text(entry.get("value") or entry.get("text"))
            else:
                value = _text(entry)
            if value:
                values.append(value)
        return "\n".join(values)
    if item_type == "table":
        rows = item.get("rows") or item.get("value") or []
        if isinstance(rows, list):
            rendered_rows = []
            for row in rows:
                if isinstance(row, list):
                    rendered_rows.append("\t".join(_text(cell) for cell in row))
            if rendered_rows:
                return "\n".join(rendered_rows)
    if item_type == "image":
        return _text(
            item.get("caption")
            or item.get("ocr_text")
            or item.get("value")
            or item.get("md")
        )
    return _text(item.get("value") or item.get("text") or item.get("md"))


def to_text(result: Any) -> str:
    """Render a deterministic plain-text projection from public items.

    The projection is additive to the established JSON and Markdown paths and
    intentionally uses the same item order.  When canonical serialization is
    active, its already-validated text view remains authoritative.
    """

    document = _as_mapping(result)
    canonical = document.get("canonical_presentation")
    if canonical is not None:
        from app.services.presentation import CanonicalPresentation

        presentation = CanonicalPresentation.model_validate(_as_primitive(canonical))
        return presentation.full.text

    blocks: list[str] = []
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        page_index = page.get("page_index")
        for item in page.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            source_text = _source_item_text(item)
            model_text = ""
            raw_bundle = item.get("visual_model_evidence")
            if raw_bundle is not None:
                try:
                    bundle = VisualModelEvidenceBundle.model_validate(
                        _as_primitive(raw_bundle), strict=True
                    )
                    if _text(item.get("id")) == bundle.public_item_id and (
                        not isinstance(page_index, int)
                        or isinstance(page_index, bool)
                        or page_index == bundle.page_index
                    ):
                        from app.services.presentation import (
                            project_visual_model_evidence,
                        )

                        _markdown, model_text = project_visual_model_evidence(bundle)
                except Exception:
                    model_text = ""
            combined = "\n\n".join(
                value.strip()
                for value in (
                    source_text,
                    model_text,
                    _office_fallback_projection(item, field="text"),
                )
                if value.strip()
            )
            if combined:
                blocks.append(combined)
    return "\n\n".join(blocks).rstrip() + "\n"
