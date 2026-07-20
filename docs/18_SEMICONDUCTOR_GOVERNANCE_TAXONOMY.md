# Semiconductor DataHub term, tag, and enrichment workflow

## Purpose and ownership

This is the controlled semantic-metadata workflow for the deterministic external
`semiconductor_seed` value-chain data. DataHub remains the canonical owner of
the applied glossary, tag, dataset, and schema metadata. The generator owns
only the synthetic seed namespace and never reads or writes DataRiver business
tables, browser credentials, or provider credentials in a client.

The vocabulary is intentionally separate from classification. It applies no
`CLASSIFICATION:*` tag and therefore does not change DataRiver ABAC visibility.
The existing classification governance process remains the only authority for
classification labels.

## Controlled term structure

The workflow creates nine glossary nodes, 33 terms, and 52 tags. Vocabulary
identifiers are stable ASCII DataHub URN fragments; the visible names and
definitions are supplied in the seed script.

```text
Semiconductor data
├─ Business foundation
│  ├─ Legal entity
│  ├─ Facility
│  ├─ Technology node
│  └─ Product master
├─ Supply and procurement
│  ├─ Supplier master / supplier qualification
│  ├─ Procurement contract / purchase order
│  └─ Material specification
├─ Logistics and inventory
│  ├─ Logistics shipment
│  └─ Inventory lot
├─ Manufacturing operations
│  ├─ Equipment asset
│  ├─ Manufacturing route / operation
│  └─ Manufacturing lot
├─ Quality and yield
│  ├─ Quality measurement
│  └─ Yield summary
├─ Finance and capital
│  ├─ Cost ledger
│  └─ Capital project
├─ Research and market intelligence
│  └─ Research and market signal
└─ Cross-cutting record semantics
   ├─ Record identifier, business key, record name, lifecycle status
   ├─ Semiconductor scenario, operational region, active indicator
   ├─ Annual volume, unit cost, effective date
   └─ Created timestamp, updated timestamp, referenced record
```

Every dataset receives its value-chain family term and the Semiconductor
scenario term. Every real PostgreSQL table field receives one cross-cutting
term, or its referenced family term for foreign keys. Oracle entities remain
explicitly `MOCK`; views and Oracle mock datasets receive dataset semantics but
do not receive a new schema aspect, preserving the existing bounded GMS schema
indexing contract.

## Tag structure

Tags are additive, controlled labels with the following dimensions:

| Dimension | Examples | Applied to |
|---|---|---|
| Domain and provenance | `Semiconductor`, `DataRiver seed`, `Synthetic` | every generated dataset |
| Value-chain stage | `Value chain · Supply and procurement`, `… Manufacturing operations` | every generated dataset |
| Physical and execution truth | `Dataset · table/view`, `Execution · applied/mock`, `Platform · PostgreSQL/Oracle` | every generated dataset |
| Scenario | `Scenario · logic 3nm`, `… global logistics` | every generated dataset |
| Field semantic | identifier, business key, lifecycle, geography, volume/cost measure, effective date, audit timestamp, relationship reference | PostgreSQL table fields |

`Synthetic` and `Execution · mock` are disclosure labels, not quality or
approval signals. A tag write never creates a new DataHub business entity
outside this vocabulary.

## Initialization and restartable execution

Run these commands from the repository root only after the local host
dependencies and the externally operated DataHub are healthy. Secrets are read
only from ignored files.

```powershell
# Optional: provision and prove the glossary/tag vocabulary before data ingestion.
.\.venv\Scripts\python.exe .\scripts\generate_semiconductor_seed.py --seed-governance

# Standard initialization: creates the dedicated physical seed, provisions the
# vocabulary, enriches datasets/real table fields, emits lineage, and verifies read-back.
.\.venv\Scripts\python.exe .\scripts\generate_semiconductor_seed.py `
  --apply --confirm-reset --ingest-datahub --entity-scope dual

# Repeatable read-only verification of vocabulary and the selected dataset range.
.\.venv\Scripts\python.exe .\scripts\generate_semiconductor_seed.py `
  --verify-datahub --entity-scope dual
```

The full ingest runs in this fixed order:

1. Verify DataHub reachability, then UPSERT glossary nodes root-first, terms, and tags.
2. For each selected deterministic dataset, write dataset properties, additive
   term/tag aspects, the existing bounded schema aspect for real PostgreSQL
   tables, and typed lineage.
3. Read back every vocabulary aspect, each selected dataset's term/tag aspects,
   and every enriched PostgreSQL table field. The run fails if an expected
   entity, reference, field, parent node, or display name is absent.
4. Write the intended and verified counts only to the ignored
   `runtime/semiconductor-seed/manifest.json` evidence file. Each bounded
   ingest and verification batch also checkpoints its completed count and
   current phase so an interrupted run has unambiguous evidence of partial
   progress and can be safely rerun.

The script uses deterministic idempotency keys. `--datahub-start-index` and
`--max-datahub-entities` retain bounded diagnostic/resume behavior; vocabulary
is still seeded before an ingest. A failed run is safe to rerun. It must not be
used to label a shared production dataset, because this workflow owns only the
synthetic `semiconductor_seed` namespace.

## Acceptance criteria

- DataHub has the complete glossary-node parent tree, terms, and tag names.
- All selected datasets have their family/scenario terms and every required
  provenance, stage, scenario, object, execution, and platform tag.
- Every real PostgreSQL table field has its expected term and field-semantic
  tag; unknown generated fields fail closed until the taxonomy is updated.
- The manifest records matching requested/verified counts. A successful HTTP
  proposal without typed aspect read-back is not an accepted result.
