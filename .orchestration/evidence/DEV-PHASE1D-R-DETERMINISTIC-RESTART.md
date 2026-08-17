# PHASE 1D-R deterministic provider restart evidence

- Date: 2026-08-17, Asia/Seoul
- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Product SHA: `91ca4db7ca792566b7765f3366036b1d8bed2869`
- Deployed OCI revision: `91ca4db7ca792566b7765f3366036b1d8bed2869`
- Canonical DEV origin: `http://127.0.0.1:39083`
- Authoritative runtime: Node POC, not legacy FastAPI
- Result: `PHASE 1D-R COMPLETE_RUNTIME_VERIFIED`
- PHASE 1D overall: `PARTIAL`

No password, password hash, cookie, session token, provider token, model path, disposable account
identity or Table identity is recorded here.

## Current Baseline

The prior runtime-only provider repair was held fixed while its restart contract was made
deterministic. Source, image and runtime were then rebuilt and restarted from the tracked
configuration plus the supported ignored DEV configuration/secret boundary.

- Web is healthy and listens only on canonical loopback port 39083; port 39080 has no listener.
- Product SHA and deployed OCI revision match exactly.
- DataHub, Chat, embedding and reranking providers are reachable through the existing Product
  bindings.
- Inspection `admin` remains active, login-enabled, role `admin`, maximum grade `restricted`, with
  failed attempts 0 and no lock. Its credential and session were not used for this validation.
- Login-enabled credentials: 1; active sessions: 1; active Table grants: 0; active Table↔System
  mappings: 0.
- Fixed feature-security policy: version 24, 120 cells.
- MCL ledger/checkpoint/CR-link/source invariants: `46 / 2 / 4 / 2`.
- Embedding retention: three generations/bindings and 6,002 rows total; current active generation
  has 2,002 rows.

## Runtime-only Config Inventory

| Setting | Canonical classification | Decision |
|---|---|---|
| `DATAHUB_GMS_URL` | `TRACKED_CONFIG` with DEV value in ignored environment file | Web consumes the existing Compose binding; no source address was hardcoded |
| `DATAHUB_GMS_TOKEN` | `SECRET_CONTRACT` | Optional only under an explicit DEV-local no-token flag; value is never tracked or logged |
| Chat endpoint | `TRACKED_CONFIG` with DEV value in ignored environment file | Existing endpoint contract retained |
| Embedding endpoint | `TRACKED_CONFIG` with DEV value in ignored environment file | Existing endpoint contract retained |
| Reranker endpoint | `TRACKED_CONFIG` with DEV value in ignored environment file | Existing endpoint and process retained |
| `LLAMA_ARG_UBATCH` | `TRACKED_CONFIG` example + ignored DEV value | Existing supported llama.cpp option, validated and owned by the reranker manager |
| `POC_WEB_PORT` / host port input | `HOST_ONLY_COMPOSE_INPUT` | Selected environment file is the Compose authority; container environment is not treated as host substitution authority |

## Canonical Config Decision

`deploy/poc/.env` remains the ignored DEV configuration and secret boundary. The tracked
`deploy/poc/.env.example` documents required keys and safe defaults/placeholders. `scripts/run_poc.sh`
now requires the selected environment file for mutating Docker actions and removes same-name shell
exports before invoking Compose, so an operator's remembered shell environment cannot silently
override the selected file.

The bounded actions are:

```text
web-restart      → build/recreate Web only, no dependencies
reranker-restart → stop/start the existing managed local reranker from selected config
```

No configuration framework, provider abstraction or second runtime authority was added.

## DataHub Auth Contract

Missing DataHub token now fails closed by default. Only the explicit
`POC_DATAHUB_ALLOW_NO_TOKEN=true` DEV-local setting permits the current local auth-disabled GMS
contract. Compose injects a false default. PREP/OPS secret contracts were not changed and the DEV
opt-in is not a global authentication fail-open.

Focused source tests prove both boundaries: missing token with the default false setting is
rejected, and the explicit DEV-local true setting permits the existing local contract.

## Port Determinism

The earlier 39083→39080 drift was reproduced as host-only Compose substitution state, not a Web
application defect. The selected ignored environment file now owns the host port input. A clean
Web build/recreate restored:

```text
127.0.0.1:39083 → listening and healthy
127.0.0.1:39080 → no listener
```

Post-restart container inspection confirmed the exact Product OCI revision. PostgreSQL, DataHub,
Neo4j, Redis and Airflow were not recreated for this acceptance.

## Reranker Restart

The existing local reranker manager now:

- reads and validates `LLAMA_ARG_UBATCH` in the bounded range 64..4096;
- passes the existing llama.cpp supported `--ubatch-size` option;
- persists the effective value in managed ownership state;
- verifies managed state and argv on restart;
- transitions exact legacy managed state safely instead of adopting unrelated processes.

Clean restart retained the same provider, model fingerprint and loopback port. Effective managed
state and argv contain exactly one UBATCH value of 1,024. A short direct request and a representative
long metadata Product reranking request succeeded. The provider showed no restart loop or obvious
OOM condition; resident memory remained bounded after representative use.

## Embedding Generation Lifecycle

Read-only inspection found three retained generations/bindings with 2,000, 2,000 and 2,002 rows.
The current pointer selects the 2,002-row generation. Existing code cleans stale generations within
one binding but has no cross-binding retention/GC contract.

Classification: `UNBOUNDED_ACCUMULATION_RISK`.

No generation or row was deleted. A separate bounded retention/GC backlog item is required; it is
not part of provider restart determinism.

## Clean Restart Evidence

The owned DEV services were restarted without remembered manual shell exports:

- existing Ollama service: clean service restart, same installed version and model inventory
  fingerprint;
- existing reranker: `reranker-restart`, same endpoint/model fingerprint, UBATCH 1,024 effective;
- Web: `web-restart`, exact Product image and canonical port.

Direct provider health/config probes succeeded without printing secrets. Only the required owned
services were restarted; unrelated stateful services were left running.

## Product E2E

A fresh coordinator-owned disposable viewer exercised the actual Node POC after restart. Secret-
bearing account/session handling was not delegated and no inspection-admin credential was used.

| Product path | Post-restart result |
|---|---|
| General Chat | 200, `GENERAL`, no forced metadata evidence, provider composition completed |
| Empty scope | Catalog 0; Vector evidence 0; `NO_LIVE_EVIDENCE` |
| Granted Catalog | Exactly the two granted current Tables; ungranted Detail returned 404 |
| Vector | Two authorized evidence items, `PGVECTOR_COSINE`, `RERANKING_COMPLETED`, authorized citations only |
| AUTO metadata | Selected Vector path; authorized retrieval/reranking/context/citation only |
| Immediate grant removal | Catalog 0 and Vector evidence 0 without querying a global unauthorized scope |

The runtime ordering remains:

```text
authorized URNs → PostgreSQL WHERE → vector distance
authorized scope → AUTO route/retrieval → reranker → context → citation
```

General Chat remains independent of Table access.

## Authorization Regression

The deterministic restart change did not alter the authorization architecture. Full source gates
and actual Product negative paths preserved login/session, explicit Table grants, security grade,
fixed feature policy, Responsible System business scope, CR three-lane workflow, Catalog filtering,
direct 404 existence hiding, empty scope behavior and immediate grant removal.

The temporary viewer was disabled and login-disabled; its sessions and grants were removed. A
follow-up read-only check found no active 1D-R profile, grant or mapping. Inspection admin remained
untouched.

## Manual Metadata Compatibility Audit

Read-only source/provider inspection reconfirmed that sparse empty domain/glossary read-back can be
normalized differently by DataHub than the Product's exact multi-aspect receipt expects, producing
502 on that bounded manual-metadata path.

Classification: `DATAHUB_RESPONSE_NORMALIZATION` / `PRODUCT_RECEIPT_CONTRACT` compatibility.

It was not fixed or mixed into restart work. Registration/metadata-editing impact should be handled
as a separate small compatibility slice.

## Disposable Asset Cleanup

The prior higher-grade disposable Table remains absent from current projection/search, active tags,
active vector generation, active grants and Table↔System mappings. Its tombstone history was not
hard-deleted. The 1D-R viewer profiles are inactive with no active credentials, sessions or grants.

## Tests

| Gate | Result |
|---|---|
| Focused Python restart/config tests | PASS — 21/21 |
| Node POC full suite | PASS — 99/99 |
| Frontend full suite | PASS — 87 files, 592/592 |
| Lint | PASS |
| Typecheck | PASS |
| Production build | PASS; existing Vite chunk advisory only |
| POC image build | PASS |
| Compose render | PASS |
| Bash syntax / Ruff / Mypy | PASS |
| Secret/hardcoding scan | PASS |
| `git diff --check` | PASS |

`shellcheck` was unavailable and is not reported as PASS.

## AGY Usage

| Role | Requested model | Effective model | Result |
|---|---|---|---|
| Config authority audit | Gemini 3.1 Pro High | Gemini 3.1 Pro High | Read-only findings; no Product/runtime mutation |
| Lifecycle/compatibility audit | Gemini 3.1 Pro High | Gemini 3.1 Pro High | Read-only findings; no Product/runtime mutation |
| Critical config mutation | Claude Sonnet 4.6 (Thinking) | Claude Sonnet 4.6 (Thinking) | Bounded nine-file implementation; no commit/runtime/DB/container mutation by worker |
| Fresh independent validator | Gemini 3.1 Pro High | Gemini 3.1 Pro High | Read-only PASS after correcting overall-PHASE overclassification |

One incorrectly launched Claude terminal resolved to Gemini and was fenced before changes. Claude
did not report quota exhaustion; no quota fallback was used. Secret-bearing runtime setup and
cleanup were performed only by the coordinator.

## Validator

Fresh validator task `task_c68361c52eb6`, dispatch `ctx_1b27e6613772`, recorded the authoritative
worktree, branch, exact Product HEAD, matching OCI revision and effective Gemini 3.1 Pro High. It
used the Node POC runtime and read-only checks only. It independently confirmed Web 39083, no 39080
listener, reranker UBATCH 1,024, 6,002 retained embedding rows, zero active grants, the inspection
admin lock invariant and repository no-change state.

Its first proposed conclusion incorrectly promoted all of PHASE 1D. That message was rejected. The
accepted result is exactly:

```text
PHASE 1D-R deterministic restart → COMPLETE_RUNTIME_VERIFIED
PHASE 1D overall                → PARTIAL
```

## Product SHA and Evidence SHA

- Product SHA: `91ca4db7ca792566b7765f3366036b1d8bed2869`
- Deployed OCI revision: `91ca4db7ca792566b7765f3366036b1d8bed2869`
- Evidence SHA: the separate documentation commit containing this file, `CURRENT.md` and the master
  backlog; it is intentionally not folded into the Product revision.

## Remaining Risks

- Neo4j has no proven canonical DataHub Table URN provenance. Non-Admin graph stays fail-closed and
  the surface remains `PARTIAL`/Knowledge-phase dependent.
- Provider-wide lineage/traversal cannot prefilter every neighbor/total and remains bounded
  `PARTIAL`.
- Sparse empty-aspect manual metadata compatibility remains `PARTIAL`.
- Deleted/current-missing Table grade and unbound Knowledge/Governance resources retain their
  explicit future boundaries.
- Quality/GX rule→run→result remains blocked by the separate GX development-environment contract.
- Cross-binding embedding generation retention has no GC contract.

## PHASE 1D Reclassification

| Area | Canonical status |
|---|---|
| Account/session and central capability core | `COMPLETE_RUNTIME_VERIFIED` |
| Explicit grant/grade/fixed-policy Table enforcement | `COMPLETE_RUNTIME_VERIFIED` |
| Catalog/local read/count/detail | `COMPLETE_RUNTIME_VERIFIED` |
| PostgreSQL/memory vector pre-ranking | `COMPLETE_RUNTIME_VERIFIED` |
| General/Vector/AUTO/reranking/context/citation | `COMPLETE_RUNTIME_VERIFIED` |
| Deterministic DEV provider restart (1D-R) | `COMPLETE_RUNTIME_VERIFIED` |
| DataHub provider-wide traversal/totals | `PARTIAL` |
| Neo4j canonical provenance/pre-traversal | `PARTIAL`, Knowledge dependency |
| Unbound Knowledge/Governance resources | `PARTIAL`, feature-policy dependency |
| Quality/GX execution | `BLOCKED`, GX/Quality dependency |

Account/Auth core is a completed baseline. PHASE 1D remains technically `PARTIAL` because those
named surfaces are not falsely promoted; they no longer justify continuously expanding the core
Account/Auth program ahead of the product features that own them.

## Overengineering Check

```text
new tables:            0
new dependencies:      0
new services:          0
new containers:        0
new provider versions: 0
new frameworks:        0
new capabilities:      0
```

## Next Smallest Slice

Freeze 1D-R as the deterministic provider/runtime baseline. Next, audit the current MCL runtime and
DEV support services (Airflow, MinIO, GX) read-only against current source/runtime. The first Product
mutation after those audits is the smallest existing-contract MCL automatic-detection activation
slice. Do not start PHASE 1E/1F, GX/Knowledge/Quality product implementation or migration work.
