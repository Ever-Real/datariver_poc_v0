# CHANGE-HIST-T07A 독립 검증 증적

## 판정

- Task: `CHANGE-HIST-T07A-INDEPENDENT-VALIDATION`
- 검증 시각: `2026-08-14` KST
- exact validation base / 시작 HEAD:
  `17cf1898b60d03a5056deb5c270214f95a493f1a`
- candidate product commit:
  `ef4adbe151901a72d159c8ba565310dc25b4a898`
- 판정: **FAIL**
- 제품 파일은 수정하지 않았다. 아래 finding을 보수하지 않았고, 이 증적과 JSON receipt만 작성했다.

차단 finding은 (1) typed adapter가 비정규 timestamp를 malformed response로 거부하지 않는 점,
(2) ADR-0123의 event precision filter family가 server와 typed filter 계약에서 누락된 점,
(3) builder가 추가 노출한 summary precision/category/operation breakdown의 단위가 불명확하고 Task의
distinct normalized transaction 계약과 달리 semantic row를 증폭 계수로 사용하는 점, (4) exact
candidate에서 ESLint가 두 번 동일한 2개 오류로 실패한 점이다.
Node v25.9.0 test-runner 호출 환경에서 prescribed Node suite가 시작 전에 정지한 것은 별도
`NOT_PASS_ENVIRONMENT`로 기록하며 제품 lifecycle 결함으로 변환하지 않는다.

## SHA, ancestry와 변경 범위

검증 시작 작업트리는 clean이었고 HEAD는 exact validation base와 일치했다. ancestry는 다음과 같이
직계로 이어진다.

```text
8e6516104de9364157af53e985081da98dae0323
  -> ef4adbe151901a72d159c8ba565310dc25b4a898  (candidate product, 1 commit)
  -> 17cf1898b60d03a5056deb5c270214f95a493f1a  (candidate evidence, validation base, 1 commit)
```

제품 parent에서 candidate까지의 diff는 정확히 다음 여덟 경로, `1347 insertions / 69 deletions`다.

1. `frontend/poc-server.mjs`
2. `frontend/poc-server.test.mjs`
3. `frontend/poc-state-store.mjs`
4. `frontend/poc-state-store.test.mjs`
5. `frontend/src/features/change-history/changeHistoryApi.test.ts`
6. `frontend/src/features/change-history/changeHistoryApi.ts`
7. `frontend/src/features/change-history/types.ts`
8. `frontend/src/poc/pocApi.live.test.ts`

candidate에서 validation base까지는 기존 T07A 계약 증적 두 파일만 추가됐다. dependency/lock,
schema/migration/data model, framework/service/container, UI component, 기존 external Monitoring 계약,
CR state/revision/approval/transition 파일 변경은 없다. 전체 추가 diff의 URL/localhost/credential/
secret/private-key pattern review는 일치 항목이 없었고, deployment-specific endpoint 또는 secret
hardcoding도 발견하지 못했다. `git diff --check`는 product diff, working diff, staged diff 모두 통과했다.

## 독립 source 계약 검토

### 확인한 계약

- `readChangeHistoryProjection`은 한 `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY` transaction에서
  access/core/catalog state, ledger, link, source, checkpoint를 모두 읽고 commit한다. catalog identity가
  중복되거나 완전 projection이 아니면 API가 fail closed한다.
- authorization pruning은 `projection.events -> row -> changeHistoryCanRead` 뒤에 이루어지고 그 결과에만
  filter, `total`, keyset page가 적용된다. viewer는 read-only, assigned steward/developer는 일치
  responsibility/System만 보고, unmapped assigned role은 숨김, admin unmapped mutation은 거부된다.
- `SCHEMA_CHANGE`는 `TECHNICAL_SCHEMA + schemaMetadata`에서만 유도되고 나머지는
  `METADATA_CHANGE`다. `EXACT_MCL`은 고정 topic, 단일 matching DataHub source/schema hash,
  matching partition checkpoint와 `[first_exact_offset, next_offset)` 범위를 모두 만족할 때만 유도된다.
- KST Monday 계산은 `[월요일 00:00, 다음 월요일 00:00)`이고 invalid date/Tuesdays를 거부한다.
  weekly total/stage는 distinct transaction map을 사용하고 rejected/cancelled는 `UNLINKED`, round 1
  `IN_REVIEW`는 `RECEIVED`, 재제출 round의 `IN_REVIEW`는 `RECHECK`로 source상 mapping된다.
- `allowed_link_actions`는 viewer/unmapped에 빈 배열, admin mapped row와 현재 동일 responsibility로
  assigned된 steward/developer에만 네 command를 노출한다. POST는 viewer, unmapped, stale ETag,
  idempotency conflict, spoofed authority, CR round/System drift를 거부하고 `CLEAR_PRIMARY` 및
  `REMOVE_CANDIDATE` 상태 fence를 유지한다. link command 전후 CR aggregate는 deep-equal evidence로
  불변이다.
- source/catalog 상태는 `SOURCE_NOT_CONFIGURED`, `SOURCE_AMBIGUOUS`, `CHECKPOINT_NOT_AVAILABLE`,
  `CHECKPOINT_INVALID`, `CAPTURE_PENDING`, `CONTIGUOUS_CAPTURE_RECORDED`의 명시 상태와 nullable watermark를
  사용하며 provider `LIVE`를 합성하지 않는다.
- `ChangeHistoryApi`는 기존 generic `ApiClient` transport만 사용하고 detail/link/access ETag,
  access `If-Match`, link `If-Match`와 `Idempotency-Key`, enum/문자열/배열 기본 bound를 확인한다.

### 차단 finding

#### F1 — typed timestamp malformed response가 fail closed하지 않음

`frontend/src/features/change-history/changeHistoryApi.ts:394`의 `timestamp()`는 문자열 길이 40 이하와
`Number.isFinite(Date.parse(value))`만 확인한다. Node probe에서 `"1"`, `"2026-08-11"`,
`"08/11/2026"`가 모두 finite로 판정됐다. 따라서 explicit UTC/ISO timestamp가 아닌 response도
event, weekly, summary, link history parser를 통과한다. acceptance 7의 timestamp 검증 및 malformed
response fail-closed 계약 위반이다.

같은 parser의 page bound도 `items.length <= 100`과 `limit in [1,100]`을 독립 검사할 뿐
`items.length <= limit`을 검사하지 않아 `limit=1`인 100-item response도 구조상 수용한다
(`changeHistoryApi.ts:193-200`). 이는 malformed response bound를 충분히 닫지 못한다.

#### F2 — ADR-0123 precision filter family 누락

ADR-0123은 event list에 category, precision, System, assignee, CR-link filter를 요구한다. server는
`week_start`, change type, category, operation, platform/database/schema, System, assignee, primary-link,
stage를 처리하지만 `precision` query를 읽거나 적용하지 않는다. `ChangeHistoryEventFilters`와
`ChangeHistoryApi.events()`에도 precision field가 없다. 따라서 “every filter family” 계약을 충족하지
못하며 focused server test 역시 precision filter를 exercise하지 않는다.

#### F3 — 추가 summary breakdown의 의미 모호성과 transaction contract 불일치

weekly `total_count`와 stage count는 transaction map을 사용하지만 summary의 `precision_counts`,
`category_counts`, `operation_counts`는 `frontend/poc-server.mjs:1139-1142`에서 `weekly.inWeek` semantic
row마다 증가한다. 이 builder 추가 breakdown의 count unit은 별도로 명시되지 않아 의미가 모호하며,
하나의 normalized transaction에서 여러 semantic row가 파생되면 동일 precision/category/operation
count가 증폭된다. 따라서 Task의 summary/weekly visible distinct normalized transaction 계약과 현재
구현은 일치하지 않는다. 현재 test fixture는 transaction당 한 row라 이 경우를 검증하지 않는다.

#### F4 — prescribed lint 실패

이 worker가 clean exact SHA에서 `npm run lint`를 두 번 실행했고 두 번 모두 다음 동일한 오류로
exit non-zero였다.

```text
frontend/src/features/change-history/changeHistoryApi.test.ts:106:30
@typescript-eslint/no-base-to-string
'calls[1]?.[1].body' may use Object's default stringification format ('[object Object]') when stringified

frontend/src/features/change-history/changeHistoryApi.ts:362:59
@typescript-eslint/no-unused-vars
'_label' is defined but never used
```

Control Plane의 첫 full-lint output capture는 불완전했다. 이후 같은 validation worktree에서 위 두
파일만 지정한 ESLint로 동일한 두 오류와 exit 1을 재현했다. 따라서 상충 PASS는 없으며 worker의
두 full-lint 실패와 Control Plane의 focused 재현을 함께 `FAIL_2_ERRORS`로 판정한다.

### coverage 한계

source mapping에는 cancelled와 resubmitted `IN_REVIEW`, cursor/total 구현이 존재하지만 focused server
fixture는 rejected만 직접 검증하고 cancelled, resubmitted round, multi-row transaction, cursor page
integrity 및 category/precision 각 filter를 별도 case로 exercise하지 않는다. 제품을 수정하거나
finding을 보수하지 않는 독립 검증 범위이므로 이 누락은 그대로 남긴다.

## Fresh 실행 결과

환경: macOS arm64 `26.5.2`, frontend shell Node `v25.9.0`, npm `11.12.1`.

| 명령 | 결과 |
|---|---|
| `cd frontend && npm ci` | PASS, 기존 lock으로 368 packages; `package-lock.json` SHA-256 `3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`, 추적 dependency diff 없음 |
| `npm run build:poc` (root-route suite 전) | PASS, 기존 500 kB chunk advisory만 발생 |
| `node --test poc-state-store.test.mjs poc-server.test.mjs` | `NOT_PASS_ENVIRONMENT`; 3분 이상 무출력/CPU 0/socket 0 정지, Control Plane이 이 Task PID 30935/30943에만 SIGTERM |
| bounded `node --test poc-state-store.test.mjs` | PASS, 12/12, 427.691 ms |
| bounded `node --test poc-server.test.mjs` | `NOT_PASS_ENVIRONMENT`, 120초 무출력 timeout |
| bounded `node --test --test-isolation=none --test-reporter=spec poc-server.test.mjs` | `NOT_PASS_ENVIRONMENT`, 첫 test `serves the POC at the root...` 진입 전 timeout |
| 동일 env import/create/listen/root/close 진단 | sandbox 내부 listen은 `EPERM`; Control Plane의 동일 cwd/env 직접 lifecycle one-liner는 즉시 PASS |
| Control Plane `node poc-server.test.mjs` 직접 실행 | PASS, 14/14, 약 1.13 s; Node v25.9.0 test-runner invocation 환경 finding과 제품 lifecycle을 분리함 |
| `npm run test:poc-server` | `NOT_PASS_ENVIRONMENT`; benchmark 1건 후 `poc-server*.test` runner가 같은 정지 상태, 진단 전환 시 종료 |
| focused Vitest | PASS, 2 files / 18 tests |
| `npm run lint` 첫 실행 | FAIL, 위 2 errors |
| `npm run lint` worker 재실행 | FAIL, 위 동일 2 errors |
| Control Plane focused ESLint 재현 | `CONTROL_PLANE_REPRODUCED_FAIL_2_ERRORS`, 동일 두 파일/오류, exit 1 |
| `npm run typecheck` | PASS |
| `npm run build:poc` 최종 | PASS, 기존 chunk advisory만 발생 |
| `git diff --check` / allowlist / hardcoding / secret review | PASS |

prescribed Node test-runner 비통과를 제품 lifecycle 결함이라고 주장하지 않는다. 그러나 prescribed
command 자체는 통과하지 않았으므로 `PASS`로 꾸미지 않고 `NOT_PASS_ENVIRONMENT`로 유지한다.
F1-F4와 coverage 누락 때문에 전체 local-source 판정은 환경 이슈와 무관하게 `FAIL`이다.

## 미실행과 남은 gate

- DEV provider/runtime, DataHub/Kafka/Schema Registry/PostgreSQL live probe: `NOT_EXECUTED`
- browser/UI runtime: `NOT_EXECUTED`
- PREP/OPS/TARGET: `NOT_EXECUTED`
- container/network/provider/runtime mutation: `NOT_EXECUTED`
- push/merge: `NOT_EXECUTED`
- G1/G2/G3/G4: `NOT_APPROVED`

후속 owner는 F1-F4와 누락 coverage를 별도 repair task에서 보수하고, 동일 prescribed Node runner를
지원 Node/toolchain 환경에서 다시 실행해야 한다. 이 독립 validator는 repair, push, merge 또는
gate 승인을 수행하지 않았다.
