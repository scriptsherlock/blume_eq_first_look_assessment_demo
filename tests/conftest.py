"""Keep tests offline and away from the real memory store."""
import pytest


@pytest.fixture(autouse=True)
def _offline_memory(monkeypatch, tmp_path):
    from server import memory

    monkeypatch.setenv("EMBEDDER", "local")
    monkeypatch.setattr(memory, "STORE", tmp_path / "memory" / "store.jsonl")
