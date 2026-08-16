"""Release-first parser stage lifecycle instrumentation.

This module deliberately measures only monotonic elapsed time and lifecycle
outcomes.  It does not inspect the document, sample CPU or memory, discover
processes, or probe accelerators.  The fixed stage/format/outcome vocabulary is
validated again by :mod:`app.services.telemetry` before an event can be queued.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import PurePath
from typing import Any, Iterator, Literal

from app.services.telemetry import current_telemetry_client


StageName = Literal[
    "intake",
    "dispatch",
    "extraction",
    "analysis",
    "validation",
    "serialization",
    "complete",
]

_FORMAT_BY_SUFFIX = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tif": "image",
    ".tiff": "image",
    ".webp": "image",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}


def bounded_input_format(filename: str) -> str:
    """Map a filename to a fixed format label without retaining the filename."""

    return _FORMAT_BY_SUFFIX.get(PurePath(filename).suffix.casefold(), "unknown")


class StageLifecycle:
    """Best-effort, privacy-safe lifecycle events for one parse invocation."""

    __slots__ = ("_enabled", "_format")

    def __init__(self, settings: Any, *, filename: str) -> None:
        disabled_capabilities = tuple(
            getattr(settings, "parser_shipping_disabled_capabilities", ())
        )
        self._enabled = bool(
            getattr(settings, "telemetry_enabled", False)
            and getattr(settings, "telemetry_resources_enabled", False)
            and not getattr(settings, "parser_shipping_kill_switch", False)
            and "telemetry" not in disabled_capabilities
        )
        self._format = bounded_input_format(filename)

    def _emit(
        self,
        *,
        kind: Literal["event", "histogram"],
        stage: StageName,
        outcome: Literal["start", "finish", "success", "error"],
        value: float = 1.0,
        reason: Literal["raised", "completed"] | None = None,
    ) -> None:
        if not self._enabled:
            return
        labels = {
            "stage": stage,
            "outcome": outcome,
            "format": self._format,
        }
        if reason is not None:
            labels["reason"] = reason
        try:
            current_telemetry_client().emit(
                name="parser.stage.lifecycle",
                kind=kind,
                value=value,
                unit="milliseconds" if kind == "histogram" else "count",
                labels=labels,
            )
        except Exception:
            # Telemetry validation/client failures are side-channel failures.
            # Exporter exceptions and slow calls are isolated by TelemetryClient.
            return

    @staticmethod
    def _started_ns() -> int | None:
        try:
            return time.monotonic_ns()
        except Exception:
            return None

    @staticmethod
    def _elapsed_ms(started_ns: int | None) -> float | None:
        if started_ns is None:
            return None
        try:
            return max((time.monotonic_ns() - started_ns) / 1_000_000, 0.0)
        except Exception:
            return None

    @contextmanager
    def stage(self, stage: StageName) -> Iterator[None]:
        """Emit ordered start/duration/outcome/finish signals around a stage."""

        if not self._enabled:
            yield
            return

        self._emit(kind="event", stage=stage, outcome="start")
        started_ns = self._started_ns()
        try:
            yield
        except BaseException:
            elapsed_ms = self._elapsed_ms(started_ns)
            if elapsed_ms is not None:
                self._emit(
                    kind="histogram",
                    stage=stage,
                    outcome="error",
                    value=elapsed_ms,
                )
            self._emit(
                kind="event",
                stage=stage,
                outcome="error",
                reason="raised",
            )
            self._emit(
                kind="event",
                stage=stage,
                outcome="finish",
                reason="raised",
            )
            raise
        else:
            elapsed_ms = self._elapsed_ms(started_ns)
            if elapsed_ms is not None:
                self._emit(
                    kind="histogram",
                    stage=stage,
                    outcome="success",
                    value=elapsed_ms,
                )
            self._emit(
                kind="event",
                stage=stage,
                outcome="finish",
                reason="completed",
            )
