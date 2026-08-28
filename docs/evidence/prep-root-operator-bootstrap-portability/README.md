# PREP root-operator bootstrap portability evidence

## Scope and boundary

This bounded Product correction changes only the first-install administrator bootstrap process
invoked by `./scripts/prep39083 deploy`. Product business logic, K9, MCL, GlossaryTerm behavior,
authorization policy, migrations, provider configuration, persistent-state ownership and the
build-once artifact transport contract are unchanged.

The target used to reproduce the defect is a disposable TEST PC running Ubuntu 22.04 under WSL2;
it is not Actual PREP. Actual PREP and OPS were not accessed or executed. `origin/main` was not
moved while preparing this candidate.

## Reproduced defect

The canonical first-install flow was exercised from a root-owned WSL checkout. Provider doctor
passed and the exact promoted linux/amd64 archive was accepted. The deploy reached `SCHEMA_READY`
and then stopped at `TARGET_BOOTSTRAP / PREP_BOOTSTRAP_FAILED` before Web start or authenticated
smoke.

A bounded replay through the same bootstrap module exposed the sanitized child failure:

```text
code   EACCES
reason permission denied opening /run/prep-admin.password
```

The operator-side deployer correctly created a short-lived password file with mode `0600`. Docker
bind-mounted that file read-only, while the Product image's default `USER node` ran the one-shot
bootstrap process with a different Linux UID. On a root-operated host, the container process could
therefore not read the file. The failure was host-UID dependent and was not an authentication,
password-policy, database, provider or Product-state defect.

The failed attempt retained the exact runtime secrets and named state volumes at `SCHEMA_READY`.
No administrator had been created, Web had not started, and no reset, volume deletion, resecret or
manual checkpoint mutation was performed.

## Minimal correction

For the `created == true` bootstrap path only, the disposable Compose `run` command now includes:

```text
--user 0:0
--volume <private-mode-0600-file>:/run/prep-admin.password:ro
```

The container is not privileged, receives no Docker socket, and has no new host write mount. The
secret remains in one mode-0600 host file, is mounted read-only, is never placed in an environment
variable or command-line value, and is deleted by the existing context manager. The normal Web
service continues to run as `USER node`.

When an administrator already exists, the bootstrap command does not elevate the container user,
does not mount the password file and does not pass `--admin-password-file`; its password remains an
in-memory smoke credential under the existing contract.

## Verification at Product checkpoint

Product:

```text
be74759b2eec0c61090feaeba9e110d66ab3e334
```

Executed evidence:

```text
Focused bootstrap/deploy classifications                  12/12 PASS
PREP deploy + Handoff unit suites                       120/120 PASS
Isolated state-machine/non-destructive recovery Docker     1/1 PASS
Ruff lint                                                    PASS
Ruff format                                                  PASS
strict mypy, changed deployment source                       PASS
static/source/migration-integrity contracts                  PASS
```

The test module has four pre-existing strict-mypy errors in an unrelated artifact-test helper that
returns `object`; the changed deployment source itself passes strict mypy. The Docker integration
initially stalled in the local Docker Desktop credential helper. Re-running with an isolated empty
credential config and the installed Compose plugin produced the recorded PASS; this was a host
tooling condition, not a Product failure.

## Exact Product artifact

The clean Product checkpoint was built once for linux/amd64 and exported without rebuilding:

```text
Image          datariver-poc:be74759b2eec0c61090feaeba9e110d66ab3e334
Archive SHA256 ccf6ecb2873981e6db7297e82741a58f03995b179d7b1bb90dcdb7a17da63c8a
Manifest       sha256:5f4153b2e6978dc5a1dc6204bf66a482314162543dd9e9fc6e6e6820fdf757d3
Config         sha256:4269a48efe853b74f2a4ea006dfd9b58770e21115498d4cf57073ab75e2e5a2c
Platform       linux/amd64
OCI revision   be74759b2eec0c61090feaeba9e110d66ab3e334
```

The archive remains an ignored release artifact and is not committed to Git.

## Remaining runtime gate

The TEST PC's retained `SCHEMA_READY` attempt must be updated to the descendant Handoff and resumed
with the unchanged canonical command. Acceptance requires exact artifact verification, no rebuild,
administrator creation, health, K9, MCL, GENERAL and GlossaryTerm smoke, preservation of the target
secrets/volumes/identities, and a final `ACCEPTED` receipt. This result is TEST evidence only and
must not be described as Actual PREP or OPS acceptance.
