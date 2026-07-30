from __future__ import annotations

from uuid import UUID

from datariver.application.quality_command_contracts import (
    QualityAuthoringField,
    QualityDeploymentBinding,
)
from datariver.application.quality_command_ports import QualityDeploymentDirectory
from datariver.infrastructure.quality.source_manifest import (
    AUTHORING_MANIFEST_CONTRACT_VERSION,
    QualitySourceManifest,
    QualitySourceManifestError,
)

_RANGE_TYPES = frozenset({"INTEGER", "DECIMAL", "DATE", "TIMESTAMP"})


class ManifestQualityDeploymentDirectory(QualityDeploymentDirectory):
    def __init__(self, manifest: QualitySourceManifest | None) -> None:
        self._manifest = manifest

    @property
    def authoring_available(self) -> bool:
        return (
            self._manifest is not None
            and self._manifest.contract_version == AUTHORING_MANIFEST_CONTRACT_VERSION
            and bool(self._manifest.authoring_bindings)
        )

    def resolve(self, *, asset_id: UUID) -> QualityDeploymentBinding | None:
        if self._manifest is None:
            return None
        try:
            target = self._manifest.resolve_authoring_target(asset_id=asset_id)
        except QualitySourceManifestError:
            return None
        fields = tuple(
            QualityAuthoringField(
                field_identifier=field_identifier,
                display_path=field_identifier,
                logical_type=logical_type,  # type: ignore[arg-type]
                supported_rule_kinds=(
                    ("NOT_NULL", "RANGE") if logical_type in _RANGE_TYPES else ("NOT_NULL",)
                ),
            )
            for field_identifier, logical_type in target.fields
        )
        return QualityDeploymentBinding(
            asset_id=asset_id,
            system_id=target.source.system_id,
            schema_hash=target.schema_hash,
            fields=fields,
            source_connection_profile_id=target.source.source_connection_profile_id,
            source_connection_profile_version=(target.source.source_connection_profile_version),
            source_connection_profile_hash=target.source.source_connection_profile_hash,
            workload_profile_id=target.workload.workload_profile_id,
            workload_profile_version=target.workload.workload_profile_version,
            workload_profile_hash=target.workload.workload_profile_hash,
        )
