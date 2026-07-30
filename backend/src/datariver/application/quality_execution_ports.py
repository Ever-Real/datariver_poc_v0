from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from datariver.application.quality_execution_contracts import (
    CompiledQualityExpectation,
    SanitizedQualityExpectationResult,
)
from datariver.domain.quality import RuleDefinition


class QualityExpectationCompilerPort(Protocol):
    def compile(self, rule: RuleDefinition) -> CompiledQualityExpectation: ...


class QualityResultSanitizerPort(Protocol):
    def sanitize(
        self, raw_validation_result: Mapping[str, object]
    ) -> SanitizedQualityExpectationResult: ...
