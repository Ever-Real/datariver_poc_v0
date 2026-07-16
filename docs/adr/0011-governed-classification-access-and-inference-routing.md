# ADR-0011: Governed classification access and inference routing

- Status: Accepted
- Date: 2026-07-16
- Refines: ADR-0001, ADR-0002, ADR-0003, ADR-0009

## Decision

Treat classification-specific Search, Chat and inference routing as workspace-scoped authorization
policy, not deployment constants, browser settings or model-provider configuration. PostgreSQL is
canonical for independently approved policy versions, explicit grants and their audit history.
External inference remains a separate deployment capability and is not enabled merely by creating
or activating a classification policy.

The current static classification access floor remains the fail-closed state whenever no governed
workspace policy is active or policy resolution is unavailable:

- Search and detail cannot return `RESTRICTED` resources.
- Chat cannot retrieve evidence above `INTERNAL`.
- No external inference route is available.

This floor is a portable security invariant, not an organization policy default. Future policy is
intersected with the built-in workspace, action, clearance, system and domain ABAC decision and may
only narrow those permissions. It cannot turn a denied ABAC result into an allow. The only controlled
extensions beyond the unconfigured floor are the typed capabilities defined below; neither can be
expressed as a generic policy exception.

### Classification access policy

Define a `ClassificationAccessPolicy` aggregate with immutable, monotonically numbered versions per
workspace. A version contains exactly one typed rule for each classification, a canonical payload
hash, maker and checker decisions, optimistic version, and `PROPOSED`, `ACTIVE`, `REJECTED` or
`SUPERSEDED` state. At most one version is active for a workspace. Activation requires a different
eligible human checker, recent phishing-resistant authentication and an atomic supersession of the
prior active version.

Rules use bounded enums rather than executable expressions or arbitrary JSON. Search can be
restricted further from the built-in ABAC result. Chat can be denied or constrained to approved
inference profiles. The following rules are non-overridable:

- `RESTRICTED` Chat is denied before catalog, graph or embedding retrieval, including internal and
  deterministic composers.
- `CONFIDENTIAL` Chat can use only an explicitly referenced, currently approved provider-profile
  version. Absence, expiry, revocation or capability mismatch denies the request.
- Cross-jurisdiction transfer is denied. A route is eligible only when its governed destination
  jurisdiction satisfies the workspace's approved residency constraint and all required retention
  attestations are current.
- An unavailable policy, provider profile or routing dependency cannot cause a fallback to a less
  restrictive classification, jurisdiction, provider or retention posture.

The policy does not contain subject lists, provider URLs, credentials, raw prompts, model API
payloads, SQL, Cypher or arbitrary HTTP instructions.

### Explicit RESTRICTED Search grants

Access to `RESTRICTED` Search/detail is a separate `RestrictedSearchGrant` aggregate, not a wider
classification rule. A grant binds one subject to one workspace, an allowlisted resource/system/
domain scope, purpose, validity interval, maker, independent checker, canonical payload hash and
optimistic version. It is scoped, expiring and immediately revocable. A valid grant is still
intersected with the subject's action, clearance and ordinary ABAC scope and never grants Chat,
export, sharing or mutation rights.

Grant approval requires a dedicated high-risk authorization action and recent phishing-resistant
authentication. Role and claim mappings that identify eligible approvers are deployment-governed
identity data; no organization-specific group name is a portable source default. Revocation is
deny-first and does not wait for independent approval or cache expiry.

### Governed inference provider profiles

Provider connection and capability data belongs to the Integration boundary and is exposed inward
through a typed application port. A versioned provider profile records only governed runtime data:
provider and model/deployment identity, internal/external posture, region and jurisdiction,
residency and zero-retention attestations with validity and fingerprints, enabled/revoked state,
and references to operator-managed endpoint and secret material. A product name, region label or
configuration flag is not proof of residency or zero retention.

Classification policy references an immutable approved provider-profile version. The browser and
classification-policy API may select an approved profile identifier but cannot submit or override a
URL, credential, secret, region, jurisdiction, model endpoint or provider request. Profile
provisioning and secret rotation use an operator-controlled registry and secret manager outside the
classification-policy mutation contract. Organization, deployment, infrastructure, provider,
region, jurisdiction and capacity values are runtime approvals and have no source default.

Profile revocation or attestation expiry makes every referencing route ineligible immediately. A
fallback is permitted only to another profile already approved for the same effective
classification and satisfying the same residency and retention constraints. Budget or dependency
failure never authorizes a previously ineligible route.

### Enforcement and inference boundary

Search resolves the active policy and applicable explicit grants before constructing the database
query. Classification and grant predicates are applied in the local projection query before counts,
facets, pagination, enrichment or serialization so hidden-resource existence cannot leak. Per-row
remote policy calls are prohibited.

Chat applies policy twice. Before retrieval, it limits catalog, graph and embedding candidates to
classifications permitted for Chat. After retrieval, it computes the effective classification as
the maximum classification of the authorized immutable evidence and resolves a provider route for
that classification. Explicitly scoped requests containing any `RESTRICTED` resource are denied;
unscoped retrieval never fetches `RESTRICTED` evidence. Citations are re-authorized against the same
policy and evidence versions before response persistence.

Inference executes in a separate assistant worker. The API process does not hold provider model
connections, generate embeddings or execute long inference calls. The worker receives only a
bounded, versioned authorized-evidence package and routing decision, uses a fixed server-side
provider adapter and allowlisted egress, and has no tool surface for model-generated SQL, Cypher,
arbitrary HTTP, catalog/governance changes or graph publication. Model output can propose a typed
changeset but cannot apply it. Missing valid citations or routing evidence returns the governed
insufficient-evidence response without exposing a hidden classification or routing reason.

Routing audit records decision and request correlation IDs, workspace, effective classification,
classification-policy version/hash, grant version where applicable, provider-profile version,
destination jurisdiction, attestation fingerprint, route outcome and bounded token/latency metrics.
It does not record credentials or raw confidential prompt/evidence content.

### Administration contract

Expose typed administrator APIs for current policy/history, policy proposal and independent
decision; approved provider-profile summaries; and scoped grant list, proposal, decision and
revocation. Mutations require `Idempotency-Key`; version-bound decisions require `If-Match`; all
resources are workspace-scoped and protected by forced RLS. There is no mutable active-policy
document, generic policy-expression endpoint, provider pass-through or client-supplied executable
configuration.

The Admin UI presents a fixed four-row classification matrix, current and proposed versions,
canonical diff/hash, approval history and effective enforcement status. Provider choices show only
approved capability metadata, jurisdiction and attestation state/expiry, never endpoint or secret
material. A separate grant panel shows exact subject/scope/purpose/expiry and supports immediate
revocation. Proposal and checker approval are distinct explicit confirmations. Returning from
strong authentication never automatically replays a mutation.

### Cache generation and revocation

Maintain a monotonic workspace security generation in canonical state. Policy activation,
supersession, provider-profile revocation/expiry recognition and grant approval, expiry or
revocation advance the relevant generation atomically with an outbox event. Search, facet,
autocomplete and future Chat-derived cache keys bind workspace, complete permission scope, active
policy ID/hash/version, applicable grant generation, source/projection watermark and request shape.

New protected requests read or validate the canonical generation before using cached data. Valkey
notification and eviction accelerate removal but are not correctness dependencies; a stale cache
entry cannot match the new generation. Chat revalidates policy, grant and provider eligibility
before provider invocation and again before final citation/response persistence. A long-lived stream
uses bounded revalidation and terminates safely after revocation. TTL expiry alone is never the
revocation mechanism.

## Rationale

Membership clearance and action editing answer who may attempt a class of operation, but they do not
express whether sensitive evidence may leave a process, which provider is eligible, or whether a
destination satisfies residency and retention obligations. Combining those concerns in membership
JSON or environment variables would make review, revocation and audit ambiguous and could permit a
browser or provider label to become an authorization authority.

Immutable policy and provider-profile versions make a routing decision reproducible. A separate
explicit grant prevents a broad `RESTRICTED` Search exception from accidentally enabling Chat or
other surfaces. Keeping the inference worker behind typed ports preserves the modular-monolith
ownership rules while allowing independent scaling or later service extraction without granting a
model mutation authority.

## Consequences

- Policy, grant and provider-profile persistence require SQLAlchemy metadata, an Alembic migration,
  forced workspace RLS, least-privilege grants and an updated data model/API/security contract.
- Release tests cover every classification across Search and Chat; missing, expired, revoked and
  cross-jurisdiction profiles; false or stale zero-retention evidence; mixed-classification evidence;
  grant scope/expiry/revocation; cache generation; maker-checker separation; replay and RLS.
- Provider failure and budget fallback tests must prove that no route downgrades classification,
  residency, retention or provider approval requirements.
- Target-environment egress, provider attestation and revocation timing are deployment acceptance
  evidence. Unit tests and provider health checks do not establish residency or zero retention.
- External inference remains disabled until the isolated worker, governed provider profiles,
  classification policy, full negative matrix and prompt-injection/tool-abuse gates are accepted.
- No deployment-specific organization, hardware, capacity, provider, region or jurisdiction value
  is committed as a portable product default.
