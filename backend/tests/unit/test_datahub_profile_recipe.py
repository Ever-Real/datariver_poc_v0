from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
RECIPE = ROOT / "infra/datahub/recipes/semiconductor_postgres.yml"

APPROVED_FIELD_METRICS = {
    "include_field_null_count": True,
    "include_field_distinct_count": True,
    "include_field_min_value": False,
    "include_field_max_value": False,
    "include_field_mean_value": False,
    "include_field_median_value": False,
    "include_field_stddev_value": False,
    "include_field_quantiles": False,
    "include_field_distinct_value_frequencies": False,
    "include_field_histogram": False,
    "include_field_sample_values": False,
}


def _profiling() -> dict[str, object]:
    document = yaml.safe_load(RECIPE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    source = document.get("source")
    assert isinstance(source, dict)
    assert source.get("type") == "postgres"
    config = source.get("config")
    assert isinstance(config, dict)
    profiling = config.get("profiling")
    assert isinstance(profiling, dict)
    return profiling


def test_postgres_profile_recipe_uses_the_v160_field_metric_allowlist() -> None:
    profiling = _profiling()

    assert profiling["enabled"] is True
    assert profiling["method"] == "sqlalchemy"
    assert profiling["profile_table_level_only"] is False
    assert profiling["profile_table_row_count_estimate_only"] is False
    assert profiling["report_dropped_profiles"] is True
    assert {
        key: value for key, value in profiling.items() if key.startswith("include_field_")
    } == APPROVED_FIELD_METRICS


def test_postgres_profile_recipe_requires_deployment_owned_capacity_bounds() -> None:
    profiling = _profiling()

    assert profiling["max_workers"] == "${SEMICONDUCTOR_POSTGRES_PROFILE_MAX_WORKERS}"
    assert (
        profiling["max_number_of_fields_to_profile"]
        == "${SEMICONDUCTOR_POSTGRES_PROFILE_MAX_FIELDS}"
    )
    assert not isinstance(profiling["max_workers"], int)
    assert not isinstance(profiling["max_number_of_fields_to_profile"], int)
