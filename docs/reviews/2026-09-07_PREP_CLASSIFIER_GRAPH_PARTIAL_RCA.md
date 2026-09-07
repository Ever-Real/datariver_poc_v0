# PREP classifier long output and graph lookup: PARTIAL

## Target identity and supplied runtime evidence

- Product: `fa78c716283c10373cfb56387fd8f85b66cdf3d2`.
- Release: `139c7065e683d3f22525abb5b08f63a9c0373b53`.
- OCI manifest: `sha256:68817138979339a93bd047a15e120dc69e25535fa94caf432c6c2012d72cbdbd`.
- The operator reports three identical AUTO classifier failures: request `max_tokens=4096`,
  `reasoning_effort=none`, temperature zero, strict JSON schema; response completion tokens 4096,
  finish LENGTH, approximately 6150 visible bytes, JSON parse failure.
- Both managed graphs have ready/published/active/store/digest evidence: `R1P1A1S1D1`.
- This Mac has no PREP Web container. The existing probe stops at `WEB_IDENTITY`, before provider
  calls. Actual PREP validation is pending; no release, image, database or graph state was changed.

## Classifier findings and bounded next evidence

`frontend/poc-server.mjs:chatRoute` passes `response_format.json_schema` through `llmRequest`
without translating or dropping its fields. This proves the Product request contract, not the
remote server's implementation or enforcement of it. The configured model comes from
`LLM_CHAT_MODEL`; neither the PREP serving software/version nor its full model identity is
available on this host. Structured-output support and the long-output cause remain UNCONFIRMED.

The schema has eight required keys and disallows additional properties. Both concept arrays
have at most eight strings of 1–100 characters; entity hints have at most eight enum entries;
mode, intent and relation intent are enums; selected graph is null or at most 100 characters.
Confidence is a number in [0,1]. Numeric lexical precision and JSON whitespace are not bounded
by these constraints. Repetition, excessive number precision, long strings and visible reasoning
are hypotheses, not established causes. No classifier request, parser or budget correction is made.

The existing `scripts/prep39083-general-classifier-rca-probe` still makes exactly three classifier
calls against the exact running Product and uses the same fixed conceptual question. It appends
`long1`/`long2`/`long3` to its single evidence line:

- Original UTF-8 bytes and Unicode character count; structural first/last and opening token.
- Prefix/suffix of at most 160 characters, with all non-allowlisted text/numbers masked.
- Fence/reasoning-marker flags, repeated-pattern and repeated-route-key indicators.
- Candidate last field, longest number/whitespace/string-token lengths.
- JSON parser error category and position, never the raw error message or offending token.
- Request/response model family and identity SHA-256, never private model aliases or provider URLs.

These are diagnostic indicators and never feed routing or repair output. Analysis of growth is
capped at 100,000 UTF-16 code units and explicitly marked if truncated. Original prefix/suffix and
lengths are retained in bounded/redacted form. Marker absence is not proof that reasoning is absent;
substring growth is not proof of a particular schema field or server grammar behavior.

## Confirmed UI cause and correction

`KnowledgeRegistry` cleared its releases, awaited a single `Promise.all` for releases/detail/
versions, and set only a generic error when any request failed. The preview rendered a missing
focused release as “미발행”, conflating lookup failure and publication absence.

Classification: `UI_FALLBACK_MISCLASSIFICATION`.

The correction keeps the three results independently with `Promise.allSettled`, tracks release
lookup LOADING/READY/ERROR per asset, and displays unavailable on failure. “미발행” requires a
successful lookup with neither a release nor an active pointer. Detail/version failures preserve
the successfully fetched release preview. Selection changes clear the prior release and cannot
request another graph's release. No backend lifecycle or graph integrity logic is changed.

## Connection path: source map, not observed failing endpoint

| Browser path in POC | Handler/read path | Dependency |
|---|---|---|
| `/poc-api/knowledge/graphs/{graph}/releases` | `knowledgeChatApi` → `getK9ManagedGraphAsset` → `knowledgeChatScope` | PostgreSQL; managed canonical release |
| `/poc-api/knowledge/managed-assets/{graph}/detail` | `knowledgeChatApi` → `managedK9Assets` | PostgreSQL; active semantic generation |
| `/poc-api/knowledge/managed-assets/{graph}/versions` | Same managed-asset lookup, version projection | PostgreSQL |
| `/poc-api/knowledge/graphs/{graph}/releases/{release}/snapshot` | `knowledgeChatScope` → `knowledgeVisualizationSnapshot` | PostgreSQL scope, then Neo4j snapshot/integrity |

The frontend's registry detail/versions paths map to the managed-assets HTTP paths in `pocApi.ts`.
`listK9ManagedGraphAssets` uses `pool.query` (implicit transaction; no explicit BEGIN in that
method); `getK9ManagedGraphAsset` calls it. The configured pool has max 4 and a 30-second idle
timeout. These settings alone do not prove a reuse or lifecycle failure.

The request-level server catch returns an untyped Error as HTTP 502 / `POC_PROVIDER_ERROR` with
its message. It does not log that request's stack/cause chain; the pool idle-error listener also
discards the error. Therefore the screen's message alone cannot establish endpoint, exception
origin, connection lifecycle or transaction state. No request/log correlation was available here.
`ConnectionTerminationCause=UNCONFIRMED`; no speculative pool retry or timeout change is made.

## Verification and remaining gate

- Focused Registry/explorer UI: **11 passed**, covering all three lookup failures, successful empty
  lookup, loading, switching assets and existing preview behavior.
- Offline bounded-output/redaction tests: **4 passed**; Bash and embedded Node syntax: PASS.
  ShellCheck is unavailable in this session.
- TypeScript, ESLint, POC production build and static verification: PASS.
- Canonical `test:poc-server`: **260 passed, 19 environment-gated skipped**. This includes local
  classifier/graph-ordering/Chat-persistence regression evidence, not real PREP provider acceptance.
- PREP handoff/artifact/deploy/transport/release-prepare contracts: **189 passed**.
- The source/build/contract portions of release preparation were exercised locally. Full canonical
  release preparation, OCI build/publication and Actual PREP acceptance remain pending the runtime
  causes and corrections. No new Product or Release is declared accepted.

Remaining: PREP long-output line plus serving software/model/version, and one correlated failing
browser request with server/PostgreSQL/Neo4j evidence. Only then can the classifier/backend fix,
new Product/Release decision, and Actual PREP GENERAL/GRAPH/preview acceptance be completed.
