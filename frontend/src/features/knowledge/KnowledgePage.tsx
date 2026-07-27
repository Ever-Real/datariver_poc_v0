import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { Page } from '../../app/navigation'
import { PageTitle } from '../../components/layout/PageTitle'
import { KnowledgeRegistry } from './KnowledgeRegistry'
import { KnowledgeWorkspaceLayout } from './KnowledgeWorkspaceLayout'

export function KnowledgePage({ client, onNavigate }: { client: ApiClient; onNavigate: (page: Page) => void }) {
  const [revision, setRevision] = useState(0)
  return <section className="grid gap-4">
    <PageTitle
      icon="KG"
      eyebrow="Versioned Knowledge Asset Management"
      title="지식관리"
      description="검증된 지식 에셋, 온톨로지 changeset, 불변 릴리스와 별도 GraphRAG 질의를 관리합니다."
      actions={<button type="button" className="button button-secondary" onClick={() => setRevision((current) => current + 1)}><RefreshCw size={14} /> 새로고침</button>}
    />
    <KnowledgeWorkspaceLayout activeSection="REGISTRY" onNavigate={onNavigate}>
      <div key={revision}>
        <KnowledgeRegistry client={client} onCreate={() => onNavigate('knowledge-studio')} />
      </div>
    </KnowledgeWorkspaceLayout>
  </section>
}
