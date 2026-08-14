# 40_DATA_AI_KNOWLEDGE REPAIR-01 검증 증적

- Task: `task_945bd67406d7`
- Dispatch: `ctx_ca34caa7e01b`
- 기준 SHA: `4543ca96353f90d448324fa67ec6e7d3ce2d17e5`
- 제품 commit: `061c6c2`
- 환경: macOS arm64 DEV POC, Node `v25.9.0` (source gate), 임시 POC candidate Node `v22.19.0`
- 결과: `PASS` (DEV POC 한정; TARGET/PREP/OPS 증명이 아님)

## 변경

`kafkajs-snappy`를 정확히 `1.1.0`으로 고정했다. npm metadata와 lockfile은 MIT license 및
순수 JavaScript `snappyjs` dependency만 기록한다. `poc-mcl-capture.mjs`의 KafkaJS infrastructure
boundary에서 CommonJS default import로 `CompressionCodecs[CompressionTypes.Snappy]`를 codec에
등록한다. native binary를 추가하지 않았으며 capture/ledger/scheduler/CR의 기존 계약은 변경하지 않았다.

초기 focused run은 KafkaJS가 ESM named export를 제공하지 않는다는 오류로 중단됐다. 해당 import만
default import destructuring으로 교정한 뒤 모든 아래 최종 gate를 새로 실행했다.

## source gate

| 명령 | 결과 |
| --- | --- |
| `node --test poc-mcl-capture.test.mjs` | `PASS 7/7`; 실제 codec registration 및 Snappy round-trip 포함 |
| `npm run lint` | `PASS` |
| `npm run typecheck` | `PASS` |
| `uv run python scripts/verify_static.py` | `PASS` |
| `npm run build:poc` | `PASS`; 기존 chunk-size warning만 존재 |
| `npm run test:poc-server` | `PASS 33/33` |
| `git diff --check` | `PASS` |

## 실제 DEV POC E2E

동일 POC PostgreSQL/Redis network와 DataHub network에만 연결한 임시 candidate image를 현재 worktree에서
빌드했다. 기존 broker의 `broker:9092` listener는 `localhost:9092`를 재광고하여 첫 candidate가
`ECONNREFUSED`로 fail-closed 했다. source 변경 없이 기존 container listener `broker:29092`로만
candidate를 재생성했고, 그 뒤 health check와 capture가 성공했다.

- durable checkpoint: partition `0`, `first_exact_offset=51815`, 최종 `next_offset=51846`.
- 첫 scheduler capture 뒤 weekly summary는 `EXACT_MCL=4`, `ADD=1`, `REMOVE=3`, `unlinked_count=4`,
  `CONTIGUOUS_CAPTURE_RECORDED`를 반환했다.
- ledger readback은 offset `51815`의 `datasetProperties UPDATE`와 offset `51817`의
  `globalTags ADD/REMOVE` records를 보존했다. raw MCL payload나 credential은 출력/저장하지 않았다.
- 후속 direct capture 두 번은 새 ledger event를 각각 `0`개 추가했다. DataHub가 계속 방출한 unsupported
  records 때문에 Kafka processed-record count 자체는 0이 아니었으나 deduplicated semantic ledger 증가는
  `0`이었다.
- candidate restart 뒤 health, Monitoring dashboard endpoint, `TAG` `UNLINKED` list가 정상이며
  `EXACT_MCL=4`와 ledger event count는 변하지 않았다.

기존 CR 두 건은 모두 `oracle` System이고 capture event는 `checkpoint-postgres-system`으로 해석되어
호환 CR이 없었다. 따라서 link/unlink/reverse mutation을 실행하지 않아 CR aggregate zero-effect를
보존했다. viewer subject를 환경만으로 바꾼 probe는 stored active-admin subject와 일치하지 않아
`401 SUBJECT_UNRESOLVED`로 fail-closed 했다. stored access authority를 변경하지 않았으며 viewer
read-only regression은 `poc-server` source gate의 `33/33`에 포함된다.

## 정리와 한계

임시 candidate 두 개를 stop/remove했고, 임시 image도 삭제했다. 이에 따라 DataHub temporary network
attachment도 제거됐다. merge, push, PREP, OPS, T08, T09, TARGET activation 및 G1-G4는
`NOT_EXECUTED`/`NOT_APPROVED`다. 이 DEV evidence는 TARGET 또는 production claim이 아니다.
