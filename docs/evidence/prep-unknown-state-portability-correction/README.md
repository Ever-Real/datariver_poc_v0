# PREP unknown-state portability correction evidence

Date: 2026-08-29 KST  
Starting Handoff: `af74fc4d0cc99295a0ebfe897ccbaeb94cb5dfe6`  
Product: `6422abe46e4f6b5e68128c981ed58c94259d479e`  
Actual PREP: not executed  
Actual OPS: not executed

## Scope

This bounded release changes only the four portability blockers recorded in
`docs/reviews/PREP_UNKNOWN_STATE_ENVIRONMENT_INDEPENDENCE_AUDIT.md`:

1. accepted-state ownership and provenance;
2. the DataRiver POC-owned PostgreSQL schema integrity boundary;
3. non-current DataHub Dataset exclusion before K9 authorization/projection; and
4. a bounded K9 cross-source consistency fence.

It does not add product features, widen authorization or classification, mutate target DataHub
metadata, reset state, regenerate retained secrets, change the exact-artifact/no-build release
contract, or move `origin/main`.

## Phase 1 — accepted-state ownership

Commit `5a6aa6f5fb21d598015f854d982c27f83c96f5b0` replaces marker-presence trust with the
`DATARIVER_PREP39083_TARGET_OWNERSHIP_V2` contract. The accepted fast path requires:

- an exact project/platform/port and canonical volume identity;
- a matching target-secret ownership fingerprint without exposing secret values;
- a valid durable `ACCEPTED` attempt receipt bound to the marker;
- marker/receipt/runtime identity agreement; and
- a proven compatible Product-to-current-Handoff ancestry relation.

Evidence/Handoff-only successors remain valid because compatibility is ancestry-based rather than
exact Product-SHA equality. Foreign markers or volumes, fingerprint mismatch, missing provenance,
partial persisted state, and incompatible/newer lineage fail closed as
`PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN`,
`PREP_ACCEPTED_STATE_FINGERPRINT_MISMATCH`, or
`PREP_ACCEPTED_STATE_LINEAGE_MISMATCH`. They are never converted to fresh state or reset.

Focused deploy/handoff tests covered current rerun, an Evidence/Handoff-only successor, foreign
marker, copied marker with foreign volume, stale marker with partial state, incompatible lineage,
legacy marker disposition, and duplicate-free accepted reconcile.

## Phase 2 — Product-owned PostgreSQL integrity

Commit `7d928e0` adds `DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V1`. The canonical fingerprint is limited
to `public` Product objects with the reserved `poc_` prefix:

- tables and required columns/types/defaults;
- PK/unique/FK/check constraints;
- indexes, including validity/readiness and uniqueness;
- Product triggers;
- Product functions; and
- Product enum/domain types.

Rows, unrelated schemas/tables/functions, extensions, and PostgreSQL catalog metadata are excluded.
The bounded catalog query returns at most 5,000 owned objects. PREP inspects before DDL and permits
only `FRESH`, exact current, or the one explicitly listed older migratable fingerprint. Missing
columns/constraints/indexes, type drift, malformed/partial state, receipt mismatch, and newer
unsupported revision fail before mutation. Exact current unversioned state receives only the
versioned receipt; existing arbitrary rows do not affect integrity.

The canonical PostgreSQL 17/pgvector fixture and one supported older fixture were exercised in
disposable Docker. Exact and unrelated-object cases passed; missing index, type drift, missing
constraint, malformed receipt, and newer revision failed closed. Disposable state was removed.

## Phase 3 — non-current Dataset exclusion

Commit `cf2b1307db3edc0eb30430e88c00342d9c38e246` introduces one currentness predicate before
identity enrichment, classification, authorization, lineage, or projection.

| Signal | Result |
|---|---|
| valid Dataset identity, current aspects, no negative signal | include |
| `entityExists=false` | exclude |
| entity `exists=false` | exclude |
| `status.removed=true` | exclude |
| malformed existence/removal signal | fail closed |
| contradictory `entityExists` / `exists` | exclude with typed contradiction |
| no properties and no schemaMetadata | exclude as aspect-less |
| status absent but existence/current aspects confirmed | include |

DataHub entity reads request existence checking, and inventory/lineage queries request `exists` and
`status.removed`. Lineage also retains `includeGhostEntities=false` and admits an edge only when
both endpoints are in the same current authorized inventory map, so removed nodes cannot leave a
dangling canonical edge. Provider page totals remain source-envelope totals; currentness reason
counts explain the post-filter current cardinality.

Tests use generic synthetic URNs and cover retained aspects on nonexistent/removed entities,
contradictory/malformed signals, historical aspects, current fallback, and dangling-edge removal.

## Phase 4 — K9 cross-source consistency

Commit `6422abe46e4f6b5e68128c981ed58c94259d479e` records that the pinned DataHub v1.6.0 APIs used by
the Product expose no reliable global metadata generation primitive. The Product therefore does
not invent one or claim globally atomic provider reads.

Each consistency attempt performs a complete current inventory/projection, metadata, lineage, and
runtime-identity collection and computes
`DATAHUB_KNOWLEDGE_SOURCE_FINGERPRINT_V1` from canonical source generation and deterministic
metadata/lineage content. Two consecutive complete fingerprints must match before semantic index
materialization and graph publication. At most three full observations and two comparisons are
performed:

- first drift followed by two equal observations publishes the stable successor;
- repeated drift fails as `K9_SOURCE_DRIFT_RETRY_EXHAUSTED`;
- collector pagination/GraphQL/contract failures retain their existing distinct classifications;
- drift never updates the semantic generation, graph staging/current pointer, or SUCCESS receipt;
- prior LKG and its promoted generation remain unchanged; and
- a later stable scheduled cycle converges without reset.

This is a bounded stable-observation/LKG contract, not a false global snapshot-isolation claim.
Generic tests cover stable large 1,001-node/1,951-edge input, inventory/metadata/lineage fingerprint
changes, first-attempt drift recovery, repeated drift, no publish, typed durable failure, LKG
preservation, and immediate PREP smoke classification.

## Local verification

Focused and integrated results on the Product source:

- Phase 4 K9/state/server/smoke: `144/144` PASS;
- PREP deploy/handoff: `130/130` PASS;
- Product server: `184/184` PASS;
- UI: `665/665` PASS;
- backend full suite: `4,060` PASS, `121` SKIP, `19` existing baseline FAIL;
- the same 19 failures reproduce at starting Handoff `af74fc4` (`127` PASS / `19` FAIL in the
  bounded baseline file set) and do not touch this correction;
- application build and POC build: PASS;
- TypeScript typecheck through both builds: PASS;
- ESLint: PASS;
- Ruff on `backend/src`, `backend/tests`, and `scripts`: PASS;
- strict mypy: PASS on 317 source files;
- static/source/migration checksum verification: PASS.

One disposable PREP Docker test completed its exact-image doctor scenario. The next state-machine
scenario was stopped after local Docker Compose remained at `up --wait` for three minutes with
zero CPU/IO and zero container/network/volume creation. This is recorded as a local Docker engine
gap, not a Product PASS. Residue for its UUID-scoped project was zero. The canonical TEST PC
accepted-state redeploy below is therefore mandatory.

## Exact Product artifact

The clean Product commit was built once for `linux/amd64` and exported without rebuilding:

- image: `datariver-poc:6422abe46e4f6b5e68128c981ed58c94259d479e`;
- OCI revision: exact Product SHA;
- child manifest: `sha256:5b4f4c7675d9d0245196c8c9d26809917229d9f705b287150f63ca6fa8211bdd`;
- config: `sha256:e75da9634cdc7f4356672f1cb0c42152e23c3568a193b56cbcdb400f27f9ae6c`;
- archive SHA-256: `3ca2a564e90d0d40e152262ad7e4922540d93511a693411b8f0463dd16deef5f`.

The archive remains ignored and outside Git. PREP/TEST deployment must verify the pinned archive,
manifest, config, platform, and revision, then use `docker load` and Compose `--no-build`; it has no
pull or rebuild fallback.

## TEST PC accepted-state revalidation

The preserved TEST PC began at accepted Handoff
`af74fc4d0cc99295a0ebfe897ccbaeb94cb5dfe6`. It is not Actual PREP. Its checkout was clean and was
fast-forwarded to provisional Handoff `7ec89277f254a1e56c676df347b1a34acdbfff33`. The exact Product
archive was transferred through the existing private transport and independently matched
`3ca2a564e90d0d40e152262ad7e4922540d93511a693411b8f0463dd16deef5f` before deployment.

The only deployment command was:

```bash
./scripts/prep39083 deploy
```

The first run classified the target as `EXISTING_ACCEPTED_RUNNING`, proved accepted marker,
ACCEPTED receipt, volume ownership, target fingerprint, and compatible ancestry, then verified and
loaded the pinned archive without rebuilding. The Product-owned PostgreSQL integrity check passed
before idempotent state reconciliation. Smoke completed in 559 seconds:

```text
1/6 Health                                      PASS
2/6 Administrator login                        PASS
3/6 DataHub current inventory + GlossaryTerm   PASS
4/6 Managed graphs + semantic index            PASS
5/6 MCL source + durable checkpoint             PASS
6/6 GENERAL provider + route                    PASS
Final receipt                                   ACCEPTED
```

The read-only GlossaryTerm smoke selected `urn:li:glossaryTerm:active_indicator` through
`RUNTIME_DISCOVERED`; `entityExists`, `glossaryTerm.exists`, and the basic metadata read were true.
Mutation was false. No Wafer or fixed DEV seed fallback was used.

A second unchanged-command rerun again classified `EXISTING_ACCEPTED_RUNNING`, passed all six smoke
stages, and reached `ACCEPTED` in 207 seconds. Bounded state counts before and after that rerun were
unchanged: three local credentials (one administrator and the two canonical services), two K9
policies, four historical/current K9 run receipts, one MCL source, one MCL checkpoint, and one
active login session. No duplicate identity was created.

The final accepted marker is `DATARIVER_PREP39083_ACCEPTED_V2` and binds Product `6422abe46e4f6b5e68128c981ed58c94259d479e`, provisional Evidence
`acb64c947bd34b324a767dce1e2ef1737b0e6899`, provisional Handoff
`7ec89277f254a1e56c676df347b1a34acdbfff33`, project `datariver-prep39083`, port 39083, and
`linux/amd64`. The loaded image carries the exact Product revision and manifest identity
`sha256:5b4f4c7675d9d0245196c8c9d26809917229d9f705b287150f63ca6fa8211bdd`; the release verifier also
proved the pinned config digest
`sha256:e75da9634cdc7f4356672f1cb0c42152e23c3568a193b56cbcdb400f27f9ae6c` before start.

Web was healthy as `1000:1000` with restart count zero. The three canonical state volumes remained
present, port 39080 was untouched, and the tailnet health endpoint returned HTTP 200. The deploy did
not reset state, regenerate retained secrets, rebuild or pull source, replace user DataHub metadata,
or mutate the discovered GlossaryTerm. Airflow, MinIO, and GX execution remained explicitly
DEFERRED in this TEST topology; the required DataHub, Chat, Embedding, Reranker, K9, MCL, and GX
read contracts were READY/PASS.

An independent Antigravity Gemini 3.1 Pro (High) read-only audit inspected the four Product commits
and returned `ACCEPT_PRODUCT_CANDIDATE`: no blocker, target-data hardcoding, fake provider token,
authorization widening, whole-database hash, unbounded retry, or runtime fail-open path was found.

## Boundaries retained

- Runtime target-business-data hardcoding count remains `0`; Wafer/Oracle MOCK/K10 values remain
  test, DEV seed, manual evaluation, or simulator-only and are not copied into the runtime image.
- Runtime node/edge fixed-count assumptions remain `0`.
- Airflow remains a provider of dynamically discovered metadata, not a hidden deploy prerequisite.
- Origin keeps loopback transport separate from the canonical public security Origin.
- GlossaryTerm smoke uses an exact configured URN or a runtime-discovered current Term and is
  read-only; there is no fixed Wafer fallback.
- Runtime Web stays non-root; elevated bootstrap remains disposable and bounded.
- Unknown ownership/schema/currentness/source drift never falls back to broader authorization,
  fresh/reset, stale-candidate promotion, or source rebuild.
