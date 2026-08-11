import { pocAssets, type PocAsset } from './pocFixtures'

export type RegistrationState = 'REQUESTED' | 'VALIDATED' | 'COMPLETED'
export type ChangeState = 'DRAFT' | 'IN_REVIEW' | 'APPROVED'
export type QualityRunState = 'QUEUED' | 'RUNNING' | 'COMPLETED'

export type PocSession = {
  registration: RegistrationState
  change: ChangeState
  qualityRun: QualityRunState
  glossaryActionApplied: boolean
  knowledgePublished: boolean
  chatAnswered: boolean
}

const registrationStates = ['REQUESTED', 'VALIDATED', 'COMPLETED'] as const
const changeStates = ['DRAFT', 'IN_REVIEW', 'APPROVED'] as const
const qualityRunStates = ['QUEUED', 'RUNNING', 'COMPLETED'] as const

export function createPocSession(): PocSession {
  return {
    registration: 'REQUESTED',
    change: 'DRAFT',
    qualityRun: 'QUEUED',
    glossaryActionApplied: false,
    knowledgePublished: false,
    chatAnswered: false,
  }
}

function nextState<State extends string>(states: readonly State[], current: State): State {
  const index = states.indexOf(current)
  return states[Math.min(index + 1, states.length - 1)] ?? current
}

export function advanceRegistration(current: RegistrationState): RegistrationState {
  return nextState(registrationStates, current)
}

export function advanceChange(current: ChangeState): ChangeState {
  return nextState(changeStates, current)
}

export function advanceQualityRun(current: QualityRunState): QualityRunState {
  return nextState(qualityRunStates, current)
}

export function searchPocAssets(query: string, domain: string): readonly PocAsset[] {
  const normalizedQuery = query.trim().toLocaleLowerCase()
  return pocAssets.filter((asset) => {
    const matchesDomain = domain === 'ALL' || asset.domain === domain
    if (!matchesDomain) return false
    if (!normalizedQuery) return true
    const searchable = [
      asset.name,
      asset.platform,
      asset.database,
      asset.schema,
      asset.domain,
      asset.owner,
      asset.description,
      ...asset.tags,
      ...asset.terms,
      ...asset.columns.flatMap((column) => [column.name, column.description]),
    ].join(' ').toLocaleLowerCase()
    return searchable.includes(normalizedQuery)
  })
}

export function qualityRunProgress(state: QualityRunState): number {
  if (state === 'QUEUED') return 14
  if (state === 'RUNNING') return 62
  return 100
}
