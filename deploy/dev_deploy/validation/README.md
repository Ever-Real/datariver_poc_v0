# Bounded regression records

These development-only helpers are stored on `dev`. They are not inputs to the
`dev_deploy` build or deployment. Run them from the candidate checkout root
(`b0d0dd074762a170b8fb6514a92c463dcaecaf81`) after installing its locked development dependencies.
Set `DEV_RECORDS` to this `dev` checkout's absolute `deploy/dev_deploy/validation` path.
No actual provider credentials or production data are used. Docker Compose config parses
synthetic env files; no container, volume, scheduler or provider is mutated.

```sh
python3 "$DEV_RECORDS/test-env.py"
python3 "$DEV_RECORDS/compare-compose.py"
node "$DEV_RECORDS/verify-extraction.mjs"
node --test "$DEV_RECORDS/readiness.test.mjs" "$DEV_RECORDS/acceptance.test.mjs" "$DEV_RECORDS/smoke_prep39083.test.mjs"
```

The two historical comparison helpers require Git objects for Product `2bd5494`
and original candidate `938fa884`. If absent from the tested checkout, set
`DATARIVER_BASELINE_REPO` to the development evidence repository containing them.
This is an explicit historical review input, never a source-build/runtime dependency.
The original 121 contract cases are preserved in Product/dev test history; their
imports were remapped to the locations in `../path-mapping.json` for this run.
The included 59 canonical and nine focused/retry cases preserve the changed smoke policy
and its negative regressions. Synthetic fixture success is not PREP acceptance.

`result.json` summarizes the exact candidate. `fresh-clone-build.json` is the launcher
receipt from a new origin clone with no-cache linux/amd64 git-archive build input.
The Docker identifier is an OCI image **index digest**, not the old Product manifest.
Full build log is retained in the existing local task evidence storage. No new image
is claimed identical to Product `2bd5494`, and no release/acceptance tag was created.
