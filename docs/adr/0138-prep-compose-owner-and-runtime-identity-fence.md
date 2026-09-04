# ADR-0138: PREP Compose ownership and runtime Product identity fence

- Status: Accepted
- Date: 2026-09-04
- Refines: ADR-0132 dedicated PREP release and deployment isolation

## Context

Repository-local deployment locks do not serialize separate clones or worktrees that control the
same host-wide Compose project. Initial PREP evidence showed a tracked target image and effective
Compose configuration for one Product while the running Web still carried a predecessor Product
revision. Its working-directory label was initially misclassified as foreign by comparing
Compose's first-file project directory with the repository root. No evidence proved either a
foreign owner or that the target Web ever started. Without a correct post-apply identity gate,
authenticated smoke could attribute a Product failure to a tracked release instead of the Web that
actually served it.

## Decision

- Compose's canonical project directory is the resolved parent of the first Compose file,
  `BASE_COMPOSE.parent` (`deploy/poc`), not the repository root. Every canonical invocation pins
  that existing default explicitly with `--project-directory`; this preserves all relative-resource
  semantics. Owner inspection compares the Docker label with that same directory and the exact
  two-file Compose set.
- Stateful deploy acquires a kernel advisory lock derived only from the Compose project in a
  host-global directory. The existing checkout-local lock remains a secondary operator guard.
  Kernel ownership, not PID metadata, is authoritative; unsafe ownership or a concurrent holder
  fails closed before Docker or Compose mutation.
- A Web labeled for another checkout can be adopted only when its project/service, unique
  container, exact OCI revision, Git ancestry, deployment/accepted receipt, persistent volume and
  network identities prove that it is an owned predecessor. Adoption force-recreates only Web from
  the canonical release checkout with no build, pull or dependency recreation.
- Immediately after Web apply and before authenticated smoke, the tracked Product, effective
  runtime Product keys, Compose image, container image reference, image OCI revision, Compose
  working directory/config files and available config hash must agree. Mismatch is
  `PREP_RUNTIME_PRODUCT_NOT_APPLIED` and no K9, MCL or GENERAL smoke begins.
- Authenticated smoke is bound to the exact inspected serving Product. The deployer monitors the
  applied container/image/revision/config identity during polling and verifies it again after smoke
  and during failure handling. Replacement is
  `PREP_FOREIGN_COMPOSE_REPLACEMENT_DETECTED`, never a K9/provider failure.
- The additive deployment-attempt V3 receipt records target, applied, smoke and post-failure
  Product identities only when each stage is observed, plus foreign-owner adoption and rollback
  booleans. Automatic rollback remains absent; a classified smoke failure leaves the verified
  incomplete candidate running for receipt-driven resume.
- `status --compact` is the permanent bounded identity/readiness surface. Historical one-off probes
  remain evidence but new Product-specific identity probes are not part of normal operations.

## Consequences

Persistent PostgreSQL, Neo4j and Redis volumes, generated secrets, K9 source snapshots, projector
receipts and MCL checkpoints are unchanged by ownership adoption. A normal descendant deploy can
reuse completed lifecycle evidence and resume only incomplete work. A controller that bypasses the
project lock is detected by the runtime stability fence before its replacement can be attributed
to the candidate Product.

The earlier Actual PREP `W=O` classification that compared the Compose working-directory label to
the repository root is invalidated. It does not prove that a foreign checkout owned that Web. The
host-global lock and fail-closed adoption capability remain preventive controls.
