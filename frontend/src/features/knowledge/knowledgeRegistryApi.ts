import type { ApiClient } from '../../api/client'
import type {
  KnowledgeAssetPage,
  KnowledgeAssetSummary,
  KnowledgeGraph,
} from '../../api/types'

export const KNOWLEDGE_ARCHIVE_CONFIRMATION = '정말 이 지식 자산을 삭제/아카이빙 하시겠습니까?'
const MAXIMUM_MANAGED_ASSETS = 10_000

export async function listKnowledgeAssetsByDomain(
  client: ApiClient,
  domainId: string,
  cursor?: string | null,
  signal?: AbortSignal,
): Promise<KnowledgeAssetPage> {
  const parameters = new URLSearchParams({
    domain_id: domainId,
    limit: '25',
    sort: 'NAME_ASC',
  })
  if (cursor) parameters.set('cursor', cursor)
  return client.request<KnowledgeAssetPage>(
    `/knowledge/registry/assets?${parameters}`,
    { cache: 'no-store', signal },
  )
}

export async function listAllKnowledgeAssets(
  client: ApiClient,
  signal?: AbortSignal,
): Promise<KnowledgeAssetSummary[]> {
  const items: KnowledgeAssetSummary[] = []
  const seenCursors = new Set<string>()
  let cursor: string | null = null
  do {
    const parameters = new URLSearchParams({ limit: '100', sort: 'NAME_ASC' })
    if (cursor) parameters.set('cursor', cursor)
    const page = await client.request<KnowledgeAssetPage>(
      `/knowledge/registry/assets?${parameters}`,
      { cache: 'no-store', signal },
    )
    items.push(...page.items)
    if (items.length > MAXIMUM_MANAGED_ASSETS) {
      throw new Error(
        `정보 관리 화면은 최대 ${MAXIMUM_MANAGED_ASSETS.toLocaleString()}개 Asset을 다룹니다.`,
      )
    }
    cursor = page.next_cursor
    if (cursor && seenCursors.has(cursor)) {
      throw new Error('Knowledge Asset 페이지 커서가 반복되었습니다.')
    }
    if (cursor) seenCursors.add(cursor)
  } while (cursor)
  return items
}

export async function archiveKnowledgeAsset(
  client: ApiClient,
  asset: Pick<KnowledgeGraph, 'id' | 'version'>,
  idempotencyKey: string = crypto.randomUUID(),
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
