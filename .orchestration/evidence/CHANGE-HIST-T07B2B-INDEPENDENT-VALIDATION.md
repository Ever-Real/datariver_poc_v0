# CHANGE-HIST-T07B2B 독립 검증 증적

## 판정

- 역할: `50_QUALITY_VALIDATION` (제품 read-only, finding repair 금지)
- 검증일: `2026-08-14` KST
- 시작 HEAD / exact candidate:
  `5735efffcc057859bd780ed3d9e86009e5cbdf17` (시작 시 clean)
- 제품 SHA: `c87df404645b62e0a79ba41f99486c403ba92abb`
- base SHA: `3b2ad95efdab74be361b3c1663728929ba55ae66`
- 판정: **`PASS_LOCAL_SOURCE / INDEPENDENT_VALIDATION_PASS`**
- 다음 단계: `PENDING_T09_AUDIT`

제품 파일은 수정하지 않았다. 이 판정은 exact local source와 지정된 정적/focused gate에 대한 독립
검증이다. browser/runtime/provider/DB/container, PREP/OPS/TARGET 또는 release 승인이 아니며,
`G1-G4`는 모두 `NOT_APPROVED`다.

## SHA, ancestry와 변경 범위

다음 직계 ancestry를 확인했다.

```text
3b2ad95efdab74be361b3c1663728929ba55ae66  (base)
  -> c87df404645b62e0a79ba41f99486c403ba92abb  (product, 1 commit)
  -> c3804a3e728accc967178fff2dc63ef4f1915959  (builder evidence, 1 commit)
  -> 5735efffcc057859bd780ed3d9e86009e5cbdf17  (receipt rename repair, 1 commit)
```

base에서 product까지의 diff는 정확히 다음 Governance 두 경로, `233 insertions / 0 deletions`다.

1. `frontend/src/features/governance/ChangeRequestDetailDialog.tsx` (`85 / 0`)
2. `frontend/src/features/governance/GovernancePage.test.tsx` (`148 / 0`)

product에서 builder evidence commit은 evidence와 당시 잘못 배치된 receipt 두 파일만 추가했다. 최종
candidate의 repair commit은
`.orchestration/evidence/CHANGE-HIST-T07B2B-CR-REVERSE-HISTORY.receipt.json`을
`.orchestration/receipts/CHANGE-HIST-T07B2B-CR-REVERSE-HISTORY.json`으로 내용 변경 없이 `R100`
rename했다. 따라서 base에서 candidate까지는 위 제품 두 경로와 최종 evidence/receipt 두 경로뿐이다.

dependency/package/lock, 기존 `ChangeHistoryApi`/type/server, schema/migration, service/container 및 CSS
변경은 없다. `frontend/package.json`과 `frontend/package-lock.json` SHA-256은 각각
`f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`,
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`이며
base/product/candidate 사이에 동일하다.

## 요구사항별 독립 검토

### exact CR read와 stale response fence

- `ChangeRequestDetailDialog`가 열려 있고 서버 상세 `value.id`가 존재할 때만 기존 typed
  `ChangeHistoryApi.reverseHistory(value.id, { limit: 50, signal })`를 호출한다. 상세가 아직 없거나
  닫힌 상태에서는 호출하지 않고 이력 상태를 초기화한다.
- open 상태, 정확한 `value.id`, memoized API client가 effect dependency다. 닫기, CR ID 변경, client
  변경과 unmount cleanup은 진행 중 controller를 abort한다.
- 각 요청은 증가하는 intent와 `reverseHistoryCurrentId` exact equality를 함께 확인한 뒤에만 data,
  error, loading 상태를 채택한다. 늦게 완료된 이전 CR 응답은 화면에 반영되지 않는다.
- 기존 `ChangeHistoryApi.reverseHistory`가 response의 `change_request_id`, `limit`, page bound와 각 typed
  event를 검증하고 `cache: no-store`로 요청하는 계약을 재사용한다.

### 독립 상태와 읽기 전용 표시

- reverse-history loading, error, authorized empty와 data는 기존 CR detail의 `loading/error/value`와
  별도 state다. 이력 조회가 403/일반 오류/404를 반환해도 CR `value`를 지우거나 dialog를 닫지 않고,
  기존 detail header, workflow, revision/approval/attachment/action UI는 유지된다.
- 로딩은 `role=status`, 오류/404는 기존 `ErrorNotice`의 `role=alert`, 성공한 빈 결과는 별도 empty 문구로
  구분한다. focused test는 loading, 일반 403 denial, empty와 stale close/switch를 직접 검증한다.
- 서버 page에서 최대 50행만 표시하며 mutation control은 없다. 브라우저 집계, 로컬 권한 판단,
  provider fetch, raw fetch, credential 또는 신규 API authority를 추가하지 않았다.
- 각 행은 category/operation, asset URN/entity key, server-returned current stage/current primary를
  표시한다. `source_occurred_at`이 있으면 이를 사용하고, null이면 `detected_at`을 사용하면서 대체임을
  명시한다. 표시 timezone은 고정 `Asia/Seoul`이다.

### 기존 CR 회귀와 금지 범위

- 제품 diff는 두 파일 모두 additive-only다. 기존 CR state mapping, transition, revision round,
  approval/test approval, attachment upload/download/page, action dispatch와 apply report 코드를 삭제하거나
  변경하지 않았다.
- exact Governance suite `5 files / 73 tests`가 신규 reverse-history 5개 시나리오와 기존 생성,
  revision, approval, attachment, transition/action 회귀를 함께 통과했다.
- API/type/server/dependency/lock/CSS, runtime/provider/DB/container/PREP/OPS/TARGET를 변경하거나
  조회하지 않았고 push/merge를 수행하지 않았다.

## Fresh 실행 결과

환경은 macOS arm64 `26.5.2` (`Darwin 25.5.0`), Node `v25.9.0`, npm `11.12.1`이다. 시작 시
`frontend/node_modules`가 없는 상태에서 설치했다.

| 명령 | 결과 |
|---|---|
| `npm --prefix frontend ci --offline --no-audit --no-fund` | PASS, 기존 lock/cache로 368 packages; 추적 dependency 변경 없음 |
| `cd frontend && npm test -- --run src/features/governance/*.test.ts src/features/governance/*.test.tsx` | PASS, exact Governance 5 files / 73 tests |
| `npm --prefix frontend run lint` | PASS, error 0 / warning 0 |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build:poc` | PASS; 기존 500 kB 초과 chunk advisory만 존재 |
| `git diff --check` (base-product, product-candidate, base-candidate, working/staged) | PASS |
| exact 2 product + 2 final builder evidence allowlist와 package hash 검토 | PASS |

## 비차단 coverage debt

1. focused test는 일반 403 denial이 CR dialog를 닫거나 실패시키지 않는 점을 직접 고정하지만, 404
   problem을 별도 case로 실행하지 않는다. source는 모든 non-remediation `ApiError`를 동일한 독립
   `ErrorNotice`로 표시하므로 현재 correctness blocker는 아니다.
2. focused test는 null `source_occurred_at`의 명시적 `detected_at` fallback과 KST를 직접 검증하지만,
   non-null `source_occurred_at` 우선 선택 case는 source review로 확인했다. 삼항 선택과 고정 timezone이
   단순·명시적이어서 현재 blocker는 아니다.

이 검증에서는 위 coverage debt를 보수하지 않았다.

## 미실행과 남은 gate

- browser/runtime/credentialless smoke: `NOT_EXECUTED`
- 실제 DataHub/Timeline/MCL/PostgreSQL/provider/DB probe 또는 mutation: `NOT_EXECUTED`
- container/service/network/volume/process mutation: `NOT_EXECUTED`
- PREP/OPS/TARGET: `NOT_EXECUTED`
- push/merge: `NOT_EXECUTED`
- repository 전체 test suite: `NOT_EXECUTED` (지정 Governance suite만 실행)
- `G1/G2/G3/G4`: `NOT_APPROVED`
- 다음 단계: `T09_AUDIT`, 위 coverage debt의 후속 보강
