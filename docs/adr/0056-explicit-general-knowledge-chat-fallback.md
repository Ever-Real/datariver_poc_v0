# ADR-0056: Explicit general-knowledge Chat fallback

- Status: Accepted
- Date: 2026-07-28
- Refines: ADR-0011, ADR-0035, ADR-0049

## Context

The governed Chat path currently returns `검증 불가` whenever a successful authorized retrieval
produces no evidence. That response is correct for adapter, policy, citation or authorization
failure, but it also makes ordinary general-knowledge questions unusable. Treating both cases as
the same state hides whether the platform failed or simply had no matching internal source.

A general answer cannot be presented as grounded evidence. It also cannot receive hidden asset
metadata, infer whether inaccessible internal data exists, or become an error fallback that bypasses
classification/provider policy.

## Decision

- A general-knowledge answer is allowed only after the selected retrieval path completed normally
  and the final authorized evidence set is empty.
- Provider, routing, retrieval, reranker, policy, authorization and citation-validation failures
  continue to return the governed refusal. They never enter the general path.
- The general composer is a separate application port and fixed provider tool contract. It receives
  only the user's bounded question—no candidate, hidden, rejected or internal evidence metadata.
- The provider prompt prohibits claims about organization-specific systems, private data, access or
  current internal state. The server accepts only one bounded typed answer and rejects citations,
  unknown fields, prose outside the tool contract and oversized output.
- Every accepted answer is prefixed server-side with
  `※ 사내 인용 근거가 없어 일반 지식으로 답변합니다.`. Its workflow records
  `GENERAL_KNOWLEDGE_DRAFT_COMPOSED` and `NO_INTERNAL_CITATIONS_GENERAL_ANSWER`, and persists zero
  evidence citations.
- The composition provider must still be enabled by the active classification policy and match the
  immutable deployment binding. This decision does not create a provider fallback or relax
  workspace, action, clearance, system, domain, retention or budget controls.
- Grounded answers remain unchanged: they require a non-empty, duplicate-free subset of the exact
  authorized evidence and final reauthorization. Invalid or revoked citations never become a
  general answer.

## Consequences

- Users can ask general questions without confusing “no internal match” with a platform failure.
- The UI and audit trail clearly distinguish grounded, general-knowledge and refused responses.
- Tests must cover zero-evidence success, forged general citations, provider/retrieval failure,
  invalid grounded citations, zero persisted citations and the visible disclosure label.
