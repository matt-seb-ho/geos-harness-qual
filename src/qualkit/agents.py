"""Which coding agent runs inside the container, and how it is invoked.

The agent is the *base policy*. This project's premise is that you improve the
adapter wrapped around it rather than the agent itself -- but nothing says the
base policy has to be Claude Code, and there is an open question in the research
programme about whether an adapter found on one harness transfers to another.
So the harness is a registry, not a hardcoded command.

**Pick one harness and keep it fixed for your whole experiment.** It is not a
searchable component. Two candidates evaluated on different harnesses are not
comparable, and "my method works on harness A" is a different claim from "my
method works". If you want to compare harnesses, that is a second experiment
with its own budget, and it is a genuinely interesting one -- say so in the
write-up rather than mixing it into the first.

What every harness must do
--------------------------
1. accept a system-prompt string (the adapter) and a user prompt (the task);
2. run non-interactively with tool use auto-approved;
3. take a turn cap;
4. write files into the container's ``/workspace/inputs/``.

Scoring reads the workspace, so it does not care which harness produced it. The
budget guard reads the *account balance*, so it does not care either. The only
thing a harness affects is the per-rollout telemetry (tool calls, turns, token
counts), which comes from parsing that harness's transcript format -- and on an
unverified harness that parse may come back empty. An empty ``Cost`` is a
missing progress estimate, not a missing spend limit.

What is here
------------
``claude``
    Claude Code's own CLI, ``claude -p``. **Verified** -- this is the one the
    research harness uses, so numbers are comparable with ours.

``acpx:claude`` / ``acpx:codex`` / ``acpx:pi`` / ``acpx:openclaw``
    The same four agents behind the Agent Client Protocol, through the ``acpx``
    CLI that is already in the image. One uniform set of flags for all of them.
    **Unverified**: the flags below are read off ``acpx --help`` and the agents
    other than ``claude`` also need their own credentials and may need
    installing. ``qual harnesses`` probes what is actually reachable.

Adding your own is a dataclass and an argv function. If you get one working,
that is a contribution -- put it in the pull request.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from qualkit.adapter import Adapter

#: Tools the agent may use. An explicit allowlist rather than a blocklist,
#: because a harness release can add a tool and a blocklist will not know.
#: Filesystem and shell only: everything the task needs is on the mounted
#: corpus.
ALLOWED_TOOLS: tuple[str, ...] = ("Bash", "Read", "Write", "Edit", "Glob", "Grep")

#: Belt and braces, each for a reason worth knowing.
#:
#: ``WebSearch``/``WebFetch``: **contamination.** Every GEOS example deck is on
#: GitHub. An agent that can fetch a URL can fetch the answer, and the corpus
#: filtering that this kit spends real effort on becomes theatre. The research
#: harness does *not* currently block these; this kit does, and that is a
#: deliberate difference.
#:
#: ``Task``/``Agent``/``TaskCreate``: a rollout nominally on one model once
#: spawned a subagent on a different, stronger model that took 85% of the bill.
#: A cost problem, and a worse validity problem -- the frozen-agent premise
#: requires the agent to be the model you named.
#:
#: ``AskUserQuestion``: nothing is listening; the call stalls the turn.
DISALLOWED_TOOLS: tuple[str, ...] = (
    "WebSearch", "WebFetch", "Task", "Agent", "TaskCreate", "AskUserQuestion",
    "Skill", "Workflow",
)


@dataclass(frozen=True)
class Harness:
    """One way to run a coding agent non-interactively inside the container."""

    name: str
    #: ``(adapter, prompt, model, max_turns) -> argv`` run inside the container.
    argv: Callable[[Adapter, str, str, int], list[str]]
    #: Which transcript parser to use. See ``qualkit.rollout.parse_events``.
    transcript: str
    #: The executable the container must have.
    binary: str
    #: Has a real rollout ever been run through this? Only claim what is true.
    verified: bool = False
    notes: str = ""


def _claude_argv(adapter: Adapter, prompt: str, model: str, max_turns: int) -> list[str]:
    argv = [
        "claude", "-p", "--verbose",
        "--model", model,
        "--append-system-prompt", adapter.system_prompt(),
        "--output-format", "stream-json",
        "--permission-mode", "bypassPermissions",
        "--max-turns", str(max_turns),
        "--tools", ",".join(ALLOWED_TOOLS),
    ]
    for tool in DISALLOWED_TOOLS:
        argv += ["--disallowedTools", tool]
    # `--` separator: the task prompt opens with `--- BEGIN ...` and would
    # otherwise be parsed as a flag.
    return argv + ["--", prompt]


def _acpx_argv(agent: str) -> Callable[[Adapter, str, str, int], list[str]]:
    def build(adapter: Adapter, prompt: str, model: str, max_turns: int) -> list[str]:
        return [
            "acpx", agent, "exec",
            "--cwd", "/workspace",
            "--model", model,
            "--append-system-prompt", adapter.system_prompt(),
            "--allowed-tools", ",".join(ALLOWED_TOOLS),
            "--max-turns", str(max_turns),
            "--approve-all",
            "--non-interactive-permissions", "deny",
            "--format", "json",
            "--", prompt,
        ]
    return build


HARNESSES: dict[str, Harness] = {
    "claude": Harness(
        name="claude", argv=_claude_argv, transcript="claude-stream-json",
        binary="claude", verified=True,
        notes="Claude Code's own CLI. What the research harness runs, so scores "
              "are comparable with ours. Start here.",
    ),
    "acpx:claude": Harness(
        name="acpx:claude", argv=_acpx_argv("claude"), transcript="acpx-json",
        binary="acpx",
        notes="Same agent through the Agent Client Protocol. The cheapest way to "
              "check that an adapter is not exploiting one CLI's quirks.",
    ),
    "acpx:codex": Harness(
        name="acpx:codex", argv=_acpx_argv("codex"), transcript="acpx-json",
        binary="acpx",
        notes="Needs its own credentials in the container environment.",
    ),
    "acpx:pi": Harness(
        name="acpx:pi", argv=_acpx_argv("pi"), transcript="acpx-json",
        binary="acpx",
    ),
    "acpx:openclaw": Harness(
        name="acpx:openclaw", argv=_acpx_argv("openclaw"), transcript="acpx-json",
        binary="acpx",
    ),
}

#: Chosen once, at the start of an experiment, and then left alone.
DEFAULT_HARNESS = os.environ.get("QUAL_HARNESS", "claude")


def get(name: str | None = None) -> Harness:
    name = name or DEFAULT_HARNESS
    try:
        return HARNESSES[name]
    except KeyError:
        raise KeyError(
            f"unknown harness {name!r}; known: {', '.join(HARNESSES)}. "
            f"Adding one is a dataclass and an argv function -- see qualkit/agents.py."
        ) from None


def probe(image: str | None = None) -> list[tuple[str, bool, str]]:
    """Which harnesses this container image can actually run. ``(name, ok, why)``."""
    import subprocess

    from qualkit.container import IMAGE, ContainerSpec

    image = image or IMAGE
    out: list[tuple[str, bool, str]] = []
    seen: dict[str, bool] = {}
    for name, harness in HARNESSES.items():
        if harness.binary not in seen:
            spec = ContainerSpec(image=image, argv=["sh", "-c",
                                                    f"command -v {harness.binary}"],
                                 workdir=None)
            try:
                probe_result = subprocess.run(spec.render(), capture_output=True,
                                              text=True, timeout=120)
                seen[harness.binary] = probe_result.returncode == 0
            except Exception:  # noqa: BLE001
                seen[harness.binary] = False
        ok = seen[harness.binary]
        why = ("verified on this project" if harness.verified and ok
               else "binary present, never run end to end here" if ok
               else f"{harness.binary} not found in the image")
        out.append((name, ok, why))
    return out
