# Test and stabilization strategy

## Current verification status

The current Search/Registration local-exit candidate passed `1,152` backend tests with `46`
explicitly environment-gated integration cases skipped. The exact README Ruff command passed,
strict mypy passed over `333` source/test files, and static
architecture/role/Compose/documentation verification passed. The frontend passed strict
TypeScript, zero-warning ESLint, `44` files / `230` tests and the production build. Canonical `0001`
generation was byte-identical across two runs at SHA-256
`1ca5b11f1c78ae6a193b2beca9f5ef19d252a2c59b32f955be0d10cf298ebbce`; Alembic has the single head
`0050`.

The current network-free JavaScript gates do not include `npm audit`: that command sends the
dependency manifest to the external npm service, and explicit disclosure permission was not
available for this run. This is recorded as an external permission gate, not as a zero-vulnerability
result.

The first whole-suite run intentionally failed five stale contract fixtures after the executable
typed profile was reduced to 16 MiB/10,000 rows and its validator advanced to the registered
low-resource version. That run exposed a real boundary mismatch: the upload-validation worker still
emitted the legacy validator identifier, making every newly accepted typed upload ineligible for
preparation. A typed CSV/XLSX regression was added, the worker now emits the exact server-owned
profile version, all 24 focused registration/validation tests pass, and the full result above is the
post-fix rerun.

A disposable native-arm64 PostgreSQL 17.10 ran the full `0001 -> 0045` chain. A separate simulated
`0044` state held 12,000 description characters, 105 tags/terms and 1,005 column names; `0045`
reduced them to `10,000 / 100 / 100 / 1,000`, bounded every retained string element, set all four
conservative truncation/provenance flags and left all `13` catalog-projection/sync CHECK constraints
validated. A legacy active sync run became `ABANDONED`. An empty external URN caused `0045` to roll
back transactionally without truncating or rewriting identity.

Database-negative probes rejected verified-snapshot state with absent evidence, a non-hex contract
hash and a 4,097-character provider cursor; a complete evidence/hash/provider tuple was accepted.
The environment-gated integration test then passed separately through the actual `datariver_app`
role and writer transaction boundary. It proved replay without a second watermark update,
cross-page duplicate/evidence-drift/incomplete-coverage rollback, unverified deletion suppression,
and verified tombstoning of DataHub-owned rows without tombstoning seed-owned rows. Two independent
sessions also proved that the pre-provider workspace reservation blocks a second run until the
first commits, while a simultaneous same-key retry returns the exact stored result and leaves the
watermark at one. Its facet path executed the single PostgreSQL `GROUPING SETS` query. Source tests
prove `RESPONSE_TOO_LARGE` page reduction `100 -> 50 -> 25` and Airflow resume from public page 731
without replaying earlier pages. The reservation's non-configurable ten-second provider budget is
tested to cancel and roll back before the runtime 15-second statement and 30-second idle-transaction
timeouts; a value above ten seconds is rejected. These are correctness and small-fixture smoke results;
representative target-volume `EXPLAIN (ANALYZE, BUFFERS)` and DataHub deployment-specific
scroll/point-in-time conformance remain external gates.

For ADR-0041, a disposable native-arm64 PostgreSQL 17.10 exercised blank/current
`0001 -> 0046`, additive `0045 -> 0046`, complete-generated-schema re-entry and malformed-column
fail-closed paths. Read-back verified forced RLS, the four expected permissive/restrictive policies,
append-only triggers and absence of broad application-role UPDATE. The additive rehearsal also
proved the bootstrap prerequisites: canonical roles must exist before migration and revision `0025`
requires its mounted export-password secret. The generated baseline and bridge use identical
constraint names through `op.f(...)`; the migration issues one asyncpg-compatible statement at a
time. The disposable database was removed.

An isolated live MinIO test concurrently wrote the same previously absent key. Exactly one writer
created the immutable receipt, the other received a conflict, and complete byte read-back matched;
the test bucket was then removed. This closes the local conditional-create behavior only. Current
source/unit tests additionally cover active-human operator gating, owner/Admin Manual history,
service-only workers, DB-time leases, at most 20 attempts, five-aspect completion, typed-candidate
ETag/object-locator evidence, atomic binding/idempotency, Change Request aggregate caps and
private/no-store reports.

Actual multi-human OIDC journeys, external Airflow client credentials, target MinIO permission,
real DataHub five-aspect mutation/read-back, WSL `linux/amd64`, representative-volume query plans
and crash/soak remain external gates. The local results do not establish production HA or authorize
browser/provider credentials.

The preceding Policy Book rehearsal ran `0001 -> 0043 -> 0044`. It replaced one canonical index
with the same name and non-default `text_pattern_ops`; `0044` failed closed and did not normalize
the drift. It then marked an exact definition invalid/not-ready, and `0044` concurrently
dropped/rebuilt only that interrupted index. All six final cursor indexes were valid/ready plain
B-trees without INCLUDE columns. Earlier rehearsals also verified the `0042` current-canonical
fingerprint, the `0043` exact CHECK bridge and application-role System-assignee soft
deactivate/reactivate with DELETE denied.

The Policy Book Phase 3 audit record and its then-current counts remain in
`docs/28_POLICY_BOOK_EXECUTION_CHECKLIST.md`; they are not promoted to current-head evidence.
Actual multi-human OIDC/WebAuthn browser acceptance, production-size
`EXPLAIN (ANALYZE, BUFFERS)`, maintained-provider WORM conformance, off-host restore,
Windows/WSL `linux/amd64` runtime/crash/low-resource acceptance and accountable operations approval
remain target gates. No local result authorizes destructive action or activation of the default-off
archive profile.

The final recovery regression uses an exact pre-write capability-attestation UUID in S3 metadata,
requires provider `LastModified` on lookup, treats its whole-second precision as the conservative
write interval `[LastModified, LastModified + 1 second)`, performs an atomic `If-None-Match: *` create with SDK
automatic retries disabled, and proves a cold-process restart links the same receipt without another
capability probe or evidence PutObject. Every expired write lease enters read-only reconciliation
before governance revalidation. Missing evidence returns to a normal write attempt only when the
stored write budget remains; transient lookup errors have three recovery fences per write attempt,
derived from persisted attempt rows. A policy superseded after the original object write may still prove
that historical receipt, while a policy activated, superseded, made effective or expired inside the
uncertain provider-write interval is rejected. The exact capability attestation and the execution
authorisation deadline must cover that complete interval as well.

An additional PostgreSQL 17 existing-volume rehearsal applied `0042` while the scheduler/archive
roles were absent, then ran the real `010_roles.sh` reconciliation. The first rehearsal exposed an
invalid shell-style comment inside the SQL heredoc; after correction the same script completed
idempotently. Read-back proved both roles are `NOBYPASSRLS`, scheduler SELECT/INSERT and archive
SELECT/INSERT/bounded-column UPDATE work, broad UPDATE is absent, and a direct archive-role DELETE
fails with `permission denied`. The refreshed fresh and additive semantic fingerprints are
`e7d66e854560db29c126f3768a3eb2d3b635c9a1f6b291bf7255b72149b75478` and
`0dcf7a560a9c9ccd090b4178c63af942283df77e1eae5e6f6841e9976dc16ae2`.

### Superseded 2026-07-23 Policy Book Retention Phase 2 candidate

The pre-remediation Phase 2 candidate passed Ruff format/lint over `307` files, strict mypy over
`290` source/test files, `835` default backend tests with two explicitly gated PostgreSQL tests
skipped, and `scripts/verify_static.py`. The existing Phase 1 PostgreSQL test and the new Phase 2
test separately passed against a disposable PostgreSQL 17 database using the actual app,
scheduler, archive and owner roles. Base Compose and the `retention-archive` profile both passed
`config --quiet`. The generated `0001` was byte-identical across two runs at SHA-256
`8d4d2f36c8f01af3a7694eadac022d6517078ecc20d9fc55f1f7273c958e2ef7`.

A completely empty volume migrated through every revision from `0001` to the then-current sole head `0042`.
The additive `0041 -> 0042` compatibility path also passed after simulating a complete Phase 1
schema without Phase 2 objects. Read-back verified the four Phase 2 tables use forced workspace
RLS, scheduler/archive roles are `NOBYPASSRLS`, event evidence is append-only, worker mutation is
column-bounded and no runtime role receives destructive privileges.

The Phase 2 PostgreSQL test requires three separate URLs in
`DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_URL`,
`DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_URL` and
`DATARIVER_RETENTION_TEST_ADMIN_DATABASE_URL`, their file-mounted secret references and
`DATARIVER_RETENTION_TEST_CONFIRM_ISOLATED=1`. It creates and removes only its own fixture rows. Two
concurrent planners create one command and two concurrent workers produce one claim. The test then
expires the lease to simulate a crashed worker, reclaims epoch 2, rejects epoch 1, places a
post-claim resource Legal Hold, verifies blocking, releases it, verifies eligibility, revokes the
checker Role and proves the command becomes `BLOCKED` with destructive effects disabled.

Unit negatives cover V1/V2 hash separation, exact four-class min/max rules, policy/target/owner/
classification/Role/Hold drift, pre-write kill-switch recheck, full checksum and retention read-back
mismatch, one-MiB archive bounds and fixed-cardinality metrics. The actual WORM endpoint was not
configured: provider Object Lock conformance, off-host restore and WSL `linux/amd64` crash/soak are
explicit target gates, and the profile remains disabled. This source evidence never authorizes
physical deletion or partition drop.

### 2026-07-23 Policy Book RBAC Phase 1 verification

The approval-gated Phase 1 passed Ruff formatting/lint over `286` files, strict mypy over `279`
source files, `804` backend tests with one environment-gated PostgreSQL test skipped, and static
verification. That PostgreSQL test separately passed in an isolated real database. The unchanged
frontend passed `39` files / `170` tests,
zero-warning lint and production build. Canonical `0001` regeneration was byte-identical at
SHA-256 `3d0b199681d72965e191f044e36c648c34a725adbe03a8420be03afcc6f3f1b4`. An
isolated empty database migrated `0001 -> 0041` and was removed; the populated Mac database upgraded
`0040 -> 0041` and passed the non-destructive compatibility replay. Read-back verified the sole head,
three forced-RLS tables, append-only/bounded app grants and the additional scope/state/composite-FK
constraints. The final arm64 API was healthy/schema-ready, and a cache-only `linux/amd64` Docker build
passed from the same source. A second isolated database with all three table names but a missing
required constraint was rejected by the `0041` complete-schema fingerprint. A same-name
`CHECK(TRUE)` plus `USING(TRUE)` RLS-policy mutation was also rejected; the fingerprint compares
column length/timezone/default, CHECK SQL, FK columns/targets/delete actions, index columns and RLS
mode/predicate rather than object names alone. Direct `datariver_app` probes confirmed
workspace-empty reads plus denial of protected Role/rule columns and event deletion.
The real PostgreSQL service/UoW test self-provisioned and removed its workspace, subjects, Roles and
failure trigger. It covered `ASSIGNED -> REASSIGNED -> REMOVED`, rejected a semantically identical
Role reaffirmation even though its optimistic expected version changed, rejected a stale Role version,
and reached a forced evidence insert identified by the exact `P0001` SQLSTATE and constraint name.
A non-transactional sequence marker proves the event insert was attempted; subject-scoped snapshots
prove membership/current/event/outbox/idempotency state is unchanged after every rejected command.
The test also exposed and closed an asyncpg JSONPath bind-type defect in the administrator cardinality
query.

The PostgreSQL test must only target an operator-confirmed disposable database. An operator first
creates and migrates that database, supplies separate least-privilege app and migration-owner URLs in
`DATARIVER_POLICY_TEST_DATABASE_URL` and `DATARIVER_POLICY_TEST_ADMIN_DATABASE_URL`, supplies their
secret references, and explicitly sets `DATARIVER_POLICY_TEST_CONFIRM_ISOLATED=1`. Without all three
conditions the default suite skips the test. The test owns fixture setup/cleanup inside that confirmed
database; database creation and final database removal remain explicit operator actions.
Windows/WSL runtime acceptance remains open. Exact scope and residual
Admin/retention gates are in [the Phase checklist](28_POLICY_BOOK_EXECUTION_CHECKLIST.md).

### 2026-07-22 low-resource multi-architecture and external-connector verification

The Redis/MinIO external-connector, bounded catalog state, OpenAI-compatible Chat and offline-release
hardening passed repository-wide Ruff formatting/lint (`280` files), strict mypy (`273` source/test
files), `774` backend tests and `scripts/verify_static.py`. The frontend passed strict TypeScript,
zero-warning ESLint, `39` files / `170` Vitest tests and the production build. The largest emitted
JavaScript chunk is `241.32 kB` (`77.16 kB` gzip); CSS is `155.37 kB` (`27.03 kB` gzip).

On the Mac `linux/arm64` daemon, PostgreSQL, Keycloak and the DataRiver services started with the
selected development profile while Redis and MinIO ran as separately managed connectors. The S3
contract verified authenticated bucket access, exact-origin CORS, anonymous GET/HEAD denial,
5,242,897-byte multipart and presigned-part upload, full-byte checksum read-back and server-side
copy. The repeatable SeaweedFS-to-MinIO migration copied `13` referenced objects and its idempotent
rerun reported `verified_existing=13` and `planned=0`. The final cutover-state probe found zero
active leases, incomplete jobs, unpublished/dead-letter outbox entries and Redis consumer-group
pending/lag. The optional Airflow database initializer also ran with a read-only root filesystem,
tmpfs, dropped capabilities and `no-new-privileges`.

Independent code and architecture reviewers found no remaining P0/P1 issue after the corrective
passes. These are source and Mac-host claims only: final WSL `linux/amd64` import, target restore,
connector reachability, smoke/load/soak and rollback rehearsal remain explicit target-environment
gates.

### 2026-07-20 account/CR/System Settings policy verification

The approved account renewal, System-routed CR authority and development System Settings activation
contracts passed repository-wide Ruff format/lint, strict mypy over `233` source/test files,
`639` backend tests and `scripts/verify_static.py`. The frontend passed TypeScript, zero-warning
ESLint, `36` files / `148` Vitest tests and the production build. The build emitted the existing
main-chunk warning at `838.50 kB` (`241.83 kB` gzip); this remains a performance backlog, not a
correctness exception.

The generated canonical `0001` produced SHA-256
`e4e8630af3604e4c3dfb676b1dddc0f91ddd4a9035cc50406a02201f90881159` on two consecutive runs.
Compatibility tests now cover absent, complete and partial canonical state plus non-destructive
downgrade for revisions `0031` through `0034`; `71` focused migration/domain tests passed. The live
Mac database upgraded `0031 -> 0034`, and a separate empty temporary database migrated from
`0001` through `0034` before being removed. Read-back verified the new renewal and configuration-version
tables, application update rights only on the required membership expiry columns, and SELECT-only
profile-version access for the upload/governance/export startup readers.

Rebuilt API, Web and affected workers started successfully. Direct API, Web and APISIX readiness
returned HTTP 200; host Ollama reported `0.32.1`, and local DataHub and Neo4j returned HTTP 200.
An API replacement exposed APISIX's former startup-pinned address, so the gateway was changed to
APISIX DNS discovery through Docker's embedded resolver and a subsequent API-only replacement
returned through the untouched gateway. The in-app browser rendered a stable unauthenticated login
screen with no console errors; authenticated Admin UI acceptance remains open because that browser
had no user session and no credential was substituted.

### 2026-07-20 enterprise UI completion verification

The Change Management, Knowledge Management, Profile and administrator completion added a shared
four-stage Stepper, non-zero React Flow canvas, Tailwind Vite integration, real registry/releases,
typed visual ontology changesets, a separate release-pinned Knowledge Chat route and server-derived
administrator profile routes. No mock API, raw SQL/Cypher pass-through, local-storage role or direct
DataHub/IdP mutation was added. Component coverage includes future-stage blocking, labelled empty
graph rendering, bounded neighbor request shape and absence of general Chat calls, verified profile
facts and administrator-menu filtering.

After implementation, strict TypeScript, zero-warning ESLint, the full Vitest run (`31` files /
`134` tests), the production Vite build and `scripts/verify_static.py` passed. The build emitted a
non-fatal main-chunk warning at `792.04 kB` (`230.77 kB` gzip), retained as a separate performance
backlog rather than hidden by raising the limit. The rebuilt web container served the matching
`main-CVV_dwJf.js` asset and an authenticated administrator SSO session rendered the CR intake,
Knowledge Registry/ingestion/separate Chat, Profile, USERS/SYSTEMS, user inspector, metadata/security
logs and real vocabulary projection with zero browser warnings or errors. The safe Cypher editor
parsed the local Product/Material relationship into a normalized preview without a server request.
A separate ordinary-user live session and a populated four-stage CR remain environment gates; no
password, browser storage, service account, direct grant or fabricated record was substituted.

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

Historical resilience checks included cache-Valkey stop/recovery. The external Redis connector now
requires equivalent cache and delivery endpoint loss/recovery evidence in each target deployment,
alongside API process restart, API container replacement behind both Nginx and APISIX, and
outbox-relay restart. The API replacement test deliberately kept the web container running and
verified that its Docker DNS resolver did not retain a stale upstream address.

The local seeded same-token revocation probe ran 100 iterations per scenario against the direct API:
membership inactive p99 100.660 ms, explicit `catalog.search` deny p99 167.743 ms and system/domain
scope removal p99 193.388 ms. All passed the provisional 60-second SLA and the original service
membership was restored. This is development evidence, not the required target-load/two-identity or
already-open Chat/SSE gate.

The strategy below remains the production release matrix. Target DataHub/object storage, backup/restore, browser PKCE/hardware-WebAuthn and governed password fallback, load/soak, queue saturation, worker crash-at-each-boundary and promoted-image scans are still environment gates rather than silently assumed passes.

Administrator Role and System Settings changes add the following focused gates:

- access-role metadata and migration checks prove workspace RLS, bounded application grants, no
  credential columns and no delete grant; deterministic initial-migration regeneration must produce
  an identical file;
- Role component tests load definitions from the server and prove assignment uses the governed
  membership-role endpoint rather than a client template;
- an in-use Role must reject security-bearing edits/deactivation, a subject cannot change its own
  Role, and assignment must retain membership version, idempotency, hardware assurance and ABAC
  validation;
- System Settings validation rejects unknown top-level keys, embedded credentials, malformed model
  identities and missing required storage fields; new secret values never cross the browser API;
- connection tests accept only a known system identifier and an already-saved profile. Probe tests
  cover fixed paths, authentication-required status, unavailable targets, and blocked
  link-local/multicast/unspecified/reserved addresses;
- backend test Settings explicitly disable the optional local Ollama path unless a test is about
  that adapter. A developer `.env` must not change unit-test expectations.
- OIDC verifier tests prove that disabling WebAuthn refuses hardware assurance even for matching
  ACR/AMR/authentication-time claims; profile-menu tests remove enrollment and Workspace switching;
  high-risk authorization continues to fail closed rather than accepting password assurance;
- the stable API-client hook test proves a token/Workspace update retains client object identity
  while the next request receives the latest Authorization and Workspace headers. This guards the
  periodic token-renewal flicker regression without suppressing a real Workspace remount.

Audit/Log component tests verify the internal tab switch and zero fabricated rows while the typed
audit read/export APIs remain absent. Retention UI tests and source review must preserve the policy
→ expiry candidate → Legal Hold precedence → erasure-review order and the invariant that APPROVED
does not execute deletion. Target-provider deletion remains an unimplemented release gate.

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
| Performance | k6 plus RSS/DB/external Redis metrics | p95, error rate, memory and soak stability |
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

## Governed Registration execution gates

- Manual SAVE tests must prove fresh projection/provider version checks happen before DB/MinIO
  writes, sparse edits rehydrate the complete non-truncated provider schema, request order is
  canonical and a committed idempotent result is returned before a later provider call.
- Receipt tests require one conditional create, full byte/hash/metadata read-back and no unsafe
  delete after an ambiguous commit. The filename remains
  `UPLOAD_METADATA_MANUAL_YYMMDD_SERIAL.csv`.
- Manual execution tests cover database time, lease epoch/token/owner fencing, expired-attempt
  supersession, per-asset FIFO, 20-attempt exhaustion and ordered evidence for every success and
  failure path. Actual PostgreSQL recovery tests prove exhausted Manual, BULK and CR work is
  terminalized, flushed and skipped before the same claim scans onward. Only five distinct
  successful Aspect reports with expected/observed hash equality permit APPLIED; a direct terminal
  attempt INSERT is rejected.
- Typed BULK tests cover 16 MiB/10,000-row input limits, CSV and XLSX deterministic roots, ZIP/XML
  event-loop isolation, expansion/shared-string budgets, disk rollover at the 256 KiB candidate
  threshold, bounded replay batches, kill/reclaim, complete-publication fences, cursor-bounded
  candidates and one candidate/one CR/outbox transaction. The 10,000-row XLSX memory regression
  remains below the explicit 8 MiB test ceiling.
- Manual and BULK route tests prove that the same authenticated Airflow run ID/call ordinal takes
  the worker effect once and replays the committed response. `0047` creates that receipt in the
  same transaction as the canonical claim, rejects attempts-only fabricated supersession and
  proactively completes an older expired receipt when a newer claim wins. DAG tests require stable
  headers and terminal business failures remain non-retryable.
- The read-only Manual receipt reconciler tests exact DB/S3 matches, missing objects, integrity
  mismatch, unreferenced exact-metadata candidates, malformed/ambiguous objects and fail-closed
  database/S3 truncation and byte limits. Its SQL manifest was executed against PostgreSQL 17 and
  the emitted file parsed as pure JSON.
- Actual PostgreSQL tests cover blank, previous-release additive and canonical re-entry migrations;
  deliberate nullability, FK, RLS and same-name index drift must fail closed. Run the
  environment-gated registration RLS matrix for no context, wrong workspace, Admin, owner/other
  Data Steward, service worker, inactive/expired memberships and immutable mutation negatives.
- Governed apply tests require `0048` exact constraint, trigger and column-ACL fingerprints;
  completed jobs cannot return to RUNNING, APPLIED/APPLY_FAILED requests cannot be rewound, and a
  corrupt completed-job/request pair blocks migration re-entry.
- Attachment tests require `0049` global object identity and `0050` two-principal evidence. The app
  may insert only a current STARTED precommit and cannot attest or directly insert the finalized
  attachment. The existing BYPASSRLS upload role has zero direct intent-table privileges and
  acquires one bounded claim only through a SECURITY DEFINER `FOR UPDATE SKIP LOCKED` function,
  then independently verifies HEAD metadata and the full provider byte hash before STORED. The
  actual-PostgreSQL negative enables BYPASSRLS and still requires direct SELECT to fail.
  Finalization must reauthorize the current human and exact CR round/version/state; the browser
  handles `202 STARTED`, exact upload-UUID response-loss recovery, finalized-response replay,
  hidden-tab pause/resume, 20-read and 120-second limits. A manual recovery query requires the
  current round, filters STORED before its ten-row SQL limit, refreshes successful finalizations
  and still reports any partial failure.
- Frontend fake-provider tests retain only one Manual schema page plus sparse edits, abort stale
  requests, ignore a late Save after draft/page/asset revision, abort an attachment upload after a
  CR switch, reset attachment cursors after upload, stop polling while hidden and after 20 checks or
  120 seconds, and require explicit refresh after the bound or a version conflict.
- External release acceptance still requires the exact target commit on WSL, external MinIO
  conditional-write permission, real Airflow OIDC execution, DataHub 1.6 five-Aspect read-back,
  multiple Keycloak humans and representative crash/load/soak evidence.

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
