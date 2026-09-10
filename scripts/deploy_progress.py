"""Deployment stage reporting without publishing command output or environment values."""

from __future__ import annotations

from contextlib import contextmanager
import json
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
STAGE_LABELS = dict(zip(DEPLOY_STAGES, (
    "소스·이미지 확인", "환경·배포 대상 확인", "외부 서비스 연결 확인", "Compose 확인",
    "상태 서비스 준비", "초기 구성·기존 상태 확인", "Web 기동", "K9·MCL 준비 확인",
    "Smoke 검증", "검색·대화·그래프 기능 검증", "최종 확인",
)))
SMOKE_LABELS = {
    "1/6": "서버·이미지 상태",
    "2/6": "관리자 로그인",
    "3/6": "DataHub 조회·용어집",
    "4/6": "관리형 그래프·의미 검색 인덱스",
    "5/6": "MCL 최신 수집·이력",
    "6/6": "AUTO 일반 대화·응답 경로",
}
SMOKE_PASS_MESSAGES = {
    "1/6": "Host and Product health PASS",
    "2/6": "Administrator login PASS",
    "3/6": "DataHub bounded read and read-only GlossaryTerm smoke PASS",
    "4/6": "Managed graphs and semantic index PASS",
    "6/6": "GENERAL provider and route PASS",
}
MCL_HISTORY_MESSAGES = {
    "MCL current capture READY; history EXACT": "EXACT",
    "MCL current capture READY; history DEGRADED_GAP (RETENTION_EXPIRED)": "DEGRADED_GAP",
}


def safe_code(value: object) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", value) else "UNKNOWN"


class DeployProgress:
    def __init__(self, path: Path, project: str, *, heartbeat_seconds: float = 15):
        self.path = path
        self.project = project
        self.heartbeat_seconds = heartbeat_seconds
        self.started = time.monotonic()
        self.stage_started = self.started
        self.current_stage = "DEPLOY"
        self.current_step = 0
        self.last_console_at = self.started
        self.smoke_status: dict[str, str] = {}
        self.smoke_announced: set[str] = set()
        self.failure_code: str | None = None
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

    def emit(self, status: str, *, step: str | None = None, step_status: str | None = None,
             history: str | None = None):
        with self.lock:
            now = time.monotonic()
            line = (f"DEPLOY_PROGRESS|project={self.project}|stage={self.current_stage}"
                    f"|status={status}|step={self.current_step}/{len(DEPLOY_STAGES)}"
                    f"|elapsed_seconds={int(now-self.started)}"
                    f"|stage_seconds={int(now-self.stage_started)}")
            if step is not None:
                line += f"|smoke_step={step}|step_status={step_status}"
            if history is not None:
                line += f"|mcl_history={history}"
                if history == "DEGRADED_GAP":
                    line += "|mcl_history_reason=RETENTION_EXPIRED"
            self.log.write(line + "\n")
            self.log.flush()
            elapsed = int(now - self.stage_started)
            prefix = f"[{self.current_step}/{len(DEPLOY_STAGES)}]"
            if step is not None:
                label = "" if step in self.smoke_announced else f" {SMOKE_LABELS[step]}"
                self.smoke_announced.add(step)
                result = " 확인 중" if step_status == "RUNNING" else f" {step_status}"
                note = " · 이력 공백(RETENTION_EXPIRED)" if history == "DEGRADED_GAP" else ""
                visible = f"  [{step}]{label}{result}{note}"
            elif status == "RUNNING":
                # Retain detailed private heartbeats, but print only after a
                # full minute without a new stage or smoke result.
                if now - self.last_console_at < 60:
                    return
                visible = f"{prefix} 실행/대기 중 ({elapsed}초)"
            elif self.current_stage == "DEPLOY":
                if status == "STARTED":
                    return
                visible = f"DEPLOY {status} ({elapsed}초)"
            elif status == "STARTED":
                visible = f"{prefix} {STAGE_LABELS.get(self.current_stage, self.current_stage)}"
            else:
                visible = f"{prefix} {status} ({elapsed}초)"
            print(visible, flush=True)
            self.last_console_at = now

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
            self.failure_code = None
            if name == "SMOKE":
                self.smoke_status.clear()
                self.smoke_announced.clear()
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
        # Only fixed labels and recognized outcomes cross the stdout boundary.
        # The raw report, URLs, names, cookies and error details stay captured.
        match = re.match(r"^\[SMOKE ([1-6]/6)(?: [^\]\r\n]+)?\] (.*)", line)
        if match:
            step, message = match[1], match[2].rstrip()
            history = MCL_HISTORY_MESSAGES.get(message) if step == "5/6" else None
            status = "PASS" if message == SMOKE_PASS_MESSAGES.get(step) or history else "RUNNING"
            if re.fullmatch(r"[A-Z][A-Z0-9_]*FAILED(?:; continuing read-only diagnostics)?", message):
                status = "FAILED"
            with self.lock:
                if self.smoke_status.get(step) == status:
                    return
                self.smoke_status[step] = status
                self.emit("RUNNING", step=step, step_status=status, history=history)

    def smoke_failure(self, stderr: str):
        # Read only the current child process's canonical failure record, never
        # a possibly stale receipt from a previous deployment.
        for line in reversed(stderr.splitlines()):
            if not line.startswith("{") or len(line) > 65536:
                continue
            try:
                failure = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(failure, dict):
                continue
            contract = failure.get("contract")
            if contract == "DATARIVER_PREP39083_SMOKE_FAILURE_V2":
                prefix = "SMOKE_FAILED"
                stage = safe_code(failure.get("stage"))
                code = safe_code(failure.get("classification"))
                status_class = failure.get("status_class")
                http = status_class if status_class in ("1xx", "2xx", "3xx", "4xx", "5xx") else "UNKNOWN"
                extra = ""
            elif contract == "DATARIVER_DEV_DEPLOY_ACCEPTANCE_FAILURE_V1":
                expected = {"K9_MCL_READINESS": "readiness", "FEATURES": "features"}.get(self.current_stage)
                if expected is None or failure.get("phase") != expected or failure.get("status") != "FAILED":
                    continue
                prefix = "READINESS_FAILED" if expected == "readiness" else "FEATURES_FAILED"
                stage = safe_code(failure.get("stage"))
                code = safe_code(failure.get("code"))
                status = failure.get("http_status")
                http = str(status) if type(status) is int and 100 <= status <= 599 else "NONE"
                diagnostic = failure.get("diagnostic")
                diagnostic = diagnostic if isinstance(diagnostic, dict) else {}
                extra = ""
                fields = {"provider_code": failure.get("provider_code"),
                          "cause_stage": diagnostic.get("stage"), "cause_code": diagnostic.get("code"),
                          "detail": diagnostic.get("detail"), "state": diagnostic.get("state")}
                for key, value in fields.items():
                    bounded = safe_code(value)
                    if bounded != "UNKNOWN":
                        extra += f"|{key}={bounded}"
            else:
                continue
            with self.lock:
                self.failure_code = f"{prefix}:{stage}:{code}"
                summary = f"{prefix}|stage={stage}|code={code}|http={http}{extra}"
                self.log.write(summary + "\n")
                self.log.flush()
                print(summary, flush=True)
                self.last_console_at = time.monotonic()
            return

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
        captured_error = "".join(stderr)
        if exit_code:
            progress.smoke_failure(captured_error)
        return subprocess.CompletedProcess(list(arguments), exit_code, "".join(stdout), captured_error)
