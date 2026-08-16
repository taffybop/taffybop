from __future__ import annotations

import io

import pytest
from PIL import Image
from pydantic import ValidationError

from app.config import Settings
from app.services.adapter_contracts import (
    AdapterBoundingBox,
    AdapterCoordinateTransform,
    AdapterDispatchError,
    AdapterManifest,
    AdapterRegistrationError,
    AdapterRegistry,
    DeterministicAdapterTestDouble,
    MissingCapabilityAdapterTestDouble,
    builtin_adapter_registry,
    builtin_image_adapter,
    builtin_pdf_adapter,
    conforming_test_manifest,
    validate_adapter_conformance,
)
from app.services.input_documents import InputKind, load_document


VALID_PDF = b"prefix\n%PDF-1.7\nfixture\n"


def _png_bytes() -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (4, 3), "white")
    try:
        image.save(output, format="PNG")
    finally:
        image.close()
    return output.getvalue()


def test_builtin_pdf_and_image_adapters_pass_compact_conformance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = validate_adapter_conformance(builtin_pdf_adapter())
    image = validate_adapter_conformance(builtin_image_adapter())

    assert pdf.registration_allowed is True
    assert image.registration_allowed is True
    assert pdf.issues == image.issues == []
    assert pdf.manifest_sha256 is not None
    assert image.manifest_sha256 is not None
    assert pdf.manifest_sha256 != image.manifest_sha256

    defaults = Settings()
    assert defaults.adapters_conformance_enabled is False
    assert defaults.adapters_image_parity_enabled is False
    with pytest.raises(ValueError, match="PARSER_ADAPTERS_IMAGE_PARITY_ENABLED"):
        Settings(adapters_image_parity_enabled=True)
    monkeypatch.setenv("PARSER_ADAPTERS_CONFORMANCE_ENABLED", "true")
    monkeypatch.setenv("PARSER_ADAPTERS_IMAGE_PARITY_ENABLED", "true")
    loaded = Settings.from_env()
    assert loaded.adapters_conformance_enabled is True
    assert loaded.adapters_image_parity_enabled is True


def test_builtin_registry_has_stable_nonoverlapping_ownership() -> None:
    registry = builtin_adapter_registry(Settings())

    assert [value.adapter_id for value in registry.registrations] == [
        "builtin-image",
        "builtin-pdf",
    ]
    assert registry.select(
        "document.pdf",
        "application/pdf; charset=binary",
        VALID_PDF,
    ).registration.adapter_id == "builtin-pdf"
    assert registry.select(
        "scan.png",
        "image/png",
        _png_bytes(),
    ).registration.adapter_id == "builtin-image"


def test_contract_dispatch_preserves_the_existing_pdf_loader_result() -> None:
    settings = Settings()
    expected = load_document(VALID_PDF, "document.pdf", settings)

    result = builtin_adapter_registry(settings).dispatch(
        VALID_PDF,
        "document.pdf",
        "application/pdf",
        settings,
    )

    assert result == expected
    assert result.kind is InputKind.PDF
    assert result.original_bytes == VALID_PDF


def test_contract_dispatch_preserves_the_existing_image_loader_result() -> None:
    data = _png_bytes()
    settings = Settings()
    expected = load_document(data, "scan.png", settings)

    result = builtin_adapter_registry(settings).dispatch(
        data,
        "scan.png",
        "image/png",
        settings,
    )

    assert result == expected
    assert result.kind is InputKind.IMAGE
    assert result.pages[0].page_index == 1
    assert result.pages[0].page_model("PNG")["page_label"] == "1"


def test_conforming_test_adapter_registers_and_dispatches_exactly_once() -> None:
    adapter = DeterministicAdapterTestDouble()
    registry = AdapterRegistry()

    registration = registry.register(adapter)
    result = registry.dispatch(
        b"FTR1 payload",
        "sample.fixture",
        "application/x-fixture",
        object(),
    )

    assert registration.adapter_id == "fixture-adapter"
    assert adapter.calls == 1
    assert result["adapter_id"] == "fixture-adapter"
    assert result["filename"] == "sample.fixture"


def test_missing_mandatory_capability_fails_without_advertising_ownership() -> None:
    adapter = MissingCapabilityAdapterTestDouble("capabilities")
    report = validate_adapter_conformance(adapter)
    registry = AdapterRegistry()

    assert report.status == "nonconforming"
    assert [issue.code for issue in report.issues] == [
        "adapter_manifest_missing_capabilities"
    ]
    with pytest.raises(AdapterRegistrationError) as captured:
        registry.register(adapter)
    assert captured.value.code == "adapter_manifest_missing_capabilities"
    assert registry.registrations == ()
    with pytest.raises(AdapterDispatchError) as dispatch:
        registry.select(
            "sample.fixture",
            "application/x-fixture",
            b"FTR1 payload",
        )
    assert dispatch.value.code == "adapter_extension_unregistered"


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "code"),
    [
        (
            "sample.unknown",
            "application/pdf",
            VALID_PDF,
            "adapter_extension_unregistered",
        ),
        ("sample.pdf", "text/plain", VALID_PDF, "adapter_mime_mismatch"),
        (
            "sample.png",
            "image/png",
            b"not a PNG",
            "adapter_signature_mismatch",
        ),
        ("sample.png", None, _png_bytes(), "adapter_mime_required"),
    ],
)
def test_unregistered_mime_signature_and_required_mime_fail_closed(
    filename: str,
    content_type: str | None,
    data: bytes,
    code: str,
) -> None:
    registry = builtin_adapter_registry()

    with pytest.raises(AdapterDispatchError) as captured:
        registry.select(filename, content_type, data)

    assert captured.value.code == code


def test_duplicate_mime_ownership_is_rejected_atomically() -> None:
    first = DeterministicAdapterTestDouble()
    second = DeterministicAdapterTestDouble(
        conforming_test_manifest(
            adapter_id="second-fixture",
            extension=".second",
            mime_type="application/x-fixture",
        )
    )
    registry = AdapterRegistry()
    registry.register(first)

    with pytest.raises(AdapterRegistrationError) as captured:
        registry.register(second)

    assert captured.value.code == "adapter_mime_conflict"
    assert [value.adapter_id for value in registry.registrations] == [
        "fixture-adapter"
    ]
    with pytest.raises(AdapterDispatchError) as dispatch:
        registry.select(
            "sample.second",
            "application/x-fixture",
            b"FTR1 payload",
        )
    assert dispatch.value.code == "adapter_extension_unregistered"


def test_registry_detects_manifest_mutation_after_registration() -> None:
    adapter = DeterministicAdapterTestDouble()
    registry = AdapterRegistry()
    registry.register(adapter)
    # Frozen Pydantic models prevent field replacement; the registry also
    # protects against mutation of a nested collection owned by a bad adapter.
    adapter.manifest.mime_types.append("application/x-mutated")

    with pytest.raises(AdapterDispatchError) as captured:
        registry.select(
            "sample.fixture",
            "application/x-fixture",
            b"FTR1 payload",
        )

    assert captured.value.code == "adapter_registration_stale"
    assert adapter.calls == 0

    validated_manifest = conforming_test_manifest(
        adapter_id="cycling-fixture",
        extension=".validated",
        mime_type="application/x-validated",
    )
    commit_manifest = conforming_test_manifest(
        adapter_id="cycling-fixture",
        extension=".commit",
        mime_type="application/x-commit",
    )

    class CommitSnapshotMutationAdapter:
        def __init__(self) -> None:
            self.reads = 0

        @property
        def manifest(self) -> AdapterManifest:
            self.reads += 1
            # The first two reads form the conformance snapshot. The registry
            # must reject a different third snapshot instead of indexing it
            # under the digest of the first one.
            return commit_manifest if self.reads == 3 else validated_manifest

        def load(self, data: bytes, filename: str, settings: object) -> object:
            raise AssertionError("an unstable adapter must never be invoked")

    cycling_adapter = CommitSnapshotMutationAdapter()
    cycling_registry = AdapterRegistry()

    with pytest.raises(AdapterRegistrationError) as registration:
        cycling_registry.register(cycling_adapter)

    assert registration.value.code == "adapter_manifest_unstable"
    assert cycling_registry.registrations == ()
    with pytest.raises(AdapterDispatchError) as dispatch:
        cycling_registry.select(
            "sample.commit",
            "application/x-commit",
            b"FTR1 payload",
        )
    assert dispatch.value.code == "adapter_extension_unregistered"


def test_affine_transform_normalizes_bbox_and_round_trips() -> None:
    transform = AdapterCoordinateTransform(
        id="pdf-render-to-pixels",
        source_unit="pt",
        target_unit="px",
        matrix=[2.0, 0.0, 0.0, 2.0, 10.0, 20.0],
    )
    source = AdapterBoundingBox(
        x=5.0,
        y=6.0,
        width=20.0,
        height=10.0,
        unit="pt",
    )

    assert transform.apply_bbox(source) == AdapterBoundingBox(
        x=20.0,
        y=32.0,
        width=40.0,
        height=20.0,
        unit="px",
    )
    assert transform.round_trip_error(17.5, 9.25) <= 1e-12
    assert transform.inverse().apply(*transform.apply(3.0, 4.0)) == pytest.approx(
        (3.0, 4.0)
    )


def test_noninvertible_coordinate_transform_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be invertible"):
        AdapterCoordinateTransform(
            id="bad-transform",
            source_unit="px",
            target_unit="pt",
            matrix=[1.0, 2.0, 2.0, 4.0, 0.0, 0.0],
        )

    # Overflowed products previously produced ``inf - inf == nan`` and let a
    # singular matrix cross the trust boundary.
    with pytest.raises(ValidationError, match="must be invertible"):
        AdapterCoordinateTransform(
            id="overflow-singular-transform",
            source_unit="px",
            target_unit="pt",
            matrix=[1e308, 1e308, 1e308, 1e308, 0.0, 0.0],
        )

    overflowing_projection = AdapterCoordinateTransform(
        id="overflowing-projection",
        source_unit="px",
        target_unit="pt",
        matrix=[1e308, 0.0, 0.0, 1.0, 0.0, 0.0],
    )
    with pytest.raises(ValueError, match="result must be finite"):
        overflowing_projection.apply(2.0, 1.0)
    with pytest.raises(ValueError, match="finite"):
        overflowing_projection.apply_bbox(
            AdapterBoundingBox(
                x=1e308,
                y=0.0,
                width=1e308,
                height=1.0,
                unit="px",
            )
        )


def test_adapter_input_limit_rejects_before_invocation() -> None:
    adapter = DeterministicAdapterTestDouble(
        conforming_test_manifest().model_copy(
            update={
                "limits": conforming_test_manifest().limits.model_copy(
                    update={"max_input_bytes": 4},
                )
            }
        )
    )
    registry = AdapterRegistry()
    registry.register(adapter)

    with pytest.raises(AdapterDispatchError) as captured:
        registry.dispatch(
            b"FTR1 payload",
            "sample.fixture",
            "application/x-fixture",
            object(),
        )

    assert captured.value.code == "adapter_input_limit_exceeded"
    assert adapter.calls == 0
