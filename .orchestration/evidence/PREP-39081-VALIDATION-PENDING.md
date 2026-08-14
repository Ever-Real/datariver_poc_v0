# PREP-39081-VALIDATION-PENDING

## PREP Base Validation Checklist
| 검증 대상 | 상태 | 결과 |
|---|---|---|
| Platform | VALIDATION_PENDING | |
| Search/Catalog | VALIDATION_PENDING | |
| Existing Dashboard/Registration/Chat GENERAL VECTOR GRAPH/Quality/Governance/Glossary/Knowledge | VALIDATION_PENDING | |
| User/System | VALIDATION_PENDING | |
| Weekly summary | VALIDATION_PENDING | |
| CR reverse history | VALIDATION_PENDING | |
| Monitoring native default zero state and external Grafana tabs | VALIDATION_PENDING | |

## MCL/Scheduler Validation Checklist
명령어는 환경 변수/크리덴셜 값 없이 심볼릭 플레이스홀더를 사용해야 합니다.

| 체크 항목 | 검증 명령/판단 기준 | 상태 |
|---|---|---|
| Kafka advertised listener | `<검증 명령/판단 기준>` | PENDING |
| Schema Registry URL | `<검증 명령/판단 기준>` | PENDING |
| MCL topic | `<검증 명령/판단 기준>` | PENDING |
| env delta | `<검증 명령/판단 기준>` | PENDING |
| enable | `<검증 명령/판단 기준>` | PENDING |
| one safe metadata change | `<검증 명령/판단 기준>` | PENDING |
| checkpoint | `<검증 명령/판단 기준>` | PENDING |
| MCL ledger | `<검증 명령/판단 기준>` | PENDING |
| Monitoring +1 | `<검증 명령/판단 기준>` | PENDING |
| unlinked +1 | `<검증 명령/판단 기준>` | PENDING |
| CR link | `<검증 명령/판단 기준>` | PENDING |
| reverse history | `<검증 명령/판단 기준>` | PENDING |
| replay dedup | `<검증 명령/판단 기준>` | PENDING |
| KST catch-up | `<검증 명령/판단 기준>` | PENDING |

## 진급 기준 (Promotion Criteria)
- `PASS` / `PASS_WITH_DEBT` / `BLOCKED`
- 사용자가 결과를 반환하기 전까지는 `PASS` 처리할 수 없습니다.

## 배포 편차 처리 (Drift Disposition Options)
PREP 검증 후 다음 중 선택:
1. tracked Dockerfile common use
2. Dockerfile.local release drift check
