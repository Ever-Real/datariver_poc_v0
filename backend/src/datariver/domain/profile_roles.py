from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from datariver.domain.authz import SERVICE_ONLY_ACTIONS, Action
from datariver.domain.capability_catalog import (
    CAPABILITY_BY_ACTION,
    CAPABILITY_CATALOG_VERSION,
    CAPABILITY_SERVICES,
    DEFAULT_HUMAN_ADMIN_ACTIONS,
)
from datariver.domain.common import canonical_json_hash

PROFILE_ROLE_POLICY_VERSION = "PROFILE_ROLE_POLICY_V1"


class ProfileRoleTier(StrEnum):
    VIEWER = "VIEWER"
    ENGINEER_STEWARD = "ENGINEER_STEWARD"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"


class StoredProfileRoleTier(StrEnum):
    VIEWER = "VIEWER"
    ENGINEER_STEWARD = "ENGINEER_STEWARD"
    MANAGER = "MANAGER"


class EffectiveProfileRoleStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNASSIGNED = "UNASSIGNED"
    STALE = "STALE"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class ProfileRolePolicy:
    tier: ProfileRoleTier
    label: str
    description: str
    allowed_actions: frozenset[Action]
    assignable_to_system: bool
    lifecycle_note: str

    @property
    def materialized_actions_hash(self) -> str:
        return canonical_json_hash(
            {
                "policy_version": PROFILE_ROLE_POLICY_VERSION,
                "tier": self.tier.value,
                "allowed_actions": sorted(action.value for action in self.allowed_actions),
            }
        )


VIEWER_ACTIONS = frozenset(
    {
        Action.CATALOG_SEARCH,
        Action.CATALOG_READ,
        Action.CATALOG_LINEAGE_READ,
        Action.CHANGE_READ,
        Action.QUALITY_READ,
        Action.QUALITY_PROFILE_READ,
        Action.QUALITY_OPERATIONS_READ,
        Action.QUALITY_AUDIT_READ,
        Action.DASHBOARD_READ,
        Action.OPERATIONS_READ,
        Action.GOVERNANCE_DOCUMENT_READ,
        Action.GOVERNANCE_DOCUMENT_HISTORY_READ,
        Action.GOVERNANCE_TEMPLATE_READ,
        Action.GOVERNANCE_KNOWLEDGE_READ,
        Action.ATTACHMENT_DOWNLOAD,
        Action.CHAT_QUERY,
    }
)

ENGINEER_STEWARD_ACTIONS = VIEWER_ACTIONS | {
    Action.REGISTRATION_CREATE,
    Action.REGISTRATION_READ,
    Action.REGISTRATION_VALIDATE,
    Action.CHANGE_CREATE,
    Action.CHANGE_EDIT,
    Action.CHANGE_REVIEW,
    Action.QUALITY_RULE_PROPOSE,
    Action.QUALITY_RULE_ARCHIVE,
    Action.QUALITY_RUN_REQUEST,
    Action.QUALITY_RUN_CANCEL,
    Action.QUALITY_RUN_RETRY,
}

MANAGER_ACTIONS = ENGINEER_STEWARD_ACTIONS | {
    Action.KG_CREATE,
    Action.KG_READ,
    Action.KG_EDIT,
    Action.KG_REVIEW,
    Action.GOVERNANCE_DOCUMENT_CREATE,
    Action.GOVERNANCE_DOCUMENT_EDIT,
    Action.GOVERNANCE_DOCUMENT_REVIEW,
    Action.GOVERNANCE_DOCUMENT_ARCHIVE,
    Action.GOVERNANCE_TEMPLATE_PROPOSE,
    Action.GOVERNANCE_TEMPLATE_REVIEW,
    Action.GOVERNANCE_TEMPLATE_ARCHIVE,
}

PROFILE_ROLE_POLICIES = (
    ProfileRolePolicy(
        tier=ProfileRoleTier.VIEWER,
        label="Viewer",
        description="Workspace의 검색·변경·품질·모니터링·거버넌스·Chat 조회 역할",
        allowed_actions=VIEWER_ACTIONS,
        assignable_to_system=False,
        lifecycle_note="조회 전용이며 데이터 변경 작업을 수행하지 않습니다.",
    ),
    ProfileRolePolicy(
        tier=ProfileRoleTier.ENGINEER_STEWARD,
        label="Engineer/Steward",
        description="Viewer 권한과 담당 System 범위의 등록·변경·품질 작업 역할",
        allowed_actions=ENGINEER_STEWARD_ACTIONS,
        assignable_to_system=True,
        lifecycle_note="삭제 요청은 서비스별 취소·보관·비활성화로 처리하고 이력을 보존합니다.",
    ),
    ProfileRolePolicy(
        tier=ProfileRoleTier.MANAGER,
        label="Manager",
        description="Engineer/Steward 권한과 지식·거버넌스 작성·검토·보관 역할",
        allowed_actions=MANAGER_ACTIONS,
        assignable_to_system=True,
        lifecycle_note="지식·거버넌스 이력은 보존하며 publish/activate 권한은 포함하지 않습니다.",
    ),
    ProfileRolePolicy(
        tier=ProfileRoleTier.ADMIN,
        label="Admin",
        description="모든 human-facing capability와 관리자 control-plane 역할",
        allowed_actions=DEFAULT_HUMAN_ADMIN_ACTIONS,
        assignable_to_system=True,
        lifecycle_note=(
            "Canonical Admin 바인딩으로만 부여하며 self-approval workflow는 아직 "
            "활성화하지 않습니다."
        ),
    ),
)

PROFILE_ROLE_BY_TIER = {policy.tier: policy for policy in PROFILE_ROLE_POLICIES}
PROFILE_ROLE_POLICY_HASH = canonical_json_hash(
    {
        "policy_version": PROFILE_ROLE_POLICY_VERSION,
        "capability_catalog_version": CAPABILITY_CATALOG_VERSION,
        "tiers": [
            {
                "tier": policy.tier.value,
                "allowed_actions": sorted(action.value for action in policy.allowed_actions),
                "assignable_to_system": policy.assignable_to_system,
            }
            for policy in PROFILE_ROLE_POLICIES
        ],
    }
)


def validate_profile_role_policy() -> None:
    if set(PROFILE_ROLE_BY_TIER) != set(ProfileRoleTier):
        raise RuntimeError("The profile Role policy must define exactly four tiers.")
    if VIEWER_ACTIONS - ENGINEER_STEWARD_ACTIONS:
        raise RuntimeError("Engineer/Steward must inherit every Viewer action.")
    if ENGINEER_STEWARD_ACTIONS - MANAGER_ACTIONS:
        raise RuntimeError("Manager must inherit every Engineer/Steward action.")
    if MANAGER_ACTIONS - DEFAULT_HUMAN_ADMIN_ACTIONS:
        raise RuntimeError("Admin must inherit every Manager action.")
    if any(policy.allowed_actions & SERVICE_ONLY_ACTIONS for policy in PROFILE_ROLE_POLICIES):
        raise RuntimeError("A human profile Role cannot include a service-only action.")
    if Action.CHANGE_READ not in VIEWER_ACTIONS:
        raise RuntimeError("Viewer must include change.read.")
    if {
        Action.KG_PUBLISH,
        Action.GOVERNANCE_DOCUMENT_PUBLISH,
        Action.GOVERNANCE_TEMPLATE_ACTIVATE,
    } & MANAGER_ACTIONS:
        raise RuntimeError("Manager cannot publish or activate governed content.")
    if set(CAPABILITY_BY_ACTION) != set(Action):
        raise RuntimeError("The capability catalog is incomplete.")
    service_keys = {service.service_key for service in CAPABILITY_SERVICES}
    if any(CAPABILITY_BY_ACTION[action].service_key not in service_keys for action in Action):
        raise RuntimeError("The profile Role policy references an unknown service.")


validate_profile_role_policy()
