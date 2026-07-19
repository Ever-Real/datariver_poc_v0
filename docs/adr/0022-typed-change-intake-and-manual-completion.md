# ADR-0022: Typed multi-target change intake with accountable manual completion

- Status: Accepted
- Date: 2026-07-19
- Refines: ADR-0014, ADR-0015, ADR-0021

## Context

The v0.3 Change Request modal combines existing DataHub tables, selected columns and proposed new
tables in one CR. Its browser payload and direct provider/object-store behavior cannot be retained
in v1. Existing `DATAHUB_ASPECT` requests remain intentionally single-item: the provider worker
has no durable per-item checkpoint and must not turn a partial multi-aspect mutation into completion.

## Decision

`POST /change-requests/intake` records a multi-target, non-executable `CHANGE_INTAKE` request.
For each existing target, the server re-reads the authorized current catalog detail, creates a
server-bound `DATAHUB_INTAKE` item and stores typed before/requested evidence. A new table gets a
server-minted `MANUAL_DATASET_INTAKE` proposal URN; the browser cannot select its URN, object key or
provider document. Tag/Term suggestions are authorization-pruned catalog vocabulary reads; a newly
typed value is an auditable proposal, not an implicit DataHub vocabulary mutation.

Intake items are never dispatched to the DataHub apply worker. They follow registered, review,
testing and final-review workflow. After independent final approval, an authorized developer/steward
records `COMPLETED` through `POST /change-requests/{id}/complete-intake` with an immutable reason.
This is a human workflow outcome, never an `APPLIED` provider claim. `APPLIED` remains reserved for
a typed DataHub aspect read-back hash reconciliation.

## Consequences

- The v0.3 multi-target/new-table UX is available without a client-held DataHub credential or a
  fabricated provider success.
- Existing executable `DATAHUB_ASPECT` requests remain exactly one item and retain existing binding
  and worker invariants.
- Request/test attachments stay behind the private server-managed manifest boundary; no CR form
  receives a bucket, object key or pre-signed write URL.
- `COMPLETED` contributes to the CR overview completion count while retaining a UI distinction from
  DataHub `APPLIED`.
