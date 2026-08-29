import { describe, expect, it } from 'vitest'
import {
  governanceMarkupFromFile,
  markdownToGovernanceHtml,
  sanitizeGovernanceHtml,
} from './governanceDocumentMarkup'

describe('governance document markup import', () => {
  it('preserves allowlisted HTML structure and strips executable content', async () => {
    const imported = await governanceMarkupFromFile(new File([
      '<style>.policy { font-size: 24px; text-align: right; position: fixed; background-image: url(https://evil.test/x) }</style>',
      '<h1 class="policy">정책</h1><p style="text-align:center"><strong>승인</strong> 본문</p>',
      '<script>globalThis.compromised=true</script>',
      '<a href="javascript:alert(1)" onclick="alert(2)">위험 링크</a>',
    ], 'policy.html', { type: 'text/html' }))

    expect(imported.format).toBe('HTML')
    expect(imported.html).toContain('>정책</h1>')
    expect(imported.html).toContain('<strong>승인</strong>')
    expect(imported.html).not.toMatch(/script|javascript|onclick/i)
    expect(imported.html).toContain('위험 링크')
    expect(imported.html).toContain('data-governance-style="font-size:24px;text-align:right"')
    expect(imported.html).toContain('data-governance-style="text-align:center"')
    expect(imported.html).not.toMatch(/position|background-image|evil\.test/)
  })

  it('converts Markdown headings, lists, tables and inline formatting to safe HTML', () => {
    const html = markdownToGovernanceHtml([
      '# 데이터 정책',
      '',
      '**필수** 통제와 `owner`를 정의합니다.',
      '',
      '- 승인 절차',
      '- 변경 이력',
      '',
      '| 항목 | 기준 |',
      '| --- | --- |',
      '| 보존 | 3년 |',
    ].join('\n'))

    expect(html).toContain('<h1>데이터 정책</h1>')
    expect(html).toContain('<strong>필수</strong>')
    expect(html).toContain('<code>owner</code>')
    expect(html).toContain('<ul><li>승인 절차</li><li>변경 이력</li></ul>')
    expect(html).toContain('<table>')
  })

  it('drops unsafe attributes from directly sanitized HTML', () => {
    expect(sanitizeGovernanceHtml('<p style="color:red" onmouseover="x()">본문</p><iframe src="x"></iframe>'))
      .toBe('<p>본문</p>')
  })

  it('keeps only bounded editor presentation properties across save sanitization', () => {
    expect(sanitizeGovernanceHtml(
      '<p data-governance-style="font-size:18px;padding-left:2em;text-align:center;position:fixed">본문</p>',
    )).toBe(
      '<p data-governance-style="font-size:18px;padding-left:2em;text-align:center">본문</p>',
    )
  })
})
