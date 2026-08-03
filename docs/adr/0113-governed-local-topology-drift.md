# ADR-0113: Governed local topology drift

- Status: Accepted; governed Mac reconciliation source staging, runtime gate open
- Date: 2026-08-03
- Owners: DataRiver application, security and operations owners

## Context

The ignored `AppliedState` records which local Airflow, DataHub, Redis, object-storage, gateway and
graph capabilities an operator selected. Compose containers can outlive a later source or
configuration change, however, so a healthy container is not proof that it still belongs to the
selected topology. On the Mac development host, Neo4j and APISIX were running while
`local_graph=false` and `local_gateway=false`; the graph environment also selected the local
Compose endpoint. Silently treating those containers as selected would make stale state look
correct, while stopping them automatically could remove a dependency that is still in use.

## Decision

The existing update workflow performs a read-only local-topology audit after Compose configuration
and the existing running-service query, but before confirmation, build-capacity locking, local
reranker reconciliation or any Docker, service or AppliedState mutation.

The audit queries only the exact `datariver-next` and `datariver-local-connectors` Compose project
labels. DataHub keeps its existing provider-health probe and is not inferred from container names.
Video, trading and every unrelated project are outside the query boundary. Known Compose services
are projected to fixed logical keys; an unknown running service increments a bounded count without
retaining or printing its name. Raw labels, container IDs, image references, paths, environment
values and provider stdout/stderr are never operator evidence. Each private project query has one
fixed 20-second timeout and no retry; process, timeout or evidence failure stops with a fixed
sanitized classification.

Evidence keeps four independent classes:

- `expected-missing`: an AppliedState-selected service has no running container;
- `unexpected-running`: a known unselected service is running, or a selected service has duplicate
  running containers;
- `selected-unhealthy`: a selected running service with a Docker health contract is `starting` or
  `unhealthy`; and
- `intent-mismatch`: persisted topology and an allowlisted unambiguous environment intent disagree.

Graph intent is local only when projection is enabled and the credential-free Neo4j URI selects the
Compose `neo4j:7687` endpoint. The environment intent is never unioned into the AppliedState
expected set. Thus `local_graph=false` plus the local graph intent reports both runtime drift and
intent drift instead of silently adopting Neo4j. APISIX has no equivalent authoritative enable
value; a configured port is not treated as adoption intent.

Any non-empty class, duplicate or unknown-running count fails with the fixed
`LOCAL_TOPOLOGY_DRIFT` classification. Query or evidence failures are also sanitized and fail
closed. The audit performs no auto-stop, auto-adopt, restart, removal or AppliedState write.
Reconciliation is a separate governed operation: an accountable operator must choose the intended
topology, prove endpoint and health contracts and use the repository state writer rather than edit
the JSON file directly.

The sole in-place transition is the optional, development-only command
`development_cycle.py dev-publish --reconcile-local-topology
mac-development-graph-gateway-v1`. It accepts only the observed Mac pre-state: graph and gateway
are false in AppliedState, healthy Neo4j and APISIX are already running, local Neo4j intent is true,
and the explicitly enabled `governance-document-worker` is missing. Any additional missing,
unexpected, unhealthy, unknown or intent finding stops before mutation. Under the existing Docker
workflow lock, the operation opens the reviewed seven bind secrets as a required subset of the
shared canonical secret directory. Unrelated canonical entries neither fail nor influence the
selection. The operation retains the root, secret-directory and seven file descriptors, rechecks
their linked identities immediately before and after the worker Compose create (including an
ambiguous create failure), recovers only the missing worker, verifies its database role and backlog
with two separate fixed queries, then applies the checked-in APISIX/Web/Airflow routing overlays.
Neo4j is not recreated or written.
Only after the target audit passes does the normal atomic writer change `local_graph` and
`local_gateway` to true while preserving every other state field and fingerprint. Origin push
remains after the complete runtime transaction.

The metadata-only secret preflight follows the repository's canonical Mac bind-secret contract:
the directory is mode `0700` and each of the selected seven regular files is mode `0444`. The held
descriptors stay under the Docker workflow lock until the topology transaction ends. On an APFS
volume mounted with `noowners`, those metadata checks detect path and identity drift but do not
claim that Unix ownership bits provide confidentiality or ownership enforcement.

## Transparent authentication boundary

Keycloak remains the sole identity provider. APISIX contains only the exact `request-id`,
`limit-count` and `proxy-rewrite` plugins; it performs no OIDC, JWT, key, basic, HMAC, forward-auth,
consumer or CORS authentication. Authorization, Cookie, Origin, preflight and correlation headers
continue through the Web and APISIX hop without a new credential exchange. The API remains the
only token/session-epoch verifier and the authority for Workspace, Action, Domain, System and
classification ABAC; PostgreSQL RLS remains the database lower bound. APISIX never reports an
authenticated or authorized state.

The source currently has no approved, non-mutating automated credential source that can exercise
the complete authorized, denied, expired, membership-revoked and session-revoked matrix for both
Knowledge and Change Request. Existing service accounts do not hold those human read permissions,
and the human development client deliberately disables direct grants. Therefore the live
unauthenticated/CORS/header/log probe is not treated as authentication-parity evidence. Under the
exclusive Docker workflow lock, the reconciliation fails closed with
`GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE` before refresh-bootstrap, capacity/cache action, reranker,
build, worker, APISIX, Web, Airflow, target audit, AppliedState write or origin push. The later live
routing probe is unreachable until a separately reviewed full parity plan exists. Gateway adoption
remains open; static status integers are never accepted.

The selected Web overlay has one fixed upstream, `apisix:9080`, depends on healthy APISIX and has
no direct API fallback. Ordinary workers keep their existing database/provider/API paths. Selected
Airflow API calls transparently forward the same service Bearer token through APISIX, while token
acquisition remains directly against Keycloak. The fixed 12 MiB proxy limit preserves the existing
bounded Knowledge and Change Request multipart contract. Browser public origin, OIDC authority,
client ID and redirect URI are unchanged.

Mac development accepts `limit-count` keyed by `remote_addr`: users behind the local Web proxy can
share one bucket and receive APISIX `429`. This is an availability/rate decision, never an
authentication `401` or authorization `403` decision. A failed gateway yields availability failure
only; it cannot fall back to a public/direct API path or bypass API ABAC/RLS.

## Compatibility

- `development_cycle.py dev-publish`, `workflow_update_restart.py`, `prep-update` and `prep-check`
  keep their names and existing arguments.
- No environment key, Dockerfile, service profile or required daily input changes. The optional
  operation alone selects the checked-in Web/APISIX and Airflow routing overlays.
- Optional worker intent continues to come from its existing explicit enable flag; one-shot and
  unselected exited containers are not reported as missing.
- Running services without a Docker healthcheck are accepted as running; services that define a
  healthcheck must reach `healthy`.
- Without the exact optional reconciliation token, `dev-publish`, update, preparation and check
  semantics remain unchanged and the current drift remains fail-closed.

## Runtime and evidence boundary

Source tests prove allowlisting, the four classifications, project exclusion, output sanitization,
transparent gateway configuration and state-last/push-last ordering. They do not claim that the
current Mac runtime has completed the transition. The canonical command must still prove direct
API versus Web-to-APISIX status/header parity for Knowledge and Change Request flows, target
topology health, unchanged OIDC redirect registration and credential-free logs before state write.
There is no auto-stop architecture.

Production and Ops remain `OPEN_TARGET_GATE`. Trusted TLS termination, authoritative HTTPS scheme,
trusted-proxy client-IP derivation, shared-NAT rate sizing, DNS, listener exposure, target OIDC
redirects and real 401/403/revocation parity require evidence from the actual target. Mac-local
`remote_addr` behavior and loopback listeners are not production readiness evidence.
