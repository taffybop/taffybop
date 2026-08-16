"""Release-first coverage for future adapter conformance and discovery."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.adapter_contracts import (
    AdapterDispatchError,
    AdapterManifest,
    AdapterRegistry,
    builtin_adapter_registry,
    conforming_test_manifest,
)
from app.services.future_adapter_gate import (
    FutureAdapterGate,
    FutureAdapterGateDisabledError,
    FutureAdapterGateError,
    compatibility_manifest_for,
    evaluate_future_adapter,
)
from app.services.input_documents import InputKind


FUTURE_MIME = "application/x-future-fixture"


def _future_enabled_settings() -> Settings:
    return Settings(
        adapters_conformance_enabled=True,
        adapters_image_parity_enabled=True,
        adapters_ooxml_intake_enabled=True,
        adapters_docx_native_enabled=True,
        adapters_pptx_native_enabled=True,
        adapters_xlsx_native_enabled=True,
        adapters_office_charts_enabled=True,
        adapters_office_fallback_enabled=True,
        adapters_future_conformance_gate_enabled=True,
    )


class _FutureAdapter:
    def __init__(self, compatibility_manifest: object | None = None) -> None:
        self._manifest = conforming_test_manifest(
            adapter_id="future-fixture",
            extension=".future",
            mime_type=FUTURE_MIME,
        )
        self.compatibility_manifest = (
            compatibility_manifest
            if compatibility_manifest is not None
            else compatibility_manifest_for(
                self._manifest.adapter_id,
                self._manifest.adapter_version,
            )
        )
        self.calls = 0

    @property
    def manifest(self) -> AdapterManifest:
        return self._manifest

    def load(self, data: bytes, filename: str, settings: Any) -> dict[str, object]:
        self.calls += 1
        return {
            "adapter_id": self._manifest.adapter_id,
            "data": data,
            "filename": filename,
            "settings": settings,
        }


def test_conforming_future_adapter_registers_advertises_and_dispatches() -> None:
    settings = _future_enabled_settings()
    gate = builtin_adapter_registry(settings)
    adapter = _FutureAdapter()

    result = gate.register(adapter)
    output = gate.dispatch(
        b"FTR1 future payload",
        "sample.future",
        FUTURE_MIME,
        settings,
    )

    assert result.accepted is True
    assert result.adapter_id == "future-fixture"
    assert result.reason_codes == ()
    assert result.manifest_sha256 is not None
    assert gate.enabled is True
    assert FUTURE_MIME in gate.advertised_mime_types()
    assert [value.adapter_id for value in gate.registrations] == [
        "builtin-image",
        "builtin-pdf",
        "docx-native",
        "future-fixture",
        "pptx-native",
        "xlsx-native",
    ]
    assert adapter.calls == 1
    assert output == {
        "adapter_id": "future-fixture",
        "data": b"FTR1 future payload",
        "filename": "sample.future",
        "settings": settings,
    }

    selection = gate.select(
        "sample.future",
        FUTURE_MIME,
        b"FTR1 future payload",
    )
    assert not hasattr(selection, "adapter")
    with pytest.raises(FutureAdapterGateError) as rebound:
        selection.load(b"wrong signature", "other.future", settings)
    assert rebound.value.code == "future_adapter_selection_input_mismatch"

    # A compatibility declaration that changes after acceptance no longer has
    # the immutable accepted digest. It is hidden and cannot dispatch, while
    # the approved current allowlist remains available through the same gate.
    adapter.compatibility_manifest.capability_tests.append("changed")
    assert FUTURE_MIME not in gate.advertised_mime_types()
    with pytest.raises(FutureAdapterGateError) as stale:
        gate.dispatch(
            b"FTR1 future payload",
            "sample.future",
            FUTURE_MIME,
            settings,
        )
    assert stale.value.code == "future_adapter_compatibility_stale"
    with pytest.raises(FutureAdapterGateError) as stale_selection:
        selection.load(b"FTR1 future payload", "sample.future", settings)
    assert stale_selection.value.code == "future_adapter_compatibility_stale"
    assert adapter.calls == 1
    loaded = gate.dispatch(
        b"prefix\n%PDF-1.7\nfixture\n",
        "document.pdf",
        "application/pdf",
        settings,
    )
    assert loaded.kind is InputKind.PDF


@pytest.mark.parametrize(
    "declaration",
    ["grounding", "limits", "fallback", "serialization", "rollback"],
)
def test_each_missing_essential_declaration_is_rejected_atomically(
    declaration: str,
) -> None:
    core = conforming_test_manifest(
        adapter_id="future-fixture",
        extension=".future",
        mime_type=FUTURE_MIME,
    )
    compatibility = compatibility_manifest_for(
        core.adapter_id,
        core.adapter_version,
    ).model_dump(mode="json")
    compatibility.pop(declaration)
    adapter = _FutureAdapter(compatibility)
    registry = AdapterRegistry()
    gate = FutureAdapterGate(registry, enabled=True)

    with pytest.raises(FutureAdapterGateError) as captured:
        gate.register(adapter)

    assert captured.value.code == (
        f"future_adapter_missing_{declaration}_declaration"
    )
    assert registry.registrations == ()
    assert gate.advertised_mime_types() == ()
    assert adapter.calls == 0


def test_direct_registry_bypass_is_not_advertised_or_dispatched() -> None:
    adapter = _FutureAdapter()
    registry = AdapterRegistry()
    gate = FutureAdapterGate(registry, enabled=True)

    # The gate surface never hands callers a mutable/raw registration or
    # dispatch capability. A constructor owner that deliberately retains its
    # own raw reference still cannot make that bypass visible through the gate.
    assert not hasattr(gate, "registry")
    assert not hasattr(gate, "_registry")

    # Deliberately bypass gate.register(). Core conformance alone must not
    # confer future compatibility approval.
    registry.register(adapter)

    assert evaluate_future_adapter(adapter).accepted is True
    assert gate.results == ()
    assert [value.adapter_id for value in registry.registrations] == [
        "future-fixture"
    ]
    assert gate.registrations == ()
    assert FUTURE_MIME not in gate.advertised_mime_types()
    with pytest.raises(FutureAdapterGateError) as captured:
        gate.dispatch(
            b"FTR1 future payload",
            "sample.future",
            FUTURE_MIME,
            object(),
        )
    assert captured.value.code == "future_adapter_compatibility_unaccepted"
    assert adapter.calls == 0

    # Public construction cannot bless raw registrations as approved-current;
    # the constructor has no caller-supplied ID/digest allowlist parameter.
    with pytest.raises(TypeError):
        FutureAdapterGate(
            registry,
            enabled=False,
            approved_registrations=registry.registrations,
        )
    registry._approved_current_registrations = lambda: registry.registrations
    injected = FutureAdapterGate(registry, enabled=False)
    assert injected.registrations == ()
    assert FUTURE_MIME not in injected.advertised_mime_types()


def test_gate_off_preserves_builtin_registration_advertising_and_dispatch() -> None:
    settings = Settings()
    gate = builtin_adapter_registry(settings)
    before_registrations = gate.registrations
    before_advertised = gate.advertised_mime_types()
    adapter = _FutureAdapter()

    assert gate.enabled is False
    with pytest.raises(AttributeError):
        gate.enabled = True
    with pytest.raises(FutureAdapterGateDisabledError) as captured:
        gate.register(adapter)

    assert captured.value.code == "future_adapter_gate_disabled"
    assert gate.registrations == before_registrations
    assert gate.advertised_mime_types() == before_advertised
    assert FUTURE_MIME not in gate.advertised_mime_types()
    loaded = gate.dispatch(
        b"prefix\n%PDF-1.7\nfixture\n",
        "document.pdf",
        "application/pdf",
        settings,
    )
    assert loaded.kind is InputKind.PDF

    enabled_gate = builtin_adapter_registry(_future_enabled_settings())
    mutable_adapter = _FutureAdapter()
    enabled_gate.register(mutable_adapter)
    mutable_adapter.load = None
    assert FUTURE_MIME not in enabled_gate.advertised_mime_types()
    with pytest.raises(AdapterDispatchError) as stale:
        enabled_gate.dispatch(
            b"FTR1 future payload",
            "sample.future",
            FUTURE_MIME,
            _future_enabled_settings(),
        )
    assert stale.value.code == "adapter_registration_stale"
