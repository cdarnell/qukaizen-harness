import pytest

from qukaizen_harness import ContextAssembler, Mutation, Segment

from .fakes import FakeWorld


def test_e301_orders_static_first_volatile_last() -> None:
    world = FakeWorld("biology", ["Adaptation — Campbell Biology"])
    ctx = ContextAssembler().assemble(
        standing=[Segment("rules", "Describe, never prescribe.", Mutation.STATIC)],
        source=world,
        session=[Segment("mem", "Last wake dealt a deck.", Mutation.SESSION)],
        volatile=[Segment("wake", "Woke: change", Mutation.VOLATILE)],
    )
    assert [s.mutation for s in ctx.segments] == [
        Mutation.STATIC,
        Mutation.WORLD,
        Mutation.SESSION,
        Mutation.VOLATILE,
    ]
    assert ctx.text.startswith("Describe, never prescribe.")
    assert ctx.text.endswith("Woke: change")


def test_static_prefix_is_stable_across_volatile_changes() -> None:
    world = FakeWorld("biology", ["Adaptation"])
    asm = ContextAssembler()
    rules = [Segment("rules", "Rules.", Mutation.STATIC)]
    a = asm.assemble(
        standing=rules, source=world, volatile=[Segment("w", "wake 1", Mutation.VOLATILE)]
    )
    b = asm.assemble(
        standing=rules,
        source=world,
        volatile=[Segment("w", "wake 2 — different", Mutation.VOLATILE)],
    )
    assert a.static_prefix_hash == b.static_prefix_hash
    assert a.full_hash != b.full_hash
    assert a.text[: a.static_prefix_chars] == b.text[: b.static_prefix_chars]


def test_static_prefix_moves_when_the_world_does() -> None:
    world = FakeWorld("biology", ["Adaptation"])
    asm = ContextAssembler()
    a = asm.assemble(source=world)
    world.add("Homology")
    b = asm.assemble(source=world)
    assert a.static_prefix_hash != b.static_prefix_hash


def test_session_can_be_pinned_too() -> None:
    world = FakeWorld("b", ["x"])
    sess = [Segment("mem", "memory", Mutation.SESSION)]
    narrow = ContextAssembler().assemble(source=world, session=sess)
    wide = ContextAssembler().assemble(source=world, session=sess, pin_through=Mutation.SESSION)
    assert wide.static_prefix_chars > narrow.static_prefix_chars


def test_order_check_is_a_build_error() -> None:
    bad = [Segment("v", "volatile", Mutation.VOLATILE), Segment("s", "static", Mutation.STATIC)]
    with pytest.raises(ValueError, match="E301"):
        ContextAssembler._check_order(bad)
