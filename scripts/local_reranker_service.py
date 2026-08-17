#!/usr/bin/env python3
"""Manage the Mac development llama.cpp reranker over one fixed loopback port."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRECTORY = ROOT / "runtime" / "local-reranker"
PID_FILE = RUNTIME_DIRECTORY / "llama-server.pid"
STATE_FILE = RUNTIME_DIRECTORY / "llama-server.json"
STDOUT_FILE = RUNTIME_DIRECTORY / "llama-server.out.log"
STDERR_FILE = RUNTIME_DIRECTORY / "llama-server.err.log"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 11435
MODEL_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
MODEL_BLOB = re.compile(r"sha256-[0-9a-f]{64}")
# Bounded ubatch range accepted by this manager. The installed llama-server exposes
# --ubatch-size and the matching LLAMA_ARG_UBATCH environment variable.
# 1024 is the confirmed stable DEV value; 512 is the llama.cpp default.
UBATCH_MIN = 64
UBATCH_MAX = 4096


class ServiceError(RuntimeError):
    """Raised when the bounded local service cannot be managed safely."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Start, stop, probe or inspect the development-only llama.cpp reranker. "
            "The GGUF remains owned by the local Ollama model store."
        )
    )
    parser.add_argument("action", choices=("start", "stop", "status", "probe"))
    parser.add_argument(
        "--model",
        default=os.environ.get("LOCAL_LLAMA_CPP_RERANKER_MODEL"),
        help="Exact installed Ollama model identity; required for start and probe.",
    )
    return parser.parse_args()


def _required_model(value: object) -> str:
    if not isinstance(value, str) or MODEL_IDENTITY.fullmatch(value) is None:
        raise ServiceError(
            "An exact installed reranker model must be selected with --model or "
            "LOCAL_LLAMA_CPP_RERANKER_MODEL."
        )
    return value


def _resolve_ubatch() -> int:
    """Read LLAMA_ARG_UBATCH from the environment, validate, and return as int.

    run_poc.sh injects this from the selected env file to prevent shell-env drift.
    When absent (legacy or direct invocation), the llama.cpp default of 512 is used
    so that existing processes are not invalidated on first probe-only calls.
    """
    raw = os.environ.get("LLAMA_ARG_UBATCH", "").strip()
    if not raw:
        return 512  # llama.cpp compiled default; safe for legacy state transition
    try:
        value = int(raw)
    except ValueError as error:
        raise ServiceError(
            f"LLAMA_ARG_UBATCH must be an integer between {UBATCH_MIN} and {UBATCH_MAX}."
        ) from error
    if not UBATCH_MIN <= value <= UBATCH_MAX:
        raise ServiceError(
            f"LLAMA_ARG_UBATCH={value} is out of the supported range "
            f"[{UBATCH_MIN}, {UBATCH_MAX}]."
        )
    return value


def _model_store_roots() -> tuple[Path, ...]:
    roots = [Path.home() / ".ollama" / "models" / "blobs"]
    configured = os.environ.get("OLLAMA_MODELS")
    if configured:
        roots.insert(0, Path(configured).expanduser() / "blobs")
    return tuple(root.resolve() for root in roots)


def _model_blob_from_modelfile(document: str) -> Path:
    source_lines = [
        line.removeprefix("FROM ").strip()
        for line in document.splitlines()
        if line.startswith("FROM ")
    ]
    if len(source_lines) != 1:
        raise ServiceError("Ollama returned an ambiguous model source.")
    source = Path(source_lines[0])
    if not source.is_absolute() or source.is_symlink():
        raise ServiceError("The Ollama model source must be one non-symlink absolute file.")
    resolved = source.resolve()
    if not resolved.is_file() or not MODEL_BLOB.fullmatch(resolved.name):
        raise ServiceError("The Ollama model source is not a regular SHA-256 GGUF blob.")
    if not any(resolved.is_relative_to(root) for root in _model_store_roots()):
        raise ServiceError("The Ollama model source is outside the configured model store.")
    return resolved


def _resolve_model_blob(model: str) -> Path:
    if MODEL_IDENTITY.fullmatch(model) is None:
        raise ServiceError("The reranker model identity is invalid.")
    ollama = shutil.which("ollama")
    if ollama is None:
        raise ServiceError("ollama is required to resolve the governed GGUF model.")
    try:
        result = subprocess.run(  # noqa: S603 - resolved executable and validated model identity.
            (ollama, "show", "--modelfile", model),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ServiceError(f"Ollama could not resolve model {model}.") from error
    return _model_blob_from_modelfile(result.stdout)


def _read_pid() -> int | None:
    if not PID_FILE.is_file() or PID_FILE.is_symlink():
        return None
    try:
        value = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if value > 1 else None


def _read_managed_state() -> tuple[str, Path, int | None] | None:
    if not STATE_FILE.is_file() or STATE_FILE.is_symlink():
        return None
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8")[:8_192])
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("port") != LISTEN_PORT:
        return None
    model = payload.get("model")
    raw_model_blob = payload.get("model_blob")
    if (
        not isinstance(model, str)
        or MODEL_IDENTITY.fullmatch(model) is None
        or not isinstance(raw_model_blob, str)
    ):
        return None
    model_blob = Path(raw_model_blob)
    if not model_blob.is_absolute() or model_blob.is_symlink():
        return None
    resolved = model_blob.resolve()
    if (
        not resolved.is_file()
        or MODEL_BLOB.fullmatch(resolved.name) is None
        or not any(resolved.is_relative_to(root) for root in _model_store_roots())
    ):
        return None
    # Legacy state files written before ubatch support have no "ubatch" key and
    # launched llama-server without an explicit CLI option. Preserve that distinction
    # so the old process can be ownership-checked and stopped once before replacement.
    raw_ubatch = payload.get("ubatch")
    if raw_ubatch is None:
        return model, resolved, None
    if not isinstance(raw_ubatch, int) or isinstance(raw_ubatch, bool):
        return None
    if not UBATCH_MIN <= raw_ubatch <= UBATCH_MAX:
        return None
    return model, resolved, raw_ubatch


def _read_managed_model() -> str | None:
    state = _read_managed_state()
    return state[0] if state is not None else None


def _process_command(pid: int) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed ps executable and numeric PID.
            ("ps", "-p", str(pid), "-o", "command="),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _owned_process(
    pid: int,
    *,
    model: str,
    model_blob: Path,
    ubatch: int | None,
) -> bool:
    command = _process_command(pid)
    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if not arguments or Path(arguments[0]).name != "llama-server":
        return False
    expected_pairs = {
        "--model": os.fspath(model_blob),
        "--alias": model,
        "--pooling": "rank",
        "--host": LISTEN_HOST,
        "--port": str(LISTEN_PORT),
    }
    for option, expected in expected_pairs.items():
        indexes = [index for index, value in enumerate(arguments) if value == option]
        if len(indexes) != 1:
            return False
        index = indexes[0]
        if index + 1 >= len(arguments) or arguments[index + 1] != expected:
            return False
    ubatch_indexes = [
        index for index, value in enumerate(arguments) if value == "--ubatch-size"
    ]
    if ubatch is None:
        if ubatch_indexes or "-ub" in arguments:
            return False
    elif (
        len(ubatch_indexes) != 1
        or ubatch_indexes[0] + 1 >= len(arguments)
        or arguments[ubatch_indexes[0] + 1] != str(ubatch)
        or "-ub" in arguments
    ):
        return False
    return arguments.count("--reranking") == 1 and arguments.count("--no-webui") == 1


def _probe(model: str) -> dict[str, object]:
    request = urllib.request.Request(
        f"http://{LISTEN_HOST}:{LISTEN_PORT}/v1/rerank",
        data=json.dumps(
            {
                "model": model,
                "query": "governed data catalog metadata",
                "documents": [
                    "Data catalog metadata and governed lineage",
                    "Unrelated weather forecast",
                ],
                "top_n": 2,
            },
            separators=(",", ":"),
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            payload = json.loads(response.read(131_072))
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise ServiceError("The local reranker probe did not return valid JSON.") from error
    if not isinstance(payload, dict) or payload.get("model") != model:
        raise ServiceError("The local reranker returned a different model identity.")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 2:
        raise ServiceError("The local reranker returned an invalid result count.")
    indexes: list[int] = []
    scores: list[float] = []
    for item in results:
        if not isinstance(item, dict):
            raise ServiceError("The local reranker returned an invalid result.")
        index = item.get("index")
        score = item.get("relevance_score")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < 2
            or not isinstance(score, int | float)
            or isinstance(score, bool)
            or not math.isfinite(float(score))
        ):
            raise ServiceError("The local reranker returned invalid index or score data.")
        indexes.append(index)
        scores.append(float(score))
    if len(set(indexes)) != len(indexes) or scores != sorted(scores, reverse=True):
        raise ServiceError("The local reranker results are not uniquely ordered by score.")
    return {
        "model": model,
        "endpoint": f"http://{LISTEN_HOST}:{LISTEN_PORT}/v1",
        "scores": scores,
    }


def _prepare_runtime_directory() -> None:
    if RUNTIME_DIRECTORY.is_symlink():
        raise ServiceError("The local reranker runtime directory cannot be a symbolic link.")
    RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME_DIRECTORY.chmod(0o700)
    for managed_file in (PID_FILE, STATE_FILE, STDOUT_FILE, STDERR_FILE):
        if managed_file.is_symlink():
            raise ServiceError("A local reranker managed file cannot be a symbolic link.")


def _write_managed_state(*, model: str, model_blob: Path, ubatch: int) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {
                "host": LISTEN_HOST,
                "model": model,
                "model_blob": os.fspath(model_blob),
                "port": LISTEN_PORT,
                "reranking": True,
                "ubatch": ubatch,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    STATE_FILE.chmod(0o600)


def _stop_owned_process() -> bool:
    pid = _read_pid()
    if pid is None:
        return False
    if not _process_command(pid):
        PID_FILE.unlink(missing_ok=True)
        STATE_FILE.unlink(missing_ok=True)
        return False
    state = _read_managed_state()
    if state is None:
        raise ServiceError("The recorded local reranker state is invalid.")
    model, model_blob, ubatch = state
    if not _owned_process(pid, model=model, model_blob=model_blob, ubatch=ubatch):
        raise ServiceError("The recorded PID is not the managed llama-server process.")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        STATE_FILE.unlink(missing_ok=True)
        return False
    for _attempt in range(20):
        if not _process_command(pid):
            break
        time.sleep(0.25)
    else:
        os.kill(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    STATE_FILE.unlink(missing_ok=True)
    return True


def _start(model: str) -> dict[str, object]:
    if sys.platform != "darwin":
        raise ServiceError("The local llama.cpp reranker service is supported only on macOS.")
    ubatch = _resolve_ubatch()
    _prepare_runtime_directory()
    model_blob = _resolve_model_blob(model)
    pid = _read_pid()
    if pid is not None:
        if not _owned_process(pid, model=model, model_blob=model_blob, ubatch=ubatch):
            _stop_owned_process()
        else:
            _write_managed_state(model=model, model_blob=model_blob, ubatch=ubatch)
            return _probe(model)
    llama_server = shutil.which("llama-server")
    if llama_server is None:
        raise ServiceError("llama-server is required for the fixed local rerank endpoint.")
    command = (
        llama_server,
        "--model",
        os.fspath(model_blob),
        "--alias",
        model,
        "--reranking",
        "--pooling",
        "rank",
        "--host",
        LISTEN_HOST,
        "--port",
        str(LISTEN_PORT),
        "--ubatch-size",
        str(ubatch),
        "--no-webui",
    )
    with STDOUT_FILE.open("ab") as stdout, STDERR_FILE.open("ab") as stderr:
        process = subprocess.Popen(  # noqa: S603 - fixed executable and validated model path.
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            start_new_session=True,
        )
    PID_FILE.write_text(f"{process.pid}\n", encoding="utf-8")
    PID_FILE.chmod(0o600)
    _write_managed_state(model=model, model_blob=model_blob, ubatch=ubatch)
    last_error: ServiceError | None = None
    for _attempt in range(120):
        if process.poll() is not None:
            break
        try:
            return _probe(model)
        except ServiceError as error:
            last_error = error
            time.sleep(0.5)
    if process.poll() is None:
        os.kill(process.pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    STATE_FILE.unlink(missing_ok=True)
    raise ServiceError(
        "The local reranker did not become ready; inspect runtime/local-reranker logs."
    ) from last_error


def main() -> int:
    arguments = _parse_args()
    try:
        if arguments.action == "start":
            model = _required_model(arguments.model)
            print(json.dumps(_start(model), ensure_ascii=False, sort_keys=True))
            return 0
        if arguments.action == "stop":
            _prepare_runtime_directory()
            stopped = _stop_owned_process()
            print("stopped" if stopped else "already stopped")
            return 0
        if arguments.action == "probe":
            model = _required_model(arguments.model)
            print(json.dumps(_probe(model), ensure_ascii=False, sort_keys=True))
            return 0
        pid = _read_pid()
        state = _read_managed_state()
        if pid is None and state is None:
            print("stopped")
            return 1
        if pid is None or state is None:
            raise ServiceError("The local reranker PID/state pair is incomplete.")
        managed_model, model_blob, ubatch = state
        if not _owned_process(pid, model=managed_model, model_blob=model_blob, ubatch=ubatch):
            raise ServiceError("The recorded PID is not the managed llama-server process.")
        model = _required_model(arguments.model or managed_model)
        if model != managed_model:
            raise ServiceError("The requested model does not match the managed reranker.")
        print(json.dumps(_probe(model), ensure_ascii=False, sort_keys=True))
        return 0
    except ServiceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
