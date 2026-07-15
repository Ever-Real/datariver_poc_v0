# ADR-0002: Canonical ownership and DataHub boundary

- Status: Accepted
- Date: 2026-07-14

## Decision

External DataHub owns applied catalog metadata. DataRiver PostgreSQL owns change intent, approval, audit, jobs, ABAC and knowledge releases. DataHub access is a typed anti-corruption adapter; UI and generic API pass-through are forbidden.

## Consequences

Catalog projections can be rebuilt. Writes require governance/outbox/reconciliation. DataHub outages cannot falsely complete requests, and provider credentials never reach clients.
