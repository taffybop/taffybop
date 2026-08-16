"""Adversarial AcroForm assurance for P03-US06."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from pdfminer.pdftypes import PDFObjRef
from pdfminer.psparser import LIT

import app.services.acroform as acroform_module
from app.services.acroform import (
    AcroFormLimits,
    AcroFormPageInput,
    afob_v1_size,
    inspect_acroform,
)


_SHA256 = "0" * 64


def _widget(**overrides: object) -> dict[str, object]:
    widget: dict[str, object] = {
        "Subtype": LIT("Widget"),
        "FT": LIT("Btn"),
        "Ff": 0,
        "T": b"control",
        "V": LIT("Yes"),
        "AS": LIT("Yes"),
        "Rect": [10, 70, 20, 80],
        "AP": {"N": {"Off": {}, "Yes": {}}},
    }
    widget.update(overrides)
    return widget


def _inspect_direct(
    widget: Mapping[str, Any],
    *,
    user_unit: object = 1,
    media_box: object = (0, 0, 100, 100),
    crop_box: object = (0, 0, 100, 100),
    rotation: int = 0,
    width: float = 100,
    height: float = 100,
) -> Any:
    return inspect_acroform(
        catalog={"AcroForm": {"Fields": [widget]}},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=width,
                height=height,
                annotations=(widget,),
                rotation=rotation,
                media_box=media_box,
                crop_box=crop_box,
                user_unit=user_unit,
            ),
        ),
        source_sha256=_SHA256,
    )


def test_pdf_names_are_exact_except_not_applicable_classification() -> None:
    widget = _widget(
        V=LIT("off"),
        AS=LIT("off"),
        AP={"N": {"off": {}}},
    )

    result = _inspect_direct(widget)

    assert result.interactivity == "interactive"
    assert result.pages[0].controls[0].state == "checked"


def test_case_distinct_appearance_export_names_remain_distinct() -> None:
    widget = _widget(
        V=LIT("Yes"),
        AS=LIT("Yes"),
        AP={"N": {"Yes": {}, "yes": {}}},
    )

    result = _inspect_direct(widget)

    assert result.interactivity == "interactive"
    assert result.pages[0].controls[0].state == "checked"


def test_pdf_text_strings_use_pdf_bom_decoding() -> None:
    result = _inspect_direct(_widget(T=b"\xfe\xff\x00A"))

    assert result.interactivity == "interactive"
    assert result.pages[0].controls[0].field_name == "A"


@pytest.mark.parametrize("field_type", ("Tx", "Btn"))
def test_all_widgets_validate_geometry_before_type_exclusion(
    field_type: str,
) -> None:
    widget = _widget(FT=LIT(field_type))
    widget.pop("Rect")
    if field_type == "Btn":
        widget["Ff"] = 1 << 16

    result = _inspect_direct(widget)

    assert result.interactivity == "unknown"
    assert result.pages[0].interactivity == "unknown"
    assert result.pages[0].controls == ()


def test_nondefault_user_unit_fails_with_sanitized_transform_concern() -> None:
    result = _inspect_direct(_widget(), user_unit=2)

    assert result.interactivity == "unknown"
    assert result.concern_codes == ("form_transform_unavailable",)
    assert result.pages[0].controls == ()


@pytest.mark.parametrize(
    ("overrides", "user_unit"),
    (
        ({"Rect": [10, 70, 20, 10**1_000]}, 1),
        ({}, 10**1_000),
    ),
)
def test_oversized_geometry_numbers_fail_closed(
    overrides: Mapping[str, object],
    user_unit: object,
) -> None:
    result = _inspect_direct(
        _widget(**overrides),
        user_unit=user_unit,
    )

    assert result.interactivity == "unknown"
    assert result.pages[0].interactivity == "unknown"
    assert result.pages[0].controls == ()


def test_crop_is_intersected_with_media_and_off_page_widget_is_rejected() -> None:
    widget = _widget(Rect=[-5, 50, 5, 60])

    result = _inspect_direct(
        widget,
        crop_box=(-10, -10, 110, 110),
    )

    assert result.interactivity == "unknown"
    assert result.pages[0].controls == ()


def test_raw_rotated_media_coordinates_are_transformed_once() -> None:
    widget = _widget(Rect=[20, 30, 30, 40])

    result = _inspect_direct(
        widget,
        media_box=(10, 20, 110, 220),
        crop_box=(10, 20, 110, 220),
        rotation=90,
        width=200,
        height=100,
    )

    assert result.interactivity == "interactive"
    assert result.pages[0].controls[0].bbox == (10.0, 10.0, 10.0, 10.0)


def test_malformed_annotation_subtype_is_page_local() -> None:
    result = inspect_acroform(
        catalog={},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=({"Subtype": "Widget"},),
            ),
            AcroFormPageInput(
                page_index=2,
                width=100,
                height=100,
                annotations=({"Subtype": LIT("Link")},),
            ),
        ),
        source_sha256=_SHA256,
    )

    assert result.interactivity == "unknown"
    assert tuple(page.interactivity for page in result.pages) == (
        "unknown",
        "none",
    )


def test_widget_repeated_across_pages_taints_both_occurrence_pages() -> None:
    widget = _widget()
    result = inspect_acroform(
        catalog={"AcroForm": {"Fields": [widget]}},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=(widget,),
            ),
            AcroFormPageInput(
                page_index=2,
                width=100,
                height=100,
                annotations=(widget,),
            ),
        ),
        source_sha256=_SHA256,
    )

    assert result.interactivity == "unknown"
    assert tuple(page.interactivity for page in result.pages) == (
        "unknown",
        "unknown",
    )


def test_orphan_without_field_type_is_retained_as_ambiguous_unknown() -> None:
    widget = _widget()
    widget.pop("FT")
    result = inspect_acroform(
        catalog={},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=(widget,),
            ),
        ),
        source_sha256=_SHA256,
    )

    assert result.interactivity == "unknown"
    assert tuple(
        (control.control_type, control.state)
        for control in result.pages[0].controls
    ) == (("unknown", "ambiguous"),)


def test_orphan_with_unresolvable_parent_fails_closed_without_crashing() -> None:
    widget = _widget(Parent=PDFObjRef(None, 99))
    result = inspect_acroform(
        catalog={},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=(widget,),
            ),
        ),
        source_sha256=_SHA256,
        resolver=lambda _reference: None,
    )

    assert result.interactivity == "unknown"
    assert result.pages[0].interactivity == "unknown"
    assert tuple(
        (control.bbox, control.state)
        for control in result.pages[0].controls
    ) == (((10.0, 20.0, 10.0, 10.0), "ambiguous"),)


def test_orphan_with_detached_parent_retains_ambiguous_geometry() -> None:
    parent_ref = PDFObjRef(None, 99)
    widget = _widget(Parent=parent_ref)
    widget.pop("FT")
    result = inspect_acroform(
        catalog={},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=(widget,),
            ),
        ),
        source_sha256=_SHA256,
        resolver=lambda _reference: {
            "FT": LIT("Btn"),
            "Ff": 0,
            "T": b"detached",
        },
    )

    assert result.interactivity == "unknown"
    assert tuple(
        (control.bbox, control.control_type, control.state)
        for control in result.pages[0].controls
    ) == (((10.0, 20.0, 10.0, 10.0), "unknown", "ambiguous"),)


def test_absent_annots_is_not_charged_as_a_direct_root() -> None:
    absent = inspect_acroform(
        catalog={},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=(),
                annotations_present=False,
            ),
        ),
        source_sha256=_SHA256,
        limits=AcroFormLimits(tree_bytes=1),
    )
    present_empty = inspect_acroform(
        catalog={},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=(),
            ),
        ),
        source_sha256=_SHA256,
        limits=AcroFormLimits(tree_bytes=1),
    )

    assert absent.interactivity == "none"
    assert absent.accounted_tree_bytes == 0
    assert present_empty.interactivity == "unknown"
    assert present_empty.concern_codes == ("form_source_limit",)


def test_oversized_direct_annots_refuses_before_iteration() -> None:
    class OversizedAnnotations(list[object]):
        def __len__(self) -> int:
            return 1_000_000

        def __iter__(self) -> Any:
            raise AssertionError("over-cap Annots must not be iterated")

    result = inspect_acroform(
        catalog={},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=OversizedAnnotations(),
            ),
        ),
        source_sha256=_SHA256,
    )

    assert result.interactivity == "unknown"
    assert result.pages[0].concern_codes == ("form_source_limit",)
    assert result.accounted_tree_bytes == 0


def test_unknown_over_cap_page_still_owns_shallow_widget_occurrence() -> None:
    widget_ref = PDFObjRef(None, 1)
    objects = {1: _widget()}
    result = inspect_acroform(
        catalog={"AcroForm": {"Fields": [widget_ref]}},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=(
                    widget_ref,
                    {"Subtype": LIT("Link")},
                ),
            ),
            AcroFormPageInput(
                page_index=2,
                width=100,
                height=100,
                annotations=(),
            ),
        ),
        source_sha256=_SHA256,
        resolver=lambda reference: objects[reference.objid],
        limits=AcroFormLimits(annotations_per_page=1),
    )

    assert tuple(page.interactivity for page in result.pages) == (
        "unknown",
        "none",
    )
    assert result.pages[0].concern_codes == ("form_source_limit",)


def test_nested_inherited_radio_without_appearance_dictionary_is_grounded() -> None:
    root_ref = PDFObjRef(None, 1)
    field_ref = PDFObjRef(None, 2)
    selected_ref = PDFObjRef(None, 3)
    unselected_ref = PDFObjRef(None, 4)
    objects: dict[int, object] = {
        1: {
            "FT": LIT("Btn"),
            "Kids": [field_ref],
        },
        2: {
            "Parent": root_ref,
            "Ff": 1 << 15,
            "T": b"inherited-radio",
            "V": LIT("A"),
            "Kids": [selected_ref, unselected_ref],
        },
        3: {
            "Subtype": LIT("Widget"),
            "Parent": field_ref,
            "AS": LIT("A"),
            "AA": {},
            "Rect": [10, 70, 20, 80],
        },
        4: {
            "Subtype": LIT("Widget"),
            "Parent": field_ref,
            "AS": LIT("Off"),
            "AA": {},
            "Rect": [10, 50, 20, 60],
        },
    }

    result = inspect_acroform(
        catalog={"AcroForm": {"Fields": [root_ref]}},
        pages=(
            AcroFormPageInput(
                page_index=1,
                width=100,
                height=100,
                annotations=(selected_ref, unselected_ref),
                media_box=(0, 0, 100, 100),
                crop_box=(0, 0, 100, 100),
            ),
        ),
        source_sha256=_SHA256,
        resolver=lambda reference: objects[reference.objid],
    )

    assert result.interactivity == "interactive"
    assert tuple(
        (control.state, control.field_name)
        for control in result.pages[0].controls
    ) == (
        ("checked", "inherited-radio"),
        ("unchecked", "inherited-radio"),
    )
    assert len(
        {
            control.field_ref_digest
            for control in result.pages[0].controls
        }
    ) == 1


def test_afob_exact_large_array_is_linear_and_max_plus_one_is_rejected() -> None:
    limits = AcroFormLimits()
    exact_items = (limits.object_bytes - 2) // 2

    assert afob_v1_size((None,) * exact_items) == limits.object_bytes
    with pytest.raises(ValueError, match="failed closed"):
        afob_v1_size((None,) * (exact_items + 1))


def test_afob_handles_deep_containers_and_sanitizes_huge_integers() -> None:
    value: object = None
    for _ in range(2_000):
        value = [value]

    assert afob_v1_size(value) == 6_001
    huge_integer = 1 << (AcroFormLimits().object_bytes * 4 + 1)
    with pytest.raises(ValueError, match="failed closed"):
        afob_v1_size(huge_integer)


def test_afob_allows_the_empty_pdf_name_payload() -> None:
    assert afob_v1_size(LIT("")) == 1


@pytest.mark.parametrize(
    ("exact", "over", "limits"),
    (
        (
            {"A": None, "B": None},
            {"A": None, "B": None, "C": None},
            replace(AcroFormLimits(), dictionary_entries=2),
        ),
        (
            LIT("NN"),
            LIT("NNN"),
            replace(AcroFormLimits(), name_bytes=2),
        ),
        (
            b"SS",
            b"SSS",
            replace(AcroFormLimits(), string_bytes=2),
        ),
        (
            999,
            1_000,
            replace(AcroFormLimits(), object_bytes=3),
        ),
    ),
)
def test_production_afob_exact_and_max_plus_one(
    exact: object,
    over: object,
    limits: AcroFormLimits,
) -> None:
    assert afob_v1_size(exact, limits=limits) <= limits.object_bytes
    with pytest.raises(ValueError, match="failed closed"):
        afob_v1_size(over, limits=limits)


def test_production_context_reference_and_tree_boundaries() -> None:
    objects = {
        1: None,
        2: None,
        3: None,
    }
    context = acroform_module._InspectionContext(
        resolver=lambda reference: objects[int(reference.objid)],
        limits=replace(
            AcroFormLimits(),
            visited_references=2,
            resolution_steps=3,
            tree_bytes=2,
        ),
        deadline_at=time.monotonic() + 1,
    )

    assert context.resolve(PDFObjRef(None, 1)) is None
    assert context.resolve(PDFObjRef(None, 1)) is None
    assert context.resolve(PDFObjRef(None, 2)) is None
    assert (
        len(context.visited_references),
        context.resolution_steps,
        context.tree_bytes,
    ) == (2, 3, 2)
    with pytest.raises(
        acroform_module._AcroFormLimitError,
        match="failed closed",
    ) as raised:
        context.resolve(PDFObjRef(None, 3))
    assert raised.value.limit_name == "acroform_max_visited_references"


def test_production_resolution_and_tree_max_plus_one() -> None:
    resolution_context = acroform_module._InspectionContext(
        resolver=lambda _reference: None,
        limits=replace(
            AcroFormLimits(),
            visited_references=1,
            resolution_steps=2,
        ),
        deadline_at=time.monotonic() + 1,
    )
    reference = PDFObjRef(None, 1)
    assert resolution_context.resolve(reference) is None
    assert resolution_context.resolve(reference) is None
    with pytest.raises(acroform_module._AcroFormLimitError) as resolution_error:
        resolution_context.resolve(reference)
    assert (
        resolution_error.value.limit_name
        == "acroform_max_resolution_steps"
    )

    tree_context = acroform_module._InspectionContext(
        resolver=lambda _reference: None,
        limits=replace(AcroFormLimits(), tree_bytes=4),
        deadline_at=time.monotonic() + 1,
    )
    tree_context.account_direct_root([None])
    assert tree_context.tree_bytes == 4
    with pytest.raises(acroform_module._AcroFormLimitError) as tree_error:
        tree_context.account_direct_root([None])
    assert tree_error.value.limit_name == "acroform_max_tree_bytes"


def test_production_context_collision_uses_frozen_counter_order() -> None:
    context = acroform_module._InspectionContext(
        resolver=lambda _reference: {"A": None},
        limits=replace(
            AcroFormLimits(),
            dictionary_entries=0,
            visited_references=0,
            resolution_steps=0,
        ),
        deadline_at=time.monotonic() + 1,
    )

    with pytest.raises(acroform_module._AcroFormLimitError) as raised:
        context.resolve(PDFObjRef(None, 1))
    assert raised.value.limit_name == "acroform_max_visited_references"


def test_production_field_depth_allows_33_nodes_and_rejects_34() -> None:
    def visit_chain(node_count: int) -> int:
        references = {
            index: PDFObjRef(None, index)
            for index in range(1, node_count + 1)
        }
        objects = {
            index: {
                **(
                    {"Parent": references[index - 1]}
                    if index > 1
                    else {}
                ),
                "Kids": (
                    [references[index + 1]]
                    if index < node_count
                    else []
                ),
                **({"FT": LIT("Btn")} if index == node_count else {}),
            }
            for index in references
        }
        context = acroform_module._InspectionContext(
            resolver=lambda reference: objects[int(reference.objid)],
            limits=AcroFormLimits(),
            deadline_at=time.monotonic() + 1,
        )
        nodes: dict[Any, Any] = {}
        acroform_module._visit_field_node(
            references[1],
            depth=0,
            expected_parent=None,
            active=(),
            nodes=nodes,
            context=context,
        )
        return len(nodes)

    assert visit_chain(33) == 33
    with pytest.raises(acroform_module._AcroFormLimitError) as raised:
        visit_chain(34)
    assert raised.value.limit_name == "acroform_max_depth"


def test_production_field_node_and_kids_boundaries() -> None:
    references = {
        index: PDFObjRef(None, index)
        for index in range(1, 5)
    }
    independent = {
        index: {"FT": LIT("Btn"), "Kids": []}
        for index in references
    }
    node_context = acroform_module._InspectionContext(
        resolver=lambda reference: independent[int(reference.objid)],
        limits=replace(AcroFormLimits(), field_nodes=3),
        deadline_at=time.monotonic() + 1,
    )
    nodes: dict[Any, Any] = {}
    for index in range(1, 4):
        acroform_module._visit_field_node(
            references[index],
            depth=0,
            expected_parent=None,
            active=(),
            nodes=nodes,
            context=node_context,
        )
    assert len(nodes) == 3
    with pytest.raises(acroform_module._AcroFormLimitError) as node_error:
        acroform_module._visit_field_node(
            references[4],
            depth=0,
            expected_parent=None,
            active=(),
            nodes=nodes,
            context=node_context,
        )
    assert node_error.value.limit_name == "acroform_max_nodes"

    root_ref = PDFObjRef(None, 10)
    child_refs = (PDFObjRef(None, 11), PDFObjRef(None, 12))
    objects = {
        10: {"Kids": list(child_refs)},
        11: {"Parent": root_ref, "FT": LIT("Btn"), "Kids": []},
        12: {"Parent": root_ref, "FT": LIT("Btn"), "Kids": []},
    }
    kids_context = acroform_module._InspectionContext(
        resolver=lambda reference: objects[int(reference.objid)],
        limits=replace(AcroFormLimits(), kids_per_node=2),
        deadline_at=time.monotonic() + 1,
    )
    kids_nodes: dict[Any, Any] = {}
    acroform_module._visit_field_node(
        root_ref,
        depth=0,
        expected_parent=None,
        active=(),
        nodes=kids_nodes,
        context=kids_context,
    )
    assert len(kids_nodes) == 3
    objects[10] = {"Kids": [*child_refs, PDFObjRef(None, 13)]}
    over_context = acroform_module._InspectionContext(
        resolver=lambda reference: objects[int(reference.objid)],
        limits=replace(AcroFormLimits(), kids_per_node=2),
        deadline_at=time.monotonic() + 1,
    )
    with pytest.raises(acroform_module._AcroFormLimitError) as kids_error:
        acroform_module._visit_field_node(
            root_ref,
            depth=0,
            expected_parent=None,
            active=(),
            nodes={},
            context=over_context,
        )
    assert kids_error.value.limit_name == "acroform_max_kids_per_node"


def test_distinct_merged_radio_export_lookup_is_linear() -> None:
    context = acroform_module._InspectionContext(
        resolver=lambda reference: reference.resolve(),
        limits=AcroFormLimits(),
        deadline_at=time.monotonic() + 1,
    )

    for index in range(2_000):
        widget = acroform_module._FieldNode(
            identity=("direct", index),
            value={
                "FT": LIT("Btn"),
                "Ff": 1 << 15,
                "V": LIT("Yes"),
                "AS": LIT("Yes"),
                "AP": {"N": {"Off": {}, "Yes": {}}},
                "Rect": [10, 70, 20, 80],
            },
            parent_identity=None,
            source_ref=None,
        )
        assert acroform_module._radio_export_names(
            widget,
            chain=(widget,),
            context=context,
            forbidden_references=frozenset(),
            field_value="Yes",
        ) == frozenset({"Yes"})

    assert len(context.radio_export_cache) == 2_000


def test_deadline_is_rechecked_after_a_slow_resolver() -> None:
    acroform_ref = PDFObjRef(None, 1)

    def slow_resolver(_reference: PDFObjRef) -> object:
        time.sleep(0.005)
        return {"Fields": []}

    result = inspect_acroform(
        catalog={"AcroForm": acroform_ref},
        pages=(),
        source_sha256=_SHA256,
        resolver=slow_resolver,
        deadline_seconds=0.001,
    )

    assert result.interactivity == "unknown"
    assert result.concern_codes == ("form_source_evidence_unavailable",)
