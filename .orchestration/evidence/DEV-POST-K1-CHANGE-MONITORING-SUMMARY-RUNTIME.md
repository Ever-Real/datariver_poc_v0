# DEV post-K1 Change Management / Monitoring summary runtime evidence

Date: 2026-08-18 (Asia/Seoul)

## Scope and lineage

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Previous Evidence HEAD: `619183ffa89b96d5139e46fb7600858f99603aa9`
- Product SHA: `b0bb9f0aafc2391f80be0e24eccdfc1d5568bffc`
- Deployed Web OCI revision: `b0bb9f0aafc2391f80be0e24eccdfc1d5568bffc`
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`
- Knowledge K1 remains the frozen `COMPLETE_RUNTIME_VERIFIED` baseline.

This bounded Product slice changes only the Change Management presentation. MCL, CR lifecycle,
Monitoring route/API/authorization, request-time Table access, Registration and Knowledge are
unchanged.

## User-visible result

The existing `CR Status Overview` and `Detected Change → CR` surfaces now share one parent section:

```text
CR 및 감지 변경 현황
├─ current authorized CR status overview
└─ current authorized detected-change → CR linkage
```

The parent section uses the existing reads, child component and state. It adds one
`Monitoring 상세 현황` button that calls the existing `onNavigate('monitoring')` page router.
The independent top-level Monitoring route and detailed Monitoring screen remain intact.

No second backend read model, duplicated client state, Monitoring ACL, route family or MCL/CR
projection was added. The nested detected-change child no longer applies a second outer `panel`
frame. The combined header has one responsive CSS rule; no new design system or component library
was introduced.

## Source and test evidence

| Gate | Result |
|---|---|
| Coordinator focused Governance tests | PASS — 2 files, 47/47 |
| Frontend full suite, stable single-worker configuration | PASS — 87 files, 603/603 |
| ESLint | PASS |
| TypeScript | PASS |
| POC production build | PASS |
| Compose no-interpolate render | PASS |
| `git diff --check` | PASS |
| Exact image label before recreate | PASS |
| Running OCI = Product SHA | PASS |
| `/healthz` | PASS — `ok` |

The existing Vite chunk-size warning remains a non-blocking technical backlog item. The existing
`FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS` backlog remains unchanged; this slice used the accepted
single-worker baseline and did not widen timeouts or introduce another test framework. Node server
source was not modified, so the full affected regression for this UI-only slice is the frontend
suite above.

## Browser runtime evidence

A coordinator-owned disposable DEV Admin subject logged into the exact deployed Product. The
browser proved:

- one accessible region named `CR 및 감지 변경 현황`;
- the current authorized schema/CR status table rendered inside it;
- the current detected-change ledger and CR-link view rendered inside the same region;
- `Monitoring 상세 현황` navigated to the independent `?page=monitoring` route;
- the Monitoring page rendered the separate `데이터 변경현황` surface;
- direct navigation back to `?page=change-management` restored exactly one combined region and one
  Monitoring button.

No password-bearing DOM snapshot was taken. The disposable credential was matched to its exact
subject before being disabled, its one session was revoked, the temporary password file/directory
was removed, and the browser returned to Sign In.

## Validation hygiene and inspection Admin

An initial disposable bootstrap used the shell variable name `USERNAME`, which zsh owns as the
current local login. The new validation subject was therefore provisioned with username
`everreal`, not the intended generated login. No browser login or session occurred. The coordinator
immediately matched the exact validation subject, disabled only that new credential and then used a
task-specific shell variable for the successful disposable account. The inspection Admin was not
included in either cleanup.

Final read-only observations:

```text
inspection admin username         admin
inspection admin active           true
inspection admin login enabled    true
inspection admin role             admin
inspection admin max grade        restricted
inspection admin failed attempts  0
inspection admin locked           false
validation/test active sessions   0
inspection admin active sessions  0
other active sessions             0
enabled validation credentials    0
active Table grants               0
```

No inspection Admin password, credential or session was read, reset, changed, disabled or revoked.

## Independent validator

A separate existing `agy` plan terminal used requested/effective Gemini 3.1 Pro High with high
reasoning. It recorded the authoritative worktree, branch, clean exact Product HEAD, Node POC
authority, exact running OCI revision and loopback health. It reviewed the exact Product diff and
ran the focused current tests: 2 files, 47/47 PASS. Its test log was independently read by the
coordinator and it modified no Product, Git or runtime state.

Two proposed validator commands were rejected before execution:

1. a full `docker inspect | grep` pipeline plus incorrect localhost ports, because it could traverse
   Docker Environment and did not use the canonical endpoint;
2. a root-level npm / `npx jest` fallback, because it was not the repository test contract and could
   fetch tooling.

The accepted validation used only the label-specific OCI template, canonical
`http://127.0.0.1:39083/healthz`, exact Git reads and the existing frontend Vitest command. The
rejected commands contribute no evidence.

The first idle validator terminal also absorbed dispatch input at its local survey prompt and did
not start the task. That dispatch was fenced and recorded as failed with zero file/runtime changes.
The succeeding validator used a separate idle Gemini plan terminal and delivered a valid
`worker_done`. Because it was a reused low-level terminal rather than a supervised worker-start
resource, `worker-release` correctly reported no supervised Dispatch resource to release.

During the external dashboard edit, one provisional Evidence value was manually expanded from the
abbreviated commit instead of being read from Git. It was rejected before dashboard validation.
`git rev-parse HEAD` was then run and the dashboard was corrected to the exact 40-character Evidence
SHA. This affected neither the Product image nor the already verified Product/OCI equality.

## AGY usage

| Task | Requested | Effective | Result |
|---|---|---|---|
| Change/Monitoring summary mutation | Gemini 3.1 Pro High | Gemini 3.1 Pro High · high | worker implementation; coordinator source repair and acceptance |
| Independent validation retry | Gemini 3.1 Pro High | Gemini 3.1 Pro High · high · plan | PASS — exact SHA/OCI/health and 47/47 focused tests |

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

- Change Management combined CR/detected-change summary: `COMPLETE_RUNTIME_VERIFIED`.
- Independent Monitoring menu/route/detail: preserved and runtime verified.
- Knowledge K1: remains `COMPLETE_RUNTIME_VERIFIED` and frozen.
- Knowledge K2/K3: not started or modified by this slice.
- K4 through K9: not started.
- No push, G1/G2 publication, PREP/OPS mutation or destructive action was performed.

The next Product mutation remains one separate, user-visible slice. Per the current ordered prompt,
that is the bounded Registration manager read-only/recent-run/workbench UX, not Knowledge K2 yet.
