# ADR-0121: POC reasoning-model Chat classifier compatibility

- Status: Accepted for the authentication-free POC only
- Date: 2026-08-12
- Refines: ADR-0085, ADR-0117, ADR-0120
- Does not modify: production Chat policy binding, explicit route behavior, retrieval authority,
  evidence authorization, or malformed-classifier fail-closed handling

## Context

The POC `AUTO` classifier uses a strict JSON-schema response from the configured OpenAI-compatible
Chat provider. The local Ollama `gemma4:e2b-it-qat` provider can spend the original 160-token output
budget on internal reasoning and return an empty `message.content` with `finish_reason=length`.
The strict parser correctly rejects that response, but users then receive a 503 before a route or
workflow can be established even though the provider itself is live.

Increasing the budget without disabling reasoning makes classifier latency and completion less
predictable. Parsing provider reasoning, guessing a route from an empty response, or silently
falling back to GENERAL would weaken ADR-0085.

The pre-classifier exact-asset resolver also treated arbitrary Korean prose tokens as possible
physical identifiers. A conversational question could therefore issue several DataHub searches
and then scan the cached full inventory before the bounded classifier began.

## Decision

The POC sends both OpenAI-compatible reasoning controls supported by the selected Ollama endpoint:
`reasoning_effort: "none"` and `reasoning: { "effort": "none" }`. The classifier remains
temperature-zero, non-streaming, and strict JSON schema. Its bounded output budget becomes 320
tokens, enough for the closed seven-field decision while remaining separate from the larger answer
composition budget.

The returned content still passes through the existing closed parser. Empty, malformed,
inconsistent, timed-out, or transport-failed responses continue to return the bounded-classifier
503. There is no heuristic fallback, no parsing of reasoning text, no second provider call, and no
new environment variable. Explicit GENERAL, VECTOR, and GRAPH selections continue to bypass the
classifier.

Before classification, exact-asset resolution accepts quoted names in any script and unquoted
technical tokens only when they contain a Latin letter, digit, or underscore. Unquoted natural
Korean prose is not sent through repeated exact-name DataHub searches. Korean catalog discovery
remains available through the semantic classifier and live retrieval, while a quoted Korean
physical name remains eligible for exact resolution.

## Consequences

- Reasoning-capable local models can emit the route contract instead of exhausting the classifier
  budget before `message.content` begins.
- AUTO retains the fail-closed behavior and route semantics established by ADR-0085.
- Providers used for this POC must accept the configured OpenAI-compatible reasoning controls;
  capability probing and target-PC acceptance remain deployment gates.
- The change does not claim that final answer generation is reasoning-free or token-streamed.

## Verification

1. Provider-contract tests assert strict JSON schema, both reasoning-disable controls, and the
   320-token classifier limit.
2. A malformed non-empty classifier response still produces 503.
3. The configured local provider returns a valid GENERAL decision for a non-catalog conversational
   question that previously exhausted the 160-token budget.
4. Explicit routes still bypass AUTO classification.
5. A general Korean question reaches the classifier without issuing a DataHub GraphQL request for
   each prose token.
