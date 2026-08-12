# ADR-0115: Isolated POC Compose state and cache topology

- Status: Accepted for the authentication-free POC only
- Date: 2026-08-11
- Owners: POC application and operations owners
- Refined by: ADR-0116
- Does not modify: ADR-0033 production connector ownership or canonical platform authorization

## Context

The authentication-free POC must still run with `npm run poc`, but browser-memory-only users,
Change Requests and administration records disappear on refresh or server restart. Repeated full
DataHub inventory reads also make the hierarchy feel slow. Neo4j is already Compose-owned for this
POC, while the target DataHub, Airflow, MinIO and inference services remain independently operated.

## Decision

The POC Compose project starts three private, non-published supporting services: PostgreSQL with
pgvector, Redis and Neo4j. PostgreSQL stores only versioned POC adapter state in `poc_state`; it is
not the production DataRiver schema and does not replace the canonical SQLAlchemy/Alembic model.
Redis stores short-lived DataHub inventory and detail cache entries only. Redis loss can increase
latency but cannot remove POC workflow records. Neo4j remains a rebuildable graph/evidence service.

The same Node server provides a fixed, same-origin state API with an allowlist of scopes. It never
accepts SQL, Redis commands, Cypher or provider credentials from the browser. Users, Change
Requests and System directory records are persisted through the `core` scope. Knowledge and
Governance may use their own scopes as their POC adapters are completed. No example business data
is seeded.

`npm run poc` remains valid without PostgreSQL or Redis: the server uses process memory and the
browser can still use the same fixed state API for the life of that server process. Redis failures
fall back to live DataHub reads. Compose supplies the private PostgreSQL/Redis coordinates and a
single operator-chosen PostgreSQL password. Image names remain `.env`-overridable for a closed
network with preloaded images.

All POC functions are open to the one POC identity. This is an adapter policy, not a production
authorization change. Production OIDC, ABAC/RLS, maker-checker, retention and external Redis
decisions remain unchanged and cannot point at this POC database.

## Consequences and evidence

- ADR-0116 activates pgvector as a bounded, rebuildable full-inventory Catalog embedding
  projection for POC Chat. Its presence remains neither a production recall/latency claim nor a
  replacement for Redis catalog response caching.
- The single-node database volume needs operator backup if POC records matter. It is not HA,
  production retention evidence or a production restore claim.
- Source verification covers npm fallback, fixed state routes, Redis fallback, Compose rendering,
  frontend contracts and browser behavior. Prep/operations image availability and live provider
  results remain target-environment gates.
