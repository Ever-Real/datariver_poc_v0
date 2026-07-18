# Legacy archive

This directory contains source snapshots physically retained before a requested
v0.3-parity replacement. They are reference material only: no production build
imports this tree. Each replacement records its source commit and active module.

## 2026-07-18 resumed parity replacements

The CR-coupled MANUAL workbench snapshot is retained at
`frontend/registration/RegistrationManualWorkbench.cr-coupled.tsx`.  It was
replaced because a registration edit must create its own typed submission and
Airflow handoff, not a Change Request.  The archived file is deliberately
outside every build and test include path.
