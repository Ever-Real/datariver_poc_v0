# Temporary operator files

These are removable acceptance helpers delivered through `origin/dev`, not Product runtime,
release tooling or a legacy subsystem. This directory is excluded from Docker build context.

`prep39083-verify.py` only wraps the existing AUTO3 probe for Product `2bd5494d`. It fetches refs,
uses and removes its own detached checkout, and prints one `CLASSIFIER_3X` line. Caller checkout
files/HEAD, deployment, databases and graph pointers are unchanged. Existing private evidence
files are retained locally; do not ask the operator to copy them. A different target Product is
rejected before probe execution.

After the new Release is deployed, run from the PREP repository:

```bash
git fetch -q origin dev &&
git show origin/dev:scripts/temporary/prep39083-verify.py | python3
```

Removal condition: once Actual PREP acceptance for Product `2bd5494d` is recorded, delete this
directory and its `.dockerignore` entry. Do not import it into application code, normal deploy
scripts or CI gates.

Offline launcher verification: `python3 scripts/temporary/prep39083-verify.test.py` (five tests,
including stdin execution against isolated local Git fixtures; no Docker or provider calls).
