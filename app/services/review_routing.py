"""Grounded, bounded, queue-independent review escalation.

Review packets contain identifiers and source geometry only; they have no
field for document text, filenames, prompts, crops, credentials, or secrets.
The default runtime has no adapter.  Adapter failures and timeouts are isolated
on one bounded daemon worker and always return the unchanged parser result.
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Annotated, Iterator, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import ContentItem, ParseResult
from app.services.deterministic_confidence import DeterministicConfidence
from app.services.telemetry import current_telemetry_client
from app.services.visual_contracts import VisualStructure


Identifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"),
]
_MAX_PACKET_BYTES = 16_384


class _ReviewContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def exact_object(cls, value: Any) -> Any:
        if type(value) is cls:
            return value
        if type(value) is not dict:
            raise ValueError("review contract values must be exact objects")
        return value


class ReviewRegion(_ReviewContract):
    x: float = Field(ge=0.0, allow_inf_nan=False)
    y: float = Field(ge=0.0, allow_inf_nan=False)
    width: float = Field(gt=0.0, allow_inf_nan=False)
    height: float = Field(gt=0.0, allow_inf_nan=False)
    unit: Literal["pt", "px"]


class ReviewTolerance(_ReviewContract):
    absolute: float = Field(ge=0.0, allow_inf_nan=False)
    lower: float = Field(ge=0.0, allow_inf_nan=False)
    upper: float = Field(ge=0.0, allow_inf_nan=False)
    basis: Literal[
        "explicit_rounding",
        "vector_geometry",
        "raster_pixels",
        "axis_residual",
        "combined",
    ]

    @model_validator(mode="after")
    def cover_bounds(self) -> ReviewTolerance:
        if self.absolute + 1e-12 < max(self.lower, self.upper):
            raise ValueError("review tolerance does not cover its bounds")
        return self


class ReviewConfidenceDimension(_ReviewContract):
    dimension: Literal[
        "text",
        "layout",
        "table",
        "structure",
        "value",
        "relationship",
        "model_observation",
    ]
    outcome: Literal[
        "supported",
        "guarded",
        "unsupported",
        "unavailable",
        "withheld",
    ]
    basis: Literal["deterministic_rules", "validator_outcome"]


class ReviewPacket(_ReviewContract):
    """Private adapter payload: grounded metadata, never source content."""

    schema_version: Literal["1.0"] = "1.0"
    policy_id: Literal["p08-grounded-review-v1"] = "p08-grounded-review-v1"
    packet_id: Identifier
    element_id: Identifier
    physical_page: int = Field(ge=1, le=1_000_000)
    printed_page_label: str = Field(min_length=1, max_length=64)
    region: ReviewRegion
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)
    origin: Literal["source", "derived", "generated"]
    reason: Literal[
        "deterministic_concern",
        "deterministic_fallback",
        "deterministic_withhold",
        "visual_withheld",
    ]
    method: Literal[
        "text_evidence",
        "layout_geometry",
        "table_grid",
        "chart_mark",
        "chart_axis",
        "diagram_edge",
        "visual_grounding",
    ]
    confidence_dimensions: tuple[ReviewConfidenceDimension, ...] = Field(
        min_length=1,
        max_length=7,
    )
    tolerance: ReviewTolerance | None = None
    cost_units: int = Field(ge=1, le=1_000_000)

    @model_validator(mode="after")
    def bounded_and_canonical(self) -> ReviewPacket:
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("review evidence IDs must be sorted and unique")
        names = [value.dimension for value in self.confidence_dimensions]
        if names != sorted(set(names)):
            raise ValueError("review confidence dimensions must be sorted and unique")
        if any(ord(character) < 32 for character in self.printed_page_label):
            raise ValueError("printed page label contains a control character")
        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_PACKET_BYTES:
            raise ValueError("review packet exceeds its byte cap")
        return self


class ReviewSubmission(_ReviewContract):
    status: Literal["queued", "duplicate"]


class ReviewPublicStatus(_ReviewContract):
    """Content-free additive status; complete packets remain adapter-private."""

    schema_version: Literal["1.0"] = "1.0"
    policy_id: Literal["p08-grounded-review-v1"] = "p08-grounded-review-v1"
    status: Literal["queued", "duplicate", "queued_with_budget_fallback"]
    packet_count: int = Field(ge=1, le=64)
    total_cost_units: int = Field(ge=1, le=64_000_000)


class ReviewOutcome(_ReviewContract):
    outcome_id: Identifier
    packet_id: Identifier
    decision: Literal["accept", "reject", "correct", "unresolved"]


class ReviewAdapter(Protocol):
    """Queue-independent boundary; no live adapter ships in release-first."""

    def submit(
        self,
        packet: ReviewPacket,
        *,
        idempotency_key: str,
    ) -> ReviewSubmission: ...


@dataclass(frozen=True, slots=True)
class ReviewBudget:
    max_packets: int = 8
    max_regions: int = 8
    max_items: int = 256
    max_bytes: int = 65_536
    max_cost_units: int = 8
    cost_per_packet: int = 1

    def __post_init__(self) -> None:
        values = (
            ("max_packets", self.max_packets, 1, 64),
            ("max_regions", self.max_regions, 1, 64),
            ("max_items", self.max_items, 1, 65_536),
            ("max_bytes", self.max_bytes, 1_024, 1_048_576),
            ("max_cost_units", self.max_cost_units, 1, 64_000_000),
            ("cost_per_packet", self.cost_per_packet, 1, 1_000_000),
        )
        for name, value, minimum, maximum in values:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise ValueError(f"review {name} is outside its bound")


@dataclass(frozen=True, slots=True)
class ReviewRuntime:
    adapter: ReviewAdapter | None = None
    budget: ReviewBudget = ReviewBudget()
    timeout_ms: int = 50

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_ms, bool)
            or not isinstance(self.timeout_ms, int)
            or not 1 <= self.timeout_ms <= 5_000
        ):
            raise ValueError("review timeout must be between 1 and 5000 ms")


@dataclass(frozen=True, slots=True)
class ReviewRoutingResult:
    result: ParseResult
    packets: tuple[ReviewPacket, ...]
    status: Literal[
        "disabled",
        "no_candidates",
        "queued",
        "duplicate",
        "budget_exhausted",
        "unavailable",
        "timeout",
        "failed",
    ]
    adapter_calls: int


class ReviewOutcomeLedger:
    """Bounded idempotent outcomes, separate from immutable source truth."""

    def __init__(self, *, max_outcomes: int = 1_024) -> None:
        if not 1 <= max_outcomes <= 100_000:
            raise ValueError("review outcome bound is invalid")
        self._max = max_outcomes
        self._values: dict[str, ReviewOutcome] = {}
        self._lock = threading.Lock()

    def record(self, outcome: ReviewOutcome) -> bool:
        with self._lock:
            existing = self._values.get(outcome.outcome_id)
            if existing is not None:
                if existing != outcome:
                    raise ValueError("review outcome idempotency conflict")
                return False
            if len(self._values) >= self._max:
                raise ValueError("review outcome ledger is full")
            if any(
                value.packet_id == outcome.packet_id for value in self._values.values()
            ):
                raise ValueError("review packet already has an outcome")
            self._values[outcome.outcome_id] = outcome
            return True

    @property
    def outcomes(self) -> tuple[ReviewOutcome, ...]:
        with self._lock:
            return tuple(self._values[key] for key in sorted(self._values))


_DEFAULT_RUNTIME = ReviewRuntime()
_CURRENT_RUNTIME: ContextVar[ReviewRuntime] = ContextVar(
    "parser_review_runtime",
    default=_DEFAULT_RUNTIME,
)


@contextmanager
def use_review_runtime(runtime: ReviewRuntime) -> Iterator[ReviewRuntime]:
    token = _CURRENT_RUNTIME.set(runtime)
    try:
        yield runtime
    finally:
        _CURRENT_RUNTIME.reset(token)


def _emit_review(*, status: str) -> None:
    mapping = {
        "queued": ("accepted", "supported", "route"),
        "duplicate": ("accepted", "supported", "route"),
        "budget_exhausted": ("fallback", "budget_exhausted", "fallback"),
        "unavailable": ("fallback", "adapter_unavailable", "fallback"),
        "timeout": ("fallback", "timeout", "fallback"),
        "failed": ("error", "raised", "fallback"),
        "no_candidates": ("withheld", "unsupported", "skip"),
    }
    values = mapping.get(status)
    if values is None:
        return
    outcome, reason, decision = values
    try:
        current_telemetry_client().emit(
            name="parser.review.route",
            labels={
                "route": "review",
                "outcome": outcome,
                "reason": reason,
                "decision": decision,
            },
        )
    except Exception:
        return


def _region(value: Any) -> ReviewRegion | None:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        value = dump(mode="json")
    if not isinstance(value, Mapping):
        return None
    try:
        return ReviewRegion.model_validate(dict(value), strict=True)
    except (TypeError, ValueError, OverflowError):
        return None


def _origin(item: ContentItem) -> Literal["source", "derived", "generated"]:
    if item.source == "derived":
        return "derived"
    bundle = item.visual_model_evidence
    if bundle is not None and any(
        member.origin == "model_generated_description"
        for member in bundle.observations
    ):
        return "generated"
    return "source"


def _packet_id(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"review-{digest}"


def _visual_packet(
    item: ContentItem,
    *,
    physical_page: int,
    printed_page_label: str,
    cost_units: int,
) -> ReviewPacket | None:
    structure = item.visual_structure
    if structure is None or not (structure.fallback.active or structure.concerns):
        return None
    evidence_universe = {record.id for record in structure.evidence}
    evidence_ids = sorted(
        set(structure.region.evidence_ids)
        | {
            value
            for concern in structure.concerns
            for value in concern.evidence_ids
        }
    )
    if not evidence_ids or not set(evidence_ids) <= evidence_universe:
        return None
    region = _region(structure.region.page_bbox)
    if region is None:
        return None
    method: Literal[
        "chart_mark", "chart_axis", "diagram_edge", "visual_grounding"
    ] = (
        "chart_mark"
        if structure.points
        else "chart_axis"
        if structure.axes
        else "diagram_edge"
        if structure.connectors
        else "visual_grounding"
    )
    tolerance = None
    if structure.points:
        tolerance = ReviewTolerance.model_validate(
            structure.points[0].tolerance.model_dump(mode="json"),
            strict=True,
        )
    dimensions = (
        ReviewConfidenceDimension(
            dimension="structure",
            outcome="withheld",
            basis="validator_outcome",
        ),
    )
    seed = {
        "element_id": item.id,
        "physical_page": physical_page,
        "printed_page_label": printed_page_label,
        "evidence_ids": evidence_ids,
        "reason": "visual_withheld",
    }
    return ReviewPacket(
        packet_id=_packet_id(seed),
        element_id=item.id,
        physical_page=physical_page,
        printed_page_label=printed_page_label,
        region=region,
        evidence_ids=tuple(evidence_ids),
        origin=_origin(item),
        reason="visual_withheld",
        method=method,
        confidence_dimensions=dimensions,
        tolerance=tolerance,
        cost_units=cost_units,
    )


def _table_packet(
    item: ContentItem,
    *,
    physical_page: int,
    printed_page_label: str,
    dimension: Any,
    cost_units: int,
) -> ReviewPacket | None:
    evidence = item.table_evidence
    if evidence is None or dimension.decision not in {
        "concern",
        "fallback",
        "withhold",
    }:
        return None
    evidence_ids = sorted(record.id for record in evidence.evidence)
    region = _region(item.bbox)
    if not evidence_ids or region is None:
        return None
    reason = {
        "concern": "deterministic_concern",
        "fallback": "deterministic_fallback",
        "withhold": "deterministic_withhold",
    }[dimension.decision]
    seed = {
        "element_id": item.id,
        "physical_page": physical_page,
        "printed_page_label": printed_page_label,
        "evidence_ids": evidence_ids,
        "reason": reason,
    }
    return ReviewPacket(
        packet_id=_packet_id(seed),
        element_id=item.id,
        physical_page=physical_page,
        printed_page_label=printed_page_label,
        region=region,
        evidence_ids=tuple(evidence_ids),
        origin=_origin(item),
        reason=reason,
        method="table_grid",
        confidence_dimensions=(
            ReviewConfidenceDimension(
                dimension="table",
                outcome=dimension.level,
                basis="deterministic_rules",
            ),
        ),
        cost_units=cost_units,
    )


def build_review_packets(
    result: ParseResult,
    *,
    budget: ReviewBudget,
) -> tuple[tuple[ReviewPacket, ...], bool]:
    """Build deterministic grounded candidates and apply every hard budget."""

    raw_confidence = (result.model_extra or {}).get("deterministic_confidence")
    try:
        confidence = DeterministicConfidence.model_validate(raw_confidence)
    except (TypeError, ValueError):
        return (), False
    dimensions = {value.dimension: value for value in confidence.dimensions}
    candidates: list[tuple[int, int, str, ReviewPacket]] = []
    inspected = 0
    inspection_exhausted = False
    for page in result.pages:
        for item in page.items:
            if inspected == budget.max_items:
                inspection_exhausted = True
                break
            inspected += 1
            try:
                packet = _visual_packet(
                    item,
                    physical_page=page.page_index,
                    printed_page_label=page.page_label,
                    cost_units=budget.cost_per_packet,
                )
                if packet is None and item.type == "table":
                    packet = _table_packet(
                        item,
                        physical_page=page.page_index,
                        printed_page_label=page.page_label,
                        dimension=dimensions["table"],
                        cost_units=budget.cost_per_packet,
                    )
            except (TypeError, ValueError, OverflowError):
                # Public predecessor contracts permit some legacy identifiers
                # and empty page labels that the stricter private review
                # contract deliberately rejects.  Optional review must treat
                # those values as an unrouteable candidate, never as a parser
                # failure or as permission to weaken the packet contract.
                packet = None
            if packet is not None:
                priority = 0 if packet.reason in {
                    "deterministic_fallback",
                    "deterministic_withhold",
                    "visual_withheld",
                } else 1
                candidates.append(
                    (priority, page.page_index, item.id, packet)
                )
        if inspection_exhausted:
            break
    candidates.sort(key=lambda value: value[:3])
    selected: list[ReviewPacket] = []
    total_bytes = 0
    total_cost = 0
    exhausted = inspection_exhausted
    for _priority, _page, _element, packet in candidates:
        packet_bytes = len(
            json.dumps(
                packet.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if (
            len(selected) == budget.max_packets
            or len(selected) == budget.max_regions
            or total_bytes + packet_bytes > budget.max_bytes
            or total_cost + packet.cost_units > budget.max_cost_units
        ):
            exhausted = True
            continue
        selected.append(packet)
        total_bytes += packet_bytes
        total_cost += packet.cost_units
    return tuple(selected), exhausted


def _submit(
    packets: tuple[ReviewPacket, ...],
    *,
    adapter: ReviewAdapter,
    timeout_ms: int,
) -> tuple[tuple[ReviewSubmission, ...] | None, str, int]:
    results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=len(packets))
    cancelled = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def worker() -> None:
        nonlocal calls
        for packet in packets:
            if cancelled.is_set():
                return
            try:
                with calls_lock:
                    calls += 1
                response = adapter.submit(
                    packet,
                    idempotency_key=packet.packet_id,
                )
                if not isinstance(response, ReviewSubmission):
                    raise ValueError("review adapter returned an invalid response")
                results.put_nowait(("ok", response))
            except Exception as exc:
                results.put_nowait(("error", type(exc).__name__))
                return

    thread = threading.Thread(
        target=worker,
        name="parser-review-adapter",
        daemon=True,
    )
    thread.start()
    responses: list[ReviewSubmission] = []
    end = time.monotonic() + timeout_ms / 1_000
    for _packet in packets:
        remaining = end - time.monotonic()
        if remaining <= 0:
            cancelled.set()
            return None, "timeout", calls
        try:
            kind, value = results.get(timeout=remaining)
        except queue.Empty:
            cancelled.set()
            return None, "timeout", calls
        if kind == "error":
            cancelled.set()
            return None, "failed", calls
        responses.append(value)
    return tuple(responses), "queued", calls


def _with_public_status(
    result: ParseResult,
    *,
    packets: tuple[ReviewPacket, ...],
    submissions: tuple[ReviewSubmission, ...],
    budget_exhausted: bool,
) -> ParseResult:
    status: Literal["queued", "duplicate", "queued_with_budget_fallback"]
    if budget_exhausted:
        status = "queued_with_budget_fallback"
    elif all(value.status == "duplicate" for value in submissions):
        status = "duplicate"
    else:
        status = "queued"
    public = ReviewPublicStatus(
        status=status,
        packet_count=len(packets),
        total_cost_units=sum(value.cost_units for value in packets),
    )
    candidate = result.model_copy()
    extras = dict(result.model_extra or {})
    extras["review_routing"] = public.model_dump(mode="json")
    object.__setattr__(candidate, "__pydantic_extra__", extras)
    return candidate


def route_parse_result_for_review(
    result: ParseResult,
    *,
    enabled: bool,
    runtime: ReviewRuntime | None = None,
) -> ReviewRoutingResult:
    """Route grounded packets or preserve the predecessor exactly."""

    if not enabled:
        return ReviewRoutingResult(result, (), "disabled", 0)
    selected = runtime or _CURRENT_RUNTIME.get()
    packets, budget_exhausted = build_review_packets(
        result,
        budget=selected.budget,
    )
    if not packets:
        status = "budget_exhausted" if budget_exhausted else "no_candidates"
        _emit_review(status=status)
        return ReviewRoutingResult(result, (), status, 0)
    if selected.adapter is None:
        _emit_review(status="unavailable")
        return ReviewRoutingResult(result, packets, "unavailable", 0)
    submissions, submit_status, calls = _submit(
        packets,
        adapter=selected.adapter,
        timeout_ms=selected.timeout_ms,
    )
    if submissions is None:
        _emit_review(status=submit_status)
        return ReviewRoutingResult(result, packets, submit_status, calls)  # type: ignore[arg-type]
    final_status = (
        "duplicate"
        if all(value.status == "duplicate" for value in submissions)
        else "queued"
    )
    routed = _with_public_status(
        result,
        packets=packets,
        submissions=submissions,
        budget_exhausted=budget_exhausted,
    )
    _emit_review(status=final_status)
    return ReviewRoutingResult(routed, packets, final_status, calls)


__all__ = [
    "ReviewAdapter",
    "ReviewBudget",
    "ReviewConfidenceDimension",
    "ReviewOutcome",
    "ReviewOutcomeLedger",
    "ReviewPacket",
    "ReviewPublicStatus",
    "ReviewRegion",
    "ReviewRoutingResult",
    "ReviewRuntime",
    "ReviewSubmission",
    "ReviewTolerance",
    "build_review_packets",
    "route_parse_result_for_review",
    "use_review_runtime",
]
