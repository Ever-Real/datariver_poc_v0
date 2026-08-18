# DEV post-K1 Quality primary-tab parity runtime evidence

Date: 2026-08-18 (Asia/Seoul)

## Scope and lineage

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Previous Evidence HEAD: `2e77355a8a0972b433398490650e4272d6a9b363`
- Product SHA: `8dc782a6b8d03ee90b935593294728d2244b03a5`
- Deployed Web OCI revision: `8dc782a6b8d03ee90b935593294728d2244b03a5`
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`
- Health: `GET /healthz` returned exact `ok`.

Knowledge K1 and the Registration Manager read-only slice remain frozen completed baselines. This
slice changes no Quality behavior, authorization, rule model, GX runtime or Knowledge code.

## User-visible result

The three Quality top tabs now use the exact existing Governance primary-tab primitive:

1. 품질 대시보드
2. 자산별 품질 현황 및 이력
3. 공통 룰셋 관리

Quality retains `useRovingTabs`, its URL/deep-link contract, authorization lease, data loading and
existing `quality-tab-panel` layout boundary. It shares `governance-primary-tabs` and
`governance-primary-panel`; no CSS declarations or component framework were duplicated.

## Source and test evidence

| Gate | Result |
|---|---|
| Focused Quality page/location tests | PASS — 2 files, 18/18 |
| Frontend full stable single-worker suite | PASS — 87 files, 606/606 |
| ESLint | PASS |
| TypeScript | PASS |
| POC production build | PASS |
| Compose no-interpolate render | PASS |
| `git diff --check` | PASS |
| Exact image label before recreate | PASS |
| Running OCI = Product SHA | PASS |
| `/healthz` | PASS — exact `ok` |

The first typecheck/build run correctly rejected the new test's positional array access as possibly
undefined. The test was repaired to use accessible tab names; the final exact source then passed
focused tests, lint, typecheck and build. This intermediate failure is not completion evidence.

The existing Vite chunk warning and `FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS` backlog are unchanged.
The full frontend suite used the accepted one-worker configuration; no timeout widening or test
framework was added.

## Browser runtime evidence

The coordinator used a new tab in the existing authenticated browser profile without logging out or
changing the inspection account/session.

Desktop Quality and Governance computed values matched exactly:

```text
tab class            governance-primary-tabs
active height        35px
padding              9px 13px 8px
font size / weight   10px / 900
active border        3px
active background    rgb(255, 255, 255)
active color         rgb(0, 75, 135)
```

Clicking Assets and Common Rules changed the exact `qualityTab` URL and selected tab/content. At an
emulated 390px viewport, document/body width stayed 390px, all tab heights stayed 35px, and only the
tab strip used bounded horizontal overflow (`368px` client / `400px` scroll). The combined
`quality-tab-panel governance-primary-panel` boundary remained present.

The coordinator-owned tab was closed. The authenticated session was neither logged out nor revoked.

## Independent validator

A fresh independent Gemini 3.1 Pro High validator in plan mode recorded the authoritative worktree,
branch, clean exact Product HEAD, Node POC authority, exact running OCI revision and `/healthz=ok`.
It read the exact commit/source, confirmed the two-file Quality-only change and reran the current
focused suite: 2 files, 18/18 PASS. It modified no file, DB, runtime, container, account, session,
browser, Dashboard or Evidence.

## AGY usage

| Task | Requested | Effective | Result |
|---|---|---|---|
| Quality tab parity mutation | Gemini 3.1 Pro High · high | Gemini 3.1 Pro High · high · accept-edits | completed; coordinator applied one layout-preservation repair |
| Independent validation | Gemini 3.1 Pro High · high | Gemini 3.1 Pro High · high · plan | PASS — 18/18, exact SHA/OCI/health |

Two stale reused-terminal dispatch attempts accepted no input and changed no file; fresh explicitly
modelled terminals were used for the completed tasks. Claude was not retried under the current
quota policy.

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

`new workers` means Product runtime workers, not temporary implementation/validation agents.

## Backlog captured without Product mutation

`CHANGE_MONITORING_LEDGER_SURFACE_RELOCATION` records the user's design feedback to move the
authoritative `data-change-status-panel` presentation into Change Management and remove overlapping
Change summary content. Before implementation, the current reusable component, Change summary and
independent Monitoring route consumers must be mapped so one server projection remains authoritative
and no duplicated client/backend state is introduced. This Quality slice does not implement it.

## Canonical status and boundary

- Quality top-tab Governance-style parity: `COMPLETE_RUNTIME_VERIFIED`.
- Quality Product functionality: remains `USER_FEATURE_DEFINITION_REQUIRED`.
- GX assertion egress: remains `GX_PREP_OPS_CONTRACT_EVIDENCE_REQUIRED`.
- Knowledge K1: remains `COMPLETE_RUNTIME_VERIFIED` and frozen.
- Knowledge K2/K3 and K4 through K9: not modified or started by this slice.
- No push, G1/G2 publication, PREP/OPS mutation, schema migration or destructive action occurred.

The next ordered Product step is the bounded Chat Router source/runtime audit. Existing
General/Vector/AUTO behavior remains frozen unless the audit finds a concrete current-policy gap.
