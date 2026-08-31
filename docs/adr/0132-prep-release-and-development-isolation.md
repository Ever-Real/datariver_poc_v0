# ADR-0132: Dedicated PREP release snapshots and Git artifact transport

- Status: Accepted
- Date: 2026-08-31
- Refines: PREP39083 release cycle and exact-artifact deployment contract

## Context

Development may have several Orca worktrees, uncommitted user changes and a `dev` branch that
continues beyond the Product selected for PREP. Requiring an operator to find a clean development
worktree, split an OCI archive, extract Git blobs and re-enter identities coupled these independent
states and made an otherwise canonical deployment error-prone. PREP can use its existing Git
authentication path but cannot use a registry, GitHub Release download or direct Mac transfer.

## Decision

- `dev` remains development integration and `main` retains its separate approval gate. The mutable
  `prep39083-release` ref identifies only the latest PREP-ready release snapshot.
- The development command `./scripts/prep39083-release prepare --product-sha <SHA>` selects one
  committed ancestor of `origin/dev`, creates disposable clean checkouts, runs canonical gates,
  builds one exact linux/amd64 OCI, creates Evidence and Handoff metadata, publishes an immutable
  Product-specific artifact branch, verifies reconstruction, and advances the dedicated ref only
  by a normal fast-forward from its observed prior value.
- If the selected Product is not a descendant of the prior release-only metadata, a release bridge
  keeps the prior release snapshot as first parent and the selected Product as second parent while
  using the exact Product tree. This lets `dev` advance independently and keeps PREP pulls
  fast-forward-only. Runtime inputs after the Product must remain unchanged.
- `deploy/prep39083/transport.json` pins the artifact branch, commit, tree, ordered chunks, size,
  SHA-256, Product, Evidence and artifact Handoff. PREP fetches that exact ref, uses `git archive`
  without merging it, reconstructs in a target-local temporary directory, validates the OCI, and
  atomically stages the approved archive before any persistent deployment mutation.
- PREP stateful operations use a kernel advisory lock. The lock file carries diagnostic metadata,
  but lock ownership—not a PID file—decides whether an operation is active. Receipts remain the
  recovery authority after terminal loss.
- `./scripts/prep39083 status` gives the short receipt/health/next-action projection without
  requiring environment parsing, Docker logs or secret-bearing diagnostics.

## Consequences

- Dirty development worktrees are never stashed, reset, cleaned or switched by release tooling.
- PREP normal operation is `git pull --ff-only origin prep39083-release` followed by one deploy
  command; artifact fetch, reconstruction, checksum, Docker load, doctor gates, migration and smoke
  remain internal and fail-closed.
- Binary chunks remain isolated on immutable transport-only branches and are never merged into
  `dev`, `main` or the dedicated release source history.
- Old artifact branches, accepted markers, failed attempts, volumes and runtime secrets remain
  valid historical evidence. No registry, Git LFS or new network service is introduced.
