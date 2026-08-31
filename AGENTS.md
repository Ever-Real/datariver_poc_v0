# DataRiver agent operating guide

This file applies to the whole repository. Product requirements and accepted ADRs remain
authoritative; an agent may not silently relax a security invariant or production gate.

## Operating model

- The primary agent owns scope, sequencing, integration, final verification and the user-facing
  decision record.
- Delegate only a concrete, bounded task with explicit file ownership and an independently
  verifiable result. Read-only review is preferred when several agents share one working tree.
- Do not let two agents edit the same file or generated artifact concurrently. The primary agent
  regenerates migrations/locks and resolves cross-cutting changes after delegated work completes.
- A delegated result is evidence, not automatic acceptance. The primary agent reads the relevant
  code, checks assumptions against the controlled documents and reruns the appropriate gates.
- Sub-agents do not choose business capacity, retention, data-classification or release exceptions.
  They identify options and consequences; the accountable product/security/operations owner decides.

## Branch and publication policy

- Keep `dev` and `main` as the source-development branches. ADR-0132 additionally reserves the
  long-lived `prep39083-release` snapshot ref and immutable `prep39083-artifact-<Product>` transport
  branches; do not use those refs for feature work or merge artifact branches into source history.
  Do not create other task, feature, agent or Codex branches unless the user explicitly overrides
  this repository policy.
- Perform ongoing development on `dev` and push each coherent, completed change to `origin/dev`.
  Development and feature pull requests normally target `dev` even though GitHub defaults new pull
  requests to the repository default branch.
- Treat `main` as the controlled PREP promotion branch and GitHub default branch. It advances only
  by a fast-forward of an exact verified Product/Evidence/Handoff descendant from `dev`; never
  commit features directly, force-push, rebase published history, squash, or create a promotion-only
  merge commit on `main`.
- PREP39083 updates its normal release contract only from `origin/prep39083-release`, automatically
  reconstructs the separately pinned exact Product archive from its immutable Git transport branch,
  and runs `./scripts/prep39083 deploy`. Advancement of `origin/dev` alone never changes the PREP
  candidate. `origin/main` retains its separate explicit promotion gate.
  OPS continues to consume only the exact image accepted and exported on PREP, never a Git branch.
- Direct-to-`dev` publication does not waive security, schema or production evidence requirements.
  Report incomplete gates honestly and do not use a branch-policy shortcut to bypass them.

## Preparation-PC delivery policy

- PREP consumes the exact verified Product image as the checksum-pinned OCI/Docker archive named
  by `deploy/prep39083/release.json`; it never rebuilds application source or falls back to a
  registry pull. Transfer that archive only through approved artifact media and stage it at the
  ignored release path before the canonical deploy command.
- Transfer a verified PREP39083 source/Handoff snapshot through `origin/prep39083-release`; transfer
  the exact approved Product archive through the manifest-pinned immutable Git artifact branch.
  Ongoing development remains on `origin/dev`, while `origin/main` remains separately approval-gated.
- Build platform-specific dependency artifacts on a connected host that matches the preparation
  PC's operating system, CPU architecture and pinned toolchain. Platform-independent wheels may be
  prepared on another host only when their lockfile hash and artifact checksum are verified.

## Stable daily development loop

- Treat `./scripts/development_cycle.py dev-publish` on the arm64 Mac as the stable development
  publication interface. Treat `./scripts/prep39083-release prepare --product-sha <SHA>` as the
  isolated release-preparation interface and `./scripts/prep39083 deploy` from the clean dedicated
  PREP release checkout as the normal PREP39083 deployment interface.
- `dev-publish` requires a clean committed `dev`, runs the repository source gates, applies that
  commit to the Mac development runtime, pushes only `origin/dev`, and verifies the exact remote
  SHA. It never creates a branch or merges `main`.
- The older `development_cycle.py prep-update` source-host workflow is not PREP39083 release
  authority and must not be substituted for the `origin/prep39083-release` plus
  `./scripts/prep39083 deploy` contract.
- The canonical daily environment files are `.env.mac-development` on the development PC and
  `.env.wsl-intranet-development` on the preparation PC. They and `secrets/` remain ignored,
  host-local and outside Git. A normal daily update must not require copying, renaming or editing an
  environment file.
- Keep detailed bootstrap, migration, dependency-cache and recovery commands as diagnostic or
  one-time procedures. Do not replace a stable daily action with a new sequence of manual commands
  merely because its implementation changes.

## Recommended review roles

| Role | Bounded responsibility | Required evidence |
|---|---|---|
| Data architect | canonical ownership, schemas, projection/release semantics | ADR/data-model diff, migration review, invariants |
| Security/ABAC reviewer | route matrix, RLS, cache keys, audit and secret boundaries | positive/negative matrix and revocation tests |
| Data engineer/SRE | sync, outbox/inbox, worker leases, partition/retention, recovery | lag/failure tests, EXPLAIN, restore evidence |
| Application reviewer | service/port boundaries, API compatibility, UI states | unit/contract/type/build results |
| Performance reviewer | workload model, load/soak, resource bottlenecks | dataset manifest, k6/DB/Valkey metrics, raw report |

## Change discipline

1. Read `docs/README.md`, the relevant requirement/specification and every applicable ADR.
2. Inspect the working tree before editing. This repository may contain user-owned uncommitted work.
3. Preserve inward dependencies: domain is framework-free; external systems implement application
   ports; cross-context effects do not write another context's tables.
4. Database changes require SQLAlchemy metadata, the generated Alembic migration and
   `docs/06_DATA_MODEL.md` to agree. Architecture changes require an ADR.
5. Treat DataHub, Valkey, graph engines, object storage, Airflow and LLM providers as fallible
   external dependencies. They never become canonical business truth.
6. Never add raw SQL/Cypher/GraphQL/HTTP pass-through, provider credentials in clients, an LLM
   mutation path, or a cache key missing workspace/permission/policy/source-version scope.
7. Report executed evidence exactly. Do not convert a unit/source pass into a production claim.

## Minimum verification

Use the commands in `README.md` and `docs/09_TEST_STRATEGY.md`. At minimum, a backend change runs
Ruff, strict mypy, the relevant pytest set and `scripts/verify_static.py`; a schema change also
regenerates the initial migration and checks its deterministic diff. Security/search/sync changes
need negative cases and an explicit statement of any target-environment gate that remains open.
