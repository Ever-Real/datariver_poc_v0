import type { ExternalSystemLink } from '../../api/types'

const symbols: Record<ExternalSystemLink['system_id'], string> = {
  datahub: 'DH',
  airflow: 'AF',
  grafana: 'GF',
  prometheus: 'PM',
  graph: 'KG',
}

export function ExternalSystemLinks({ links }: { links: ExternalSystemLink[] }) {
  if (links.length === 0) return null
  return (
    <nav className="external-system-links" aria-label="보조 시스템">
      {links.map((link) => (
        <a key={link.system_id} href={link.url} target="_blank" rel="noopener noreferrer" title={`${link.label} 새 창에서 열기`}>
          <span aria-hidden="true">{symbols[link.system_id]}</span>
          <span className="sr-only">{link.label}</span>
        </a>
      ))}
    </nav>
  )
}
