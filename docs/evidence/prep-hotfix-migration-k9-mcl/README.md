# PREP hotfix: Migration integrity, K9 failure propagation, and MCL diagnostics

Recorded at `2026-08-28T02:50:19Z` for Product
`b0402d142cc3920cbe936e7b19d1426009b0cdf1`. The development and PREP-promotion refs remained
fixed during implementation and validation:

- starting `origin/dev`: `44ae27abbfef133076908c798ec0024fb34b389f`
- frozen `origin/main`: `44ae27abbfef133076908c798ec0024fb34b389f`

Actual PREP and Actual OPS were not accessed or executed by the Control Plane.

## Exact hotfix scope

The release contains only the three PREP recovery blockers. UX-A `7aa2d1c`, UX-B `c889463`, Chat
`e99d94a`, Quality bulk, Site Management, Monitoring enhancements, and all other feature work remain
quarantined for POST-PREP work.

### Migration fail-closed remediation

The one-time historical review classified all 54 migration files affected by the proven blanket
`RuntimeError`-to-`print` rewrite. Forty-eight guards restore their original fail-closed control
flow. Six squashed-baseline compatibility migrations accept only a definition-fingerprinted exact
canonical state, migrate an absent state normally, and raise on partial or malformed state.
Constraints, indexes, RLS policies, RLS enable/force flags, and trigger function/definition/enabled
state are compared rather than object names alone. Revision 0091 received the bounded current
upgrade-path disposition: its reviewed function replacement executes instead of returning
unconditionally.

`patch_migrations.py` is absent and the historical bypass marker count is zero. Static verification
rejects that file, the marker, blanket migration rewriting, changed or missing accepted migration
checksums, and an unmanifested new migration. The accepted-history manifest covers 100 revisions
through 0100. The future policy is documented in
`docs/68_MIGRATION_GOVERNANCE_AND_INTEGRITY.md`: historical migrations are immutable, unchanged
releases do not repeat this 54-file audit, and broad review is reserved for baseline/framework,
integrity, or supported-upgrade-policy changes. `MIGRATION_BASELINE_V2_AND_LEGACY_RETIREMENT` is a
separate POST-PREP design backlog; no legacy migration was deleted or reorganized.

Audit 2 was run exactly once by GPT-5.6 Sol xhigh. Its verdict was BLOCK because the six initial
compatibility validators compared names rather than normalized definitions and one 0092 fixture
described an unreachable state. Only those bounded findings were corrected. The corrected candidate
proved all six canonical squashed-0001 states and rejected same-name malformed constraint, index,
policy, and trigger states. Audit 2 found no K9, MCL, one-command deploy, authorization-widening,
secret, reset, or remote-ref blocker. It was not rerun.

Known c306 reachability findings for revisions 0082 and 0084 are explicitly outside this closure
scope and remain POST-PREP backlog. They are not represented as passing hotfix assertions.

### K9 terminal refresh failure

Actual PREP read-only evidence showed a scheduled refresh did run and fail:

- scheduler status `FAILURE`, reason `K9_REFRESH_FAILED`, trigger `scheduled`
- Default Lineage and Metadata Master both remained `PENDING`
- smoke timed out as `PREP_SMOKE_K9_NOT_READY`

The retired scheduler-skip hypothesis is not used. The Product defect was failure propagation: a
terminal shared refresh failure did not finalize the canonical managed-graph rows with a durable
typed error, so smoke could not distinguish terminal failure from ongoing work. The correction
atomically writes terminal failure rows for unfinished canonical policies, preserves the active
last-known-good/current promoted generation, and reports semantic READY only for an active matching
generation. Smoke now consumes the Product error code and fails immediately. The unknown external
PREP provider exception is not guessed; when no narrower typed cause exists the bounded K9 failure
classification remains explicit.

### MCL durable typed diagnostics

Actual PREP read-only evidence showed `CAPTURE_FAILED` under
`DATARIVER_CHANGE_HISTORY_RUNTIME_STATUS_V1`, classification
`PREP_MCL_CAPTURE_RUNTIME_UNEXPECTED_FAILED`, version 9, with no matching transient Web log. The
Product now maps expected capture exception families to bounded classification/stage/detail enums
and awaits a version-verified durable status write. It never persists raw exception text, schema
body, password, token, or provider response body. Ledger, checkpoints, source identity, and existing
receipts are preserved; no reset path was added.

## Verification

- Migration integration selection: `127/127 PASS`.
- Migration corrected candidate: `111/111 focused PASS`; bounded suite `269 PASS`, with three
  explicitly deselected known c306 backlog cases.
- K9 candidate: `74/74 focused PASS`.
- MCL candidate: `77/77 focused PASS`; server `37/37`; handoff `13/13`.
- Integrated affected Node selection: `137/137 PASS` after the required POC build.
- POC build, ESLint, TypeScript typecheck, static verification, focused Ruff, strict mypy over 319
  source files, Python compilation, and diff-check: `PASS`.
- Repository-wide Ruff was not claimed: it reports pre-existing generated-0001/c306 baseline
  findings outside the hotfix. No unrelated formatting cleanup was included.
- Marker/tool/blanket-rewrite static scan: `PASS`.
- Secret scan found only explicit test fixtures and static negative fixtures; no runtime secret,
  token, schema body, or private provider response was added to source or Evidence.

The exact Product image is `linux/amd64`, carries OCI revision
`b0402d142cc3920cbe936e7b19d1426009b0cdf1`, and currently resolves to image ID
`sha256:5e12e7becf8a466200500b15d75ea281fa6cb6407f67f53a2eb2ec8d4ec8daf6`.
Inside that exact image, the K9 success fixture completed `SUCCESS`; a shared semantic failure
returned and persisted `K9_SEMANTIC_INDEX_FAILED` for both canonical managed-graph intents; and an
MCL durable-append exception persisted only
`PREP_MCL_CAPTURE_DURABLE_APPEND_FAILED / DURABLE_APPEND / LEDGER_WRITE_REJECTED` while raw
password/schema text remained absent from the rendered diagnostic.

## Isolated Docker recovery gates

- Historical accepted Product upgrade to this Product: `1 PASS` in `213.52s`, ending
  `EXISTING_ACCEPTED_RUNNING`, K9/MCL READY, one existing administrator, and 39080 untouched.
- Current-style `SMOKE_FAILED` descendant resume: `1 PASS` in `230.24s`, ending
  `EXISTING_OWNED_INCOMPLETE`, K9/MCL READY, with the existing administrator reused and 39080
  untouched.
- The first current-style attempt was interrupted after Docker Compose 5.3.1 temporarily failed to
  return from `up --wait` although the services were healthy. Its exact disposable containers,
  volumes, and network were removed individually. A single clean rerun passed the complete fixture,
  so this transient tool behavior is not a remaining release blocker.
- A separate auxiliary state-machine-only fixture was attempted after release assembly. Docker
  Compose 5.3.1 did not return from its first `up --wait` and produced no test result in 217.84s.
  The one exact disposable container, three volumes, and network were then removed individually.
  This auxiliary attempt is not counted as PASS and does not replace the two complete full-deploy
  recovery gates above.
- Disposable Docker resources remaining after the gates: zero.
- No test invoked `docker compose down -v`, deleted a PREP volume, reset a database, regenerated an
  accepted secret, or accessed actual PREP/OPS.

The canonical operator command remains unchanged:

```bash
./scripts/prep39083 deploy
```

Actual PREP: **NOT EXECUTED**.

Actual OPS: **NOT EXECUTED**.
