import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { KnowledgeStudioBasicInformation } from '../knowledgeStudioApi'
import {
  BasicInformationStep,
  parseEndpointAliases,
} from './BasicInformationStep'

const value: KnowledgeStudioBasicInformation = {
  name: 'Enterprise ontology',
  description: 'Enterprise knowledge asset',
  endpoint_alias: 'enterprise_ontology',
  endpoint_aliases: ['enterprise_ontology'],
  domain_id: '019fa57b-52de-74c0-9f5e-06ae7b1bf3af',
  domain_source_version: 'domain-v1',
  classification: 'normal',
}

describe('BasicInformationStep', () => {
  it('parses comma-separated aliases as a stable unique array', () => {
    expect(parseEndpointAliases(
      'enterprise_ontology, catalog_ontology, enterprise_ontology',
    )).toEqual(['enterprise_ontology', 'catalog_ontology'])
  })

  it('enables direct domain input only for the explicit option and preserves focus', async () => {
    const onChange = vi.fn()
    const onCreateDomain = vi.fn().mockResolvedValue(undefined)
    render(
      <BasicInformationStep
        value={value}
        domains={[{
          id: value.domain_id,
          display_name: 'Data Governance',
          source_version: value.domain_source_version,
        }]}
        domainsLoading={false}
        domainQuery=""
        busy={false}
        saveStatus="준비됨"
        onChange={onChange}
        onDomainQueryChange={vi.fn()}
        onCreateDomain={onCreateDomain}
        onSave={vi.fn()}
        onContinue={vi.fn()}
      />,
    )

    const directInput = screen.getByLabelText('직접 입력 도메인명')
    expect(directInput).toBeDisabled()
    fireEvent.change(screen.getByLabelText('업무 도메인'), {
      target: { value: '__DIRECT__' },
    })
    expect(directInput).toBeEnabled()
    directInput.focus()
    fireEvent.change(directInput, { target: { value: '항공 우주' } })
    expect(directInput).toHaveFocus()
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      domain_id: '',
      domain_source_version: '',
    }))
    await waitFor(() => expect(directInput).toBeInTheDocument())
  })

  it('keeps the endpoint alias input focused while emitting the parsed array', () => {
    const onChange = vi.fn()
    render(
      <BasicInformationStep
        value={value}
        domains={[]}
        domainsLoading={false}
        domainQuery=""
        busy={false}
        saveStatus="준비됨"
        onChange={onChange}
        onDomainQueryChange={vi.fn()}
        onCreateDomain={vi.fn().mockResolvedValue(undefined)}
        onSave={vi.fn()}
        onContinue={vi.fn()}
      />,
    )

    const input = screen.getByLabelText('Endpoint alias')
    input.focus()
    fireEvent.change(input, {
      target: { value: 'enterprise_ontology, catalog_ontology' },
    })
    expect(input).toHaveFocus()
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      endpoint_alias: 'enterprise_ontology',
      endpoint_aliases: ['enterprise_ontology', 'catalog_ontology'],
    }))
  })

  it('keeps the user-visible asset description in the basic-information contract', () => {
    const onChange = vi.fn()
    render(
      <BasicInformationStep
        value={value}
        domains={[]}
        domainsLoading={false}
        domainQuery=""
        busy={false}
        saveStatus="준비됨"
        onChange={onChange}
        onDomainQueryChange={vi.fn()}
        onCreateDomain={vi.fn().mockResolvedValue(undefined)}
        onSave={vi.fn()}
        onContinue={vi.fn()}
      />,
    )
    fireEvent.change(screen.getByLabelText('지식 그래프 설명'), {
      target: { value: 'Updated description' },
    })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      description: 'Updated description',
    }))
  })

  it('renders the managed intent banner if serverDraft contains managed intent', () => {
    const serverDraft = {
      managed_intent: 'metadata-lineage',
      managed_graph_type: 'CATALOG_MIRROR',
      accepted_proposal_id: 'contract.123',
      accepted_proposal_hash: 'hash123',
    }
    render(
      <BasicInformationStep
        value={value}
        domains={[]}
        domainsLoading={false}
        domainQuery=""
        busy={false}
        saveStatus="준비됨"
        onChange={vi.fn()}
        onDomainQueryChange={vi.fn()}
        onCreateDomain={vi.fn().mockResolvedValue(undefined)}
        onSave={vi.fn()}
        onContinue={vi.fn()}
        serverDraft={serverDraft}
      />,
    )
    expect(screen.getByText('Managed Intent: metadata-lineage')).toBeInTheDocument()
    expect(screen.getByText(/CATALOG_MIRROR/)).toBeInTheDocument()
    expect(screen.getByText(/contract\.123/)).toBeInTheDocument()
    expect(screen.getByText(/hash123/)).toBeInTheDocument()
  })
})
