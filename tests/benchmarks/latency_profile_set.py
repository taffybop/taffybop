"""Closed LAT-US01 all-corpus and bounded-concurrency evidence gates.

This module evaluates already-retained :class:`LatencyAttempt` records.  It
does not execute the parser, contact a provider, read document content, or
change production state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from tests.benchmarks.latency_contracts import (
    ArtifactIdentity,
    AttemptStatus,
    ContractModel,
    EnvironmentIdentityEvidence,
    FailureCode,
    FailureRecord,
    FailureType,
    LatencyAttempt,
    OutputFormat,
    ProcessRole,
    ProcessTreeMetrics,
    ProcessTreeSnapshot,
    Sha256,
    SourceIdentity,
    SystemName,
    WorkerExecutionEvidence,
    WorkerFatalEnvelope,
    WorkerLifecycle,
    WorkerWatchdogEvidence,
    model_sha256,
)

PROFILE_SET_SCHEMA_ID = "phase-latency-candidate-profile-set-v1"
CONCURRENT_BATCH_SCHEMA_ID = "phase-latency-concurrent-batch-v1"
PROFILE_EVALUATION_SCHEMA_ID = "phase-latency-profile-evaluation-v1"

CASE_ORDER = (
    "catastrophe-recap",
    "clean-energy",
    "clinical-study",
    "component-datasheet",
    "egov-survey",
    "esg-metrics",
    "finance-10k",
    "health-report",
    "insurance-acord",
    "manufacturing-report",
    "ny-timetable",
    "postal-10k",
    "purchase-agreement",
    "settlement-agreement",
    "uber-earnings",
)
CONCURRENT_CASE_ORDER = ("ny-timetable", "uber-earnings")

PER_WORKER_DELTA_BYTES = 67_108_864
MAXIMUM_EXECUTIONS_PER_SLOT = 16
COLD_HWM_P50_CEILING_BYTES = 1_883_504_640
COLD_HWM_MAXIMUM_CEILING_BYTES = 3_394_068_480
CONCURRENT_AGGREGATE_RSS_CEILING_BYTES = 4_887_855_104
CONCURRENT_SWEEP_MAXIMUM_DURATION_NS = 250_000_000
SOURCE_CUSTODY = {
    "catastrophe-recap": (
        "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e",
        58_779,
        1,
    ),
    "clean-energy": (
        "161d513c3ffa53ee3967bac6a7bb420d5d60a2008f79b4f7421b83e9b3a11a7d",
        122_014,
        1,
    ),
    "clinical-study": (
        "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2",
        750_004,
        4,
    ),
    "component-datasheet": (
        "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4",
        329_199,
        3,
    ),
    "egov-survey": (
        "7b6b95d79149c16297c6f7280caed0e14b7dcd53ad5067cb2657885b90562846",
        82_800,
        1,
    ),
    "esg-metrics": (
        "6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9",
        60_516,
        1,
    ),
    "finance-10k": (
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086",
        87_105,
        3,
    ),
    "health-report": (
        "fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181",
        222_282,
        1,
    ),
    "insurance-acord": (
        "85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4",
        17_086,
        1,
    ),
    "manufacturing-report": (
        "414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f",
        380_274,
        3,
    ),
    "ny-timetable": (
        "f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30",
        26_109,
        3,
    ),
    "postal-10k": (
        "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74",
        83_589,
        3,
    ),
    "purchase-agreement": (
        "00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14",
        152_828,
        1,
    ),
    "settlement-agreement": (
        "adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc",
        164_483,
        1,
    ),
    "uber-earnings": (
        "76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5",
        7_584_019,
        3,
    ),
}

M0_CASE_HWM_BYTES = {
    "catastrophe-recap": 1_496_825_856,
    "clean-energy": 1_497_022_464,
    "clinical-study": 1_637_777_408,
    "component-datasheet": 1_929_658_368,
    "egov-survey": 1_496_268_800,
    "esg-metrics": 1_492_434_944,
    "finance-10k": 1_890_254_848,
    "health-report": 1_506_803_712,
    "insurance-acord": 1_469_136_896,
    "manufacturing-report": 1_914_470_400,
    "ny-timetable": 2_038_382_592,
    "postal-10k": 2_010_890_240,
    "purchase-agreement": 1_469_104_128,
    "settlement-agreement": 1_479_245_824,
    "uber-earnings": 2_715_254_784,
}

P00_OUTPUT_IDENTITIES = {
    "catastrophe-recap": (
        "0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9",
        "9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1",
        2_008,
    ),
    "clean-energy": (
        "26f222c20ddd2298bb6e37a3bb52f1b9476ff86a6cc04e8638d3ccac45f1c21a",
        "e94fdcfd242a09cd33cc2198e7fca7bbea3e9abd3ef006eeaa833adf7c5264f3",
        886,
    ),
    "clinical-study": (
        "2fb9508e6027b1c2f88341ce92445e5da56bdf805a71a9563b768cbe59bbf863",
        "11a5339797e1ed41a164b23ada5386dc7220d32e10633181a76323f06271a160",
        18_012,
    ),
    "component-datasheet": (
        "5be1be6bfbdede05a7c29a24d88ee41ed6b9e2b20dd3aa76966a571c9f463204",
        "76baf4c7ce7206f3adb36427bfa5593e0d72675276d8c0d5d20e74fdd6e081a7",
        3_771,
    ),
    "egov-survey": (
        "c47d41c7cb9bf0c27ed1eb13c63a8c71c4778888dbe4fd5b95ab33d5b589c5d4",
        "273f2a1256285e0068b7dc3afdc0de9a7001d9c79ccf43ef81dd67ae44c32e09",
        3_056,
    ),
    "esg-metrics": (
        "46a10fc5b9324a72e1b681d90d9e70f02ea61df7bab17fc76e5d1a5f330e7a02",
        "67efecc558dfbdd15f84eede895e3d4339e9bab39c8e8293bc21d4065586544b",
        3_190,
    ),
    "finance-10k": (
        "ec1d4b327bd0542b8e76e1a9517b8d940df2692f20bf59476536284298ad5abe",
        "c09584ed42ed53f0cf2287bb3bb82e0c4f35d5fe0237e0c8785fc765f9026b3b",
        12_622,
    ),
    "health-report": (
        "c532e241bad95695c337f2b4aad2b81a27b801ae466a3c6f1f82ed572ef353ba",
        "4a1ba6026b146bd7996bf81d592f3e9f47901bf096073afccb100717187e752a",
        1_897,
    ),
    "insurance-acord": (
        "1ce18508462dee0fd90821d4e1d974f77bed9e733c3f82954986efdd08b46432",
        "e1b2e3601f507ce75317b727e682a62616b81ce2868f49740a1967d02680250c",
        5_127,
    ),
    "manufacturing-report": (
        "eece6c9fe1b35e77a404e5a989c0396db14cf349da432cfc76fef21851abf1a7",
        "5825a6f58b1b59197ea287c5838258c2419519ef1068482176da3c5f981d19a8",
        6_296,
    ),
    "ny-timetable": (
        "ebdc1985c66a590a0085e07cb9fa4d1cdf5b1b2cbd7731c412371488b2a06e56",
        "f8c2a61c0e795e16bc4022e153ee89e96a5b2c37ff7b8b1e217a3a794fd4823e",
        40_319,
    ),
    "postal-10k": (
        "ea51e1fd5dbb8b9c0dc0d1ef46033f7d808c5daf8092fe4f4daccc5495752524",
        "3288912afb3677a846dd6ac190e40e2b015122292564a038031e85b9759a9f87",
        11_109,
    ),
    "purchase-agreement": (
        "64b7e33c88ba63223eb860cd0c550768aa52659ab47a92e008f52282c8879bf6",
        "51c10e783da3400010151f11ea6cb7120513561c3b68f2ddebe869574852a7ce",
        3_370,
    ),
    "settlement-agreement": (
        "acb56e5c38c208d9a6b84a4be71711e2aeb807e7b3e3e79a205a59d0099a2491",
        "6fe637d18229a5ab90b501b687d41902335c70a41d39d410e4fa41015c0f3305",
        3_144,
    ),
    "uber-earnings": (
        "b4d3afe7b93370a97b96aee04416497baa93b52bfefcbecd48074971859219e3",
        "9beb6dc3d71d0ff97718df827390831e0e4942e88f1399a24d17fc8823c799df",
        1_453,
    ),
}

# P00 remains the immutable historical quality baseline.  The current-runtime
# baseline is an additive, reviewed exact-output baseline for the dependency
# versions that execute LAT-US01; it must never be substituted back into P00.
CURRENT_RUNTIME_OUTPUT_IDENTITIES = {
    "catastrophe-recap": (
        "0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9",
        "9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1",
        2_008,
    ),
    "clean-energy": (
        "d9a69df351a0de33b5ed606fa89048d14e6259969b69519322820f39ae30293a",
        "e94fdcfd242a09cd33cc2198e7fca7bbea3e9abd3ef006eeaa833adf7c5264f3",
        886,
    ),
    "clinical-study": (
        "ef38d5e3ca37cfceadc61bdcfbb836b3d3287debfe8e2883bdaedbb1edf18bd6",
        "11a5339797e1ed41a164b23ada5386dc7220d32e10633181a76323f06271a160",
        18_012,
    ),
    "component-datasheet": (
        "5be1be6bfbdede05a7c29a24d88ee41ed6b9e2b20dd3aa76966a571c9f463204",
        "76baf4c7ce7206f3adb36427bfa5593e0d72675276d8c0d5d20e74fdd6e081a7",
        3_771,
    ),
    "egov-survey": (
        "c47d41c7cb9bf0c27ed1eb13c63a8c71c4778888dbe4fd5b95ab33d5b589c5d4",
        "273f2a1256285e0068b7dc3afdc0de9a7001d9c79ccf43ef81dd67ae44c32e09",
        3_056,
    ),
    "esg-metrics": (
        "46a10fc5b9324a72e1b681d90d9e70f02ea61df7bab17fc76e5d1a5f330e7a02",
        "67efecc558dfbdd15f84eede895e3d4339e9bab39c8e8293bc21d4065586544b",
        3_190,
    ),
    "finance-10k": (
        "b2fa079cbc7bb415625f8fd48f9df2e8dc57e8f60c209138e52ae01a68b82ea9",
        "c09584ed42ed53f0cf2287bb3bb82e0c4f35d5fe0237e0c8785fc765f9026b3b",
        12_622,
    ),
    "health-report": (
        "c532e241bad95695c337f2b4aad2b81a27b801ae466a3c6f1f82ed572ef353ba",
        "4a1ba6026b146bd7996bf81d592f3e9f47901bf096073afccb100717187e752a",
        1_897,
    ),
    "insurance-acord": (
        "1ce18508462dee0fd90821d4e1d974f77bed9e733c3f82954986efdd08b46432",
        "e1b2e3601f507ce75317b727e682a62616b81ce2868f49740a1967d02680250c",
        5_127,
    ),
    "manufacturing-report": (
        "048f3e3c9ef983c265e525e7ca2bd0a9f6ca35a36cae4b7b4793b0e4bfda8a0d",
        "5825a6f58b1b59197ea287c5838258c2419519ef1068482176da3c5f981d19a8",
        6_296,
    ),
    "ny-timetable": (
        "6e49f93ab1690e60ef189749c66b3dc51ddc448e2be14e16f1148d1681c52e46",
        "f8c2a61c0e795e16bc4022e153ee89e96a5b2c37ff7b8b1e217a3a794fd4823e",
        40_319,
    ),
    "postal-10k": (
        "42e0c3f29ea0e772db6fad177e3b876184a70b9534a2bdb0e2dc282828ab6811",
        "3288912afb3677a846dd6ac190e40e2b015122292564a038031e85b9759a9f87",
        11_109,
    ),
    "purchase-agreement": (
        "64b7e33c88ba63223eb860cd0c550768aa52659ab47a92e008f52282c8879bf6",
        "51c10e783da3400010151f11ea6cb7120513561c3b68f2ddebe869574852a7ce",
        3_370,
    ),
    "settlement-agreement": (
        "acb56e5c38c208d9a6b84a4be71711e2aeb807e7b3e3e79a205a59d0099a2491",
        "6fe637d18229a5ab90b501b687d41902335c70a41d39d410e4fa41015c0f3305",
        3_144,
    ),
    "uber-earnings": (
        "a8b08bbac5fe6d8c909d79b2115e3c67c23bab1cc27fd24daf75daf7b18b7f02",
        "9beb6dc3d71d0ff97718df827390831e0e4942e88f1399a24d17fc8823c799df",
        1_453,
    ),
}

HARNESS_PATHS = (
    "tests/benchmarks/latency_campaign.py",
    "tests/benchmarks/latency_child_guard/sitecustomize.py",
    "tests/benchmarks/latency_contracts.py",
    "tests/benchmarks/latency_instrumentation.py",
    "tests/benchmarks/latency_isolation.py",
    "tests/benchmarks/latency_network_probe.py",
    "tests/benchmarks/latency_profile_set.py",
    "tests/benchmarks/latency_runner.py",
    "tests/benchmarks/latency_watchdog.py",
    "tests/benchmarks/latency_worker.py",
)
OBSERVER_HARNESS_PATHS = tuple(
    path for path in HARNESS_PATHS if path != "tests/benchmarks/latency_profile_set.py"
)

ProfileKind = Literal[
    "cold-json",
    "prewarmed-json",
    "cold-markdown",
    "bound2-cold-json",
]


class CandidateProfileSlotSpec(ContractModel):
    slot_id: Annotated[str, Field(min_length=1, max_length=128)]
    order_index: Annotated[int, Field(strict=True, ge=1, le=47)]
    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    profile: ProfileKind
    worker_lifecycle: WorkerLifecycle
    output_format: OutputFormat
    bounded_concurrency: Literal[1, 2]


def build_candidate_profile_slot_plan() -> tuple[CandidateProfileSlotSpec, ...]:
    """Return the immutable 47-slot LAT-US01 execution plan."""

    slots: list[CandidateProfileSlotSpec] = []
    for case_index, case_id in enumerate(CASE_ORDER):
        for offset, (profile, lifecycle, output_format) in enumerate(
            (
                (
                    "cold-json",
                    WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD,
                    OutputFormat.JSON,
                ),
                (
                    "prewarmed-json",
                    WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED,
                    OutputFormat.JSON,
                ),
                (
                    "cold-markdown",
                    WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD,
                    OutputFormat.MARKDOWN,
                ),
            ),
            start=1,
        ):
            slots.append(
                CandidateProfileSlotSpec(
                    slot_id=f"{case_id}-{profile}",
                    order_index=3 * case_index + offset,
                    case_id=case_id,
                    profile=profile,
                    worker_lifecycle=lifecycle,
                    output_format=output_format,
                    bounded_concurrency=1,
                )
            )
    for offset, case_id in enumerate(CONCURRENT_CASE_ORDER, start=46):
        slots.append(
            CandidateProfileSlotSpec(
                slot_id=f"{case_id}-bound2-cold-json",
                order_index=offset,
                case_id=case_id,
                profile="bound2-cold-json",
                worker_lifecycle=WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD,
                output_format=OutputFormat.JSON,
                bounded_concurrency=2,
            )
        )
    return tuple(slots)


CANDIDATE_PROFILE_SLOT_PLAN = build_candidate_profile_slot_plan()
_SLOT_BY_ID = {item.slot_id: item for item in CANDIDATE_PROFILE_SLOT_PLAN}
CANDIDATE_PROFILE_SLOT_PLAN_SHA256 = hashlib.sha256(
    json.dumps(
        [item.model_dump(mode="json") for item in CANDIDATE_PROFILE_SLOT_PLAN],
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


def candidate_profile_execution_id(slot_id: str, execution_number: int) -> str:
    """Return the only accepted retry-aware execution ID for a fixed slot."""

    if slot_id not in _SLOT_BY_ID:
        raise ValueError("candidate execution slot is outside the fixed plan")
    if (
        isinstance(execution_number, bool)
        or not isinstance(execution_number, int)
        or not 1 <= execution_number <= MAXIMUM_EXECUTIONS_PER_SLOT
    ):
        raise ValueError("candidate execution number must be an integer from 1 to 16")
    return f"lat-us01-{slot_id}-execution-{execution_number:02d}"


def _candidate_profile_execution_number(
    execution_id: str, *, slot_id: str
) -> int | None:
    prefix = f"lat-us01-{slot_id}-execution-"
    if not execution_id.startswith(prefix):
        return None
    suffix = execution_id.removeprefix(prefix)
    if len(suffix) != 2 or not suffix.isascii() or not suffix.isdigit():
        return None
    execution_number = int(suffix)
    if not 1 <= execution_number <= MAXIMUM_EXECUTIONS_PER_SLOT:
        return None
    if execution_id != candidate_profile_execution_id(slot_id, execution_number):
        return None
    return execution_number


def _attempt_matches_slot(
    attempt: LatencyAttempt, slot: CandidateProfileSlotSpec
) -> bool:
    return (
        attempt.slot_id == slot.slot_id
        and attempt.order_index == slot.order_index
        and attempt.case_id == slot.case_id
        and attempt.pair_index == 1
        and attempt.system is SystemName.CANDIDATE
        and attempt.configuration.worker_lifecycle is slot.worker_lifecycle
        and attempt.configuration.output_format is slot.output_format
        and attempt.configuration.bounded_concurrency == slot.bounded_concurrency
    )


def attempt_output_matches_current_runtime(
    attempt: LatencyAttempt, slot: CandidateProfileSlotSpec
) -> bool:
    if attempt.status is not AttemptStatus.SUCCESS:
        return False
    expected_json, expected_markdown, markdown_size = (
        CURRENT_RUNTIME_OUTPUT_IDENTITIES[slot.case_id]
    )
    output = attempt.output
    diagnostic = attempt.diagnostic_output
    if slot.output_format is OutputFormat.JSON:
        return bool(
            output is not None
            and diagnostic is not None
            and output.validation == "ParseResult"
            and diagnostic.validation == "ParseResult"
            and output.semantic_exclusions == ("/processing/duration_ms",)
            and diagnostic.semantic_exclusions == ("/processing/duration_ms",)
            and output.semantic_sha256 == expected_json
            and diagnostic.semantic_sha256 == expected_json
        )
    return bool(
        output is not None
        and diagnostic is not None
        and output.validation == "Markdown"
        and output.sha256 == expected_markdown
        and output.semantic_sha256 == expected_markdown
        and output.size_bytes == markdown_size
        and diagnostic == output
    )


def _attempt_output_matches_p00(
    attempt: LatencyAttempt, slot: CandidateProfileSlotSpec
) -> bool:
    if attempt.status is not AttemptStatus.SUCCESS:
        return False
    expected_json, expected_markdown, markdown_size = P00_OUTPUT_IDENTITIES[
        slot.case_id
    ]
    output = attempt.output
    diagnostic = attempt.diagnostic_output
    if slot.output_format is OutputFormat.JSON:
        return bool(
            output is not None
            and diagnostic is not None
            and output.validation == "ParseResult"
            and diagnostic.validation == "ParseResult"
            and output.semantic_exclusions == ("/processing/duration_ms",)
            and diagnostic.semantic_exclusions == ("/processing/duration_ms",)
            and output.semantic_sha256 == expected_json
            and diagnostic.semantic_sha256 == expected_json
        )
    return bool(
        output is not None
        and diagnostic is not None
        and output.validation == "Markdown"
        and output.sha256 == expected_markdown
        and output.semantic_sha256 == expected_markdown
        and output.size_bytes == markdown_size
        and diagnostic == output
    )


def _ledger_attempt_output_matches(
    attempt: LatencyAttempt,
    slot: CandidateProfileSlotSpec,
    identity: CandidateExecutionIdentity,
) -> bool:
    current_artifacts = (
        identity.current_runtime_run_record,
        identity.current_runtime_semantic_report,
        identity.current_runtime_semantic_report_markdown,
    )
    if all(item is None for item in current_artifacts):
        return _attempt_output_matches_p00(attempt, slot)
    return attempt_output_matches_current_runtime(attempt, slot)


class CandidateExecutionIdentity(ContractModel):
    candidate_code_sha256: Sha256
    pyproject: ArtifactIdentity
    dependency_lock: ArtifactIdentity
    dependency_manifest_sha256: Sha256
    environment_manifest: EnvironmentIdentityEvidence
    environment_comparable: Literal[False]
    model_artifacts_sha256: Sha256
    corpus_registry: ArtifactIdentity
    phase03_oracle: ArtifactIdentity
    m0_resource_record: ArtifactIdentity
    p00_run_record: ArtifactIdentity
    p00_semantic_report: ArtifactIdentity
    current_runtime_run_record: ArtifactIdentity | None = None
    current_runtime_semantic_report: ArtifactIdentity | None = None
    current_runtime_semantic_report_markdown: ArtifactIdentity | None = None
    harness_files: Annotated[
        tuple[ArtifactIdentity, ...], Field(min_length=10, max_length=10)
    ]
    source_registry_sha256: Literal[
        "0fe1648db893170c6584246e553afbc2939f70ed72d3ea15ec1a1d4fe6d05b5a"
    ]

    @model_validator(mode="after")
    def validate_fixed_custody(self) -> CandidateExecutionIdentity:
        fixed = (
            (self.pyproject, "pyproject.toml", None, None),
            (self.dependency_lock, "uv.lock", None, None),
            (
                self.corpus_registry,
                "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json",
                "f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb",
                20_744,
            ),
            (
                self.phase03_oracle,
                "tests/fixtures/phase_03/running_regions/oracle.py",
                "5e70b5df58284f544b43a6189055044c80c2a9a6404f143758be550e3879b563",
                160_147,
            ),
            (
                self.m0_resource_record,
                "tracker/benchmarks/llamaparse-15/runs/baseline-20260728-current/run-metadata.json",
                "386c333bff8ec0678d1194fff5899f82ec9475d29be7d72999a58c3817e3128f",
                8_025,
            ),
            (
                self.p00_run_record,
                "tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/run-record.json",
                "aa6192f99e8c7ac8136aad7a7ed47278e02f9093d8d37b219e2068b020c310e2",
                79_247,
            ),
            (
                self.p00_semantic_report,
                "tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/semantic-report.json",
                "3d2e36fd6696039abaeb346fc458687f9f114a340bc895c8ee5b921efbb17c77",
                317_372,
            ),
        )
        for artifact, path, sha256, size_bytes in fixed:
            if artifact.path != path:
                raise ValueError(f"fixed artifact path differs: {path}")
            if sha256 is not None and (
                artifact.sha256 != sha256 or artifact.size_bytes != size_bytes
            ):
                raise ValueError(f"fixed artifact custody differs: {path}")
        current_runtime = (
            self.current_runtime_run_record,
            self.current_runtime_semantic_report,
            self.current_runtime_semantic_report_markdown,
        )
        if any(item is not None for item in current_runtime):
            if any(item is None for item in current_runtime):
                raise ValueError("current-runtime baseline custody is incomplete")
            current_fixed = (
                (
                    self.current_runtime_run_record,
                    "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/run-record.json",
                    "2cfecdf72a588e0088618ed7001a20ddfa6742d2acf6e89b0a6f0efe5805cb3c",
                    81_637,
                ),
                (
                    self.current_runtime_semantic_report,
                    "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/semantic-report.json",
                    "03044b2c9c4d9caec2cb7d247989ca00bd6556fea12502efc09cc2fb4143567a",
                    317_415,
                ),
                (
                    self.current_runtime_semantic_report_markdown,
                    "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/semantic-report.md",
                    "47318b48735d81e1c7d5bb971617ef2d23e58cbe7e55c150229855359f2d8fe3",
                    1_383,
                ),
            )
            for artifact, path, sha256, size_bytes in current_fixed:
                if artifact is None or (
                    artifact.path != path
                    or artifact.sha256 != sha256
                    or artifact.size_bytes != size_bytes
                ):
                    raise ValueError(f"current-runtime baseline custody differs: {path}")
        if tuple(item.path for item in self.harness_files) != HARNESS_PATHS:
            raise ValueError("complete canonical harness identity order differs")
        lock_records = [
            {
                "path": item.path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in (self.pyproject, self.dependency_lock)
        ]
        derived_lock = hashlib.sha256(
            json.dumps(
                lock_records,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.dependency_manifest_sha256 != derived_lock:
            raise ValueError("pyproject/lock composite identity differs")
        if self.environment_manifest.p00_comparable is not False:
            raise ValueError("M0/current environment must remain non-comparable")
        return self


class P00QualityEvidence(ContractModel):
    case_count: Literal[15]
    page_count: Literal[30]
    reviewed_claim_count: Literal[210]
    literal_eligible_count: Literal[109]
    semantic_eligible_count: Literal[162]
    excluded_unsupported_count: Literal[48]
    control_count: Literal[25]
    dimension_count: Literal[12]
    quality_signature_sha256: Literal[
        "a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed"
    ]
    stable_output_signature_sha256: Literal[
        "a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0"
    ]
    current_runtime_stable_output_signature_sha256: Literal[
        "d10fb6107c9a0b97788ec23d2519a31b53dc3c23df5b06a1566b9e96a072e71e"
    ]
    baseline_policy: Literal[
        "p00-historical-plus-reviewed-current-runtime-exact-v1"
    ]
    zero_unexplained_drift: StrictBool


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be UTC")
    return value.astimezone(UTC)


class CandidateProfileRoleObservation(ContractModel):
    ledger_index: Annotated[int, Field(strict=True, ge=1, le=3_008)]
    observation_id: Annotated[str, Field(min_length=1, max_length=128)]
    execution_id: Annotated[str, Field(min_length=1, max_length=128)]
    slot_id: Annotated[str, Field(min_length=1, max_length=128)]
    role: Literal["authoritative_uninstrumented", "diagnostic_instrumented"]
    status: AttemptStatus
    failure: FailureRecord | None
    started_at_utc: datetime
    completed_at_utc: datetime
    started_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]
    ended_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    worker_evidence: WorkerExecutionEvidence | None
    snapshots: Annotated[tuple[ProcessTreeSnapshot, ...], Field(max_length=8_192)]
    watchdog: WorkerWatchdogEvidence | None
    worker_fatal_envelope: WorkerFatalEnvelope | None = None

    @field_validator("started_at_utc", "completed_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime, info: object) -> datetime:
        return _utc(value, label="role observation timestamp")

    @model_validator(mode="after")
    def validate_role_observation(self) -> CandidateProfileRoleObservation:
        expected_id = f"lat-us01-ledger-{self.ledger_index:04d}-role"
        if self.observation_id != expected_id:
            raise ValueError("role observation ID/order differs")
        if self.slot_id not in _SLOT_BY_ID:
            raise ValueError("role observation slot is outside the fixed plan")
        if (
            _candidate_profile_execution_number(self.execution_id, slot_id=self.slot_id)
            is None
        ):
            raise ValueError("role observation execution ID is non-canonical")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("role observation UTC interval is negative")
        if self.ended_monotonic_ns <= self.started_monotonic_ns:
            raise ValueError("role observation monotonic interval must be positive")
        if self.status is AttemptStatus.SUCCESS:
            if (
                self.failure is not None
                or self.worker_evidence is None
                or not self.snapshots
                or self.watchdog is None
                or self.worker_fatal_envelope is not None
            ):
                raise ValueError(
                    "successful role observation requires worker, process, and watchdog evidence"
                )
        elif self.failure is None:
            raise ValueError("failed role observation requires a closed failure")
        if self.worker_fatal_envelope is not None and (
            self.worker_evidence is not None
            or self.status is AttemptStatus.SUCCESS
            or self.failure is None
            or self.failure.exception_type
            not in {FailureType.WORKER_CRASH, FailureType.WORKER_PROTOCOL_ERROR}
        ):
            raise ValueError(
                "worker fatal envelope is inconsistent with role-observation failure"
            )
        if self.worker_evidence is not None:
            expected_role = self.role
            if (
                self.worker_evidence.measurement_role != expected_role
                or self.worker_evidence.status is not self.status
                or self.worker_evidence.failure != self.failure
                or self.worker_evidence.started_at_utc != self.started_at_utc
                or self.worker_evidence.completed_at_utc != self.completed_at_utc
                or self.worker_evidence.request_started_monotonic_ns
                != self.started_monotonic_ns
                or self.worker_evidence.request_ended_monotonic_ns
                != self.ended_monotonic_ns
            ):
                raise ValueError("role observation/worker evidence differs")
            if (
                self.worker_evidence.schema_id != "phase-latency-external-worker-v2"
                or self.worker_evidence.response_boundary_protocol
                != "controller-response-freeze-and-post-response-resource-closure-v2"
                or self.worker_evidence.network_isolation.policy
                != "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
                or self.worker_evidence.network_isolation.python_guard_restore_disposition
                != "controller-verified-worker-zero-exit"
                or self.worker_evidence.resource_tracker_disposition is None
                or self.worker_evidence.resource_tracker_disposition.controller_no_relaunch_through_zero_exit_verified
                is not True
            ):
                raise ValueError(
                    "profile role observation requires v2 lifecycle evidence"
                )
        return self


class CandidateProfileAttemptObservation(ContractModel):
    ledger_index: Annotated[int, Field(strict=True, ge=1, le=3_008)]
    observation_id: Annotated[str, Field(min_length=1, max_length=128)]
    execution_id: Annotated[str, Field(min_length=1, max_length=128)]
    role_observation_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=2)]
    attempt: LatencyAttempt

    @model_validator(mode="after")
    def validate_attempt_observation(self) -> CandidateProfileAttemptObservation:
        if self.observation_id != f"lat-us01-ledger-{self.ledger_index:04d}-attempt":
            raise ValueError("attempt observation ID/order differs")
        if self.role_observation_ids != tuple(dict.fromkeys(self.role_observation_ids)):
            raise ValueError("attempt role-observation links must be unique")
        slot = _SLOT_BY_ID.get(self.attempt.slot_id)
        if slot is None or not _attempt_matches_slot(self.attempt, slot):
            raise ValueError("attempt observation differs from the fixed slot plan")
        if (
            self.execution_id != self.attempt.attempt_id
            or _candidate_profile_execution_number(
                self.execution_id, slot_id=self.attempt.slot_id
            )
            is None
        ):
            raise ValueError("attempt observation execution ID is non-canonical")
        return self


class CandidateProfileControllerFailureEvent(ContractModel):
    ledger_index: Annotated[int, Field(strict=True, ge=1, le=3_008)]
    event_id: Annotated[str, Field(min_length=1, max_length=128)]
    event_kind: Literal[
        "controller_exception",
        "controller_keyboard_interrupt",
        "controller_hard_death_recovered",
        "evidence_serialization_error",
    ]
    slot_id: Annotated[str, Field(min_length=1, max_length=128)] | None
    execution_id: Annotated[str, Field(min_length=1, max_length=128)] | None
    status: Literal[
        AttemptStatus.ERROR,
        AttemptStatus.CANCELLED,
        AttemptStatus.TIMEOUT,
    ]
    failure_code: FailureCode
    failure_type: FailureType
    observed_at_utc: datetime
    observed_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("observed_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="controller failure timestamp")

    @model_validator(mode="after")
    def validate_controller_failure(self) -> CandidateProfileControllerFailureEvent:
        if self.event_id != f"lat-us01-ledger-{self.ledger_index:04d}-controller":
            raise ValueError("controller failure ID/order differs")
        if self.slot_id is not None and self.slot_id not in _SLOT_BY_ID:
            raise ValueError("controller failure slot is outside the fixed plan")
        if (self.slot_id is None) != (self.execution_id is None):
            raise ValueError("controller failure slot/execution linkage differs")
        if (
            self.slot_id is not None
            and self.execution_id is not None
            and _candidate_profile_execution_number(
                self.execution_id, slot_id=self.slot_id
            )
            is None
        ):
            raise ValueError("controller failure execution ID is non-canonical")
        return self


class CandidateProfileFinalizationEvent(ContractModel):
    ledger_index: Annotated[int, Field(strict=True, ge=1, le=3_009)]
    event_id: Annotated[str, Field(min_length=1, max_length=128)]
    disposition: Literal["aborted", "complete"]
    missing_slot_ids: Annotated[tuple[str, ...], Field(max_length=47)]
    finalized_at_utc: datetime
    finalized_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("finalized_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="candidate ledger finalization timestamp")

    @model_validator(mode="after")
    def validate_finalization(self) -> CandidateProfileFinalizationEvent:
        if self.event_id != f"lat-us01-ledger-{self.ledger_index:04d}-finalize":
            raise ValueError("candidate finalization ID/order differs")
        if (self.disposition == "complete") != (not self.missing_slot_ids):
            raise ValueError("candidate finalization disposition/missing slots differ")
        return self


class CandidateProfileSelection(ContractModel):
    slot_id: Annotated[str, Field(min_length=1, max_length=128)]
    selected_observation_id: Annotated[str, Field(min_length=1, max_length=128)]
    selected_attempt_id: Annotated[str, Field(min_length=1, max_length=128)]


def _tree_response_hwm_differs(
    tree: ProcessTreeMetrics, worker: WorkerExecutionEvidence
) -> bool:
    reported = tree.worker_reported_hwm_bytes_at_response_boundary
    if reported is None:
        # Preserve byte-for-byte readability of sealed pre-field ledgers.
        return tree.peak_worker_hwm_bytes != (
            worker.worker_hwm_bytes_at_response_boundary
        )
    return bool(
        reported != worker.worker_hwm_bytes_at_response_boundary
        or reported
        != worker.resource_boundary.response_boundary_worker_process_lifetime_hwm_bytes
        or tree.peak_worker_hwm_bytes < reported
    )


def _worker_role_projection_differs(
    attempt: LatencyAttempt,
    role_observation: CandidateProfileRoleObservation,
    tree: ProcessTreeMetrics,
    *,
    diagnostic_role: bool,
) -> bool:
    """Compare one retained raw worker role to its assembled attempt fields."""

    worker = role_observation.worker_evidence
    if worker is None:
        return True
    boundary = worker.resource_boundary
    expected_total_ns = (
        attempt.diagnostic_total_latency_ns
        if diagnostic_role
        else attempt.total_latency_ns
    )
    expected_output = attempt.diagnostic_output if diagnostic_role else attempt.output
    expected_error = (
        attempt.diagnostic_error_response if diagnostic_role else attempt.error_response
    )
    expected_failure = (
        attempt.diagnostic_failure if diagnostic_role else attempt.failure
    )
    expected_cache = (
        attempt.diagnostic_cache_state
        if diagnostic_role
        else attempt.authoritative_cache_state
    )
    expected_network = (
        attempt.diagnostic_network_isolation
        if diagnostic_role
        else attempt.authoritative_network_isolation
    )
    expected_protocol = (
        attempt.diagnostic_response_boundary_protocol
        if diagnostic_role
        else attempt.authoritative_response_boundary_protocol
    )
    expected_tracker = (
        attempt.diagnostic_resource_tracker_disposition
        if diagnostic_role
        else attempt.authoritative_resource_tracker_disposition
    )
    expected_post_response_ns = (
        attempt.diagnostic_post_response_validation_duration_ns
        if diagnostic_role
        else attempt.authoritative_post_response_validation_duration_ns
    )
    response = tree.response_boundary_snapshot
    closure = tree.resource_closure_snapshot
    return bool(
        worker.source != attempt.source
        or worker.configuration != attempt.configuration
        or worker.status is not attempt.status
        or worker.output != expected_output
        or worker.error_response != expected_error
        or worker.failure != expected_failure
        or worker.request_started_monotonic_ns != tree.request_started_monotonic_ns
        or worker.request_ended_monotonic_ns != tree.request_ended_monotonic_ns
        or worker.request_ended_monotonic_ns - worker.request_started_monotonic_ns
        != expected_total_ns
        or worker.cache_state != expected_cache
        or worker.network_isolation != expected_network
        or worker.response_boundary_protocol != expected_protocol
        or worker.resource_tracker_disposition != expected_tracker
        or worker.post_response_validation_duration_ns != expected_post_response_ns
        or (
            diagnostic_role
            and (
                worker.stage_trace != attempt.stage_trace
                or worker.instrumentation_manifest != attempt.instrumentation_manifest
            )
        )
        or (
            not diagnostic_role
            and (
                worker.started_at_utc != attempt.started_at_utc
                or worker.completed_at_utc != attempt.completed_at_utc
            )
        )
        or role_observation.snapshots != tree.snapshots
        or _tree_response_hwm_differs(tree, worker)
        or tree.worker_lifetime_hwm_bytes_at_resource_closure
        != worker.worker_hwm_bytes_at_resource_closure
        or response is None
        or not (
            worker.response_boundary_signal_monotonic_ns
            <= response.observed_monotonic_ns
            <= worker.response_boundary_ack_monotonic_ns
        )
        or closure is None
        or worker.resource_closure_signal_monotonic_ns is None
        or worker.resource_closure_ack_monotonic_ns is None
        or not (
            worker.resource_closure_signal_monotonic_ns
            <= closure.observed_monotonic_ns
            <= worker.resource_closure_ack_monotonic_ns
        )
        or tree.exact_worker_self_cpu_ns
        != int(boundary.response_boundary_worker_self_user_cpu_delta_ns or 0)
        + int(boundary.response_boundary_worker_self_system_cpu_delta_ns or 0)
        or tree.exact_reaped_children_cpu_ns
        != int(boundary.response_boundary_reaped_children_user_cpu_delta_ns or 0)
        + int(boundary.response_boundary_reaped_children_system_cpu_delta_ns or 0)
        or tree.lifecycle_exact_worker_self_cpu_ns
        != boundary.worker_self_user_cpu_delta_ns
        + boundary.worker_self_system_cpu_delta_ns
        or tree.lifecycle_reaped_children_cpu_ns
        != boundary.reaped_children_user_cpu_delta_ns
        + boundary.reaped_children_system_cpu_delta_ns
        or tree.worker_lifetime_hwm_bytes_at_resource_closure
        != boundary.worker_process_lifetime_hwm_bytes
        or tree.reaped_children_hwm_bytes
        != boundary.reaped_children_process_lifetime_hwm_bytes
    )


def candidate_profile_ledger_payload_sha256(
    value: ContractModel | Mapping[str, object],
) -> str:
    if isinstance(value, ContractModel):
        payload = value.model_dump(mode="json", exclude={"checkpoint_sha256"})
    else:
        payload = dict(value)
        payload.pop("checkpoint_sha256", None)
    execution_identity = payload.get("execution_identity")
    if isinstance(execution_identity, dict) and all(
        execution_identity.get(field) is None
        for field in (
            "current_runtime_run_record",
            "current_runtime_semantic_report",
            "current_runtime_semantic_report_markdown",
        )
    ):
        for field in (
            "current_runtime_run_record",
            "current_runtime_semantic_report",
            "current_runtime_semantic_report_markdown",
        ):
            execution_identity.pop(field, None)
    def strip_pre_field_none(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: strip_pre_field_none(item)
                for key, item in value.items()
                if not (
                    key == "worker_reported_hwm_bytes_at_response_boundary"
                    and item is None
                )
            }
        if isinstance(value, (list, tuple)):
            return [strip_pre_field_none(item) for item in value]
        return value

    payload = strip_pre_field_none(payload)
    assert isinstance(payload, dict)
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class CandidateProfileAttemptLedger(ContractModel):
    schema_id: Literal["phase-latency-candidate-attempt-ledger-v1"]
    schema_version: Literal["1.0"]
    ledger_id: Literal["lat-us01-all-15-attempt-ledger-v1"]
    slot_plan_sha256: Sha256
    execution_identity: CandidateExecutionIdentity
    disposition: Literal["in_progress", "aborted", "complete"]
    role_observations: Annotated[
        tuple[CandidateProfileRoleObservation, ...], Field(max_length=1_504)
    ]
    attempt_observations: Annotated[
        tuple[CandidateProfileAttemptObservation, ...], Field(max_length=752)
    ]
    controller_failures: Annotated[
        tuple[CandidateProfileControllerFailureEvent, ...], Field(max_length=752)
    ]
    finalization_event: CandidateProfileFinalizationEvent | None
    selections: Annotated[tuple[CandidateProfileSelection, ...], Field(max_length=47)]
    missing_slot_ids: Annotated[tuple[str, ...], Field(max_length=47)]
    journal_event_count: Annotated[int, Field(strict=True, ge=0, le=3_009)]
    role_observation_count: Annotated[int, Field(strict=True, ge=0, le=1_504)]
    attempt_observation_count: Annotated[int, Field(strict=True, ge=0, le=752)]
    controller_failure_count: Annotated[int, Field(strict=True, ge=0, le=752)]
    finalization_event_count: Literal[0, 1]
    failed_role_observation_count: Annotated[int, Field(strict=True, ge=0, le=1_504)]
    failed_attempt_observation_count: Annotated[int, Field(strict=True, ge=0, le=752)]
    drifted_attempt_observation_count: Annotated[int, Field(strict=True, ge=0, le=752)]
    initial_checkpoint_written_before_worker_launch: Literal[True]
    persistence_policy: Literal[
        "initial-before-launch-atomic-0600-replace-after-every-journal-event-v1"
    ]
    retained_file_mode: Literal["0600"]
    checkpoint_index: Annotated[int, Field(strict=True, ge=1, le=3_010)]
    previous_checkpoint_sha256: Sha256 | None
    checkpoint_sha256: Sha256
    acceptance_claimed: Literal[False]
    hosted_calls: Literal[0]
    hosted_credits: Literal[0]
    prompt_tokens: Literal[0]
    completion_tokens: Literal[0]
    billed_cost_microusd: Literal[0]
    egress_bytes: Literal[0]

    @model_validator(mode="after")
    def validate_ledger(self) -> CandidateProfileAttemptLedger:
        expected_plan_sha = CANDIDATE_PROFILE_SLOT_PLAN_SHA256
        if self.slot_plan_sha256 != expected_plan_sha:
            raise ValueError("candidate ledger slot-plan identity differs")
        event_rows = tuple(
            sorted(
                (
                    *(
                        (item.ledger_index, item.observation_id, "role", item)
                        for item in self.role_observations
                    ),
                    *(
                        (item.ledger_index, item.observation_id, "attempt", item)
                        for item in self.attempt_observations
                    ),
                    *(
                        (item.ledger_index, item.event_id, "controller", item)
                        for item in self.controller_failures
                    ),
                    *(
                        (
                            (
                                self.finalization_event.ledger_index,
                                self.finalization_event.event_id,
                                "finalize",
                                self.finalization_event,
                            ),
                        )
                        if self.finalization_event is not None
                        else ()
                    ),
                ),
                key=lambda item: item[0],
            )
        )
        if tuple(item[0] for item in event_rows) != tuple(
            range(1, len(event_rows) + 1)
        ):
            raise ValueError("candidate ledger journal indices must be contiguous")
        if len({item[1] for item in event_rows}) != len(event_rows):
            raise ValueError("candidate ledger journal IDs must be globally unique")
        for collection in (
            self.role_observations,
            self.attempt_observations,
            self.controller_failures,
        ):
            if tuple(item.ledger_index for item in collection) != tuple(
                sorted(item.ledger_index for item in collection)
            ):
                raise ValueError("candidate ledger collections must be canonical")

        roles_by_id = {item.observation_id: item for item in self.role_observations}
        if len(roles_by_id) != len(self.role_observations):
            raise ValueError("candidate role-observation IDs must be unique")
        attempts_by_id = {
            item.observation_id: item for item in self.attempt_observations
        }
        if len(attempts_by_id) != len(self.attempt_observations):
            raise ValueError("candidate attempt-observation IDs must be unique")
        attempt_ids: set[str] = set()
        execution_rows: dict[
            tuple[str, str],
            dict[str, list[object]],
        ] = {}
        for role in self.role_observations:
            row = execution_rows.setdefault(
                (role.slot_id, role.execution_id),
                {"role": [], "attempt": [], "controller": []},
            )
            row["role"].append(role)
        for observation in self.attempt_observations:
            if observation.attempt.attempt_id in attempt_ids:
                raise ValueError("retained LatencyAttempt IDs must be globally unique")
            attempt_ids.add(observation.attempt.attempt_id)
            row = execution_rows.setdefault(
                (observation.attempt.slot_id, observation.execution_id),
                {"role": [], "attempt": [], "controller": []},
            )
            row["attempt"].append(observation)
        for event in self.controller_failures:
            if event.slot_id is None or event.execution_id is None:
                continue
            row = execution_rows.setdefault(
                (event.slot_id, event.execution_id),
                {"role": [], "attempt": [], "controller": []},
            )
            row["controller"].append(event)

        execution_first_indices: dict[str, list[tuple[int, str]]] = {}
        for (slot_id, execution_id), row in execution_rows.items():
            roles = tuple(sorted(row["role"], key=lambda item: item.ledger_index))
            attempts = tuple(row["attempt"])
            controllers = tuple(row["controller"])
            if (
                len(roles) > 2
                or tuple(item.role for item in roles)
                not in (
                    (),
                    ("authoritative_uninstrumented",),
                    (
                        "authoritative_uninstrumented",
                        "diagnostic_instrumented",
                    ),
                )
                or len(attempts) > 1
                or len(controllers) > 1
                or (attempts and controllers)
            ):
                raise ValueError("candidate execution event sequence is non-canonical")
            indices = tuple(
                item.ledger_index for item in (*roles, *attempts, *controllers)
            )
            execution_first_indices.setdefault(slot_id, []).append(
                (min(indices), execution_id)
            )
            if attempts:
                observation = attempts[0]
                if observation.role_observation_ids != tuple(
                    item.observation_id for item in roles
                ) or any(
                    item.ledger_index >= observation.ledger_index for item in roles
                ):
                    raise ValueError("attempt role links are not causal/canonical")
                attempt = observation.attempt
                if attempt.status is AttemptStatus.SUCCESS:
                    if len(roles) != 2 or any(
                        item.status is not AttemptStatus.SUCCESS for item in roles
                    ):
                        raise ValueError(
                            "successful attempt requires both successful role checkpoints"
                        )
                    authoritative, diagnostic = roles
                    authoritative_tree = attempt.process_tree
                    diagnostic_tree = attempt.diagnostic_process_tree
                    if (
                        authoritative.worker_evidence is None
                        or diagnostic.worker_evidence is None
                        or authoritative_tree is None
                        or diagnostic_tree is None
                        or authoritative.worker_evidence.source != attempt.source
                        or diagnostic.worker_evidence.source != attempt.source
                        or authoritative.worker_evidence.configuration
                        != attempt.configuration
                        or diagnostic.worker_evidence.configuration
                        != attempt.configuration
                        or authoritative.worker_evidence.output != attempt.output
                        or diagnostic.worker_evidence.output
                        != attempt.diagnostic_output
                        or authoritative.snapshots != authoritative_tree.snapshots
                        or diagnostic.snapshots != diagnostic_tree.snapshots
                        or authoritative.watchdog != attempt.authoritative_watchdog
                        or diagnostic.watchdog != attempt.diagnostic_watchdog
                        or authoritative.worker_evidence.network_isolation
                        != attempt.authoritative_network_isolation
                        or diagnostic.worker_evidence.network_isolation
                        != attempt.diagnostic_network_isolation
                        or authoritative.worker_evidence.response_boundary_protocol
                        != attempt.authoritative_response_boundary_protocol
                        or diagnostic.worker_evidence.response_boundary_protocol
                        != attempt.diagnostic_response_boundary_protocol
                        or authoritative.worker_evidence.resource_tracker_disposition
                        != attempt.authoritative_resource_tracker_disposition
                        or diagnostic.worker_evidence.resource_tracker_disposition
                        != attempt.diagnostic_resource_tracker_disposition
                    ):
                        raise ValueError(
                            "successful attempt differs from retained twin-role evidence"
                        )
                    for role_observation, tree in (
                        (authoritative, authoritative_tree),
                        (diagnostic, diagnostic_tree),
                    ):
                        worker = role_observation.worker_evidence
                        boundary = worker.resource_boundary
                        diagnostic_role = role_observation is diagnostic
                        expected_total_ns = (
                            attempt.diagnostic_total_latency_ns
                            if diagnostic_role
                            else attempt.total_latency_ns
                        )
                        expected_cache_state = (
                            attempt.diagnostic_cache_state
                            if diagnostic_role
                            else attempt.authoritative_cache_state
                        )
                        expected_post_response_ns = (
                            attempt.diagnostic_post_response_validation_duration_ns
                            if diagnostic_role
                            else attempt.authoritative_post_response_validation_duration_ns
                        )
                        expected_output = (
                            attempt.diagnostic_output
                            if diagnostic_role
                            else attempt.output
                        )
                        expected_network = (
                            attempt.diagnostic_network_isolation
                            if diagnostic_role
                            else attempt.authoritative_network_isolation
                        )
                        expected_protocol = (
                            attempt.diagnostic_response_boundary_protocol
                            if diagnostic_role
                            else attempt.authoritative_response_boundary_protocol
                        )
                        expected_tracker = (
                            attempt.diagnostic_resource_tracker_disposition
                            if diagnostic_role
                            else attempt.authoritative_resource_tracker_disposition
                        )
                        if (
                            worker.status is not attempt.status
                            or worker.evidence_complete is not attempt.evidence_complete
                            or worker.output != expected_output
                            or worker.error_response is not None
                            or worker.failure is not None
                            or worker.request_started_monotonic_ns
                            != tree.request_started_monotonic_ns
                            or worker.request_ended_monotonic_ns
                            != tree.request_ended_monotonic_ns
                            or worker.request_ended_monotonic_ns
                            - worker.request_started_monotonic_ns
                            != expected_total_ns
                            or worker.cache_state != expected_cache_state
                            or worker.network_isolation != expected_network
                            or worker.response_boundary_protocol != expected_protocol
                            or worker.resource_tracker_disposition != expected_tracker
                            or worker.post_response_validation_duration_ns
                            != expected_post_response_ns
                            or (
                                diagnostic_role
                                and (
                                    worker.stage_trace != attempt.stage_trace
                                    or worker.instrumentation_manifest
                                    != attempt.instrumentation_manifest
                                )
                            )
                            or (
                                not diagnostic_role
                                and (
                                    worker.started_at_utc != attempt.started_at_utc
                                    or worker.completed_at_utc
                                    != attempt.completed_at_utc
                                )
                            )
                            or _tree_response_hwm_differs(tree, worker)
                            or tree.worker_lifetime_hwm_bytes_at_resource_closure
                            != worker.worker_hwm_bytes_at_resource_closure
                            or tree.response_boundary_snapshot is None
                            or not (
                                worker.response_boundary_signal_monotonic_ns
                                <= tree.response_boundary_snapshot.observed_monotonic_ns
                                <= worker.response_boundary_ack_monotonic_ns
                            )
                            or tree.resource_closure_snapshot is None
                            or worker.resource_closure_signal_monotonic_ns is None
                            or worker.resource_closure_ack_monotonic_ns is None
                            or not (
                                worker.resource_closure_signal_monotonic_ns
                                <= tree.resource_closure_snapshot.observed_monotonic_ns
                                <= worker.resource_closure_ack_monotonic_ns
                            )
                            or tree.exact_worker_self_cpu_ns
                            != int(
                                boundary.response_boundary_worker_self_user_cpu_delta_ns
                                or 0
                            )
                            + int(
                                boundary.response_boundary_worker_self_system_cpu_delta_ns
                                or 0
                            )
                            or tree.exact_reaped_children_cpu_ns
                            != int(
                                boundary.response_boundary_reaped_children_user_cpu_delta_ns
                                or 0
                            )
                            + int(
                                boundary.response_boundary_reaped_children_system_cpu_delta_ns
                                or 0
                            )
                            or tree.lifecycle_exact_worker_self_cpu_ns
                            != boundary.worker_self_user_cpu_delta_ns
                            + boundary.worker_self_system_cpu_delta_ns
                            or tree.lifecycle_reaped_children_cpu_ns
                            != boundary.reaped_children_user_cpu_delta_ns
                            + boundary.reaped_children_system_cpu_delta_ns
                            or tree.worker_lifetime_hwm_bytes_at_resource_closure
                            != boundary.worker_process_lifetime_hwm_bytes
                            or tree.reaped_children_hwm_bytes
                            != boundary.reaped_children_process_lifetime_hwm_bytes
                        ):
                            raise ValueError(
                                "attempt process resources differ from worker evidence"
                            )
                elif attempt.instrumentation_manifest is not None:
                    if (
                        len(roles) != 2
                        or any(item.worker_evidence is None for item in roles)
                        or attempt.process_tree is None
                        or attempt.diagnostic_process_tree is None
                    ):
                        raise ValueError(
                            "failed complete twin requires both raw worker roles"
                        )
                    authoritative, diagnostic = roles
                    authoritative_worker = authoritative.worker_evidence
                    diagnostic_worker = diagnostic.worker_evidence
                    assert authoritative_worker is not None
                    assert diagnostic_worker is not None
                    if (
                        _worker_role_projection_differs(
                            attempt,
                            authoritative,
                            attempt.process_tree,
                            diagnostic_role=False,
                        )
                        or _worker_role_projection_differs(
                            attempt,
                            diagnostic,
                            attempt.diagnostic_process_tree,
                            diagnostic_role=True,
                        )
                        or authoritative.watchdog != attempt.authoritative_watchdog
                        or diagnostic.watchdog != attempt.diagnostic_watchdog
                        or authoritative_worker.http_status
                        != diagnostic_worker.http_status
                        or attempt.evidence_complete
                        is not (
                            authoritative_worker.evidence_complete
                            and diagnostic_worker.evidence_complete
                        )
                    ):
                        raise ValueError(
                            "failed attempt differs from retained twin-role evidence"
                        )
                elif not any(
                    item.status is not AttemptStatus.SUCCESS for item in roles
                ) and not (
                    attempt.evidence_complete is False
                    and attempt.failure is not None
                    and attempt.failure.code
                    in {
                        "controller_execution_identity_drift",
                        "worker_evidence_rejected",
                        "worker_identity_mismatch",
                    }
                ):
                    raise ValueError(
                        "failed attempt requires a failing role or controller rejection"
                    )

        for slot_id, rows in execution_first_indices.items():
            ordered_execution_ids = tuple(
                execution_id for _, execution_id in sorted(rows)
            )
            expected_execution_ids = tuple(
                candidate_profile_execution_id(slot_id, number)
                for number in range(1, len(ordered_execution_ids) + 1)
            )
            if ordered_execution_ids != expected_execution_ids:
                raise ValueError("candidate retry execution IDs must be contiguous")

        open_executions = tuple(
            (slot_id, execution_id)
            for (slot_id, execution_id), row in execution_rows.items()
            if not row["attempt"] and not row["controller"]
        )
        if len(open_executions) > 1 and (
            len(open_executions) != 2
            or {item[0] for item in open_executions}
            != {
                "ny-timetable-bound2-cold-json",
                "uber-earnings-bound2-cold-json",
            }
        ):
            raise ValueError(
                "candidate ledger active executions exceed the fixed concurrency plan"
            )

        terminal = self.disposition in ("aborted", "complete")
        if terminal and open_executions:
            raise ValueError("terminal ledger cannot retain an open execution")
        if terminal:
            if (
                self.finalization_event is None
                or self.finalization_event.ledger_index != len(event_rows)
                or self.finalization_event.disposition != self.disposition
            ):
                raise ValueError("terminal ledger requires the final journal event")
            prior_utc = tuple(
                item.completed_at_utc for item in self.role_observations
            ) + tuple(item.observed_at_utc for item in self.controller_failures)
            prior_monotonic = tuple(
                item.ended_monotonic_ns for item in self.role_observations
            ) + tuple(item.observed_monotonic_ns for item in self.controller_failures)
            if (
                prior_utc and self.finalization_event.finalized_at_utc < max(prior_utc)
            ) or (
                prior_monotonic
                and self.finalization_event.finalized_monotonic_ns
                < max(prior_monotonic)
            ):
                raise ValueError("candidate finalization precedes retained evidence")
        elif self.finalization_event is not None:
            raise ValueError("in-progress ledger cannot contain a finalization event")

        identity = self.execution_identity
        expected_worker_environment_sha256 = (
            identity.environment_manifest.sanitized_worker_environment_sha256
        )
        for observation in self.attempt_observations:
            attempt = observation.attempt
            if (
                attempt.candidate_code_sha256 != identity.candidate_code_sha256
                or attempt.dependency_lock_sha256 != identity.dependency_manifest_sha256
                or attempt.environment_sha256
                != identity.environment_manifest.manifest_sha256
                or attempt.model_artifacts_sha256 != identity.model_artifacts_sha256
            ):
                raise ValueError(
                    "ledger attempt differs from pre-run execution identity"
                )
            for isolation in (
                attempt.authoritative_network_isolation,
                attempt.diagnostic_network_isolation,
            ):
                if isolation is not None and (
                    isolation.policy
                    != "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
                    or isolation.worker_environment_sha256
                    != expected_worker_environment_sha256
                ):
                    raise ValueError(
                        "ledger attempt sanitized worker environment differs"
                    )
        for observation in self.role_observations:
            evidence = observation.worker_evidence
            if evidence is None:
                continue
            identity_differs = (
                evidence.candidate_code_sha256 != identity.candidate_code_sha256
                or evidence.dependency_lock_sha256
                != identity.dependency_manifest_sha256
                or evidence.environment_sha256
                != identity.environment_manifest.manifest_sha256
                or evidence.environment_manifest != identity.environment_manifest
                or evidence.model_artifacts_sha256 != identity.model_artifacts_sha256
                or evidence.network_isolation.worker_environment_sha256
                != expected_worker_environment_sha256
            )
            if not identity_differs:
                continue
            row = execution_rows[(observation.slot_id, observation.execution_id)]
            retained_attempts = tuple(row["attempt"])
            open_mismatch = not retained_attempts and not row["controller"]
            classified_mismatch = bool(
                len(retained_attempts) == 1
                and retained_attempts[0].attempt.status is not AttemptStatus.SUCCESS
                and retained_attempts[0].attempt.evidence_complete is False
                and retained_attempts[0].attempt.failure is not None
                and retained_attempts[0].attempt.failure.code
                in {
                    "controller_execution_identity_drift",
                    "worker_identity_mismatch",
                }
            )
            classified_controller_failure = len(row["controller"]) == 1
            if not (
                open_mismatch or classified_mismatch or classified_controller_failure
            ):
                raise ValueError("ledger role differs from pre-run execution identity")

        selections = self.selections
        plan_order = {
            item.slot_id: item.order_index for item in CANDIDATE_PROFILE_SLOT_PLAN
        }
        if tuple(item.slot_id for item in selections) != tuple(
            sorted((item.slot_id for item in selections), key=plan_order.__getitem__)
        ) or len({item.slot_id for item in selections}) != len(selections):
            raise ValueError("candidate ledger selections must be unique/canonical")
        by_slot: dict[str, list[CandidateProfileAttemptObservation]] = {}
        for observation in self.attempt_observations:
            by_slot.setdefault(observation.attempt.slot_id, []).append(observation)
        expected_selections: list[CandidateProfileSelection] = []
        for slot in CANDIDATE_PROFILE_SLOT_PLAN:
            eligible = tuple(
                observation
                for observation in by_slot.get(slot.slot_id, [])
                if observation.attempt.status is AttemptStatus.SUCCESS
                and _ledger_attempt_output_matches(
                    observation.attempt, slot, self.execution_identity
                )
            )
            if eligible:
                selected = eligible[-1]
                expected_selections.append(
                    CandidateProfileSelection(
                        slot_id=slot.slot_id,
                        selected_observation_id=selected.observation_id,
                        selected_attempt_id=selected.attempt.attempt_id,
                    )
                )
        if selections != tuple(expected_selections):
            raise ValueError("candidate ledger selections must be derived")
        for selection in selections:
            observation = attempts_by_id.get(selection.selected_observation_id)
            if observation is None or (
                selection.selected_attempt_id != observation.attempt.attempt_id
            ):
                raise ValueError("candidate selection must bind a retained attempt")
        selected_ids = {item.slot_id for item in selections}
        expected_missing = tuple(
            item.slot_id
            for item in CANDIDATE_PROFILE_SLOT_PLAN
            if item.slot_id not in selected_ids
        )
        if self.missing_slot_ids != expected_missing:
            raise ValueError("candidate ledger missing slots must be derived")
        if self.finalization_event is not None and (
            self.finalization_event.missing_slot_ids != expected_missing
        ):
            raise ValueError("candidate finalization missing slots must be derived")
        if self.disposition == "complete":
            if expected_missing:
                raise ValueError("complete candidate ledger cannot omit a slot")
        elif self.disposition == "aborted" and not expected_missing:
            raise ValueError("aborted candidate ledger must retain a missing slot")

        failed_roles = sum(
            item.status is not AttemptStatus.SUCCESS for item in self.role_observations
        )
        failed_attempts = sum(
            item.attempt.status is not AttemptStatus.SUCCESS
            for item in self.attempt_observations
        )
        drifted_attempts = sum(
            item.attempt.status is AttemptStatus.SUCCESS
            and not _ledger_attempt_output_matches(
                item.attempt,
                _SLOT_BY_ID[item.attempt.slot_id],
                self.execution_identity,
            )
            for item in self.attempt_observations
        )
        counts = (
            self.journal_event_count,
            self.role_observation_count,
            self.attempt_observation_count,
            self.controller_failure_count,
            self.finalization_event_count,
            self.failed_role_observation_count,
            self.failed_attempt_observation_count,
            self.drifted_attempt_observation_count,
        )
        expected_counts = (
            len(event_rows),
            len(self.role_observations),
            len(self.attempt_observations),
            len(self.controller_failures),
            int(self.finalization_event is not None),
            failed_roles,
            failed_attempts,
            drifted_attempts,
        )
        if counts != expected_counts:
            raise ValueError("candidate ledger denominators must be recomputed")
        if self.checkpoint_index != self.journal_event_count + 1:
            raise ValueError("candidate ledger checkpoint index must follow journal")
        if (self.checkpoint_index == 1) != (self.previous_checkpoint_sha256 is None):
            raise ValueError("candidate ledger previous-checkpoint linkage differs")
        if self.checkpoint_sha256 != candidate_profile_ledger_payload_sha256(self):
            raise ValueError("candidate ledger checkpoint digest must be recomputed")
        return self

    @property
    def has_blocking_observation(self) -> bool:
        return bool(
            self.controller_failure_count
            or self.failed_role_observation_count
            or self.failed_attempt_observation_count
            or self.drifted_attempt_observation_count
        )


def seal_candidate_profile_attempt_ledger(
    payload: Mapping[str, object],
) -> CandidateProfileAttemptLedger:
    candidate = dict(payload)
    candidate["checkpoint_sha256"] = candidate_profile_ledger_payload_sha256(candidate)
    return CandidateProfileAttemptLedger.model_validate(candidate)


def initial_candidate_profile_attempt_ledger(
    identity: CandidateExecutionIdentity,
) -> CandidateProfileAttemptLedger:
    return seal_candidate_profile_attempt_ledger(
        {
            "schema_id": "phase-latency-candidate-attempt-ledger-v1",
            "schema_version": "1.0",
            "ledger_id": "lat-us01-all-15-attempt-ledger-v1",
            "slot_plan_sha256": CANDIDATE_PROFILE_SLOT_PLAN_SHA256,
            "execution_identity": identity.model_dump(mode="json"),
            "disposition": "in_progress",
            "role_observations": [],
            "attempt_observations": [],
            "controller_failures": [],
            "finalization_event": None,
            "selections": [],
            "missing_slot_ids": [item.slot_id for item in CANDIDATE_PROFILE_SLOT_PLAN],
            "journal_event_count": 0,
            "role_observation_count": 0,
            "attempt_observation_count": 0,
            "controller_failure_count": 0,
            "finalization_event_count": 0,
            "failed_role_observation_count": 0,
            "failed_attempt_observation_count": 0,
            "drifted_attempt_observation_count": 0,
            "initial_checkpoint_written_before_worker_launch": True,
            "persistence_policy": (
                "initial-before-launch-atomic-0600-replace-after-every-journal-event-v1"
            ),
            "retained_file_mode": "0600",
            "checkpoint_index": 1,
            "previous_checkpoint_sha256": None,
            "acceptance_claimed": False,
            "hosted_calls": 0,
            "hosted_credits": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "billed_cost_microusd": 0,
            "egress_bytes": 0,
        }
    )


def next_candidate_profile_execution_id(
    ledger: CandidateProfileAttemptLedger, slot_id: str
) -> str:
    """Return the active or next retry ID without mutating the ledger."""

    if ledger.disposition != "in_progress":
        raise ValueError("terminal candidate ledger cannot start an execution")
    if slot_id not in _SLOT_BY_ID:
        raise ValueError("candidate execution slot is outside the fixed plan")
    execution_ids: list[str] = []
    closed_execution_ids = {
        item.execution_id for item in ledger.attempt_observations
    } | {
        item.execution_id
        for item in ledger.controller_failures
        if item.slot_id == slot_id and item.execution_id is not None
    }
    rows = sorted(
        (
            *(
                (item.ledger_index, item.execution_id)
                for item in ledger.role_observations
                if item.slot_id == slot_id
            ),
            *(
                (item.ledger_index, item.execution_id)
                for item in ledger.attempt_observations
                if item.attempt.slot_id == slot_id
            ),
            *(
                (item.ledger_index, item.execution_id)
                for item in ledger.controller_failures
                if item.slot_id == slot_id and item.execution_id is not None
            ),
        )
    )
    for _, execution_id in rows:
        if execution_id not in execution_ids:
            execution_ids.append(execution_id)
    if execution_ids and execution_ids[-1] not in closed_execution_ids:
        return execution_ids[-1]
    next_number = len(execution_ids) + 1
    return candidate_profile_execution_id(slot_id, next_number)


def _checkpoint_candidate_profile_attempt_ledger(
    ledger: CandidateProfileAttemptLedger,
    *,
    role_observations: tuple[CandidateProfileRoleObservation, ...],
    attempt_observations: tuple[CandidateProfileAttemptObservation, ...],
    controller_failures: tuple[CandidateProfileControllerFailureEvent, ...],
    disposition: Literal["in_progress", "aborted", "complete"],
    finalization_event: CandidateProfileFinalizationEvent | None = None,
) -> CandidateProfileAttemptLedger:
    roles_by_id = {item.observation_id: item for item in role_observations}
    selections: list[CandidateProfileSelection] = []
    for slot in CANDIDATE_PROFILE_SLOT_PLAN:
        eligible = tuple(
            observation
            for observation in attempt_observations
            if observation.attempt.slot_id == slot.slot_id
            and observation.attempt.status is AttemptStatus.SUCCESS
            and _ledger_attempt_output_matches(
                observation.attempt, slot, ledger.execution_identity
            )
            and len(observation.role_observation_ids) == 2
            and all(
                roles_by_id[item].status is AttemptStatus.SUCCESS
                for item in observation.role_observation_ids
            )
        )
        if eligible:
            selected = eligible[-1]
            selections.append(
                CandidateProfileSelection(
                    slot_id=slot.slot_id,
                    selected_observation_id=selected.observation_id,
                    selected_attempt_id=selected.attempt.attempt_id,
                )
            )
    selected_slots = {item.slot_id for item in selections}
    missing_slot_ids = tuple(
        item.slot_id
        for item in CANDIDATE_PROFILE_SLOT_PLAN
        if item.slot_id not in selected_slots
    )
    journal_event_count = (
        len(role_observations)
        + len(attempt_observations)
        + len(controller_failures)
        + int(finalization_event is not None)
    )
    payload = ledger.model_dump(mode="json")
    payload.update(
        disposition=disposition,
        role_observations=[item.model_dump(mode="json") for item in role_observations],
        attempt_observations=[
            item.model_dump(mode="json") for item in attempt_observations
        ],
        controller_failures=[
            item.model_dump(mode="json") for item in controller_failures
        ],
        finalization_event=(
            finalization_event.model_dump(mode="json")
            if finalization_event is not None
            else None
        ),
        selections=[item.model_dump(mode="json") for item in selections],
        missing_slot_ids=list(missing_slot_ids),
        journal_event_count=journal_event_count,
        role_observation_count=len(role_observations),
        attempt_observation_count=len(attempt_observations),
        controller_failure_count=len(controller_failures),
        finalization_event_count=int(finalization_event is not None),
        failed_role_observation_count=sum(
            item.status is not AttemptStatus.SUCCESS for item in role_observations
        ),
        failed_attempt_observation_count=sum(
            item.attempt.status is not AttemptStatus.SUCCESS
            for item in attempt_observations
        ),
        drifted_attempt_observation_count=sum(
            item.attempt.status is AttemptStatus.SUCCESS
            and not _ledger_attempt_output_matches(
                item.attempt,
                _SLOT_BY_ID[item.attempt.slot_id],
                ledger.execution_identity,
            )
            for item in attempt_observations
        ),
        checkpoint_index=ledger.checkpoint_index + 1,
        previous_checkpoint_sha256=ledger.checkpoint_sha256,
    )
    return seal_candidate_profile_attempt_ledger(payload)


def append_role_observation(
    ledger: CandidateProfileAttemptLedger,
    *,
    execution_id: str,
    slot_id: str,
    role: Literal["authoritative_uninstrumented", "diagnostic_instrumented"],
    status: AttemptStatus,
    failure: FailureRecord | None,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    started_monotonic_ns: int,
    ended_monotonic_ns: int,
    worker_evidence: WorkerExecutionEvidence | None,
    snapshots: tuple[ProcessTreeSnapshot, ...],
    watchdog: WorkerWatchdogEvidence | None,
    worker_fatal_envelope: WorkerFatalEnvelope | None = None,
) -> CandidateProfileAttemptLedger:
    """Append and reseal one bounded, content-free twin-role checkpoint."""

    if ledger.disposition != "in_progress":
        raise ValueError("terminal candidate ledger is immutable")
    expected_execution_id = next_candidate_profile_execution_id(ledger, slot_id)
    if execution_id != expected_execution_id:
        raise ValueError("role execution ID is not the active canonical retry")
    ledger_index = ledger.journal_event_count + 1
    observation = CandidateProfileRoleObservation(
        ledger_index=ledger_index,
        observation_id=f"lat-us01-ledger-{ledger_index:04d}-role",
        execution_id=execution_id,
        slot_id=slot_id,
        role=role,
        status=status,
        failure=failure,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        started_monotonic_ns=started_monotonic_ns,
        ended_monotonic_ns=ended_monotonic_ns,
        worker_evidence=worker_evidence,
        snapshots=snapshots,
        watchdog=watchdog,
        worker_fatal_envelope=worker_fatal_envelope,
    )
    return _checkpoint_candidate_profile_attempt_ledger(
        ledger,
        role_observations=(*ledger.role_observations, observation),
        attempt_observations=ledger.attempt_observations,
        controller_failures=ledger.controller_failures,
        disposition="in_progress",
    )


def append_attempt_observation(
    ledger: CandidateProfileAttemptLedger,
    attempt: LatencyAttempt,
) -> CandidateProfileAttemptLedger:
    """Append one closed attempt, deriving its role links and all denominators."""

    if ledger.disposition != "in_progress":
        raise ValueError("terminal candidate ledger is immutable")
    execution_id = attempt.attempt_id
    if execution_id != next_candidate_profile_execution_id(ledger, attempt.slot_id):
        raise ValueError("attempt execution ID is not the active canonical retry")
    role_ids = tuple(
        item.observation_id
        for item in ledger.role_observations
        if item.execution_id == execution_id and item.slot_id == attempt.slot_id
    )
    ledger_index = ledger.journal_event_count + 1
    observation = CandidateProfileAttemptObservation(
        ledger_index=ledger_index,
        observation_id=f"lat-us01-ledger-{ledger_index:04d}-attempt",
        execution_id=execution_id,
        role_observation_ids=role_ids,
        attempt=attempt,
    )
    return _checkpoint_candidate_profile_attempt_ledger(
        ledger,
        role_observations=ledger.role_observations,
        attempt_observations=(*ledger.attempt_observations, observation),
        controller_failures=ledger.controller_failures,
        disposition="in_progress",
    )


def append_controller_failure(
    ledger: CandidateProfileAttemptLedger,
    *,
    event_kind: Literal[
        "controller_exception",
        "controller_keyboard_interrupt",
        "controller_hard_death_recovered",
        "evidence_serialization_error",
    ],
    slot_id: str | None,
    execution_id: str | None,
    status: Literal[
        AttemptStatus.ERROR,
        AttemptStatus.CANCELLED,
        AttemptStatus.TIMEOUT,
    ],
    failure_code: FailureCode,
    failure_type: FailureType,
    observed_at_utc: datetime,
    observed_monotonic_ns: int,
) -> CandidateProfileAttemptLedger:
    """Append a closed controller failure when no LatencyAttempt can be formed."""

    if ledger.disposition != "in_progress":
        raise ValueError("terminal candidate ledger is immutable")
    if slot_id is not None and execution_id != next_candidate_profile_execution_id(
        ledger, slot_id
    ):
        raise ValueError("controller execution ID is not the active canonical retry")
    ledger_index = ledger.journal_event_count + 1
    event = CandidateProfileControllerFailureEvent(
        ledger_index=ledger_index,
        event_id=f"lat-us01-ledger-{ledger_index:04d}-controller",
        event_kind=event_kind,
        slot_id=slot_id,
        execution_id=execution_id,
        status=status,
        failure_code=failure_code,
        failure_type=failure_type,
        observed_at_utc=observed_at_utc,
        observed_monotonic_ns=observed_monotonic_ns,
    )
    return _checkpoint_candidate_profile_attempt_ledger(
        ledger,
        role_observations=ledger.role_observations,
        attempt_observations=ledger.attempt_observations,
        controller_failures=(*ledger.controller_failures, event),
        disposition="in_progress",
    )


def finalize_ledger(
    ledger: CandidateProfileAttemptLedger,
    *,
    finalized_at_utc: datetime,
    finalized_monotonic_ns: int,
) -> CandidateProfileAttemptLedger:
    """Close the ledger as complete, or aborted when an eligible slot is absent."""

    if ledger.disposition != "in_progress":
        raise ValueError("terminal candidate ledger is immutable")
    disposition: Literal["aborted", "complete"] = (
        "aborted" if ledger.missing_slot_ids else "complete"
    )
    ledger_index = ledger.journal_event_count + 1
    finalization_event = CandidateProfileFinalizationEvent(
        ledger_index=ledger_index,
        event_id=f"lat-us01-ledger-{ledger_index:04d}-finalize",
        disposition=disposition,
        missing_slot_ids=ledger.missing_slot_ids,
        finalized_at_utc=finalized_at_utc,
        finalized_monotonic_ns=finalized_monotonic_ns,
    )
    return _checkpoint_candidate_profile_attempt_ledger(
        ledger,
        role_observations=ledger.role_observations,
        attempt_observations=ledger.attempt_observations,
        controller_failures=ledger.controller_failures,
        disposition=disposition,
        finalization_event=finalization_event,
    )


class CandidateProfileCase(ContractModel):
    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    source: SourceIdentity
    source_custody: Literal["public-redistributable"]
    m0_case_hwm_bytes: Annotated[int, Field(strict=True, gt=0)]
    p00_semantic_json_sha256: Sha256
    p00_markdown_sha256: Sha256
    p00_markdown_size_bytes: Annotated[int, Field(strict=True, gt=0)]
    current_runtime_semantic_json_sha256: Sha256
    current_runtime_markdown_sha256: Sha256
    current_runtime_markdown_size_bytes: Annotated[int, Field(strict=True, gt=0)]
    cold_json: LatencyAttempt
    prewarmed_json: LatencyAttempt
    cold_markdown: LatencyAttempt

    @model_validator(mode="after")
    def validate_case_layout(self) -> CandidateProfileCase:
        if self.case_id not in SOURCE_CUSTODY:
            raise ValueError("profile case is outside the frozen corpus")
        sha256, size_bytes, page_count = SOURCE_CUSTODY[self.case_id]
        expected_source = SourceIdentity(
            case_id=self.case_id,
            path=f"benchmark-expertmodeldata/{self.case_id}.pdf",
            filename=f"{self.case_id}.pdf",
            sha256=sha256,
            size_bytes=size_bytes,
            page_count=page_count,
        )
        if self.source != expected_source:
            raise ValueError("profile source custody differs")
        if self.m0_case_hwm_bytes != M0_CASE_HWM_BYTES[self.case_id]:
            raise ValueError("profile M0 case HWM differs")
        if (
            self.p00_semantic_json_sha256,
            self.p00_markdown_sha256,
            self.p00_markdown_size_bytes,
        ) != P00_OUTPUT_IDENTITIES[self.case_id]:
            raise ValueError("profile P00 output custody differs")
        if (
            self.current_runtime_semantic_json_sha256,
            self.current_runtime_markdown_sha256,
            self.current_runtime_markdown_size_bytes,
        ) != CURRENT_RUNTIME_OUTPUT_IDENTITIES[self.case_id]:
            raise ValueError("profile current-runtime output custody differs")
        case_index = CASE_ORDER.index(self.case_id)
        attempts = (
            (
                self.cold_json,
                "cold-json",
                3 * case_index + 1,
                WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD,
                OutputFormat.JSON,
            ),
            (
                self.prewarmed_json,
                "prewarmed-json",
                3 * case_index + 2,
                WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED,
                OutputFormat.JSON,
            ),
            (
                self.cold_markdown,
                "cold-markdown",
                3 * case_index + 3,
                WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD,
                OutputFormat.MARKDOWN,
            ),
        )
        for attempt, label, order_index, lifecycle, output_format in attempts:
            slot_id = f"{self.case_id}-{label}"
            if (
                _candidate_profile_execution_number(attempt.attempt_id, slot_id=slot_id)
                is None
                or attempt.slot_id != slot_id
                or attempt.order_index != order_index
                or attempt.case_id != self.case_id
                or attempt.pair_index != 1
                or attempt.system is not SystemName.CANDIDATE
                or attempt.source != self.source
                or attempt.configuration.worker_lifecycle is not lifecycle
                or attempt.configuration.output_format is not output_format
                or attempt.configuration.bounded_concurrency != 1
            ):
                raise ValueError(f"{label} attempt identity/profile differs")
        return self


class ConcurrentWorkerInterval(ContractModel):
    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    attempt_id: Annotated[str, Field(min_length=1, max_length=128)]
    slot_id: Annotated[str, Field(min_length=1, max_length=128)]
    worker_group_id: Annotated[int, Field(strict=True, gt=0)]
    worker_create_time_ns: Annotated[int, Field(strict=True, gt=0)]
    request_started_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]
    request_ended_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def validate_interval(self) -> ConcurrentWorkerInterval:
        if self.request_ended_monotonic_ns <= self.request_started_monotonic_ns:
            raise ValueError("concurrent worker interval must be positive")
        return self


class ActiveSlotEvent(ContractModel):
    observed_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]
    event: Literal["start", "end"]
    slot_id: Annotated[str, Field(min_length=1, max_length=128)]
    active_slot_ids: Annotated[tuple[str, ...], Field(max_length=2)]


class ConcurrentWorkerGroupMetric(ContractModel):
    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    attempt_id: Annotated[str, Field(min_length=1, max_length=128)]
    slot_id: Annotated[str, Field(min_length=1, max_length=128)]
    worker_group_id: Annotated[int, Field(strict=True, gt=0)]
    worker_create_time_ns: Annotated[int, Field(strict=True, gt=0)]
    sampled_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]
    rss_bytes: Annotated[int, Field(strict=True, gt=0)]
    cumulative_cpu_ns: Annotated[int, Field(strict=True, ge=0)]


class ConcurrentAggregateSnapshot(ContractModel):
    aggregation_basis: Literal["bounded-skew-sequential-process-tree-sweep-v1"]
    sweep_started_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]
    sweep_ended_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    observed_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]
    groups: Annotated[
        tuple[ConcurrentWorkerGroupMetric, ...], Field(min_length=1, max_length=2)
    ]
    aggregate_rss_bytes: Annotated[int, Field(strict=True, gt=0)]
    aggregate_cpu_ns: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="after")
    def recompute_aggregate(self) -> ConcurrentAggregateSnapshot:
        if (
            self.observed_monotonic_ns != self.sweep_ended_monotonic_ns
            or not 0
            < self.sweep_ended_monotonic_ns - self.sweep_started_monotonic_ns
            <= CONCURRENT_SWEEP_MAXIMUM_DURATION_NS
        ):
            raise ValueError("concurrent aggregate sweep boundary is invalid")
        keys = tuple(
            (item.worker_group_id, item.worker_create_time_ns) for item in self.groups
        )
        if len(keys) != len(set(keys)):
            raise ValueError("concurrent snapshot group identities must be unique")
        sampled_at = tuple(item.sampled_monotonic_ns for item in self.groups)
        if any(
            current <= previous for previous, current in pairwise(sampled_at)
        ) or any(
            not self.sweep_started_monotonic_ns <= item <= self.sweep_ended_monotonic_ns
            for item in sampled_at
        ):
            raise ValueError("concurrent group sample timing is non-canonical")
        if self.aggregate_rss_bytes != sum(item.rss_bytes for item in self.groups):
            raise ValueError("concurrent aggregate RSS must be recomputed")
        if self.aggregate_cpu_ns != sum(item.cumulative_cpu_ns for item in self.groups):
            raise ValueError("concurrent aggregate CPU must be recomputed")
        return self


class ConcurrentRoundEvidence(ContractModel):
    role: Literal["authoritative_uninstrumented", "diagnostic_instrumented"]
    round_index: Literal[1, 2]
    barrier_id: Annotated[str, Field(min_length=1, max_length=128)]
    controller_started_monotonic_ns: Annotated[int, Field(strict=True, ge=0)]
    controller_ended_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    worker_intervals: Annotated[
        tuple[ConcurrentWorkerInterval, ...], Field(min_length=2, max_length=2)
    ]
    active_slot_ledger: Annotated[
        tuple[ActiveSlotEvent, ...], Field(min_length=4, max_length=4)
    ]
    maximum_occupancy: Literal[2]
    overlap_ns: Annotated[int, Field(strict=True, gt=0)]
    worker_group_count: Literal[2]
    bounded_skew_snapshots: Annotated[
        tuple[ConcurrentAggregateSnapshot, ...], Field(min_length=1, max_length=8_192)
    ]
    sampling_interval_target_ns: Literal[50_000_000]
    hard_maximum_gap_ns: Literal[250_000_000]
    maximum_observed_gap_ns: Annotated[int, Field(strict=True, ge=0)]
    peak_bounded_skew_aggregate_rss_bytes: Annotated[int, Field(strict=True, gt=0)]
    exact_aggregate_cpu_ns: Annotated[int, Field(strict=True, ge=0)]
    conservative_aggregate_cpu_ns: Annotated[int, Field(strict=True, ge=0)]
    all_groups_reaped: Literal[True]

    @model_validator(mode="after")
    def validate_round(self) -> ConcurrentRoundEvidence:
        if self.controller_ended_monotonic_ns <= self.controller_started_monotonic_ns:
            raise ValueError("concurrent controller interval must be positive")
        if (
            tuple(item.case_id for item in self.worker_intervals)
            != CONCURRENT_CASE_ORDER
        ):
            raise ValueError("concurrent worker interval order differs")
        identities = tuple(
            (item.worker_group_id, item.worker_create_time_ns)
            for item in self.worker_intervals
        )
        if len(set(identities)) != 2:
            raise ValueError("concurrent round must retain two exact worker groups")
        for item in self.worker_intervals:
            if not (
                self.controller_started_monotonic_ns
                <= item.request_started_monotonic_ns
                < item.request_ended_monotonic_ns
                <= self.controller_ended_monotonic_ns
            ):
                raise ValueError("worker interval escaped concurrent controller window")
        overlap_start = max(
            item.request_started_monotonic_ns for item in self.worker_intervals
        )
        overlap_end = min(
            item.request_ended_monotonic_ns for item in self.worker_intervals
        )
        if self.overlap_ns != overlap_end - overlap_start or self.overlap_ns <= 0:
            raise ValueError("concurrent overlap must be positive and recomputed")

        events = self.active_slot_ledger
        if any(
            current.observed_monotonic_ns <= previous.observed_monotonic_ns
            for previous, current in pairwise(events)
        ):
            raise ValueError("active-slot ledger timestamps must increase")
        allowed_slots = {item.slot_id for item in self.worker_intervals}
        active: set[str] = set()
        observed_maximum = 0
        for event in events:
            if event.slot_id not in allowed_slots:
                raise ValueError("active-slot ledger contains an unknown slot")
            if event.event == "start":
                if event.slot_id in active:
                    raise ValueError("active-slot ledger double-started a slot")
                active.add(event.slot_id)
            else:
                if event.slot_id not in active:
                    raise ValueError("active-slot ledger ended an inactive slot")
                active.remove(event.slot_id)
            if event.active_slot_ids != tuple(sorted(active)):
                raise ValueError("active-slot ledger state must be recomputed")
            observed_maximum = max(observed_maximum, len(active))
        if active or observed_maximum != self.maximum_occupancy:
            raise ValueError("active-slot ledger must close after occupancy two")

        snapshots = self.bounded_skew_snapshots
        if any(
            current.observed_monotonic_ns <= previous.observed_monotonic_ns
            for previous, current in pairwise(snapshots)
        ):
            raise ValueError("concurrent snapshot timestamps must increase")
        interval_by_slot = {item.slot_id: item for item in self.worker_intervals}
        bounded_skew: list[ConcurrentAggregateSnapshot] = []
        for snapshot in snapshots:
            if not (
                self.controller_started_monotonic_ns
                <= snapshot.sweep_started_monotonic_ns
                < snapshot.sweep_ended_monotonic_ns
                <= self.controller_ended_monotonic_ns
            ):
                raise ValueError("concurrent sweep escaped controller window")
            if tuple(item.case_id for item in snapshot.groups) != tuple(
                case_id
                for case_id in CONCURRENT_CASE_ORDER
                if any(group.case_id == case_id for group in snapshot.groups)
            ):
                raise ValueError("concurrent snapshot group order differs")
            for group in snapshot.groups:
                interval = interval_by_slot.get(group.slot_id)
                if interval is None or (
                    group.case_id,
                    group.attempt_id,
                    group.worker_group_id,
                    group.worker_create_time_ns,
                ) != (
                    interval.case_id,
                    interval.attempt_id,
                    interval.worker_group_id,
                    interval.worker_create_time_ns,
                ):
                    raise ValueError("concurrent snapshot exact group identity differs")
                if not (
                    interval.request_started_monotonic_ns
                    <= group.sampled_monotonic_ns
                    <= interval.request_ended_monotonic_ns
                ):
                    raise ValueError("concurrent group sampled outside its request")
            if (
                len(snapshot.groups) == 2
                and overlap_start <= snapshot.sweep_started_monotonic_ns
                and snapshot.sweep_ended_monotonic_ns <= overlap_end
            ):
                bounded_skew.append(snapshot)
        if not bounded_skew or self.peak_bounded_skew_aggregate_rss_bytes != max(
            item.aggregate_rss_bytes for item in bounded_skew
        ):
            raise ValueError("bounded-skew aggregate RSS peak must be recomputed")
        bounded_skew_times = tuple(item.observed_monotonic_ns for item in bounded_skew)
        cadence_gaps = (
            bounded_skew_times[0] - overlap_start,
            *(current - previous for previous, current in pairwise(bounded_skew_times)),
            overlap_end - bounded_skew_times[-1],
        )
        if any(item < 0 for item in cadence_gaps) or (
            self.maximum_observed_gap_ns != max(cadence_gaps)
            or self.maximum_observed_gap_ns > self.hard_maximum_gap_ns
        ):
            raise ValueError(
                "concurrent sampling cadence must be recomputed and bounded"
            )
        if self.conservative_aggregate_cpu_ns < self.exact_aggregate_cpu_ns:
            raise ValueError("conservative concurrent CPU cannot be below exact CPU")
        return self


class ConcurrentBatchEvidence(ContractModel):
    schema_id: Literal["phase-latency-concurrent-batch-v1"]
    batch_id: Literal["lat-us01-ny-uber-bound2-cold-json"]
    bounded_concurrency: Literal[2]
    ordered_attempts: Annotated[
        tuple[LatencyAttempt, ...], Field(min_length=2, max_length=2)
    ]
    authoritative_round: ConcurrentRoundEvidence
    diagnostic_round: ConcurrentRoundEvidence
    controller_thread_count_before: Annotated[int, Field(strict=True, gt=0)]
    controller_thread_count_after: Annotated[int, Field(strict=True, gt=0)]
    controller_fd_count_before: Annotated[int, Field(strict=True, ge=0)]
    controller_fd_count_after: Annotated[int, Field(strict=True, ge=0)]
    hosted_calls: Literal[0]
    hosted_credits: Literal[0]
    prompt_tokens: Literal[0]
    completion_tokens: Literal[0]
    billed_cost_microusd: Literal[0]
    egress_bytes: Literal[0]

    @model_validator(mode="after")
    def validate_batch(self) -> ConcurrentBatchEvidence:
        if (
            tuple(item.case_id for item in self.ordered_attempts)
            != CONCURRENT_CASE_ORDER
        ):
            raise ValueError("concurrent batch case order differs")
        for offset, attempt in enumerate(self.ordered_attempts, start=46):
            slot_id = f"{attempt.case_id}-bound2-cold-json"
            if (
                _candidate_profile_execution_number(attempt.attempt_id, slot_id=slot_id)
                is None
                or attempt.slot_id != slot_id
                or attempt.order_index != offset
                or attempt.pair_index != 1
                or attempt.system is not SystemName.CANDIDATE
                or attempt.configuration.bounded_concurrency != 2
                or attempt.configuration.worker_lifecycle
                is not WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD
                or attempt.configuration.output_format is not OutputFormat.JSON
            ):
                raise ValueError("concurrent attempt identity/profile differs")
        if (
            self.authoritative_round.role != "authoritative_uninstrumented"
            or self.authoritative_round.round_index != 1
            or self.authoritative_round.barrier_id
            != "lat-us01-bound2-authoritative-barrier"
            or self.diagnostic_round.role != "diagnostic_instrumented"
            or self.diagnostic_round.round_index != 2
            or self.diagnostic_round.barrier_id != "lat-us01-bound2-diagnostic-barrier"
        ):
            raise ValueError("concurrent rounds must be role-homogeneous and ordered")
        if self.authoritative_round.barrier_id == self.diagnostic_round.barrier_id:
            raise ValueError("concurrent round barriers must be distinct")
        if (
            self.controller_thread_count_before != self.controller_thread_count_after
            or self.controller_fd_count_before != self.controller_fd_count_after
        ):
            raise ValueError("controller threads/file descriptors were not restored")
        for round_evidence, diagnostic in (
            (self.authoritative_round, False),
            (self.diagnostic_round, True),
        ):
            for interval, attempt in zip(
                round_evidence.worker_intervals, self.ordered_attempts, strict=True
            ):
                tree = (
                    attempt.diagnostic_process_tree
                    if diagnostic
                    else attempt.process_tree
                )
                if tree is None or (
                    interval.case_id,
                    interval.attempt_id,
                    interval.slot_id,
                    interval.request_started_monotonic_ns,
                    interval.request_ended_monotonic_ns,
                ) != (
                    attempt.case_id,
                    attempt.attempt_id,
                    attempt.slot_id,
                    tree.request_started_monotonic_ns,
                    tree.request_ended_monotonic_ns,
                ):
                    raise ValueError(
                        "concurrent round interval/attempt evidence differs"
                    )
                root = tree.snapshots[0].members[0].identity
                if (
                    interval.worker_group_id != root.pid
                    or interval.worker_create_time_ns != root.create_time_ns
                ):
                    raise ValueError(
                        "concurrent interval/root process identity differs"
                    )
            trees = tuple(
                attempt.diagnostic_process_tree if diagnostic else attempt.process_tree
                for attempt in self.ordered_attempts
            )
            exact_cpu = sum(
                tree.exact_worker_self_cpu_ns
                + tree.exact_reaped_children_cpu_ns
                + tree.conservative_frozen_response_boundary_descendant_cpu_ns
                for tree in trees
                if tree is not None
            )
            conservative_cpu = sum(
                max(
                    tree.maximum_observed_process_cpu_ns,
                    tree.exact_worker_self_cpu_ns
                    + tree.exact_reaped_children_cpu_ns
                    + tree.conservative_frozen_response_boundary_descendant_cpu_ns,
                )
                for tree in trees
                if tree is not None
            )
            if (
                round_evidence.exact_aggregate_cpu_ns != exact_cpu
                or round_evidence.conservative_aggregate_cpu_ns != conservative_cpu
            ):
                raise ValueError("concurrent exact/conservative CPU must be recomputed")
        return self


class CandidateProfileSet(ContractModel):
    schema_id: Literal["phase-latency-candidate-profile-set-v1"]
    schema_version: Literal["1.0"]
    profile_set_id: Literal["lat-us01-all-15-profile-v1"]
    identity: CandidateExecutionIdentity
    attempt_ledger: CandidateProfileAttemptLedger
    quality: P00QualityEvidence
    cases: Annotated[
        tuple[CandidateProfileCase, ...], Field(min_length=15, max_length=15)
    ]
    concurrent_batch: ConcurrentBatchEvidence
    production_instrumentation_enabled: Literal[False]
    production_feature_flag: None
    rollback_disposition: Literal["stop-disposable-benchmark-workers"]
    cache_policy: Literal["content-result-cache-disabled-filesystem-cache-uncontrolled"]
    failure_retention_policy: Literal["retain-every-attempt-no-aggregate-masking-v1"]
    environment_comparable: Literal[False]
    hosted_calls: Literal[0]
    hosted_credits: Literal[0]
    prompt_tokens: Literal[0]
    completion_tokens: Literal[0]
    billed_cost_microusd: Literal[0]
    egress_bytes: Literal[0]

    @model_validator(mode="after")
    def validate_profile_set(self) -> CandidateProfileSet:
        if tuple(item.case_id for item in self.cases) != CASE_ORDER:
            raise ValueError("profile set must retain exact all-15 order")
        if self.environment_comparable != self.identity.environment_comparable:
            raise ValueError("environment comparability disposition differs")
        if any(
            item is None
            for item in (
                self.identity.current_runtime_run_record,
                self.identity.current_runtime_semantic_report,
                self.identity.current_runtime_semantic_report_markdown,
            )
        ):
            raise ValueError("final profile requires current-runtime baseline custody")
        attempts = (
            tuple(
                attempt
                for case in self.cases
                for attempt in (case.cold_json, case.prewarmed_json, case.cold_markdown)
            )
            + self.concurrent_batch.ordered_attempts
        )
        if len(attempts) != 47:
            raise ValueError("profile set must retain exactly 47 candidate attempts")
        if (
            len({item.attempt_id for item in attempts}) != 47
            or len({item.slot_id for item in attempts}) != 47
        ):
            raise ValueError("profile attempt/slot IDs must be globally unique")
        if tuple(item.order_index for item in attempts) != tuple(range(1, 48)):
            raise ValueError("profile attempt order indices must be exact")
        identity = self.identity
        ledger = self.attempt_ledger
        if (
            ledger.disposition != "complete"
            or ledger.execution_identity != identity
            or ledger.missing_slot_ids
            or len(ledger.selections) != 47
        ):
            raise ValueError("complete profile requires the complete retained ledger")
        observations_by_id = {
            item.observation_id: item for item in ledger.attempt_observations
        }
        selected_by_slot: dict[str, LatencyAttempt] = {}
        for selection in ledger.selections:
            observation = observations_by_id.get(selection.selected_observation_id)
            if observation is None:
                raise ValueError("profile selection is absent from retained ledger")
            selected_by_slot[selection.slot_id] = observation.attempt
        if (
            tuple(
                selected_by_slot.get(item.slot_id)
                for item in CANDIDATE_PROFILE_SLOT_PLAN
            )
            != attempts
        ):
            raise ValueError("profile attempts must equal retained ledger selections")
        for attempt in attempts:
            expected_worker_environment_sha256 = (
                identity.environment_manifest.sanitized_worker_environment_sha256
            )
            if (
                attempt.candidate_code_sha256 != identity.candidate_code_sha256
                or attempt.dependency_lock_sha256 != identity.dependency_manifest_sha256
                or attempt.environment_sha256
                != identity.environment_manifest.manifest_sha256
                or attempt.model_artifacts_sha256 != identity.model_artifacts_sha256
                or attempt.cache_hit is not False
                or attempt.configuration.cache_disabled is not True
                or attempt.provider_total_latency is not None
                or attempt.legacy_v1_authorization is not None
                or attempt.authoritative_network_isolation is None
                or attempt.diagnostic_network_isolation is None
                or attempt.authoritative_network_isolation.policy
                != "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
                or attempt.diagnostic_network_isolation.policy
                != "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
                or attempt.authoritative_network_isolation.worker_environment_sha256
                != expected_worker_environment_sha256
                or attempt.diagnostic_network_isolation.worker_environment_sha256
                != expected_worker_environment_sha256
                or attempt.authoritative_response_boundary_protocol
                != "controller-response-freeze-and-post-response-resource-closure-v2"
                or attempt.diagnostic_response_boundary_protocol
                != "controller-response-freeze-and-post-response-resource-closure-v2"
            ):
                raise ValueError(
                    "profile attempt execution identity/cache/provider policy differs"
                )
            if attempt.instrumentation_manifest is not None and (
                attempt.instrumentation_manifest.harness_files
                != tuple(
                    item
                    for item in identity.harness_files
                    if item.path in OBSERVER_HARNESS_PATHS
                )
            ):
                raise ValueError(
                    "attempt harness identities differ from profile custody"
                )
        expected_zero_drift = not ledger.has_blocking_observation and all(
            attempt_output_matches_current_runtime(
                attempt, _SLOT_BY_ID[attempt.slot_id]
            )
            for attempt in attempts
        )
        if self.quality.zero_unexplained_drift is not expected_zero_drift:
            raise ValueError(
                "candidate zero-drift claim must derive from retained ledger"
            )
        return self


class CandidateProfileEvaluation(ContractModel):
    schema_id: Literal["phase-latency-profile-evaluation-v1"]
    profile_set_sha256: Sha256
    attempt_count: Annotated[int, Field(strict=True, ge=47, le=752)]
    selected_attempt_count: Literal[47]
    success_count: Annotated[int, Field(strict=True, ge=0, le=752)]
    failure_count: Annotated[int, Field(strict=True, ge=0, le=752)]
    controller_failure_count: Annotated[int, Field(strict=True, ge=0, le=752)]
    failed_role_observation_count: Annotated[int, Field(strict=True, ge=0, le=1_504)]
    cold_authoritative_hwm_p50_bytes: Annotated[int, Field(strict=True, gt=0)]
    cold_authoritative_hwm_maximum_bytes: Annotated[int, Field(strict=True, gt=0)]
    maximum_worker_hwm_bytes: Annotated[int, Field(strict=True, gt=0)]
    maximum_diagnostic_authoritative_delta_bytes: Annotated[int, Field(strict=True)]
    concurrent_peak_aggregate_rss_bytes: Annotated[int, Field(strict=True, gt=0)]
    failure_codes: Annotated[tuple[str, ...], Field(max_length=16)]
    passed: StrictBool

    @field_validator("failure_codes")
    @classmethod
    def validate_failure_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("profile failure codes must be unique and sorted")
        allowed = {
            "attempt_failed",
            "cache_or_network_policy_failed",
            "cold_hwm_maximum_exceeded",
            "cold_hwm_p50_exceeded",
            "concurrent_cpu_capacity_exceeded",
            "concurrent_rss_exceeded",
            "controller_failure_retained",
            "diagnostic_hwm_delta_exceeded",
            "evidence_incomplete",
            "harness_identity_incomplete",
            "output_identity_drift",
            "per_case_hwm_exceeded",
            "protocol_v2_required",
            "resource_cpu_sanity_failed",
            "role_observation_failed",
        }
        if set(value) - allowed:
            raise ValueError("profile failure code is outside the closed vocabulary")
        return value

    @model_validator(mode="after")
    def bind_disposition(self) -> CandidateProfileEvaluation:
        if self.success_count + self.failure_count != self.attempt_count:
            raise ValueError("profile success/failure denominator differs")
        if self.passed != (not self.failure_codes):
            raise ValueError("profile pass disposition must derive from failures")
        return self


def _nearest_rank_p50(values: tuple[int, ...]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) + 1) // 2 - 1]


def _tree_is_complete_and_sane(
    tree: ProcessTreeMetrics | None, *, logical_cpu_count: int
) -> bool:
    if tree is None or tree.resource_boundary_complete is not True:
        return False
    if tree.response_boundary_snapshot is None:
        return False
    observed_roles = tuple(
        member.identity.role for member in tree.response_boundary_snapshot.members[1:]
    )
    tracker_present = observed_roles == (ProcessRole.RESOURCE_TRACKER,)
    if (
        tree.cleanup_disposition != "external_worker_reaped"
        or tree.worker_reaped is not True
        or tree.observed_descendants_reaped is not True
        or tree.resource_boundary_basis
        != "response-boundary-plus-post-response-reaped-lifecycle-v2"
        or tree.response_boundary_snapshot is None
        or tree.response_boundary_snapshot_index is None
        or tree.resource_closure_snapshot is None
        or tree.worker_reported_hwm_bytes_at_response_boundary is None
        or tree.peak_worker_hwm_bytes
        < tree.worker_reported_hwm_bytes_at_response_boundary
        or len(tree.resource_closure_snapshot.members) != 1
        or tree.resource_closure_complete is not True
        or tree.resource_tracker_freeze_disposition is None
        or tree.response_boundary_descendant_count != len(observed_roles)
        or tree.response_boundary_descendant_roles != observed_roles
        or (
            tracker_present
            and (
                tree.response_boundary_descendant_count != 1
                or tree.resource_tracker_freeze_disposition
                != "controller-sigstop-snapshot-sigcont-v1"
                or tree.resource_tracker_command_fd is None
                or tree.resource_tracker_worker_write_fd is None
                or tree.resource_tracker_command_fd
                == tree.resource_tracker_worker_write_fd
                or tree.resource_tracker_stopped_state_verified is not True
                or tree.resource_tracker_resumed_state_verified is not True
            )
        )
        or (
            not tracker_present
            and (
                tree.response_boundary_descendant_count != 0
                or observed_roles != ()
                or tree.resource_tracker_freeze_disposition != "not_required_root_only"
                or tree.resource_tracker_command_fd is not None
                or tree.resource_tracker_worker_write_fd is not None
                or tree.resource_tracker_stopped_state_verified is not None
                or tree.resource_tracker_resumed_state_verified is not None
            )
        )
    ):
        return False
    exact_cpu = (
        tree.exact_worker_self_cpu_ns
        + tree.exact_reaped_children_cpu_ns
        + tree.conservative_frozen_response_boundary_descendant_cpu_ns
    )
    wall_ns = tree.request_ended_monotonic_ns - tree.request_started_monotonic_ns
    return max(tree.maximum_observed_process_cpu_ns, exact_cpu) <= (
        wall_ns * logical_cpu_count
    )


def evaluate_candidate_profile_set(
    profile_set: CandidateProfileSet,
) -> CandidateProfileEvaluation:
    """Evaluate every predeclared LAT-US01 non-latency/profile gate."""

    selected_attempts = (
        tuple(
            attempt
            for case in profile_set.cases
            for attempt in (case.cold_json, case.prewarmed_json, case.cold_markdown)
        )
        + profile_set.concurrent_batch.ordered_attempts
    )
    ledger = profile_set.attempt_ledger
    selected_by_slot = {item.slot_id: item for item in selected_attempts}
    selected_observation_ids = {
        item.selected_observation_id: item.slot_id for item in ledger.selections
    }
    attempts = tuple(
        selected_by_slot[selected_observation_ids[item.observation_id]]
        if item.observation_id in selected_observation_ids
        else item.attempt
        for item in ledger.attempt_observations
    )
    failures: set[str] = set()
    success_count = sum(item.status is AttemptStatus.SUCCESS for item in attempts)
    if success_count != len(attempts):
        failures.add("attempt_failed")
    if ledger.controller_failure_count:
        failures.add("controller_failure_retained")
    if ledger.failed_role_observation_count:
        failures.add("role_observation_failed")

    logical_cpu_count = profile_set.identity.environment_manifest.logical_cpu_count
    expected_worker_environment_sha256 = (
        profile_set.identity.environment_manifest.sanitized_worker_environment_sha256
    )
    worker_hwms: list[int] = []
    deltas: list[int] = []
    for attempt in attempts:
        if (
            attempt.status is not AttemptStatus.SUCCESS
            or attempt.evidence_complete is not True
            or attempt.process_tree is None
            or attempt.diagnostic_process_tree is None
        ):
            failures.add("evidence_incomplete")
            continue
        if not _tree_is_complete_and_sane(
            attempt.process_tree, logical_cpu_count=logical_cpu_count
        ) or not _tree_is_complete_and_sane(
            attempt.diagnostic_process_tree, logical_cpu_count=logical_cpu_count
        ):
            failures.add("resource_cpu_sanity_failed")
        authoritative_hwm = attempt.process_tree.peak_worker_hwm_bytes
        diagnostic_hwm = attempt.diagnostic_process_tree.peak_worker_hwm_bytes
        worker_hwms.extend((authoritative_hwm, diagnostic_hwm))
        delta = diagnostic_hwm - authoritative_hwm
        deltas.append(delta)
        cap = M0_CASE_HWM_BYTES[attempt.case_id] + PER_WORKER_DELTA_BYTES
        if authoritative_hwm > cap or diagnostic_hwm > cap:
            failures.add("per_case_hwm_exceeded")
        if delta > PER_WORKER_DELTA_BYTES:
            failures.add("diagnostic_hwm_delta_exceeded")
        if (
            attempt.instrumentation_manifest is None
            or attempt.instrumentation_manifest.harness_files
            != tuple(
                item
                for item in profile_set.identity.harness_files
                if item.path in OBSERVER_HARNESS_PATHS
            )
        ):
            failures.add("harness_identity_incomplete")
        if (
            attempt.authoritative_network_isolation is None
            or attempt.diagnostic_network_isolation is None
            or attempt.authoritative_network_isolation.hosted_calls_completed != 0
            or attempt.diagnostic_network_isolation.hosted_calls_completed != 0
            or attempt.cache_hit is not False
            or attempt.legacy_v1_authorization is not None
            or attempt.authoritative_network_isolation.policy
            != "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
            or attempt.diagnostic_network_isolation.policy
            != "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
            or attempt.authoritative_network_isolation.worker_environment_sha256
            != expected_worker_environment_sha256
            or attempt.diagnostic_network_isolation.worker_environment_sha256
            != expected_worker_environment_sha256
        ):
            failures.add("cache_or_network_policy_failed")
        if (
            attempt.authoritative_response_boundary_protocol
            != "controller-response-freeze-and-post-response-resource-closure-v2"
            or attempt.diagnostic_response_boundary_protocol
            != "controller-response-freeze-and-post-response-resource-closure-v2"
            or attempt.authoritative_resource_tracker_disposition is None
            or attempt.diagnostic_resource_tracker_disposition is None
            or attempt.authoritative_resource_tracker_disposition.controller_no_relaunch_through_zero_exit_verified
            is not True
            or attempt.diagnostic_resource_tracker_disposition.controller_no_relaunch_through_zero_exit_verified
            is not True
            or attempt.authoritative_network_isolation is None
            or attempt.diagnostic_network_isolation is None
            or attempt.authoritative_network_isolation.python_guard_restore_disposition
            != "controller-verified-worker-zero-exit"
            or attempt.diagnostic_network_isolation.python_guard_restore_disposition
            != "controller-verified-worker-zero-exit"
        ):
            failures.add("protocol_v2_required")
        if not attempt_output_matches_current_runtime(
            attempt, _SLOT_BY_ID[attempt.slot_id]
        ):
            failures.add("output_identity_drift")
        if attempt.configuration.worker_lifecycle is (
            WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED
        ):
            cache_states = (
                attempt.authoritative_cache_state,
                attempt.diagnostic_cache_state,
            )
            if any(
                state is None
                or state.profile != "request_prewarmed_after_app_startup"
                or state.prewarm_evidence is None
                or state.prewarm_evidence.source.sha256 == attempt.source.sha256
                or state.prewarm_evidence.content_result_cache_observed is not False
                for state in cache_states
            ):
                failures.add("cache_or_network_policy_failed")

    for case in profile_set.cases:
        prewarmed = case.prewarmed_json
        cache_states = (
            prewarmed.authoritative_cache_state,
            prewarmed.diagnostic_cache_state,
        )
        if any(
            state is None
            or state.profile != "request_prewarmed_after_app_startup"
            or state.prewarm_evidence is None
            or state.prewarm_evidence.source.sha256 == case.source.sha256
            or state.prewarm_evidence.content_result_cache_observed is not False
            for state in cache_states
        ):
            failures.add("cache_or_network_policy_failed")

    cold_hwms = tuple(
        case.cold_json.process_tree.peak_worker_hwm_bytes
        for case in profile_set.cases
        if case.cold_json.process_tree is not None
    )
    cold_p50 = _nearest_rank_p50(cold_hwms) if cold_hwms else 1
    cold_maximum = max(cold_hwms, default=1)
    if len(cold_hwms) != 15:
        failures.add("evidence_incomplete")
    if cold_p50 > COLD_HWM_P50_CEILING_BYTES:
        failures.add("cold_hwm_p50_exceeded")
    if cold_maximum > COLD_HWM_MAXIMUM_CEILING_BYTES:
        failures.add("cold_hwm_maximum_exceeded")

    concurrent_peak = max(
        profile_set.concurrent_batch.authoritative_round.peak_bounded_skew_aggregate_rss_bytes,
        profile_set.concurrent_batch.diagnostic_round.peak_bounded_skew_aggregate_rss_bytes,
    )
    if concurrent_peak > CONCURRENT_AGGREGATE_RSS_CEILING_BYTES:
        failures.add("concurrent_rss_exceeded")
    for round_evidence in (
        profile_set.concurrent_batch.authoritative_round,
        profile_set.concurrent_batch.diagnostic_round,
    ):
        request_active_union_ns = max(
            item.request_ended_monotonic_ns for item in round_evidence.worker_intervals
        ) - min(
            item.request_started_monotonic_ns
            for item in round_evidence.worker_intervals
        )
        if round_evidence.conservative_aggregate_cpu_ns > (
            request_active_union_ns * logical_cpu_count
        ):
            failures.add("concurrent_cpu_capacity_exceeded")

    return CandidateProfileEvaluation(
        schema_id=PROFILE_EVALUATION_SCHEMA_ID,
        profile_set_sha256=model_sha256(profile_set),
        attempt_count=len(attempts),
        selected_attempt_count=len(selected_attempts),
        success_count=success_count,
        failure_count=len(attempts) - success_count,
        controller_failure_count=ledger.controller_failure_count,
        failed_role_observation_count=ledger.failed_role_observation_count,
        cold_authoritative_hwm_p50_bytes=cold_p50,
        cold_authoritative_hwm_maximum_bytes=cold_maximum,
        maximum_worker_hwm_bytes=max(worker_hwms, default=1),
        maximum_diagnostic_authoritative_delta_bytes=max(deltas, default=0),
        concurrent_peak_aggregate_rss_bytes=concurrent_peak,
        failure_codes=tuple(sorted(failures)),
        passed=not failures,
    )


__all__ = [
    "CANDIDATE_PROFILE_SLOT_PLAN",
    "CANDIDATE_PROFILE_SLOT_PLAN_SHA256",
    "CASE_ORDER",
    "COLD_HWM_MAXIMUM_CEILING_BYTES",
    "COLD_HWM_P50_CEILING_BYTES",
    "CONCURRENT_AGGREGATE_RSS_CEILING_BYTES",
    "CONCURRENT_CASE_ORDER",
    "CONCURRENT_SWEEP_MAXIMUM_DURATION_NS",
    "M0_CASE_HWM_BYTES",
    "MAXIMUM_EXECUTIONS_PER_SLOT",
    "P00_OUTPUT_IDENTITIES",
    "CURRENT_RUNTIME_OUTPUT_IDENTITIES",
    "PER_WORKER_DELTA_BYTES",
    "SOURCE_CUSTODY",
    "ActiveSlotEvent",
    "CandidateExecutionIdentity",
    "CandidateProfileAttemptLedger",
    "CandidateProfileAttemptObservation",
    "CandidateProfileCase",
    "CandidateProfileControllerFailureEvent",
    "CandidateProfileEvaluation",
    "CandidateProfileFinalizationEvent",
    "CandidateProfileRoleObservation",
    "CandidateProfileSelection",
    "CandidateProfileSet",
    "CandidateProfileSlotSpec",
    "ConcurrentAggregateSnapshot",
    "ConcurrentBatchEvidence",
    "ConcurrentRoundEvidence",
    "ConcurrentWorkerGroupMetric",
    "ConcurrentWorkerInterval",
    "P00QualityEvidence",
    "append_attempt_observation",
    "append_controller_failure",
    "append_role_observation",
    "attempt_output_matches_current_runtime",
    "build_candidate_profile_slot_plan",
    "candidate_profile_execution_id",
    "candidate_profile_ledger_payload_sha256",
    "evaluate_candidate_profile_set",
    "finalize_ledger",
    "initial_candidate_profile_attempt_ledger",
    "next_candidate_profile_execution_id",
    "seal_candidate_profile_attempt_ledger",
]
