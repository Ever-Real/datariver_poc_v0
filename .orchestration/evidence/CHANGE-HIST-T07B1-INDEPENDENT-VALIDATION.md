# CHANGE-HIST-T07B1 독립 검증 증적

## 판정

- Task/dispatch: `task_8e07a0ac4ad5` / `ctx_126e2af39bff`
- 역할: `50_QUALITY_VALIDATION` (제품 read-only, finding repair 금지)
- 검증일: `2026-08-14` KST
- 시작 HEAD: `2ebcbfaa3905d537c935d671652cc4b6b635adf1` (시작 시 clean)
- 제품 SHA: `06aeeedc8142254e2b96e1eaaf67e25da9964362`
- builder base SHA: `fead4c4f6dfe507359be1c9eccb558518ab33787`
- 판정: **`PASS_LOCAL_SOURCE / INDEPENDENT_VALIDATION_PASS`**
- 다음 단계: `PENDING_T09_AUDIT`

제품 파일은 수정하지 않았다. 이 판정은 지정된 local source와 focused gate에 대한 독립 검증이며,
browser/provider/DB/runtime, PREP/OPS/TARGET 또는 release 승인이 아니다. `G1-G4`는 모두
`NOT_APPROVED`다.

## SHA, ancestry와 변경 범위

다음 직계 ancestry를 확인했다.

```text
fead4c4f6dfe507359be1c9eccb558518ab33787  (builder base)
  -> 06aeeedc8142254e2b96e1eaaf67e25da9964362  (product, 1 commit)
  -> 2ebcbfaa3905d537c935d671652cc4b6b635adf1  (builder evidence, 1 commit)
```

builder base에서 product까지의 diff는 정확히 다음 Monitoring 다섯 경로,
`1,623 insertions / 17 deletions`다.

1. `frontend/src/features/monitoring/MonitoringPage.tsx`
2. `frontend/src/features/monitoring/MonitoringPage.test.tsx`
3. `frontend/src/features/monitoring/DataChangeStatusPanel.tsx`
4. `frontend/src/features/monitoring/DataChangeStatusPanel.test.tsx`
5. `frontend/src/features/monitoring/dataChangeStatus.css`

product에서 시작 HEAD까지는 builder evidence/receipt 두 파일만 추가됐다. dependency/lock,
`ChangeHistoryApi`/type/server, schema/migration/service/container/framework, CR state와 기존 global style
파일 변경은 없다. `frontend/package.json`과 `frontend/package-lock.json` SHA-256은 각각
`f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`,
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`이고 base-product diff가 없다.

## 요구사항별 독립 검토

### 고정 native 탭과 외부 Monitoring 회귀

- `data-change-status` 내부 ID가 외부 server-owned item 배열 앞에 항상 삽입되고 초기 active ID로
  사용된다. native view에는 iframe이 없으며 외부 configuration에 포함되지 않는다.
- 편집 draft와 PUT payload는 계속 `configuration.items`만 사용한다. native ID는 편집, 삭제, 재정렬,
  저장 payload와 외부 최대 8개 계산에서 제외된다.
- 외부 tab 순서, server-returned `url`/`embed_url`/`height_px`, `AVAILABLE` frame 분기,
  `sandbox="allow-forms allow-same-origin allow-scripts"`, `no-referrer`, 새 창 fallback과 ETag 기반
  fresh-assurance 편집 경로는 변경되지 않았다.
- native ID를 기존 roving-tab ID의 첫 항목으로 전달해 Arrow/Home/End keyboard 계약을 보존한다.
  focused test는 native default, ArrowRight 외부 tab 이동, 외부 link/frame/height/sandbox, editor의 native
  제외, PUT payload native 제외와 assurance read-only 상태를 통과했다.
- capabilities refresh는 직전 요청과 unmount 요청을 abort하고 aborted 응답을 state에 반영하지 않는다.

### 서버 권위, bound와 상태 의미

- native panel은 기존 검증된 `ChangeHistoryApi`를 직접 생성해 `summary`, `events`, `event`, `links`만
  호출한다. 별도 `fetch`, local authorization filter, local aggregation, provider 추정 또는 raw
  pass-through가 없다.
- event와 CR link history 요청은 UI에서 고정 `50`을 전달한다. filter 적용 시 caller의 limit도 다시
  `50`으로 덮어쓰며 local 재필터링 없이 열두 필드를 server query로 전달한다.
- 숫자 `0`은 그대로 표시되고 nullable watermark는 `기록 없음`, 닫힌 sync enum은 별도 한국어 상태,
  transport/contract error는 `ErrorNotice`, event zero는 별도 empty view로 표시된다. source/provider
  미구성 상태를 성공이나 숫자 zero로 추정하지 않는다.
- summary/list 요청과 detail/link 요청은 각각 이전 `AbortController`를 취소한다. unmount와 dialog close도
  abort하며, signal이 stale이면 결과를 state에 반영하지 않는다.

### KST, detected fallback과 안전한 semantic diff

- 현재 날짜를 `Intl.DateTimeFormat(..., timeZone: 'Asia/Seoul')`로 KST calendar date로 변환한 뒤 실제
  월요일을 계산한다. fixed week/date는 제품 코드에 없다. invalid/non-Monday filter는 transport 전에
  거부된다.
- 모든 표시 시각은 KST `Intl`을 사용한다. `source_occurred_at`이 null일 때만 `detected_at`을 사용하며
  행에 `감지 시각 (detected)`를 명시해 발생 시각으로 위장하지 않는다.
- before/after는 `JSON.stringify` 결과를 React `<pre>` text child로 렌더링한다. raw HTML/JS 실행,
  `dangerouslySetInnerHTML`, DOM injection, link/unlink command, POST/PUT 또는 CR mutation control이 없다.
  detail/link history도 authoritative API 응답만 표시한다.

### hardcoding, style와 scope

- 새 deployment host/port/credential/token/system/user hardcoding, secret, validator/lint suppression 또는
  security 완화가 없다. test의 `https://datariver.invalid`만 URL query parsing fixture로 존재한다.
- 새 CSS는 기존 global style 파일을 바꾸지 않고 `data-change-*` class 아래에 범위가 한정된다.
  dependency, chart library 또는 새 framework를 추가하지 않고 semantic HTML, `<meter>`, 기존
  `Dialog`/`ErrorNotice`/`PageTitle`을 재사용한다.

## 구체적 overengineering 위험

`DataChangeStatusPanel.tsx` 678줄과 `dataChangeStatus.css` 503줄은 현재 요구 기능을 실제로 구현하지만,
fetch orchestration, 12-field filter, summary, table, detail, formatting과 closed-enum label map을 한 파일에
모은 큰 presentation unit이다. 향후 API enum/filter가 바뀌면 `types`/adapter 외에 option 배열,
`FilterDraft`, `toEventFilters`, table/detail 표시를 수동으로 함께 갱신해야 해 계약 drift와 회귀 테스트
누락 위험이 있다. CSS도 이 단일 기능에 503줄이어서 layout 변경 영향 검토 비용이 높다.

다만 현재 diff에는 중복 data authority, 새 framework/dependency, global selector, server/type 재정의 또는
추상화 계층이 없고, focused tests와 typed adapter가 현재 동작을 고정한다. 따라서 이는
**nonblocking maintainability debt**이며 이번 read-only 검증에서 product failure나 repair 사유로
분류하지 않았다.

## Fresh 실행 결과

환경은 macOS arm64 `26.5.2`, Node `v25.9.0`, npm `11.12.1`이다.

| 명령 | 결과 |
|---|---|
| `npm --prefix frontend ci --offline --no-audit --no-fund` | PASS, 기존 lock/cache로 368 packages; 추적 dependency 변경 없음 |
| `npm --prefix frontend test -- --run src/features/monitoring/MonitoringPage.test.tsx src/features/monitoring/DataChangeStatusPanel.test.tsx` | PASS, 2 files / 13 tests |
| `npm --prefix frontend run lint` | PASS, error 0 / warning 0 |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build:poc` | PASS; 기존 500 kB 초과 chunk advisory만 존재 |
| `git diff --check` (base-product와 base-HEAD) | PASS |
| exact allowlist/package/hardcoding/secret/suppression review | PASS |
| `npm --prefix frontend run test:poc` | PASS, `PocApp.test.tsx` 1 file / 6 tests |

### PocApp 진단 분류

builder가 기록한 broad `npm test`의 static-navigation zero-fetch 충돌은 이번 exact focused PocApp
실행에서는 재현되지 않았다. 이를 complete-suite PASS로 바꾸거나 기존 기록을 숨기지 않는다.

source 검토상 product diff는 `PocApp.test.tsx`와 `pocApi.ts`를 변경하지 않았다. 기존 POC client는
`/change-history/*`를 authoritative `/api/v1` gateway read로 전달하고, native panel은 capabilities가
완료되어 mount된 뒤 summary/events를 읽는다. 반면 기존 navigation test는 Monitoring heading만 확인한
즉시 다음 화면으로 이동한 후 `fetch zero`를 주장한다. 따라서 scheduler가 native panel mount/read보다
빨리 이동하면 focused run처럼 통과하고, read가 먼저 시작되면 builder broad run처럼 실패할 수 있다.

이는 authoritative read를 숨겨서 고칠 product defect가 아니라 **out-of-allowlist의 stale하고
timing-sensitive한 POC test expectation/fixture debt**로 분류한다. 지정 focused acceptance gate는
통과했으므로 local-source 판정의 blocker는 아니지만, T09 전 POC test 소유자가 Monitoring 체류 시의
허용된 change-history GET을 명시적으로 기다리고 검증하도록 정리해야 한다.

## 미실행과 남은 gate

- browser/runtime/safe credentialless smoke: `NOT_EXECUTED`
- 실제 DataHub/Timeline/MCL/PostgreSQL/provider/DB probe 또는 mutation: `NOT_EXECUTED`
- container/service/network/volume/process mutation: `NOT_EXECUTED`
- push/merge/PREP/OPS/TARGET: `NOT_EXECUTED`
- full frontend suite 재실행: `NOT_EXECUTED` (지정 focused PocApp diagnostic만 fresh 실행)
- `G1/G2/G3/G4`: `NOT_APPROVED`
- 다음 단계: `T09_AUDIT`, POC static-navigation expectation/fixture follow-up
