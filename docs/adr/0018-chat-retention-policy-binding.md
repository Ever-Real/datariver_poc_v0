# ADR-0018: Bind Chat content to an active governed retention policy

- Status: Accepted
- Date: 2026-07-17
- Refines: ADR-0010, ADR-0011

## Decision

Persist a Chat exchange only inside a dedicated workspace-scoped transaction that locks the
retention-policy aggregate and reads its current `ACTIVE` version. The session stores the exact
policy ID and payload hash, database transaction timestamp, calculated retention deadline and the
binding contract version. The deadline is derived from the active policy's `chat_content_days`; no
portable source-code duration is a fallback.

The Chat service performs retrieval and authorization before opening this final persistence unit of
work. Immediately before writing content it sets both workspace and subject RLS context, obtains the
same per-workspace advisory lock used by retention administration, reads the active policy with a
row lock and binds the exchange to database transaction time. Missing or invalid policy state
returns a conflict and writes no Chat session or message.

Session retention evidence is immutable. Appending to an existing session is allowed only while the
same policy version remains active and the session has not expired. Policy supersession, legacy
unbound state or expiry requires a new session. Existing pre-migration sessions are marked
`LEGACY_UNBOUND_V1`; the platform does not fabricate historical policy evidence and never appends to
those sessions.

PostgreSQL independently enforces the contract:

- a composite foreign key binds workspace, policy ID and policy hash;
- insert triggers require the exact active policy, transaction timestamp and calculated deadline;
- message inserts require the current subject to own an unexpired session under that active policy;
- retention evidence cannot be updated, and the application role can update only optimistic session
  version/timestamp columns;
- ordinary application roles have no Chat deletion privilege.

Alembic `0018` is a compatibility bridge over the regenerated canonical `0001`. A clean install
must find the complete baseline contract and validate it; an upgraded database must find none of
the new columns and install them. A partially present contract fails closed. Compatibility
downgrade does not remove objects owned by canonical `0001`.

## Rationale

A fixed 90-day deadline could diverge from the policy administrators approved and could not prove
which version governed a stored conversation. Resolving policy in a separate request transaction
would also leave a race between policy supersession and content persistence. Exact immutable
binding plus database enforcement makes the decision reproducible without granting the Chat route
or an inference provider any retention authority.

## Consequences

- A deployment must activate a governed retention policy through the independent maker-checker
  workflow before Chat content can be persisted. Operators must not seed or update an active row
  directly to make Chat appear available.
- Policy activation affects new Chat sessions immediately. Existing sessions bound to the
  superseded version become read-only historical evidence.
- This decision enables neither automatic expiry deletion nor WORM export. Legal Hold, immutable
  archive verification, one-time destructive execution and target restore evidence remain the
  independent ADR-0010 gates, so retention automation stays `DISABLED_NOT_READY`.
- Chat history/SSE, isolated inference, token budgets and provider routing remain separate delivery
  work and cannot weaken this persistence boundary.
