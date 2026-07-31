# ADR-0089: Server-observed live Chat workflow progress

- Status: Accepted
- Date: 2026-07-31
- Owners: Knowledge Platform, Application, Security Architecture
- Refines: ADR-0049, ADR-0082, ADR-0085

## Context

Chat retained a final workflow trace, but the browser could only see it after the full answer had
completed. A client-side countdown or a predicted stage list would misrepresent authorization,
retrieval, reranking, provider composition and final citation checks as completed when they had not
started or could not occur.

The product needs a live indication of the real stage currently being processed without turning the
Chat response into provider token streaming, exposing internal adapter detail, weakening the final
grounding contract, or persisting transient status as audit truth.

## Decision

`POST /chat/query/stream` accepts the same bounded request and follows the same authorization,
classification access, rate/token budget, retention, evidence and final citation reauthorization
contract as `POST /chat/query`. It returns `text/event-stream` with `Cache-Control: no-store` and
`X-Accel-Buffering: no`.

The Chat application service owns an optional observational workflow observer. It publishes an
`IN_PROGRESS` event immediately before each real server operation begins, then publishes the
existing terminal event when that operation has actually resolved. The route relays only those
typed stage, status and detail-code values, in order, followed by one unchanged final
`ChatQueryResponse` result event. The browser replaces a stage's transient status with its terminal
status; it never invents or advances a stage locally.

Transient `IN_PROGRESS` events are request-local and never become persisted Chat workflow records.
The existing stored response therefore remains an immutable terminal audit trace. An observer
failure, a full bounded queue or a disconnected browser cannot affect authorization, retrieval,
answer composition, persistence or the final result. Stream failures have one generic client-safe
error event; detailed RFC 9457 errors remain available from the ordinary endpoint.

This is not LLM output-token streaming. It does not expose model thoughts, prompts, evidence before
final authorization, provider credentials, raw Cypher, adapter diagnostics or a mutation path. It
does not change provider bindings, routing intent policy, query scope or graph-adapter readiness.

## Consequences

- Users can see the exact currently running authorization, budget, routing, retrieval, reranking,
  composition, citation-validation or persistence stage.
- A finished response and a restored history retain only verified final workflow states.
- UI state remains bounded to the eight named workflow stages, and an interrupted stream cannot
  leave a fabricated successful stage in the history.
- API consumers that do not need live progress retain the stable `POST /chat/query` contract.

## Verification

- Chat service tests prove server-observed `IN_PROGRESS` transitions are emitted in operation order
  and never persisted.
- SSE route tests prove workflow events precede the final result event.
- Client and Chat page tests prove authenticated stream parsing, security-boundary fencing and UI
  rendering of an in-progress stage before the final answer.
- The development runtime/browser check verifies a visible live stage and a final terminal trace;
  target-environment readiness remains a separate gate.
