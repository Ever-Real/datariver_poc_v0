# CHANGE-HIST-T05 Catalog current projection 성능 증거

## 판정

- 최종 판정: `PASS`
- exact base SHA: `7cc7b6a0791add7b91f2d801b3e0650060556045`
- task worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05`
- task branch: `Ever-Real/change-hist-t05`
- 범위: POC Catalog/Search/Tree/Chat의 최신 DataHub read model과 요청 경로 성능만 수정했다.
- DataHub canonical ownership, PostgreSQL current projection, pgvector 최신 semantic generation,
  선택적 Redis acceleration 경계는 유지했다. 변경 이력 원장과 current projection을 섞지 않았다.
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## 수정 전 실제 DEV 기준선

2026-08-13 KST에 활성 runtime을 재시작하거나 cache를 flush하지 않고 read-only로 측정했다.

| 항목 | 분류 | 결과 |
|---|---|---|
| runtime process | `MEASURED` | native Node PID `45143`, `*:39080`, cwd `/Volumes/SSD_Mac/workspace/datariver_poc_v0/frontend` |
| runtime source/SHA | `MEASURED` | 활성 cwd의 Git HEAD `b0b666a7e3b78fca96e8b19312599ae3a5624fa3`; T05 exact base/candidate runtime이 아니므로 after-runtime으로 사용하지 않았다. |
| health | `MEASURED` | `/healthz` HTTP 200, `0.001037s`, 3 B; `/` HTTP 200, `0.005439s`, 998 B |
| warm unfiltered Catalog | `MEASURED` | `/poc-api/datahub/catalog?limit=20` HTTP 200, `0.163218s`, 23,825 B, total 2,000 / returned 20 |
| normal filtered Catalog | `MEASURED` | `q=evidence&limit=20`은 60.005732초까지 응답 body 0 B, curl timeout/status `000` |
| provider page count | `STATIC_INFERRED` | 기존 상세 inventory는 요청마다 `count=250` 전체 scroll이므로 관찰 total 2,000 기준 최소 8 page다. 활성 process 내부 실제 완료 page 수는 tracing을 추가하지 않아 `NOT_EXECUTED`다. |
| Redis | `MEASURED` + `STATIC_INFERRED` | Node에서 `127.0.0.1:16379` established connection 1개를 관찰했다. 기존 상세/column inventory 함수는 Redis와 PostgreSQL inventory를 모두 우회했다. |
| Redis hit/miss counter | `NOT_EXECUTED` | host에 `redis-cli`가 없었고 credential을 읽거나 출력하지 않았다. 연결과 코드 경로만 증거로 사용했다. |
| PostgreSQL current projection | `STATIC_INFERRED` | 기존 `poc_state`에는 Catalog current inventory reader/writer가 없었다. PID의 당시 TCP 연결에서도 PostgreSQL 연결은 관찰되지 않았다. 기존 pgvector embedding은 current Catalog JSON read model이 아니다. |
| serialization | `MEASURED` | unfiltered 20-item JSON은 23,825 B였다. timeout된 filtered 요청은 직렬화 결과가 없었다. |
| 실제 browser render timing | `NOT_EXECUTED` | 활성 runtime restart/build 금지와 exact SHA 불일치 때문에 browser timing을 후보 성능으로 가장하지 않았다. |

따라서 일반 검색 요청이 Redis나 PostgreSQL last-good을 재사용하지 못하고 상세 DataHub inventory를
동기 full-scan하는 병목이 실제로 확인되었다. 수정 조건은 충족한다.

## 최소 구현

1. 세 종류의 inventory scan을 상세 current inventory 하나로 통합했다. Catalog, Search, Tree,
   Facet, Dashboard, Profile coverage와 Chat/pgvector refresh가 같은 latest item set을 사용한다.
2. 전체 provider scroll이 끝난 뒤에만 source-scoped generation과 items를 기존 `poc_state`의 한
   scope에 단일 UPSERT한다. 중간 page 실패는 PostgreSQL last-good을 덮어쓰지 않는다.
3. PostgreSQL이 구성된 cold process는 사용자 요청에서 full-scan을 기다리지 않는다. 즉시 503
   warming 상태를 반환하고 background refresh를 시작하며 server startup도 같은 warm-up을 시작한다.
4. stale projection은 즉시 last-good을 반환하면서 background refresh한다. provider 실패 후에는
   60초 bounded retry window를 적용하고 `DEGRADED_LAST_GOOD`을 노출한다. 실패를 빈 결과로 바꾸지 않는다.
5. Redis key v5는 PostgreSQL commit 뒤 완성된 projection만 저장한다. Redis가 없거나 실패하면
   PostgreSQL current projection을 읽는다. Redis는 source of truth가 아니다.
6. generation은 provider source scope, 안정 정렬된 asset ID와 volatile observation/match field를
   제외한 content hash로 계산한다. 성공한 replacement generation은 삭제된 asset을 list/search에서
   제거하고 pgvector refresh를 재예약하여 latest Chat generation도 정리한다.
7. 상세 응답의 `observed_at`, `stale_at`, source generation과 refresh state를 실제 projection에
   결합했다. provider failure나 오래된 last-good을 현재 live 관찰로 표시하지 않는다.

새 테이블, migration, DB/cache/service/container/framework, dependency/lockfile은 추가하지 않았다.

## 수정 후 결정적 격리 성능 증거

활성 platform을 건드리지 않고 25ms/page의 2-page DataHub harness, Redis failure, process 간 공유되는
가짜 PostgreSQL state-store 계약으로 cold/warm/partial failure/replacement를 검증했다.

| 항목 | 분류 | 결과 |
|---|---|---|
| cold user request | `MEASURED_TEST` | HTTP 503 warming, 20.316ms; 요청은 provider full-scan 완료를 기다리지 않았다. background provider page는 2회였다. |
| fresh server warm request | `MEASURED_TEST` | HTTP 200, 5.412ms, provider page 0회, JSON 2,861 B |
| JSON parse | `MEASURED_TEST` | 2-item bounded payload parse 0.049ms |
| Redis unavailable | `PASS` | 모든 Redis get/set이 실패해도 새 server instance가 공유 PostgreSQL last-good 2건을 반환했고 provider page는 0회였다. |
| partial provider failure | `PASS` | page 1 후 page 2 HTTP 502에서도 write 수가 증가하지 않았고 last-good 2건과 `DEGRADED_LAST_GOOD`이 유지됐다. |
| atomic generation replacement | `PASS` | 다음 성공 refresh가 1건 generation을 commit했고 새 server instance는 삭제된 1건을 노출하지 않았으며 provider page 0회였다. |
| frontend bounded render contract | `PASS` | `CatalogWorkspace.test.tsx`와 `pocApi.live.test.ts` 32개 테스트가 PASS했다. 실제 browser frame timing은 `NOT_EXECUTED`다. |

이 값은 deterministic local harness 증거이며 TARGET capacity/load/soak 수치로 승격하지 않는다.

## 자동 검증

- focused ESLint: `PASS`
  - `poc-server.mjs`
  - `poc-server.providers.test.mjs`
  - `poc-catalog-performance.test.mjs`
- POC TypeScript/Vite build: `PASS`
- Node server/provider/chat/performance: `PASS` — 26 passed, 0 failed
- Catalog workspace/API Vitest: `PASS` — 32 passed, 0 failed
- `git diff --check`: `PASS`
- conflict marker scan: `PASS`
- allowlist/status 확인: `PASS`

Task worktree에는 `node_modules`가 없었다. dependency 설치나 symlink를 repository에 만들지 않고,
DEV 통합 worktree의 기존 동일 lock 의존성을 `/tmp`의 source 복사본에만 연결하여 lint/build/test를
수행했다. 첫 direct test의 `ERR_MODULE_NOT_FOUND: pg`와 static root 404는 이 격리 환경 준비 누락이며,
의존성/`dist-poc`를 포함한 최종 임시 복사본에서 모두 PASS했다.

## NOT_EXECUTED 및 경계

- 활성 DEV runtime restart, cache flush, code replacement 또는 후보 after-runtime 측정
- 활성 Redis key/value/hit/miss 조회: host `redis-cli` 부재; credential 미조회
- 정상 POC PostgreSQL 데이터 mutation 또는 실제 current projection row 생성
- 실제 browser frame/render timing, target load/soak, PREP/OPS 측정
- DataHub metadata write, provider/Kafka mutation, 새 service/container/DB/cache 생성
- backend/T03/T04, UI layout, CR state, IAM, package/dependency/lockfile 변경
- merge, push, integration, publication
- G1/G2/G3/G4 승인

## 결론

실제 DEV에서 2,000건 Catalog의 상세 검색이 60초 timeout되는 동기 full-scan 병목을 확인했다.
허용 범위 안에서 기존 `poc_state`를 atomic last-good current projection으로 재사용하여 정상 요청을
provider scan에서 분리했고, Redis failure, partial provider failure, generation 교체, 삭제 asset 제거를
결정적 테스트로 입증했다. 활성 runtime과 외부 시스템은 변경하지 않았고 TARGET 성능 승인은 열려 있다.
