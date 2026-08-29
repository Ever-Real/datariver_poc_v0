# DataRiver continuous feature program control-plane handoff

Updated: 2026-08-29T20:18:00+09:00

## Live cumulative source state

- canonical worktree: `/Users/everreal/orca/workspaces/datariver-k9-implementation/CHAT-KG-Router-GPT56-Sol`
- accepted baseline Product: `567da6ba6e11f5b72126dffa3ccf7dac9621ef58`
- cumulative source candidate: `f9aa8df` (integration source complete; this documentation commit will be the clean Product checkpoint)
- Evidence: `66bca666b15c36b23d694ce20415be573024d917`
- worktree: only this documentation update remains; release manifest stays pinned to the accepted baseline until the new exact artifact is exported
- source closure: `TEST_PC_ACCEPTED`
- TEST PC: exact accepted-state deploy and same-command rerun `6/6` PASS
- exact cumulative OCI: built/exported once and consumed on TEST
- current published Handoff / `origin/dev`: `28c14424e9d5279f0c3a40b436e9912f3d5e541a`
- `origin/main`: `17f32a52de79077c433bf0beaabac81a48e46062` (frozen)
- Actual PREP: NOT EXECUTED
- Actual OPS: NOT EXECUTED

## Last published Wave C artifact — INTERMEDIATE / NOT FINAL

- Product: `1ad090d084b34906438e281ee208f9ec49d9a95f`
- Evidence: `32af64f84bb0140cc53bdae1674acff489570c69`
- Handoff / `origin/dev`: `f9c9d7595c70b70d41728e01ce66cc0406e92f28`
- platform: `linux/amd64`
- archive SHA-256: `dec34d0d532e24fb8236f8c115fa0cf699dbdef79c6bdd377b043bceda10b3f3`
- exact scope: Product `1ad090d084b34906438e281ee208f9ec49d9a95f` only
- final reuse: `PROHIBITED`

The archive remains immutable evidence for its exact Product. Descendant runtime
inputs changed after that Product checkpoint, so it must not be reused,
relabeled, or promoted as the final cumulative artifact. A source check against
the current cumulative HEAD fails closed for this expected drift.

## Verification at the cumulative checkpoint

- UI: `731/731` PASS
- Node Product: `201/201` PASS
- release/deploy/handoff/migration-integrity: `138/138` PASS
- PREP smoke: `34/34` PASS
- Chat focused backend: `90/90` PASS
- Chat/Catalog/Admin focused UI: `78/78` PASS
- build, POC build, typecheck, full ESLint, changed-source Ruff/strict mypy and
  static/source contract: PASS
- Product→Evidence runtime input diff: `NONE`
- exact OCI: `linux/amd64`; revision equals Product; archive SHA-256
  `2c8246d5bab1cb52c956eba95f11c325dcf855a79f901d7f022dee79d6f13df6`
- TEST PC cumulative API/runtime acceptance: PASS; no connected browser surface,
  so no manual visual PASS is claimed

## Active workstreams and ownership

| Workstream | Owner/model | Worktree | Base | State | Exact next action |
| --- | --- | --- | --- | --- | --- |
| CH-01/02 | prior controlled implementation and TEST closure | canonical | `567da6b` | TEST_PC_ACCEPTED | preserve exact total/pagination/evidence/authorization contract |
| CH-PERF-01~03 | GPT-5.6 Sol High implementation + Control Plane review | canonical through `1c5e982` | `28c1442` | IN_PROGRESS | prompt assembly, request serialization, provider wait and response-body attribution are local verified; full Catalog pagination remains preserved and same-provider TEST measurement is still required |
| DQ-01 | Control Plane read-only contract audit | canonical preview foundation | `28c1442` | IN_PROGRESS | exact cross-page selection, dry-preview fence, exact Tag/Term identity and apply receipt remain the next bundle; nullability is explicitly unavailable |
| AF-02~04 | GPT-5.6 Sol High controlled implementation + independent audit PASS | canonical through `4fec59a` | `28c1442` | LOCAL_VERIFIED | deployment-managed sanitized connection status, durable allowlisted actions and explicit WORKSPACE_WIDE scope are verified; external provider runtime remains blocked and persistent per-System binding is a separate minimal decision |
| MP-04/06 | GPT-5.6 Sol High correction + Gemini 3.1 Pro High final independent re-audit + Control Plane | canonical through `dade6fd` | `9d09e26` | LOCAL_VERIFIED | exact session/Origin, user∩service scope, feature-policy-consistent discovery/execution, AbortSignal and immutable hashed V3 receipt; closed-network runtime remains external |
| HM-03 current | GPT-5.6 Sol High implementation + Control Plane review | canonical through `055f3a2` | `28c1442` | LOCAL_VERIFIED | include current-week authorized summary in the cumulative TEST artifact; historical trend remains separate |
| AC-01 durable receipt | GPT-5.6 Sol xhigh implementation + independent re-audit PASS | canonical through `9d09e26` | `d381e21` | LOCAL_VERIFIED | include in the next exact Product artifact and accepted-state TEST redeploy |
| DQ-02 recommendation | GPT-5.6 Sol High implementation + independent audit; Control Plane integration | canonical through `184dc01` | `1c5e982` | LOCAL_VERIFIED | exact authorized local vocabulary, preview/reject/approve/bulk confirmation, atomic CR/audit/replay and 0101 contract; TEST migration/browser acceptance pending |
| Control Plane | Codex | canonical at `f9aa8df` plus this evidence update | `28c1442` | IN_PROGRESS | create a new exact Product artifact, then revalidate the existing TEST accepted state including prior revision→0101 and same-command rerun |

Antigravity Gemini 3.1 Pro High became available for the bounded Chat call-path
analysis and the single final MCP independent re-audit. The Chat analysis found
optimization candidates but no same-provider evidence, so no speculative
provider-call collapse or concurrency change entered this Product. MCP re-audit
passed six areas and found one exact `tools/list` feature-policy mismatch; the
Control Plane corrected only that blocker and proved the focused deny path.

## Canonical decisions and blockers

- CH-01/02/03 are `TEST_PC_ACCEPTED`. TEST proved 20 discovery candidates vs
  5 answer items, exact authorized Catalog total 2,003, distinct first/next
  pages, and routing/retrieval/reranking/composition/total timings. No connected
  browser surface was available, so manual visual acceptance is not claimed.
- DQ-01 remains `IN_PROGRESS`. Its current-principal authorized Table preview
  proves an exact first-page total and opaque cursor pages, but exact
  cross-page selection/exclusion, dry-preview source/auth fence, exact Tag/Term
  identity and final apply receipt remain the next bundle. The current
  provider projection has no authoritative nullability field, so
  `NULLABILITY_SOURCE_UNAVAILABLE` is explicit instead of inferred.
- DQ-02 is `LOCAL_VERIFIED` through `7081f68`, `36f0b3e` and `184dc01`.
  Recommendation candidates use only current authorized local vocabulary UUIDs
  and exact asset/Column identity. Approval creates the canonical Governance CR
  atomically with recommendation decisions, audit events and actor-bound replay;
  it does not mutate DataHub metadata. Automatic application alone remains the
  minimal policy decision. Migration `0101` and its regenerated `0001` passed
  focused/static/checksum gates; the preserved TEST accepted database must
  still prove prior revision→0101 with data retention and idempotent rerun.
- AF-02/03/04 safe local scope is verified through `4fec59a`. ADR-0048 remains
  authoritative: the deployment environment is the single connector source,
  so no UI CRUD or second desired-state store was added. The server projects a
  bounded sanitized connection status, the reviewed DAG allowlist retains
  canonical admin authorization and durable idempotent audit, and every
  current execution is explicitly `WORKSPACE_WIDE`. `AIRFLOW` remains a
  connector configuration identifier rather than a fabricated domain System
  UUID; no name matching or implicit linkage exists. Node `81/81`, Admin UI
  `15/15`, typecheck and ESLint pass, and an independent audit is PASS. A live
  Airflow provider remains `BLOCKED_EXTERNAL`; a future persistent per-System
  binding alone remains a minimal policy decision.
- MP-01/02/03/04/05 and the local portion of MP-06 are `LOCAL_VERIFIED` through
  `9dce364`, `9d92e67` and `dade6fd`. The rejected `0ad645e`
  caller-grant/JSONL broker was not integrated. The bounded replacement keeps
  the bearer endpoint compatible and adds a canonical session+Origin user
  boundary, exact user/service capability-grade-system-table-feature
  intersection, deny-before-provider, AbortSignal and hashes-only immutable V3
  receipt. Gemini final re-audit found only that user `tools/list` did not apply
  the same native Knowledge feature policy as `tools/call`; `dade6fd` unifies
  both through one predicate and the focused denial test passes. Mutation stays
  disabled pending its explicit policy; closed-network runtime is external.
- Chat Catalog full-result pagination remains TEST accepted. Commits `19254cc`
  and `1c5e982` add honest prompt-assembly, request-serialization,
  response-header/provider-wait and response-body timing while keeping the four
  low-level timings collapsed by default. Retrieval order, authorization,
  totals, cursors and evidence are unchanged. Canonical POC `33/33`, Chat UI
  `29/29`, typecheck and ESLint pass; this remains instrumentation rather than a
  proven latency improvement until the same TEST provider is measured. Gemini's
  bounded read-only call-path analysis suggested context-call collapse and
  concurrent independent retrieval, but both were withheld because routing
  quality and shared connection safety require same-provider evidence first.
- KG-02 is `NEEDS_DECISION`: no canonical mutable K9 schedule/Trigger Now API
  and approved capability contract exist.
- KG-07 is `NEEDS_DECISION`: no approved typed, release- and
  classification-fenced cross-graph materialization contract exists.
- AC-01 self-service local password change and its durable receipt are locally
  verified and integrated through `9d09e26`, including current-password
  verification, bounded policy, Argon2id reuse, all-session revocation, atomic
  credential/session/event rollback, immutable receipt/event guards, exact
  Product-owned V1-to-V2 convergence, malformed/newer fail-closed behavior and
  zero disposable PostgreSQL residue. Independent re-audit is PASS. HM-03
  current views are separate from the
  still-unapproved historical trend aggregation policy.
- TEST PC exact artifact deploy, same-command rerun, and final Handoff-only
  successor rerun are all accepted.
- No origin/main move, Actual PREP/OPS execution, state reset/resecret,
  authorization widening or user metadata mutation is authorized.

## Current integration bundle closure

The Product source bundle contains only the already-open DQ-02, Airflow, MCP,
Chat instrumentation and their bounded integration corrections. No Home/Search
or other new feature lane was opened.

- Node Product: `218/218` PASS with `10` explicit external PostgreSQL skips.
- full UI: `94` files, `737/737` PASS.
- DQ-02 focused backend: `58/58` PASS with `4` isolated PostgreSQL skips;
  the independent candidate evidence already proves those four against one
  disposable PostgreSQL database.
- PREP release/deploy/handoff: `136/136` PASS; PREP smoke: `34/34` PASS.
- changed Python surface strict mypy: `34` files PASS; Ruff lint PASS.
- TypeScript typecheck, full ESLint, POC build, application build, static/source
  integrity and accepted migration checksum gate: PASS.
- initial migration regeneration was deterministic and produced no diff.

The full Python suite reported `4,157` PASS, `125` explicit environment skips
and `19` failures. Two failures were current-head revision expectations for the
new `0101` head; both were corrected and focused PASS. The remaining `17` are
pre-existing origin/dev baseline failures in unchanged dev-host secret
fixtures, historical migration assertions, three missing documented source-host
environment keys and the pilot bind-message assertion. They are recorded as
baseline and are not mixed into this bounded Product correction. No Product
runtime fallback or assertion weakening was added.

The TEST gate is stricter than the local migration fixture: the preserved
accepted database must prove its prior revision to `0101`, Product-owned schema
fingerprint, existing row/DQ record preservation and same-command safe rerun.
Migration failure is terminal; reset/resecret is prohibited.

## Dashboard and release readiness

- dashboard source:
  `/Users/everreal/.local/state/datariver/status-dashboard/status.json`
- dashboard URL: `http://127.0.0.1:39090`
- last HTTP check: `200`
- current status: `INTEGRATION_BUNDLE_LOCAL_VERIFIED`
- release readiness: `NEW_EXACT_PRODUCT_ARTIFACT_PENDING`
- old Wave C OCI: `SUPERSEDED_INTERMEDIATE`
- accepted baseline OCI: `EXACT_TEST_CONSUMED`
- next OCI: `MUST_BE_REBUILT_ONCE_FROM_FINAL_NEW_PRODUCT`; no prior Wave C or
  baseline archive may be relabeled or reused for changed Product source
- TEST runtime acceptance: `6/6 PASS + same-command rerun PASS`

The next step is to commit this clean Product checkpoint, build/export exactly
one new `linux/amd64` image for that SHA, then create the Evidence and Handoff
successors with `runtime_input_diff=NONE`. Only that new archive may be
transferred for a no-build canonical redeploy of the existing TEST accepted
state. The Wave C intermediate and accepted baseline OCI remain immutable
evidence for their own Product revisions and are not reused.
