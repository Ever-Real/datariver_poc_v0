# ADR-0030: Development intranet OpenAI-compatible knowledge adapter

- Status: Accepted
- Date: 2026-07-21
- Refines: ADR-0011, ADR-0019, ADR-0023, ADR-0028

## Decision

Keep commercial or public-provider inference disabled. The browser continues to reject provider
URLs, literal API keys and secret values; production continues to have no external inference route.

Add one distinct **development-only** adapter for a model endpoint operated inside the organisation's
private network and implementing the bounded OpenAI-compatible `/v1/chat/completions` and
`/v1/embeddings` contracts. It is not classified as a commercial-provider route and cannot be
enabled by an inference-provider profile, a classification policy or an Admin browser action alone.

An operator must configure the following deployment controls before a tested System Settings revision
can activate it:

- `APP_ENV=development` only;
- one exact hostname allowlist in `INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS`;
- HTTPS endpoint ending exactly in `/v1`; no URL credentials, query or fragment;
- DNS resolution exclusively to private, non-loopback, non-link-local addresses at process startup
  and during the configuration probe;
- a distinct mounted file secret for the Chat and Embedding bearer API key; and
- a separately configured Chat model and Embedding model. A chat-only Gemma deployment is not an
  embedding provider.

The persisted LLM configuration includes `connection_mode: INTRANET_OPENAI_COMPATIBLE`, a model ID,
endpoint, bounded timeout/context options and only the portable
`file:/run/secrets/<name>` reference. The actual source-host process maps that virtual Docker-secret
root to its ignored `secrets/` directory through an operator-owned environment value. The browser
cannot change that mapping or submit a key.

TEST sends one fixed strict-JSON Chat request or one fixed Embedding request with the mounted bearer
credential. It never uses a request-supplied path or arbitrary body. A `401`/`403` after the key is
supplied is `UNAVAILABLE`, not a successful authentication requirement. ACTIVATE still selects an
immutable tested revision for the next source/API process startup; it does not hot reload a client.

The adapter uses the existing fixed OpenAI-compatible extraction and GraphRAG contracts. Model output
remains untrusted: it cannot issue tools, HTTP, SQL, Cypher, DataHub operations, filesystem actions
or mutations, and citations/evidence are validated server-side. The HTTP client has a fixed host
allowlist, no redirects and ignores proxy environment variables.

## Consequences

- This is an integration/development capability, not a production inference approval. The isolated
  worker, policy/profile route selection, token ledger, residency/retention attestation, egress
  evidence, red-team and streaming gates in ADR-0011 and ADR-0019 remain required before any
  production inference claim.
- A public hostname, an HTTP endpoint, a private URL outside the allowlist, a loopback endpoint, a
  missing API key or an incompatible strict JSON/embedding response fails closed.
- The current local Ollama bridge remains available, but it is mutually exclusive with this adapter.
- No database schema changes are required: immutable System Settings profile revisions already own
  the non-secret configuration and test/activation evidence.
