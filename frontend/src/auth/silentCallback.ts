import { InMemoryWebStorage, UserManager, WebStorageStateStore } from 'oidc-client-ts'
import { publicRuntimeConfig } from '../runtimeConfig'

const { oidcAuthority: authority, oidcClientId: clientId } = publicRuntimeConfig()

if (authority && clientId) {
  const manager = new UserManager({
    authority,
    client_id: clientId,
    response_type: 'code',
    scope: 'openid profile email',
    redirect_uri: window.location.href,
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    // This must match AuthProvider's short-lived PKCE transaction store. The
    // callback is loaded in a same-origin frame and does not persist a user,
    // bearer token, profile, workspace, or authorization decision.
    stateStore: new WebStorageStateStore({
      store: window.sessionStorage,
      prefix: 'datariver.oidc.transaction.',
    }),
    automaticSilentRenew: false,
    monitorSession: false,
  })
  void manager.signinSilentCallback()
}
