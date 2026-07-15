# ADR-0001: Modular monolith first

- Status: Accepted
- Date: 2026-07-14

## Decision

Implement bounded contexts inside one versioned application distribution, with separate API/worker/relay processes and architecture-enforced dependencies. Communicate cross-context effects through ports/events and prohibit cross-context table writes.

## Rationale

The current product and team need clean ownership and reliable transactions more than independent service deployments. Immediate MSA would introduce network contracts, distributed tracing, deployment and consistency cost before boundaries/load are proven.

## Consequences

Local operation is smaller and governance/outbox transactions remain simple. Scaling is process-level initially. A context is extracted only under the criteria in the architecture definition.
