# ADR-0110: Editable Change Request revision rounds

- Status: Accepted
- Date: 2026-08-02
- Refines: ADR-0027, ADR-0109

## Context

The Change Request workflow already distinguished a recoverable `CHANGES_REQUESTED` state from
terminal `REJECTED`, and approvals, transitions, attachments and test evidence were bound to a
round.  Resubmission nevertheless accepted only a transition reason.  It created another round
whose evidence hash referenced the same request metadata and the same immutable item identifiers;
there was no governed command for changing the title, request reason/content, table selection or
field selection.

Enabling the disabled browser button or updating `governance.change_requests` and
`governance.change_request_items` in place would make historical reviewer decisions refer to
different content.  A direct `round_id` backfill on each item is also historically false: before
this decision, the same item set was intentionally reused by every round of a request.

## Decision

### Immutable snapshot and item membership

`governance.change_request_rounds` is the authority for typed revision metadata.  Each round stores
its revision kind, title, request date, bounded department display value, separate request reason
and content, requested due date, priority, urgency, classification and selected canonical System.
The existing `evidence_hash` remains the only round digest:

- `LEGACY` rows retain their existing hash byte-for-byte;
- new `INITIAL` and `EDITED` rows hash a V2 canonical document containing the typed metadata and
  the ordered item identities/contracts.

There is no second snapshot hash.  The root request keeps only the current compatibility mirror
used by existing list/detail clients: title, combined description, due date, priority, urgency,
classification, current round pointer, state and optimistic version.

The additive `governance.change_request_round_items` relation owns the exact
`(workspace, request, round, ordinal)` membership.  It has composite foreign keys to the round and
immutable item.  Migration `0092` links every legacy round to the unchanged legacy item set,
because that is what the old workflow represented.  It does not rewrite an item ID, item document
or legacy evidence hash.  A new initial or edited round receives newly minted item IDs and links
only to its own set.  `change_request_items.ordinal` remains a physical compatibility field, while
the association ordinal is authoritative for a round. Ordinals remain the repository's existing
zero-based sequence and therefore accept `0` as the first position.

The pre-0092 root did not persist the requester's entered request date. Legacy snapshots therefore
set `request_date` to `NULL`; they do not fabricate that value from `created_at`. Mapping the old
combined description to `request_reason` and leaving `request_content` empty preserves the exact
legacy text while declaring the unavailable split honestly.

Normal application roles may select and insert snapshots, items and associations but cannot
update or delete their immutable content.  The only permitted round update is `closed_at` through
the governed workflow path.

### Revision command

Only an active human original requester with current `change.edit`, no matching deny and current
target/System authority may call the dedicated version-fenced and idempotent revision command.
The request must be an ordinary `CHANGE_INTAKE` in `CHANGES_REQUESTED`.  `REJECTED` remains
terminal.  The generic transition endpoint cannot perform `CHANGES_REQUESTED -> REGISTERED`.

The revision body has the same bounded typed intake shape as initial registration.  The selected
System must exactly match the current round; this decision does not permit cross-System rebinding.
Existing assets and fields are re-read through the Change-target Catalog reader, and manual targets
receive server-minted identities.  Browser locators, binding hashes and provider documents are
never authoritative inputs.

One transaction locks and reauthorizes the current aggregate and dependencies, closes the old
round, inserts the new metadata snapshot, inserts a new item set and associations, records one
transition/outbox/idempotency result, and advances the root mirror to `REGISTERED`.  An exact replay
returns the committed result without another round, item, association, transition or outbox event;
the same key with a different body fails closed.

Revision target search/detail reads are anchored to the request and its selected System and use
`change.edit`; they do not reuse or widen the creation-only `change.create` directory contract.

### Current-round consumers

Aggregate detail, list summaries, target authorization and attachment dependency checks read only
the item set linked to `change_requests.current_round_id`.  Historical metadata, items,
attachments, approvals, transitions and test results stay attached to their original round and are
not moved or reused.

Migration `0092` forward-replaces only the current attachment-finalization function from `0091`.
Its `STORED` authorization path scopes every item query to the current round association while
preserving the `0091` actor/profile/responsibility/mapping/policy checks.  A matching already
`FINALIZED` attachment still returns immediately before mutable authority is re-evaluated.  The
raw single-item DataHub apply function from `0052` is unchanged because editable revisions are
limited to non-executable `CHANGE_INTAKE` requests.

### Downgrade

Downgrade checks for `EDITED` history before changing any DDL and refuses when such evidence
exists.  It also proves the legacy request/ordinal uniqueness can be restored.  With only legacy or
initial-only requests, the root and immutable items still represent the current request, so the
association and snapshot additions can be removed after restoring the exact `0091` finalize
function.  Downgrade never silently discards an edited revision.

## Consequences

- Requesters can make real changes after a recoverable reviewer request without corrupting prior
  evidence.
- A terminal rejection cannot be converted into a revision.  A separate new CR is required.
- Previous attachments are visible as historical evidence but are not moved into the new round;
  an optional new REQUEST attachment belongs only to the new round.
- The current UI can reuse its bounded intake editor in revision mode, but the server remains the
  authority for requester identity, state, System and target currentness.
- Migration and generated baseline tests must prove legacy multi-round backfill, current-round
  reads, zero-based ordinal preservation, non-fabricated legacy dates, append-only privileges,
  exact replay and fail-closed downgrade.
