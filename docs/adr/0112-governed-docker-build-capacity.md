# ADR-0112: Governed Docker build capacity

- Status: Accepted for P0-B1 source implementation; runtime gate open
- Date: 2026-08-03
- Owners: DataRiver application, security and operations owners

## Context

The arm64 development workflow builds source on a Docker Desktop VM with a bounded backing
filesystem. A full VM previously prevented DataHub checkpoint writes, container evidence capture
and the next source build even though the external host filesystem had ample free space. A
one-time non-`--all` Buildx prune returned success but reclaimed zero bytes from cache reported as
reclaimable, so that command is not a valid persistent capacity policy.

A later governed action exposed a separate accounting defect: Buildx disk usage reported
`Shared` records whose storage was also owned by another resource, normally a local image. The
logical total was incorrectly treated as independently recoverable private cache. That double
count triggered a cache action even though private cache was already below its budget; the action
correctly reclaimed zero physical bytes, and the same incorrect logical total then failed the
postcondition. Shared storage remains fully represented by actual Docker-filesystem free space,
but it is not independently available to this cache-only deletion policy.

The stable `workflow_update_restart.py` command must continue to select and build only affected
services. It must not expose resolved Compose values or build arguments, silently operate on a
remote daemon, overlap another managed build, or turn capacity recovery into a broad Docker
cleanup operation.

## Decision

P0-B1 adds a fail-closed build-capacity gate to the existing build-mode update workflow. The gate
runs after the affected service set and operator confirmation are known, but before the local
reranker or any Docker build or service mutation. `--refresh-bootstrap` remains earlier because it
only refreshes host-local configuration and secrets; this decision claims a Docker mutation
boundary, not a zero-host-mutation boundary.

The workflow acquires a nonblocking Unix advisory lock at the ignored host-local path
`runtime/operator-locks/update-build.lock`. The directory and file are owned by the current user,
non-symlinked, and mode `0700`/`0600`. The same lock remains held across Compose evidence,
optional cache recovery, every subsequent builder-idle check, Docker/service mutation and applied
state write. Contention fails before any Docker mutation, and every success or failure exit
releases the lock.

The gate accepts only the single current Buildx builder using the local `docker` driver through a
Unix Docker endpoint. Its one running node name and endpoint must match the current Docker context;
multi-node builders and a `BUILDX_BUILDER` override to any non-current builder are rejected.
`BUILDKIT_HOST`, non-Unix Docker contexts and ambiguous context selection are also rejected.
Immediately before an optional prune and before each online Compose build, Buildx history must
report zero running builds for that builder.

Builder selection also advances one closed, value-free structural recorder. It distinguishes an
external BuildKit host; invalid list, row, node-count or node shapes; conflicting duplicates;
missing or ambiguous current selection; invalid or non-current overrides; non-`docker` driver;
non-running node; and builder/context, node-name or endpoint/context mismatch. The recorder exposes
none of the builder, context, node, endpoint, driver, status or environment values. Without a
recorder, the canonical action-enabled failure text and fail-closed behavior remain unchanged.
When several final checks are simultaneously defective, the fixed first-defect order is driver,
node status, builder/context, node name, then endpoint/context.

Resolved Compose JSON stays in process memory. Each selected build is reduced to a SHA-256
fingerprint of its allowlisted context, Dockerfile, target and resolved build arguments. Raw
configuration, argument values, image references, image IDs and provider output are never logged
or persisted. The evidence report contains only the validated builder name, byte counts, selected
service/fingerprint counts and action classification.

Capacity evidence requires all of the following:

1. the Git checkout is clean;
2. each context and Dockerfile is a regular, non-symlinked path inside the checkout;
3. the repository `.dockerignore` excludes Git, environment/secrets, runtime, dependency,
   generated image and frontend build directories;
4. context bytes come only from tracked files in each selected context; and
5. every Compose tag in a selected build fingerprint has an exact existing local image ID and
   positive size on the selected Docker server OS/architecture; tags built at different
   historical commits may differ, so `Iᵢ` is their conservative maximum current size.

Let `T` be the Docker backing-filesystem total bytes observed inside the running PostgreSQL
container, not host SSD free space. For each unique build fingerprint `i`, let `Iᵢ` be its exact
current image size and `Cᵢ` its tracked context bytes. The governed values are:

- selected build peak `P = Σ(2 × Iᵢ + Cᵢ)`;
- safety margin `S = ceil(T / 10)`;
- required free space `F = P + S`;
- cache budget `B = ceil(T / 8)`; and
- retained cache floor `R = floor(B / 2)`.

All values must be positive, integral and feasible within `T`. Missing image, builder, context,
filesystem or cache evidence fails closed.

The selected peak includes every source build issued by this workflow: affected Core services and
`migrate`, `local-bootstrap`, the shared Airflow image and APISIX. All four Compose build sites
repeat the active-build-zero check while the same lock is held. Neo4j projection and local
connector recreation use prebuilt pinned images with `--no-build`. The daily DataHub update uses
the wrapper's `start-offline` path, so it cannot pull the quickstart's ancillary tag-only images;
initial image acquisition remains a fresh-setup responsibility. These non-build paths remain
inside the exclusive lock, but add zero image bytes to `P` only when the staged read-only runtime
review proves every selected image already exists locally. A missing or changed image is not
covered by this build-peak proof and must stop authorization of the reviewed run until a separate
pull-capacity plan exists; it cannot be treated as zero-byte evidence.

Every Buildx disk-usage record must contain a boolean `Shared` classification. Identical duplicate
records collapse only when size, reclaimable status and shared status all agree; any conflict
fails closed. The bounded evidence partitions record counts and bytes into logical total, private
and shared, and separately partitions the reclaimable counts and bytes. It proves both identities:
logical = private + shared and logical reclaimable = private reclaimable + shared reclaimable.
Cache IDs, descriptions and references are never reported.

Let `K` be current private (`Shared=false`) cache bytes and `Q` be private bytes reported
reclaimable. Shared logical bytes and shared reclaimable bytes are diagnosis-only: they never
satisfy a recovery requirement and the workflow never claims that pruning them frees physical
bytes. When private cache use is at or below `B`, the workflow performs no cache action. When it
exceeds `B`, let `A` be the maximum safe private recovery while retaining the floor:
`A = min(Q, max(0, K - R))`. Before any partial mutation, both
`Q >= K - B` and `free + A >= F` must hold. Under the exclusive lock and with zero active builds,
the workflow may then execute exactly once:

```text
docker buildx prune --builder <validated-local-builder> --all --force \
  --reserved-space <R> --max-used-space <B> --min-free-space <F>
```

CLI byte values are rounded upward to integer decimal megabytes. Whether the action succeeds,
fails or times out, the workflow remeasures the same builder cache and Docker backing filesystem
exactly once. Action and post-probe outcomes are reduced to fixed sanitized classifications; raw
provider output is not retained or printed. Every failing post-action path emits exactly one
operator error line containing only its fixed classification, validated builder name, before-byte
values, probe-success booleans, `action_attempts=1` and `retry_count=0`. Values and signed deltas
from a post-probe appear only when that probe passed; unavailable values are omitted rather than
estimated. Successful and failing evidence uses unambiguous logical/private/shared count and byte
field names before and, only when the post-probe succeeds, after the action. This records partial
cache mutation without exposing cache IDs, paths, image references, configuration or arguments. A
post-probe failure, changed backing filesystem, private cache still above `B`, or free space below
`F` stops the update without retry. A failed action may already have deleted part of the private
cache: there is no rollback, and later cache recovery occurs only through an independently governed
source rebuild. This authorization never permits `docker system prune`, image/container/volume
prune or removal, and it does not change Docker daemon JSON or Docker Desktop settings.

The fixed `BUILD_CAPACITY_PREFLIGHT` diagnostic reuses this canonical evaluator with the immutable
`MEASURE_ONLY` mode. The normal default remains action-enabled. Measure-only evaluation performs
the same lock, clean-checkout, Dockerignore, resolved Compose/build-target, tracked-context, local
Docker context, current builder, platform, image, private/shared cache, backing-filesystem,
capacity-policy and pre-action cache-support/active-build proofs. If the private cache is over
budget and every existing feasibility gate would permit the bounded prune, it returns the closed
`CACHE_ACTION_REQUIRED` predicate immediately before the prune argv; it never executes that argv.
The diagnostic permits only the exact read-only `docker buildx prune --help` capability probe and
structurally rejects every other prune-prefixed command. It retains the initial fixture-source
fingerprint and reproves a clean, identical source after capacity evaluation, before reporting an
action requirement, and again after the selected-builder idle proof before reporting `PASS`.
Source drift or an interrupted source proof yields only operator-review-required `UNKNOWN`.
The following initial selected-builder idle proof is separately classified as probe failure or an
observed active build.

Every boundary advances one shared typed, value-free phase recorder. Existing
`DockerCapacityError` text and action-enabled behavior are unchanged when the recorder is absent;
the diagnostic receives a structured phase rather than matching exception text. Its evidence
contains `builder_selection_known` and the optional closed `builder_selection_predicate`: an exact
selection failure keeps the top-level `BUILDER_SELECTION`, while any observed success is retained
as `PASS` through later phases and outer review-required failures. Unknown or pre-selection stops
omit the subpredicate; null and reconstructed results are forbidden. The evidence contains no
builder name, Compose configuration, service/image/cache identity, byte count, path, environment
or provider output. The operation performs cache action, build and container action zero and stops
before database, login, identity, topology, AppliedState or push work.
If a selection failure is followed by a lock/context-exit defect, review-required evidence retains
top-level `BUILDER_SELECTION` and its exact first subtype. This is the sole review-required result
whose top-level predicate is not `UNKNOWN`.

## Compatibility and deferred scope

- Existing workflow names, arguments, confirmation, source selection and service restart meaning
  do not change.
- No Compose file, Dockerfile, environment schema or root README is changed by P0-B1.
- The lock is host-local and ignored; it is not runtime readiness evidence and stores no content.
- Fresh setup, offline release loading, `prep-update`, amd64 dependency caches and first-build
  policy remain P0-B2 target gates. P0-B1 therefore does not require online builder-capacity
  evidence for the existing offline `local-bootstrap` build path.
- Local/external/disabled topology drift, backup/restore and durable external-volume placement
  remain P0-C.

## Evidence boundary

Unit and static gates prove formulas, path confinement, lock lifecycle, fixed cache-only argv,
active-build negatives, measure-only pre-action classification, output sanitization and workflow
ordering. No Buildx prune, image build,
container restart or service mutation is executed as part of this source slice. Actual Mac and
Linux/WSL runtime capacity behavior remains open until the staged byte values and exact command
are reviewed and a separately bounded operator run is authorized.
