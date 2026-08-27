# PREP final pre-deploy hardening evidence

Recorded at `2026-08-27T07:38:41Z` for Product
`6021f591d2e47ade387b40d6174d896795126f12` on `dev`. The controlled PREP branch `main`
remained fixed at `2876508145cbed410ae343623a2e3bedcac823cf` throughout this work.

## Collect-all doctor and fail-closed deploy

`./scripts/prep39083 doctor` now executes one read-only, sanitized matrix containing exactly
`WEB_INTRANET`, `DATAHUB`, `QUALITY_READ`, `CHAT`, `EMBEDDING`, `RERANKER`, `MCL_DISCOVERY`,
`AIRFLOW`, and `MINIO`. Each stage is `READY`, `DEFERRED`, `FAILED`, or
`BLOCKED_BY_DEPENDENCY`; a failed stage exposes only its bounded classification and an optional
safe status class. The matrix contains no URLs, credentials, provider bodies, Kafka metadata
bodies, Registry schema bodies, checkpoint, receipt, or source identity payload.

Independent LLM, Kafka, Airflow, and MinIO checks continue after another failure. QUALITY_READ is
blocked only when DataHub CONFIG, AUTH, CONNECTIVITY, or TIMEOUT proves its transport unavailable;
an HTTP response proves transport and the Assertion read still runs. MCL always attempts the
Kafka-owned configuration/client/admin/connect/cluster/topic stages. Only a later DataHub
provider-version or Registry dependency may become `BLOCKED_BY_DEPENDENCY`. Airflow and MinIO are
independent, and an unconfigured optional provider is `DEFERRED`. QUALITY_READ is READY for a valid
zero-Assertion response. QUALITY_EXECUTION is READY only when the configured external Airflow
`datariver_quality_dispatch` DAG is readable; otherwise it is DEFERRED.

Doctor returns nonzero after printing the complete matrix if a required stage failed. It uses
`mutate_runtime=false` and does not write Product databases, Neo4j, MCL checkpoints, deployment
receipts, accepted markers, or runtime secrets. `./scripts/prep39083 deploy` deliberately retains
the existing fail-fast provider gate and performs no persistent Product mutation while a required
preflight is unacceptable.

## MCL bounded startup catch-up

Each Kafka consume invocation remains bounded by `POC_MCL_MAX_MESSAGES`. At startup the existing
single advisory-lock owner repeats those bounded capture calls and yields between batches until
the captured high watermark is reached. Catalog reconciliation runs once after the captured
batches, preserving capture-before-catalog ordering. The next daily boundary is not used as a
backlog throttle.

Fresh source identity starts from the earliest retained offset. Existing partition checkpoints
are never reset. Every capture commits its bounded checkpoint transaction independently. Graceful
stop completes the active bounded batch, starts no new batch after either the batch or inter-batch
yield, reconciles the captured subset, and does not advance the daily success receipt. A checkpoint
behind retention fails closed and never silently skips history.

The sanitized states are `CONTIGUOUS_CAPTURE_RECORDED`, `CAPTURE_CATCHING_UP`,
`CAPTURE_CAUGHT_UP`, and `HISTORY_GAP_BLOCKED`. Runtime discovery, capture, and retention failures
remain separately typed through Product status and authenticated deployment smoke.

Kafka bootstrap reachability is not treated as cluster readiness. If the bootstrap listener
returns an advertised broker hostname/address that PREP cannot reach, doctor reports the bounded
Kafka connectivity/cluster stage. DataRiver does not deploy another Kafka or rewrite DataHub's
advertised listener configuration.

## Historical accepted upgrade

One isolated Docker project reproduced the actual historical topology shape, not an invented
fresh install:

- accepted release A used K9 `DEFERRED`, loopback Web binding, preserved PostgreSQL/Neo4j/Redis
  volumes and generated secrets, a valid accepted marker/receipt, and no historical MCL checkpoint;
- descendant B required built-in K9, changed Web binding to `0.0.0.0`, enabled MCL and used the
  CIDR-aware intranet origin contract.

The same deploy path preserved every generated secret, every Compose volume identity, and a
pre-existing durable database row. It retained the accepted/attempt evidence, reconciled the two
canonical K9 policies and distinct K9/MCP service identities, did not reject the historical
DEFERRED-to-REQUIRED transition, and wrote the descendant attempt/accepted state only after the
normal gates. No `down -v`, volume deletion, database reset, secret regeneration, or duplicate
bootstrap occurred. The isolated historical accepted-upgrade test passed in `124.80s`.

The existing isolated retry tests also passed: forced authenticated-smoke failure followed by the
same deploy command (`113.59s`), and the fresh/residual/accepted state matrix (`202.98s`). These
tests used disposable Docker project identities only; no actual PREP state was accessed.

## Post-preflight typed gates

Known post-preflight boundaries no longer fall through a generic deployment failure:

| Gate | Bounded classification |
|---|---|
| TARGET_STATE | `PREP_TARGET_STATE_RECONCILIATION_FAILED` / `PREP_ATTEMPT_RECEIPT_WRITE_FAILED` |
| STATE_SERVICES | `PREP_STATE_SERVICES_FAILED` |
| SCHEMA | `PREP_SCHEMA_INITIALIZATION_FAILED` |
| BOOTSTRAP | `PREP_BOOTSTRAP_RECONCILIATION_FAILED` |
| WEB_START | `PREP_WEB_START_FAILED` |
| AUTHENTICATED_SMOKE receipt | `PREP_ACCEPTANCE_RECEIPT_WRITE_FAILED` |

Existing precise `PrepError` classifications retain precedence. K9 smoke separately reports
DataHub source, policy/pin drift, Neo4j projection, promotion, semantic-index readiness, and
readiness timeout. MCL smoke separately reports runtime discovery, bounded capture, and retention
gap failures even after read-only preflight succeeded.

## Verification

- PREP deploy/handoff unit contract: `85/85 PASS`.
- Provider/MCL/K9/state focused Node tests: `85/85 PASS` after the final dependency-rule case.
- PREP authenticated smoke: `25/25 PASS`.
- Node Product server: `166/166 PASS`.
- UI: `90 files / 663 tests PASS`.
- Historical accepted-state Docker upgrade: `1/1 PASS`.
- Forced smoke failure to same-command resume Docker regression: `1/1 PASS`.
- Isolated Docker state/recovery matrix: `1/1 PASS`.
- ESLint, TypeScript, production build, POC build, repository-wide Ruff lint, changed-file Ruff
  format, strict mypy over `577` files, static verification, Python compile, shell syntax,
  Compose/handoff contract, diff-check, and delta secret scan: `PASS`.
- Repository-wide Python aggregate: `3955 passed / 119 skipped / 55 known baseline failures`.
  The failures remain in unchanged strict migration-schema test doubles, DEV-host fixtures and
  legacy expectations outside this change. Repository-wide Ruff format likewise retains three
  unchanged baseline files; every changed Python file is formatted and the entire Ruff lint gate
  passes. No global all-green claim is made.
- Router/retrieval/reranking semantics changed: `NO`; Router 60 plus Boundary 8 was not rerun.

The exact image is `linux/amd64`, carries OCI revision
`6021f591d2e47ade387b40d6174d896795126f12`, and has image ID
`sha256:a333002f0fb49852b2d5bfd50ceea062f41dd9c3644768ab486ca12b6af62079`.
Changed runtime adapters parse under pinned Node 22.19. Final image configuration/history contains
no provider credential or credential-bearing proxy value.

The only Product deployment command remains:

```bash
./scripts/prep39083 deploy
```

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
