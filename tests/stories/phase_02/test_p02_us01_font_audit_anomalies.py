from __future__ import annotations

import pytest

from app.services.font_audit import (
    _Character,
    _FontSpec,
    _classify_font,
)


@pytest.mark.parametrize(
    ("mapped_text", "expected_reason"),
    (
        ("\ufffd", "replacement_or_undefined_mapping"),
        ("\ue000", "private_use_mapping"),
        ("\u0001", "control_character_mapping"),
    ),
)
def test_reason_coded_anomaly_detectors_are_exercised(
    mapped_text: str,
    expected_reason: str,
) -> None:
    spec = _FontSpec(
        font_ref="object:41",
        object_id=41,
        object_identity_basis="indirect_object",
        base_font="SyntheticAnomaly",
        subtype="Type0",
        encoding="Identity-H",
        to_unicode="present",
        to_unicode_ambiguous_cids=frozenset(),
        cid_to_gid="identity",
        cid_to_gid_bytes=None,
        embedded_program=False,
        embedded_program_state="missing",
        standard_14=False,
    )
    characters = [
        _Character(
            font_ref=spec.font_ref,
            page_index=1,
            cid=index,
            mapped_text=mapped_text,
            advance=8.0,
            bbox=(float(index * 8), 72.0, 8.0, 12.0),
        )
        for index in range(1, 11)
    ]

    inventory, finding = _classify_font(spec, characters, [])

    assert inventory.classification == "suspicious"
    assert finding is not None
    assert finding.health == "suspicious"
    assert finding.reason_codes == [expected_reason]
    assert finding.confidence_basis[
        {
            "replacement_or_undefined_mapping": (
                "replacement_or_undefined_count"
            ),
            "private_use_mapping": "private_use_count",
            "control_character_mapping": "control_count",
        }[expected_reason]
    ] == 10
