# DataRiver continuous feature program control-plane handoff

Updated: 2026-08-29T15:46:27+09:00

## Live cumulative source state

- canonical worktree: `/Users/everreal/orca/workspaces/datariver-k9-implementation/CHAT-KG-Router-GPT56-Sol`
- Product: `567da6ba6e11f5b72126dffa3ccf7dac9621ef58`
- current Evidence candidate: this documentation successor (final SHA pending commit)
- worktree: clean
- source closure: `TEST_PC_ACCEPTED`
- TEST PC: exact accepted-state deploy and same-command rerun `6/6` PASS
- exact cumulative OCI: built/exported once and consumed on TEST
- current published Handoff / `origin/dev`: `462639897f79bffd15244419e5e2f03bcae84d37`
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
| CH-01~03 | Gemini 3.1 Pro High read-only audit; GPT-5.6 Sol High controlled implementation; Control Plane runtime closure | canonical | `567da6b` | TEST_PC_ACCEPTED | preserve full-result handoff contract; manual visual check awaits a connected browser surface |
| DQ-01/02 | GPT-5.6 Sol High controlled audit | clean read-only lane | `d0273c4` | NEEDS_DECISION | approve authoritative nullability plus durable recommendation/provenance aggregate; do not infer |
| AF-02~04 | GPT-5.6 Sol High controlled implementation/audit | integrated through `8d26fdd` | `d0273c4` | NEEDS_DECISION | approve durable trigger receipt/recovery, browser secret ownership, and exact System↔DAG contract |
| MP-01~06 | GPT-5.6 Sol High controlled audit | integrated through `d0273c4` | prior Wave C | NEEDS_DECISION / BLOCKED_EXTERNAL | approve delegation/tool-audit contract; perform exact TEST runtime acceptance |
| Control Plane | Codex | canonical | `4626398` | IN_PROGRESS | publish runtime Evidence/final Handoff and run one compatible accepted-state rerun |

Claude is not configured on this Orca host. Antigravity Gemini 3.1 Pro High was
started for CH-01~03 but reported an individual quota reset wait. The task and
clean worktree were preserved before the controlled GPT fallback; discovery is
not restarted from the feature-batch beginning.

## Canonical decisions and blockers

- CH-01/02/03 are `TEST_PC_ACCEPTED`. TEST proved 20 discovery candidates vs
  5 answer items, exact authorized Catalog total 2,003, distinct first/next
  pages, and routing/retrieval/reranking/composition/total timings. No connected
  browser surface was available, so manual visual acceptance is not claimed.
- DQ-01/02 remain `NEEDS_DECISION`. Safe authorized preview and idempotency
  slices are locally verified; canonical nullability metadata and an approved
  durable recommendation/audit aggregate do not exist.
- AF-02/03/04 remain `NEEDS_DECISION`. Reviewed DAG inventory is read-only;
  unsafe manual trigger now fails before request-body parsing/provider contact
  as `AIRFLOW_TRIGGER_SAFETY_HOLD` pending a durable execution contract.
- MP-01/02/03/05 are locally verified. MP-04/06 remain
  `NEEDS_DECISION`/`BLOCKED_EXTERNAL`: the fixed service-subject contract is
  preserved, while human delegation and immutable tool auditing are not
  approved.
- KG-02 is `NEEDS_DECISION`: no canonical mutable K9 schedule/Trigger Now API
  and approved capability contract exist.
- KG-07 is `NEEDS_DECISION`: no approved typed, release- and
  classification-fenced cross-graph materialization contract exists.
- AC-01 immutable audit-event sink and HM-03 historical trend read model remain
  `NEEDS_DECISION`; implemented safe portions stay locally verified.
- TEST PC exact artifact deploy and same-command rerun are accepted; final
  Evidence/Handoff-only successor rerun remains in progress.
- No origin/main move, Actual PREP/OPS execution, state reset/resecret,
  authorization widening or user metadata mutation is authorized.

## Dashboard and release readiness

- dashboard source:
  `/Users/everreal/.local/state/datariver/status-dashboard/status.json`
- dashboard URL: `http://127.0.0.1:39090`
- last HTTP check: `200`
- current status: `CHAT_FULL_RESULT_TEST_ACCEPTED`
- release readiness: `FINAL_EVIDENCE_HANDOFF_IN_PROGRESS`
- old Wave C OCI: `SUPERSEDED_INTERMEDIATE`
- final OCI: `EXACT_TEST_CONSUMED`
- TEST runtime acceptance: `6/6 PASS + same-command rerun PASS`

The next step is to commit the runtime Evidence, update only its Handoff pin,
prove `runtime_input_diff=NONE`, push the exact final Handoff to `origin/dev`,
and run one compatible accepted-state TEST rerun. The Wave C intermediate
remains prohibited, while Quality/Airflow/MCP safety decisions remain open.
