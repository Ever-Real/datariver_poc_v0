# Wave B AC-01 password-change audit review

## Verdict

Product source `0fe6af3285ea184e69020d6c5617f19641afc8c2`, including AC-01
implementation `74cf02e`, does not yet satisfy the durable password-change audit
criterion. The credential `version` and `updated_at` fields are current mutable
state, not accepted audit evidence. No canonical immutable audit or outbox sink
exists inside the Node POC local-auth persistence boundary, so this review does
not invent one or write into another subsystem's ledger.

The remaining AC-01 result is therefore `NEEDS_DECISION` for the Product-owned
local-auth audit contract. The implemented password-change behavior remains
source-verified for current-password verification, Argon2id replacement,
replacement policy, self-only targeting, and atomic all-session revocation.
No TEST, PREP, OPS, deployment, or publication action was performed.

## Source evidence

- `frontend/poc-local-auth.mjs` reads the credential by the authenticated
  subject, verifies the supplied current password with the existing Argon2id
  verifier, validates the bounded replacement policy, hashes the replacement
  with Argon2id, and calls the credential CAS. It accepts no target subject.
- `frontend/poc-state-store.mjs::administerLocalCredential` locks the exact
  credential row, checks its version, updates the credential, revokes all
  unrevoked sessions for that subject, and commits those effects in one
  PostgreSQL transaction. The returned result includes the new credential
  version and revoked-session count, but no durable event is inserted.
- `poc_local_credentials.version` is also advanced by login success/failure and
  administrator credential changes. `updated_at` is overwritten by those
  operations. Neither field identifies a self password change, preserves an
  event history, identifies the actor, or records the revoked-session count.
- `deploy/poc/postgres-init/001-poc-state.sql` and the matching runtime DDL
  contain credentials and sessions but no local-auth event or outbox table.
- The `poc_change_history_ledger_events` contract is normalized external
  DataHub MCL evidence. Its source identity, topic/partition/offset, Dataset
  aspect, category, and operation constraints cannot represent a local
  password change without violating that ledger's accepted purpose.
- The FastAPI `integration.outbox_events` table belongs to the separate
  Alembic-managed Workspace/RLS application architecture. The POC Compose
  profile uses the isolated `datariver_poc` database and its own schema/init
  contract, so writing the POC password transaction into that backend table
  would create an unapproved cross-subsystem dependency and would not be
  atomic in the deployed topology.
- The Product-owned PostgreSQL fingerprint covers every public `poc_*` table,
  column, constraint, index, trigger, and function. With integrity enabled,
  startup inspects the exact fingerprint and receipt before applying DDL.
  Adding a local-auth event table therefore requires an authorized schema
  revision and upgrade path; it is not a safe additive source-only change.

## Bounded future contract

The smallest safe follow-up is a Product-approved local-auth event store in the
same POC PostgreSQL database, implemented together with the owned-schema
revision/upgrade contract. It should:

1. append exactly one immutable `SELF_PASSWORD_CHANGED_V1` event in the same
   transaction as credential CAS and all-session revocation;
2. store only an event ID, bounded event type, subject ID (or an approved keyed
   subject hash), actor kind `SELF`, actor subject binding, database-derived
   `occurred_at`, resulting credential version, and revoked-session count;
3. enforce actor equals subject for this event type, uniqueness for the
   resulting subject/credential version, bounded values, and append-only
   update/delete protection;
4. never accept or persist the password, password hash, session token/hash,
   username, request body, cookie, or secret-derived material in the event;
5. fail the whole password change if the event insert fails, with PostgreSQL
   fault-injection evidence proving no credential, session, or event partial
   commit; and
6. advance the Product-owned schema revision/fingerprint through an approved
   migration from the currently receipted schema. The current
   `KNOWN_OLDER_MIGRATABLE` path only accepts an older fingerprint without a
   receipt, so it does not by itself authorize migration of a valid current
   receipted deployment.

No audit-read UI or API is required for this bounded write-side correction.
Retention, export, subject-hash policy, and any future read authorization remain
Product/Security decisions rather than assumptions in AC-01.
