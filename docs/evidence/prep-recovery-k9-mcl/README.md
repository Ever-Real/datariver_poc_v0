# PREP K9/MCL recovery evidence

## Disposition

```text
Goal:                         PREP_RECOVERY_K9_MCL_READY
Integrated Product:           71529ba69c2191884144e5f43ab5bc97720be4e9
Starting remote main/dev:     ede617edf47ac3800ad9c4dbcef96729c85c15bc
Actual PREP Product input:    9c960e28d10c5cd7fb748e745860d73c6ffeb2ae
Actual PREP/OPS access:       NOT EXECUTED
Feature WIP integration:      NOT EXECUTED
Historical Migration audit:  NOT REOPENED
```

This release contains only the K9 real-data metadata reconciliation/diagnostic correction, the
previously independently verified MCL normalization correction, their bounded tests, and the
exact disposable recovery fixture. It contains no migration, Compose topology, environment
contract, port, package-lock, Change Management, Admin, Quality, Site Management, or quarantined
feature change.

## Frozen Actual PREP input

The operator-provided state for Product `9c960e28d10c5cd7fb748e745860d73c6ffeb2ae`
was health/login/DataHub `PASS`, followed by:

```text
K9 product_error_code   K9_DATAHUB_SOURCE_FAILED
failure_stage           METADATA_COLLECTION
failure_detail_code     METADATA_IDENTITY_CONFLICT
Default Lineage         FAILED
Metadata Master         FAILED
semantic index          PENDING
deploy attempt          SMOKE_FAILED
```

The historical Product collapsed several local identity invariants into that one detail and did
not persist a staged metadata source profile. The exact historical identity/URN cannot be
retroactively recovered, and no PREP business metadata was copied into this evidence. The new
bounded profiler is the first Product capable of distinguishing the exact locus on a later
failure; this evidence does not invent a more specific historical PREP locus.

## K9 source profiler and identity contract

`DATARIVER_K9_METADATA_SOURCE_PROFILE_V1` follows the same inventory, glossary scroll,
relationship, and assignment source path as the managed refresh. It persists only counts,
bounded enums, page/ordinal values, and SHA-256 identity/shape hashes. It has no field for raw
GraphQL content, descriptions, names, unrestricted URNs, provider exceptions, tokens, or
credentials.

The generic identity contract is:

- Dataset: canonical DataHub dataset URN.
- Column: dataset URN plus exact field path.
- Tag, Glossary Term, Glossary Node: their canonical DataHub URN.
- Relationship: source identity, target identity, and relationship type.
- Exact duplicates are idempotently deduplicated.
- Sparse/rich compatible observations merge deterministically and independently of input order.
- Structural contradictions fail closed with a bounded locus; they do not promote the semantic
  index or either managed graph.

The former catch-all paths now have bounded loci for response-entity mismatch, duplicate Term or
Node identity, duplicate Term/Node parent edge, assignment outside the collected snapshot,
duplicate assignment identity, and relationship identity conflict. Pagination completeness,
source generation, relationship totals, snapshot binding, LKG, authorization, and semantic
promotion fences remain unchanged.

## Actual-PREP-style shape reproduction

The disposable provider uses only synthetic shape values. It presents one current TABLE with one
column and one classification tag, plus the same Glossary Term URN twice: first sparse and then
with richer optional metadata. The exact parent Product reproduces the frozen broad failure:

```text
stage                K9_INITIAL_REFRESH
classification       PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED
product_error_code   K9_DATAHUB_SOURCE_FAILED
failure_stage        METADATA_COLLECTION
failure_detail_code  METADATA_IDENTITY_CONFLICT
attempt phase         SMOKE_FAILED
```

The descendant Product classifies this sanitized shape as `COMPATIBLE_SPARSE_RICH`, merges it
deterministically, and completes both managed graphs. Its persisted bounded profile is:

| Stage | Bounded result |
|---|---|
| Inventory | datasets 1; TABLE 1; VIEW 0; MATERIALIZED_VIEW 0; columns 1 |
| Inventory observations | table tags 1; column tags 0; table Terms 0; column Terms 0 |
| Glossary scroll | provider total 2; pages 1; fetched 2; unique Terms 1; Nodes 0 |
| Duplicate observations | Term 1; Node 0 |
| Scroll | cursor COMPLETE; collection complete |
| Relationships | inspected 2; provider total 0; pages 2; fetched 0; duplicates/mismatches 0 |
| Assignments | declared/observed Table 0/0; Column 0/0; outside snapshot 0; duplicates 0 |
| Identity classification | exact duplicate 0; compatible sparse/rich 1; contradiction 0 |

During the first descendant run, smoke also exposed a separate startup visibility race: an active
non-destructive retry was running while the read model still presented the retained parent
terminal result as current. The scheduler now exposes only its in-process active attempt, startup
begins that attempt before the HTTP listener is observable, and managed-assets reports `RUNNING`
with no current terminal code until the attempt completes. The retained database failure record
is not deleted or rewritten. A new failure still becomes terminal immediately; success replaces
the current result while preserving any prior LKG.

## MCL candidate integration

The integrated delta is derived from the independently verified MCL chain:

```text
Product  16ad344e7bde7ec060816a04b4f40aab40f28097
Evidence ed5f21015772f913f181a6e2e316226f832744a7
Handoff  993be1b522d718790bbf98295da36388720caf45
```

The MCL capture and runtime-normalization modules and the Change History diagnostic read-model
files match that candidate byte-for-byte. The only integration overlap was resolved in the state
store/server while preserving the newer K9 source diagnostics. No MCL work was reimplemented.

The exact integrated image repeats the focused MCL normalization suite, including the case that
rejects an invalid retained offset without advancing its checkpoint, then accepts the corrected
same offset exactly once. The independently verified checkpoint/append sequence remains:

| Step | Checkpoint | Append count |
|---|---:|---:|
| Before rejected offset 0 | 0 | 0 |
| Malformed retained offset rejected | 0 | 0 |
| Corrected same-offset replay | 1 | 1 |
| Repeated replay | 1 | 1 |

Numeric DataHub v1.6.0 epoch-millisecond `created.time` remains supported and normalized to UTC.
The bounded record-shape profiler and exact rejection loci persist no URN, aspect body, schema,
description, provider exception, secret, or token. Source identity, ledger, checkpoints, and
exactly-once append/CAS behavior are preserved.

The integrated Docker recovery fixture additionally seeded a retained MCL checkpoint boundary of
7 twice and read it back as `before=7, repeated=7, after=7`; smoke accepted the resulting bounded
`CAPTURE_PENDING` state without reset, skip, resecret, or source-identity change.

## Verification

```text
K9/MCL/state/server/smoke Node selection  179/179 PASS
Change History/Monitoring UI selection     25/25 PASS
Handoff + migration integrity              15/15 PASS
Exact OCI K9 metadata tests                 PASS
Exact OCI MCL normalization tests           22/22 PASS
Ruff / Python compile                       PASS
ESLint                                      PASS
TypeScript typecheck                        PASS
POC build / application build               PASS
Static/source/migration integrity           PASS
git diff --check                            PASS
```

The build retains only the pre-existing Vite chunk-size advisory. No broad historical migration
review was repeated; the accepted migration checksum/static gate passed.

## Exact OCI

```text
Product revision  71529ba69c2191884144e5f43ab5bc97720be4e9
Image ID          sha256:9df0a63e8c42d3e639ca62b734119dee8b4b5778f6eed74d9d092a72b2148668
Platform          linux/amd64
Runtime user      node
```

The K9 metadata collector/scheduler and MCL capture/runtime-failure module hashes inside the
networkless image match their exact Product Git contents. The focused image probes used a
read-only root filesystem, no network, and an in-memory `/tmp`.

## Same-command descendant recovery

The exact disposable test used the standard deploy flow for both releases:

1. Exact Actual-PREP Product `9c960e28...` created the retained two-graph failure and
   `SMOKE_FAILED` attempt.
2. Exact descendant Product `71529ba6...` was applied without changing the project, named
   volumes, generated secrets, or operator flow.
3. Smoke completed in order: health, administrator login, DataHub bounded read, both managed K9
   graphs and semantic index, MCL source/checkpoint, and GENERAL route/provider.
4. Final attempt phase was `ACCEPTED`, with `resumed_from_product_sha=9c960e28...`.

The existing administrator count remained 1; target users remained 3; K9 and MCP identities each
remained exactly one. Port 39080 was unchanged. Final disposable residue was:

```text
containers 0
volumes    0
networks   0
```

No `down -v`, state reset, volume deletion during deployment, resecret, checkpoint reset, ledger
deletion, graph identity replacement, or Actual PREP/OPS operation occurred.

## Operator boundary

`origin/main` remains frozen pending explicit user promotion approval. After the verified Handoff
is promoted to `main`, the PREP operator uses the unchanged path:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
./scripts/prep39083 deploy
```

The first Actual PREP execution of this Product is still operator acceptance. If the operational
record is a genuine contradiction rather than the compatible shape reproduced here, the new
Product will fail closed with its exact bounded locus/profile instead of silently merging it.
