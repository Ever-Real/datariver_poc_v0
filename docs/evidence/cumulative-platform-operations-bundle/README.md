# Cumulative platform operations integration bundle

## Boundary

This Evidence records the bounded bundle that was already in flight after the
accepted Chat release. It contains DQ-02 governed metadata recommendations,
the reviewed Airflow connection projection, the MCP user-scoped read-only
broker, and honest Chat performance attribution. It does not integrate a new
Home/Search lane, automatic metadata mutation, MCP mutation, or a second
Airflow configuration source.

Starting accepted baseline:

- Product: `567da6ba6e11f5b72126dffa3ccf7dac9621ef58`
- Evidence: `66bca666b15c36b23d694ce20415be573024d917`
- Handoff / origin/dev: `28c14424e9d5279f0c3a40b436e9912f3d5e541a`
- origin/main: `17f32a52de79077c433bf0beaabac81a48e46062` (unchanged)
- TEST baseline: cumulative accepted-state deploy and same-command rerun `6/6`
- Actual PREP / OPS: NOT EXECUTED

## Product

The clean Product checkpoint is
`7e256911aab99489735cc6921cd01564153640c8`.

### DQ-02

- Candidates are derived only from the current authorized asset/Column context
  and caller-selected existing local Tag/GlossaryTerm vocabulary UUIDs.
- No provider/business URN, name, table or count is invented or hardcoded.
- Preview, reject, individual approve and bounded bulk confirmation are exposed.
- Approval creates the canonical Governance change request atomically with the
  recommendation decision, immutable event and actor-bound replay receipt.
- DataHub metadata is not automatically mutated. Automatic application remains
  `NEEDS_DECISION`.
- Migration `0101` and regenerated `0001` agree with SQLAlchemy metadata and the
  accepted checksum inventory.

### Airflow

- ADR-0048 remains the only deployment configuration authority.
- Product exposes a bounded, sanitized, read-only connection status and the
  existing allowlisted durable DAG actions.
- Current actions are explicitly `WORKSPACE_WIDE`; the deployment connector ID
  is not fabricated as a domain System UUID and no name matching is used.
- Live external Airflow acceptance remains `BLOCKED_EXTERNAL`.

### MCP

- The rejected `0ad645e` JSONL/caller-grant design is not included.
- The existing bearer endpoint remains compatible; the user endpoint requires
  canonical session authentication and exact request Origin.
- Every read applies the exact intersection of user and service capability,
  grade, System/Table and feature-policy scope before one provider operation.
- `tools/list` and `tools/call` now share the same feature-policy predicate.
- Timeout cancellation reaches scope, snapshot, Neo4j and metadata providers.
- Durable receipts contain bounded hashes only and are append-only under the
  Product-owned PostgreSQL V3 contract.
- Mutation tools remain absent pending `MCP_MUTATION_DELEGATION_POLICY`.

The single final Gemini 3.1 Pro High independent re-audit passed six areas and
found one blocker: user `tools/list` advertised Knowledge tools that the native
feature policy denied at execution. Commit `dade6fd` corrected only that
surface, and the focused deny test plus ESLint pass. No further MCP audit cycle
was opened.

### Chat

Commits `19254cc` and `1c5e982` attribute prompt assembly, request
serialization, provider wait and response-body time without changing retrieval,
authorization, totals, cursors or evidence. A bounded Gemini call-path analysis
identified possible provider-call and concurrency optimizations, but they were
not applied without same-provider routing/connection evidence. This Product is
instrumentation, not a claimed latency improvement.

## Verification

- Node Product: `218/218` PASS; `10` explicit external PostgreSQL skips.
- full UI: `94` files, `737/737` PASS.
- DQ-02 focused backend: `58/58` PASS; `4` isolated PostgreSQL tests skipped in
  this final run and already passed on the independently audited candidate.
- PREP release/deploy/handoff: `136/136` PASS.
- PREP smoke: `34/34` PASS.
- changed Python surface strict mypy: `34` files PASS.
- Ruff lint, TypeScript typecheck, full ESLint, POC build, application build,
  static/source integrity and migration checksum: PASS.
- canonical `0001` regeneration: deterministic, no diff.

The broad Python run recorded `4,157` PASS, `125` explicit environment skips
and `19` failures. Two current-head revision assertions were corrected and
focused PASS. The remaining `17` are pre-existing origin/dev failures in
unchanged dev-host secret fixtures, historical migration assertions, missing
documented source-host keys and the pilot bind-message assertion. They are not
reclassified as Product PASS and were not changed in this bundle.

## Exact build-once artifact

The clean Product was built exactly once for `linux/amd64`, then exported from
that already-verified local image without a rebuild, pull or load.

| Identity | Exact value |
| --- | --- |
| Product | `7e256911aab99489735cc6921cd01564153640c8` |
| image | `datariver-poc:7e256911aab99489735cc6921cd01564153640c8` |
| child manifest | `sha256:cb91ab43e35160a88c3fd58c3a6c8d7f5b49f9bc499c25ff4891007546e198a0` |
| config digest | `sha256:800a748bfccc1f81ac4d6f6152f6a71262c5b6230ac339703604c38fa23e9c8c` |
| archive SHA-256 | `33586a04774b34c89cda007e5125dd99b21fcba92cdea9609ff176652fdac584` |
| platform | `linux/amd64` |
| OCI revision | exact Product SHA |

The prior Wave C and accepted baseline images are not retagged or reused.

## Pending TEST acceptance

The existing accepted TEST state must be preserved. The provisional Handoff
will pin the exact archive above, fast-forward origin/dev and use only:

```bash
./scripts/prep39083 deploy
```

Acceptance must prove the prior database revision to `0101`, Product-owned
schema fingerprint, existing data and DQ record preservation, exact archive
load with no build, 6/6 smoke, feature/API checks and a same-command safe rerun.
Failure is fail-closed; reset, resecret, volume deletion and user metadata
mutation are prohibited.

Actual PREP and Actual OPS remain NOT EXECUTED. No PREP readiness claim is made.

## TEST packaging correction candidate

The first accepted-state TEST attempt reached authenticated deployment stage
`WEB_START` but the exact `7e25691` Web image entered a restart loop with
`ERR_MODULE_NOT_FOUND` for the Product-owned `poc-airflow-control.mjs` import.
Provider preflight had passed, and PostgreSQL, Neo4j and Redis remained healthy;
the failed Web container was stopped without deleting volumes, resetting state
or regenerating secrets. This is a Product image inventory defect, not an admin
credential, provider, storage or authorization failure.

The bounded correction adds only the missing explicit Dockerfile `COPY` and a
release-contract regression assertion. The recursively inspected local runtime
import graph reports no other uncopied module. The corrected clean Product is:

| Identity | Exact value |
| --- | --- |
| Product | `579b068340f2e38ecc8f2f05ed0460c66797b226` |
| image | `datariver-poc:579b068340f2e38ecc8f2f05ed0460c66797b226` |
| child manifest | `sha256:ef7509a259406bcbefea5716f7efdbf7b2159d7edc71e1c759f2f9d4b8d46414` |
| config digest | `sha256:b13ee5ee2af4ff66035e0ced0bf42acffdaf104c3c2a3d8f2c7db0f39c495ec8` |
| archive SHA-256 | `06b57db5c1a31f6e54cac9e638eb11837196ffaa515fd6fee89f032830ac8f63` |
| platform | `linux/amd64` |
| OCI revision | exact Product SHA |

Focused release/deploy/handoff tests are `137/137` PASS, the image-local
Airflow runtime module import is PASS, and the artifact was exported from the
already-built exact image without rebuild or pull. TEST accepted-state resume,
6/6 smoke and same-command rerun remain pending and are not claimed here.
