from __future__ import annotations

from typing import Final

# DataHub exposes datasets with table/view subtypes. The projection retains
# that useful subtype in ``asset_type``, so dataset-governed workflows must
# accept the generic entity and both supported relational subtypes.
DATASET_ASSET_TYPES: Final[frozenset[str]] = frozenset({"DATASET", "TABLE", "VIEW"})


def is_dataset_asset_type(value: str | None) -> bool:
    return value in DATASET_ASSET_TYPES
