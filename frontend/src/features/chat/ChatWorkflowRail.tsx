import {
  BadgeCheck,
  Database,
  Gauge,
  Route,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  WandSparkles,
  type LucideIcon,
} from 'lucide-react'
import type { ChatWorkflowStep } from '../../api/types'

const labels: Record<ChatWorkflowStep['stage'], string> = {
  AUTHORIZATION: '권한 확인',
  BUDGET_RESERVATION: '예산 예약',
  ROUTING: '경로 결정',
  RETRIEVAL: '근거 검색',
  RERANKING: '근거 정렬',
  COMPOSITION: '답변 생성',
  CITATION_VALIDATION: '인용 검증',
  PERSISTENCE: '대화 저장',
}

const icons: Record<ChatWorkflowStep['stage'], LucideIcon> = {
  AUTHORIZATION: ShieldCheck,
  BUDGET_RESERVATION: Gauge,
  ROUTING: Route,
  RETRIEVAL: Search,
  RERANKING: SlidersHorizontal,
  COMPOSITION: WandSparkles,
  CITATION_VALIDATION: BadgeCheck,
  PERSISTENCE: Database,
}

const detailLabels: Partial<Record<string, string>> = {
  CHAT_QUERY_AUTHORIZED: '질문 실행 권한을 확인했습니다.',
  CHAT_RATE_AND_TOKEN_BUDGET_RESERVED: '요청 및 토큰 예산을 예약했습니다.',
  INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE: '승인된 추론 프로필 연결이 필요합니다.',
  GRAPH_ADAPTER_UNAVAILABLE: 'Asset Graph 어댑터가 준비되지 않았습니다.',
  VECTOR_ADAPTER_UNAVAILABLE: '벡터 검색 어댑터가 준비되지 않았습니다.',
  GENERAL_ROUTE_SELECTED: '일반 카탈로그 검색 경로를 선택했습니다.',
  VECTOR_ROUTE_SELECTED: '벡터 검색 경로를 선택했습니다.',
  GRAPH_ROUTE_SELECTED: 'Asset Graph 검색 경로를 선택했습니다.',
  GENERAL_RETRIEVAL_COMPLETED: '일반 카탈로그 근거 검색을 완료했습니다.',
  VECTOR_RETRIEVAL_COMPLETED: '벡터 근거 검색을 완료했습니다.',
  GRAPH_RETRIEVAL_COMPLETED: 'Asset Graph 근거 검색을 완료했습니다.',
  GENERAL_RETRIEVAL_FAILED: '일반 카탈로그 근거 검색에 실패했습니다.',
  VECTOR_RETRIEVAL_FAILED: '벡터 근거 검색에 실패했습니다.',
  GRAPH_RETRIEVAL_FAILED: 'Asset Graph 근거 검색에 실패했습니다.',
  RETRIEVAL_NOT_EXECUTED: '근거 검색을 실행하지 않았습니다.',
  RETRIEVAL_FAILED: '근거 검색에 실패했습니다.',
  RETRIEVAL_FAILURE_REFUSED: '근거 검색 실패로 답변 생성을 중단했습니다.',
  NO_RETRIEVED_EVIDENCE: '검색된 근거가 없어 정렬을 건너뛰었습니다.',
  RERANKER_NOT_CONFIGURED: '검색 순위를 그대로 사용했습니다.',
  EVIDENCE_RERANKED: '인가된 근거 순위를 다시 계산했습니다.',
  RERANKER_FAILED: '근거 순위 계산에 실패했습니다.',
  RERANKER_FAILURE_REFUSED: '근거 순위 검증 실패로 답변 생성을 중단했습니다.',
  NO_AUTHORIZED_EVIDENCE: '인가된 사내 근거가 없습니다.',
  COMPOSER_FAILED: '근거 기반 답변 작성에 실패했습니다.',
  GENERAL_KNOWLEDGE_COMPOSER_FAILED: '일반 지식 답변 작성에 실패했습니다.',
  INVALID_GENERAL_KNOWLEDGE_DRAFT: '일반 지식 답변 형식 검증에 실패했습니다.',
  GROUNDED_DRAFT_COMPOSED: '인가된 근거로 답변 초안을 작성했습니다.',
  GENERAL_KNOWLEDGE_DRAFT_COMPOSED: '사내 근거와 분리된 일반 지식 답변을 작성했습니다.',
  NO_DRAFT: '검증할 답변 초안이 없습니다.',
  CITATIONS_VALIDATED: '인용 근거와 최종 권한을 검증했습니다.',
  NO_INTERNAL_CITATIONS_GENERAL_ANSWER: '일반 지식 답변이므로 사내 인용이 없습니다.',
  UNAVAILABLE_ROUTE_REFUSED: '사용할 수 없는 검색 경로입니다.',
  INVALID_REVOKED_OR_MISSING_CITATIONS: '인용 근거가 최종 검증을 통과하지 못했습니다.',
  RETENTION_BOUND_EXCHANGE_PERSISTED: '보존정책에 따라 대화를 저장했습니다.',
  EPHEMERAL_NO_STORE: '활성 보존정책이 없어 저장하지 않았습니다.',
  AUTHORIZED: '질문 실행 권한을 확인했습니다.',
  BUDGET_RESERVED: '요청 및 토큰 예산을 예약했습니다.',
  VECTOR_SELECTED: '벡터 검색 경로를 선택했습니다.',
  EVIDENCE_FOUND: '인가된 근거를 찾았습니다.',
  RERANKED: '인가된 근거 순위를 계산했습니다.',
  ANSWER_COMPOSED: '근거 기반 답변을 작성했습니다.',
  CITATIONS_VALID: '인용 근거를 검증했습니다.',
  PERSISTED: '보존정책에 따라 대화를 저장했습니다.',
}

const statusLabels: Record<ChatWorkflowStep['status'], string> = {
  COMPLETED: '완료',
  SKIPPED: '건너뜀',
  UNAVAILABLE: '사용 불가',
  FAILED: '실패',
  REFUSED: '중단',
}

function statusClass(status: ChatWorkflowStep['status']): string {
  if (status === 'COMPLETED') return 'is-completed'
  if (status === 'SKIPPED') return 'is-skipped'
  if (status === 'UNAVAILABLE') return 'is-unavailable'
  return 'is-failed'
}

export function ChatWorkflowRail({ steps }: { steps: ChatWorkflowStep[] }) {
  if (steps.length === 0) {
    return <p className="chat-evidence-empty">서버가 응답하면 실제 처리 단계가 표시됩니다.</p>
  }
  return (
    <ol aria-label="질문 응답 Workflow" className="chat-workflow-rail">
      {steps.map((step, index) => {
        const Icon = icons[step.stage]
        const detail = detailLabels[step.detail_code] ?? '서버가 반환한 처리 상태입니다.'
        return (
          <li
            className={statusClass(step.status)}
            key={`${step.stage}-${index}`}
            title={`${labels[step.stage]} · ${statusLabels[step.status]}\n${detail}`}
          >
            {index < steps.length - 1 && <span aria-hidden="true" className="chat-workflow-edge" />}
            <div className="chat-workflow-node">
              <Icon aria-hidden="true" size={15} />
            </div>
            <strong>{labels[step.stage]}</strong>
            <small>{statusLabels[step.status]}</small>
            <span className="chat-workflow-tooltip" role="tooltip">
              <b>{index + 1}. {labels[step.stage]}</b>
              {detail}
              <code>{step.detail_code}</code>
            </span>
          </li>
        )
      })}
    </ol>
  )
}
