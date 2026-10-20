import json
from pathlib import Path

import pytest

from qukaizen_harness import ModelManager, ModelPolicy, PolicyError

from .fakes import FakeRuntime

CATALOG = {"resident-9b": 9.0, "frontier-120b": 117.0, "tiny-0.5b": 0.5, "big-70b": 70.0}


def rt() -> FakeRuntime:
    return FakeRuntime(CATALOG, lambda p: "")


def test_policy_round_trips_through_a_file(tmp_path: Path) -> None:
    p = ModelPolicy("resident-9b", streamable=frozenset({"frontier-120b"}))
    f = tmp_path / "model-policy.json"
    f.write_text(json.dumps(p.dump()))
    assert ModelPolicy.load(f) == p


def test_resident_is_loaded_once_and_pinned() -> None:
    r = rt()
    m = ModelManager(ModelPolicy("resident-9b"), r)
    a = m.ensure_resident()
    b = m.ensure_resident()
    assert a is b and a.resident
    assert [x.name for x in r.loaded()] == ["resident-9b"]


@pytest.mark.parametrize("name", ["tiny-0.5b", "big-70b"])
def test_resident_outside_the_ceiling_is_refused(name: str) -> None:
    m = ModelManager(ModelPolicy(name), rt())
    with pytest.raises(PolicyError):
        m.ensure_resident()


def test_streaming_a_frontier_model_keeps_the_resident() -> None:
    r = rt()
    m = ModelManager(ModelPolicy("resident-9b", streamable=frozenset({"frontier-120b"})), r)
    info = m.stream("frontier-120b")
    assert not info.resident
    assert {x.name: x.resident for x in r.loaded()} == {"resident-9b": True, "frontier-120b": False}


def test_unlisted_model_cannot_be_streamed() -> None:
    m = ModelManager(ModelPolicy("resident-9b"), rt())
    with pytest.raises(PolicyError):
        m.stream("frontier-120b")


def test_eviction_is_a_policy_violation() -> None:
    r = rt()
    r.evict_on_load = True
    m = ModelManager(ModelPolicy("resident-9b", streamable=frozenset({"frontier-120b"})), r)
    with pytest.raises(PolicyError, match="evicted"):
        m.stream("frontier-120b")
