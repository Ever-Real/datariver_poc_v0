# CHANGE-HIST-T07B2A 독립 검증 증적

## 판정

- 역할: `50_QUALITY_VALIDATION` (제품 read-only, finding repair 금지)
- 검증일: `2026-08-14` KST
- 시작 HEAD / exact candidate:
  `c1662a5674cca2f7bda0c77d2acb7206462b82bd` (시작 시 clean)
- 제품 SHA: `5493517466334557c9de57bd15f28a43ff73ff4f`
- builder base SHA: `bdd96fb02762aa8d510ec3021a14212a83c4a125`
- 판정: **`PASS_LOCAL_SOURCE / INDEPENDENT_VALIDATION_PASS`**
- 다음 단계: `PENDING_T09_AUDIT`

제품 파일은 수정하지 않았다. 이 판정은 exact local source와 지정된 정적/focused gate에 대한 독립
검증이다. browser/runtime/provider/DB/container, PREP/OPS/TARGET 또는 release 승인이 아니며,
`G1-G4`는 모두 `NOT_APPROVED`다.

## SHA, ancestry와 변경 범위

다음 직계 ancestry를 확인했다.

```text
bdd96fb02762aa8d510ec3021a14212a83c4a125  (builder base)
  -> 5493517466334557c9de57bd15f28a43ff73ff4f  (product, 1 commit)
  -> c1662a5674cca2f7bda0c77d2acb7206462b82bd  (builder evidence, 1 commit)
```

builder base에서 product까지의 diff는 정확히 다음 Governance 다섯 경로,
`748 insertions / 0 deletions`다.

1. `frontend/src/features/governance/GovernancePage.tsx`
2. `frontend/src/features/governance/GovernancePage.test.tsx`
3. `frontend/src/features/governance/DetectedChangeCrPanel.tsx`
4. `frontend/src/features/governance/DetectedChangeCrPanel.test.tsx`
5. `frontend/src/features/governance/changeHistoryCr.css`

product에서 시작 HEAD까지는 builder evidence/receipt 두 경로,
`123 insertions / 0 deletions`만 추가됐다.

1. `.orchestration/evidence/CHANGE-HIST-T07B2A-WEEKLY-LINK-UI.md`
2. `.orchestration/receipts/CHANGE-HIST-T07B2A-WEEKLY-LINK-UI.json`

dependency/package/lock, `ChangeHistoryApi`/type/server, schema/migration, service/container, 기존 CR
state/revision/approval/transition, 기존 global CSS 파일 변경은 없다. 새 CSS의 selector도
`detected-change-*` 아래로 한정된다. `frontend/package.json`과 `frontend/package-lock.json` SHA-256은
각각 `f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`,
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`이며 base/product/candidate 사이에
변경이 없다.

## 요구사항별 독립 검토

### 서버 주간 집계와 정확한 일곱 filter

- 현재 시각을 `Asia/Seoul` calendar date로 변환한 뒤 실제 월요일을 계산하며 fixed 날짜가 없다.
- 일곱 카드는 weekly 응답의 `total_count`, `unlinked_count`, `received_count`, `recheck_count`,
  `testing_count`, `final_review_count`, `completed_count`를 그대로 표시한다. browser-side count나
  authorization 집계가 없다.
- 전체는 `week_start + limit=50`, CR 미연결은 `week_start + link_state=UNLINKED + limit=50`, 나머지
  다섯 카드는 각각 `stage=RECEIVED|RECHECK|TESTING|FINAL_REVIEW|COMPLETED + limit=50`만 전송한다.
  CR 미연결 요청에는 `stage`가 없다.
- 모든 read는 기존 typed `ChangeHistoryApi`의 `no-store` 경로를 사용한다. 새 API/type/server 구현,
  raw fetch, local data authority 또는 provider 추정이 없다.

### fresh ETag, 허용 action과 current-round 대상

- 행 선택 때 event detail과 CR link history를 함께 새로 읽는다. 어느 ETag라도 없거나 두 값이 exact
  equality를 만족하지 않으면 detail을 만들지 않고 mutation UI를 fail closed한다.
- action selector는 fresh event의 `allowed_link_actions`만 렌더링한다. 빈 배열인 viewer/no-action
  응답은 selector, target, reason, submit control을 모두 숨긴다.
- `SET_PRIMARY`와 `ADD_CANDIDATE`는 현재 server-returned Governance summary window의
  `id/current_round_number`만 대상에 넣는다. `CLEAR_PRIMARY`와 `REMOVE_CANDIDATE`는 이 목록을 fresh
  primary/candidate와 다시 exact 교차하므로 숨겨진 CR과 과거 round를 선택할 수 없다.
- 네 command는 `action`, `change_request_id`, `change_request_round`, trimmed `reason`만 보낸다. 검증한
  fresh event/link-head ETag를 `If-Match`에 넣고 각 명시적 submit마다 `crypto.randomUUID()`로 새
  `Idempotency-Key`를 만든다. actor/role/System/time/policy/basis를 만들거나 전송하지 않는다.

### zero-effect, 성공 refetch와 기존 CR 회귀

- submit 전 또는 진행 중 primary/candidate/list/weekly를 바꾸는 optimistic mutation이 없다.
- command 실패와 stale ETag 실패는 기존 authoritative detail/list/weekly와 입력을 보존하고 자동
  refetch/retry를 하지 않는다.
- command 성공 뒤 event, links, weekly, 현재 filter의 list 네 read가 모두 완료되고 fresh ETag equality가
  다시 성립한 뒤에만 화면 상태와 form을 교체한다. refetch 하나라도 실패하면 중간 state 적용이 없다.
- `GovernancePage` 변경은 새 panel import/mount뿐이며 기존 상세/생성/revision/attachment/approval/
  transition/apply 로직은 변경하지 않았다. exact Governance 68-test suite가 기존 흐름을 함께 통과했다.

### 상태, abort, KST와 접근성

- initial loading, authorized empty, weekly/list error, detail loading/ETag error, viewer/no actions,
  current-round target 없음, saving 상태가 서로 구분된다. 오류는 기존 `ErrorNotice`의 `role=alert`,
  loading은 `role=status`를 사용한다.
- list refresh/filter 전환은 직전 list controller를 abort하고, event detail 전환은 직전 detail controller를
  abort한다. unmount와 API client 교체에 따른 effect cleanup도 진행 중 list/detail read를 abort하며,
  aborted result는 state에 반영하지 않는다.
- filter button은 native button과 `aria-pressed`, panel은 `aria-labelledby`/`aria-busy`, table은 caption,
  form control은 label을 제공한다. 표시 시각은 `Asia/Seoul`로 format한다.

## 구체적 비차단 debt

1. `DetectedChangeCrPanel.tsx` 306줄은 load/detail/mutation/refetch, filter/target derivation과 presentation을
   한 component에 모은다. 특히 command와 성공 뒤 네 refetch에는 별도 `AbortController`가 없어 unmount나
   API client 교체가 일어나면 generic client의 security-context fence에 의존해 stale state 적용을 막는다.
   현재 local source 계약과 테스트에서는 correctness failure가 재현되지 않았지만, list/detail과 같은
   explicit cancellation/intent fence를 적용하면 lifecycle reasoning이 더 단순해진다.
2. `DetectedChangeCrPanel.test.tsx` 413줄은 exact filters, 네 command, stale 실패와 refetch call count를
   강하게 고정하지만, list/detail abort signal, command 성공 후 refetch 하나의 실패, refetch 결과의 실제
   화면 채택은 직접 exercise하지 않는다. 제품 source는 Promise-all 뒤 일괄 state 교체로 중간 적용을
   막으므로 현재 blocker는 아니며 후속 coverage debt다.

두 항목은 새 dependency/framework/authority나 현재 동작 위반을 만들지 않아 **nonblocking
maintainability/coverage debt**로 분류했다. 이 read-only 검증에서 보수하지 않았다.

## Fresh 실행 결과

환경은 macOS arm64 `26.5.2`, Node `v25.9.0`, npm `11.12.1`이다. 시작 시
`frontend/node_modules`가 없는 상태에서 설치했다.

| 명령 | 결과 |
|---|---|
| `npm --prefix frontend ci --offline --no-audit --no-fund` | PASS, 기존 lock/cache로 368 packages; 추적 dependency 변경 없음 |
| `npm --prefix frontend test -- --run src/features/governance/DetectedChangeCrPanel.test.tsx src/features/governance/GovernancePage.test.tsx` | PASS, 2 files / 41 tests |
| `cd frontend && npm test -- --run src/features/governance/*.test.ts src/features/governance/*.test.tsx` | PASS, exact Governance 5 files / 68 tests |
| `npm --prefix frontend test -- --run src/features/governance --reporter=verbose` | PASS, 추가 prefix diagnostic 10 files / 91 tests (`governance-documents` 포함) |
| `npm --prefix frontend run lint` | PASS, error 0 / warning 0 |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build:poc` | PASS; 기존 500 kB 초과 chunk advisory만 존재 |
| `git diff --check` (base-product, product-candidate, base-candidate, working/staged) | PASS |
| exact 5 product + 2 builder evidence allowlist와 package hash 검토 | PASS |

## 미실행과 남은 gate

- browser/runtime/credentialless smoke: `NOT_EXECUTED`
- 실제 DataHub/Timeline/MCL/PostgreSQL/provider/DB probe 또는 mutation: `NOT_EXECUTED`
- container/service/network/volume/process mutation: `NOT_EXECUTED`
- PREP/OPS/TARGET: `NOT_EXECUTED`
- push/merge: `NOT_EXECUTED`
- repository 전체 test suite: `NOT_EXECUTED` (지정 Governance focused suite만 실행)
- `G1/G2/G3/G4`: `NOT_APPROVED`
- 다음 단계: `T09_AUDIT`, 위 lifecycle/coverage debt의 후속 정리
