# Phase 6D Admin/auth session-epoch PRD and execution checklist

## Purpose and scope

This package closes `R5-FE-02`. It prevents a delayed authentication response, OIDC session
transition or token-renewal race from publishing data into a browser tree created for a different
authenticated security context.

The backend remains the authorization authority. The browser epoch is an opaque, process-local
discard fence; it is not a role, permission, token claim, session identifier or replacement for
current membership, RLS, ABAC and assurance checks.

No database, migration or public JSON payload changed. The only HTTP semantic refinement is that
successful `GET /auth/me` and `GET /admin/me` responses are explicitly
`Cache-Control: private, no-store`.

## Product and security requirements

| ID | Requirement | Local disposition |
|---|---|---|
| ASE-01 | Publish the OIDC user and server-verified `/auth/me` profile as one accepted in-memory snapshot. The two external subjects must match. | Implemented |
| ASE-02 | Maintain an opaque monotonic `securityEpoch` that changes when the authenticated subject, provider session or security-bearing profile facts change. Never persist or log the epoch or raw session handle. | Implemented |
| ASE-03 | Bind every profile hydration to an AbortController and monotonic generation. A newer load, unload, sign-out or unmount makes every older result stale even if transport cancellation is ignored. | Implemented |
| ASE-04 | Coalesce concurrent renewal, preserve a newer OIDC event over an older renewal result/failure, and reject a renewal whose subject differs from the accepted server-verified subject. | Implemented |
| ASE-05 | Increment a separate accepted-hydration revision after every successful `/auth/me`. This revalidates Admin eligibility after ordinary same-session renewal without remounting unrelated features. | Implemented |
| ASE-06 | Capture `{workspace, securityEpoch}` for every API request/download. Reject a late response or a `401` retry if either value changes. Existing safe/idempotent retry rules remain unchanged. | Implemented |
| ASE-07 | Hydrate `/admin/me` only from the verified profile subject, current Workspace, epoch and authorization revision. Abort older work, require the returned Workspace to match and hide the previous context while checking. | Implemented |
| ASE-08 | Remount global search and feature state on Workspace or security-epoch transition. During same-session Admin revalidation, hide/suspend the mounted subtree; resume it only for an unchanged returned context fingerprint, otherwise remount/purge its rows, forms, ETags, confirmations and idempotency keys. | Implemented |
| ASE-09 | A manual Admin-context refresh is no-store and fail-closed: it clears the previous context and pending confirmation before loading, validates the returned Workspace, and does not restore old controls on mismatch, denial or failure. | Implemented |
| ASE-10 | Bearer tokens, roles, Admin context, epoch and provider session markers remain absent from localStorage, IndexedDB and persistent session storage. The existing bounded PKCE transaction is the only sessionStorage use. | Implemented and statically verified |

## Runtime behavior

1. `AuthProvider` starts a generation-bound, `cache: no-store` profile hydration.
2. The response is accepted only when it is the newest generation and its `subject` exactly equals
   the OIDC `sub`.
3. A normal same-session renewal keeps `securityEpoch` and the stable `ApiClient` identity, but
   advances `authorizationRevision` so Admin discovery is suspended and re-read.
4. A subject, provider-session, assurance, authentication-time, role or operator-control change
   advances `securityEpoch`. Sign-out and unload invalidate memory before redirect/event completion.
5. `ApiClient` checks the captured security boundary after fetch, after renewal, after retry and
   after response-body parsing. A mismatch raises `StaleSecurityContextError`.
6. `App` exposes no Admin context until the current revision-bound `/admin/me` succeeds. The
   response's internal `subject_id` is not compared with the OIDC external subject; the backend
   derives it from the verified bearer and current Workspace, while the client-side epoch binds the
   response to that request.

## TDD and verification record

### RED evidence

- The initial focused frontend run produced `10` expected failures covering changed-claim epoch,
  A/B out-of-order hydration, subject mismatch, sign-out purge, request/retry/download drift and
  same-Workspace UI remount.
- The backend cache-contract tests initially failed `2/2` because neither successful route accepted
  a response object or emitted a no-store header.

### GREEN evidence

| Gate | Result |
|---|---|
| Focused auth/API/shell/Admin regression | `7` files / `69` tests passed |
| Frontend whole suite | `47` files / `266` tests passed |
| Frontend static/build | strict TypeScript, zero-warning ESLint and production Vite build passed |
| Backend whole suite | `1,421 passed / 97 environment-gated skipped` |
| Backend static | Ruff format/lint passed over `382` formatted files; strict mypy passed over `375` source/test files |
| Repository static verification | Compose, release context, identity assurance, browser storage, roles, architecture, tenant FKs, seed and docs passed |
| Schema/migration | Not applicable: no metadata or DDL changed; current sole-head migration evidence is inherited, not rerun as a new schema claim |

## Adversarial checklist

- [x] An older `/auth/me` response cannot overwrite a newer OIDC session.
- [x] Unload, sign-out and unmount invalidate pending hydration.
- [x] OIDC `sub` and `/auth/me.subject` mismatch fails closed.
- [x] A different-subject silent-renew result clears the old identity and returns no token.
- [x] An older renewal failure cannot clear a newer loaded session.
- [x] Failed verification of a newer `UserLoaded` event leaves no previous identity.
- [x] Same-session renewal preserves the security epoch and stable API client while advancing the
  authorization revision.
- [x] Same-session Admin revalidation hides the previous subtree, preserves an unchanged-context
  draft, and remounts only when the returned context fingerprint changes.
- [x] Changed assurance/security facts advance the epoch.
- [x] A `401` does not retry a read or idempotent mutation after epoch drift.
- [x] A late success or download is discarded after Workspace/epoch drift.
- [x] Same-Workspace epoch change purges feature and global-search state.
- [x] Manual Admin refresh uses no-store, rejects another Workspace and removes previous context
  and navigation on mismatch or denial.
- [x] Successful auth/Admin discovery is private and non-cacheable on both request and response
  paths.
- [x] Final independent source/security/traceability reviews report `P0=0`, `P1=0`.
- [x] This checklist and its accepted source/test changes form one isolated focused commit.

## External acceptance gates

The local evidence does not establish production identity or browser behavior. The following remain
`EXTERNAL_GATE`:

- real approved OIDC/Keycloak silent renewal, expiry, logout, session monitoring, account switch,
  token rotation and same-account new-login behavior;
- multi-tab logout/session transition and slow-response A/B journeys with two real users;
- Chrome, Firefox and Safari cache inspection, plus APISIX/Nginx preservation of
  `private, no-store`;
- preparation-PC WSL `linux/amd64` authenticated browser regression using the exact release source;
- IdP back-channel logout or instantaneous revocation, which requires a separate server/IdP
  architecture decision rather than a browser-epoch claim.

## Decision record

This is a conformance hardening of ADR-0009 and ADR-0025. It preserves the accepted stable-client
behavior for ordinary renewal and introduces no server-issued session nonce, cookie/BFF session or
public renewal protocol. Therefore no new ADR is required.
