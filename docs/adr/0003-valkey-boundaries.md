# ADR-0003: Separate Valkey cache and delivery instances

- Status: Accepted
- Date: 2026-07-14

## Decision

Use one non-persistent, TTL-only, memory-bounded Valkey for cache and a distinct `noeviction`, AOF-backed Valkey for short-lived delivery. PostgreSQL outbox/inbox remains the durable recovery mechanism.

## Consequences

Cache eviction cannot discard work. Queue loss/downtime delays delivery but not intent. Operations monitor independent memory policies and the application must function correctly with no cache.
