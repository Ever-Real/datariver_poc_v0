import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SafeGovernanceHtml } from './SafeGovernanceHtml'

const governanceDocumentsCss = readFileSync(
  resolve('src/features/governance-documents/governanceDocuments.css'),
  'utf8',
)

describe('SafeGovernanceHtml', () => {
  it('keeps published document metadata at the existing readable Governance table scale', () => {
    expect(governanceDocumentsCss).toContain(
      '.governance-viewer-meta dt { font-size: 11px; line-height: 1.45; }',
    )
    expect(governanceDocumentsCss).toContain(
      '.governance-viewer-meta dd { font-size: 13px; line-height: 1.45; }',
    )
  })

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

  it('renders allowlisted void elements without passing forbidden children', () => {
    const { container } = render(<SafeGovernanceHtml
      html={'<p>첫 줄<br>둘째 줄</p><hr>'}
      contentHash={'d'.repeat(64)}
      sanitizerPolicyVersion="GOVERNANCE_HTML_V1"
    />)

    expect(screen.getByText(/첫 줄/)).toBeInTheDocument()
    expect(container.querySelectorAll('br')).toHaveLength(1)
    expect(container.querySelectorAll('hr')).toHaveLength(1)
  })

  it('renders only static presentation tokens without an inline style attribute', () => {
    const { container } = render(<SafeGovernanceHtml
      html={'<h2 data-governance-style="font-size:18px;padding-left:2em;text-align:center;position:fixed;background-image:url(https://evil.test/x)">정적 디자인</h2>'}
      contentHash={'e'.repeat(64)}
      sanitizerPolicyVersion="POC_STATIC_PRESENTATION_V1"
    />)

    expect(screen.getByRole('heading', { name: '정적 디자인' })).toHaveAttribute(
      'data-governance-style',
      'font-size:18px;padding-left:2em;text-align:center',
    )
    expect(container.querySelector('h2')).not.toHaveAttribute('style')
  })

  it('canonicalizes legacy italic markup and renders bounded table-cell colors without inline style', () => {
    const { container } = render(<SafeGovernanceHtml
      html={'<p><i>기울임</i></p><table><tbody><tr><td data-governance-style="background-color:#f4f8fa">셀</td></tr></tbody></table>'}
      contentHash={'9'.repeat(64)}
      sanitizerPolicyVersion="GOVERNANCE_HTML_SANITIZER_V4_TABLE_PRESENTATION_TOKENS"
    />)

    expect(container.querySelector('i')).toBeNull()
    expect(container.querySelector('em')).toHaveTextContent('기울임')
    expect(container.querySelector('td')).toHaveAttribute(
      'data-governance-style',
      'background-color:#f4f8fa',
    )
    expect(container.querySelector('td')).not.toHaveAttribute('style')
  })

  it('keeps legacy V2 canonical markup readable without presentation attributes', () => {
    const { container } = render(<SafeGovernanceHtml
      html={'<h2>Legacy policy</h2><p><strong>Approved</strong> body</p>'}
      contentHash={'f'.repeat(64)}
      sanitizerPolicyVersion="GOVERNANCE_HTML_SANITIZER_V2_BLEACH"
    />)

    expect(screen.getByRole('heading', { name: 'Legacy policy' })).toBeInTheDocument()
    expect(screen.getByText(/Approved/)).toBeInTheDocument()
    expect(container.querySelector('[style], [data-governance-style]')).toBeNull()
  })

  it('maps every accepted presentation token to a static CSS rule', () => {
    const tokens = [
      ['font-size:10px', 'font-size: 10px'],
      ['font-size:12px', 'font-size: 12px'],
      ['font-size:14px', 'font-size: 14px'],
      ['font-size:16px', 'font-size: 16px'],
      ['font-size:18px', 'font-size: 18px'],
      ['font-size:24px', 'font-size: 24px'],
      ['font-size:32px', 'font-size: 32px'],
      ['padding-left:2em', 'padding-left: 2em'],
      ['padding-left:4em', 'padding-left: 4em'],
      ['padding-left:6em', 'padding-left: 6em'],
      ['padding-left:8em', 'padding-left: 8em'],
      ['padding-left:10em', 'padding-left: 10em'],
      ['padding-left:12em', 'padding-left: 12em'],
      ['text-align:center', 'text-align: center'],
      ['text-align:right', 'text-align: right'],
    ] as const
    const { container } = render(<SafeGovernanceHtml
      html={tokens.map(([token], index) => (
        `<p data-governance-style="${token}">Token ${index}</p>`
      )).join('')}
      contentHash={'1'.repeat(64)}
      sanitizerPolicyVersion="GOVERNANCE_HTML_SANITIZER_V3_PRESENTATION_TOKENS"
    />)

    Array.from(container.querySelectorAll<HTMLElement>('p')).forEach((element, index) => {
      const [token, declaration] = tokens[index]!
      expect(governanceDocumentsCss).toContain(
        `.governance-safe-html [data-governance-style*="${token}"]`,
      )
      expect(governanceDocumentsCss).toContain(`{ ${declaration}; }`)
      expect(element).not.toHaveAttribute('style')
    })
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
