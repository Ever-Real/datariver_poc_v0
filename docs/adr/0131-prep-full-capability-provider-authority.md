# ADR 0131: PREP full-capability provider authority

## Status

Accepted.

## Decision

PREP exposes only DataRiver web on `0.0.0.0:39083`. PostgreSQL, Neo4j and Redis stay loopback-only.
Literal loopback, RFC1918 and IPv6 ULA origins may deliberately use HTTP on the intranet. A reviewed
operator CIDR allowlist may additionally admit a non-RFC1918 company range without creating a
hostname, wildcard or public/unbounded HTTP exception. Unapproved public HTTP is
rejected and authentication/authorization remain unchanged.

The two default managed graphs use the Product-owned `K9_POLICIES` pins as their built-in policy
authority. They are reconciled in local PostgreSQL and projected from one live DataHub snapshot to
local Neo4j. A second Studio PostgreSQL whose only deployment use was `SELECT 1` is not an authority
and is removed from the enablement contract.

Change History connects to the configured DataHub Kafka rather than deploying another broker. It
discovers cluster identity, exactly one supported versioned MCL topic, the GMS-internal or explicit
external Schema Registry, the exact value subject/schema hash, DataHub version, and a deterministic
source identity. Only sanitized hashes/identifiers are persisted. New identities begin at the
earliest retained offset; existing checkpoints are never reset and retention loss remains explicit.

Quality Read is DataHub Assertion metadata/result retrieval through GMS, including assertions
produced by an existing GX runtime. Quality Execution reuses the existing approved Airflow quality
dispatch when configured. Zero assertions is a valid read-ready state, and no duplicate GX runtime
is deployed.

## Consequences

`./scripts/prep39083 deploy` remains the only deployment command after target-owned external
connectivity is configured. Provider discovery happens before Product-owned durable mutation;
built-in K9 refresh, MCL checkpoint creation, and bootstrap remain idempotent and target-local.
