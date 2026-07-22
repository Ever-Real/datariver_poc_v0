from __future__ import annotations

import pytest

from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError
from datariver.domain.data_access import (
    DataAccessLevel,
    DataProcessingPurpose,
    PartialAccessTreatment,
    RoleDataAccessRule,
    decide_role_data_access,
)


def _rule(
    *,
    level: DataAccessLevel = DataAccessLevel.FULL_ACCESS,
    treatment: PartialAccessTreatment | None = None,
) -> RoleDataAccessRule:
    return RoleDataAccessRule(
        classification=Classification.CONFIDENTIAL,
        access_level=level,
        partial_treatment=treatment,
        allowed_residency_regions=("KR", "AP-NORTHEAST-2"),
        allowed_processing_purposes=frozenset(
            {DataProcessingPurpose.METADATA_READ, DataProcessingPurpose.DATA_READ}
        ),
    )


def test_missing_rule_and_explicit_no_access_fail_closed() -> None:
    missing = decide_role_data_access(
        rule=None,
        resource_classification=Classification.CONFIDENTIAL,
        residency_region="KR",
        purpose=DataProcessingPurpose.DATA_READ,
    )
    denied = decide_role_data_access(
        rule=RoleDataAccessRule(
            classification=Classification.CONFIDENTIAL,
            access_level=DataAccessLevel.NO_ACCESS,
        ),
        resource_classification=Classification.CONFIDENTIAL,
        residency_region="KR",
        purpose=DataProcessingPurpose.DATA_READ,
    )

    assert missing.allowed is False
    assert missing.effective_level is DataAccessLevel.NO_ACCESS
    assert missing.reason_codes == ("ROLE_DATA_RULE_MISSING",)
    assert denied.allowed is False
    assert denied.reason_codes == ("ROLE_DATA_ACCESS_DENIED",)


def test_full_access_requires_exact_residency_and_processing_purpose() -> None:
    rule = _rule()

    allowed = decide_role_data_access(
        rule=rule,
        resource_classification=Classification.CONFIDENTIAL,
        residency_region="kr",
        purpose=DataProcessingPurpose.DATA_READ,
    )
    wrong_region = decide_role_data_access(
        rule=rule,
        resource_classification=Classification.CONFIDENTIAL,
        residency_region="US-EAST-1",
        purpose=DataProcessingPurpose.DATA_READ,
    )
    wrong_purpose = decide_role_data_access(
        rule=rule,
        resource_classification=Classification.CONFIDENTIAL,
        residency_region="KR",
        purpose=DataProcessingPurpose.EXPORT,
    )

    assert allowed.allowed is True
    assert allowed.effective_level is DataAccessLevel.FULL_ACCESS
    assert wrong_region.reason_codes == ("RESIDENCY_REGION_DENIED",)
    assert wrong_purpose.reason_codes == ("PROCESSING_PURPOSE_DENIED",)


def test_partial_access_requires_an_available_treatment_adapter() -> None:
    rule = _rule(
        level=DataAccessLevel.PARTIAL_ACCESS,
        treatment=PartialAccessTreatment.TOKENIZE,
    )

    unavailable = decide_role_data_access(
        rule=rule,
        resource_classification=Classification.CONFIDENTIAL,
        residency_region="KR",
        purpose=DataProcessingPurpose.DATA_READ,
    )
    available = decide_role_data_access(
        rule=rule,
        resource_classification=Classification.CONFIDENTIAL,
        residency_region="KR",
        purpose=DataProcessingPurpose.DATA_READ,
        available_treatments=frozenset({PartialAccessTreatment.TOKENIZE}),
    )

    assert unavailable.allowed is False
    assert unavailable.reason_codes == ("PARTIAL_TREATMENT_UNAVAILABLE",)
    assert available.allowed is True
    assert available.effective_level is DataAccessLevel.PARTIAL_ACCESS
    assert available.partial_treatment is PartialAccessTreatment.TOKENIZE


@pytest.mark.parametrize(
    ("level", "treatment"),
    [
        (DataAccessLevel.PARTIAL_ACCESS, None),
        (DataAccessLevel.FULL_ACCESS, PartialAccessTreatment.MASK),
        (DataAccessLevel.NO_ACCESS, PartialAccessTreatment.REDACT),
    ],
)
def test_rule_rejects_incoherent_access_level_and_treatment(
    level: DataAccessLevel,
    treatment: PartialAccessTreatment | None,
) -> None:
    with pytest.raises(ValidationError):
        _rule(level=level, treatment=treatment)


def test_rule_hash_is_order_independent_and_contains_no_secret() -> None:
    left = _rule()
    right = RoleDataAccessRule(
        classification=Classification.CONFIDENTIAL,
        access_level=DataAccessLevel.FULL_ACCESS,
        allowed_residency_regions=("AP-NORTHEAST-2", "KR"),
        allowed_processing_purposes=frozenset(
            {DataProcessingPurpose.DATA_READ, DataProcessingPurpose.METADATA_READ}
        ),
    )

    assert left.payload_hash == right.payload_hash
    assert "secret" not in left.payload_document()
