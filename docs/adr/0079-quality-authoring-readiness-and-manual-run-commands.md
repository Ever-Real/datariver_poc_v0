# ADR-0079: Quality authoring readiness and manual Run commands

- Status: Accepted
- Date: 2026-07-30
- Owners: Product, Data Architecture, Data Platform, Security/Governance
- Refines: ADR-0077, ADR-0078

## Context

ADR-0077 kept human Rule mutations closed until the server could prove an exact field identity,
source connection profile and workload profile for a current local Catalog asset. The Phase 3
execution manifest deliberately solved only worker-side Run replay; using it as a browser
authoring directory would conflate an opaque execution target with a governed Catalog asset.

The existing database lifecycle functions already enforce maker-checker review, WebAuthn
activation, current-target matching, immutable evidence and exact retention binding. Public API
adapters still needed a narrow way to derive their inputs without accepting DataHub URNs, source
coordinates, secrets, SQL, GX classes, retention deadlines or authorization evidence from a
browser.

## Decision

### Additive authoring manifest contract

`QUALITY_SOURCE_MANIFEST_V1` remains a valid execution-only contract. An additive
`QUALITY_SOURCE_MANIFEST_V2` adds:

- a closed logical field type for every execution field;
- an exact field-map/type-map key match;
- an explicit local `asset_id` to source-profile and workload-profile binding;
- a server-derived schema hash over the exact field identities and logical types.

The API loads this deployment-owned file fail-closed. It does not return endpoints, base
relations, source secret references, allowlisted IPs or workload budgets. Manifest replacement is
a deployment operation and takes effect after application restart.

Authoring readiness is true only when the V2 directory exists and the Workspace has one current
active V3 or V4 policy containing `QUALITY_RULE`, `QUALITY_RESULT` and `QUALITY_AUDIT`. Each target
is revalidated against the current local Catalog asset, exact source version, lifecycle,
classification, System, Domain and complete field set. Missing or drifting evidence returns a
sanitized unavailable reason; it never falls back to names, DataHub URNs or example fields.

### Bounded Rule proposal

The public proposal accepts one name prefix, one to 25 unique local asset IDs and one to 100 typed
rules. `NOT_NULL` is available for every declared field; `RANGE` is available only for numeric,
date or timestamp fields. `REGEX`, raw GX configuration, raw SQL and provider identifiers remain
closed.

The application authorizes every target and submits one transaction-scoped repository command.
It locks targets in deterministic asset-ID order, rechecks the server directory and Catalog
projection, resolves retention at database time, and creates one immutable
RuleSet/Version/Definition aggregate per target. A single idempotency result covers the whole
batch; partial browser fan-out is prohibited.

### Review, activation and manual execution

Revision `0071` adds no table or mutable provider configuration. It adds three fixed
`SECURITY DEFINER` wrappers:

- server-derived review assurance and `QUALITY_AUDIT` retention;
- `MANUAL_ONLY` activation with server-derived authorization, schedule and retention hashes;
- manual Run creation that atomically inserts the canonical Run, first Run event and outbox event.

The exact authorization decision ID returned for the current request is passed to each wrapper;
the repository never searches for a merely recent decision. Review and activation require a
quoted positive `If-Match`, actor-bound `Idempotency-Key`, current target and the existing
maker-checker controls. Activation keeps its recent hardware WebAuthn requirement. A stale
version is HTTP 412, a missing precondition is HTTP 428 and an exact replay returns the prior
result.

Manual execution remains unavailable unless authoring readiness is true and the isolated Quality
worker is enabled. The browser cannot insert a Run or outbox row directly. Scheduling remains
unavailable because no deployment-approved schedule profile has been supplied.

## Consequences

- V1 worker deployments remain compatible but cannot expose authoring readiness.
- V2 provides a deterministic authoring identity without making DataHub, Airflow or GX canonical.
- Portable source still chooses no retention duration, source credential, full-scan budget,
  concurrency, schedule or target asset.
- The local development runtime may expose the routes while every mutation capability remains
  honestly unavailable until deployment inputs exist.
- Actual source execution, target DataHub collection, representative load and WSL evidence remain
  external acceptance gates.
