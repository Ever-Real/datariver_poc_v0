# ADR-0114: Governed persistent-data bind migration

- Status: Accepted for C2-A source implementation; runtime probe and migration open
- Date: 2026-08-03
- Owners: DataRiver application, security and operations owners

## Context

The Mac development host currently keeps PostgreSQL and MinIO canonical data in Docker named
volumes. The Docker backing store is already on the external SSD, but an explicit host bind under
`/Volumes/SSD_Mac` gives backup and rollback evidence a stable host-local boundary. The current
PostgreSQL and MinIO data total only about 510 MiB, so this is a portability and backup-isolation
change, not a meaningful Docker-capacity recovery measure.

The target APFS volume reports `noowners`. A successful write and readback there proves filesystem
durability and application compatibility, but it cannot prove Unix ownership enforcement. Moving
canonical data before that distinction and the exact image behavior are verified would create an
avoidable data-loss risk.

## Decision

C2-A adds a one-time, explicitly confirmed feasibility probe. It is not part of `dev-publish`,
`prep-update` or another daily operator interface. Source acceptance does not authorize running the
probe. Runtime remains a separate Security and user decision.

The probe holds the existing exclusive Docker workflow lock for its entire observation, container
and cleanup lifecycle. It requires the checked-in immutable PostgreSQL and MinIO image IDs and
their exact repository digest references, uses `--pull never`, and records no raw inspect, command,
provider or credential payload. Before any probe mutation it verifies that the production
PostgreSQL and MinIO containers are running with the expected named volumes and captures their
container IDs and volume fingerprints. It verifies the same identities and the complete volume
name set after the probe.

The immutable image inspection also establishes each image's duplicate-free `Config.Env` baseline
before host or container mutation. A probe container must expose exactly that baseline with the
reviewed PostgreSQL or MinIO/`mc` overrides applied. Conflicting duplicate keys and every added
password, access, host or other environment key are rejected.

The fixed target is `/Volumes/SSD_Mac/datariver-data/.c2-bind-probe-v1`. The only group-writable
placement root exception is the exact `/Volumes/SSD_Mac` mountpoint at mode `0775`; arbitrary roots
still reject every group- or world-writable mode, and mode `0777`, `0770` or another mode at the
fixed mountpoint is invalid. The mountpoint must be a real, non-symlink APFS local `noowners`
mount owned by the current uid and gid, on a different filesystem device from `/Volumes`.

The probe keeps the mount-root directory descriptor open for its entire host-mutation lifecycle.
It validates an anchored local `/dev/disk*` block-device source in memory, including its device,
inode and raw-device identity, but does not persist or emit the source, a source hash or another
stable device fingerprint. Mount source, options and root device/inode/mode/uid/gid are compared
before host mutation, after layout/atomicity/secret creation immediately before each bind-using
container create, on failure before any secret unlink, immediately before successful container and
tree cleanup, and after successful cleanup. A failed or unknown failure-path mount recheck retains
all secrets and reports `PROBE_SECRET_CLEANUP_REQUIRED`; container stop attempts may still proceed.
Operator evidence includes only the bounded booleans `filesystem_noowners=true`,
`mount_root_group_writable=true` and `ownership_enforcement_claimed=false`.

The parent and leaf use fixed single-component, directory-descriptor-relative creation. Each
directory is created absent-only with `mkdir(..., dir_fd=...)`, opened with
`O_DIRECTORY|O_NOFOLLOW`, compared by path and open-descriptor `fstat`, forced to mode `0700`, and
`fsync`ed together with its parent directory. There is no exists-then-mkdir check, `exist_ok`, glob
or generalized recursive delete. The task may create the parent only when it is absent. Successful
cleanup builds an identity-checked manifest only beneath the exact leaf and deletes that bounded
manifest depth-first through the held leaf descriptor; every reopened directory and deletion target
must match the manifest before a directory-FD-relative unlink or removal. It is not an arbitrary-path
deletion facility. It then removes the parent only when the task created it, it is still the same
inode and it is empty. After cleanup, held descriptors must retain their captured identities while
the deleted child paths are absent; a pre-existing valid private parent must still map to its held
descriptor. Failure evidence remains in place.

The probe also holds identity-pinned descriptors for the parent, leaf, evidence, secrets,
PostgreSQL data, MinIO data and their intermediate directories until the outer command `finally`
block. Every child path must still resolve to the metadata observed through its held descriptor.
Atomicity and synthetic-secret files are created, published, read and `fsync`ed relative to the
held evidence or secrets descriptor. The bounded PostgreSQL dump is captured and published relative
to the held evidence descriptor. The complete child guard is checked before and after each Docker
bind-create, around these sensitive host writes, before and after every failure-path secret unlink,
and before the successful cleanup manifest is captured and applied. Successful cleanup then proves
the held directory identities are unchanged and the removed child paths remain absent. Child
identity drift stops further host write or unlink; already-created probe containers may only undergo
the bounded failure stop sequence and all evidence is retained.

The isolated containers have no network, published ports, Docker socket, host namespaces, device
mounts, named or anonymous volumes, registry pull or Docker log driver:

- PostgreSQL uses a read-only root filesystem, `no-new-privileges`, `cap-drop ALL`, and only
  `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID` and `SETUID`. It is bounded to 1 GiB, 1.5 CPU,
  128 PIDs and a 60-second stop timeout. Local peer authentication avoids a credential in argv.
- MinIO uses a read-only root filesystem, `no-new-privileges`, `cap-drop ALL`, no added
  capabilities, 512 MiB, 0.5 CPU, 64 PIDs and a 30-second stop timeout.

Both use only allowlisted bind mounts and bounded tmpfs paths. Three independent CSPRNG-generated
non-production credentials are written as `0600`, single-link regular files. Each creation-time
device and inode identity is captured with `fstat` while its original file descriptor is still
open. After close and directory `fsync`, every path must resolve to that exact identity before the
secret bundle is accepted. Failure cleanup validates all three identities
before the first unlink and revalidates each immediately before unlinking it; any replacement,
symlink, hardlink or mode/link-count drift retains all remaining files and reports only the fixed
cleanup classification. PostgreSQL and MinIO server credentials use read-only `_FILE` mounts. The
exact bundled `mc` receives its access and
secret keys as two binary stdin lines through fixed non-TTY `docker exec -i` argv, with a 20-second
timeout and its configuration on tmpfs. Credentials never enter Docker Config.Env, positional
arguments, inspect evidence or operator output. The exact pinned server `_FILE` and `mc alias set`
stdin contracts are corroborated by the upstream
[MinIO server release documentation](https://github.com/minio/minio/blob/RELEASE.2025-09-07T16-13-09Z/docs/docker/README.md)
and [mc release source](https://github.com/minio/mc/blob/RELEASE.2025-08-13T08-35-41Z/cmd/alias-set.go).

The host probe requires at least 2 GiB available, an `fsync` plus atomic rename and directory
`fsync`, and makes no ownership-enforcement claim for the APFS `noowners` volume. PostgreSQL creates
and checkpoints a row, captures a binary
custom-format dump directly into an `O_EXCL`/`O_NOFOLLOW` bounded `0600` file, hashes it, atomically
publishes it and proves the row and data mode after the same container restarts. The child stdout
is read incrementally and never writes beyond 16 MiB; overflow terminates and boundedly reaps the
child after fsyncing the partial file, while stderr is discarded rather than buffered. MinIO
creates a versioned bucket and requires the structured JSON state `Enabled`. It validates one
non-delete version after the first write, then exactly two distinct non-delete version IDs and both
content hashes after the second write and again after restart. Version IDs remain private and never
enter evidence or operator output.

The dump SHA-256 is updated from the same bounded chunks written to the open destination. Size,
mode, link count and identity are validated with `fstat` on that descriptor, and the destination
path must still resolve to the same identity. The digest path is never reopened after capture.

On failure, each exact probe name is recorded as possibly created before its `docker create`
request, so a daemon-side creation followed by a client timeout remains inside the cleanup scope.
Cleanup performs one initial inspect, issues at most one bounded stop when stopped state was not
proven, and then performs exactly one final inspect regardless of inspect or stop ambiguity. The
three secret files may be unlinked only after both exact probe containers are independently
confirmed with `Running=false`, `Restarting=false` and `Pid=0`. If either container is missing from
the created set, cannot be stopped or cannot be verified stopped, every remaining `0600` secret is
retained and the operator receives only bounded cleanup counts and the fixed
`PROBE_SECRET_CLEANUP_REQUIRED`
classification.

Cleanup continues best effort across both probe containers. Stopped state and secret removed or
retained counts are reported only when observed. If an inspect, presence probe or cleanup operation
leaves a value unknown, its numeric value is omitted and the matching `*_known=false` field is
emitted with `PROBE_SECRET_CLEANUP_REQUIRED`; no retained or removed count is estimated.

Any unexpected `OSError`, programming exception or operator interrupt after host mutation enters
the same bounded cleanup and production container/volume recheck. Unexpected failures become the
fixed `PROBE_INTERNAL_FAILURE`; an interrupt is re-raised after cleanup and the command boundary
returns the fixed `PROBE_OPERATOR_INTERRUPT` exit 130 without a traceback or provider payload.

## C2-B and C2-C boundary

Passing C2-A authorizes neither a production backup nor a cutover. C2-B must separately define and
verify logical PostgreSQL backup, MinIO semantic inventory, cold copies, checksums, available
capacity, exact writers/readers stop ordering, isolated restore, restart health and rollback
criteria. The original named volumes remain untouched indefinitely as rollback anchors; this ADR
does not authorize their deletion.

C2-C may introduce the three ignored host-local keys
`DATARIVER_PERSISTENT_DATA_ROOT`, `POSTGRES_DATA_BIND_PATH` and `MINIO_DATA_BIND_PATH` only with a
separate source review. Its cutover transaction must atomically write or roll back both the bind
configuration and the matching `AppliedState.environment_key_hashes`. A failed cutover may not
leave new paths with old hashes or old paths with new hashes. These keys are inactive in C2-A and
normal daily commands keep their existing names and required arguments.

## Evidence boundary

Mocked source tests prove the exact mountpoint-only `0775` exception, arbitrary-root group-write
rejection, world-write and wrong-mode denial, mount/source/owner/device drift, non-symlink local
block-device evidence without source disclosure, directory-descriptor creation and race rejection,
all lifecycle rechecks and failure-path secret retention. They also prove fixed argv, exact
capabilities and limits, CSPRNG lengths, binary stdin,
in-flight dump bounds and child reap, structured two-version readback, immutable image environment,
secret inode/link identity, exact lifecycle ordering, unexpected-failure cleanup, symlink rejection,
stop-before-secret-unlink, APFS noowners non-claim, top-level restart-count validation and immutable
image pins. The recorder covers PostgreSQL start, MinIO start/semantic, first remove, PASS cleanup
and cleanup-handler failures, including exact mutation counts and post-failure production/volume
checks. They do not prove actual
APFS persistence, container entrypoint behavior, production identity preservation or restore
fitness. Those remain `OPEN_TARGET_GATE` until the reviewed probe is explicitly approved and run.
