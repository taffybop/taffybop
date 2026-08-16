"""Bounded raw-structure audit for AcroForm source objects.

``pdfminer.six`` intentionally exposes ordinary Python dictionaries and
``PDFObjRef`` instances.  During that conversion it collapses duplicate PDF
dictionary keys, drops entries whose value is PDF ``null``, and discards the
generation operand of indirect references.  Those behaviours are convenient
for rendering but are too lossy for source-evidence decisions.

This module uses a private, separately instantiated pdfminer reader that keeps
the lost metadata long enough to audit the AcroForm field graph, page widgets,
and appearance dictionaries.  Content and appearance stream *data* is never
tokenized.  Only xref streams and object streams, which contain PDF structure,
are decoded, under a shared byte limit.
"""

from __future__ import annotations

import io
import math
import time
import zlib
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pdfminer import settings as pdfminer_settings
from pdfminer.pdfdocument import (
    PDFBaseXRef,
    PDFDocument,
    PDFXRef,
    PDFXRefStream,
)
from pdfminer.pdfparser import PDFParser, PDFStreamParser, PDFSyntaxError
from pdfminer.pdftypes import (
    LITERALS_FLATE_DECODE,
    PDFObjRef,
    PDFStream,
    dict_value,
    int_value,
)
from pdfminer.psparser import (
    KEYWORD_ARRAY_BEGIN,
    KEYWORD_ARRAY_END,
    KEYWORD_DICT_BEGIN,
    KEYWORD_DICT_END,
    KEYWORD_PROC_BEGIN,
    KEYWORD_PROC_END,
    KWD,
    PSEOF,
    PSException,
    PSKeyword,
    PSLiteral,
    PSSyntaxError,
    PSTypeError,
    choplist,
    literal_name,
)


@dataclass(frozen=True, slots=True)
class RawAcroFormLimits:
    """Frozen resource limits for :func:`audit_acroform_raw`."""

    pdf_bytes: int = 25 * 1024 * 1024
    parser_tokens: int = 1_000_000
    parser_token_bytes: int = 256 * 1024
    decoded_structural_stream_bytes: int = 16 * 1024 * 1024
    xref_sections: int = 64
    xref_subsections: int = 4_096
    xref_entries: int = 100_000
    object_stream_objects: int = 65_536
    relevant_dictionaries: int = 20_000
    relevant_references: int = 32_768
    dictionary_entries: int = 256
    name_bytes: int = 256
    string_bytes: int = 16 * 1024
    array_items: int = 10_000
    parser_nesting: int = 64
    traversal_depth: int = 64
    field_depth: int = 32
    kids_per_field: int = 256
    fields: int = 10_000
    pages: int = 10_000
    annotations_per_page: int = 2_048
    annotations: int = 10_000
    object_bytes: int = 256 * 1024
    tree_bytes: int = 8 * 1024 * 1024
    total_key_bytes: int = 8 * 1024 * 1024


DEFAULT_RAW_ACROFORM_LIMITS = RawAcroFormLimits()


@dataclass(frozen=True, slots=True)
class RawAcroFormAudit:
    """Non-sensitive metrics returned by a successful structural audit."""

    acroform_present: bool
    relevant_dictionary_count: int
    relevant_reference_count: int
    field_count: int
    page_count: int
    annotation_count: int
    explicit_null_entry_count: int
    audited_key_bytes: int
    accounted_tree_bytes: int


class RawAcroFormAuditError(ValueError):
    """A sanitized, fail-closed raw AcroForm refusal."""

    def __init__(
        self,
        reason_code: str = "malformed_pdf_structure",
    ) -> None:
        super().__init__("Raw AcroForm structural audit failed closed")
        self.code = "form_source_evidence_unavailable"
        self.reason_code = reason_code


class _AuditFailure(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _validate_limits(limits: RawAcroFormLimits) -> None:
    for value in (
        limits.pdf_bytes,
        limits.parser_tokens,
        limits.parser_token_bytes,
        limits.decoded_structural_stream_bytes,
        limits.xref_sections,
        limits.xref_subsections,
        limits.xref_entries,
        limits.object_stream_objects,
        limits.relevant_dictionaries,
        limits.relevant_references,
        limits.dictionary_entries,
        limits.name_bytes,
        limits.string_bytes,
        limits.array_items,
        limits.parser_nesting,
        limits.traversal_depth,
        limits.field_depth,
        limits.kids_per_field,
        limits.fields,
        limits.pages,
        limits.annotations_per_page,
        limits.annotations,
        limits.object_bytes,
        limits.tree_bytes,
        limits.total_key_bytes,
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("raw AcroForm limits must be positive integers")


class _AuditBudget:
    def __init__(
        self,
        limits: RawAcroFormLimits,
        deadline_at: float,
    ) -> None:
        self.limits = limits
        self.deadline_at = deadline_at
        self.tokens = 0
        self.decoded_stream_bytes = 0
        self.xref_subsections = 0
        self.xref_entries = 0

    def check_deadline(self) -> None:
        if time.monotonic() > self.deadline_at:
            raise _AuditFailure("raw_acroform_deadline")

    def account_token(self) -> None:
        self.check_deadline()
        self.tokens += 1
        if self.tokens > self.limits.parser_tokens:
            raise _AuditFailure("raw_acroform_token_limit")

    def account_decoded_stream(self, size: int) -> None:
        self.check_deadline()
        self.decoded_stream_bytes += size
        if (
            self.decoded_stream_bytes
            > self.limits.decoded_structural_stream_bytes
        ):
            raise _AuditFailure("raw_acroform_decoded_stream_limit")

    def account_xref_subsection(self, entries: int) -> None:
        self.check_deadline()
        if entries < 0:
            raise _AuditFailure("malformed_pdf_structure")
        self.xref_subsections += 1
        self.xref_entries += entries
        if self.xref_subsections > self.limits.xref_subsections:
            raise _AuditFailure("raw_acroform_xref_subsection_limit")
        if self.xref_entries > self.limits.xref_entries:
            raise _AuditFailure("raw_acroform_xref_entry_limit")


class _AuditedDictionary(dict[str, Any]):
    """pdfminer-compatible dictionary retaining every original entry."""

    def __init__(
        self,
        pairs: Sequence[tuple[str, object]],
        *,
        parser_afob_size: int,
    ) -> None:
        self.raw_pairs = tuple(pairs)
        self.parser_afob_size = parser_afob_size
        super().__init__((key, value) for key, value in pairs if value is not None)


class _AuditedArray(list[Any]):
    """pdfminer-compatible array retaining its incremental AFOB size."""

    def __init__(self, values: Sequence[object], *, parser_afob_size: int) -> None:
        self.parser_afob_size = parser_afob_size
        super().__init__(values)


class _GenerationPDFObjRef(PDFObjRef):
    """A pdfminer reference that retains and enforces its generation."""

    def __init__(
        self,
        doc: PDFDocument | None,
        objid: int,
        generation: int | None,
    ) -> None:
        super().__init__(doc, objid)
        self.generation = generation

    def resolve(self, default: object = None) -> Any:
        if self.generation != 0:
            raise _AuditFailure("raw_acroform_nonzero_generation")
        return super().resolve(default)


def _lossless_afob_v1_size(
    value: object,
    *,
    limits: RawAcroFormLimits,
    budget: _AuditBudget,
) -> int:
    active: set[int] = set()
    operations = 0

    def visit(current: object, depth: int) -> int:
        nonlocal operations
        operations += 1
        if operations % 128 == 0:
            budget.check_deadline()
        if depth > limits.parser_nesting:
            raise _AuditFailure("raw_acroform_parser_nesting_limit")

        if current is None or isinstance(current, bool):
            size = 1
        elif isinstance(current, int):
            try:
                size = len(str(current).encode("ascii"))
            except (OverflowError, ValueError) as exc:
                raise _AuditFailure("raw_acroform_object_bytes_limit") from exc
        elif isinstance(current, float):
            if not math.isfinite(current):
                raise _AuditFailure("malformed_pdf_structure")
            size = len(format(current, ".17g").encode("ascii"))
        elif isinstance(current, PSLiteral):
            payload = current.name.encode("utf-8", errors="surrogatepass")
            if len(payload) > limits.name_bytes:
                raise _AuditFailure("raw_acroform_name_bytes_limit")
            size = 1 + len(payload)
        elif isinstance(current, bytes):
            if len(current) > limits.string_bytes:
                raise _AuditFailure("raw_acroform_string_bytes_limit")
            size = 2 + len(current)
        elif isinstance(current, str):
            payload = current.encode("utf-8", errors="surrogatepass")
            if len(payload) > limits.string_bytes:
                raise _AuditFailure("raw_acroform_string_bytes_limit")
            size = 2 + len(payload)
        elif isinstance(current, PDFObjRef):
            generation = getattr(current, "generation", None)
            if (
                isinstance(generation, bool)
                or not isinstance(generation, int)
                or generation < 0
            ):
                raise _AuditFailure("raw_acroform_metadata_unavailable")
            size = 4 + len(str(current.objid)) + len(str(generation))
        else:
            container_id = id(current)
            if container_id in active:
                raise _AuditFailure("malformed_pdf_structure")
            active.add(container_id)
            try:
                if isinstance(current, PDFStream):
                    if not isinstance(current.rawdata, bytes):
                        raise _AuditFailure("raw_acroform_metadata_unavailable")
                    base = len(current.rawdata)
                    children: Sequence[object] = (current.attrs,)
                elif isinstance(current, _AuditedDictionary):
                    pairs = current.raw_pairs
                    if len(pairs) > limits.dictionary_entries:
                        raise _AuditFailure(
                            "raw_acroform_dictionary_entry_limit"
                        )
                    keys = [key for key, _ in pairs]
                    if len(keys) != len(set(keys)):
                        raise _AuditFailure(
                            "raw_acroform_duplicate_dictionary_key"
                        )
                    key_payloads = tuple(
                        key.encode("utf-8", errors="surrogatepass")
                        for key in keys
                    )
                    if any(
                        len(payload) > limits.name_bytes
                        for payload in key_payloads
                    ):
                        raise _AuditFailure("raw_acroform_name_bytes_limit")
                    base = 2 + len(pairs) + sum(
                        1 + len(payload) for payload in key_payloads
                    )
                    children = tuple(child for _, child in pairs)
                elif isinstance(current, (list, tuple)):
                    if len(current) > limits.array_items:
                        raise _AuditFailure("raw_acroform_array_limit")
                    base = 2 + len(current)
                    children = current
                else:
                    raise _AuditFailure("raw_acroform_metadata_unavailable")

                if base > limits.object_bytes:
                    raise _AuditFailure("raw_acroform_object_bytes_limit")
                total = base
                for child in children:
                    total += visit(child, depth + 1)
                    if total > limits.object_bytes:
                        raise _AuditFailure(
                            "raw_acroform_object_bytes_limit"
                        )
                size = total
            finally:
                active.remove(container_id)

        if size > limits.object_bytes:
            raise _AuditFailure("raw_acroform_object_bytes_limit")
        return size

    result = visit(value, 0)
    budget.check_deadline()
    return result


def _bounded_flate_decode(data: bytes, maximum: int) -> bytes:
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(data, maximum + 1)
        if len(decoded) > maximum or decoder.unconsumed_tail:
            raise _AuditFailure("raw_acroform_decoded_stream_limit")
        remaining = maximum - len(decoded)
        decoded += decoder.flush(remaining + 1)
    except zlib.error as exc:
        raise _AuditFailure("malformed_pdf_structure") from exc
    if len(decoded) > maximum or not decoder.eof or decoder.unused_data:
        raise _AuditFailure("raw_acroform_decoded_stream_limit")
    return decoded


def _predictor_geometry(
    parameters: Mapping[str, object],
    maximum: int,
    *,
    png: bool,
) -> tuple[int, int, int]:
    try:
        raw_colors = parameters.get("Colors", 1)
        raw_columns = parameters.get("Columns", 1)
        raw_bits = parameters.get("BitsPerComponent", 8)
        if any(
            isinstance(value, bool)
            for value in (raw_colors, raw_columns, raw_bits)
        ):
            raise _AuditFailure("malformed_pdf_structure")
        colors = int_value(raw_colors)
        columns = int_value(raw_columns)
        bits = int_value(raw_bits)
    except _AuditFailure:
        raise
    except Exception as exc:
        raise _AuditFailure("malformed_pdf_structure") from exc

    allowed_bits = {1, 8} if png else {8}
    bytes_per_pixel = colors * bits // 8
    row_bytes = colors * columns * bits // 8
    if (
        colors < 1
        or columns < 1
        or bits not in allowed_bits
        or bytes_per_pixel < 1
        or row_bytes < 1
        or columns > maximum
        or bytes_per_pixel > maximum
        or row_bytes > maximum
    ):
        raise _AuditFailure("raw_acroform_predictor_limit")
    return colors, columns, bits


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _bounded_tiff_predictor(
    data: bytes,
    *,
    colors: int,
    columns: int,
    bits: int,
    maximum: int,
    check_deadline: Callable[[], None],
) -> bytes:
    bytes_per_pixel = colors * bits // 8
    row_bytes = colors * columns * bits // 8
    if len(data) > maximum or len(data) % row_bytes != 0:
        raise _AuditFailure("malformed_pdf_structure")
    output = bytearray(data)
    for row_start in range(0, len(output), row_bytes):
        check_deadline()
        for offset in range(bytes_per_pixel, row_bytes):
            if offset % 4_096 == 0:
                check_deadline()
            index = row_start + offset
            output[index] = (
                output[index] + output[index - bytes_per_pixel]
            ) & 0xFF
    return bytes(output)


def _bounded_png_predictor(
    data: bytes,
    *,
    colors: int,
    columns: int,
    bits: int,
    maximum: int,
    check_deadline: Callable[[], None],
) -> bytes:
    bytes_per_pixel = colors * bits // 8
    row_bytes = colors * columns * bits // 8
    encoded_row_bytes = row_bytes + 1
    if (
        len(data) > maximum
        or not data
        or len(data) % encoded_row_bytes != 0
    ):
        raise _AuditFailure("malformed_pdf_structure")

    source = memoryview(data)
    output = bytearray()
    input_offset = 0
    previous_row_start: int | None = None
    while input_offset < len(data):
        check_deadline()
        filter_type = data[input_offset]
        input_offset += 1
        input_end = input_offset + row_bytes
        if input_end > len(data) or len(output) + row_bytes > maximum:
            raise _AuditFailure("raw_acroform_decoded_stream_limit")
        row_start = len(output)
        output.extend(source[input_offset:input_end])

        if filter_type == 0:
            pass
        elif filter_type == 1:
            for offset in range(bytes_per_pixel, row_bytes):
                if offset % 4_096 == 0:
                    check_deadline()
                index = row_start + offset
                output[index] = (
                    output[index] + output[index - bytes_per_pixel]
                ) & 0xFF
        elif filter_type == 2:
            if previous_row_start is not None:
                for offset in range(row_bytes):
                    if offset % 4_096 == 0:
                        check_deadline()
                    index = row_start + offset
                    output[index] = (
                        output[index] + output[previous_row_start + offset]
                    ) & 0xFF
        elif filter_type == 3:
            for offset in range(row_bytes):
                if offset % 4_096 == 0:
                    check_deadline()
                index = row_start + offset
                left = (
                    output[index - bytes_per_pixel]
                    if offset >= bytes_per_pixel
                    else 0
                )
                above = (
                    output[previous_row_start + offset]
                    if previous_row_start is not None
                    else 0
                )
                output[index] = (output[index] + (left + above) // 2) & 0xFF
        elif filter_type == 4:
            for offset in range(row_bytes):
                if offset % 4_096 == 0:
                    check_deadline()
                index = row_start + offset
                has_left = offset >= bytes_per_pixel
                left = output[index - bytes_per_pixel] if has_left else 0
                above = (
                    output[previous_row_start + offset]
                    if previous_row_start is not None
                    else 0
                )
                upper_left = (
                    output[previous_row_start + offset - bytes_per_pixel]
                    if previous_row_start is not None and has_left
                    else 0
                )
                output[index] = (
                    output[index] + _paeth(left, above, upper_left)
                ) & 0xFF
        else:
            raise _AuditFailure("malformed_pdf_structure")

        previous_row_start = row_start
        input_offset = input_end
    return bytes(output)


class _BoundedPDFStream(PDFStream):
    def __init__(
        self,
        attrs: dict[str, Any],
        rawdata: bytes,
        decipher: Any,
        budget: _AuditBudget,
    ) -> None:
        super().__init__(attrs, rawdata, decipher)
        self._audit_budget = budget

    def decode(self) -> None:
        self._audit_budget.check_deadline()
        if self.data is not None or self.rawdata is None:
            raise _AuditFailure("malformed_pdf_structure")
        data = self.rawdata
        if self.decipher:
            if self.objid is None or self.genno is None:
                raise _AuditFailure("malformed_pdf_structure")
            data = self.decipher(
                self.objid,
                self.genno,
                data,
                self.attrs,
            )
            self._audit_budget.check_deadline()

        maximum = (
            self._audit_budget.limits.decoded_structural_stream_bytes
            - self._audit_budget.decoded_stream_bytes
        )
        if maximum < 1:
            raise _AuditFailure("raw_acroform_decoded_stream_limit")
        filters = self.get_filters()
        for filter_name, parameters in filters:
            self._audit_budget.check_deadline()
            if filter_name not in LITERALS_FLATE_DECODE:
                raise _AuditFailure("raw_acroform_stream_filter_unsupported")
            data = _bounded_flate_decode(data, maximum)
            self._audit_budget.check_deadline()
            if parameters and "Predictor" in parameters:
                predictor = int_value(parameters["Predictor"])
                if predictor == 1:
                    pass
                elif predictor == 2:
                    colors, columns, bits = _predictor_geometry(
                        parameters,
                        maximum,
                        png=False,
                    )
                    data = _bounded_tiff_predictor(
                        data,
                        colors=colors,
                        columns=columns,
                        bits=bits,
                        maximum=maximum,
                        check_deadline=self._audit_budget.check_deadline,
                    )
                elif predictor >= 10:
                    colors, columns, bits = _predictor_geometry(
                        parameters,
                        maximum,
                        png=True,
                    )
                    data = _bounded_png_predictor(
                        data,
                        colors=colors,
                        columns=columns,
                        bits=bits,
                        maximum=maximum,
                        check_deadline=self._audit_budget.check_deadline,
                    )
                else:
                    raise _AuditFailure("malformed_pdf_structure")
                if len(data) > maximum:
                    raise _AuditFailure("raw_acroform_decoded_stream_limit")
                self._audit_budget.check_deadline()

        self._audit_budget.check_deadline()
        self._audit_budget.account_decoded_stream(len(data))
        self.data = data
        self.rawdata = None


def _parser_afob_size(value: object, limits: RawAcroFormLimits) -> int:
    if value is None or isinstance(value, bool):
        size = 1
    elif isinstance(value, int):
        try:
            size = len(str(value).encode("ascii"))
        except (OverflowError, ValueError) as exc:
            raise _AuditFailure("raw_acroform_object_bytes_limit") from exc
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise _AuditFailure("malformed_pdf_structure")
        size = len(format(value, ".17g").encode("ascii"))
    elif isinstance(value, PSLiteral):
        size = 1 + len(
            value.name.encode("utf-8", errors="surrogatepass")
        )
    elif isinstance(value, PSKeyword):
        size = 1 + len(value.name)
    elif isinstance(value, bytes):
        size = 2 + len(value)
    elif isinstance(value, str):
        size = 2 + len(value.encode("utf-8", errors="surrogatepass"))
    elif isinstance(value, PDFObjRef):
        generation = getattr(value, "generation", None)
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 0
        ):
            raise _AuditFailure("raw_acroform_metadata_unavailable")
        size = 4 + len(str(value.objid)) + len(str(generation))
    elif isinstance(value, (_AuditedArray, _AuditedDictionary)):
        size = value.parser_afob_size
    elif isinstance(value, PDFStream):
        if (
            not isinstance(value.rawdata, bytes)
            or not isinstance(value.attrs, _AuditedDictionary)
        ):
            raise _AuditFailure("raw_acroform_metadata_unavailable")
        size = len(value.rawdata) + value.attrs.parser_afob_size
    else:
        raise _AuditFailure("raw_acroform_metadata_unavailable")
    if size > limits.object_bytes:
        raise _AuditFailure("raw_acroform_object_bytes_limit")
    return size


class _AuditParserMixin:
    _audit_budget: _AuditBudget

    def reset(self) -> None:
        super().reset()
        self._audit_size_context: list[tuple[int, list[int]]] = []
        self._audit_current_size = 0
        self._audit_contributions: list[int] = []

    def _validate_materialized_token(self, token: object) -> None:
        if isinstance(token, PSLiteral):
            size = len(token.name.encode("utf-8", errors="surrogatepass"))
            if size > self._audit_budget.limits.name_bytes:
                raise _AuditFailure("raw_acroform_name_bytes_limit")
        elif isinstance(token, bytes):
            if len(token) > self._audit_budget.limits.string_bytes:
                raise _AuditFailure("raw_acroform_string_bytes_limit")
        elif isinstance(token, str):
            size = len(token.encode("utf-8", errors="surrogatepass"))
            if size > self._audit_budget.limits.string_bytes:
                raise _AuditFailure("raw_acroform_string_bytes_limit")

    def _current_token_limit(self) -> int:
        state_name = getattr(self._parse1, "__name__", "")
        if state_name in {"_parse_literal", "_parse_literal_hex"}:
            return self._audit_budget.limits.name_bytes
        if state_name in {
            "_parse_comment",
            "_parse_hexstring",
            "_parse_string",
            "_parse_string_1",
        }:
            return self._audit_budget.limits.string_bytes
        if state_name == "_parse_keyword":
            return self._audit_budget.limits.name_bytes
        return self._audit_budget.limits.parser_token_bytes

    def fillbuf(self) -> bool:
        self._audit_budget.check_deadline()
        if len(self._curtoken) > self._current_token_limit():
            raise _AuditFailure("raw_acroform_token_bytes_limit")
        result = super().fillbuf()
        self._audit_budget.check_deadline()
        return result

    def revreadlines(self) -> Iterator[bytes]:
        """Read trailer lines backward without quadratic concatenation."""

        self.fp.seek(0, io.SEEK_END)
        position = self.fp.tell()
        fragments: deque[bytes] = deque()
        buffered_bytes = 0
        maximum = self._audit_budget.limits.parser_token_bytes
        while position > 0:
            self._audit_budget.check_deadline()
            previous_position = position
            position = max(0, position - self.BUFSIZ)
            self.fp.seek(position)
            chunk = self.fp.read(previous_position - position)
            if not chunk:
                break
            while True:
                newline = max(chunk.rfind(b"\r"), chunk.rfind(b"\n"))
                if newline == -1:
                    buffered_bytes += len(chunk)
                    if buffered_bytes > maximum:
                        raise _AuditFailure("raw_acroform_token_bytes_limit")
                    fragments.appendleft(chunk)
                    break
                tail = chunk[newline:]
                if len(tail) + buffered_bytes > maximum:
                    raise _AuditFailure("raw_acroform_token_bytes_limit")
                yield b"".join((tail, *fragments))
                fragments.clear()
                buffered_bytes = 0
                chunk = chunk[:newline]

    def push(self, *objects: tuple[int, object]) -> None:
        projected_size = len(self.curstack) + len(objects)
        if (
            self.curtype == "d"
            and projected_size
            > self._audit_budget.limits.dictionary_entries * 2 + 2
        ):
            raise _AuditFailure("raw_acroform_dictionary_entry_limit")
        if (
            self.curtype in {"a", "p"}
            and projected_size > self._audit_budget.limits.array_items + 2
        ):
            raise _AuditFailure("raw_acroform_array_limit")
        contributions: list[int] = []
        running_size = self._audit_current_size
        for offset, (_, value) in enumerate(objects):
            item_size = _parser_afob_size(value, self._audit_budget.limits)
            stack_index = len(self.curstack) + offset
            if self.curtype == "d":
                if stack_index % 2 == 0:
                    contribution = (
                        2
                        + len(
                            value.name.encode(
                                "utf-8",
                                errors="surrogatepass",
                            )
                        )
                        if isinstance(value, PSLiteral)
                        else 1 + item_size
                    )
                else:
                    contribution = item_size
            elif self.curtype in {"a", "p"}:
                contribution = 1 + item_size
            else:
                contribution = item_size
            running_size += contribution
            if (
                self.curtype in {"a", "d", "p"}
                and running_size > self._audit_budget.limits.object_bytes
            ):
                raise _AuditFailure("raw_acroform_object_bytes_limit")
            contributions.append(contribution)
        super().push(*objects)
        self._audit_contributions.extend(contributions)
        self._audit_current_size = running_size

    def pop(self, count: int) -> list[tuple[int, object]]:
        values = cast(list[tuple[int, object]], super().pop(count))
        removed = self._audit_contributions[-count:] if count else []
        if count:
            self._audit_contributions[-count:] = []
        self._audit_current_size -= sum(removed)
        return values

    def popall(self) -> list[tuple[int, object]]:
        values = cast(list[tuple[int, object]], super().popall())
        self._audit_contributions = []
        self._audit_current_size = 0
        return values

    def start_type(self, position: int, object_type: str) -> None:
        if len(self.context) >= self._audit_budget.limits.parser_nesting:
            raise _AuditFailure("raw_acroform_parser_nesting_limit")
        self._audit_size_context.append(
            (self._audit_current_size, self._audit_contributions)
        )
        super().start_type(position, object_type)
        self._audit_current_size = 2
        self._audit_contributions = []

    def end_type(self, object_type: str) -> tuple[int, list[object]]:
        result = cast(tuple[int, list[object]], super().end_type(object_type))
        if not self._audit_size_context:
            raise _AuditFailure("malformed_pdf_structure")
        (
            self._audit_current_size,
            self._audit_contributions,
        ) = self._audit_size_context.pop()
        return result

    def nextline(self) -> tuple[int, bytes]:
        self._audit_budget.account_token()
        line = bytearray()
        line_position = self.bufpos + self.charpos
        saw_carriage_return = False
        maximum = self._audit_budget.limits.parser_token_bytes
        while True:
            self.fillbuf()
            if saw_carriage_return:
                if self.buf[self.charpos : self.charpos + 1] == b"\n":
                    line.append(0x0A)
                    self.charpos += 1
                break

            remaining = self.buf[self.charpos :]
            carriage_return = remaining.find(b"\r")
            line_feed = remaining.find(b"\n")
            candidates = tuple(
                value for value in (carriage_return, line_feed) if value >= 0
            )
            if candidates:
                end = min(candidates) + 1
                line.extend(remaining[:end])
                self.charpos += end
                if len(line) > maximum:
                    raise _AuditFailure("raw_acroform_token_bytes_limit")
                if line[-1] == 0x0D:
                    saw_carriage_return = True
                else:
                    break
            else:
                line.extend(remaining)
                self.charpos = len(self.buf)
                if len(line) > maximum:
                    raise _AuditFailure("raw_acroform_token_bytes_limit")
        return line_position, bytes(line)

    def nexttoken(self) -> tuple[int, object]:
        self._audit_budget.account_token()
        result = cast(tuple[int, object], super().nexttoken())
        self._validate_materialized_token(result[1])
        return result

    def nextobject(self) -> tuple[int, object]:
        """Pinned pdfminer stack conversion with lossless dictionaries."""

        while not self.results:
            position, token = self.nexttoken()
            if isinstance(token, (int, float, bool, str, bytes, PSLiteral)):
                self.push((position, token))
            elif token == KEYWORD_ARRAY_BEGIN:
                self.start_type(position, "a")
            elif token == KEYWORD_ARRAY_END:
                try:
                    if len(self.curstack) > self._audit_budget.limits.array_items:
                        raise _AuditFailure("raw_acroform_array_limit")
                    container_size = self._audit_current_size
                    array_position, values = self.end_type("a")
                    self.push(
                        (
                            array_position,
                            _AuditedArray(
                                values,
                                parser_afob_size=container_size,
                            ),
                        )
                    )
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif token == KEYWORD_DICT_BEGIN:
                self.start_type(position, "d")
            elif token == KEYWORD_DICT_END:
                try:
                    if (
                        len(self.curstack)
                        > self._audit_budget.limits.dictionary_entries * 2
                    ):
                        raise _AuditFailure(
                            "raw_acroform_dictionary_entry_limit"
                        )
                    container_size = self._audit_current_size
                    dictionary_position, objects = self.end_type("d")
                    if len(objects) % 2 != 0:
                        raise PSSyntaxError("Invalid dictionary construct")
                    pairs = tuple(
                        (literal_name(key), value)
                        for key, value in choplist(2, objects)
                    )
                    self.push(
                        (
                            dictionary_position,
                            _AuditedDictionary(
                                pairs,
                                parser_afob_size=container_size,
                            ),
                        )
                    )
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif token == KEYWORD_PROC_BEGIN:
                self.start_type(position, "p")
            elif token == KEYWORD_PROC_END:
                try:
                    container_size = self._audit_current_size
                    procedure_position, values = self.end_type("p")
                    self.push(
                        (
                            procedure_position,
                            _AuditedArray(
                                values,
                                parser_afob_size=container_size,
                            ),
                        )
                    )
                except PSTypeError:
                    if pdfminer_settings.STRICT:
                        raise
            elif isinstance(token, PSKeyword):
                self.do_keyword(position, token)
            else:
                self.do_keyword(position, token)
                raise PSException
            if not self.context:
                self.flush()
        return cast(tuple[int, object], self.results.pop(0))

    def do_keyword(self, position: int, token: PSKeyword) -> None:
        if token is self.KEYWORD_R:
            if len(self.curstack) >= 2:
                object_entry, generation_entry = self.pop(2)
                object_id = _safe_nonnegative_integer(object_entry[1])
                generation = _safe_nonnegative_integer(generation_entry[1])
                if object_id is not None:
                    self.push(
                        (
                            position,
                            _GenerationPDFObjRef(
                                self.doc,
                                object_id,
                                generation,
                            ),
                        )
                    )
            return

        if token is self.KEYWORD_STREAM:
            popped = self.pop(1)
            try:
                ((_, dictionary),) = popped
            except ValueError as exc:
                raise PDFSyntaxError("Invalid stream dictionary") from exc
            dictionary = dict_value(dictionary)
            object_length = 0
            if not self.fallback:
                try:
                    object_length = int_value(dictionary["Length"])
                except KeyError as exc:
                    if pdfminer_settings.STRICT:
                        raise PDFSyntaxError("Stream length is undefined") from exc
            if object_length < 0 or object_length > self._audit_budget.limits.pdf_bytes:
                raise _AuditFailure("raw_acroform_stream_length_limit")
            self.seek(position)
            try:
                _, line = self.nextline()
            except PSEOF as exc:
                raise PDFSyntaxError("Unexpected EOF") from exc
            position += len(line)
            self.fp.seek(position)
            if self.fallback:
                raise _AuditFailure("raw_acroform_fallback_disabled")
            data = self.fp.read(object_length)
            if len(data) != object_length:
                raise _AuditFailure("malformed_pdf_structure")
            self.seek(position + object_length)
            while True:
                try:
                    _, line = self.nextline()
                except PSEOF:
                    if pdfminer_settings.STRICT:
                        raise PDFSyntaxError("Unexpected EOF") from None
                    break
                if b"endstream" in line:
                    marker = line.index(b"endstream")
                    object_length += marker
                    break
                object_length += len(line)
                if object_length > self._audit_budget.limits.pdf_bytes:
                    raise _AuditFailure("raw_acroform_stream_length_limit")
            self.seek(position + object_length)
            if self.doc is None:
                raise _AuditFailure("malformed_pdf_structure")
            stream = _BoundedPDFStream(
                dictionary,
                data,
                self.doc.decipher,
                self._audit_budget,
            )
            self.push((position, stream))
            return

        super().do_keyword(position, token)


def _safe_nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class _AuditPDFParser(_AuditParserMixin, PDFParser):
    def __init__(self, stream: io.BytesIO, budget: _AuditBudget) -> None:
        self._audit_budget = budget
        super().__init__(stream)


class _AuditPDFStreamParser(_AuditParserMixin, PDFStreamParser):
    def __init__(self, data: bytes, budget: _AuditBudget) -> None:
        self._audit_budget = budget
        PDFParser.__init__(self, io.BytesIO(data))


class _BoundedPDFXRef(PDFXRef):
    def __init__(self, budget: _AuditBudget) -> None:
        super().__init__()
        self._audit_budget = budget

    def load(self, parser: PDFParser) -> None:
        while True:
            self._audit_budget.check_deadline()
            try:
                position, line = parser.nextline()
            except PSEOF as exc:
                raise _AuditFailure("malformed_pdf_structure") from exc
            line = line.strip()
            if not line:
                continue
            if line.startswith(b"trailer"):
                parser.seek(position)
                break
            subsection = line.split()
            if len(subsection) != 2:
                raise _AuditFailure("malformed_pdf_structure")
            try:
                start, count = (int(value) for value in subsection)
            except ValueError as exc:
                raise _AuditFailure("malformed_pdf_structure") from exc
            if start < 0:
                raise _AuditFailure("malformed_pdf_structure")
            self._audit_budget.account_xref_subsection(count)
            for object_id in range(start, start + count):
                try:
                    _, entry_line = parser.nextline()
                except PSEOF as exc:
                    raise _AuditFailure("malformed_pdf_structure") from exc
                entry = entry_line.strip().split()
                if len(entry) != 3:
                    raise _AuditFailure("malformed_pdf_structure")
                position_bytes, generation_bytes, use = entry
                if use != b"n":
                    continue
                try:
                    object_position = int(position_bytes)
                    generation = int(generation_bytes)
                except ValueError as exc:
                    raise _AuditFailure("malformed_pdf_structure") from exc
                if object_position < 0 or generation < 0:
                    raise _AuditFailure("malformed_pdf_structure")
                self.offsets[object_id] = (
                    None,
                    object_position,
                    generation,
                )
        self.load_trailer(parser)


class _AuditPDFDocument(PDFDocument):
    def __init__(
        self,
        parser: _AuditPDFParser,
        budget: _AuditBudget,
    ) -> None:
        self._audit_budget = budget
        self._audit_xref_positions: set[int] = set()
        super().__init__(parser, caching=True, fallback=False)

    def read_xref_from(
        self,
        parser: PDFParser,
        start: int,
        xrefs: list[PDFBaseXRef],
    ) -> None:
        self._audit_budget.check_deadline()
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or start < 0
            or start >= self._audit_budget.limits.pdf_bytes
            or start in self._audit_xref_positions
        ):
            raise _AuditFailure("malformed_pdf_structure")
        self._audit_xref_positions.add(start)
        if (
            len(self._audit_xref_positions)
            > self._audit_budget.limits.xref_sections
        ):
            raise _AuditFailure("raw_acroform_xref_limit")
        parser.seek(start)
        parser.reset()
        position, first_token = parser.nexttoken()
        if isinstance(first_token, int) and not isinstance(first_token, bool):
            _, generation = parser.nexttoken()
            if _safe_nonnegative_integer(generation) != 0:
                raise _AuditFailure("raw_acroform_nonzero_generation")
            parser.seek(position)
            parser.reset()
            xref: PDFBaseXRef = PDFXRefStream()
            xref.load(parser)
            if not isinstance(xref, PDFXRefStream):
                raise _AuditFailure("malformed_pdf_structure")
            widths = (xref.fl1, xref.fl2, xref.fl3)
            if any(
                isinstance(width, bool)
                or not isinstance(width, int)
                or width < 0
                for width in widths
            ):
                raise _AuditFailure("malformed_pdf_structure")
            total_entries = 0
            for range_start, range_count in xref.ranges:
                if range_start < 0:
                    raise _AuditFailure("malformed_pdf_structure")
                self._audit_budget.account_xref_subsection(range_count)
                total_entries += range_count
            if xref.entlen < 1 or total_entries * xref.entlen > len(xref.data):
                raise _AuditFailure("malformed_pdf_structure")
        else:
            if first_token is not parser.KEYWORD_XREF:
                raise _AuditFailure("malformed_pdf_structure")
            parser.nextline()
            xref = _BoundedPDFXRef(self._audit_budget)
            xref.load(parser)

        xrefs.append(xref)
        trailer = xref.get_trailer()
        if "XRefStm" in trailer:
            self.read_xref_from(
                parser,
                int_value(trailer["XRefStm"]),
                xrefs,
            )
        if "Prev" in trailer:
            self.read_xref_from(
                parser,
                int_value(trailer["Prev"]),
                xrefs,
            )

    def getobj(self, objid: int) -> object:
        self._audit_budget.check_deadline()
        for xref in self.xrefs:
            try:
                _, _, generation = xref.get_pos(objid)
            except KeyError:
                continue
            if generation != 0:
                raise _AuditFailure("raw_acroform_nonzero_generation")
            break
        return super().getobj(objid)

    def _getobj_parse(self, position: int, objid: int) -> object:
        parser = self._parser
        if parser is None:
            raise _AuditFailure("malformed_pdf_structure")
        parser.seek(position)
        _, parsed_object_id = parser.nexttoken()
        _, parsed_generation = parser.nexttoken()
        _, keyword = parser.nexttoken()
        if (
            parsed_object_id != objid
            or _safe_nonnegative_integer(parsed_generation) != 0
            or keyword != KWD(b"obj")
        ):
            raise _AuditFailure("raw_acroform_nonzero_generation")
        _, value = parser.nextobject()
        return value

    def _get_objects(self, stream: PDFStream) -> tuple[list[object], int]:
        self._audit_budget.check_deadline()
        try:
            count = int_value(stream["N"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _AuditFailure("malformed_pdf_structure") from exc
        if count < 0 or count > self._audit_budget.limits.object_stream_objects:
            raise _AuditFailure("raw_acroform_object_stream_limit")
        parser = _AuditPDFStreamParser(stream.get_data(), self._audit_budget)
        parser.set_document(self)
        objects: list[object] = []
        try:
            while True:
                _, value = parser.nextobject()
                objects.append(value)
                if len(objects) > count * 3 + 2:
                    raise _AuditFailure("malformed_pdf_structure")
        except PSEOF:
            pass
        if len(objects) != count * 3:
            raise _AuditFailure("malformed_pdf_structure")
        object_ids = objects[: count * 2 : 2]
        offsets = objects[1 : count * 2 : 2]
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for value in (*object_ids, *offsets)
        ):
            raise _AuditFailure("malformed_pdf_structure")
        if len(object_ids) != len(set(object_ids)):
            raise _AuditFailure("malformed_pdf_structure")
        if offsets and (
            offsets[0] != 0
            or any(left >= right for left, right in zip(offsets, offsets[1:]))
        ):
            raise _AuditFailure("malformed_pdf_structure")
        return objects, count

    def _getobj_objstm(
        self,
        stream: PDFStream,
        index: int,
        objid: int,
    ) -> object:
        if stream.objid in self._parsed_objs:
            objects, count = self._parsed_objs[stream.objid]
        else:
            objects, count = self._get_objects(stream)
            if self.caching:
                if stream.objid is None:
                    raise _AuditFailure("malformed_pdf_structure")
                self._parsed_objs[stream.objid] = (objects, count)
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= count
            or objects[index * 2] != objid
        ):
            raise _AuditFailure("malformed_pdf_structure")
        try:
            return objects[count * 2 + index]
        except IndexError as exc:
            raise _AuditFailure("malformed_pdf_structure") from exc


class _RawAcroFormWalker:
    def __init__(
        self,
        document: _AuditPDFDocument,
        budget: _AuditBudget,
    ) -> None:
        self.document = document
        self.budget = budget
        self.limits = budget.limits
        self.relevant_dictionary_ids: set[int] = set()
        self.relevant_reference_ids: set[tuple[int, int]] = set()
        self.field_ids: set[int] = set()
        self.page_ids: set[int] = set()
        self.annotation_ids: set[int] = set()
        self.afob_reference_ids: set[tuple[int, int]] = set()
        self.afob_direct_ids: set[int] = set()
        self.null_entries = 0
        self.key_bytes = 0
        self.tree_bytes = 0

    def run(self) -> RawAcroFormAudit:
        catalog = self._mapping(self.document.catalog)
        self._audit_mapping(catalog, target_keys={"AcroForm", "Pages"})
        self._reject_explicit_null(catalog, {"AcroForm", "Pages"})

        acroform_present = "AcroForm" in catalog
        if acroform_present:
            raw_acroform = catalog["AcroForm"]
            acroform = self._mapping(raw_acroform)
            if not isinstance(raw_acroform, PDFObjRef):
                self._account_direct_root(acroform)
            self._audit_mapping(acroform)
            self._reject_explicit_null(acroform, {"Fields"})
            fields = self._array(acroform.get("Fields", ()))
            self._walk_fields(fields)

        if "Pages" in catalog:
            self._walk_page_tree(catalog["Pages"])

        return RawAcroFormAudit(
            acroform_present=acroform_present,
            relevant_dictionary_count=len(self.relevant_dictionary_ids),
            relevant_reference_count=len(self.relevant_reference_ids),
            field_count=len(self.field_ids | self.annotation_ids),
            page_count=len(self.page_ids),
            annotation_count=len(self.annotation_ids),
            explicit_null_entry_count=self.null_entries,
            audited_key_bytes=self.key_bytes,
            accounted_tree_bytes=self.tree_bytes,
        )

    def _account_size(self, value: object) -> None:
        self.tree_bytes += _lossless_afob_v1_size(
            value,
            limits=self.limits,
            budget=self.budget,
        )
        if self.tree_bytes > self.limits.tree_bytes:
            raise _AuditFailure("raw_acroform_tree_bytes_limit")

    def _account_direct_root(self, value: object) -> None:
        identity = id(value)
        if identity in self.afob_direct_ids:
            return
        self.afob_direct_ids.add(identity)
        self._account_size(value)

    def _resolve(
        self,
        value: object,
        *,
        account_afob: bool = True,
    ) -> object:
        active: set[tuple[int, int]] = set()
        while isinstance(value, PDFObjRef):
            self.budget.check_deadline()
            generation = getattr(value, "generation", None)
            if generation != 0:
                raise _AuditFailure("raw_acroform_nonzero_generation")
            identity = (value.objid, generation)
            if identity in active:
                raise _AuditFailure("malformed_pdf_structure")
            active.add(identity)
            self.relevant_reference_ids.add(identity)
            if (
                len(self.relevant_reference_ids)
                > self.limits.relevant_references
            ):
                raise _AuditFailure("raw_acroform_reference_limit")
            try:
                resolved = self.document.getobj(value.objid)
            except _AuditFailure:
                raise
            except Exception as exc:
                raise _AuditFailure("malformed_pdf_structure") from exc
            if account_afob and identity not in self.afob_reference_ids:
                self.afob_reference_ids.add(identity)
                self._account_size(resolved)
            value = resolved
        return value

    def _mapping(
        self,
        value: object,
        *,
        account_afob: bool = True,
    ) -> _AuditedDictionary:
        value = self._resolve(value, account_afob=account_afob)
        if isinstance(value, PDFStream):
            value = value.attrs
        if not isinstance(value, _AuditedDictionary):
            raise _AuditFailure("raw_acroform_metadata_unavailable")
        return value

    def _array(
        self,
        value: object,
        *,
        account_afob: bool = True,
    ) -> Sequence[object]:
        value = self._resolve(value, account_afob=account_afob)
        if not isinstance(value, (list, tuple)):
            raise _AuditFailure("malformed_pdf_structure")
        if len(value) > self.limits.array_items:
            raise _AuditFailure("raw_acroform_array_limit")
        return value

    def _audit_mapping(
        self,
        mapping: _AuditedDictionary,
        *,
        target_keys: set[str] | None = None,
    ) -> None:
        identity = id(mapping)
        first_audit = identity not in self.relevant_dictionary_ids
        if first_audit:
            self.relevant_dictionary_ids.add(identity)
            if (
                len(self.relevant_dictionary_ids)
                > self.limits.relevant_dictionaries
            ):
                raise _AuditFailure("raw_acroform_dictionary_limit")

        pairs = mapping.raw_pairs
        if len(pairs) > self.limits.dictionary_entries:
            raise _AuditFailure("raw_acroform_dictionary_entry_limit")
        if any(
            len(key.encode("utf-8", errors="surrogatepass"))
            > self.limits.name_bytes
            for key, _ in pairs
        ):
            raise _AuditFailure("raw_acroform_name_bytes_limit")
        selected_keys = [
            key
            for key, _ in pairs
            if target_keys is None or key in target_keys
        ]
        if len(selected_keys) != len(set(selected_keys)):
            raise _AuditFailure("raw_acroform_duplicate_dictionary_key")

        if first_audit:
            self.null_entries += sum(value is None for _, value in pairs)
            self.key_bytes += sum(
                len(key.encode("utf-8", errors="surrogatepass"))
                for key, _ in pairs
            )
            if self.key_bytes > self.limits.total_key_bytes:
                raise _AuditFailure("raw_acroform_key_bytes_limit")

    @staticmethod
    def _reject_explicit_null(
        mapping: _AuditedDictionary,
        keys: set[str],
    ) -> None:
        if any(
            key in keys and value is None
            for key, value in mapping.raw_pairs
        ):
            raise _AuditFailure("raw_acroform_null_structural_value")

    def _walk_fields(self, roots: Sequence[object]) -> None:
        stack = [(value, 0, frozenset()) for value in reversed(roots)]
        while stack:
            raw_value, depth, ancestors = stack.pop()
            self.budget.check_deadline()
            if depth > self.limits.field_depth:
                raise _AuditFailure("raw_acroform_depth_limit")
            field = self._mapping(raw_value)
            field_identity = id(field)
            if field_identity in ancestors:
                raise _AuditFailure("raw_acroform_field_tree_cycle")
            if field_identity in self.field_ids:
                raise _AuditFailure("raw_acroform_field_tree_shared_node")
            self.field_ids.add(field_identity)
            child_ancestors = ancestors | {field_identity}
            if len(self.field_ids) > self.limits.fields:
                raise _AuditFailure("raw_acroform_field_limit")
            self._audit_mapping(field)
            self._reject_explicit_null(field, {"AP"})
            self._audit_appearance(field)
            self._walk_parent_chain(field)
            if "Kids" in field:
                kids = self._array(field["Kids"])
                if len(kids) > self.limits.kids_per_field:
                    raise _AuditFailure("raw_acroform_field_kids_limit")
                stack.extend(
                    (child, depth + 1, child_ancestors)
                    for child in reversed(kids)
                )

    def _walk_parent_chain(
        self,
        child: _AuditedDictionary,
    ) -> None:
        seen: set[int] = {id(child)}
        current = child
        depth = 0
        while "Parent" in current:
            depth += 1
            if depth > self.limits.field_depth:
                raise _AuditFailure("raw_acroform_depth_limit")
            parent = self._mapping(current["Parent"])
            if id(parent) in seen:
                raise _AuditFailure("raw_acroform_parent_cycle")
            seen.add(id(parent))
            self._audit_mapping(parent)
            self._reject_explicit_null(parent, {"AP"})
            self._audit_appearance(parent)
            current = parent

    def _walk_page_tree(self, root: object) -> None:
        stack = [(root, 1, frozenset())]
        seen: set[int] = set()
        total_annotations = 0
        while stack:
            raw_page, depth, ancestors = stack.pop()
            self.budget.check_deadline()
            if depth > self.limits.traversal_depth:
                raise _AuditFailure("raw_acroform_depth_limit")
            page = self._mapping(raw_page, account_afob=False)
            page_identity = id(page)
            if page_identity in ancestors:
                raise _AuditFailure("raw_acroform_page_tree_cycle")
            if page_identity in seen:
                raise _AuditFailure("raw_acroform_page_tree_shared_node")
            seen.add(page_identity)
            child_ancestors = ancestors | {page_identity}
            self._audit_mapping(
                page,
                target_keys={"Type", "Kids", "Annots"},
            )
            has_kids = "Kids" in page
            if has_kids:
                kids = self._array(page["Kids"], account_afob=False)
                stack.extend(
                    (child, depth + 1, child_ancestors)
                    for child in reversed(kids)
                )
            page_type = self._resolve(page.get("Type"), account_afob=False)
            if (
                not has_kids
                or isinstance(page_type, PSLiteral)
                and page_type.name == "Page"
            ):
                self.page_ids.add(page_identity)
                if len(self.page_ids) > self.limits.pages:
                    raise _AuditFailure("raw_acroform_page_limit")
            if "Annots" not in page:
                continue
            raw_annotations = page["Annots"]
            annotations = self._array(raw_annotations)
            if not isinstance(raw_annotations, PDFObjRef):
                self._account_direct_root(annotations)
            if len(annotations) > self.limits.annotations_per_page:
                raise _AuditFailure("raw_acroform_page_annotation_limit")
            total_annotations += len(annotations)
            if total_annotations > self.limits.annotations:
                raise _AuditFailure("raw_acroform_annotation_limit")
            for raw_annotation in annotations:
                annotation = self._mapping(raw_annotation)
                if not self._looks_like_widget(annotation):
                    continue
                self.annotation_ids.add(id(annotation))
                if (
                    len(self.field_ids | self.annotation_ids)
                    > self.limits.fields
                ):
                    raise _AuditFailure("raw_acroform_field_limit")
                self._audit_mapping(annotation)
                self._reject_explicit_null(annotation, {"AP"})
                self._audit_appearance(annotation)
                self._walk_parent_chain(annotation)

    def _looks_like_widget(self, mapping: _AuditedDictionary) -> bool:
        for key, raw_value in mapping.raw_pairs:
            if key != "Subtype":
                continue
            value = self._resolve(raw_value)
            if isinstance(value, PSLiteral) and value.name == "Widget":
                return True
        return False

    def _audit_appearance(self, owner: _AuditedDictionary) -> None:
        if "AP" not in owner:
            return
        appearance = self._mapping(owner["AP"])
        self._audit_mapping(appearance)
        self._reject_explicit_null(appearance, {"N"})
        if "N" not in appearance:
            return
        normal_appearance = self._resolve(appearance["N"])
        if isinstance(normal_appearance, PDFStream):
            return
        state_dictionary = self._mapping(normal_appearance)
        self._audit_mapping(state_dictionary)


def audit_acroform_raw(
    pdf_bytes: bytes,
    *,
    limits: RawAcroFormLimits = DEFAULT_RAW_ACROFORM_LIMITS,
    deadline_seconds: float = 2.0,
) -> RawAcroFormAudit:
    """Audit raw AcroForm/widget/AP structure before lossy normalization.

    Errors caused by document bytes always use :class:`RawAcroFormAuditError`
    with static reason codes and a constant message.  Invalid caller arguments
    use ordinary ``TypeError``/``ValueError`` exceptions.
    """

    if not isinstance(pdf_bytes, bytes):
        raise TypeError("pdf_bytes must be bytes")
    if not isinstance(limits, RawAcroFormLimits):
        raise TypeError("limits must be RawAcroFormLimits")
    _validate_limits(limits)
    if (
        isinstance(deadline_seconds, bool)
        or not isinstance(deadline_seconds, (int, float))
        or not math.isfinite(float(deadline_seconds))
        or deadline_seconds <= 0
    ):
        raise ValueError("deadline_seconds must be finite and positive")
    if len(pdf_bytes) > limits.pdf_bytes:
        raise RawAcroFormAuditError("raw_acroform_pdf_bytes_limit")

    budget = _AuditBudget(
        limits,
        time.monotonic() + float(deadline_seconds),
    )
    try:
        parser = _AuditPDFParser(io.BytesIO(pdf_bytes), budget)
        document = _AuditPDFDocument(parser, budget)
        budget.check_deadline()
        return _RawAcroFormWalker(document, budget).run()
    except RawAcroFormAuditError:
        raise
    except _AuditFailure as exc:
        raise RawAcroFormAuditError(exc.reason_code) from None
    except Exception:
        raise RawAcroFormAuditError() from None


__all__ = [
    "DEFAULT_RAW_ACROFORM_LIMITS",
    "RawAcroFormAudit",
    "RawAcroFormAuditError",
    "RawAcroFormLimits",
    "audit_acroform_raw",
]
