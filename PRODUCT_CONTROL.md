# PRODUCT_CONTROL.md

## Authority Order
1. Current User
2. AGENTS.md
3. Accepted ADR or Architecture Policy
4. Product or Security Policy
5. .orchestration Policy
6. Current Task Receipt and Evidence
7. Historical Reports

## 00 Control-Plane Responsibilities
- Coordinates the orchestration framework.
- STRICT PROHIBITION: General product implementation or finding repair.
- See .orchestration/policies/command-permissions.md for project policy and runtime limitations (e.g., RUNTIME_PERMISSION_BLOCKED).
- Enforce mandatory COMMAND_PERMISSION_CONTRACT for every session/provider/model.

## Engineering Invariants
- Inspect before change.
- Make minimal scoped changes only.
- No unrelated refactor or unused abstraction.
- No new framework service or container without authority.
- Do not hardcode host, port, path, architecture, credential, or environment values.
- Keep external systems behind adapters and preserve dependency direction.
- Never claim unexecuted tests or reuse PASS from another SHA.
- Never weaken validators, security, or migration guards.
- Keep credentials out of prompts, logs, diffs, and receipts.
- Report executed commands and NOT_EXECUTED honestly.
- Out-of-scope issues are BLOCKED or FOLLOW_UP.
- EXPLICIT PROHIBITION: Hardcoding, hallucinated evidence or status, and architecture-boundary destruction.

## Evidence Isolation
- DEV_MAC_ARM64
- PREP_WSL_AMD64
- OPS_LINUX_AMD64

## Risk and Sequence
- R1: Ordinary feature UI test small change.
- R2: API multi-module DataHub Neo4j pgvector connector Docker Compose.
- R3: Auth security credential DB migration Git publication or PREP OPS mutation.
- R3 Sequence: Planning -> Builder -> Independent Validation -> Fresh Assurance Audit -> User Gate -> Mutation.

## Gates
- G1 SOURCE_MERGE: NOT_APPROVED (Independently user-approved)
- G2 DEV_PUBLISH: NOT_APPROVED (Independently user-approved)
- G3 PREP_MUTATION: NOT_APPROVED (Independently user-approved)
- G4 OPS_MUTATION: NOT_APPROVED (Independently user-approved)

## Role Matrix
| Session | Role | Preferred Model | Ownership / Status / Notes |
|---------|------|-----------------|----------------------------|
| 00_CONTROL_PLANE | Project Manager, Technical Lead, Change Controller, Multi-Agent Orchestrator, Evidence/Gate Controller | GPT-5.6 Sol High | Persistent active. No general product implementation. |
| 10_ARCHITECTURE | Architecture/API/module boundary/ADR | GPT-5.6 Sol High | ON_DEMAND_TASK_WORKTREE. No product repair. |
| 20_PLATFORM_RELEASE | Docker/Compose/environment/release/packaging | Gemini 3.1 Pro High via Antigravity | ON_DEMAND_TASK_WORKTREE. |
| 30_IDENTITY_ACCESS | Authentication/identity/admin access | Gemini 3.1 Pro High via Antigravity | ON_DEMAND_TASK_WORKTREE. |
| 40_DATA_AI_KNOWLEDGE | Catalog/Search/KG/Chat/LLM/DataHub/Airflow | Gemini 3.1 Pro High via Antigravity | ON_DEMAND_TASK_WORKTREE. |
| 50_QUALITY_VALIDATION | Independent validation/regression/static/runtime | Gemini 3.1 Pro High via Antigravity | ON_DEMAND_TASK_WORKTREE. Repair forbidden. |
| 60_FRONTEND_UX | Frontend/UI/UX/browser flow | Gemini 3.1 Pro High via Antigravity | ON_DEMAND_TASK_WORKTREE. |
| 90_ASSURANCE_SECURITY | Fresh independent security/architecture audit | GPT-5.6 Sol High to Max | ON_DEMAND_TASK_WORKTREE. Do not repair findings. |
| 98_EVIDENCE_REPORT | CURRENT/receipt/evidence ledger | Gemini 3.1 Pro Low via Antigravity | Persistent active. |

## Task Policy
- One Task, one responsibility.
- Strict tracking of: exact base SHA, owner role, preferred and actual model, reasoning, branch or worktree, allowed paths, acceptance criteria.
- Local-only Task branches/worktrees are authorized (explicit exception to dev/main-only rule). One Task per branch/worktree, based from the current controlled dev SHA. No push or publication of task branches. No automatic merge/integration into dev.
- One mutating owner per worktree.
- Idle sessions receive no product Task or repository scan.
- Model capacity checkpoint and controlled fallback rules.
- STATUS_ONLY queries do not interrupt workers.
- No automatic heartbeat; use bounded wait and explicit status only when task policy requires.
- Evidence freshness, executed commands, and NOT_EXECUTED.
- Product regression and Mac arm64 to WSL amd64 to Linux amd64 portability boundaries.
- No merge, push, PREP, or OPS mutation without the corresponding Gate.
