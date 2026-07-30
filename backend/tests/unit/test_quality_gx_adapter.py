from __future__ import annotations

import json
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from datariver.application.quality_execution_contracts import GX_RUNTIME_VERSION
from datariver.domain.common import ValidationError
from datariver.domain.quality import RuleDefinition, RuleKind, RuleSeverity
from datariver.infrastructure.quality.gx_compiler import FixedGxExpectationCompiler
from datariver.infrastructure.quality.result_sanitizer import StrictGxResultSanitizer


def _gx_module(version: str = GX_RUNTIME_VERSION) -> ModuleType:
    module = ModuleType("great_expectations")
    module.__dict__["__version__"] = version
    return module


def _rule(
    *,
    kind: RuleKind = RuleKind.NOT_NULL,
    parameters: dict[str, object] | None = None,
) -> RuleDefinition:
    return RuleDefinition.create(
        ordinal=1,
        field_identifier="customer.amount",
        kind=kind,
        severity=RuleSeverity.BLOCKING,
        parameters=parameters or {},
    )


def _raw_result(
    *,
    expectation_type: str,
    success: bool,
    element_count: int = 10,
    missing_count: int = 0,
    unexpected_count: int = 0,
    partial_unexpected_count: int = 0,
) -> dict[str, object]:
    return {
        "success": success,
        "duration_ms": 125,
        "expectation_config": {
            "type": expectation_type,
            "kwargs": {
                "column": "customer.amount",
                "result_format": {
                    "result_format": "SUMMARY",
                    "partial_unexpected_count": partial_unexpected_count,
                    "include_config": True,
                    "return_unexpected_index_query": False,
                },
            },
        },
        "result": {
            "element_count": element_count,
            "missing_count": missing_count,
            "unexpected_count": unexpected_count,
        },
        "exception_info": {
            "raised_exception": False,
            "exception_message": None,
            "exception_traceback": None,
        },
    }


def test_compiler_imports_gx_lazily_and_pins_exact_runtime() -> None:
    calls: list[str] = []

    def loader(name: str) -> ModuleType:
        calls.append(name)
        return _gx_module()

    compiler = FixedGxExpectationCompiler(module_loader=loader)
    assert calls == []

    compiled = compiler.compile(_rule())

    assert calls == ["great_expectations"]
    assert compiled.gx_version == "1.19.1"
    assert compiled.gx_configuration() == {
        "type": "expect_column_values_to_not_be_null",
        "kwargs": {
            "column": "customer.amount",
            "result_format": {
                "result_format": "SUMMARY",
                "partial_unexpected_count": 0,
                "include_config": True,
                "return_unexpected_index_query": False,
            },
        },
    }


def test_compiler_rejects_unpinned_runtime_without_importing_at_module_load() -> None:
    compiler = FixedGxExpectationCompiler(module_loader=lambda _: _gx_module("1.19.2"))

    with pytest.raises(RuntimeError, match=r"requires GX 1\.19\.1 exactly"):
        compiler.compile(_rule())


def test_compiler_builds_only_the_fixed_typed_range_configuration() -> None:
    compiler = FixedGxExpectationCompiler(module_loader=lambda _: _gx_module())
    rule = _rule(
        kind=RuleKind.RANGE,
        parameters={
            "value_type": "DECIMAL",
            "min_value": "1.00",
            "max_value": "99.50",
            "inclusive_min": True,
            "inclusive_max": False,
        },
    )

    compiled = compiler.compile(rule)

    assert compiled.gx_configuration() == {
        "type": "expect_column_values_to_be_between",
        "kwargs": {
            "column": "customer.amount",
            "min_value": "1",
            "max_value": "99.5",
            "strict_min": False,
            "strict_max": True,
            "result_format": {
                "result_format": "SUMMARY",
                "partial_unexpected_count": 0,
                "include_config": True,
                "return_unexpected_index_query": False,
            },
        },
    }
    rendered = json.dumps(compiled.configuration_document(), sort_keys=True)
    for prohibited in ('"sql":', '"query":', '"batch_request":', '"plugin":', '"row_condition":'):
        assert prohibited not in rendered


def test_compiler_rejects_regex_even_if_an_invalid_domain_object_reaches_the_adapter() -> None:
    invalid_rule = cast(
        RuleDefinition,
        SimpleNamespace(
            kind=RuleKind.REGEX,
            field_identifier="customer.email",
            parameters={"pattern": ".+"},
            definition_hash="a" * 64,
        ),
    )
    compiler = FixedGxExpectationCompiler(module_loader=lambda _: _gx_module())

    with pytest.raises(ValidationError, match="no approved GX compiler"):
        compiler.compile(invalid_rule)


def test_sanitizer_derives_not_null_metrics_and_discards_sensitive_gx_fields() -> None:
    raw = _raw_result(
        expectation_type="expect_column_values_to_not_be_null",
        success=False,
        element_count=10,
        unexpected_count=2,
    )
    result = cast(dict[str, object], raw["result"])
    result["partial_unexpected_list"] = ["secret@example.test"]
    result["unexpected_rows"] = [{"password": "never-persist"}]
    result["unexpected_index_list"] = [7, 9]
    result["unexpected_index_query"] = "SELECT secret FROM source"

    sanitized = StrictGxResultSanitizer().sanitize(raw)

    assert sanitized.evaluated_count == 10
    assert sanitized.missing_count == 2
    assert sanitized.unexpected_count == 2
    assert sanitized.missing_ratio == pytest.approx(0.2)
    assert sanitized.unexpected_ratio == pytest.approx(0.2)
    document = sanitized.result_document()
    assert set(document) == {
        "contract",
        "success",
        "evaluated_count",
        "missing_count",
        "unexpected_count",
        "missing_ratio",
        "unexpected_ratio",
        "duration_ms",
    }
    rendered = json.dumps(document, sort_keys=True)
    for secret in ("secret@example.test", "never-persist", "SELECT secret", "unexpected_rows"):
        assert secret not in rendered


def test_sanitizer_excludes_nulls_from_range_evaluated_denominator() -> None:
    raw = _raw_result(
        expectation_type="expect_column_values_to_be_between",
        success=False,
        element_count=10,
        missing_count=2,
        unexpected_count=2,
    )

    sanitized = StrictGxResultSanitizer().sanitize(raw)

    assert sanitized.evaluated_count == 8
    assert sanitized.missing_count == 2
    assert sanitized.missing_ratio == pytest.approx(0.2)
    assert sanitized.unexpected_ratio == pytest.approx(0.25)
    assert len(sanitized.result_hash) == 64


def test_sanitizer_rejects_nonzero_partial_unexpected_contract() -> None:
    raw = _raw_result(
        expectation_type="expect_column_values_to_not_be_null",
        success=True,
        partial_unexpected_count=1,
    )

    with pytest.raises(ValidationError, match="partial-unexpected contract"):
        StrictGxResultSanitizer().sanitize(raw)


def test_sanitizer_fails_closed_without_exposing_provider_exception_text() -> None:
    raw = _raw_result(
        expectation_type="expect_column_values_to_not_be_null",
        success=True,
    )
    raw["exception_info"] = {
        "raised_exception": True,
        "exception_message": "postgres://user:secret@source/private",
        "exception_traceback": "SELECT * FROM restricted_table",
    }

    with pytest.raises(ValidationError) as captured:
        StrictGxResultSanitizer().sanitize(raw)

    assert "secret" not in str(captured.value)
    assert "restricted_table" not in str(captured.value)


@pytest.mark.parametrize(
    ("success", "unexpected_count"),
    ((True, 1), (False, 0)),
)
def test_sanitizer_rejects_success_and_count_mismatch(success: bool, unexpected_count: int) -> None:
    raw = _raw_result(
        expectation_type="expect_column_values_to_not_be_null",
        success=success,
        unexpected_count=unexpected_count,
    )

    with pytest.raises(ValidationError, match="success flag conflicts"):
        StrictGxResultSanitizer().sanitize(raw)
