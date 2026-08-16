"""Portable, immutable registry contracts for the LlamaParse-15 corpus.

This module is test/reporting infrastructure only.  It records fixture
identity, custody, categories, and physical-to-printed page maps without
modeling reviewed claims, parser output, or production behavior.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from tests.benchmarks.contracts import (
    CONTRACT_VERSION,
    ContractModel,
    FixtureManifest,
    NonEmptyString,
    SchemaVersion,
    Sha256,
    canonical_json,
)
from tests.benchmarks.source_truth import ArtifactIdentity, ArtifactRole


REGISTRY_ID = "llamaparse-15"
CORPUS_ROOT = "benchmark-expertmodeldata"
CUSTODY_DECISION_ID = "p00-us04-all-corpus-public-redistributable"
INVENTORY_MANIFEST_PATH = "tracker/benchmarks/llamaparse-15/manifest.json"
CUSTODY_DECISION_PATH = (
    "tracker/phase-00-baseline/decisions/P00-US04-corpus-custody.md"
)
CUSTODY_EVIDENCE_PATH = (
    "tracker/phase-00-baseline/evidence/P00-US04-source-rights.md"
)

EXPECTED_CASE_COUNT = 15
EXPECTED_PAGE_COUNT = 30
EXPECTED_ARTIFACT_COUNT = 45

EXPECTED_CASE_IDS = (
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

EXPECTED_PRINTED_PAGE_LABELS: dict[str, tuple[str | None, ...]] = {
    "catastrophe-recap": ("7",),
    "clean-energy": ("11",),
    "clinical-study": ("1/21", "7/21", "10/21", "11/21"),
    "component-datasheet": ("3", "7", "11"),
    "egov-survey": ("37",),
    "esg-metrics": ("80",),
    "finance-10k": ("28", "30", "32"),
    "health-report": ("103",),
    "insurance-acord": (None,),
    "manufacturing-report": ("11", "15", "38"),
    "ny-timetable": ("2 of 28", "3 of 28", "4 of 28"),
    "postal-10k": ("2", "46", "49"),
    "purchase-agreement": (None,),
    "settlement-agreement": ("24",),
    "uber-earnings": ("1", "5", "6"),
}

PERMITTED_USES = (
    "workspace_retention",
    "repository_commit",
    "benchmark_redistribution",
    "local_validation",
    "private_ci_validation",
    "committed_ci_validation",
)

PermittedUse = Literal[
    "workspace_retention",
    "repository_commit",
    "benchmark_redistribution",
    "local_validation",
    "private_ci_validation",
    "committed_ci_validation",
]
SourceRotation = Literal[0, 90, 180, 270]

_CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ROLE_EXTENSIONS = {
    ArtifactRole.SOURCE: ".pdf",
    ArtifactRole.EXPERT_MARKDOWN: ".md",
    ArtifactRole.EXPERT_JSON: ".json",
}
_ROLE_ORDER = tuple(_ROLE_EXTENSIONS)


class RegistryVerificationError(ValueError):
    """A registry reference does not match the current workspace bytes."""


def _portable_path(value: str) -> PurePosixPath:
    """Validate one canonical, workspace-relative POSIX path."""

    if value != value.strip():
        raise ValueError("portable paths must not have surrounding whitespace")
    if "\x00" in value:
        raise ValueError("portable paths must not contain NUL bytes")
    if "\\" in value:
        raise ValueError("portable paths must use POSIX separators")
    if not value:
        raise ValueError("portable paths must not be empty")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(
            "portable paths must not contain empty, dot, or parent segments"
        )
    if raw_parts[0].startswith("~") or ":" in raw_parts[0]:
        raise ValueError("portable paths must be workspace-relative")

    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ValueError("portable paths must be canonical workspace-relative paths")
    return path


class RegistryPageIdentity(ContractModel):
    """One immutable physical page and its reviewed printed-page identity."""

    physical_page: int = Field(ge=1)
    printed_page: NonEmptyString | None
    width_pt: float = Field(gt=0, allow_inf_nan=False)
    height_pt: float = Field(gt=0, allow_inf_nan=False)
    source_rotation_deg: SourceRotation

    @field_validator("printed_page")
    @classmethod
    def require_canonical_printed_page(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError(
                "printed page labels must not have surrounding whitespace"
            )
        return value

    @field_validator("width_pt", "height_pt")
    @classmethod
    def require_millipoint_precision(cls, value: float) -> float:
        if value != round(value, 3):
            raise ValueError("page dimensions must use at most three decimals")
        return value

    @property
    def printed_page_label(self) -> str | None:
        """Compatibility-friendly name for the reviewed printed label."""

        return self.printed_page


class RegistryCustody(ContractModel):
    """The approved no-exceptions custody decision for the whole corpus."""

    decision_id: Literal[
        "p00-us04-all-corpus-public-redistributable"
    ]
    record_status: Literal["approved"]
    decision: Literal["public-redistributable"]
    decision_date: Literal["2026-07-29"]
    approver: NonEmptyString
    no_exceptions: Literal[True]
    derived_annotations_covered: Literal[True]
    permitted_uses: tuple[PermittedUse, ...] = Field(
        min_length=len(PERMITTED_USES),
        max_length=len(PERMITTED_USES),
    )
    decision_path: Literal[
        "tracker/phase-00-baseline/decisions/P00-US04-corpus-custody.md"
    ]
    decision_sha256: Sha256
    evidence_path: Literal[
        "tracker/phase-00-baseline/evidence/P00-US04-source-rights.md"
    ]
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def require_complete_ordered_approval(self) -> "RegistryCustody":
        if self.permitted_uses != PERMITTED_USES:
            raise ValueError(
                "custody must retain every approved use in canonical order"
            )
        _portable_path(self.decision_path)
        _portable_path(self.evidence_path)
        return self


class RegistryCase(ContractModel):
    """Portable artifact, category, and page identity for one corpus case."""

    case_id: NonEmptyString
    category: NonEmptyString
    layout_characteristics: tuple[NonEmptyString, ...] = Field(min_length=1)
    complex_elements: tuple[NonEmptyString, ...] = Field(min_length=1)
    source_format: Literal["PDF"]
    custody: Literal["public-redistributable"]
    custody_decision_id: Literal[
        "p00-us04-all-corpus-public-redistributable"
    ]
    review_path: NonEmptyString
    page_count: int = Field(gt=0)
    artifacts: tuple[ArtifactIdentity, ...] = Field(min_length=3, max_length=3)
    pages: tuple[RegistryPageIdentity, ...] = Field(min_length=1)

    @field_validator("case_id", "category")
    @classmethod
    def require_trimmed_identity(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("case identity and category must be trimmed")
        return value

    @field_validator("layout_characteristics", "complex_elements")
    @classmethod
    def require_unique_metadata(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if any(value != value.strip() for value in values):
            raise ValueError("case metadata values must be trimmed")
        if len(values) != len(set(values)):
            raise ValueError("case metadata values must be unique")
        return values

    @model_validator(mode="after")
    def validate_case_identity(self) -> "RegistryCase":
        if not _CASE_ID_PATTERN.fullmatch(self.case_id):
            raise ValueError("case_id must be a lowercase hyphenated identifier")

        expected_review_path = (
            f"tracker/benchmarks/llamaparse-15/cases/{self.case_id}.md"
        )
        _portable_path(self.review_path)
        if self.review_path != expected_review_path:
            raise ValueError("review_path must identify the matching case report")

        if tuple(artifact.role for artifact in self.artifacts) != _ROLE_ORDER:
            raise ValueError(
                "artifacts must contain source, expert Markdown, and expert JSON "
                "in canonical order"
            )

        artifact_paths = [artifact.path for artifact in self.artifacts]
        artifact_hashes = [artifact.sha256 for artifact in self.artifacts]
        if len(artifact_paths) != len(set(artifact_paths)):
            raise ValueError("artifact paths must be unique within a case")
        if len(artifact_hashes) != len(set(artifact_hashes)):
            raise ValueError("artifact hashes must not collide within a case")

        for artifact in self.artifacts:
            path = _portable_path(artifact.path)
            expected_extension = _ROLE_EXTENSIONS[artifact.role]
            expected_path = (
                f"{CORPUS_ROOT}/{self.case_id}{expected_extension}"
            )
            if path.parts[0] != CORPUS_ROOT or artifact.path != expected_path:
                raise ValueError(
                    "artifact path must match its case, role, and corpus root"
                )

        if self.page_count != len(self.pages):
            raise ValueError("page_count must match the registered page map")
        physical_pages = tuple(page.physical_page for page in self.pages)
        if physical_pages != tuple(range(1, self.page_count + 1)):
            raise ValueError(
                "physical pages must be contiguous, one-based, and canonical"
            )
        return self

    def fixture_manifest(self) -> FixtureManifest:
        """Project this case onto the unchanged P00-US01 source contract."""

        source = self.artifacts[0]
        if source.role is not ArtifactRole.SOURCE:  # defensive after validation
            raise ValueError("the first canonical artifact must be the source")
        return FixtureManifest(
            schema_version=CONTRACT_VERSION,
            fixture_id=self.case_id,
            source_sha256=source.sha256,
            source_format=self.source_format,
            custody=self.custody,
        )


class PortableCorpusRegistry(ContractModel):
    """Complete portable registry for the immutable LlamaParse-15 corpus."""

    schema_version: SchemaVersion
    registry_id: Literal["llamaparse-15"]
    corpus_root: Literal["benchmark-expertmodeldata"]
    source_files_immutable: Literal[True]
    case_count: Literal[15]
    page_count: Literal[30]
    artifact_count: Literal[45]
    inventory_manifest_path: Literal[
        "tracker/benchmarks/llamaparse-15/manifest.json"
    ]
    inventory_manifest_sha256: Sha256
    custody: RegistryCustody
    cases: tuple[RegistryCase, ...] = Field(
        min_length=EXPECTED_CASE_COUNT,
        max_length=EXPECTED_CASE_COUNT,
    )

    @model_validator(mode="after")
    def validate_complete_registry(self) -> "PortableCorpusRegistry":
        _portable_path(self.inventory_manifest_path)

        case_ids = tuple(case.case_id for case in self.cases)
        if case_ids != EXPECTED_CASE_IDS:
            raise ValueError(
                "cases must match the complete LlamaParse-15 inventory in "
                "canonical order"
            )
        if self.case_count != len(self.cases):
            raise ValueError("case_count must match the registry")

        pages = sum(case.page_count for case in self.cases)
        artifacts = tuple(
            artifact
            for case in self.cases
            for artifact in case.artifacts
        )
        if pages != self.page_count:
            raise ValueError("page_count must match all registered page maps")
        if len(artifacts) != self.artifact_count:
            raise ValueError("artifact_count must match all registered triplets")

        paths = [artifact.path for artifact in artifacts]
        hashes = [artifact.sha256 for artifact in artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("artifact paths must be globally unique")
        if len(hashes) != len(set(hashes)):
            raise ValueError("artifact hashes must not collide across cases")

        for case in self.cases:
            if case.custody_decision_id != self.custody.decision_id:
                raise ValueError(
                    "every case must reference the registry custody decision"
                )
            actual_labels = tuple(page.printed_page for page in case.pages)
            if actual_labels != EXPECTED_PRINTED_PAGE_LABELS[case.case_id]:
                raise ValueError(
                    f"{case.case_id} printed page map must match reviewed evidence"
                )

        missing_labels = sum(
            page.printed_page is None
            for case in self.cases
            for page in case.pages
        )
        if missing_labels != 2:
            raise ValueError(
                "exactly two source pages must explicitly lack printed labels"
            )
        return self

    def case_by_id(self, case_id: str) -> RegistryCase:
        """Return one registered case or raise a precise lookup error."""

        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(f"unregistered corpus case: {case_id}")

    @property
    def artifacts(self) -> tuple[ArtifactIdentity, ...]:
        """Return all artifacts in deterministic case/role order."""

        return tuple(
            artifact
            for case in self.cases
            for artifact in case.artifacts
        )


def canonical_registry_json(registry: PortableCorpusRegistry) -> str:
    """Serialize a validated registry deterministically."""

    return canonical_json(registry)


def load_corpus_registry(path: str | Path) -> PortableCorpusRegistry:
    """Load and fully validate one portable corpus registry."""

    return PortableCorpusRegistry.model_validate_json(Path(path).read_bytes())


def resolve_portable_path(
    workspace_root: str | Path,
    portable_path: str,
) -> Path:
    """Resolve a validated registry path without permitting workspace escape."""

    relative = _portable_path(portable_path)
    root = Path(workspace_root).resolve()
    candidate = root.joinpath(*relative.parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("portable path resolves outside the workspace") from exc
    return candidate


def sha256_file(path: str | Path) -> str:
    """Stream a file and return its lowercase SHA-256 digest."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_reference(
    workspace_root: str | Path,
    portable_path: str,
    expected_sha256: str,
    *,
    expected_size: int | None = None,
) -> None:
    current_path = resolve_portable_path(workspace_root, portable_path)
    if not current_path.exists():
        raise RegistryVerificationError(
            f"registered file is missing: {portable_path}"
        )
    if not current_path.is_file():
        raise RegistryVerificationError(
            f"registered path is not a file: {portable_path}"
        )
    if expected_size is not None and current_path.stat().st_size != expected_size:
        raise RegistryVerificationError(
            f"registered size changed for {portable_path}: "
            f"expected {expected_size}, got {current_path.stat().st_size}"
        )
    current_sha256 = sha256_file(current_path)
    if current_sha256 != expected_sha256:
        raise RegistryVerificationError(
            f"registered SHA-256 changed for {portable_path}: "
            f"expected {expected_sha256}, got {current_sha256}"
        )


def verify_current_artifacts(
    registry: PortableCorpusRegistry,
    workspace_root: str | Path,
) -> tuple[ArtifactIdentity, ...]:
    """Verify support records and all 45 artifact identities against disk.

    The returned tuple preserves the registry's deterministic case/role order.
    Any missing file, non-file path, size drift, hash drift, or workspace escape
    fails closed with ``RegistryVerificationError`` or ``ValueError``.
    """

    _verify_reference(
        workspace_root,
        registry.inventory_manifest_path,
        registry.inventory_manifest_sha256,
    )
    _verify_reference(
        workspace_root,
        registry.custody.decision_path,
        registry.custody.decision_sha256,
    )
    _verify_reference(
        workspace_root,
        registry.custody.evidence_path,
        registry.custody.evidence_sha256,
    )
    for artifact in registry.artifacts:
        _verify_reference(
            workspace_root,
            artifact.path,
            artifact.sha256,
            expected_size=artifact.size_bytes,
        )
    return registry.artifacts
