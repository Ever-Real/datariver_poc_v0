import { create } from 'zustand'
import type { Viewport } from '@xyflow/react'
import type {
  KnowledgeStudioBasicInformation,
  KnowledgeStudioSourceDataset,
  KnowledgeStudioTBoxElement,
} from './knowledgeStudioApi'
import type { KnowledgeStudioStep } from '../routes/knowledgeLocation'

export interface TBoxBlockEditorSession {
  blockVersion: number
  elements: KnowledgeStudioTBoxElement[]
  editorText: string
  viewport: Viewport
}

export interface ABoxEditorSession {
  selectedTargetId?: string
  sourceQuery: string
  selectedSource?: KnowledgeStudioSourceDataset
  selectedSourceStale: boolean
  subjectField: string
  propertyFields: Record<string, string>
  selectedPreviewNodeId?: string
  reviewReason: string
}

interface KnowledgeStudioSession {
  step: KnowledgeStudioStep
  basic?: KnowledgeStudioBasicInformation
  selectedBlockId?: string
  blocks: Record<string, TBoxBlockEditorSession>
  abox?: ABoxEditorSession
}

interface KnowledgeStudioSessionState {
  sessions: Record<string, KnowledgeStudioSession>
  setStep: (draftId: string, step: KnowledgeStudioStep) => void
  setBasic: (draftId: string, basic: KnowledgeStudioBasicInformation) => void
  setSelectedBlock: (draftId: string, blockId: string) => void
  setBlock: (
    draftId: string,
    blockId: string,
    session: TBoxBlockEditorSession,
  ) => void
  setABox: (draftId: string, session: ABoxEditorSession) => void
  removeBlock: (draftId: string, blockId: string) => void
  clearDraft: (draftId: string) => void
}

const DEFAULT_VIEWPORT: Viewport = { x: 0, y: 0, zoom: 0.8 }

function emptySession(): KnowledgeStudioSession {
  return {
    step: 'basic',
    blocks: {},
  }
}

export const useKnowledgeStudioSessionStore = create<KnowledgeStudioSessionState>((set) => ({
  sessions: {},
  setStep: (draftId, step) => set((state) => {
    const current = state.sessions[draftId] ?? emptySession()
    return {
      sessions: {
        ...state.sessions,
        [draftId]: { ...current, step },
      },
    }
  }),
  setBasic: (draftId, basic) => set((state) => {
    const current = state.sessions[draftId] ?? emptySession()
    return {
      sessions: {
        ...state.sessions,
        [draftId]: { ...current, basic },
      },
    }
  }),
  setSelectedBlock: (draftId, blockId) => set((state) => {
    const current = state.sessions[draftId] ?? emptySession()
    return {
      sessions: {
        ...state.sessions,
        [draftId]: { ...current, selectedBlockId: blockId },
      },
    }
  }),
  setBlock: (draftId, blockId, session) => set((state) => {
    const current = state.sessions[draftId] ?? emptySession()
    return {
      sessions: {
        ...state.sessions,
        [draftId]: {
          ...current,
          blocks: {
            ...current.blocks,
            [blockId]: {
              ...session,
              elements: session.elements.map((item) => ({ ...item })),
              viewport: { ...session.viewport },
            },
          },
        },
      },
    }
  }),
  setABox: (draftId, session) => set((state) => {
    const current = state.sessions[draftId] ?? emptySession()
    return {
      sessions: {
        ...state.sessions,
        [draftId]: {
          ...current,
          abox: {
            ...session,
            selectedSource: session.selectedSource
              ? {
                  ...session.selectedSource,
                  field_paths: [...session.selectedSource.field_paths],
                }
              : undefined,
            propertyFields: { ...session.propertyFields },
          },
        },
      },
    }
  }),
  removeBlock: (draftId, blockId) => set((state) => {
    const current = state.sessions[draftId]
    if (!current?.blocks[blockId]) return state
    const blocks = { ...current.blocks }
    delete blocks[blockId]
    return {
      sessions: {
        ...state.sessions,
        [draftId]: { ...current, blocks },
      },
    }
  }),
  clearDraft: (draftId) => set((state) => {
    if (!state.sessions[draftId]) return state
    const sessions = { ...state.sessions }
    delete sessions[draftId]
    return { sessions }
  }),
}))

export function getKnowledgeStudioBlockSession(
  draftId: string,
  blockId: string,
): TBoxBlockEditorSession | undefined {
  return useKnowledgeStudioSessionStore.getState().sessions[draftId]?.blocks[blockId]
}

export function getKnowledgeStudioABoxSession(
  draftId: string,
): ABoxEditorSession | undefined {
  return useKnowledgeStudioSessionStore.getState().sessions[draftId]?.abox
}

export function defaultKnowledgeStudioViewport(): Viewport {
  return { ...DEFAULT_VIEWPORT }
}
