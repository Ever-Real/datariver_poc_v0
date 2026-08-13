# CHANGE-HIST-T06B 독립 검증 증거

- 역할: `50_QUALITY_VALIDATION`
- 검증 시각: `2026-08-14 03:27 KST`
- exact candidate SHA: `cd459585d2c67a825b6d236745ea2a7e51dd49e7`
- product SHA: `e917bf382e79a672d52636d81b22cedb748d1263`
- 비교 기준 SHA: `49f7f5c8b1f75e9990a9fb13e4b990b7503d1c61`
- 종합 판정: **FAIL_LOCAL_SOURCE / INDEPENDENT_VALIDATION_FAIL / REPAIR_REQUIRED**
- 승인 상태: `G1-G4 NOT_APPROVED`

## 1. 범위와 provenance

시작 시 HEAD가 지정된 exact candidate SHA와 일치하고 작업 트리가 clean임을 확인했다. 제품 소스는
수정하지 않았다. `base..product` 제품 diff는 아래 허용된 6개 경로뿐이며, product 뒤 candidate
커밋은 기존 구현 evidence/receipt 2개만 추가한다.

- `frontend/poc-state-store.mjs`
- `frontend/poc-state-store.test.mjs`
- `frontend/poc-server.mjs`
- `frontend/poc-server.test.mjs`
- `frontend/src/poc/pocApi.ts`
- `frontend/src/poc/pocApi.live.test.ts`

package/lockfile, schema/init SQL/migration, dependency, service/container/framework, backend, 배포 설정은
변경되지 않았다. 제품 실행 코드의 추가 줄에서 deployment host/URL, UUID, 기본 user/System 식별자
literal도 확인되지 않았다. 테스트 fixture의 `business-system` 등은 서버 기본값이나 배포 식별자가
아니다.

## 2. 독립 소스 검토

| 검토 계약 | 판정 | 근거 |
|---|---|---|
| exact Catalog join과 System 해석 | PASS | ledger `asset_urn`을 current PostgreSQL Catalog `items[].id`와 exact 비교하고, 그 asset의 platform/database/schema를 active schema scope에 조인한다. platform을 business System ID로 사용하지 않는다. Catalog 문서 부재·기본 형식 오류·asset ID 중복은 503이다. exact asset/coordinates가 없거나 System이 미매핑·모호하면 assigned role에서 숨기고 mutation을 거부한다. |
| subject/role/assignment 권위 | PASS | server-configured subject와 저장 active subject를 교차 검증한다. inactive/unknown/mismatch와 browser header/query/body role/System/priority/actor/policy/basis/time spoof는 거부한다. admin은 전체, steward/developer는 현재 responsibility assignment System만, viewer는 read-only다. |
| assignee | PASS | active `DATA_STEWARD`, 다음 `DEVELOPER`의 unique minimum priority를 선택하고 동순위/미해결은 `UNASSIGNED`다. 검토된 OWNERSHIP owner-ref 추출 계약이 없어 provider owner fallback을 추측하지 않는다. |
| list/detail/reverse/link history/link/unlink | PASS | bounded keyset list/detail/reverse/history와 typed `SET_PRIMARY`, `CLEAR_PRIMARY`, `ADD_CANDIDATE`, `REMOVE_CANDIDATE` command가 존재한다. append-only link event fold가 current primary/candidates를 계산한다. |
| ETag/CAS/idempotency/동시성 | PASS | quoted `If-Match`, link-head hash, access/core/catalog version+canonical hash, ledger row lock, idempotency-key advisory transaction lock과 stored replay/conflict가 있다. 서로 다른 event의 동시 동일 key도 직렬화한다. |
| CR binding과 zero effect | PASS | 저장 CR의 current round ID/number, selected System 및 모든 current item routing System을 검증한다. link transaction은 core canonical hash를 다시 검사하고 `core.changeRecords`를 쓰지 않는다. 기존 state/round/revision/approval/transition에 효과가 없다. |
| weekly distinct/stage/sum | **FAIL** | distinct normalized transaction, source occurred time, candidate-only/primary conflict, inactive/rejected/cancelled primary의 unlinked 처리 및 합계 구조는 있으나, KST 월요일 검증이 잘못되어 주간 API 계약 전체가 차단된다. |
| POC client authority 전달 | PASS | logical path를 Node `/api/v1`로 전달하며 body/signal, `Idempotency-Key`, `If-Match`, response ETag를 보존한다. browser에서 권한·담당자·집계를 계산하지 않는다. |

## 3. 차단 finding

### F01 — BLOCKER — KST 월요일을 거부하고 KST 화요일을 허용

`frontend/poc-server.mjs:1004-1006`은 `week_start`를
`${weekStart}T00:00:00+09:00`로 만든 뒤 `start.getUTCDay() === 1`을 요구한다. KST 월요일 00:00은
UTC 일요일 15:00이므로 `getUTCDay()`는 `0`이고, 반대로 KST 화요일 00:00은 UTC 월요일 15:00이라
`1`이다. 따라서 ADR-0123의 `Asia/Seoul` 월요일 `[00:00, 다음 월요일 00:00)` 계약과 반대로 동작한다.

제품 파일을 바꾸지 않은 독립 HTTP probe 결과:

```text
2026-08-10 status=400 body={"code":"WEEK_START_INVALID",...}
2026-08-11 status=200 body={"week_start":"2026-08-11","week_end_exclusive":"2026-08-18",...}
```

`2026-08-10`은 KST 월요일이고 `2026-08-11`은 화요일이다. 이 결함은 유효한 주간 요청을 사용할 수
없게 하고 잘못된 cohort를 허용하므로 T06B 수용 조건을 차단한다.

- repair scope: `frontend/poc-server.mjs`의 KST local weekday 검증 및
  `frontend/poc-server.test.mjs`의 월요일 허용/화요일 거부 HTTP 회귀 테스트
- repair 비수행: 독립 검증 역할에 따라 제품 수정 없음

## 4. fresh 실행 결과

Node는 기존 프로젝트 관례에 맞춰 `/Users/everreal/.nvm/versions/node/v25.6.1/bin`을 사용했다.
새 worktree에 `node_modules`와 `dist-poc`가 없어 exact lockfile로 의존성을 설치했다.

| 순서 | 명령 | 결과 |
|---:|---|---|
| 1 | `npm ci --no-audit --no-fund` | PASS, 368 packages 설치; audit는 이 명령에서 미실행 |
| 2 | `node --test poc-state-store.test.mjs poc-server.test.mjs` | 초기 FAIL, 25/26; 제품 assertion이 아니라 미생성 `dist-poc` 때문에 root가 404 |
| 3 | `node --test poc-state-store.test.mjs` | PASS, 12/12 |
| 4 | `npm run test:poc-server` | 초기 FAIL, 32/33; 같은 미생성 `dist-poc` root 404 |
| 5 | `npx vitest run --config vitest.config.ts src/poc/pocApi.live.test.ts` | PASS, 14/14 |
| 6 | `npm run lint` | PASS, warning/error 0 |
| 7 | `npm run build:poc` | PASS, 기존 500 kB 초과 chunk advisory만 출력 |
| 8 | `node --test poc-state-store.test.mjs poc-server.test.mjs` | 빌드 후 동일 명령 PASS, 26/26 |
| 9 | `npm run test:poc-server` | 빌드 후 동일 명령 PASS, 33/33 |
| 10 | 독립 Node HTTP KST boundary probe | **FAIL contract**: 월요일 400, 화요일 200 |
| 11 | `git diff --check 49f7f5c8...e917bf38` | PASS |
| 12 | `git diff --check 49f7f5c8...cd459585` | PASS |

빌드 산출물 생성 뒤 지정 focused/full 테스트는 모두 성공했지만 F01을 검사하는 회귀 테스트가 없어
기존 suite의 녹색 결과가 KST 경계 결함을 발견하지 못했다. 검증을 약화하거나 실패 assertion을
변경하지 않았다.

## 5. 판정과 미실행 범위

exact candidate의 read/link 권위, scope, 동시성 및 CR zero-effect 구현은 정적 검토와 기존 suite를
통과했다. 그러나 필수 KST Monday boundary가 독립 HTTP probe에서 반대로 동작하므로 종합 판정은
`FAIL_LOCAL_SOURCE / REPAIR_REQUIRED`다.

- 실제 PostgreSQL/DataHub target runtime 통합: `NOT_EXECUTED`
- production workload/EXPLAIN/load/soak: `NOT_EXECUTED`
- PREP/OPS/TARGET: `NOT_EXECUTED`
- push/merge/publication: `NOT_EXECUTED`
- G1-G4: `NOT_APPROVED`

이 증거는 production readiness, runtime verification 또는 gate 승인을 주장하지 않는다.
