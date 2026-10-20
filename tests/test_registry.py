import pytest

from qukaizen_harness import RegistryError, ToolRegistry, ToolSpec

PARAMS = {"type": "object", "properties": {"world": {"type": "string"}}, "required": ["world"]}


def test_declare_and_get_latest() -> None:
    reg = ToolRegistry()
    reg.declare(ToolSpec("deck", "1.0", "deal a deck", PARAMS, lambda world: world))
    reg.declare(ToolSpec("deck", "1.2", "deal a deck", PARAMS, lambda world: world))
    reg.declare(ToolSpec("deck", "1.10", "deal a deck", PARAMS, lambda world: world))
    assert reg.get("deck").version == "1.10"  # numeric, not lexical
    assert reg.get("deck", "1.0").version == "1.0"
    assert len(reg) == 3


def test_redeclaring_a_version_is_refused() -> None:
    reg = ToolRegistry()
    reg.declare(ToolSpec("deck", "1.0", "x", PARAMS, lambda world: world))
    with pytest.raises(RegistryError):
        reg.declare(ToolSpec("deck", "1.0", "x", PARAMS, lambda world: world))


def test_unknown_tool_does_not_exist() -> None:
    reg = ToolRegistry()
    with pytest.raises(RegistryError):
        reg.get("docent")
    assert "docent" not in reg


def test_visibility_by_resident() -> None:
    reg = ToolRegistry()

    @reg.tool("deck", "1.0", "deal", PARAMS, allowed={"team-crew"})
    def deck(world: str) -> str:
        return world

    @reg.tool("eval", "1.0", "measure", PARAMS)
    def ev(world: str) -> str:
        return world

    assert [s.name for s in reg.visible_to("team-crew")] == ["deck", "eval"]
    assert [s.name for s in reg.visible_to("buddy")] == ["eval"]


def test_manifest_hash_moves_with_declarations() -> None:
    reg = ToolRegistry()
    h0 = reg.manifest_hash()
    reg.declare(ToolSpec("deck", "1.0", "x", PARAMS, lambda world: world))
    h1 = reg.manifest_hash()
    assert h0 != h1
    spec = reg.get("deck")
    assert spec.schema_hash() == ToolSpec("deck", "1.0", "other desc", PARAMS, print).schema_hash()
