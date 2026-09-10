"""Deployment stage reporting without publishing command output or environment values."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Mapping, Sequence


DEPLOY_STAGES = (
    "SOURCE_IMAGE", "ENV_TARGET", "PROVIDER_PREFLIGHT", "COMPOSE_CONFIG",
    "STATE_SERVICES", "BOOTSTRAP", "WEB_START", "K9_MCL_READINESS",
    "SMOKE", "FEATURES", "FINAL_VERIFY",
)


class DeployProgress:
    def __init__(self, path: Path, project: str, *, heartbeat_seconds: float = 15):
        self.path = path
        self.project = project
        self.heartbeat_seconds = heartbeat_seconds
        self.started = time.monotonic()
        self.stage_started = self.started
        self.current_stage = "DEPLOY"
        self.current_step = 0
        self.lock = threading.RLock()
        self.stopped = threading.Event()

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.log = os.fdopen(descriptor, "w", encoding="utf-8")
        self.emit("STARTED")
        print(f"DEPLOY_LOG|path={self.path}", flush=True)
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.thread.start()
        return self

    def emit(self, status: str, *, step: str | None = None, step_status: str | None = None):
        with self.lock:
            now = time.monotonic()
            line = (f"DEPLOY_PROGRESS|project={self.project}|stage={self.current_stage}"
                    f"|status={status}|step={self.current_step}/{len(DEPLOY_STAGES)}"
                    f"|elapsed_seconds={int(now-self.started)}"
                    f"|stage_seconds={int(now-self.stage_started)}")
            if step is not None:
                line += f"|smoke_step={step}|step_status={step_status}"
            self.log.write(line + "\n")
            self.log.flush()
            print(line, flush=True)

    def heartbeat(self):
        while not self.stopped.wait(self.heartbeat_seconds):
            with self.lock:
                if self.current_stage != "DEPLOY":
                    self.emit("RUNNING")

    @contextmanager
    def stage(self, name: str):
        with self.lock:
            self.current_stage = name
            self.current_step = DEPLOY_STAGES.index(name) + 1 if name in DEPLOY_STAGES else "?"
            self.stage_started = time.monotonic()
            self.emit("STARTED")
        try:
            yield
        except KeyboardInterrupt:
            with self.lock:
                self.emit("INTERRUPTED")
                self.current_stage = "DEPLOY"
            raise
        except BaseException:
            # Exception text can contain command arguments or provider responses.
            with self.lock:
                self.emit("FAILED")
                self.current_stage = "DEPLOY"
            raise
        else:
            with self.lock:
                self.emit("PASS")
                self.current_stage = "DEPLOY"

    def smoke_line(self, line: str):
        # Only a canonical step number and status cross the stdout boundary.
        # The raw report, URLs, names, cookies and error details stay captured.
        match = re.match(r"^\[SMOKE ([1-6]/6)\] ", line)
        if match:
            self.emit("RUNNING", step=match[1],
                      step_status="PASS" if line.rstrip().endswith(" PASS") else "RUNNING")

    def __exit__(self, error_type, error, traceback):
        self.stopped.set()
        self.thread.join()
        try:
            with self.lock:
                self.current_stage = "DEPLOY"
                self.stage_started = self.started
                self.emit("PASS" if error_type is None else
                          "INTERRUPTED" if issubclass(error_type, KeyboardInterrupt) else "FAILED")
        finally:
            self.log.close()


def capture_smoke(arguments: Sequence[str], *, cwd: Path,
                  environment: Mapping[str, str] | None,
                  progress: DeployProgress) -> subprocess.CompletedProcess[str]:
    """Preserve separate captured streams while forwarding only safe smoke markers."""
    with subprocess.Popen(list(arguments), cwd=cwd, env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace") as process:
        stdout: list[str] = []
        stderr: list[str] = []

        def drain(stream, result, observe=False):
            for line in stream:
                result.append(line)
                if observe:
                    progress.smoke_line(line)

        readers = [threading.Thread(target=drain, args=(process.stdout, stdout, True), daemon=True),
                   threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True)]
        for reader in readers:
            reader.start()
        try:
            exit_code = process.wait()
        except BaseException:
            # Stop only the CLI process we started. Never remove Docker state.
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        finally:
            for reader in readers:
                reader.join()
        return subprocess.CompletedProcess(list(arguments), exit_code, "".join(stdout), "".join(stderr))
