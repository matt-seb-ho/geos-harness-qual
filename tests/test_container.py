"""Container argv construction. Runs without docker, enroot, or a network."""
from __future__ import annotations

from pathlib import Path

import pytest

from qualkit import agents
from qualkit.adapter import load_seed
from qualkit.container import ContainerSpec, Mount, render_docker, render_enroot
from qualkit.rollout import build_argv, build_spec, build_task_prompt


@pytest.fixture
def spec():
    return build_spec(load_seed(), "kgdToughnessDominated", Path("/ws"), Path("/corp"),
                      build_task_prompt("kgdToughnessDominated"))


def test_corpus_is_mounted_read_only(spec):
    corpus = next(m for m in spec.mounts if str(m.target) == "/geos_lib")
    assert corpus.read_only, "a writable corpus lets a rollout edit its own evidence"


def test_workspace_is_writable(spec):
    workspace = next(m for m in spec.mounts if str(m.target) == "/workspace")
    assert not workspace.read_only


def test_ground_truth_is_never_mounted(spec):
    targets = " ".join(str(m.source) for m in spec.mounts)
    assert "ground_truth" not in targets


def test_subagent_tools_are_disallowed(spec):
    rendered = " ".join(spec.argv)
    for tool in ("Task", "Agent", "TaskCreate"):
        assert f"--disallowedTools {tool}" in rendered


def test_web_tools_are_disallowed(spec):
    """Every GEOS deck is on GitHub; a fetch tool is a route around the corpus filter."""
    rendered = " ".join(spec.argv)
    for tool in ("WebSearch", "WebFetch"):
        assert f"--disallowedTools {tool}" in rendered
    assert {"WebSearch", "WebFetch"} <= set(agents.DISALLOWED_TOOLS)


def test_no_simulator_is_mounted(spec):
    """Execution is out of the loop, as in the published SIGA setup.

    Measured here: letting the agent run solves cost 7.3 invocations per rollout
    and was a campaign's largest cost driver, for output scoring never reads.
    """
    mounts = " ".join(str(m.target) for m in spec.mounts)
    for path in ("geosx", "geos-install", "geosx-install", "opt"):
        assert path not in mounts
    assert "There is no GEOS binary" in build_task_prompt("kgdToughnessDominated")


def test_every_harness_builds_an_argv():
    from qualkit.agents import HARNESSES
    for name, harness in HARNESSES.items():
        argv = harness.argv(load_seed(), "PROMPT", "some/model", 40)
        assert argv[0] == harness.binary, name
        assert argv[-1] == "PROMPT", name
        assert "some/model" in argv, name


def test_only_claude_claims_to_be_verified():
    from qualkit.agents import HARNESSES
    assert [n for n, h in HARNESSES.items() if h.verified] == ["claude"]


def test_turn_cap_is_passed(spec):
    assert "--max-turns" in spec.argv


def test_prompt_is_separated_from_flags(spec):
    """The task spec starts with `---`; without `--` it parses as a flag."""
    assert spec.argv[-2] == "--"
    assert spec.argv[-1].startswith("--- BEGIN SIMULATION SPECIFICATION ---")


def test_scope_note_is_in_the_task_prompt_not_the_adapter():
    """It defines the task, so it must be identical across candidates."""
    prompt = build_task_prompt("kgdToughnessDominated")
    assert "Do NOT run the simulation" in prompt
    assert "Do NOT run the simulation" not in load_seed().system_prompt()


def test_docker_and_enroot_carry_the_same_mounts():
    spec = ContainerSpec(image="i", argv=["echo", "hi"],
                         mounts=[Mount("/a", "/b", True)], env=["X=1"])
    docker, enroot = render_docker(spec), render_enroot(spec)
    assert "/a:/b:ro" in " ".join(docker)
    assert "/a:/b:none,bind,ro,x-create=dir" in " ".join(enroot)
    assert "cd /workspace" in " ".join(enroot), "enroot ignores the image WORKDIR"
