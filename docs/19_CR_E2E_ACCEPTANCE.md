# Two-person Change Request browser acceptance

## Purpose and scope

This runbook is the target-environment acceptance procedure for an ordinary typed Change Request
(CR) intake. It proves the requester, independent reviewer and final completion path through the
browser. It is deliberately not a provider-apply test: intake stores governed proposal evidence and
does not grant the browser a DataHub credential or perform a DataHub mutation.

Automated unit, contract and component tests do not replace this procedure because it requires real
OIDC sessions and any deployment-required recent WebAuthn ceremony. Do not use a service account,
password grant, copied bearer token, mocked reviewer or browser-supplied provider URL as a shortcut.

## Preconditions

1. The target deployment reports API readiness and the browser uses the configured OIDC
   authorization-code + PKCE flow.
2. Prepare two distinct active human subjects in the same workspace: **Requester** has
   `change.create`; **Reviewer** has the review/approval permissions required by the deployment.
   The subjects must not share an identity, access token or browser profile.
3. Enroll and verify a real user-verifying WebAuthn authenticator for every action whose deployed
   assurance policy requires it. A password, OTP or numeric ACR alone is not evidence of hardware
   assurance.
4. Select a non-restricted existing catalog asset with at least one column, or use a clearly marked
   new-table proposal. Record only its opaque DataRiver asset ID in the acceptance record.
5. Do not place passwords, recovery codes, bearer tokens, raw WebAuthn assertions, DataHub service
   tokens, secret references or personal IP addresses in screenshots or test evidence.

## Browser procedure

| Step | Actor | Action | Required observation |
|---|---|---|---|
| 1 | Requester | Sign in, select the verified workspace, open Change Management and create a new CR. | The page exposes only server-authorized data and a new opaque CR number/ID. |
| 2 | Requester | Add an existing table, select or enter table/column Terms and Tags, and add a column. Open each `+` picker once without a keyword and once with one. | The picker shows its bounded existing vocabulary results, keyword narrowing works, and a comma-delimited unknown value is marked as a new proposal rather than a provider write. Table and column tracks remain aligned. |
| 3 | Requester | Submit the typed intake with a non-empty requested-change reason. | The detail view shows immutable target binding/evidence and a legal initial state. No DataHub login/token or raw aspect editor appears. |
| 4 | Reviewer | In a separate browser profile, sign in as the independent reviewer and open the same CR through the authorized list. | The current target is reauthorized; a requester cannot approve their own CR. If the deployment asks for step-up, complete its real WebAuthn ceremony before retrying the explicit action. |
| 5 | Reviewer | Move through the legal review/final-approval actions, giving a reason for each decision. | Version/ETag changes after each command; refresh shows the append-only transition and approval evidence. A stale version, self-approval, or invalid transition is rejected without replay. |
| 6 | Authorized completion actor | Run the explicit intake-completion action only after the required final approval. | The CR reaches `COMPLETED` for typed intake. This is distinct from DataHub `APPLIED`; no provider mutation is inferred. |
| 7 | Requester and Reviewer | Refresh both sessions and reopen the CR. | Both see the same governed state and evidence within their permissions; no credential, secret or unbounded provider response is displayed. |

## Negative checks

- Attempt final approval with the Requester. It must fail.
- Attempt a command using an obsolete `If-Match`/version after the other subject changes the CR. It
  must fail without changing state.
- If a target loses authorization between creation and review, the subsequent fresh target read must
  be denied or existence-hidden; the previous browser display is not authorization evidence.
- Verify that changing only a Tag/Term input does not write a controlled vocabulary directly to
  DataHub.

## Evidence and pass criteria

Record the deployment identifier, timestamp, redacted browser screenshots of the CR state at each
transition, opaque CR ID, actor role (not credentials), required assurance result, response version
and the final state. Link the evidence from the release acceptance record.

The run passes only if all positive steps and negative checks hold with two independent human
identities. A failed DataHub SSO frame, browser-control connection, unavailable authenticator, or
missing permission is an environment gate to remediate and rerun; it is not evidence that the CR
workflow succeeded.
