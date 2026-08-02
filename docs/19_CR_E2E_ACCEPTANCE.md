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
   `change.create` and `change.edit`; **Reviewer** has the review/approval permissions required by
   the deployment.
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
| 3 | Requester | Submit the typed intake with a non-empty requested-change reason and one allowlisted REQUEST sample file. | The detail view shows immutable target binding/evidence, exactly one finalized REQUEST manifest and a legal initial state. No DataHub login/token or raw aspect editor appears. |
| 4 | Reviewer | In a separate browser profile, sign in as the independent reviewer and open the same CR through the authorized list. | The current target is reauthorized; a requester cannot approve their own CR. If the deployment asks for step-up, complete its real WebAuthn ceremony before retrying the explicit action. |
| 5 | Reviewer | Start review and choose recoverable **보완 요청**, not terminal **최종 반려**, with a reason. | The CR reaches `CHANGES_REQUESTED`; the previous round, item set, REQUEST attachment, decision and transition remain readable and immutable. |
| 6 | Requester | Reopen the CR, choose **요청 수정**, and actually change the title, reason/content and at least one existing/new table or field before submitting. | Only the original requester sees the enabled editor. Submission uses the exact selected System and current target reader, creates one EDITED round with new item IDs, and returns to `REGISTERED`; the old round is unchanged. |
| 7 | Reviewer | Reopen the revised CR, approve REVIEW and move it into `TESTING`. | The list/detail state and ETag agree, only current-round targets count, and prior-round approval is not reused. |
| 8 | Reviewer | Upload the allowlisted sample file as TEST result evidence for the current round. | Exactly one finalized TEST manifest is bound to the current round and current Developer; the historical REQUEST file is not moved or reused. |
| 9 | Reviewer | Submit the final approval path with the deployment-required independent actors and assurance. | Version/ETag changes after each command; refresh shows append-only approval/transition evidence and no stale or self-approved mutation. |
| 10 | Authorized completion actor | Run the explicit intake-completion action only after the required final approval. | The CR reaches `COMPLETED` for typed intake. This is distinct from DataHub `APPLIED`; no provider mutation is inferred. |
| 11 | Requester and Reviewer | Refresh both sessions and reopen the CR. | Both see the same current state plus historical rounds/evidence within their permissions; no credential, secret or unbounded provider response is displayed. |

## Negative checks

- Attempt final approval with the Requester. It must fail.
- Attempt a command using an obsolete `If-Match`/version after the other subject changes the CR. It
  must fail without changing state.
- Confirm the terminal **최종 반려 (재상신 불가)** action is visually distinct from **보완 요청**;
  arming/cancelling it must cause zero POSTs, and a terminal `REJECTED` CR must never expose the
  revision command.
- Attempt revision as the Reviewer, against a different System, and with the same idempotency key
  plus a changed body. Each must fail without a second round/item/link/transition/outbox effect.
- Confirm prior-round targets and attachments cannot satisfy current-round revision, attachment or
  final-approval checks.
- If a target loses authorization between creation and review, the subsequent fresh target read must
  be denied or existence-hidden; the previous browser display is not authorization evidence.
- Verify that changing only a Tag/Term input does not write a controlled vocabulary directly to
  DataHub.

## Evidence and pass criteria

Record the deployment identifier, timestamp, redacted browser screenshots of the CR state at each
transition, opaque CR ID, actor role (not credentials), round ID/revision kind, response version,
attachment kind/hash metadata, required assurance result and the final state. Compare the list,
detail and audit evidence after every exactly-once mutation. Link the evidence from the release
acceptance record.

The run passes only if all positive steps and negative checks hold with two independent human
identities. A failed DataHub SSO frame, browser-control connection, unavailable authenticator, or
missing permission is an environment gate to remediate and rerun; it is not evidence that the CR
workflow succeeded.
