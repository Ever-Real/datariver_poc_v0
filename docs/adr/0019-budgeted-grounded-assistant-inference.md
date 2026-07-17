# ADR-0019: Budgeted and independently grounded assistant inference

- Status: Accepted
- Date: 2026-07-17
- Refines: ADR-0011, ADR-0013

## Decision

Version the disabled-first assistant inference contract independently from Chat persistence. Every
inference package binds the exact requested and selected provider profiles, provider/model/deployment
identity, region and jurisdiction, classification ceiling, current residency and zero-retention
attestations, authorization policy, monthly token-accounting decision and immutable authorized
evidence. Provider connection data, secrets and executable tools remain outside the package.

Internal inference uses `MONITOR_ONLY` token accounting. External inference requires a durable
workspace-and-user `HARD_LIMIT` reservation covering the estimated prompt and completion budget;
reported input plus output usage above that envelope is rejected.
When that reservation is denied because a limit is exceeded, routing may preselect an explicitly
approved internal provider. The fallback must satisfy the same workspace, effective classification,
jurisdiction, residency and zero-retention eligibility predicates. The route retains two decisions:
the external hard-limit denial and a separate internal monitor-only observation. The worker still
executes exactly one selected route; provider exceptions never trigger an implicit retry, route
downgrade or newly chosen fallback.

Provider citations alone are insufficient. Authorized inference evidence must expose a canonical
URN. After model output, a separate server-side grounding verifier binds the normalized answer hash,
package and route IDs, exact cited chunk order and an evidence-bundle hash over source URN, source
version and content hash. Metric, non-zero threshold and evaluator identity come from an immutable
workspace grounding-policy snapshot; the verifier supplies only its measured score and matching
policy evidence. The provider cannot submit its own grounding verdict. A missing verifier,
mismatched evidence or a score below the governed threshold returns
`보안 규정 및 근거 데이터 부족으로 답변할 수 없습니다` with no citation.

If a model call produced a structurally valid draft, token and latency observations survive later
budget-envelope, grounding-unavailable, grounding-invalid and insufficient-grounding refusal. If a
provider call fails without usable metrics, usage is explicitly `UNAVAILABLE`; a future ledger must
settle the reservation conservatively rather than treating missing metrics as zero usage.

TTFT, output tokens and duration remain bounded result measurements, and token generation rate is
derived from them. A separate pure evaluator calculates nearest-rank TTFT p95, mean token rate and
benchmark accuracy against deployment-supplied targets. Every report retains a pinned dataset
revision/hash and evaluator/scoring-policy version/hash. Its result is benchmark evidence only; it
does not establish production SLA compliance or substitute for independently timed streaming
telemetry.

## Rationale

Selecting a fallback inside exception handling would make the route unauditable and could bypass a
revoked profile, a classification ceiling or a residency decision. Reserving budget before route
selection makes external limits race-safe once backed by a canonical ledger, while monitor-only
accounting does not accidentally disable an internal service. Separating provider generation from
grounding prevents a model from declaring its own answer trustworthy.

Canonical URNs, source versions and content hashes make a citation reproducible across catalog and
knowledge-graph evidence. An explicit score and threshold revision also distinguishes a measured
grounding gate from prompt wording or the mere presence of a citation.

## Consequences

- The current adapter and grounding verifier remain disabled. This ADR adds no endpoint, credential,
  provider SDK, egress, worker deployment, API dispatch or model call.
- Runtime enablement requires an atomic monthly reserve/settle ledger with idempotency and RLS,
  pre-call and post-call policy/profile revalidation, a durable job/result protocol, an isolated
  worker role and a server-owned route registry.
- Exact provider/model/deployment identity, endpoint and TLS trust, secret reference, egress
  allowlist, context/output limits, concurrency and timeout values are deployment approvals and have
  no source default.
- External routes additionally require approved destination-region evidence and current residency
  and zero-retention attestations. A provider or region label alone is not evidence.
- A governed threshold policy, embedding/evaluator identity and pinned benchmark dataset are required
  before grounding or accuracy can be claimed. Runtime TTFT requires independently timed streaming;
  a provider-reported scalar is not sufficient.
- Prometheus/OTel metrics, token ledger persistence, SSE cancellation, red-team evaluation and Admin
  budget mutation remain delivery work. Until those gates pass, deterministic evidence Chat is the
  only active Chat composer.
