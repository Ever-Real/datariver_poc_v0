# ADR-0020: Audited administrator review of quarantined DataHub catalog projections

- Status: Accepted
- Date: 2026-07-17
- Refines: ADR-0011

## Context

DataHub assets that have not yet received a governed classification are projected locally as
`RESTRICTED` and `QUARANTINED`. That fail-closed default correctly prevents ordinary Search/detail
from revealing a new asset, but it also prevents the human security administrators responsible for
classification from discovering the full workspace projection. The resulting deadlock makes it
impossible to review the real provider metadata before classifying it.

The required operational outcome is limited: an eligible human security administrator may see every
non-deleted DataHub projection in its own workspace, including the quarantined/unclassified rows.
This is not a generic RESTRICTED Search grant and must not broaden export, Chat, provider access,
mutations, attachments, service identities or cross-workspace access.

## Decision

Introduce the typed internal action `catalog.quarantine.read`. `CatalogService` evaluates it once
per catalog request and appends a durable decision record. It can allow only when all conditions
hold:

- the authenticated subject is active, human and a `security-administrators` member;
- the subject has `RESTRICTED` clearance;
- `catalog.search`, `catalog.read` and `admin.manage` are each explicitly granted and none is
  explicitly denied; and
- the request is bound to the subject's active workspace.

The allowed decision adds a value to the server-only classification-access snapshot. The local
catalog SQL reader then uses only `workspace_id` and `deleted_at IS NULL` predicates for that one
snapshot. Normal snapshots retain the lifecycle, classification, system/domain and grant predicates
defined by ADR-0011. The snapshot value participates in cursor and cache scope hashing, so an
ordinary cached page cannot become an administrator review page, and vice versa.

This is an observation and classification-remediation scope only. It permits the existing typed
DataHub metadata enrichment for an authorized catalog detail, but does not reach catalog export,
Chat evidence retrieval, attachment download, DataHub write or arbitrary provider calls, API
sharing, graph access, any mutation, another workspace, or a service account. The browser receives
only the standard typed catalog responses and never a provider credential, raw provider request or
an authority-bearing role flag.

No recent-password/FIDO2 prompt is required for this read-only review. Strong/recent
authentication remains enforced for the write, delete, approval and configuration actions already
classified as high risk.

## Consequences

- The action is a narrow, audited exception to ADR-0011's unconfigured classification floor, not an
  organization-specific policy default or a user-configurable bypass.
- SQL and service tests must prove normal lifecycle/classification predicates remain for ordinary
  users, the review snapshot remains workspace/tombstone-bound, service identities and explicit
  denies fail, and the cache/cursor scope differs.
- The production acceptance journey must demonstrate all real projected DataHub assets for an
  eligible administrator and zero quarantined rows for an ordinary user in the same workspace.
- Export remains unable to include `RESTRICTED` rows, including those visible through this review
  scope.
