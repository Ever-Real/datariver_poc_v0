# 50_QUALITY_VALIDATION MCL Snappy 독립 검증 증적

## 판정

- Task / dispatch: `task_5add1f6544ef` / `ctx_8c3cd9f09650`
- 역할 / 모델: `50_QUALITY_VALIDATION`, `gpt-5.6-terra` High controlled fallback
- 기준 / 제품 / candidate: `4543ca96353f90d448324fa67ec6e7d3ce2d17e5` / `061c6c2` / `9a7eb985323f493a7e24868140e43b9e24d0e30d`
- 환경: DEV macOS arm64; Node source gate `v25.9.0`; Node 22.19.0 Docker image build
- 최종 판정: `PASS_DEV_RUNTIME_WITH_DEBT`
- 후속 재확인: runtime-only task가 만든 durable scheduler receipt를 같은 DB에서 읽기 전용으로 확인했다. `change-history-scheduler-v1:datariver:poc:change-history-scheduler:v1`, version `1`, trigger `scheduled`, `last_successful_schedule=2026-08-14T15:00:00.000Z` (KST 2026-08-15 00:00), `completed_at=2026-08-14T15:11:41.313Z`이다.

source gate, ledger 핵심 사실 및 scheduler durable receipt가 통과했다. 남은 debt는 compatible CR test data 부재, 저장된 authority를 바꾸지 않는 viewer subject switch 부재, 그리고 실제 일일 시계 경과를 관찰하지 못한 `DAILY_CLOCK_NOT_OBSERVED`뿐이다. source repair, PREP, OPS, publication, T08, T09는 수행하지 않았다.

## 범위ㆍ정적 검증

`4543ca9..061c6c2`의 제품 변경은 정확히 다음 네 경로뿐이다.

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/poc-mcl-capture.mjs`
- `frontend/poc-mcl-capture.test.mjs`

`git diff --check`는 통과했다. `kafkajs-snappy@1.1.0`은 lock에 정확히 고정되어 MIT이고, 의존성은 `snappyjs@0.6.1` 뿐이다. lock의 package metadata와 설치물을 확인했으며 native binary, preinstall/install script 또는 새 native addon은 발견하지 못했다. KafkaJS `CompressionCodecs[CompressionTypes.Snappy]` 등록은 MCL infrastructure boundary에만 있고, 변경 diff에는 host/topic/credential/timezone 상수, validator/guard 완화, `skip`/`only`/`todo` 또는 assertion 삭제가 없다.

## 새 설치ㆍ빌드ㆍ회귀

| 검증 | 결과 |
| --- | --- |
| fresh `frontend/npm ci` | `PASS`, 370 packages, audit 0 |
| `node --test poc-mcl-capture.test.mjs` | `PASS 7/7` |
| scheduler + store + MCL focused suite | `PASS 23/23` |
| `npm run lint` / `npm run typecheck` | `PASS` / `PASS` |
| `uv run python scripts/verify_static.py` | `PASS` |
| `npm run build:poc` | `PASS`; 기존 large chunk warning만 관찰 |
| `npm run test:poc-server` | build 후 `PASS 33/33` |
| Node `22.19.0-bookworm-slim` Docker build | `PASS` |

fresh install 직후의 첫 server regression은 `dist-poc` 부재 때문에 root가 404여서 32/33이었다. 이는 test가 요구한 build precondition이며, `build:poc` 후 같은 명령을 재실행해 33/33 통과했다. 제품 수정은 하지 않았다.

## DEV 읽기 전용 SQL/API 대조

Control Plane 지침에 따라 39083과 기존 pgvector만 읽었다. credential은 읽거나 출력하지 않았고, DataHub metadata, access, CR, DB state를 변경하지 않았다.

- `/healthz`: `ok`; `/api/v1/change-history/access`은 active admin `checkpoint-admin`을 반환했다.
- checkpoint: partition `0`, `first_exact_offset=51815`, `next_offset=51864`, version `50`; offset은 최초 boundary 이후 단조 증가 상태다.
- 고유 태그 `datariver_mcl_foundation_20260814_1426`은 ledger에 정확히 2행이다. ADD는 partition `0`, offset `51817`, ordinal `8`, `2026-08-14T14:26:32.440Z`; REMOVE는 offset `51827`, ordinal `0`, `2026-08-14T14:31:51.892Z`. 두 행 모두 `TAG` / `globalTags` / `EXACT_MCL`, actor `urn:li:corpuser:__datahub_system`이며 ADD < REMOVE다.
- 다른 REMOVE는 같은 offset `51817`의 별도 `TAG` 값 8개(`datariver_execution_applied`, `datariver_object_table`, `datariver_platform_postgres`, `datariver_scenario_ai_accelerator`, `datariver_seed`, `datariver_semiconductor`, `datariver_synthetic`, `datariver_value_chain_finance`) 및 offset `51818`의 `GLOSSARY_TERM` 2개다. 따라서 고유 태그 REMOVE와 혼동되지 않는다.
- ledger는 13 rows = 13 unique event identities = 13 unique `(partition, offset, ordinal)`이다. runtime-only task의 restart read 3회 뒤에도 ledger는 13으로 유지됐고, 이 작업자는 같은 DB 재조회로 현재 13/13/13을 독립 확인했다. weekly API는 4 distinct normalized transactions, `EXACT_MCL=4`, `ADD=1`, `REMOVE=3`, `UNLINKED=4`, `CONTIGUOUS_CAPTURE_RECORDED`를 반환한다. 이는 event-row 수가 아닌 transaction aggregation이다.
- DataHub asset readback의 dataset `tags`는 빈 배열이며 unique tag는 없다.
- compatible CR: `core`의 `change_requests`는 null, CR link events는 0이다. 따라서 link/unlink/reverse는 `NOT_EXECUTED_BLOCKED_TEST_DATA`이고 synthetic CR을 만들지 않았다. `core` hash `79789e4f710df4368a3ed3bca0f66ae1`, version `23`, access hash `74050e15e3a1b89b6d1686fbabeb82ba`, version `1`은 읽기 전/후 조회에서 같았다.
- active admin GET은 성공했다. stored authority를 바꾸지 않고 viewer로 subject-switch할 안전한 방법이 없어 `RUNTIME_SUBJECT_SWITCH_DEBT`다. source server regression의 viewer fail-closed test는 통과했다.

## Scheduler 재확인ㆍdebtㆍ정리

초기 조회 시 receipt가 없었으나, 40 runtime-only task 완료 뒤 위 durable receipt가 생성됐다. Controller가 보고한 restart read 3회에서는 receipt version 1, ledger 13, checkpoint `next_offset=51864`/version 50이 변하지 않았고, 본 작업자는 같은 DB에서 그 최종값을 read-only 재확인했다. 따라서 startup catch-up 및 same-day suppression의 runtime 결과는 해당 durable receipt와 restart read report로 확인한다. source focused test의 singleton/lock은 별도의 source-contract evidence이며, live lock 경쟁을 직접 관찰한 증거로 과장하지 않는다. `DAILY_CLOCK_NOT_OBSERVED`는 실제 다음 일 경과를 관찰하지 못한 debt다.

Control Plane의 read-only 제한 때문에 이 작업자는 capture replay, candidate restart, scheduler trigger/lock을 직접 실행하지 않았다. 이들은 `NOT_EXECUTED_BY_50_READ_ONLY_CONSTRAINT`다.

독립 검증 중 생성한 `datariver-mcl-validation-9a7eb98` container는 시작 전에 제거했고, `datariver-mcl-validation:9a7eb98` image도 제거했다. 기존 `39083`, pgvector, Redis, Neo4j와 지원 서비스는 보존했다. G1/G2/G3/G4는 모두 `NOT_APPROVED`다.
