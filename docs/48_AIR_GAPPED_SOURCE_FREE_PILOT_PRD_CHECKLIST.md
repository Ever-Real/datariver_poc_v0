# Air-gapped source-free amd64 Pilot PRD/checklist

Status: local implementation complete; target evidence remains open.

## Outcome and non-goals

An operator builds an exact clean commit on the amd64 preparation PC, transfers
`release.tar.gz`, its checksum and `deploy_pilot.sh`, and deploys it below
`/home/datariver/`. The isolated server stores release assets, one host-local `.env`, secret files
and named volumes, but no source checkout or build context.

The export commit is the exact `main` checkpoint promoted only after the preparation PC has passed
`prep-update`, `prep-check` and an unchanged second `prep-check`. Mac-to-preparation delivery remains
source-only through `origin/dev`; the Pilot archive is a separate preparation-to-operations release
boundary.

This does not provide HA, WAF, production Secret Manager, database restore acceptance, enterprise
IdP onboarding or an IP-trusted TLS certificate. It does not bundle independently operated
DataHub/S3/Airflow/LLM/graph/observability systems.

## Requirements

- **PILOT-REL-001** — Export requires `--commit <full-sha>`, a clean matching checkout and a native
  Linux amd64 Docker daemon.
- **PILOT-REL-002** — The archive includes backend (and all locked Python libraries), built web
  assets, Keycloak, PostgreSQL init and digest-pinned Redis runtime images.
- **PILOT-REL-003** — The archive has SHA-256 checksums and an image inventory binding every local
  tag to an image ID and `linux/amd64`.
- **PILOT-REL-004** — No standalone source checkout/bundle, Git metadata, real environment, secret,
  data or volume is present in the archive. Executable application modules remain inside the
  runtime image.
- **PILOT-DEP-001** — Target Compose has no `build:` and uses `pull_policy: never`; deployment uses
  `--no-build` and never performs a registry pull.
- **PILOT-DEP-002** — PostgreSQL, Redis and API are internal only. Web and Keycloak publish only
  loopback upstream ports; an approved HTTPS ingress owns any LAN listener.
- **PILOT-DEP-003** — Alembic runs to `head` as a one-shot container after PostgreSQL health and
  before application start. Failure aborts deployment.
- **PILOT-DEP-004** — Existing named volumes are preserved. Neither script deletes databases,
  Drafts, Releases, uploaded objects or Docker volumes.
- **PILOT-CFG-001** — `.env` contains non-secret values and `file:/run/secrets/...` references;
  literal credentials live only in owner-readable files below `secrets/`.
- **PILOT-CFG-002** — Export never packages the host `.env` or `secrets/`. First deployment stops
  until required operator-supplied provider credentials and reviewed origins are present.
- **PILOT-SEC-001** — Direct private-IP HTTP is only a server-local smoke path. Browser login and
  `crypto.subtle` features need an approved HTTPS secure context.
- **PILOT-OPS-001** — The release records the exact Git commit. Production promotion still requires
  `main` plus the existing production gates.
- **PILOT-OPS-002** — Admin displays `/home/datariver/.env` and the `source-free-pilot` lifecycle
  from the running Settings snapshot. A successful fixed probe may copy the exact
  `deploy_pilot.sh` handoff, but the API never executes a host command or receives Docker control.

## Operator sequence

```bash
# Preparation PC: exact clean approved main checkpoint on native Linux amd64
./scripts/export_release.sh \
  --commit <FULL_GIT_SHA> \
  --output /approved-transfer/datariver-<12-char-sha> \
  --accept-redis-image-redistribution

# Copy these three files through the approved transfer path:
# release.tar.gz, release.tar.gz.sha256, deploy_pilot.sh

# Pilot server
chmod 0755 ./deploy_pilot.sh
DATARIVER_PILOT_HOME=/home/datariver \
  ./deploy_pilot.sh ./release.tar.gz
```

On the first run, complete `/home/datariver/.env` and the explicitly reported files under
`/home/datariver/secrets/`, then rerun the same deploy command. Do not copy the preparation PC's
development secrets.

For a redeploy or an idempotence check, invoke the same `deploy_pilot.sh` command with the same
verified archive. It loads the checked image bundle but performs no build or pull, and it moves the
`current` pointer only after health succeeds. The archive is produced with `docker image save`; it
must never be replaced by `docker export`, `docker container export`, `docker commit` or a captured
running container. Keep the previous release and a compatible PostgreSQL backup for rollback.

## Rollback boundary

Keep the previous release directory/archive, image tags, `.env` backup and a tested PostgreSQL
backup. If the new migration has not run, redeploy the previous archive with the same command. If
Alembic has advanced the database, restore the compatible database backup before starting the
previous images; do not assume application-image rollback is schema rollback. Restore the prior
`current`/`docker-compose.yaml` link only after readiness succeeds. Never remove
`datariver-pilot_postgres-data`, Keycloak, Redis delivery or Knowledge spool volumes as a rollback
shortcut.

## Acceptance checklist

- [x] Static tests prove archive/Compose have no build or pull path and no API/DB/Redis publication.
- [x] Shell syntax, Ruff, strict mypy, relevant pytest and `scripts/verify_static.py` pass.
- [ ] Preparation PC produces an amd64 archive for the requested full commit.
- [ ] The requested full commit is the exact accepted `main` checkpoint after one `prep-update` and
      two unchanged successful `prep-check` runs.
- [ ] Target verifies the archive checksum and every loaded image as `linux/amd64`.
- [ ] Reapplying the same archive through the same deploy command preserves host-local environment,
      secrets and volumes and changes `current` only after readiness succeeds.
- [ ] Empty-volume migration and local identity bootstrap succeed.
- [ ] Existing-volume update preserves DB/Draft/Release state and passes readiness.
- [ ] Target backup/restore and rollback rehearsal is recorded.
- [ ] DataHub/S3/Airflow/LLM reachability and browser mixed-content evidence are recorded.
- [ ] Approved HTTPS edge/certificate, client trust and real browser login are recorded.
- [ ] Redis redistribution approval for the exact bundled digest is recorded.

The unchecked target items are `TARGET_EXTERNAL_GATE`; local source tests must not report them as
successful.
