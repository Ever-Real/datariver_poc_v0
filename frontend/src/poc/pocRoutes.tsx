export type PocRoute =
  | 'overview'
  | 'catalog'
  | 'registration'
  | 'changes'
  | 'metadata'
  | 'knowledge'
  | 'quality'
  | 'quality-run'
  | 'chat'
  | 'monitoring'

export type PocRouteDefinition = {
  id: PocRoute
  label: string
  shortLabel: string
  eyebrow: string
  title: string
  description: string
}

export const pocRoutes = [
  {
    id: 'overview',
    label: 'Dashboard',
    shortLabel: '01',
    eyebrow: 'Platform snapshot',
    title: 'DataRiver at a glance',
    description: 'Synthetic platform signals and the guided static walkthrough.',
  },
  {
    id: 'catalog',
    label: 'Search & assets',
    shortLabel: '02',
    eyebrow: 'Catalog discovery',
    title: 'Find trusted data faster',
    description: 'Search sample catalog assets, filter results and inspect a selected table.',
  },
  {
    id: 'registration',
    label: 'Registration',
    shortLabel: '03',
    eyebrow: 'Registration management',
    title: 'Move an intake request forward',
    description: 'Demonstrate a deterministic validation and completion flow in browser memory.',
  },
  {
    id: 'changes',
    label: 'Change management',
    shortLabel: '04',
    eyebrow: 'Governance workflow',
    title: 'Review a governed change',
    description: 'Illustrate draft, independent review and approval without a backend mutation.',
  },
  {
    id: 'metadata',
    label: 'Metadata & lineage',
    shortLabel: '05',
    eyebrow: 'DataHub-style view',
    title: 'Understand the table in context',
    description: 'Browse dataset, column and lineage evidence with simulated administration.',
  },
  {
    id: 'knowledge',
    label: 'Knowledge',
    shortLabel: '06',
    eyebrow: 'Knowledge management',
    title: 'Turn evidence into reusable knowledge',
    description: 'Inspect sample sources and illustrate a governed publication lifecycle.',
  },
  {
    id: 'quality',
    label: 'Quality control',
    shortLabel: '07',
    eyebrow: 'Quality control plane',
    title: 'Define what good data means',
    description: 'Review sample Rule Sets, checks, ownership and recent quality posture.',
  },
  {
    id: 'quality-run',
    label: 'Quality Run',
    shortLabel: '08',
    eyebrow: 'Execution simulation',
    title: 'Follow a quality execution',
    description: 'Step through queued, running and completed states with sanitized results.',
  },
  {
    id: 'chat',
    label: 'Chat',
    shortLabel: '09',
    eyebrow: 'Evidence-aware assistant',
    title: 'Ask with evidence attached',
    description: 'Reveal one canned, citation-linked answer with no model or provider call.',
  },
  {
    id: 'monitoring',
    label: 'Monitoring',
    shortLabel: '10',
    eyebrow: 'Operations view',
    title: 'See platform posture clearly',
    description: 'Read synthetic availability, latency, activity and dependency indicators.',
  },
] as const satisfies readonly PocRouteDefinition[]

const routeIds = new Set<PocRoute>(pocRoutes.map((route) => route.id))

export function routeFromHash(hash = window.location.hash): PocRoute {
  const candidate = hash.replace(/^#\/?/, '').trim() as PocRoute
  return routeIds.has(candidate) ? candidate : 'overview'
}

export function routeHash(route: PocRoute): string {
  return `#/${route}`
}

export function routeDefinition(route: PocRoute): PocRouteDefinition {
  return pocRoutes.find((candidate) => candidate.id === route) ?? pocRoutes[0]
}
