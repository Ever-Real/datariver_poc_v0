#!/usr/bin/env bash
set -euo pipefail

username=${AIRFLOW_USERNAME:?AIRFLOW_USERNAME is required}
password=${AIRFLOW_PASSWORD:?AIRFLOW_PASSWORD is required}
if [[ ! "$username" =~ ^[A-Za-z0-9._-]{2,64}$ ]]; then
  echo "AIRFLOW_USERNAME has an invalid format." >&2
  exit 2
fi
if (( ${#password} < 12 )); then
  echo "AIRFLOW_PASSWORD must contain at least 12 characters." >&2
  exit 2
fi

umask 077
mkdir -p /opt/airflow/auth /opt/airflow/logs
python -c 'import json, os, pathlib; pathlib.Path("/opt/airflow/auth/passwords.json").write_text(json.dumps({os.environ["AIRFLOW_USERNAME"]: os.environ["AIRFLOW_PASSWORD"]}), encoding="utf-8")'
exec /entrypoint standalone
