from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.quality import RuleKind, require_finite_ratio

GX_RUNTIME_VERSION = "1.19.1"
GX_COMPILER_CONTRACT = "DATARIVER_GX_COMPILER_V1"
GX_RESULT_CONTRACT = "DATARIVER_GX_RESULT_V1"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_GX_EXPECTATION_TYPES = frozenset(
    {
        "expect_column_values_to_not_be_null",
        "expect_column_values_to_be_between",
    }
)
_MAX_SIGNED_BIGINT = (1 << 63) - 1


@dataclass(frozen=True, slots=True)
class CompiledQualityExpectation:
    rule_definition_hash: str
    rule_kind: RuleKind
    expectation_type: str
    kwargs: dict[str, object]
    gx_version: str = GX_RUNTIME_VERSION
    compiler_contract: str = GX_COMPILER_CONTRACT
    configuration_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.rule_definition_hash):
            raise ValidationError("The Quality rule-definition hash is invalid.")
        if self.gx_version != GX_RUNTIME_VERSION:
            raise ValidationError("The compiled Quality expectation has an unsupported GX version.")
        if self.compiler_contract != GX_COMPILER_CONTRACT:
            raise ValidationError("The Quality compiler contract is invalid.")
        if self.expectation_type not in _GX_EXPECTATION_TYPES:
            raise ValidationError("The compiled Quality expectation type is not allowlisted.")
        safe_kwargs = copy.deepcopy(self.kwargs)
        object.__setattr__(self, "kwargs", safe_kwargs)
        object.__setattr__(
            self,
            "configuration_hash",
            canonical_json_hash(self.configuration_document()),
        )

    def gx_configuration(self) -> dict[str, object]:
        return {
            "type": self.expectation_type,
            "kwargs": copy.deepcopy(self.kwargs),
        }

    def configuration_document(self) -> dict[str, object]:
        return {
            "contract": self.compiler_contract,
            "gx_version": self.gx_version,
            "rule_definition_hash": self.rule_definition_hash,
            "rule_kind": self.rule_kind.value,
            "expectation": self.gx_configuration(),
        }


@dataclass(frozen=True, slots=True)
class SanitizedQualityExpectationResult:
    success: bool
    evaluated_count: int
    missing_count: int
    unexpected_count: int
    missing_ratio: float
    unexpected_ratio: float
    duration_ms: int
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.evaluated_count, "evaluated count"),
            (self.missing_count, "missing count"),
            (self.unexpected_count, "unexpected count"),
            (self.duration_ms, "duration"),
        ):
            if isinstance(value, bool) or not 0 <= value <= _MAX_SIGNED_BIGINT:
                raise ValidationError(f"The sanitized Quality {label} is invalid.")
        if self.unexpected_count > self.evaluated_count:
            raise ValidationError(
                "The sanitized Quality unexpected count exceeds the evaluated count."
            )
        require_finite_ratio(self.missing_ratio, "Quality missing ratio")
        require_finite_ratio(self.unexpected_ratio, "Quality unexpected ratio")
        if self.success is not (self.unexpected_count == 0):
            raise ValidationError("The sanitized Quality success flag conflicts with its counts.")
        object.__setattr__(self, "result_hash", canonical_json_hash(self.result_document()))

    def result_document(self) -> dict[str, object]:
        return {
            "contract": GX_RESULT_CONTRACT,
            "success": self.success,
            "evaluated_count": self.evaluated_count,
            "missing_count": self.missing_count,
            "unexpected_count": self.unexpected_count,
            "missing_ratio": self.missing_ratio,
            "unexpected_ratio": self.unexpected_ratio,
            "duration_ms": self.duration_ms,
        }
