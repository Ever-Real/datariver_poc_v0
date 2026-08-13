# 영수증: CHANGE-HIST-T04-INDEPENDENT-VALIDATION

## provenance

- Orca run: `run_fe1ea01316d1`
- task: `task_137c260299b8`
- dispatch: `ctx_129bac464483`
- owner role: `50_QUALITY_VALIDATION`
- actual model: `gpt-5.6-sol` controlled fallback, reasoning High
- exact candidate: `a52eb4f6f66ae315d7a73ee703f04eaa3326bd63`
- product SHA: `5cc3652cdc82d2a033edd95003e0f5f6525c7e0e`
- base for diff: `9fb7deaa88dfd03d6604ecfd5e86b3c8a8c69a83`
- evidence commit: 이 receipt를 포함하는 focused local commit; exact SHA는 coordinator message에 기록
- 허용 쓰기: 이 receipt와
  `.orchestration/evidence/CHANGE-HIST-T04-INDEPENDENT-VALIDATION.md`만 사용

## 결과

- verdict: `FAIL`
- blocker: `BLOCKED_BY_INITIAL_CHECKPOINT_AND_CONTENT_TYPE_FENCE`
- `F-01 HIGH`: checkpoint 없는/빈 partition에서 durable boundary를 쓰지 않아 이후 retention gap을
  조용히 건너뛸 수 있음
- `F-02 MEDIUM`: GenericAspect `contentType`을 검증하지 않아 `application/avro` wrapper도 JSON value이면
  정상 supported event로 수용함
- source/product/dependency/test repair: `NOT_EXECUTED`

## PASS evidence

- focused Node `10/10`, 전체 frontend ESLint, POC build, build 후 POC server `28/28`
- exact direct dependency/lock pins, integrity, no added native artifact, scoped license evidence
- fixed high watermark/bounded count, existing-checkpoint retention check, atomic record/zero-event append,
  replay/dedup/restart, secret/log/bounds 및 allowlist/static scan
- `git diff --check`와 conflict marker scan

최초 server suite를 build와 동시에 실행했을 때 `dist-poc` 교체 경합으로 root 1건만 404여서 27/28이었고,
build 완료 후 동일 명령 단독 재실행은 28/28 PASS였다. 이 경합은 F-01/F-02 판정 근거가 아니다.

## cleanup / NOT_EXECUTED

- builder `frontend/node_modules` 임시 symlink: 제거 완료; install/change 없음
- local Node `v25.9.0`; Node 22.19+/Linux AMD64: `TARGET_RECHECK_REQUIRED`
- live Kafka/Schema Registry/PostgreSQL/runtime/provider/container 및 PREP/OPS: `NOT_EXECUTED`
- merge/push/publication, `datariver_v1`, G1/G2/G3/G4: `NOT_EXECUTED` / `NOT_APPROVED`

## next repair acceptance

모든 partition의 최초 boundary를 consume 전에 durable하게 영속화하고 빈-run/retention/new-partition
negative를 추가해야 한다. 또한 GenericAspect의 승인된 JSON content type만 허용하고 누락/미지원
encoding을 해당 offset 앞에서 거부한 뒤 fresh independent validation을 다시 수행해야 한다.
