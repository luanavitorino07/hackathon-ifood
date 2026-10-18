import pytest

from backend.agents.ports import MemoryPort, RevisionConflict
from backend.api.session_memory import EphemeralSessionMemory


def test_temporary_memory_preserves_port_revision_and_session_isolation():
    memory = EphemeralSessionMemory()
    assert isinstance(memory, MemoryPort)
    patch = {"initial_context": {"preferences": ["pizza"]}}
    assert memory.save_patch("one", patch, expected_revision=0, author="api") == 1
    patch["initial_context"]["preferences"].clear()
    loaded = memory.load("one")
    assert loaded.state["initial_context"]["preferences"] == ["pizza"]
    loaded.state.clear()
    assert memory.load("one").state["initial_context"]["preferences"] == ["pizza"]
    assert memory.load("two").revision == 0
    with pytest.raises(RevisionConflict):
        memory.save_patch("one", {"unexpected": True}, expected_revision=0, author="agent")
    assert memory.load("one").revision == 1
    assert "unexpected" not in memory.load("one").state
