# PREP provider-preflight classification correction evidence

Recorded at `2026-08-27T06:40:34Z` for Product
`c4d8284c347194c3cb0c30728b66c036c362cd67` on `dev`. The controlled PREP branch `main`
remained fixed at `2876508145cbed410ae343623a2e3bedcac823cf` throughout this work.

## Root-cause audit

The previous Product could lose the failing stage because `runProviderPreflight()` invoked the
known WEB_INTRANET, DATAHUB, QUALITY_READ, CHAT, EMBEDDING, RERANKER, MCL_DISCOVERY, AIRFLOW and
MINIO operations without a stage-owned exception boundary. In particular:

- MCL Kafka configuration, Kafka client construction and `admin()` construction happened before
  its main `try/catch`.
- MCL's generic catch labeled every remaining exception as Kafka connectivity, while URL/provider
  version and Registry construction had untyped or incorrectly typed paths.
- provider URL and Chat-timeout parsing could fail before the request wrapper; Airflow and MinIO
  URL construction had the same boundary gap.
- generic local-auth and cleanup exceptions could be mislabeled or override a more precise primary
  failure.
- optional `error.code?.startsWith(...)` checks were unsafe when an exception exposed a non-string
  code.
- the deploy wrapper used `PREP_PREFLIGHT_UNKNOWN_FAILED` when the child envelope was absent or
  malformed.

These defects prove why the prior diagnostic could collapse to UNKNOWN. The historical PREP output
did not retain the original exception, so it does **not** prove which one of those branches occurred
on that host. The exact PREP cause therefore requires one rerun of the corrected descendant; no
operator environment guess or mutation is justified before that rerun.

## Corrected boundary

- Every known provider operation now runs inside one bounded stage wrapper. Existing
  `PREP_PREFLIGHT_*` and `PREP_MCL_DISCOVERY_*` classifications are preserved exactly; other
  exceptions become `PREP_PREFLIGHT_<STAGE>_UNEXPECTED_FAILED`.
- The final fallback is `PREP_PREFLIGHT_INTERNAL_UNEXPECTED_FAILED` and is reserved for programmer
  errors outside known stages. `PREP_PREFLIGHT_UNKNOWN_FAILED` is absent from the provider path.
- The emitted failure envelope contains only contract, status, stage, classification and a safe
  HTTP status class.
- MCL now types configuration, transport construction, Kafka client/admin construction, connect,
  cluster, topics, provider version, Registry, schema and cleanup separately. SSL accepts only
  `true`/`false`; brokers require `host:port` (or bracketed IPv6); SASL is restricted to the
  reviewed username/password mechanisms supported by this contract.
- cleanup failures cannot replace an earlier typed primary failure.
- malformed DataHub/LLM/Airflow/MinIO/Registry URLs and malformed Chat timeout configuration are
  deterministic CONFIG failures, not UNKNOWN or generic connectivity.
- The deploy wrapper preserves sanitized provider/MCL classifications and maps a malformed child
  envelope to the INTERNAL fallback.

No provider URL, token, proxy, CA, K9, GX, MCL architecture or authorization semantic was changed.
No Product data count, topic inventory or PREP-specific runtime observation was introduced.

## Verification

- Provider/MCL focused suite: `29/29 PASS`, including all nine known-stage injected exceptions,
  typed classification preservation, Kafka constructor/admin failures before connect, strict
  broker/SSL/SASL parsing, malformed Registry URL and cleanup precedence.
- Node Product server: `160/160 PASS`.
- UI: `90 files / 663 tests PASS`.
- PREP deploy/handoff unit contract: `76/76 PASS`.
- Isolated Docker non-destructive state matrix: `1/1 PASS` in `214.74s`, covering fresh,
  failed-first-install recovery, owned SMOKE_FAILED, accepted running/stopped update, same-release
  rerun and ambiguous fail-closed state without touching non-test volumes.
- ESLint, TypeScript, standard build, POC build, Ruff check, changed-file Ruff format, strict mypy
  over 587 files, static verification, Python compile, Compose/source-contract static checks,
  diff-check and changed-diff secret scan: `PASS`.
- Repository-wide Python aggregate: `3946 passed / 118 skipped / 55 known baseline failures`.
  The 55 are the unchanged strict migration-schema test doubles, DEV-host fixtures and unrelated
  legacy expectations recorded by the accepted prior Evidence. Every affected PREP/provider test
  passed independently.
- Router/retrieval semantics changed: `NO`; Router 60 plus Boundary 8 was not rerun.

The exact image is `linux/amd64`, carries OCI revision
`c4d8284c347194c3cb0c30728b66c036c362cd67`, and has image ID
`sha256:e696cc3192307693fb128dfefc4bcb68f060178a506b6fd1b40f37ea1f83cc67`.
Both corrected runtime adapters are present and parse under the pinned Node runtime. Final image
configuration/history contains no provider credential or credential-bearing proxy value.

## Deployment

The correction is a descendant release and does not alter ownership, volumes, generated secrets,
receipts or persistent state. The only PREP Product command remains:

```bash
./scripts/prep39083 deploy
```

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
