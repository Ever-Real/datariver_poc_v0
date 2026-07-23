# ADR-0038: Bounded Admin navigation and delta assignment

- Status: Accepted
- Date: 2026-07-23
- Refines: ADR-0024, ADR-0036, ADR-0037

## Decision

Every administrator collection is exposed as a workspace- and filter-bound keyset page. HTTP limits
are from 1 through 100, while the browser requests 25 by default and retains at most 50 prior cursor
tokens. Cursor documents are canonical, bounded to 2,000 characters and bind the exact workspace,
collection, filters and ordered boundary. System-assignee cursors also bind the System version.
Malformed, non-canonical or mismatched cursors fail closed. A cursor is continuation state rather
than authorization evidence: each page repeats administrator eligibility, ABAC and PostgreSQL RLS
checks.

The Admin browser owns separate request generations for each collection and selector. A filter,
section close or newer request aborts the previous request and discards a late result. Mutations
return the affected collection to its first page unless the exact current-page evidence remains the
required editing context. Selectors query bounded active server pages and preserve an already
selected identifier outside the current page as an explicit identifier; they never preload every
member, Role, System or provider profile.

System assignees have a dedicated cursor page and an additive `PATCH` command containing disjoint
`upserts` and `removals`, with at most 100 combined operations. The command is protected by recent
hardware WebAuthn, quoted System-version `If-Match`, idempotency and one transaction. The repository
locks the System and addressed rows, rejects missing removals and identical-only changes, validates
the complete resulting Developer/Data-Steward lanes and emits one bounded audit event. The previous
complete-replacement `PUT` remains a compatibility contract but is not used by the Admin browser.

Audit-log export, security-log export, canonical terminology CRUD, user-profile editing and
user-specific CR/owned-table drill-down remain unavailable because their separately authorized,
masked and paged APIs do not exist. The UI renders one explicit governed-unavailable explanation
instead of tabs, rows or controls that imply those APIs exist.

Development System Settings accept only the exact server-owned mounted-secret reference names for
each connector. TEST remains a fixed typed probe with bounded response handling; inventory reads
only the current and activated revision evidence needed by the screen. Connector credentials,
provider response bodies and raw internal commands are never returned.

Alembic `0043` reconciles the connector probe-scope CHECK only when the exact legacy definition is
present and no-ops on the exact current definition; a missing or malformed same-name constraint is
rejected. Alembic `0044` adds only the six indexes needed by the new keyset contracts, using
retry-safe concurrent creation outside a migration transaction. The current canonical `0001`
contains the same indexes, and the reviewed Phase 2 fingerprint explicitly recognizes that exact
future-index baseline without accepting arbitrary schema drift.

## Consequences

- Browser memory is bounded by the current page, explicit form state and capped cursor history
  rather than enterprise directory or policy-history size.
- Stale responses cannot combine one selected subject/System with another subject/System's mutable
  evidence.
- Large assignee sets no longer require a full replacement payload or first-page-only editing.
- Concurrent index creation is intentionally non-atomic; operators may retry `0044`, but API and
  workers remain stopped until the revision reaches the packaged head.
- Cursor integrity prevents accidental cross-query reuse, not client-selected skipping. Authorization
  and RLS are still evaluated on every page.
- Actual OIDC/WebAuthn browser journeys, WSL `linux/amd64` migration, target-provider probes and
  representative production-size `EXPLAIN (ANALYZE, BUFFERS)` remain target-environment gates.
