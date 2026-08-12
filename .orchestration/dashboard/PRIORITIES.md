# PRIORITIES.md

| Rank | Task | Status | Owner | Risk | Dependency | Gate |
|---|---|---|---|---|---|---|
| 1 | ARCH-SEC-001 | READY | 10 | R3 | CP-RECON-DOC-001 | NONE for planning |
| 2 | SEC-INGRESS-001 | BLOCKED_BY ARCH-SEC-001 | 30 | R3 | ARCH-SEC-001 | G1 before integration |
| 3 | STATE-BOUNDARY-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | G1 |
| 4 | EVIDENCE-INTEGRITY-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | G1 |
| 5 | PROVIDER-WRITE-001 | BLOCKED_BY ARCH-SEC-001 | 40 | R3 | ARCH-SEC-001 | separate user gate |
