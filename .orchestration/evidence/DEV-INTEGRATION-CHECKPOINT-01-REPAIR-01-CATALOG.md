# DEV-INTEGRATION-CHECKPOINT-01-REPAIR-01-CATALOG 증거

## 범위와 판정

- 역할: `40_DATA_AI_KNOWLEDGE`
- 범위: `B-01 Catalog scroll`만 repair
- 정확한 base SHA: `8665f5d67a19fdbc41caf3b77c5c72b7399bbfd4`
- 제품 commit SHA: `4deb4de21e29a8fcec0d08c40682ed93ffe52da9`
- branch: `Ever-Real/dev-checkpoint-repair-01-catalog`
- 기록 시각: `2026-08-14T09:22:07+09:00`
- 환경: macOS DEV, Node `v25.9.0`, npm `11.12.1`
- 판정: `SUCCEEDED_LOCAL_CANDIDATE`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

지정 base와 clean 상태에서 시작했다. 제품 변경은 허용된 `frontend/poc-server.mjs`,
`frontend/poc-catalog-performance.test.mjs`, `frontend/poc-server.providers.test.mjs` 세 경로뿐이다.
새 dependency, service, framework, provider pass-through, runtime/container 또는 deploy 변경은 없다.

## B-01 repair

- 안정된 provider `total`과 관찰한 unique cardinality가 같지만 cursor가 남은 exact page 경계에서만 바로
  다음 terminal confirmation page를 한 번 허용한다.
- 확인 page는 같은 `total`, raw hit 0개, 후속 cursor 없음이어야 한다. 기존 코드는 새 unique 수만 0이면
  이미 본 asset의 duplicate hit도 빈 확인으로 오인할 수 있었다. 이제 `page.items.length === 0`을 요구해
  terminal 새 asset, duplicate asset 또는 continuation을 모두 commit 전 bounded `502`로 거부한다.
- 기존 cursor `Set`은 모든 응답 cursor를 추적하여 즉시 반복과 A-B-A 비인접 cycle을 거부한다. stable
  total, exact unique cardinality, 최대 page bound, 단일 refresh promise를 유지했다.
- cold/no-snapshot refresh 실패 뒤 `inventoryRefreshRetryAt` 이전 polling은 새 scan 없이 `503`을 반환한다.
- 전체 검증 뒤 PostgreSQL write를 먼저 완료하고 memory snapshot을 교체한 다음 Redis를 best-effort로
  갱신하는 순서, last-good 보존, valid zero generation 계약을 유지했다.

## DataHub v1.6 정렬 계약

DataHub `v1.6.0` 공식 source를 확인했다. GraphQL
`ScrollAcrossEntitiesResolver`는 `sortInput`이 없으면 빈 sort criteria를 provider search에 전달한다.
`ESUtils.buildSortOrder`는 빈 criteria에 score 내림차순을 적용하고 항상 URN 오름차순 tie-breaker를
추가한다고 명시하고 구현한다. 따라서 source가 지원하지 않아 실제 runtime에서 warning을 내던 explicit
`sortInput: urn`을 Catalog inventory query에서 제거했다. provider 계약 테스트는 `sortInput` 부재를
명시적으로 확인하도록 기존 query-shape 기대를 갱신했으며 validator를 완화하지 않았다.

- resolver: `https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/resolvers/search/ScrollAcrossEntitiesResolver.java`
- default ordering: `https://github.com/datahub-project/datahub/blob/v1.6.0/metadata-io/src/main/java/com/linkedin/metadata/search/utils/ESUtils.java#L605-L681`

## 테스트 우선 재현

수정 전 새 negative fixture는 250개 exact-boundary page 뒤 duplicate asset 1개를 가진 terminal page가
거부되지 않아 실패했다. provider query-shape assertion도 explicit `sortInput`이 남아 있어 실패했다.
최소 제품 수정 후 두 focused 계약은 모두 통과했다.

집중 fixture는 다음을 확인한다.

- 250개 + cursor + 빈 terminal: provider 2회, PostgreSQL write 1회, Redis cache write 1회, 최종 `200`
- terminal continuation/new asset/duplicate asset: 각각 `502`, durable write 0회
- A-B-A cursor cycle: `502`, durable write 0회
- cold failure 뒤 즉시 4회 polling: 모두 `503`, provider 추가 scan 0회
- partial/later-page failure의 last-good, PostgreSQL authoritative read, optional Redis, valid zero 보존

## fresh 검증

| 명령 | 결과 |
|---|---|
| `npm ci --offline` | `PASS`; 368 packages, audit 0, lockfile 변경 없음 |
| `npm run build:poc` | `PASS`; 기존 500 kB chunk warning만 관찰 |
| `node --test poc-catalog-performance.test.mjs` | `PASS`; 4/4 |
| `node --test poc-server.providers.test.mjs` | `PASS`; 18/18 |
| `node --test poc-server.test.mjs` | `PASS`; 14/14 |
| `node --test *.test.mjs` | `PASS`; 59/59 |
| `npm run lint` | `PASS`; warning/error 0 |
| `git diff --check` 및 base-to-product allowlist | `PASS`; 허용 제품 3경로만 변경 |

fresh install 뒤 build artifact가 없을 때 Catalog 파일의 B-01 두 건은 통과했고 B-02 lifecycle 두 건은
명시적 `build:poc` precondition으로 실패했다. B-02를 수정하지 않고 필수 build를 수행한 뒤 동일 파일은
4/4 통과했다. 이는 B-01 제품 finding이 아니다.

## 경계

- blocking finding: 없음
- B-02 또는 새 기능 자동 repair: `NOT_EXECUTED`
- 실제 DataHub/provider/runtime 접근 또는 mutation: `NOT_EXECUTED`
- 기존 listener, container, volume, network, PREP, OPS, TARGET: `NOT_EXECUTED`
- push, merge, rebase, publication: `NOT_EXECUTED`
- G1-G4: `NOT_APPROVED`

이 판정은 B-01의 local source/fixture candidate에 한정되며 실제 provider 또는 배포 승인을 대신하지 않는다.
