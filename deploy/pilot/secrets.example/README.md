# Pilot secret-file template

Create one regular file per name in this directory's two manifests, then store the real directory
as `/home/datariver/secrets` with directory mode `0700` and file mode `0600`.

`generated-files.txt` contains credentials owned by this isolated stack. `deploy_pilot.sh` creates
missing values from `/dev/urandom`; keep them stable across upgrades and backups.

`operator-files.txt` contains credentials issued by independently operated providers. The deployer
creates no value for these files and stops until the required default-provider files are present:

- `datahub_token`
- `s3_access_key`
- `s3_secret_key`

The remaining operator files are required only when the matching worker/profile is enabled. Never
put literal values in `.env`, this template, the release archive or Git. Do not reuse preparation-PC
development credentials.
