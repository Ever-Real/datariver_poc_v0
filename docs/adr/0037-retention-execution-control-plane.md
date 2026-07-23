# ADR-0037: Retention execution control plane and archive-only Phase 2

- Status: Accepted
- Date: 2026-07-23
- Refines: ADR-0010, ADR-0012, ADR-0018, ADR-0036

## Decision

Phase 2 introduces a retention-owned execution control plane without introducing a destructive
data path. Human review remains canonical in `retention.erasure_requests`; an approved request is
not mutated into an execution state. A separate execution command is created at most once for the
exact workspace, request version and payload hash. The command freezes the exact target snapshot,
active policy version and hash, maker/checker evidence, execution-authorisation deadline and
archive disposition.

The current four numeric retention fields are named `SINGLE_DEADLINE_V1`. Under a V2 policy,
`chat_content_days` remains the default Chat scheduling deadline and must fall within the V2
`CHAT_CONTENT` minimum/maximum interval; it does not replace those class bounds. A new
`POLICY_BOOK_V2` contract contains exactly one immutable rule for each
governed data class, with an explicit unit, minimum and maximum duration and archive disposition.
It also contains an effective interval and a bounded post-approval execution-authorisation window.
Legacy or incomplete policy versions can never produce an execution command.

Execution commands, fenced attempts and append-only transition events belong to the retention
context rather than generic integration jobs. Claim order is deterministic and bounded. Each claim
increments a monotonic fence and creates a new random lease token whose hash is stored. Completion
and failure compare the command, fence, token hash and database-time lease while holding the job row
lock and incrementing its optimistic version. An expired worker can neither attach a receipt nor
change canonical state.

The scheduler and archive executor use separate `NOBYPASSRLS` PostgreSQL login roles and separate
processes. Both operate only on an explicit deployment allowlist of workspace identifiers and set a
transaction-local RLS context for one workspace at a time. The scheduler has no object-store
credential. The archive executor uses the dedicated `ImmutableArchiveStore`, private endpoint,
bucket, prefix and credential; those credentials are not mounted into the API, relay, upload or
governance workers. Neither process receives a generic SQL, table, object-key, HTTP or provider
command from a client.

For an explicit erasure command, Phase 2 archives only the minimal pseudonymised approval and
execution evidence selected by the active V2 policy. It never copies raw Chat, upload or subject
content into WORM storage merely to make it deletable. The deterministic evidence manifest is
bounded to one MiB, written under a server-generated command/fence/hash key, read back in bounded
chunks, and checked for byte count and SHA-256 equality. Compliance retention and the immutable
object version are read back independently. The existing capability attestation and immutable
receipt tables remain canonical; the execution command references the exact verified receipt and
capability evidence.

Policy, target version/owner/classification, current human eligibility, every applicable
workspace/resource/subject Legal Hold, process kill-switch state, archive configuration and lease are
rechecked before command creation, before archive write and immediately after WORM read-back before
the final database transition. The switch cannot be transactionally read by PostgreSQL; therefore a
post-write disable records the exact immutable receipt and blocks the job instead of claiming
completion. A
Chat target is conservatively affected by both Chat-content and audit-evidence holds. Unsupported
targets, ambiguous impact sets, missing V2 rules, policy drift, expired approval, stale target,
hold, capability mismatch or dependency ambiguity fail closed.

The strongest Phase 2 terminal state is `ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED`. There is no
`DELETED`, `PURGED`, `DROPPED` or generic success state. The operational port contains no delete,
retention-bypass, lifecycle or partition operation, and runtime database roles receive no `DELETE`
or `TRUNCATE` privilege. The adapter's capability probe deliberately attempts deletion of its own
retained challenge version and accepts only a provider/IAM denial; that probe is not exposed as an
execution operation. The public retention automation state remains `DISABLED_NOT_READY` even when
archive-only execution is enabled.

## Runtime gates

Archive-only processing requires all of the following:

1. the Compose profile is explicitly selected;
2. the process kill switch is enabled;
3. a non-empty workspace allowlist is configured;
4. separate scheduler/archive database identities and archive secrets are mounted;
5. the workspace has an effective exact `POLICY_BOOK_V2` policy;
6. current target, Role/membership, Legal Hold and archive capability evidence pass every recheck.

The deployment flag and mounted control file both default to disabled; the file must contain exactly
`ENABLED` and is reread every cycle and at the write boundary. Each worker exposes a
container-internal Prometheus endpoint with
only fixed worker and outcome labels plus cycle/command counts, duration and kill-switch state.
Workspace, subject, target, object key, command and request identifiers are forbidden as labels.

## Consequences

- Phase 2 proves planning, one-time consumption, expired-lease reclamation, stale-fence rejection
  and immutable evidence read-back while preserving zero destructive effects.
- Existing policies and requests are not fabricated or backfilled. Operators must author and
  independently approve a V2 policy before a request can enter the control plane.
- The evidence content and object key are deterministic per command and independent of a retry
  lease. The worker persists the exact capability attestation under its live DB fence before the
  object write, embeds that attestation UUID in object metadata and uses an atomic conditional
  `If-None-Match: *` PutObject with SDK automatic retries disabled. Before a write, and again after
  an ambiguous response, it probes the deterministic key and fully verifies any existing locked
  version instead of creating a duplicate.
- Every expired write lease becomes a read-only recovery fence before current-governance checks. It
  loads the exact persisted attestation by object metadata and provider `LastModified`; it cannot
  call the capability probe or PutObject. Missing evidence may return to a normal attempt only when
  the stored write budget remains. Transient recovery reads are bounded to three fences for each
  write attempt, derived from persisted execution-attempt rows so a later write always gets its own
  recovery opportunity.
- When a verified immutable object cannot complete because the switch closes, governance changes,
  or database completion fails, its exact bucket, key, version, content hash and manifest are
  recorded in the immutable receipt table and linked from the BLOCKED job. A provider checksum or
  retention mismatch cannot be represented as a verified receipt and fails closed; the
  deterministic key remains the reconciliation target. Neither case is deletion authority.
- Receipt capability and policy eligibility are evaluated at the original provider write time.
  Provider `LastModified` is normalized to UTC whole seconds and interpreted as the conservative
  interval `[t, t+1 second)`; the exact capability attestation, policy lifecycle, V2 effective
  interval and execution-authorisation deadline must cover that entire interval. A transition or
  expiry inside the interval fails closed.
  Recovery-time read-back may occur after capability expiry or policy supersession, but a policy
  superseded before the write or a different/missing attestation UUID fails closed.
- The configured archive worker-principal fingerprint is audit attribution rather than a
  provider-discovered identity. Target activation requires accountable-operator evidence binding it
  to the mounted provider access-key principal; HA promotion also requires a simultaneous
  capability-probe rehearsal.
- Target-provider conformance, off-host restore, conditional deletion, partitioning and real
  destructive execution remain separate production gates and require a future ADR and explicit
  approval.
