# ADR-0120: POC bounded Chat session memory and response focus

- Status: Accepted for the authenticated POC
- Date: 2026-08-12
- Refined: 2026-08-26
- Refines: ADR-0089, ADR-0102, ADR-0117, ADR-0118, ADR-0119
- Does not modify: production Chat retention/authorization, canonical evidence ownership,
  raw provider-token exposure, or production conversation checkpoints

## Context

The earlier POC retained visible questions and answers in a browser-owned session list, so refresh,
relogin or a web restart could not prove account-scoped history. A follow-up such as
`그 테이블의 컬럼은?` also needs bounded context. Sending the complete transcript would grow the
prompt without a bound and would incorrectly encourage treating a previous assistant answer as
current DataHub evidence.

The composer also limited questions to 4,000 characters and did not expose the limit. When a result
arrived, the conversation did not focus the new answer. A client timer replay could imitate
streaming but would not be a truthful network-progress contract.

## Decision

The POC PostgreSQL state store owns account-scoped sessions and completed turns. An existing session
is read only for its exact authenticated owner; client local storage is not a history authority.
At most five persisted turns are reduced to bounded request-time continuity memory. Each question
is capped at 900 characters and each answer at 1,300 characters within that derived memory.

For a referential follow-up only, the server uses a closed JSON-schema model call to rewrite the
current text as a standalone question. Routing and live DataHub/Neo4j retrieval use that rewritten
question. The final composer receives the original question, standalone question, bounded memory
and freshly retrieved evidence in separate labelled sections. Memory is non-authoritative continuity
text: it cannot become `ChatEvidence`, a citation, authorization input, provider request syntax or a
replacement for current retrieval. New sessions and deleted sessions have no reusable memory.

Question input is capped at 12,000 Unicode code units in both browser and gateway, with a live
`current / 12,000` counter. The conversation follows workflow progress and focuses the completed
answer. Any user wheel, touch, pointer/scrollbar or scrolling-key action disables that follow mode
until the next submitted question.

After the server has fully composed, grounded and authorized an answer, it emits bounded
`answer_delta` frames before the canonical persisted result. The browser displays those network
chunks directly and follows the newest content until the user scrolls away from the bottom.

## Consequences

- Pronoun-based follow-ups can preserve same-session intent while every Catalog fact is still
  revalidated against live provider evidence.
- Prompt growth is bounded independently of visible, durable session history.
- Restarting the web container does not discard completed session history because PostgreSQL is the
  canonical store. A different subject cannot list or read another subject's session.
- Server SSE streams real workflow stages and approved answer chunks, never raw provider tokens.

## Required evidence

1. A same-session follow-up derives continuity from no more than five completed persisted turns.
2. Oversized question and derived-memory fields fail before provider execution.
3. Referential follow-ups are resolved and retrieve current DataHub evidence; no memory record is
   returned as evidence.
4. The 12,000-character counter and clamp, answer-delta following and user-scroll cancellation have
   component/browser evidence.
