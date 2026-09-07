#!/usr/bin/env python3
"""Temporary PREP acceptance launcher; no Product/runtime integration.

Remove this file and its test after Product 2bd5494d Actual PREP acceptance is recorded.
Uses only the existing AUTO3 probe: three completions, no retries or new diagnostics.
Delivered from origin/dev; the current Product/Release/OCI are not changed.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PRODUCT = "2bd5494d6f100abc8e50a844e0d01c30b93cc698"
PROBE = "scripts/prep39083-general-classifier-rca-probe"
RELEASE = "refs/remotes/origin/prep39083-release"


class VerificationFailure(Exception):
    pass


def command(root, arguments, stage):
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell evaluation.
        arguments,
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode:
        raise VerificationFailure(stage)
    return result.stdout.strip()


def summarize(output, expected_head):
    if len(output) > 4096 or len(output.splitlines()) != 1:
        raise VerificationFailure("OUTPUT_CONTRACT")
    if not output.startswith("RCA_AUTO|"):
        stage = re.search(r"(?:^|\|)stage=([A-Z0-9_]{1,64})(?:\||$)", output)
        failure = stage.group(1) if stage else "PROBE"
        if failure.startswith("PRODUCT_"):
            for name in ("expected", "running"):
                value = re.search(
                    rf"(?:^|\|){name}_product=([0-9a-f]{{8}}|UNKNOWN)(?:\||$)", output
                )
                failure += f"|{name}={value.group(1) if value else 'UNKNOWN'}"
        raise VerificationFailure(failure)
    summary = dict(part.split("=", 1) for part in output.split("|")[1:])
    if summary["mode"] != "AUTO3" or summary["diag"] != expected_head[:8]:
        raise VerificationFailure("OUTPUT_MODE_IDENTITY")
    detail = Path(summary["detail"])
    # Match the private mktemp path produced by the existing probe; no file is created here.
    pattern = r"/tmp/datariver-prep39083-rca\.[A-Za-z0-9]+/diagnostic\.log"  # noqa: S108
    if not re.fullmatch(pattern, str(detail)):
        raise VerificationFailure("DETAIL_PATH")
    with detail.open() as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise VerificationFailure("DETAIL_SIZE")
    record = json.loads(raw)
    evidence = record["evidence"].strip()
    if not evidence.startswith("GENERAL_RCA_EVIDENCE|") or len(evidence.splitlines()) != 1:
        raise VerificationFailure("EVIDENCE_CONTRACT")
    fields = dict(part.split("=", 1) for part in evidence.split("|")[1:])
    if record["mode"] != "AUTO3" or fields["mode"] != "AUTO3":
        raise VerificationFailure("MODE")
    if record["diag"] != expected_head or fields["diag"] != expected_head:
        raise VerificationFailure("DIAGNOSTIC_IDENTITY")
    runs = [fields[f"run{i}"].split(",") for i in (1, 2, 3)]
    stop = sum(run[5] == "STOP" for run in runs)
    valid = all(run[9] in ("JSON_OBJECT_EXACT_KEYS", "JSON_OBJECT_OTHER_KEYS") for run in runs)
    # Existing Product validation checks types/bounds; EXACT_KEYS closes surplus keys.
    schema = all(run[0] == "PASS" and run[9] == "JSON_OBJECT_EXACT_KEYS" for run in runs)
    semantic = all(run[0] == "PASS" and run[8] == "GENERAL" for run in runs)
    constraint = fields["constraint"] == "PASS"
    binding = fields["discovery_bind"] == "SQL_NULL"

    def status(value):
        return "PASS" if value else "FAIL"

    bind = "SQL_NULL" if binding else "FAIL"
    line = (
        f"CLASSIFIER_3X|finish=STOP_{stop}/3|json={status(valid)}"
        f"|schema={status(schema)}|semantic={status(semantic)}"
        f"|constraint={status(constraint)}|discovery_bind={bind}"
    )
    return line, 0 if stop == 3 and valid and schema and semantic and constraint and binding else 2


def verify():
    root = command(None, ["git", "rev-parse", "--show-toplevel"], "CHECKOUT")
    command(
        root,
        [
            "git",
            "fetch",
            "-q",
            "origin",
            "refs/heads/dev:refs/remotes/origin/dev",
            f"refs/heads/prep39083-release:{RELEASE}",
        ],
        "FETCH",
    )
    head = command(root, ["git", "rev-parse", "origin/dev"], "DIAGNOSTIC_IDENTITY")
    release = json.loads(
        command(root, ["git", "show", f"{RELEASE}:deploy/prep39083/release.json"], "RELEASE")
    )
    if release.get("product_sha") != PRODUCT:
        raise VerificationFailure("TARGET_PRODUCT_CHANGED")
    source = command(root, ["git", "show", f"{head}:{PROBE}"], "PROBE_SOURCE")
    if "PREP39083_RCA_AB_IDENTITY_V2" not in source or "'--auto-3'" not in source:
        raise VerificationFailure("STALE_DIAGNOSTIC")
    checkout = Path(tempfile.mkdtemp(prefix="datariver-prep39083-verify-"))
    added = False
    try:
        command(
            root,
            ["git", "worktree", "add", "-q", "--detach", str(checkout), head],
            "CHECKOUT_CREATE",
        )
        added = True
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell evaluation.
            ["bash", str(checkout / PROBE), "--auto-3"],  # noqa: S607 - operator's Bash.
            cwd=checkout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        line, status = summarize(result.stdout.strip(), head)
        if result.returncode and status == 0:
            raise VerificationFailure("PROBE_EXIT")
        return line, status
    finally:
        if added:
            # Never force-remove a checkout that somebody has modified.
            subprocess.run(  # noqa: S603 - only this helper's newly created checkout.
                ["git", "worktree", "remove", str(checkout)],  # noqa: S607 - operator's Git.
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        if checkout.exists():
            try:
                checkout.rmdir()
            except OSError:
                pass


def main():
    try:
        if len(sys.argv) != 1:
            raise VerificationFailure("ARGUMENTS")
        line, status = verify()
    except VerificationFailure as error:
        line, status = f"CLASSIFIER_3X|state=UNAVAILABLE|stage={error}", 2
    except (AttributeError, IndexError, KeyError, OSError, ValueError, TypeError):
        line, status = "CLASSIFIER_3X|state=UNAVAILABLE|stage=LOCAL_CONTRACT", 2
    print(line)
    return status


if __name__ == "__main__":
    sys.exit(main())
