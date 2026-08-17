# DEV PHASE 1D bounded Table enforcement slice evidence

## Identity and scope

- Fresh observation: `2026-08-17T12:38:32+09:00` (`Asia/Seoul`)
- Pre-slice Evidence HEAD: `d0dbe9b19dea9248fc57987dde9c08035e1a97fd`
- Table-enforcement implementation commit: `805fe1279f38066c57e054b7720295b9495d9b55`
- Packaging correction/current Product SHA: `2f247107d28716aeba3cfe3fa201fb040ac437e3`
- Deployed OCI revision: `2f247107d28716aeba3cfe3fa201fb040ac437e3`
- Runtime: authoritative Node POC, `datariver-poc-web-1`, canonical DEV origin
  `http://127.0.0.1:39083`, healthy
- Authoritative worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Git/release: no push, merge, publication, G1/G2/G3/G4, PREP/OPS mutation, migration,
  schema change, legacy deletion or broad refactor

This evidence covers one bounded PHASE 1D Product slice: request-time Table decisions and the
covered Catalog/Search/Tree/Detail/count/dashboard/profile/vector/Chat/lineage/mutation paths. It
does not close overall PHASE 1D, provider-wide graph traversal, unbound Knowledge/Governance
documents, deleted/current-missing grade policy, Quality/GX runtime, PHASE 1E/1F or any target
environment.

## Canonical status boundary

- Bounded Table-enforcement slice source: `VERIFIED`
- Bounded Table-enforcement slice DEV runtime: `PARTIAL_RUNTIME_VERIFIED`
- Bounded Table-enforcement slice canonical status: `PARTIAL`
- PHASE 1D overall: `PARTIAL`
- Overall Account/Auth program: `PARTIAL`

The slice is intentionally not `COMPLETE_RUNTIME_VERIFIED`. Canonical grant/no-grant, policy,
Admin, hiding, count, direct lineage, non-Admin Neo4j fail-closed, exact AUTO inventory and
mutation-negative behavior passed. External LLM/embedding/reranker endpoints were unavailable,
and every current canonical Table had grade `normal`; therefore external semantic-vector/AUTO and
negative higher-grade runtime PASS are not claimed.

## Implemented request-time decision

The Product adds no capability, table, dependency, service, provider framework, generic IAM/ACL
engine or graph-policy framework. Capabilities remain exactly 15. The fixed policy remains the
bounded 8-feature × 5-role × 3-grade matrix.

For each authenticated request, `frontend/poc-server.mjs` reads the current access document,
active exact User↔Table grants and the current fixed feature-security policy once, then
`frontend/poc-authorization.mjs` hydrates grant and allowed-policy `Set` values on the principal.
There is no session permission snapshot and no per-Table grant/policy/provider query loop.

The non-Admin Table decision is:

```text
authenticated current principal
AND current canonical TABLE identity
AND active exact Table grant
AND user max grade >= current canonical Table grade
AND allowed fixed feature-role-grade cell
```

Admin bypasses these application data restrictions only after a valid canonical data identity is
present. TABLE-only mutations still reject non-TABLE input, and malformed input, stale CAS,
Origin/CSRF and schema/data-integrity checks are unchanged.

Responsible System is not part of this general-read decision. It remains workflow/business scope
for Change Requests, Registration, Knowledge and Quality responsibilities. Source and mock-provider
tests prove that assigning two Tables to the same System does not expose an ungranted Table.

## Covered read, ranking and mutation paths

- Catalog/Search/Tree/Detail/autocomplete/facets/counts/dashboard filter the normalized local
  inventory before matching, sorting, paging and aggregation.
- Profile coverage uses the `quality` feature policy. Vector-index and glossary raw/global totals
  are hidden from non-Admin principals.
- Direct unauthorized Detail identities are 404. Unauthorized Table mutations are 403 with no
  provider mutation.
- Direct DataHub lineage authorizes the center before provider traversal and filters every returned
  neighbor. Raw provider truncation/count metadata is not exposed to non-Admin callers.
- PostgreSQL vector search places exact authorized URNs in `WHERE ... asset_urn = ANY($7::text[])`
  before vector `ORDER BY`; memory search filters authorized candidates before cosine and sort.
  Empty non-Admin grant scope returns before inventory, embedding or provider query.
- AUTO exact resolution, inventory, semantic candidates, reranking input, context and citations use
  the Chat feature scope. Detail hydration rechecks current authorization before evidence is kept.
- General Chat does not require a Table grant. Non-Admin direct Neo4j evidence returns empty because
  canonical DataHub Table provenance is not proven; full traversal followed by hiding is not used.

## Source, build and packaging gates

| Gate | Result at final Product |
|---|---|
| Node POC full suite | PASS — 97/97 |
| Catalog performance/reconciliation | PASS — 5/5 |
| Frontend full suite | PASS — 87 files, 592/592 on final clean rerun |
| Lint | PASS |
| Typecheck | PASS |
| Production build | PASS; existing `>500 kB` advisory only |
| Compose `config --no-interpolate --quiet` | PASS |
| `git diff --check` | PASS |
| protected auth weakening / secret-hardcoding scan | PASS |
| exact Docker build and packaged module syntax | PASS |

The first Product commit did not copy the new authorization module into the production image.
This was found before deployment and fixed in the separate packaging commit `2f247107...`.
Compose then rebuilt and recreated only the Web service with pulling disabled; PostgreSQL, Redis,
Neo4j and Airflow were not recreated. The final image label and deployed revision equal the
Product SHA.

Tests cover exact grant/no grant, grade order, fixed policy, Admin data bypass plus integrity
validation, Responsible System having no general-read effect, Detail 404, count/facet/tree/dashboard
leakage, PostgreSQL and memory pre-ranking, empty-scope short circuit, AUTO authorized inventory,
citations, immediate grant/grade/policy changes and non-Admin Neo4j fail-closed behavior.

## Canonical DEV runtime matrix

Disposable DEV principals used random in-memory credentials. No password, cookie, token, subject
identifier, Table identity or provider endpoint is recorded here.

| Behavior | Result |
|---|---|
| Admin application-wide catalog access without a Table grant | PASS — restored total 2,002 |
| Non-Admin without a grant | PASS — catalog total 0; direct Detail 404 |
| One exact grant | PASS — catalog total 1; granted Detail 200; ungranted Detail 404 |
| Facet/tree/dashboard counts | PASS — computed from the one authorized Table |
| Profile/vector-index/glossary global metadata | PASS — feature policy applied; global projection facts hidden |
| Fixed Catalog policy change | PASS — deny observed immediately as 0/404; restore observed immediately |
| Fixed Chat policy change | PASS — deny observed immediately as authorized inventory 0 |
| User maximum-grade change | PASS for current positive path — `normal → credential → restricted` observed immediately |
| Grant removal | PASS — Catalog and Chat authorized inventory became 0 immediately |
| Exact AUTO catalog inventory/citation | PASS — only authorized evidence and citations were emitted |
| Direct DataHub lineage | PASS — authorized center only; no ungranted neighbor/edge |
| Non-Admin Neo4j | PASS for fail-closed contract — empty nodes/edges |
| Unauthorized manual metadata mutation | PASS — 403 `TABLE_DATA_FORBIDDEN`; provider not called |

All 1,002 current canonical Tables in the observed 2,002-asset inventory were grade `normal`
(502 distinct Table names). A negative `credential`/`restricted` canonical runtime target therefore
does not exist. The mock-provider tests cover insufficient-grade denial without fabricating or
mutating provider data.

Chat, embedding and reranker reachability each returned `NETWORK_ECONNREFUSED`. The exact AUTO
inventory path above is deterministic and passed, but semantic vector retrieval, external AUTO
classification/composition and reranking are not canonical runtime PASS. Provider-unavailable is
kept distinct from an empty authorized scope.

## Fresh independent Validator

- Orca Run: `run_d05f117889c1`
- Task: `task_6e25cb340319`
- Dispatch: `ctx_bce49334343a`
- Effective model: Gemini 3.1 Pro High
- Mode: independent read-only; files modified: none; DB/runtime/container mutation: none
- Validator start identity: `pwd` and Git root both the authoritative worktree above; branch
  `Ever-Real/dev-core-t04-validation`; HEAD/Product and deployed OCI revision both
  `2f247107d28716aeba3cfe3fa201fb040ac437e3`; worktree clean
- Authoritative runtime explicitly identified as Node POC, not legacy FastAPI
- Independent commands: `npm run test:poc-server` and
  `node --test poc-catalog-performance.test.mjs` both PASS

The Validator independently accepted the request-time grant/grade/policy boundary, Admin
data-versus-integrity distinction, 404/count protection, no-N+1 hydration, vector pre-ranking,
empty-scope short circuit and immediate policy changes. It explicitly rejected an overall PHASE 1D
completion claim because of the external provider and canonical grade-sample limits.

## Cleanup and preserved state

- Four PHASE 1D disposable accounts remain as disabled historical DEV rows: active 0,
  login-enabled 0, active sessions 0, active Table grants 0, active System assignments 0.
- Global active User↔Table validation grants were removed.
- Feature policy was restored to the reviewed matrix: version 16, 120 cells, 50 allowed cells,
  reason `Restore reviewed DEV feature security policy`.
- MCL ledger/checkpoint/CR-link/source invariants remain `46 / 2 / 4 / 2`.
- The inspection `admin` account is active, login-enabled, role `admin`, maximum grade
  `restricted`, failed attempts 0, not locked, with one active session, no active Table grant and
  no Responsible System assignment. It was not reset, disabled, deleted or session-revoked.
- Inspection Admin status remains `SERVER_VERIFIED`, `BROWSER_FLOW_VERIFIED`,
  `USER_CONFIRMATION_PENDING`. No browser diagnosis or credential issuance was repeated.

## Remaining PHASE 1D risks

- Neo4j lacks proven canonical DataHub Table URN provenance. Non-Admin graph evidence remains
  fail-closed until a bounded pre-traversal identity contract exists.
- DataHub lineage/glossary provider APIs cannot prefilter every traversal or provider total. The
  covered code authorizes centers and filters outputs, but provider-wide completion is not claimed.
- Deleted/current-missing Tables have no authoritative current grade and fail closed for non-Admin.
  `VIEW` and `MATERIALIZED_VIEW` are not grantable TABLE identities under this policy.
- Table-bound coarse state can be projected or guarded; unbound Knowledge/Governance documents are
  not treated as Table ACL resources.
- Quality/GX runtime remains externally incomplete. Authorization seams are not a Quality runtime
  PASS.

No PHASE 1E/1F, GX, migration implementation, legacy deletion or publication follows automatically
from this slice.
