"""Deterministic readiness fixtures for P03-US07 outline structure.

Small PDFs are assembled directly with stable object numbers and document IDs;
non-PDF graph/resource fixtures are canonical dictionaries. Production code
must not import this test-only package.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal


FixtureKind = Literal["pdf", "outline_spec", "resource_spec"]

_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_DOCUMENT_ID = b"503033555330374f55544c494e45464958"

SYNTHETIC_THRESHOLDS: Mapping[str, int | float] = MappingProxyType(
    {
        "indent_tolerance_pt": 2.0,
        "minimum_indent_step_pt": 6.0,
        "maximum_source_characters_per_page": 500_000,
        "maximum_source_characters_per_document": 2_000_000,
        "maximum_source_words_per_page": 100_000,
        "maximum_source_words_per_document": 500_000,
        "maximum_marker_candidates_per_page": 2_048,
        "maximum_marker_candidates_per_document": 10_000,
        "maximum_depth": 8,
        "maximum_marker_bytes": 64,
        "maximum_item_text_bytes": 16 * 1024,
        "maximum_nodes_per_group": 256,
        "maximum_groups_per_page": 256,
        "maximum_groups_per_document": 2_048,
        "maximum_nodes_per_page": 4_096,
        "maximum_nodes_per_document": 32_768,
        "maximum_interstitials_per_group": 64,
        "maximum_relationships_per_page": 16_384,
        "maximum_relationships_per_document": 65_536,
        "maximum_comparisons_per_page": 65_536,
        "maximum_public_group_bytes": 512 * 1024,
        "maximum_report_bytes": 8 * 1024 * 1024,
        "maximum_concerns_per_page": 64,
        "maximum_concerns_per_document": 256,
        "source_extraction_deadline_seconds": 2.0,
        "projection_page_deadline_seconds": 0.25,
        "projection_document_deadline_seconds": 2.0,
    }
)

REQUIRED_SYNTHETIC_COVERAGE = (
    "nested_unordered_list",
    "ordered_numeric_list",
    "ordered_parenthesized_alpha_list",
    "legal_table_interruption",
    "broken_sequence_refusal",
    "parenthesized_prose_non_target",
    "financial_rows_non_target",
    "ambiguous_indentation_refusal",
    "marker_html_injection",
    "unicode_confusable_marker_refusal",
    "duplicate_node_refusal",
    "cycle_refusal",
    "multiple_parent_refusal",
    "skipped_level_refusal",
    "cross_page_parent_refusal",
    "malformed_bbox_refusal",
    "marker_byte_limit",
    "item_text_byte_limit",
    "depth_limit",
    "nodes_per_group_limit",
    "groups_per_page_limit",
    "groups_per_document_limit",
    "nodes_per_page_limit",
    "nodes_per_document_limit",
    "interstitial_limit",
    "relationship_page_limit",
    "relationship_document_limit",
    "comparison_limit",
    "public_group_byte_limit",
    "report_byte_limit",
    "deadline_refusal",
    "page_transaction_rollback",
    "document_transaction_rollback",
    "flag_off_zero_work",
    "idempotent_projection",
    "terminal_source_alignment_reentry",
    "form_contributor_exclusion",
)


@dataclass(frozen=True, slots=True)
class SyntheticFixtureDefinition:
    """Registry metadata for one deterministic readiness fixture."""

    fixture_id: str
    kind: FixtureKind
    purpose: str
    covers: tuple[str, ...]


class SyntheticFixtureIntegrityError(RuntimeError):
    """Raised when registry coverage or deterministic fixture bytes drift."""


@dataclass(frozen=True, slots=True)
class ResourceBoundaryWitness:
    """One isolated, executable exact or maximum+1 resource witness."""

    counter: str
    limit: int
    observed: int
    unit: Literal["characters", "words", "items", "utf8_bytes", "json_bytes"]
    scope: Literal["candidate", "group", "page", "document"]
    payload: Any

    def measure(self) -> int:
        """Measure the real payload using the frozen production rule."""

        if self.unit == "characters":
            if not isinstance(self.payload, str):
                raise SyntheticFixtureIntegrityError("character payload is invalid")
            return len(self.payload)
        if self.unit in {"words", "items"}:
            if not isinstance(self.payload, tuple):
                raise SyntheticFixtureIntegrityError("count payload is invalid")
            return len(self.payload)
        if self.unit == "utf8_bytes":
            if not isinstance(self.payload, str):
                raise SyntheticFixtureIntegrityError("UTF-8 payload is invalid")
            return len(self.payload.encode("utf-8"))
        if not isinstance(self.payload, bytes):
            raise SyntheticFixtureIntegrityError("JSON byte payload is invalid")
        json.loads(self.payload.decode("utf-8"))
        return len(self.payload)

    def execute(self) -> bool:
        """Return acceptance at the inclusive boundary and refusal above it."""

        measured = self.measure()
        if measured != self.observed:
            raise SyntheticFixtureIntegrityError("boundary witness measurement drifted")
        return measured <= self.limit


@dataclass(frozen=True, slots=True)
class DeadlineWitness:
    """One executable injected-clock deadline boundary."""

    name: Literal[
        "source_extraction_deadline",
        "projection_page_deadline",
        "projection_document_deadline",
    ]
    limit_seconds: float
    elapsed_seconds: float

    def execute(self) -> bool:
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise SyntheticFixtureIntegrityError("deadline witness is invalid")
        return self.elapsed_seconds <= self.limit_seconds


def _stream(data: bytes) -> bytes:
    return (
        b"<< /Length "
        + str(len(data)).encode("ascii")
        + b" >>\nstream\n"
        + data
        + b"\nendstream"
    )


def _assemble_pdf(objects: Sequence[bytes]) -> bytes:
    parts = [_PDF_HEADER]
    offsets = [0]
    cursor = len(_PDF_HEADER)
    for object_number, body in enumerate(objects, start=1):
        serialized = f"{object_number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
        offsets.append(cursor)
        parts.append(serialized)
        cursor += len(serialized)

    xref_offset = cursor
    parts.extend(
        [
            f"xref\n0 {len(objects) + 1}\n".encode("ascii"),
            b"0000000000 65535 f \n",
            *(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]),
            (
                b"trailer\n<< /Size "
                + str(len(objects) + 1).encode("ascii")
                + b" /Root 1 0 R /ID [<"
                + _DOCUMENT_ID
                + b"><"
                + _DOCUMENT_ID
                + b">] >>\n"
            ),
            b"startxref\n",
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        ]
    )
    return b"".join(parts)


def _pdf_escape(value: str) -> bytes:
    encoded = value.encode("latin-1", errors="strict")
    return encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _single_page_pdf(
    lines: Sequence[tuple[float, float, str]],
    *,
    rules: Sequence[tuple[float, float, float, float]] = (),
) -> bytes:
    commands: list[bytes] = [b"BT /F1 12 Tf"]
    for x, y, value in lines:
        commands.append(
            f"1 0 0 1 {x:.3f} {y:.3f} Tm (".encode("ascii")
            + _pdf_escape(value)
            + b") Tj"
        )
    commands.append(b"ET")
    for x1, y1, x2, y2 in rules:
        commands.append(f"{x1:.3f} {y1:.3f} m {x2:.3f} {y2:.3f} l S".encode("ascii"))
    content = b"\n".join(commands)
    return _assemble_pdf(
        (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            _stream(content),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        )
    )


def _nested_unordered_pdf() -> bytes:
    return _single_page_pdf(
        (
            (72, 720, "- Root one"),
            (90, 700, "* Child one"),
            (90, 680, "* Child two"),
            (72, 660, "- Root two"),
        )
    )


def _ordered_numeric_pdf() -> bytes:
    return _single_page_pdf(
        (
            (72, 720, "1. First"),
            (72, 700, "2. Second"),
            (72, 680, "3. Third"),
        )
    )


def _parenthesized_alpha_pdf() -> bytes:
    return _single_page_pdf(
        (
            (72, 720, "(a) First clause"),
            (72, 700, "(b) Second clause"),
            (72, 680, "(c) Third clause"),
        )
    )


def _legal_table_interruption_pdf() -> bytes:
    rules = (
        (90, 680, 420, 680),
        (90, 640, 420, 640),
        (90, 600, 420, 600),
        (90, 600, 90, 680),
        (260, 600, 260, 680),
        (420, 600, 420, 680),
    )
    return _single_page_pdf(
        (
            (72, 740, "a. First clause"),
            (72, 710, "b. Second clause"),
            (100, 655, "Threshold"),
            (280, 655, "Percent"),
            (100, 615, "Example"),
            (280, 615, "10%"),
            (72, 570, "c. Third clause"),
        ),
        rules=rules,
    )


def _broken_sequence_pdf() -> bytes:
    return _single_page_pdf(
        (
            (72, 720, "a. First"),
            (72, 700, "c. Broken"),
            (72, 680, "d. Still broken"),
        )
    )


def _parenthesized_prose_pdf() -> bytes:
    return _single_page_pdf(
        (
            (72, 720, "The result (a) remains ordinary prose."),
            (72, 700, "A single (b) reference is not a list."),
        )
    )


def _financial_rows_pdf() -> bytes:
    return _single_page_pdf(
        (
            (72, 720, "Revenue 1. 100"),
            (72, 700, "Tax expense (25)"),
            (72, 680, "Net income 75"),
        )
    )


def _ambiguous_indentation_pdf() -> bytes:
    return _single_page_pdf(
        (
            (72, 720, "- Root"),
            (75, 700, "- Ambiguous offset"),
            (72, 680, "- Root again"),
        )
    )


def _marker_injection_pdf() -> bytes:
    return _single_page_pdf(
        (
            (72, 720, "- <script>alert(1)</script>"),
            (72, 700, "- [unsafe](javascript:alert(1))"),
        )
    )


def _graph_failure_spec() -> dict[str, Any]:
    return {
        "duplicate_node_ids": ["node-1", "node-1"],
        "cycle": [("node-1", "node-2"), ("node-2", "node-1")],
        "multiple_parents": [("node-1", "node-3"), ("node-2", "node-3")],
        "skipped_level": [0, 2],
        "cross_page_parent": {"parent_page": 1, "child_page": 2},
        "malformed_bbox": {
            "x": {"invalid_number": "nan"},
            "y": 0,
            "width": -1,
            "height": 1,
        },
        "confusable_markers": ["．", "｡", "․", "ꓸ"],
    }


def build_nonfinite_bbox_witness() -> dict[str, float]:
    """Return an in-memory NaN witness that is intentionally not JSON data."""

    return {"x": float("nan"), "y": 0.0, "width": 1.0, "height": 1.0}


_RESOURCE_WITNESS_RULES: Mapping[
    str,
    tuple[
        Literal["characters", "words", "items", "utf8_bytes", "json_bytes"],
        Literal["candidate", "group", "page", "document"],
    ],
] = MappingProxyType(
    {
        "maximum_source_characters_per_page": ("characters", "page"),
        "maximum_source_characters_per_document": ("characters", "document"),
        "maximum_source_words_per_page": ("words", "page"),
        "maximum_source_words_per_document": ("words", "document"),
        "maximum_marker_candidates_per_page": ("items", "page"),
        "maximum_marker_candidates_per_document": ("items", "document"),
        "maximum_marker_bytes": ("utf8_bytes", "candidate"),
        "maximum_item_text_bytes": ("utf8_bytes", "candidate"),
        "maximum_depth": ("items", "group"),
        "maximum_nodes_per_group": ("items", "group"),
        "maximum_groups_per_page": ("items", "page"),
        "maximum_groups_per_document": ("items", "document"),
        "maximum_nodes_per_page": ("items", "page"),
        "maximum_nodes_per_document": ("items", "document"),
        "maximum_interstitials_per_group": ("items", "group"),
        "maximum_relationships_per_page": ("items", "page"),
        "maximum_relationships_per_document": ("items", "document"),
        "maximum_comparisons_per_page": ("items", "page"),
        "maximum_public_group_bytes": ("json_bytes", "group"),
        "maximum_report_bytes": ("json_bytes", "document"),
        "maximum_concerns_per_page": ("items", "page"),
        "maximum_concerns_per_document": ("items", "document"),
    }
)


def build_resource_boundary_witness(
    counter: str,
    *,
    maximum_plus_one: bool = False,
) -> ResourceBoundaryWitness:
    """Materialize one isolated real payload at an inclusive resource edge."""

    if counter not in _RESOURCE_WITNESS_RULES:
        raise KeyError(f"unknown resource counter: {counter}")
    raw_limit = SYNTHETIC_THRESHOLDS[counter]
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        raise SyntheticFixtureIntegrityError("resource counter is not integral")
    observed = raw_limit + int(maximum_plus_one)
    unit, scope = _RESOURCE_WITNESS_RULES[counter]
    if unit == "characters":
        payload: Any = "x" * observed
    elif unit == "words":
        payload = ("word",) * observed
    elif unit == "utf8_bytes":
        payload = "x" * observed
    elif unit == "json_bytes":
        if observed < 2:
            raise SyntheticFixtureIntegrityError("JSON byte cap is too small")
        payload = b'"' + (b"x" * (observed - 2)) + b'"'
    else:
        payload = tuple(range(observed))
    return ResourceBoundaryWitness(
        counter=counter,
        limit=raw_limit,
        observed=observed,
        unit=unit,
        scope=scope,
        payload=payload,
    )


def build_deadline_witness(
    name: str,
    *,
    maximum_plus_one: bool = False,
) -> DeadlineWitness:
    """Build an exact or one-microsecond-over injected-clock witness."""

    threshold_name = {
        "source_extraction_deadline": "source_extraction_deadline_seconds",
        "projection_page_deadline": "projection_page_deadline_seconds",
        "projection_document_deadline": "projection_document_deadline_seconds",
    }.get(name)
    if threshold_name is None:
        raise KeyError(f"unknown deadline: {name}")
    limit = float(SYNTHETIC_THRESHOLDS[threshold_name])
    return DeadlineWitness(
        name=name,  # type: ignore[arg-type]
        limit_seconds=limit,
        elapsed_seconds=limit + (0.000_001 if maximum_plus_one else 0.0),
    )


def _resource_boundary_spec() -> dict[str, Any]:
    return {
        "thresholds": dict(SYNTHETIC_THRESHOLDS),
        "boundaries": {
            key: {"exact": value, "maximum_plus_one": value + 1}
            for key, value in SYNTHETIC_THRESHOLDS.items()
            if isinstance(value, int)
        },
        "failure_injections": (
            "source_extraction_deadline",
            "projection_page_deadline",
            "projection_document_deadline",
            "page_transaction",
            "document_transaction",
            "terminal_source_alignment_reentry",
        ),
        "coexistence": {
            "exclude_form_contributors": True,
            "flag_off_zero_work": True,
            "projection_idempotent": True,
        },
    }


_BUILDERS: dict[str, Callable[[], Any]] = {
    "synthetic:p03-us07:nested-unordered-v1": _nested_unordered_pdf,
    "synthetic:p03-us07:ordered-numeric-v1": _ordered_numeric_pdf,
    "synthetic:p03-us07:parenthesized-alpha-v1": _parenthesized_alpha_pdf,
    "synthetic:p03-us07:legal-table-interruption-v1": _legal_table_interruption_pdf,
    "synthetic:p03-us07:broken-sequence-v1": _broken_sequence_pdf,
    "synthetic:p03-us07:parenthesized-prose-v1": _parenthesized_prose_pdf,
    "synthetic:p03-us07:financial-rows-v1": _financial_rows_pdf,
    "synthetic:p03-us07:ambiguous-indentation-v1": _ambiguous_indentation_pdf,
    "synthetic:p03-us07:marker-injection-v1": _marker_injection_pdf,
    "synthetic:p03-us07:graph-failures-v1": _graph_failure_spec,
    "synthetic:p03-us07:resource-boundaries-v1": _resource_boundary_spec,
}

SYNTHETIC_FIXTURES: tuple[SyntheticFixtureDefinition, ...] = (
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:nested-unordered-v1",
        "pdf",
        "Two-level unordered list with two children.",
        ("nested_unordered_list",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:ordered-numeric-v1",
        "pdf",
        "Exact numeric sequence.",
        ("ordered_numeric_list",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:parenthesized-alpha-v1",
        "pdf",
        "Three separately grounded parenthesized alpha clauses.",
        ("ordered_parenthesized_alpha_list",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:legal-table-interruption-v1",
        "pdf",
        "Lettered outline with an aligned table between b and c.",
        ("legal_table_interruption",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:broken-sequence-v1",
        "pdf",
        "Broken alpha sequence must remain predecessor text.",
        ("broken_sequence_refusal",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:parenthesized-prose-v1",
        "pdf",
        "Inline parenthesized prose is a non-target.",
        ("parenthesized_prose_non_target",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:financial-rows-v1",
        "pdf",
        "Numeric and parenthesized financial values are non-targets.",
        ("financial_rows_non_target",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:ambiguous-indentation-v1",
        "pdf",
        "Offset below the minimum indent step must not invent depth.",
        ("ambiguous_indentation_refusal",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:marker-injection-v1",
        "pdf",
        "Marker content exercises HTML and Markdown escaping.",
        ("marker_html_injection",),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:graph-failures-v1",
        "outline_spec",
        "Confusable, duplicate, cyclic, multi-parent, skipped-level, cross-page, and bbox refusals.",
        (
            "unicode_confusable_marker_refusal",
            "duplicate_node_refusal",
            "cycle_refusal",
            "multiple_parent_refusal",
            "skipped_level_refusal",
            "cross_page_parent_refusal",
            "malformed_bbox_refusal",
        ),
    ),
    SyntheticFixtureDefinition(
        "synthetic:p03-us07:resource-boundaries-v1",
        "resource_spec",
        "Exact/max+1 limits, rollback, coexistence, and terminal re-entry.",
        (
            "marker_byte_limit",
            "item_text_byte_limit",
            "depth_limit",
            "nodes_per_group_limit",
            "groups_per_page_limit",
            "groups_per_document_limit",
            "nodes_per_page_limit",
            "nodes_per_document_limit",
            "interstitial_limit",
            "relationship_page_limit",
            "relationship_document_limit",
            "comparison_limit",
            "public_group_byte_limit",
            "report_byte_limit",
            "deadline_refusal",
            "page_transaction_rollback",
            "document_transaction_rollback",
            "flag_off_zero_work",
            "idempotent_projection",
            "terminal_source_alignment_reentry",
            "form_contributor_exclusion",
        ),
    ),
)


def _definition(fixture_id: str) -> SyntheticFixtureDefinition:
    matches = [item for item in SYNTHETIC_FIXTURES if item.fixture_id == fixture_id]
    if len(matches) != 1:
        raise KeyError(f"unknown fixture: {fixture_id}")
    return matches[0]


def build_synthetic_fixture(fixture_id: str) -> dict[str, Any]:
    """Build one fresh deterministic fixture payload."""

    definition = _definition(fixture_id)
    payload = _BUILDERS[fixture_id]()
    return {
        "fixture_id": definition.fixture_id,
        "kind": definition.kind,
        "purpose": definition.purpose,
        "covers": list(definition.covers),
        "payload": payload if isinstance(payload, bytes) else deepcopy(payload),
    }


def _payload_digest(payload: Any) -> str:
    if isinstance(payload, bytes):
        encoded = payload
    else:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fixture_hashes() -> dict[str, str]:
    """Return deterministic payload hashes for every registered fixture."""

    return {
        definition.fixture_id: _payload_digest(
            build_synthetic_fixture(definition.fixture_id)["payload"]
        )
        for definition in SYNTHETIC_FIXTURES
    }


def registry_sha256() -> str:
    """Return a stable semantic digest for metadata and payload identities."""

    payload = [
        {
            "fixture_id": definition.fixture_id,
            "kind": definition.kind,
            "purpose": definition.purpose,
            "covers": definition.covers,
            "payload_sha256": fixture_hashes()[definition.fixture_id],
        }
        for definition in SYNTHETIC_FIXTURES
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def self_check() -> None:
    """Validate uniqueness, complete coverage, and deterministic rebuilding."""

    fixture_ids = [definition.fixture_id for definition in SYNTHETIC_FIXTURES]
    if len(fixture_ids) != len(set(fixture_ids)):
        raise SyntheticFixtureIntegrityError("fixture IDs must be unique")
    if set(fixture_ids) != set(_BUILDERS):
        raise SyntheticFixtureIntegrityError("fixture registry/builders differ")
    covered = {
        capability
        for definition in SYNTHETIC_FIXTURES
        for capability in definition.covers
    }
    if covered != set(REQUIRED_SYNTHETIC_COVERAGE):
        raise SyntheticFixtureIntegrityError("required coverage is incomplete")
    first = fixture_hashes()
    second = fixture_hashes()
    if first != second or len(first) != len(SYNTHETIC_FIXTURES):
        raise SyntheticFixtureIntegrityError("fixture payloads are not stable")


def verify_pdf_readers() -> None:
    """Require both supported local readers to open/render every PDF."""

    import pdfplumber
    import pypdfium2 as pdfium

    for definition in SYNTHETIC_FIXTURES:
        payload = build_synthetic_fixture(definition.fixture_id)["payload"]
        if not isinstance(payload, bytes):
            continue
        try:
            with pdfplumber.open(io.BytesIO(payload)) as document:
                if len(document.pages) != 1:
                    raise SyntheticFixtureIntegrityError(
                        f"{definition.fixture_id} pdfplumber page count drifted"
                    )
                _ = document.pages[0].objects
        except SyntheticFixtureIntegrityError:
            raise
        except Exception as exc:  # pragma: no cover - dependency detail varies
            raise SyntheticFixtureIntegrityError(
                f"pdfplumber could not open {definition.fixture_id}: "
                f"{type(exc).__name__}"
            ) from exc

        try:
            document = pdfium.PdfDocument(payload)
            try:
                if len(document) != 1:
                    raise SyntheticFixtureIntegrityError(
                        f"{definition.fixture_id} pdfium page count drifted"
                    )
                page = document[0]
                try:
                    bitmap = page.render(scale=0.25)
                    bitmap.close()
                finally:
                    page.close()
            finally:
                document.close()
        except SyntheticFixtureIntegrityError:
            raise
        except Exception as exc:  # pragma: no cover - dependency detail varies
            raise SyntheticFixtureIntegrityError(
                f"pypdfium2 could not render {definition.fixture_id}: "
                f"{type(exc).__name__}"
            ) from exc


__all__ = [
    "DeadlineWitness",
    "REQUIRED_SYNTHETIC_COVERAGE",
    "ResourceBoundaryWitness",
    "SYNTHETIC_FIXTURES",
    "SYNTHETIC_THRESHOLDS",
    "SyntheticFixtureDefinition",
    "SyntheticFixtureIntegrityError",
    "build_deadline_witness",
    "build_nonfinite_bbox_witness",
    "build_resource_boundary_witness",
    "build_synthetic_fixture",
    "fixture_hashes",
    "registry_sha256",
    "self_check",
    "verify_pdf_readers",
]
