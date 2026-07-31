# Phase 8 Quality authoring and execution-readiness record

- Date: 2026-07-31
- Scope: V2 authoring directory, bounded Rule proposal, review/activation, manual Run request,
  search-integrated Quality evidence, reusable common Rules, an asset-centric Quality workspace
  and a schema-level Quality dashboard
- Decisions: [ADR-0079](adr/0079-quality-authoring-readiness-and-manual-run-commands.md),
  [ADR-0081](adr/0081-user-centric-quality-workspace-and-common-rule-templates.md),
  [ADR-0084](adr/0084-rule-weighted-asset-quality-score.md),
  [ADR-0088](adr/0088-schema-quality-dashboard-and-managed-indicators.md)

## Implemented boundary

The server now derives field identities and types from a deployment-owned V2 manifest, then
reconciles them with the current authorization-pruned Catalog asset before accepting a Rule. A
multi-asset proposal is one atomic command bounded to 25 unique targets. Review and activation use
the existing maker-checker and WebAuthn controls; manual execution creates Run, event and outbox
evidence in one database function. The API never accepts source coordinates, GX classes,
connection data, retention values or authorization evidence from the browser.

Capability is intentionally split:

- authoring/activation require a V2 directory and active V3/V4 Quality retention classes;
- manual execution additionally requires the isolated worker to be enabled;
- scheduling remains unavailable without an approved schedule profile.

The user-facing information architecture is now user-first. Catalog Search loads one
authorization-bound batch of recent Quality summaries for the visible result page and shows the
pass rate and `PASS/WARN/FAIL` state in both the row and selected Evidence panel. The Quality page
has three primary tabs. `품질 대시보드` compares schema/table counts and managed
accuracy/completeness/timeliness indicators. `자산별 품질 현황 및 이력` reuses the Catalog global
search and lazy Resource Tree, then combines applied Rule Sets, recent Run history and a 30-day
score trend in one inspector. `공통 룰셋 관리` owns reusable templates and multi-asset mapping.
The former Overview, separate Run and Issue navigation and maker-checker controls are absent from
the ordinary UI.

Dashboard indicator analysis is an authorization-pruned read model. Accuracy and completeness
pool sanitized evaluated/missing/unexpected counts from the latest successful evidence of each
active Rule Set Version. Timeliness evaluates the latest COMPLETE FULL/PARTITION Profile against
its stored `stale_at`; no fixed age or source update time is invented. Platform-managed definitions
are versioned read-only semantics, not hidden executable Rule Sets. Until a governed
Quality-specific inference route exists, the report is explicitly `FACTS_ONLY` and does not claim
to be LLM-generated.

Common Rules are workspace templates for one to 100 typed `NOT_NULL` or `RANGE` definitions. A
user can search schema/table targets, select at most 25 compatible assets and apply the template
through one atomic command. The template is not executable truth: mapping creates the existing
canonical per-asset Rule Set/Version/definition aggregates and records their template relationship
in the same transaction. Existing activation and immutable audit invariants remain unchanged.
`REGEX` remains explicitly unavailable.

The score displayed for one table pools the newest `SUCCEEDED` Run for every active Rule Set's
current active Version. It is calculated as the sum of passed Rules divided by the sum of all
evaluated Rules across those Runs. Outcome precedence is blocking failure `FAIL`, advisory failure
`WARN`, then `PASS`. This replaces the former single-latest-Run asset score without changing the
HTTP response shape or persistence schema.

Revision `0073` supplies the missing RLS-scoped application read grants for Quality Profile
projection. Revision `0074` adds forced-RLS `quality.common_rule_templates` and
`quality.common_rule_template_mappings`. The schema dashboard adds no persistence change or
migration; the packaged required revision remains the repository's current `0077`.

## Executed verification and open target gates

The exact Quality commit candidate was exported from the Git index so concurrent Governance,
Knowledge and Knowledge Chat work could not enter the result. Repository Ruff format/lint passed
over `512` files, strict mypy passed over `503` source/test files, the complete backend suite
passed `1,960` tests with `104` explicitly environment-gated skips, and static
architecture/security verification passed. Frontend TypeScript/ESLint passed; `69` files /
`371` tests passed and the production build emitted the lazy Quality chunk at `32.72 kB`
(`9.74 kB` gzip).

The ADR-0084 Rule-weighted score follow-up was verified again from an isolated `dev` snapshot
containing Governance revision `0075` plus only the four Quality-owned changes. Ruff format/lint
and strict mypy passed over `496` backend source/test files, the complete backend suite passed
`1,974` tests with `104`
environment-gated skips, and `scripts/verify_static.py` passed. Frontend typecheck and the focused
Catalog/Quality suite also passed (`9` files / `40` tests). No HTTP response shape or database
schema changed.

Two consecutive canonical `0001` generations from that isolated source snapshot were
byte-identical to the staged baseline at SHA-256
`5f26b4d177cf8f6b09abf3cea47d5d3f6be00638323dc6b39dab3226ec9cf6af`. The frozen `0067`
helper was also constrained to its original Quality table allowlist, so later `0074` tables do
not leak backward into a historical migration.

The in-app browser rendered the staged React components against bounded local contract fixtures.
It confirmed one Search summary batch renders `PASS 98.75%` and `WARN 92%` in result rows, the
selected Evidence panel repeats `PASS 98.75%`, the asset inspector exposes applied Rule Sets,
recent Runs and the 30-day score trend, and the common Rule dialog supports schema/table search,
checkbox selection, compatibility confirmation and an enabled single batch apply. The resulting
success notice was `1개 테이블에 적용했습니다.` and no Issue/review tab was present. This is a
browser rendering and interaction claim, not live target-identity or source-execution evidence.

The ADR-0088 dashboard follow-up adds `GET /quality/dashboard`, the three-tab UI, a
calculation-tooltip schema grid, gauge/report/risk modal, Catalog hierarchy reuse and an actionable
mapping-readiness explanation. Its final isolated full-suite and browser evidence is recorded in
the completion briefing for the publishing commit; it does not change the target source/Profile,
LLM or accessibility gates below.

The local deployment has no approved V3/V4 Quality retention values, V2 target manifest,
read-only TLS source principal, fixed egress identity or enabled Quality worker. Those values are
owned by operations/security and are not fabricated in source. Consequently a real semiconductor
full-table GX Run, DataHub service-principal collection, live `0072 -> 0074` target migration and
representative multi-Workspace browser acceptance remain external target gates, while local
capabilities stay fail-closed.

## Deferred medium/low items

- make authoring readiness distinguish a complete V3/V4 policy class set from a policy containing
  only the three Quality classes; the mutation function already rejects the incomplete set;
- enforce workload-profile `max_concurrency` across worker replicas;
- assert manifest lease duration equals the deployed worker lease;
- hydrate V4 policy details in the retention administration repository;
- reconcile the stale semiconductor bootstrap manifest `postgres.applied` observation;
- add scheduled authoring only after an approved schedule-profile directory exists.
