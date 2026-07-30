import { Profiler } from 'react'
import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../../../api/client'
import type { KnowledgeStudioDomainOption } from '../knowledgeStudioApi'
import { DomainManagementDialog } from './DomainManagementDialog'

const domains: KnowledgeStudioDomainOption[] = [{
  id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3af',
  display_name: '반도체',
  source_version: 'domain-v3',
  managed: true,
  version: 3,
}]

describe('DomainManagementDialog', () => {
  it('keeps the hidden TanStack table data reference stable without a render loop', async () => {
    let commits = 0
    const client = new ApiClient('/api/v1', () => 'token', () => 'workspace')

    render(
      <Profiler id="domain-management" onRender={() => { commits += 1 }}>
        <DomainManagementDialog
          client={client}
          open={false}
          items={domains}
          loading={false}
          onRequestClose={vi.fn()}
          onChanged={vi.fn(() => Promise.resolve())}
        />
      </Profiler>,
    )

    await Promise.resolve()
    await Promise.resolve()

    expect(commits).toBe(1)
  })
})
