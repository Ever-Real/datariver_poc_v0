# ADR-0068: Live connection status and source-host Chat governance bootstrap

- Status: Accepted
- Date: 2026-07-28
- Refines: ADR-0046, ADR-0048, ADR-0050, ADR-0064
- Supersedes: ADR-0064 decision 4-5 only for the Admin button interaction

## Context

Admin System Settings showed a button named **현재값 테스트 후 반영 명령 복사**. The running
API had already loaded those values, so probing the old snapshot and copying a restart command did
not apply a connection and was misleading. The page also conflated configured transport with
governed Chat readiness and had no visible connection lifecycle.

The explicit governed Chat bootstrap supported a Compose API container only. The WSL preparation
profile runs the API from source, so its successful model probes could still leave all three
provider-profile UUIDs unset and Chat correctly failed closed with
`INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE`.

## Decision

1. System Settings keeps the deployment environment and mounted secrets as its only live
   configuration source. The browser still cannot submit a URL or credential, write `.env`, run a
   host command, or restart a process.
2. **테스트 후 반영** invokes the existing fixed, body-free deployment probe. While it runs, the
   selected page state is `연결중`; an `AVAILABLE` result is immediately reflected as `연결됨`
   and `정상 연결됨`; a negative result becomes `오류`. Before a successful probe the state is
   `미연결`.
3. Connection badges are current-page probe evidence, not durable provider health, desired state
   or inference authorization. Refreshing the server inventory clears them until another probe,
   avoiding stale status across a changed environment or API restart.
4. Core and LLM navigation badges aggregate only configured, probeable members. All such members
   must have a successful applied probe before the aggregate becomes green `연결됨`.
5. An enabled inference adapter without its stage-specific deployment
   `CHAT_*_PROVIDER_PROFILE_VERSION_ID` is reported as `GOVERNED_PROFILE_REQUIRED`. Its transport
   probe remains available, but the UI separately explains that Chat still needs an exact approved
   provider profile and active classification-policy binding.
6. The explicit governed Chat wrapper selects execution from
   `DATARIVER_OPERATOR_PROFILE`. `source-host-development` and `wsl-source-host` execute the same
   module through `dev_host.sh`, which reconstructs the selected source-host Settings and secret
   mapping. Container profiles retain the existing Compose execution. The governance command,
   maker/checker rules and explicit retention inputs are unchanged.

## Consequences

- Admin no longer pretends that copying a command applied a connection, and connection state is
  visible at the page, navigation-group and connector-result levels.
- A green model connection badge proves only the fixed model probe. It cannot override missing,
  revoked or mismatched inference governance.
- Changing environment values still requires the stable operator workflow and process recreation.
- Preparation-PC operators can create the exact governed Chat bindings without converting the
  source-host runtime into a container topology.
- This change adds no database state or migration and grants no new infrastructure privilege.
