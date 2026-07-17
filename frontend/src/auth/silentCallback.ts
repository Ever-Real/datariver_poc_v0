import { InMemoryWebStorage, UserManager, WebStorageStateStore } from 'oidc-client-ts'

const authority = String(import.meta.env.VITE_OIDC_AUTHORITY || '').trim()
const clientId = String(import.meta.env.VITE_OIDC_CLIENT_ID || '').trim()

if (authority && clientId) {
  const manager = new UserManager({
    authority,
    client_id: clientId,
    response_type: 'code',
    scope: 'openid profile email',
    redirect_uri: window.location.href,
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    automaticSilentRenew: false,
    monitorSession: false,
  })
  void manager.signinSilentCallback()
}
