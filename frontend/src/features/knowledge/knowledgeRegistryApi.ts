import type { ApiClient } from '../../api/client'
import type { KnowledgeGraph } from '../../api/types'

export const KNOWLEDGE_ARCHIVE_CONFIRMATION = '정말 이 지식 자산을 삭제/아카이빙 하시겠습니까?'

export async function archiveKnowledgeAsset(
  client: ApiClient,
  asset: KnowledgeGraph,
  idempotencyKey = crypto.randomUUID(),
): Promise<KnowledgeGraph> {
  return client.request<KnowledgeGraph>(
    `/knowledge/graphs/${encodeURIComponent(asset.id)}/archive`,
    {
      method: 'POST',
      body: JSON.stringify({ reason: KNOWLEDGE_ARCHIVE_CONFIRMATION }),
      cache: 'no-store',
      ifMatch: `"${asset.version}"`,
      idempotencyKey,
    },
  )
}
