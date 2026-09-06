# ADR-0141: POC AUTO classifier completion envelope V2

- Status: Accepted for the authentication-free POC only
- Date: 2026-09-06
- Refines: ADR-0121, ADR-0140
- Does not modify: route schema, parsing, semantic validation, fail-closed behavior, provider/model
  selection, transport, timeout, explicit routes, or Chat persistence

## Context

PREP39083 executed the exact `AUTO` smoke classifier three times after ADR-0140. Runtime request
capture proved that every request carried `max_tokens: 1024`, both reasoning-disable controls,
temperature zero, non-streaming output and the strict JSON schema. All three provider responses
still ended with `finish_reason=length`; their string content was truncated and failed strict JSON
parsing. PostgreSQL Chat discovery persistence was independently healthy and both managed graph
assets were available to the planner.

The evidence proves that the 1,024-token Product-owned classifier completion ceiling remains too
small for the selected provider's bounded reasoning/output behavior. It does not prove a timeout,
transport, authentication, schema or parser defect, and it does not establish the provider's
maximum completion limit.

## Decision

The `AUTO` routing classifier alone uses a bounded 4,096-token completion ceiling. It continues to
send `max_tokens`, the exact parameter exercised by PREP, and does not add a provider-specific
parallel completion parameter.

The request retains `reasoning_effort: "none"`, `reasoning: { "effort": "none" }`, temperature
zero, non-streaming output and the existing strict `json_schema`. The shared 120-second provider
timeout remains unchanged. There is no retry, malformed-JSON repair, schema relaxation, parsing of
reasoning content, heuristic routing or fallback to GENERAL.

## Consequences

- Contextualization, memory compaction and answer-composition budgets do not change.
- The 4,096-token value is a conservative Product ceiling, not a declared provider token limit.
- Empty, length-truncated, malformed, schema-invalid, semantically inconsistent and timed-out
  classifier results remain typed fail-closed failures.
- Provider/model and credential configuration remain operator-owned and unchanged.

## Verification

1. Provider-contract tests assert the 4,096-token classifier-only ceiling and absence of
   `max_completion_tokens`.
2. Three repeated exact `AUTO` fixtures return stopped, valid GENERAL route documents.
3. Malformed, truncated, schema-invalid and semantic-invalid results retain the typed classifier
   contract failure.
4. A classifier timeout remains a typed routing-classifier timeout.
