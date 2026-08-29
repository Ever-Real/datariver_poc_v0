# DataRiver POC release cycle: DEV → PREP39083 → OPS

## Repeatable operator loop

```text
DEV macOS arm64
  develop → verify → Product checkpoint → build exact linux/amd64 image once
  → export/checksum exact Product archive → Evidence closeout → git push origin/dev
  → exact verified Handoff → fast-forward promotion to origin/main
       ↓ promoted Handoff plus approved checksum-pinned Product archive
PREP WSL/Linux amd64
  git switch main → git pull --ff-only origin main
  → stage archive at release.json path
  → ./scripts/prep39083 deploy
  → browser/explicit acceptance
  → ./scripts/prep39083 export
       ↓ checksum-approved exact tested images
OPS Linux amd64
  verify bundle → docker load → Compose --no-build → smoke/browser
```

DEV never claims PREP or OPS runtime acceptance. PREP consumes the exact artifact already verified
on DEV and never rebuilds it. PREP never exports an untested artifact. OPS never rebuilds the
release. The existing 39080 project is not stopped, overwritten or volume-shared by
PREP39083. DataHub, Airflow, MinIO and OpenAI-compatible inference remain external services.

## Stable PREP command

After the one-time `.env.prep` configuration and staging the separately delivered archive at the
exact ignored path in `release.json`, normal release updates require only:

```bash
git switch main
git pull --ff-only origin main
./scripts/prep39083 deploy
```

The tracked release identity eliminates shell `PRODUCT_SHA`/`IMAGE_REF` state. The ignored operator
and generated runtime environments survive Git updates. New required external keys fail by name;
new generated keys are created once; default/fixed keys update automatically; existing operator
values are never overwritten. The same deploy command classifies and reconciles a clean host,
accepted running/stopped stacks, exact-release reruns and safely empty failed-install residue.
Ambiguous or durable unaccepted state stops without deleting a volume.

## Authority and state

| Concern | Owner |
|---|---|
| runtime source | accepted Product Git SHA and immutable archive/checksum/manifest identity in `release.json` |
| verification narrative | accepted Evidence Git SHA in `release.json` |
| development integration | `origin/dev` |
| GitHub default / PREP promotion | `origin/main`, fast-forward only |
| PREP runtime | `datariver-prep39083`, port 39083, Linux amd64 |
| external endpoints/proxy | target-local mode-0600 `.env.prep` |
| local secrets/derived topology | generated mode-0600 `.env.prep.runtime` |
| optional integrations | optional mode-0600 `.env.prep.optional` |
| PostgreSQL/pgvector and Neo4j | target-local persistent Compose volumes |
| managed graph refresh | built-in DAILY shared snapshot, local PostgreSQL policies and local Neo4j projection |
| Change History | configured DataHub Kafka, auto-discovered MCL/Registry/source identity, durable earliest-retained checkpoint |
| Quality | DataHub Assertions read; existing Airflow/GX dispatch when configured |
| semantic generation | DB-fenced exact binding/generation owner, heartbeat, wait/reuse |

Multiple processes must share the same durable PostgreSQL store. Only one materializer owns an
exact semantic binding/generation; ownership loss aborts the producer and peers wait/reuse the
completed generation. No PREP setting disables this contract.

## Gates

1. DEV: source gates, new Product checkpoint, exact linux/amd64 OCI/browser and clean secret scan;
   save that already verified image once as the approved archive and bind its archive SHA-256,
   child manifest digest, config digest, platform and revision in the Handoff.
2. Git: handoff-only release identity/docs, source-check, commit and push to `origin/dev`; then
   fast-forward `origin/main` to that exact verified Handoff without rebuilding or modifying it.
3. PREP deploy: native amd64, target-state classification, separate runtime proxy policy, exact
   archive checksum/content verification, exact Product image load/inspection, read-only provider
   preflight, attempt receipt, isolated Compose, idempotent
   bootstrap and staged bounded smoke. A failed smoke resumes through the same command. Managed
   Assets and semantic index are strict built-in READY gates. MCL discovery/checkpoint readiness is
   also required; optional Airflow/MinIO capabilities report DEFERRED without adding containers.
   Startup catch-up repeats bounded MCL batches under the existing single-owner lock until the
   observed high watermark is reached; it never resets a checkpoint or defers an oversized
   retained backlog to later daily boundaries. Read-only `doctor` collects all independent
   provider results in one matrix, while `deploy` still blocks before mutation on any required
   failure.
   Doctor verifies the same promoted archive and loads it only when the exact Product image is
   absent, or reuses an exact manifest/platform/revision match, before running its disposable
   collect-all container. This diagnostic load/cache action never starts or mutates Product state
   services. Deploy never builds or pulls an image and has no rebuild fallback.
   Both paths discard ambient application and Compose variables from the interactive shell. The
   tracked environment contract and target-owned env files exclusively define Product, provider,
   image, platform, project, bind, and port values; only reviewed host/Docker connectivity keys are
   inherited. The fully resolved Compose identity and provider projection are checked before the
   image gate. Doctor collect-all and deploy fail-fast provider checks then share the same hardened
   direct `docker run --rm` executor and exact private effective env file; neither provider gate
   depends on the Web Compose service environment or creates Product volumes.
   Authenticated smoke keeps host-health transport on loopback but projects the exact tracked
   `POC_PUBLIC_ORIGIN` into every state-changing request `Origin` header; origin rejection and
   administrator credential rejection remain separate bounded failure classes.

Cross-release resume treats generated target secrets and canonical volume/topology identities as
ownership, while tracked `FIXED` values remain descendant release configuration. Ownership and Git
ancestry are proven before the new release writes its runtime configuration. Legacy V1 unfinished
receipts migrate automatically to the ownership-only V2 contract; operators never delete or edit a
receipt, runtime secret, container, database, or volume to apply a legitimate release update.
Accepted-state reuse also requires marker/ACCEPTED-receipt agreement, exact owned volumes and a
compatible Product/Handoff ancestry; marker presence alone is not trusted. Before Product DDL, the
bounded `public.poc_*` schema surface is fingerprinted while non-owned database objects and row
cardinality are ignored. Unknown, partial, receipt-mismatched or newer owned state fails before
mutation.

K9 uses a bounded stable-observation fence because the pinned DataHub source APIs have no reliable
global generation primitive. Two consecutive complete inventory/metadata/lineage fingerprints
must match. Repeated drift produces a typed terminal failure, does not promote semantic or graph
staging state, and retains the prior LKG for convergence on a later stable cycle.
4. PREP acceptance: browser, representative routes, Router 60, Boundary 8 and MCP/auth.
5. Promotion: exact running image inspection, `images.tar`, manifest and bundle SHA-256.
6. OPS: artifact-only verification, image-ID match, target config, `--no-build`, smoke and rollback.

## Build-once Product artifact

At the clean Product checkpoint, after the exact linux/amd64 image has passed its Product gates,
export that existing image without rebuilding it:

```bash
uv run --frozen python scripts/prep39083_release.py web-artifact-export \
  --product-sha <exact-product-sha> \
  --output-dir dist/prep39083-web-<exact-product-sha>
```

The command requires `HEAD == Product`, a clean worktree, the exact local Product tag, linux/amd64
platform and matching OCI revision. It uses `docker image save --platform linux/amd64`, validates
the bounded OCI/Docker archive, and emits the archive, SHA-256 sidecar and manifest fields for
`release.json`. It never builds, pulls or loads. The archive is transferred separately through the
approved artifact medium and staged at its manifest-pinned ignored PREP path. Missing or mismatched
artifacts are terminal pre-start failures; neither doctor nor deploy falls back to source build.

## Cumulative Product closure and artifact invalidation

An OCI artifact is exact only for its Product SHA. Any descendant change to a
runtime input makes that earlier artifact ineligible for the descendant release,
even when the original archive checksum and OCI identity remain valid. Never
reuse, retag, or copy an earlier `release.json` identity onto a newer Product.

For the continuous feature program, the final artifact is created only after:

1. cumulative Product source closure;
2. Chat full authorized-result exploration contract closure;
3. Quality, Airflow, and MCP safety holds are recorded as `NEEDS_DECISION`
   rather than falsely completed;
4. required local integration and static gates pass;
5. the Product checkpoint is clean and immutable; and
6. TEST PC transport is available.

Then build and verify one fresh linux/amd64 image, export its exact archive,
create Evidence and Handoff-only commits with `runtime_input_diff=NONE`, push
the exact Handoff to `origin/dev`, and perform the canonical accepted-state TEST
redeploy. The previously published Wave C artifact is intermediate evidence only
and is never reused as this final artifact.

## Controlled `dev` → `main` promotion

Feature and Product development stays on `dev`; development pull requests normally target `dev`.
`main` is not an ordinary feature-merge destination. Given one exact verified Handoff:

```bash
git fetch origin dev main

CANDIDATE=<exact-verified-dev-handoff-sha>
PRODUCT=<product-sha-from-candidate-release-json>
EVIDENCE=<evidence-sha-from-candidate-release-json>
VERIFY_DIR=../datariver-prep39083-promotion-check

git merge-base --is-ancestor origin/main "$CANDIDATE"
git worktree add --detach "$VERIFY_DIR" "$CANDIDATE"
(
  cd "$VERIFY_DIR"
  uv run --frozen python scripts/prep39083_release.py source-check \
    --product-sha "$PRODUCT" --evidence-sha "$EVIDENCE"
)
git worktree remove "$VERIFY_DIR"
git push origin "$CANDIDATE":refs/heads/main
```

The ancestry command is the fast-forward gate: a non-descendant candidate is rejected before the
push. Never force-push, squash, rebase published release history, cherry-pick Product commits into
`main`, or create a merge commit only for promotion. Advancing `dev` after promotion leaves `main`
and the current PREP candidate unchanged until this procedure is run again. Candidate/accepted tags
may be added as immutable audit references but are not required for deployment.

Changing GitHub's default branch to `main` does not change OPS authority: OPS receives only the
checksum-verified exact image actually accepted and exported on PREP, with no rebuild.

Detailed commands are in [PREP39083 one-command deployment](64_PREP39083_HANDOFF.md) and
[PREP39083 to OPS image promotion](65_PREP_TO_OPS_PROMOTION.md).
