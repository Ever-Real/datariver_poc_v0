import { describe, expect, it } from 'vitest'
import { defaultWorkspaceSelection, workspaceFromLocation } from './workspace'

const defaultWorkspace = '00000000-0000-4000-8000-000000000100'
const selectedWorkspace = '00000000-0000-4000-8000-000000000200'

describe('workspace hydration selection', () => {
  it('uses only a valid Workspace query value', () => {
    expect(workspaceFromLocation(`https://example.test/?workspace=${selectedWorkspace}`)).toBe(selectedWorkspace)
    expect(workspaceFromLocation('https://example.test/?workspace=administrator')).toBe('')
  })

  it('hydrates the server default only when no explicit selection exists', () => {
    expect(defaultWorkspaceSelection('', defaultWorkspace)).toBe(defaultWorkspace)
    expect(defaultWorkspaceSelection(selectedWorkspace, defaultWorkspace)).toBe(selectedWorkspace)
  })

  it('rejects a malformed server value before it reaches request state', () => {
    expect(defaultWorkspaceSelection('', 'not-a-workspace')).toBe('')
  })
})
