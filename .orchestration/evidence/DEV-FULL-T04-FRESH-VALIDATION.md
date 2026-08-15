# DEV-FULL-T04 독립 신규 검증

- Task: `DEV-FULL-T04-FRESH-VALIDATION` (`task_237a0bbaba16`)
- 검증 시각: `2026-08-15T14:01:51Z`
- 검증 대상 evidence SHA: `9200984d08bad8dcab51b774d5f889aed07ff0c7`
- 제품 SHA: `4aea6d19c64253130e00d997c2837b74fac4837d`
- 비교 기준: `7b7f427a30332b446b8a90b798def7134f90b6ad`
- 결과: `PASS_LOCAL_SOURCE_AND_DEV_EVIDENCE`
- 실행 정책: read-only validator, 제품/DEV 데이터/서비스 수정 없음

## 1. Git·범위·보안 검토

시작 HEAD는 정확히 `9200984d08bad8dcab51b774d5f889aed07ff0c7`이었고 worktree는 clean이었다.
`7b7f427...`은 제품 SHA `4aea6d1...`의 ancestor이며 제품 SHA는 evidence SHA의 ancestor다.
docs hold `e7ba19`는 대상 ancestry에 없었다. 제품 범위 diff에는 package/lock, SQL schema,
Dockerfile, Compose 변경이 없고 최종 `git diff --check`도 통과했다.

추가된 소스 줄의 credential·URL·IP 패턴을 검토했다. 실제 credential/secret 하드코딩은 없었다.
발견된 `127.0.0.1:6543/datariver_poc_isolated_test`는 명시적 테스트 격리 계약 fixture이고,
`https://poc.invalid`는 네트워크 송신 없는 URL parser fixture다. package/lock/schema는 설치·빌드 뒤에도
tracked diff가 없었다. `datariver_v1`, PREP, OPS, push에는 접근하거나 작업하지 않았다.

Vitest는 `**/*.test.mjs`를 의도적으로 제외하며, 숨겨진 Node suite가 되지 않도록 실제 7개 파일을
별도의 `node --test *.test.mjs`로 전부 실행했다.

## 2. 신규 로컬 소스 검증

모든 명령에서 `POC_DATABASE_URL`, `POC_POSTGRES_*`, `POC_REDIS_URL`, DataHub token/URL,
MCL Kafka/Schema Registry binding을 제거했다. `npm ci --ignore-scripts --no-audit --no-fund`는 lock을
변경하지 않았다.

| 검증 | 신규 실행 결과 |
|---|---|
| Vitest 전체 | `84 files`, `568/568 PASS` |
| Node `.mjs` 전체 7파일 | `71/71 PASS` |
| ESLint | PASS, warning 0 |
| TypeScript `tsc -b` | PASS |
| `npm run build:poc` | PASS |
| `npm run build` | PASS |
| `git diff --check` | PASS |

최초 fresh worktree에서 `build:poc` 전에 catalog shutdown 두 테스트가 의도된
`Run npm run build:poc before starting the POC server.` guard로 중단됐다. 이는 제품 assertion 실패가
아니며, 요구된 `build:poc` 실행 후 동일 전체 Node 명령은 71/71로 통과했다. Vitest의 임의 `basic`
reporter 추가 시도도 Vitest 4.1.10 CLI에서 거부되어 공식 결과에서 제외했고, 저장소의 정확한
`npm test` 명령은 568/568로 통과했다.

테스트 격리 guard는 Node suite에서 독립적으로 검증됐다. 상속된 persistent PostgreSQL target은 Pool
생성 전에 `POC_TEST_DATABASE_ISOLATION_REQUIRED`로 거부되고, 명시적 pool double은 허용된다. 명시적
격리 acknowledgement/target 경로는 target 일치만 확인한 뒤 실제 연결 없이 닫혔다. live DEV DB binding을
가진 unit test는 실행하지 않았다.

## 3. Linux/AMD64·Node 22 검증

다음 현재-SHA build를 수행했으며 service를 시작하거나 교체하지 않았다.

```text
docker buildx build --platform linux/amd64 --load \
  --tag datariver-poc:t04-validation-4aea6d1 \
  --file deploy/poc/Dockerfile.example \
  --build-arg POC_SOURCE_COMMIT=4aea6d19c64253130e00d997c2837b74fac4837d .
```

결과 image ID는 `sha256:b0710116172d8646ac9707b2c60b7bca023e86f0697c4344042b3b1b0b67ad3`,
플랫폼은 `linux/amd64`, OCI revision은 정확히 제품 SHA다. 최종 image config는
`NODE_VERSION=22.19.0`, CMD `node poc-server.mjs`이며, image build 안에서 `npm ci`, `build:poc`,
production prune와 POC server/state/scheduler/MCL import copy가 모두 성공했다. 별도 container/service는
실행하지 않았다.

## 4. 기존 39083 DEV runtime 읽기 전용 fence

기존 `datariver-poc-web-1`은 healthy이며 image ID `sha256:d59b0b...`, OCI revision
`4aea6d19c64253130e00d997c2837b74fac4837d`다. `/healthz`는 `ok`를 반환했다. API 및 PostgreSQL
`BEGIN TRANSACTION READ ONLY` 조회 결과는 다음과 같다.

| 항목 | 실제 값 |
|---|---|
| access | version `10`, active `checkpoint-admin`, users/systems/scopes/assignments `4/2/2/2` |
| access 저장 MD5 | `74050e15e3a1b89b6d1686fbabeb82ba` |
| 역할 | admin/data_steward/developer/viewer 각 1 |
| core | version `37`, sequence `903`, MD5 `62436ccb65aa85477c0416603be24689` |
| CR | `poc-change-request-901`, `CR-POC-00902`, REGISTERED, round `1`, version `1` |
| canonical checkpoint | `a2a280e5d04c...`, partition `0`, first `52849`, next `52942`, version `94` |
| 보조 checkpoint | `62db387b0627...`, partition `0`, first `51815`, next `52854`, version `1040` |
| semantic ledger | rows `46`, distinct identity `46`, distinct transaction `35` |
| frozen link | rows `4`, max version `4`, 최종 `UNLINKED`, primary 없음, candidate `0` |
| frozen event ETag | `ea6d42cba2ad1e68257cd2a5ec349c49262562fb44c76d3f8ebe224316a27df2` |
| scheduler receipts | canonical/T03B version `1/1`, boundary 모두 `2026-08-14T15:00:00.000Z` |

KST 주간 summary는 normalized transaction `35`, unlinked `35`, 이후 단계 전부 `0`이고 event rows는
`46`이다. frozen reverse 조회는 CR에 해당 event 한 건을 보존한다. 어떤 role/CR/MCL/scheduler mutation도
재실행하지 않았다.

브라우저 read-only 확인에서 CR Status Overview는 정확히
`스키마/시스템/담당자/CR 전체/데이터셋별 미진행/접수완료/재검토/변경 / TEST/완료검토/완료`
10개 column을 표시했다. Oracle 행은 전부 `0`; PostgreSQL 행은 담당자 `1`, CR 전체/미진행/접수완료
`1/1/1`, 나머지 단계 `0/0/0/0`이다. 목록에는 `CR-POC-00902` 한 건이 표시됐다.

## 5. 결론과 debt

제품/evidence와 실제 DEV fence 사이의 blocking 불일치는 발견되지 않았다. 따라서 결과는
`PASS_LOCAL_SOURCE_AND_DEV_EVIDENCE`다. 이 결과는 PREP/OPS/production 승인이나 provider 복구를
의미하지 않는다.

Vector provider debt는 그대로다. `/poc-api/capabilities`에서 `LLM Embedding`, `LLM Chat`,
`LLM Reranker`가 `unavailable`이며 이번 검증은 provider recovery를 주장하지 않는다. 이는 현재
core/access/CR/MCL acceptance를 막지 않는 nonblocking debt다. 빌드의 500 kB 초과 chunk warning도
기존 nonblocking 경고로 남는다.

검증 중 제품 파일, live DB/DataHub/Kafka/offset, container/service 상태는 수정하지 않았다. 생성한 유일한
지속 산출물은 이 evidence와 matching receipt이며, Docker에는 service가 아닌 로컬 검증 image tag만
추가됐다.
