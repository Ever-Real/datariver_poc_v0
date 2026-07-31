# Security and ABAC definition

## Trust boundaries and threats

Untrusted inputs include browser/API payloads, OIDC claims before verification, DataHub/provider responses, uploaded files, object metadata, LLM output, graph content, webhook/event duplicates and operator-supplied connection settings. Primary threats are IDOR/cross-workspace access, search existence leakage, privilege escalation, confused-deputy worker actions, SSRF, prompt injection, arbitrary query execution, secret/log exposure, malicious uploads, replay and false workflow completion.

## Identity

- Production accepts asymmetric OIDC JWTs after signature, issuer, audience, expiry, not-before and allowed-algorithm validation.
- Subject ID is `(issuer, sub)` mapped to a DataRiver subject and active workspace membership.
- Workspace comes from the route/header but must match an active membership; a token-provided default does not grant access.
- Administrative/high-classification actions require a recent phishing-resistant authentication
  context. DataRiver recognizes hardware WebAuthn only when the signed token contains an exact,
  deployment-approved ACR and AMR combination plus `auth_time`; generic MFA, OTP and `iat` are not
  substitutes. Password reauthentication never becomes hardware assurance.
- Service identities are separate from users, scoped to one purpose and never impersonate a human approver.
- API-product invocation accepts only an active, non-expiring `SERVICE_ACCOUNT` Subject with an
  active workspace membership. A V2 grant binds that Subject, its normalized issuer and exact OIDC
  `client_id`; a client string alone is legacy evidence, not invocation authority.
- Administrator membership changes never accept arbitrary identity-provider JSON. The direct path
  requires recent hardware WebAuthn. The default-disabled fallback accepts only the versioned full
  membership-access command and requires a recent password-authenticated maker, an independent
  eligible human checker, a five-minute expiry, canonical payload confirmation and one-time consume.
  At least two eligible human security administrators must remain; service accounts, OTP and
  ordinary password assurance are ineligible.
- The browser keeps the OIDC user/token object and the selected Workspace only in memory: neither
  `localStorage` nor `sessionStorage` holds a bearer token, refresh token or tenant/RLS context.
  Only the OIDC library's short-lived PKCE transaction state is stored in tab-scoped
  `sessionStorage` (never `localStorage`) to validate a redirect; it carries a versioned authentication
  intent and same-origin relative return path across a redirect. It never carries a mutation body,
  idempotency key or executable callback, and approval/publish operations are never replayed after
  WebAuthn. Backend authorization remains authoritative.
- Knowledge Studio may persist only a typed, unsent Step 1 recovery record in same-origin IndexedDB.
  The record has no token, credential, role, clearance, permission result, raw Workspace ID or raw
  Subject ID; an in-memory SHA-256 scope selects it and every replay is reauthenticated,
  reauthorized and checked by RLS. It is removed after confirmed persistence or an explicit
  latest-version reload. IndexedDB is not an encryption boundary or canonical truth, and
  `localStorage`/`sessionStorage` remain prohibited for Draft payloads.
- Data Enricher source discovery reuses Catalog ABAC and the classification-access snapshot before
  any DataHub enrichment. Browser contracts expose a local asset UUID, bounded field paths and two
  opaque version strings, never an external URN, provider query, endpoint or credential. A new
  binding fails closed for stale detail, projection/schema drift, an inactive Dataset, a source
  above the Draft classification envelope, an unaccepted T-Box target or a field absent from the
  server-returned schema. Forced workspace and restrictive Draft-author RLS remain authoritative.

## ABAC vocabulary

| Category | Required attributes |
|---|---|
| Subject | workspace, department, groups, job function, clearance, allowed system/domain IDs, auth strength, active |
| Resource | workspace, owner department, system/domain, classification, sensitivity, lifecycle, share scope |
| Action | `catalog.read`, `change.create/review/approve`, `quality.read/profile.read/rule.*/run.*`, `kg.read/edit/publish/share`, `chat.query`, `attachment.download`, `admin.manage`, etc. |
| Environment | time, network zone, client type, authentication age, purpose, request/CR ID |

## Decision algorithm

1. Verify identity and membership.
2. Resolve the protected resource without disclosing forbidden existence.
3. Resolve subject/resource/environment attributes from canonical stores.
4. Evaluate all applicable policy versions; default deny and explicit deny wins.
5. Require workspace equality and clearance/range constraints.
6. Apply separation-of-duties and strong-auth rules.
7. Set transaction-local workspace/subject attributes for PostgreSQL RLS.
8. Apply field-level redaction.
9. Persist decision ID, policy versions and reason codes; a bounded list/Chat evaluation may use one grouped record containing per-resource effects instead of one transaction/row per candidate. Avoid sensitive raw inputs.

Typed upload candidate reads require `registration.read`, `catalog.read` and `change.create`. The
service first validates READY receipt/V2 hash evidence, then batch-loads only current ACTIVE DATASET
targets under the classification snapshot and applies grouped authorization. A missing, denied,
legacy or identity-drifted row fails the complete page through the same existence-hiding response;
the API never reveals the failing ordinal or falls back to DataHub/object storage.

Manual metadata submission requires fresh `catalog.read` and `registration.create` decisions on the
selected current DATASET. It compares both the authorization-pruned projection version and the
fresh provider canonical version before any DB/object write, rehydrates the full provider schema
server-side and accepts only sparse editable field values from the browser. It then creates an
append-only PostgreSQL record and a server-authored CSV receipt in the deployment-configured
InfoSchema bucket. The storage coordinate, Airflow service
identity and DataHub service credential are never returned to the browser.  Only the Airflow service
identity with `catalog.sync` may claim an apply lease; it calls the typed internal boundary, which
streams and hash-verifies the private CSV before DataHub read–merge–read-back.  Vocabulary
suggestions are catalog discovery reads under the same authorization scope; entering an absent
Tag/Term/Domain only creates typed intent and never calls a provider from the browser.

Every Manual/BULK browser route first enforces an active human security administrator or a
canonical Data Steward and then performs the route-specific authorization. The page capability is
private/no-store and reveals only a fixed eligibility/reason/role contract; it does not echo OIDC
claims, group sets, tokens or provider credentials. A Data Steward can read only submissions whose
requester is the current subject. Workspace history is security-Admin-only. PostgreSQL repeats that
owner/Admin/purpose-bound-worker split through restrictive forced-RLS reader policies, so a missed
HTTP filter cannot widen evidence reads.

The accountable actor for a registration write is the initiating DataRiver human stored on the
intent, candidate binding and authorization audit. Provider mutation is executed by a separate
least-privilege DataHub service principal. DataRiver never accepts a DataHub credential or delegated
browser token in a registration request. Five ordered aspect hash read-backs, not the service
principal's successful response, establish Manual completion. BULK candidate creation similarly
requires the immutable receipt/object-locator SHA-256, a fresh current-target read and the exact
preview ETag before the candidate binding, Change Request item and outbox event commit atomically.

## Mandatory policies

- Workspace mismatch always denies.
- Inactive subject, membership, resource or expired grant denies.
- `resource.classification <= subject.clearance` and system/domain assignments must match.
- A requester cannot provide final approval. High-classification publish/apply/share requires two distinct eligible approvers.
- Attachment URL issuance and every actual download perform fresh authorization.
- Search, facets, suggestions, counts, exports and SSE apply the same ABAC scope as detail reads.
  ADR-0020 is the sole exception: its audited `catalog.quarantine.read` decision permits an eligible
  human security administrator to inspect only non-deleted, same-workspace quarantined catalog
  projections for classification remediation. It never applies to export, Chat, attachments,
  arbitrary provider egress, mutations, service identities or another workspace. The existing typed
  DataHub metadata enrichment remains available only through authorized catalog detail.
- Chat filters evidence before model invocation. Every external stage additionally requires its
  deployment-selected immutable profile UUID and exact route/provider/model/deployment identity to
  match the active classification rule.
  The exact provider-bound rule set is applied to the catalog query before vector candidate text
  reaches an embedding provider. After composition, Chat re-reads current membership attributes
  and canonical catalog or active-release evidence, re-resolves the exact
  policy-ID/hash/version/generation and re-runs resource authorization for every citation before
  persistence; drift, revocation or dependency failure yields no answer evidence.
- Existing Chat session requests read and match the canonical session owner before authorization,
  budget reservation, retrieval or provider invocation. The application predicates and
  restrictive owner RLS remain independent, defense-in-depth controls.
- Before a governed workspace classification policy is active, Search/detail cannot return
  RESTRICTED assets and Chat cannot retrieve evidence above INTERNAL. A future explicit Search grant
  may narrow the Search deny, while RESTRICTED Chat remains a non-overridable deny.
  The ADR-0020 administrator review scope may expose the local quarantined projection only; it is
  not a RESTRICTED Search grant and cannot expose Chat evidence or an export artifact.
- Search cache keys bind workspace, complete subject permission scope, policy version, request shape and projection watermark; non-empty short queries and unescaped wildcard semantics are rejected.
- Policy service failure is fail-closed for protected reads and writes.
- Gateway authentication, DataHub permissions, a UI-hidden button, or graph-database users never substitute for application authorization.
- API-product first execution and replay both reauthorize current membership, Subject, issuer,
  grant, product/version, governed release lineage, permission fingerprint and retention binding.
  A matching idempotency key never revives revoked or drifted authority. The raw key is not stored,
  successful responses are `private, no-store`, and authorization-only quota reservation is
  retired.
- Legal Hold takes precedence over expiry, lifecycle rules and erasure. A missing or ambiguous hold
  evaluation denies the destructive operation.
- A retention duration, expired timestamp, object lifecycle result or provider capability label is
  never deletion authority. Automatic deletion and partition detach/drop remain disabled until the
  governed retention gates in ADR-0010 are implemented and verified.

## Governed Quality security boundary

ADR-0077 introduces separate human Actions `quality.read`, `quality.profile.read`,
`quality.rule.propose`, `quality.rule.review`, `quality.rule.activate`, `quality.rule.revoke`,
`quality.rule.archive`, `quality.run.request`, `quality.run.cancel`, `quality.run.retry`,
`quality.operations.read` and `quality.audit.read`, plus service-only `quality.dispatch`,
`quality.execute` and `catalog.profile.collect`. Existing `catalog.sync`, `admin.manage`, browser
Role labels or service group names do not imply any of them. Every decision still intersects
current workspace membership, clearance, System/Domain, classification policy, lifecycle, Policy
Book restrictions, explicit deny and forced workspace RLS. The route-to-Action matrix in
`docs/52_GX_QUALITY_MANAGEMENT_PRD_CHECKLIST.md` is normative; generic "mutation" permission does
not exist.

Rule versions are immutable. The author cannot review or activate their version; service identities
cannot propose, review, activate or revoke. Activation and revocation require a current
independently eligible human, `If-Match`, durable idempotency and recent approved hardware WebAuthn.
Revocation is deny-first; reactivation requires a new version and review. A manual source run
reauthorizes its requester immediately before source access. A scheduled run relies on the current
unrevoked activation decision rather than impersonating the author, and revalidates the current
target/policy plus both purpose-bound service identities.

The browser submits only a local asset ID, a server-returned field identity, RuleKind, severity and
typed parameters. The server derives the provider/source/System/Domain/classification/schema and
connection-profile binding. External URNs, provider relation names, arbitrary GX
expectation/kwargs/suite/checkpoint documents, BatchRequest, datasource or connection URL, SQL,
GraphQL, Python/import/plugin and row conditions are absent from the public schema. `REGEX` remains
unavailable until the complete engine/compiler/connector grammar has a bounded-execution proof.

Airflow owns only `quality.dispatch` and has no GX package, source/DataHub/object credential or
source endpoint. The NOBYPASSRLS quality worker owns only `quality.execute` and may resolve only the
canonical run's exact deployment-manifest connection profile through a mounted `file:` secret.
The connector enforces read-only source authority, server-owned quoted identifiers, a pinned
workload profile, complete source-access hard deadline, per-statement source-server timeout,
cancellation/connection close, scan/concurrency budget and exact egress/DNS/IP policy. Lease
renewal is forbidden during the source-access window and every statement rechecks the current
epoch/token. Any target, policy, version, lease, worker or source-binding drift causes zero further
source calls. Airflow dispatch also uses approved max-due/max-created bounds pinned in the
run-independent receipt; caller input cannot raise them or override the pinned SKIP/LATEST_ONLY/
OLDEST_FIRST missed-window policy, DB-time cutoff, late grace, evaluator or tzdb contract.

DataHub Profile collection uses a fixed GraphQL document and a server-owned URN variable. The v1
allowlist is table row/column/byte counts and field null/unique counts/proportions with full/sample
provenance and timestamps. Sample values, distinct frequencies, top values and example rows are
never requested, stored or returned. Min/max, mean/median/stdev, quantile and histogram remain
disabled until a classification/data-type disclosure policy and workload budget are approved.
The existing fixed typed API adapter or a separate `catalog-profile-collector` may hold a
least-privilege DataHub read token. The collector uses its own OIDC Subject,
`catalog.profile.collect`, NOBYPASSRLS role and one fixed Catalog projection function. The token is
never available to browser, Airflow or quality worker, and the collector has no source credential
or Quality write grant. Profile provenance is normalized to
`FULL/SAMPLE/PARTITION/QUERY/UNKNOWN`. A bounded raw partition exists only inside the fixed parser;
PARTITION/QUERY idempotency may retain a deployment-keyed HMAC-SHA-256 fingerprint and key ID.
Unkeyed digests and raw partition names/specifications never cross the adapter.

Raw GX output is untrusted. An allowlist sanitizer retains only exact rule/run/source/compiler/GX
hashes, boolean result, bounded evaluated/missing/unexpected counts/ratios, duration, observation
time and sanitized failure code. Unexpected rows/values/indexes, generated or rendered SQL,
queries, samples, exception text and connection data are discarded before DB, cache, queue, log,
trace or response. Sanitizer failure is an execution failure with no raw evidence persisted.

All dashboard cards, score denominators, trends and grids aggregate from the same
authorization-pruned asset relation. They expose neither global totals nor hidden buckets/deltas,
and visibly identify the result as permission-scoped. Until an organization approves small-cell
suppression, classification/System/Domain cohort buckets and every detailed distribution output are
unavailable; those attributes may only filter the permitted asset base. Cache and cursor security
scope includes workspace, full permission fingerprint, policy/generation, System/Domain,
profile/source/rule watermark and normalized request shape. Capability returns an authorization
`valid_until` no more than 30 seconds after server database time. At expiry the browser hides and
purges all Quality memory before reauthorization; resource freshness cannot outlive this lease.
Dependency unavailability blocks only the affected new operation/section and does not erase
authorized historical reads. An actual read denial prevents all Quality resource requests.

Quality rules, reviews, runs, attempts, normalized results, profiles and audits have governed
`QUALITY_RULE`, `QUALITY_PROFILE`, `QUALITY_RESULT` and `QUALITY_AUDIT` kinds. RuleSet, Run,
ProfileSnapshot and run-independent dispatch receipt roots pin policy ID/version/hash, deadline,
data kind and resolved Legal Hold generation/hash; child evidence inherits the exact root binding
through composite foreign keys. Dispatch resolves workspace-scoped AUDIT holds even when it creates
no Run. RuleSet, Run and ProfileSnapshot are typed resource hold targets. Creation, claim
immediately before source access and completion recheck the exact retention/hold snapshot; mid-run
drift produces STALE/UNKNOWN and no canonical result. Missing retention/Legal Hold coverage
disables source execution as well as
physical cleanup. Airflow cleanup, TTL and object lifecycle never become deletion authority, and
v1 writes no GX Data Docs or raw results to the filefolder/upload store.

## Governance Document security boundary

Public Governance Document routes are human-only. Reads and every command use explicit document,
history, Template or knowledge Actions; forced RLS repeats Workspace, active membership,
classification and System/Domain scope. Existing-aggregate commands require a quoted `If-Match`
and actor-bound idempotency. Publication/activation and Archive remain high-risk actions, and the
author cannot approve their own version. Archive is logical; application and worker roles receive
no document-table DELETE grant.

HTML, Markdown and DOCX are untrusted ingress. The server applies input/output byte, node, depth,
link, table and cell limits; rejects macro-enabled/external XML DOCX relationships; and canonicalizes
an allowlist that excludes script/style/iframe/SVG/MathML/form/media, `on*`, `style`, `src`,
`srcdoc`, `id` and `name`. Links are HTTPS or relative. Responses contain only canonical HTML plus
the exact sanitizer policy/version hash. The browser parses that HTML into allowlisted React nodes
and never uses `dangerouslySetInnerHTML`.

The API and projector use one dedicated MinIO identity under `governance/documents/v1/` in
`datariver-filefolder`. Its policy allows only conditional Put and exact-version Get/Head; it has
no bucket list, copy, presign or delete capability. Bucket versioning and provider VersionId are
mandatory, and every write is read back by exact version/checksum/metadata. This prevents
application overwrite/delete but does not represent operator/root credentials as regulatory WORM.

The projection worker uses a separate NOBYPASSRLS PostgreSQL login with no role membership. It can
select document/version inputs, update only projection lease/status columns, and insert immutable
artifact/chunk/projection receipts. It has no human review/publication/archive authority. Neo4j
receives only fixed parameterized Cypher. The evidence API accepts text only, uses the active
server-side embedding binding, and never accepts a vector, model/provider, SQL, Cypher or GraphQL
from the caller. Results are restricted to active documents and their exact current published
version after the same classification/System/Domain scope.

## Atomic API-product invocation boundary

Only the fixed local `SNAPSHOT_V1`, `NEIGHBORS_V1` and `CHAT_LOCAL_V1` executors can enter the
atomic Sharing completion path; an external provider is prohibited inside this transaction.
`datariver_app` has no direct table access to invocation ledger, result or monthly usage. Its two
allowed `SECURITY DEFINER` functions pin `search_path` and UTC, verify transaction-local
workspace/Subject context and lock the current revocable authority before reading or writing.
Result completion writes the immutable ledger, canonical JSON result and monthly aggregate
together; any validation, executor, serialization, size or commit failure consumes no quota.

The request hash covers permission scope, service Subject/issuer/client, product/version/release,
contract, operation/scope and canonical payload. An exact completed replay returns the stored
document and invocation ID without executing or charging again; any changed binding conflicts.
Result bodies are capped at 1 MiB before JSON parsing and bind the active `POLICY_BOOK_V2` rule and
deadline for `OBJECT_DATA` or `CHAT_CONTENT`; the immutable ledger separately binds the same
policy's `AUDIT_EVIDENCE` rule and deadline. Replay is denied after body expiry or current-policy
drift. Physical deletion remains a separate governed retention operation.

## Policy Book Role rules

- Role-version data rules express No/Partial/Full access, typed partial treatment, residency and
  processing-purpose allowlists. Missing, inconsistent or unavailable-treatment state denies.
- The policy-book result can only add a deny to existing workspace/action/clearance/System/Domain,
  classification-policy and RLS decisions. A Role marker in membership JSON is not authority.
- Current assignment and append-only event evidence bind subject, positive Role/version, membership
  version, canonical access hash and administrator actor. Rule scope arrays are normalized before
  hashing and DB constraints restrict item shape/vocabulary. The app cannot delete rule or event rows.
- Reserved `datariver-role-*` membership markers are accepted only from the server-owned Role
  assignment path. Manual and fallback access documents reject them so marker display state cannot
  diverge from normalized assignment/removal evidence. The repository compares the marker with the
  locked Role row, and exact same Role/version/hash reassignment is rejected instead of producing
  false `REASSIGNED` evidence.
- No endpoint currently treats a Role rule as permission to fetch arbitrary source-system values.
  A future Partial path must use an attested adapter and prove that plaintext is not returned.

## Query and LLM safety

- LLM output is parsed into strict versioned proposal schemas with size/depth limits.
- Generated SQL/Cypher is never executed. Graph analysis uses approved templates and typed parameters.
- Templates enforce read-only operation, label/relation allowlist, maximum hops/rows/time/cost, statement timeout and database read-only transaction.
- Retrieved documents are data, not instructions. System/tool policy is isolated from evidence and tool output.
- Model requests exclude unauthorized fields and secrets; raw prompts/responses are not production logs.
- External inference remains disabled. The immutable authorized evidence-chunk and fail-closed citation boundary is implemented; the classification-specific Chat matrix, isolated worker and full prompt-injection red-team gate in `14_PRODUCTION_HARDENING.md` still require acceptance.

## API and browser controls

- Strict CORS allowlist; never wildcard with credentials.
- Secure, HttpOnly, SameSite cookies only if a BFF session is used; otherwise short-lived bearer
  tokens stay in memory and a refresh/new-tab requires the normal OIDC session journey.
- In-memory OIDC renewal uses the provider's standard refresh/silent flow. A `401` retries only one
  `GET`/`HEAD` request or a request carrying DataRiver's durable `Idempotency-Key`; a non-idempotent
  mutation is never replayed. Failed renewal clears in-memory identity and returns the existing
  custom login state without another automatic redirect loop.
- OIDC hydration uses a generation and AbortController; only the newest response whose server
  subject equals the OIDC `sub` may publish identity. Unload and sign-out invalidate memory before
  the provider event or redirect completes. An opaque, non-persisted security epoch binds every
  browser request/download to its Workspace; epoch drift discards late bodies and prevents even a
  durable-idempotency retry from crossing authenticated sessions. Successful `/auth/me` and
  `/admin/me` discovery is `private, no-store`.
- CSRF protection for cookie-authenticated mutations.
- Request/body/file limits, rate limits by subject/workspace/product, and bounded decompression.
- The web Nginx edge owns one canonical CSP, frame denial, nosniff, no-referrer and restricted
  Permissions Policy value. Each uses `always`, and recursive `add_header` merge prevents a
  location-specific cache header from shadowing the security set on `2xx/3xx/4xx/5xx`. Proxied API
  copies of those names are hidden before the edge values are added once; authorization and ABAC
  remain authoritative rather than relying on browser headers.
- HSTS is emitted and verified only by the externally reachable HTTPS termination edge. The inner
  plain-HTTP web container is not TLS/HSTS evidence.
- Outbound connector endpoints use approved schemes/hosts, DNS/IP revalidation and private/metadata address blocking to prevent SSRF.

## Secrets and encryption

- Git contains `.env.example` names only. Bootstrap generates strong local secrets into ignored files.
- Every environment uses deployment variables and secret mounts or a secret manager as the sole
  live connector source. Historical database profile rows are audit-only: no API, worker or
  capability path may load them into runtime Settings. Admin returns a redacted snapshot, publishes
  no write/activate route and never accepts a probe destination from the browser.
- Monitoring tab updates are a separate RLS-protected presentation aggregate, not a connector
  profile. The server accepts credential-free HTTP(S) Dashboard Links from any origin but never
  fetches, probes or proxies them. Administrator input cannot enable iframe use, widen CSP or
  provide a connector destination; only the existing deployment-owned exact-origin Grafana gate
  may produce an iframe descriptor. Other links open with browser opener isolation. Fresh
  administrator assurance and optimistic concurrency are required for every replacement.
- No zero/default encryption key fallback. Startup fails when required secret material is missing or weak.
- TLS is mandatory outside a single-host private development network. PostgreSQL/object backups are encrypted and restoration is tested.
- Logs redact Authorization, cookies, provider tokens, presigned URLs, connection strings, prompt content and personal data.

## Upload security

Direct multipart upload enters a private quarantine prefix. Completion validates ownership, object key, content length, MIME, checksum and part manifest. A streaming worker performs malware/type/structure checks before an accepted-state transition. URLs expire within 15 minutes; abandoned multipart uploads and quarantine objects are garbage-collected. Overwrite is disabled unless a new immutable object version is explicitly created.

The upload store is not the immutable audit archive. Archive writes use a separate private port,
bucket and least-privilege credential unavailable to the API, relay and upload workers. That port has
no delete or governance-retention-bypass operation. Provider names, including SeaweedFS or MinIO, do
not assert WORM behavior; the deployment must prove versioning, Object Lock, compliance retention,
checksum/version read-back and protected-version shortening/delete denial.

## Retention, Legal Hold and erasure security

- Retention durations are operating data in an independently approved and activated database policy
  version, not portable source defaults or environment deletion switches.
- A Legal Hold UI toggle issues a typed place or release workflow and append-only history. Hold
  release is a high-risk command; release-pending is treated as held.
- Explicit erasure accepts only allowlisted target kinds and canonical UUIDs resolved server-side.
  Raw object keys, bucket names, tables, SQL and arbitrary provider requests are prohibited.
- Erasure review binds workspace, canonical target version/owner/classification, policy ID/hash and
  payload hash; requires a distinct eligible human maker and checker; is hardware-WebAuthn
  authenticated, idempotent and optimistic-version guarded. APPROVED remains non-executable.
- Future destructive execution additionally requires atomic one-time consumption and rechecks
  policy, authorization, target state and holds immediately before any effect.
- Archive-required deletion proceeds only after a deterministic manifest and SHA-256 content are
  written, fully read back, retention/Object-Lock state is read back and a matching immutable receipt
  is committed. Missing, stale, unsupported or contradictory capability evidence fails closed.
- A future retention worker uses a distinct DB role, archive credential and bounded egress. Any
  BYPASSRLS use records workspace and correlation scope and receives no unrelated table privileges.
  Current relay roles retain no deletion privilege.

## Audit requirements

Security-relevant requests record request/trace ID, subject/service identity, workspace, resource/action, decision/effect/reason, policy versions, aggregate version and outcome. Audit events are append-only to normal application roles and protected from payload tampering with chained/batched hashes or external immutable export in production. An archive is accepted only with a canonical manifest, SHA-256, immutable object version and successful content and retention read-back; object-store metadata alone is not audit proof.

## Security acceptance matrix

Tests cover allow and deny for every endpoint/action, cross-workspace IDs, hidden resource `404`, list/count/facet leakage, stale permission cache, revoked grant, self-approval, weak authentication, object URL replay, duplicated idempotency keys, SSRF targets, malicious archive/content, prompt injection and prohibited query clauses. Retention acceptance additionally covers maker/checker and hold races, stale target/policy versions, altered payload hashes, archive checksum/read-back mismatches, expired capability evidence, retention shortening/delete denial, worker crash/retry and proof that every failed gate causes zero deletes or partition drops. Release requires secret scan, SAST, dependency/image scan, SBOM/license inventory and zero unresolved Critical/High findings.
