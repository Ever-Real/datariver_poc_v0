# Environment file profiles

Real deployment files are ignored and must not be committed. Generate a complete file from the
canonical `.env.example` through bootstrap; do not concatenate shell fragments at runtime.

Mac source-host development:

```bash
./scripts/bootstrap.sh --env-file .env.mac-development --mac-development
./scripts/dev_host.sh --env-file .env.mac-development start \
  --redis-cache-url redis://127.0.0.1:6379/0 \
  --redis-delivery-url redis://127.0.0.1:6380/0 \
  --s3-endpoint-url http://127.0.0.1:9000 \
  --enable-local-ollama
```

WSL container preparation:

```bash
./scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --datahub-base-url https://replace-with-private-datahub.example
./scripts/compose.sh --env-file .env.wsl-preparation -f compose.local-connectors.yaml up -d
./scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml up -d
```

Before either `up`, edit only the generated environment file and place approved values for external
DataHub, MinIO/S3 and LLM endpoints. The WSL profile starts Redis only in the local-connectors
project; add `--profile graph` only after enabling the development graph contract. The Mac command
adds `--profile object-storage` when its MinIO is local.

`DATARIVER_ENV_FILE` inside each generated file binds Compose interpolation and backend `env_file`
to the same path. Credentials remain in `secrets/`. Keep
`SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED=false` so the database does not become a second
live configuration source.

## Local connector distribution gate

The reference Compose currently names Redis `8.2.6-bookworm`, matching the upstream 8.2.6 security
release, and the last upstream MinIO security release
`RELEASE.2025-09-07T16-13-09Z` with OCI index digest
`sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`.
The newer `RELEASE.2025-10-15T17-29-55Z` source release has no matching official Quay image, so it
must not be used as a container tag. These are review inputs, not automatic redistribution approval.
Redis 8 uses its upstream tri-license choices; MinIO is AGPLv3/commercial and its upstream repository
was archived in April 2026. Record an approved registry digest, vulnerability result and legal
decision before `--include-local-connectors` is ever added to an offline release.

- Redis release and license sources: <https://github.com/redis/redis/releases/tag/8.2.6>,
  <https://redis.io/legal/licenses/>
- MinIO release and repository state: <https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z>
