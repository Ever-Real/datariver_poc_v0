# DEV Knowledge K1 exact identity/provenance runtime evidence

## Status

- Product SHA: `afb95a45c45ae065223faa39c53278884c935f37`
- Deployed OCI revision: `afb95a45c45ae065223faa39c53278884c935f37`
- Canonical DEV Web: `http://127.0.0.1:39083/`
- Node POC authority: current `frontend/poc-server.mjs` and the current browser Product
- Knowledge K0: `COMPLETE_SOURCE_RUNTIME_AUDIT`
- Knowledge K1 bounded exact identity/provenance slice: `COMPLETE_RUNTIME_VERIFIED`
- Knowledge overall: `PARTIAL`
- Publication/PREP/OPS: not performed

K1 closes only the exact current DataHub Table/Column identity to release-pinned Knowledge entity
to bounded Neo4j projection gate. It does not close Registry/version completeness, A-Box row
ingestion, Knowledge Chat, Main Chat routing, MCP or default system assets.

## Read-only existing identity audit

The audit preceded all Product mutation.

| Surface | Current representation | K1 conclusion |
|---|---|---|
| DataHub Table | exact `urn:li:dataset:(urn:li:dataPlatform:...,name,DEV)` | reusable canonical external identity |
| DataHub Column | provider-returned `urn:li:schemaField:(<dataset URN>,<fieldPath>)`, entity type `SCHEMA_FIELD` | reusable only when returned by the current provider; never reconstruct after loss |
| Knowledge T-Box | stable `stable_element_id`, graph identity, immutable Studio release identity and binding target IDs | reusable release-pinned authoring identity |
| Knowledge source binding | exact `source_asset_id` plus exact `source_field_path` and target stable ID | reusable input to current-provider confirmation |
| Neo4j before K1 | three `PocEntity` nodes, two relationships, no exact DataHub URN property/identity map | not reusable as canonical Table/Column bridge |
| Historical Python | substantial design/schema code | not current Node Product or runtime evidence |

There was no existing exact DataHub Table/Column URN to current Knowledge release to Neo4j node
bridge. K1 therefore uses the smallest release-pinned identity contract and does not create a
generic graph identity framework.

## Minimal K1 identity contract

The canonical external identity stays the exact current provider URN. The bounded projection ID is
deterministic over:

```text
KNOWLEDGE_SOURCE_IDENTITY_V1
+ knowledge_graph_id
+ pinned studio_release_id
+ exact external_urn
→ SHA-256
→ knowledge:<hash>
```

The fixed Neo4j projection is limited to:

- label `KnowledgeSourceEntity`;
- entity kinds `TABLE` and `COLUMN`;
- provenance `DATAHUB_SYNC`;
- fixed relationship `HAS_COLUMN`;
- parameterized `MERGE`, never arbitrary Cypher;
- current exact Table confirmation and exact provider Column URN confirmation before write;
- release, graph and T-Box target stable identities in every node;
- request-time current Knowledge data authorization before Neo4j write.

Current-missing, non-TABLE, malformed binding, missing rule, unknown target, unresolved exact Column
URN and unavailable provider paths fail closed. Admin bypasses data scope only; it does not bypass
these integrity checks.

## Source changes

Product commits:

1. `a7de09e61d3e9fc5b74f2f4b973fab6f9e371572` — exact K1 identity projection, tests and the frontend
   parallel-test containment.
2. `64021f4dff6d902cdab12ae2dd01813568676dcc` — missing resumable Knowledge draft is a typed 404,
   allowing the actual create flow to start.
3. `200eb3c2e00106b25a91f46615b2fc11254efe00` — new Draft starts with one existing DIRECT T-Box
   block primitive so the browser can add its first Class.
4. `afb95a45c45ae065223faa39c53278884c935f37` — Draft author identity comes from the current
   authenticated authorization boundary rather than a fixed placeholder.

The last three fixes are bounded K0 browser-flow defects discovered while executing the required
K1 browser E2E. They add no Knowledge architecture.

## Browser UX audit

The actual current Product was inspected at desktop and narrow mobile layout. The browser audit
confirmed:

- canonical top-level menu order and route-backed full-screen Knowledge Studio;
- clear three-step Basic → Graph Builder → Data Enricher navigation;
- actual create, T-Box Class edit, Catalog Table/Column binding, save, reload and Pre-flight flow;
- REVIEW locking and independent reviewer publication;
- current React Flow canvas and quick Class property editor;
- no narrow-viewport horizontal page overflow at 390×844.

Open UX gaps for later K2/K3 slices:

- Registry empty state is generic and does not explain the first useful action;
- Knowledge left navigation still exposes three items rather than the accepted Registry/Knowledge
  Chat pair;
- Registry columns do not yet cover grade, version clarity, Main Chat or MCP state;
- Step 1 displays the legacy PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED vocabulary rather than the
  canonical normal/credential/restricted vocabulary;
- active/pinned version indication is weak;
- quick property editing lacks aliases, description, datatype, unit, required and cardinality;
- validation/errors are mostly transient status text rather than a durable actionable panel;
- the narrow dialog fits without horizontal overflow but is not a true compact/full-screen mobile
  workflow and has high vertical navigation cost.

These gaps were audited, not implemented in K1.

## Actual disposable Knowledge Asset E2E

One clearly labelled DEV-only Knowledge Asset was created in the current browser. It did not mutate
the bound DataHub Table; the Table and one exact Column are read-only provenance inputs.

```text
authenticated author
→ DRAFT create
→ DIRECT T-Box block
→ stable Class identity
→ exact current DataHub Table binding
→ exact current DataHub Column mapping
→ save
→ hard reload and state recovery
→ author Pre-flight PASS
→ REVIEW lock
→ different disposable Admin reviewer Pre-flight
→ immutable Studio Release publish
→ Neo4j projection
→ projection rerun
```

Runtime receipt:

| Check | Result |
|---|---|
| Draft state | `PUBLISHED` |
| Author and reviewer | distinct subjects |
| Studio release | `ACTIVE`, `KNOWLEDGE_STUDIO_RELEASE_V1` |
| Projection receipt | `KNOWLEDGE_PROJECTION_RECEIPT_V1`, `SUCCESS` |
| Neo4j nodes | 2 (`TABLE`, `COLUMN`) |
| Neo4j edges | 1 (`HAS_COLUMN`) |
| duplicate identities after rerun | 0 |
| provenance entries | 2, both exact current DataHub URNs and `DATAHUB_SYNC` |
| no-grant manager projection | 403 `KNOWLEDGE_TABLE_FORBIDDEN` before a new write |
| post-negative Neo4j audit | 2 nodes / 1 edge / duplicate 0 |

The test Asset remains an explicitly named DEV evidence Asset because current Node Registry archive
is not implemented. K1 does not add or bypass K2 lifecycle/archival semantics, and no hard delete or
direct Neo4j cleanup was performed.

## Disposable account cleanup and inspection admin observation

The disposable reviewer and no-grant manager were both made access-inactive, login-disabled, have
zero active sessions, zero active Table grants and zero Responsible-System assignments. Their
history was not hard-deleted.

The inspection `admin` account remains access-active, login-enabled, role `admin`, maximum grade
`restricted`, unlocked with failed attempts 0, zero grants and no Responsible System. Its password
was not read, reset, reconstructed or changed.

During independent-review browser switching, the existing inspection admin browser session was
logged out and therefore revoked. The account/credential remained unchanged and can log in again
with its frozen credential, but this session side effect violated the validation guard and is
recorded as a closeout deviation. No password reset or session reconstruction is permitted as a
repair.

One candidate credential for a not-yet-created disposable reviewer was inadvertently rendered in a
tool DOM snapshot. That candidate was immediately canceled, never used to create or authenticate an
account, and replaced through the memory-only path. The literal value is not retained in Product,
Evidence or Dashboard. This is recorded as a secret-harness deviation; no existing credential was
read or exposed.

## Frontend async parallel flakiness

Reason code: `FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS`.

At two Vitest workers, four navigation/timeout failures were observed across PocApp primary/admin/
security-policy navigation and CatalogWorkspace Lineage. The failures did not reproduce
deterministically in isolation and moved between full runs, demonstrating shared async navigation
contention rather than four K1 product defects. The existing test runner is contained at one worker;
no new test framework or product runtime behavior was introduced.

Final current-source frontend result is 87 files and 600/600 tests PASS. The earlier parallel result
is rejected and is not reused as completion evidence.

## Current-source validation

| Gate | Result |
|---|---|
| K1 focused Node/provider tests | PASS |
| K1 focused frontend adapter/browser-flow tests | 3 files, 47/47 PASS |
| Node full suite | 108/108 PASS |
| Frontend full suite | 87 files, 600/600 PASS |
| lint | PASS |
| typecheck | PASS |
| production build | PASS |
| POC production build | PASS |
| Compose no-interpolate render | PASS |
| `git diff --check` | PASS |
| exact 40-character Product SHA image build | PASS |
| Web health / loopback 39083 / OCI equality | PASS |

## Fresh independent validator

The accepted fresh validator was a separate read-only AGY Gemini 3.1 Pro High (High) run in plan
mode. It recorded the authoritative worktree, branch and exact Product revision, inspected the
current Node POC rather than legacy FastAPI, independently compared the deployed OCI label with the
40-character Product SHA, inspected the bounded identity/projection/authorization implementation,
and reran the current frontend suite at the checked-in single-worker boundary.

Verdict: `PASS`.

- authoritative worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`;
- Product SHA / deployed OCI: exact `afb95a45c45ae065223faa39c53278884c935f37` equality;
- Node POC source boundary, fixed projection, request-time authorization and absence of a generic
  identity/framework dependency: PASS;
- frontend fresh rerun: 87 files, 600/600 PASS;
- Knowledge K1 bounded slice only; Knowledge overall remains `PARTIAL`.

Two earlier invocations were discarded: one did not receive the workspace prompt, and one could not
obtain read-only command permission in headless plan mode. Neither is runtime evidence. The accepted
run made no Product, DB, runtime, container, account or session mutation and emitted no secret dump.

## AGY use

- Critical mutation requested Claude Sonnet 4.6 (Thinking). Requested and effective models matched,
  but Claude returned explicit quota exhaustion before any command or mutation.
- Ownership was fenced and Gemini 3.1 Pro High (High) continued under the allowed fallback. Its
  initial draft was not accepted as source of truth; the coordinator reviewed and minimally repaired
  the implementation and reran all current-source gates.
- The accepted fresh validator was a separate read-only AGY Gemini 3.1 Pro High (High) run and
  returned `PASS`. Two incomplete launcher/permission attempts were explicitly discarded.

## Overengineering check

```text
new tables       0
new dependencies 0
new services     0
new containers   0
new queues       0
new workers      0
new frameworks   0
new capabilities 0
```

Two bounded Knowledge projection routes were added within the current Node modular monolith. The
central capability count remains exactly 15.

## Remaining risks and next single slice

- No Neo4j uniqueness constraint is added in K1. Sequential rerun duplicate 0 is proven; concurrent
  first-write uniqueness remains a K2 data-integrity decision, not a reason to invent a graph ACL or
  identity framework.
- The DEV evidence Asset cannot yet be archived through the current Node Registry path.
- Column identity is fail-closed when DataHub does not return an exact `schemaFieldEntity` URN.
- Knowledge Registry/version lifecycle remains incomplete; Knowledge Chat, Main Chat integration,
  MCP and default system assets are not started.

Next single Product slice: K2 Registry/Asset/version lifecycle, beginning with canonical
normal/credential/restricted grade alignment and a real archive/history path. Every K2 acceptance
must include actual browser create/edit/save/reload/error/authorization UX.
