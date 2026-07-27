# ADR-0047: Intranet WebAuthn default and local GGUF reranker

- Status: Accepted
- Date: 2026-07-26
- Refines: ADR-0025, ADR-0030, ADR-0043, ADR-0046

## Decision

### WebAuthn remains optional and fail-closed

Set `OIDC_HARDWARE_WEBAUTHN_ENABLED=false` by default for intranet development and preparation
profiles. The operator may set it to `true` only when the configured IdP has an exercised WebAuthn
enrollment and step-up flow. The API profile response and browser both treat an omitted value as
disabled.

Disabling the capability hides enrollment and step-up controls but never converts
`HARDWARE_WEBAUTHN` authorization into password authorization. High-risk mutations remain denied,
and the separately governed Maker-Checker fallback in ADR-0009/ADR-0025 is unchanged.

### Ollama-owned local models have three distinct capability paths

The Mac development profile uses:

- `datariver-gemma4-dev:0.1` through Ollama's OpenAI-compatible Chat route;
- `bge-m3:latest` through Ollama's OpenAI-compatible Embedding route; and
- `qllama/bge-reranker-v2-m3:q4_k_m`, whose GGUF remains in the Ollama model store, through a
  loopback-only `llama-server --reranking` process on port `11435`.

Ollama itself does not expose `/api/rerank` or `/v1/rerank` and its generation route cannot serve
this non-causal BERT classifier. Therefore the reranker connection mode is named
`LOCAL_LLAMA_CPP`, not `LOCAL_OLLAMA`. The managed process resolves the model blob only through
`ollama show --modelfile`, accepts only a regular `sha256-*` blob beneath the configured Ollama
model store, binds only `127.0.0.1:11435`, and exposes the fixed `POST /v1/rerank` request.
Containers reach that loopback service only through Docker Desktop's
`host.docker.internal:11435/v1` gateway.

The operator workflow starts and probes the local reranker. PID/state/log files are bounded to the
ignored `runtime/local-reranker` directory. A recorded PID is stopped only if its command still
matches the managed `llama-server` port and model path.

The local llama.cpp response contains finite raw classifier logits rather than `[0, 1]`
probabilities. The local connection probe therefore validates a bounded result count, unique
in-range document indexes and descending finite scores. The private `INTRANET_RERANK_V1` contract
continues to require descending finite scores in `[0, 1]`, TLS, a private allowlisted destination
and the canonical mounted API-key reference.

Reranking remains a configured/testable System Settings capability with no ACTIVATE route or
runtime retrieval consumer. A passing local connection test must not be described as production
inference or as search reranking being active.

## Consequences

- An intranet test deployment no longer presents unusable authenticator registration controls by
  default, while high-risk authorization remains fail-closed.
- Chat, Embedding and Reranker model identities are explicit and independently probed.
- A local reranker requires both Ollama (model ownership) and `llama-server` (the inference route).
- WSL and production do not enable this bridge; their private reranker gate remains unchanged.
