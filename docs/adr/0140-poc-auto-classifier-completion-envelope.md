# ADR-0140: POC AUTO classifier completion envelope

- Status: Accepted for the authentication-free POC only
- Date: 2026-09-06
- Refines: ADR-0085, ADR-0121
- Does not modify: route schema, parsing, semantic validation, fail-closed behavior, explicit routes,
  Chat persistence, provider selection, or the shared provider timeout

## Context

PREP39083 ran the exact `AUTO` GENERAL classifier three times with two managed graph assets. One
call reached the existing 120-second provider timeout, while two calls returned string content with
`finish_reason=length`; both truncated responses failed strict JSON parsing. The active provider
accepted the OpenAI-compatible request and its 320-token limit, but that Product-owned completion
envelope was insufficient to reliably return the small closed route document. This evidence does
not establish a provider token limit or show that the shared 120-second timeout is too short for a
normal completed response.

## Decision

The `AUTO` routing classifier alone uses a bounded 1,024-token completion envelope. It continues to
send `reasoning_effort: "none"`, `reasoning: { "effort": "none" }`, temperature zero, non-streaming
output and the same strict `json_schema`. The Product continues to use `max_tokens`, which the
active OpenAI-compatible provider demonstrably honors, and does not add a second provider-specific
token option.

The shared provider timeout remains 120 seconds. There is no retry, malformed-JSON repair,
reasoning-content parser, schema relaxation, heuristic routing or fallback to GENERAL. Empty,
truncated, malformed, schema-invalid, semantically inconsistent and timed-out classifier responses
remain typed fail-closed failures.

## Consequences

- The envelope is classifier-specific; contextualization and answer composition budgets do not
  change.
- The value is a conservative Product output bound, not a claim about the provider's context or
  token limit.
- Provider/model selection and transport configuration remain operator-owned and unchanged.
- Chat discovery persistence and its SQL-null contract remain unchanged.

## Verification

1. Provider-contract tests assert the 1,024-token classifier envelope, the strict JSON schema and
   both reasoning-disable controls.
2. Repeated AUTO fixtures that require the expanded envelope complete as GENERAL with a stopped,
   valid route document.
3. Truncated JSON, malformed JSON, schema-invalid and semantic-invalid results remain typed
   classifier contract failures.
4. A classifier call exceeding the configured timeout remains a typed routing-classifier timeout.
