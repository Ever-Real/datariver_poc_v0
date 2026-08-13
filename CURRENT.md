# CURRENT.md

## Repository State
- Path: /Volumes/SSD_Mac/workspace/datariver_poc_v0
- Exact SHA: 78e533db6db0352dc0b6d44a557db22a7b05162c (discovery evidence base)
- Branch: dev
- Origin dev: af97af3c5c77449398711fbf33638aad1f980499
- Local Checkpoint Commits: 5628cec, 14e6118, 4c733a1, fe8d229, a9038fc, 78e533d, 8bc8001 (prior plan checkpoint) (No push)
- Origin main: ABSENT
- Environment: DEV_MAC_ARM64
- State: Root clean before this Task. Runtime and product tests NOT_EXECUTED. Product source unchanged.
- PREP and OPS: UNKNOWN
- Note: The existing Ever-Real/dev worktree is explicitly user-authorized as the local 00 orchestration parent for the current session and is not a source candidate; no reset/rebase/delete performed.

## Orchestration State
- Orca restructuring in progress, historical Run run_e7880cbe956e frozen for new work after CP-WORKTREE-TOPOLOGY-001.
- Active execution Run: run_fe1ea01316d1
- Active Product Task: NONE
- Active Mutating Task: NONE
- Active Harness Task: NONE
- Active Validation Task: NONE
- Active Audit Task: NONE
- Next executable: TARGET_READ_ONLY_PROBE external NOTI pending (NOTI terminal term_0ab35fd4-b773-4885-b714-3aa2b7715325)
- Gates: G1 through G4 NOT_APPROVED
- 98 documentation complete after this correction.

## Worktree Topology
- 00_CONTROL_PLANE path /Users/everreal/orca/workspaces/datariver_poc_v0/dev, branch Ever-Real/dev at af97af3..., orchestration-only parent, handle term_fad7860d-0fa4-4760-82fc-79f47b69aa81
- DEV_INTEGRATION path /Volumes/SSD_Mac/workspace/datariver_poc_v0, branch dev, dev at 8bc8001..., child of 00, canonical base/integration, G1 required

## Evidence and Blockers
- DEV runtime STATUS_ONLY evidence: native node listens 39080, /healthz and root HTTP 200, Neo4j/pgvector/Redis Compose healthy; this is not product acceptance or provider validation. External DataHub/LLM etc not probed.
- PLATFORM-RUNTIME-STATUS-001 failed task acceptance for OUT_OF_SCOPE_ARTIFACT_WRITE; 00 independently reverified the inline runtime facts; no repository file modification.
- product source code unchanged in DEV_INTEGRATION from af97; commits contain harness only.
- Completed discovery T00/T01.

## Documents
- [.orchestration/evidence/PROJECT_HANDOFF_RECONCILIATION.md](.orchestration/evidence/PROJECT_HANDOFF_RECONCILIATION.md)
- [.orchestration/checklists/PROJECT_ACCEPTANCE.md](.orchestration/checklists/PROJECT_ACCEPTANCE.md)
- [.orchestration/dashboard/PRIORITIES.md](.orchestration/dashboard/PRIORITIES.md)
- [.orchestration/receipts/CP-RECON-001.md](.orchestration/receipts/CP-RECON-001.md)
- [.orchestration/policies/task-worktrees.md](.orchestration/policies/task-worktrees.md)
- [.orchestration/receipts/CP-WORKTREE-TOPOLOGY-001.md](.orchestration/receipts/CP-WORKTREE-TOPOLOGY-001.md)
- [.orchestration/evidence/CHANGE_HISTORY_EXECUTION_PLAN.md](.orchestration/evidence/CHANGE_HISTORY_EXECUTION_PLAN.md)

## Session Inventory
- 00_CONTROL_PLANE | preferred GPT-5.6 Sol High | actual gpt-5.6-sol | xhigh | term_fad7860d-0fa4-4760-82fc-79f47b69aa81 | persistent active | current task NONE
- 10_ARCHITECTURE | GPT-5.6 Sol High | gpt-5.6-sol | high | ON_DEMAND_TASK_WORKTREE | NOT_INSTANTIATED (do not repair)
- 20_PLATFORM_RELEASE | Gemini 3.1 Pro High | Gemini 3.1 Pro High | high | ON_DEMAND_TASK_WORKTREE | NOT_INSTANTIATED
- 30_IDENTITY_ACCESS | Gemini 3.1 Pro High | Gemini 3.1 Pro High | high | ON_DEMAND_TASK_WORKTREE | NOT_INSTANTIATED
- 40_DATA_AI_KNOWLEDGE | Gemini 3.1 Pro High | Gemini 3.1 Pro High | high | ON_DEMAND_TASK_WORKTREE | NOT_INSTANTIATED
- 50_QUALITY_VALIDATION | Gemini 3.1 Pro High | Gemini 3.1 Pro High | high | ON_DEMAND_TASK_WORKTREE | NOT_INSTANTIATED (repair forbidden)
- 60_FRONTEND_UX | Gemini 3.1 Pro High | Gemini 3.1 Pro High | high | ON_DEMAND_TASK_WORKTREE | NOT_INSTANTIATED
- 90_ASSURANCE_SECURITY | GPT-5.6 Sol High~XHigh | gpt-5.6-sol | high | ON_DEMAND_TASK_WORKTREE | NOT_INSTANTIATED (do not repair)
- 98_EVIDENCE_REPORT | Gemini 3.1 Pro Low | Gemini 3.1 Pro Low | low | term_c7014f8f-7603-45c4-9174-4a1d71b41675 | persistent active in DEV_INTEGRATION | current task NONE
- Note: old 10/20/30/40/50/60/90 terminals closed. Active ASSURANCE-ARCH-SEC-001-R1 actual effort High remains compliant and is not restarted. T00/T01 task terminals closed; on-demand roles not instantiated.
