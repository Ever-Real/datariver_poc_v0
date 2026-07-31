# ADR-0083: Knowledge information profiles and bounded document Proposal timeout

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Knowledge Platform, Application
- Refines: ADR-0069, ADR-0070, ADR-0072, ADR-0076

## Context

Domain administration and released Property metadata were split across two first-depth menu
entries even though both are controlled information used by the same Knowledge Asset workflow.
The Instance Management route had no approved aggregate and therefore could not offer working
Property detail management without mock state.

Property description, unit and synonyms must evolve without rewriting an immutable Ontology
release. They also require an exact released-Property identity, optimistic concurrency,
idempotency, workspace isolation and the same domain and classification authorization envelope as
the owning graph.

The document-to-T-Box route currently makes a bounded synchronous call to the configured inference
provider. The provider timeout can be as high as 120 seconds, but the generic reverse-proxy read
timeout was 30 seconds. The proxy therefore emitted a 504 before the API could return either the
validated Proposal or its typed dependency error.

The Studio DB selector also used a narrow stacked list and checkbox layout. Its search already
delegated to the governed Catalog service, but the UI did not make its Dataset-only and Draft
classification ceiling visible.

## Decision

### One Information Management workspace

The Knowledge menu exposes one first-depth **정보 관리** entry after **조회 및 생성**. Domain CRUD
and Property Profile CRUD are tabs in that workspace. The previous `knowledge-profiles` location
remains a compatibility alias to the same page and does not create a second state or API.

The third tab documents, but does not simulate, the next Asset-management increment:

1. Asset and immutable Release selection;
2. Property Profiles;
3. A-Box Binding evidence;
4. PostgreSQL outbox and Neo4j Projection receipts.

Registry continues to own Asset discovery, creation and version focusing. Graph Builder continues
to own only T-Box topology and lightweight Property name/type authoring.

### Released Property Profile aggregate

`knowledge.property_profiles` is the mutable PostgreSQL aggregate root. It references exactly one
immutable Property `ontology_element` from the graph's active Studio Release and retains the graph,
release, ontology version and stable Property identities as database-enforced references. Composite
references prove that the Release selects the same ontology version and that the referenced element
has the exact stable ID and `PROPERTY` kind. The API publishes the standard UUID URN
`urn:uuid:<ontology_element_id>`; it does not invent a provider or business namespace.

Description and unit live on the aggregate. Synonyms are normalized Unicode NFC values in
`knowledge.property_profile_synonyms`, deduplicated case-insensitively and limited to 50 values.
An empty profile is invalid. Archive is a lifecycle transition; the application has no parent-row
delete permission. A partial unique index permits exactly one active profile per released Property
while retaining archived predecessors, so a steward may create a new active profile after archive
without erasing history.

Reads require `kg.read`, use the caller's classification clearance and allowed domains, and return
only active released Properties. Create, update and archive require `kg.edit` against the owning
graph's exact domain and classification resource. Both tables use forced workspace RLS. Mutations
use typed request schemas, idempotency keys and quoted-version `If-Match` checks. The repository
locks and rechecks the graph's active Studio Release before a fresh mutation can commit, preventing
a concurrent Publish from attaching edits to a just-superseded target. This aggregate does not
mutate Neo4j directly.

The browser retains one idempotency key for the same create/update/archive payload across ambiguous
transport failures and rotates it only after success or a materially different operation. A
committed mutation therefore remains replayable when its HTTP response is lost.

Profiles intentionally remain bound to the immutable Release Property in this increment. Carrying
a profile across a later Release requires an explicit, reviewed stable-ID migration workflow; the
application must not silently attach old semantics to a structurally changed Property.

### Governed Catalog selector presentation

Studio search continues to call the same authorization-pruned Catalog service as the primary
search page. It additionally limits candidates to supported Dataset/Table/View types and the
current Draft classification ceiling because only those records satisfy the typed T-Box Proposal
contract. Both the result directory and selected-field directory use TanStack Table. No browser
fallback, fabricated record or provider-side query is introduced.

### Scoped document Proposal proxy timeout

Only the exact document-Proposal API path receives a deployment-configurable reverse-proxy read
timeout. Its default is 135 seconds, above the current 120-second provider maximum, while request
send timeout and the generic API timeout remain unchanged. The value is validated at container
startup and bounded to 900 seconds.

This is an operational compatibility bridge for the existing bounded synchronous endpoint, not a
claim that long-running inference is a durable job. Large or slow production Proposal generation
still requires the background job, lease, progress, cancellation and retry contract accepted by
ADR-0069/ADR-0072 before that production gate can be closed.

## Consequences

- Domain and Property detail management share one discoverable Information workspace without
  duplicating canonical state.
- Released T-Box structure remains immutable while curated Property semantics gain real CRUD,
  RLS, ABAC, ETag and idempotency controls.
- Archived profiles remain evidence, and the same released Property can later receive one new
  active profile without reviving or deleting the archived row.
- Profile carry-forward cannot happen implicitly across Releases.
- DB search has a readable table layout and clearly states why its governed candidate set can be
  narrower than the general Catalog.
- Document inference can complete or return its typed API error instead of being preempted by the
  generic 30-second proxy timeout.
- The durable asynchronous document Proposal production gate remains open and explicit.

## Verification

- Domain and service tests cover Unicode normalization, synonym deduplication, empty-value
  rejection, authorization and optimistic mutation inputs.
- Persistence tests inspect composite references, forced RLS, least-privilege grants and
  deterministic revision `0076`.
- Component tests cover menu consolidation, Profile API CRUD, response-loss idempotency replay,
  post-archive re-creation, the nearly invisible persisted block-title border, Proposal apply-mode
  layout and TanStack Catalog field selection.
- Nginx configuration tests verify that only the exact document Proposal path receives the longer
  validated timeout.
- Full Ruff, strict mypy, pytest, static verification, TypeScript, ESLint and production build.
