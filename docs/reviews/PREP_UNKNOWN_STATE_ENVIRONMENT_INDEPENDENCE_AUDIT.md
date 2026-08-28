# PREP Unknown-State / Environment-Independence Deployment Audit

Date: 2026-08-29 KST  
Scope: read-only source/release audit; no Actual PREP/OPS access; no TEST PC change  
Canonical Handoff: `af74fc4d0cc99295a0ebfe897ccbaeb94cb5dfe6`  
Product: `be74759b2eec0c61090feaeba9e110d66ab3e334`  
Evidence: `394bb681e541d7a281a5e825a89ecc198230f552`  
`origin/main`: `17f32a52de79077c433bf0beaabac81a48e46062` (unchanged)  
`origin/dev`: `af74fc4d0cc99295a0ebfe897ccbaeb94cb5dfe6` (unchanged during the audit)

## Verdict

`SOURCE_AUDIT_PREP_PORTABILITY_BLOCKED`

`TEST_PC_RUNTIME_ACCEPTED` remains valid for the exact known TEST state. The audit does not
cancel that acceptance. It found four source-contract gaps that prevent extending the result to
an unpredictable pre-existing PREP state:

1. an `accepted.json` marker can select the accepted reconcile path without the attempt receipt,
   ownership fingerprint, exact volume identity, or source ancestry checks used for incomplete
   deployments;
2. K9 can combine inventory, lineage, and metadata read at different provider moments without a
   final cross-source consistency fence before semantic/graph publication;
3. the current Dataset predicate accepts a removed/non-existent Dataset when current-looking
   aspects remain, and the inventory query does not request the existence/removal fields;
4. the Product-owned PostgreSQL schema is initialized with `CREATE TABLE IF NOT EXISTS` plus
   incremental statements but has no exact accepted schema revision/integrity check for malformed
   or newer existing schemas.

No Product source was changed in this audit. Actual PREP availability and configuration alone
cannot close these four source findings.

## Independent audit execution

An isolated Orca worktree at the same Handoff was created for an Antigravity
`gemini-3.1-pro-high` read-only review. Its first run could not see the source through the tool
sandbox and returned an evidence-gap result; that result was rejected. A second bounded run used
the exact worktree as an explicit Antigravity workspace and reviewed only the four findings and
the named release boundaries. The Control Plane retained only conclusions supported by exact
repository evidence; an agent statement alone is not evidence.

The second run independently classified all four findings as `CONFIRMED` and returned
`SOURCE_AUDIT_PREP_PORTABILITY_BLOCKED`. Two imprecise agent phrases were not adopted: collector
pagination is bounded even though cross-source consistency is not fenced, and smoke reads the
existing private password file rather than creating a password seed. This report uses the exact
code contracts instead.

## Historical defect inventory

| Area | First symptom | Proven cause | Fix/current ancestry | Regression/current reachability |
| --- | --- | --- | --- | --- |
| ADMIN_LOGIN Origin | `POST /auth/login`, HTTP 403, `ORIGIN_FORBIDDEN` | loopback transport URL was reused as the HTTP security Origin | `2a26dc43f1bac3242811c3803c80dc845884bc80`; ancestor of Product | `smoke_prep39083.mjs` uses `transportOrigin` for the URL and exact `requestOrigin` for `Origin`; smoke suite PASS |
| Wafer/DEV seed suspicion | fixed `Wafer`, `Wafer ID`, and Wafer URNs found by repository search | test, mock, manual evaluation, documentation, and deterministic DEV seed data; not a PREP runtime call path | no Product correction required | zero runtime/deploy/PREP-smoke target-data dependency; unit fixtures remain allowed |
| GlossaryTerm PREP coverage | older smoke did not verify a Term | coverage gap, not a Wafer runtime dependency | `3daf21e43830cc42411c15ed375042feadae661c`; ancestor of Product | optional exact configured URN or deterministic runtime discovery, followed by direct existence/type/basic metadata checks; no mutation/fixed fallback |
| Exact OCI promotion | verified local image was previously rebuilt on the destination | build-once/promote-same-artifact contract was absent | `abcfa63`, corrected descriptor support in `052d8867501bd6aaf3d75b9e9c7158a327c6a264`; ancestors | checksum/manifest/config/platform/revision pin, `docker load`, `pull_policy: never`, `up --no-build`, no build fallback |
| root-owned bootstrap secret | host-root `0600` admin password was unreadable to UID 1000 | first-admin bootstrap crossed the host/container UID boundary incorrectly | Product commit `be74759b2eec0c61090feaeba9e110d66ab3e334` | only disposable first-admin command runs `0:0` with a read-only private mount; normal web remains `1000:1000`; TEST same-state resume accepted |
| partial deploy resume | target stopped at `SCHEMA_READY` | resume required durable ownership/source proof without resecret/reset | `749f568`; ancestor | V2 ownership fingerprint, exact volume/project/platform/port/K9 identity, Product/Handoff ancestry; TEST `SCHEMA_READY` resume accepted |
| MCL/Kafka topology | TEST broker advertised `localhost` to a remote consumer | external advertised-listener topology, not a Product seed/state defect | diagnostic contract is in current Product | MCL discovery separates connect/cluster/topic failures; Product does not require Tailscale; actual topology remains environment acceptance |
| K9 graph count | DEV 1,001/1,950 and TEST 1/0 | authorized classification ceiling and inventory content differed: DEV included 1,000 Oracle MOCK nodes/1,950 edges; TEST did not | no fix required | full deterministic authorized projection; no runtime exact-count assertion; category/identity mismatch was zero |

All named fixing commits above are ancestors of the current Product. The tests executed by this
audit are local/static evidence, not Actual PREP runtime evidence.

## Runtime target-data hardcoding audit

Repository occurrences were classified by call path, not by raw text count. `Wafer`,
semiconductor/Oracle MOCK identities, sample Dataset/Term URNs, display names, and expected sample
counts occur in unit/integration fixtures, deterministic DEV seed material, manual evaluation,
or documentation. None is reachable from Product runtime, canonical PREP deploy, or PREP smoke as
a required target entity.

`RUNTIME_TARGET_DATA_HARDCODING_COUNT = 0`

The fixed graph intent identifiers, MCL protocol topics/group identifiers, reviewed Airflow DAG
allowlist, and controlled authorization tag vocabulary are Product-owned protocol/policy
identities. They are not assumptions that target DataHub business metadata already exists.

No runtime path falls back to Wafer or another fixed business entity when discovery is empty.
GlossaryTerm discovery returns a typed not-found blocker when there is no valid candidate.

## Confirmed blocker 1: accepted-state provenance is incomplete

Evidence:

- `scripts/prep39083_deploy.py:471` validates only the accepted marker contract and syntactically
  valid Product/Evidence/Handoff SHA strings.
- `scripts/prep39083_deploy.py:640` selects `EXISTING_ACCEPTED_RUNNING` or
  `EXISTING_ACCEPTED_STOPPED` from that marker, a valid runtime env, and required logical volume
  names.
- `scripts/prep39083_deploy.py:1193` invokes `validate_owned_attempt()` only for
  `EXISTING_OWNED_INCOMPLETE`.
- `scripts/prep39083_deploy.py:1441` contains the missing checks: exact release/project/platform/
  port/K9/volume identity, ownership fingerprint, and Product/Handoff ancestry.

A pure in-memory `TargetInventory` reproduction with a syntactically valid accepted marker and a
divergent/malformed ACCEPTED receipt classified as `EXISTING_ACCEPTED_STOPPED`. No filesystem or
runtime state was changed.

Risk: a copied, divergent, or newer accepted marker can make an unproven target enter reconcile.
The deploy path does not reset it, but safe ownership/ancestry is not established before mutation.

Bounded correction requirement: accepted state must bind its marker to a consistent ACCEPTED
receipt and exact ownership/source evidence. Legacy accepted state without sufficient proof must
fail closed to bounded operator recovery; it must never be reset or treated as fresh.

## Confirmed blocker 2: K9 cross-source consistency fence is absent

Evidence:

- `frontend/poc-k9-scheduler.mjs:233` reads current inventory once.
- `frontend/poc-k9-scheduler.mjs:235` then collects lineage, metadata, and runtime identity in
  parallel.
- `frontend/poc-k9-scheduler.mjs:248` builds/promotes the semantic index and source snapshot and
  publishes both graphs without a final full-source consistency validation.

The individual collectors are strong within a request sequence: inventory uses stable totals,
bounded pagination, cursor progress, exact fetched-total reconciliation, canonical-URN dedupe,
and deterministic ordering; lineage reconciles both directions and excludes edges whose endpoint
is outside the authorized inventory. Those checks do not detect a same-cardinality entity,
classification, lineage, or glossary mutation between independent source reads.

A dependency-level read-only probe returned success after one inventory read while lineage
returned a `before` source marker and metadata returned an `after` marker. Both were published.
This proves a cross-source contract gap without relying on a business name or DEV seed.

Risk: concurrent Airflow/DataHub ingestion can produce a mixed graph and silently publish it.
Because the current provider API does not expose a repository-proven atomic snapshot token, the
correction must use a bounded consistency/reconciliation design. A simple inventory reread alone
is insufficient for lineage-only or metadata-only mutation.

Bounded correction requirement: bind all collected inputs to one verifiable source generation or
perform bounded end-of-read recollection/hash reconciliation; detected drift must cause typed
bounded retry/failure before semantic or graph promotion. LKG and the semantic promotion fence
must remain intact.

## Confirmed blocker 3: removed Dataset can enter current inventory

Evidence:

- `frontend/poc-datahub-current-table.mjs:19` accepts a canonical Dataset when either properties or
  schema metadata is present; it does not check `entity.exists` or `status.removed`.
- the current inventory Dataset fragment in `frontend/poc-server.mjs` does not request existence or
  removal status.
- a read-only function probe with `exists=false`, `status.removed=true`, and retained properties
  returned `true`.
- the existing “deleted” test covers an aspect-less ghost and therefore does not cover a removed
  Dataset whose current-looking aspects remain.

Risk: a tombstoned entity can be projected as current. This affects unknown historical DataHub
state and concurrent deletion handling.

Bounded correction requirement: request and validate the canonical DataHub v1.6.0 existence/
status fields on every current-identity path; exclude proven removed/non-existent entities while
keeping status-absent and incomplete-shape behavior explicit and fail closed where identity is not
provable.

## Confirmed blocker 4: Product PostgreSQL schema provenance is incomplete

Evidence:

- `frontend/poc-state-store.mjs:585` opens the Product PostgreSQL connection.
- `frontend/poc-state-store.mjs:603` uses `CREATE TABLE IF NOT EXISTS`, followed by schema statement
  families at lines 626-631.
- there is no Product-state schema revision/checksum ledger or exact accepted definition check for
  all columns, constraints, indexes, and security-critical invariants.

An existing same-name table missing a constraint is not corrected by `CREATE TABLE IF NOT EXISTS`.
Some historical corrections are explicit, but malformed, unexpected, or newer schema provenance
is not comprehensively classified. A later query may fail for some missing columns, whereas a
missing constraint can remain silent.

This is distinct from the backend Alembic historical-migration checksum gate, which passed and was
not reopened.

Bounded correction requirement: define a versioned Product state-schema manifest and supported
upgrade path; verify exact integrity, transactionally migrate known older revisions, and fail
closed on malformed/newer states. Do not drop, recreate, or reset existing data.

## DataHub unknown-state contract

| Concern | Current behavior | Audit result |
| --- | --- | --- |
| Inventory pagination | bounded pages; provider total must remain stable; cursor must progress; exact raw/fetched accounting; canonical-URN sorting/dedupe | safe within one inventory read |
| Empty inventory | K9 source returns typed `EMPTY_SOURCE`; no fixture fallback; Term smoke returns typed no-candidate | fail closed, environment-independent |
| Large inventory | bounded multi-page collection; generic 1,000+ Dataset and 1,950+ lineage tests pass | cardinality-independent within configured bounds |
| Identity/display collision | Dataset identity is canonical DataHub URN; display names are attributes | safe for equal names across schema/platform identity encoded in URN |
| Deleted/incomplete | aspect-less ghosts rejected | **blocked** for removed entities retaining aspects |
| Classification | K9 requires exactly one known `CLASSIFICATION:` tag within ceiling; missing/multiple/invalid/above-ceiling entities are excluded | fail closed; no include-all fallback |
| Lineage | direct inbound/outbound pagination, stable totals, deterministic dedupe, authorized endpoint map | no unauthorized endpoint leak; cross-read drift remains blocker |
| GlossaryTerm | explicit exact URN or deterministic one-item discovery; direct exists/type/basic metadata; no mutation | seed-independent; zero-Term environment fails typed |
| Airflow/ingestion | K9 reads current DataHub dynamically; Airflow may be DEFERRED; reviewed DAG IDs are execution allowlists | `AIRFLOW_STATE_INDEPENDENT`, but concurrent ingestion triggers the K9 consistency blocker |

The Product does not promise DataHub atomic snapshot isolation. Its existing eventual convergence
cannot justify publishing an undetected mixed source because the current code does not label that
result as partial/eventual or fence its promotion.

## Local persistent target-state inventory

| State | Detect/allowed transition | Mutation/secret/replay boundary | Audit result |
| --- | --- | --- | --- |
| `FRESH_CLEAN` | no owned/runtime state; preflight and exact artifact checks precede persistence; bootstrap to accepted | new secrets/volumes; idempotent schema/bootstrap; no reset | covered |
| `EXISTING_OWNED_INCOMPLETE` | valid non-ACCEPTED receipt, exact volume identity, runtime fingerprint, and source ancestry | preserve secrets/volumes; resume exact phase | covered |
| `LEGACY_SELF_BOOTSTRAPPED_PARTIAL_REQUIRES_INSPECTION` | bounded live inspection proves exact admin/service/policy/table and managed Neo4j footprint | safe adoption only after proof | covered |
| `FAILED_FIRST_INSTALL_RECOVERABLE` | residual owned services but PostgreSQL/Neo4j data are empty | preserve volumes/secrets and resume | covered |
| `FAILED_FIRST_INSTALL_REQUIRES_INSPECTION` | any durable row or graph node lacks ownership proof | no cleanup/reset; fail closed | covered |
| `EXISTING_STATE_AMBIGUOUS` | receipts/runtime/containers/volumes/networks disagree | no mutation; fail closed | covered |
| `EXISTING_ACCEPTED_RUNNING/STOPPED` | syntactically valid accepted marker, runtime env, logical volumes | reconcile/rerun | **blocked: marker is not bound to exact ownership/ancestry** |
| unknown/newer Product schema | no exact Product schema revision detector | starts idempotent DDL | **blocked: malformed/newer provenance not classified** |

The deploy code contains no runtime `down -v`, volume reset, resecret fallback, automatic downgrade,
or “unknown means fresh” branch. Exact 39080 state is snapshotted and compared. These safeguards do
not eliminate the two accepted/schema provenance gaps above.

### PostgreSQL

Durable row inspection prevents adopting a non-empty unowned failed-first-install database, and
owned incomplete receipts preserve the exact volumes. The Product schema itself lacks an exact
accepted revision/integrity contract, so unknown/malformed/newer schema handling is blocked.

### Neo4j

Managed namespace and historical/staging ownership are explicit. Unowned residual nodes/edges
block legacy adoption; failure cleanup targets only the exact generated staging namespace and
preserves LKG/promoted generations. Accepted-state provenance still inherits the marker gap.

### Redis

Redis is cache/session infrastructure, not the durable release/ledger authority. Current K9 uses a
fresh provider inventory; cache entries are scope/projection bound for read availability. No
Product reset is used. Unknown stale Redis state is low risk relative to PostgreSQL/Neo4j, but its
operational validation remains host-only.

## Provider, network, secret, and UID portability

- Provider endpoints are environment contracts; Product runtime does not require Tailscale.
  Tailscale was TEST transport only.
- host PostgreSQL/Neo4j/Redis ports bind to loopback; browser/public web binds 39083 as designed.
- HTTP transport and security Origin are separate. `Origin` is the exact public origin, not the
  loopback transport URL.
- Docker-internal state services use Compose service names rather than host localhost.
- Kafka advertised-listener topology is external; MCL reports typed discovery/connect/cluster/topic
  states rather than silently passing.
- the admin password file remains host-root `0600`; only the bounded first-admin container runs as
  root to read its read-only mount. Normal web and provider preflight stay UID/GID `1000:1000`, with
  dropped capabilities/no-new-privileges where applicable.
- runtime CA sources are bounded absolute regular non-symlink files, but host readability by UID
  1000 is proven only when the non-root provider-preflight container reads the mount. A root-only CA
  therefore fails before persistent mutation. This is an explicit environment acceptance gap, not
  a chmod/fail-open path.
- no code changes a private secret to `0644`/`0777` or logs the secret value.

## Exact OCI release contract

`deploy/prep39083/release.json` pins:

- Product: `be74759b2eec0c61090feaeba9e110d66ab3e334`
- archive SHA-256: `ccf6ecb2873981e6db7297e82741a58f03995b179d7b1bb90dcdb7a17da63c8a`
- child manifest: `sha256:5f4153b2e6978dc5a1dc6204bf66a482314162543dd9e9fc6e6e6820fdf757d3`
- config: `sha256:4269a48efe853b74f2a4ea006dfd9b58770e21115498d4cf57073ab75e2e5a2c`
- platform: `linux/amd64`
- OCI revision: exact Product SHA

`prepare_exact_web_image()` rejects missing/unreadable/checksum-mismatched archives and manifest,
config, revision, platform, and image-reference mismatches. It only reuses an exact inspected image
or performs `docker image load`; no source build or mutable pull fallback exists. Runtime starts
with `docker compose up --no-build`, and the artifact override uses `pull_policy: never`.

The tracked archive is intentionally target-local and absent from this Mac worktree. Existing TEST
evidence proves consumption of its exact staged copy. Actual PREP archive staging/identity remains
an Actual-PREP-only acceptance item.

Current source contract: `runtime_input_diff=NONE` between Product and Handoff.

## PREP smoke inventory

| Stage | Contract | Data/read-write | Seed/count dependency | Diagnostic boundary |
| --- | --- | --- | --- | --- |
| 1/6 Health | host and Product health | Product read | none | typed health stage/status |
| 2/6 ADMIN_LOGIN | exact account/session and Origin | Product auth mutation (session only) | none | login endpoint, HTTP status, nested code; canonical request Origin |
| 3/6 DataHub + Term | forced current ROOT inventory plus bounded catalog; configured/discovered Term direct read | provider read-only | no fixed entity/count; zero Term is typed blocker | operation/substage/status/nested sanitized code |
| 4/6 K9 | both canonical managed graphs and semantic index READY | Product-owned projection/state | full authorized inventory, no exact node/edge count | terminal typed K9 failure fails immediately |
| 5/6 MCL | scheduler/runtime capture state and checkpoint continuity | Product ledger/checkpoint | protocol topic, no business seed | Product-vs-provider topology typed diagnostics |
| 6/6 GENERAL | GENERAL routing and provider completion, no internal retrieval evidence | chat provider/session | domain-neutral prompt, no target Dataset | route/provider/nested sanitized code |

The smoke never creates, edits, or deletes user DataHub metadata. Cleanup is limited to the auth
session/output artifacts. The broad top-level code retains bounded substage, endpoint/operation,
status, nested error code, and sanitized reason for supported failures. It does not reinterpret a
provider/auth failure as PASS.

## Fail-open/fallback audit

No runtime path was found that:

- falls back to a DEV seed or fixed Term/Dataset after discovery failure;
- rebuilds after OCI identity failure;
- retries authorization with a broader credential or includes all entities on missing
  classification;
- treats ambiguous target ownership as fresh or resets it;
- treats Kafka/MCL failure as overall smoke PASS;
- deletes user metadata or unowned graph state.

However, three effective fail-open behaviors are release blockers:

1. accepted marker provenance is weaker than incomplete receipt provenance;
2. K9 promotes independently timed inputs without detecting cross-source drift;
3. removed Datasets with retained aspects are treated as current.

The PostgreSQL issue is a fail-closed/integrity gap: some malformed states fail only incidentally,
while missing constraints/newer provenance may remain undetected.

## Verification executed

All results below are local/source verification only:

- selected DataHub inventory/K9/MCL/provider/transport Node tests: **102/102 PASS**;
- PREP deploy and handoff unit tests: **120/120 PASS**;
- PREP smoke tests: **33/33 PASS**;
- migration checksum manifest: **2/2 PASS**;
- static/source contract: **PASS**;
- Product/Evidence/Handoff source contract: **PASS**, `runtime_input_diff=NONE`;
- in-memory accepted-marker negative probe: reproduced unsafe accepted classification;
- dependency-level K9 mixed-source probe: reproduced successful mixed publication;
- current-Dataset predicate probe: reproduced acceptance of removed Dataset with retained aspects.

No tests or Product source were added/changed. No Docker runtime, TEST PC runtime, Actual PREP, or
Actual OPS command was executed for this audit.

## Risk matrix

| Area | Environment-dependent? | Unknown-state safe? | Runtime verified? | Remaining risk |
| --- | --- | --- | --- | --- |
| Seed/business metadata | No | Yes | TEST + local | no runtime target-data hardcoding found |
| DataHub inventory | Provider content only | Partly | TEST + local | removed entity and cross-read drift blockers |
| GlossaryTerm | Provider may have zero Terms | Yes/fail-closed | TEST + local | Actual PREP candidate/shape pending |
| Classification | Policy ceiling is environment config | Yes | TEST + local | Actual PREP inventory differs by design |
| Lineage/K9 | Provider content/concurrency | **No** | TEST + local | no cross-source consistency fence |
| Airflow/ingestion | Endpoint optional | Partly | local | state independent, but concurrent writes expose K9 blocker |
| PostgreSQL | Existing state | **No** | TEST known state + local | accepted provenance and exact schema integrity gaps |
| Neo4j | Existing state | Partly | TEST known state + local | ownership safe except accepted marker provenance |
| Redis | Existing cache/session | Yes by current contract | TEST + local | host/runtime observation pending |
| Admin/bootstrap | Existing identity | Partly | TEST runtime | accepted marker ownership gap |
| Secrets/UID | Host UID/mode | Yes/fail-closed | TEST runtime + local | non-root CA readability is host preflight item |
| Origin/network | Endpoint topology | Yes/fail-closed | TEST runtime + local | Actual PREP public origin/provider routing pending |
| Kafka/MCL | Advertised topology | Product-safe, provider-dependent | TEST external gap + local | Actual PREP provider acceptance pending |
| OCI artifact | Target-local archive | Yes/fail-closed | TEST runtime + local | exact Actual PREP transfer/load pending |
| Partial resume | Existing owned receipt | Yes | TEST runtime + local | exact Product still preserves contract |
| Existing accepted rerun | Existing marker/receipt | **No** | TEST known state only | divergent/unowned accepted marker not rejected |
| Smoke diagnostics | Provider/error shape | Yes for covered codes | TEST + local | Actual PREP-specific error paths pending |

## Exact next action

Do not deploy Actual PREP or move `origin/main`. Keep feature work quarantined. Prepare four bounded,
independently reviewed correction candidates in this order:

1. bind accepted marker/reconcile to exact ownership receipt and ancestry with legacy fail-closed
   handling;
2. exclude proven removed/non-existent current Datasets;
3. add a K9 pre-promotion cross-source consistency/retry fence that covers lineage and metadata,
   not only inventory;
4. introduce a supported, versioned Product PostgreSQL schema-integrity contract without reset or
   broad historical migration work.

After focused negative/positive tests and an independent audit, create one exact OCI candidate and
use the preserved accepted TEST state for same-state canonical resume/redeploy. Only after that
passes should the same Handoff/artifact be offered for Actual PREP doctor → deploy/resume → 6/6
smoke → GlossaryTerm/K9/MCL/provider acceptance.

Actual PREP: **NOT EXECUTED**  
Actual OPS: **NOT EXECUTED**
