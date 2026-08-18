import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { Page } from '../../app/navigation'
import { PageTitle } from '../../components/layout/PageTitle'
import { KnowledgeChatContent } from './KnowledgeChatPage'
import { KnowledgeRegistry } from './KnowledgeRegistry'
import { KnowledgeInformationManagementPage } from './KnowledgeInformationManagementPage'
import { KnowledgeWorkspaceLayout, type KnowledgeWorkspaceSection } from './KnowledgeWorkspaceLayout'
import { KnowledgeStudioPage } from './studio/KnowledgeStudioPage'

type KnowledgePage = Extract<
  Page,
  | 'knowledge'
  | 'knowledge-chat'
  | 'knowledge-instances'
  | 'knowledge-profiles'
  | 'knowledge-studio'
>

interface KnowledgeWorkspacePageProps {
  page: KnowledgePage
  client: ApiClient
  workspaceId: string
  subjectId: string
  locationRevision: number
  canManage: boolean
  canReview: boolean
  onNavigate: (page: Page) => void
  onOpenStudio: (assetId?: string, status?: string) => void
  onStepUp?: () => Promise<void>
  onPasswordReauth?: () => Promise<void>
  onEnroll?: () => Promise<void>
  hardwareWebauthnEnabled?: boolean
}

function activeSection(page: KnowledgePage): KnowledgeWorkspaceSection {
  if (page === 'knowledge-chat') return 'CHAT'
  if (page === 'knowledge-instances') return 'INFORMATION'
  if (page === 'knowledge-profiles') return 'INFORMATION'
  if (page === 'knowledge-studio') return 'STUDIO'
  return 'REGISTRY'
}

export function KnowledgeWorkspacePage({
  page,
  client,
  workspaceId,
  subjectId,
  locationRevision,
  canManage,
  canReview,
  onNavigate,
  onOpenStudio,
  onStepUp,
  onPasswordReauth,
  onEnroll,
  hardwareWebauthnEnabled,
}: KnowledgeWorkspacePageProps) {
  const [registryRevision, setRegistryRevision] = useState(0)
  const query = new URLSearchParams(window.location.search)
  const requestedInformationTab = query.get('information_tab')
  const informationTab = requestedInformationTab === 'instances'
    ? 'INSTANCES'
    : page === 'knowledge-profiles'
      ? 'PROFILES'
      : 'DOMAINS'
  const focusedAssetId = query.get('asset_id') ?? undefined
  const focusedChangesetId = query.get('changeset_id') ?? undefined

  return (
    <section className="grid gap-4">
      <PageTitle
        icon="KG"
        eyebrow="Versioned Knowledge Asset Management"
        title="지식관리"
        description="검증된 지식 에셋, 온톨로지 changeset, 불변 릴리스와 별도 GraphRAG 질의를 관리합니다."
        actions={page === 'knowledge'
          ? (
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setRegistryRevision((current) => current + 1)}
              >
                <RefreshCw size={14} /> 새로고침
              </button>
            )
          : undefined}
      />
      <KnowledgeWorkspaceLayout activeSection={activeSection(page)} onNavigate={onNavigate}>
        {page === 'knowledge' && (
          <div key={registryRevision}>
            <KnowledgeRegistry
              client={client}
              onCreate={() => onOpenStudio()}
              onEdit={onOpenStudio}
              canManage={canManage}
              canArchive={canReview}
            />
          </div>
        )}
        {page === 'knowledge-chat' && <KnowledgeChatContent client={client} />}
        {(page === 'knowledge-instances' || page === 'knowledge-profiles') && (
          <KnowledgeInformationManagementPage
            client={client}
            onStepUp={onStepUp}
            onPasswordReauth={onPasswordReauth}
            onEnroll={onEnroll}
            hardwareWebauthnEnabled={hardwareWebauthnEnabled}
            onEditAsset={onOpenStudio}
            initialTab={informationTab}
            initialAssetId={focusedAssetId}
            initialChangesetId={focusedChangesetId}
          />
        )}
        {page === 'knowledge-studio' && (
          <KnowledgeStudioPage
            client={client}
            workspaceId={workspaceId}
            subjectId={subjectId}
            locationRevision={locationRevision}
            onNavigate={onNavigate}
            onStepUp={onStepUp}
            onPasswordReauth={onPasswordReauth}
            onEnroll={onEnroll}
            hardwareWebauthnEnabled={hardwareWebauthnEnabled}
          />
        )}
      </KnowledgeWorkspaceLayout>
    </section>
  )
}
