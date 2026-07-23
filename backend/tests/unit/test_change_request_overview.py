from datariver.infrastructure.db.change_request_overview import _bounded_schema_keys


def test_overview_window_stays_bounded_when_target_schemas_extend_a_full_catalog_window() -> None:
    catalog = tuple(("postgres", "warehouse", f"schema_{index:03d}") for index in range(101))
    targets = frozenset(
        {
            ("oracle", "fab", "current_a"),
            ("oracle", "fab", "current_b"),
        }
    )

    retained, truncated = _bounded_schema_keys(
        schemas=(*catalog, *targets),
        target_schema_keys=targets,
        limit=101,
        catalog_window_full=True,
    )

    assert truncated is True
    assert len(retained) == 100
    assert retained[:2] == tuple(sorted(targets))
    assert set(retained).issubset(set(catalog) | set(targets))
