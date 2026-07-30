from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from datariver.application.quality_execution_contracts import (
    SanitizedQualityExpectationResult,
)
from datariver.domain.common import ValidationError

_NOT_NULL_EXPECTATION = "expect_column_values_to_not_be_null"
_RANGE_EXPECTATION = "expect_column_values_to_be_between"
_ALLOWED_EXPECTATIONS = frozenset({_NOT_NULL_EXPECTATION, _RANGE_EXPECTATION})
_MAX_SIGNED_BIGINT = (1 << 63) - 1


class StrictGxResultSanitizer:
    """Reduce one GX result plus worker-measured duration to the persistence allowlist."""

    def sanitize(
        self, raw_validation_result: Mapping[str, object]
    ) -> SanitizedQualityExpectationResult:
        success = _required_bool(raw_validation_result, "success")
        duration_ms = _required_count(raw_validation_result, "duration_ms")
        expectation = _required_mapping(raw_validation_result, "expectation_config")
        expectation_type = _required_text(expectation, "type")
        if expectation_type not in _ALLOWED_EXPECTATIONS:
            raise ValidationError("The GX result expectation type is not allowlisted.")
        kwargs = _required_mapping(expectation, "kwargs")
        result_format = _required_mapping(kwargs, "result_format")
        partial_count = _required_count(result_format, "partial_unexpected_count")
        if partial_count != 0:
            raise ValidationError("The GX partial-unexpected contract is not disabled.")
        _reject_exception_payload(raw_validation_result.get("exception_info"))

        result = _required_mapping(raw_validation_result, "result")
        element_count = _required_count(result, "element_count")
        raw_missing_count = _required_count(result, "missing_count")
        unexpected_count = _required_count(result, "unexpected_count")
        if raw_missing_count > element_count:
            raise ValidationError("The GX missing count exceeds its element count.")

        if expectation_type == _NOT_NULL_EXPECTATION:
            evaluated_count = element_count
            missing_count = unexpected_count
            if unexpected_count > evaluated_count:
                raise ValidationError("The GX unexpected count exceeds its evaluated count.")
            denominator = evaluated_count
            missing_ratio = _ratio(missing_count, denominator)
            unexpected_ratio = missing_ratio
        else:
            evaluated_count = element_count - raw_missing_count
            missing_count = raw_missing_count
            if unexpected_count > evaluated_count:
                raise ValidationError("The GX unexpected count exceeds its evaluated count.")
            missing_ratio = _ratio(missing_count, element_count)
            unexpected_ratio = _ratio(unexpected_count, evaluated_count)

        return SanitizedQualityExpectationResult(
            success=success,
            evaluated_count=evaluated_count,
            missing_count=missing_count,
            unexpected_count=unexpected_count,
            missing_ratio=missing_ratio,
            unexpected_ratio=unexpected_ratio,
            duration_ms=duration_ms,
        )


def _required_mapping(document: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = document.get(key)
    if not isinstance(value, Mapping) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"The GX {key} document is invalid.")
    return cast(Mapping[str, object], value)


def _required_bool(document: Mapping[str, object], key: str) -> bool:
    value = document.get(key)
    if not isinstance(value, bool):
        raise ValidationError(f"The GX {key} value is invalid.")
    return value


def _required_count(document: Mapping[str, object], key: str) -> int:
    value = document.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _MAX_SIGNED_BIGINT
    ):
        raise ValidationError(f"The GX {key} value is invalid.")
    return value


def _required_text(document: Mapping[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise ValidationError(f"The GX {key} value is invalid.")
    return value


def _reject_exception_payload(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValidationError("The GX exception document is invalid.")
    raised = value.get("raised_exception")
    message = value.get("exception_message")
    traceback = value.get("exception_traceback")
    if raised is not False or message not in {None, ""} or traceback not in {None, ""}:
        raise ValidationError("The GX execution did not produce a sanitizable result.")


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        if numerator != 0:
            raise ValidationError("The GX ratio denominator is zero for a non-zero count.")
        return 0.0
    value = numerator / denominator
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValidationError("The GX result ratio is invalid.")
    return value
