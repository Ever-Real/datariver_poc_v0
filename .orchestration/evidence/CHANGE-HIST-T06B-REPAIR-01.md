# CHANGE-HIST-T06B REPAIR-01 KST 주간 경계 보수 증거

## 범위와 provenance

- 역할: `30_IDENTITY_ACCESS Builder`
- 검증 시각: `2026-08-14 03:34 KST`
- exact base SHA: `f025fb60d07ddacf0c3ad7bcaa76872539143512`
- product SHA: `5521bead52d8b923e772f735352d3046327e7140`
- 판정: `REPAIRED_SELF_VALIDATED_PENDING_INDEPENDENT_VALIDATION`
- 대상 finding: `CHANGE-HIST-T06B-INDEPENDENT-VALIDATION F01`
- 승인 상태: `G1-G4 NOT_APPROVED`

시작 시 HEAD가 exact base와 일치하고 작업 트리가 clean임을 확인했다. 허용된 제품 경로인
`frontend/poc-server.mjs`, `frontend/poc-server.test.mjs`만 변경했다. dependency, package/lockfile,
schema/migration, backend, UI, service/container, 기존 권한·집계 계약은 변경하지 않았다.

## F01 보수

기존 구현은 KST 자정 instant에 `getUTCDay()`를 적용하여 KST 월요일을 일요일로, KST 화요일을
월요일로 판정했다. 보수 구현은 다음 경계를 유지한다.

1. `YYYY-MM-DDT00:00:00+09:00` instant를 고정 KST 오프셋으로 달력 날짜에 정규화한 뒤 입력 문자열과
   exact 비교한다. 따라서 존재하지 않는 날짜를 허용하지 않는다.
2. 정규화한 KST day number를 Unix calendar의 Monday-zero 산술로 변환한다. UTC weekday API나
   host locale에 의존하지 않으며 제품 코드에 특정 날짜를 넣지 않는다.
3. 동일한 고정 오프셋 기반 ISO date 변환으로 `week_end_exclusive`를 계산한다. 기존
   `[KST 월요일 00:00, 다음 월요일 00:00)` 집계 구간과 `Asia/Seoul` 응답 계약은 유지한다.

HTTP 회귀 테스트는 `2026-08-10` 요청이 `200`이고 `week_end_exclusive=2026-08-17`임을 확인하며,
`2026-08-11` 요청이 `400 WEEK_START_INVALID`로 거부됨을 확인한다. 기존 distinct transaction,
stage 합계, rejected primary의 unlinked 판정 assertion은 유효한 월요일 입력으로 그대로 수행한다.

## 실행 검증

새 worktree에 `node_modules`와 `dist-poc`가 없어 exact lockfile로
`npm ci --no-audit --no-fund`를 실행해 368 packages를 설치했다. 추적 package/lockfile 변경은 없다.
검증 환경은 macOS arm64, Node `v25.9.0`, npm `11.12.1`이다.

| 구분 | 명령 | 결과 |
|---|---|---|
| focused server | `node --test --test-name-pattern='serves authoritative change-history reads' poc-server.test.mjs` | `PASS`, 1/1 |
| POC build | `npm run build:poc` | `PASS`; 기존 500 kB 초과 chunk advisory만 출력 |
| full server | `npm run test:poc-server` | `PASS`, 33/33 |
| frontend lint | `npm run lint` | `PASS`, exit 0, warning/error 0 |
| whitespace/allowlist | `git diff --check`, 변경 경로 확인 | `PASS`, 허용된 제품 2개 경로만 변경 |

제품 diff는 2 files, 18 insertions, 5 deletions이다. 검증을 약화하거나 기존 assertion을 제거하지 않았다.

## 미실행 범위와 잔여 gate

- 실제 PostgreSQL/DataHub target runtime 통합: `NOT_EXECUTED`
- production workload/EXPLAIN/load/soak: `NOT_EXECUTED`
- PREP/OPS/TARGET 및 active runtime mutation: `NOT_EXECUTED`
- push/merge/publication: `NOT_EXECUTED`
- G1/G2/G3/G4 승인: `NOT_APPROVED`

F01의 로컬 repair blocker는 없으며 exact evidence candidate에 대한 fresh independent validation이 남아 있다.
