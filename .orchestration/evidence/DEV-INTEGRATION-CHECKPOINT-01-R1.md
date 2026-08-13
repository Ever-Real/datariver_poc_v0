# DEV-INTEGRATION-CHECKPOINT-01-R1 실제 provider 체크포인트

## 범위와 판정

- Task: `DEV_INTEGRATION_CHECKPOINT_01-R1`
- 역할: `20_PLATFORM_RELEASE` + `50_QUALITY_VALIDATION` 체크포인트 규율
- 판정: `PASS_WITH_DEBT`
- exact candidate SHA: `11632c9159ca97e5a7903789bf58cc884e1e7303`
- product SHA: `639a4830d7db2775b0932c58adb14ac6185f437c` (`git merge-base --is-ancestor`: `PASS`)
- branch: `Ever-Real/dev-integration-checkpoint-01-r1`
- 실행 시각: `2026-08-14T05:19:30+09:00` ~ `2026-08-14T05:27:02+09:00`
- 환경: macOS `26.5.2`, arm64, Node `v25.9.0`, npm `11.12.1`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

시작 시 `pwd`는 지정 worktree와 정확히 일치했고 HEAD는 지정 candidate SHA였으며 작업트리는
clean이었다. 제품 source, dependency/lockfile, 기존 39080 process, container/network/volume,
DataHub metadata, Kafka offset, Schema Registry, Airflow, MinIO는 수정하지 않았다. 기존 secret env는
파일 경로로만 참조했고 값은 출력하지 않았다.

## 의존성 재사용과 빌드

candidate에는 `frontend/node_modules`가 없었다. 이미 검증된
`dev-checkpoint-01-repair-01-validation/frontend/node_modules`와 양쪽 `package-lock.json` SHA-256
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`가 정확히 일치함을 확인한 뒤
임시 symlink로만 재사용했다. 설치, audit mutation, package/lock 변경은 없었고 체크포인트 종료 전에
symlink를 제거했다.

첫 build 명령은 workdir가 이미 `frontend`인데 symlink 경로를 한 번 더 `frontend/`로 적은 로컬 명령
오류로 `tsc: command not found` 전에 종료했다. 파일 변화는 없었다. 경로를 바로잡은 뒤
`npm run build:poc`은 12.45초에 `PASS`했고 기존 500 kB chunk warning만 관찰됐다.

## 변경 금지 대상의 사전/사후 기준선

| 대상 | 사전 | 사후 | 판정 |
|---|---|---|---|
| 기존 39080 | PID `45143`, cwd `/Volumes/SSD_Mac/workspace/datariver_poc_v0/frontend` | 동일 PID/cwd | `UNCHANGED` |
| 실행 중 container | 19개 | 19개 | `UNCHANGED` |
| sanitized container identity/state hash | `c27c9aaf70308863362d82272dec3de614e331f218cf6f6f2c0294103ddc6662` | 동일 | `UNCHANGED` |
| candidate port 39081 | free | 두 process 종료 후 free | `PASS` |

container hash 입력은 container ID/name/image/state/startedAt/restartCount만 사용했다. env, mount secret,
container inspect 전체 문서는 읽거나 출력하지 않았다. container start/stop/restart/exec는 수행하지 않았다.

## actual-provider cold 경로

candidate는 기존 env 파일을 값 출력 없이 참조하여 `127.0.0.1:39081`, PID `91435`로 시작했다.

### health와 capabilities

| 항목 | HTTP/상태 | 지연 |
|---|---|---:|
| `/healthz` | `200` | 2.981 ms |
| capabilities | `200` | 94.830 ms |
| DataHub | `available / LIVE` | 4 ms |
| Airflow | `available / AIRFLOW_API_V2` | 3 ms |
| LLM Chat / Embedding | `available / LIVE` | 8 / 7 ms |
| Neo4j | `available / LIVE` | 29 ms |
| LLM Reranker | `unavailable / PROBE_FAILED` | 4 ms |
| MinIO / Grafana | `disabled / NOT_CONFIGURED` | - |

### Catalog completion과 exact-boundary 증거

- 시작 후 약 96.9초의 첫 Catalog 관찰은 HTTP `503`, code `POC_PROVIDER_ERROR`, detail
  `The PostgreSQL Catalog projection is warming; retry shortly.`였다. provider 준비 실패를 정상 0건으로
  가장하지 않았다.
- 시작 후 200.2초에 처음 관찰한 성공은 HTTP `200`, `total=2000`, `total_exact=true`,
  projection version `1`, source generation prefix `88c15c4274d4`였다. 8분 상한 안이다.
- PostgreSQL read-only transaction에서 exact scope row `1`, row version `1`, projection version `1`,
  items `2000`을 확인했다.
- Redis는 구성돼 있었지만 optional inventory key는 없었고 TTL은 `-2`였다. PostgreSQL current가
  authoritative하므로 이를 cache 성공으로 부풀리지 않는다.
- 고정 provider page 크기는 250이고 2,000은 정확히 8 page 경계다. 시작 이후 DataHub GMS의
  sanitized log count는 `urn` sort warning 9줄, slow operation 8줄이었다. slow page 지연은
  `25417, 23457, 18371, 18828, 25588, 23570, 18782, 19249` ms였다. 제품의 terminal-confirmation
  계약과 함께 보면 8개 data page 뒤 9번째 empty terminal confirmation request가 실행됐다는 runtime
  증거이며, raw GraphQL 변수, scroll cursor, URN과 log line은 출력하지 않았다.

### Search / Tree / Detail과 0-vs-error

| 검증 | 결과 | 지연/근거 |
|---|---|---|
| Catalog 첫 성공 | `200`, exact total 2,000 | 113.823 ms |
| Catalog warm 5회 | 모두 `200`, exact total 2,000 | 101.289 / 31.670 / 48.510 / 82.262 / 121.669 ms |
| unmatched TABLE Search | `200`, exact total `0`, items `0` | 13.307 ms; 정상 zero |
| Tree ROOT | `200`, items `2` | 2.519 ms |
| live Detail | `200`, `DATASET`, field 10/14 | 139.125 ms; identity는 SHA-256 prefix `371b15e82133`으로만 기록 |

초기 provider/warming 상태는 `503 POC_PROVIDER_ERROR`, projection 완료 후 실제 unmatched query는
`200` exact zero이므로 failure와 valid-zero의 의미가 분리됐다.

## warm restart와 자연 종료

첫 candidate PID `91435`에만 SIGTERM을 보냈다. 0.114초 안에 force kill 없이 자연 종료했고 39081이
해제됐다. 이어 같은 exact candidate를 PID `93523`으로 재시작했다. health는 74.865 ms에 `200`, 첫
Catalog는 32.833 ms에 PostgreSQL current projection source, 동일 generation prefix, exact 2,000건으로
즉시 `200`이었다. 10초 뒤 Catalog도 119.133 ms에 동일했다. 재시작 이후 bounded log window에서 새
inventory warning과 slow operation은 각각 0줄이므로 fresh full scan 없이 current projection을 재사용했다.
두 번째 PID에도 SIGTERM만 보냈고 0.115초 안에 자연 종료했으며 39081이 해제됐다.

## MCL/scheduler와 미실행 경계

env 값은 출력하지 않고 설정 존재 여부만 검사했다. scheduler는 `requested=false`, `enabled=false`,
reason `DISABLED`였고 필수 MCL binding은 9개 중 0개가 존재했다. 안전한 실제 catch-up을 발명할 수
없으므로 MCL capture, ledger/checkpoint append, scheduler catch-up은 `NOT_EXECUTED`다. 이를 PASS로
표현하지 않는다.

actual-provider runtime이 repair된 핵심 경계를 직접 입증했으므로 full local suite와 focused fixture를
반복하지 않았다. 이전 exact candidate source validation의 4/4, native Node 59/59, lint, build 및
Vitest-only 527개 결과를 runtime PASS로 대체하거나 재해석하지 않는다.

## 판정 근거, debt, NOT_EXECUTED

핵심 Catalog completion은 8분 이내 성공했고 Search/Tree/Detail 및 valid-zero가 200으로 분리됐으며,
두 candidate process 모두 SIGTERM 후 1초 미만에 자연 종료했다. 따라서 blocking 조건은 없다.

`PASS_WITH_DEBT` 사유:

- optional Redis inventory key 부재
- LLM Reranker `unavailable / PROBE_FAILED`
- MCL/scheduler 실제 catch-up `NOT_EXECUTED` (scheduler disabled, required binding 0/9)

그 밖의 `NOT_EXECUTED` 범위는 DataHub metadata write, Kafka read/offset mutation, Schema Registry/Airflow/
MinIO mutation, container/network/volume lifecycle, 기존 39080 접근·종료·재시작, dependency 설치,
제품/test/config repair, push/merge/rebase/publication, PREP/OPS/TARGET, G1-G4 승인이다.
