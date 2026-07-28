# ADR-0065: Intranet inference gateway prefixes and runtime reranking

- Status: Accepted
- Date: 2026-07-28
- Refines: ADR-0030, ADR-0043, ADR-0047, ADR-0049

## Context

The preparation environment receives Chat, Embedding and Reranking from one private gateway. Its
OpenAI-compatible routes are below `/api/llm/openai/v1`, its non-standard reranking route is below
`/api/llm/openai/rerank`, and its provider model identities begin with `/models/`. The prior
development adapter required an exact `/v1` base path, rejected a leading slash in model IDs and
had no runtime consumer for the already-probed private reranker.

## Decision

Continue to permit this adapter only in `APP_ENV=development`. Chat and Embedding accept a safe,
deployment-owned HTTPS base path whose final segment is `/v1`; DataRiver appends only its fixed
`/chat/completions` and `/embeddings` routes. Reranking accepts a safe HTTPS base path and appends
only `/rerank`. Path traversal, empty path segments, URL credentials, query strings, fragments,
redirects, proxy-environment routing and hosts outside the exact operator allowlist remain denied.
Startup and probes continue to require DNS resolution exclusively to private, non-loopback,
non-link-local addresses.

Provider model identities are opaque deployment values and may begin with one `/`, including
`/models/...`. They remain bounded to 128 characters and may not contain query, fragment, traversal,
empty or control-bearing segments.

The private reranker becomes a governed Chat runtime adapter. It receives only the already
authorized bounded evidence set, may only return unique evidence indices in finite descending score
order, and cannot add evidence or mutate canonical data. Runtime use still requires the active
classification rule's exact immutable Reranker provider-profile binding. Probe success alone does
not authorize use.

The deployment may set bounded Chat compatibility options: `temperature` in `[0,2]`, optional
`top_p` in `(0,1]`, optional `repetition_penalty` in `(0,2]`, and the boolean provider extension
`chat_template_kwargs.enable_thinking`. These values are included in the immutable deployment
binding. `stream` is always `false`; the current typed response validators do not accept streamed
responses.

Chat, Embedding and Reranking preserve distinct canonical secret-file references. When one gateway
credential covers every stage, the operator may place the same value in all three ignored,
mode-0600 files. This does not merge their rotation/audit identities and never places the literal
token in Git, `.env`, browser state or database configuration.

## Consequences

- A gateway base such as `https://llm.corp/api/llm/openai/v1` is portable without source changes.
- A Reranker base such as `https://llm.corp/api/llm/openai` resolves only to the fixed
  `/api/llm/openai/rerank` runtime route.
- Existing direct `/v1` Chat, Embedding and Reranking profiles remain valid.
- Provider support for forced tool calling and strict JSON response formats remains an external
  acceptance gate; no fallback weakens those response contracts.
- Public/SaaS endpoints and production inference remain outside this decision.
