# DataRiver POC release cycle: DEV → PREP39083 → OPS

## Repeatable operator loop

```text
DEV macOS arm64
  develop → verify → Product/Evidence closeout → git push origin/dev
       ↓ source only
PREP WSL/Linux amd64
  git switch dev → git pull --ff-only origin dev
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
git switch dev
git pull --ff-only origin dev
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
| PREP fetch | `origin/dev`, fast-forward only |
| PREP runtime | `datariver-prep39083`, port 39083, Linux amd64 |
| external endpoints/proxy | target-local mode-0600 `.env.prep` |
| local secrets/derived topology | generated mode-0600 `.env.prep.runtime` |
| optional integrations | optional mode-0600 `.env.prep.optional` |
| PostgreSQL/pgvector and Neo4j | target-local persistent Compose volumes |
| managed graph refresh | DAILY shared snapshot when Studio DB is configured; otherwise DEFERRED |
| semantic generation | DB-fenced exact binding/generation owner, heartbeat, wait/reuse |

Multiple processes must share the same durable PostgreSQL store. Only one materializer owns an
exact semantic binding/generation; ownership loss aborts the producer and peers wait/reuse the
completed generation. No PREP setting disables this contract.

## Gates

1. DEV: source gates, new Product/Evidence, exact DEV OCI/browser and clean secret scan.
2. Git: handoff-only release identity/docs, source-check, commit and push to `origin/dev`.
3. PREP deploy: native amd64, target-state classification, separate build/runtime proxy policy,
   exact Product image, read-only provider preflight, attempt receipt, isolated Compose, idempotent
   bootstrap and staged bounded smoke. A failed smoke resumes through the same command. Managed
   Assets are strict only when the feature-dependent Studio DB authority is configured; otherwise
   core boot reports K9 DEFERRED.

Cross-release resume treats generated target secrets and canonical volume/topology identities as
ownership, while tracked `FIXED` values remain descendant release configuration. Ownership and Git
ancestry are proven before the new release writes its runtime configuration. Legacy V1 unfinished
receipts migrate automatically to the ownership-only V2 contract; operators never delete or edit a
receipt, runtime secret, container, database, or volume to apply a legitimate release update.
4. PREP acceptance: browser, representative routes, Router 60, Boundary 8 and MCP/auth.
5. Promotion: exact running image inspection, `images.tar`, manifest and bundle SHA-256.
6. OPS: artifact-only verification, image-ID match, target config, `--no-build`, smoke and rollback.

Detailed commands are in [PREP39083 one-command deployment](64_PREP39083_HANDOFF.md) and
[PREP39083 to OPS image promotion](65_PREP_TO_OPS_PROMOTION.md).
