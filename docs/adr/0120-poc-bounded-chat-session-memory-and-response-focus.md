# ADR-0120: POC bounded Chat session memory and response focus

- Status: Accepted for the authentication-free POC only
- Date: 2026-08-12
- Refines: ADR-0089, ADR-0102, ADR-0117, ADR-0118, ADR-0119
- Does not modify: production Chat retention/authorization, canonical evidence ownership,
  provider token streaming, or production conversation checkpoints

## Context

The POC retained visible questions and answers in its browser-owned session list, but every provider
request contained only the current question. A follow-up such as `그 테이블의 컬럼은?` therefore
lost the preceding asset reference. Sending the complete transcript on every request would grow the
prompt without a bound and would incorrectly encourage treating a previous assistant answer as
current DataHub evidence.

The composer also limited questions to 4,000 characters and did not expose the limit. When a result
arrived, the conversation did not focus the new answer. A token-by-token replay would improve the
appearance of streaming but would delay an answer that the server had already completed.

## Decision

The POC browser keeps request-time memory only for the same POC Chat session. Each completed turn is
reduced to at most 900 question characters and 1,300 answer characters. At most five uncompacted
turns and one summary of at most 5,000 characters cross the same-origin gateway; the complete memory
payload is capped at 16,000 characters. After every five completed questions the browser schedules
one fixed Chat-model compaction. Successful compaction replaces those five turns with the summary.
Failure falls back to a deterministic bounded transcript summary and never blocks the next question.

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

The complete answer is inserted into the document immediately. A 480 ms CSS blur-to-sharp sweep
provides a streaming-like reveal without delaying content, making extra provider calls, or replaying
characters. Reduced-motion preference disables the effect.

## Consequences

- Pronoun-based follow-ups can preserve same-session intent while every Catalog fact is still
  revalidated against live provider evidence.
- Prompt growth is bounded independently of the visible session history. Compaction is a five-turn
  cadence, not an unbounded append and not a production durable checkpoint.
- Refreshing the POC process/browser memory may discard this convenience memory; it is not a
  retention, audit, multi-user or production continuity claim.
- The response animation is presentation only. Server SSE continues to stream real workflow stages,
  not provider output tokens.

## Required evidence

1. The sixth same-session request carries either the completed five-turn summary or the still-bounded
   five recent turns when compaction is pending.
2. Oversized questions, summaries, turn fields and more than five recent turns fail before provider
   execution.
3. Referential follow-ups are resolved and retrieve current DataHub evidence; no memory record is
   returned as evidence.
4. The 12,000-character counter and clamp, answer focusing, user-scroll cancellation, reveal class
   and reduced-motion fallback have component/browser evidence.
