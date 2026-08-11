import { FlaskConical } from 'lucide-react'

export function PocBanner() {
  return (
    <div className="poc-banner" role="status" data-testid="poc-banner">
      <FlaskConical size={15} aria-hidden="true" />
      <strong>POC</strong>
      <span aria-hidden="true">/</span>
      <strong>NO AUTH</strong>
      <span aria-hidden="true">/</span>
      <strong>SAMPLE DATA</strong>
      <span aria-hidden="true">/</span>
      <strong>NOT FOR PRODUCTION</strong>
    </div>
  )
}
