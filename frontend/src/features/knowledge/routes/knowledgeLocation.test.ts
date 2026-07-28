import { describe, expect, it } from 'vitest'
import {
  knowledgeStudioLocationFromHref,
  knowledgeStudioUrl,
} from './knowledgeLocation'

describe('Knowledge Studio route contract', () => {
  it('accepts a typed draft and step while preserving workspace only', () => {
    const draftId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3af'
    expect(knowledgeStudioLocationFromHref(
      `https://catalog.example/app?page=knowledge-studio&workspace=ws&draft=${draftId}&step=tbox`,
    )).toEqual({ draftId, step: 'tbox', valid: true })
    expect(knowledgeStudioUrl({
      draftId,
      step: 'abox',
      href: 'https://catalog.example/app?page=knowledge&workspace=ws&asset=old&drawerTab=api',
    })).toBe(`/app?page=knowledge-studio&workspace=ws&draft=${draftId}&step=abox`)
  })

  it('rejects malformed drafts, unknown steps and later steps without a draft', () => {
    expect(knowledgeStudioLocationFromHref(
      'https://catalog.example/app?page=knowledge-studio&draft=not-a-uuid',
    ).valid).toBe(false)
    expect(knowledgeStudioLocationFromHref(
      'https://catalog.example/app?page=knowledge-studio&step=unknown',
    ).valid).toBe(false)
    expect(knowledgeStudioLocationFromHref(
      'https://catalog.example/app?page=knowledge-studio&step=tbox',
    ).valid).toBe(false)
  })

  it('accepts one asset edit target and never mixes it with a Draft', () => {
    const assetId = '019fa57b-52de-74c0-9f5e-06ae7b1bf3c1'
    expect(knowledgeStudioLocationFromHref(
      `https://catalog.example/app?page=knowledge-studio&asset_id=${assetId}`,
    )).toEqual({
      assetId,
      step: 'basic',
      valid: true,
    })
    expect(knowledgeStudioUrl({
      assetId,
      href: 'https://catalog.example/app?page=knowledge&workspace=ws',
    })).toBe(`/app?page=knowledge-studio&workspace=ws&asset_id=${assetId}`)
    expect(knowledgeStudioLocationFromHref(
      `https://catalog.example/app?page=knowledge-studio&asset_id=${assetId}&draft=${assetId}`,
    ).valid).toBe(false)
  })
})
