# ADR-0064: Admin environment identity and operator-command handoff

- Status: Accepted
- Date: 2026-07-28
- Refines: ADR-0046, ADR-0048, ADR-0063
- Owners: Application, Security and Operations

## Context

An administrator needs to know which deployment environment supplied the running System Settings
snapshot. After changing connector values, the administrator also needs an unambiguous route to
the correct operator workflow.

The regular API cannot safely execute that workflow. In a source-host deployment the workflow can
restart the API serving the request, so the HTTP operation cannot own its own reliable completion.
In a source-free Pilot container there is no source checkout or
`scripts/workflow_update_restart.py`, and the API has neither the host Docker socket nor permission
to control host processes. Adding either capability would turn a connector-read permission into
host infrastructure control and violate ADR-0048 and ADR-0063.

## Decision

1. Bootstrap and Pilot templates write two non-secret metadata values into the selected deployment
   environment: `DATARIVER_ENV_FILE` and `DATARIVER_OPERATOR_PROFILE`.
2. Admin **System settings** returns those values only from the API process's already validated
   `Settings` snapshot. It does not discover, open, parse, write or synchronize a host file.
3. The API maps the closed operator-profile vocabulary to one server-owned command:
   `workflow_update_restart.py` for managed development profiles, `development_cycle.py
   prep-update` for the WSL source host, a bounded `dev_host.sh` sequence for other source-host
   development, and `deploy_pilot.sh` for the source-free Pilot.
4. The browser may run the existing fixed, body-free connection probe against the current runtime
   snapshot. Only an `AVAILABLE` result permits the UI to copy the mapped command. The browser never
   supplies a path, profile, URL, command or argument.
5. The copied command is an operator handoff, not browser execution. The operator runs it from the
   appropriate host terminal. That workflow validates the edited environment and performs the
   required restart/redeployment. A successful pre-copy probe proves only the old running snapshot.
6. The source-free Pilot keeps `/home/datariver/.env` as its one environment file and
   `source-free-pilot` as its profile. `deploy_pilot.sh` rejects any other identity. It never invokes
   the source-checkout workflow.

## Consequences

- Admin can identify the effective environment without exposing a secret value or creating a
  second desired-state store.
- A browser compromise cannot acquire the Docker socket, spawn a host command or restart the API.
- Environment changes remain a two-step operation: edit host-owned configuration, then run the
  copied operator command. The post-change workflow is the authoritative validation.
- WSL source-host and source-free Pilot lifecycle commands are visibly different. Operators do not
  accidentally run an unavailable source workflow on the Pilot server.
- This change adds no database state or migration and does not alter production deployment paths.

## Rejected alternatives

- Mounting the Docker socket or source checkout into the API: excessive host privilege and violates
  the source-free release boundary.
- Spawning a detached self-restart from the HTTP handler: no durable completion/result channel and
  the serving process can terminate before a trustworthy response.
- Accepting a browser-supplied environment path or shell command: command-injection and arbitrary
  file-selection boundary.
- Treating a successful current-runtime probe as validation of an edited but unapplied file: tests
  the wrong configuration snapshot.
