import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { Page } from '../../app/navigation'
import { PageTitle } from '../../components/layout/PageTitle'
import { KnowledgeIngestionStudio } from './KnowledgeIngestionStudio'
import { KnowledgeRegistry } from './KnowledgeRegistry'
import { KnowledgeWorkspaceLayout } from './KnowledgeWorkspaceLayout'

type KnowledgeSection = 'REGISTRY' | 'INGESTION'

export function KnowledgePage({ client, onNavigate }: { client: ApiClient; onNavigate: (page: Page) => void }) {
  const [section, setSection] = useState<KnowledgeSection>('REGISTRY')
  const [revision, setRevision] = useState(0)
  return <section className="grid gap-4">
    <PageTitle
      icon="KG"
      eyebrow="Versioned Knowledge Asset Management"
      title="지식관리"
      description="검증된 지식 에셋, 온톨로지 changeset, 불변 릴리스와 별도 GraphRAG 질의를 관리합니다."
      actions={<button type="button" className="button button-secondary" onClick={() => setRevision((current) => current + 1)}><RefreshCw size={14} /> 새로고침</button>}
    />
    <KnowledgeWorkspaceLayout activeSection={section} onLocalSection={setSection} onNavigate={onNavigate}>
      <div key={`${section}:${revision}`}>
        {section === 'REGISTRY' ? <KnowledgeRegistry client={client} /> : <KnowledgeIngestionStudio client={client} />}
      </div>
    </KnowledgeWorkspaceLayout>
  </section>
}
