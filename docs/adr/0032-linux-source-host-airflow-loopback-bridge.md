# ADR-0032: Linux source-host Airflow loopback bridge

- Status: Accepted
- Date: 2026-07-22
- Refines: ADR-0013, ADR-0021

## Context

In source-host development, Uvicorn and mutable DataRiver workers run from the checkout and bind the
API to `127.0.0.1`. Airflow stays containerized for its isolated scheduler database, Keycloak client
credential and retry contract. On Linux and WSL, `host.docker.internal` resolves to a private Docker
bridge address, not the host loopback namespace. Directing Airflow to source API port `38101` cannot
reach the listener; falling back to `http://api:8000` is also invalid because the containerized API
is deliberately absent in this topology.

## Decision

Keep Uvicorn loopback-only. When the source API itself runs on Linux/WSL, the operator explicitly
uses `bootstrap.sh --host-development --source-host-airflow-bridge`. It sets the ignored deployment
values `AIRFLOW_SOURCE_API_BRIDGE_ENABLED=true`, `AIRFLOW_SOURCE_API_BRIDGE_PORT=38103` and
`DATARIVER_API_BASE_URL=http://host.docker.internal:38103`. A WSL checkout whose source API runs on
Windows does not select this bridge and retains the existing direct host gateway.

`dev_host.sh start` discovers Docker's default-bridge gateway and validates that it is a non-loopback
RFC1918 IPv4 address. It then starts a managed standard-library TCP bridge on that address only,
with a 32-connection bound and a fixed target of `127.0.0.1:<source API port>`. The bridge never
binds all interfaces, a LAN address or a public endpoint. It carries opaque HTTP bytes only: DataRiver
still validates the Airflow Keycloak service token, workspace, ABAC and PostgreSQL RLS. The bridge
has no DataHub credential or provider egress, and starts/stops with source-host processes.

Airflow's `NO_PROXY`/`no_proxy` covers only local Compose/source-host names so a corporate proxy
cannot intercept Keycloak client-credential or local API calls. It does not alter DataHub egress,
which remains exclusively in the DataRiver API.

macOS continues to use its Docker Desktop loopback gateway at port `38101`. Production and shared
deployments do not use this Single-node Pilot transport shim.

## Consequences

- Linux/WSL Airflow tasks can reach the source API without widening the API's listener.
- `dev_host.sh status` reports `airflow-api-bridge`; a bridge startup failure is explicit in
  `runtime/source-host/airflow-api-bridge.err.log`.
- Operators recreate Airflow after bootstrap and start source-host before scheduler services.
- This is not an authorization gateway, public service or production deployment pattern.
