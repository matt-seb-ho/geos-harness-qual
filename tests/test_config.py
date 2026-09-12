"""The configuration contract: immutable, content-addressed, few constraints."""
from __future__ import annotations

import pytest

from qualkit.config import (FORBIDDEN_TOOLS, ConfigError, HarnessConfig,
                            RetryPolicy, diff, load_seed)


def test_seed_is_valid_and_minimal():
    seed = load_seed()
    seed.validate()
    assert seed.files == {} and seed.settings == {} and seed.mcp_servers == {}
    assert seed.retry.max_attempts == 1


def test_identical_content_is_the_same_configuration():
    a = HarnessConfig(system_prompt="x", files={"a.md": "y"})
    b = HarnessConfig(system_prompt="x", files={"a.md": "y"},
                      origin="found by a different method")
    assert a.cid == b.cid, "the id must not depend on provenance, or caching breaks"


def test_there_is_no_size_limit():
    """Deliberate. Size is measured and reported, not forbidden."""
    huge = HarnessConfig(system_prompt="word " * 100_000)
    huge.validate()
    assert huge.size()["system_prompt"] > 100_000


@pytest.mark.parametrize("tool", sorted(FORBIDDEN_TOOLS))
def test_validity_floor_cannot_be_opted_out_of(tool):
    with pytest.raises(ConfigError):
        HarnessConfig(tools=("Bash", tool)).validate()


def test_forbidden_tools_are_disallowed_even_if_you_say_nothing():
    assert set(load_seed().effective_disallowed) >= set(FORBIDDEN_TOOLS)


def test_the_model_cannot_be_changed_through_the_escape_hatch():
    with pytest.raises(ConfigError, match="model is frozen"):
        HarnessConfig(extra_argv=("--model", "something/else")).validate()


def test_file_paths_must_stay_inside_the_bundle():
    with pytest.raises(ConfigError):
        HarnessConfig(files={"../../etc/passwd": "x"}).validate()
    with pytest.raises(ConfigError):
        HarnessConfig(workspace_files={"/etc/passwd": "x"}).validate()


def test_with_changes_requires_a_reason_and_records_lineage():
    seed = load_seed()
    with pytest.raises(ConfigError):
        seed.with_changes(origin="", max_turns=10)
    child = seed.with_changes(origin="because", max_turns=10)
    assert child.parent_id == seed.cid and child.cid != seed.cid
    assert seed.max_turns != 10, "the parent must not be mutated"


def test_round_trip_through_disk(tmp_path):
    original = load_seed().with_changes(
        origin="test",
        files={"hooks/stop.py": "print('hi')", "notes/cheatsheet.md": "c"},
        workspace_files={"CLAUDE.md": "w"},
        settings={"hooks": {"Stop": [{"matcher": ""}]}},
        mcp_servers={"xmllint": {"command": "python3", "args": ["/harness/mcp.py"]}},
        retry=RetryPolicy(max_attempts=3, checks=("xmllint --noout inputs/*.xml",),
                          feedback="verbose"))
    original.save(tmp_path)
    assert HarnessConfig.load(tmp_path).cid == original.cid
    assert (tmp_path / "files" / "hooks" / "stop.py").is_file(), "browsable, not escaped JSON"


def test_diff_names_what_moved():
    seed = load_seed()
    changed = seed.with_changes(origin="t", max_turns=20, files={"a.md": "x"})
    rendered = " ".join(diff(seed, changed))
    assert "max_turns" in rendered and "files" in rendered
    assert diff(seed, seed) == ["no change"]
