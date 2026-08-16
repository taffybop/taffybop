from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.input_documents import InputKind
from app.services.visual_contracts import VisualBoundingBox
from app.services.visual_model_contracts import (
    VisualModelConfidenceDimensions,
    VisualModelCrop,
    VisualModelEvidenceReference,
    VisualModelIdentity,
    VisualModelObservation,
    VisualModelRegion,
    VisualModelRequest,
    VisualModelResponse,
    canonical_visual_model_json,
    validate_visual_model_response,
)
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import _item, _payload


def _box(
    x: float = 10.0,
    y: float = 20.0,
    width: float = 100.0,
    height: float = 80.0,
) -> VisualBoundingBox:
    return VisualBoundingBox(x=x, y=y, width=width, height=height, unit="pt")


def _identity(*, kind: str = "test_double") -> VisualModelIdentity:
    return VisualModelIdentity(
        adapter_kind=kind,
        adapter_name="deterministic-visual-adapter",
        adapter_version="1.0.0",
        model_name="fixture-model",
        model_version="fixture-v1",
        prompt_version="grounded-v1",
        response_schema_version="1.0",
        artifact_sha256="a" * 64 if kind == "local" else None,
        artifact_source="fixture://approved" if kind == "local" else None,
        license_id="fixture-test-only" if kind == "local" else None,
    )


def _request(
    *,
    kind: str = "chart",
    requested: list[str] | None = None,
) -> VisualModelRequest:
    crop_bytes = b"deterministic-crop"
    region_box = _box()
    evidence = [
        VisualModelEvidenceReference(
            id="evidence-label",
            page_index=1,
            kind="label",
            page_bbox=_box(15.0, 25.0, 40.0, 10.0),
            source_origin="explicit_text",
            text="Revenue",
            source_token_ids=["token-revenue"],
        ),
        VisualModelEvidenceReference(
            id="evidence-region",
            page_index=1,
            kind="region",
            page_bbox=region_box,
            source_origin="layout",
            source_object_ids=["source-region"],
        ),
    ]
    return VisualModelRequest(
        schema_version="1.0",
        request_id="request-1",
        document_sha256="1" * 64,
        region=VisualModelRegion(
            id="region-1",
            public_item_id="chart-1" if kind == "chart" else "visual-1",
            page_index=1,
            kind=kind,
            page_bbox=region_box,
            evidence_ids=["evidence-region"],
        ),
        crop=VisualModelCrop(
            mime_type="image/png",
            width=100,
            height=80,
            byte_length=len(crop_bytes),
            content_sha256=hashlib.sha256(crop_bytes).hexdigest(),
            data=crop_bytes,
        ),
        evidence=evidence,
        requested_observation_types=sorted(
            requested or ["generated_description", "visual_identification"]
        ),
    )


def _observation(
    *,
    identity: VisualModelIdentity | None = None,
) -> VisualModelObservation:
    return VisualModelObservation(
        id="observation-1",
        operation="add",
        observation_type="visual_identification",
        origin="model_visual_identification",
        explicitness="derived",
        method="explicit_text",
        text="Revenue",
        region_id="region-1",
        page_index=1,
        page_bbox=_box(15.0, 25.0, 40.0, 10.0),
        evidence_ids=["evidence-label"],
        identity=identity or _identity(),
        confidence=VisualModelConfidenceDimensions(
            model=0.91,
            geometry=0.99,
            semantic=0.94,
        ),
    )


def _response(
    observation: VisualModelObservation | None = None,
) -> VisualModelResponse:
    identity = observation.identity if observation is not None else _identity()
    return VisualModelResponse(
        schema_version="1.0",
        request_id="request-1",
        identity=identity,
        observations=[observation or _observation(identity=identity)],
    )


def test_grounded_observation_round_trips_canonically() -> None:
    request = _request()
    response = _response()

    envelope = validate_visual_model_response(
        request,
        response.model_dump(mode="json", exclude_none=True),
    )

    assert envelope.status == "accepted"
    assert envelope.response == response
    encoded = canonical_visual_model_json(response)
    assert VisualModelResponse.model_validate_json(encoded) == response
    assert encoded == canonical_visual_model_json(
        VisualModelResponse.model_validate_json(encoded)
    )
    assert response.observations[0].confidence.model == 0.91
    assert response.observations[0].confidence.semantic == 0.94


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda payload: payload["observations"][0]["evidence_ids"].append(
                "unknown-evidence"
            ),
            "visual_model_unknown_evidence_reference",
        ),
        (
            lambda payload: payload["observations"][0].__setitem__(
                "page_index", 2
            ),
            "visual_model_cross_page_reference",
        ),
        (
            lambda payload: payload["observations"][0].__setitem__(
                "page_bbox",
                {
                    "x": 500.0,
                    "y": 500.0,
                    "width": 10.0,
                    "height": 10.0,
                    "unit": "pt",
                },
            ),
            "visual_model_observation_outside_region",
        ),
    ],
)
def test_unknown_cross_page_and_outside_references_are_rejected(
    mutation: Any,
    code: str,
) -> None:
    raw = _response().model_dump(mode="json", exclude_none=True)
    mutation(raw)
    raw["observations"][0]["evidence_ids"] = sorted(
        raw["observations"][0]["evidence_ids"]
    )

    envelope = validate_visual_model_response(_request(), raw)

    assert envelope.status == "rejected"
    assert envelope.response is None
    assert [concern.code for concern in envelope.concerns] == [code]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["observations"][0].__setitem__(
            "operation", "overwrite"
        ),
        lambda payload: payload["observations"][0].__setitem__(
            "origin", "source_transcription"
        ),
        lambda payload: payload["observations"][0].__setitem__(
            "observation_type", "free_form_claim"
        ),
        lambda payload: payload["observations"][0].__setitem__(
            "confidence", {"model": float("nan")}
        ),
    ],
)
def test_malformed_overwrite_and_source_claims_become_concerns_not_content(
    mutation: Any,
) -> None:
    raw = _response().model_dump(mode="json", exclude_none=True)
    mutation(raw)

    envelope = validate_visual_model_response(_request(), raw)

    assert envelope.status == "rejected"
    assert envelope.response is None
    assert envelope.concerns[0].code == "visual_model_response_malformed"
    assert "Revenue" not in canonical_visual_model_json(envelope)


def test_request_rejects_unknown_or_out_of_region_submitted_evidence() -> None:
    payload = _request().model_dump(mode="python", exclude_none=True)
    payload["region"]["evidence_ids"] = ["not-submitted"]
    with pytest.raises(ValidationError, match="unknown submitted evidence"):
        VisualModelRequest.model_validate(payload)

    payload = _request().model_dump(mode="python", exclude_none=True)
    payload["evidence"][1]["page_bbox"]["x"] = 300.0
    with pytest.raises(ValidationError, match="leaves the requested region"):
        VisualModelRequest.model_validate(payload)


def test_contract_defaults_off_and_does_not_change_phase05_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _payload(_item("chart", "chart-1", x=10.0))
    phase05_settings = Settings(visual_structure_schema_enabled=True)
    baseline = apply_visual_semantics(
        deepcopy(source),
        phase05_settings,
        input_kind=InputKind.PDF,
    )
    explicit_off = apply_visual_semantics(
        deepcopy(source),
        Settings(
            visual_structure_schema_enabled=True,
            visual_models_contract_enabled=False,
        ),
        input_kind=InputKind.PDF,
    )

    assert Settings().visual_models_contract_enabled is False
    assert explicit_off == baseline
    assert "visual_model" not in json.dumps(explicit_off, sort_keys=True)
    with pytest.raises(ValueError, match="PARSER_VISUAL_MODELS_CONTRACT_ENABLED"):
        Settings(visual_models_contract_enabled=True)

    monkeypatch.setenv("PARSER_VISUAL_MODELS_CONTRACT_ENABLED", "false")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MAX_CROP_WIDTH", "not-an-integer")
    assert Settings.from_env().visual_models_max_crop_width == 2_048
