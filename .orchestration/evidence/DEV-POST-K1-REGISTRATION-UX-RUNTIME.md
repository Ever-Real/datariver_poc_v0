# DEV post-K1 Registration read-only history UX runtime evidence

Date: 2026-08-18 (Asia/Seoul)

## Scope and lineage

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Previous Evidence HEAD: `d5275aee3839afcbb9868d082902e871c0ab4874`
- Product SHA: `691b889af35fbbe49b5e2850420f877aebf5ca56`
- Deployed Web OCI revision: `691b889af35fbbe49b5e2850420f877aebf5ca56`
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`
- Health contract: `GET /healthz` returned exact `ok`.

Knowledge K1 exact identity/provenance remains the frozen `COMPLETE_RUNTIME_VERIFIED` baseline.
This slice does not change Knowledge identity, projection or graph code.

## User-visible result

- Data Steward and Admin retain the existing Registration mutation workbench.
- Manager gets a clearly labelled read-only Registration page with execution status/history only.
- Viewer and Developer remain excluded from Registration.
- Manual and Bulk share one unified `최근 실행` panel on the right. The panel filters the current
  run/preparation projection by type, status, period and executor; it does not add another analytics
  store.
- The per-Table duplicate Manual history block was removed.
- The Manual workbench has bounded viewport-height scrolling, a sticky header and reachable sticky
  actions, including the 390px layout.

Menu visibility remains UX only. Direct server authority still limits Registration mutation to
`data_steward` and `admin`; Manager candidate and mutation routes return 403.

## Request-time manager history scope

The manager history projection does not use Responsible System as general read authority. The
frontend `managerVisibleRegistrationUrns` helper hydrates the Manager's currently visible Catalog
scope once, caps it at 100 exact URNs and sends one repeated `urn` query. Server `datahubCatalog`
validates every `urn` value, applies request-time `filterAssetsForPrincipal`, and then applies the
exact-URN filter before matching, sorting, paging and counting.

This is the existing Table-access conjunction and a Set/batched request boundary, not one provider
or grant query per Table. Chat's `getAllowedTableUrnsScope` is unrelated and is not evidence for
Registration.

## Source and test evidence

| Gate | Result |
|---|---|
| Focused frontend and authorization tests | PASS — 64 tests |
| Node POC full suite | PASS — 108/108 |
| Provider exact-scope suite | PASS — 22/22 |
| Frontend full stable single-worker suite | PASS — 87 files, 605/605 |
| ESLint | PASS |
| TypeScript | PASS |
| Production build | PASS |
| Compose no-interpolate render | PASS |
| `git diff --check` | PASS |
| Exact image label before recreate | PASS |
| Running OCI = Product SHA | PASS |
| `/healthz` | PASS — exact `ok` |

The accepted frontend baseline remains `maxWorkers: 1`. The separate
`FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS` backlog is unchanged; this slice neither widened timeouts
nor introduced a test framework.

## Browser and direct API runtime evidence

A coordinator-owned disposable Manager subject used the exact deployed Product. The browser proved:

- the profile menu displayed Registration, Knowledge and Quality without Admin surfaces;
- Registration rendered `등록관리 조회 전용` and the unified recent panel;
- no Manual/Bulk mutation controls were rendered;
- at 390px device width the document width remained 390px, the recent panel and read-only callout
  remained visible, and the mutation-button count remained zero;
- direct Bulk mutation returned 403 `ROLE_FORBIDDEN`;
- direct candidate read returned 403 `ROLE_FORBIDDEN`;
- direct execution-history read returned 200.

The disposable Manager logged out. Its exact credential was disabled, with zero active sessions and
zero active Table grants. The isolated browser profile and memory-only temporary secret file were
removed. No password or token was written to Evidence or Dashboard.

## Validation hygiene and inspection Admin

Cleanup used the exact disposable subject only. Final read-only observations were:

```text
inspection admin username         admin
inspection admin subject          c0d0f718-77ed-4ec3-ae4f-bdd158d0489c
inspection admin active           true
inspection admin login enabled    true
inspection admin role             admin
inspection admin max grade        restricted
inspection admin failed attempts  0
inspection admin locked           false
validation/test active sessions   0
inspection admin active sessions  1
other active sessions             0
enabled validation credentials    0
active Table grants               0
```

The inspection Admin password, credential and session were not read, reset, changed, disabled or
revoked. MCL current source/checkpoint/ledger/CR-link remained `2/2/66/4`.

## Independent validator

The first independent result was explicitly discarded as
`VALIDATOR_RESULT_DISCARDED_INACCURATE_HEALTH_AND_SOURCE_CLAIMS`: although 70 tests passed, it used
the SPA `/health` fallback and made inaccurate source attributions. It contributes no completion
claim.

A fresh independent Gemini 3.1 Pro High validator then recorded the exact worktree, branch, clean
Product HEAD, Node POC authority, exact OCI revision and `/healthz=ok`. It reran:

```text
Node authorization/provider tests  29/29 PASS
Frontend Registration/navigation   72/72 PASS
Total                              101 PASS
```

The same independent validator corrected its report after reading the exact source: Registration
batching belongs to `managerVisibleRegistrationUrns` and `datahubCatalog`, not the Chat scope helper.
The corrected external report changed no repository file, DB, runtime, account, browser or container.

## AGY usage

| Task | Requested | Effective | Result |
|---|---|---|---|
| Registration read-only UX mutation | Gemini 3.1 Pro High | Gemini 3.1 Pro High · high | worker implementation; coordinator review/runtime acceptance |
| Independent validator retry/correction | Gemini 3.1 Pro High | Gemini 3.1 Pro High · high · plan | PASS — exact SHA/OCI/health and 101 focused tests |

Claude was not retried because the current user policy freezes the known exhausted quota state.

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

`new workers` means Product runtime workers, not temporary validation agents.

## Canonical status and boundary

- Registration Manager read-only history/recent-run/workbench UX:
  `COMPLETE_RUNTIME_VERIFIED`.
- Registration overall: `PARTIAL`; governed provider apply and durable preparation/restart recovery
  remain outside this slice.
- Knowledge K1: remains `COMPLETE_RUNTIME_VERIFIED` and frozen.
- Knowledge K2/K3 and K4 through K9: not modified or started by this slice.
- No push, G1/G2 publication, PREP/OPS mutation, schema migration or destructive action occurred.

The next single Product mutation in the ordered prompt is Quality tab style parity with the existing
Governance tab primitive. Quality Product behavior and GX runtime remain out of scope.
