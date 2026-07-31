# Test and stabilization strategy

## Current verification status

### Governed administrator user profile and credential reset — 2026-07-31

ADR-0098 adds only subject-bound typed identity profile read/update and temporary-password reset.
Tests cover Keycloak response bounds, exact provider paths, temporary credential shape, session
revocation, human/service-account target rejection, optimistic membership versioning, secret-free
idempotency/audit evidence and the execute-only `0083` projection function. Admin component tests
cover the business-job versus data/screen-access Role distinction, compact profile layout, actual
CR/owned-table activity and guarded profile/password mutations. The complete source gate passed
Ruff format/lint over `555` files, strict mypy over `546` source/test files, `2,094` backend tests
with `105` explicitly environment-gated skips, static architecture/security verification,
TypeScript/ESLint, `73` frontend files / `400` tests and the production build. Runtime migration,
health and authenticated browser evidence is recorded only after the exact clean `dev` commit
passes the stable `dev-publish` gate.

### Administrator-approved Monitoring frames — 2026-07-31

ADR-0097 treats a fresh-assurance administrator save as iframe approval for every credential-free
HTTP(S) Dashboard Link in the persisted Workspace configuration. The response still controls frame
creation, each frame remains sandboxed/no-referrer with a bounded height, and a new-window fallback
remains visible because the target site's own CSP or `X-Frame-Options` may independently deny
framing. Registration causes no server fetch, probe or proxy.

Focused domain/configuration/Nginx tests passed `85` cases and the Monitoring component passed `6`
cases, including a non-Grafana administrator-approved iframe descriptor. Target Ruff,
TypeScript/ESLint and static architecture/security verification passed. Exact-image Nginx header,
complete repository and authenticated browser results are recorded only after the concurrently
owned Knowledge increment publishes and the clean combined source can run the stable
`dev-publish` gate.

### Provider-neutral Monitoring dashboard links — 2026-07-31

ADR-0095 refines the Monitoring presentation boundary so an administrator may save a
credential-free HTTP(S) Dashboard Link from any origin. Registration never causes a server fetch,
probe, proxy, connector change or CSP expansion. The existing deployment-owned exact-origin
Grafana gate remains the only way to receive a sandboxed iframe descriptor; all other origins open
as isolated external links. Domain tests cover heterogeneous origins, credential rejection,
active-content scheme rejection and the existing tab/height bounds. Component tests use a
non-Grafana link and require the provider-neutral **Dashboard Link** label.

The complete backend suite passed `2,069` tests with `104` explicitly environment-gated skips.
Strict mypy passed over `540` source/test files and static architecture/security verification
passed. Frontend TypeScript/ESLint passed; `73` files / `395` tests passed and the production build
completed. Runtime/browser evidence is recorded only after the exact commit is published.

### Governed monitoring dashboard tabs — 2026-07-31

Revision `0078` adds a Workspace-scoped monitoring presentation aggregate with forced RLS.
Administrators with fresh assurance can save at most eight ordered dashboard tabs, but the server
accepts only HTTP(S) URLs whose exact origin is already deployment-approved by
`UI_GRAFANA_URL` or `GRAFANA_EMBED_BASE_URL`. Saved presentation metadata cannot enable iframe
embedding, expand CSP, change the Grafana connector or store credentials. Component tests cover
multi-tab selection, bounded dashboard height, the administrator-only editor and the relocation of
server capability observations to System Settings.

Repository Ruff format/lint passed over `528` files, strict mypy passed over `519` source/test
files, the backend suite passed `2,010` tests with `104` explicitly environment-gated skips, and
static architecture/security verification passed. Frontend TypeScript/ESLint passed; the complete
single-worker suite passed `71` files / `386` tests and the production build completed. Two
canonical `0001` generations were byte-identical at SHA-256
`ea8ded7766ac7606b3a9b91664c6814a3251d26a6997df97ddd1967cd8147d1d`.
Authenticated browser/runtime evidence is recorded only after publishing the exact commit; target
deployment Grafana/CSP acceptance remains an external gate.

### Server-observed Chat live workflow progress — 2026-07-31

The Chat stream uses the same bounded request and authorization contract as the ordinary endpoint.
Focused service tests assert that only real operation starts emit request-local `IN_PROGRESS`
events and that those events are not persisted. Route tests assert the SSE workflow-to-final-result
ordering, while browser-component tests assert an in-progress stage renders before the final answer
and is replaced by a terminal stored trace. Development runtime/browser evidence is recorded only
after the exact committed source has been published; target deployment behavior remains a separate
acceptance gate.

### Durable Knowledge Studio T-Box Proposal jobs — 2026-07-31

Revision `0084` adds the forced-RLS Proposal job/attempt/event ledger, owner-scoped idempotent
commands and a function-only `datariver_knowledge_proposal` worker boundary. Its focused source
tests cover accepted manifest/Catalog pin validation, typed lifecycle handling, worker
cancellation and the exact function/grant contract. The isolated PostgreSQL gate additionally
must exercise direct-DML denial, `SKIP LOCKED` claim, lease fencing and running cancellation.
Cross-Workspace/owner denial, retry/lease recovery, requester/Draft/T-Box/source/model drift and
atomic READY-Proposal finalization remain required database cases; they must not be inferred from
source-only tests.

Upload tests cover the exact 10 MiB PDF/CSV/TXT/JSON/XML/HTML/DOCX/XLSX/PPTX profile and
legacy/MIME/extension/macro/external-link/XML-entity negatives. HTTP/UI tests require `202`,
ETag/idempotency, no provider call in the API request, refresh recovery, visibility-aware polling,
cancel/retry and exact Proposal preview. Redaction tests prohibit prompt/excerpt/provider body,
bucket/object key, presigned URL and lease token in jobs, events, API responses and representations.
The previous synchronous document/Catalog routes return `410`, and the route-specific Nginx timeout
assertion is removed. Provider/runtime browser evidence is reported only for the exact published
commit and is not inferred from source tests.

### Knowledge Information Profiles and superseded bounded Proposal timeout — 2026-07-31

Revision `0076` adds forced-RLS Property Profile and normalized synonym tables tied by composite
foreign keys to the exact active Studio Release ontology and `PROPERTY` element identity.
Unit/service tests cover Unicode normalization, domain/classification authorization, archive and
post-archive re-creation, least-privilege grants, ETag mutation and response-loss idempotency-key
replay. Knowledge component tests cover the consolidated Information workspace, real Profile CRUD,
saved block-title feedback, document apply-mode layout and TanStack Catalog/field selection.

Revision `0076` originally carried a route-specific timeout bridge for the bounded synchronous
document Proposal. ADR-0099 and revision `0084` retire that route after the durable UI cutover and
remove the timeout bridge. The Profile aggregate tests remain current; timeout-specific assertions
are historical evidence only. Canonical `0001` is regenerated twice and compared byte-for-byte
before publication; target PostgreSQL migration/RLS and authenticated browser results are reported
separately from source gates.

### Governance Document pgvector/download/Chat refinement — 2026-07-31

Revision `0075` adds Bleach policy evidence, exact-VersionId Presigned download, exact pgvector
cosine retrieval, declared GovernancePolicy-to-Dataset/Term graph edges, the POST RAG contract and
Chat current-version citation reauthorization. Source and runtime results are recorded in the
Phase 9 implementation record after the final clean `dev` gate; no ANN, WORM or production SLO
claim follows from source tests.

Revision `0077` is a compatibility-only migration that renames the dimension check left by the
`0075` additive naming-convention path to the exact SQLAlchemy/canonical `0001` identity. Contract
tests require both known names, a fail-closed catalog lookup and the canonical metadata name; the
target runtime gate additionally inspects `pg_constraint`, `vector_dims` and the Alembic head.

### Governance Document Phase 9 local release gate — 2026-07-31

Revision `0072` implements forced-RLS document/Template authoring, immutable version and approval
evidence, safe HTML, create-only versioned MinIO artifacts/attachments and authorized
vector/Neo4j projection. Repository Ruff passed over `511` files, strict mypy passed over `502`
source/test files, static architecture/security verification passed, and the backend suite passed
`1,955` tests with `104` explicitly environment-gated skips. Frontend TypeScript/ESLint passed;
`68` files / `367` tests passed and the production build completed.

Two canonical `0001` generations matched at SHA-256
`bbe25ca8451f60720c353e5bd70461ef2885fa6b8b5f36ea19732ff4ccdab030`.
PostgreSQL `17.10` accepted `0071 -> 0072`; all eight new tables reported forced RLS, both deferred
foreign keys existed and the dedicated NOBYPASSRLS/NOSUPERUSER worker retained only projection
column updates. The live MinIO adapter passed create/read/replay while list/delete were denied, and
the API/worker runtime passed readiness and error-free idle cycles. Production Object Lock,
representative retrieval/load, WSL amd64 and target identity/browser acceptance remain external
gates.

### GX Quality Phase 8 authoring/manual execution readiness — 2026-07-30

Revision `0071` adds only fixed server-derived review, activation and manual-Run command functions.
The browser cannot submit source coordinates, GX classes, connection data, retention bindings or
authorization evidence. V2 deployment manifests provide exact field/type/source/workload bindings;
missing deployment inputs keep authoring and execution capability closed.

Repository Ruff passed, strict mypy passed over `481` source/test files, the complete backend suite
passed `1,882` with `104` explicitly environment-gated skips, and static architecture/security
verification passed. Frontend TypeScript and ESLint passed; `65` files / `356` tests passed and the
production build emitted the lazy Quality chunk at `62.12 kB` (`16.63 kB` gzip). Two consecutive
canonical `0001` generations were byte-identical at SHA-256
`59502d46caa5bd9bb5b6f2764c1e160740586c6724d8d8e69bc0887bd5d83033`.

An isolated PostgreSQL `17.10` database accepted canonical `0001` and the actual `0070 -> 0071`
upgrade. Five live Quality tests passed, including semantic fingerprint drift rollback, complete
V3 retention genesis, concurrent Legal Hold generation and the manual command's atomic
Run/event/outbox creation. Real DataHub collection, approved target source execution, worker/Airflow
enablement, target identities, screen-reader/zoom acceptance and WSL amd64 artifacts remain
external gates.

### GX Quality Phase 6 local operational gate — 2026-07-30

The implementation under test is commit
`cdf2eb24c520787abd114c4c8ec7db2e49ab1ae2` on `dev`, with database revision `0070`.
This gate closes the source and Mac-development checks that can be executed without inventing a
target source, retention decision, human identity or WSL environment. It does not open the
Quality worker, Airflow schedule, Rule mutations or production release.

Focused backend Quality/Profile/Airflow tests passed `99/99`; the four Quality frontend test files
passed `9/9`. Those tests keep `REGEX` unavailable at both the domain and GX compiler boundary,
discard raw unexpected rows/values/indexes/query/provider exceptions, reject unapproved source
URLs/queries/credentials, deny service identities on the public API, bind authorization leases and
cursors, cap list pages at `100`, cap cursor input at `2,000` characters and bound selected-Run
polling to 20 reads or 120 visible seconds.

The running Mac PostgreSQL `17.10` database reported revision `0070`. The
`datariver_app`, `datariver_quality` and `datariver_catalog_profile` roles all reported
`rolbypassrls=false`; the inspected Catalog/Quality relations retained their Workspace and
Quality read policies. Direct `datariver_app` reads with no session context returned zero Catalog
assets, Rule Sets and Runs. The local dataset contains `2,000` Catalog assets in the application
Workspace but no Quality Rule/Run evidence, so a cross-Workspace Quality count-leakage load claim
would be meaningless and remains a target gate.

On that non-representative dataset, an authorization-pruned active-asset list used
`ix_assets_projection_active_scope_order` as an index-only scan in `0.067 ms` with three shared
buffer hits. The active Rule Set aggregate used the expected Rule Set and ACTIVE-Version indexes
in `0.053 ms` with two shared buffer hits, but traversed no Quality row. These measurements prove
the local structural access path only; they are not a representative SLO, load or soak result.

The live local gateway returned a bounded `268`-byte `401` problem for a Workspace-scoped request
without a bearer token. A real Keycloak client-credentials token for the dedicated Airflow Quality
dispatcher reached the public capability endpoint and was denied as a human-only boundary with a
bounded `243`-byte `403` problem. The in-app browser rendered the sign-in-required state without
persisted credentials; no human session was available for post-login accessibility testing. The
Chrome control extension was absent, so no alternate authenticated browser claim is made.

The built Mac worker image is
`sha256:12262595340cd28e8c51bad9712ce58b22ec03bbae3e85d20dd6c60ea5ede98a`
(`linux/arm64`). A network-disabled one-shot import reported `aarch64`, DataRiver `0.1.0`, GX
`1.19.1`, asyncpg `0.31.0` and SQLAlchemy `2.0.49`. The running API and Web images are respectively
`sha256:392b183557a48ffd48a7c912aa76182b753431f6c0e7492ebfcb90b8553e48df` and
`sha256:9f9d15db014e2c934cefda7273c60e74e765863e506f9afd5d2bb99340a3fe25`
on `linux/arm64/v8`.

The full repository verification passed Ruff format/lint over `482` files, strict mypy over `473`
source/test files, backend `1,871 passed / 103 environment-gated skipped`, static verification,
frontend TypeScript/ESLint, `63 files / 348 tests` and the production build. Final `dev-publish`
reruns these gates after the evidence commit. Representative source and Quality datasets,
60-minute soak, real multi-Workspace human identities, target
DataHub/Profile/Airflow/source execution, screen reader/zoom, exact WSL amd64 artifacts and
`prep-update` remain explicit external gates.

### GX Quality Phase 4 authorized read model and dashboard — 2026-07-30

Revision `0070` adds only three bounded read-path indexes. The human Quality API authorizes
`quality.read` on every resource request, records the separate `quality.profile.read` decision
before returning approved FULL/PARTITION Profile readiness, rejects service identities and joins
the Catalog authorization-pruned asset relation before every count, score, trend, list, detail,
result and issue aggregate. Cursor material binds the Workspace, permission/classification scope,
resource and page size. Responses are `private, no-store`; no sample value, failure row, provider
locator or source credential enters the contract.

The React surface performs a capability-first read with a database-time lease no longer than 30
seconds, binds query memory to Workspace/Subject/security epoch/authorization revision/cache scope,
and provides four roving tabs. Score and coverage use only server values; the chart has an
equivalent table. Rule Set detail is fetched lazily. Only the selected non-terminal Run uses
immediate `1/2/5/10` second polling, bounded to 20 reads or 120 visible seconds and paused while
hidden. Rule authoring, activation, manual execution and scheduling remain visibly
capability-closed because portable source has no trusted field-directory or deployment-readiness
attestation.

Repository Ruff format/lint passed over `482` files, strict mypy passed over `473` source/test
files, the complete backend suite passed `1,871` with `103` explicitly environment-gated skips,
and static architecture/security/documentation verification passed. Frontend TypeScript and ESLint
passed; `63` files / `348` tests passed and the production build emitted the lazy Quality chunk at
`38.10 kB` (`10.31 kB` gzip). Two consecutive canonical `0001` generations were byte-identical at
SHA-256 `cbae1511f3431f77c422da52b95a79d3d1cdda209e96ad84142927b39ee79f56`.

The running PostgreSQL `17.10` Mac development database passed the actual `0069 -> 0070` upgrade.
All three indexes were present; `0070 -> 0069` removed exactly those indexes and the immediate
re-upgrade restored revision `0070` and all three. One repository-wide frontend run observed a
pre-existing Knowledge Studio timeout assertion choose its alternate bounded timeout message; the
unchanged file then passed `12/12` alone and the complete frontend suite passed `348/348`. This
intermittent message-choice assertion is retained as a medium/low-priority test-stability item and
was not patched as part of Quality.

Target browser zoom/screen-reader acceptance, representative dashboard `EXPLAIN (ANALYZE,
BUFFERS)`, multi-workspace count-leakage load, real Profile/source execution and WSL amd64 remain
later external gates. This phase does not claim mutation or production enablement.

### GX Quality Phase 3 execution plane — 2026-07-30

Revision `0069` adds the service-only execution plane without adding another canonical table:
authenticated bounded Airflow dispatch, database-time schedule/run creation, fenced claim and
source-access functions, immutable execution receipts/events/outbox, a disabled-by-default
quality-worker, a fixed GX `1.19.1` compiler, strict result sanitizer and an exact-hash source
manifest. The worker uses a separate NOBYPASSRLS database role, a read-only PostgreSQL
`REPEATABLE READ` transaction and no DataHub credential; Airflow has a different OIDC client and
has neither GX nor source credentials.

Repository Ruff format/lint passed over `473` files, strict mypy passed over `464` source/test
files, the complete backend suite passed `1,865` with `103` explicitly environment-gated skips,
and static architecture/security/documentation verification passed. Two consecutive canonical
`0001` generations were byte-identical at SHA-256
`0634ea3c75f5b9004973c1525a05f88983bcb9516993681beaaca44031123096`. The arm64
quality-worker image built with GX `1.19.1`.

The existing PostgreSQL `17.10` development database passed the actual `0068 -> 0069` upgrade.
Catalog probes show zero direct Quality table grants to `datariver_quality`, exactly five approved
execution functions granted to that role and zero PUBLIC execution grants. A real Airflow
service-account OIDC call reached the internal API and, because this development Workspace has no
active Quality retention policy, failed closed as a sanitized retryable `503` without exposing the
database error. A target read-only source execution remains a deployment acceptance gate until an
operator supplies the approved retention binding, source manifest, secret, target mapping and scan
budget; no synthetic business policy or credential was seeded to manufacture a portable pass.

### GX Quality Phase 2 DataHub Profile integration — 2026-07-30

Revision `0068` adds a privacy-allowlisted DataHub v1.6 Profile adapter, explicit
`FULL/SAMPLE/PARTITION/QUERY/UNKNOWN` and `COMPLETE/PARTIAL` semantics, a disabled-by-default
one-target collector, dedicated NOBYPASSRLS role, immutable Catalog projection and exact
`QUALITY_PROFILE` retention/Legal Hold binding. Sample values, top values, distribution payloads
and raw partition/query text are not persisted or returned.

Repository Ruff format/lint passed over `453` files, strict mypy passed over `447` source/test
files, the complete backend suite passed `1,819` with `103` explicitly environment-gated skips,
and static architecture/security/documentation verification passed. Isolated PostgreSQL `17.10`
passed clean canonical `0001`, `0067 -> 0068`, canonical re-entry, exact service-role
positive/negative projection, immutable replay and both evidence-refusing and empty-development
downgrade paths. The pinned DataHub v1.6 service accepted the fixed GraphQL schema; the target
least-privilege service token and recipe ingestion report remain an explicit deployment gate.

### GX Quality Phase 1 domain, authorization and PostgreSQL control plane — 2026-07-30

Revision `0067` adds the framework-free Quality aggregate/contracts, dedicated human and
service-only Actions, three typed retention classes, typed RuleSet/Run Legal Hold targets, 13
Quality control-plane tables, fixed maker-checker lifecycle functions, forced RLS and a
NOBYPASSRLS `datariver_quality` role. GX remains an optional, disabled worker dependency; this
phase does not claim DataHub Profile collection, source execution, API or UI behavior.

Repository Ruff format/lint passed over `441` files, strict mypy passed over `435` source/test
files, the complete backend suite passed `1,792` with `101` explicitly environment-gated skips, and
static architecture/security/documentation verification passed. Two consecutive canonical `0001`
generations are byte-identical at SHA-256
`76896d4104a3fe44ac24b411ec987b685919204fc3410499dcaab4ed3dc68a2c`; Alembic has the sole head
`0067`, and `alembic check` against the isolated head reports no upgrade operations.

An isolated official PostgreSQL `17.10` instance passed a clean empty-to-head migration, an actual
pre-change `0066 -> 0067` additive upgrade, complete canonical re-entry and a partial-contract
fail-closed re-entry. All 13 Quality tables have forced RLS. Actual application-role probes returned
zero rows for the wrong Workspace, one permitted Legal Hold generation for the correct Workspace,
and denied direct RuleSet mutation. The service role has no direct table privilege, PUBLIC has no
Quality function execute privilege, and lifecycle functions remain application-callable only
through their fixed signatures. Forced index plans selected the ACTIVE-version, due-schedule,
runnable-run and terminal-dashboard indexes. Downgrade refused non-empty immutable evidence; a
provably empty schema downgraded to `0066`, removed the Quality schema and typed Legal Hold column,
then reapplied `0067` successfully.

The final isolated canonical and additive databases each passed four focused PostgreSQL tests:
semantic-catalog drift rejection, live target-drift rejection, atomic first-generation
initialization for a newly created Workspace and concurrent Legal Hold generation serialization.
Quality Legal Hold data-class/resource-type combinations are closed in both domain and DDL
contracts. Successful-run results are bound to the exact current successful attempt and Rule Set
Version, and deferred commit-time triggers require one result per Definition with matching summary
counts and outcome. The managed catalog fingerprint also covers retention policy/rule/hold tables,
all table/column/function/schema ACLs, schema owners and trigger enabled state.

The broader historical `head -> base` recovery probe is not a Phase 1 acceptance claim: after
successfully removing revision `0067` and continuing through older revisions, it found a pre-existing
revision `0051` check-constraint naming mismatch. PostgreSQL rolled the command back. That legacy
full-chain downgrade repair is recorded for the final consolidated maintenance pass and is not
silently represented as fixed here.

The arm64 dependency audit pins GX `1.19.1`, produced a 71-component CycloneDX SBOM
(`60c4ac1c7d115b17e887a7269189ab46fdbb2767053427eb6e5f0a5e1c67e710`) from lock
`c822728328b67e71d8d5b24dc8da22c9ab420daef33153c58db86e55715d09a3`, imported GX, passed
dependency consistency and found no known vulnerabilities. Runtime enablement remains closed:
the new `tqdm` transitive declares `MPL-2.0 AND MIT` and requires the repository's accountable
distribution decision, and the matching Linux/WSL amd64 artifact has not yet been validated.

### GX Quality Phase 0 contract and ADR — 2026-07-30

ADR-0077 and the Quality PRD/checklist approve a new bounded context, but no Quality table,
migration, dependency, worker, Airflow DAG, API or dashboard is implemented in this phase. The
review is source-based and cross-checks the current DataHub query/recipe, canonical ownership,
credential boundaries, target model, Rule/score semantics, security matrix and later acceptance
gates.

The review found that the checked-in PostgreSQL DataHub recipe combines table-only profiling with
an enabled field metric, which the pinned DataHub v1.6 configuration rejects. It also found that
the current asset query accepts FULL and SAMPLE profiles while omitting partition provenance. These
are explicit Phase 2 correction/target gates, not current field-profile evidence. Phase 0 must not
be reported as GX, profile, PostgreSQL RLS, Airflow or UI execution evidence.

### Knowledge Studio Phase 2.6 session/domain/document UX increment — 2026-07-29

Revision `0066` adds bounded endpoint-alias arrays, managed DOMAIN creator/version evidence and
document-Proposal source references. Draft-scoped Zustand sessions retain Basic, per-block
T-Box/Cypher/viewport and unfinished A-Box mapping inputs across component unmounts. The Graph
Builder now provides compact saved block headers, zoom-scaled node editing, hierarchy drop targets,
direct selected-element deletion, read-only layer groups and editable typed Proposal overlays.
The real bounded upload route writes create-only filefolder objects, invokes only the approved
Schema Assistant and never fabricates progress or elements.

Ruff format/lint over `433` files, strict mypy over `427` source/test files and static
architecture/security/documentation verification pass. The complete backend suite passes
`1,752 passed / 97 environment-gated skipped`; frontend strict TypeScript, zero-warning ESLint,
`58 files / 327 tests` and the Vite production build pass. Two consecutive canonical `0001`
generations are byte-identical at SHA-256
`8a134ba55fd18c33b99bd5205061b727e1af9f364558dfc1a646b2dd37e335b1`, and Alembic has the sole
head `0066`.

The source gates do not claim the skipped isolated PostgreSQL/S3 targets. Authenticated browser DOM
acceptance remains separate because the available local browser session returned to the Keycloak
login screen after the source build.

### Knowledge Studio Phase 2.5 Unicode and integrated Proposal increment — 2026-07-29

Revision `0065` adds the named Class hierarchy edge and covering parent/child lookup index. Domain,
safe-editor and UI tests cover Korean NFC Class/Property round trips, invalid-buffer retention,
name-click-only floating editing, Property create/update/delete, sibling re-parenting,
hierarchy-label synchronization, explicit block-title confirmation, read-only groups and
latest-only block deletion. Service tests cover TBOX-step catalog authorization scope.

Ruff, strict mypy over `222` backend source files and static architecture/security/documentation
verification pass. The complete backend suite passes `1,743 passed / 97 environment-gated
skipped`; frontend strict TypeScript, zero-warning ESLint, `56 files / 321 tests` and the Vite
production build pass. Two consecutive canonical `0001` generations are byte-identical at
SHA-256 `22ec1c62f87b0c5679a93eb8ea2bd0d4a5c6c598908e36a8dd3b4a5fc681c949`.
Document Proposal inference remains capability-closed until the separately fenced ADR-0069 worker
is deployed; no browser or API path fabricates a successful document analysis.

### Knowledge Studio normalized hierarchy and layer dependency increment — 2026-07-29

Revision `0064` normalizes the accepted T-Box Draft shape into the common element registry plus
Class, Property and Relationship subtype tables. Focused domain/service/UI tests cover single-parent
hierarchy, cycle and missing-parent rejection, tree drag/drop `SUBCLASS_OF` synchronization,
invalid-editor last-valid retention, floating Property addition, read-only layer groups,
later-reference locks, current-to-earlier references and latest-only block deletion.

Repository Ruff format/lint, strict mypy over `425` source/test files and static
architecture/security/documentation verification pass. The complete backend suite passes
`1,741 passed / 97 environment-gated skipped`. Frontend strict TypeScript, zero-warning ESLint,
`56 files / 318 tests` and the production build pass. Three consecutive canonical `0001`
generations are byte-identical at SHA-256
`95ba1cd1046c8b1a625e6cb095c3b5b89ca28e190852db40d831186597e2751c`.

These source gates do not by themselves claim a target PostgreSQL migration or authenticated
browser acceptance. The stable `dev-publish` runtime migration/health pass and an authorized
Graph Builder interaction remain separate execution evidence.

### Knowledge Phase 6 cutover QA remediation — 2026-07-28

Revision `0062` adds deterministic workspace DOMAIN seed data and an auditable graph Archive
lifecycle. The Knowledge UI keeps one PageTitle/left workspace shell while switching Registry,
GraphRAG Chat and Studio content. Registry actions now open a base-pinned EDIT Draft or execute a
version-fenced soft archive; the bounded right drawer is mouse/keyboard resizable and release
selection drives the metadata and snapshot preview from the same immutable release ID.

Frontend strict TypeScript, zero-warning ESLint, `56 files / 312 tests` and production build pass.
Backend Ruff format/lint, strict mypy over `222` source files, static verification and the complete
suite pass at `1,726 passed / 97 environment-gated skipped`. Repeated canonical `0001` generation is
byte-identical at SHA-256
`7f4e1d543f9eab64d7d03ce503c7ec5306af140cbecd846240b1227033e5bd70`; Alembic has the sole head
`0062`.

The skipped external PostgreSQL/RLS suites, authenticated target-browser interaction, mouse resize
capture, actual target migration and preparation-PC health remain target-environment gates. The
local passes are not production acceptance.

### Knowledge Studio Phase 6 Graph Builder scaffold / RC preparation — 2026-07-28

The Step 2 route now exposes a genuinely empty React Flow canvas. Only a user-named local test node
can be added; drag/connect/explicit selected-node deletion remain browser-memory interactions and
never become a typed operation, Accepted T-Box, autosave, Publish or provider/Neo4j mutation.
`REVIEW`, `PUBLISHED` and `DISCARDED` lock the scaffold.

The stable `development_cycle.py dev-publish` gate passes repository-wide Ruff format over `427`
files, Ruff lint, strict mypy over `421` source/test files, static architecture/security/
documentation verification and the whole backend suite at `1,694 passed / 97 environment-gated
skipped`. The two prior DataHub format-only baseline files are now mechanically normalized and
their focused test passes `49`.

Frontend strict TypeScript, zero-warning ESLint, `55 files / 303 tests` and the production build
pass. The focused Graph Builder/Studio routing set passes `2 files / 8 tests`, including true empty
state, no fabricated schema, user-named local add, explicit selected-node deletion, lifecycle lock
and saved Step 1 routing.

The Mac development workflow executed the real additive PostgreSQL chain `0058 -> 0059 -> 0060 ->
0061`, reapplied roles and reported API readiness, Web health, Keycloak, DataHub GMS `v1.6.0` and a
2,000-row authorization-pruned catalog projection sync as healthy. The visible in-app browser
reached the local Keycloak login form. No existing login session was present, so authenticated
Graph Builder interaction remains a human sign-in gate; no credential or token was bypassed or
injected.

### Knowledge Studio governed Publish / Phase 5A — 2026-07-28

Revision `0061` adds durable pre-flight receipts, immutable Studio Releases/T-Box element/A-Box
mapping versions, independent-review publication, physical-source adapter boundaries and exact
cleanup tooling. The focused backend service/persistence/preview/connection/cleanup suite passes
`39`; the whole backend suite passes `1,694` with `97` explicitly environment-gated skips. Ruff
lint, strict mypy over `421` source/test files and static architecture/security/documentation
verification pass.

The frontend passes strict TypeScript, zero-warning ESLint, `54 files / 300 tests` and production
build. The focused Data Enricher/API selection passes `2 files / 8 tests`, covering receipt headers,
REVIEW/Publish lifecycle, read-only reviewer mapping, Discard, release response and explicit
`Ingestion: NOT_RUN`.

Repeated canonical `0001` generation is byte-identical at SHA-256
`185641e239e82d7f6948e761fd929a618fdacaebc766cbb45f031a713728eba1`; the sole Alembic head is
`0061`, with `0060 -> 0061` confirmed in the local chain. Changed Python files pass Ruff format.
The repository-wide format check still reports only the two unrelated pre-existing files already
recorded below: `infrastructure/datahub/http.py` and `test_datahub_gateway.py`.

The local suite proves typed/service/persistence-source invariants but skips `97` external
integration cases by configuration. In particular, isolated PostgreSQL `0060 -> 0061` execution,
app-role maker/checker RLS, concurrent same-graph archive/Publish rollback, real two-human
OIDC/WebAuthn, browser accessibility, approved physical row access and WSL `linux/amd64` remain
external gates and are not represented as passes.

### Knowledge Studio Data Enricher / A-Box Mapping Draft — 2026-07-28

The Data Enricher increment advances Alembic head to `0060`. Focused domain, source-adapter,
service, persistence and OpenAPI tests pass `85` cases. The whole backend suite passes `1,670` with
`97` explicitly environment-gated skips. Repository Ruff lint, strict mypy over `414` source/test
files and static architecture/storage verification pass. The exact repository Ruff format gate
continues to identify only the two unrelated pre-existing DataHub files recorded by the preceding
Studio addendum; all changed Python files pass format.

The frontend passes strict TypeScript, zero-warning ESLint, `54 files / 296 tests` and the
production build. Nine focused Studio tests include Dataset/column mapping, target-scoped payload
and ETag headers, persisted accessible `Mapped · DRAFT` feedback, local-input preservation on
`412`, confirmed latest-ETag rebase and the existing Step 1/route contracts.

Canonical `0001` generation is byte-identical across repeated runs at SHA-256
`978de14ce3e5947e5be3d4d67b34aba60e5029ed542ce805596eec11785f7f40`; the sole Alembic head is
`0060`. Model/source checks verify FORCE RLS, restrictive owner policies, composite `RESTRICT`
foreign keys, least privilege and one non-duplicated self-reference constraint per accepted T-Box
link. An isolated PostgreSQL upgrade/app-role RLS/concurrent-session run, live DataHub schema drift,
real browser interaction and target WSL `linux/amd64` remain external gates and are not represented
as passes. The Step 2 accepted-operation writer remains a prerequisite; without accepted
`tbox_draft_elements`, Step 3 intentionally renders an empty state and cannot invent a schema.

### Knowledge Studio Draft API and recoverable Step 1 — 2026-07-28

The additive Studio command/read implementation retains Alembic head `0059`. Focused backend
domain/service/persistence/OpenAPI/error tests passed `27` selected cases; the whole backend suite
passed `1,655` with `97` explicitly environment-gated skips. Ruff lint, strict mypy over `412`
source/test files and static architecture/storage verification passed. The exact repository Ruff
format gate is clean for all changed files and still reports two unrelated pre-existing files:
`infrastructure/datahub/http.py` and `test_datahub_gateway.py`.

The frontend passed strict TypeScript, zero-warning ESLint, `53 files / 294 tests` and the
production build. Seven focused Studio tests cover typed API headers, required response ETags,
queue-before-send, 1.5-second debounced creation, Step 2 routing, offline retry, queue-write
fail-closed behavior and both explicit 412 resolution choices. Browser storage deletion/eviction,
device loss, real multi-tab/two-session concurrency and isolated PostgreSQL row-lock/RLS execution
remain external gates and are not represented as passes.

### Phase 6C atomic Sharing hardening — 2026-07-24

Phase 6C closes local backlog item `R5-BE-05H` without changing Alembic head `0055`. Ruff
format/lint, strict mypy over `374` source/test files, static verification and the whole backend
suite passed: `1,419 passed / 97 environment-gated skipped`. The frontend regression passed
TypeScript, zero-warning ESLint, `46 files / 244 tests` and the production build.

The focused source set passed `39` tests. The isolated PostgreSQL 17 clean-room harness passed
`13` tests, adding contract-timeout rollback, canonical-serialization rejection, result/monthly/
deferred-commit fault injection, the complete ineligible grant-Subject matrix, absent and
mismatched fixed-function context, expired-body and current-state replay denial, and observed-lock
invoke/revoke/publish interleavings in both directions. The revoke/publish and membership
linearization tests use PostgreSQL backend PIDs and `pg_blocking_pids`, not elapsed delay, to prove
the intended blocker before release.

The unchanged migration contract again passed additive/canonical/downgrade/tamper checks and
`alembic check`; canonical SHA-256 remains
`ffc0abb58b3f4550bcc5d1524ffd9cd954076d0bf73112cab19fc7b3252e7c2f`. WSL `linux/amd64`, real
Keycloak service identity/rotation, representative target graph/load/lock/soak and accountable
physical purge remain external gates.

### Phase 6B atomic Sharing invocation — 2026-07-24

The current worktree closes the local `R5-BE-05` implementation at Alembic head `0055`. Ruff
format/lint, strict mypy over `374` source/test files, static architecture/Compose/document
verification and the whole backend suite passed: `1,417 passed / 93 environment-gated skipped`.
The skips are not passes. The frontend passed TypeScript, zero-warning ESLint, `46 files / 244
tests` and the production Vite build.

The focused domain/persistence suite passed `37` tests. The repository-owned
`scripts/verify_atomic_sharing_postgres.sh` provisions and removes an isolated PostgreSQL 17
container, roles and three disposable databases. It passed `9` app/owner concurrency and security
tests at `0055`: exact first/replay,
same-key races, changed binding conflict, builder/oversize rollback, revocation/non-disclosure,
direct-table denial, immutable/orphan evidence, pre-parse byte rejection, membership-lock
serialization, concurrent RPM/month quota, 59/61-second and UTC-month boundaries, legacy
usage/replay, permission/product/retention drift and separate audit/body retention. Additive `0054 -> 0055`, empty canonical
`0001 -> 0055`, safe no-evidence downgrade and downgrade refusal with evidence were also exercised.
The additive path seeded three 0054 legacy rows across a UTC month boundary and verified preserved
IDs, honest legacy evidence, exact monthly sums/timestamps and no fabricated result. Malformed
canonical states with RLS disabled, the exact-result trigger disabled, inherited or SET-only app
capability, app outbound SET ROLE, unsafe app attributes or runtime-owned evidence failed `0055`
before revision advance.
`alembic check` reported no new operations.

Canonical `0001` was generated twice byte-identically at SHA-256
`ffc0abb58b3f4550bcc5d1524ffd9cd954076d0bf73112cab19fc7b3252e7c2f`. WSL `linux/amd64`, real
Keycloak service identity/rotation, representative target load/lock-wait/soak and accountable
physical result-purge evidence remain external gates.

### Phase 6A WSL bootstrap and connector network — 2026-07-24

The current worktree adds fail-before-mutation blank-profile coverage, approved token-file
preservation/non-disclosure, positional-secret rejection, same-file and symlink negatives,
deterministic inspect/create/Compose ordering, config-only behavior and invalid-network negatives.
The focused set passes `15` tests. The full source passes Ruff format over `377` files, Ruff
lint, strict mypy over `370` source files, static verification and backend
`1,380 passed / 84 environment-gated skipped`; frontend TypeScript, ESLint,
`45 files / 243 tests` and production build pass.

Native and `DOCKER_DEFAULT_PLATFORM=linux/amd64` Compose rendering is configuration-only evidence.
`pwsh`, target WSL and target Docker/provider execution remain external.

### Phase 5 durable Knowledge source jobs — 2026-07-24

The current worktree's local Phase 5 gates passed with Alembic head `0054`. Ruff format/lint,
strict mypy over 370 source/test files and static architecture/Compose/document verification
passed. The whole backend suite reported `1,369 passed, 84 skipped`; the skips require explicit
external/isolated environments and are not passes. The frontend passed TypeScript, zero-warning
ESLint, `45` files / `243` Vitest tests and the production Vite build.

An additive `0053 -> 0054` PostgreSQL 17 database and a completely empty database migrated from the
regenerated canonical `0001` through `0054`; each passed `24` owner/app/worker and cross-service
role tests for paging/capacity, claim fencing, recovery, cancellation, exact-claim RLS, atomic DRAFT
finalization and event/outbox/policy evidence integrity. `alembic check` reported no new operations.
A dirty-principal probe removed an intentionally added `DELETE` privilege. A temporary membership
that allowed the worker to `SET ROLE` caused canonical migration to fail closed and was removed
after the test. Upload/governance/relay namespace-forgery and mutation cases also failed closed.

Canonical `0001` was regenerated twice with byte-identical SHA-256
`a9978344ab90982c6d5f6c8929b8a976f34418d5fbcae2a8de6758171bda6f98`. Native and
`DOCKER_DEFAULT_PLATFORM=linux/amd64` Compose rendering passed for core and local object-storage
profiles. Target WSL image execution, private MinIO/S3 IAM, private Chat/Embedding DNS/TLS,
distinct-human IdP/browser acceptance and representative queue/load/recovery telemetry remain
external gates.

The Phase 4 Knowledge entry implementation `bd0ee22`, based on `716fb6f`, passed the whole current
backend suite:
`1,328` tests passed and `60` target-environment integration cases were explicitly skipped. The
README-equivalent Ruff format/lint arguments passed over `375` files, strict mypy passed over `358`
source/test files, and static architecture/Compose/document verification passed. The `uv run`
wrapper could not initialize its user cache inside the restricted filesystem sandbox; the same
locked environment executables in `.venv` ran the gates without dependency resolution. The
frontend passed strict TypeScript, zero-warning ESLint, `45` files / `238` tests and the production
build. Canonical `0001`
generation was byte-identical across two runs at SHA-256
`2f38f83bfbcaf57ad6bfffb1ab182617a0dfd1ecb0766e5723924ba361fbcaa6`; Alembic has the single head
`0053`.

Nine publication tests ran separately against isolated native-arm64 PostgreSQL 17 at revision
`0053`. They cover all-or-none release/content/receipt/changeset/outbox/idempotency commit, injected
pre-commit failure, same-key concurrency, different-changeset/same-snapshot concurrency, graph
classification ceiling, maker/checker and governed-lineage eligibility, exact activation receipt,
whitespace-only review denial, exact Neo4j shadow-receipt binding and zero partial state. A legacy
lineage-corruption regression proves that general Chat evidence and release-pinned Sharing
list/detail/version replay/publish/grant/invocation all fail closed. It also proves cross-actor
graph/changeset and cross-owner/resource Sharing idempotency replay fails closed and legacy grants
are hidden after lineage corruption. The first current rerun used an invalid `file://` secret
reference and failed before opening a database connection. Two later attempts stopped at
authentication because stale temporary/container secrets did not match the initialized audit
role. After synchronizing that dedicated role to its test secret, the corrected canonical `file:`
reference under explicitly approved local-loopback access passed `9/9`. The
isolated database also passed `0053 -> 0052 -> 0053` and finished at the sole head. Command/input
errors are recorded as execution evidence, not converted into product failures or hidden passes.

The optional semiconductor seed was applied, verified and removed against that same isolated
database. The first apply exposed an ORM flush-order foreign-key failure and rolled back; an
explicit changeset flush was added. The accepted rerun persisted a separate maker/checker and
authorized publisher,
536 immutable operations, canonical database read-back and the exact PostgreSQL deployment receipt
for `12` catalog assets, `257` nodes and `279` edges, then verified and removed the synthetic pack.
Deleting one operation and mutating one canonical node property without changing row counts each
made `verify` fail closed. Both cases then passed explicit remove/reapply/verify/remove recovery.

System Settings reranking tests execute one fixed `POST /v1/rerank` request and reject
401/404, duplicate/out-of-range or boolean indices and unsorted/non-finite scores. The private
contract additionally rejects scores outside `[0, 1]`; the Mac llama.cpp bridge explicitly accepts
finite raw classifier logits.
Migration `0053` extends only the TEST-scope vocabulary and refuses downgrade while such evidence
exists. The current Mac authenticated Neo4j query, strict-JSON Chat and Embedding inference passed;
Ollama's own reranking route remains absent. Mac development separately verifies the Ollama-owned
GGUF through the loopback-only `LOCAL_LLAMA_CPP` bridge, including a container-to-host probe and
ordered finite raw-logit validation. WSL/private
provider and runtime-consumer evidence remains external. Probe destinations are exact-allowlisted
before DNS and resolved addresses are checked, but the default HTTP transport can resolve the
hostname again at connection time. Address pinning while preserving original-host TLS verification
therefore remains an explicit security gate rather than a completed DNS-rebinding claim.
The final independent source audit found `P0=0`, `P1=0`. It carries one `P2` into the durable
source-job phase: the synchronous PDF path commits a pending source before eligibility and does not
pin/revalidate the prepared base release and ontology across inference.

The typed-BULK Phase 3.7 local implementation at `39d20d0` passed `1,297` backend tests with `51`
explicitly environment-gated integration cases skipped. The exact README Ruff command passed,
strict mypy passed over all `351` backend source/test files, and static
architecture/role/Compose/documentation verification passed. The frontend passed strict
TypeScript, zero-warning ESLint, `45` files / `238` tests and the production build. Canonical `0001`
generation was byte-identical across two runs at SHA-256
`5ba6583738b074d7ee2ed008a63d9a6e91aec75b59e8fe6e7f9ad12efc5c5694`; Alembic has the single head
`0052` at that historical Phase 3.7 boundary.

The five Phase 3.7 PostgreSQL tests were then enabled separately against an isolated native-arm64
PostgreSQL 17 database and passed both before and after `0052 -> 0051 -> 0052`. They prove valid V2
binding compatibility, V2/V3 drift denials, current classification/generation/Restricted grants,
same-key claim renewal, coarse non-locking evaluation, final publication locking against concurrent
membership/rule revocation, deterministic-denial lock release and zero denied receipt/row/candidate
evidence. `alembic check` reported no upgrade operations.

The maximum 10,000-row V3 parser regression passed with `tracemalloc` below 64 MiB. An independent
macOS `/usr/bin/time -l` run recorded 77,971,456 bytes maximum RSS and 64,733,736 bytes peak memory
footprint for that isolated pytest process. A separate full-worker boundary uses a parser-valid
16,159,007-byte CSV whose escaped JSON evidence exceeded the retired 32 MiB formula; the fixed
64 MiB attempt spool accepted all 1,600 rows. These are local regression measurements, not a WSL
soak or production capacity claim.

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

Historical execution evidence recorded on 2026-07-20 (it does not describe the current live
configuration path): the local seeded same-token revocation probe ran 100 iterations per scenario
against the direct API:
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
- System Settings inventory contains deployment-owned option names and redacted effective values;
  OpenAPI and HTTP negatives prove that database profile SAVE/version/draft-test/saved-test/ACTIVATE
  routes remain absent and new secret values never cross the browser API;
- connection tests accept only a known system identifier and the server's loaded Settings snapshot.
  Probe tests cover fixed paths, authentication-required status, unavailable targets, and blocked
  link-local/multicast/unspecified/reserved addresses;
- backend test Settings explicitly disable the optional local Ollama path unless a test is about
  that adapter. A developer `.env` must not change unit-test expectations.
- OIDC verifier tests prove that disabling WebAuthn refuses hardware assurance even for matching
  ACR/AMR/authentication-time claims; profile-menu tests remove enrollment and Workspace switching;
  high-risk authorization continues to fail closed rather than accepting password assurance;
- the stable API-client hook test proves a token/Workspace update retains client object identity
  while the next request receives the latest Authorization and Workspace headers. This guards the
  periodic token-renewal flicker regression without suppressing a real Workspace remount.
- authentication-race tests resolve profile requests out of order, unload/sign out during pending
  work, reject OIDC/server subject mismatch and prove an old renewal failure cannot clear a newer
  session. API tests prove Workspace/epoch drift discards late JSON/downloads and forbids a second
  fetch even for an idempotency-key mutation. Shell/Admin tests prove same-Workspace epoch teardown,
  authorization-revision reload and fail-closed manual refresh. Real IdP/browser behavior remains a
  target gate.
- Nginx header tests first prove the historical inheritance shadow: a child
  `add_header Cache-Control` removed every server security header. Source/static checks require one
  recursive merge rule, one exact `always` definition per canonical security field and exact API
  upstream hiding, while rejecting any extra hidden application header or inner-server HSTS. The
  offline native-container verifier then renders empty and sentinel origins and checks
  health/runtime/SPA, asset `200/304/404`, API `200/503` and proxy-down `502/504`. It also proves
  cache ownership, exact upstream ETag/Vary preservation and retry/auth/download/request-ID
  preservation, plus HSTS absence on direct-inner responses. WSL amd64, browsers and the real
  TLS/APISIX/HSTS edge remain separate acceptance gates.

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
- V3 catalog-metadata tests cover all five fixed record-kind/Aspect mappings, deterministic
  profile-bound CSV/XLSX row/group roots, non-contiguous ordered membership, group-operation caps,
  strict UUID/XOR/header/ZIP/XML rejection and server-versioned header-only templates. Publication
  tests require a current Airflow receipt/attempt/lease plus initiating-human/target-set
  reauthorization before the first evidence insert.
- Vocabulary tests cover DataHub kind/type/prefix/name/count/cursor validation, stable local UUID
  upsert, workspace/kind/lifecycle resolution, keyset cursor binding, idempotent page replay,
  incomplete/duplicate/cross-kind failure and deletion suppression unless a full frozen snapshot
  is independently verified. HTTP/UI negatives assert that provider URNs and arbitrary Aspects or
  documents are absent and that the browser replaces, rather than accumulates, 20-row pages.
- V3 apply tests parameterize `datasetProperties`, `schemaMetadata`, `domains`, `glossaryTerms`
  and `globalTags` for no-op, stale-before, ambiguous prior success, transient retry, read-back
  mismatch and success. The database authorization function binds the exact running job/attempt/
  worker lease and current human/target/binding; denial must occur before any provider call.
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

## Governed Quality execution gates

Phase 0 establishes requirements only. Phase 1 and later cannot claim completion until the
applicable evidence below exists.

- Domain/compiler tests cover all Rule/version/run/attempt transitions, terminal immutability,
  execution-state versus quality-outcome separation, `NOT_NULL` and typed `RANGE` exact semantics,
  severity outcome, activation denial for an empty Version, `SUCCEEDED` only with exactly one
  sanitized result per Rule Definition, aggregate zero-denominator UNKNOWN and deterministic
  `UNWEIGHTED_RULE_PASS_RATE_V1`. `REGEX` remains unavailable until its bounded-execution engine
  proof and positive/negative grammar set pass.
- Compiler/API schema tests prove there is no arbitrary expectation name/kwargs, suite/checkpoint
  JSON/YAML, BatchRequest, datasource/URL, external identifier, SQL, GraphQL, Python/import/plugin,
  row condition or runtime-result-format input. Unsupported/unknown fields fail before job creation.
- Rule-command tests cover current target binding, immutable version creation, one ACTIVE version,
  author/reviewer separation, service-account rejection, recent hardware WebAuthn,
  `If-Match`, same/different-body idempotency, fixed transition-function-only lifecycle updates,
  atomic prior-version/schedule supersession, revoke deny-first, logical archive and no physical
  delete. A route-to-Action matrix includes archive, cancel, operations/audit and both service
  boundaries; an unspecified or wrong Action is denied.
- Actual PostgreSQL 17 tests cover blank-to-head, prior-head additive upgrade, canonical re-entry,
  exact metadata equivalence, partial/same-name-definition drift fail-closed, RLS no-context/wrong
  workspace/correct scope, composite tenant foreign keys, app UPDATE/DELETE denial, NOBYPASSRLS
  worker/collector scope, evidence-bearing downgrade refusal and `alembic check`. Phase 1 Quality
  and Phase 2 Catalog Profile revisions are separately additive. Partial ACTIVE-version,
  due-schedule, runnable/reclaimable Run, terminal-dashboard and latest-profile indexes must serve
  representative keyset/claim plans in `EXPLAIN (ANALYZE, BUFFERS)`.
- Run tests prove enqueue/outbox/audit/idempotency atomicity, scheduled-window uniqueness,
  database-time claim, stored current-attempt/lease-owner/expiry/source-start/access-deadline
  fences, monotonic
  lease epoch/token hash, expired-attempt supersession, exact-worker completion, duplicate delivery,
  cancel/complete and retry/reclaim races, crash before/during/after source access and one canonical
  result. Source tests enforce complete GX source-access hard timeout plus
  cancel/reconciliation/completion margins inside the frozen lease, prohibit renewal until source
  transaction/connection close, recheck epoch/token before every statement and bound each
  source-server `statement_timeout` by the remaining source-access deadline/lease. They prove a
  newer epoch cannot overlap any expired worker statement or source connection. Retry creates a
  `retry_of_run_id` successor after current reauthorization and never reopens the terminal
  predecessor. Expectation violations complete the execution without becoming infrastructure
  `FAILED`.
- State-machine tests cover the closed attempt vocabulary and every permitted Run/current-attempt
  pair, including queued cancellation without an attempt, in-flight cancellation,
  retry-wait cancellation and non-current SUPERSEDED history. Only a SUCCEEDED current attempt may
  own canonical expectation results.
- Dispatch tests cover authenticated no-work, one-Run and multi-Run calls, exact replay,
  different-body call-ID conflict and one-transaction due-lock → scheduled-window unique Run/outbox
  → next-due advance → receipt semantics. A call cannot exceed the receipt-pinned approved
  max-due/max-created bounds or source hard maxima, and processes only a deterministic keyset.
  Execution-call replay remains separately bound to one current Run/attempt/lease.
- Sanitizer adversarial fixtures inject raw rows/values/indexes, rendered SQL, queries, credential
  strings, private endpoints and provider exceptions. None may reach PostgreSQL, API, cursor/cache,
  outbox/delivery, log, trace or metric. Unknown shape/sanitizer failure produces only a bounded
  failure code and no raw evidence. Numeric fixtures reject negative/overflow counts,
  boolean-as-integer, NaN/Infinity, proportions outside `0..1`, percentages outside `0..100`,
  count/ratio inconsistency, duration overflow and oversized/unknown failure codes.
- DataHub v1.6 contract tests use a separate fixed profile query containing profile/partition
  provenance, including `partitionSpec { type partition }` and excluding nonexistent
  `profileType`. Fixtures map FULL_TABLE/canonical marker to FULL, QUERY/exact SAMPLE marker or its
  sample-row suffix form to SAMPLE, valid PARTITION to PARTITION, other valid QUERY to QUERY and
  missing/unsupported/ambiguous input to UNKNOWN. They also cover empty/missing fields, ordering,
  response oversize, 401/403/429/5xx and schema/version drift. A bounded raw partition is accepted
  only at fixed parser ingress,
  normalized before DTO construction and then discarded. PARTITION/QUERY may retain only the
  deployment-keyed HMAC/key ID; raw text and unkeyed digests are absent downstream.
  SAMPLE/ambiguous provenance is never promoted to FULL, and an eight-MiB overflow is explicit
  PARTIAL/UNAVAILABLE rather than silent truncation.
- Profile projection tests prove the deterministic asset/profiled-time/kind/provider/source/
  normalized-payload/keyed-provenance identity: identical re-observation advances only
  `last_observed_at`, changed metrics create a new immutable snapshot, and HMAC key rotation creates
  a new explicit provenance lineage without exposing the raw partition.
- The PostgreSQL DataHub recipe first passes the pinned v1.6 configuration validator. Field
  profiling explicitly disables sample values, distinct frequencies, histogram, quantiles and
  every unapproved statistic; it explicitly bounds workers/field scope rather than inheriting the
  `5 * CPU` worker or sample-value defaults. The retained target run report records selected,
  dropped and failed profiles without credentials.
- Profile privacy tests prove `sampleValues`, `distinctValueFrequencies`, top values and example
  rows are absent from GraphQL requests. Raw partition text is present only in the bounded fixed
  adapter response ingress and absent from DTO/projection/cache/API/UI/log/trace/error; only an
  allowlisted keyed HMAC/key ID may remain for PARTITION/QUERY identity.
  Min/max/mean/median/stdev/quantile/histogram remain unavailable without the approved
  classification/data-type policy and workload evidence.
- Source tests use a dedicated PostgreSQL read-only role and approved base relations. They prove
  write/DDL/arbitrary-query denial, transaction read-only mode, server-owned identifier quoting,
  statement/lock/execution timeout, cancellation, pool/concurrency/scan budget and exact
  manifest/secret/egress enforcement. Missing budget, secret or source binding makes the
  capability unavailable before a source call.
- Airflow image/config/secret inventory proves it contains no GX/source/DataHub/object credential.
  OIDC issuer/audience/client/group/Action, stable run/call ordinal, replay and workspace/run
  mismatch negatives are mandatory. PostgreSQL owns due-window/missed-window/catch-up reconciliation
  under an approved cap, so scheduler downtime does not silently discard canonical intent.
- Schedule tests cover closed FIXED_INTERVAL/DAILY_LOCAL_TIME grammars, invalid IANA zones,
  ambiguous-time EARLIER/LATER offsets, nonexistent-time SKIP/SHIFT_FORWARD, evaluator/tzdb
  version/hash drift and canonical UTC window-key replay. With a receipt-pinned DB-time cutoff they
  prove exact `SKIP_MISSED_V1`, newest-only `LATEST_ONLY_V1` and bounded deterministic
  `(due_at, schedule_id, window_key)` `CATCH_UP_OLDEST_FIRST_V1` behavior, late-grace boundaries,
  skipped-range hashes, cursor advancement and outage recovery. Schedule payload/history is
  immutable per Rule Set Version, only fixed functions advance its cursor/state, and activation
  atomically enforces one ACTIVE schedule per Rule Set.
- Credential/role inventory proves the fixed API DataHub adapter or dedicated
  `catalog-profile-collector` alone can read DataHub; the collector has
  `catalog.profile.collect` and one fixed Catalog projection function but no source credential or
  Quality write grant. Airflow and quality worker have no DataHub token.
- Dashboard/list/count/facet/trend tests use one authorization-pruned asset relation and cover no/
  invalid token, inactive/expired membership, cross-workspace ID, clearance/System/Domain,
  explicit deny, policy drift/outage, hidden resource `404`, hidden count/bucket/delta leakage and
  stale cursor/cache scope. The current snapshot considers only Runs bound to the current ACTIVE
  Rule Set Version, so newly activated Versions cannot inherit a superseded Version's success. A
  latest same-Version FAILED/STALE/CANCELLED Run makes the Rule Set UNKNOWN and cannot be hidden by
  an older same-Version `SUCCEEDED`; Rule Set unknown/coverage counts and Rule Definition evaluated
  counts cannot be mixed. Without an approved small-cell
  policy, classification/System/Domain cohort buckets and distributions are absent. All values are
  visibly permission-scoped.
- Frontend tests cover read denial with zero follow-up calls, independent profile/worker/source/
  scheduling dependency outages that preserve authorized history, loading/background-refresh/
  empty/error/forbidden/partial/stale/unknown, `SUCCEEDED != PASS`, integer basis-point
  `ROUND_HALF_UP` scoring, cursor/page maximum 100, trend maximum 90, typed asset lookup and Rule
  errors/status/ETag/idempotency conflicts, normalized sort/filter query keys and allowlisted URL
  state. Authorization lease tests hide/purge at no more than 30 seconds, abort late responses and
  revalidate before redisplay. Polling tests count the initial immediate read, pause both elapsed
  time and reads while hidden, resume within the remaining 20-read/visible-active-120-second cap,
  and bound `Retry-After`. Semantic tests plus table caption/headers/keyboard row actions,
  reduced-motion, non-repeating live-region, target screen-reader/200%-zoom/320-CSS-pixel manual
  checks are required.
- User-centric Quality tests additionally prove Catalog Search uses one permission-bound summary
  batch for the visible IDs and renders the same score/status in the result row and Evidence panel;
  no per-row request is allowed. The two-tab Quality workspace proves one selected asset combines
  Rule Sets, recent Runs and score trend while Issue/review controls are absent. Common Rule tests
  cover closed typed creation, exact field/type compatibility, schema/table search, 25-target
  maximum, duplicate rejection, atomic mapping/idempotent replay and authorization-pruned mapping
  counts/details.
- Revision `0074` tests require forced RLS, composite tenant foreign keys, no update/delete app
  grant, unique Template/asset and Rule Set mappings, blank-to-head and `0073 -> 0074` upgrade,
  metadata equivalence and deterministic canonical `0001` regeneration.
- Representative narrow, wide and large PostgreSQL tables provide source query plans and CPU/IO/
  latency/lock-wait/replica-lag, cancellation, worker concurrency and 60-minute soak evidence.
  Dashboard SQL records `EXPLAIN (ANALYZE, BUFFERS)` and response/p95 measurements. Capacity-owner
  limits are deployment inputs, not portable source defaults.
- Release acceptance requires exact GX 1.19.1/compiler/driver/lock/SBOM fingerprints, zero
  unresolved Critical/High findings, Mac arm64 and WSL amd64 offline-artifact parity, actual
  DataHub v1.6 profile evidence, actual Airflow-to-DataRiver dispatch, actual read-only PostgreSQL
  GX execution, revocation-before-query and crash/reclaim evidence. Unit/source passes do not open
  those target gates.
- Retention tests prove Phase 1 pins `QUALITY_RULE/QUALITY_RESULT/QUALITY_AUDIT` policy
  ID/version/hash/deadline and RuleSet/Run hold target generation/hash, while Phase 2 separately
  pins `QUALITY_PROFILE` and ProfileSnapshot holds. A no-work dispatch receipt independently pins
  workspace-scoped QUALITY_AUDIT policy/deadline/hold resolution; child rows inherit exact root
  bindings through composite FKs. Creation, claim and completion reject missing, ambiguous or
  drifted bindings. A membership/Action/classification/System/Domain/lifecycle/active
  version/source-connection/workload-profile/retention change after source access but before
  completion produces STALE/UNKNOWN and zero canonical result. Negatives also prove no
  app/Airflow/worker TTL, DELETE, TRUNCATE, object lifecycle or partition detach/drop exists for
  Quality evidence.

## Governance Document execution gates

- Domain/service tests cover the three sanitized starter blueprints, HTML sanitizer idempotency and
  adversarial XSS corpus, Markdown/DOCX conversion bounds, logical Archive, one live candidate,
  maker-checker publication, stale `If-Match`, actor-bound idempotency and human-only APIs.
- PostgreSQL 17 applies canonical `0001` and additive `0071 -> 0072`, reports no Alembic metadata
  diff, installs both deferred circular/template foreign keys and forced RLS on all eight tables,
  and proves wrong/no Workspace reads and direct UPDATE/DELETE fail closed.
- Role probes prove `datariver_governance_document` is NOBYPASSRLS with no unsafe membership, no
  document DELETE, no publication/content update columns and only the exact projection
  table/column grants.
- Object-store tests prove UUID-only keys, `If-None-Match: *`, exact VersionId/checksum/metadata
  read-back, identical collision adoption, changed collision rejection, versioning enabled and
  delete/list denial for the dedicated identity. No WORM/Object Lock claim is made without a
  separately approved storage profile.
- Projection tests cover artifact-before-vector ordering, published-version-only projection,
  deterministic bounded chunking, exact embedding binding/dimension, fixed parameterized Neo4j
  statements, verified graph hash, immutable relational receipts, retry/lease behavior and no raw
  provider error persistence.
- Evidence API tests prove authorization occurs before external embedding, the query uses the same
  provider/model binding as stored chunks, only active current published authorized documents are
  ranked, and callers cannot supply raw vectors/provider/model/Cypher/SQL.
- Revision `0075` tests additionally prove exact pgvector SQL ordering after all authorization
  predicates, vector/JSON dimension equality, exact provider VersionId signing, declared
  Dataset/Term projection, POST RAG parity and Chat refusal after active-version drift.
- Frontend tests cover capability-first zero-follow-up denial, cursor/cache scope, ETag and
  idempotency commands, list/detail/history/review/Archive/attachment/import states, controlled
  blueprint loading and the DOM-to-React viewer with no raw HTML insertion. TypeScript, ESLint,
  Vitest and production build are release gates.
- Revision `0079` tests cover deterministic legacy attachment numbering, the 1–25 serial bound,
  readable server-derived body/reference basenames, exact receipt signing, same-Workspace
  permission-pruned parent/child links, self/cycle rejection and DB-level parent immutability.
  Canonical `0001` must contain the same trigger and be byte-identical across two generations.
- Browser acceptance uses distinct author and reviewer identities: create or import a managed
  document, add an editor-bottom reference, submit, independently approve, observe it in
  **문서 조회**, download the authorized export and verify that the export contains no MinIO
  address/key/VersionId/credential/Presigned URL. The three controlled starter documents are
  ordinary records and must each traverse the same workflow before they appear in the viewer.
- Representative vector dimension, exact-search latency/recall, future ANN sizing, Neo4j projection,
  MinIO throughput, worker crash/reclaim, multi-Workspace leakage, WSL amd64 and accessibility are
  target acceptance gates. Exact pgvector search is not a production SLO claim.

### Knowledge Asset lifecycle and delivery acceptance

- Revision `0080` and canonical `0001` must agree on the `knowledge.delivery_policies`
  constraints, composite Workspace foreign keys, forced RLS, index and least-privilege grants.
  Canonical generation is executed twice and the SHA-256 must remain identical.
- Registry tests cover permission-pruned cursor pagination, server-side ordering, focused historical
  Release metadata, bounded graph preview failure, real A-Box bindings and projection status.
- Information Management tests cover direct typed A-Box UPSERT/DELETE changesets, exact
  classification mapping, stable retry idempotency, property-profile deep links and delivery-policy
  ETag handling.
- Delivery-policy tests cover Unicode normalization, ANY/ALL/excluded conflicts, optimistic
  concurrency, exact lost-response replay, concurrent-create serialization and ambiguous Chat route
  refusal.
- Governed Chat tests prove the selected graph/release/policy ID, version and hash are persisted,
  retrieval is constrained to that immutable Release, and policy/release revocation between
  retrieval and final citation validation fails closed without citations.
- Browser acceptance verifies the existing Shell stays mounted, 조회 및 생성 and 정보 관리 switch
  without a full reload, a Registry detail drawer focuses Release metadata, and API & Chat policy
  feedback survives a successful save. External provider, large ingestion and preparation-PC
  performance claims remain separate target-environment gates.

On 2026-07-31, the revision `0080` source gate passed Ruff format/lint, strict mypy over
`529` source files, `scripts/verify_static.py`, `2024` backend tests with `104` explicitly
environment-gated skips, and the deterministic canonical migration check with an unchanged SHA-256
across two generations. The frontend passed strict TypeScript, zero-warning ESLint, `390` tests in
`73` files and the Vite production build. Live PostgreSQL migration, authenticated browser and
preparation-PC checks remain runtime gates until the committed revision is applied.

### Governed Studio database ingestion acceptance

- Revision `0081` and canonical `0001` must contain the same five-table execution aggregate,
  reciprocal result provenance, exact function signatures, forced RLS, immutable evidence triggers
  and least-privilege grants. Canonical generation runs twice with an identical SHA-256.
- Migration tests provision the dedicated safe NOBYPASSRLS login before applying `0081`, reject
  unreconciled legacy jobs and prove the application and worker roles cannot call one another's
  functions or directly mutate evidence.
- Source-manifest/adapter tests cover exact Asset/version/profile/workload hashes, safe absolute
  secret roots, regular-file credentials, exact IP/TLS/quoted identifiers, read-only
  `REPEATABLE READ`, keyset batches and row/byte/statement/deadline bounds.
- Service/API tests reject mutable Drafts, missing released Bindings, manifest drift and absent
  embedding activation; OpenAPI proves ETag/idempotency on request/cancel/retry and redacts lease,
  authorization and source-coordinate evidence.
- Worker/database tests cover claim/reclaim, lease token/epoch/fingerprint fencing, cancellation,
  retry exhaustion, requester authorization/release drift, contiguous typed operation scope,
  vector-receipt set completeness and atomic DRAFT Changeset success with no Release/Neo4j write.
- Frontend tests cover PUBLISHED-only start, all eight states, visibility-bounded polling,
  in-flight duplicate suppression, ETag/idempotent cancel/retry and SPA navigation to the result.
- Runtime acceptance enables the explicit worker profile only after the manifest, source secrets,
  service Subject, database role and retention binding are provisioned. It applies the migration,
  verifies API/Web/worker health, runs one bounded authorized source through `SUCCESS`, opens the
  returned DRAFT Changeset and proves a revoked requester becomes `STALE` with no result.

## Core correctness scenarios

- State machine rejects every undeclared transition and stale aggregate version.
- Requester cannot final-approve; required multi-approval actors are distinct.
- `APPLY_QUEUED` and outbox insert are one transaction.
- Duplicate event and duplicate idempotency key produce one business effect.
- DataHub failure/mismatch never produces `APPLIED`; reconcile retry can recover.
- Catalog writes cannot bypass governance.
- Every graph publish assertion has provenance and passes ontology/reference checks.
- Release content is immutable; same release rebuild has identical hash/count and golden-query output.
- Grounded Chat citations are a non-empty, duplicate-free subset of the exact currently authorized immutable chunks; workspace/chunk/content hash is revalidated and invalid output becomes `검증 불가` with no persisted citation. A general-knowledge answer is tested only after successful zero-evidence retrieval, receives no internal candidate data, rejects any citation, carries the visible no-internal-evidence disclosure and persists zero citations. Provider, policy, authorization, retrieval, reranker and citation failures cannot trigger that path. Future model inference additionally requires the ADR-0019 grounding verdict and its longer governed refusal text.

## Authorization matrix

For each route, test no token, invalid issuer/audience/algorithm, inactive subject, missing workspace membership, workspace mismatch, insufficient clearance/system/domain, lifecycle restriction, positive allow, explicit deny, policy-service outage, changed policy with stale cache and protected-field redaction. List, facet, suggestion, count, download, export and SSE receive the same coverage as detail endpoints.

## Failure injection

| Fault | Pass condition |
|---|---|
| DataHub unavailable/rate-limited/contract drift | bounded stale or classified 503; durable pending work; no false complete; fixed-label request/circuit metrics |
| DataHub concurrency saturated | bounded queue timeout and classified `OVERLOADED`; bulkhead rejection metric increments |
| cache unavailable/evicted | correct uncached response, no secret leakage |
| API container replaced | Nginx/APISIX re-resolve service DNS; no dependent restart or persistent 502 |
| child Nginx location adds a cache header | all five canonical browser-security headers remain exactly once on success and error |
| API upstream sends conflicting browser-security fields | web edge removes only those fields, supplies canonical values and preserves cache/auth/retry/trace/download headers |
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
