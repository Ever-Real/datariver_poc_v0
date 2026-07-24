# Optional deep semiconductor value-chain seed

## Safety contract

The pack is deterministic synthetic reference data for discovery, graph analysis, Chat evidence and UI evaluation. It is disabled by default, rejected in production mode and uses a fixed namespace/run ID so verification and removal cannot select unrelated resources.

```bash
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  run --rm semiconductor-seed
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed verify
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed remove --confirm-synthetic-data
```

Direct CLI use also requires `SEED_PROFILE=semiconductor`; apply/remove require `--confirm-synthetic-data`. Re-applying an already applied content hash is idempotent. If a graph exists without the matching seed-run ownership record, the installer refuses overwrite.

## Delivered logical model

The current `1.0.0` pack produces:

| Resource | Count |
|---|---:|
| catalog assets | 12 |
| graph nodes | 257 |
| graph edges | 279 |
| monthly facility observations | 72 |
| monthly product-demand observations | 96 |

Nine value-chain stages connect 18 companies, six facilities, ten materials, eight equipment/tool families, twelve process/technology entities, eight products, six risk entities and twelve catalog datasets. Twelve deterministic 2026 periods add facility capacity/utilization/yield/good-unit facts and product demand/price-index facts. `OBSERVES` relationships keep every quantitative assertion attached to its subject.

Every node/edge contains non-empty source reference/locator/version, generation method and confidence. Synthetic claims are explicitly marked and no value is represented as externally verified market truth.

## Analysis intent

The topology supports bounded questions such as:

- upstream supplier/material/equipment dependencies for a process or product;
- single-source and geographic concentration paths;
- facility/process ownership and manufacturing relationships;
- risk propagation to downstream products/datasets;
- substitution candidates restricted to modeled relationship types;
- catalog-to-knowledge evidence citations.
- monthly capacity, utilization, yield-adjusted output, demand trend and supply-gap inputs;
- maximum equipment lead time and qualified-source-count screening.

The released bounded-neighbor API and API-product invocation can execute these paths with typed parameters. Machine-readable analytical fixtures assert 12 periods, 72 capacity observations, 96 demand observations, 168 observation edges, three single-source materials and a 435-day maximum equipment lead time. HHI and multi-scenario shock solvers remain roadmap items.

## Artifacts

```text
seed/semiconductor/
  manifest.yaml             namespace, versions, license, counts and provenance
  ontology.json             allowed entity/edge types
  data/catalog_assets.csv   deterministic local catalog projection
  queries/golden_queries.json
                            intended analysis questions/contracts
  expected/counts.json      machine-readable count gate
  expected/analytical_fixtures.json
                            deterministic quantitative assertions
```

The Python builder in `datariver.seed.semiconductor` generates the graph deterministically and tests validate counts, endpoints, ontology membership, classification and provenance. The installer creates the optional workspace/local membership, catalog projection and immutable graph release in one controlled database transaction, plus an outbox audit event. It does not call external DataHub or claim that synthetic assets exist there.

## Verification and removal

`verify` checks the namespace/run state, content hash and exact catalog/node/edge counts. `remove` deletes only fixed seed-owned catalog assets, graph/release/ontology records and marks the seed run removed while retaining its audit/outbox evidence. The core deployment is accepted only when `SEED_PROFILE=none`; demo acceptance separately records the seed content hash.
