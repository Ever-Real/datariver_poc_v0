# DEV 메뉴 구조·Registration 역할 경계 및 Knowledge K0 Evidence

Date: 2026-08-18 KST

## Lineage and authority

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Previous Product/Evidence baseline:
  `fd379567a220f1e677deb5225b8e0b36c1d28d8d` /
  `c1d9d3fa437dc146f1d903e6fee28f809e03eb0f`
- Menu/Registration Product:
  `536c02f61476a35ad653cac041a3d8b76cbdf5a1`
- Deployed image and running Web OCI revision:
  `536c02f61476a35ad653cac041a3d8b76cbdf5a1`
- Authoritative runtime: Node POC at `http://127.0.0.1:39083`
- Push, G1/G2 publication, PREP/OPS mutation and G3/G4 were not performed.

## Closed Product slice

The primary Product menu now uses one exact source order:

1. Admin — 접근관리
2. 검색
3. 변경관리
4. 모니터링
5. 등록관리
6. 거버넌스 — 정책·표준 문서 관리
7. Chat
8. 지식관리
9. 품질관리

The existing routes and deep links were retained. Change Management, Monitoring and Registration
remain separate top-level routes. Admin is still hidden without Admin authority.

Registration mutation is now limited to `data_steward` and `admin` at the primary navigation,
direct page guard, server route authorization and local POC adapter. Manager keeps its existing
Catalog capabilities but cannot use Registration routes or pages. Non-Admin Registration Table
access continues to require this exact request-time conjunction:

```text
current canonical TABLE
AND active exact Table grant
AND user grade >= current Table grade
AND fixed Registration × Role × Grade Allow
AND current Table.systems ∩ current User.responsible_systems != empty
```

Admin bypasses the data-authorization restrictions only after valid canonical TABLE and grade
identity checks. Input, unsupported operation, stale-CAS, Origin and CSRF integrity checks remain.
Exactly 15 central capabilities remain; no Registration capability or new policy layer was added.

Existing persisted policy data created under the superseded Manager Registration rule is read with
one narrow compatibility projection: only `registration + manager + allow` is treated as Deny.
Ordinary normalization and policy updates remain strict, and other role-ineligible Allows still
fail closed.

Changed Product files: 15 existing frontend/Node POC files. No database schema, dependency,
service, container, route family or capability was added.

## Runtime acceptance and cleanup

The exact deployed Product passed the following coordinator-owned, memory-only runtime matrix:

- Manager login 200, Registration bulk-list 403, Catalog 200.
- Data Steward login 200, the same Registration bulk-list 200.
- Both disposable credentials were disabled, users inactivated and sessions reduced to zero.
- The inspection `admin` was preserved. It remains active, login-enabled, role `admin`, maximum
  grade `restricted`, failed attempts 0 and not locked.
- Current sessions after cleanup: validation/test 0, inspection admin 1, other 0.
- Current active Table grants: 0.
- MCL source/checkpoint/ledger/CR-link: `2/2/66/4`.

The actual Admin browser showed the exact nine-item menu order. Change Management, Monitoring and
Registration navigated to independent query routes, and Registration hard reload preserved its
route and page heading. No inspection Admin credential was read, reset, output or revoked.

## Source and test evidence

| Gate | Result |
|---|---|
| Focused menu/authorization/policy/adapter tests | PASS |
| Node POC full suite | PASS — 107/107 |
| Frontend full suite | PASS — 87 files, 599/599 |
| ESLint | PASS |
| TypeScript | PASS |
| Production POC build | PASS |
| Compose no-interpolate render | PASS |
| Secret/security/hardcoding scan | PASS |
| `git diff --check` | PASS |
| Image label = running OCI = Product SHA | PASS |

The existing Vite chunk-size warning remains a technical backlog item and is not a new regression.

## Fresh independent validator

A fresh read-only Gemini 3.1 Pro High validator recorded the authoritative worktree, branch, exact
Product SHA, running OCI revision and Node POC authority. It confirmed exact Product/OCI equality,
reviewed the menu, route, Registration role/policy boundaries and current Knowledge/MCP state, and
made no Product, Git, database, runtime, container, credential or session mutation.

Its first default two-worker frontend run produced 595/599 with three asynchronous POC navigation
wait failures and one explicit five-second Lineage timeout. That run was rejected rather than
reported as PASS. The coordinator reran exactly those two files with one worker and obtained 26/26;
the independent validator then reran the complete frontend suite with one worker and obtained
87/87 files and 599/599 tests. Only the clean final run is completion evidence. The current dirty
Markdown files were coordinator-owned Evidence drafts created after the validator's initial clean
preflight; validator files modified remain 0.

## Knowledge K0 — Existing Design

Canonical documents describe PostgreSQL/canonical storage as Knowledge authoring authority and
Neo4j as a rebuildable projection. They also contain a much richer historical Python implementation
with typed assets, changesets, releases and provenance. That legacy source is a reusable design
input only; it is not current Node POC runtime evidence.

The current Product already depends on TanStack Table, XYFlow and Tailwind, so a future Registry and
bounded visual T-Box builder can reuse existing dependencies. No new frontend framework is needed.

## Knowledge K0 — Existing Implementation

- Primary Knowledge routing retains `knowledge`, `knowledge-chat`, `knowledge-instances`,
  `knowledge-profiles` and `knowledge-studio` deep links.
- The current Knowledge workspace still renders three labels: `조회 및 생성`, `정보 관리`,
  `Chat Test`. It does not yet meet the requested final two-item left menu.
- `KnowledgeRegistry` contains a table, drawer, version/archive and create/edit/source UI.
- Knowledge Studio contains the three Basic/T-Box/A-Box-oriented steps and extensive component
  tests.
- The local Node POC adapter stores coarse `knowledgeDomains`, `knowledgeDrafts`,
  `knowledgeReleases`, blocks and bindings inside the global `core` JSON state. It supports local
  draft/publish projections and still defaults to the older `INTERNAL` classification vocabulary.
- The local release projection reports empty node/edge counts; it does not perform a verified
  Knowledge Neo4j projection.
- Knowledge Chat UI calls a release-pinned `graphrag` path, but the authoritative Node gateway has
  no matching current route/handler. Its component tests mock the response.
- The only current Node Neo4j gateway is the bounded read endpoint
  `/poc-api/neo4j/graph`; no Knowledge graph mutation route is registered.
- No current Node MCP route, server, adapter or test exists. The master backlog keeps MCP R4-13
  `PENDING`, and the API specification treats unlisted MCP surfaces as backlog.

## Knowledge K0 — Runtime Verified

Read-only runtime state at the exact Product shows:

```text
core scope version            261
knowledgeDomains              0
knowledgeDrafts               0
knowledgeReleases             0
knowledgeDraftBlocks          0
knowledgeDraftBindings        0
knowledge scope version       4
knowledge scope keys          0
```

Therefore there is no current Knowledge Asset, version, binding or projection on which to perform a
truthful Registry, A-Box, Knowledge Chat or MCP end-to-end closeout. Current non-Admin Neo4j remains
fail-closed, which is the safe behavior until exact identity/provenance is proved.

## Knowledge K0 — Missing

- exact DataHub Table/Column URN ↔ Knowledge entity ↔ Neo4j node identity and provenance;
- canonical `normal < credential < restricted` Knowledge Asset grade model;
- durable/current Node Asset and immutable-version authority suitable for activation/pinning;
- actual A-Box write and Neo4j projection receipt;
- current Node Knowledge Chat handler and real Asset/version evidence;
- bounded Main Chat Knowledge usage profile and authorized routing;
- bounded read-only MCP profile/runtime and external handshake;
- idempotent default Lineage/Glossary Asset sync.

## Knowledge K0 — Legacy / Duplicate

- Historical Python backend models and migrations are richer than the Node POC, but cannot prove
  current runtime behavior.
- Canonical documents still mix the older `PUBLIC/INTERNAL/...` classification with the current
  DataRiver security grades.
- A document says the former loading/information navigation was retired, while current source and
  tests still retain the route and consumer. Source wins; the route must not be deleted before a
  consumer/deep-link audit.
- Knowledge records are split between coarse `core` JSON fields and an empty `knowledge` scope.
  This is a current authority/ownership risk, not permission to create another storage framework.

## Knowledge K0 — Reusable

- Current primary/deep-link router and Product design system.
- Existing Registry, drawer, Studio stepper, typed editor components and their tests.
- Existing TanStack Table, XYFlow and Tailwind dependencies.
- Existing request-time principal, Table grant, grade and feature-policy helpers.
- Existing DataHub exact URN and bounded lineage reads.
- Historical typed Knowledge models/ADRs as design references after reconciling them with the Node
  modular monolith and current security grades.
- Existing Main Chat router/provider contracts after a later authorized Knowledge profile exists.

## Knowledge K0 — Risk

- Treating legacy `Provenance.source_locator` as current exact identity would be false evidence.
- Writing a graph before exact Table/Column identity is proved can duplicate or cross-link nodes and
  leak unauthorized graph evidence.
- Treating UI mocks as runtime PASS would falsely close Knowledge Chat/A-Box/MCP.
- Reusing the coarse global JSON blob as a new Knowledge platform could create unrelated CAS
  contention and ambiguous authority.
- Removing `knowledge-instances`/Studio routes immediately could break live deep links and tests.
- Building MCP before Asset/version/identity authority would create a second, unsafe source of
  truth.

## Knowledge K0 — Minimal Close Plan

K0 is complete as a source/runtime audit. Knowledge overall remains `PARTIAL`.

The next single slice is K1, a read-only exact identity/provenance gate:

1. inventory actual DataHub Table and Column URN shapes;
2. inspect current Neo4j node keys and Table/Column distinction;
3. prove or reject an existing stable bridge and its rename/delete/duplicate behavior;
4. define the smallest canonical identity/provenance record using existing authorities;
5. retain non-Admin graph fail-closed until pre-traversal authorization can be proved.

K1 does not include graph writes, a new graph service, Knowledge storage migration, Main Chat
integration or MCP implementation.

## K0 canonical status

| Surface | Status | Current boundary |
|---|---|---|
| Knowledge menu topology | `PARTIAL` | top-level item exists; requested two-item left menu not aligned |
| Registry UI/API source | `IMPLEMENTED_NOT_VERIFIED` | substantial UI/local adapter; zero current Assets |
| Asset/draft/T-Box source | `IMPLEMENTED_NOT_VERIFIED` | typed UI/local coarse state; no runtime Asset lifecycle |
| Version/release | `IMPLEMENTED_NOT_VERIFIED` | local coarse release, not proven immutable canonical authority |
| A-Box enrichment | `PARTIAL` | binding/preview source exists; no actual Neo4j projection |
| Neo4j Knowledge projection | `BLOCKED` | K1 identity/provenance gate absent |
| Knowledge Chat | `PARTIAL` | UI/mocks exist; current Node handler and Asset evidence absent |
| Main Chat Knowledge routing | `BACKLOG` | no bounded usage profile or authorized route signal |
| MCP | `BACKLOG` | no current route/server/test; not the K1 gate |
| Default system Assets | `BLOCKED` | identity, provenance and idempotent sync gates absent |
| Knowledge overall | `PARTIAL` | K0 audited; K1 is next |

## AGY usage and claim control

| Task | Requested/effective | Result |
|---|---|---|
| Critical Product mutation | Claude Sonnet 4.6 Thinking / Claude Sonnet 4.6 Thinking | explicit Individual quota exhaustion before command or mutation |
| Product fallback | Gemini 3.1 Pro High / Gemini 3.1 Pro High | produced bounded source changes; coordinator narrowed persisted-policy compatibility and completed direct adapter/UI role guards |
| Navigation/Registration audit | Gemini 3.1 Pro High / Gemini 3.1 Pro High | read-only; coordinator rechecked exact source/runtime |
| Knowledge K0 audit | Gemini 3.1 Pro High / Gemini 3.1 Pro High | read-only; legacy-Python-as-current and MCP-as-K1 claims discarded |
| Fresh independent validator | Gemini 3.1 Pro High / Gemini 3.1 Pro High | exact Product/OCI PASS; rejected 595/599 parallel timing run, accepted full single-worker 599/599; files modified 0 |

## Overengineering check

```text
new tables        0
new dependencies  0
new services      0
new containers    0
new queues        0
new workers       0
new frameworks    0
new capabilities  0 (still exactly 15)
```

## Canonical status

- Menu topology and independent Change/Monitoring/Registration routes:
  `COMPLETE_RUNTIME_VERIFIED`.
- Registration role realignment (`data_steward`, `admin` only):
  `COMPLETE_RUNTIME_VERIFIED`.
- Registration overall: `PARTIAL`; provider apply and approved durability remain separate gaps.
- Knowledge K0 audit: `COMPLETE_SOURCE_RUNTIME_AUDIT`.
- Knowledge overall: `PARTIAL`.
- Knowledge K1 exact identity/provenance gate: `NOT_STARTED`.
- MCP: `BACKLOG`; not an implemented current capability and not the next gate.
- Quality Product: `USER_FEATURE_DEFINITION_REQUIRED`; no Quality mutation occurred.
