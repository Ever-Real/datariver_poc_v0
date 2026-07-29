from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from uuid import UUID

from datariver.application.dto import (
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioPreflightRecord,
    KnowledgeStudioPreviewGraph,
    KnowledgeStudioPreviewNode,
    KnowledgeStudioPreviewRecord,
    KnowledgeStudioSamplePage,
    KnowledgeStudioSampleRequest,
    KnowledgeStudioSampleScalar,
    KnowledgeStudioSourceAccess,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioValidationEvidence,
)
from datariver.application.ports import (
    KnowledgeStudioSampleReader,
    KnowledgeStudioSourceReader,
    KnowledgeStudioStore,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge_studio import KnowledgeStudioService
from datariver.domain.authz import EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import DomainError, ValidationError, canonical_json_hash, utc_now
from datariver.domain.knowledge_studio import require_studio_version, validate_stable_element_id

MAXIMUM_SAMPLE_VALUE_CHARACTERS = 2_000
MAXIMUM_PREFLIGHT_SOURCES = 500


def _evidence(
    *,
    severity: str,
    code: str,
    location: str,
    message: str,
) -> KnowledgeStudioValidationEvidence:
    return KnowledgeStudioValidationEvidence(
        severity=severity,
        code=code,
        location=location,
        message=message,
    )


def _empty_graph() -> KnowledgeStudioPreviewGraph:
    return KnowledgeStudioPreviewGraph(nodes=(), edges=())


def _typed_identity(value: KnowledgeStudioSampleScalar) -> dict[str, object]:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    if isinstance(value, float):
        return {"type": "number", "value": value}
    return {"type": "string", "value": value}


def _valid_scalar(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return -(2**63) <= value <= (2**63) - 1
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= MAXIMUM_SAMPLE_VALUE_CHARACTERS and "\x00" not in value
    return False


def build_class_preview_graph(
    *,
    target: KnowledgeStudioTBoxElementRecord,
    elements: tuple[KnowledgeStudioTBoxElementRecord, ...],
    binding: KnowledgeStudioBindingRecord,
    sample: KnowledgeStudioSamplePage,
) -> tuple[KnowledgeStudioPreviewGraph, tuple[KnowledgeStudioValidationEvidence, ...]]:
    """Project typed sample rows without producing or executing Cypher."""

    evidence: list[KnowledgeStudioValidationEvidence] = []
    if target.kind != "CLASS":
        return _empty_graph(), (
            _evidence(
                severity="ERROR",
                code="RELATION_PREVIEW_UNSUPPORTED",
                location=f"tbox:{target.stable_element_id}",
                message=("Relation preview requires an approved endpoint and join-key contract."),
            ),
        )
    subject_rules = tuple(rule for rule in binding.rules if rule.method == "SUBJECT_ID")
    if len(subject_rules) != 1:
        return _empty_graph(), (
            _evidence(
                severity="ERROR",
                code="SUBJECT_ID_REQUIRED",
                location=f"binding:{target.stable_element_id}",
                message="A Class preview requires exactly one SUBJECT_ID mapping.",
            ),
        )
    subject_rule = subject_rules[0]
    if subject_rule.target_stable_element_id != target.stable_element_id:
        return _empty_graph(), (
            _evidence(
                severity="ERROR",
                code="SUBJECT_ID_TARGET_INVALID",
                location=f"binding:{target.stable_element_id}",
                message="The SUBJECT_ID mapping no longer targets the selected Class.",
            ),
        )
    properties = {
        element.stable_element_id: element
        for element in elements
        if element.kind == "PROPERTY"
        and element.parent_stable_element_id == target.stable_element_id
    }
    property_rules = tuple(rule for rule in binding.rules if rule.method == "PROPERTY")
    if any(rule.target_stable_element_id not in properties for rule in property_rules):
        return _empty_graph(), (
            _evidence(
                severity="ERROR",
                code="PROPERTY_TARGET_MISSING",
                location=f"binding:{target.stable_element_id}",
                message="A persisted mapping targets a Property outside the selected Class.",
            ),
        )
    canonical_names = [
        properties[rule.target_stable_element_id].canonical_name
        for rule in property_rules
        if rule.target_stable_element_id in properties
    ]
    if len(canonical_names) != len(set(canonical_names)):
        return _empty_graph(), (
            _evidence(
                severity="ERROR",
                code="DUPLICATE_PROPERTY_NAME",
                location=f"tbox:{target.stable_element_id}",
                message="Mapped T-Box Properties must have unique canonical names.",
            ),
        )

    nodes_by_id: dict[str, KnowledgeStudioPreviewNode] = {}
    for ordinal, row in enumerate(sample.rows):
        row_location = f"sample:row:{ordinal}"
        required_fields = {
            subject_rule.source_field_path,
            *(rule.source_field_path for rule in property_rules),
        }
        missing_fields = sorted(required_fields.difference(row))
        if missing_fields:
            evidence.append(
                _evidence(
                    severity="ERROR",
                    code="SAMPLE_FIELD_MISSING",
                    location=row_location,
                    message="The source reader omitted one or more persisted mapping fields.",
                )
            )
            continue
        invalid_value = next(
            (
                value
                for key, value in row.items()
                if key in required_fields and not _valid_scalar(value)
            ),
            None,
        )
        if invalid_value is not None:
            evidence.append(
                _evidence(
                    severity="ERROR",
                    code="SAMPLE_VALUE_INVALID",
                    location=row_location,
                    message="A mapped sample value is not a bounded JSON scalar.",
                )
            )
            continue
        identity = row[subject_rule.source_field_path]
        if identity is None or identity == "":
            evidence.append(
                _evidence(
                    severity="ERROR",
                    code="SUBJECT_ID_VALUE_MISSING",
                    location=row_location,
                    message="A sampled row has no SUBJECT_ID value.",
                )
            )
            continue
        node_id = "preview:" + canonical_json_hash(
            {
                "binding_id": str(binding.binding_id),
                "identity": _typed_identity(identity),
                "target": target.stable_element_id,
            }
        )
        mapped_properties: dict[str, KnowledgeStudioSampleScalar] = {}
        row_invalid = False
        for rule in property_rules:
            property_element = properties.get(rule.target_stable_element_id)
            if property_element is None:
                evidence.append(
                    _evidence(
                        severity="ERROR",
                        code="PROPERTY_TARGET_MISSING",
                        location=f"binding:{target.stable_element_id}",
                        message=(
                            "A persisted mapping targets a Property outside the selected Class."
                        ),
                    )
                )
                row_invalid = True
                break
            value = row[rule.source_field_path]
            if property_element.nullable is False and value is None:
                evidence.append(
                    _evidence(
                        severity="ERROR",
                        code="REQUIRED_PROPERTY_VALUE_MISSING",
                        location=row_location,
                        message=(
                            f"Required Property {property_element.display_name} has a null value."
                        ),
                    )
                )
            mapped_properties[property_element.canonical_name] = value
        if row_invalid:
            continue
        if node_id in nodes_by_id:
            evidence.append(
                _evidence(
                    severity="WARNING",
                    code="DUPLICATE_SAMPLE_SUBJECT_ID",
                    location=row_location,
                    message="Multiple sampled rows resolve to the same SUBJECT_ID.",
                )
            )
            continue
        nodes_by_id[node_id] = KnowledgeStudioPreviewNode(
            node_id=node_id,
            stable_element_id=target.stable_element_id,
            type_name=target.canonical_name,
            identity=identity,
            properties=mapped_properties,
        )
    if not sample.rows:
        evidence.append(
            _evidence(
                severity="INFO",
                code="SOURCE_SAMPLE_EMPTY",
                location=f"binding:{target.stable_element_id}",
                message="The physical Dataset returned no rows within the sample bound.",
            )
        )
    if len(evidence) > 200:
        evidence = [
            *evidence[:199],
            _evidence(
                severity="WARNING",
                code="PREVIEW_EVIDENCE_TRUNCATED",
                location=f"binding:{target.stable_element_id}",
                message="Additional preview evidence was omitted by the response bound.",
            ),
        ]
    return (
        KnowledgeStudioPreviewGraph(nodes=tuple(nodes_by_id.values()), edges=()),
        tuple(evidence),
    )


class KnowledgeStudioPreviewService:
    def __init__(
        self,
        *,
        store: KnowledgeStudioStore,
        authorization: AuthorizationService,
        sources: KnowledgeStudioSourceReader | None,
        samples: KnowledgeStudioSampleReader | None,
    ) -> None:
        self._store = store
        self._studio = KnowledgeStudioService(
            store=store,
            authorization=authorization,
            sources=sources,
        )
        self._sources = sources
        self._samples = samples

    async def preview_binding(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        target_stable_element_id: str,
        sample_limit: int,
        expected_version: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioPreviewRecord:
        validate_stable_element_id(target_stable_element_id)
        if sample_limit < 5 or sample_limit > 10:
            raise ValidationError("Knowledge Studio preview limit must be between 5 and 10.")
        abox = await self._studio.get_abox(
            workspace_id=workspace_id,
            subject=subject,
            draft_id=draft_id,
            environment=environment,
            request_id=request_id,
        )
        require_studio_version(abox.draft.version, expected_version)
        target = next(
            (
                item
                for item in abox.tbox_elements
                if item.stable_element_id == target_stable_element_id
            ),
            None,
        )
        binding = next(
            (
                item
                for item in abox.bindings
                if item.target_stable_element_id == target_stable_element_id
            ),
            None,
        )
        if target is None or binding is None:
            return self._preview_failure(
                draft_version=abox.draft.version,
                target_stable_element_id=target_stable_element_id,
                binding=binding,
                status="INVALID",
                code="BINDING_REQUIRED",
                message="Save a current Binding Draft before requesting a preview.",
            )
        if binding.readiness == "STALE" or binding.tbox_version != target.version:
            return self._preview_failure(
                draft_version=abox.draft.version,
                target_stable_element_id=target_stable_element_id,
                binding=binding,
                status="INVALID",
                code="BINDING_TBOX_STALE",
                message="Rebind the selected target to the current accepted T-Box.",
            )
        if target.kind != "CLASS":
            graph, evidence = build_class_preview_graph(
                target=target,
                elements=abox.tbox_elements,
                binding=binding,
                sample=KnowledgeStudioSamplePage(
                    source_reference_id=binding.source_reference_id,
                    source_version=binding.source_version,
                    projection_source_version=binding.projection_source_version,
                    rows=(),
                    observed_at=environment.requested_at,
                ),
            )
            return KnowledgeStudioPreviewRecord(
                status="INVALID",
                draft_version=abox.draft.version,
                binding_version=binding.version,
                target_stable_element_id=target_stable_element_id,
                dry_run=True,
                sample_size=0,
                graph=graph,
                evidence=evidence,
            )
        source_error = await self._validate_preview_source(
            abox=abox,
            binding=binding,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        if source_error is not None:
            return replace(
                self._preview_failure(
                    draft_version=abox.draft.version,
                    target_stable_element_id=target_stable_element_id,
                    binding=binding,
                    status=source_error[0],
                    code=source_error[1],
                    message=source_error[2],
                ),
                graph=_empty_graph(),
            )
        if self._samples is None:
            return self._preview_failure(
                draft_version=abox.draft.version,
                target_stable_element_id=target_stable_element_id,
                binding=binding,
                status="UNAVAILABLE",
                code="SOURCE_ROW_READER_UNAVAILABLE",
                message="No approved physical Dataset row reader is configured.",
            )
        source_request = self._sample_request(binding=binding, limit=sample_limit)
        try:
            sample = await self._samples.sample_rows(
                subject=subject,
                source=source_request,
                environment=environment,
                request_id=request_id,
            )
        except DomainError:
            return self._preview_failure(
                draft_version=abox.draft.version,
                target_stable_element_id=target_stable_element_id,
                binding=binding,
                status="UNAVAILABLE",
                code="SOURCE_ROW_ACCESS_INVALID",
                message="The physical Dataset sample could not be read with the current access.",
            )
        sample_error = self._sample_receipt_error(source_request, sample)
        if sample_error is not None:
            return self._preview_failure(
                draft_version=abox.draft.version,
                target_stable_element_id=target_stable_element_id,
                binding=binding,
                status="INVALID",
                code=sample_error[0],
                message=sample_error[1],
            )
        graph, evidence = build_class_preview_graph(
            target=target,
            elements=abox.tbox_elements,
            binding=binding,
            sample=sample,
        )
        return KnowledgeStudioPreviewRecord(
            status=("INVALID" if any(item.severity == "ERROR" for item in evidence) else "READY"),
            draft_version=abox.draft.version,
            binding_version=binding.version,
            target_stable_element_id=target_stable_element_id,
            dry_run=True,
            sample_size=len(sample.rows),
            graph=graph,
            evidence=evidence,
        )

    async def preflight(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioPreflightRecord:
        abox = await self._studio.get_abox(
            workspace_id=workspace_id,
            subject=subject,
            draft_id=draft_id,
            environment=environment,
            request_id=request_id,
        )
        require_studio_version(abox.draft.version, expected_version)
        evidence = self._mapping_evidence(abox)
        class_bindings = self._class_bindings(abox)
        source_requests = self._deduplicated_source_requests(class_bindings)
        if len(source_requests) > MAXIMUM_PREFLIGHT_SOURCES:
            evidence.append(
                _evidence(
                    severity="ERROR",
                    code="PREFLIGHT_SOURCE_BOUND_EXCEEDED",
                    location="abox",
                    message="The A-Box source set exceeds the pre-flight validation bound.",
                )
            )
        else:
            evidence.extend(
                await self._source_access_evidence(
                    abox=abox,
                    bindings=class_bindings,
                    source_requests=source_requests,
                    subject=subject,
                    environment=environment,
                    request_id=request_id,
                )
            )
        has_errors = any(item.severity == "ERROR" for item in evidence)
        unavailable = any(
            item.code
            in {
                "SOURCE_METADATA_UNAVAILABLE",
                "SOURCE_ROW_READER_UNAVAILABLE",
                "SOURCE_ROW_ACCESS_INVALID",
            }
            for item in evidence
        )
        status = "UNAVAILABLE" if unavailable else ("FAIL" if has_errors else "PASS")
        return await self._store.record_preflight(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
            expected_version=expected_version,
            status=status,
            valid=not has_errors,
            evidence=tuple(evidence),
            checked_at=utc_now(),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def _validate_preview_source(
        self,
        *,
        abox: KnowledgeStudioABoxRecord,
        binding: KnowledgeStudioBindingRecord,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[str, str, str] | None:
        if self._sources is None:
            return (
                "UNAVAILABLE",
                "SOURCE_METADATA_UNAVAILABLE",
                "Knowledge Studio Dataset metadata access is unavailable.",
            )
        try:
            detail = await self._sources.get_dataset(
                subject=subject,
                asset_id=binding.source_asset_id,
                environment=environment,
                request_id=request_id,
            )
        except DomainError:
            return (
                "UNAVAILABLE",
                "SOURCE_METADATA_UNAVAILABLE",
                "The selected Dataset metadata could not be revalidated.",
            )
        if detail is None:
            return (
                "INVALID",
                "SOURCE_METADATA_ACCESS_INVALID",
                "The selected Dataset is no longer in the authorized catalog scope.",
            )
        dataset = detail.dataset
        if detail.stale_at is not None:
            return (
                "INVALID",
                "SOURCE_METADATA_STALE",
                "The selected Dataset metadata is stale.",
            )
        if (
            dataset.source_version != binding.source_version
            or dataset.projection_source_version != binding.projection_source_version
            or dataset.classification != binding.source_classification
            or dataset.classification > abox.draft.classification
        ):
            return (
                "INVALID",
                "SOURCE_CONTRACT_DRIFT",
                "The selected Dataset version or classification changed.",
            )
        mapped_fields = {rule.source_field_path for rule in binding.rules}
        if not mapped_fields.issubset(dataset.field_paths):
            return (
                "INVALID",
                "SOURCE_FIELD_DRIFT",
                "One or more persisted mapping fields are no longer available.",
            )
        return None

    async def _source_access_evidence(
        self,
        *,
        abox: KnowledgeStudioABoxRecord,
        bindings: tuple[KnowledgeStudioBindingRecord, ...],
        source_requests: tuple[KnowledgeStudioSampleRequest, ...],
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> list[KnowledgeStudioValidationEvidence]:
        evidence: list[KnowledgeStudioValidationEvidence] = []
        if not source_requests:
            return evidence
        if self._sources is None:
            evidence.append(
                _evidence(
                    severity="ERROR",
                    code="SOURCE_METADATA_UNAVAILABLE",
                    location="abox",
                    message="Knowledge Studio Dataset metadata access is unavailable.",
                )
            )
            return evidence
        try:
            accessible_sources = await self._sources.validate_dataset_access(
                subject=subject,
                asset_ids=tuple(dict.fromkeys(item.source_asset_id for item in bindings)),
                environment=environment,
                request_id=request_id,
            )
        except DomainError:
            evidence.append(
                _evidence(
                    severity="ERROR",
                    code="SOURCE_METADATA_UNAVAILABLE",
                    location="abox",
                    message="Dataset metadata access could not be revalidated.",
                )
            )
            return evidence
        access_by_id: dict[UUID, KnowledgeStudioSourceAccess] = {
            item.asset_id: item for item in accessible_sources
        }
        eligible_source_references: set[UUID] = set()
        for binding in bindings:
            access = access_by_id.get(binding.source_asset_id)
            if access is None:
                evidence.append(
                    _evidence(
                        severity="ERROR",
                        code="SOURCE_METADATA_ACCESS_INVALID",
                        location=f"binding:{binding.target_stable_element_id}",
                        message="The mapped Dataset is no longer in the authorized catalog scope.",
                    )
                )
            elif (
                access.projection_source_version != binding.projection_source_version
                or access.classification != binding.source_classification
                or access.classification > abox.draft.classification
            ):
                evidence.append(
                    _evidence(
                        severity="ERROR",
                        code="SOURCE_CONTRACT_DRIFT",
                        location=f"binding:{binding.target_stable_element_id}",
                        message="The mapped Dataset projection or classification changed.",
                    )
                )
            else:
                eligible_source_references.add(binding.source_reference_id)
        eligible_requests = tuple(
            item
            for item in source_requests
            if item.source_reference_id in eligible_source_references
        )
        if not eligible_requests:
            return evidence
        if self._samples is None:
            evidence.append(
                _evidence(
                    severity="ERROR",
                    code="SOURCE_ROW_READER_UNAVAILABLE",
                    location="abox",
                    message="No approved physical Dataset row reader is configured.",
                )
            )
            return evidence
        try:
            probes = await self._samples.probe_access(
                subject=subject,
                sources=eligible_requests,
                environment=environment,
                request_id=request_id,
            )
        except DomainError:
            evidence.append(
                _evidence(
                    severity="ERROR",
                    code="SOURCE_ROW_ACCESS_INVALID",
                    location="abox",
                    message="Physical Dataset access could not be verified.",
                )
            )
            return evidence
        probe_by_source = {item.source_reference_id: item for item in probes}
        for source in eligible_requests:
            probe = probe_by_source.get(source.source_reference_id)
            if (
                probe is None
                or not probe.accessible
                or probe.source_version != source.source_version
                or probe.projection_source_version != source.projection_source_version
            ):
                evidence.append(
                    _evidence(
                        severity="ERROR",
                        code="SOURCE_ROW_ACCESS_INVALID",
                        location=f"source:{source.source_reference_id}",
                        message="Physical Dataset access or its exact version is no longer valid.",
                    )
                )
        return evidence

    @staticmethod
    def _mapping_evidence(
        abox: KnowledgeStudioABoxRecord,
    ) -> list[KnowledgeStudioValidationEvidence]:
        evidence: list[KnowledgeStudioValidationEvidence] = []
        bindings = {item.target_stable_element_id: item for item in abox.bindings}
        properties_by_class: dict[str, list[KnowledgeStudioTBoxElementRecord]] = {}
        for element in abox.tbox_elements:
            if element.kind == "PROPERTY" and element.parent_stable_element_id is not None:
                properties_by_class.setdefault(element.parent_stable_element_id, []).append(element)
        for element in abox.tbox_elements:
            if element.kind != "CLASS":
                continue
            binding = bindings.get(element.stable_element_id)
            location = f"tbox:{element.stable_element_id}"
            if binding is None:
                evidence.append(
                    _evidence(
                        severity="ERROR",
                        code="REQUIRED_CLASS_UNBOUND",
                        location=location,
                        message=f"Required Class {element.display_name} has no persisted binding.",
                    )
                )
                continue
            if binding.readiness == "STALE" or binding.tbox_version != element.version:
                evidence.append(
                    _evidence(
                        severity="ERROR",
                        code="BINDING_TBOX_STALE",
                        location=location,
                        message=(
                            f"Class {element.display_name} must be rebound to the current T-Box."
                        ),
                    )
                )
            subject_rules = tuple(rule for rule in binding.rules if rule.method == "SUBJECT_ID")
            if len(subject_rules) != 1:
                evidence.append(
                    _evidence(
                        severity="ERROR",
                        code="SUBJECT_ID_REQUIRED",
                        location=location,
                        message=f"Class {element.display_name} requires one SUBJECT_ID mapping.",
                    )
                )
            mapped_properties = {
                rule.target_stable_element_id for rule in binding.rules if rule.method == "PROPERTY"
            }
            for property_element in properties_by_class.get(element.stable_element_id, ()):
                if (
                    property_element.nullable is False
                    and property_element.stable_element_id not in mapped_properties
                ):
                    evidence.append(
                        _evidence(
                            severity="ERROR",
                            code="REQUIRED_PROPERTY_UNMAPPED",
                            location=f"tbox:{property_element.stable_element_id}",
                            message=(
                                f"Required Property {property_element.display_name} is not mapped."
                            ),
                        )
                    )
                if (
                    property_element.vector_index_enabled
                    and property_element.stable_element_id not in mapped_properties
                ):
                    evidence.append(
                        _evidence(
                            severity="ERROR",
                            code="VECTOR_PROPERTY_UNMAPPED",
                            location=f"tbox:{property_element.stable_element_id}",
                            message=(
                                f"Vector Property {property_element.display_name} must be "
                                "mapped before ingestion."
                            ),
                        )
                    )
        return evidence

    @staticmethod
    def _class_bindings(
        abox: KnowledgeStudioABoxRecord,
    ) -> tuple[KnowledgeStudioBindingRecord, ...]:
        class_ids = {item.stable_element_id for item in abox.tbox_elements if item.kind == "CLASS"}
        return tuple(item for item in abox.bindings if item.target_stable_element_id in class_ids)

    @classmethod
    def _deduplicated_source_requests(
        cls,
        bindings: tuple[KnowledgeStudioBindingRecord, ...],
    ) -> tuple[KnowledgeStudioSampleRequest, ...]:
        grouped: dict[UUID, KnowledgeStudioSampleRequest] = {}
        for binding in bindings:
            candidate = cls._sample_request(binding=binding, limit=5)
            current = grouped.get(binding.source_reference_id)
            if current is None:
                grouped[binding.source_reference_id] = candidate
                continue
            grouped[binding.source_reference_id] = replace(
                current,
                field_paths=tuple(sorted(set(current.field_paths).union(candidate.field_paths))),
            )
        return tuple(grouped.values())

    @staticmethod
    def _sample_request(
        *,
        binding: KnowledgeStudioBindingRecord,
        limit: int,
    ) -> KnowledgeStudioSampleRequest:
        return KnowledgeStudioSampleRequest(
            source_reference_id=binding.source_reference_id,
            asset_id=binding.source_asset_id,
            source_version=binding.source_version,
            projection_source_version=binding.projection_source_version,
            field_paths=tuple(sorted({rule.source_field_path for rule in binding.rules})),
            limit=limit,
        )

    @staticmethod
    def _sample_receipt_error(
        requested: KnowledgeStudioSampleRequest,
        sample: KnowledgeStudioSamplePage,
    ) -> tuple[str, str] | None:
        if (
            sample.source_reference_id != requested.source_reference_id
            or sample.source_version != requested.source_version
            or sample.projection_source_version != requested.projection_source_version
        ):
            return (
                "SOURCE_SAMPLE_VERSION_MISMATCH",
                "The source reader did not confirm the exact persisted source contract.",
            )
        if len(sample.rows) > requested.limit:
            return (
                "SOURCE_SAMPLE_BOUND_EXCEEDED",
                "The source reader returned more rows than the requested preview limit.",
            )
        if any(not isinstance(row, Mapping) for row in sample.rows):
            return (
                "SOURCE_SAMPLE_CONTRACT_INVALID",
                "The source reader returned an invalid typed row contract.",
            )
        return None

    @staticmethod
    def _preview_failure(
        *,
        draft_version: int,
        target_stable_element_id: str,
        binding: KnowledgeStudioBindingRecord | None,
        status: str,
        code: str,
        message: str,
    ) -> KnowledgeStudioPreviewRecord:
        return KnowledgeStudioPreviewRecord(
            status=status,
            draft_version=draft_version,
            binding_version=binding.version if binding is not None else None,
            target_stable_element_id=target_stable_element_id,
            dry_run=True,
            sample_size=0,
            graph=_empty_graph(),
            evidence=(
                _evidence(
                    severity="ERROR",
                    code=code,
                    location=f"tbox:{target_stable_element_id}",
                    message=message,
                ),
            ),
        )
