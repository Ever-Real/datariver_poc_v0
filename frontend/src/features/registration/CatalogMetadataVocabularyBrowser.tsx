import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import type { ApiClient } from '../../api/client'
import type {
  CatalogMetadataVocabularyItem,
  CatalogMetadataVocabularyKind,
  CatalogMetadataVocabularyPage,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const PAGE_LIMIT = 20
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_PATTERN = /^[0-9a-f]{64}$/

function boundedPage(
  value: CatalogMetadataVocabularyPage,
  expectedKind: CatalogMetadataVocabularyKind,
): CatalogMetadataVocabularyPage {
  if (
    !Array.isArray(value.items)
    || value.items.length > PAGE_LIMIT
    || value.items.some((item) => (
      item.kind !== expectedKind
      || !UUID_PATTERN.test(item.id)
      || !item.display_name
      || item.display_name !== item.display_name.trim()
      || item.display_name.length > 500
      || !SHA256_PATTERN.test(item.source_version)
    ))
    || !Number.isInteger(value.page.limit)
    || value.page.limit < 1
    || value.page.limit > PAGE_LIMIT
    || (value.page.next_cursor !== undefined && (
      !value.page.next_cursor
      || value.page.next_cursor.length > 2_000
    ))
  ) {
    throw new Error('통제 어휘 응답이 요청 범위와 일치하지 않습니다.')
  }
  return {
    items: value.items
      .map((item) => ({
        id: item.id,
        kind: item.kind,
        display_name: item.display_name.slice(0, 500),
        source_version: item.source_version.slice(0, 255),
      })),
    page: {
      limit: Math.min(value.page.limit, PAGE_LIMIT),
      ...(value.page.next_cursor
        ? { next_cursor: value.page.next_cursor.slice(0, 2_000) }
        : {}),
    },
  }
}

export function CatalogMetadataVocabularyBrowser({ client }: { client: ApiClient }) {
  const [kind, setKind] = useState<CatalogMetadataVocabularyKind>('TAG')
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState<CatalogMetadataVocabularyPage>()
  const [cursorStack, setCursorStack] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const [copiedId, setCopiedId] = useState<string>()
  const intent = useRef(0)
  const activeController = useRef<AbortController | undefined>(undefined)

  const load = useCallback(async (
    selectedKind: CatalogMetadataVocabularyKind,
    selectedQuery: string,
    cursor?: string,
  ) => {
    activeController.current?.abort()
    const controller = new AbortController()
    activeController.current = controller
    const expectedIntent = intent.current + 1
    intent.current = expectedIntent
    setBusy(true)
    setError(undefined)
    setCopiedId(undefined)
    try {
      const parameters = new URLSearchParams({
        kind: selectedKind,
        limit: String(PAGE_LIMIT),
      })
      if (selectedQuery) parameters.set('q', selectedQuery)
      if (cursor) parameters.set('cursor', cursor)
      const received = await client.request<CatalogMetadataVocabularyPage>(
        `/uploads/metadata-vocabulary?${parameters.toString()}`,
        { cache: 'no-store', signal: controller.signal },
      )
      if (expectedIntent === intent.current && !controller.signal.aborted) {
        setPage(boundedPage(received, selectedKind))
      }
    } catch (next) {
      if (expectedIntent === intent.current && !controller.signal.aborted) setError(next)
    } finally {
      if (activeController.current === controller) activeController.current = undefined
      if (expectedIntent === intent.current) setBusy(false)
    }
  }, [client])

  useEffect(() => {
    setPage(undefined)
    setCursorStack([])
    void load(kind, query)
    return () => activeController.current?.abort()
  }, [kind, load, query])

  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    const normalized = queryInput.trim().slice(0, 200)
    setQueryInput(normalized)
    setQuery(normalized)
  }

  const nextPage = () => {
    const cursor = page?.page.next_cursor
    if (!cursor || busy) return
    const stack = [...cursorStack, cursor].slice(-50)
    setCursorStack(stack)
    void load(kind, query, cursor)
  }

  const previousPage = () => {
    if (!cursorStack.length || busy) return
    const stack = cursorStack.slice(0, -1)
    setCursorStack(stack)
    void load(kind, query, stack.at(-1))
  }

  const copyReference = async (item: CatalogMetadataVocabularyItem) => {
    try {
      await navigator.clipboard.writeText(item.id)
      setCopiedId(item.id)
    } catch (next) {
      setError(next)
    }
  }

  return (
    <section aria-labelledby="catalog-vocabulary-title" className="registration-vocabulary-browser">
      <header>
        <div>
          <span className="eyebrow">Controlled references</span>
          <h3 id="catalog-vocabulary-title">통제 어휘 UUID 찾기</h3>
        </div>
      </header>
      <p className="muted">
        도메인·용어·태그 행에는 공급자 URN 대신 아래 워크스페이스 전용 UUID를 입력합니다.
      </p>
      <form onSubmit={submitSearch}>
        <label>
          어휘 종류
          <select
            disabled={busy}
            value={kind}
            onChange={(event) => setKind(event.target.value as CatalogMetadataVocabularyKind)}
          >
            <option value="TAG">태그</option>
            <option value="TERM">용어</option>
            <option value="DOMAIN">도메인</option>
          </select>
        </label>
        <label>
          표시명 검색
          <input
            disabled={busy}
            maxLength={200}
            value={queryInput}
            onChange={(event) => setQueryInput(event.target.value)}
          />
        </label>
        <button className="button button-secondary" disabled={busy} type="submit">
          {busy ? '조회 중…' : '검색'}
        </button>
      </form>
      <ErrorNotice error={error} />
      <div className="compact-list" aria-live="polite">
        {page?.items.map((item: CatalogMetadataVocabularyItem) => (
          <div key={item.id}>
            <strong>{item.display_name}</strong>
            <code>{item.id}</code>
            <button
              aria-label={`${item.display_name} UUID 복사`}
              className="button button-secondary"
              onClick={() => void copyReference(item)}
              type="button"
            >
              {copiedId === item.id ? '복사됨' : 'UUID 복사'}
            </button>
          </div>
        ))}
        {!busy && page && page.items.length === 0 && (
          <p className="muted">현재 사용할 수 있는 통제 어휘가 없습니다.</p>
        )}
      </div>
      <nav aria-label="통제 어휘 페이지">
        <button
          aria-label="이전 어휘 페이지"
          className="button button-secondary"
          disabled={busy || cursorStack.length === 0}
          onClick={previousPage}
          type="button"
        >
          이전
        </button>
        <button
          aria-label="다음 어휘 페이지"
          className="button button-secondary"
          disabled={busy || !page?.page.next_cursor}
          onClick={nextPage}
          type="button"
        >
          다음
        </button>
      </nav>
    </section>
  )
}
