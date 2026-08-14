# DEV-INTEGRATION-CHECKPOINT-01-REPAIR-01-CATALOG 독립 검증 증적

## 범위와 판정

- 역할: `50_QUALITY_VALIDATION`
- 범위: `B-01 Catalog scroll` 제품 read-only 독립 검증
- 정확한 base SHA: `8665f5d67a19fdbc41caf3b77c5c72b7399bbfd4`
- 제품 commit SHA: `4deb4de21e29a8fcec0d08c40682ed93ffe52da9`
- 검증 candidate SHA: `e9d744bade52adc740ff96c17025064ecd263b25`
- branch: `Ever-Real/dev-checkpoint-repair-01-catalog-validation`
- 검증 시각: `2026-08-14T09:29:26+09:00`
- 환경: macOS DEV Mac ARM64, Node `v25.9.0`, npm `11.12.1`
- 판정: `PASS_LOCAL_SOURCE`
- 제품 수정: 없음
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

시작 시 HEAD는 지정 candidate와 정확히 일치했고 worktree는 clean이었다. `base..product` 변경은
`frontend/poc-server.mjs`, `frontend/poc-catalog-performance.test.mjs`,
`frontend/poc-server.providers.test.mjs` 세 제품 경로뿐이고, `product..candidate` 변경은 기존 repair
evidence와 receipt 두 경로뿐이다. dependency/lock/service/framework/deploy 변경과 `B-02` 변경은 없다.

## B-01 독립 검토

- 최초 page의 provider `total`을 고정하고 이후 모든 page에서 같은 값을 요구한다. unique asset 수가
  stable `total`과 정확히 같고 cursor가 남은 경우에만 바로 다음 terminal confirmation page를 한 번
  허용한다.
- exact-boundary 250개 full page + cursor + 빈 terminal page는 provider 2회, PostgreSQL write 1회,
  memory snapshot 교체, Redis best-effort cache write 1회 뒤 최종 HTTP `200`으로 완료된다.
- terminal confirmation은 새 unique 수가 아니라 raw `page.items.length === 0`을 요구한다. 따라서 duplicate
  hit, 새 asset 또는 추가 continuation을 모두 commit 전 bounded `502`로 거부하고 durable write는 0회다.
  기존 F-01의 duplicate-hit 허용 결함은 이 stricter 조건과 새 negative fixture로 교정됐으며 assertion
  삭제·skip·완화는 없다.
- 모든 응답 cursor를 하나의 `Set`에 추가하므로 즉시 반복과 A-B-A 비인접 cycle을 모두 `502`로 거부한다.
  고정 `maximumInventoryPages` bound도 유지된다.
- cold/no-snapshot 실패 뒤 `inventoryRefreshRetryAt` 전 4회 polling은 모두 `503`이고 provider 추가 scan은
  0회다. 단일 `inventoryRefreshPromise` 계약도 유지된다.
- 전체 검증이 끝난 뒤 PostgreSQL write가 먼저 성공해야 memory snapshot을 교체하고 그 다음 Redis를
  best-effort로 갱신한다. partial/later-page 실패의 last-good, PostgreSQL authoritative read, Redis fallback
  경계와 valid-zero generation도 기존 fixture에서 유지된다.

## DataHub v1.6 정렬 source 확인

공식 `v1.6.0` tag source를 독립 확인했다. `ScrollAcrossEntitiesResolver`는 `sortInput`을
`SearchUtils.getSortCriteria`에 넘기며, 해당 함수는 입력이 없을 때 빈 criteria list를 반환한다.
`ESUtils.buildSortOrder`는 빈 criteria에서 score 내림차순을 추가하고 항상 URN 오름차순 tie-breaker를
추가한다. 따라서 inventory query에서 runtime warning을 유발한 explicit `sortInput: urn` 제거는 source와
일치한다. provider 계약 테스트는 query body의 `sortInput` 부재를 새로 확인하므로 validator를 약화하지
않았다.

- resolver: `https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/resolvers/search/ScrollAcrossEntitiesResolver.java`
- sort mapping: `https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/resolvers/search/SearchUtils.java#L328-L346`
- default ordering: `https://github.com/datahub-project/datahub/blob/v1.6.0/metadata-io/src/main/java/com/linkedin/metadata/search/utils/ESUtils.java#L570-L656`

## 실행 검증

| 명령/검증 | 결과 | 근거 |
|---|---|---|
| fresh `npm ci --offline` | `PASS` | 368 packages 설치, audit 0, lockfile 변경 없음 |
| `npm run build:poc` | `PASS` | 필수 dist precondition 충족; 기존 500 kB chunk warning만 관찰 |
| `node --test --test-reporter=tap poc-catalog-performance.test.mjs` | `PASS` | 4/4 |
| `node --test --test-reporter=tap poc-server.providers.test.mjs` | `PASS` | 18/18 |
| `node --test --test-reporter=tap poc-server.test.mjs` | `PASS` | 14/14 |
| `node --test --test-reporter=tap *.test.mjs` | `PASS` | 단독 실행 59/59, cold response 28.709 ms |
| `npm run lint` | `PASS` | warning/error 0 |
| ancestry, `git diff --check`, exact allowlist | `PASS` | 지정 3 제품 + 2 기존 evidence 경로만 확인 |

검증자가 full Node와 lint를 병렬 실행한 최초 시도에서는 machine load 아래 cold timing이 103.150 ms로
`<100 ms` assertion을 3.150 ms 넘었다. 해당 assertion이 test server close 전에 종료돼 남은 task-local
Node PID만 정확히 종료한 뒤, full Node를 단독 재실행해 cold 28.709 ms와 59/59를 확인했다. 제품 수정이나
validator 완화 없이 통과했으므로 blocking/non-blocking 제품 finding으로 분류하지 않는다.

## finding과 미실행 경계

- blocking finding: 없음
- non-blocking product finding: 없음
- `B-02` 검토·repair 또는 새 기능: `NOT_EXECUTED`
- 실제 DataHub/provider/runtime 접근 또는 mutation: `NOT_EXECUTED`
- 기존 listener, container, volume, network, PREP, OPS, TARGET: `NOT_EXECUTED`
- push, merge, rebase, publication: `NOT_EXECUTED`
- G1-G4 승인: `NOT_APPROVED`

결론은 `PASS_LOCAL_SOURCE`다. 이는 지정 candidate의 B-01 local source/static/fixture 계약만 검증한 결과이며
실제 provider, runtime, target 환경, 통합 또는 배포 승인을 대신하지 않는다.
