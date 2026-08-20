# DEV Knowledge K6 bounded Knowledge Chat runtime

## Scope and lineage

- Canonical K6 start Product: `43e74a0f4a6f696a64aa70ff8afeb681bf14c2d8`
- Canonical K5 closeout Evidence: `9f70f616184ec054ac1edc3de19581eb4fecb856`
- K6 Product / deployed OCI revision: `137bbb331d1dfdb2eef518e3e1d30192adc1b796`
- Status: `COMPLETE_RUNTIME_VERIFIED`
- Git ancestry: `34af2b86...` → `43e74a0f...` → `9f70f616...` → `137bbb33...`
- PREP external-contract recheck: not required for bounded DEV K6; it remains an independent
  deployment gate and PREP was not mutated.

## Minimal implementation

The current Node modular monolith adds bounded graph list, release list, release snapshot and
GraphRAG routes plus the existing Knowledge Chat live adapter. It reuses K2 Asset authorization,
K5 release/version authority and `PROJECTED` receipt, request-time grant/grade/fixed Knowledge
policy, fixed parameterized Neo4j reads and the existing provider. Unauthorized Assets are omitted
from collection results and direct identity requests return concealed 404. No generic Chat or raw
Neo4j path bypasses Asset/version authority.

## Validation

- Focused Node: 30/30 PASS
- Focused frontend: 35/35 PASS
- lint, typecheck, production POC build, Compose render and diff check: PASS
- Product SHA equals deployed OCI revision: PASS

## Bounded runtime proof

The first fixture returned 409 because its Column identity did not match current DataHub schema.
This was classified `FIXTURE_FAILURE`, not a Product defect. After read-only discovery, the single
allowed retry reused the existing K1 exact current `id` Column identity for the disposable fixture.

- Fixture: exactly 3 nodes / 2 relations
- Preview, confirm and identical replay: PASS
- Snapshot and hard reload identity: PASS
- Simple 1-hop question: 2 nodes / 1 relation / 3 citations, provider answer received
- 2-hop question: 3 nodes / 2 relations / 5 citations, provider answer received
- Provenance: exact K5 `PROJECTED` receipt, pinned release and current Table/Column URNs
- Unsafe arbitrary-Cypher-shaped input: 400
- Grant removal: collection hides Asset; direct snapshot returns 404
- Generic Chat/raw Neo4j authorization bypass: absent
- Cleanup: jobs 0, source rows 0, active grants 0, enabled test credentials 0, active test sessions
  0, state references 0, disposable graph nodes 0 and relations 0
- Three disabled disposable credential history rows remain as non-active audit history. Inspection
  admin retained one active session and was excluded from cleanup.

The actual authoritative Node/API path and provider were exercised. Existing UI/live-adapter
behavior is covered by the focused frontend suite; no second conversation store was introduced.

## Complexity guard

New tables, dependencies, services, containers, queues, workers and frameworks: 0. New capability:
1 bounded Knowledge Chat slice using existing authority and provider mechanisms. K7 was not started.
