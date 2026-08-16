"""Focused raw-structure security tests for P03-US06 AcroForms."""

from __future__ import annotations

import zlib
import tracemalloc
import time
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.acroform_raw import (
    DEFAULT_RAW_ACROFORM_LIMITS,
    RawAcroFormAuditError,
    _bounded_png_predictor,
    _bounded_tiff_predictor,
    audit_acroform_raw,
)


WORKSPACE = Path(__file__).resolve().parents[3]


def _classic_pdf(objects: list[bytes]) -> bytes:
    result = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, value in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{object_id} 0 obj\n".encode("ascii"))
        result.extend(value)
        result.extend(b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(result)


def _stream(data: bytes) -> bytes:
    return (
        f"<< /Length {len(data)} >>\nstream\n".encode("ascii")
        + data
        + b"\nendstream"
    )


def _interactive_pdf(
    *,
    widget_appearance: bytes = b"/AP << /N << /Off 6 0 R /Yes 7 0 R >> >>",
    widget_extra: bytes = b"",
    catalog_extra: bytes = b"",
    page_extra: bytes = b"",
    content: bytes = b"",
    appearance_content: bytes = b"",
) -> bytes:
    return _classic_pdf(
        [
            (
                b"<< /Type /Catalog /Pages 2 0 R /AcroForm 4 0 R "
                + catalog_extra
                + b" >>"
            ),
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /Annots [5 0 R] "
                b"/Contents 8 0 R "
                + page_extra
                + b" >>"
            ),
            b"<< /Fields [5 0 R] >>",
            (
                b"<< /Type /Annot /Subtype /Widget /FT /Btn "
                b"/Rect [0 0 10 10] "
                + widget_appearance
                + b" "
                + widget_extra
                + b" >>"
            ),
            _stream(appearance_content),
            _stream(b""),
            _stream(content),
        ]
    )


def _field_chain_pdf(node_count: int) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 4 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R >>",
        b"<< /Fields [5 0 R] >>",
    ]
    for index in range(node_count):
        object_id = index + 5
        entries = [f"/T (field-{index})".encode("ascii")]
        if index:
            entries.append(f"/Parent {object_id - 1} 0 R".encode("ascii"))
        if index + 1 < node_count:
            entries.append(f"/Kids [{object_id + 1} 0 R]".encode("ascii"))
        else:
            entries.extend((b"/Subtype /Widget", b"/FT /Btn"))
        objects.append(b"<< " + b" ".join(entries) + b" >>")
    return _classic_pdf(objects)


def _xref_stream_pdf(
    compressed_widget: bytes,
    *,
    xref_predictor_columns: int | None = None,
) -> bytes:
    result = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}

    def append_object(object_id: int, value: bytes) -> None:
        offsets[object_id] = len(result)
        result.extend(f"{object_id} 0 obj\n".encode("ascii"))
        result.extend(value)
        result.extend(b"\nendobj\n")

    append_object(1, b"<< /Type /Catalog /Pages 2 0 R /AcroForm 4 0 R >>")
    append_object(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    append_object(
        3,
        b"<< /Type /Page /Parent 2 0 R /Annots [5 0 R] >>",
    )
    append_object(4, b"<< /Fields [5 0 R] >>")
    append_object(6, _stream(b""))
    append_object(7, _stream(b""))

    object_stream_header = b"5 0 "
    object_stream_data = object_stream_header + compressed_widget
    compressed = zlib.compress(object_stream_data)
    append_object(
        8,
        (
            b"<< /Type /ObjStm /N 1 /First "
            + str(len(object_stream_header)).encode("ascii")
            + b" /Filter /FlateDecode /Length "
            + str(len(compressed)).encode("ascii")
            + b" >>\nstream\n"
            + compressed
            + b"\nendstream"
        ),
    )

    offsets[9] = len(result)
    entries = bytearray()
    for object_id in range(10):
        if object_id == 0:
            entry_type, first, second = 0, 0, 65_535
        elif object_id == 5:
            entry_type, first, second = 2, 8, 0
        else:
            entry_type, first, second = 1, offsets[object_id], 0
        entries.extend(bytes([entry_type]))
        entries.extend(first.to_bytes(4, "big"))
        entries.extend(second.to_bytes(2, "big"))
    result.extend(b"9 0 obj\n")
    xref_data = bytes(entries)
    filter_dictionary = b""
    if xref_predictor_columns is not None:
        xref_data = zlib.compress(xref_data)
        filter_dictionary = (
            b"/Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns "
            + str(xref_predictor_columns).encode("ascii")
            + b" >> "
        )
    result.extend(
        b"<< /Type /XRef /Size 10 /Root 1 0 R /W [1 4 2] "
        b"/Index [0 10] "
        + filter_dictionary
        + b"/Length "
        + str(len(xref_data)).encode("ascii")
        + b" >>\nstream\n"
    )
    result.extend(xref_data)
    result.extend(b"\nendstream\nendobj\n")
    result.extend(f"startxref\n{offsets[9]}\n%%EOF\n".encode("ascii"))
    return bytes(result)


def _assert_refused(source: bytes, reason: str) -> None:
    with pytest.raises(RawAcroFormAuditError) as raised:
        audit_acroform_raw(source)
    assert str(raised.value) == "Raw AcroForm structural audit failed closed"
    assert raised.value.code == "form_source_evidence_unavailable"
    assert raised.value.reason_code == reason


def test_valid_interactive_and_real_corpus_sources_pass_raw_audit() -> None:
    result = audit_acroform_raw(_interactive_pdf())
    assert result.acroform_present is True
    assert result.field_count == 1
    assert result.page_count == 1
    assert result.annotation_count == 1
    assert result.explicit_null_entry_count == 0

    for filename in ("insurance-acord.pdf", "component-datasheet.pdf"):
        corpus_result = audit_acroform_raw(
            (WORKSPACE / "benchmark-expertmodeldata" / filename).read_bytes()
        )
        assert corpus_result.relevant_dictionary_count > 0


@pytest.mark.parametrize(
    "widget_extra",
    [
        b"/AP << /N 6 0 R >>",
        b"/A#50 << /N 6 0 R >>",
        b"/Subtype /Widget",
        b"/Sub#74ype /Widget",
    ],
)
def test_exact_widget_key_collisions_fail_closed(
    widget_extra: bytes,
) -> None:
    _assert_refused(
        _interactive_pdf(widget_extra=widget_extra),
        "raw_acroform_duplicate_dictionary_key",
    )


def test_pdf_name_case_is_exact_for_widget_and_appearance_keys() -> None:
    source = _interactive_pdf(
        widget_appearance=b"/AP << /N << /Yes 6 0 R /yes 7 0 R >> >>",
        widget_extra=b"/ap << /N 6 0 R >> /subtype /Widget",
    )
    assert audit_acroform_raw(source).annotation_count == 1


def test_exact_appearance_state_duplicate_fails_closed() -> None:
    source = _interactive_pdf(
        widget_appearance=b"/AP << /N << /Yes 6 0 R /Yes 7 0 R >> >>"
    )
    _assert_refused(source, "raw_acroform_duplicate_dictionary_key")


def test_duplicate_key_in_compressed_object_is_detected() -> None:
    source = _xref_stream_pdf(
        b"<< /Type /Annot /Subtype /Widget /FT /Btn "
        b"/AP << /N 6 0 R >> /AP << /N 7 0 R >> >>"
    )
    _assert_refused(source, "raw_acroform_duplicate_dictionary_key")


def test_null_entries_are_retained_for_caps_and_ap_null_is_ambiguous() -> None:
    source = _interactive_pdf(widget_appearance=b"/AP null")
    _assert_refused(source, "raw_acroform_null_structural_value")

    retained = audit_acroform_raw(_interactive_pdf(widget_extra=b"/V null"))
    assert retained.explicit_null_entry_count == 1

    exact_null_entries = b" ".join(
        f"/K{index} null".encode("ascii") for index in range(251)
    )
    exact = audit_acroform_raw(
        _interactive_pdf(widget_extra=exact_null_entries)
    )
    assert exact.explicit_null_entry_count == 251

    over_limit_entries = exact_null_entries + b" /K251 null"
    _assert_refused(
        _interactive_pdf(widget_extra=over_limit_entries),
        "raw_acroform_dictionary_entry_limit",
    )


def test_nonzero_generation_is_rejected_only_when_relevant() -> None:
    relevant = _interactive_pdf(widget_extra=b"/Parent 6 1 R")
    _assert_refused(relevant, "raw_acroform_nonzero_generation")

    unrelated = _interactive_pdf(page_extra=b"/Contents 8 1 R")
    result = audit_acroform_raw(unrelated)
    assert result.annotation_count == 1

    mismatched_header = _interactive_pdf(widget_extra=b"/Parent 6 0 R").replace(
        b"6 0 obj",
        b"6 1 obj",
        1,
    )
    _assert_refused(
        mismatched_header,
        "raw_acroform_nonzero_generation",
    )


def test_only_ap_and_ap_n_keys_are_followed() -> None:
    source = _interactive_pdf(
        widget_appearance=(
            b"/AP << /N << /Off 6 12345 R /Yes 7 12345 R >> "
            b"/R 6 12345 R /D 7 12345 R >>"
        )
    )
    preserved = audit_acroform_raw(source)
    generation_zero = audit_acroform_raw(
        _interactive_pdf(
            widget_appearance=(
                b"/AP << /N << /Off 6 0 R /Yes 7 0 R >> "
                b"/R 6 0 R /D 7 0 R >>"
            )
        )
    )
    assert preserved.annotation_count == 1
    assert preserved.accounted_tree_bytes == (
        generation_zero.accounted_tree_bytes + 16
    )


def test_stream_payload_dictionary_decoys_are_never_tokenized() -> None:
    decoy = b"BT (<< /AP 1 /AP 2 /Subtype /Widget >>) Tj ET"
    result = audit_acroform_raw(
        _interactive_pdf(content=decoy, appearance_content=decoy)
    )
    assert result.annotation_count == 1


def test_gateway_collisions_are_audited_but_unrelated_dictionaries_are_not() -> None:
    _assert_refused(
        _interactive_pdf(catalog_extra=b"/AcroForm 4 0 R"),
        "raw_acroform_duplicate_dictionary_key",
    )
    source = _interactive_pdf(
        catalog_extra=b"/acroform 4 0 R /Metadata << /X 1 /X 2 >>"
    )
    assert audit_acroform_raw(source).annotation_count == 1


def test_predictor_dimensions_are_bounded_before_pdfminer_allocation() -> None:
    source = _xref_stream_pdf(
        b"<< /Type /Annot /Subtype /Widget /FT /Btn >>",
        xref_predictor_columns=10**12,
    )
    _assert_refused(source, "raw_acroform_predictor_limit")


def test_active_page_tree_cycle_fails_closed() -> None:
    source = _classic_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [2 0 R] /Count 1 >>",
        ]
    )
    _assert_refused(source, "raw_acroform_page_tree_cycle")


def test_shared_page_tree_node_fails_closed() -> None:
    source = _classic_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 3 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R >>",
        ]
    )
    _assert_refused(source, "raw_acroform_page_tree_shared_node")


def test_field_depth_counts_edges_from_zero_without_parent_compounding() -> None:
    exact = audit_acroform_raw(_field_chain_pdf(33))
    assert exact.field_count == 33
    _assert_refused(
        _field_chain_pdf(34),
        "raw_acroform_depth_limit",
    )


def test_corrupt_xref_does_not_fall_back_to_lossy_scanning() -> None:
    source = _interactive_pdf()
    prefix, _ = source.rsplit(b"startxref\n", maxsplit=1)
    corrupted = prefix + b"startxref\n0\n%%EOF\n"
    _assert_refused(corrupted, "malformed_pdf_structure")


def test_classic_xref_entries_are_bounded_before_offset_accumulation() -> None:
    source = _interactive_pdf()
    exact = replace(DEFAULT_RAW_ACROFORM_LIMITS, xref_entries=9)
    assert audit_acroform_raw(source, limits=exact).annotation_count == 1
    _assert_refused_with_limits(
        source,
        replace(exact, xref_entries=8),
        "raw_acroform_xref_entry_limit",
    )

    xref_offset = len(b"%PDF-1.7\n")
    hostile = (
        b"%PDF-1.7\nxref\n0 100001\n"
        b"trailer\n<< /Size 100001 >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    tracemalloc.start()
    _assert_refused(hostile, "raw_acroform_xref_entry_limit")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 1 * 1024 * 1024


def test_dictionary_cap_is_incremental_before_large_stack_allocation() -> None:
    entries = b" ".join(
        f"/K{index} 0".encode("ascii") for index in range(500_000)
    )
    source = _interactive_pdf(widget_extra=entries)
    tracemalloc.start()
    started = time.perf_counter()
    _assert_refused(source, "raw_acroform_dictionary_entry_limit")
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert elapsed < 1.0
    assert peak < 2 * 1024 * 1024


def test_object_byte_cap_is_incremental_during_container_growth() -> None:
    values = b" ".join([b"(" + b"A" * 300 + b")"] * 2_000)
    source = _interactive_pdf(widget_extra=b"/X [" + values + b"]")
    tracemalloc.start()
    started = time.perf_counter()
    _assert_refused(source, "raw_acroform_object_bytes_limit")
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert elapsed < 1.0
    assert peak < 4 * 1024 * 1024


def test_parser_nesting_is_rejected_while_context_stack_grows() -> None:
    nested = b"/X " + b"[" * 65 + b"0" + b"]" * 65
    _assert_refused(
        _interactive_pdf(widget_extra=nested),
        "raw_acroform_parser_nesting_limit",
    )


def test_nested_null_dictionary_on_nonwidget_annotation_is_lossless() -> None:
    def source(entry_count: int) -> bytes:
        entries = b" ".join(
            f"/K{index} null".encode("ascii")
            for index in range(entry_count)
        )
        return _classic_pdf(
            [
                b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /Annots [4 0 R] >>",
                b"<< /Type /Annot /Subtype /Link /X << "
                + entries
                + b" >> >>",
            ]
        )

    exact_source = source(256)
    exact = audit_acroform_raw(exact_source)
    assert exact.annotation_count == 0
    assert exact.accounted_tree_bytes > 256
    assert audit_acroform_raw(
        exact_source,
        limits=replace(
            DEFAULT_RAW_ACROFORM_LIMITS,
            tree_bytes=exact.accounted_tree_bytes,
        ),
    ).accounted_tree_bytes == exact.accounted_tree_bytes
    _assert_refused_with_limits(
        exact_source,
        replace(
            DEFAULT_RAW_ACROFORM_LIMITS,
            tree_bytes=exact.accounted_tree_bytes - 1,
        ),
        "raw_acroform_tree_bytes_limit",
    )
    _assert_refused(source(257), "raw_acroform_dictionary_entry_limit")

    duplicate = _classic_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /Annots [4 0 R] >>",
            b"<< /Type /Annot /Subtype /Link /X << /K null /K null >> >>",
        ]
    )
    _assert_refused(duplicate, "raw_acroform_duplicate_dictionary_key")


@pytest.mark.parametrize("opening", [b"(", b"%"])
def test_long_unterminated_tokens_stop_at_incremental_byte_cap(
    opening: bytes,
) -> None:
    source = _interactive_pdf(widget_extra=b"/X " + opening + b"A" * 1_000_000)
    tracemalloc.start()
    started = time.perf_counter()
    _assert_refused(source, "raw_acroform_token_bytes_limit")
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert elapsed < 1.0
    assert peak < 2 * 1024 * 1024


def test_forward_and_reverse_line_readers_are_incrementally_bounded() -> None:
    reverse_hostile = _interactive_pdf() + b"A" * 1_000_000
    tracemalloc.start()
    started = time.perf_counter()
    _assert_refused(reverse_hostile, "raw_acroform_token_bytes_limit")
    reverse_elapsed = time.perf_counter() - started
    _, reverse_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert reverse_elapsed < 1.0
    assert reverse_peak < 2 * 1024 * 1024

    header = b"%PDF-1.7\n"
    xref_offset = len(header)
    forward_hostile = (
        header
        + b"xref\n0 1\n"
        + b"0" * 1_000_000
        + b"\ntrailer\n<< /Size 1 >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    tracemalloc.start()
    started = time.perf_counter()
    _assert_refused(forward_hostile, "raw_acroform_token_bytes_limit")
    forward_elapsed = time.perf_counter() - started
    _, forward_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert forward_elapsed < 1.0
    assert forward_peak < 2 * 1024 * 1024


def test_predictor_decoders_use_bounded_bytearrays() -> None:
    assert _bounded_png_predictor(
        b"\x03\x0a\x0f\x14",
        colors=1,
        columns=3,
        bits=8,
        maximum=16,
        check_deadline=lambda: None,
    ) == b"\x0a\x14\x1e"

    png_size = 8 * 1024 * 1024
    columns = 4_096
    encoded_row = b"\x00" + b"x" * columns
    png_data = encoded_row * (png_size // columns)
    tracemalloc.start()
    png_result = _bounded_png_predictor(
        png_data,
        colors=1,
        columns=columns,
        bits=8,
        maximum=16 * 1024 * 1024,
        check_deadline=lambda: None,
    )
    _, png_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(png_result) == png_size
    assert png_peak < 24 * 1024 * 1024

    tiff_size = 512 * 1024
    tiff_data = b"\x01" * tiff_size
    tracemalloc.start()
    tiff_result = _bounded_tiff_predictor(
        tiff_data,
        colors=1,
        columns=columns,
        bits=8,
        maximum=16 * 1024 * 1024,
        check_deadline=lambda: None,
    )
    _, tiff_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(tiff_result) == tiff_size
    assert tiff_peak < 2 * 1024 * 1024


def test_nonfallback_stream_read_does_not_make_bytearray_and_bytes_copies() -> None:
    source = _interactive_pdf(
        widget_appearance=b"/AP << /N 6 0 R >>",
        appearance_content=b"A" * (4 * 1024 * 1024),
    )
    tracemalloc.start()
    _assert_refused(source, "raw_acroform_object_bytes_limit")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 6 * 1024 * 1024


def test_input_and_parser_resource_boundaries_are_exact() -> None:
    source = _interactive_pdf()
    exact = replace(DEFAULT_RAW_ACROFORM_LIMITS, pdf_bytes=len(source))
    assert audit_acroform_raw(source, limits=exact).annotation_count == 1

    too_small = replace(exact, pdf_bytes=len(source) - 1)
    _assert_refused_with_limits(
        source,
        too_small,
        "raw_acroform_pdf_bytes_limit",
    )

    baseline = audit_acroform_raw(source)
    ref_exact = replace(
        DEFAULT_RAW_ACROFORM_LIMITS,
        relevant_references=baseline.relevant_reference_count,
    )
    assert audit_acroform_raw(source, limits=ref_exact) == baseline
    _assert_refused_with_limits(
        source,
        replace(
            ref_exact,
            relevant_references=baseline.relevant_reference_count - 1,
        ),
        "raw_acroform_reference_limit",
    )


def _assert_refused_with_limits(source: bytes, limits: object, reason: str) -> None:
    with pytest.raises(RawAcroFormAuditError) as raised:
        audit_acroform_raw(source, limits=limits)  # type: ignore[arg-type]
    assert raised.value.reason_code == reason
