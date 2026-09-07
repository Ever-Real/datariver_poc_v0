"""Offline checks for the temporary launcher; no Docker or provider access."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

SCRIPT = Path(__file__).with_name("prep39083-verify.py")
SPEC = importlib.util.spec_from_file_location("temporary_verify", SCRIPT)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
HEAD = "a" * 40
RUN = "PASS,NONE,NONE,1,STRING,STOP,NONE,NONE,GENERAL,JSON_OBJECT_EXACT_KEYS,NONE,controls,usage"
SUCCESS = (
    "CLASSIFIER_3X|finish=STOP_3/3|json=PASS|schema=PASS|semantic=PASS"
    "|constraint=PASS|discovery_bind=SQL_NULL"
)


class TemporaryVerifierTests(unittest.TestCase):
    def setUp(self):
        self.detail_dir = Path("/tmp") / f"datariver-prep39083-rca.{uuid.uuid4().hex}"  # noqa: S108 - unique private fixture.
        self.detail_dir.mkdir(mode=0o700)
        self.addCleanup(shutil.rmtree, self.detail_dir)
        self.detail = self.detail_dir / "diagnostic.log"

    def output(self, *, run=RUN, head=HEAD, mode="AUTO3", constraint="PASS", bind="SQL_NULL"):
        fields = (
            f"GENERAL_RCA_EVIDENCE|mode={mode}|diag={head}|run1={run}|run2={RUN}|run3={RUN}"
            f"|constraint={constraint}|discovery_bind={bind}"
        )
        self.detail.write_text(json.dumps({"diag": head, "mode": mode, "evidence": fields}))
        self.detail.chmod(0o600)
        return f"RCA_AUTO|diag={head[:8]}|mode={mode}|detail={self.detail}"

    def test_three_valid_general_routes_pass(self):
        self.assertEqual(verify.summarize(self.output(), HEAD), (SUCCESS, 0))

    def test_length_schema_semantic_and_persistence_failures_cannot_pass(self):
        cases = (
            ({"run": RUN.replace(",STOP,", ",LENGTH,")}, "finish=STOP_2/3"),
            ({"run": RUN.replace("EXACT_KEYS", "OTHER_KEYS")}, "schema=FAIL"),
            ({"run": RUN.replace("JSON_OBJECT_EXACT_KEYS", "INVALID_JSON")}, "json=FAIL"),
            ({"run": RUN.replace(",GENERAL,", ",GRAPH,")}, "semantic=FAIL"),
            (
                {"run": RUN.replace("PASS,", "CLASSIFIER_SCHEMA_VALIDATION_FAILED,", 1)},
                "schema=FAIL",
            ),
            ({"constraint": "FAIL"}, "constraint=FAIL"),
            ({"bind": "JSON_NULL"}, "discovery_bind=FAIL"),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                line, status = verify.summarize(self.output(**arguments), HEAD)
                self.assertEqual(status, 2)
                self.assertIn(expected, line)

    def test_wrong_identity_mode_and_probe_errors_are_unavailable(self):
        cases = (
            (self.output(head="b" * 40), "OUTPUT_MODE_IDENTITY"),
            (self.output(mode="AB"), "OUTPUT_MODE_IDENTITY"),
            ("RCA|status=STALE_DIAGNOSTIC|stage=STALE_CHECKOUT", "STALE_CHECKOUT"),
            ("RCA|stage=secret-token-fixture", "PROBE"),
            ("old\nprobe\noutput", "OUTPUT_CONTRACT"),
        )
        for output, stage in cases:
            with (
                self.subTest(stage=stage),
                self.assertRaisesRegex(verify.VerificationFailure, stage),
            ):
                verify.summarize(output, HEAD)

    def test_detail_identity_is_independently_checked(self):
        output = self.output()
        record = json.loads(self.detail.read_text())
        record["diag"] = "b" * 40
        self.detail.write_text(json.dumps(record))
        with self.assertRaisesRegex(verify.VerificationFailure, "DIAGNOSTIC_IDENTITY"):
            verify.summarize(output, HEAD)

    def test_stdin_execution_uses_one_auto3_and_preserves_callers_checkout(self):
        with tempfile.TemporaryDirectory(prefix="prep39083-offline-test-") as directory:
            root = Path(directory)
            remote, caller = root / "remote.git", root / "caller"

            def git(*arguments, cwd=root):
                return subprocess.run(  # noqa: S603 - offline fixture Git argv only.
                    ["git", *arguments],  # noqa: S607 - local Git, no external commands.
                    cwd=cwd,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            git("init", "--bare", "-q", str(remote))
            git("init", "-q", "-b", "dev", str(caller))
            git("config", "user.name", "Offline Test", cwd=caller)
            git("config", "user.email", "offline@example.invalid", cwd=caller)
            git("config", "commit.gpgsign", "false", cwd=caller)
            git("remote", "add", "origin", str(remote), cwd=caller)
            release = caller / "deploy/prep39083/release.json"
            release.parent.mkdir(parents=True)
            release.write_text(json.dumps({"product_sha": verify.PRODUCT}))
            probe = caller / verify.PROBE
            probe.parent.mkdir(parents=True)
            probe.write_text("""#!/usr/bin/env bash
# PREP39083_RCA_AB_IDENTITY_V2 '--auto-3'
exec python3 - "$@" <<'PY'
import json, os, subprocess, sys
from pathlib import Path
Path(os.environ['TEST_CALLS']).write_text(json.dumps(sys.argv[1:]))
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
run = os.environ['TEST_RUN']
evidence = (f'GENERAL_RCA_EVIDENCE|mode=AUTO3|diag={head}'
            f'|run1={run}|run2={run}|run3={run}|constraint=PASS|discovery_bind=SQL_NULL')
detail = Path(os.environ['TEST_DETAIL'])
detail.write_text(json.dumps(dict(diag=head, mode='AUTO3', evidence=evidence)))
print(f'RCA_AUTO|diag={head[:8]}|mode=AUTO3|detail={detail}')
sys.exit(int(os.environ.get('TEST_PROBE_EXIT', '0')))
PY
""")
            git("add", ".", cwd=caller)
            git("commit", "-qm", "offline fixture", cwd=caller)
            git("push", "-q", "origin", "HEAD:dev", "HEAD:prep39083-release", cwd=caller)
            head = git("rev-parse", "HEAD", cwd=caller)
            dirty = caller / "operator-notes.txt"
            dirty.write_text("Keep operator work.\n")
            calls = root / "calls.json"
            environment = dict(
                os.environ, TEST_CALLS=str(calls), TEST_DETAIL=str(self.detail), TEST_RUN=RUN
            )

            def invoke():
                # Identical stdin entry point to `git show ... | python3`.
                return subprocess.run(  # noqa: S603 - current interpreter, fixed stdin script.
                    [sys.executable],
                    cwd=caller,
                    input=SCRIPT.read_text(),
                    capture_output=True,
                    text=True,
                    env=environment,
                    check=False,
                )

            result = invoke()
            self.assertEqual(
                (result.returncode, result.stdout.strip(), result.stderr), (0, SUCCESS, "")
            )
            self.assertEqual(json.loads(calls.read_text()), ["--auto-3"])
            self.assertEqual(git("rev-parse", "HEAD", cwd=caller), head)
            self.assertEqual(dirty.read_text(), "Keep operator work.\n")
            self.assertEqual(
                git("worktree", "list", "--porcelain", cwd=caller).count("worktree "), 1
            )
            self.assertTrue(self.detail.exists())

            environment["TEST_PROBE_EXIT"] = "2"
            result = invoke()
            self.assertEqual(result.returncode, 2)
            self.assertIn("state=UNAVAILABLE|stage=PROBE_EXIT", result.stdout)
            del environment["TEST_PROBE_EXIT"]

            for stale in ("STALE_DIAGNOSTIC", "TARGET_PRODUCT_CHANGED"):
                calls.unlink()
                if stale == "STALE_DIAGNOSTIC":
                    probe.write_text("#!/usr/bin/env bash\nexit 99\n")
                else:
                    release.write_text(json.dumps({"product_sha": "b" * 40}))
                git("add", str(probe), str(release), cwd=caller)
                git("commit", "-qm", stale, cwd=caller)
                git("push", "-q", "origin", "HEAD:dev", "HEAD:prep39083-release", cwd=caller)
                result = invoke()
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"state=UNAVAILABLE|stage={stale}", result.stdout)
                self.assertFalse(calls.exists())
                # Permit both pre-call failure cases to use the same fixture.
                calls.touch()


if __name__ == "__main__":
    unittest.main()
