# PREP39083 unified fresh/update deployment evidence

This evidence advances the accepted PREP39083 one-command handoff Product
`fab42bd03eb8cbe9b3bcbff6c4cfdb2cf5e5fc6c`, Evidence
`5761754d3a09b714b31f5430744e8b9da6b15136`, and handoff
`9644c0274c321f6b224ca487f2c2d5529c51f947` to Product
`99acf0d2a8be977323ead2f8647ef5b2ad77add7`.

The work is a deployment-orchestration correction. Product application, Router, Knowledge Graph,
MCP, and authorization semantics are unchanged. No PREP or OPS host was accessed or mutated.

## One command and target states

The canonical command remains:

```bash
./scripts/prep39083 deploy
```

The deployer now classifies persistent target state before selecting or generating local secrets.
The bounded states are:

- `FRESH_CLEAN`
- `EXISTING_ACCEPTED_RUNNING`
- `EXISTING_ACCEPTED_STOPPED`
- `FAILED_FIRST_INSTALL_RECOVERABLE`
- `EXISTING_STATE_AMBIGUOUS`

The classifier independently observes the Compose containers, network, named volumes,
`.env.prep.runtime`, and the accepted receipt. It does not infer database freshness from a missing
or stopped PostgreSQL container.

Existing valid runtime secrets have first priority. Legacy generated values in `.env.prep` are
second. A residual first install is inspected before any new database credential is selected. New
secrets are generated only for a proven clean host or a proven empty recoverable residual.

## Non-destructive failed-install recovery

An unaccepted residual is recoverable only after read-only inspection proves that all PostgreSQL
public tables contain no row and Neo4j contains no node. The PostgreSQL role password is then
reconciled through the container-local trusted administrator path; the final password is passed on
stdin and is not present in argv or logs. The existing volumes are retained.

An accepted marker, any durable PostgreSQL row, any Neo4j node, or an inconclusive inspection fails
closed as `PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY`. The deployer never invokes `down -v`,
removes a named volume, resets accepted data, or fabricates Product state.

## K9 feature-dependent contract

`POC_K9_STUDIO_DATABASE_URL` is `FEATURE_REQUIRED_WHEN_K9_ENABLED`, not a core boot requirement.

- Non-empty approved Studio URL: the deployer derives K9 enabled, provisions/verifies the distinct
  K9 service identity, and requires DAILY managed refresh plus READY managed graphs and semantic
  index in smoke.
- Blank URL: core Product boot, login, DataHub, Chat and provider checks continue; K9 scheduler is
  disabled and smoke/summary report `K9 Managed Refresh: DEFERRED — Studio DB not configured`.

No Studio URL, database, graph, or identity is fabricated. The MCP and K9 Subjects remain distinct,
and K9 identity provisioning does not block core boot while K9 is deferred.

## Isolated Docker state-machine verification

A unique disposable Compose project exercised the real PostgreSQL and Neo4j images and proved:

- zero containers/networks/volumes/runtime env/accepted marker classified `FRESH_CLEAN`;
- fresh generated PostgreSQL identity was shared exactly by pgvector and web configuration;
- same-release rerun was idempotent;
- accepted running update classified and reused persistent state;
- accepted stopped update classified and reused persistent state;
- an initialized but empty residual with an old PostgreSQL credential was recovered without volume
  deletion and completed with the generated runtime credential;
- a residual containing a durable PostgreSQL row was rejected as ambiguous;
- no duplicate administrator, K9/MCP Subject, Workspace, or scheduler state was introduced.

The final isolated run passed in 197.46 seconds. Its exact test containers, network, volumes,
effective environment, and temporary credential files were removed after observation. No accepted
DEV or target volume was deleted.

## Source and runtime gates

- Deployment/handoff focused tests: 31/31 PASS.
- Bootstrap and smoke Node tests: 6/6 PASS.
- Actual isolated Docker state-machine integration: PASS.
- POC server: 122/122 PASS.
- UI: 90 files / 658 tests PASS.
- ESLint, TypeScript, POC build, static verification, Ruff, strict mypy, shell/Node syntax, Python
  compile, Compose validation, and diff-check: PASS.
- Secret scan: PASS; no private key, credential-bearing URL, target secret, or proxy credential was
  added to source, image configuration/history, logs, or Evidence.
- Final DEV image: `linux/amd64`, OCI revision exactly
  `99acf0d2a8be977323ead2f8647ef5b2ad77add7`.
- DEV 39083: healthy, restart count 0, HTTP 200; unauthenticated protected API HTTP 401.
- DEV 39090: HTTP 200.

An initial DEV build inherited the source host's arm64 platform setting and was rejected before
acceptance. The same Product was rebuilt explicitly as `linux/amd64`, reconciled to 39083, and then
accepted. Recreating the DEV web container also removed a pre-existing manual Studio-network
attachment; that existing attachment was restored without changing or deleting persistent state.
These were DEV reconciliation corrections, not PREP execution.

Actual PREP deployment and runtime verification: **NOT EXECUTED**.
Actual OPS deployment and runtime verification: **NOT EXECUTED**.

Result at this Evidence checkpoint: `DEV_RUNTIME_VERIFIED_HANDOFF_PENDING`.
