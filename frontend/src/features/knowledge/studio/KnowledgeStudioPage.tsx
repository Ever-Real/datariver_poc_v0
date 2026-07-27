import { useEffect, useMemo } from 'react'
import { Database, Network } from 'lucide-react'
import type { Page } from '../../../app/navigation'
import {
  knowledgeStudioLocationFromHref,
  type KnowledgeStudioStep,
} from '../routes/knowledgeLocation'
import { BasicInformationStep } from './basic/BasicInformationStep'
import { StudioShell } from './StudioShell'

function FoundationPlaceholder({ step }: { step: Exclude<KnowledgeStudioStep, 'basic'> }) {
  const tbox = step === 'tbox'
  const Icon = tbox ? Network : Database
  return <section className="grid min-h-[420px] place-items-center rounded-enterprise border border-dashed border-slate-300 bg-white p-8 text-center">
    <div className="max-w-xl">
      <Icon className="mx-auto mb-3 text-enterprise-blue" size={38} />
      <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
        {tbox ? 'Step 2 · T-Box' : 'Step 3 · A-Box'}
      </span>
      <h2 className="my-2 text-lg font-black text-navy-900">
        {tbox ? 'Graph Builder canvas foundation' : 'Data Enricher mapping foundation'}
      </h2>
      <p className="m-0 text-xs leading-5 text-slate-500">
        {tbox
          ? 'Lexer → AST → typed operation → React Flow projection 경계가 준비됐습니다. Block/Proposal persistence가 연결되기 전에는 LLM 또는 파일 결과를 accepted graph로 표시하지 않습니다.'
          : 'PUBLISHED T-Box target과 versioned source contract가 연결되기 전에는 실제 row mapping이나 ingestion 성공을 표시하지 않습니다.'}
      </p>
    </div>
  </section>
}

export function KnowledgeStudioPage({ onNavigate }: { onNavigate: (page: Page) => void }) {
  const location = useMemo(() => knowledgeStudioLocationFromHref(), [])
  useEffect(() => {
    if (!location.valid) onNavigate('knowledge')
  }, [location.valid, onNavigate])
  if (!location.valid) return null

  return <StudioShell
    step={location.step}
    draftId={location.draftId}
    onBack={() => onNavigate('knowledge')}
  >
    {location.step === 'basic'
      ? <BasicInformationStep />
      : <FoundationPlaceholder step={location.step} />}
  </StudioShell>
}
