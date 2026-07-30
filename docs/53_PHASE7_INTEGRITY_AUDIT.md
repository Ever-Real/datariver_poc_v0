# Phase 7 source, migration and secret-integrity audit

## Decision

Phase 7 is a bounded one-pass audit and remediation package over the published Quality Phase 6
baseline `7f58d6cf586cebb74a93aea7870802d6453aa832`. It does not reopen the accepted Quality
architecture and does not claim production readiness.

The Data architect, application/data QA and security reviewers each performed one read-only pass.
The primary agent reproduced the relevant findings, applied the changes below and ran only the
repository static gates and focused regression tests. No recursive final-review loop was opened.

## Closed findings

| Area | Finding | Resolution |
|---|---|---|
| Retention governance | The HTTP/UI contract stopped at `POLICY_BOOK_V3`/seven classes and the browser proposed fixed V2 business values. This could not create the explicit V4 policy required by Profile collection. | The request schema accepts V4/eight exact classes. The UI exposes V2/V3/V4 vocabulary, starts every class duration/unit/disposition empty, includes `QUALITY_PROFILE`, and sends the selected `contract_version`. No retention duration is invented. |
| Legal Hold | The browser omitted the typed Quality/Profile resource namespace. | TypeScript and the Admin API now carry `resource_type`; the form exposes all eight data classes and only the server-approved resource-type combinations. |
| Governance evidence | A formal change decision started with a pre-attested reason. | Mutation reasons start empty and the confirmation remains disabled until the actor enters evidence. A user-entered reason is preserved only for an explicit retry after a version conflict. |
| Policy presentation | The workflow view fabricated completed author/review/approval steps and labelled a browser clock as server evidence. | The page shows only the current server state, explicitly says full lifecycle history is unavailable, and labels the local timestamp as the screen refresh time. |
| Dashboard | The home card claimed that no Quality read model existed after `/quality/overview` shipped. | The card is now a neutral navigation summary and makes no unsupported availability assertion. |
| Dispatch capacity | Source defaults `25/100` could schedule work without a deployment-owned capacity decision. | Both settings default to absent, must be supplied together, and the internal dispatch route returns `503` while they are absent. `.env.example` contains placeholders only. |
| Airflow secret scope | The Quality dispatcher secret was mounted into every Airflow component. | Under `LocalExecutor`, only `airflow-scheduler`, which owns task subprocesses, receives the Quality dispatch environment and secret. |
| Compose regression | The Quality worker had no exact static secret-set assertion. | Static verification now fixes its allowed set to the dedicated PostgreSQL and delivery credentials. |
| Source integrity | Mock/fake runtime declarations, debug residue, administrator-name bypasses and common credential fingerprints had no permanent source gate. | `verify_static.py` scans production backend/frontend/Airflow sources and `.env.example`, while excluding test files and documented development-only fixtures. |

## Migration and live PostgreSQL evidence

Static comparison against the pre-Quality baseline found no altered existing SQLAlchemy model in
Integration or Connections. Catalog changes are additive Profile models. Revisions `0067` and
`0068` use evidence-preserving `RESTRICT` relationships for Quality/Profile rows; `0069` installs
the execution functions/role boundary; `0070` adds only Quality read indexes. Existing downgrade
dependency order remains child-before-parent.

The running PostgreSQL 17 instance returned:

- Alembic revision: `0070`
- unvalidated relevant Catalog/Integration/Connections/Quality foreign keys: `0`
- Quality foreign keys to Integration or `platform.external_service_profile*`: `0`
- CASCADE relationships in the inspected Catalog/Quality-to-Catalog/Retention/Platform boundary:
  exactly the pre-existing
  `catalog.projection_watermarks.fk_projection_watermarks_workspace_id_workspaces`

No `0067`–`0069` upgrade performs destructive DDL against the protected legacy
`catalog.assets_projection`, non-outbox Integration, or Connections relations.

## Plaintext and residue audit

Tracked production sources, Compose files, `.env.example`, Dockerfiles and Airflow DAGs contain no
detected private key, AWS access key, GitHub token or OpenAI-style token literal. Runtime
`TODO`/`FIXME`/`HACK`/`XXX`, `console.log/debug/trace`, `debugger` and Python `breakpoint` findings
are zero. The direct development administrator password assurance exception is action-bounded,
authentication-denial-only, freshness checked, audited and rejected by configuration outside the
documented development posture; it is not a display-name bypass.

Local `.env*`, `secrets/` and `runtime/` remain ignored and host-owned. Quality source secrets are
read from a read-only dedicated directory below a `0700` host parent. File mounts remain readable
across the development/preparation host UID boundary as documented by bootstrap; changing that
cross-platform ownership model is deferred to the Phase 8 worker runtime gate, not represented as
a plaintext-secret defect.

## Removed obsolete test state

After exact-name and ownership inspection, these non-Compose, no-restart PostgreSQL test
containers and their anonymous test volumes were physically removed:

- `datariver-profile-phase2-pg17`
- `datariver-quality-phase1-pg17`
- `datariver-0046-audit-pg`
- `datariver-policy-expression-pg`

The active `datariver-next`, local connectors, DataHub and unrelated workspace/project containers
were not targeted. The removed anonymous test data is not recoverable, but every container is
reproducible from its test setup.

## Verification

- Ruff format: `483 files already formatted`
- Ruff lint: passed
- strict mypy: `474 source files`, no issues
- backend focused config/retention tests: `79 passed`
- frontend TypeScript and zero-warning ESLint: passed
- frontend focused Admin/Dashboard/Governance/Policy tests: `5 files / 37 tests`, passed
- static architecture/Compose/source/document verification: passed
- `git diff --check`: passed

Target WSL, representative load/soak, real human identity and Phase 8 source execution remain
separate gates.
