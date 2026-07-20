# ADR-0027: Change-request system-role authority evidence

- Status: Accepted
- Date: 2026-07-20
- Refines: ADR-0003, ADR-0011

## Context

A change request can affect more than one canonical System. Generic `change.review` or
`change.approve` ABAC permission is necessary but does not prove that the actor is the Developer or
Data Steward assigned to every affected System. Role cards inferred in the browser would be false
workflow evidence.

## Decision

Every new CR target stores a canonical `routing_system_id`. Catalog targets derive it from the
server catalog binding; manual intake targets use the active System selected from the authorized
System directory. A legacy item without routing evidence can still be read but cannot progress to
approval/completion.

The workflow has three approval evidence stages:

1. `REVIEW`: before entering TESTING, every target System needs an APPROVED decision from one of
   its active Developers.
2. `TEST`: before entering FINAL_REVIEW, every target System again needs an APPROVED decision from
   an active Developer, representing the separate test/result checkpoint.
3. `FINAL`: every target System needs an APPROVED Developer and Data Steward decision, and the CR
   needs one APPROVED global administrator decision.

The server snapshots the actor's current System/global authority into each approval. One person who
is legitimately assigned the same responsibility to several target Systems may cover those Systems
in one decision. Final Developer, Data Steward and global administrator authority remain
role-separated: the same actor cannot satisfy two of those role classes. The requester cannot give
the final approval. Any rejection at the applicable checkpoint prevents forward progress.

Authorization is evaluated again against current target bindings and active, unexpired membership
before recording the immutable snapshot. Later assignment changes do not rewrite historical
approval evidence. The browser derives pending/completed lanes only from server routing and
approval snapshots.

## Consequences

- Multi-System CRs wait until every affected System has the required role evidence; one arbitrary
  reviewer cannot advance the entire request.
- REVIEW and TEST are no longer collapsed into one transition. Direct IN_REVIEW to FINAL_REVIEW is
  prohibited.
- Notification delivery remains a future integration. The CR list/detail API is the authoritative
  work queue and does not invent assignee messages.
