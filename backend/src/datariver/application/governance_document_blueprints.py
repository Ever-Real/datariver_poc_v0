from __future__ import annotations

from dataclasses import dataclass

from datariver.application.governance_document_formats import (
    prepare_governance_document_html,
)
from datariver.domain.governance_documents import (
    GovernanceDocumentBlueprint,
    GovernanceDocumentBlueprintPurpose,
    GovernanceDocumentCategory,
)

BLUEPRINT_CATALOG_VERSION = "GOVERNANCE_DOCUMENT_BLUEPRINTS_V2"


@dataclass(frozen=True, slots=True)
class _BlueprintSource:
    blueprint_id: str
    purpose: GovernanceDocumentBlueprintPurpose
    category: GovernanceDocumentCategory
    title: str
    summary: str
    applicability_scope: str
    html: str


_SOURCES = (
    _BlueprintSource(
        blueprint_id="policy-v1",
        purpose=GovernanceDocumentBlueprintPurpose.TEMPLATE,
        category=GovernanceDocumentCategory.POLICY,
        title="정책 문서 기본 양식",
        summary="목적, 적용 범위, 책임, 통제 항목과 예외 절차를 포함하는 정책 문서 양식",
        applicability_scope="적용 조직, 시스템, 데이터 범위와 제외 대상을 명시합니다.",
        html=(
            "<h1>정책명</h1>"
            "<h2>1. 목적</h2><p>정책이 해결하는 위험과 달성 목표를 작성합니다.</p>"
            "<h2>2. 적용 범위</h2><p>적용 조직, 시스템, 데이터와 예외 범위를 작성합니다.</p>"
            "<h2>3. 역할과 책임</h2>"
            '<table><thead><tr><th scope="col">역할</th><th scope="col">책임</th></tr>'
            "</thead><tbody><tr><td>정책 소유자</td><td>승인, 정기 검토와 예외 판단</td></tr>"
            "<tr><td>실행 책임자</td><td>통제 이행과 증적 관리</td></tr></tbody></table>"
            "<h2>4. 정책 및 통제</h2><ol><li>통제 요구사항을 작성합니다.</li>"
            "<li>측정 가능한 준수 기준을 작성합니다.</li></ol>"
            "<h2>5. 예외와 위반 처리</h2><p>예외 승인, 만료, 시정 조치 절차를 작성합니다.</p>"
            "<h2>6. 검토 주기</h2><p>정기 검토 주기와 재승인 조건을 작성합니다.</p>"
        ),
    ),
    _BlueprintSource(
        blueprint_id="standard-terminology-v1",
        purpose=GovernanceDocumentBlueprintPurpose.TEMPLATE,
        category=GovernanceDocumentCategory.STANDARD_TERMINOLOGY,
        title="표준어 사전 기본 양식",
        summary="표준 용어의 정의, 허용어, 금칙어, 데이터 타입과 관리 책임을 기록하는 양식",
        applicability_scope="표준 용어를 적용할 업무 도메인과 데이터 자산 범위를 명시합니다.",
        html=(
            "<h1>표준어 사전</h1>"
            "<h2>1. 사전 운영 원칙</h2>"
            "<p>용어 등록, 변경, 폐기와 동의어 관리 원칙을 작성합니다.</p>"
            "<h2>2. 표준 용어</h2>"
            '<table><thead><tr><th scope="col">표준 용어</th>'
            '<th scope="col">영문명</th><th scope="col">정의</th>'
            '<th scope="col">허용 값/형식</th><th scope="col">소유자</th></tr></thead>'
            "<tbody><tr><td>예시 용어</td><td>EXAMPLE_TERM</td>"
            "<td>업무 의미를 모호하지 않게 작성합니다.</td>"
            "<td>데이터 타입, 길이 또는 코드 체계</td><td>관리 조직 또는 역할</td>"
            "</tr></tbody></table>"
            "<h2>3. 동의어 및 금칙어</h2>"
            '<table><thead><tr><th scope="col">표준 용어</th>'
            '<th scope="col">동의어</th><th scope="col">금칙어</th>'
            '<th scope="col">사유</th></tr></thead><tbody>'
            "<tr><td>예시 용어</td><td>허용 동의어</td><td>금칙 표현</td>"
            "<td>표준화 또는 규제 근거</td></tr></tbody></table>"
            "<h2>4. 변경 이력 기준</h2><p>변경 사유와 영향 자산 검토 기준을 작성합니다.</p>"
        ),
    ),
    _BlueprintSource(
        blueprint_id="security-guide-v1",
        purpose=GovernanceDocumentBlueprintPurpose.TEMPLATE,
        category=GovernanceDocumentCategory.SECURITY_GUIDE,
        title="보안 가이드 기본 양식",
        summary="위협 모델, 접근 통제, 암호화, 로깅, 사고 대응을 구조화하는 보안 가이드 양식",
        applicability_scope="보호 대상 시스템, 데이터 등급, 운영 환경과 담당 조직을 명시합니다.",
        html=(
            "<h1>보안 가이드</h1>"
            "<h2>1. 보호 대상과 위협 모델</h2>"
            "<p>자산, 신뢰 경계, 위협 행위자와 주요 위험을 작성합니다.</p>"
            "<h2>2. 데이터 분류와 처리</h2>"
            '<table><thead><tr><th scope="col">분류</th><th scope="col">처리 기준</th>'
            '<th scope="col">보존/폐기 근거</th></tr></thead><tbody>'
            "<tr><td>분류 등급</td><td>저장, 전송, 표시와 반출 통제</td>"
            "<td>승인된 정책 또는 법적 근거</td></tr></tbody></table>"
            "<h2>3. 인증과 접근 통제</h2><ul><li>최소 권한과 직무 분리를 작성합니다.</li>"
            "<li>강화 인증과 권한 재검토 조건을 작성합니다.</li></ul>"
            "<h2>4. 암호화와 비밀 관리</h2>"
            "<p>전송/저장 암호화, 키 수명주기와 비밀 회전 기준을 작성합니다.</p>"
            "<h2>5. 로깅과 모니터링</h2>"
            "<p>감사 이벤트, 경보 조건, 접근 제한과 검토 주기를 작성합니다.</p>"
            "<h2>6. 취약점 및 사고 대응</h2>"
            "<p>탐지, 격리, 보고, 복구와 사후 검토 절차를 작성합니다.</p>"
        ),
    ),
    _BlueprintSource(
        blueprint_id="starter-data-classification-access-v1",
        purpose=GovernanceDocumentBlueprintPurpose.STARTER_DOCUMENT,
        category=GovernanceDocumentCategory.POLICY,
        title="데이터 분류·접근 정책",
        summary="데이터 분류별 열람·검색·Chat 접근 경계와 승인 책임을 관리하는 기본 문서",
        applicability_scope="현재 Workspace의 데이터 자산, 검색, Chat 및 외부 제공 경로",
        html=(
            "<h1>데이터 분류·접근 정책</h1>"
            "<h2>1. 목적</h2><p>데이터 분류에 맞는 최소 권한과 승인된 이용 경계를 정의합니다.</p>"
            "<h2>2. 적용 범위</h2><p>현재 Workspace의 데이터 자산, 검색, Chat 및 "
            "반출 경로에 적용합니다.</p>"
            "<h2>3. 통제 원칙</h2><ol><li>분류 등급과 사용자 clearance를 함께 확인합니다.</li>"
            "<li>Workspace와 Domain/System 범위를 벗어난 접근을 허용하지 않습니다.</li>"
            "<li>권한 변경과 민감 작업은 감사 증거로 남깁니다.</li></ol>"
            "<h2>4. 예외</h2><p>예외는 목적·범위·만료일을 명시한 별도 승인으로 관리합니다.</p>"
        ),
    ),
    _BlueprintSource(
        blueprint_id="starter-retention-disposal-v1",
        purpose=GovernanceDocumentBlueprintPurpose.STARTER_DOCUMENT,
        category=GovernanceDocumentCategory.POLICY,
        title="보존·파기 정책",
        summary="데이터 클래스별 보존기간, Legal Hold 우선순위와 파기 승인 절차의 기본 문서",
        applicability_scope="현재 Workspace에서 생성·수집·처리·보관하는 데이터와 감사 증거",
        html=(
            "<h1>보존·파기 정책</h1>"
            "<h2>1. 목적</h2><p>업무·규제 근거에 따른 보존과 검증 가능한 "
            "파기 절차를 정의합니다.</p>"
            "<h2>2. 보존 원칙</h2><ol><li>승인된 데이터 클래스 계약의 최소·최대 "
            "기간을 준수합니다.</li>"
            "<li>Legal Hold가 활성화된 범위는 자동 파기에서 제외합니다.</li>"
            "<li>파기 전 승인과 대상 증거를 확인하고 실행 결과를 감사 기록으로 남깁니다.</li></ol>"
            "<h2>3. 검토 주기</h2><p>법규, 계약 또는 업무 목적 변경 시 재검토합니다.</p>"
        ),
    ),
    _BlueprintSource(
        blueprint_id="starter-legal-hold-management-v1",
        purpose=GovernanceDocumentBlueprintPurpose.STARTER_DOCUMENT,
        category=GovernanceDocumentCategory.POLICY,
        title="Legal Hold 관리",
        summary="보존 의무가 있는 데이터의 파기 보류, 범위 변경과 해제 결재를 관리하는 기본 문서",
        applicability_scope="소송·조사·감사·규제 대응으로 보존이 요구되는 현재 Workspace 데이터",
        html=(
            "<h1>Legal Hold 관리</h1>"
            "<h2>1. 목적</h2><p>법적 또는 조사상 보존 의무가 있는 데이터의 "
            "변경·파기를 중지합니다.</p>"
            "<h2>2. 등록</h2><p>근거, 대상 범위, 책임자, 시작일과 검토일을 "
            "명시하고 승인받습니다.</p>"
            "<h2>3. 운영</h2><ol><li>활성 Hold는 일반 보존·파기 정책보다 우선합니다.</li>"
            "<li>범위 변경과 해제는 독립 검토자의 결재를 거칩니다.</li>"
            "<li>등록·변경·해제 및 영향 대상은 감사 증거로 보존합니다.</li></ol>"
        ),
    ),
)


def governance_document_blueprints() -> tuple[GovernanceDocumentBlueprint, ...]:
    values: list[GovernanceDocumentBlueprint] = []
    for source in _SOURCES:
        content = prepare_governance_document_html(source.html)
        values.append(
            GovernanceDocumentBlueprint(
                blueprint_id=source.blueprint_id,
                blueprint_version=BLUEPRINT_CATALOG_VERSION,
                purpose=source.purpose,
                category=source.category,
                title=source.title,
                summary=source.summary,
                applicability_scope=source.applicability_scope,
                sanitized_html=content.sanitized_html,
                content_sha256=content.content_sha256,
                sanitizer_policy_version=content.sanitizer_policy_version,
                sanitizer_policy_sha256=content.sanitizer_policy_sha256,
            )
        )
    return tuple(values)
