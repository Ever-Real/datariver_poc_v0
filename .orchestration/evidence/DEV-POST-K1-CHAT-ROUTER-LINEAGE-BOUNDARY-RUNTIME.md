# DEV post-K1 Main Chat routing boundary runtime evidence

Date: 2026-08-18 (Asia/Seoul)

## Scope and lineage

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Previous Evidence HEAD: `96e389806fa71f75d2ade61d26e351c7cc21891b`
- Pre-K7 Graph boundary Product: `601a7ec14fbaa9af2068671e6777206c96a3c19b`
- Current Product SHA: `cc15ebce4181ad7a72dae641eb52d4696ab8e686`
- Deployed Web OCI revision: `cc15ebce4181ad7a72dae641eb52d4696ab8e686`
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`
- Health: `GET /healthz` returned exact `ok`.

This slice does not implement Knowledge K7 routing, a fallback engine, a classifier rewrite or a
new Chat architecture. General, Vector, AUTO, provider, reranker, authorized context and citation
remain frozen completed baselines except for the two concrete current-policy defects below.

## User-visible result

1. Main Chat `GRAPH` is explicitly DataHub-lineage-only before K7 for every role, including Admin.
   It no longer reads the generic Neo4j evidence query. The Chat workflow and UI identify the
   source as authorized DataHub lineage rather than implying that a Knowledge Asset was selected.
2. Main Chat `GENERAL` performs no metadata retrieval and now receives a dedicated composition
   prompt. It answers ordinary general-knowledge questions directly instead of refusing because
   no DataHub evidence was supplied.
3. K1's bounded Knowledge projection APIs, exact URN bridge, `KnowledgeSourceEntity` and
   `HAS_COLUMN` behavior are unchanged.

## Source boundary

- Both explicit `GRAPH` and deterministic AUTO Graph readiness require DataHub.
- `liveChat` contains no generic Neo4j evidence call; its Graph evidence is produced only through
  the existing authorized DataHub lineage path.
- Graph completion uses `DATAHUB_LINEAGE_EVIDENCE_BOUND`.
- General completion returns a skipped retrieval step with `RETRIEVAL_NOT_EXECUTED` and
  `NO_INTERNAL_CITATIONS_GENERAL_ANSWER`.
- General composition receives no `Live POC evidence` or `no matching live evidence` payload.
- Metadata routes retain their evidence-only composition contract.
- `fallback_mode` remains a declarative route field. Actual unresolved-lineage fallback execution
  is not implemented or claimed by this slice.

## Current-source test and build evidence

| Gate | Result |
|---|---|
| Focused Node provider/Chat test | PASS — 21/21 |
| Focused Chat UI test | PASS — 22/22 |
| Node POC full stable serialized suite | PASS — 107/107 |
| Frontend full stable single-worker suite | PASS — 87 files, 607/607 |
| ESLint | PASS |
| TypeScript | PASS |
| POC production build | PASS |
| Compose no-interpolate render | PASS |
| `git diff --check` | PASS |
| Diff secret/hardcoding scan | PASS — no match |
| Exact image label before recreate | PASS |
| Running OCI = Product SHA | PASS |
| `/healthz` | PASS — exact `ok` |

The default-concurrency Node full run twice hit an isolated `ECONNRESET` in the unrelated safe
provider-capability probe. That exact test passed alone, and the complete current suite then passed
107/107 with Node test concurrency fixed at one. The failed parallel results are not completion
evidence. The existing Vite chunk warning and `FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS` backlog are
unchanged; no timeout widening or test framework was added.

## Actual DEV runtime evidence

The exact Product image was rebuilt from the 40-character Git revision and Web alone was recreated
through the existing Compose/provider overlay. Source, image label and running container label all
equal `cc15ebce4181ad7a72dae641eb52d4696ab8e686`; Web remained loopback-bound at port 39083.

Using a coordinator-owned tab in the existing authenticated local Admin profile, with no credential
or cookie output:

```text
GRAPH question
→ HTTP 200
→ route GRAPH
→ evidence types [DATAHUB_LINEAGE]
→ DATAHUB_LINEAGE_EVIDENCE_BOUND
→ no KNOWLEDGE_GRAPH evidence

GENERAL question
→ HTTP 200
→ route GENERAL
→ evidence count 0
→ RETRIEVAL_NOT_EXECUTED
→ NO_INTERNAL_CITATIONS_GENERAL_ANSWER
→ useful ordinary Korean answer
```

The long synchronous General browser-eval connection exposed an Orca automation connection
closure, not a Product health failure. The accepted E2E started the same-origin request without a
long-held automation connection and later read only its non-secret result receipt. The Product,
provider capability probe and Web health stayed available. The coordinator-owned Chat tab was
closed; no account, credential or session was revoked.

## Independent validator

A fresh standalone Gemini 3.1 Pro High (High) validator recorded the canonical worktree and exact
clean HEAD, used only the Node POC, confirmed `/healthz=ok`, compared the bounded OCI revision label
with Product SHA, inspected the committed Graph/General boundary, reran the provider test 21/21 and
Chat UI test 22/22, and confirmed final Git status clean. It made no file, DB, runtime, container,
account, browser or session change and did not inspect an environment dump or secret.

Two earlier validator attempts are rejected: the first ended `Validation Incomplete` because plan
mode command approvals prevented the focused/OCI gates, and the retry was fenced after exact
read-only commands when result generation remained hung. Neither is completion evidence and both
left the worktree unchanged.

## AGY usage and coordinator review

| Task | Requested/effective model | Accepted result |
|---|---|---|
| Router/source audit | Gemini 3.1 Pro High · high · read-only | source leads only; claims that K7 and fallback execution were complete were discarded |
| Graph boundary mutation | Gemini 3.1 Pro High · high · accept-edits | bounded draft; coordinator repaired readiness, copy and exact no-Neo4j assertion |
| Independent validation | Gemini 3.1 Pro High · high · read-only behavior | PASS — exact SHA/OCI/health, 21/21 and 22/22, no change |

One initial mutator was fenced before mutation because its actual process cwd was the wrong
workspace despite stale terminal metadata. The accepted retry ran in the canonical worktree. Worker
summaries were never treated as source of truth.

## Overengineering check

```text
new tables          0
new dependencies    0
new services        0
new containers      0
new queues          0
new runtime workers 0
new frameworks      0
new capabilities    0
```

## Feedback and remaining boundary

- `CHANGE_MONITORING_LEDGER_SURFACE_RELOCATION` remains `NEXT_SLICE_FEEDBACK`. The authoritative
  Monitoring ledger presentation will be considered in a later Change Management UX slice; this
  Chat closeout did not move or duplicate it.
- Feedback is now handled non-interruptingly: only blocking feedback may stop a coherent Product
  slice; other feedback remains in the canonical backlog/Dashboard inbox until closeout.
- Pre-K7 DataHub-lineage-only Main Chat Graph boundary: `COMPLETE_RUNTIME_VERIFIED`.
- General no-retrieval/general-answer contract: `COMPLETE_RUNTIME_VERIFIED`.
- Chat overall: `PARTIAL` for actual Graph fallback execution and future K7 authorized Knowledge
  Asset routing.
- Knowledge K1 remains frozen `COMPLETE_RUNTIME_VERIFIED`; K2 Registry/Asset/version is the next
  single Product slice.
- No push, G1/G2 publication, PREP/OPS mutation, schema migration or destructive action occurred.
