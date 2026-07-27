# ADR-0053: Verified Neo4j bundle and explicit source-host graph profile

- Status: Accepted
- Date: 2026-07-27
- Refines: ADR-0034, ADR-0043, ADR-0048, ADR-0051, ADR-0052

## Context

The WSL preparation PC has two intentionally different runtime shapes. The immutable acceptance
profile runs DataRiver application containers and reaches Neo4j through Docker DNS at
`bolt://neo4j:7687`. Rapid source validation runs Python processes from the WSL checkout and must
reach the same loopback-published connector at
`bolt://127.0.0.1:${NEO4J_BOLT_PORT}`. Reusing one environment without an explicit topology marker
made these endpoints appear interchangeable and left the application validator with a separately
hardcoded default port.

The optional Neo4j `linux/amd64` image is intentionally carried in the separate
`datariver-platform-amd64-distribution` repository. A local version tag alone is not release
evidence: `docker save`/`load` can restore a tag without its original repository-digest
association, and an ARM64 Mac can also hold both native and emulated image variants.

## Decision

- `.env.wsl-preparation` remains the container-oriented immutable acceptance profile. A distinct,
  ignored `.env.wsl-intranet-development` is derived for WSL source-host execution.
- `NEO4J_SOURCE_HOST_ENABLED` marks the source-host topology. The application validates its
  loopback endpoint against the deployment-owned `NEO4J_BOLT_PORT`; container mode continues to
  require Docker DNS and port `7687`.
- The source launcher clears managed inherited variables before reading the selected environment,
  rejects duplicate active keys, accepts CRLF record endings and reports the selected environment
  plus sanitized Neo4j scheme/host/port diagnostics.
- Host profile derivation translates only known local-container Neo4j endpoints to the selected
  loopback publication. It does not rewrite private TLS endpoints or choose a remote host.
- `workflow_source_host_infra.py --neo4j-bundle-dir <directory> prepare` accepts the separately
  transferred bundle only when it contains one regular manifest, archive and checksum sidecar.
  It validates the manifest schema and matching upstream digest fields against the exact approved
  digest pin in `compose.local-connectors.yaml`, then binds the archive SHA-256, local tag, image ID
  and `linux/amd64` platform before stopping any application process.
- The workflow validates the local `username/password` secret and selected Bolt port before
  stopping writers. It starts Neo4j with registry pulls disabled, waits on an authenticated
  healthcheck and executes an authenticated `RETURN 1`.
- `dev_host.sh preflight` remains a configuration gate. Container health and authenticated Cypher
  execution are deployment gates owned by the infrastructure workflow.

## Consequences

- Changing `NEO4J_BOLT_PORT` no longer requires a code change or a matching hidden constant.
- The source checkout does not contain the Neo4j image. The separate distribution remains the
  artifact transport and trust boundary.
- An ARM64 Mac may build and execute `linux/amd64` images through Docker emulation to catch
  dependency, image and Settings incompatibilities. This does not prove WSL filesystem behavior,
  Windows/Hyper-V firewall policy, corporate DNS/CA, browser OIDC redirects or native AMD64
  performance.
- Closed-network success still depends on all required image archives and native package caches
  being staged before transfer. The workflow fails closed instead of substituting a registry
  image, disabling TLS or publishing a private upstream port.
