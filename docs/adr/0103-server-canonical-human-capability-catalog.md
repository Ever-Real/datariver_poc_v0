# ADR-0103: Server-canonical human capability catalog and Role assignment boundary

- Status: Accepted
- Date: 2026-08-01
- Refines: ADR-0024, ADR-0036, ADR-0075, ADR-0077, ADR-0080

## Context

The `Action` enum contains 69 values, but the Role editor previously rendered the unstructured
`action_vocabulary` returned by `/admin/me`. It could not explain service ownership, human versus
worker identity, assurance, reason or self-approval posture. Bootstrap and the semiconductor seed
also maintained separate administrator lists. That drift could leave an active local human security
administrator with only a historical subset even though the Role UI appeared authoritative.

Action assignment must remain distinct from self-approval. In particular, `admin.manage` and
`change.raw.create` are assignable to a human Role so a second Admin or bounded Reviewer can be
configured. Assigning either Action does not grant raw secrets, a worker database identity, RLS
bypass or a self-approval exception. `admin.manage` covers operations with different policies, so an
Action-level flag must not imply that provider-profile, grant or IAM decisions are self-approvable.

## Decision

Introduce one framework-free, exhaustive server catalog keyed by `Action`. Every entry declares a
service key, labels and description, actor kind, Role assignability, default-Admin membership,
assurance, reason policy, self-approval metadata and risk. Import validation fails closed unless all
69 Actions appear exactly once and the existing authorization constants match these partitions:

- 64 human Actions are `HUMAN_ROLE` assignable and `default_admin=true`, including
  `admin.manage` and `change.raw.create`;
- only `quality.dispatch`, `quality.execute`, `catalog.profile.collect`,
  `kg.ingestion.execute` and `kg.proposal.execute` are service-principal-only;
- service-only Actions are rejected at human Role request validation, before authorization or any
  repository write;
- current high-risk Action membership remains the source of the assurance parity assertion.

`GET /admin/access-roles/capabilities` publishes the bounded catalog to eligible human security
administrators with membership-read capability. It is private/no-store and contains no credentials,
provider coordinates, subject grants or mutable policy state. The Role UI groups the response by
service and uses its `HUMAN_ROLE` entries as the only selectable vocabulary. Service-principal-only
entries remain visible and disabled for explanation. `/admin/me.action_vocabulary` remains compatible
for existing clients but is no longer the Role editor's source.

Local bootstrap and the optional semiconductor seed derive canonical human administrator Actions
from the same `default_admin` set. Existing local memberships are reconciled by the existing
idempotent bootstrap/seed update paths; no database schema or production identity bootstrap changes.

Self-approval metadata does not activate self-approval. Candidate workflow Actions are marked
`CANONICAL_ADMIN_ONLY` with `PENDING_PROTECTED_BINDING`; the Role assignment boundary cannot assign
that protected exception. `admin.manage` and `erasure.approve` are `NOT_APPLICABLE` at Action level.
Existing maker/checker equality checks, erasure target-owner denial and service authorization remain
unchanged.

## Consequences

- Adding or removing an `Action` without catalog metadata stops application import and tests.
- A custom human Role can still assign every current human Action; this decision narrows only the
  invalid service-principal Action path.
- A4b must define a server-canonical operation catalog and canonical-Admin protected binding before
  any self-approval exception. It must keep provider-profile, grant, IAM and erasure exclusions
  explicit. A4c may then add workflow-specific evidence and UI confirmation; neither is implemented
  here.
- Raw secret access, service identities, direct worker execution, RLS bypass and database superuser
  privileges remain outside the human capability catalog.
- No DDL, migration or `docs/06_DATA_MODEL.md` change is required for A4a.

## Required evidence

1. Catalog tests assert exact `69 = 64 human + 5 service-only` parity, non-empty labels/descriptions
   and fail-closed missing/duplicate behavior.
2. `admin.manage` and `change.raw.create` validate as human Role Actions; each service-only Action is
   rejected before authorization/repository access.
3. Bootstrap and seed tests assert the same 64-Action administrator set, including
   `change.raw.create`, and exclude all service-only Actions.
4. HTTP/OpenAPI tests assert the bounded route, no-store response and complete metadata contract.
5. Frontend tests prove service grouping and descriptions come from the server catalog even when
   `action_vocabulary` is empty, while service-only controls stay disabled. Loading/failure keeps
   save fail-closed, and a late response cannot silently strip an existing Role's Actions.
6. Existing maker/checker and authorization suites remain green; no test may claim that Admin
   self-approval is active.
