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

The fixed no-argument Mac-only `reconcile_docker_builder_selection.py` operator is the sole
governed recovery for an already observed `DRIVER_NOT_DOCKER` prerequisite. It is deliberately
not part of `dev-publish`. Under the same exclusive lock it requires a clean, stable `dev` source
identity, the exact Mac development AppliedState and environment fingerprint, an unchanged local
Unix Docker context, empty `BUILDKIT_HOST` and `BUILDX_BUILDER`, and zero active builds for both
the selected and target builders. Its complete private Buildx inventory must contain exactly one
current running `docker-container` builder and exactly one non-current, running, context-default
`docker` builder whose builder name, node name and endpoint equal the validated current context.
Duplicate, conflicting or extra eligible evidence fails before mutation and none of those private
values is reported.

Plan construction uses one frozen, value-free `BuilderPrestateSnapshot`, computed from one complete
parsed inventory. It deterministically projects the existing current-selector, already-canonical,
duplicate, cardinality, prior, target and pass first-defect order without changing the legacy error
or acceptance contract. The runtime retains one capture snapshot and creates one local reproof
snapshot; any whole-value difference becomes the existing `PLAN_DRIFT`/`PRESTATE` result. It does
not maintain independent mutable recorders for the additional observations.

The nested prior-driver recorder uses Docker's official core
[`docker`, `docker-container`, `kubernetes`, and `remote` driver vocabulary](https://docs.docker.com/build/builders/drivers/)
plus the exact [`cloud` driver documented by Docker Build Cloud](https://docs.docker.com/build-cloud/setup/)
and its [multi-platform example](https://docs.docker.com/build/building/multi-platform/). It reports
`EMPTY`, `CLOUD`, `KUBERNETES`, `REMOTE`, or `UNRECOGNIZED` when the exact current driver is not the
required `docker-container`; `EMPTY` is reserved for the unresolved empty factory result and
`UNRECOGNIZED` is nonempty. Only exact `docker-container` records `PASS`. It does not expose the
provider string, accept a new driver, normalize a spelling or claim that the current host binary is
pinned to a particular Buildx version. Later plan findings retain the observed prior-driver `PASS`,
while findings before that check omit it.

The snapshot classifies optional builder- and prior-node-level `Err` fields only as `ABSENT`,
`PRESENT` or `INVALID`: absence and a nonempty string are structurally observed, while empty or
non-string values are invalid, and error text is never retained or compared. This follows the
immutable Buildx v0.35.0 [`Builder.MarshalJSON`](https://github.com/docker/buildx/blob/v0.35.0/builder/builder.go)
and [`Node.MarshalJSON`](https://github.com/docker/buildx/blob/v0.35.0/builder/node.go) shapes.
The same authority shows that `LoadNodes` resolves an empty default-context driver through its
factory before assigning a concrete driver. This is parser authority only, not a claim that the
installed host binary is v0.35.0.

The fixed `--diagnostic-phase BUILDER_SELECTION_PRESTATE` mode is read-only. Under the same
exclusive lock it performs the operator's canonical source, AppliedState/environment, Docker
override and local-context checks, then makes exactly one bounded `docker buildx version` query and
performs the complete-inventory capture followed by one exact snapshot reproof. The version line is
reduced to `UPSTREAM_V0_35_0`, `UPSTREAM_OTHER`, `OTHER_DISTRIBUTION` or `OUTPUT_INVALID`.
`OTHER_DISTRIBUTION` is refined only as documented `-desktop.<positive-integer>` shape,
upstream-module nonrelease shape, or other-module shape. The exact two-token Docker Docs form and
an otherwise bounded three-field line with that suffix both classify the suffix independently of
the module token. Docker's [Desktop release notes](https://docs.docker.com/desktop/release-notes/)
establish that shape, not the installed distribution. Module, version, revision and raw output are
never emitted.
The snapshot also reduces the prior/target relation, prior status and node-error shape, and complete
target contract even when the unchanged public first defect remains `PRIOR_DRIVER`.
It stops before active-build history, `buildx use`, rollback, prune, build, container, database,
identity, topology, AppliedState-write or push work. Its one bounded line uses schema
`BUILDER_PRESTATE_V2`, one `observation_known` flag and one optional literal-key `observation`
object containing only closed predicates. Early failure omits the object; completed capture
survives reproof or lock failure, and unequal reproof projects only the original capture snapshot
with `PLAN_DRIFT`. The line otherwise contains only the closed classification, phase and zero
action/mutation/retry counts; it never contains a
builder/context/node/endpoint name, source SHA, path, environment value or provider output. A
`PASS` is diagnostic evidence only and does not authorize the mutating operator or a host repair.

The fixed `--diagnostic-phase CONTEXT_DEFAULT_BUILDER_PREFLIGHT` mode is a narrower read-only
follow-up for one exact rejected snapshot: the current and context-default identities are the same,
the prior driver is empty, the builder-level error is present, and the context-default target fails
the `docker` driver contract. It reuses the same lock, source, AppliedState/environment, Docker
override, local-context and immutable-snapshot evaluator. No second inventory parser or mutable
recorder is introduced. A different capture is `PRESTATE_DRIFT` and stops before the daemon probe.

For the exact phenotype, the phase invokes the official fixed read-only
[`docker version`](https://docs.docker.com/reference/cli/docker/version/) tuple
`docker version --format {{.Server.Version}}` once. The returned version is accepted only as one
bounded visible-ASCII non-whitespace token with one optional line terminator; leading or trailing
whitespace, spaces, tabs, NUL/control bytes, empty, multiline, oversized and invalid UTF-8 output
are rejected. The token is never parsed, retained or emitted and does not establish a Docker
Desktop product or installed-version identity.

The bounded runner retains a private typed process outcome until final liveness and cleanup proof.
Only a reaped nonzero or a bounded timeout with trustworthy cleanup is
`DAEMON_API_UNAVAILABLE`. A zero exit with trustworthy cleanup but invalid output evidence is
`DAEMON_EVIDENCE_INVALID`. A reaped nonzero remains the first outcome even when its discarded
output is oversized, malformed or invalid UTF-8. Spawn, selector, registration, read, wait,
finalization or cleanup ambiguity is operator-review-required `UNKNOWN`; an unreaped or
liveness-unknown child has highest priority and permits neither snapshot reproof nor host-action
inference. The runner caps and discards excess output in flight but continues to observe the fixed
command's exit and cleanup state only for this diagnostic typed-outcome boundary. Existing normal
operator callers continue through the legacy `output()` adapter: its first output-cap breach stops
all later payload reads and immediately starts terminate/reap, preserving the accepted mutation
opportunity as well as the fixed process-failure or unreaped result. Both adapters share one private
runner and finalizer. Before the first breach, their read request is bounded to the smaller of 64
KiB and the remaining cap plus exactly one byte, so the legacy cleanup boundary cannot consume
additional bytes beyond the first over-cap byte. Only the two fixed read-only probes—the
`CONTEXT_DEFAULT_BUILDER_PREFLIGHT` daemon probe and the `DOCKER_DESKTOP_STATUS_PREFLIGHT` status
probe—select observe-exit-after-overflow and may use larger discard reads after that first bounded
breach. Every normal or mutating caller remains on immediate-stop overflow handling.

A structurally valid daemon response followed by an identical whole-snapshot reproof is
`BUILDX_DEFAULT_UNRESOLVED`. Any source, host, context or snapshot change is `PRESTATE_DRIFT`. An
interruption, lock-exit defect or other unstructured failure is likewise only
operator-review-required `UNKNOWN`.

Every conclusive result remains `REJECTED`; this phase never reports `PASS` because it classifies an
already rejected builder prestate rather than proving builder health. Its fixed one-line schema
reports only the closed predicate, whether the exact phenotype was observed, bounded Buildx-version,
inventory and daemon-query counts, and zero action, rollback, selection-mutation, cache, build,
container, general-mutation and retry counts. It performs no active-history query, `buildx inspect`,
builder create/use/remove/stop/bootstrap, context or environment change, Docker Desktop setting or
restart, prune, build, container, database, identity, topology, AppliedState write or push. Normal
no-argument operator and Linux/WSL behavior issue this daemon probe zero times and remain unchanged.

The fixed `--diagnostic-phase DOCKER_DESKTOP_STATUS_PREFLIGHT` mode is a still narrower Mac-only
read-only follow-up after an attempted Docker Desktop recovery has an unknown result. It holds the
same B1 lock, captures the clean source, AppliedState/environment, Docker override and validated
local-Unix context identities, invokes the official
[`docker desktop status`](https://docs.docker.com/reference/cli/docker/desktop/status/) tuple
`docker desktop status --format json` exactly once, and then reproves every captured identity.
The status query is not an Engine probe and does not query Buildx, cache, images, containers or
volumes.

The public Docker reference documents JSON output and only the semantic states `running` and
`stopped`; it does not publish a JSON field-name contract. The phase therefore parses a bounded,
duplicate-free JSON mapping without trusting any key name. It permits at most 32 top-level primitive
values so undocumented primitive metadata does not become a provider-schema assumption, rejects
every nested mapping or list, and requires exactly one exact lowercase `running` or `stopped`
semantic value. Duplicate keys, zero or multiple semantic values, `starting`, `unknown`, spelling
variants, non-mappings, non-finite JSON numbers including `NaN` and `Infinity`, malformed JSON,
invalid UTF-8, entry-bound overflow and oversized output are `STATUS_EVIDENCE_INVALID`. Keys, values,
IDs, sessions, versions, paths and provider output are discarded and never emitted.
An otherwise valid `running` or `stopped` value cannot override an additional lifecycle-like value:
exact `starting` or `unknown`, or any case or outer-whitespace variant of those four lifecycle words,
makes the whole observation ambiguous and invalid after the complete bounded value scan.

A trustworthy reaped nonzero or bounded timeout is `STATUS_UNAVAILABLE`; process-boundary,
cleanup, liveness or interrupt ambiguity is operator-review-required `UNKNOWN` and performs no
reproof. A successful or trustworthy failed query is followed by exact source, host, environment
and context reproof; inequality is `PRESTATE_DRIFT`. Conclusive observations are `REJECTED` rather
than `PASS`, because `RUNNING` or `STOPPED` describes only the Desktop control plane and proves
nothing about Engine availability, builder health or container and volume invariants. The fixed
line reports one status-query count and zero Engine, Buildx, action, rollback, selection, cache,
build, container, volume, business, state, push, mutation and retry counts. It cannot start, stop or
restart Desktop, gather logs or diagnostics, or authorize another host action. Normal no-argument
operator, generic deployment and Linux/WSL behavior issue this status query zero times.

The operator may issue exactly one `docker buildx use <validated-current-context>` command, with
neither `--default` nor `--global`; the Docker driver is automatically created by the Docker
context and is never created by this workflow. Afterward, the complete inventory must differ only
in the two `Current` flags, the context/source/state/environment identities must be unchanged, the
target must pass the canonical selector, and both builders must again have zero active builds.
The existing `docker-container` builder, its container and its cache are retained. The operator
contains no builder create/remove/stop/bootstrap, context or environment change, Docker Desktop
setting or restart, cache prune, image build, or container/volume/data action.

A nonzero, timeout or response-loss result permits one read-only post-state proof and never a
retry. If the target state is completely proven, the selection succeeds despite the lost CLI
response. If the prior exact state is proven, the attempt stops without rollback. A rollback is
allowed at most once only when the target became current, another postcondition failed, and the
privately retained prior identity plus its active-build-zero state are re-proven; ambiguous or
drifted identity performs no rollback. Total selection mutations are therefore at most two and
all output remains one bounded, value-free evidence object. Source acceptance does not authorize
this host mutation: `SEC-DOCKER-BUILDER-SELECT-001` requires explicit user approval after staged
Security review.

Immediately before the first selection, the operator privately reproves the exact clean source
commit and branch, AppliedState and environment fingerprint, process Docker overrides, local
context, complete builder inventory and selection identity. Active-build-zero for the prior and
target builders are the final two probes before the monotonic action marker and fixed `buildx use`
call. Any drift stops with action zero. Exact post-state residual evidence is reported only through
the bounded range 0..128; a larger exact residual remains invalid but is reported as unknown and
never clamped or estimated.

Every bounded subprocess must be proven reaped. If terminate, kill and bounded waits cannot prove
that a selection or rollback process exited, the operator performs no post query or further
selection, reports the attempted mutation and unknown outcome, and requires operator review. A
read-only subprocess with the same unreaped condition also stops before mutation. An ordinary
reaped response loss may use the single post proof, but `KeyboardInterrupt`, `SystemExit` or any
other non-`Exception` interruption during rollback always remains operator-review-required even
when the one post proof establishes whether rollback applied. Such proof preserves the observed
rollback facts and never permits a third action.

This recovery does not make `docker-container` acceptable to the canonical capacity policy. The
official [`docker` driver](https://docs.docker.com/build/builders/drivers/docker/) uses Docker
Engine's integrated BuildKit and automatically loads results into the Engine image store. The
official [`docker-container` driver](https://docs.docker.com/build/builders/drivers/docker-container/)
owns a dedicated BuildKit container and volume, has a separate cache lifecycle, and does not load
results by default. Docker's [`buildx use`](https://docs.docker.com/reference/cli/docker/buildx/use/)
contract permits the already validated context name to select its automatically created default
builder. Supporting `docker-container` would require a separate T3 decision covering image
loading, builder lifecycle, cache and backing-filesystem ownership, capacity evidence and
rollback; it cannot be introduced by relaxing `DRIVER_NOT_DOCKER`.

Builder selection also advances one closed, value-free structural recorder. It distinguishes an
external BuildKit host; invalid list, row, node-count or node shapes; conflicting duplicates;
missing or ambiguous current selection; invalid or non-current overrides; non-`docker` driver;
non-running node; and builder/context, node-name or endpoint/context mismatch. The recorder exposes
none of the builder, context, node, endpoint, driver, status or environment values. Without a
recorder, the canonical action-enabled failure text and fail-closed behavior remain unchanged.
When several final checks are simultaneously defective, the fixed first-defect order is driver,
node status, builder/context, node name, then endpoint/context.

The bounded JSON compatibility contract is tied to the immutable upstream `docker/buildx`
`v0.35.0` formatter sources in
[`commands/ls.go`](https://raw.githubusercontent.com/docker/buildx/v0.35.0/commands/ls.go),
[`builder/builder.go`](https://raw.githubusercontent.com/docker/buildx/v0.35.0/builder/builder.go),
and [`builder/node.go`](https://raw.githubusercontent.com/docker/buildx/v0.35.0/builder/node.go),
together with the official [`docker buildx ls` documentation](https://docs.docker.com/reference/cli/docker/buildx/ls/).
This source authority does not claim that the current host binary is pinned to that tag. A node
must remain a mapping whose name and endpoint are exact strings. The upstream serializer does not
apply DataRiver's builder-name grammar to the node name, so the node name is not separately matched
against that grammar; it must still equal the already validated selected builder exactly. Empty or
unusual node-name strings therefore fail as a node-name mismatch and can never pass. No endpoint
URI parsing, normalization or builder-name coercion is allowed, and the selected endpoint must
still equal the validated current context exactly. An omitted or empty node status is the upstream
representation of unavailable status and fails as not running; a present non-string status remains
invalid schema, and only exact `running` can pass.

The read-only diagnostic also retains one closed node-schema subpredicate without exposing a node
value. It distinguishes a non-mapping node; missing, null and non-string name or endpoint fields;
and null or non-string present status fields. Missing status remains the reviewed unavailable
state. `PASS` is recorded only after the complete row/node structural scan; later duplicate,
selection or semantic failures retain it. An interrupt before a structured outcome remains unknown.
This finer evidence does not relax any mapping, type, exact-equality, running-status, driver or
current-context invariant and is not evidence that the host binary is pinned to upstream v0.35.0.

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
