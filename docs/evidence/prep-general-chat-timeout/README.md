# PREP GENERAL Chat Timeout Contract Evidence

Recorded at `2026-08-26T09:25:25Z` for Product
`2dc2b56a0a056bfa6cd6e6985c42fb1418be5b99`.

## Root cause

The configured PREP provider, route, authentication, and transport were already healthy. The old
release contract nevertheless fixed `POC_LLM_TIMEOUT_MS` at 15,000 ms while the Chat preflight used
a separate 60,000 ms deadline and the final GENERAL composer carried another hardcoded 60,000 ms
override. Contextualization, AUTO classification, memory compaction, Knowledge composition, and the
final answer therefore did not share one reviewed inference deadline. A one-token preflight could
pass while a longer GENERAL composition or another Product Chat stage exhausted its shorter Product
deadline and surfaced as a generic provider failure.

The corrected Product uses one tracked per-call Chat provider deadline:

```text
POC_LLM_TIMEOUT_MS = 120000
accepted range      = 1000..300000
smoke HTTP envelope = 300000
```

The 120-second value is fixed in the tracked PREP environment contract and is not an operator-owned
`.env.prep` value. It gives bounded headroom for remote inference without extending the existing
five-minute maximum. Contextualization, AUTO classification, memory compaction, GENERAL/VECTOR/GRAPH
answer composition, and Knowledge Chat composition use the same per-call value. Chat provider
preflight uses that same value. The smoke envelope remains longer because one Product request may
perform a classifier and composer sequentially; it does not override either Product call deadline.

## Sanitized failure contract

The Product now distinguishes:

- `POC_LLM_PROVIDER_TIMEOUT`;
- `POC_LLM_PROVIDER_AUTH_FAILED`;
- `POC_LLM_PROVIDER_CONNECTIVITY_FAILED`;
- `POC_LLM_PROVIDER_HTTP_FAILED`;
- `POC_LLM_PROVIDER_CONTRACT_FAILED`.

The PREP smoke and deploy wrapper propagate only their bounded mapped forms, including
`PREP_SMOKE_GENERAL_PROVIDER_TIMEOUT_FAILED`. An unknown GENERAL-provider-shaped value is rejected
as `PREP_SMOKE_UNKNOWN_FAILED`. The independent GENERAL route/evidence invariant remains
`PREP_SMOKE_GENERAL_ROUTE_FAILED`. Provider response bodies, URLs, credentials, tokens, and secrets
are never included in the failure record.

## Regression

- Shared timeout focused tests: `5/5 PASS`.
- Generated latency beyond the former short deadline but below the canonical bound: `PASS`.
- Exceeded configured bound: HTTP 504 plus typed timeout: `PASS`.
- Provider HTTP, auth, transport/timeout, and response-contract separation: `PASS`.
- AUTO classifier plus GENERAL composition: `GENERAL`, zero evidence, `PASS`.
- Node Product server: `144/144 PASS`.
- UI: `90 files / 663 tests PASS` (UI source unchanged by the final timeout consolidation).
- ESLint / TypeScript / production build / POC build: `PASS`.
- Ruff lint and changed-file format: `PASS`.
- strict mypy: `588` source files `PASS`.
- static verification: `PASS`.
- PREP deploy/handoff unit contract: `49/49 PASS`.
- Isolated Docker fresh/existing/residual state matrix: `PASS`.
- Exact-Product forced smoke failure to same-command resume: `1/1 PASS` in `113.82s`.
- exact linux/amd64 OCI revision: `PASS`.
- final image proxy/credential environment leakage: `NONE`.
- `git diff --check`: `PASS`.

The exact OCI is `linux/amd64`, carries revision
`2dc2b56a0a056bfa6cd6e6985c42fb1418be5b99`, and has image ID
`sha256:20aed124f502f9b7f714d6d02daa77977c63c527c7ccdb77e1a4b0855859d9e3`. The
full-stack runtime gate used isolated PostgreSQL, Neo4j, Redis, bootstrap identities, and web health;
it did not touch canonical 39080 or PREP/OPS state.

Router intent, retrieval, reranking, grounding, and authorization semantics were not changed. The
accepted Router 60 plus Boundary 8 regression was therefore retained rather than repeated.

## Deployment

The only PREP operator command remains:

```bash
./scripts/prep39083 deploy
```

An existing Product-owned `SMOKE_FAILED` attempt resumes through the same command. No volume
deletion, database reset, `.env.prep.runtime` removal, attempt-receipt deletion, manual container
recreation, or operator environment edit is required.

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.

