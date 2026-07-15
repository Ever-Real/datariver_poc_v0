# Independent data-engineering/SRE review — 2026-07-14

> Post-review status, 2026-07-15: the original independent findings are retained, while later Docker and supply-chain evidence supersedes the runtime-open statements below. See [the acceptance report](../12_ACCEPTANCE_REPORT.md).

Reviewer role: delegated Data Engineer sub-agent. Scope: OSS/runtime choices, memory safety, delivery, object ingestion, scheduling, portability, failure recovery and verification.

## Findings and disposition

| Severity | Finding | Disposition/evidence |
|---|---|---|
| High | A single Valkey for cache and jobs would couple eviction to correctness | Resolved: separate endpoints/instances; volatile bounded cache versus AOF/no-eviction delivery; PostgreSQL outbox canonical |
| High | Multipart completion could duplicate/fail after an external success and DB crash | Resolved: leased completion worker treats `NoSuchUpload` class responses as reconciliation and verifies object `HEAD` |
| High | Uploads stopped at quarantine and lacked bounded-memory content validation | Resolved: independent validation worker streams chunks, verifies full SHA/size, applies format rules and copy-before-commit promotion |
| High | Approved changes had no durable application worker or attempt history | Resolved: leased jobs/attempts, backoff, terminal failure, system decision audit and DataHub re-read reconciliation |
| Medium | Core search depended on demo seed because no DataHub projection sync existed | Resolved: typed page sync API plus paused six-hour Airflow DAG using scoped service identity |
| Medium | Local Keycloak user had no application membership without semiconductor seed | Resolved: production-guarded local identity bootstrap independent of seed; first login requires password/TOTP |
| Medium | Browser MIME variation rejected valid Parquet/YAML uploads | Resolved: extension-derived canonical server contract and frontend tests |
| Medium | Git portability lacked repeatable CI | Resolved: frozen Python/frontend jobs, migration freshness, DAG compile and Compose static profiles in GitHub Actions |
| Resolved after review | Docker was unavailable during the delegated review | Combined Core/Keycloak/Airflow/APISIX stack, migration, seed, OIDC, RLS, cache outage and API/relay replacement were subsequently verified live |
| Partially resolved after review | Metrics/traces/SBOM/image scanning were only specified | ABAC-protected Prometheus metrics, pip/npm audit, Trivy source/IaC and CI image scans/CycloneDX gates are shipped; target trace backend, retained release artifacts and all-overlay image scans remain deployment gates |

## Conclusion

The chosen free/open components and process separation are reasonable for a portable baseline. Memory correctness is improved by bounded uploads, small worker concurrency, DB leases and non-canonical cache. The local live Compose and selected recovery/security gates subsequently passed; target DataHub/object conformance, backup/restore, load/soak, enterprise auth and signed supply-chain evidence still block production acceptance.
