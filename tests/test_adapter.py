"""The adapter contract: immutable, budgeted, content-addressed."""
from __future__ import annotations

import pytest

from qualkit.adapter import TOKEN_BUDGET, Adapter, AdapterError, StopPolicy, load_seed


def test_seed_is_valid_and_small():
    seed = load_seed()
    seed.validate()
    assert seed.token_counts()["primer"] < TOKEN_BUDGET["primer"]
    assert seed.cheatsheet.strip() == "" and seed.constraints.strip() == ""


def test_identical_content_is_the_same_adapter():
    a = Adapter(primer="x", cheatsheet="y")
    b = Adapter(primer="x", cheatsheet="y", origin="written by a different method")
    assert a.cid == b.cid, "the id must not depend on provenance, or caching breaks"


def test_over_budget_is_rejected_before_any_spend():
    fat = Adapter(primer="word " * (TOKEN_BUDGET["primer"] + 10))
    with pytest.raises(AdapterError, match="token budget"):
        fat.validate()


def test_empty_primer_is_rejected():
    with pytest.raises(AdapterError):
        Adapter(primer="   ").validate()


def test_with_changes_requires_a_reason():
    with pytest.raises(AdapterError):
        load_seed().with_changes(origin="", cheatsheet="x")


def test_with_changes_records_lineage():
    seed = load_seed()
    child = seed.with_changes(origin="because", cheatsheet="x")
    assert child.parent_id == seed.cid and child.cid != seed.cid
    assert seed.cheatsheet == "", "the parent must not be mutated"


def test_stop_policy_rejects_unknown_checks():
    with pytest.raises(AdapterError, match="unknown checks"):
        StopPolicy(checks=("parse", "run_the_simulation")).validate()


def test_round_trip_through_disk(tmp_path):
    original = load_seed().with_changes(
        origin="test", cheatsheet="c", constraints="d",
        stop_policy=StopPolicy(max_retries=2, feedback_shape="structured"))
    original.save(tmp_path)
    assert Adapter.load(tmp_path).cid == original.cid


def test_system_prompt_order_is_fixed():
    adapter = Adapter(primer="P", cheatsheet="C", constraints="K")
    prompt = adapter.system_prompt()
    assert prompt.index("P") < prompt.index("C") < prompt.index("K")
