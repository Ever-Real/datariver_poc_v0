# PREP doctor/deploy provider-preflight parity evidence

Recorded at `2026-08-27T11:16:15Z` for Product
`79efaf7523e96c8ae15690f6a9c1a1eca9ffc426` on `dev`. The controlled PREP branch
`origin/main` remained fixed at `dd200d40c75392879e0cabc0b5baf2179c85cf9b`.

## Proven root cause and correction

Actual PREP proved that doctor passed every provider stage and the immediately following deploy
failed `WEB_INTRANET` with `PREP_PREFLIGHT_WEB_INTRANET_BIND_FAILED`. The tracked contract already
fixed `POC_BIND_HOST=0.0.0.0` and `POC_STATE_BIND_HOST=127.0.0.1`. Doctor passed the complete
mode-0600 effective environment to a direct exact-image `docker run`; deploy instead used
`docker compose run web`, whose service environment did not include those host-orchestration
values. The deploy child therefore observed a different environment. No operator or provider
configuration caused this failure.

Doctor collect-all and deploy fail-fast now call one shared ephemeral executor. Both use the exact
Product image and the same private effective env file with `docker run --rm`, `linux/amd64`, the
Product non-root user, a read-only root filesystem, all Linux capabilities dropped,
`no-new-privileges`, no Product volumes, and the same optional read-only runtime-CA bind. Only the
final preflight mode argument differs. Deploy no longer invokes the provider gate through the Web
Compose service.

The parity contract covers all nine stages: `WEB_INTRANET`, `DATAHUB`, `QUALITY_READ`, `CHAT`,
`EMBEDDING`, `RERANKER`, `MCL_DISCOVERY`, `AIRFLOW`, and `MINIO`. The unit regression proves exact
command-prefix and private-env-file identity for both modes. Every non-secret value is identical;
sensitive values are compared in memory/private-file form and never emitted. An intentionally
polluted parent shell cannot replace the canonical bind, provider, MCL, project, or Compose values.

The isolated exact-image Docker regression observed doctor `WEB_INTRANET: READY`; the deploy
fail-fast child then passed that same stage and reached the intentionally unavailable DataHub
endpoint, where it produced the expected typed DataHub connectivity failure. After both runs the
isolated Compose project still had zero containers and zero volumes, and no runtime-secret file,
attempt receipt, or accepted marker existed.

## Non-destructive deployment regressions

The complete isolated Docker state suite passed:

- exact-image doctor plus deploy fail-fast parity under a polluted parent shell;
- fresh/residual target-state classification and non-destructive failed-install handling;
- provider failure before mutation, followed by zero Product volumes and zero receipts;
- forced authenticated-smoke failure followed by same-command owned-state resume;
- legacy V1 `SMOKE_FAILED` receipt plus descendant FIXED-contract update, preserving secrets and
  volumes while migrating the receipt;
- historical accepted K9-DEFERRED/loopback topology upgraded to current K9-REQUIRED/intranet
  topology without duplicate administrator, K9, or MCP identities.

No tested path ran `down -v`, removed a persistent volume, reset a database, deleted a receipt, or
regenerated a preserved target secret. Actual PREP state was not accessed.

## Verification

- PREP deploy/handoff focused contracts: `108/108 PASS`.
- Isolated Docker state/recovery suite: `5/5 PASS` (the corrected historical fixture was rerun after
  its pre-existing ENV V4/V5 setup drift was removed).
- Node Product server: `167/167 PASS`.
- UI: `90 files / 663 tests PASS`.
- ESLint, TypeScript typecheck, standard build, POC build, Ruff lint, strict mypy over `588` source
  files plus the strict deploy script, static verification, Python compile, shell syntax, Compose
  contract, diff-check, and image secret/proxy scan: `PASS`.
- Repository-wide Ruff format check retains three unrelated baseline formatting drifts in
  `test_knowledge_studio_service.py`, `test_local_reranker_service.py`, and
  `test_pilot_release_contract.py`; none is touched by this Product and no global format-all claim
  is made.
- Router/retrieval/reranking/grounding semantics changed: `NO`; Router 60 plus Boundary 8 was not
  rerun.

The exact Product OCI is `linux/amd64`, carries revision
`79efaf7523e96c8ae15690f6a9c1a1eca9ffc426`, and has image ID
`sha256:693b5831ac0b1b9a03a88ea65c6e0260a871a5e00cbd61a5e72e2124861810b3`. Its pinned Node runtime
imports the provider-preflight module under the same hardened disposable-container policy. Image
configuration/history contains no provider credential or credential-bearing proxy value.

The only PREP Product deployment command remains:

```bash
./scripts/prep39083 deploy
```

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
