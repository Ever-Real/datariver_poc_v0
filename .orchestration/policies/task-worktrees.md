# Task Worktrees Policy

## Lifecycle & Naming
- Task child worktrees are direct Orca children of the 00_CONTROL_PLANE orchestration parent.
- Git-based from the exact controlled dev SHA (DEV_INTEGRATION).
- DEV_INTEGRATION itself remains a separate child/sibling base node, not their lineage parent.
- Branch naming: `local/task/<task-id>` or actual Orca-generated local equivalent recorded in receipt, never pushed.

## Ownership & Lineage
- One mutating owner (role agent) per worktree, instantiated only when a concrete Task exists. Do not pre-create idle role worktrees.

## Rules
- Allowed paths: Strictly enforced per Task.
- Validation/Audit: Sequential read-only inspection; do not repair findings. Validation and assurance are phases of the same Task candidate unless file isolation requires a separate read-only child.
- No auto merge, no push/publication of task branches.

## Handoff & Cleanup
- Checkpoint/handoff required for completion.
- Conflict rules: G1 remains required before source integration; G2 before publication; G3/G4 unchanged.
- Cleanup conditions: Archived/removed only after checkpoint/evidence and controlled integration disposition.
