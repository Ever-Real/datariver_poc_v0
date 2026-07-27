# ADR-0055: Preloaded Neo4j source validation

- Status: Accepted
- Date: 2026-07-27
- Refines: ADR-0034, ADR-0053, ADR-0054

## Context

The Neo4j AMD64 archive is transported independently from the DataRiver source repository. Some
preparation PCs retain the distribution checkout and can give its archive, checksum and manifest
directory to the infrastructure workflow. Other preparation PCs verify the transferred files,
run `docker image load`, and retain only the resulting local image. Requiring
`--neo4j-bundle-dir` on the latter hosts incorrectly assumed a filesystem layout that was not part
of their runtime.

## Decision

- `--neo4j-bundle-dir` remains the strong path when archive evidence is locally present; it
  validates checksum, manifest, approved upstream digest, image ID and `linux/amd64` before load.
- `--reuse-loaded-neo4j` is a development-only alternative when the image was already loaded. It
  requires the local tag selected by the checked-in approved Neo4j pin, verifies the image is
  `linux/amd64`, and refuses a missing, differently tagged or wrong-platform image.
- Both paths validate the `username/password` secret and configured Bolt port, start Neo4j with
  registry pulls disabled, wait on the authenticated healthcheck and execute `RETURN 1` before
  persisting source-host graph settings.
- The preloaded-image path does not reconstruct or claim archive, digest or release evidence.
  Managed offline promotion continues to require the verified bundle/manifest contract.
- Graph-disabled environments omit both options.

## Consequences

- A preparation PC that retained only a loaded Docker image no longer needs a fake or reconstructed
  distribution directory.
- Runtime convenience is separated from release evidence without introducing registry access or
  accepting arbitrary image tags.
