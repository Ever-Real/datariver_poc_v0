# Phase 4 Knowledge entry gate — PRD and execution checklist

## Objective

Establish a fail-closed canonical publication boundary and prove the exact local provider
capabilities before adding durable Knowledge extraction, Chat routing or MCP. This gate prevents a
feature phase from building on an unreviewed release, an over-classified source or a merely
reachable model endpoint.

## Scope

Included:

- atomic reviewed changeset publication and separate activation;
- governed-release read eligibility and legacy bypass closure;
- graph/source/model classification-envelope enforcement;
- canonical PostgreSQL and optional Neo4j shadow receipt verification;
- independent source-host Neo4j, Chat, Embedding and Reranking preflight;
- one fixed private reranking TEST contract and database evidence vocabulary;
- current-source unit, integration, static, migration and independent P0/P1 review.

Excluded from completion claims:

- durable source-analysis leases, retry/cancel and evaluation;
- a general Chat `GENERAL`/`VECTOR`/`GRAPH`/`AUTO` contract;
- a runtime reranking consumer or activation path;
- WSL/private-provider, real-user browser, load, recovery and production acceptance.

## Product and security requirements

| ID | Requirement | Acceptance |
|---|---|---|
| K-EG-01 | Publish one approved changeset in one transaction | release/content/read-back receipt/changeset/outbox/idempotency all commit or none commit |
| K-EG-02 | Keep activation separate | publication leaves the graph inactive; activation requires exact verified receipt |
| K-EG-03 | Require independent review | author cannot review; non-blank normalized reason and review time are required |
| K-EG-04 | Close direct publication bypass | legacy HTTP path returns `410`; unlineaged releases are invisible to every consumer |
| K-EG-05 | Enforce one governed lineage | a consumable release has exactly one valid published changeset lineage |
| K-EG-06 | Enforce classification envelope | append, submit, review, publish, source, model persistence and read paths fail closed |
| K-EG-07 | Avoid policy or object oracles | unauthorized/integrity failures precede generic classification errors; rejected legacy content is redacted |
| K-EG-08 | Keep Neo4j rebuildable | PostgreSQL is canonical; shadow activation requires exact adapter/target/hash/count receipt |
| K-EG-09 | Split capability gates | local Neo4j, Chat, Embedding and Reranking are reported independently |
| K-EG-10 | Probe actual inference contracts | Chat strict JSON, Embedding vector and Reranking ordered scores are executed, not inferred from discovery |
| K-EG-11 | Bound the reranker probe | fixed route/body, mounted secret, host/TLS/private-network checks, no redirects, response cap |
| K-EG-12 | Preserve honest promotion state | local evidence cannot close WSL, external provider, real identity or production gates |

## TDD and negative-case checklist

- [x] Inject a pre-commit publication fault and prove zero release, node, edge, receipt, outbox and
  idempotency rows.
- [x] Race the same idempotency key and prove one canonical release.
- [x] Race two different approved changesets producing the same snapshot and prove one succeeds,
  one conflicts and only one publication evidence chain exists.
- [x] Prove publication is inactive until an exact receipt-backed activation.
- [x] Reject author-as-reviewer, blank decision reason, invalid state and tampered receipt.
- [x] Hide unlineaged release list/snapshot/export/projection/GraphRAG paths.
- [x] Revalidate governed lineage on idempotent publication, source-draft, general Chat and every
  release-pinned Sharing read/replay/publish/grant/invocation path.
- [x] Bind graph/changeset/product/version/grant idempotent replay to the exact actor, owner and
  resource; reject cross-principal and cross-resource reuse even when the request hash matches.
- [x] Treat Neo4j query results only as an ID selector; rebuild properties, classifications,
  provenance and edge endpoints from the exact PostgreSQL release before composing a prompt.
- [x] Apply/verify/remove the optional semiconductor seed through distinct maker/checker and
  authorized-publisher evidence, 536 exact operations, active-release and canonical-row hash
  read-back and an exact PostgreSQL receipt.
- [x] Delete one seed operation and mutate one canonical node without changing row counts; prove
  `verify` fails closed, then remove/reapply/verify/remove successfully.
- [x] Reject append and full-snapshot classification overflow under graph row locking.
- [x] Permit a reviewer to reject a legacy invalid proposal without returning its operation
  payload; reject approval.
- [x] Verify PDF ownership, finalized state, PDF media, size/hash and classification before analysis.
- [x] Require model proposal classification to equal the immutable source classification.
- [x] Reject confidential development inference before provider or Neo4j access.
- [x] Probe authenticated Neo4j with the fixed `RETURN 1` query.
- [x] Probe Chat with a strict JSON response contract and Embedding with one finite vector.
- [x] Execute the fixed private `/v1/rerank` request and reject 401, 404, duplicate/out-of-range
  indices, booleans, unsorted or non-finite/out-of-range scores.
- [x] Persist `RERANKING_INFERENCE` only under migration `0053`; refuse evidence-destroying
  downgrade.
- [x] Resolve and authorize the canonical graph/release before revealing whether the optional
  Neo4j adapter is available.

## Executed evidence

Evidence date: 2026-07-24, implementation commit `bd0ee22` based on `716fb6f`.

| Gate | Result | Boundary |
|---|---|---|
| Whole backend suite | `1,328 passed`, `60 skipped` | current source; skipped cases remain target-gated |
| Ruff format/lint | `375` files, pass | pinned local environment |
| Strict mypy | `358` source/test files, pass | pinned local environment |
| Static architecture/config/document gate | pass | source/local |
| Isolated PostgreSQL publication integration | `9 passed` | local PostgreSQL at revision `0053` |
| Migration compatibility | `0053 -> 0052 -> 0053`, sole head | isolated local PostgreSQL |
| Canonical `0001` reproducibility | two equal runs, SHA-256 `2f38f83bfbcaf57ad6bfffb1ab182617a0dfd1ecb0766e5723924ba361fbcaa6` | source/local |
| Optional governed seed | apply/verify/remove and deletion/content-drift negatives pass, `12 / 257 / 279 / 536`; graph envelope `CONFIDENTIAL` | isolated local PostgreSQL |
| Frontend | TypeScript, ESLint, `45 / 238`, build pass | source/local |
| Compose models | native Mac and `DOCKER_DEFAULT_PLATFORM=linux/amd64` core plus full local overlays render | config-only; not WSL runtime evidence |
| Neo4j authenticated fixed query | available, result `1` | current Mac local container |
| Chat strict JSON inference | available | current Mac native Ollama |
| Embedding inference | available, dimension `1024` | current Mac native Ollama |
| Reranking inference | unavailable: local routes do not implement fixed `/v1/rerank` | honest local capability result |
| Independent publication/security reviews | final `P0=0`, `P1=0`; one durable-source-job TOCTOU `P2` carried forward | read-only sub-agent reviews |

The `uv run` wrapper could not initialize its user cache inside the restricted filesystem sandbox.
The same locked `.venv` executables ran the exact gate arguments without dependency resolution.
The first final isolated-DB command used an invalid `file://` reference and failed before a
connection; the corrected canonical `file:` reference passed `9/9`.
Two later rerun attempts also stopped at authentication because an old temporary secret and the
container's post-initialization environment no longer matched the persisted audit-role password.
The dedicated audit role was synchronized to its test secret; the accepted rerun then passed
`9/9`. None of the connection-only failures is counted as product-test evidence.

## Open source follow-up

- [ ] Pin the actual System Settings probe connection to the vetted DNS address set while
  preserving original-host TLS verification. Pre-DNS allowlisting and address validation are
  implemented, but the default transport can resolve again at connect time.
- [ ] Replace synchronous source analysis with a durable leased job that pins the prepared
  base-release and ontology IDs, rejects eligibility before durable submission where possible,
  and revalidates both bindings atomically before draft persistence.

## External gates

- [ ] WSL amd64 exact-source/image import and revision `0053` migration.
- [ ] Private Neo4j DNS/TLS/credential/query evidence if Neo4j is externalized.
- [ ] Private Chat, Embedding and Reranking endpoint/model/credential/response evidence.
- [ ] Repeat DNS/TLS/credential/rebinding negatives against the actual private endpoint after the
  source address-pinning follow-up is implemented.
- [ ] Runtime restart evidence for implemented consumers; Reranking remains non-activatable.
- [ ] Authenticated Admin/Data Steward browser acceptance with distinct human identities.
- [ ] Parse and execute the PowerShell bootstrap on Windows; `pwsh` is unavailable on the current
  Mac, while source assertions cover the owner-only Windows ACL contract.
- [ ] Representative load, queue/restart, graph rebuild/drift and rollback evidence.

## Exit rule

The entry gate closes locally only when all in-scope source/DB checks pass, no independent P0/P1
finding remains and the focused commit contains code, migration, ADR and this checklist. Open
external gates are carried forward explicitly and do not justify a bypass. The next Phase may then
implement durable Knowledge capabilities without waiting for unavailable target infrastructure.
