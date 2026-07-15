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
