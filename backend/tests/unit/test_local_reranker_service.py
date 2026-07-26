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
