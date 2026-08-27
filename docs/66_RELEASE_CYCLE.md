# DataRiver POC release cycle: DEV → PREP39083 → OPS

## Repeatable operator loop

```text
DEV macOS arm64
  develop → verify → Product/Evidence closeout → git push origin/dev
  → exact verified Handoff → fast-forward promotion to origin/main
       ↓ promoted source only
PREP WSL/Linux amd64
  git switch main → git pull --ff-only origin main
  → ./scripts/prep39083 deploy
  → browser/explicit acceptance
  → ./scripts/prep39083 export
       ↓ checksum-approved exact tested images
OPS Linux amd64
  verify bundle → docker load → Compose --no-build → smoke/browser
```

DEV never claims PREP or OPS runtime acceptance. PREP never exports an untested build. OPS never
rebuilds the release. The existing 39080 project is not stopped, overwritten or volume-shared by
PREP39083. DataHub, Airflow, MinIO and OpenAI-compatible inference remain external services.

## Stable PREP command

After the one-time `.env.prep` configuration, normal release updates require only:

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
| runtime source | accepted Product Git SHA in `release.json` |
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

1. DEV: source gates, new Product/Evidence, exact DEV OCI/browser and clean secret scan.
2. Git: handoff-only release identity/docs, source-check, commit and push to `origin/dev`; then
   fast-forward `origin/main` to that exact verified Handoff without rebuilding or modifying it.
3. PREP deploy: native amd64, target-state classification, separate build/runtime proxy policy,
   exact Product image, read-only provider preflight, attempt receipt, isolated Compose, idempotent
   bootstrap and staged bounded smoke. A failed smoke resumes through the same command. Managed
   Assets and semantic index are strict built-in READY gates. MCL discovery/checkpoint readiness is
   also required; optional Airflow/MinIO capabilities report DEFERRED without adding containers.
   Startup catch-up repeats bounded MCL batches under the existing single-owner lock until the
   observed high watermark is reached; it never resets a checkpoint or defers an oversized
   retained backlog to later daily boundaries. Read-only `doctor` collects all independent
   provider results in one matrix, while `deploy` still blocks before mutation on any required
   failure.

Cross-release resume treats generated target secrets and canonical volume/topology identities as
ownership, while tracked `FIXED` values remain descendant release configuration. Ownership and Git
ancestry are proven before the new release writes its runtime configuration. Legacy V1 unfinished
receipts migrate automatically to the ownership-only V2 contract; operators never delete or edit a
receipt, runtime secret, container, database, or volume to apply a legitimate release update.
4. PREP acceptance: browser, representative routes, Router 60, Boundary 8 and MCP/auth.
5. Promotion: exact running image inspection, `images.tar`, manifest and bundle SHA-256.
6. OPS: artifact-only verification, image-ID match, target config, `--no-build`, smoke and rollback.

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
