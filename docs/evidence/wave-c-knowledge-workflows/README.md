# Wave C knowledge-workflow evidence

## Scope and status

This checkpoint records the Wave C Product
`1ad090d084b34906438e281ee208f9ec49d9a95f`, based on the Wave B Handoff
`20099fa6a232a9e87d54c4db8431feb45c3f93e5`.

The locally verified Wave C slices are:

- Chat keeps answer/citation evidence separate from a bounded authorized
  discovery window. The response envelope reports returned count, limit and
  truncation truthfully, does not persist discovery in history, and renders an
  expandable discovery panel separately from grounded citations.
- Every Chat discovery row is reauthorized against the current principal before
  response. Candidate authorization drift removes the discovery envelope, while
  citations are independently revalidated so an unrelated uncited candidate
  cannot erase an otherwise valid grounded answer. Catalog assets alone are
  interactive; Knowledge and Governance sources are explicitly labelled and
  non-interactive.
- Glossary is restored as a top-level `catalog.read` route. Provider entity and
  relationship pagination is complete and reconciled, current Term/Node
  identities remain canonical, and every assigned Dataset is re-resolved through
  the canonical current authorized inventory before it is returned. Removed,
  restricted or non-Table assignment targets are excluded.
- Knowledge refresh status exposes the existing durable scheduler configuration,
  last attempt and receipts without adding a second scheduler or mutation path.
  The initial managed-graph creation/reconciliation contract remains unchanged.
- Governance uses Workspace-scoped display names, preserves only the supported
  CSP-safe editor formatting tokens, keeps paste and editor scroll bounded, and
  removes only the presentation route for the redundant role-policy tab. Backend
  authorization remains intact.
- Change detection continues to use the existing exact Table-to-System mapping,
  active-system, ETag/CAS and authorization contracts; no fuzzy or fallback
  mapping was added.

The following requested slices are intentionally not marked complete:

- `CH-01`, `CH-02`, and `CH-03` remain `IN_PROGRESS`: the Product now exposes a
  truthful bounded discovery window, but complete authorized result pagination
  and end-to-end performance timing are not yet closed.
- `KG-02` is `NEEDS_DECISION`: there is no canonical mutable K9 schedule/trigger
  API and no approved capability contract to widen.
- `KG-07` is `NEEDS_DECISION`: there is no approved typed, release- and
  classification-fenced cross-graph materialization contract. This checkpoint
  does not create a second graph source of truth.

## Security and architecture review

An independent bounded integration audit initially found three authorization /
provenance defects and one CSP issue. All were corrected before this Product:

1. the full Chat discovery window is reauthorized at response time;
2. Chat source labels and click behavior no longer imply that non-catalog
   evidence is a catalog asset;
3. Glossary assignment targets are resolved through the canonical current
   security-grade inventory before `canReadAsset` is evaluated;
4. Glossary indentation uses bounded stylesheet classes rather than inline
   style.

The final independent disposition at Product parent `b9c2a67` was PASS with no
remaining blocker. Focused auditor verification covered 7 backend, 29 frontend,
and 2 provider tests. The final `1ad090d` commit only aligns integration
expectations with the reviewed contracts.

The Product delta adds no dependency, migration, CSP relaxation, authorization
widening, direct DataHub backing-store write, target-business URN, fixed provider
cardinality, PREP reset/resecret behavior, or OCI fallback build.

## Verification

Focused and Wave-level results:

- Chat backend: `87/87` PASS;
- Chat/Glossary UI: `29/29` PASS;
- Node provider/server/K9 contracts: `80/80` PASS;
- Governance backend: `81/81` PASS;
- Governance frontend: `43/43` PASS;
- navigation: `7/7` PASS;
- full UI Vitest: `93` files, `723/723` PASS;
- full Node Product server: `198/198` PASS;
- TypeScript typecheck, ESLint, application build and POC build: PASS;
- Ruff lint, changed-source strict mypy and static/source verification: PASS;
- `git diff --check`: PASS.

The complete backend pytest run produced `4105` PASS, `121` SKIP and `19`
failures. Those failures are the existing baseline outside the Wave C diff:
stale migration-revision/change-history downgrade expectations, DEV host
preflight environment tests, a documented-env example assertion, Knowledge
media/persistence/managed-intent migration tests, and pilot-release
expectations. No commit in `origin/dev..1ad090d` modifies those failure files.
Full strict mypy retains six pre-existing errors in the two PREP test modules.
They are recorded rather than mixed into this feature checkpoint.

The frontend build retains only its existing large-chunk advisory. Local results
are not reported as browser or TEST PC acceptance.

## Exact Product artifact

The clean Product was built once for `linux/amd64` and exported without a second
build:

- image reference:
  `datariver-poc:1ad090d084b34906438e281ee208f9ec49d9a95f`;
- local image identity:
  `sha256:f1c81d22efb6f5499f596a15afadf991274fb0f942ecfecc5d53ae1912f11e35`;
- archive:
  `datariver-poc-1ad090d084b34906438e281ee208f9ec49d9a95f-linux-amd64.tar`;
- archive SHA-256:
  `dec34d0d532e24fb8236f8c115fa0cf699dbdef79c6bdd377b043bceda10b3f3`;
- child manifest:
  `sha256:aac2c7eea072c6824a49f6df1395c81f74378447d305089ccc949acc15d0be41`;
- config digest:
  `sha256:e89baf1b49cbbaafbe005cc1dd7634479aeea9fc3a9837b6e2dae56d0b1263be`;
- platform: `linux/amd64`;
- OCI revision:
  `1ad090d084b34906438e281ee208f9ec49d9a95f`.

The first build attempt exhausted only Docker's build-cache allocation after
source compilation. Recovery pruned unused build cache older than 24 hours; it
did not remove images, containers, volumes or runtime state. The successful
image above was then exported exactly once. The ignored archive remains outside
Git and the Handoff pins its exact checksum, child manifest, config, platform
and revision. Deployment retains `pull_policy: never`, `--no-build`, and no
fallback build or pull.

## Runtime boundary

- The earlier TEST PC acceptance remains preserved. This Wave C Product was not
  deployed because no approved TEST environment/browser transport was available;
  its runtime acceptance is `BLOCKED_EXTERNAL`.
- Browser/API runtime verification for the changed surfaces: NOT EXECUTED.
- User DataHub metadata modified: NO.
- Actual PREP: NOT EXECUTED.
- Actual OPS: NOT EXECUTED.
- `origin/main`: unchanged and frozen.

Wave C is a locally verified partial checkpoint. Completed slices are
`LOCAL_VERIFIED`; runtime-reachable completion is not promoted to `DONE` until
TEST PC acceptance, and the explicitly listed Chat/K9 design items remain open.
