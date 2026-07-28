import type { KnowledgeStudioBasicInformation } from './knowledgeStudioApi'

const DATABASE_NAME = 'datariver-knowledge-studio-recovery-v1'
const STORE_NAME = 'pending-drafts'

export interface DraftRecoveryRecord {
  key: string
  scopeHash: string
  draftId?: string
  payload: KnowledgeStudioBasicInformation
  expectedEtag?: string
  idempotencyKey: string
  updatedAt: string
}

export interface DraftRecoveryQueue {
  read(scopeHash: string, draftId?: string): Promise<DraftRecoveryRecord | undefined>
  put(record: DraftRecoveryRecord): Promise<void>
  remove(scopeHash: string, draftId: string | undefined, idempotencyKey: string): Promise<void>
}

function recoveryKey(scopeHash: string, draftId?: string): string {
  return `${scopeHash}:${draftId ?? 'NEW'}`
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed.'))
  })
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onabort = () => reject(transaction.error ?? new Error('IndexedDB transaction aborted.'))
    transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB transaction failed.'))
  })
}

class IndexedDbDraftRecoveryQueue implements DraftRecoveryQueue {
  private database?: Promise<IDBDatabase>

  constructor(private readonly factory: IDBFactory) {}

  async read(scopeHash: string, draftId?: string): Promise<DraftRecoveryRecord | undefined> {
    const database = await this.open()
    const transaction = database.transaction(STORE_NAME, 'readonly')
    const value = await requestResult(
      transaction.objectStore(STORE_NAME).get(
        recoveryKey(scopeHash, draftId),
      ) as IDBRequest<unknown>,
    )
    await transactionDone(transaction)
    return value as DraftRecoveryRecord | undefined
  }

  async put(record: DraftRecoveryRecord): Promise<void> {
    const database = await this.open()
    const transaction = database.transaction(STORE_NAME, 'readwrite')
    transaction.objectStore(STORE_NAME).put({
      ...record,
      key: recoveryKey(record.scopeHash, record.draftId),
    })
    await transactionDone(transaction)
  }

  async remove(
    scopeHash: string,
    draftId: string | undefined,
    idempotencyKey: string,
  ): Promise<void> {
    const database = await this.open()
    const transaction = database.transaction(STORE_NAME, 'readwrite')
    const store = transaction.objectStore(STORE_NAME)
    const key = recoveryKey(scopeHash, draftId)
    const current = await requestResult(
      store.get(key) as IDBRequest<unknown>,
    ) as DraftRecoveryRecord | undefined
    if (current?.idempotencyKey === idempotencyKey) store.delete(key)
    await transactionDone(transaction)
  }

  private open(): Promise<IDBDatabase> {
    this.database ??= new Promise((resolve, reject) => {
      const request = this.factory.open(DATABASE_NAME, 1)
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE_NAME)) {
          request.result.createObjectStore(STORE_NAME, { keyPath: 'key' })
        }
      }
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error ?? new Error('IndexedDB open failed.'))
      request.onblocked = () => reject(new Error('IndexedDB upgrade is blocked.'))
    })
    return this.database
  }
}

export function createDraftRecoveryQueue(): DraftRecoveryQueue {
  if (!window.indexedDB) throw new Error('이 브라우저는 안전한 Draft 복구 저장소를 지원하지 않습니다.')
  return new IndexedDbDraftRecoveryQueue(window.indexedDB)
}

export async function knowledgeDraftRecoveryScope(
  workspaceId: string,
  subjectId: string,
): Promise<string> {
  const input = new TextEncoder().encode(`${workspaceId}\u0000${subjectId}`)
  const digest = await crypto.subtle.digest('SHA-256', input)
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}
