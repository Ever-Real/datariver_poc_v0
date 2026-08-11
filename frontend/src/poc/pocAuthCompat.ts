import type { AuthenticatedProfile } from '../api/types'

const workspaceId = '00000000-0000-4000-8000-000000000061'
const subjectId = '00000000-0000-4000-8000-000000000111'

const profile: AuthenticatedProfile = {
  subject: subjectId,
  display_name: 'POC User',
  email: 'poc.user@local',
  roles: ['Data Steward'],
  authentication_assurance: 'UNKNOWN',
  default_workspace_id: workspaceId,
  workspace_selection_enabled: false,
  hardware_webauthn_enabled: false,
  password_change_supported: false,
}

const noAuthenticationAction = () => Promise.resolve(undefined)
const readSecurityEpoch = () => 0

const pocAuthState = {
  user: {
    access_token: 'poc-memory-only',
    profile: {
      sub: subjectId,
      name: profile.display_name,
      email: profile.email,
    },
  },
  profile,
  securityEpoch: 0,
  authorizationRevision: 0,
  readSecurityEpoch,
  loading: false,
  notice: undefined,
  renewAccessToken: () => Promise.resolve('poc-memory-only'),
  signIn: noAuthenticationAction,
  signOut: noAuthenticationAction,
  beginWebAuthnEnrollment: noAuthenticationAction,
  beginStepUp: noAuthenticationAction,
  beginPasswordReauth: noAuthenticationAction,
  beginPasswordChange: noAuthenticationAction,
  clearNotice: () => undefined,
}

export function useAuth() {
  return pocAuthState
}
