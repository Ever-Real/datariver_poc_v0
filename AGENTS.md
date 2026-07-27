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

- Keep only the long-lived `dev` and `main` branches. Do not create task, feature, agent or Codex
  branches unless the user explicitly overrides this repository policy.
- Perform ongoing development on `dev` and push each coherent, completed change to `origin/dev`
  promptly so the preparation PC can test the current source without waiting for a release merge.
- Treat `main` as a deliberate checkpoint branch. Merge `dev` into `main` only when the user asks
  to preserve or release a tested checkpoint; a routine development save does not target `main`.
- Preparation and development PCs update application source from `origin/dev`. Production or
  release workflows continue to use `main` and the accepted production gates.
- Direct-to-`dev` publication does not waive security, schema or production evidence requirements.
  Report incomplete gates honestly and do not use a branch-policy shortcut to bypass them.

## Preparation-PC delivery policy

- Do not use Docker images, containers or registries to transfer or deploy the application between
  the development PC and the preparation PC.
- Transfer source through `origin/dev` and transfer approved, checksum-verified dependency
  artifacts separately when the preparation PC cannot reach an external package index.
- Build platform-specific dependency artifacts on a connected host that matches the preparation
  PC's operating system, CPU architecture and pinned toolchain. Platform-independent wheels may be
  prepared on another host only when their lockfile hash and artifact checksum are verified.

## Stable daily development loop

- Treat `./scripts/development_cycle.py dev-publish` on the arm64 Mac and
  `./scripts/development_cycle.py prep-update` on the amd64 Linux/WSL preparation PC as stable
  operator interfaces. Do not rename them, change their existing action semantics, or add required
  daily arguments without an explicit operator migration plan.
- `dev-publish` requires a clean committed `dev`, runs the repository source gates, applies that
  commit to the Mac development runtime, pushes only `origin/dev`, and verifies the exact remote
  SHA. It never creates a branch or merges `main`.
- `prep-update` requires a clean `dev`, accepts only a fast-forward from the exact
  `Ever-Real/datariver_v1` origin, performs offline dependency sync only when a lock changed or an
  installation is absent, reapplies the ignored source-host environment schema, migrates, starts,
  and verifies API/Web/OIDC health.
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
