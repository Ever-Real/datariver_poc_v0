# PRIORITIES.md

## Deferred / Foundation
| Rank | Task | Status | Owner | Risk | Dependency | Gate |
|---|---|---|---|---|---|---|
| 1 | ARCH-SEC-001 | READY | 10 | R3 | CP-RECON-DOC-001 | NONE for planning |
| 2 | SEC-INGRESS-001 | BLOCKED_BY ARCH-SEC-001 | 30 | R3 | ARCH-SEC-001 | G1 before integration |
| 3 | STATE-BOUNDARY-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | G1 |
| 4 | EVIDENCE-INTEGRITY-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | G1 |
| 5 | PROVIDER-WRITE-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | separate user gate |

## Change History
| Rank | Task | Status | Owner | Risk | Dependency | Gate |
|---|---|---|---|---|---|---|
| 1 | TARGET_READ_ONLY_PROBE | PENDING_EXTERNAL_NOTI | 40 | R2 | None | NONE |
| 2 | T02_PLANNING | BLOCKED_ON_PROBE | 10 | R3 | TARGET_READ_ONLY_PROBE | G1 integration |
| 3 | T03_BACKEND_BUILD | BLOCKED_ON_T02 | 40 | R3 | T02 | G1 |
| 4 | T04_EXACT_CAPTURE | BLOCKED_ON_T02_T03 | 40 | R2 | T02, T03 | G1 |
| 5 | T05_RECONCILIATION | BLOCKED_ON_T02_T03 | 40 | R2 | T02, T03 | G1 |
| 6 | T06_ACCESS_CR_APIS | BLOCKED_ON_T02_T03 | 30 | R3 | T02, T03 | G1 |
| 7 | T07_FRONTEND_UI | BLOCKED_ON_T05_T06 | 60 | R2 | T05, T06 | G1 |
| 8 | T08_VALIDATION | BLOCKED_ON_T04_T07 | 50 | R3 | T04-T07 | NONE (No repair) |
| 9 | T09_AUDIT | BLOCKED_ON_T08 | 90 | R3 | T08 | NONE (No repair) |

## Phase Checklist
- [x] Discovery done
- [ ] Architecture blocked on target probe
- [ ] Persistence/Capture/API/UI/Validation/Audit pending
- [ ] PREP/OPS gated

## Long-term Invariants & Short-term Working Memory
- Long-term: current/history separation; Timeline > existing MCL > BLOCKED; nightly non-authoritative; UTC storage/KST week/schedule; indefinite normalized retention/no raw schema duplication; deleted asset excluded current/history retained; CR link no auto-transition; no new DB/container/framework; max two mutating.
- Short-term: discovery base 78e533d; plan commit 8bc8001; T00/T01 done no changes; selected UNDECIDED; next target probe NOTI terminal term_0ab35fd4-b773-4885-b714-3aa2b7715325; G1-G4 not approved.
