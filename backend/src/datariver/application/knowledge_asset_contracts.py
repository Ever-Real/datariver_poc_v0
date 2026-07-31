from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.knowledge_assets import KnowledgeDeliveryPolicy


@dataclass(frozen=True, slots=True)
class KnowledgeAssetSummary:
    graph_id: UUID
    slug: str
    name: str
    graph_type: str
    status: str
    classification: Classification
    domain_id: UUID | None
    domain_name: str | None
    creator_name: str | None
    creator_email: str | None
    editor_name: str | None
    editor_email: str | None
    active_studio_release_id: UUID | None
    active_studio_release_no: int | None
    active_release_id: UUID | None
    active_release_no: int | None
    class_count: int
    property_count: int
    relationship_count: int
    binding_count: int
    source_count: int
    node_count: int
    edge_count: int
    projection_state: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    delivery_policy: KnowledgeDeliveryPolicy | None


@dataclass(frozen=True, slots=True)
class KnowledgeAssetPage:
    items: tuple[KnowledgeAssetSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeAssetVersionEvent:
    event_id: UUID
    kind: str
    version_label: str
    title: str
    status: str
    author_id: UUID
    author_name: str | None
    author_email: str | None
    reviewed_by: UUID | None
    reviewer_name: str | None
    reviewer_email: str | None
    published_by: UUID | None
    publisher_name: str | None
    publisher_email: str | None
    created_at: datetime
    is_current: bool
    studio_release_id: UUID | None = None
    instance_release_id: UUID | None = None
    changeset_id: UUID | None = None
    content_hash: str | None = None
    node_count: int | None = None
    edge_count: int | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeAssetVersionPage:
    items: tuple[KnowledgeAssetVersionEvent, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeAssetBindingSummary:
    binding_id: UUID
    target_stable_element_id: str
    source_reference_id: UUID
    source_kind: str
    source_name: str
    source_version: str
    mapping_rule_count: int


@dataclass(frozen=True, slots=True)
class KnowledgeAssetProjectionSummary:
    deployment_id: UUID
    release_id: UUID
    adapter: str
    state: str
    node_count: int | None
    edge_count: int | None
    verified_at: datetime | None
    error_code: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeAssetSchemaElementSummary:
    stable_element_id: str
    kind: str
    display_name: str
    canonical_name: str
    data_type: str | None
    source_stable_element_id: str | None
    target_stable_element_id: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeAssetOperationalDetail:
    asset: KnowledgeAssetSummary
    schema_elements: tuple[KnowledgeAssetSchemaElementSummary, ...]
    bindings: tuple[KnowledgeAssetBindingSummary, ...]
    projections: tuple[KnowledgeAssetProjectionSummary, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeGraphChatScope:
    graph_id: UUID
    release_id: UUID
    policy_id: UUID
    policy_version: int
    policy_hash: str
    domain_id: UUID | None
    classification: Classification


@dataclass(frozen=True, slots=True)
class KnowledgeChatCandidate:
    graph_id: UUID
    release_id: UUID
    domain_id: UUID | None
    classification: Classification
    delivery_policy: KnowledgeDeliveryPolicy
