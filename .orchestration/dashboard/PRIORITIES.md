# 우선순위 (PRIORITIES.md)

## 연기됨 / 기반 작업 (Deferred / Foundation)
| 순위 (Rank) | 작업 (Task) | 상태 (Status) | 소유자 (Owner) | 위험도 (Risk) | 의존성 (Dependency) | 게이트 (Gate) |
|---|---|---|---|---|---|---|
| 1 | ARCH-SEC-001 | READY | 10 | R3 | CP-RECON-DOC-001 | 계획 단계는 NONE |
| 2 | SEC-INGRESS-001 | BLOCKED_BY ARCH-SEC-001 | 30 | R3 | ARCH-SEC-001 | 통합 전 G1 |
| 3 | STATE-BOUNDARY-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | G1 |
| 4 | EVIDENCE-INTEGRITY-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | G1 |
| 5 | PROVIDER-WRITE-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | 별도의 사용자 게이트 |

## 변경 이력 (Change History)
| 순위 (Rank) | 작업 (Task) | 상태 (Status) | 소유자 (Owner) | 위험도 (Risk) | 의존성 (Dependency) | 게이트 (Gate) |
|---|---|---|---|---|---|---|
| 1 | TARGET_READ_ONLY_PROBE | PENDING_EXTERNAL_NOTI | 40 | R2 | None | NONE |
| 2 | T02_PLANNING | BLOCKED_ON_PROBE | 10 | R3 | TARGET_READ_ONLY_PROBE | G1 통합 |
| 3 | T03_BACKEND_BUILD | BLOCKED_ON_T02 | 40 | R3 | T02 | G1 |
| 4 | T04_EXACT_CAPTURE | BLOCKED_ON_T02_T03 | 40 | R2 | T02, T03 | G1 |
| 5 | T05_RECONCILIATION | BLOCKED_ON_T02_T03 | 40 | R2 | T02, T03 | G1 |
| 6 | T06_ACCESS_CR_APIS | BLOCKED_ON_T02_T03 | 30 | R3 | T02, T03 | G1 |
| 7 | T07_FRONTEND_UI | BLOCKED_ON_T05_T06 | 60 | R2 | T05, T06 | G1 |
| 8 | T08_VALIDATION | BLOCKED_ON_T04_T07 | 50 | R3 | T04-T07 | NONE (수정 불가) |
| 9 | T09_AUDIT | BLOCKED_ON_T08 | 90 | R3 | T08 | NONE (수정 불가) |

## 단계별 체크리스트 (Phase Checklist)
- [x] 탐색(Discovery) 완료
- [ ] 아키텍처는 타겟 프로브로 인해 차단됨
- [ ] 영속성/캡처/API/UI/검증/감사 대기 중
- [ ] PREP/OPS 게이트 통제됨

## 장기 불변식 및 단기 작업 메모 (Long-term Invariants & Short-term Working Memory)
- 장기 (Long-term): 현재/이력 분리; Timeline > 기존 MCL > BLOCKED; 야간 비권위적(non-authoritative) 동기화; UTC 저장/KST 주간/일정; 무기한 정규화 보존/원시 스키마 중복 없음; 삭제 자산은 current에서 제외하고 history는 유지; CR 링크 자동 전환 없음; 새로운 DB/컨테이너/프레임워크 없음; 최대 2개의 변경 작업 허용.
- 단기 (Short-term): 탐색 베이스 78e533d; 계획 커밋 8bc8001; T00/T01 완료 및 변경 없음; 선택 항목 UNDECIDED; 다음 타겟 프로브 NOTI 터미널 term_0ab35fd4-b773-4885-b714-3aa2b7715325; G1-G4 승인되지 않음(NOT_APPROVED).
