# PREP39083 portable one-command deployment evidence

This evidence advances the accepted Product
`99acf0d2a8be977323ead2f8647ef5b2ad77add7`, Evidence
`8daedd1b6ee1a8cad3d086486ad81e16504752c2`, and handoff
`43aa355221bfe6bf492a89486b14c76a2be6a48d` to Product
`46500c130de9c8bebedd143eca946b5d9166e63b`.

The work is a deployment-orchestration and provider-network portability correction. Router,
Knowledge Graph, MCP, DataHub projection, and authorization semantics are unchanged. No PREP or OPS
host was accessed or mutated.

## Retry ownership

The canonical operator command remains:

```bash
./scripts/prep39083 deploy
```

Immediately before the first Product-owned persistent mutation, the deployer atomically creates
ignored, mode-0600 `runtime/prep39083/deploy-attempt.json`. The receipt binds the exact Product,
Evidence, handoff, Compose project, persistent volume identities, K9 mode, and an HMAC runtime-env
fingerprint without storing any secret. Its bounded phases are `PREPARED`,
`STATE_SERVICES_READY`, `SCHEMA_READY`, `BOOTSTRAP_READY`, `WEB_READY`, `SMOKE_RUNNING`,
`SMOKE_FAILED`, and `ACCEPTED`.

A matching unfinished receipt is classified `EXISTING_OWNED_INCOMPLETE`. The deployer reuses the
existing runtime secrets and volumes and repeats only idempotent schema/bootstrap/web/smoke gates.
It does not reset PostgreSQL or Neo4j, rotate an accepted credential, delete a volume, or duplicate
an administrator or service Subject.

The exact final Product passed an isolated linux/amd64 Docker scenario in 190.04 seconds:

1. fresh state services, schema, one administrator, and one MCP Subject were created;
2. smoke was deliberately failed as `PREP_SMOKE_GENERAL_PROVIDER_FAILED` after durable bootstrap;
3. no accepted marker existed and the attempt phase was `SMOKE_FAILED`;
4. the same deployment entry point classified `EXISTING_OWNED_INCOMPLETE`;
5. the second run reused the same state and completed `ACCEPTED`;
6. administrator count remained one, MCP Subject count remained one, and no volume was deleted.

All disposable integration containers, networks, volumes, runtime files, and credentials were
removed after observation. Product deployment code contains no `down -v`, volume deletion, or
database reset path.

## Legacy pre-receipt compatibility

The canonical PREP bootstrap inspector is also the ownership proof for a handoff that failed before
attempt receipts existed. It recognizes only the exact deployment-owned footprint: one canonical
administrator, the requested distinct MCP/K9 service identities, zero active sessions, canonical
K9 policies/runs when enabled, no unexpected business/user state, and Neo4j data confined to the
managed namespaces recorded by those runs. That state becomes
`LEGACY_SELF_BOOTSTRAPPED_PARTIAL` and resumes idempotently.

Unknown identities, an unexpected user/business row, an unowned Neo4j node, invalid runtime
secrets, unknown project resources, or any inconclusive state remains fail-closed as
`PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY`. The currently described PREP residual is therefore
compatible when it matches the existing canonical bootstrap contract; no manual volume deletion is
required or permitted.

## Build and runtime network separation

`HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` are build/toolchain inputs only. They support `uv`,
Docker dependency resolution, and the bounded npm installation layer, and are not injected into the
Product web container.

Application provider routing is explicit:

- blank `POC_RUNTIME_HTTP_PROXY`/`POC_RUNTIME_HTTPS_PROXY` means direct provider traffic;
- configured runtime proxy routes through one pinned `undici@7.29.0` transport;
- `POC_RUNTIME_NO_PROXY` supports exact host, IPv4/IPv6, domain suffix, and optional port matching;
- optional `RUNTIME_CA_CERT_FILE` is mounted read-only and used with TLS verification enabled;
- global TLS rejection is never disabled.

The same shared transport handles DataHub, Chat, Embedding, Reranker, Airflow, MinIO, and the other
server-side HTTP provider calls without changing their API semantics. No proxy URL or credential is
stored in an OCI label, final image environment, npmrc, Evidence, or log.

Actual local network tests passed the supported matrix: no proxy/direct, build proxy only with
runtime direct, runtime proxy, mixed runtime proxy plus `NO_PROXY`, and private-CA HTTPS. The
private-CA test first rejected the untrusted endpoint and then accepted it through the target-local
CA while preserving `rejectUnauthorized=true`.

## Provider preflight and smoke

The exact built image runs bounded DataHub GraphQL, Chat, Embedding, and Reranker requests before the
attempt receipt and before Product-owned persistent mutation. A configured K9 Studio database is
checked with a read-only transaction; an absent Studio authority remains `DEFERRED`. The preflight
uses configured endpoints and does not assume `/health` or `/models`.

Authenticated smoke now emits login, DataHub, K9, and GENERAL progress plus bounded heartbeats.
Sanitized failure evidence contains only stage, classification, safe HTTP status class, elapsed
time, K9 mode, and timestamp. Implemented operator classifications include:

- `PREP_SMOKE_WEB_HEALTH_FAILED`
- `PREP_SMOKE_ADMIN_AUTH_FAILED`
- `PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED`
- `PREP_SMOKE_K9_NOT_READY`
- `PREP_SMOKE_SEMANTIC_INDEX_NOT_READY`
- `PREP_SMOKE_GENERAL_PROVIDER_FAILED`
- `PREP_SMOKE_GENERAL_ROUTE_FAILED`

Provider preflight separately classifies configuration, connectivity, authentication, and contract
failures without exposing credentials, provider bodies, or full URLs.

## Verification

- Deployment/handoff focused tests: 35/35 PASS.
- Provider transport, preflight, bootstrap, and smoke focused tests: 16/16 PASS.
- POC server: 129/129 PASS.
- UI: 90 files / 658 tests PASS.
- ESLint, TypeScript, POC build, static verification, Ruff, strict mypy, shell/Node syntax, Python
  compile, Compose validation, secret/proxy leak scan, and diff-check: PASS.
- Isolated Docker target-state matrix: fresh, same-release rerun, accepted running, accepted stopped,
  empty failed-first-install recovery, and ambiguous durable-state rejection PASS.
- Exact-Product failed-smoke same-command retry: PASS.
- Final DEV image: `linux/amd64`, OCI revision exactly
  `46500c130de9c8bebedd143eca946b5d9166e63b`.
- DEV 39083: HTTP 200, healthy, restart count 0; unauthenticated protected API HTTP 401.
- DEV 39090: HTTP 200.

Actual PREP deployment and runtime verification: **NOT EXECUTED**.
Actual OPS deployment and runtime verification: **NOT EXECUTED**.

Result at this Evidence checkpoint: `DEV_RUNTIME_VERIFIED_HANDOFF_PENDING`.
