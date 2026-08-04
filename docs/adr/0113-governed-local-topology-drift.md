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
mac-development-graph-gateway-v1`. It accepts only either of two complete Mac pre-states. The
`initial` checkpoint requires graph and gateway false in AppliedState, healthy Neo4j and APISIX
already running, local Neo4j intent true, and only the explicitly enabled
`governance-document-worker` missing. The `web-missing-recovery` checkpoint requires that same
complete evidence plus `core.web` missing, which is the one reviewed partial state left by the same
governed transition. For unexpected running managed services, health remains separate bounded
`unexpected-unhealthy` evidence rather than being discarded or overloaded into
`selected-unhealthy`. Both complete checkpoints require healthy APISIX and Neo4j and empty selected
and unexpected unhealthy evidence. Any other missing, unexpected, unhealthy, unknown or intent
finding stops before mutation. The immutable plan records the checkpoint, so a change between the
first audit and the locked audit also stops. This is not a general resumability contract; any other
partial state requires a separate exact RCA and review.

Under the existing Docker workflow lock, the operation opens the reviewed eight bind secrets as a
required subset of the shared canonical secret directory. Unrelated canonical entries neither fail
nor influence the selection. The operation retains the root, secret-directory and eight file
descriptors, rechecks their linked identities immediately before and after the worker Compose
create (including an ambiguous create failure), recovers only the missing worker, verifies its
database role and backlog with two separate fixed queries, then applies the checked-in
APISIX/Web/Airflow routing overlays. Both checkpoints use that same governed order: APISIX is
reconciled before Web is force-recreated exactly once through its selected gateway overlay. There
is no preliminary manual Web start. Neo4j is not recreated or written.
In reconciliation mode the general `ChangePlan` immediate-restart set reserves exactly Web and the
plan's named missing worker, so the worker has one governed `up --no-build` site after any selected
image build proof. The same exact reservation filters migration-time general stops, so neither Web
nor the named worker is stopped before its governed recovery. The displayed plan identifies the
governed worker, APISIX build/up, Web force-recreate and selected Airflow recreation before operator
confirmation. The general graph restart flag is suppressed for both execution and displayed plan
evidence: Neo4j is observed and required healthy at both audits but is never mutated by this
transition. Tokenless update behavior retains its existing worker, Web and graph restart semantics.
Only after the target audit passes does the normal atomic writer change `local_graph` and
`local_gateway` to true while preserving every other state field and fingerprint. Origin push
remains after the complete runtime transaction.

The metadata-only secret preflight follows the repository's canonical Mac bind-secret contract:
the directory is mode `0700` and each of the selected eight regular files is mode `0444`. The held
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

The user-approved Mac-development parity operation, `SEC-GATEWAY-AUTH-PARITY-001-A-V1`, is an
exact, one-attempt fixture inside the exclusive Docker workflow lock. It creates one task-named
public PKCE `S256` client and two
task-named disabled human users. Direct grants, implicit flow, service accounts, WebAuthn,
real-user credentials and reusable client secrets remain disabled or absent. The canonical
local-bootstrap module creates only two fixed inactive Subjects and Workspace Memberships in the
existing local development Workspace: one allows exactly `kg.read` and `change.read`, while the
other explicitly denies exactly those actions. It assigns no administrator, service or profile
role. The Keycloak users and database rows are enabled only after both disabled sides exist.
Before any fixture client deletion, the cleanup path rediscovers only the fixed task name and
requires the full public-client marker, exact default/optional scopes, client-authenticator and
authentication-flow defaults, disabled auth surfaces, PKCE attributes and either the exact
audience mapper or the valid pre-mapper partial-create state. Cleanup deliberately invalidates any
earlier Admin API token once at its boundary before rediscovery.
Ambiguous, multiple, UUID-mismatched or drifted clients are retained and reported as cleanup
required; no real or general client is a deletion target.
The production `datariver-web` invariant is captured from its exact Admin API client document and
complete bounded protocol-mapper inventory, not from a search summary. The fingerprint covers the
client UUID and name, protocol and authenticator, every reviewed authentication-flow flag,
redirect/origin lists, PKCE and other authentication attributes, default/optional scopes and the
normalized mapper configuration. Missing, duplicate, extra or drifted authentication surfaces fail
closed without exposing their values.

The fixed Mac-development diagnostic `classify_gateway_production_invariant.py` uses that same
private normalizer; it does not duplicate or relax the runtime predicate. Normal reconciliation
continues to collapse every internal predicate to
`GATEWAY_AUTH_PARITY_PRODUCTION_INVARIANT_FAILED`. The diagnostic holds the existing exclusive
workflow lock, requires the exact Mac AppliedState and ignored environment fingerprint, retains the
reviewed eight-secret guard and reads the held administrator-password descriptor through its
existing pre/post revalidation. It then performs exactly one memory-only administrator token grant
(`admin_token_grant=1`) followed only by the fixed `datariver-web` search, exact client-document and
complete bounded mapper reads. This administrator boundary is not a human or fixture PKCE login.
Password, token, provider response, client/mapper content and fingerprint are discarded locally.

Its only evidence is one line containing a closed predicate, known booleans and bounded client or
mapper counts when available, plus `mutation_count=0` and `retry_count=0`. Missing counts are omitted
rather than estimated. The executable accepts no URL, realm, client or field argument and performs
no fixture absence check, create, update, delete, logout, PKCE flow, topology/capacity action,
Docker/service operation, state write or push. Source acceptance does not authorize this Admin read;
runtime remains a separate reviewed exact-one operation.

The `CLIENT_BOOLEAN_SHAPE` diagnostic refines only its value-free evidence. The checked-in realm
template and exact host-development updater explicitly set
`authorizationServicesEnabled=false`. In pinned Keycloak 26.7, however, the Admin GET
representation emits this field only as `true` when an Authorization ResourceServer exists and
omits it when Authorization Services are disabled; it never serializes `false`. The shared
normalizer therefore scans the complete fixed ordered field enum once and classifies each entry
only as `PRESENT_BOOL`, `MISSING` or `NON_BOOL`, then normalizes omission to `false` only for the
exact `AUTHORIZATION_SERVICES_ENABLED` field on a private document copy. Omission and explicit
`false` have the same fingerprint. Present `true` fails the closed
`CLIENT_AUTHORIZATION_SERVICES_POLICY` predicate before mapper reads. Missing any other boolean or
any non-boolean value still fails the existing shape boundary. Normal reconciliation continues to
map every internal predicate to the existing generic production-invariant failure. This exact
version-bound rule does not authorize a wildcard provider default or Keycloak Authorization
Services: Keycloak remains the identity provider, while API membership/session checks and ABAC plus
PostgreSQL RLS remain the authorization authorities.

The checked-in Mac-only `converge_gateway_web_authorization_services.py` operator is the sole
narrow existing-client convergence boundary. It accepts no arguments or target overrides, holds
the exclusive Docker workflow lock, proves the exact AppliedState/environment/eight-secret guard
and pinned Keycloak 26.7 container/image identity, and uses the held administrator-password
descriptor. The shared full client-and-mapper normalizer must pass before mutation with the raw
wire status exactly `MISSING` or `FALSE`. The sole permitted mutation attempt is one Admin `PUT` to
the already resolved exact `datariver-web` UUID with the complete literal body
`{"authorizationServicesEnabled": false}`; create, delete, realm, mapper, redirect, origin, theme,
session, secret and other-client writes remain forbidden. A second full read must prove the same
UUID/client, `MISSING` or `FALSE`, and an unchanged private fingerprint. The operator emits only a
closed bounded result, action/request counts and known/unknown booleans; passwords, tokens, UUIDs,
fingerprints, URLs, bodies and provider values remain private.

An unavailable or non-204 action response is ambiguous even when the bounded read-only postcheck
still sees the desired invariant. It is reported as operator review required, never retried or
inferred successful. A monotonic action-attempt marker is set before the request; any later request,
postcheck, identity-release, secret-guard or lock-finalization defect preserves that action evidence,
downgrades the result to operator review required and still attempts every independent final guard.
There is no automatic rollback: the accepted prestate and desired state are
both semantically false in pinned Keycloak 26.7, while a compensating full-client write would be a
broader and less safe mutation and cannot recreate a distinct omitted-false wire representation.
The general `configure_keycloak_host_dev.sh` bootstrap remains valid for its canonical authorized
workflow, but its multi-client/realm/identity envelope is not this narrow operator contract.

The fixed no-argument `workflow_update_restart.py` fixture diagnostic is the sole checked-in
operator boundary for a failed pre-mutation fixture absence proof. It holds the existing exclusive
Docker workflow lock, requires a clean exact Mac-development build AppliedState and environment
fingerprint, applies the governed capacity and active-builder-idle gates, and builds only the
`local-bootstrap` image once. The host fingerprints the identity-pinned current fixture module;
after the build it reproves clean source, the same source fingerprint and builder idle. The one
ephemeral `local-bootstrap` run then compares its baked module with that private fingerprint before
any database query. A stale, missing or ambiguous module therefore yields fixed image-provenance
evidence and query zero. This boundary honestly has Docker image-build action at most one and
ephemeral-container action at most one, with retry zero; it is read-only only with respect to
application, identity and database state. Its outer evidence separately records the governed cache
action count and known outcome, build attempted/succeeded/known outcome, final selected-builder
idle proof, exact ephemeral-container attempt, bounded stop/remove attempts, cleanup-required and
known/unknown residual state. Business, data, identity, topology, AppliedState and push mutation
counts remain zero.

The local-bootstrap build is followed by a selected-builder idle proof in an unconditional
finalization boundary, including nonzero, timeout, kill or reap ambiguity; failure to prove idle is
operator-review-required evidence while the exclusive lock is still held. The ephemeral run uses
one fixed task-owned name plus exact contract/operation labels and requires that name absent before
the attempt. After every attempt, including client response loss, timeout, overflow or interrupt,
only that exact labeled one-off may be stopped and removed, each at most once. A foreign, ambiguous
or retained exact-name observation is never touched and remains cleanup-required or unknown
evidence. Docker CLI termination is not treated as proof that the daemon-side container is absent.
A child `PASS` is accepted by both the standalone diagnostic and canonical parity session only
after cleanup is known, no cleanup is required, residual state is known and its count is zero. A
non-PASS child predicate remains the first defect when cleanup also fails; a child PASS with an
unknown or retained container becomes the fixed unknown predicate before any identity creation.

The fixed `--diagnostic-phase HOST_ENVIRONMENT_PREFLIGHT` operation is the narrower read-only
classifier for a fixture diagnostic that stopped with `ENVIRONMENT_DEPENDENCY` before its governed
build attempt. It holds the same exclusive workflow lock and reuses the canonical AppliedState
loader, repository-path resolution, regular environment-file guard, environment parser and
key-schema fingerprint, and Compose-file selection. It stops before source/image provenance,
capacity or cache probing, builder inspection, build, Compose execution, network or login, database
access, identity, topology, AppliedState write or push. Its closed first-failure predicate is exactly
one of `APPLIED_STATE_CONTRACT`, `PROFILE_SELECTION`, `DEPLOYMENT_MODE_SELECTION`,
`GATEWAY_SELECTION`, `GRAPH_SELECTION`, `ENV_PATH_CONTRACT`, `ENV_FILE_CONTRACT`, `ENV_READ`,
`ENV_FINGERPRINT`, `COMPOSE_SELECTION`, `PASS` or `UNKNOWN`. The one-line evidence contains only
classification, fixed phase, predicate, mutation count zero and retry count zero. Environment keys,
values, hashes and paths, secrets, state SHAs, Compose paths and exception text are never emitted.
Unexpected arguments fail before lock acquisition, and a lock acquisition or release defect yields
operator-review-required `UNKNOWN` rather than a false pass. An interrupt or other `BaseException`
at any canonical preflight step follows that same unknown review boundary; it is never reported as
proof that a specific environment predicate failed.

The fixed `--diagnostic-phase BUILD_CAPACITY_PREFLIGHT` operation is the next disjoint read-only
classifier after that host phase passes. Under the same exclusive lock it repeats the canonical
host preflight and clean current-source proof, then calls the governed capacity evaluator only in
its immutable `MEASURE_ONLY` mode for `local-bootstrap`. One shared structural recorder distinguishes
the lock, clean checkout, Dockerignore, Compose config, selected build contract, tracked context,
local Docker context, builder-list probe, builder selection, platform, image, cache, backing
filesystem, capacity policy, cache-policy support and cache active-build boundaries without parsing
exception text. `CACHE_ACTION_REQUIRED` stops immediately before a prune. A following initial
builder-idle probe distinguishes an unavailable/invalid probe from an observed active build.
Within the top-level builder-selection phase, a separate closed subpredicate distinguishes every
reviewed selection branch without disclosing builder, context, node, endpoint, driver, status or
environment values. `builder_selection_known` is always present; the subpredicate is present only
when structurally observed. A selection failure retains top-level `BUILDER_SELECTION`; observed
success records `PASS` monotonically through later or outer review-required results. Pre-selection
or interrupted unknown results omit it, and no phase name is used to reconstruct it.
If lock/context exit also fails after a recorded selection failure, the review-required result
retains top-level `BUILDER_SELECTION` plus that exact first subtype; every other review-required
top-level result remains `UNKNOWN`.
Within the builder `NODE_SCHEMA` subtype, `node_schema_known` is always present and an optional
closed node-schema predicate is emitted only when structurally observed. It distinguishes a
non-mapping node and missing, null or non-string name/endpoint or present-status fields without
emitting any provider value. A non-PASS node subtype requires the top-level builder subtype to
remain `NODE_SCHEMA`; a complete structural scan records `PASS` monotonically through later
selection or outer failures. A simultaneous node-schema first defect and lock/context-exit defect
therefore remains review-required with top-level `BUILDER_SELECTION`, builder subtype
`NODE_SCHEMA` and the exact closed node subtype. Pre-scan interruption remains unknown and omits
the subtype; null and reconstructed values are forbidden.
The source-clean boundary preserves the closed states `CLEAN`, `DIRTY`, `INVALID` and `UNKNOWN`
without reducing an interrupted Git or file-identity proof to an environment defect. The initial
source fingerprint remains private and is revalidated after capacity evaluation, before an action-
required result, and after the idle probe before `PASS`. Every argument beginning with the
`--diagnostic-phase=` prefix is intercepted before normal argument parsing. A malformed known prefix
returns its corresponding fixed phase with `UNKNOWN`; an unknown or duplicate equals selector
returns one fixed `INVALID_DIAGNOSTIC/UNKNOWN` result. No noncanonical form echoes operator input.

Its single line contains only a closed classification, the fixed phase and predicate, and zero
mutation, cache-action, build, container and retry counts. Builder names, paths, resolved Compose,
service/image/cache identities, byte values, environment material, commands and provider output are
not evidence. `KeyboardInterrupt`, `SystemExit`, another `BaseException`, or lock finalization drift
is `OPERATOR_REVIEW_REQUIRED/UNKNOWN`. The phase stops before prune, build, ephemeral container,
database, network login, fixture identity, topology, AppliedState write or push. A pass is only
diagnostic evidence and does not authorize the no-argument fixture operation or canonical publish.

The child and parent share one closed `REQUIRE_ABSENT` envelope whose value-free predicate is
exactly one of PASS, fixed-input/protocol, environment/dependency, repository-not-absent,
repository-query/dependency, image-provenance, process-spawn, process-timeout, process-nonzero,
output-size, output-line, output-JSON, output-shape, output-tuple or unknown. The child emits one
bounded fixed line. The parent captures stdout and stderr under one hard in-flight byte cap, with a
fixed timeout and terminate, bounded wait, kill and bounded reap sequence, then accepts only the
exact grammar; SQL/provider output, identifiers, statements, counts and exception payloads are
never forwarded or persisted. This diagnostic performs SELECT-only absence checks and stops before
fixture or Keycloak identity creation, prepare/enable, topology mutation, AppliedState write or
push. It is not a general fixture runner and does not authorize a canonical reconciliation retry.

The operation then executes real HTTP requests for Knowledge Registry and Change Request through
the direct loopback API, loopback APISIX and Web proxy. It requires identical bounded status,
response-header and body-digest evidence for authorized `200`, explicitly denied `403`, malformed
`401` and genuinely expired `401` requests. It obtains a fresh still-valid access token, sets the
allow Membership to `active=false` and advances its version through the fixed local-bootstrap
operation, proves that the token is still unexpired on both sides of that update and requires the
same `403` through all three hops. Authorization, Cookie, Origin, CORS and selected response headers
must remain identical; token, password, verifier, code, cookie and provider responses stay in
private process memory and must not occur in APISIX, Web or operator output. Static status integers
are never evidence.
Immediately before the first credential-bearing direct/API gateway/Web request, the traffic probe
records one UTC operation timestamp. Cleanup scans the complete interval for `api`, `apisix` and `web`
without a relative-time or tail-line truncation. The combined log stream is capped in flight;
overflow, timeout, child failure or reap failure produces only a fixed classification and retry
count zero.
The genuine-expiry boundary shares the API verifier's exact 30-second leeway: `exp + 30` is not
expiry evidence, while `exp + 30 + 1` is, and the single wait is bounded by the fixture token TTL
plus that leeway. On the reviewed loopback HTTP target, Secure cookies from the initial Keycloak
authorization response are normalized for loopback before the credential POST and before every
following same-origin request. Cookie values remain private.

Immediate logout/session-epoch invalidation is recorded honestly as `OPEN_UNSUPPORTED`; the
membership result is never substituted for it. Any mutation enters one BaseException-safe,
exactly-once best-effort cleanup: revoke fixture sessions and delete the two users, delete the exact
database memberships/subjects only after proving that role and canonical-admin assignments are
already absent, delete the task client,
then prove both Keycloak production-client invariants and zero fixture privilege residual. Cleanup
first locks and validates each fixed Subject and local Membership. While those locks remain held it
re-reads the exact issuer/external-subject alias set, all-Workspace Membership count and every
privilege residual immediately before destructive SQL. It validates the complete human Membership
envelope, including the exact prepare/enable/revoke version;
swapped, aliased, drifted, privilege-bearing or invalid-lifecycle rows are
retained rather than normalized by cleanup. A first
topology/parity failure is preserved independently. An independent cleanup-required outcome and a
log-evidence failed/known outcome are reported as separate bounded fields, never by raw exception
chaining. A credential log defect never
masquerades as residual cleanup, and KeyboardInterrupt follows the same cleanup boundary.
The probe has retry count zero and no standalone mutation entry point. Only after the parity matrix
and the target topology audit pass may the normal state writer persist graph/gateway adoption; the
canonical `dev-publish` push remains last.

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
the fixed least-scope PKCE fixture, transparent gateway configuration, real executor invocation,
exact cleanup and state-last/push-last ordering. They do not claim that the current Mac runtime has
completed the transition. The canonical command must still execute the exact one-attempt parity
matrix, prove target topology health, unchanged OIDC redirect registration, credential-free logs
and zero fixture residual before state write. There is no auto-stop architecture.

Production and Ops remain `OPEN_TARGET_GATE`. Trusted TLS termination, authoritative HTTPS scheme,
trusted-proxy client-IP derivation, shared-NAT rate sizing, DNS, listener exposure, target OIDC
redirects and real 401/403/revocation parity require evidence from the actual target. Mac-local
`remote_addr` behavior and loopback listeners are not production readiness evidence.
