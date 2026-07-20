# ADR-0026: Expiring human Workspace membership renewal

- Status: Accepted
- Date: 2026-07-20
- Refines: ADR-0009, ADR-0025

## Context

Registered human users may access the ordinary CONFIDENTIAL operating tier, but that access must be
reviewed every six months. A date rendered only in the browser would neither stop authorization
after expiry nor provide an accountable request and decision. Renewal also cannot silently become
a self-service privilege extension.

## Decision

Human Workspace memberships have `access_expires_at`; service accounts retain an operator-managed
lifecycle and use `NULL`. New local human memberships expire six calendar months after creation.
Migration gives already-overdue human memberships a 30-day transition window so an upgrade does
not silently lock out the installation before administrators can review it.

A member may create one pending renewal request only during the final 30 days before expiry. The
requested expiry is six calendar months after the observed current expiry, not six months after the
request or decision. Every eligible global administrator can read the pending queue. An eligible
administrator with the existing recent hardware-WebAuthn assurance may approve or reject, but the
requester cannot decide their own request. Approval compares the currently locked membership
expiry to the request snapshot before extending it and incrementing the membership version.

The default-Workspace resolver, request authorization subject hydration, administrator eligibility
and system-assignee directory all reject expired human memberships. Renewal request and decision
write immutable outbox audit evidence and use optimistic version/idempotency controls. Email, chat
or external notification delivery is not inferred; the administrator queue is the implemented
notification surface until a typed delivery integration exists.

## Consequences

- A development or production Workspace that wants independently renewable administrators needs
  at least two eligible global administrators before the first expiry window.
- Expired users cannot use an ordinary authenticated session to repair their own access; an
  accountable operator/identity recovery process is required.
- Six-month and 30-day calculations are server-owned. The UI renders server dates and an explicit
  `renewal_request_eligible` fact rather than evaluating local browser time as authority.
