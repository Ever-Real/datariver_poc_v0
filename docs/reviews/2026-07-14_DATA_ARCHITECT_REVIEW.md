# Independent data-architecture review — 2026-07-14

> Post-review status, 2026-07-15: the original independent findings are retained, while later implementation and live evidence supersede count/runtime-open statements below. See [the acceptance report](../12_ACCEPTANCE_REPORT.md).

Reviewer role: delegated Data Architect sub-agent. Scope: bounded contexts, canonical ownership, table model, ABAC leakage, governance lifecycle, knowledge releases and migration safety.

## Findings and disposition

| Severity | Finding | Disposition/evidence |
|---|---|---|
| High | DataHub and local database ownership could diverge if acknowledgement were treated as completion | Resolved: DataHub owns applied aspect; worker re-reads and compares canonical aggregate hashes before `APPLIED` |
| High | Search/detail/Chat could leak resources if DataHub were queried before local authorization | Resolved: local workspace/classification/system/domain projection prefilters; detail and each Chat citation receive a decision |
| High | Requester/self approval and high-classification approval count were under-specified in early code | Resolved: final self-approval denied; confidential/restricted application requires two distinct final approvers |
| Medium | Change item lacked a typed aspect name and deterministic order | Resolved: explicit `aspect_name`, `ordinal UQ`, canonical server-generated `after_hash` |
| Medium | Knowledge projection engine risked becoming canonical | Resolved by ADR: immutable PostgreSQL release is canonical; exports/analysis are release-pinned and bounded |
| Medium | Seed assertions needed deterministic IDs, ontology validation and assertion-level provenance | Resolved: 257-node/279-edge count/hash gates and required provenance; removal fixed to namespace/run |
| Medium | Planned schema and implemented schema were mixed in one table specification | Resolved: data specification now separates authoritative implemented DDL and backlog tables |
| Resolved after review | Full changeset/ontology-edit workflow was modeled but not exposed | Graph/ontology creation, changeset operations, submit/review/publish, release activation/export and bounded analysis are now exposed; automated source-specific extractor adapters remain optional extensions |
| Resolved after review | Cross-workspace PostgreSQL runtime matrix needed a live database | Application-role live result was 0 rows without context, 12 in the permitted seed workspace and 0 in another workspace; direct catalog delete was denied |

## Conclusion

The modular-monolith boundary is suitable for the current scale and is safer than immediate MSA decomposition. Extraction should occur only at existing ports (DataHub, catalog projection, jobs, object store, knowledge projection, Chat provider). Live RLS and migration gates subsequently passed; production acceptance still requires target backup/restore, deployed DataHub contract, enterprise identity, load and signed release evidence.
