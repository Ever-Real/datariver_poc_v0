# Final DEV UI/runtime acceptance correction evidence

This bundle records the bounded correction from Product
`a09cd4cb47db7bb31f608dfd94c61f34844d33af`, Evidence
`07d6344ab287fa83c4611c780d3c8a23f8ffb878` and Handoff
`48b9dd7eee42a7d3bec413396c2fc6026a06d314`.

The corrected Product is `0be3551e95755cc7ffb4733ab4a90fd9610b81a3`. Its exact linux/amd64 OCI
was running healthy on DEV port 39083 and returned HTTP 200. Dashboard 39090 returned HTTP 200.
Port 39080 was down before this work and remains down; it was not mutated. PREP and OPS were not
executed.

## Change History current DEV state

The append-only canonical ledger contains **100** events: **28** technical-schema rows and **72**
metadata rows. The prior 73 historical events and the earlier 20-event live E2E remain intact. The
retained demonstration fixture added seven real events by this canonical path:

`quant_db source DDL -> official DataHub 1.6 stateful ingestion -> DataHub MCL -> bounded DataRiver
capture -> canonical ledger`.

The intentionally retained DEV-only fixture is:

- source schema `datariver_change_e2e`;
- source Table `datariver_change_e2e_table_a`;
- canonical DataHub Dataset
  `urn:li:dataset:(urn:li:dataPlatform:postgres,datariver-change-e2e-dev.quant_db.datariver_change_e2e.datariver_change_e2e_table_a,DEV)`;
- existing active System `checkpoint-postgres-system`;
- one active exact Table-to-System binding, assigned through the governed ETag/CAS API;
- source identity `9f26d351b6009dce2510e4d0f190e0295c0c06ff0a7db6840c30a0da3dc4caaa`;
- MCL partition 0 advanced from offset 71826 to 72675, processing 849 source records and appending
  seven normalized ledger events.

The normal DEV admin role was evaluated through the production Change Management API before the
disposable credential was disabled. The exact final read returned **11 authorized Schema Change
rows** and **14 authorized Metadata Change rows**; every returned event had `RESOLVED` System
authority. This is ordinary policy evaluation against the retained exact binding, not an admin
fallback. No fake ledger insert, direct mapping insert, policy widening, schema-scope authority or
PREP/OPS auto-seed was introduced.

The API and page now distinguish:

- `NO_LEDGER_EVENTS`;
- `EVENTS_EXIST_BUT_NOT_AUTHORIZED`, with `NO_EXACT_MAPPING` or `AUTHORIZATION_SCOPE` detail;
- `FILTER_DATE_RANGE_EMPTY`.

A future-date production API query returned `FILTER_DATE_RANGE_EMPTY`; populated responses do not
carry an empty-state reason.

## Resource Tree canonical hierarchy

The current DataHub inventory was refreshed at the root boundary. Empty hierarchy values no longer
become visible Database nodes, and `catalogDatabaseBranchLabel` no longer fabricates a display
label. Soft-deleted/non-current Datasets are removed by the existing current-entity predicate.

Three current DEV assets had genuinely incomplete Database hierarchy metadata at audit time. Two
had explicit `status.removed=false`; the third had no status aspect but remained a current inventory
entity. All three had no container/browse-path Database authority. They remain searchable but do not
create fake hierarchy branches.

After the retained fixture ingestion and full root refresh:

- labels containing `Database 메타데이터 없음` or an equivalent missing-Database branch: **0**;
- stale deleted schema/Table branches: **0**;
- the real `quant_db / datariver_change_e2e / datariver_change_e2e_table_a` hierarchy resolves from
  canonical DataHub metadata.

## Chat durable history

A real production-path test used disposable local users A and B against exact DEV 39083:

1. A submitted a GENERAL question and received the canonical final result.
2. `/chat/sessions` immediately returned the new session.
3. `/chat/sessions/{id}/messages` returned the immutable user and assistant turns.
4. Client recreation and A logout/re-login preserved the session and messages.
5. B's session list did not contain A's session.
6. The web container was restarted while retaining the same PostgreSQL container and
   `datariver-poc_pgvector-data` volume; A's history remained present afterward.

The implementation uses subject-owned PostgreSQL `poc_chat_sessions` and `poc_chat_messages` with
composite ownership fencing. It does not use localStorage as the state authority. Four protected
history routes share the existing authorization registry.

Cancellation was also exercised against an actual stream after its first `answer_delta`: the
submitted user question remained in the transient UI contract, but no partial assistant result and
no new durable session were persisted.

## Chat SSE, viewport and evidence surface

`/chat/query/stream` now emits bounded server-approved `answer_delta` events after final
grounding/citation authorization and before the canonical persisted `result`. It never exposes raw
provider tokens, prompts, thoughts, graph queries, credentials or unauthorized evidence. The final
`result` remains the persistence and audit truth.

Runtime production-path observations:

- long GENERAL answer: 13 network `answer_delta` events, 1,981 characters, then `PERSISTED` result;
- VECTOR representative: four deltas and one authorized managed-asset evidence item;
- GRAPH representative: seven deltas and the bounded authorized graph projection (20 node evidence
  items and 28 relation evidence items).

The client timer that sliced an already-complete answer was removed. Auto-follow tests now deliver
multiple real delta events and prove: follow on new deltas, immediate stop on user scroll-up, no
forced return while away from the bottom, resume at bottom, and reset for a new question.

The manual Evidence panel width/collapse state, button, layout class and CSS were removed from source
and the built Product asset. The independent `인가된 인용 근거` content disclosure remains.

The exact built production CSS contains this user-footer rule:

```css
article.message-user>footer.chat-message-actions-user{box-shadow:none;background:0 0;border:0;justify-content:flex-end;gap:2px;margin-top:1px;padding-top:0}
```

It is scoped to the user-message footer; global Footer and Button styles were not changed.

## Verification gates

- Focused Chat/Resource Tree/Change History UI: **5 files / 99 tests PASS**.
- Final UI suite: **90 files / 662 tests PASS**.
- Node Product server suite: **131/131 PASS**.
- PREP deploy/handoff/proxy contract: **41/41 PASS**.
- PREP smoke contract: **3/3 PASS**.
- Isolated Docker state-machine and non-destructive recovery: **1/1 PASS**.
- Isolated forced-smoke-failure then same-command retry without duplicate bootstrap: **1/1 PASS**.
- ESLint, TypeScript, standard build, POC build, Ruff lint, strict mypy over 587 files, static
  verification and `git diff --check`: PASS.
- Compose resolved to four services, exact Product image, linux/amd64 and port 39083.
- Delta secret scan and final-image proxy env/label/history leak scan: PASS.
- Representative GENERAL, VECTOR and GRAPH runtime routes: PASS. Router/retrieval/reranking semantics
  did not change, so the accepted 60+8 suite was not repeated.

## Cleanup

- Four disposable Chat sessions were archived.
- Both disposable credentials were disabled.
- Their two active sessions were revoked; final active test sessions and enabled test credentials
  are both zero.
- Re-login for both disposable accounts returns HTTP 401.
- Temporary passwords, login payloads, cookies, streams, runtime env and verification files were
  removed.
- No MCL capture or ingestion verifier remained running.
- The one DEV demonstration source fixture, DataHub Dataset, ledger history and exact binding are
  intentionally retained as accepted current DEV Product state.

## Browser acceptance limitation

The required in-app Browser open and documented troubleshooting sequence found no available browser
instance (`agent.browsers.list()` returned an empty list). Per the Browser contract, no alternate
browser backend was substituted. Runtime APIs, built production assets and component behavior are
verified, but actual pointer/visual acceptance is still
`FINAL_BROWSER_ACCEPTANCE_SURFACE_UNAVAILABLE`.

Therefore this closeout is truthful `PARTIAL_BROWSER_ACCEPTANCE_BLOCKED`, not
`COMPLETE_RUNTIME_VERIFIED`.
