"""Bounded AcroForm inspection for P03-US06.

The parser in this module deliberately follows only the AcroForm properties
needed to classify widgets.  It never decodes appearance streams and it keeps
all document-derived strings out of diagnostics.  The caller remains
responsible for combining the returned interactive state with static-vector
form evidence.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from pdfminer.pdftypes import PDFObjRef, PDFStream
from pdfminer.psparser import PSLiteral
from pdfminer.utils import decode_text


Interactivity = Literal["none", "interactive", "unknown"]
ControlType = Literal["checkbox", "radio", "unknown"]
ControlState = Literal["checked", "unchecked", "not_applicable", "ambiguous"]
Identity = tuple[Literal["ref"], int, int] | tuple[Literal["direct"], int]


@dataclass(frozen=True, slots=True)
class AcroFormLimits:
    """Frozen P03-US06 AcroForm resource limits."""

    annotations_per_page: int = 2_048
    annotations_per_document: int = 10_000
    field_nodes: int = 10_000
    field_depth: int = 32
    kids_per_node: int = 256
    dictionary_entries: int = 256
    visited_references: int = 32_768
    resolution_steps: int = 65_536
    name_bytes: int = 256
    string_bytes: int = 16 * 1024
    object_bytes: int = 256 * 1024
    tree_bytes: int = 8 * 1024 * 1024


DEFAULT_LIMITS = AcroFormLimits()


@dataclass(frozen=True, slots=True)
class AcroFormPageInput:
    """The bounded page information required by AcroForm inspection."""

    page_index: int
    width: float
    height: float
    annotations: object
    annotations_present: bool = True
    rotation: int = 0
    page_object_id: int | None = None
    media_box: object | None = None
    crop_box: object | None = None
    user_unit: object = 1.0


@dataclass(frozen=True, slots=True)
class InteractiveControlEvidence:
    """Source-grounded evidence for one non-pushbutton widget."""

    page_index: int
    annotation_index: int
    bbox: tuple[float, float, float, float]
    object_ref_digest: str
    field_ref_digest: str
    field_name: str | None
    control_type: ControlType
    state: ControlState
    concern_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcroFormPageInspection:
    page_index: int
    interactivity: Interactivity
    controls: tuple[InteractiveControlEvidence, ...]
    concern_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcroFormInspection:
    interactivity: Interactivity
    pages: tuple[AcroFormPageInspection, ...]
    concern_codes: tuple[str, ...]
    field_node_count: int
    visited_reference_count: int
    resolution_step_count: int
    accounted_tree_bytes: int


@dataclass(frozen=True, slots=True)
class AcroFormLimitResult:
    accepted: bool
    violated_limit: str | None


class AcroFormInspectionError(ValueError):
    """A sanitized fail-closed AcroForm refusal."""

    def __init__(self, code: str = "form_interactivity_unknown") -> None:
        super().__init__("AcroForm inspection failed closed")
        self.code = code


class _AcroFormLimitError(AcroFormInspectionError):
    def __init__(self, limit_name: str) -> None:
        super().__init__("form_source_limit")
        self.limit_name = limit_name


@dataclass(slots=True)
class _FieldNode:
    identity: Identity
    value: Mapping[str, Any]
    parent_identity: Identity | None
    source_ref: PDFObjRef | None


@dataclass(slots=True)
class _AfobFrame:
    container: object
    children: Sequence[object]
    next_index: int
    total: int


class _InspectionContext:
    def __init__(
        self,
        *,
        resolver: Callable[[PDFObjRef], object],
        limits: AcroFormLimits,
        deadline_at: float,
    ) -> None:
        self.resolver = resolver
        self.limits = limits
        self.deadline_at = deadline_at
        self.cache: dict[tuple[int, int], object] = {}
        self.accounted_references: set[tuple[int, int]] = set()
        self.visited_references: set[tuple[int, int]] = set()
        self.resolution_steps = 0
        self.tree_bytes = 0
        self.radio_export_cache: dict[
            tuple[Identity, str | None],
            frozenset[str],
        ] = {}
        self.children_by_parent: dict[Identity, list[_FieldNode]] = {}

    def check_deadline(self) -> None:
        if time.monotonic() > self.deadline_at:
            raise AcroFormInspectionError("form_source_evidence_unavailable")

    def resolve(
        self,
        value: object,
        *,
        active_references: frozenset[tuple[int, int]] = frozenset(),
    ) -> object:
        if not isinstance(value, PDFObjRef):
            return value
        self.check_deadline()
        reference = _reference_identity(value)
        if reference not in self.visited_references:
            self.visited_references.add(reference)
            if len(self.visited_references) > self.limits.visited_references:
                raise _AcroFormLimitError("acroform_max_visited_references")
        self.resolution_steps += 1
        if self.resolution_steps > self.limits.resolution_steps:
            raise _AcroFormLimitError("acroform_max_resolution_steps")
        if reference in active_references:
            raise AcroFormInspectionError()
        if reference in self.cache:
            return self.cache[reference]
        try:
            resolved = self.resolver(value)
        except Exception as exc:
            raise AcroFormInspectionError() from exc
        self.check_deadline()
        if resolved is value or isinstance(resolved, PDFObjRef):
            raise AcroFormInspectionError()
        size = _afob_v1_size(
            resolved,
            self.limits,
            deadline_check=self.check_deadline,
        )
        self.check_deadline()
        if reference not in self.accounted_references:
            self.accounted_references.add(reference)
            self.tree_bytes += size
            if self.tree_bytes > self.limits.tree_bytes:
                raise _AcroFormLimitError("acroform_max_tree_bytes")
        self.cache[reference] = resolved
        return resolved

    def account_direct_root(self, value: object) -> None:
        self.check_deadline()
        self.tree_bytes += _afob_v1_size(
            value,
            self.limits,
            deadline_check=self.check_deadline,
        )
        if self.tree_bytes > self.limits.tree_bytes:
            raise _AcroFormLimitError("acroform_max_tree_bytes")

    def register_field_node(self, node: _FieldNode) -> None:
        self.check_deadline()
        if node.parent_identity is not None:
            self.children_by_parent.setdefault(
                node.parent_identity,
                [],
            ).append(node)


def inspect_acroform(
    *,
    catalog: Mapping[str, Any],
    pages: Sequence[AcroFormPageInput],
    source_sha256: str,
    resolver: Callable[[PDFObjRef], object] | None = None,
    limits: AcroFormLimits = DEFAULT_LIMITS,
    deadline_seconds: float = 2.0,
) -> AcroFormInspection:
    """Inspect a catalog field tree and page annotations with frozen limits."""

    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_sha256)
    ):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(catalog, Mapping):
        raise ValueError("catalog must be a mapping")
    if (
        isinstance(deadline_seconds, bool)
        or not isinstance(deadline_seconds, (int, float))
        or not math.isfinite(float(deadline_seconds))
        or deadline_seconds <= 0
    ):
        raise ValueError("deadline_seconds must be finite and positive")
    page_inputs = tuple(pages)
    if len({page.page_index for page in page_inputs}) != len(page_inputs):
        raise ValueError("page indexes must be unique")
    if any(page.page_index < 1 for page in page_inputs):
        raise ValueError("page indexes must be positive")
    if any(
        not isinstance(page.annotations_present, bool)
        for page in page_inputs
    ):
        raise ValueError("annotations_present must be a boolean")
    if any(
        page.page_object_id is not None
        and (
            isinstance(page.page_object_id, bool)
            or not isinstance(page.page_object_id, int)
            or page.page_object_id < 1
        )
        for page in page_inputs
    ):
        raise ValueError("page object IDs must be positive integers")

    resolver_fn = resolver or (lambda reference: reference.resolve())
    context = _InspectionContext(
        resolver=resolver_fn,
        limits=limits,
        deadline_at=time.monotonic() + float(deadline_seconds),
    )
    empty_pages = tuple(
        AcroFormPageInspection(
            page_index=page.page_index,
            interactivity="none",
            controls=(),
            concern_codes=(),
        )
        for page in page_inputs
    )
    raw_acroform = catalog.get("AcroForm")
    try:
        field_nodes: dict[Identity, _FieldNode] = {}
        if raw_acroform is not None:
            acroform = context.resolve(raw_acroform)
            if not isinstance(raw_acroform, PDFObjRef):
                context.account_direct_root(acroform)
            if not isinstance(acroform, Mapping):
                raise AcroFormInspectionError()
            raw_fields = acroform.get("Fields", ())
            fields = context.resolve(raw_fields)
            if not isinstance(fields, (list, tuple)):
                raise AcroFormInspectionError()
            for root in fields:
                _visit_field_node(
                    root,
                    depth=0,
                    expected_parent=None,
                    active=(),
                    nodes=field_nodes,
                    context=context,
                )
            validated_field_count = _validate_terminal_fields(
                field_nodes,
                context=context,
            )
        else:
            validated_field_count = 0

        (
            page_results,
            seen_widgets,
            unknown_page_object_ids,
            unknown_annotation_identities,
            orphan_widget_count,
        ) = _inspect_page_annotations(
            page_inputs,
            field_nodes=field_nodes,
            source_sha256=source_sha256,
            context=context,
        )
        unowned_tree_widgets = {
            identity
            for identity, node in field_nodes.items()
            if node.value.get("Subtype") is not None
            and _pdf_name(node.value["Subtype"], context=context) == "Widget"
            and not _node_belongs_to_page_ids(
                node,
                unknown_page_object_ids,
            )
            and identity not in unknown_annotation_identities
        } - seen_widgets
        if unowned_tree_widgets:
            raise AcroFormInspectionError()
    except AcroFormInspectionError as exc:
        concerns = (exc.code,)
        unknown_pages = tuple(
            AcroFormPageInspection(
                page_index=page.page_index,
                interactivity="unknown",
                controls=(),
                concern_codes=concerns,
            )
            for page in page_inputs
        )
        return AcroFormInspection(
            interactivity="unknown",
            pages=unknown_pages,
            concern_codes=concerns,
            field_node_count=len(field_nodes),
            visited_reference_count=len(context.visited_references),
            resolution_step_count=context.resolution_steps,
            accounted_tree_bytes=context.tree_bytes,
        )

    states = {page.interactivity for page in page_results}
    interactivity: Interactivity
    if "unknown" in states:
        interactivity = "unknown"
    elif "interactive" in states or validated_field_count:
        interactivity = "interactive"
    else:
        interactivity = "none"
    concerns = tuple(
        dict.fromkeys(
            code for page in page_results for code in page.concern_codes
        )
    )
    return AcroFormInspection(
        interactivity=interactivity,
        pages=page_results if page_results else empty_pages,
        concern_codes=concerns,
        field_node_count=len(field_nodes) + orphan_widget_count,
        visited_reference_count=len(context.visited_references),
        resolution_step_count=context.resolution_steps,
        accounted_tree_bytes=context.tree_bytes,
    )


def _visit_field_node(
    raw_node: object,
    *,
    depth: int,
    expected_parent: Identity | None,
    active: tuple[Identity, ...],
    nodes: dict[Identity, _FieldNode],
    context: _InspectionContext,
) -> None:
    context.check_deadline()
    reference = raw_node if isinstance(raw_node, PDFObjRef) else None
    provisional_identity: Identity | None = None
    if reference is not None:
        objid, genno = _reference_identity(reference)
        provisional_identity = ("ref", objid, genno)
    elif isinstance(raw_node, Mapping):
        provisional_identity = ("direct", id(raw_node))
    if provisional_identity is not None:
        if provisional_identity in active or provisional_identity in nodes:
            raise AcroFormInspectionError()
        if len(nodes) + 1 > context.limits.field_nodes:
            raise _AcroFormLimitError("acroform_max_nodes")
    if depth > context.limits.field_depth:
        raise _AcroFormLimitError("acroform_max_depth")
    active_references = frozenset(
        (identity[1], identity[2])
        for identity in active
        if identity[0] == "ref"
    )
    resolved = context.resolve(
        raw_node,
        active_references=active_references,
    )
    if not isinstance(resolved, Mapping):
        raise AcroFormInspectionError()
    identity = _object_identity(reference, resolved)
    if identity in active or identity in nodes:
        raise AcroFormInspectionError()
    if (
        provisional_identity is None
        and len(nodes) + 1 > context.limits.field_nodes
    ):
        raise _AcroFormLimitError("acroform_max_nodes")

    raw_parent = resolved.get("Parent")
    actual_parent: Identity | None = None
    if raw_parent is not None:
        parent_value = context.resolve(raw_parent)
        if not isinstance(parent_value, Mapping):
            raise AcroFormInspectionError()
        actual_parent = _object_identity(
            raw_parent if isinstance(raw_parent, PDFObjRef) else None,
            parent_value,
        )
    if actual_parent != expected_parent:
        raise AcroFormInspectionError()

    node = _FieldNode(
        identity=identity,
        value=resolved,
        parent_identity=actual_parent,
        source_ref=reference,
    )
    nodes[identity] = node
    context.register_field_node(node)
    raw_kids = resolved.get("Kids", ())
    kids = context.resolve(raw_kids)
    if not isinstance(kids, (list, tuple)):
        raise AcroFormInspectionError()
    if len(kids) > context.limits.kids_per_node:
        raise _AcroFormLimitError("acroform_max_kids_per_node")
    next_active = (*active, identity)
    for raw_kid in kids:
        _visit_field_node(
            raw_kid,
            depth=depth + 1,
            expected_parent=identity,
            active=next_active,
            nodes=nodes,
            context=context,
        )


def _inspect_page_annotations(
    pages: Sequence[AcroFormPageInput],
    *,
    field_nodes: Mapping[Identity, _FieldNode],
    source_sha256: str,
    context: _InspectionContext,
) -> tuple[
    tuple[AcroFormPageInspection, ...],
    set[Identity],
    set[int],
    set[Identity],
    int,
]:
    document_annotation_count = 0
    seen_widgets: set[Identity] = set()
    widget_first_pages: dict[Identity, int] = {}
    duplicate_widget_pages: set[int] = set()
    unknown_page_object_ids: set[int] = set()
    unknown_annotation_identities: set[Identity] = set()
    orphan_widgets: set[Identity] = set()
    lookup_nodes = dict(field_nodes)
    results: list[AcroFormPageInspection] = []
    shallow_page_identities: dict[int, set[Identity]] = {}
    for page in pages:
        context.check_deadline()
        page_occurrence_identities = _annotation_occurrence_identities(
            page.annotations,
            maximum=context.limits.annotations_per_page,
            context=context,
        )
        shallow_page_identities[page.page_index] = set(
            page_occurrence_identities
        )
        try:
            raw_annotations = context.resolve(page.annotations)
        except _AcroFormLimitError:
            raise
        except AcroFormInspectionError as exc:
            if exc.code == "form_source_evidence_unavailable":
                raise
            results.append(_unknown_page(page.page_index, exc.code))
            if page.page_object_id is not None:
                unknown_page_object_ids.add(page.page_object_id)
            unknown_annotation_identities.update(page_occurrence_identities)
            continue
        if not isinstance(raw_annotations, (list, tuple)):
            results.append(
                _unknown_page(
                    page.page_index,
                    "form_interactivity_unknown",
                )
            )
            if page.page_object_id is not None:
                unknown_page_object_ids.add(page.page_object_id)
            unknown_annotation_identities.update(page_occurrence_identities)
            continue
        annotation_count = len(raw_annotations)
        document_annotation_count += annotation_count
        if annotation_count > context.limits.annotations_per_page:
            results.append(_unknown_page(page.page_index, "form_source_limit"))
            if page.page_object_id is not None:
                unknown_page_object_ids.add(page.page_object_id)
            # Ownership cannot be complete for an over-cap page.  Suppress
            # later unowned-tree escalation without scanning the hostile
            # annotation array.
            unknown_annotation_identities.update(field_nodes)
            continue
        if document_annotation_count > context.limits.annotations_per_document:
            raise _AcroFormLimitError("max_annotations_widgets_per_document")
        page_occurrence_identities.update(
            _annotation_occurrence_identities(
                raw_annotations,
                maximum=context.limits.annotations_per_page,
                context=context,
            )
        )
        shallow_page_identities[page.page_index] = set(
            page_occurrence_identities
        )
        if (
            page.annotations_present
            and not isinstance(page.annotations, PDFObjRef)
        ):
            context.account_direct_root(raw_annotations)
        controls: list[InteractiveControlEvidence] = []
        page_unknown = False
        page_concerns: list[str] = []
        validated_widget = False
        for annotation_index, raw in enumerate(raw_annotations):
            if annotation_index % 128 == 0:
                context.check_deadline()
            try:
                resolved = context.resolve(raw)
            except _AcroFormLimitError:
                raise
            except AcroFormInspectionError as exc:
                if exc.code == "form_source_evidence_unavailable":
                    raise
                page_unknown = True
                page_concerns.append(exc.code)
                continue
            if not isinstance(resolved, Mapping):
                page_unknown = True
                page_concerns.append("form_interactivity_unknown")
                continue
            try:
                subtype = _pdf_name(
                    resolved.get("Subtype"),
                    context=context,
                )
            except _AcroFormLimitError:
                raise
            except AcroFormInspectionError as exc:
                if exc.code == "form_source_evidence_unavailable":
                    raise
                page_unknown = True
                page_concerns.append(exc.code)
                continue
            if subtype != "Widget":
                continue
            identity = _object_identity(
                raw if isinstance(raw, PDFObjRef) else None,
                resolved,
            )
            first_page = widget_first_pages.get(identity)
            if first_page is not None:
                duplicate_widget_pages.update(
                    (first_page, page.page_index)
                )
                page_unknown = True
                page_concerns.append("form_interactivity_unknown")
                continue
            widget_first_pages[identity] = page.page_index
            seen_widgets.add(identity)
            node = field_nodes.get(identity)
            if node is None:
                orphan_widgets.add(identity)
                if (
                    len(field_nodes) + len(orphan_widgets)
                    > context.limits.field_nodes
                ):
                    raise _AcroFormLimitError("acroform_max_nodes")
                page_unknown = True
                page_concerns.append("form_interactivity_unknown")
                fallback_orphan_node = _FieldNode(
                    identity=identity,
                    value={
                        key: value
                        for key, value in resolved.items()
                        if key != "Parent"
                    },
                    parent_identity=None,
                    source_ref=(
                        raw if isinstance(raw, PDFObjRef) else None
                    ),
                )
                orphan_node = fallback_orphan_node
                try:
                    orphan_node = _orphan_field_node(
                        raw,
                        resolved,
                        identity=identity,
                        context=context,
                    )
                    lookup_nodes[identity] = orphan_node
                    context.register_field_node(orphan_node)
                    control = _inspect_widget(
                        orphan_node,
                        page_index=page.page_index,
                        annotation_index=annotation_index,
                        page_width=page.width,
                        page_height=page.height,
                        page_rotation=page.rotation,
                        page_object_id=page.page_object_id,
                        media_box=page.media_box,
                        crop_box=page.crop_box,
                        user_unit=page.user_unit,
                        nodes=lookup_nodes,
                        source_sha256=source_sha256,
                        context=context,
                    )
                    if control is None:
                        control = _ambiguous_widget_evidence(
                            fallback_orphan_node,
                            page_index=page.page_index,
                            annotation_index=annotation_index,
                            page_width=page.width,
                            page_height=page.height,
                            page_rotation=page.rotation,
                            page_object_id=page.page_object_id,
                            media_box=page.media_box,
                            crop_box=page.crop_box,
                            user_unit=page.user_unit,
                            nodes=lookup_nodes,
                            source_sha256=source_sha256,
                            context=context,
                        )
                except _AcroFormLimitError:
                    raise
                except AcroFormInspectionError as exc:
                    if exc.code == "form_source_evidence_unavailable":
                        raise
                    page_concerns.append(exc.code)
                    try:
                        control = _ambiguous_widget_evidence(
                            fallback_orphan_node,
                            page_index=page.page_index,
                            annotation_index=annotation_index,
                            page_width=page.width,
                            page_height=page.height,
                            page_rotation=page.rotation,
                            page_object_id=page.page_object_id,
                            media_box=page.media_box,
                            crop_box=page.crop_box,
                            user_unit=page.user_unit,
                            nodes=lookup_nodes,
                            source_sha256=source_sha256,
                            context=context,
                        )
                    except _AcroFormLimitError:
                        raise
                    except AcroFormInspectionError as fallback_exc:
                        if (
                            fallback_exc.code
                            == "form_source_evidence_unavailable"
                        ):
                            raise
                        page_concerns.append(fallback_exc.code)
                        continue
                if control is not None:
                    controls.append(
                        replace(
                            control,
                            field_name=None,
                            state="ambiguous",
                            concern_codes=(
                                "form_control_state_ambiguous",
                            ),
                        )
                    )
                continue
            validated_widget = True
            try:
                control = _inspect_widget(
                    node,
                    page_index=page.page_index,
                    annotation_index=annotation_index,
                    page_width=page.width,
                    page_height=page.height,
                    page_rotation=page.rotation,
                    page_object_id=page.page_object_id,
                    media_box=page.media_box,
                    crop_box=page.crop_box,
                    user_unit=page.user_unit,
                    nodes=lookup_nodes,
                    source_sha256=source_sha256,
                    context=context,
                )
            except _AcroFormLimitError:
                raise
            except AcroFormInspectionError as exc:
                if exc.code == "form_source_evidence_unavailable":
                    raise
                page_unknown = True
                page_concerns.append(exc.code)
                try:
                    control = _ambiguous_widget_evidence(
                        node,
                        page_index=page.page_index,
                        annotation_index=annotation_index,
                        page_width=page.width,
                        page_height=page.height,
                        page_rotation=page.rotation,
                        page_object_id=page.page_object_id,
                        media_box=page.media_box,
                        crop_box=page.crop_box,
                        user_unit=page.user_unit,
                        nodes=lookup_nodes,
                        source_sha256=source_sha256,
                        context=context,
                    )
                except _AcroFormLimitError:
                    raise
                except AcroFormInspectionError as fallback_exc:
                    if (
                        fallback_exc.code
                        == "form_source_evidence_unavailable"
                    ):
                        raise
                    page_concerns.append(fallback_exc.code)
                    continue
            if control is not None:
                controls.append(control)
                if control.state == "ambiguous":
                    page_unknown = True
                    page_concerns.append("form_interactivity_unknown")
        controls.sort(
            key=lambda item: (
                item.bbox[1],
                item.bbox[0],
                item.annotation_index,
                item.object_ref_digest,
            )
        )
        if page_unknown:
            state: Interactivity = "unknown"
            concerns = tuple(
                dict.fromkeys(
                    page_concerns or ("form_interactivity_unknown",)
                )
            )
            unknown_annotation_identities.update(
                page_occurrence_identities
            )
            if page.page_object_id is not None:
                unknown_page_object_ids.add(page.page_object_id)
        elif validated_widget:
            state = "interactive"
            concerns = ()
        else:
            state = "none"
            concerns = ()
        results.append(
            AcroFormPageInspection(
                page_index=page.page_index,
                interactivity=state,
                controls=tuple(controls),
                concern_codes=concerns,
            )
        )
    if duplicate_widget_pages:
        results = [
            (
                replace(
                    result,
                    interactivity="unknown",
                    concern_codes=tuple(
                        dict.fromkeys(
                            (
                                *result.concern_codes,
                                "form_interactivity_unknown",
                            )
                        )
                    ),
                )
                if result.page_index in duplicate_widget_pages
                else result
            )
            for result in results
        ]
        for page in pages:
            if page.page_index not in duplicate_widget_pages:
                continue
            if page.page_object_id is not None:
                unknown_page_object_ids.add(page.page_object_id)
            unknown_annotation_identities.update(
                shallow_page_identities[page.page_index]
            )
    return (
        tuple(results),
        seen_widgets,
        unknown_page_object_ids,
        unknown_annotation_identities,
        len(orphan_widgets),
    )


def _annotation_occurrence_identities(
    raw_annotations: object,
    *,
    maximum: int,
    context: _InspectionContext,
) -> set[Identity]:
    if not isinstance(raw_annotations, (list, tuple)):
        return set()
    if len(raw_annotations) > maximum:
        return set()
    identities: set[Identity] = set()
    for index, raw in enumerate(raw_annotations):
        if index % 128 == 0:
            context.check_deadline()
        if isinstance(raw, PDFObjRef):
            objid, genno = _reference_identity(raw)
            identities.add(("ref", objid, genno))
        elif isinstance(raw, Mapping):
            identities.add(("direct", id(raw)))
    return identities


def _orphan_field_node(
    raw: object,
    resolved: Mapping[str, Any],
    *,
    identity: Identity,
    context: _InspectionContext,
) -> _FieldNode:
    raw_parent = resolved.get("Parent")
    parent_identity: Identity | None = None
    if raw_parent is not None:
        parent = context.resolve(raw_parent)
        if not isinstance(parent, Mapping):
            raise AcroFormInspectionError()
        parent_identity = _object_identity(
            raw_parent if isinstance(raw_parent, PDFObjRef) else None,
            parent,
        )
    return _FieldNode(
        identity=identity,
        value=resolved,
        parent_identity=parent_identity,
        source_ref=raw if isinstance(raw, PDFObjRef) else None,
    )


def _unknown_page(
    page_index: int,
    concern_code: str,
) -> AcroFormPageInspection:
    return AcroFormPageInspection(
        page_index=page_index,
        interactivity="unknown",
        controls=(),
        concern_codes=(concern_code,),
    )


def _node_belongs_to_page_ids(
    node: _FieldNode,
    page_object_ids: set[int],
) -> bool:
    raw_page = node.value.get("P")
    return (
        isinstance(raw_page, PDFObjRef)
        and int(raw_page.objid) in page_object_ids
    )


def _validate_terminal_fields(
    nodes: Mapping[Identity, _FieldNode],
    *,
    context: _InspectionContext,
) -> int:
    validated = 0
    for node in nodes.values():
        context.check_deadline()
        raw_kids = node.value.get("Kids", ())
        kids = context.resolve(raw_kids)
        if not isinstance(kids, (list, tuple)):
            raise AcroFormInspectionError()
        if kids:
            continue
        raw_subtype = node.value.get("Subtype")
        if (
            raw_subtype is not None
            and _pdf_name(raw_subtype, context=context) != "Widget"
        ):
            raise AcroFormInspectionError()
        chain = _inheritance_chain(node, nodes=nodes, context=context)
        if (
            _inherited_name(
                chain,
                "FT",
                context=context,
                forbidden_references=_chain_reference_identities(chain),
            )
            is None
        ):
            raise AcroFormInspectionError()
        validated += 1
    return validated


def _inspect_widget(
    widget: _FieldNode,
    *,
    page_index: int,
    annotation_index: int,
    page_width: float,
    page_height: float,
    page_rotation: int,
    page_object_id: int | None,
    media_box: object | None,
    crop_box: object | None,
    user_unit: object,
    nodes: Mapping[Identity, _FieldNode],
    source_sha256: str,
    context: _InspectionContext,
) -> InteractiveControlEvidence | None:
    chain = _inheritance_chain(widget, nodes=nodes, context=context)
    forbidden_references = _chain_reference_identities(chain)
    _validate_user_unit(
        user_unit,
        context=context,
        forbidden_references=forbidden_references,
    )
    _validate_page_owner(widget.value.get("P"), page_object_id=page_object_id)
    bbox = _widget_bbox(
        widget.value.get("Rect"),
        page_width=page_width,
        page_height=page_height,
        page_rotation=page_rotation,
        media_box=media_box,
        crop_box=crop_box,
        context=context,
        forbidden_references=forbidden_references,
    )
    field_type = _inherited_name(
        chain,
        "FT",
        context=context,
        forbidden_references=forbidden_references,
    )
    if field_type is None:
        raise AcroFormInspectionError()
    field_flags = _inherited_integer(
        chain,
        "Ff",
        context=context,
        default=0,
        forbidden_references=forbidden_references,
    )
    if field_type != "Btn":
        return None
    if field_flags & (1 << 16):
        return None
    control_type: ControlType = (
        "radio" if field_flags & (1 << 15) else "checkbox"
    )
    field_value = _inherited_name(
        chain,
        "V",
        context=context,
        forbidden_references=forbidden_references,
    )
    appearance_state = _optional_name(
        widget.value.get("AS"),
        context=context,
        forbidden_references=forbidden_references,
    )
    (
        appearance_names,
        appearance_absent,
        appearance_resolved,
    ) = _appearance_names(
        widget.value.get("AP"),
        context=context,
        forbidden_references=forbidden_references,
    )
    field_export_names = (
        _radio_export_names(
            widget,
            chain=chain,
            context=context,
            forbidden_references=forbidden_references,
            field_value=field_value,
        )
        if control_type == "radio"
        else frozenset(
            name for name in appearance_names if name != "Off"
        )
    )
    state = _control_state(
        control_type=control_type,
        field_value=field_value,
        appearance_state=appearance_state,
        appearance_names=appearance_names,
        appearance_absent=appearance_absent,
        appearance_resolved=appearance_resolved,
        field_export_names=field_export_names,
    )
    field_name = _inherited_text(
        chain,
        "T",
        context=context,
        forbidden_references=forbidden_references,
    )
    widget_digest = _source_digest(
        source_sha256,
        "widget",
        widget.identity,
        page_index=page_index,
        annotation_index=annotation_index,
    )
    field_node = _field_owner(chain)
    field_digest = _source_digest(
        source_sha256,
        "field",
        field_node.identity,
        page_index=page_index,
        annotation_index=annotation_index,
    )
    concerns = (
        ("form_control_state_ambiguous",) if state == "ambiguous" else ()
    )
    return InteractiveControlEvidence(
        page_index=page_index,
        annotation_index=annotation_index,
        bbox=bbox,
        object_ref_digest=widget_digest,
        field_ref_digest=field_digest,
        field_name=field_name,
        control_type=control_type,
        state=state,
        concern_codes=concerns,
    )


def _ambiguous_widget_evidence(
    widget: _FieldNode,
    *,
    page_index: int,
    annotation_index: int,
    page_width: float,
    page_height: float,
    page_rotation: int,
    page_object_id: int | None,
    media_box: object | None,
    crop_box: object | None,
    user_unit: object,
    nodes: Mapping[Identity, _FieldNode],
    source_sha256: str,
    context: _InspectionContext,
) -> InteractiveControlEvidence:
    chain = _inheritance_chain(widget, nodes=nodes, context=context)
    forbidden_references = _chain_reference_identities(chain)
    _validate_user_unit(
        user_unit,
        context=context,
        forbidden_references=forbidden_references,
    )
    _validate_page_owner(widget.value.get("P"), page_object_id=page_object_id)
    bbox = _widget_bbox(
        widget.value.get("Rect"),
        page_width=page_width,
        page_height=page_height,
        page_rotation=page_rotation,
        media_box=media_box,
        crop_box=crop_box,
        context=context,
        forbidden_references=forbidden_references,
    )
    control_type: ControlType = "unknown"
    try:
        field_type = _inherited_name(
            chain,
            "FT",
            context=context,
            forbidden_references=forbidden_references,
        )
        field_flags = _inherited_integer(
            chain,
            "Ff",
            context=context,
            default=0,
            forbidden_references=forbidden_references,
        )
        if field_type == "Btn":
            control_type = (
                "radio" if field_flags & (1 << 15) else "checkbox"
            )
    except _AcroFormLimitError:
        raise
    except AcroFormInspectionError as exc:
        if exc.code == "form_source_evidence_unavailable":
            raise
    try:
        field_node = _field_owner(chain)
    except AcroFormInspectionError:
        field_node = widget
    return InteractiveControlEvidence(
        page_index=page_index,
        annotation_index=annotation_index,
        bbox=bbox,
        object_ref_digest=_source_digest(
            source_sha256,
            "widget",
            widget.identity,
            page_index=page_index,
            annotation_index=annotation_index,
        ),
        field_ref_digest=_source_digest(
            source_sha256,
            "field",
            field_node.identity,
            page_index=page_index,
            annotation_index=annotation_index,
        ),
        field_name=None,
        control_type=control_type,
        state="ambiguous",
        concern_codes=("form_control_state_ambiguous",),
    )


def _inheritance_chain(
    node: _FieldNode,
    *,
    nodes: Mapping[Identity, _FieldNode],
    context: _InspectionContext,
) -> tuple[_FieldNode, ...]:
    chain: list[_FieldNode] = []
    active: set[Identity] = set()
    current = node
    while True:
        if current.identity in active:
            raise AcroFormInspectionError()
        active.add(current.identity)
        chain.append(current)
        raw_parent = current.value.get("Parent")
        if raw_parent is None:
            break
        active_references = frozenset(
            (identity[1], identity[2])
            for identity in active
            if identity[0] == "ref" and identity != current.identity
        )
        parent_value = context.resolve(
            raw_parent,
            active_references=active_references,
        )
        if not isinstance(parent_value, Mapping):
            raise AcroFormInspectionError()
        parent_identity = _object_identity(
            raw_parent if isinstance(raw_parent, PDFObjRef) else None,
            parent_value,
        )
        parent = nodes.get(parent_identity)
        if parent is None:
            raise AcroFormInspectionError()
        current = parent
    return tuple(chain)


def _chain_reference_identities(
    chain: Sequence[_FieldNode],
) -> frozenset[tuple[int, int]]:
    return frozenset(
        (node.identity[1], node.identity[2])
        for node in chain
        if node.identity[0] == "ref"
    )


def _field_owner(chain: Sequence[_FieldNode]) -> _FieldNode:
    if not chain:
        raise AcroFormInspectionError()
    widget = chain[0]
    merged_field_keys = {
        "FT",
        "T",
        "TU",
        "TM",
        "Ff",
        "V",
        "DV",
        "Opt",
        "MaxLen",
    }
    if len(chain) == 1 or merged_field_keys.intersection(widget.value):
        return widget
    return chain[1]


def _inherited_name(
    chain: Sequence[_FieldNode],
    key: str,
    *,
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]] = frozenset(),
) -> str | None:
    for node in chain:
        if key in node.value:
            return _pdf_name(
                node.value[key],
                context=context,
                forbidden_references=forbidden_references,
            )
    return None


def _optional_name(
    value: object,
    *,
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]] = frozenset(),
) -> str | None:
    if value is None:
        return None
    return _pdf_name(
        value,
        context=context,
        forbidden_references=forbidden_references,
    )


def _inherited_integer(
    chain: Sequence[_FieldNode],
    key: str,
    *,
    context: _InspectionContext,
    default: int,
    forbidden_references: frozenset[tuple[int, int]] = frozenset(),
) -> int:
    for node in chain:
        if key not in node.value:
            continue
        value = context.resolve(
            node.value[key],
            active_references=forbidden_references,
        )
        if isinstance(value, bool) or not isinstance(value, int):
            raise AcroFormInspectionError()
        return value
    return default


def _inherited_text(
    chain: Sequence[_FieldNode],
    key: str,
    *,
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]] = frozenset(),
) -> str | None:
    for node in chain:
        if key not in node.value:
            continue
        value = context.resolve(
            node.value[key],
            active_references=forbidden_references,
        )
        if isinstance(value, bytes):
            try:
                text = decode_text(value)
            except (TypeError, UnicodeError, ValueError) as exc:
                raise AcroFormInspectionError() from exc
        elif isinstance(value, str):
            text = value
        else:
            raise AcroFormInspectionError()
        if not text or len(_utf8_bytes(text)) > context.limits.string_bytes:
            raise AcroFormInspectionError()
        return text
    return None


def _appearance_names(
    raw_appearance: object,
    *,
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]] = frozenset(),
) -> tuple[tuple[str, ...], bool, bool]:
    if raw_appearance is None:
        return (), True, True
    appearance = context.resolve(
        raw_appearance,
        active_references=forbidden_references,
    )
    if not isinstance(appearance, Mapping) or "N" not in appearance:
        raise AcroFormInspectionError()
    appearance_references = set(forbidden_references)
    if isinstance(raw_appearance, PDFObjRef):
        appearance_references.add(_reference_identity(raw_appearance))
    normal = context.resolve(
        appearance["N"],
        active_references=frozenset(appearance_references),
    )
    if isinstance(normal, PDFStream):
        return (), False, False
    if not isinstance(normal, Mapping):
        raise AcroFormInspectionError()
    names = tuple(
        _name_payload(key, context.limits)
        for key in normal
    )
    if len(names) != len(set(names)):
        raise AcroFormInspectionError()
    return names, False, True


def _radio_export_names(
    widget: _FieldNode,
    *,
    chain: Sequence[_FieldNode],
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]],
    field_value: str | None,
) -> frozenset[str]:
    owner = _field_owner(chain)
    cache_key = (owner.identity, field_value)
    cached = context.radio_export_cache.get(cache_key)
    if cached is not None:
        return cached
    siblings = context.children_by_parent.get(owner.identity, ())
    if not siblings:
        siblings = (widget,)
    exports: set[str] = set()
    for sibling_index, sibling in enumerate(siblings):
        if sibling_index % 128 == 0:
            context.check_deadline()
        sibling_forbidden = set(forbidden_references)
        if sibling.identity[0] == "ref":
            sibling_forbidden.add(
                (sibling.identity[1], sibling.identity[2])
            )
        names, absent, resolved = _appearance_names(
            sibling.value.get("AP"),
            context=context,
            forbidden_references=frozenset(sibling_forbidden),
        )
        if not resolved:
            raise AcroFormInspectionError()
        for name in names:
            if name == "Off":
                continue
            if name in exports:
                raise AcroFormInspectionError()
            exports.add(name)
        if absent:
            sibling_state = _optional_name(
                sibling.value.get("AS"),
                context=context,
                forbidden_references=frozenset(sibling_forbidden),
            )
            if (
                sibling_state is not None
                and sibling_state != "Off"
                and sibling_state == field_value
            ):
                if sibling_state in exports:
                    raise AcroFormInspectionError()
                exports.add(sibling_state)
    result = frozenset(exports)
    context.radio_export_cache[cache_key] = result
    return result


def _control_state(
    *,
    control_type: ControlType,
    field_value: str | None,
    appearance_state: str | None,
    appearance_names: Sequence[str],
    appearance_absent: bool,
    appearance_resolved: bool,
    field_export_names: frozenset[str],
) -> ControlState:
    export_names = {
        name for name in appearance_names if name != "Off"
    }
    if not appearance_resolved:
        return "ambiguous"
    if appearance_state is None:
        return "ambiguous"
    if appearance_state == "Off":
        if field_value in (None, "Off"):
            return "unchecked"
        if (
            control_type == "radio"
            and field_value in field_export_names
            and field_value not in export_names
        ):
            return "unchecked"
        return "ambiguous"
    if field_value not in (None, appearance_state):
        return "ambiguous"
    if appearance_absent:
        if field_value != appearance_state:
            return "ambiguous"
    elif appearance_state not in export_names:
        return "ambiguous"
    if appearance_state.casefold() in {
        "n/a",
        "na",
        "not_applicable",
    }:
        return "not_applicable"
    return "checked"


def _widget_bbox(
    raw_rect: object,
    *,
    page_width: float,
    page_height: float,
    page_rotation: int,
    media_box: object | None,
    crop_box: object | None,
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]],
) -> tuple[float, float, float, float]:
    rect = _resolved_box(
        raw_rect,
        context=context,
        forbidden_references=forbidden_references,
    )
    width = _finite_number(page_width)
    height = _finite_number(page_height)
    if width <= 0 or height <= 0:
        raise AcroFormInspectionError()
    rotation = page_rotation % 360
    if rotation not in {0, 90, 180, 270}:
        raise AcroFormInspectionError()
    if media_box is None:
        if rotation in {0, 180}:
            media = (0.0, 0.0, width, height)
        else:
            media = (0.0, 0.0, height, width)
    else:
        media = _resolved_box(
            media_box,
            context=context,
            forbidden_references=forbidden_references,
        )
    media_width = media[2] - media[0]
    media_height = media[3] - media[1]
    if media_width <= 0 or media_height <= 0:
        raise AcroFormInspectionError("form_transform_unavailable")
    rendered_width, rendered_height = (
        (media_width, media_height)
        if rotation in {0, 180}
        else (media_height, media_width)
    )
    if (
        abs(rendered_width - width) > 0.01
        or abs(rendered_height - height) > 0.01
    ):
        raise AcroFormInspectionError()
    normalized = _transform_raw_box_to_page(
        rect,
        media_box=media,
        rotation=rotation,
    )
    if crop_box is None:
        effective_crop = media
    else:
        crop = _resolved_box(
            crop_box,
            context=context,
            forbidden_references=forbidden_references,
        )
        effective_crop = (
            max(media[0], crop[0]),
            max(media[1], crop[1]),
            min(media[2], crop[2]),
            min(media[3], crop[3]),
        )
        if (
            effective_crop[0] >= effective_crop[2]
            or effective_crop[1] >= effective_crop[3]
        ):
            raise AcroFormInspectionError("form_transform_unavailable")
    normalized_crop = tuple(
        round(value, 3)
        for value in _transform_raw_box_to_page(
            effective_crop,
            media_box=media,
            rotation=rotation,
        )
    )
    x, y, normalized_width, normalized_height = (
        round(value, 3) for value in normalized
    )
    crop_x, crop_y, crop_width, crop_height = normalized_crop
    if (
        x < -0.001
        or y < -0.001
        or x + normalized_width > width + 0.001
        or y + normalized_height > height + 0.001
        or x < crop_x - 0.001
        or y < crop_y - 0.001
        or normalized_width <= 0
        or normalized_height <= 0
        or x + normalized_width > crop_x + crop_width + 0.001
        or y + normalized_height > crop_y + crop_height + 0.001
    ):
        raise AcroFormInspectionError()
    return (x, y, normalized_width, normalized_height)


def _resolved_box(
    raw_box: object,
    *,
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]],
) -> tuple[float, float, float, float]:
    resolved = context.resolve(
        raw_box,
        active_references=forbidden_references,
    )
    if not isinstance(resolved, (list, tuple)) or len(resolved) != 4:
        raise AcroFormInspectionError()
    x0, y0, x1, y1 = (_finite_number(value) for value in resolved)
    left, right = sorted((x0, x1))
    bottom, top = sorted((y0, y1))
    if left == right or bottom == top:
        raise AcroFormInspectionError()
    return (left, bottom, right, top)


def _transform_raw_box_to_page(
    box: tuple[float, float, float, float],
    *,
    media_box: tuple[float, float, float, float],
    rotation: int,
) -> tuple[float, float, float, float]:
    media_left, media_bottom, media_right, media_top = media_box
    media_width = media_right - media_left
    media_height = media_top - media_bottom
    rendered_height = media_height if rotation in {0, 180} else media_width

    def rotate_point(x: float, y: float) -> tuple[float, float]:
        local_x = x - media_left
        local_y = y - media_bottom
        if rotation == 0:
            return (local_x, local_y)
        if rotation == 90:
            return (local_y, media_width - local_x)
        if rotation == 180:
            return (media_width - local_x, media_height - local_y)
        return (media_height - local_y, local_x)

    left, bottom, right, top = box
    points = tuple(
        rotate_point(x, y)
        for x, y in (
            (left, bottom),
            (left, top),
            (right, bottom),
            (right, top),
        )
    )
    xs = tuple(point[0] for point in points)
    ys = tuple(point[1] for point in points)
    transformed_left = min(xs)
    transformed_right = max(xs)
    transformed_top = rendered_height - max(ys)
    transformed_bottom = rendered_height - min(ys)
    return (
        transformed_left,
        transformed_top,
        transformed_right - transformed_left,
        transformed_bottom - transformed_top,
    )


def _validate_page_owner(
    raw_page: object,
    *,
    page_object_id: int | None,
) -> None:
    if raw_page is None:
        return
    if (
        page_object_id is None
        or isinstance(page_object_id, bool)
        or not isinstance(page_object_id, int)
        or page_object_id < 1
        or not isinstance(raw_page, PDFObjRef)
        or int(raw_page.objid) != page_object_id
    ):
        raise AcroFormInspectionError()


def _validate_user_unit(
    raw_user_unit: object,
    *,
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]],
) -> None:
    try:
        resolved = context.resolve(
            raw_user_unit,
            active_references=forbidden_references,
        )
        user_unit = _finite_number(resolved)
    except _AcroFormLimitError:
        raise
    except AcroFormInspectionError as exc:
        if exc.code == "form_source_evidence_unavailable":
            raise
        raise AcroFormInspectionError(
            "form_transform_unavailable"
        ) from exc
    if user_unit <= 0 or user_unit != 1.0:
        raise AcroFormInspectionError("form_transform_unavailable")


def _pdf_name(
    value: object,
    *,
    context: _InspectionContext,
    forbidden_references: frozenset[tuple[int, int]] = frozenset(),
) -> str:
    resolved = context.resolve(
        value,
        active_references=forbidden_references,
    )
    if not isinstance(resolved, PSLiteral):
        raise AcroFormInspectionError()
    return _name_payload(resolved.name, context.limits)


def _name_payload(value: object, limits: AcroFormLimits) -> str:
    text = _afob_name_payload(value, limits)
    if not text:
        raise AcroFormInspectionError()
    return text


def _afob_name_payload(value: object, limits: AcroFormLimits) -> str:
    if isinstance(value, PSLiteral):
        value = value.name
    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AcroFormInspectionError() from exc
    elif isinstance(value, str):
        text = value
    else:
        raise AcroFormInspectionError()
    if len(_utf8_bytes(text)) > limits.name_bytes:
        raise _AcroFormLimitError("acroform_max_name_bytes")
    return text


def _utf8_bytes(value: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeError as exc:
        raise AcroFormInspectionError() from exc


def _reference_identity(reference: PDFObjRef) -> tuple[int, int]:
    objid = int(reference.objid)
    genno = int(getattr(reference, "genno", 0))
    return (objid, genno)


def _object_identity(
    reference: PDFObjRef | None,
    value: object,
) -> Identity:
    if reference is not None:
        objid, genno = _reference_identity(reference)
        return ("ref", objid, genno)
    return ("direct", id(value))


def _source_digest(
    source_sha256: str,
    kind: Literal["field", "widget"],
    identity: Identity,
    *,
    page_index: int,
    annotation_index: int,
) -> str:
    if identity[0] == "ref":
        identity_text = f"{identity[1]}:{identity[2]}"
    else:
        identity_text = f"direct:{page_index}:{annotation_index}"
    payload = f"{source_sha256}:{kind}:{identity_text}"
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AcroFormInspectionError()
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise AcroFormInspectionError() from exc
    if not math.isfinite(number):
        raise AcroFormInspectionError()
    return number


def afob_v1_size(
    value: object,
    *,
    limits: AcroFormLimits = DEFAULT_LIMITS,
) -> int:
    """Return the local AFOB-v1 decoded-object size."""

    return _afob_v1_size(value, limits)


def _afob_v1_size(
    value: object,
    limits: AcroFormLimits,
    *,
    deadline_check: Callable[[], None] | None = None,
) -> int:
    frames: list[_AfobFrame] = []
    active_containers: set[int] = set()
    current = value
    operations = 0
    while True:
        operations += 1
        if deadline_check is not None and operations % 256 == 0:
            deadline_check()
        scalar_size = _afob_scalar_size(current, limits)
        if scalar_size is not None:
            completed_size = scalar_size
        else:
            container_id = id(current)
            if container_id in active_containers:
                raise AcroFormInspectionError()
            active_containers.add(container_id)
            if isinstance(current, PDFStream):
                raw = current.rawdata
                if not isinstance(raw, bytes):
                    raise AcroFormInspectionError()
                base = len(raw)
                children: Sequence[object] = (current.attrs,)
            elif isinstance(current, Mapping):
                if len(current) > limits.dictionary_entries:
                    raise _AcroFormLimitError(
                        "acroform_max_dictionary_entries"
                    )
                entries: list[tuple[bytes, object]] = []
                for key, child in current.items():
                    key_bytes = _utf8_bytes(
                        _afob_name_payload(key, limits)
                    )
                    entries.append((key_bytes, child))
                entries.sort(key=lambda item: item[0])
                base = 2 + len(entries) + sum(
                    1 + len(key_bytes)
                    for key_bytes, _child in entries
                )
                children = tuple(child for _key, child in entries)
            elif isinstance(current, (list, tuple)):
                base = 2 + len(current)
                children = current
            else:
                active_containers.remove(container_id)
                raise AcroFormInspectionError()
            if base > limits.object_bytes:
                raise _AcroFormLimitError("acroform_max_object_bytes")
            if children:
                frames.append(
                    _AfobFrame(
                        container=current,
                        children=children,
                        next_index=1,
                        total=base,
                    )
                )
                current = children[0]
                continue
            active_containers.remove(container_id)
            completed_size = base

        while frames:
            frame = frames[-1]
            frame.total += completed_size
            if frame.total > limits.object_bytes:
                raise _AcroFormLimitError(
                    "acroform_max_object_bytes"
                )
            if frame.next_index < len(frame.children):
                current = frame.children[frame.next_index]
                frame.next_index += 1
                break
            frames.pop()
            active_containers.remove(id(frame.container))
            completed_size = frame.total
        else:
            if deadline_check is not None:
                deadline_check()
            return completed_size


def _afob_scalar_size(
    value: object,
    limits: AcroFormLimits,
) -> int | None:
    if value is None or isinstance(value, bool):
        size = 1
    elif isinstance(value, int):
        if value.bit_length() > limits.object_bytes * 4:
            raise _AcroFormLimitError("acroform_max_object_bytes")
        try:
            size = len(str(value).encode("ascii"))
        except (OverflowError, ValueError) as exc:
            raise AcroFormInspectionError() from exc
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise AcroFormInspectionError()
        size = len(format(value, ".17g").encode("ascii"))
    elif isinstance(value, PSLiteral):
        size = 1 + len(
            _utf8_bytes(_afob_name_payload(value.name, limits))
        )
    elif isinstance(value, bytes):
        if len(value) > limits.string_bytes:
            raise _AcroFormLimitError("acroform_max_string_bytes")
        size = 2 + len(value)
    elif isinstance(value, str):
        payload = _utf8_bytes(value)
        if len(payload) > limits.string_bytes:
            raise _AcroFormLimitError("acroform_max_string_bytes")
        size = 2 + len(payload)
    elif isinstance(value, PDFObjRef):
        objid, genno = _reference_identity(value)
        size = 4 + len(str(objid)) + len(str(genno))
    else:
        return None
    if size > limits.object_bytes:
        raise _AcroFormLimitError("acroform_max_object_bytes")
    return size


def validate_acroform_graph(
    graph: Mapping[str, object],
    *,
    limits: AcroFormLimits = DEFAULT_LIMITS,
) -> AcroFormLimitResult:
    """Exercise the production AcroForm budgets with an abstract field graph.

    The deterministic Phase 03 boundary fixtures use this compact form for
    limits that would otherwise require multi-megabyte malicious PDFs.
    """

    try:
        _validate_graph_or_raise(graph, limits=limits)
    except _AcroFormLimitError as exc:
        return AcroFormLimitResult(False, exc.limit_name)
    except (AcroFormInspectionError, TypeError, ValueError):
        return AcroFormLimitResult(False, "form_interactivity_unknown")
    return AcroFormLimitResult(True, None)


def _validate_graph_or_raise(
    graph: Mapping[str, object],
    *,
    limits: AcroFormLimits,
) -> None:
    raw_nodes = graph.get("nodes")
    raw_roots = graph.get("root_ids")
    if not isinstance(raw_nodes, (list, tuple)) or not isinstance(
        raw_roots, (list, tuple)
    ):
        raise AcroFormInspectionError()
    resource_probe = graph.get("resource_probe")
    resource_summary: Mapping[str, object] | None = None
    if resource_probe is not None:
        if not isinstance(resource_probe, Mapping):
            raise AcroFormInspectionError()
        possible_summary = resource_probe.get("non_target_counts")
        if not isinstance(possible_summary, Mapping):
            raise AcroFormInspectionError()
        resource_summary = possible_summary
        _validate_summary_limit(
            resource_summary,
            "widgets",
            limits.annotations_per_document,
            "max_annotations_widgets_per_document",
        )
    virtual_field_nodes = (
        _summary_integer(resource_summary, "field_nodes")
        if resource_summary is not None
        else 0
    )
    if max(len(raw_nodes), virtual_field_nodes) > limits.field_nodes:
        raise _AcroFormLimitError("acroform_max_nodes")
    nodes: dict[str, Mapping[str, object]] = {}
    for raw_node in raw_nodes:
        if not isinstance(raw_node, Mapping):
            raise AcroFormInspectionError()
        object_id = raw_node.get("object_id")
        if not isinstance(object_id, str) or not object_id or object_id in nodes:
            raise AcroFormInspectionError()
        raw_kids = raw_node.get("kid_ids", ())
        if not isinstance(raw_kids, (list, tuple)):
            raise AcroFormInspectionError()
        if len(raw_kids) > limits.kids_per_node:
            raise _AcroFormLimitError("acroform_max_kids_per_node")
        nodes[object_id] = raw_node

    seen: set[str] = set()

    def visit(node_id: str, depth: int, active: frozenset[str]) -> None:
        if depth > limits.field_depth:
            raise _AcroFormLimitError("acroform_max_depth")
        if node_id in active or node_id in seen or node_id not in nodes:
            raise AcroFormInspectionError()
        seen.add(node_id)
        node = nodes[node_id]
        raw_kids = node.get("kid_ids", ())
        assert isinstance(raw_kids, (list, tuple))
        for kid_id in raw_kids:
            if not isinstance(kid_id, str):
                raise AcroFormInspectionError()
            visit(kid_id, depth + 1, active | {node_id})

    for root_id in raw_roots:
        if not isinstance(root_id, str):
            raise AcroFormInspectionError()
        visit(root_id, 0, frozenset())
    if seen != set(nodes):
        raise AcroFormInspectionError()

    if resource_probe is None:
        return
    assert isinstance(resource_probe, Mapping)
    _validate_resource_probe(resource_probe, limits=limits)


def _validate_resource_probe(
    probe: Mapping[str, object],
    *,
    limits: AcroFormLimits,
) -> None:
    summary = probe.get("non_target_counts")
    if not isinstance(summary, Mapping):
        raise AcroFormInspectionError()
    ordered_limits = (
        (
            "max_dictionary_entries",
            limits.dictionary_entries,
            "acroform_max_dictionary_entries",
        ),
        (
            "distinct_visited_references",
            limits.visited_references,
            "acroform_max_visited_references",
        ),
        (
            "resolution_steps",
            limits.resolution_steps,
            "acroform_max_resolution_steps",
        ),
        ("max_name_bytes", limits.name_bytes, "acroform_max_name_bytes"),
        (
            "max_string_bytes",
            limits.string_bytes,
            "acroform_max_string_bytes",
        ),
        ("max_object_bytes", limits.object_bytes, "acroform_max_object_bytes"),
        ("tree_bytes", limits.tree_bytes, "acroform_max_tree_bytes"),
    )
    for key, maximum, limit_name in ordered_limits:
        _validate_summary_limit(summary, key, maximum, limit_name)

    raw_objects = probe.get("objects", ())
    if not isinstance(raw_objects, (list, tuple)):
        raise AcroFormInspectionError()
    for raw_object in raw_objects:
        if not isinstance(raw_object, Mapping):
            raise AcroFormInspectionError()
        pdf_type = raw_object.get("pdf_type")
        if pdf_type == "dictionary":
            entries = raw_object.get("entries")
            if not isinstance(entries, (list, tuple)):
                raise AcroFormInspectionError()
            value = {str(key): value for key, value in entries}
            _afob_v1_size(value, limits)
        elif pdf_type == "stream":
            raw = raw_object.get("encoded_stream_bytes")
            entries = raw_object.get("dictionary_entries")
            accounted = raw_object.get("accounted_bytes")
            if (
                not isinstance(raw, bytes)
                or not isinstance(entries, (list, tuple))
                or isinstance(accounted, bool)
                or not isinstance(accounted, int)
            ):
                raise AcroFormInspectionError()
            entry_mapping: dict[str, object] = {}
            for entry in entries:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    raise AcroFormInspectionError()
                key, value = entry
                if not isinstance(key, str) or key in entry_mapping:
                    raise AcroFormInspectionError()
                entry_mapping[key] = value
            calculated = _afob_v1_size(entry_mapping, limits) + len(raw)
            if calculated != accounted:
                raise AcroFormInspectionError()
            if calculated > limits.object_bytes:
                raise _AcroFormLimitError("acroform_max_object_bytes")
        elif pdf_type == "name":
            raw = raw_object.get("raw_bytes")
            if not isinstance(raw, bytes):
                raise AcroFormInspectionError()
            if len(raw) > limits.name_bytes:
                raise _AcroFormLimitError("acroform_max_name_bytes")
        elif pdf_type == "string":
            raw = raw_object.get("raw_bytes")
            if not isinstance(raw, bytes):
                raise AcroFormInspectionError()
            if len(raw) > limits.string_bytes:
                raise _AcroFormLimitError("acroform_max_string_bytes")
        else:
            raise AcroFormInspectionError()


def _summary_integer(
    summary: Mapping[str, object] | None,
    key: str,
) -> int:
    if summary is None:
        raise AcroFormInspectionError()
    observed = summary.get(key)
    if isinstance(observed, bool) or not isinstance(observed, int):
        raise AcroFormInspectionError()
    return observed


def _validate_summary_limit(
    summary: Mapping[str, object],
    key: str,
    maximum: int,
    limit_name: str,
) -> None:
    if _summary_integer(summary, key) > maximum:
        raise _AcroFormLimitError(limit_name)


__all__ = [
    "AcroFormInspection",
    "AcroFormLimitResult",
    "AcroFormLimits",
    "AcroFormPageInput",
    "DEFAULT_LIMITS",
    "InteractiveControlEvidence",
    "afob_v1_size",
    "inspect_acroform",
    "validate_acroform_graph",
]
