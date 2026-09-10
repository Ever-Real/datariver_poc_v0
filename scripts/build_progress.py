"""Stream a single owned build process; retain a private diagnostic log."""

from __future__ import annotations

import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Mapping, Sequence


def run_build(arguments: Sequence[str], *, cwd: Path, archive: BinaryIO,
              log_path: Path, heartbeat_seconds: float = 15.0,
              environment: Mapping[str, str] | None = None) -> int:
    started = last_output = time.monotonic()
    next_heartbeat = started + heartbeat_seconds
    log_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as log:
        def emit(line: str) -> None:
            # npm errors can include authenticated URLs. Never echo userinfo.
            line = re.sub(r"(https?://)[^\s/@]+(?::[^\s/@]*)?@", r"\1[REDACTED]@", line)
            log.write(line)
            log.flush()
            sys.stdout.write(line)
            sys.stdout.flush()

        emit(f"BUILD_PROGRESS|status=STARTED|log={log_path}\n")
        process = subprocess.Popen(list(arguments), cwd=cwd, stdin=archive,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   env=None if environment is None else dict(environment))
        lines: queue.Queue[bytes | None] = queue.Queue()
        def read_output() -> None:
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            while True:
                try:
                    line = lines.get(timeout=max(0.01, next_heartbeat - time.monotonic()))
                except queue.Empty:
                    line = b""
                if line is None:
                    break
                if line:
                    emit(line.decode("utf-8", errors="replace"))
                    last_output = time.monotonic()
                now = time.monotonic()
                if now >= next_heartbeat:
                    emit(f"BUILD_PROGRESS|status=RUNNING|elapsed_seconds={int(now-started)}"
                         f"|output_idle_seconds={int(now-last_output)}\n")
                    next_heartbeat = now + heartbeat_seconds
            exit_code = process.wait()
            emit(f"BUILD_PROGRESS|status={'PASS' if exit_code == 0 else 'FAILED'}"
                 f"|exit={exit_code}|elapsed_seconds={int(time.monotonic()-started)}|log={log_path}\n")
            return exit_code
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            reader.join(timeout=1)
            if process.stdout is not None:
                process.stdout.close()
