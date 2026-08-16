from __future__ import annotations

import hashlib
import io
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.api as api_module
import app.services.pipeline as pipeline
import app.services.visual_models as visual_models
from app.config import Settings
from app.main import create_app
from app.models import ParseResult
from app.services.input_documents import InputKind
from app.services.presentation import build_canonical_presentation
from app.services.serializer import to_markdown
from app.services.visual_model_contracts import (
    VisualModelConfidenceDimensions,
    VisualModelConcern,
    VisualModelContractEnvelope,
    VisualModelCrop,
    VisualModelObservation,
    VisualModelResponse,
    validate_visual_model_response,
)
from app.services.visual_model_grounding import ground_visual_model_observations
from app.services.visual_model_merge import (
    VisualModelMergeEntry,
    merge_visual_model_evidence,
)
from app.services.visual_models import (
    VisualModelDependencies,
    apply_optional_visual_models,
)
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import (
    _item,
    _payload,
    _public_loaded_image,
    _public_raw_layout,
    _public_region,
)
from tests.stories.phase_05.test_p05_us05_chart_validation import (
    _settings as _complete_chart_settings,
    _source as _complete_chart_source,
)
from tests.stories.phase_06.test_p06_us01_model_contract import _identity
from tests.stories.phase_06.test_p06_us05_grounding import (
    _contract,
    _fallback_chart,
    _request_for,
)


def _phase06_settings(**updates: Any) -> Settings:
    values: dict[str, Any] = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "visual_structure_schema_enabled": True,
        "visual_models_contract_enabled": True,
        "visual_models_routing_enabled": True,
        "visual_models_grounding_enabled": True,
        "visual_models_merge_enabled": True,
    }
    values.update(updates)
    return Settings(**values)


def _crop_provider(
    _source: bytes,
    _kind: InputKind,
    _page_index: int,
    box: Any,
    _settings: Settings,
) -> VisualModelCrop:
    data = b"deterministic-phase06-crop"
    return VisualModelCrop(
        mime_type="image/png",
        width=max(1, int(round(box.width))),
        height=max(1, int(round(box.height))),
        byte_length=len(data),
        content_sha256=hashlib.sha256(data).hexdigest(),
        data=data,
    )


@dataclass
class _AdapterResult:
    contract_envelope: VisualModelContractEnvelope | None = None
    failure: Any | None = None


class _GroundedAdapter:
    kind = "local"

    def __init__(self, outcomes: list[str] | None = None) -> None:
        self.outcomes = list(outcomes or ["accepted"])
        self.calls: list[Any] = []

    def is_available(self) -> bool:
        return True

    def invoke(self, request: Any) -> _AdapterResult:
        self.calls.append(request)
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if outcome == "raise":
            raise RuntimeError("deterministic adapter failure")
        if outcome == "failure":
            failure = type("Failure", (), {"code": "timeout"})()
            return _AdapterResult(failure=failure)
        if outcome == "malformed":
            return _AdapterResult(
                contract_envelope=validate_visual_model_response(
                    request,
                    {"not": "a response"},
                )
            )
        reference = next(
            value
            for value in request.evidence
            if value.text and value.source_origin in {"ocr", "explicit_text"}
        )
        identity = _identity()
        observation = VisualModelObservation(
            id=f"observation-{request.region.public_item_id}",
            operation="add",
            observation_type="visual_identification",
            origin="model_visual_identification",
            explicitness="derived",
            method="explicit_text",
            text=reference.text,
            region_id=request.region.id,
            page_index=request.region.page_index,
            page_bbox=reference.page_bbox,
            evidence_ids=[reference.id],
            identity=identity,
            confidence=VisualModelConfidenceDimensions(
                model=0.9,
                geometry=0.99,
                semantic=0.99,
            ),
        )
        response = VisualModelResponse(
            schema_version="1.0",
            request_id=request.request_id,
            identity=identity,
            observations=[observation],
        )
        return _AdapterResult(
            contract_envelope=validate_visual_model_response(
                request,
                response.model_dump(mode="json", exclude_none=True),
            )
        )


def _dependencies(adapter: _GroundedAdapter) -> VisualModelDependencies:
    return VisualModelDependencies(
        adapters={"local": adapter},
        crop_provider=_crop_provider,
        deterministic_test_double=True,
    )


def _accepted_merge_fixture() -> tuple[dict[str, Any], VisualModelMergeEntry]:
    item, structure = _fallback_chart()
    label = next(label for label in structure.labels if label.text == "2024")
    request = _request_for(
        item,
        structure,
        types=["visual_identification"],
        evidence_ids={*structure.region.evidence_ids, *label.evidence_ids},
    )
    identity = _identity()
    observation = VisualModelObservation(
        id="observation-grounded-label",
        operation="add",
        observation_type="visual_identification",
        origin="model_visual_identification",
        explicitness="derived",
        method="explicit_text",
        text="2024",
        region_id=request.region.id,
        page_index=1,
        page_bbox=label.page_bbox,
        evidence_ids=sorted(label.evidence_ids),
        identity=identity,
        confidence=VisualModelConfidenceDimensions(
            model=0.9,
            geometry=0.99,
            semantic=0.99,
        ),
    )
    grounding = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )
    assert grounding.status == "accepted"
    # Give the Phase 05 fallback an existing canonical body. The pipeline seam
    # normally merges before canonical construction; this direct merge fixture
    # intentionally exercises augmentation of an already-built presentation.
    item["include_ocr_in_primary"] = True
    payload = _payload(item)
    from app.services.ir import build_document_ir

    payload["canonical_presentation"] = build_canonical_presentation(
        build_document_ir(payload)
    ).model_dump(mode="json", exclude_none=True)
    return payload, VisualModelMergeEntry(
        public_item_id=item["id"],
        page_index=1,
        region_id=structure.region.id,
        grounding=grounding,
    )


def _without_model_channel(payload: dict[str, Any]) -> dict[str, Any]:
    output = deepcopy(payload)
    output.pop("canonical_presentation", None)
    for page in output["pages"]:
        for item in page["items"]:
            item.pop("visual_model_evidence", None)
    return output


def test_accepted_merge_is_additive_public_and_idempotent() -> None:
    baseline, entry = _accepted_merge_fixture()
    baseline_source = _without_model_channel(baseline)

    first = merge_visual_model_evidence(
        baseline,
        [entry],
        enabled=True,
    )
    second = merge_visual_model_evidence(
        first.payload,
        [entry],
        enabled=True,
    )

    assert first.status == "accepted"
    assert first.reason == "merged"
    assert first.merged_observations == 1
    assert first.added_bytes > 0
    assert second.status == "accepted"
    assert second.reason == "already_merged"
    assert second.payload == first.payload
    assert _without_model_channel(first.payload) == baseline_source
    item = first.payload["pages"][0]["items"][0]
    assert item["value"] == baseline["pages"][0]["items"][0]["value"]
    assert item["md"] == baseline["pages"][0]["items"][0]["md"]
    assert item["source"] == baseline["pages"][0]["items"][0]["source"]
    assert item["visual_model_evidence"]["source_evidence_preserved"] is True
    encoded = json.dumps(first.payload, allow_nan=False, sort_keys=True)
    assert "model_visual_identification" in encoded
    assert to_markdown(first.payload).count("Model-generated evidence") == 1
    assert first.payload["canonical_presentation"]["full"]["text"].count(
        "Model-generated evidence"
    ) == 1
    ParseResult.model_validate(first.payload)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"enabled": False}, "merge_disabled"),
        ({"enabled": True, "max_observations": 0}, "output_limit"),
        ({"enabled": True, "max_added_bytes": 1}, "output_limit"),
    ],
)
def test_merge_skip_and_resource_refusal_restore_exact_baseline(
    kwargs: dict[str, Any],
    reason: str,
) -> None:
    baseline, entry = _accepted_merge_fixture()
    before = deepcopy(baseline)

    result = merge_visual_model_evidence(baseline, [entry], **kwargs)

    assert result.status == "fallback"
    assert result.reason == reason
    assert result.payload == before
    assert baseline == before


def test_collision_malformed_sidecar_and_validator_failure_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, entry = _accepted_merge_fixture()
    accepted = merge_visual_model_evidence(baseline, [entry], enabled=True)
    collision_entry = entry.model_copy(deep=True)
    grounded = collision_entry.grounding.observations[0]
    conflicting_observation = grounded.observation.model_copy(
        update={"text": "conflicting text"}
    )
    conflicting_grounded = grounded.model_copy(
        update={"observation": conflicting_observation}
    )
    collision_entry = collision_entry.model_copy(
        update={
            "grounding": collision_entry.grounding.model_copy(
                update={"observations": [conflicting_grounded]}
            )
        }
    )
    collision = merge_visual_model_evidence(
        accepted.payload,
        [collision_entry],
        enabled=True,
    )
    malformed = deepcopy(baseline)
    malformed["pages"][0]["items"][0]["visual_model_evidence"] = {
        "malformed": True
    }
    malformed_before = deepcopy(malformed)
    isolated = merge_visual_model_evidence(malformed, [entry], enabled=True)
    def reject_candidate(_payload: dict[str, Any]) -> None:
        raise ValueError("injected candidate validation failure")

    failed_validation = merge_visual_model_evidence(
        baseline,
        [entry],
        enabled=True,
        candidate_validator=reject_candidate,
    )

    def reject_projection(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("injected serializer failure")

    monkeypatch.setattr(
        "app.services.presentation.augment_canonical_visual_model_evidence",
        reject_projection,
    )
    serializer_failed = merge_visual_model_evidence(
        baseline,
        [entry],
        enabled=True,
    )

    assert collision.reason == "observation_collision"
    assert collision.payload == accepted.payload
    assert isolated.reason == "candidate_validation_failed"
    assert isolated.payload == malformed_before
    assert failed_validation.reason == "candidate_validation_failed"
    assert failed_validation.payload == baseline
    assert serializer_failed.reason == "canonical_projection_failed"
    assert serializer_failed.payload == baseline


def test_orchestrator_is_deterministic_and_ignores_complete_non_targets() -> None:
    fallback = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    first_adapter = _GroundedAdapter()
    second_adapter = _GroundedAdapter()

    first = apply_optional_visual_models(
        fallback,
        _phase06_settings(),
        source_document_bytes=b"unused source",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(first_adapter),
    )
    second = apply_optional_visual_models(
        deepcopy(fallback),
        _phase06_settings(),
        source_document_bytes=b"unused source",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(second_adapter),
    )

    assert first == second
    assert len(first_adapter.calls) == len(second_adapter.calls) == 1
    assert "visual_model_evidence" in first["pages"][0]["items"][0]

    complete = apply_visual_semantics(
        _complete_chart_source(),
        _complete_chart_settings(),
        input_kind=InputKind.PDF,
    )
    complete["pages"][0]["items"].append(
        {
            "id": "text-1",
            "type": "text",
            "reading_order": 1,
            "value": "complete source text",
            "md": "complete source text",
        }
    )
    adapter = _GroundedAdapter()
    unchanged = apply_optional_visual_models(
        complete,
        _phase06_settings(),
        source_document_bytes=b"unused source",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(adapter),
    )
    assert unchanged == complete
    assert adapter.calls == []


@pytest.mark.parametrize("outcome", ["raise", "failure", "malformed"])
def test_adapter_exception_failure_and_malformed_response_restore_phase05(
    outcome: str,
) -> None:
    baseline = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    adapter = _GroundedAdapter([outcome])

    result = apply_optional_visual_models(
        baseline,
        _phase06_settings(),
        source_document_bytes=b"unused source",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(adapter),
    )

    assert result == baseline
    assert len(adapter.calls) == 1
    assert "visual_model_evidence" not in json.dumps(result)


def test_one_malformed_region_rolls_back_all_prior_region_work() -> None:
    baseline = apply_visual_semantics(
        _payload(
            _item("chart", "chart-1", x=10.0),
            _item("chart", "chart-2", x=20.0),
        ),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    adapter = _GroundedAdapter(["accepted", "malformed"])

    result = apply_optional_visual_models(
        baseline,
        _phase06_settings(),
        source_document_bytes=b"unused source",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(adapter),
    )

    assert len(adapter.calls) == 2
    assert result == baseline
    assert "visual_model_evidence" not in json.dumps(result)


def _patch_public_image_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _public_loaded_image()
    raw = _public_raw_layout()
    raw["pictures"] = raw["pictures"][:1]
    raw["body"]["children"] = raw["body"]["children"][:1]
    monkeypatch.setattr(pipeline, "load_document", lambda *_args, **_kwargs: loaded)
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (raw, []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: [_public_region()]},
    )
    monkeypatch.setattr(
        pipeline,
        "extract_vector_tables",
        lambda *_args, **_kwargs: pytest.fail("image flow cannot read PDF vectors"),
    )


def _png_upload() -> bytes:
    image = Image.new("RGB", (8, 6), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def test_public_pipeline_and_http_json_markdown_text_expose_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_public_image_pipeline(monkeypatch)
    adapter = _GroundedAdapter()
    monkeypatch.setattr(
        visual_models,
        "configured_visual_model_dependencies",
        lambda _settings: _dependencies(adapter),
    )
    settings = _phase06_settings()

    result = pipeline.parse_document(b"request bytes", "visual.png", settings)
    public = result.model_dump(mode="json", exclude_unset=True)
    visual_item = next(
        item
        for item in public["pages"][0]["items"]
        if item.get("visual_model_evidence") is not None
    )
    assert visual_item["visual_model_evidence"]["observations"]
    assert public["canonical_presentation"]["full"]["markdown"].count(
        "Model-generated evidence"
    ) == 1
    assert public["canonical_presentation"]["full"]["text"].count(
        "Model-generated evidence"
    ) == 1
    assert to_markdown(result).count("Model-generated evidence") == 1

    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: result,
    )
    app = create_app()
    with TestClient(app) as client:
        json_response = client.post(
            "/v1/parse?output_format=json",
            files={"file": ("visual.png", _png_upload(), "image/png")},
        )
        markdown_response = client.post(
            "/v1/parse?output_format=markdown",
            files={"file": ("visual.png", _png_upload(), "image/png")},
        )
    assert json_response.status_code == 200
    assert json_response.json()["pages"][0]["items"]
    public_item = next(
        item
        for item in json_response.json()["pages"][0]["items"]
        if item.get("visual_model_evidence") is not None
    )
    assert len(public_item["visual_model_evidence"]["observations"]) == 1
    assert (
        public_item["visual_model_evidence"]["observations"][0]["origin"]
        == "model_visual_identification"
    )
    assert markdown_response.status_code == 200
    assert markdown_response.text.count("Model-generated evidence") == 1


def test_all_flags_off_preserve_public_json_markdown_and_repeated_output() -> None:
    baseline = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    adapter = _GroundedAdapter()
    default_off = apply_optional_visual_models(
        baseline,
        Settings(),
        source_document_bytes=b"unused",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(adapter),
    )
    explicit_off = apply_optional_visual_models(
        deepcopy(baseline),
        Settings(visual_structure_schema_enabled=True),
        source_document_bytes=b"unused",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(adapter),
    )

    assert default_off == explicit_off == baseline
    assert adapter.calls == []
    assert to_markdown(default_off) == to_markdown(baseline)
    assert json.dumps(default_off, allow_nan=False, sort_keys=True) == json.dumps(
        baseline,
        allow_nan=False,
        sort_keys=True,
    )
