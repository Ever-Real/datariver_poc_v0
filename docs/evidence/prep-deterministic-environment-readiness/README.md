# PREP deterministic environment and deployment readiness evidence

Recorded at `2026-08-27T09:10:02Z` for Product
`6a56c4013d21a39bd81ca199c3a6835d9b7dffc7` on `dev`. The PREP promotion branch
`origin/main` remained fixed at `aaeb0a7cc811da50ae4a7d364436699574f73b46` throughout this work.

## Proven root cause

The ambient-shell precedence hypothesis is **proven**. Before the correction,
`child_environment()` copied all of `os.environ`; Docker Compose gives that process environment
precedence over `--env-file`. A deliberately polluted parent therefore replaced the canonical
values for `POC_IMAGE_TAG`, `POC_SOURCE_COMMIT`, `PREP_RELEASE_PRODUCT_SHA`, `POC_BIND_HOST`,
`POC_STATE_BIND_HOST`, `POC_PORT`, `POC_PLATFORM`, `DATAHUB_GMS_URL`, `DATAHUB_GMS_TOKEN`,
`LLM_CHAT_URL`, `LLM_EMBEDDING_URL`, `LLM_RERANKER_URL`, `POC_MCL_KAFKA_BROKERS`,
`COMPOSE_PROJECT_NAME`, `COMPOSE_FILE`, `COMPOSE_ENV_FILES`, and `DOCKER_DEFAULT_PLATFORM`.
This directly explains why Compose did not resolve `datariver-poc:<current Product SHA>` even though
environment reconciliation had rendered the correct tracked value.

The boundary now inherits only reviewed host execution keys: path, bounded user/temp/locale data,
and Docker engine/context/TLS configuration. Product configuration comes exclusively from the
tracked environment contract, `.env.prep`, optional `.env.prep.optional`, preserved
`.env.prep.runtime`, and `release.json`. The complete canonical effective map is passed to child
Product/Compose processes; arbitrary ambient Product, provider, database, `COMPOSE_*`, and
`DOCKER_DEFAULT_PLATFORM` values are discarded.

Every Compose invocation uses an exact project, file, and mode-0600 env file. Before image build,
doctor and deploy verify the resolved project, exact Product image, linux/amd64 platform, Product
revision build argument, build proxy arguments, Web/state port bindings, and every canonical
provider setting projected into the Web service. Sensitive values are compared in memory and are
never printed.

## Polluted-shell and state-machine proof

Four isolated final-source Docker scenarios passed together in `531.36s`:

1. an absent exact image under a polluted shell built the exact doctor image, ran the collect-all
   matrix, and left zero Product containers, volumes, receipts, runtime secrets, or state;
2. a polluted fresh deploy rejected a deliberate provider failure before mutation, then recorded a
   deliberate smoke failure and reached `ACCEPTED` through the same deploy command without duplicate
   administrator, K9, or MCP identities;
3. a historical accepted installation with preserved PostgreSQL/Neo4j/Redis volumes, generated
   secrets, durable data, K9 `DEFERRED`, loopback Web publish, and no MCL checkpoint upgraded to the
   descendant wildcard-Web, K9 `REQUIRED`, MCL-enabled contract and reached `ACCEPTED`;
4. failed-first-install recovery and the fresh/running/stopped/same-release state machine remained
   idempotent, while unknown durable state failed closed without deletion or reset.

The polluted parent contained stale Product SHA, source SHA, release SHA, ARM64 platform, wrong
port/bind hosts, wrong DataHub/LLM/MCL providers, wrong Compose project/file/env files, and wrong
Docker default platform. Doctor and deploy resolved only the target-owned values: the exact Product,
project `datariver-prep39083`, linux/amd64, Web `0.0.0.0:39083`, and loopback-only state services.
No deploy code contains `down -v`, volume deletion, database reset, receipt deletion, or generated
secret regeneration for accepted state.

## Bounded external diagnostics and post-preflight gates

Kafka discovery now has explicit connection, request, and retry budgets. Bootstrap TCP success is
not treated as readiness: failure while resolving cluster metadata, including an advertised broker
that PREP cannot reach, is classified at the Kafka cluster/metadata boundary. Cluster contract,
topic connectivity/not-found/ambiguity, provider version, Registry configuration/connectivity,
subject, and schema contract remain distinct. DataRiver neither deploys another Kafka nor rewrites
DataHub listener configuration. Existing bounded MCL batches, single-owner lock, inter-batch yield,
earliest-retained fresh start, durable checkpoint, catch-up, and retention-gap fail-closed behavior
remain unchanged.

Known post-preflight failure domains retain a typed stage: `TARGET_STATE`, `STATE_SERVICES`,
`SCHEMA`, `BOOTSTRAP`, `K9_INITIAL_REFRESH`, `WEB_START`, `MCL_INITIAL_CAPTURE`,
`AUTHENTICATED_SMOKE`, and `ACCEPTED_RECEIPT`. K9 source/policy/Neo4j/promotion/semantic failures and
MCL source/discovery/capture/history-gap failures retain their bounded classifications instead of
falling through `PREP_SMOKE_UNKNOWN_FAILED`.

## Operator-facing readiness matrix

| Stage | Tested | Expected actual PREP behavior | Remaining external dependency |
|---|---|---|---|
| Image identity | Exact absent/present image, tag, revision and amd64 Docker gates PASS | Build/reuse only `datariver-poc:<Product SHA>` | Docker daemon, AMD64 builder and dependency-download capacity |
| Environment isolation | Polluted-shell unit and Docker doctor/deploy PASS | Ignore ambient Product/Compose/provider variables | Correct target-owned `.env.prep` values |
| Web intranet | Compose wildcard Web and loopback state bindings PASS | Publish only Web on `0.0.0.0:39083` | Target Windows/WSL route and firewall policy |
| DataHub | Typed query/auth/GraphQL/provider-version contracts PASS | READY or precise sanitized failure | Reachable configured GMS and valid credential/provider contract |
| Quality Read | Zero-Assertion and populated read contracts PASS | READY even with zero assertions | DataHub Assertion API availability |
| Chat | URL/auth/timeout/response classifications PASS | READY or typed CONFIG/AUTH/CONNECTIVITY/TIMEOUT/CONTRACT failure | Configured remote Chat provider |
| Embedding | Independent collect-all stage PASS | READY or stage-specific failure | Configured remote embedding provider |
| Reranker | Independent collect-all stage PASS | READY or stage-specific failure | Configured remote reranker provider |
| Kafka | Config/client/admin/connect/cluster/topic and bounded metadata tests PASS | Detect unreachable advertised broker without hanging | Bootstrap plus every advertised broker reachable from PREP |
| Schema Registry | Internal discovery and external fallback tests PASS | Select exact MCL value subject and validate schema | Reachable GMS registry or configured Confluent Registry |
| MCL capture/catch-up | Bounded capture, checkpoint, multi-batch catch-up and history-gap tests PASS | Continue background catch-up; never reset accepted checkpoint | Retained Kafka offsets and supported MCL topic/schema |
| K9 | Historical DEFERRED-to-REQUIRED Docker upgrade PASS | Reconcile identities/policies, refresh, Neo4j project and semantic promotion | Current DataHub inventory and adequate local Docker resources |
| Airflow/GX execution | Optional DAG/readiness classification PASS | READY only for readable configured quality DAG; otherwise DEFERRED | Existing approved Airflow/GX path when execution is required |
| MinIO | Independent optional preflight classification PASS | READY when configured; otherwise DEFERRED | Existing external MinIO only when configured |
| Target-state upgrade | Historical accepted descendant upgrade PASS | Preserve volumes, secrets, rows and receipts | Target Docker state must match canonical owned identities |
| Authenticated smoke | Forced failure then same-command resume PASS | Typed K9/MCL/provider/admin result; no duplicate bootstrap | Valid PREP administrator password and live providers |
| Accepted receipt | Atomic post-gate receipt test PASS | Write only after all required gates pass | Writable target-owned runtime directory |
| WSL/LAN access | Product bind/isolation contract PASS | Product changes no Windows firewall or portproxy state | Windows firewall, Hyper-V/WSL mirrored networking or bounded port forwarding |

## Verification

- PREP deploy/handoff focused contract: `107/107 PASS`.
- Provider/MCL discovery/scheduler/capture focused Node tests: `62/62 PASS`.
- Final-source isolated Docker scenarios: `4/4 PASS`.
- Node Product server: `167/167 PASS`.
- UI: `90 files / 663 tests PASS`.
- ESLint, TypeScript, standard build, POC build, changed-file Ruff format/lint, CI-scope strict
  mypy over `580` files, static verification, Python compile, shell syntax, diff-check, and delta
  secret scan: `PASS`.
- Repository-wide Python aggregate: `3977 passed / 120 skipped / 55 known baseline failures`.
  The same strict-migration/source-host/legacy failures are present in unchanged `origin/main`
  source and are outside this deployment correction. No global all-green claim is made.
- Router/retrieval/reranking semantics changed: `NO`; Router 60 plus Boundary 8 was not rerun.

The exact Product OCI image is `linux/amd64`, carries revision
`6a56c4013d21a39bd81ca199c3a6835d9b7dffc7`, and has image ID
`sha256:96f2350aaa0902584064fb9cf1f257f48cf4a2e11074758add13510408f9c456`. The
pinned runtime imports provider preflight and MCL discovery successfully. Final image configuration
and history contain no provider credential or credential-bearing proxy value.

The only Product deployment command remains:

```bash
./scripts/prep39083 deploy
```

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
