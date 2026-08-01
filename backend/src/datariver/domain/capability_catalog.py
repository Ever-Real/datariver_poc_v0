from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from datariver.domain.authz import HIGH_RISK_ACTIONS, SERVICE_ONLY_ACTIONS, Action
from datariver.domain.common import canonical_json_hash

CAPABILITY_CATALOG_VERSION = "ACCESS_ROLE_CAPABILITY_CATALOG_V2"
CANONICAL_ADMIN_ROLE_KEY = "canonical-admin"


class AccessRoleKind(StrEnum):
    HUMAN_ROLE = "HUMAN_ROLE"
    CANONICAL_ADMIN = "CANONICAL_ADMIN"


class AccessRoleManagementSource(StrEnum):
    HUMAN_ADMIN = "HUMAN_ADMIN"
    SERVER_CANONICAL = "SERVER_CANONICAL"


class CapabilityActorKind(StrEnum):
    HUMAN = "HUMAN"
    SERVICE_PRINCIPAL = "SERVICE_PRINCIPAL"


class CapabilityAssignability(StrEnum):
    HUMAN_ROLE = "HUMAN_ROLE"
    CANONICAL_ADMIN_ONLY = "CANONICAL_ADMIN_ONLY"
    SERVICE_PRINCIPAL_ONLY = "SERVICE_PRINCIPAL_ONLY"


class CapabilityAssurance(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SESSION = "SESSION"
    FRESH_PHISHING_RESISTANT = "FRESH_PHISHING_RESISTANT"


class CapabilityReasonPolicy(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"


class CapabilitySelfApprovalPolicy(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CANONICAL_ADMIN_ONLY = "CANONICAL_ADMIN_ONLY"


class CapabilitySelfApprovalBinding(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_PROTECTED_BINDING = "PENDING_PROTECTED_BINDING"


class CapabilityRisk(StrEnum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    SERVICE_PRIVILEGED = "SERVICE_PRIVILEGED"


@dataclass(frozen=True, slots=True)
class CapabilityService:
    service_key: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class CapabilityMetadata:
    action: Action
    service_key: str
    label: str
    description: str
    actor_kind: CapabilityActorKind
    assignability: CapabilityAssignability
    default_admin: bool
    assurance: CapabilityAssurance
    reason_policy: CapabilityReasonPolicy
    self_approval_policy: CapabilitySelfApprovalPolicy
    self_approval_binding: CapabilitySelfApprovalBinding
    risk: CapabilityRisk


@dataclass(frozen=True, slots=True)
class ProtectedCapabilityMetadata:
    capability_key: str
    service_key: str
    label: str
    description: str
    actor_kind: CapabilityActorKind
    assignability: CapabilityAssignability
    default_admin: bool
    assurance: CapabilityAssurance
    reason_policy: CapabilityReasonPolicy
    self_approval_policy: CapabilitySelfApprovalPolicy
    self_approval_binding: CapabilitySelfApprovalBinding
    risk: CapabilityRisk


CAPABILITY_SERVICES = (
    CapabilityService("catalog", "카탈로그", "검색, 상세, 동기화 및 반출 capability"),
    CapabilityService("registration", "등록", "파일과 수동 등록 lifecycle capability"),
    CapabilityService("change", "변경관리", "변경 요청, 검토, 승인 및 재시도 capability"),
    CapabilityService("knowledge", "지식관리", "지식 그래프 작성, 검토, 배포 및 worker capability"),
    CapabilityService("chat", "Chat", "권한 범위 내 근거 기반 질의 capability"),
    CapabilityService(
        "governance_documents", "거버넌스 문서", "문서 첨부파일과 안전한 artifact 접근 capability"
    ),
    CapabilityService("delivery", "Delivery", "API product 배포, 관리 및 호출 capability"),
    CapabilityService("dashboard", "대시보드", "공통 업무 대시보드 조회 capability"),
    CapabilityService("operations", "운영", "운영 상태 조회와 통제된 재시도 capability"),
    CapabilityService("audit", "감사", "Workspace 감사 증적 조회 capability"),
    CapabilityService("admin", "관리", "Workspace 보안 및 관리 control-plane capability"),
    CapabilityService("retention", "보존", "보존정책, Legal Hold, 삭제 및 archive capability"),
    CapabilityService("quality", "품질관리", "품질 Rule, 실행, 결과 및 worker capability"),
    CapabilityService("governance", "정책 문서", "정책·Template lifecycle 및 지식 투영 capability"),
)

_DECLARED_PROTECTED_CAPABILITIES = (
    ProtectedCapabilityMetadata(
        capability_key="admin.self_approve",
        service_key="admin",
        label="Canonical Admin 자기승인",
        description=(
            "Canonical Admin 전용 자기승인 정책 capability입니다. 일반 Role에는 위임할 수 없으며 "
            "보호된 서버 바인딩이 구현되기 전에는 실제 승인 동작을 활성화하지 않습니다."
        ),
        actor_kind=CapabilityActorKind.HUMAN,
        assignability=CapabilityAssignability.CANONICAL_ADMIN_ONLY,
        default_admin=True,
        assurance=CapabilityAssurance.FRESH_PHISHING_RESISTANT,
        reason_policy=CapabilityReasonPolicy.REQUIRED,
        self_approval_policy=CapabilitySelfApprovalPolicy.CANONICAL_ADMIN_ONLY,
        self_approval_binding=CapabilitySelfApprovalBinding.PENDING_PROTECTED_BINDING,
        risk=CapabilityRisk.HIGH,
    ),
)

SELF_APPROVAL_CANDIDATE_ACTIONS = frozenset(
    {
        Action.CHANGE_APPROVE,
        Action.KG_REVIEW,
        Action.KG_PUBLISH,
        Action.RETENTION_MANAGE,
        Action.LEGAL_HOLD_RELEASE,
        Action.QUALITY_RULE_REVIEW,
        Action.QUALITY_RULE_ACTIVATE,
        Action.GOVERNANCE_DOCUMENT_REVIEW,
        Action.GOVERNANCE_DOCUMENT_PUBLISH,
        Action.GOVERNANCE_TEMPLATE_REVIEW,
        Action.GOVERNANCE_TEMPLATE_ACTIVATE,
    }
)

REASON_REQUIRED_ACTIONS = frozenset(
    {
        Action.CHANGE_CREATE,
        Action.CHANGE_RAW_CREATE,
        Action.CHANGE_REVIEW,
        Action.CHANGE_APPROVE,
        Action.CHANGE_RETRY,
        Action.KG_REVIEW,
        Action.KG_PUBLISH,
        Action.OPERATIONS_RETRY,
        Action.ADMIN_MANAGE,
        Action.RETENTION_MANAGE,
        Action.LEGAL_HOLD_PLACE,
        Action.LEGAL_HOLD_RELEASE,
        Action.ERASURE_REQUEST,
        Action.ERASURE_APPROVE,
        Action.QUALITY_RULE_PROPOSE,
        Action.QUALITY_RULE_REVIEW,
        Action.QUALITY_RULE_ACTIVATE,
        Action.QUALITY_RULE_REVOKE,
        Action.QUALITY_RULE_ARCHIVE,
        Action.QUALITY_RUN_REQUEST,
        Action.QUALITY_RUN_CANCEL,
        Action.QUALITY_RUN_RETRY,
        Action.GOVERNANCE_DOCUMENT_CREATE,
        Action.GOVERNANCE_DOCUMENT_EDIT,
        Action.GOVERNANCE_DOCUMENT_REVIEW,
        Action.GOVERNANCE_DOCUMENT_PUBLISH,
        Action.GOVERNANCE_DOCUMENT_ARCHIVE,
        Action.GOVERNANCE_TEMPLATE_PROPOSE,
        Action.GOVERNANCE_TEMPLATE_REVIEW,
        Action.GOVERNANCE_TEMPLATE_ACTIVATE,
        Action.GOVERNANCE_TEMPLATE_ARCHIVE,
    }
)

STANDARD_RISK_ACTIONS = frozenset(
    {
        Action.CATALOG_SEARCH,
        Action.CATALOG_READ,
        Action.CATALOG_QUARANTINE_READ,
        Action.CATALOG_LINEAGE_READ,
        Action.REGISTRATION_READ,
        Action.CHANGE_READ,
        Action.KG_READ,
        Action.CHAT_QUERY,
        Action.DASHBOARD_READ,
        Action.OPERATIONS_READ,
        Action.AUDIT_READ,
        Action.RETENTION_READ,
        Action.ARCHIVE_READ,
        Action.QUALITY_READ,
        Action.QUALITY_PROFILE_READ,
        Action.QUALITY_OPERATIONS_READ,
        Action.QUALITY_AUDIT_READ,
        Action.GOVERNANCE_DOCUMENT_READ,
        Action.GOVERNANCE_DOCUMENT_HISTORY_READ,
        Action.GOVERNANCE_TEMPLATE_READ,
        Action.GOVERNANCE_KNOWLEDGE_READ,
    }
)


def _metadata(
    action: Action,
    service_key: str,
    label: str,
    description: str,
) -> CapabilityMetadata:
    service_only = action in SERVICE_ONLY_ACTIONS
    self_approval = action in SELF_APPROVAL_CANDIDATE_ACTIONS
    return CapabilityMetadata(
        action=action,
        service_key=service_key,
        label=label,
        description=description,
        actor_kind=(
            CapabilityActorKind.SERVICE_PRINCIPAL if service_only else CapabilityActorKind.HUMAN
        ),
        assignability=(
            CapabilityAssignability.SERVICE_PRINCIPAL_ONLY
            if service_only
            else CapabilityAssignability.HUMAN_ROLE
        ),
        default_admin=not service_only,
        assurance=(
            CapabilityAssurance.NOT_APPLICABLE
            if service_only
            else (
                CapabilityAssurance.FRESH_PHISHING_RESISTANT
                if action in HIGH_RISK_ACTIONS
                else CapabilityAssurance.SESSION
            )
        ),
        reason_policy=(
            CapabilityReasonPolicy.REQUIRED
            if action in REASON_REQUIRED_ACTIONS
            else CapabilityReasonPolicy.NOT_REQUIRED
        ),
        self_approval_policy=(
            CapabilitySelfApprovalPolicy.CANONICAL_ADMIN_ONLY
            if self_approval
            else CapabilitySelfApprovalPolicy.NOT_APPLICABLE
        ),
        self_approval_binding=(
            CapabilitySelfApprovalBinding.PENDING_PROTECTED_BINDING
            if self_approval
            else CapabilitySelfApprovalBinding.NOT_APPLICABLE
        ),
        risk=(
            CapabilityRisk.SERVICE_PRIVILEGED
            if service_only
            else (
                CapabilityRisk.HIGH
                if action in HIGH_RISK_ACTIONS
                else (
                    CapabilityRisk.STANDARD
                    if action in STANDARD_RISK_ACTIONS
                    else CapabilityRisk.ELEVATED
                )
            )
        ),
    )


_DECLARED_CAPABILITIES = (
    _metadata(Action.CATALOG_SEARCH, "catalog", "카탈로그 검색", "권한 범위 내 자산을 검색합니다."),
    _metadata(
        Action.CATALOG_READ,
        "catalog",
        "카탈로그 조회",
        "권한 범위 내 자산 상세와 메타데이터를 조회합니다.",
    ),
    _metadata(
        Action.CATALOG_QUARANTINE_READ,
        "catalog",
        "격리 자산 검토",
        "분류 대기 중인 격리 자산을 관리자 검토 경계에서 조회합니다.",
    ),
    _metadata(
        Action.CATALOG_LINEAGE_READ,
        "catalog",
        "Lineage 조회",
        "권한 범위 내 자산 lineage를 조회합니다.",
    ),
    _metadata(
        Action.CATALOG_SYNC,
        "catalog",
        "카탈로그 동기화",
        "검증된 source에서 카탈로그 projection 동기화를 요청합니다.",
    ),
    _metadata(
        Action.CATALOG_EXPORT,
        "catalog",
        "카탈로그 내보내기",
        "권한과 분류정책이 허용한 카탈로그 결과를 내보냅니다.",
    ),
    _metadata(
        Action.REGISTRATION_CREATE,
        "registration",
        "등록 생성",
        "수동 또는 파일 기반 등록을 생성합니다.",
    ),
    _metadata(
        Action.REGISTRATION_READ,
        "registration",
        "등록 조회",
        "등록 manifest와 처리 상태를 조회합니다.",
    ),
    _metadata(
        Action.REGISTRATION_VALIDATE,
        "registration",
        "등록 검증",
        "등록 입력의 검증과 promotion 준비를 수행합니다.",
    ),
    _metadata(Action.CHANGE_CREATE, "change", "변경 요청 생성", "typed 변경 요청을 생성합니다."),
    _metadata(
        Action.CHANGE_RAW_CREATE,
        "change",
        "Raw 변경 요청 생성",
        "복구용 raw provider 변경 요청을 강한 human 권한 경계에서 생성합니다.",
    ),
    _metadata(
        Action.CHANGE_READ,
        "change",
        "변경 요청 조회",
        "권한 범위 내 변경 요청과 증적을 조회합니다.",
    ),
    _metadata(
        Action.CHANGE_EDIT,
        "change",
        "변경 요청 편집",
        "허용된 상태의 변경 요청과 첨부 증적을 편집합니다.",
    ),
    _metadata(
        Action.CHANGE_REVIEW,
        "change",
        "변경 요청 검토",
        "변경 요청의 검토 및 시험 단계를 판단합니다.",
    ),
    _metadata(
        Action.CHANGE_APPROVE,
        "change",
        "변경 요청 최종 승인",
        "변경 요청의 최종 승인 결정을 기록합니다.",
    ),
    _metadata(
        Action.CHANGE_RETRY,
        "change",
        "변경 적용 재시도",
        "실패한 변경 적용을 통제된 경로로 재시도합니다.",
    ),
    _metadata(
        Action.KG_CREATE, "knowledge", "지식 그래프 생성", "지식 그래프와 Draft를 생성합니다."
    ),
    _metadata(
        Action.KG_READ,
        "knowledge",
        "지식 그래프 조회",
        "권한 범위 내 지식 그래프와 Release를 조회합니다.",
    ),
    _metadata(
        Action.KG_EDIT,
        "knowledge",
        "지식 그래프 편집",
        "Draft, schema, mapping 및 delivery 설정을 편집합니다.",
    ),
    _metadata(
        Action.KG_REVIEW,
        "knowledge",
        "지식 변경 검토",
        "지식 changeset 또는 Studio Draft를 검토합니다.",
    ),
    _metadata(
        Action.KG_PUBLISH,
        "knowledge",
        "지식 Release 배포",
        "검토된 지식 snapshot을 Release로 배포합니다.",
    ),
    _metadata(
        Action.KG_EXPORT,
        "knowledge",
        "지식 그래프 내보내기",
        "권한 범위 내 Release snapshot을 내보냅니다.",
    ),
    _metadata(
        Action.KG_INGEST_EXECUTE,
        "knowledge",
        "지식 ingestion 실행",
        "전용 ingestion worker가 고정 계약을 실행합니다.",
    ),
    _metadata(
        Action.KG_PROPOSAL_EXECUTE,
        "knowledge",
        "지식 proposal 실행",
        "전용 proposal worker가 bounded proposal을 생성합니다.",
    ),
    _metadata(
        Action.CHAT_QUERY,
        "chat",
        "Chat 질의",
        "권한과 분류정책 범위 내 근거로 Chat 질의를 수행합니다.",
    ),
    _metadata(
        Action.ATTACHMENT_DOWNLOAD,
        "governance_documents",
        "첨부파일 다운로드",
        "권한이 확인된 문서 첨부파일을 다운로드합니다.",
    ),
    _metadata(
        Action.SHARING_PUBLISH,
        "delivery",
        "API product 배포",
        "소유한 API product version을 배포합니다.",
    ),
    _metadata(
        Action.SHARING_MANAGE,
        "delivery",
        "API product 관리",
        "API product와 consumer grant를 관리합니다.",
    ),
    _metadata(
        Action.SHARING_INVOKE,
        "delivery",
        "API product 호출",
        "승인된 contract와 quota로 API product를 호출합니다.",
    ),
    _metadata(
        Action.DASHBOARD_READ, "dashboard", "대시보드 조회", "공통 업무 대시보드를 조회합니다."
    ),
    _metadata(
        Action.OPERATIONS_READ,
        "operations",
        "운영 상태 조회",
        "worker와 integration 운영 상태를 조회합니다.",
    ),
    _metadata(
        Action.OPERATIONS_RETRY,
        "operations",
        "운영 작업 재시도",
        "재시도 가능한 실패 작업을 통제된 경로로 재시도합니다.",
    ),
    _metadata(
        Action.AUDIT_READ,
        "audit",
        "감사 증적 조회",
        "Workspace 범위의 감사 및 정책 결정 증적을 조회합니다.",
    ),
    _metadata(
        Action.ADMIN_MANAGE,
        "admin",
        "Workspace 관리",
        "권한 있는 human Admin이 보안 및 관리 control-plane을 운영합니다.",
    ),
    _metadata(
        Action.RETENTION_READ,
        "retention",
        "보존정책 조회",
        "보존정책, Legal Hold와 삭제 요청을 조회합니다.",
    ),
    _metadata(
        Action.RETENTION_MANAGE, "retention", "보존정책 관리", "보존정책을 제안하고 결정합니다."
    ),
    _metadata(
        Action.LEGAL_HOLD_PLACE, "retention", "Legal Hold 설정", "대상에 Legal Hold를 설정합니다."
    ),
    _metadata(
        Action.LEGAL_HOLD_RELEASE,
        "retention",
        "Legal Hold 해제",
        "Legal Hold 해제 요청과 결정을 처리합니다.",
    ),
    _metadata(
        Action.ERASURE_REQUEST, "retention", "삭제 요청", "보존정책에 묶인 삭제 요청을 생성합니다."
    ),
    _metadata(
        Action.ERASURE_APPROVE,
        "retention",
        "삭제 승인",
        "삭제 요청에 대한 승인 또는 거절을 기록합니다.",
    ),
    _metadata(
        Action.ARCHIVE_READ, "retention", "Archive 조회", "보존 archive의 제한된 증적을 조회합니다."
    ),
    _metadata(
        Action.QUALITY_READ,
        "quality",
        "품질 현황 조회",
        "품질 현황, Rule, Run과 Issue를 조회합니다.",
    ),
    _metadata(
        Action.QUALITY_PROFILE_READ,
        "quality",
        "Profile 조회",
        "DataHub Profile 기반 품질 통계를 조회합니다.",
    ),
    _metadata(
        Action.QUALITY_RULE_PROPOSE,
        "quality",
        "품질 Rule 제안",
        "typed 품질 Rule Set version을 제안합니다.",
    ),
    _metadata(
        Action.QUALITY_RULE_REVIEW,
        "quality",
        "품질 Rule 검토",
        "제안된 Rule Set version을 검토합니다.",
    ),
    _metadata(
        Action.QUALITY_RULE_ACTIVATE,
        "quality",
        "품질 Rule 활성화",
        "승인된 Rule Set version을 활성화합니다.",
    ),
    _metadata(
        Action.QUALITY_RULE_REVOKE,
        "quality",
        "품질 Rule 폐기",
        "활성 Rule Set version을 폐기합니다.",
    ),
    _metadata(
        Action.QUALITY_RULE_ARCHIVE, "quality", "품질 Rule 보관", "비활성 Rule Set을 archive합니다."
    ),
    _metadata(
        Action.QUALITY_RUN_REQUEST,
        "quality",
        "품질 Run 요청",
        "활성 Rule을 사용한 수동 품질 Run을 요청합니다.",
    ),
    _metadata(
        Action.QUALITY_RUN_CANCEL,
        "quality",
        "품질 Run 취소",
        "취소 가능한 품질 Run을 취소 요청합니다.",
    ),
    _metadata(
        Action.QUALITY_RUN_RETRY,
        "quality",
        "품질 Run 재시도",
        "재시도 가능한 품질 Run을 다시 요청합니다.",
    ),
    _metadata(
        Action.QUALITY_OPERATIONS_READ,
        "quality",
        "품질 운영 조회",
        "품질 worker와 실행 지연 상태를 조회합니다.",
    ),
    _metadata(
        Action.QUALITY_AUDIT_READ,
        "quality",
        "품질 감사 조회",
        "품질 Rule과 Run의 감사 증적을 조회합니다.",
    ),
    _metadata(
        Action.QUALITY_DISPATCH,
        "quality",
        "품질 Run dispatch",
        "전용 dispatcher가 승인된 Run을 worker에 전달합니다.",
    ),
    _metadata(
        Action.QUALITY_EXECUTE,
        "quality",
        "품질 Run 실행",
        "전용 quality worker가 고정 GX 계약을 실행합니다.",
    ),
    _metadata(
        Action.CATALOG_PROFILE_COLLECT,
        "catalog",
        "Catalog Profile 수집",
        "전용 collector가 source Profile을 수집합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_DOCUMENT_READ,
        "governance",
        "정책 문서 조회",
        "권한 범위 내 Governance Document를 조회합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_DOCUMENT_HISTORY_READ,
        "governance",
        "정책 문서 이력 조회",
        "정책 문서의 version과 review 이력을 조회합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_DOCUMENT_CREATE,
        "governance",
        "정책 문서 생성",
        "Governance Document Draft를 생성합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_DOCUMENT_EDIT,
        "governance",
        "정책 문서 편집",
        "Governance Document Draft version을 편집합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_DOCUMENT_REVIEW,
        "governance",
        "정책 문서 검토",
        "제출된 Governance Document version을 검토합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_DOCUMENT_PUBLISH,
        "governance",
        "정책 문서 게시",
        "승인된 Governance Document version을 게시합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_DOCUMENT_ARCHIVE,
        "governance",
        "정책 문서 보관",
        "게시된 Governance Document를 archive합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_TEMPLATE_READ,
        "governance",
        "정책 Template 조회",
        "Governance Template과 version을 조회합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_TEMPLATE_PROPOSE,
        "governance",
        "정책 Template 제안",
        "Governance Template Draft version을 제안합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_TEMPLATE_REVIEW,
        "governance",
        "정책 Template 검토",
        "제안된 Governance Template version을 검토합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_TEMPLATE_ACTIVATE,
        "governance",
        "정책 Template 활성화",
        "승인된 Governance Template version을 활성화합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_TEMPLATE_ARCHIVE,
        "governance",
        "정책 Template 보관",
        "Governance Template을 archive합니다.",
    ),
    _metadata(
        Action.GOVERNANCE_KNOWLEDGE_READ,
        "governance",
        "정책 지식 조회",
        "게시된 정책 지식 projection과 검색 근거를 조회합니다.",
    ),
)


def validate_capability_catalog(
    entries: tuple[CapabilityMetadata, ...],
) -> tuple[CapabilityMetadata, ...]:
    declared_actions = tuple(entry.action for entry in entries)
    if len(declared_actions) != len(set(declared_actions)):
        raise RuntimeError("The capability catalog contains a duplicate Action.")
    missing = set(Action) - set(declared_actions)
    extra = set(declared_actions) - set(Action)
    if missing or extra:
        raise RuntimeError(
            "The capability catalog must contain every Action exactly once: "
            f"missing={sorted(action.value for action in missing)}, "
            f"extra={sorted(action.value for action in extra)}"
        )
    service_keys = {service.service_key for service in CAPABILITY_SERVICES}
    if len(service_keys) != len(CAPABILITY_SERVICES) or any(
        not service.label.strip() or not service.description.strip()
        for service in CAPABILITY_SERVICES
    ):
        raise RuntimeError("The capability service catalog contains invalid metadata.")
    used_service_keys = {entry.service_key for entry in entries}
    if used_service_keys != service_keys:
        raise RuntimeError(
            "The capability service catalog is incomplete or contains an unused key."
        )
    service_actions = {
        entry.action
        for entry in entries
        if entry.actor_kind is CapabilityActorKind.SERVICE_PRINCIPAL
    }
    if service_actions != set(SERVICE_ONLY_ACTIONS):
        raise RuntimeError("The capability catalog service-only partition is invalid.")
    default_admin_actions = {entry.action for entry in entries if entry.default_admin}
    if default_admin_actions != set(Action) - set(SERVICE_ONLY_ACTIONS):
        raise RuntimeError("The default human Admin partition is invalid.")
    for entry in entries:
        if not entry.label.strip() or not entry.description.strip():
            raise RuntimeError(f"The labels for {entry.action.value} are invalid.")
        service_only = entry.action in SERVICE_ONLY_ACTIONS
        if service_only != (entry.actor_kind is CapabilityActorKind.SERVICE_PRINCIPAL):
            raise RuntimeError(f"The actor metadata for {entry.action.value} is invalid.")
        if service_only != (entry.assignability is CapabilityAssignability.SERVICE_PRINCIPAL_ONLY):
            raise RuntimeError(f"The assignability metadata for {entry.action.value} is invalid.")
        if entry.default_admin == service_only:
            raise RuntimeError(f"The default Admin metadata for {entry.action.value} is invalid.")
        high_risk = entry.action in HIGH_RISK_ACTIONS
        expected_assurance = (
            CapabilityAssurance.NOT_APPLICABLE
            if service_only
            else (
                CapabilityAssurance.FRESH_PHISHING_RESISTANT
                if high_risk
                else CapabilityAssurance.SESSION
            )
        )
        if entry.assurance is not expected_assurance:
            raise RuntimeError(f"The assurance metadata for {entry.action.value} is invalid.")
        reason_required = entry.action in REASON_REQUIRED_ACTIONS
        if reason_required != (entry.reason_policy is CapabilityReasonPolicy.REQUIRED):
            raise RuntimeError(f"The reason metadata for {entry.action.value} is invalid.")
        self_approval = entry.action in SELF_APPROVAL_CANDIDATE_ACTIONS
        expected_self_approval_policy = (
            CapabilitySelfApprovalPolicy.CANONICAL_ADMIN_ONLY
            if self_approval
            else CapabilitySelfApprovalPolicy.NOT_APPLICABLE
        )
        expected_self_approval_binding = (
            CapabilitySelfApprovalBinding.PENDING_PROTECTED_BINDING
            if self_approval
            else CapabilitySelfApprovalBinding.NOT_APPLICABLE
        )
        if (
            entry.self_approval_policy is not expected_self_approval_policy
            or entry.self_approval_binding is not expected_self_approval_binding
        ):
            raise RuntimeError(
                f"The pending self-approval metadata for {entry.action.value} is invalid."
            )
        expected_risk = (
            CapabilityRisk.SERVICE_PRIVILEGED
            if service_only
            else (
                CapabilityRisk.HIGH
                if high_risk
                else (
                    CapabilityRisk.STANDARD
                    if entry.action in STANDARD_RISK_ACTIONS
                    else CapabilityRisk.ELEVATED
                )
            )
        )
        if entry.risk is not expected_risk:
            raise RuntimeError(f"The risk metadata for {entry.action.value} is invalid.")
    return tuple(sorted(entries, key=lambda entry: entry.action.value))


def validate_protected_capabilities(
    entries: tuple[ProtectedCapabilityMetadata, ...],
) -> tuple[ProtectedCapabilityMetadata, ...]:
    expected_keys = {"admin.self_approve"}
    declared_keys = tuple(entry.capability_key for entry in entries)
    if len(declared_keys) != len(set(declared_keys)):
        raise RuntimeError("The protected capability catalog contains a duplicate key.")
    if set(declared_keys) != expected_keys:
        raise RuntimeError(
            "The protected capability catalog is incomplete or contains an extra key."
        )
    service_keys = {service.service_key for service in CAPABILITY_SERVICES}
    for entry in entries:
        if (
            entry.service_key not in service_keys
            or not entry.label.strip()
            or not entry.description.strip()
        ):
            raise RuntimeError(f"The protected capability {entry.capability_key} is invalid.")
        if (
            entry.actor_kind is not CapabilityActorKind.HUMAN
            or entry.assignability is not CapabilityAssignability.CANONICAL_ADMIN_ONLY
            or not entry.default_admin
            or entry.assurance is not CapabilityAssurance.FRESH_PHISHING_RESISTANT
            or entry.reason_policy is not CapabilityReasonPolicy.REQUIRED
            or entry.self_approval_policy is not CapabilitySelfApprovalPolicy.CANONICAL_ADMIN_ONLY
            or entry.self_approval_binding
            is not CapabilitySelfApprovalBinding.PENDING_PROTECTED_BINDING
            or entry.risk is not CapabilityRisk.HIGH
        ):
            raise RuntimeError(
                f"The protected capability metadata for {entry.capability_key} is invalid."
            )
    return tuple(sorted(entries, key=lambda entry: entry.capability_key))


CAPABILITY_CATALOG = validate_capability_catalog(_DECLARED_CAPABILITIES)
PROTECTED_ADMIN_CAPABILITIES = validate_protected_capabilities(_DECLARED_PROTECTED_CAPABILITIES)
CAPABILITY_BY_ACTION = {entry.action: entry for entry in CAPABILITY_CATALOG}
DEFAULT_HUMAN_ADMIN_ACTIONS = frozenset(
    entry.action for entry in CAPABILITY_CATALOG if entry.default_admin
)
CUSTOM_ROLE_ASSIGNABLE_ACTIONS = frozenset(
    entry.action
    for entry in CAPABILITY_CATALOG
    if entry.assignability is CapabilityAssignability.HUMAN_ROLE
)
CANONICAL_ADMIN_CAPABILITY_DOCUMENT = {
    "catalog_version": CAPABILITY_CATALOG_VERSION,
    "role_kind": AccessRoleKind.CANONICAL_ADMIN.value,
    "role_key": CANONICAL_ADMIN_ROLE_KEY,
    "clearance": "RESTRICTED",
    "groups": ["security-administrators"],
    "allowed_actions": sorted(action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS),
    "denied_actions": [],
}
CANONICAL_ADMIN_CAPABILITY_HASH = canonical_json_hash(CANONICAL_ADMIN_CAPABILITY_DOCUMENT)


def forbidden_custom_role_actions(actions: frozenset[Action]) -> tuple[Action, ...]:
    return tuple(sorted(actions - CUSTOM_ROLE_ASSIGNABLE_ACTIONS, key=lambda action: action.value))
