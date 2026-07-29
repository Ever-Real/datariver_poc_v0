import { beforeEach, describe, expect, it } from 'vitest'
import {
  getKnowledgeStudioABoxSession,
  getKnowledgeStudioBlockSession,
  useKnowledgeStudioSessionStore,
} from './knowledgeStudioSessionStore'

const draftId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3b0'

describe('knowledgeStudioSessionStore', () => {
  beforeEach(() => {
    useKnowledgeStudioSessionStore.setState({ sessions: {} })
  })

  it('keeps independent T-Box block and A-Box editor buffers outside component lifecycles', () => {
    const state = useKnowledgeStudioSessionStore.getState()
    state.setBlock(draftId, 'block-a', {
      blockVersion: 3,
      elements: [],
      editorText: 'CREATE (:Class {name: "임직원"})',
      viewport: { x: 12, y: 24, zoom: 0.7 },
    })
    state.setABox(draftId, {
      selectedTargetId: 'class.employee',
      sourceQuery: '인사',
      selectedSourceStale: false,
      subjectField: 'employee_id',
      propertyFields: { 'property.employee.name': 'employee_name' },
      reviewReason: '정합성 확인 완료',
    })

    expect(getKnowledgeStudioBlockSession(draftId, 'block-a')).toMatchObject({
      editorText: 'CREATE (:Class {name: "임직원"})',
      viewport: { zoom: 0.7 },
    })
    expect(getKnowledgeStudioABoxSession(draftId)).toMatchObject({
      selectedTargetId: 'class.employee',
      sourceQuery: '인사',
      subjectField: 'employee_id',
      propertyFields: { 'property.employee.name': 'employee_name' },
    })
  })
})
