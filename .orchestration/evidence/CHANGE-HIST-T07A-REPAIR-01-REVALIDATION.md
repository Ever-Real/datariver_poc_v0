# CHANGE-HIST-T07A REPAIR-01 독립 재검증 증적

## 판정

- Task: `CHANGE-HIST-T07A-REPAIR-01-REVALIDATION`
- Task/dispatch: `task_109cde7f894c` / `ctx_4687756965c1`
- 역할: `50_QUALITY_VALIDATION`
- 검증일: `2026-08-14` KST
- exact base / 시작 HEAD: `1b79b8160fb3c94606ca4a2ead574e0a41b1e38f`
- candidate product SHA: `8c20d1da10279f4a5c3b25708ce0e73e89f0d3ca`
- repair base SHA: `8ec867f2cf020a5b2b2af57011353d53123e5321`
- 판정: **`PASS_LOCAL_SOURCE / INDEPENDENT_REVALIDATION_PASS`**
- 제품 파일은 수정하지 않았고 finding을 보수하지 않았다. 이 증적과 JSON receipt만 작성했다.
- `G1-G4 NOT_APPROVED`; 이 판정은 provider/runtime, browser, PREP, OPS, TARGET 또는 release 승인이 아니다.

원 독립 검증의 F1-F4는 exact candidate와 fresh 실행에서 모두 닫혔다. typed adapter는 server/store가
내보내는 canonical millisecond UTC만 수용하고 page/total/cursor 모순을 fail closed하며, precision은
닫힌 enum으로 authorization pruning 뒤 count/page 전에 적용된다. summary breakdown은 visible distinct
transaction별 dimension value를 한 번만 세고, full lint는 suppression/config 완화 없이 오류와 warning
0건으로 통과했다.

## SHA, ancestry와 변경 범위

검증 시작 작업트리는 clean이었고 `HEAD`는 exact base와 정확히 같았다. 다음 직계 ancestry를 확인했다.

```text
8ec867f2cf020a5b2b2af57011353d53123e5321  (repair base)
  -> 8c20d1da10279f4a5c3b25708ce0e73e89f0d3ca  (candidate product, 1 commit)
  -> 1b79b8160fb3c94606ca4a2ead574e0a41b1e38f  (candidate evidence/exact base, 1 commit)
```

repair base에서 candidate product까지의 diff는 정확히 다음 다섯 product path,
`175 insertions / 43 deletions`다.

1. `frontend/poc-server.mjs`
2. `frontend/poc-server.test.mjs`
3. `frontend/src/features/change-history/changeHistoryApi.test.ts`
4. `frontend/src/features/change-history/changeHistoryApi.ts`
5. `frontend/src/features/change-history/types.ts`

candidate product에서 exact base까지는 기존 REPAIR-01 evidence/receipt 두 파일만 추가됐다.
dependency/package/lock, schema/migration/data model, framework/service/container, UI component,
CR state/revision/approval/transition과 기존 external Monitoring 계약 변경은 없다. 제품 diff의
URL/localhost/credential/secret/token/private-key/deployment-hardcoding pattern 및 validation/security
suppression review에서 새 hardcoding, secret, raw pass-through, validator disable 또는 완화된 lint 설정을
찾지 못했다. `package.json`과 `package-lock.json` SHA-256은 각각
`f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`,
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`이며 추적 diff가 없다.
`git diff --check`는 product/evidence/working/staged 범위에서 통과했다.

## F1-F4 독립 재검증

### F1 — canonical timestamp와 page 진행 불변식: CLOSED

`ChangeHistoryApi.timestamp()`는 정확한 `YYYY-MM-DDTHH:mm:ss.sssZ` 정규식과
`Date#toISOString()` 동일성으로 canonical UTC millisecond만 수용한다. focused Vitest는 event,
weekly, summary, link-history surface에서 숫자형 문자열, date-only와 locale timestamp를 거부한다.
별도 read-only adapter probe는 숫자 값, 숫자형 문자열, date-only, locale 형식과 불가능한
`2026-02-30T00:00:00.000Z`를 모두 거부하고 canonical 값을 수용함을 확인했다.
store command timestamp는 `requireTimestamp()`에서 `toISOString()`으로 정규화되고 PostgreSQL
`timestamptz` read의 `Date` 및 server가 새로 만드는 시각도 JSON 경계에서 동일 형식으로 나온다.
따라서 adapter의 좁은 형식은 실제 server/store emission을 거부하지 않는다.

모든 typed page는 응답 `limit === request limit`, `items.length <= limit`, non-null next cursor이면
full page, next cursor와 request cursor 불일치, event `total >= items.length`를 검사한다. 첫 event
page에서는 `total > items.length`와 next cursor 존재가 정확히 일치해야 한다. focused Vitest와 별도
adapter probe가 overflow, short page + next cursor, 동일 cursor와 첫 page total/cursor 모순을
거부했고, first/last 두 valid page 진행은 거부하지 않았다. server `limit=1` fixture는 세 event를
마지막 null cursor까지 순회하여 중복 없는 세 ID, 응답 limit, item bound, 동일 total과 cursor 진행을
확인한다.

### F2 — precision enum, 적용 순서와 비가시 count: CLOSED

precision은 client type/filter, client runtime validator와 server query에서 ADR-0123의 닫힌 다섯 값만
수용한다. client의 unsupported 값은 transport 전 거부되고 server의 `GUESSED`는 400이다. server는
먼저 `changeHistoryCanRead`로 현재 권한에 따라 row를 pruning한 뒤 precision을 포함한 filter를 적용하고,
그 결과에서 `total`과 keyset page를 계산한다.

focused server test는 `EXACT_MCL` positive와 invalid precision을 실행한다. 별도 bounded loopback
negative는 assignment 없는 steward가 실제 `EXACT_MCL` row를 precision으로 조회해도
`total=0/items=0`이고, 동일 row를 현재 assignment 뒤에만 `total=1`로 관찰함을 확인하여 precision
filter가 숨겨진 row/count를 유출하지 않음을 재현했다.

### F3 — distinct transaction summary와 stage 의미: CLOSED

`changeHistorySummary()`는 weekly authorization-pruned in-week transaction map을 재사용한다.
각 transaction에서 precision/category/operation을 각각 `Set`으로 만든 뒤 dimension value당 최대 한 번만
증가시킨다. server fixture의 동일 transaction 세 semantic row는 두 category 값과 중복
DOCUMENTATION/EXACT_MCL/UPDATE를 포함하며 결과는 `TECHNICAL_SCHEMA=1`, `DOCUMENTATION=1`,
`EXACT_MCL=1`, `UPDATE=1`이다. 동시에 `event_count=3`, schema/metadata transaction count 각 1을
보존하므로 semantic event 수와 distinct transaction/dimension count를 섞지 않는다.

같은 fixture에서 weekly `total_count=1`, stage 합계 동일성, KST 월요일
`[2026-08-10, 2026-08-17)`, 재제출 round 2 `IN_REVIEW -> RECHECK`, `CANCELLED/REJECTED -> UNLINKED`를
확인했다. builder는 기존 `time_unknown_count`와 event count 계산을 바꾸지 않았고 candidate/non-primary
history, 동일 transaction의 여러 semantic row 또는 link row가 stage count를 증폭하지 않는다.

### F4 — full lint: CLOSED

`npm run lint`는 `eslint . --max-warnings=0`으로 exit 0, error 0, warning 0을 반환했다. candidate diff에
ESLint/TypeScript suppression, validator bypass 또는 relaxed config 변경은 없다. 함께 실행한
`npm run typecheck`도 exit 0이었다.

## 권한·회귀 source 검토

- access/core/catalog/ledger/link/source/checkpoint는 authoritative projection에서 읽고, catalog identity가
  누락·중복되거나 active subject가 불일치하면 fail closed한다.
- viewer는 read-only이고 link action이 비어 있다. steward/developer는 현재 동일 System의 해당
  responsibility assignment가 있는 row만 읽고 변경하며, 미할당·unmapped·stale mutation은 0 effect다.
- `allowed_link_actions`와 POST authority는 server가 현재 subject/System/assignment에서 계산한다.
  header/query/body authority spoof는 거부한다.
- link POST는 ETag/CAS, idempotency replay/conflict, current round와 routing System drift를 검증하고
  CR aggregate의 state/round/approval/transition을 쓰지 않는다. fixture의 command 전후 CR aggregate는
  동일하다.
- authoritative reverse lookup, event/detail/link page, source precision/checkpoint, KST week와 기존
  external route 계약은 full direct server 14/14 및 focused tests에서 회귀 없이 통과했다.

## Fresh 실행 결과

환경은 macOS arm64 `26.5.2`, NVM Node `v25.6.1`, npm `11.9.0`이다.

| 명령 | 결과 |
|---|---|
| `npm ci --offline --no-audit --no-fund` | PASS, 기존 lock/cache로 368 packages; package/lock 추적 diff 없음 |
| root route test 전 `npm run build:poc` | PASS; 기존 500 kB chunk advisory만 존재 |
| `/Users/everreal/.nvm/versions/node/v25.6.1/bin/node poc-server.test.mjs` | PASS, 14/14, 956.868 ms |
| generic `--test-name-pattern=change-history` sandbox 시도 | `NOT_PASS_ENVIRONMENT`; 67.963초 동안 무출력 뒤 worker 중단, pending Promise/cancelled 1로 종료 |
| coordinator 지정 exact `--test-name-pattern='serves authoritative change-history reads'` | PASS, 1/1, 373.750 ms; 허용된 loopback 경계에서 1회만 실행 |
| focused Vitest `changeHistoryApi + pocApi.live` | PASS, 2 files / 22 tests |
| canonical timestamp/page read-only adapter probe | PASS; canonical 및 valid two-page 수용, numeric/date-only/locale/impossible 및 네 page 모순 거부 |
| precision visibility/count read-only loopback probe | PASS; hidden `0/0`, assigned visible `1/1`, invalid precision 400 |
| `npm run lint` | PASS, error 0 / warning 0 |
| `npm run typecheck` | PASS |
| 최종 `npm run build:poc` | PASS; 기존 chunk advisory만 존재 |
| `git diff --check`, allowlist, hardcoding/secret/suppression review | PASS |

generic pattern의 sandbox/runner 정지는 full direct 14/14와 exact focused 1/1 product 결과와 분리하여
`NOT_PASS_ENVIRONMENT`로 유지한다. 선행 독립 검증의 Homebrew Node `v25.9.0` prescribed-runner 정지도
동일하게 별도 알려진 환경 이슈이며, 이 worker는 test를 바꾸거나 이를 PASS로 재분류하지 않았다.

## 미실행과 남은 gate

- DEV provider/runtime 및 DataHub/Kafka/Schema Registry/PostgreSQL live probe: `NOT_EXECUTED`
- browser/UI runtime: `NOT_EXECUTED`
- PREP/OPS/TARGET: `NOT_EXECUTED`
- container/network/provider/runtime mutation: `NOT_EXECUTED`
- push/merge/publication: `NOT_EXECUTED`
- `G1/G2/G3/G4`: `NOT_APPROVED`

따라서 F1-F4와 요구된 local-source 회귀는 독립적으로 닫혔지만, 이 결과를 production, target 또는
provider runtime claim으로 확장하지 않는다.
