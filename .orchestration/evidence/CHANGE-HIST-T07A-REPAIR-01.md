# CHANGE-HIST-T07A REPAIR-01 보수 증거

## 범위와 provenance

- 작업: `CHANGE-HIST-T07A-REPAIR-01` / `task_cac5144cbf16`
- dispatch: `ctx_ccb2f0a28025`
- 역할: `40_DATA_AI_KNOWLEDGE Builder`
- 위험 표기: `R2 REPAIR-01`이며 gate 승인 또는 위험 등급 완화가 아님
- exact base SHA: `8ec867f2cf020a5b2b2af57011353d53123e5321`
- 원 candidate product SHA: `ef4adbe151901a72d159c8ba565310dc25b4a898`
- repair product commit: `8c20d1da10279f4a5c3b25708ce0e73e89f0d3ca`
- 판정: `PASS_LOCAL_SOURCE_REPAIR_PENDING_INDEPENDENT_VALIDATION`
- 승인 상태: `G1-G4 NOT_APPROVED`

시작 HEAD는 요구된 exact base와 일치했고 작업 트리는 clean이었다. 제품 변경은 허용된 다섯 경로에만
한정했으며 dependency/lockfile, schema/migration, framework/service/container, UI component,
CR state/revision/approval/transition과 기존 Monitoring 구조는 변경하지 않았다.

## F1-F4 보수 내용

1. F1: typed adapter timestamp는 이제 정확히 `YYYY-MM-DDTHH:mm:ss.sssZ` 형식이고
   `Date#toISOString()` round trip이 동일한 canonical UTC 값만 수용한다. date-only, 숫자형 문자열,
   locale 형식과 달력상 정규화되는 잘못된 값을 fail closed한다. 모든 page는 응답 `limit`이 요청값과
   같고 `items.length <= limit`이며, 다음 cursor가 있으면 full page이고 요청 cursor와 같지 않아야
   한다. event 첫 page의 `total/items/next_cursor` 관계도 함께 검증한다.
2. F2: 닫힌 precision enum을 `ChangeHistoryEventFilters`, typed query adapter와 server query에
   끝까지 연결했다. 지원하지 않는 값은 transport 전에 typed adapter가 거부하고 server도 400으로
   거부한다. server는 기존 authorization pruning이 끝난 visible row에 precision을 적용한 뒤
   `total`과 keyset page를 계산한다.
3. F3: summary의 `precision_counts`, `category_counts`, `operation_counts`는 주간 visible transaction
   map을 재사용한다. 각 `normalized_change_transaction_id`에서 각 dimension 값을 Set으로 한 번만
   세므로 동일 transaction의 여러 semantic row가 count를 증폭하지 않는다. `total_count`와
   `time_unknown_count` 및 stage 합계 불변식은 그대로다.
4. F4: 테스트 body는 먼저 string임을 증명한 뒤 JSON parse하고, 사용하지 않던 identifier label
   인자를 제거했다. ESLint rule이나 validator를 disable/완화하지 않았다.

focused coverage는 세 가지 비정규 timestamp를 event/weekly/summary/link-history 모든 parser에서
거부하고, page overflow와 short-page cursor 모순을 거부한다. server fixture는 동일 transaction의
세 semantic row와 중복 category/operation/precision을 검증하고, `limit=1` cursor를 마지막 page까지
진행해 3개 event가 중복 없이 반환됨을 확인한다. precision valid/invalid, 재제출 round의
`IN_REVIEW → RECHECK`, `CANCELLED → UNLINKED`, 기존 rejected/link CAS/idempotency/zero-effect 회귀도
같은 bounded test에서 확인했다.

## 실행 증거

환경은 macOS arm64 `26.5.2`다. frontend gate와 loopback 직접 server 비교는 NVM Node `v25.6.1`,
npm `11.9.0`을 명시했다. 작업트리의 불완전한 `node_modules` 때문에 최초 `npx` 두 호출은 registry
DNS `ENOTFOUND`였고 제품 실행 전 실패였다. 기존 lock/cache만 사용하는
`npm ci --offline --no-audit --no-fund`로 368 packages를 설치했으며 package/lock 추적 diff는 없다.

| 명령 | 결과 |
|---|---|
| exact base Node 25.6.1 focused server 동일-binary 비교 | `PASS`, 1/1, 439 ms; 같은 base 즉시 반복도 1/1, 290 ms |
| repair candidate Node 25.6.1 focused server 동일-binary 비교 | `PASS`, 1/1, 319 ms |
| build 전 `node poc-server.test.mjs` 직접 실행 | change-history 포함 13/14 PASS; `dist-poc` 부재로 root static route만 404 |
| `npm run build:poc` | `PASS`; 기존 500 kB 초과 chunk advisory만 존재 |
| build 후 `node poc-server.test.mjs` 직접 실행 | `PASS`, 14/14, 약 957 ms |
| focused Vitest 두 파일 | `PASS`, 2 files / 22 tests |
| `npm run lint` | `PASS`, exit 0, warning/error 0 |
| `npm run typecheck` | `PASS`, exit 0 |
| `git diff --check`와 product allowlist review | `PASS`, 정확히 허용된 5 product paths |
| package/lock SHA-256 | package `f331ee0a...28f6f`, lock `3fdccef4...7a0ca`; 변경 없음 |

build 전 root 404는 candidate source failure가 아니라 정적 산출물 선행 조건이며 동일 source를 build한
뒤 전체 14/14가 통과했다. 새 fixture는 기존 test의 `finally` server close를 그대로 사용하고,
base/candidate focused test와 candidate 전체 직접 실행이 모두 1초 안에 종료되어 close 누락 또는
assertion 전 제품 hang을 배제했다.

## Node/Orca 환경 및 lifecycle 기록

독립 검증에서 기록한 Homebrew Node `v25.9.0`의 prescribed `node --test` 무출력 정지는
`NOT_PASS_ENVIRONMENT`로 유지한다. 이 repair에서도 Orca sandbox 안의 Homebrew Node `v25.9.0`
직접 server와 명시적 NVM Node `v25.6.1` 직접 server가 listen 전 무출력 상태가 되어 bounded
중단했지만, 같은 NVM binary의 loopback 허용 실행은 base/candidate focused와 candidate 14/14를
즉시 통과했다. 따라서 test를 변경하거나 결과를 PASS로 위장하지 않고, sandbox/runner 환경과 제품
lifecycle을 분리했다. `npm run test:poc-server` 전체 provider/router runner는 Control Plane의 재시도
중단 지시에 따라 이 repair에서 `NOT_EXECUTED`이며 direct server와 focused Vitest 결과를 그 명령의
PASS로 대체하지 않는다.

Orca runtime은 시작 시 `stale_bootstrap/not_running`이었고 heartbeat delivery가 실패했다. 한 번의
`orca open` 뒤에도 lifecycle delivery가 실패했으며, Control Plane의 명시 지시에 따라 추가 open,
health-check와 heartbeat 재시도는 중단했다. 제품 repair와 local source 검증에는 이 장애를 gate
승인이나 예외로 사용하지 않았다.

## 미실행과 잔여 gate

- DEV provider/runtime, DataHub/Kafka/Schema Registry/PostgreSQL live probe: `NOT_EXECUTED`
- browser/UI runtime: `NOT_EXECUTED`
- PREP/OPS/TARGET: `NOT_EXECUTED`
- container/network/provider/runtime mutation: `NOT_EXECUTED`
- push/merge/publication: `NOT_EXECUTED`
- `G1/G2/G3/G4`: `NOT_APPROVED`

남은 작업은 repair product/evidence의 fresh 독립 검증과 지원 runner 환경의 prescribed 전체 suite다.
이 worker는 push, merge, runtime delivery, PREP, OPS, TARGET 또는 gate 승인을 수행하지 않았다.
