# Test and stabilization strategy

## Latest executed baseline

The current development/integration baseline passes 495 backend tests, strict mypy over 199 source/test files, Ruff formatting/lint, TypeScript/ESLint/build, deterministic migration generation and static architecture/Compose/role/readiness checks. Post-baseline migration tests cover absent, complete and partial canonical states plus non-destructive compatibility downgrade for `0013` through `0018`. A completely empty temporary database migrated through the sole head, and a separate canonical-`0001` database advanced through every compatibility revision; both reached `0018`. The last complete frontend baseline remains 18 files/75 tests; the two registration test files pass 17/17 tests and the governed change-workbench file passes 9/9 tests, while both ordinary and single-worker whole-suite runs on the Windows WSL network drive reached a five-minute bound without assertion output. The frontend build emits JS 503.11 kB (gzip 143.36 kB) and CSS 46.70 kB (gzip 9.12 kB), with the documented post-minification chunk-size warning still open. The live hybrid-development baseline also passed PostgreSQL RLS, Keycloak service-token OIDC, schema-aware API/APISIX readiness, Vite-to-APISIX proxying, DataHub GraphQL authentication and semiconductor seed verification. The current source additionally serves immutable server-owned governance target bindings and a typed MANUAL dataset-description preview/create contract through APISIX; raw Aspect entry points require a separately granted hardware-human action and have no ordinary browser form. BULK upload/validation uses attempt-scoped promotion, full promoted-byte SHA-256 read-back and a commit receipt before source cleanup. Migration `0016` installs forced-RLS preparation job/receipt/candidate/binding evidence, `0017` preserves legacy candidates honestly and requires submitted hierarchy plus V2 hashes, and `0018` binds new Chat sessions to the exact active governed retention policy and policy-derived deadline. A non-default 37-day policy passed live insert, while legacy insert, deadline mutation and superseded-policy append were denied. The API and v0.3-style BULK workbench select a bounded typed profile and queue/read exact accepted-evidence preparation state without exposing a raw proposal path. The source-only bounded parser enforces the unchanged V1 CSV byte shape and the V2 submitted-identity/hash evidence contract; its read-only candidate page revalidates receipt/hash evidence and current set-based authorization without provider/object calls, while the runtime worker and typed proposal execution remain disabled. The governed change workbench now provides a bounded authorized list, fresh detail authorization, immutable target/approval/transition evidence and explicit version-fenced commands; denied commands are never replayed automatically. The assistant-inference contract now binds monthly workspace/user token accounting, explicit pre-execution internal budget fallback, exact provider identity/region and independently verified URN grounding; its provider and verifier adapters remain disabled. The earlier container baseline additionally passed Airflow DAG imports, optional seed remove and repository/IaC Trivy scanning. Exact commands and the distinction between current source and earlier evidence are in [the acceptance report](12_ACCEPTANCE_REPORT.md).

### 2026-07-19 catalog/governance corrective verification

The corrective catalog/governance change passed `579` backend tests, full Ruff formatting/lint,
strict mypy over `221` source/test files (with a separate temporary cache because an existing shared
mypy cache was locked), and `scripts/verify_static.py`. The subsequent interaction update passed
TypeScript, ESLint, production Vite build and 36 focused frontend tests: catalog workspace/detail
tabs, the two-tab `Table Details`/`Lineage` separation, four-column metadata summary, one-line
Type/classification/URN layout, top-to-bottom lineage layout with clickable names, fixed stage
badges, pan/node-drag/button and Ctrl-wheel zoom, Registration one-line vocabulary scroll/nearby
floating entry, Governance CR creation, and the no-403 policy-read state. The catalog vocabulary
backend tests verify one-character input, fixed DataHub Tag/Glossary-Term contracts, initial bounded
`*` browse, and projection fallback when the external dependency is unavailable. The default thread-pool runner could not
start workers reliably on the Windows-network-drive test environment, but the complete suite was
then run with a single `vmThreads` worker and no file parallelism: 26 files and 126 tests passed in
64.91 seconds. That runner choice is local UI evidence, not a replacement for browser acceptance.
The rebuilt API reported
`/api/v1/health/ready` as ready and its OpenAPI contract exposed the database, schema, domain and
lifecycle facet buckets plus the bounded lineage endpoint. A token-redacted in-container DataHub
probe scanned one of the current 2,010 assets and returned three non-partial upstream lineage nodes
at depth two, so no GraphQL contract error occurred. The automated UI flow verifies that the node
detail modal requests only the server-authorized, configured DataHub Lineage URL and frames that
actual provider screen; it does not render a second local lineage graph or receive a provider token.
An interactive Chrome visual pass remains an environment gate because the local Chrome connector
failed while initializing its kernel assets. The local runtime is healthy, but ordinary user tokens
use OIDC authorization-code + PKCE only; direct password grant is deliberately disabled. A complete
browser CR journey therefore still needs two independently authenticated human identities and a
real WebAuthn ceremony rather than a service-account substitute.

The follow-up Lineage containment and CR vocabulary/column-alignment correction passed TypeScript,
targeted ESLint and a production Vite build. Under the stable single-worker `vmThreads` runner,
`CatalogLineageGraph` plus `CatalogWorkspace` passed 10/10 tests and `GovernancePage` passed 10/10
tests. The default thread-pool runner could not start a worker on the Windows network-drive runtime
within 60 seconds; the successful complete-suite `vmThreads` run above is the accepted local test
evidence. The focused tests cover the two-tab detail contract, bounded Lineage loading, canvas interaction and the
initial existing-vocabulary list shown by the CR Tag `+` control, including the fixed bounded DataHub
browse before keyword narrowing.

The administrator System-directory follow-up adds an actual `GET /admin/systems?limit=` read
contract over canonical systems and assignees. Its service unit suite passed 16/16 tests; targeted
strict mypy and Ruff passed, and the administrator UI test verifies that the System tab renders the
server-returned Developer priority rather than a static row.

The final local re-check after that addition passed `44` focused backend tests (administrator
access, catalog service and DataHub gateway), repository-wide Ruff check/format and
`scripts/verify_static.py`. TypeScript and targeted ESLint passed. The stable single-worker
`vmThreads` UI run passed the System tab and the catalog/governance correction files (`21` tests in
total); the production Vite build passed with the existing post-minification `>500 kB` main-chunk
warning. These are source/component checks, not a substitute for the still-open authenticated
browser, DataHub SSO-frame and two-human WebAuthn acceptance gates.

The Grafana embed follow-up passed `32` configuration tests, targeted strict mypy, Ruff and the
static deployment/CSP verifier. Its three UI tests prove that a configured direct link alone does
not create an iframe, while an `AVAILABLE` server descriptor renders only the returned URL with the
required sandbox and no-referrer attributes. The production Vite build passed; the existing
post-minification main-chunk warning remains. A target Grafana SSO and `frame-ancestors` browser
acceptance remains an environment gate before an operator may set the evidence-gated enable flag.

The administrator System-settings inventory follow-up passed `49` focused backend tests, targeted
strict mypy and Ruff. Its unit coverage checks the fixed server-owned inventory contains no endpoint
or secret-reference field and that a valid Grafana deployment setup reports only an embed state. The
administrator UI test verifies the newly authorized tab renders server-returned state without a YAML
or connection-test control; TypeScript and targeted ESLint passed. It is a safe read substitution,
not evidence that a browser may edit deployment configuration.

The System-assignment command follow-up adds a typed, complete-replacement `PUT` contract behind
recent hardware WebAuthn, optimistic concurrency and idempotency. Focused service tests cover the
minimum Developer/Data Steward invariant, priority validation, idempotent replay and the single
versioned outbox event. OpenAPI tests assert the mutation route and its required `If-Match`,
`Idempotency-Key` and returned `ETag` contract. The administrator UI test covers the confirmation
boundary before any assignment mutation is sent. The final target browser and two-human WebAuthn
acceptance remain environment gates.

The Knowledge follow-up rechecked the existing domain suite for immutable releases, typed
provenance-bearing graph operations, bounded traversal and independent review. The browser Studio
now maps its structured Node/Edge form directly to the existing typed operation contract; it has no
raw JSON, Cypher, filesystem path, endpoint or credential field. TypeScript compilation covers the
new contract shape. Browser acceptance still requires a real authorized graph and independent
reviewer identity.

### 2026-07-20 controlled-vocabulary and workflow re-check

The CR and Registration `Tag`/`Term` picker now performs a fixed, bounded DataHub `*` browse when
its compact `+` control opens, before narrowing with the user's keyword. This closes the case where
the authorized local projection contained only values already selected on the current asset and the
floating list therefore appeared empty. The call remains server-side, returns at most the requested
limit and degrades to the authorization-pruned projection if DataHub is unavailable; comma/Enter/Tab
new values remain proposal intent rather than a browser-owned provider write. Focused catalog-service
and DataHub-adapter tests passed `30/30`, including the wildcard request and failure fallback;
strict mypy passed for the changed service and tests, and Ruff format/lint plus `verify_static.py`
passed. The five focused Catalog/Governance/Registration/Knowledge frontend files passed `36/36`,
with TypeScript, targeted ESLint and a production Vite build succeeding. The existing `>500 kB`
post-minification main-chunk warning remains open.

The domain, service, apply and persistence CR workflow suite passed `26/26`, covering intake,
independent final review and target binding. A direct local browser journey was not claimed: Vite,
API and gateway ports were reachable, but the available browser-control runtime could not initialize
its local assets, and the runtime deliberately requires two independently authenticated OIDC humans
with an actual hardware-WebAuthn ceremony for the creation/review boundary. No password grant,
service account or mocked reviewer was used to bypass that production gate.

The final client recovery split the pure lineage layout and administrator section-policy exports
from their React component modules. This prevents those exports from making Vite invalidate an
otherwise compatible component update and preserves the layout rule that every same-level lineage
node is rendered, wrapping only after the third column. The focused `CatalogLineageGraph`,
`AdminPage`, and shell-policy suite passed `16/16`; TypeScript, targeted ESLint, and the production
Vite build passed. Vite was restarted with its documented `VITE_USE_POLLING=true` setting because
the Windows-to-WSL workspace watch otherwise treated the root `.env` as a directory. The restored
server returned current JavaScript modules for the catalog dialog, graph/layout, and administrator
sections, with no old `DataHubLineageDialog` module reference or syntax error. The API container
was rebuilt from the same working tree and `/api/v1/health/ready` returned `200`; its live OpenAPI
contract contains the catalog lineage and DataHub-lineage-embed endpoints, CR intake, administrator
systems/assignee mutation, and administrator system-configuration inventory. This is runtime
route/module evidence only; it does not substitute for the still-open interactive OIDC/WebAuthn
and DataHub SSO-frame acceptance checks.

The subsequent full-source re-audit passed all `590` backend tests in `50.65s`, all `27` frontend
test files / `128` tests in `42.19s` with the stable single-worker `vmThreads` runner, Ruff format
over `236` files, Ruff lint, and strict mypy over `221` source/test files. `verify_static.py` and
`git diff --check` also passed. The `uv` runner reported a non-fatal pre-existing `.venv` lock
warning while each command was running; it did not prevent creation of the isolated mypy cache or
execution of any test. These checks cover source and component contracts. They deliberately do not
claim the final two-human OIDC/WebAuthn CR browser journey or provider-owned DataHub/Grafana SSO
frame rendering, both of which remain target-environment acceptance gates.

Executed resilience checks included cache-Valkey stop/recovery, API process restart, API container replacement behind both Nginx and APISIX, and outbox-relay restart. The API replacement test deliberately kept the web container running and verified that its Docker DNS resolver did not retain a stale upstream address.

The local seeded same-token revocation probe ran 100 iterations per scenario against the direct API:
membership inactive p99 100.660 ms, explicit `catalog.search` deny p99 167.743 ms and system/domain
scope removal p99 193.388 ms. All passed the provisional 60-second SLA and the original service
membership was restored. This is development evidence, not the required target-load/two-identity or
already-open Chat/SSE gate.

The strategy below remains the production release matrix. Target DataHub/object storage, backup/restore, browser PKCE/hardware-WebAuthn and governed password fallback, load/soak, queue saturation, worker crash-at-each-boundary and promoted-image scans are still environment gates rather than silently assumed passes.

## Test pyramid and gates

| Layer | Tools/approach | Required evidence |
|---|---|---|
| Domain unit | pytest, pure TypeScript tests | state transitions, policy rules, graph validation |
| Architecture | import graph/AST tests | domain/application contain no adapter imports; contexts do not write across schemas |
| Repository/integration | PostgreSQL/Testcontainers | constraints, RLS, migrations, outbox atomicity, idempotency |
| Contract | OpenAPI snapshot, DataHub/S3/OIDC/OPA fixtures, Schemathesis | provider error mapping and API compatibility |
| UI component | Vitest/Testing Library | loading/error/permission/accessibility behavior |
| Browser E2E | Playwright | search, upload/dry-run, CR lifecycle, monitoring, KG release, Chat |
| Resilience | Toxiproxy/process kill | dependency failure matrix and recovery |
| Performance | k6 plus RSS/DB/Valkey metrics | p95, error rate, memory and soak stability |
| Security/supply chain | pip-audit, npm audit, Trivy secret/vulnerability/IaC/image scan, CycloneDX, license allowlist | zero unresolved Critical/High, retained SBOM |
| Recovery | isolated restore/rebuild scripts | PostgreSQL restore and graph projection deterministic hash |

Target performance runs must first validate their ignored deployment input with
`uv run python scripts/validate_deployment_profile.py runtime/deployment-profile.json --require-ready`.
The profile treats a workspace as a logical tenant/security boundary, keeps workload and SLO values
out of portable defaults, and refuses target-ready status until production CPU topology, RAM,
storage and network evidence are complete. Chat sizing records QPS and concurrent streams together;
TTFT or token rate alone is not sufficient capacity evidence.

Retention negative tests must prove that the relay exposes no pruning operation and has no `DELETE` privilege. Future retention automation is not accepted until dependency failure, missing approval, active Legal Hold, WORM retention read-back mismatch and replay/concurrency cases all produce zero deletions.

The source-level identity suite additionally checks same-origin return-state validation, explicit
WebAuthn AIA and LoA request arguments, missing/ambiguous ACR fail-closed behavior, bounded problem
remediation and exactly one HTTP attempt for a denied mutation. The backend administrator suite
checks the exact password/hardware assurance matrix, default-disabled fallback, maker/checker/target
separation, five-minute expiry, canonical hash and versions, eligibility revocation, two-admin
invariant, idempotent one-time consume, minimal outbox data, forced RLS and column-level grants.
Browser E2E must still prove a real security-key ceremony, `max_age=0` password reauthentication
with two real users, no password field or direct bypass in the page, and explicit resubmission after
returning from authentication.

The source-level inference suite checks that the package and provider draft contain no SQL, Cypher,
HTTP, tool or mutation fields; RESTRICTED and cross-workspace evidence is rejected; policy/profile
hashes, identity/region, jurisdiction, classification ceiling and both attestations are bound;
internal usage is monitor-only; and external usage requires a workspace/user monthly hard-limit
reservation. The accounting-period label is bound to both timezone-aware month boundaries. Budget
exhaustion retains the external denial and can select only a separately observed, approved internal
route before worker execution. Provider exceptions never select a fallback.

Authorized evidence uses a canonical URN grammar. Grounding binds package/route IDs, policy hash,
answer hash and an ordered evidence-bundle hash over URN, version and content hash. The non-zero
threshold and evaluator identity come from the route's immutable grounding-policy snapshot rather
than verifier output. Forged/replayed verdicts, duplicate citations, mismatched evidence, unavailable
grounding or a score below the versioned threshold becomes
`보안 규정 및 근거 데이터 부족으로 답변할 수 없습니다`. The pure benchmark evaluator reports
nearest-rank TTFT p95, mean token rate and benchmark accuracy against supplied targets and retains
dataset/evaluator/scoring-policy hashes, but is not production telemetry evidence. Malformed adapter
or verifier returns fail closed, and structurally valid post-call usage survives later refusal.
External enablement still requires a durable atomic reserve/settle
ledger, pre-call and post-call live policy/profile/attestation revalidation, durable delivery and
idempotency, independently timed SSE/cancellation tests, provider/grounding metrics and the scaled
red-team corpus.

## Core correctness scenarios

- State machine rejects every undeclared transition and stale aggregate version.
- Requester cannot final-approve; required multi-approval actors are distinct.
- `APPLY_QUEUED` and outbox insert are one transaction.
- Duplicate event and duplicate idempotency key produce one business effect.
- DataHub failure/mismatch never produces `APPLIED`; reconcile retry can recover.
- Catalog writes cannot bypass governance.
- Every graph publish assertion has provenance and passes ontology/reference checks.
- Release content is immutable; same release rebuild has identical hash/count and golden-query output.
- Chat citations are a non-empty, duplicate-free subset of the exact currently authorized immutable chunks; workspace/chunk/content hash is revalidated and invalid deterministic-composer output becomes `검증 불가` with no persisted citation. Future model inference additionally requires the ADR-0019 grounding verdict and its longer governed refusal text.

## Authorization matrix

For each route, test no token, invalid issuer/audience/algorithm, inactive subject, missing workspace membership, workspace mismatch, insufficient clearance/system/domain, lifecycle restriction, positive allow, explicit deny, policy-service outage, changed policy with stale cache and protected-field redaction. List, facet, suggestion, count, download, export and SSE receive the same coverage as detail endpoints.

## Failure injection

| Fault | Pass condition |
|---|---|
| DataHub unavailable/rate-limited/contract drift | bounded stale or classified 503; durable pending work; no false complete; fixed-label request/circuit metrics |
| DataHub concurrency saturated | bounded queue timeout and classified `OVERLOADED`; bulkhead rejection metric increments |
| cache unavailable/evicted | correct uncached response, no secret leakage |
| API container replaced | Nginx/APISIX re-resolve service DNS; no dependent restart or persistent 502 |
| queue unavailable | outbox age grows; automatic replay after recovery |
| worker killed before/after external call | idempotent resume and reconcile, no duplicate result |
| PostgreSQL unavailable | writes fail 503 and no message is published |
| object store/multipart interruption | upload recover/abort; orphan reconciliation works |
| policy unavailable | protected operations fail closed |
| graph unavailable/drift | catalog works; projection rebuild restores hash |
| LLM unavailable/malicious response | authorized evidence remains; no mutation/query execution |
| poison event | bounded retry to DLQ; audited operator replay |

## Memory and performance

- Stream synthetic 500 MiB and 1 GiB objects; API RSS increase <= 64 MiB.
- Cap list results at 100 and cache value at 1 MiB.
- Run target load for 60 minutes; after warm-up API RSS stays within ±10% absent explained cache bounds.
- Reference-host targets: cached search p95 <= 300 ms, uncached <= 800 ms, CR write <= 400 ms, error rate < 1%.
- Queue eviction count stays zero; cache respects maxmemory and TTL.
- Test ABAC-aware pagination/facets at realistic permitted/denied ratios.
- Reuse a search cursor only with its exact workspace, permission scope, policy/generation, projection version, query, filters and page size; stale or cross-shape cursors must fail explicitly.
- Prove multi-term search uses ALL semantics while `%`, `_` and backslash remain literal data, and render only client-escaped highlights from server plain-text match fragments.
- Expand Resource Tree branches one page at a time; no browser test may preload the catalog to synthesize hierarchy or count hidden rows.
- Filter every lineage node and intermediary as a set through the catalog authorization predicate; a denied intermediary must truncate the path and must never be bypassed to connect two visible endpoints.

## Migration and portability

- Empty DB upgrades to one Alembic head and matches declared metadata.
- Previous release DB upgrades and rolls application forward without data loss.
- Clean clone on Windows/WSL2, Linux and macOS follows one documented Compose path.
- No absolute path, committed secret, volume, upload, test artifact or seed appears in a clean production checkout.

### PgBouncer pre-adoption RLS gate

PgBouncer must not become an API database path until transaction-local workspace and subject context
has passed `scripts/probe_pgbouncer_rls.py`. Run the probe only against an isolated integration
database with at least one catalog fixture in each of two distinct workspaces. Its separate admin
connection verifies transaction mode and `default_pool_size=1`; the application connection then
forces reuse of one PostgreSQL server connection across commit, rollback and database-error paths,
checks an interrupted transaction, and proves both context reset and cross-workspace row denial.

The URLs must not contain passwords and every secret must be a `file:` reference. The command has no
portable endpoint, identity or workspace defaults; the deployment supplies all six values. A missing
fixture, a non-reused server connection or an unavailable PgBouncer admin console is inconclusive and
therefore fails the gate. This probe is a prerequisite, not evidence that PgBouncer, a connection
budget or a target `max_connections` value has been accepted for production.

## Release gate

CI success alone is insufficient. The acceptance report records commit/image digest, environment, dataset, commands, machine-readable reports, reviewer, exceptions and expiry. Image scanners run only in an isolated CI/release runner; never grant a third-party scanner a developer Docker socket merely to produce local evidence. Release is blocked by failed functional/ABAC/migration/recovery gates or unresolved Critical/High security findings. Performance variance is a documented block unless the acceptance owner approves a time-bounded exception with mitigation.
