from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError, canonical_json_hash

_RESIDENCY_REGION_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,63}$")


class DataAccessLevel(StrEnum):
    NO_ACCESS = "NO_ACCESS"
    PARTIAL_ACCESS = "PARTIAL_ACCESS"
    FULL_ACCESS = "FULL_ACCESS"


class PartialAccessTreatment(StrEnum):
    MASK = "MASK"
    REDACT = "REDACT"
    TOKENIZE = "TOKENIZE"


class DataProcessingPurpose(StrEnum):
    METADATA_READ = "METADATA_READ"
    DATA_READ = "DATA_READ"
    EXPORT = "EXPORT"
    ANALYTICS = "ANALYTICS"
    MODEL_TRAINING = "MODEL_TRAINING"


@dataclass(frozen=True, slots=True)
class RoleDataAccessRule:
    """A secret-free policy-book rule for one classification and role version."""

    classification: Classification
    access_level: DataAccessLevel
    partial_treatment: PartialAccessTreatment | None = None
    allowed_residency_regions: tuple[str, ...] = ()
    allowed_processing_purposes: frozenset[DataProcessingPurpose] = frozenset()

    def __post_init__(self) -> None:
        normalized_regions = tuple(
            sorted({region.strip().upper() for region in self.allowed_residency_regions})
        )
        if any(
            _RESIDENCY_REGION_PATTERN.fullmatch(region) is None for region in normalized_regions
        ):
            raise ValidationError("Residency regions must be bounded uppercase identifiers.")
        object.__setattr__(self, "allowed_residency_regions", normalized_regions)

        if self.access_level is DataAccessLevel.PARTIAL_ACCESS:
            if self.partial_treatment is None:
                raise ValidationError("Partial access requires a deterministic treatment.")
        elif self.partial_treatment is not None:
            raise ValidationError("Only partial access can declare a treatment.")

        if self.access_level is DataAccessLevel.NO_ACCESS:
            if normalized_regions or self.allowed_processing_purposes:
                raise ValidationError("No-access rules cannot declare processing scope.")
        elif not normalized_regions or not self.allowed_processing_purposes:
            raise ValidationError("Granted access requires residency and processing scope.")

    def payload_document(self) -> dict[str, object]:
        return {
            "classification": self.classification.name,
            "access_level": self.access_level.value,
            "partial_treatment": (
                self.partial_treatment.value if self.partial_treatment is not None else None
            ),
            "allowed_residency_regions": list(self.allowed_residency_regions),
            "allowed_processing_purposes": sorted(
                purpose.value for purpose in self.allowed_processing_purposes
            ),
        }

    @property
    def payload_hash(self) -> str:
        return canonical_json_hash(self.payload_document())


@dataclass(frozen=True, slots=True)
class DataAccessDecision:
    allowed: bool
    effective_level: DataAccessLevel
    reason_codes: tuple[str, ...]
    partial_treatment: PartialAccessTreatment | None = None


def decide_role_data_access(
    *,
    rule: RoleDataAccessRule | None,
    resource_classification: Classification,
    residency_region: str,
    purpose: DataProcessingPurpose,
    available_treatments: frozenset[PartialAccessTreatment] = frozenset(),
) -> DataAccessDecision:
    """Evaluate the policy-book layer; callers must also pass existing ABAC/RLS checks."""

    if rule is None:
        return DataAccessDecision(False, DataAccessLevel.NO_ACCESS, ("ROLE_DATA_RULE_MISSING",))
    if rule.classification is not resource_classification:
        return DataAccessDecision(
            False, DataAccessLevel.NO_ACCESS, ("RESOURCE_CLASSIFICATION_MISMATCH",)
        )
    if rule.access_level is DataAccessLevel.NO_ACCESS:
        return DataAccessDecision(False, DataAccessLevel.NO_ACCESS, ("ROLE_DATA_ACCESS_DENIED",))
    if residency_region.strip().upper() not in rule.allowed_residency_regions:
        return DataAccessDecision(False, DataAccessLevel.NO_ACCESS, ("RESIDENCY_REGION_DENIED",))
    if purpose not in rule.allowed_processing_purposes:
        return DataAccessDecision(False, DataAccessLevel.NO_ACCESS, ("PROCESSING_PURPOSE_DENIED",))
    if (
        rule.access_level is DataAccessLevel.PARTIAL_ACCESS
        and rule.partial_treatment not in available_treatments
    ):
        return DataAccessDecision(
            False, DataAccessLevel.NO_ACCESS, ("PARTIAL_TREATMENT_UNAVAILABLE",)
        )
    return DataAccessDecision(
        True,
        rule.access_level,
        (),
        partial_treatment=rule.partial_treatment,
    )
