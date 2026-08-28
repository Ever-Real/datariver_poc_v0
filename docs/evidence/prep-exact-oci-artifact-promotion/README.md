# PREP exact OCI artifact promotion evidence

## Scope and boundary

This checkpoint changes only the PREP release/deployment artifact contract. Product business
logic, GlossaryTerm behavior, K9, MCL, projections, authorization, migrations and provider
configuration are unchanged. Actual PREP and OPS were not accessed or executed. `origin/main`
remained unchanged.

## Defect and identity classification

The prior release verified Product `3daf21e43830cc42411c15ed375042feadae661c` as a local
linux/amd64 Docker image, but canonical PREP deploy then ran a new Compose source build. The
verified artifact and the deployed artifact therefore were not the same build.

The previously reported
`sha256:6aa0316a55ad268163453d6fa286789c508377f46891f5f30049b88dd523e463`
was the local Docker content-store image ID and OCI index digest. Docker also rendered a local
`datariver-poc@sha256:6aa031...` RepoDigest, but no approved registry push existed. It was not a
cross-host registry manifest reference and could not be pulled immutably on PREP. It was not the
image config digest; the platform child manifest was `sha256:a132858f...` and the config digest was
`sha256:d9b906e1...`.

The repository already approved archive transport for PREP→OPS: Docker archive, SHA-256 sidecar,
approved transfer media, bounded verification, `docker load`, exact identity checks and
`--no-build`. The correction reuses that mechanism for DEV→PREP rather than adding a registry.

## Corrected contract

Product checkpoint:

```text
052d8867501bd6aaf3d75b9e9c7158a327c6a264
```

The release host builds that Product image once. `web-artifact-export` requires a clean worktree
at exact Product HEAD, verifies the existing linux/amd64 tag and OCI revision, then saves one
platform archive without building, pulling or loading. `release.json` V3 pins:

- Product SHA and exact image tag
- approved archive transport and fixed ignored PREP path
- archive SHA-256
- linux/amd64 child manifest digest
- config digest
- OCI revision and platform

PREP Compose uses `docker-compose.artifact.yaml`, which removes the Web `build:` section and sets
`pull_policy: never`. Doctor/deploy verify the archive checksum and bounded OCI/Docker inventory,
load it only when needed, inspect the exact manifest/platform/revision, and start Web with
`--no-build`. Missing artifact, checksum drift, archive contract drift, load failure, image tag
drift, manifest drift, platform drift and revision drift all fail before Web startup. No path
falls back to build or pull.

## Exact verified artifact

```text
Artifact ID    datariver-poc-052d8867501bd6aaf3d75b9e9c7158a327c6a264-linux-amd64
Image          datariver-poc:052d8867501bd6aaf3d75b9e9c7158a327c6a264
Archive SHA256 b94bbb795fd3432bc7dae9297fc6dbc1765930041e941ee39ee7ff2439fba032
Manifest       sha256:0f8d225383be4b5f326aa074fa8cf0f29b5782be7e5c1c34741422484a26c71a
Config         sha256:fbcc09bd6385eb336c47274870d445b7abd49885e32d9ab0313972524cf79836
Platform       linux/amd64
OCI revision   052d8867501bd6aaf3d75b9e9c7158a327c6a264
Archive bytes  124225024
```

The archive sidecar verification passed. The Product tag was then removed locally and restored
from this exact archive through the canonical loader. The result was
`LOADED_EXACT_ARTIFACT`; post-load child manifest, linux/amd64 platform and OCI revision matched
the pinned identity exactly.

Docker omits the optional `Descriptor.platform` object after loading this single-platform archive.
The loader accepts that Docker representation only after the archive platform, loaded image
`Os/Architecture`, exact child manifest digest and revision have independently matched. A present
but different descriptor platform remains a terminal mismatch.

## Verification

Local release-contract verification:

```text
PREP artifact/deploy/handoff unit tests       123/123 PASS
Exact Docker archive load/provider fixture     1/1 PASS
Ruff changed Python sources/tests                   PASS
strict mypy release/deploy/artifact tools           PASS
Python syntax                                         PASS
real Docker archive parser                            PASS
archive SHA-256 sidecar                               PASS
Compose Web build removed / pull_policy never         PASS
canonical Web startup --no-build                      PASS
```

Negative tests cover missing artifact, checksum mismatch, invalid release identity, archive
contract/path mismatch, manifest mismatch, revision mismatch, platform mismatch, load failure and
post-load image absence. Tests also assert that neither the export command nor the canonical
artifact preparation path invokes build or pull.

Final source/static, Product→Evidence→Handoff ancestry, `runtime_input_diff`, remote exact-match and
clean-worktree results are recorded by the following release/Handoff checkpoint.

## Runtime boundary

```text
Actual PREP: NOT EXECUTED
Actual OPS:  NOT EXECUTED
```

The exact archive must be transferred through the already approved artifact medium and staged at
the path pinned by the promoted `release.json` before the operator runs the unchanged command:

```bash
./scripts/prep39083 deploy
```
