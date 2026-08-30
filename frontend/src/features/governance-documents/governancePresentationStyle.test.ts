import { describe, expect, it } from 'vitest'
import { safeGovernancePresentation } from './governancePresentationStyle'

const allowedTokens = [
  'font-size:10px',
  'font-size:12px',
  'font-size:14px',
  'font-size:16px',
  'font-size:18px',
  'font-size:24px',
  'font-size:32px',
  'padding-left:2em',
  'padding-left:4em',
  'padding-left:6em',
  'padding-left:8em',
  'padding-left:10em',
  'padding-left:12em',
  'text-align:center',
  'text-align:right',
] as const

describe('governance presentation token contract', () => {
  it.each(allowedTokens)('accepts the exact static token %s', (token) => {
    expect(safeGovernancePresentation(token)).toBe(token)
  })

  it.each(['font-size:11px', 'padding-left:3em', 'text-align:justify'])(
    'rejects unsupported token lookalike %s',
    (token) => {
      expect(safeGovernancePresentation(token)).toBe('')
    },
  )

  it('canonicalizes declaration order for stable save and reload', () => {
    expect(safeGovernancePresentation(
      'text-align:right;padding-left:4em;font-size:16px',
    )).toBe('font-size:16px;padding-left:4em;text-align:right')
  })

  it.each(['#f4f8fa', '#fff3f2', '#eff9f2', '#fff9e9'])(
    'accepts bounded table-cell color %s only for a table cell',
    (color) => {
      const token = `background-color:${color}`
      expect(safeGovernancePresentation(token)).toBe('')
      expect(safeGovernancePresentation(token, { allowBackground: true })).toBe(token)
    },
  )
})
