from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "local_reranker_service.py"


def _load_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "local_reranker_service",
        MODULE_PATH,
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_modelfile_resolution_accepts_only_one_ollama_sha256_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    model_root = tmp_path / "models" / "blobs"
    model_root.mkdir(parents=True)
    blob = model_root / ("sha256-" + "a" * 64)
    blob.write_bytes(b"gguf")
    monkeypatch.setattr(module, "_model_store_roots", lambda: (model_root.resolve(),))

    resolved = module._model_blob_from_modelfile(f"FROM {blob}\nTEMPLATE {{{{ .Prompt }}}}\n")

    assert resolved == blob.resolve()


@pytest.mark.parametrize(
    "source",
    (
        "FROM relative/model\n",
        "FROM /tmp/not-a-sha256-model\n",
        "FROM /tmp/one\nFROM /tmp/two\n",
    ),
)
def test_modelfile_resolution_rejects_unbounded_sources(
    source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_model_store_roots", lambda: (tmp_path.resolve(),))

    with pytest.raises(module.ServiceError):
        module._model_blob_from_modelfile(source)


def test_stop_clears_stale_managed_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    pid_file = tmp_path / "llama-server.pid"
    state_file = tmp_path / "llama-server.json"
    pid_file.write_text("4242\n", encoding="utf-8")
    state_file.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(module, "PID_FILE", pid_file)
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "_process_command", lambda _pid: "")

    assert module._stop_owned_process() is False
    assert not pid_file.exists()
    assert not state_file.exists()


def test_managed_state_model_is_validated_without_a_source_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    model_root = tmp_path / "models" / "blobs"
    model_root.mkdir(parents=True)
    blob = model_root / ("sha256-" + "a" * 64)
    blob.write_bytes(b"gguf")
    state_file = tmp_path / "llama-server.json"
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "_model_store_roots", lambda: (model_root.resolve(),))
    state_file.write_text(
        (f'{{"model":"operator-selected/model:q4","model_blob":"{blob}","port":11435}}\n'),
        encoding="utf-8",
    )

    assert module._read_managed_model() == "operator-selected/model:q4"

    state_file.write_text(
        f'{{"model":"invalid model","model_blob":"{blob}","port":11435}}\n',
        encoding="utf-8",
    )
    assert module._read_managed_model() is None

    with pytest.raises(module.ServiceError, match="exact installed reranker model"):
        module._required_model(None)


@pytest.mark.parametrize(
    "command",
    (
        (
            "/opt/homebrew/bin/llama-server --model {blob} --alias "
            "operator-selected/model:q4 --reranking --pooling rank "
            "--host 0.0.0.0 --port 11435 --no-webui"
        ),
        (
            "/opt/homebrew/bin/llama-server --model {blob} --alias "
            "operator-selected/model:q4 --pooling rank "
            "--host 127.0.0.1 --port 11435 --no-webui"
        ),
        (
            "/opt/homebrew/bin/llama-server --model /tmp/other-blob --alias "
            "operator-selected/model:q4 --reranking --pooling rank "
            "--host 127.0.0.1 --port 11435 --no-webui"
        ),
    ),
)
def test_stop_refuses_process_that_does_not_match_full_owned_state(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    model_root = tmp_path / "models" / "blobs"
    model_root.mkdir(parents=True)
    blob = model_root / ("sha256-" + "b" * 64)
    blob.write_bytes(b"gguf")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_file = runtime / "llama-server.pid"
    pid_file.write_text("4242\n", encoding="utf-8")
    state_file = runtime / "llama-server.json"
    state_file.write_text(
        (f'{{"model":"operator-selected/model:q4","model_blob":"{blob}","port":11435}}\n'),
        encoding="utf-8",
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(module, "PID_FILE", pid_file)
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "_model_store_roots", lambda: (model_root.resolve(),))
    monkeypatch.setattr(module, "_process_command", lambda _pid: command.format(blob=blob))
    monkeypatch.setattr(
        module.os,
        "kill",
        lambda pid, signal: signals.append((pid, signal)),
    )

    with pytest.raises(module.ServiceError, match="not the managed"):
        module._stop_owned_process()

    assert signals == []
    assert pid_file.exists()
    assert state_file.exists()


def test_resolve_ubatch_reads_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    monkeypatch.setenv("LLAMA_ARG_UBATCH", "1024")
    assert module._resolve_ubatch() == 1024

    monkeypatch.setenv("LLAMA_ARG_UBATCH", "512")
    assert module._resolve_ubatch() == 512

    monkeypatch.delenv("LLAMA_ARG_UBATCH", raising=False)
    # When absent the llama.cpp compiled default (512) is returned for legacy safety.
    assert module._resolve_ubatch() == 512


def test_resolve_ubatch_rejects_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    monkeypatch.setenv("LLAMA_ARG_UBATCH", "0")
    with pytest.raises(module.ServiceError, match="LLAMA_ARG_UBATCH"):
        module._resolve_ubatch()

    monkeypatch.setenv("LLAMA_ARG_UBATCH", "9999")
    with pytest.raises(module.ServiceError, match="LLAMA_ARG_UBATCH"):
        module._resolve_ubatch()

    monkeypatch.setenv("LLAMA_ARG_UBATCH", "not-a-number")
    with pytest.raises(module.ServiceError, match="LLAMA_ARG_UBATCH"):
        module._resolve_ubatch()


def test_read_managed_state_preserves_legacy_state_without_ubatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy state has no explicit CLI ubatch and must remain distinguishable."""
    module = _load_module()
    model_root = tmp_path / "models" / "blobs"
    model_root.mkdir(parents=True)
    blob = model_root / ("sha256-" + "c" * 64)
    blob.write_bytes(b"gguf")
    state_file = tmp_path / "llama-server.json"
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "_model_store_roots", lambda: (model_root.resolve(),))

    # Write legacy state without ubatch key.
    state_file.write_text(
        f'{{"model":"op/model:q4","model_blob":"{blob}","port":11435}}\n',
        encoding="utf-8",
    )

    result = module._read_managed_state()
    assert result is not None
    managed_model, _blob, ubatch = result
    assert managed_model == "op/model:q4"
    assert ubatch is None


def test_read_managed_state_returns_ubatch_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    model_root = tmp_path / "models" / "blobs"
    model_root.mkdir(parents=True)
    blob = model_root / ("sha256-" + "d" * 64)
    blob.write_bytes(b"gguf")
    state_file = tmp_path / "llama-server.json"
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "_model_store_roots", lambda: (model_root.resolve(),))

    state_file.write_text(
        f'{{"model":"op/model:q4","model_blob":"{blob}","port":11435,"ubatch":1024}}\n',
        encoding="utf-8",
    )

    result = module._read_managed_state()
    assert result is not None
    _, _blob, ubatch = result
    assert ubatch == 1024


def test_owned_process_accepts_legacy_command_only_for_legacy_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-contract process can be stopped once, not accepted as configured."""
    module = _load_module()
    model_root = tmp_path / "models" / "blobs"
    model_root.mkdir(parents=True)
    blob = model_root / ("sha256-" + "e" * 64)
    blob.write_bytes(b"gguf")
    monkeypatch.setattr(module, "_model_store_roots", lambda: (model_root.resolve(),))

    command_without_ubatch = (
        f"/opt/homebrew/bin/llama-server --model {blob} --alias op/model:q4 "
        "--reranking --pooling rank --host 127.0.0.1 --port 11435 --no-webui"
    )
    monkeypatch.setattr(module, "_process_command", lambda _pid: command_without_ubatch)

    assert module._owned_process(
        4242, model="op/model:q4", model_blob=blob.resolve(), ubatch=None
    )
    assert not module._owned_process(
        4242, model="op/model:q4", model_blob=blob.resolve(), ubatch=1024
    )


def test_owned_process_accepts_command_with_matching_ubatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    model_root = tmp_path / "models" / "blobs"
    model_root.mkdir(parents=True)
    blob = model_root / ("sha256-" + "f" * 64)
    blob.write_bytes(b"gguf")
    monkeypatch.setattr(module, "_model_store_roots", lambda: (model_root.resolve(),))

    command_with_ubatch = (
        f"/opt/homebrew/bin/llama-server --model {blob} --alias op/model:q4 "
        "--reranking --pooling rank --host 127.0.0.1 --port 11435 "
        "--ubatch-size 1024 --no-webui"
    )
    monkeypatch.setattr(module, "_process_command", lambda _pid: command_with_ubatch)

    assert module._owned_process(
        4242, model="op/model:q4", model_blob=blob.resolve(), ubatch=1024
    )


def test_stop_accepts_the_exact_legacy_owned_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    model_root = tmp_path / "models" / "blobs"
    model_root.mkdir(parents=True)
    blob = model_root / ("sha256-" + "1" * 64)
    blob.write_bytes(b"gguf")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pid_file = runtime / "llama-server.pid"
    pid_file.write_text("4242\n", encoding="utf-8")
    state_file = runtime / "llama-server.json"
    state_file.write_text(
        f'{{"model":"op/model:q4","model_blob":"{blob}","port":11435}}\n',
        encoding="utf-8",
    )
    command = (
        f"/opt/homebrew/bin/llama-server --model {blob} --alias op/model:q4 "
        "--reranking --pooling rank --host 127.0.0.1 --port 11435 --no-webui"
    )
    running = True
    signals: list[tuple[int, int]] = []

    def process_command(_pid: int) -> str:
        return command if running else ""

    def kill(pid: int, selected_signal: int) -> None:
        nonlocal running
        signals.append((pid, selected_signal))
        running = False

    monkeypatch.setattr(module, "PID_FILE", pid_file)
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "_model_store_roots", lambda: (model_root.resolve(),))
    monkeypatch.setattr(module, "_process_command", process_command)
    monkeypatch.setattr(module.os, "kill", kill)

    assert module._stop_owned_process() is True
    assert signals == [(4242, module.signal.SIGTERM)]
    assert not pid_file.exists()
    assert not state_file.exists()
