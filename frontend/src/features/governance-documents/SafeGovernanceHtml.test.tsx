import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SafeGovernanceHtml } from './SafeGovernanceHtml'

describe('SafeGovernanceHtml', () => {
  it('renders the allowlisted document structure without an HTML injection sink', () => {
    const { container } = render(<SafeGovernanceHtml
      html={'<h2 id="clobber">안전한 정책</h2><p>본문 <strong>강조</strong></p><table><tbody><tr><th colspan="2">항목</th></tr></tbody></table><a href="https://example.test/policy" onclick="alert(1)">근거 링크</a>'}
      contentHash={'a'.repeat(64)}
      sanitizerPolicyVersion="GOVERNANCE_HTML_V1"
    />)

    expect(screen.getByRole('heading', { name: '안전한 정책' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '근거 링크' })).toHaveAttribute(
      'href',
      'https://example.test/policy',
    )
    expect(screen.getByRole('link', { name: '근거 링크' })).not.toHaveAttribute('onclick')
    expect(container.querySelector('[id="clobber"]')).toBeNull()
    expect(container.querySelector('th')).toHaveAttribute('colspan', '2')
  })

  it('suppresses executable, embedded, form and active-media subtrees', () => {
    const { container } = render(<SafeGovernanceHtml
      html={'<script>script-secret</script><style>style-secret</style><svg><a>svg-secret</a></svg><img src=x onerror=alert(1)><iframe srcdoc="<script>alert(1)</script>"></iframe><form><input value="credential"></form><a href="javascript:alert(1)">unsafe-link</a><p>허용 본문</p>'}
      contentHash={'b'.repeat(64)}
      sanitizerPolicyVersion="GOVERNANCE_HTML_V1"
    />)

    expect(screen.getByText('허용 본문')).toBeInTheDocument()
    expect(screen.getByText('unsafe-link')).not.toHaveRole('link')
    expect(screen.queryByText('script-secret')).not.toBeInTheDocument()
    expect(screen.queryByText('style-secret')).not.toBeInTheDocument()
    expect(screen.queryByText('svg-secret')).not.toBeInTheDocument()
    expect(container.querySelector('script,style,svg,img,iframe,form,input')).toBeNull()
  })

  it('accepts only relative and HTTPS links from the server sanitizer contract', () => {
    render(<SafeGovernanceHtml
      html={'<a href="//evil.test/path">protocol-relative</a><a href="http://evil.test">http</a><a href="mailto:person@example.test">mail</a><a href="../policy?v=1#scope">relative</a><a href="https://example.test/policy">https</a>'}
      contentHash={'c'.repeat(64)}
      sanitizerPolicyVersion="GOVERNANCE_HTML_V1"
    />)

    expect(screen.queryByRole('link', { name: 'protocol-relative' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'http' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'mail' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'relative' })).toHaveAttribute(
      'href',
      '../policy?v=1#scope',
    )
    expect(screen.getByRole('link', { name: 'https' })).toHaveAttribute(
      'href',
      'https://example.test/policy',
    )
  })
})
