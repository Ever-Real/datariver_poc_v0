# ADR-0073: Knowledge domain author bootstrap without ABAC scope escalation

- Status: Accepted
- Date: 2026-07-30
- Owners: Product, Security, Knowledge Platform
- Refines: ADR-0059, ADR-0072

## Context

ADR-0072 made every managed-domain mutation an `admin.manage` operation. The Studio Basic form,
however, intentionally allows a Knowledge author to register a missing workspace domain while
creating an Asset. An author with `kg.create` therefore received a 403, and a domain created by an
administrator was not selectable until a separate membership-domain grant changed. Treating all
managed domains as globally allowed would bypass the existing non-PUBLIC `allowed_domain_ids`
boundary.

## Decision

Creating one managed domain is an idempotent `kg.create` authoring operation. Listing the complete
management inventory, renaming and archiving remain `admin.manage` operations with the existing
ETag fence.

For non-PUBLIC Studio authoring, the picker returns the union of the Subject's explicit
`allowed_domain_ids` and active DataRiver-managed domains whose membership-bound `created_by`
equals that Subject. A Draft create/edit authorization may omit the normal domain-scope comparison
only when PostgreSQL proves the exact active managed-domain UUID, creator and pinned source version
for the Draft owner. This narrow author-bootstrap exception does not grant another Subject access,
does not change membership attributes, and does not apply to review or publish. A reviewer still
requires the normal domain grant before governed publication.

The frontend re-reads `GET /api/v1/knowledge/domains` after create and refuses to continue if the
server does not return the created UUID in the current author scope. The common API client remains
the sole HTTP boundary and injects the Bearer token and Workspace header for both calls.

## Consequences

- Knowledge authors can register and immediately use a missing domain without receiving
  `admin.manage`.
- Existing ABAC membership scopes remain authoritative for every domain not created by that author.
- Domain administration and governed review/publish do not inherit the bootstrap exception.
- The exception is backed by canonical PostgreSQL identity and source-version evidence rather than
  frontend state or token mutation.

## Verification

- Service positives for `kg.create` domain creation and exact creator-owned Draft creation.
- Negative Draft creation for a non-PUBLIC domain outside both membership and creator scope.
- Persistence coverage for authored-domain picker filtering.
- Authenticated browser flow: server-backed domain refresh, create without 403, Draft save and
  Graph Builder transition without 500.
