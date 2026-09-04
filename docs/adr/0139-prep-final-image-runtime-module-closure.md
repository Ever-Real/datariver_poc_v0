# ADR-0139: PREP final-image runtime module closure

- Status: Accepted
- Date: 2026-09-04
- Refines: ADR-0132 dedicated PREP release and deployment isolation

## Context

Product `4d853c0f8072e0b47273944992b8e69c88fec331` added the approved Semantic input
segmentation module to source, but its final OCI Dockerfile omitted that module. The provider
preflight imports the Semantic projector, which imports the missing module, so the hardened
ephemeral Product container started and Node ran but module loading failed before any provider
request. The release gate verified selected files rather than the complete relative import closure.

## Decision

- The final image continues to copy an explicit reviewed set of runtime modules. Broad frontend
  wildcards and test/development files are not admitted.
- Product artifact preparation recursively resolves static relative `.mjs` dependencies from
  `poc-server.mjs`, `poc-prep-bootstrap.mjs` and `poc-provider-preflight.mjs`, then requires every
  dependency to have an exact source-equal final-image COPY entry.
- The built linux/amd64 OCI is verified from its real `/app` working directory with a hardened
  `/usr/bin/true` probe, Node version probe, provider-preflight import and direct Semantic projector
  and input-module imports before artifact export.
- Ephemeral container creation, Node startup and module import have distinct bounded doctor/deploy
  diagnostics. Operator output never includes raw filesystem paths, stack traces or provider data.

## Consequences

The final-image dependency closure fails before release publication when a runtime module is
omitted. Semantic segmentation, K9 lifecycle data, provider configuration, Compose ownership,
persistent volumes and Actual PREP state are unchanged by this packaging correction.
