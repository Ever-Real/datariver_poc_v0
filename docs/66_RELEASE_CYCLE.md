# DataRiver POC release cycle: DEV → PREP39083 → OPS

## One-way checkpoints

```text
DEV macOS arm64
  verified Product + Evidence → clean handoff commit → origin/dev
        ↓ source only
PREP WSL/Linux amd64
  exact Product build → 39083 smoke/browser/full acceptance
  → inspect running image IDs → save exact tested images + checksum/manifest
        ↓ approved artifact transfer only
OPS Linux amd64
  checksum verify → docker load → Compose --no-build → smoke/browser
```

DEV never claims PREP or OPS runtime acceptance. PREP never exports an untested build. OPS never
rebuilds the release. The existing 39080 project is not stopped, overwritten or volume-shared by
PREP39083. DataHub, Airflow, MinIO and OpenAI-compatible inference remain configured external
services at every target.

## Authority and state

| Concern | Owner |
|---|---|
| runtime source | accepted Product Git SHA |
| verification narrative/results | accepted Evidence Git SHA |
| PREP fetch | `origin/dev`, fast-forward only |
| PREP runtime | `datariver-prep39083`, port 39083, Linux amd64 |
| OPS runtime | `datariver-ops39083`, exact loaded PREP image IDs |
| credentials/provider endpoints | target-local mode-0600 ignored env file |
| PostgreSQL/pgvector and Neo4j | target-local persistent Compose volumes |
| managed graph refresh | DAILY shared snapshot with validated atomic promotion |
| semantic generation | DB-fenced exact binding/generation owner, heartbeat, wait/reuse |

Multiple processes must point at the same durable PostgreSQL store. The accepted KG2 protection
allows only one materializer for an exact semantic binding/generation; ownership loss aborts the
producer and peers wait/reuse the completed generation. No PREP/OPS setting disables this contract.

## Gates

1. DEV: Product/Evidence checkpoint, source gates, exact arm64 DEV OCI/browser and clean secret scan.
2. Git: handoff-only diff, source-check, commit and push to `origin/dev`.
3. PREP: Linux/amd64 proof, isolated Compose config, exact Product OCI, HTTP/login/providers,
   managed Assets, Cytoscape, representative routes, Router 60, Boundary 8 and MCP/auth.
4. Promotion: exact running image inspection, `images.tar`, manifest and bundle SHA-256.
5. OPS: artifact-only verification, image-ID match, target config, `--no-build`, smoke and rollback
   anchor.

Detailed copy/paste commands are in [PREP39083 source build and acceptance](64_PREP39083_HANDOFF.md)
and [PREP39083 to OPS image promotion](65_PREP_TO_OPS_PROMOTION.md).
