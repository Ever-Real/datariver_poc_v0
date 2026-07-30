# GX Quality Phase 0 architecture review

- Date: 2026-07-30
- Scope: Task 1 Phase 0 contract, ADR, target model, security and later acceptance gates
- Source baseline: branch `dev`, commit `21f3db1`, Alembic head `0066`
- Change class: documentation and architecture decision only
- Decision: accepted for Phase 0; Phase 1 requires a new user approval

The primary architect integrated four independent read-only reviews. Review findings are evidence
for the decision, not implementation or target-environment acceptance.

## Data Engineer review

### Findings

- DataHub Profile observations, the rebuildable PostgreSQL profile projection and GX Validation
  outcomes require separate canonical ownership and timestamps.
- The existing asset query filters both FULL and SAMPLE profiles with `limit: 1` but does not
  request `partitionSpec`; it cannot prove the returned population.
- `infra/datahub/recipes/semiconductor_postgres.yml` combines
  `profile_table_level_only: true` and `include_field_null_count: true`. The pinned DataHub v1.6
  validator rejects that combination.
- Enabling field profiling without explicit flags would inherit sample-value collection and a
  worker default tied to host CPU. Neither is an approved privacy or capacity decision.
- DataHub's PostgreSQL profiler does not provide a sufficient portable row/size/sampling workload
  gate. Source scope, full-scan budget, timeout and concurrency need deployment approval.
- Airflow dispatch must be replay-safe, while PostgreSQL owns scheduled due/missed-window
  reconciliation.

### Disposition

- ADR-0077 requires a separate fixed profile query with profile kind/provenance and forbids
  SAMPLE/ambiguous evidence from becoming FULL.
- The Quality PRD marks the current recipe as non-evidence and requires explicit disabling of
  sample/distribution metrics plus bounded workers/field scope before target execution.
- V1 GX validation is PostgreSQL full-table only. Missing workload approval is unavailable, not an
  implicit sample.
- Due-window/catch-up state remains canonical in PostgreSQL; Airflow is OIDC dispatch only.

## Backend/DBA review

### Findings

- No `quality` managed schema, Quality Action, GX dependency or source connection resolver exists.
- Current outbox, idempotency, DB-clock lease/epoch/token-hash and worker-call receipt patterns are
  suitable, but a Quality context must not write Catalog or Integration tables directly.
- Execution state and quality outcome must be different columns/contracts.
- Immutable versions/results/events, forced RLS, composite tenant FKs, NOBYPASSRLS worker and
  destructive-downgrade refusal are required.
- Connection endpoints, schedule, timeout/concurrency, score threshold and retention are operating
  data, not portable defaults.

### Disposition

- `docs/06_DATA_MODEL.md` now contains an explicitly unimplemented Quality target model with Rule
  Set/Version/Definition/Review, Run/Attempt/Result/Event/Call Receipt and Catalog Profile tables.
- ADR-0077 fixes canonical ownership and completion fencing.
- Phase 1 requires then-current-head migration, SQLAlchemy/canonical `0001` equivalence,
  PostgreSQL 17 RLS/grant/drift tests and exact dependency supply-chain gates.

## Frontend UI/UX review

### Findings

- The current Quality route is an honest unavailable page; it has no security-bound API client
  inputs or Quality contract.
- Quality needs `현황 / 룰 관리 / 실행 이력 / 품질 이슈`, server-owned scoring, cursor lists,
  explicit partial/stale/unknown states and bounded active-run polling.
- Global React Query freshness is unsuitable for a running validation. Workspace/Subject/security
  epoch/authorization/cache scope must fence requests and memory cache.
- Charts need an equivalent accessible table; status cannot rely on color.

### Disposition

- The Quality PRD defines stable UI requirement IDs, four routes/tabs, server aggregation,
  permission-scoped labels, accessibility and cache/cursor scope.
- V1 polls only the selected active Run with `1/2/5/10` second backoff and a 20-read/120-second
  bound. Poll expiry does not claim completion.
- Dashboard-wide polling, SSE, browser-side raw aggregation, browser storage and a new chart
  dependency are outside Phase 0.

## Security/Governance review

### Findings

- GX/source execution, field profiles and dashboard counts are new data-access surfaces.
- Reusing `admin.manage` or `catalog.sync` would combine incompatible human and service powers.
- Arbitrary GX/SQL/Python/URL/identifier input, regex backtracking, source over-scan, confused-deputy
  service calls and raw GX results are material threats.
- Sample/top/distinct values and even distributions can disclose protected business/personal data.
- Retention duration, Airflow cleanup, TTL or object lifecycle cannot authorize deletion.

### Disposition

- ADR-0077 defines separate human Actions, service-only dispatch/execute Actions,
  maker-checker/WebAuthn activation and deny-first revocation.
- Public contracts exclude provider identifiers, GX configs, queries, code, URLs and credentials.
- Profile and result allowlists prohibit sample/top/distinct values, unexpected rows/values/indexes,
  generated SQL and exception text. Sanitizer failure is fail-closed.
- All aggregates begin from the authorization-pruned asset relation; no global/hidden count delta
  is returned.
- Quality physical cleanup remains absent until approved retention kinds and Legal Hold coverage
  are implemented and verified.

## Draft-close review and corrective decisions

The four roles reviewed the assembled controlled-document set again. The first close review was
not treated as automatic approval: findings were corrected and the affected reviewers re-read the
latest files until no P0/P1/P2 blocker remained.

### Data engineering closure

- The pinned DataHub v1.6 `DatasetProfile` schema has no `profileType`. The fixed query therefore
  requests only valid fields, including `partitionSpec { type partition }`, and the parser has an
  exact FULL/SAMPLE/PARTITION/QUERY/UNKNOWN mapping.
- Raw partition text exists only at bounded fixed-parser ingress. PARTITION/QUERY idempotency may
  retain only a deployment-keyed HMAC/key ID; deterministic snapshot identity and repeated
  `last_observed_at` behavior are explicit.
- Versioned schedules now pin cadence/DST/evaluator/tzdb contracts. Closed
  SKIP/LATEST_ONLY/OLDEST_FIRST missed-window semantics, DB-time cutoff, cursor order, dispatch caps
  and canonical UTC window replay remove outage ambiguity.
- The full GX source-access window, not one SQL statement, fits inside the frozen lease and rechecks
  its epoch before every source statement.

### Backend/DBA closure

- RuleSet, Run, ProfileSnapshot and run-independent no-work dispatch receipts have exact retention
  roots; child evidence inherits policy/deadline/Legal Hold bindings through composite FKs.
- Rule Set Version-specific schedule history, one-ACTIVE partial constraints, scheduled-window
  uniqueness, no-work/multi-run dispatch receipts and bounded global dispatch contracts are fixed.
- Run/Attempt pairing, successor-Run retry, source-access deadline, expired-claim supersession and
  current ACTIVE-Version-only dashboard selection are closed state/index contracts.
- Phase 1 Quality and Phase 2 Catalog Profile migrations are additive and separate. Evidence-bearing
  destructive downgrade is refused.

### Frontend closure

- The current snapshot selects the latest terminal Run for the current ACTIVE Version, so neither
  an older success nor a superseded Version can mask a current UNKNOWN.
- Rule Set and Rule Definition aggregation grains, integer basis-point rounding, section-specific
  dependency availability, 30-second authorization lease, endpoint status/precondition contracts,
  bounded polling, URL/query-key fences and accessibility behaviors are explicit.
- A non-empty Version and exactly one sanitized result per Rule make `SUCCEEDED + UNKNOWN`
  impossible; aggregate UNKNOWN remains honest when there is no contributing success.

### Security/Governance closure

- Archive/cancel and service/collector Actions, route mapping, maker-checker/WebAuthn commands and
  DataHub/source credential separation are complete.
- Mid-run authorization/source/workload/retention drift produces STALE/UNKNOWN and no canonical
  result. Numeric sanitizer negatives, small-cell/cohort suppression and permission-scoped counts
  are mandatory tests.
- Archive remains a reversible logical visibility transition after revoke and never deletes
  evidence. Physical cleanup remains absent.

**Final role verdict:** Data Engineer, Backend/DBA, Frontend UI/UX and Security/Governance approved
the Phase 0 contract with no remaining P0, P1 or P2 blocker. This verdict approves design
traceability only; it does not claim implementation or target-environment acceptance.

## Accepted Phase 0 decisions

- New Quality bounded context with PostgreSQL canonical Rule/Run/result evidence.
- DataHub remains canonical for Profile observations; Catalog owns a rebuildable bounded projection.
- Separate GX quality worker; Airflow schedules/dispatches only.
- Exact GX target `1.19.1`, quality-worker-only dependency, PostgreSQL/full-table first.
- No MinIO/filefolder Data Docs or raw validation results.
- V1 Rule kinds `NOT_NULL`, typed `RANGE`, safety-gated `REGEX`.
- Rule-set-version activation, independent human reviewer and hardware WebAuthn.
- `UNWEIGHTED_RULE_PASS_RATE_V1`, separate Run state and Quality outcome.
- Sample/top/distribution privacy controls and sanitized normalized result storage.
- No physical delete, TTL or partition cleanup.

## Open activation evidence, not open architecture

The architecture is accepted, but the following deployment values/evidence remain fail-closed gates:

- exact source manifest, read-only principal, mounted secret owner and egress allowlist;
- approved full-scan/timeout/pool/concurrency/cost envelope and schedule/timezone/catch-up cap;
- Profile freshness and DataHub field-scope/history budgets;
- Quality retention duration/residency/Legal Hold policy binding;
- exact frozen GX/driver lock, transitive license/SBOM/vulnerability and arm64/amd64 artifacts;
- corrected DataHub v1.6 recipe plus real run/GraphQL contract evidence;
- actual PostgreSQL RLS, source read-only, Airflow OIDC, worker crash/reclaim and load evidence.

Missing evidence produces `UNAVAILABLE` or `DISABLED_NOT_READY`; it is not replaced by a source
default or local unit-test claim.

## Phase 0 verification

- `git diff --check`
- `.venv/bin/python scripts/verify_static.py`

Both checks passed after the Phase 0 document set was assembled. No backend/frontend test,
migration, provider call or runtime deployment was represented as executed by this review.
