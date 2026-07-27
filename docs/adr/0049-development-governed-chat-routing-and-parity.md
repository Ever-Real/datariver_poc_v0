# ADR-0049: Development governed Chat routing and bounded parity

- Status: Accepted
- Date: 2026-07-26
- Refines: ADR-0011, ADR-0018, ADR-0019, ADR-0023, ADR-0035, ADR-0043, ADR-0048

## Context

The accepted production baseline keeps the durable assistant-inference worker disabled until its
provider, budget, attestation, grounding-verifier and operational gates are complete. The
development product nevertheless needs the existing Chat interaction contract: persisted
owner-scoped conversations, favorites, explicit or automatic retrieval modes, ranked evidence,
workflow status, safe Markdown and authorized catalog detail/lineage navigation.

Earlier local Chat code combined lexical catalog and release-node retrieval and did not expose which
route actually ran. The browser could not distinguish an unavailable graph adapter from a general
fallback. Vector and reranker models were configured and probed but were not application ports used
by Chat. History endpoints also reconstructed citation names from locators rather than persisted
display evidence.

## Decision

### Development-only direct inference

The interactive API may call an environment-selected Chat, Embedding or Reranker adapter only when
`APP_ENV=development`. Model identities, URLs and enablement remain deployment-owned under
ADR-0048. Production keeps the deterministic evidence composer and does not call these direct
adapters even if a private Knowledge provider is configured; production provider execution still
requires the durable ADR-0019 path and its independent gates.

Local Ollama is restricted to the fixed port-11434 origin. The configured `/v1` inventory endpoint
is normalized to the same origin's native `/api/chat` route so Ollama applies the selected
`num_ctx`; the OpenAI-compatible Chat route cannot enforce that option. Chat response bodies are
streamed into a one-MiB bound with redirects and process proxy variables disabled. The local
llama.cpp reranker is restricted to the fixed port-11435 `/v1/rerank` boundary and validates model
identity, result count, unique indices, finite descending scores and bounded response size. Neither
adapter accepts a browser URL, executable tool, SQL, Cypher, file operation or mutation.

Every interactive Chat request reserves both a request count and a conservative input-plus-output
token envelope before retrieval or direct inference. The envelope reserves one token per possible
question UTF-8 byte, a fixed maximum serialized envelope for every allowed evidence item and the
bounded output. The Redis operation is atomic and scoped by workspace, subject and the exact
classification-policy identity. It uses the deployment's no-eviction/AOF delivery Redis rather
than an evictable cache; exhaustion returns a retryable 429 and a Redis failure makes Chat
unavailable instead of bypassing the guard. The reservation is a short-lived protection boundary,
not canonical billing evidence. Durable external-provider accounting remains on the ADR-0019
inference path.

Model reachability is not authorization. The deployment selects separate immutable profile
versions through `CHAT_COMPOSITION_PROVIDER_PROFILE_VERSION_ID`,
`CHAT_EMBEDDING_PROVIDER_PROFILE_VERSION_ID` and
`CHAT_RERANKER_PROVIDER_PROFILE_VERSION_ID`. Before any direct inference, the active governed
classification rule must reference every stage the selected route can invoke. The approved
profile's `server_route_key`, provider, model and deployment identity must exactly match the
effective environment-derived runtime binding, not only its UUID. Only classifications satisfying
the complete stage set may enter retrieval or a prompt. Static-floor, missing, revoked or
mismatched bindings are explicit unavailable/refused states and never select the deterministic
composer as a silent substitute.

### Typed routing without silent fallback

`AUTO`, `GENERAL`, `VECTOR` and `GRAPH` are typed application modes. The deterministic router records
requested mode, selected mode, reason and adapter state.

- `GENERAL` searches the authorization-pruned catalog projection.
- `VECTOR` embeds one question and at most 20 authorization-pruned catalog candidates, validates
  the exact deployment binding and vector shape, then ranks by finite cosine similarity.
- `GRAPH` is an application port only. The interactive runtime does not supply an asset-graph
  adapter in this scope. An explicit or inferred graph route therefore returns `UNAVAILABLE`; it
  never changes itself to general or vector retrieval.

Retrieval, embedding, reranking or composition failure records `FAILED` and produces the existing
`검증 불가` result with no citations. Reranker output may select a bounded subset but cannot add or
forge evidence IDs. The composer receives only already authorized evidence, and its cited IDs are
first reauthorized after composition. The service re-resolves the classification policy and
authorization generation, requires the complete security identity to remain unchanged, and re-runs
resource ABAC for every citation before it revalidates workspace, integrity, uniqueness and
membership. Any dependency error or revocation produces `검증 불가` with zero citations.

### History, presentation and evidence

Chat sessions remain workspace/owner scoped and bound to the exact active retention policy.
Favorites use an optimistic session version and a column-limited database grant. Persisted
citations store their original display name and description; legacy citations lacking those values
are omitted rather than reconstructed from an opaque locator. Assistant-run metrics retain the
actual provider/model, provider-profile UUID, classification policy ID/hash/version/generation,
route, workflow and ranking audit without secrets. Forced workspace RLS is supplemented by
restrictive application-role owner policies on all four assistant tables.

The browser displays only server-returned route/workflow state. It retrieves at most 50 sessions and
200 messages, supports Enter submission with Shift+Enter multiline input, and provides explicit
copy/favorite feedback. Assistant Markdown is rendered as bounded React text and tables: raw HTML,
answer-provided links and untrusted components are never activated. Ranked catalog evidence opens
the existing authorized detail and lineage surface using an opaque internal asset ID.

## Consequences

- Development can exercise the selected installed Chat, Embedding and Reranker models through the
  real governed Chat path without committing a model choice.
- The user can see an unavailable graph capability instead of receiving a misleading fallback.
- External dependency failure cannot produce uncited prose or reuse a different model/strategy.
- PostgreSQL remains canonical for conversation, retention and citation audit; embeddings and
  reranking are request-time projections.
- The future asset-graph task must implement and verify a bounded graph reader before changing
  `GRAPH` from `UNAVAILABLE`.
- This ADR does not approve production direct inference, streaming, token settlement, public
  providers, graph mutation or LLM-generated query execution.

## Required acceptance evidence

1. route tests cover explicit selection, automatic intent and unavailable adapters;
2. vector tests prove the candidate window, binding, index and dimension checks;
3. Chat and reranker transports enforce destination and response bounds;
4. failed adapters produce `검증 불가` with no silently substituted strategy or citation;
5. owner authorization, optimistic favorites and migration grants have positive and negative tests;
6. frontend tests cover Enter/Shift+Enter, copy feedback, safe Markdown/table rendering, server
   workflow, ranked evidence and authorized detail navigation;
7. target development probes record the selected installed model identities and observed embedding
   dimension without treating that dimension as a source constant.
