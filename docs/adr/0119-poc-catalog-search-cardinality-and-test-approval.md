# ADR-0119: POC Catalog search cardinality and TEST approval command

- Status: Accepted for the authentication-free POC only
- Date: 2026-08-12
- Refines: ADR-0116, ADR-0117, ADR-0118
- Does not modify: DataHub canonical ownership, production authorization, provider mutation,
  production vector chunking, or the canonical Change aggregate

## Context

The POC Catalog endpoint delegated non-empty queries to DataHub full-text ranking. The adapter then
reported a synthetic `NAME` match even when DataHub had ranked an item because of another field.
This differed from the existing Catalog contract, which requires every whitespace-delimited term
to match at least one enabled table, description, schema, column, tag or glossary-term field and
returns the actual bounded match fragments.

Chat semantic retrieval also used a fixed top-five evidence window at lexical retrieval, vector
retrieval and reranking. Top-k is appropriate for semantic discovery, but it cannot answer a
complete inventory count or an explicit request to list more than five assets. The UI therefore
looked as though DataHub itself contained only five relevant tables.

In Change TESTING, the UI exposed a separate typed-result command and disabled approval until that
command had already succeeded. The product interaction requires one approval request that either
identifies missing current-round evidence or atomically sequences the existing version-fenced
commands.

## Decision

The POC Catalog adapter applies the existing `ALL` keyword semantics to its complete cached DataHub
inventory. It accepts at most 12 unique terms of at most 120 characters, evaluates only the enabled
`SCHEMA`, `TABLE`, `COLUMN`, `TAG`, `TERM` and `DESCRIPTION` fields, and returns provider-derived
`NAME`, `DESCRIPTION`, `SCHEMA`, `COLUMN`, `TAG` and `TERM` match fragments. DataHub remains the
source; this local projection changes selection semantics, not metadata ownership.

Chat distinguishes semantic discovery from a complete Catalog inventory request. An unfiltered
table/dataset/view count reads the reconciled full DataHub inventory and composes the count
deterministically. An explicit list request returns the requested cardinality, bounded to 20 per
response, plus one aggregate inventory evidence record. Semantic discovery keeps a default top-five
window but honors an explicit list cardinality up to the same bound through vector retrieval and
reranking. The bound protects response size; it is not presented as a DataHub total.

TESTING presents `보완 요청` and `승인 요청`. Approval validates the current-round system, TEST
attachment and summary only when no PASSED run already exists. If values are missing it names them
without mutation. Otherwise the client sequences the existing idempotent, ETag-fenced commands:
record PASSED if needed, record TEST approval, then transition to `FINAL_REVIEW`. A CR change or
component unmount aborts the chain before a later command can run.

## Consequences

- Catalog results and `Matches` now explain the actual provider field and terms that satisfied the
  query, while absent keywords no longer leak fuzzy-ranked unrelated rows.
- Chat can report complete counts and list more than five live assets without asking the model to
  infer cardinality from a top-k sample. Requests above 20 require pagination or a future export
  contract.
- One button no longer means one HTTP mutation: optimistic versions and idempotency keys remain
  mandatory between each canonical command, and partial success is re-readable server evidence.
- This decision is POC presentation/orchestration only and is not proof of production scale,
  authorization, maker-checker separation or transactional provider execution.
