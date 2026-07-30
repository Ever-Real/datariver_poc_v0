from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType

from datariver.application.quality_execution_contracts import (
    GX_RUNTIME_VERSION,
    CompiledQualityExpectation,
)
from datariver.domain.common import ValidationError
from datariver.domain.quality import RuleDefinition, RuleKind

ModuleLoader = Callable[[str], ModuleType]

_RESULT_FORMAT: dict[str, object] = {
    "result_format": "SUMMARY",
    "partial_unexpected_count": 0,
    "include_config": True,
    "return_unexpected_index_query": False,
}


class FixedGxExpectationCompiler:
    """Compile typed domain rules without accepting arbitrary GX configuration."""

    def __init__(self, *, module_loader: ModuleLoader = importlib.import_module) -> None:
        self._module_loader = module_loader

    def compile(self, rule: RuleDefinition) -> CompiledQualityExpectation:
        self._require_pinned_runtime()
        if rule.kind is RuleKind.NOT_NULL:
            expectation_type = "expect_column_values_to_not_be_null"
            kwargs: dict[str, object] = {
                "column": rule.field_identifier,
                "result_format": dict(_RESULT_FORMAT),
            }
        elif rule.kind is RuleKind.RANGE:
            expectation_type = "expect_column_values_to_be_between"
            parameters = rule.parameters
            kwargs = {
                "column": rule.field_identifier,
                "min_value": parameters["min_value"],
                "max_value": parameters["max_value"],
                "strict_min": not _required_bool(parameters, "inclusive_min"),
                "strict_max": not _required_bool(parameters, "inclusive_max"),
                "result_format": dict(_RESULT_FORMAT),
            }
        else:
            raise ValidationError("The Quality rule kind has no approved GX compiler.")
        return CompiledQualityExpectation(
            rule_definition_hash=rule.definition_hash,
            rule_kind=rule.kind,
            expectation_type=expectation_type,
            kwargs=kwargs,
        )

    def _require_pinned_runtime(self) -> None:
        try:
            module = self._module_loader("great_expectations")
        except ModuleNotFoundError as error:
            raise RuntimeError("The isolated GX 1.19.1 runtime is unavailable.") from error
        version = getattr(module, "__version__", None)
        if version != GX_RUNTIME_VERSION:
            raise RuntimeError("The isolated Quality worker requires GX 1.19.1 exactly.")


def _required_bool(parameters: dict[str, object], key: str) -> bool:
    value = parameters.get(key)
    if not isinstance(value, bool):
        raise ValidationError("The normalized RANGE inclusivity contract is invalid.")
    return value
