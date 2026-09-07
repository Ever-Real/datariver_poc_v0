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

Remaining: the compact PREP A/B result and one correlated failing
browser request with server/PostgreSQL/Neo4j evidence. Only then can the classifier/backend fix,
new Product/Release decision, and Actual PREP GENERAL/GRAPH/preview acceptance be completed.

## Follow-up: operator-reported repetition and bounded A/B

The next supplied PREP result reports the same GEMMA model identity hash on all three calls,
4096 completion tokens, LENGTH, 6150 visible bytes, EXPECTED_DELIMITER and repeated-pattern=true.
Both excerpts begin/end around `{"mode":"GENERAL"`. The remaining classifier hypotheses are
provider/model structured-output failure versus current schema/prompt interaction. Neither is
declared proven by the repetition alone.

Run the existing probe with `--ab` from the separate PREP diagnostic checkout. It captures the
running Product's exact B request before transport, then sends exactly two direct completions:
A has only the mode enum and a short classification prompt; B retains the captured schema,
messages and authorized capability context byte for byte. Both retain model, 4096 budget,
temperature zero, non-streaming output and both reasoning-disable controls. No retry is automatic.
The default three-call probe is not run in this mode, and the Neo4j audit is skipped.

The output uses the requested A/B classification matrix. Transport/authentication/timeout failures
are INCONCLUSIVE_PROVIDER_FAILURE; A-fail/B-pass is INCONCLUSIVE_A_FAIL_B_PASS. A's PASS concerns
schema/STOP, with semantic outcome separately reported; B also requires the existing Product parser
and the expected GENERAL result. Diagnostic schema validation does not change Product validation.

At most two metadata GETs use the same configured provider origin/prefix and transport, each with
a 10-second deadline and 128-KiB response ceiling. The documented Ollama
[`/api/version`](https://docs.ollama.com/api-reference/get-version) and
[`/api/tags`](https://docs.ollama.com/api/tags) expose a version and selected model digest.
Matching responses are labeled OLLAMA_API, not proof of a particular backend binary behind a
compatible gateway. Other providers remain UNKNOWN; no discovery sweep is performed. Output
contains only the selected model identifier/digest and bounded/redacted completion evidence.

Local verification: **10 diagnostic tests passed**, including actual Product request extraction,
zero network calls during capture, identical controls, B preservation, exactly two completions,
metadata bounds, secret redaction and inconclusive transport failure. Bash and embedded/temporary
Node module syntax pass. This is not an Actual PREP A/B result.

The existing Chrome PREP tab at `100.84.101.79:39083` shows ERR_CONNECTION_TIMED_OUT, and the
current bounded connection check also timed out before any HTTP response. No remote Orca host is
connected. The graph selection request has therefore not been reproduced, and no Web log was
available to correlate. This reachability failure does not establish the earlier graph connection
error's cause. No Product, Release, deployment, graph pointer, DB or Neo4j state is changed.

## Follow-up: stale execution fence and compact output

The operator-reported `run1/run2/run3` output cannot be the `f283bd62` AB branch. It does not
identify the operator's actual checkout, script bytes or received mode, so the exact stale path
remains unobserved. The Mac diagnostic HEAD and live origin/dev both matched `f283bd62` before
this correction. No further three-call repetition was requested or performed.

The existing probe now requires explicit `--ab` or `--auto-3`. Before Docker or provider access it
requires diagnostic HEAD, cached origin/dev and live origin/dev to match, and compares the actual
executing script blob with that commit's blob. A mismatch returns `RCA|status=STALE_DIAGNOSTIC`.
An argv/environment mode-and-commit handshake runs before persistence reads; mode is immutable
after that check. Successful AB output must carry the same diagnostic identity, `mode=AB` and
`completion_calls=2`; old default-mode output is rejected.

Old copies cannot acquire this guard themselves. Run the following from the PREP repository;
it fetches origin/dev, verifies the new contract marker before invoking anything, and uses a fresh
detached diagnostic worktree. The caller's HEAD and files, including a Release checkout, are
unchanged. The script independently rechecks the live ref and its own bytes before provider calls.

<!-- PREP39083_RCA_AB_LAUNCHER -->
```bash
git fetch -q origin refs/heads/dev:refs/remotes/origin/dev && (git grep -qF PREP39083_RCA_AB_IDENTITY_V2 origin/dev -- scripts/prep39083-general-classifier-rca-probe || { printf 'RCA|status=STALE_DIAGNOSTIC\n'; exit 2; }) && prep_rca_dir="$(mktemp -d /tmp/datariver-rca.XXXXXX)" && git worktree add -q --detach "$prep_rca_dir" origin/dev && "$prep_rca_dir/scripts/prep39083-general-classifier-rca-probe" --ab
```

Stdout contains one `RCA_AB` summary with diagnostic SHA, mode, call count, A/B statuses,
classification, provider API/version, model family and finish reasons. Detailed redacted evidence
and checkout/ref/blob provenance are saved in a private temporary directory (0700), file 0600;
only its path is printed. Do not request the file contents, full hashes or long evidence line from
the operator. The separate graph request is limited to
`GRAPH_UI|path=...|http=...|time=HH:MM:SS|message=Connection terminated unexpectedly`.

Offline tests verify stale/dirty identity rejection before Docker, the detached launch preserving
the caller checkout, rejection of pre-guard copies, the mode handshake, two completion calls,
compact output and private evidence. Runtime A/B, the failing graph endpoint and actual acceptance
remain pending access to PREP; this diagnostic correction is not a classifier/backend cause claim.

Verification: **13 diagnostic tests passed**; Bash, embedded/temporary Node syntax and static
verification passed. ShellCheck is unavailable. No Product source changed in this follow-up, so
Product TypeScript/ESLint/canonical release gates were not rerun or claimed as Actual PREP evidence.

## Follow-up: Actual PREP A/B result and two cross-tests

Operator-supplied Actual PREP evidence from `45c3d44a`: A=PASS/STOP, B=FAIL/LENGTH,
`CLASSIFIER_SCHEMA_OR_PROMPT_INTERACTION`, provider=UNKNOWN, model=GEMMA. This establishes that
the minimal request succeeds on the selected runtime. Generic structured-output incompatibility
and a simple completion-ceiling explanation are therefore not the working causes. It does not yet
separate the full schema from the full messages/capability context.

The same probe's `--cd` mode captures B from the running Product before network transport, then
makes exactly two completions without retries or metadata reads. C replaces only B's messages
with A's exact short messages; D replaces only B's schema with A's exact minimal schema. All other
request fields, provider, model, temperature=0, 4096 budget and reasoning/strict controls remain
identical. Neither A/B nor the three-call probe is rerun.

C/D PASS means STOP with valid JSON meeting the requested strict schema. The existing Product
semantic parser is still called for C and its result is recorded independently in the private file;
a semantic error is not mislabeled as the observed generation-length failure. D records its GENERAL
decision check separately. These cross-tests are not Product semantic acceptance. No Product
parser, schema, prompt or safety behavior has changed.

Classification: C-fail/D-pass → CLASSIFIER_SCHEMA_CAUSE; C-pass/D-fail →
CLASSIFIER_PROMPT_CONTEXT_CAUSE; both pass → CLASSIFIER_SCHEMA_PROMPT_INTERACTION; both fail →
MULTIPLE_CLASSIFIER_TRIGGERS. A transport/auth/timeout failure stays
INCONCLUSIVE_PROVIDER_FAILURE, with UNAVAILABLE for the affected call.

<!-- PREP39083_RCA_CD_LAUNCHER -->
```bash
git fetch -q origin refs/heads/dev:refs/remotes/origin/dev && (git grep -qF PREP39083_RCA_CD_IDENTITY_V1 origin/dev -- scripts/prep39083-general-classifier-rca-probe || { printf 'RCA|status=STALE_DIAGNOSTIC\n'; exit 2; }) && prep_rca_dir="$(mktemp -d /tmp/datariver-rca.XXXXXX)" && git worktree add -q --detach "$prep_rca_dir" origin/dev && "$prep_rca_dir/scripts/prep39083-general-classifier-rca-probe" --cd
```

The existing identity fence validates diagnostic HEAD, remote dev, executing blob and received
mode before access. Stdout is only `RCA_CD|C=...|D=...|class=...|C_finish=...|D_finish=...`.
Redacted details and identity/call-count evidence remain in the existing private temporary file.
The operator is not asked to transfer that file. Actual C/D outcomes remain pending; only after
the observed result can a minimal Product correction and 3/3 JSON/schema/semantic acceptance
precede the Product gates and release decision.

Local verification: **15 diagnostic tests passed**, including both fresh-checkout launchers,
immutable mode dispatch, zero-call capture, the exact crossed requests, two completions with no
metadata reads in CD, outcome mapping and private/compact output. Bash, embedded/temporary Node
syntax and static verification pass. No Actual PREP C/D result or Product gate is claimed here.

## Classifier RCA closed: prompt/context correction

The operator supplied Actual PREP C=PASS/STOP and D=PASS/STOP. Together with A=PASS/STOP and
B=FAIL/LENGTH, the accepted root cause is **CLASSIFIER_SCHEMA_PROMPT_INTERACTION** on the same
GEMMA runtime. The full schema works with the short prompt; the full prompt works with the minimal
schema. This is not classified as generic provider failure, schema-only failure, prompt-only
failure or insufficient completion budget. No further diagnostic modes or cross-tests are added.

The Product correction changes only classifier messages:

- The system instruction shrinks from **1,499 to 819 characters**, retaining route boundaries,
  inventory/exact/discovery distinctions, literal Unicode search terms, authorized graph selection
  and the untrusted-data boundary. Repeated output-format directions and schema-field explanations
  are removed; no example response is included.
- The user message is one JSON object containing the question and compact graph capability rows.
  Each row retains the exact authorized ID, name, type, intents, capabilities and entity types from
  the two fixed managed K9 definitions. The redundant READY status and prose wrapper are omitted.
  No graph capability is truncated, synthesized or added, and source definitions remain bounded.
- The full strict schema, parser, semantic validation, graph eligibility lookup, 4096 budget,
  model, transport, timeout and reasoning controls are unchanged. Existing SQL NULL persistence,
  order-independent graph integrity and lookup-error-versus-unpublished UI corrections remain.

Focused classifier/provider/semantic/fail-closed regressions: **110 passed**. Existing diagnostic
offline tests: **15 passed**; no remote provider calls were made by either test set. A direct source
comparison confirms the schema/controls, parser and graph eligibility lookup are unchanged.
Full source/release gates and Actual PREP revised-request 3/3 acceptance are recorded separately;
this correction is not an Actual PREP runtime PASS claim. The graph connection cause still awaits
the single bounded GRAPH_UI endpoint/status/time result.

Correction verification:

- TypeScript, ESLint and static: PASS. Registry/explorer regression: 11 PASS.
- Canonical POC Node regression: 260 PASS, 19 environment-gated skips.
- Canonical PREP handoff/artifact/deploy/transport/release-prepare contracts: 189 PASS.
- Ruff and strict mypy (605 files): PASS.
- Additional repository-wide `development_cycle.py verify`: NOT PASS; backend result is
  4,215 PASS, 126 skips, 17 failures. All 17 failures reproduce in an unmodified `227c3e9f`
  archive: historical migration assertions (4), development-host secret/preflight fixtures (11),
  environment-template keys (1), and the pilot deploy contract (1). These are not waived or
  repaired by this prompt-only change. The formal PREP release command runs its own defined
  canonical gates in an isolated Product checkout; its result is reported separately.

Actual PREP remains unreachable from this Mac. Product source tests and the forthcoming exact
artifact do not establish revised classifier 3/3, GENERAL smoke, preview or GRAPH Chat acceptance.
