# ADR-0108: Confidential Catalog workspace discovery

- Status: Accepted
- Date: 2026-08-01
- Refines: ADR-0004, ADR-0036

## Context

A CONFIDENTIAL-cleared human should be able to discover active Catalog metadata up to that
clearance across the current Workspace. The existing scoped reader is also reused by Change,
Registration, Quality, Knowledge and Chat, so widening its System/Domain predicate would silently
expand downstream data-use authority. Asset classifications from DataHub must remain intact; a
classification rewrite would break governed lifecycle and Knowledge input contracts.

## Decision

Catalog HTTP presentation alone opts into typed `WORKSPACE_DISCOVERY`. Search preparation retains
the existing `catalog.search` authorization. SQL listing, facets, suggestions, tree and vocabulary
may omit System/Domain intersection only for ACTIVE, non-deleted PUBLIC, INTERNAL or CONFIDENTIAL
projections within the same Workspace, subject clearance and the current classification-access
Search policy. Detail and lineage use the exact `catalog_asset_browse` and
`catalog_lineage_browse` resource types and an independent `catalog.read` decision with the same
classification/lifecycle boundary and durable policy identity.

This is not a post-processing override of a generic denial. The generic built-in policy and the
existing scoped SQL predicate remain unchanged. Explicit action denial, inactive/service identity,
cross-Workspace access, insufficient clearance and a DENY classification policy fail closed.
RESTRICTED assets never use the discovery exception: they still require the existing exact grant
and ordinary System/Domain intersection through generic authorization.

The reader mode is part of cache and cursor material. Detail/lineage audit retains the actual
asset System/Domain while using the presentation-specific resource type and policy reason. The API
returns the existing effective projection classification; no DataHub tag, asset classification,
lifecycle or source data is changed.

## Exclusions

Description mutation, export, Registration/Change targets, Quality, Chat, Knowledge and Knowledge
Studio pickers continue to use the byte-for-byte scoped reader. No migration, DDL, new table,
generic Action or provider write is introduced.

## Consequences

- Workspace-wide discovery is limited to Catalog presentation metadata and the subject's actual
  clearance.
- RESTRICTED and every downstream data-use path retain existing resource scope.
- Revocation, deny or classification-policy change is fenced by request-time authorization and
  mode-bound caches/cursors.
