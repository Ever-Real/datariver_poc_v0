# ADR-0081: User-centric Quality workspace and reusable Rule templates

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Application, Data Platform
- Refines: ADR-0077, ADR-0078, ADR-0079

## Context

The first Quality UI mirrored the control plane as four separate views for Overview, Rule Sets,
Runs and Issues. That exposed implementation lifecycle and audit concepts more prominently than
the questions an ordinary user needs answered: whether a table is healthy, which checks apply,
what happened recently and whether the score is improving. It also required users to recreate the
same typed Rule intent independently for every table.

Catalog search is the primary asset-discovery surface. Requiring a separate visit to Quality to
see the latest authorized score makes the most common workflow unnecessarily indirect. At the
same time, search integration must not add one request per row, extend the 30-second Quality
authorization lease or disclose a hidden asset through counts or status.

## Decision

### Search and asset-centric read models

Catalog search requests one bounded `POST /quality/assets/summary-batch` for the visible result IDs
after obtaining the existing Quality capability lease. The server reuses the authorization-pruned
Catalog asset relation and preserves caller order while omitting unavailable IDs. Search displays
the latest pass-rate basis points and `PASS/WARN/FAIL` outcome in both the result row and the
selected asset Evidence panel. No Quality denial prevents the Catalog result itself from loading.

The ordinary Quality page has only two primary tabs:

1. `자산별 품질 현황 및 이력` combines the searchable schema/table directory with one selected
   table's applied Rule Sets, last 50 Runs and at most 90 daily score points.
2. `공통 룰셋 관리` owns reusable typed Rule authoring and multi-asset mapping.

The former Overview, Run and Issue navigation is removed from the ordinary UI. Existing immutable
review, activation, issue and audit APIs remain enforcement/evidence boundaries and are not
weakened by this presentation decision.

### Reusable templates and canonical mappings

`quality.common_rule_templates` stores a workspace-scoped, non-executable authoring template with
one to 100 typed `NOT_NULL` or `RANGE` Rule documents. It is convenience intent, not execution
truth. `REGEX` remains unavailable under ADR-0077 until its separate bounded-execution safety gate
is accepted.

A mapping command accepts one template and at most 25 unique assets. It resolves the server-owned
field directory, reauthorizes every target and validates field/type compatibility before invoking
the existing atomic Rule proposal transaction. That transaction creates the per-asset immutable
Rule Set/Version/definitions and `quality.common_rule_template_mappings` rows together. Therefore:

- a template is never executed directly;
- a mapping cannot partially succeed;
- source coordinates, GX classes, SQL and provider configuration remain absent from the browser;
- the canonical per-asset Rule Set lifecycle and activation controls from ADR-0079 remain intact.

Template detail reports only mappings whose assets are visible to the current caller. Mapping
counts use the same pruned relation and never reveal hidden assets.

### Persistence and concurrency

Revision `0073` grants the application only RLS-scoped reads of the two existing Catalog Profile
tables needed by the already accepted Quality read model. Revision `0074` adds the two template
tables with forced workspace RLS, composite tenant foreign keys, append-only application grants
and uniqueness for `(template, asset)` and `rule_set`. The application exposes no update or delete
route for either table in this phase.

The reusable template name is unique per workspace. Creation and mapping are actor-bound,
idempotent commands. Concurrent duplicate mapping is closed by both the idempotency boundary and
database uniqueness.

## Consequences

- Users can assess Quality from search and inspect a table without translating control-plane tabs.
- A common Rule reduces repeated authoring while preserving per-asset execution evidence.
- The ordinary UI no longer presents maker-checker or Issue tracking as daily work, but backend
  activation and immutable audit invariants remain unchanged.
- Search adds at most one bounded Quality summary request per visible page and keeps Catalog usable
  when Quality is denied or unavailable.
- Target acceptance still requires the existing V2 field directory, V3/V4 retention readiness,
  isolated source/worker proof and representative PostgreSQL/browser evidence.
