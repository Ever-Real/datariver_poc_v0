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
- Notification sessions ([ACTION REQUIRED]) are UI/coordination surfaces, not Git worktrees unless they own files.
- Preflight Check: Before any Task action, the worker must run `cd` to the exact assigned worktree, `pwd`, `git rev-parse HEAD`, `git branch --show-current`, and `git status`. If there is a mismatch, the worker must stop and notify the Controller. Do not scan parent/sibling/main checkout.
- Canonical Product checkpoint invariant: local worktree `HEAD` is never assumed to be the
  canonical Product checkpoint. Before validation, deployment, status reporting or handoff, verify
  the exact Product SHA and deployed OCI revision against canonical `CURRENT.md`/Evidence lineage;
  record repository/document HEAD separately. A later docs/evidence commit or untracked handoff
  artifact must not silently replace the verified Product SHA.

## Handoff & Cleanup
- Checkpoint/handoff required for completion.
- Conflict rules: G1 remains required before source integration; G2 before publication; G3/G4 unchanged.
- Cleanup conditions: Archived/removed only after checkpoint/evidence and controlled integration disposition.

## Session Lifecycle & Durable Memory
- Canonical long-lived coordination sessions (including `CONTROL_PLANE`, `ARCHITECTURE`,
  `QUALITY_VALIDATION`, `PLATFORM_RELEASE` and `DEV_INTEGRATION`) are preserved while idle.
- Child/worker sessions and their terminals are task-scoped. A completed worker is not kept alive
  merely as a reference once its result is recorded.
- Before cleanup, the parent records only durable resume state: result/status, blocker,
  evidence/reference, exact next action and any exceptional preservation requirement. Historical
  reasoning remains in evidence or handoff artifacts, not in a live session.
- A completed worker/session/terminal may be gracefully closed only after its handoff is present in
  canonical memory and no foreground task remains. `working` or uncertain sessions are held, not
  force-terminated.
- Before creating a new worker, reuse an existing suitable worker when possible. Superseded retry or
  duplicate workers are cleaned up after the replacement checkpoint is accepted.
- At milestone/gate close, perform a bounded orphan-session/terminal sweep. Preserve project
  services, required containers, branches, worktrees and untracked artifacts unless a separate
  explicit cleanup authorization exists.
- Long-lived context belongs in canonical memory/documents; it must not be represented by a growing
  collection of persistent agent sessions.
