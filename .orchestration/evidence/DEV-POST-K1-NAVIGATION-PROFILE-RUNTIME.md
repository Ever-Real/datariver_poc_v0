# DEV post-K1 navigation and profile-menu runtime evidence

Date: 2026-08-18 (Asia/Seoul)

## Scope and baseline

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Final Product SHA: `1eb4d5ba53078882c4ef7d7b31b28f233d9e0e30`
- Deployed OCI revision: `1eb4d5ba53078882c4ef7d7b31b28f233d9e0e30`
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`
- Knowledge K1 remains the frozen `COMPLETE_RUNTIME_VERIFIED` baseline.

This slice changes only user-facing navigation/profile topology and the existing Admin deep-link
selection. It does not change capabilities, request-time authorization, Registration mutation
roles, Knowledge identity/provenance, CR, MCL, provider configuration or data state.

## User-visible result

The top navigation now contains, in order:

1. 검색
2. 변경관리
3. 모니터링
4. 거버넌스
5. Chat

Admin, 등록관리, 지식관리 and 품질관리 retain their existing routes/deep links but no longer
appear in the top navigation.

The authenticated profile menu now has these bounded visibility rules:

- every user: `내 프로필`;
- data steward, manager and Admin: 등록관리, 지식관리, 품질관리;
- Admin only: Admin — 접근관리, 사용자 관리, System 관리, 메타데이터 변경 로그,
  시스템 보안 로그 and 용어사전.

These rules are navigation UX only. Existing backend route/capability/data authorization remains
the security authority. No browser or local-storage authority was added.

## Runtime defect found and repaired

The first exact-SHA browser run proved that profile-menu Admin URLs changed, but a previously
mounted Admin page stayed on the original section. `pushState` does not emit `popstate`, and the
existing Admin subviews read their query selection at mount time.

The bounded repair increments an Admin-route-only revision after a profile Admin selection and uses
it in the existing Admin page key. This remounts only the current Admin surface so it reads the new
`adminSection`/`adminView`; it does not add a router, state authority or generic navigation event
framework. A focused App regression fixes this exact same-page deep-link case.

Final browser verification at the deployed Product SHA proved:

- 메타데이터 변경 로그 → `adminSection=auditLogs&adminView=metadata` and the metadata log view;
- 시스템 보안 로그 → `adminSection=auditLogs&adminView=security` and the security log view;
- 사용자 관리 → `adminSection=memberships&adminView=users` and local account view;
- System 관리 → `adminSection=memberships&adminView=systems` and System master/Table view;
- 용어사전 → `adminSection=dictionary` and terminology view;
- direct reload of the security-log deep link restores the same surface.

## Product lineage

- `3e0f1f03b9d5a32709c91598541ec56b42339b53` — top navigation, profile menu and existing
  Admin read-only surfaces.
- `1eb4d5ba53078882c4ef7d7b31b28f233d9e0e30` — same-page Admin profile deep-link synchronization.

The image build always used `git rev-parse HEAD` as a validated 40-character SHA. One intermediate
post-repair script correctly stopped after image build because it selected the first image from the
whole Compose image list rather than the `web` service image. It did not recreate Web and contributes
no runtime PASS. The service-specific image was then selected, its OCI label was exactly compared,
and Web alone was recreated.

## Source and test evidence

- Focused App/PocApp/Admin tests: 3 files, 19/19 PASS.
- Final full frontend suite with the stable single-worker configuration: 87 files, 602/602 PASS.
- ESLint: PASS.
- TypeScript: PASS.
- POC production build: PASS.
- Compose no-interpolate render: PASS.
- `git diff --check`: PASS.
- Existing Vite `PolicyGovernancePage` chunk-size warning remains a non-blocking backlog item.

Earlier parallel/navigation timeouts remain classified as
`FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS`. This slice did not create another test framework or widen
timeouts. One topology test was narrowed to its actual URL-routing responsibility; the final clean
single-worker suite is the completion evidence.

## Browser and cleanup evidence

A coordinator-only disposable DEV Admin subject was created through the existing bounded
password-file/stdin contract. No password entered argv, a worker prompt, evidence, dashboard,
Docker environment output or a DOM snapshot.

The browser verified the exact top navigation, full profile menu, `내 프로필` route and all five
Admin sub-surface deep links. The account was then matched against an exact subject allowlist before
cleanup. Its credential was disabled and its one session revoked; the temporary secret directory was
removed. The browser returned to the Sign In surface.

Final read-only observations:

```text
validation/test active sessions  0
inspection admin active sessions 0
other active sessions            0
active Table grants              0
validation credential enabled    false
```

The inspection Admin remains username `admin`, active, login-enabled, role Admin, maximum security
grade restricted, failed attempts 0 and unlocked. Its password and credential were not read, reset,
reissued or disabled.

## Independent validator

A fresh independent `agy` terminal used requested/effective Gemini 3.1 Pro High with high reasoning
in plan mode. It recorded the authoritative worktree, branch, clean Product HEAD, exact running OCI
revision and Node POC authority, checked loopback health, read the current navigation source and ran
the current Node POC tests: 108/108 PASS. It modified no files or runtime state and did not use legacy
FastAPI or inspect secrets.

Orca's direct `gemini` and `agy` composed launchers were unavailable before any worker command. The
fallback low-level terminal ran the validation correctly, but its `worker_done` lifecycle signal was
rejected because that manually created `agy` process lacked the dispatch capability. The coordinator
did not relabel the rejected signal as accepted: it independently rechecked clean HEAD/OCI/health and
recorded the task by explicit recovery with the validator's actual results. The exact validator
terminal was then closed.

## AGY usage

| Task | Requested | Effective | Result |
|---|---|---|---|
| menu/profile mutation | Gemini 3.1 Pro High | Gemini 3.1 Pro High · high | worker implementation, coordinator review/repair |
| independent validator | Gemini 3.1 Pro High | Gemini 3.1 Pro High · high · plan | PASS; 108/108 Node POC; lifecycle recovery noted above |

Claude was not retried because the current user policy freezes its known exhausted quota state.

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

## Status and next boundary

- Navigation/profile topology slice: `COMPLETE_RUNTIME_VERIFIED`.
- Knowledge K0: remains complete.
- Knowledge K1: remains `COMPLETE_RUNTIME_VERIFIED` and frozen.
- Knowledge K2: not started by this slice; remains the next Knowledge Product slice.
- K4 through K9: not started.
- No push, G1/G2 publication, PREP/OPS mutation or destructive action was performed.

The next Product mutation must remain one bounded user-facing slice. Change/Monitoring summary,
Registration manager/read-only recent-run UX, Quality tab styling and Chat router gaps are still
separate from K2/K3 and must not reopen K1.
