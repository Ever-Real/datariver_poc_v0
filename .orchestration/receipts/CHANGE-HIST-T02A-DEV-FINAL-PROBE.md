# 영수증: CHANGE-HIST-T02A-DEV-FINAL-PROBE

## 계약

- exact base SHA: `57c43cf5921bc55a5e2a5d02ec00310943d25320`
- environment: `DEV_MAC_ARM64`
- allowed outputs:
  - `.orchestration/evidence/CHANGE-HIST-DEV-FINAL-PROBE.md`
  - `.orchestration/receipts/CHANGE-HIST-T02A-DEV-FINAL-PROBE.md`
- mutation boundary: 위 두 문서와 이를 담는 focused local commit만 허용

## 결과

- existing MCL record를 `partition=0`, `offset=50422`, `max-messages=1`,
  `enable.auto.commit=false`로 decode했다.
- entity identity를 SHA-256으로 치환하고 aspect/previous/system metadata는 존재 여부, 타입, byte size,
  SHA-256만 기록했다. 원문 payload와 credential은 출력·보존하지 않았다.
- 기존 `generic-mae-consumer-job-client` offset은 decode 전후 `50423`, log end `50423`으로 같았다.
- broker의 effective retention은 `cleanup.policy=delete`, `retention.hours=168`,
  `retention.bytes=-1`, `segment.bytes=1073741824`였고 topic retention override는 없었다.
- 실측 retained offset 범위는 `[46325, 50423)`으로 4,098 records였다.
- 실제 DEV DataRiver web은 native Node 한 process이고 Compose web container는 없었다. 현재 source에
  MCL loop, singleton lock/lease, signal drain, supervised native restart가 없음을 확인했다.
- 실행 위치는 ADR-0123을 보존해 `CONDITIONAL_EXISTING_WEB_PROCESS_CONTROLLER`로 선택했지만,
  단일 Node web process에 무조건 내장하지 않는다. 기존 process 안의 명시적 lifecycle controller와
  PostgreSQL advisory lock/lease/fence가 선행되어야 하며, failure isolation/graceful restart가
  구현·검증되지 않아 T04를
  `BLOCKED_TARGET_RECHECK`로 유지했다. 새 container/service는 필요하거나 승인되지 않았다.

## 증거 한계

- DEV DataHub `v1.6.0` 결과를 TARGET `v1.6.0rc1` PASS로 변환하지 않았다.
- 한 record decode는 capability evidence이며 모든 aspect/event 또는 exact capture 보장이 아니다.
- native process의 CWD checkout은 관찰했지만 실행 artifact에 source SHA가 없어 runtime exact SHA는
  `UNATTESTED`다.
- restart/catch-up, target retention, target payload, target singleton은 재검증이 필요하다.
- TARGET checklist 전 항목의 현재 상태는 `RECHECK_REQUIRED`다.

## 검증

- changed-path scan: `PASS` — 허용된 두 문서만 존재
- new-file `git diff --no-index --check`: `PASS`
- conflict marker scan: `PASS`
- focused local commit: `docs: finalize DEV change capture probe`
- product tests: `NOT_EXECUTED` — product code 변경 없음

## NOT_EXECUTED

- product/provider/Kafka offset·group/container mutation
- dependency install/change
- merge, push, PREP, OPS
- G1/G2/G3/G4 승인
