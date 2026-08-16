"""Real-corpus regressions for terminal P03/P04 public projection custody."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.models import (
    ParseResult,
    _canonical_document_views,
    _canonical_presentation_sha256,
    _canonical_views_from_blocks,
)


REPOSITORY = Path(__file__).resolve().parents[3]
CORPUS = REPOSITORY / "benchmark-expertmodeldata"
PROFILE = (
    REPOSITORY
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "runs"
    / "functional-fidelity-20260813"
    / "service-profile.json"
)


def _reseal_canonical(payload: dict[str, object]) -> None:
    canonical = payload["canonical_presentation"]
    assert isinstance(canonical, dict)
    pages = canonical["pages"]
    assert isinstance(pages, list)
    for page in pages:
        assert isinstance(page, dict)
        page.update(_canonical_views_from_blocks(page))
    canonical.update(_canonical_document_views(pages))
    custody = payload["canonical_source_custody"]
    assert isinstance(custody, dict)
    custody["canonical_presentation_sha256"] = (
        _canonical_presentation_sha256(canonical)
    )


@pytest.mark.parametrize(
    ("case_id", "primary_id", "primary_text"),
    (
        (
            "catastrophe-recap",
            "el-05e74d7032a69bdc451e",
            None,
        ),
        (
            "postal-10k",
            None,
            "2025 Report on Form 10-K United States Postal Service 2",
        ),
    ),
)
def test_real_pdf_survives_http_public_projection_validation(
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    primary_id: str | None,
    primary_text: str | None,
) -> None:
    """The exact benchmark profile must produce a public-valid JSON response."""

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    for name, value in profile["environment"].items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    source = CORPUS / f"{case_id}.pdf"

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/parse?output_format=json",
            headers={"accept": "application/json"},
            files={
                "file": (
                    source.name,
                    source.read_bytes(),
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 200, response.text
    public = response.json()
    validated = ParseResult.model_validate(public)
    assert validated.model_dump(mode="json", exclude_unset=True) == public
    assert sum(
        item.table_evidence is not None
        for page in validated.pages
        for item in page.items
    ) == 1
    assert validated.canonical_source_custody is not None

    canonical = public["canonical_presentation"]
    blocks = [block for page in canonical["pages"] for block in page["blocks"]]
    matching_targets = [
        block
        for block in blocks
        if (
            block["primary_element_id"] == primary_id
            if primary_id is not None
            else block["primary_element_type"] == "footer"
            and block["text"] == primary_text
        )
    ]
    assert len(matching_targets) == 1
    target = matching_targets[0]
    primary_id = target["primary_element_id"]
    if case_id == "catastrophe-recap":
        # The visual overlay retains only its public layout graph; raw child
        # relationships that disappeared at P03 may not be restored by P04.
        assert len(target["relationship_ids"]) == 16
        assert len(target["excluded_contributions"]) == 12
        assert "layout-rel-497b2ac79fe5845097a3" in target[
            "relationship_ids"
        ]
        assert "rel-c730a7f75ecfecdbefe3" in target[
            "relationship_ids"
        ]
        assert {
            "element_id": "el-737d0804f16f00851bf6",
            "reason": "evidence_only_relationship",
            "relationship_ids": ["rel-c730a7f75ecfecdbefe3"],
        } in target["excluded_contributions"]
        assert "rel-131b1f0eb09a226c1027" not in target[
            "relationship_ids"
        ]
        forged = deepcopy(public)
        forged_target = next(
            block
            for page in forged["canonical_presentation"]["pages"]
            for block in page["blocks"]
            if block["primary_element_id"] == primary_id
        )
        forged_target["relationship_ids"] = sorted(
            [
                *forged_target["relationship_ids"],
                "rel-131b1f0eb09a226c1027",
            ]
        )
        forged_target["excluded_contributions"].append(
            {
                "element_id": "el-6f8f108fafa807e0c322",
                "reason": "evidence_only_relationship",
                "relationship_ids": ["rel-131b1f0eb09a226c1027"],
            }
        )
        forged_target["excluded_contributions"].sort(
            key=lambda value: (value["element_id"], value["reason"])
        )
        _reseal_canonical(forged)
        with pytest.raises(ValueError, match="canonical layout overlay differs"):
            ParseResult.model_validate(forged)
    else:
        # A running-region block owns exactly its synthetic public source;
        # predecessor child contributors are not part of this overlay.
        assert target["contributing_element_ids"] == [primary_id]
        assert target["relationship_ids"] == []
        assert target["excluded_contributions"] == []
        forged = deepcopy(public)
        forged_target = next(
            block
            for page in forged["canonical_presentation"]["pages"]
            for block in page["blocks"]
            if block["primary_element_id"] == primary_id
        )
        forged_target["contributing_element_ids"].append(
            "el-e38a6033e27ce0105ebe"
        )
        forged_target["relationship_ids"] = [
            "rel-48a07ada5aa6bce17c3e"
        ]
        _reseal_canonical(forged)
        with pytest.raises(
            ValueError,
            match="canonical running-region overlay differs",
        ):
            ParseResult.model_validate(forged)
