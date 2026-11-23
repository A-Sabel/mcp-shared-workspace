import json

import pytest

from server.sandbox import Sandbox
from server.workspaces import WorkspaceRegistry


def make_registry(tmp_path):
    active = tmp_path / "active"
    other = tmp_path / "other"
    active.mkdir()
    other.mkdir()
    registry = WorkspaceRegistry(tmp_path / "workspaces.json", Sandbox(active))
    registry.register("Other", str(other))
    return registry, active, other


def test_delete_unregisters_without_deleting_directory_or_files(tmp_path):
    registry, _active, other = make_registry(tmp_path)
    marker = other / "keep.txt"
    marker.write_text("keep me", encoding="utf-8")

    result = registry.delete("Other")

    assert "not deleted" in result
    assert "Other" not in registry.entries
    assert marker.read_text(encoding="utf-8") == "keep me"
    assert json.loads(registry.path.read_text(encoding="utf-8")) == {"default": str(registry.sandbox.root)}


def test_delete_protects_default_workspace(tmp_path):
    registry, _active, _other = make_registry(tmp_path)

    with pytest.raises(ValueError, match="default or currently active"):
        registry.delete("default")


def test_delete_protects_currently_active_workspace_alias(tmp_path):
    registry, active, _other = make_registry(tmp_path)
    registry.register("Active Alias", str(active))

    with pytest.raises(ValueError, match="default or currently active"):
        registry.delete("Active Alias")


def test_delete_unknown_workspace_fails(tmp_path):
    registry, _active, _other = make_registry(tmp_path)

    with pytest.raises(ValueError, match="not registered"):
        registry.delete("Missing")


def test_deleted_workspace_can_be_registered_again(tmp_path):
    registry, _active, other = make_registry(tmp_path)

    registry.delete("Other")
    result = registry.register("Other", str(other))

    assert result == "Registered workspace 'Other'."
    assert registry.entries["Other"] == other.resolve()
