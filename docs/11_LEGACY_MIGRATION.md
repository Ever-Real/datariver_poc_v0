# Legacy migration and retirement plan

## Reference policy

The current implementation is preserved at `../../datariver_v0_3/legacy/datariver_v0_3_reference_20260714/` as read-only reference. It is not a source package dependency and is excluded from new images, tests and runtime configuration. The original working tree remains untouched apart from the separate new-project and snapshot paths.

## Migration strategy

Use a strangler boundary at `/api/v1` with explicit compatibility adapters only where an existing consumer must remain. New domain models and DTOs are not shaped around legacy database tables. Each legacy capability is retired after contract comparison, data reconciliation and consumer sign-off.

Recommended sequence:

1. Inventory active consumers, endpoints, DataHub aspects, DB rows, files and jobs.
2. Freeze schema/config changes for the migration window and export checksummed snapshots.
3. Migrate identity references and workspace/resource attributes; do not migrate passwords or tokens.
4. Rebuild catalog projection from external DataHub rather than copying ambiguous local cache rows.
5. Migrate open change requests through explicit state mapping and manual reconciliation.
6. Verify object size/type/checksum before creating object manifests.
7. Rebuild embeddings with known model/dimension/provenance.
8. Import knowledge content as unverified proposals, then validate and publish a first immutable release.
9. Run shadow reads and compare authorized results, then route consumers by capability.
10. Revoke legacy credentials, archive runtime data under retention policy, and remove compatibility code.

## Data disposition

| Legacy data | Treatment |
|---|---|
| DataHub URNs | map to internal UUID/external identifier; inspect >255-char truncation |
| users/roles | map external subject; replace duplicated role models with ABAC attributes |
| CR states | map only after legal-transition/evidence validation; no automatic completion |
| attachments | checksum/MIME/ownership validation before manifest import |
| chat/evidence | label `legacy_unverified`; do not claim policy/source lineage |
| vectors | discard/rebuild unless model revision and dimension are proven |
| graph versions | import as proposal/snapshot; diff summaries alone are not recoverable versions |
| configuration secrets | rotate and provide through new secret references; never copy values |
| audit rows | immutable archive with provenance; fix URN uniqueness model on import |

## Compatibility prohibitions

- No legacy endpoint may return DataHub credentials.
- No direct DataHub or graph write is preserved for compatibility.
- No wildcard credentialed CORS, weak/default secret or zero-key crypto fallback.
- No raw LLM-generated Cypher execution.
- No in-process dictionary is treated as shared cache or workflow state.
- No MySQL schema is imported into the PostgreSQL canonical model.

## Retirement gates

A legacy capability is retired only after the replacement passes functional/negative authorization tests, data count/hash reconciliation, performance target, rollback rehearsal, operations runbook and consumer communication. Rollback restores routing, not divergent writes; write-capability cutovers require a single active writer.
