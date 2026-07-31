# ADR-0102: Bounded request-time Chat conversation memory

- Status: Accepted
- Date: 2026-08-01
- Refines: ADR-0018, ADR-0019, ADR-0035, ADR-0049, ADR-0089

## Context

Chat persists owner-scoped question/answer pairs, but every new request previously sent only its
current question to routing, retrieval and composition. Passing browser history back to the server
would make the client an authority and could cross Workspace, Subject, retention or policy
boundaries. Storing a reusable model summary in `chat_sessions.scope`, run metrics or an assistant
message would also create an untyped durable authority without lifecycle or erasure semantics.

## Decision

Enable bounded request-time conversation memory by default without adding a durable checkpoint.
For an existing server-issued session, a dedicated database query reads completed USER messages
only when the exact Workspace, owner Subject and session match, the session is not archived, its
`ACTIVE_POLICY_V1` deadline has not expired, and the same policy ID/hash is still ACTIVE. Current
Subject state is refreshed before that query. Assistant answers, evidence and citations never enter
conversation context.

The first three user requests use only the available bounded prior user-intent window. Beginning
with the fourth request, the server re-reads and re-compresses that bounded window on every request.
This is a start threshold, configured by
`CHAT_CONVERSATION_COMPRESSION_START_AFTER_USER_TURNS` with default `3`; it is not a cadence and
does not create a reusable checkpoint. `CHAT_CONVERSATION_CONTEXT_MAX_TOKENS` bounds the added
context conservatively, while the selected provider-specific context window keeps the fixed
system/output reserve. The original request remains the only persisted user message.

Compression uses the same currently approved composition provider and one fixed non-executable
tool. Its input contains only prior user utterances and the current question. Its output may resolve
referents, intent and explicit entity names, but may not add assistant content, organizational
facts, evidence, citations, UUIDs, URNs, URLs, locators, versions, hashes, tools or code. The output
is untrusted query context, never `ChatEvidence`, citation authority or authorization input. Every
fact still comes from current retrieval, ABAC and final citation reauthorization.

The request budget reserves the bounded context and a possible compression call before provider
execution. A history read, membership refresh, provider call or output validation failure discards
all prior context and executes the existing current-question pipeline once. It never falls back to
full raw history. A successful degraded answer carries a visible disclosure, and the persisted
terminal workflow records only `CONTEXT_NOT_NEEDED`, `RAW_CONTEXT_USED`,
`COMPRESSED_CONTEXT_USED` or `CONTEXT_DEGRADED`; no summary content is stored.

## Consequences

- Archive, expiry, policy supersession or membership/security-identity revocation produces zero
  reusable context on the next request.
- Request and response schemas, Assistant tables, relevance thresholds, grants and citation
  validation remain unchanged. No migration or data-model revision is introduced.
- Requests after the start threshold pay bounded compression latency and tokens each time. This is
  intentional: it avoids a new durable authority and reflects current lifecycle state immediately.
- An exact reusable three-turn checkpoint remains OPEN. It requires a separately approved typed
  table with forced RLS, Workspace/owner/session/message fences, policy-hash and retention binding,
  archive/expiry/revocation invalidation, erasure handling and a migration; it must not reuse JSON
  scope, run metrics or visible messages.

## Required evidence

1. Cross-owner/session, archived, expired and superseded-policy reads return no context.
2. Only completed USER messages are read, in bounded chronological order.
3. The fourth and later request invokes bounded compression; earlier requests use only bounded raw
   user intent.
4. Provider/read/output failure passes only the current question downstream and records degraded
   state without raw fallback.
5. Compression payloads and outputs exclude assistant answers and internal evidence identifiers.
6. Existing retrieval authorization, reranking and final citation fail-closed tests remain green.
