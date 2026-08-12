# command-permissions.md

## 1. Two Layers
- **Layer A:** Repository policy.
- **Layer B:** Actual Antigravity runtime.
- Policy approval never implies prompt removal. `LOW_RISK_COMMANDS_PREAPPROVED=TRUE` only inside scope.

## 2. Class A
- Filesystem: `pwd`, `cd`, `ls`, safe `find`/`rg`/`grep`/`head`/`tail`/`wc`/`file` and `cat`/`sed`/`awk` read-only.
- Exclude: `.env` values, `secrets/**`, SSH keys, token/password files, credential stores, and never output secrets.
- Git allowed: `git status`; `diff`; `diff --check`; `log`; `show`; `rev-parse`; `merge-base` including `--is-ancestor`; `branch --show-current`; `ls-files`; `grep`; `worktree list`. Explicitly no git wildcard.

## 3. Class B
- Existing repo `uv run`/`pytest`/`ruff`/`mypy` and existing scripts; `npm test`/`run test`/`lint`/`typecheck`/`build` plus task-approved dev/test command; static/schema/formatter check/unit/integration/local build/read-only health check.
- Conditions: no dependency/system install, PREP/OPS, credential/external publication/destructive data.
- Check dirty/tracked diff afterward; outputs allowed.

## 4. Class C
- **20:** only `docker ps`/`images`/`inspect`/`logs`/`compose config`/`compose ps` read-only; no lifecycle.
- **40:** task read-only provider query/probe; no DataHub writes/Airflow triggers/Neo4j writes/MinIO upload-delete.
- **50:** broad current-candidate read/test/build; no repair.
- **90:** read-only inspection/static/security validation; no repair.

## 5. Class D
- Only explicitly dispatched Builder with task identity, owner, exact SHA, allowed paths, acceptance.
- Edit only allowed paths without per-file prompt at policy layer. Out-of-scope edit not auto-approved.
- Commit only if repository policy and Controller Task preapproval; never equivalent to push.

## 6. Always Governed
- `git push`/`force`/`merge` governed branch/history rewrite/destructive `reset`/`clean`/`.git` edit/remote change.
- Credential generation/output/secret/auth-security guard/firewall/network policy.
- Dependency add/delete/package/global/system install/sudo/root.
- Migrations/destructive SQL/schema/data mutations/truncate/drop.
- Container lifecycle/destructive volume/PREP/OPS runtime.
- G1 integration/G2 publication/G3/G4.

## 7. Explicit Deny (unless separately approved task)
- Broad `rm -rf`, destructive outside repo, home traversal, SSH/private key changes, validator/security bypass, remote pipe-to-shell, unknown binary, cleanup/reset hiding failures, dummy credential, unapproved external mutation. BLOCKED/FOLLOW_UP.

## 8. Session/Runtime
- Apply common policy to 20, 30, 40, 50, 60, 98; no per-command controller messages/heartbeats.
- Exact runtime evidence: CLI 1.1.12, POC-only project id: 18df69b7-f847-48c1-b41d-9e6f38f4200e, Resource only: datariver_poc_v0.
- Note project allow/deny/ask config was applied as a stored scoped config but safe prompt suppression FAILED, so Runtime Config status is PARTIAL_POLICY_LOADED / RUNTIME_PERMISSION_BLOCKED, never APPLIED.
- Global `toolPermission=request-review` caused the prompt even with `command(pwd)` allowlisted, and global always-proceed and `--dangerously-skip-permissions` were NOT applied because they exceed repository scope and weaken governance.

## 9. Invariants
- Keep no hardcoding/hallucination/architecture destruction; G1-G4 unchanged.
