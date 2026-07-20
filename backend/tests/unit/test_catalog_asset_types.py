from datariver.domain.catalog import DATASET_ASSET_TYPES, is_dataset_asset_type


def test_dataset_asset_type_family_is_explicit_and_closed() -> None:
    assert DATASET_ASSET_TYPES == frozenset({"DATASET", "TABLE", "VIEW"})
    assert all(is_dataset_asset_type(value) for value in DATASET_ASSET_TYPES)
    assert not is_dataset_asset_type("DASHBOARD")
    assert not is_dataset_asset_type(None)
