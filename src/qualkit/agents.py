"""Which coding agent runs inside the container, and how a configuration reaches it.

The agent is the *base policy*, and it is a choice. The premise of this work is
that you improve the harness around a frozen model, not that the harness has to
be Claude Code -- and whether a configuration found on one agent transfers to
another is an open question in the research programme.

**Pick one and keep it fixed for the whole experiment.** The agent is not part
of the search space. Two candidates evaluated on different agents are not
comparable, and "my method works on agent A" is a different claim from "my method
works".

What a harness has to do
------------------------
1. accept a system prompt and a user prompt;
2. run non-interactively with tool use auto-approved;
3. take a turn cap and a tool list;
4. write files into ``/workspace/inputs/``.

Anything a given CLI offers beyond that -- hooks, settings files, MCP servers --
is reachable through :class:`~qualkit.config.HarnessConfig`, and which of those
a particular agent supports is recorded below. Scoring reads the workspace and
the budget guard reads the account balance, so neither depends on the agent.

``claude``
    Claude Code's own CLI, ``claude -p``. **Verified** end to end here, and what
    the research harness uses, so numbers are comparable with ours. Supports
    settings-file hooks and MCP config.

``acpx:claude`` / ``acpx:codex`` / ``acpx:pi`` / ``acpx:openclaw``
    The same four agents behind the Agent Client Protocol via ``acpx``, which is
    already in the image. One uniform flag set. **Unverified**: the flags come
    from ``acpx --help`` and nobody has run one end to end; the non-Claude agents
    also need their own credentials. ``qual harnesses`` probes what is reachable.
    ACP has no settings-file hook mechanism, so a configuration that relies on
    ``settings["hooks"]`` will silently do nothing there -- use
    ``retry`` instead, which is host-driven and works everywhere.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from qualkit.config import CONTAINER_HARNESS_DIR, HarnessConfig

#: Paths inside the container that a rendered configuration writes to.
CONTAINER_SETTINGS_PATH = "/workspace/.harness_settings.json"
CONTAINER_MCP_PATH = "/workspace/.harness_mcp.json"


@dataclass(frozen=True)
class Harness:
    """One way to run a coding agent non-interactively inside the container."""

    name: str
    #: ``(config, prompt, model) -> argv``, run inside the container.
    argv: Callable[[HarnessConfig, str, str], list[str]]
    #: Which transcript parser to use. See ``qualkit.rollout.parse_events``.
    transcript: str
    #: The executable the image must have.
    binary: str
    #: Config fields this agent can actually honour. A field outside this set is
    #: reported by ``qual harnesses`` rather than silently ignored.
    supports: frozenset[str] = frozenset({"system_prompt", "tools",
                                          "disallowed_tools", "max_turns",
                                          "files", "workspace_files", "env",
                                          "retry", "extra_argv"})
    #: Has a real rollout ever been run through this? Claim only what is true.
    verified: bool = False
    notes: str = ""

    def unsupported(self, config: HarnessConfig) -> list[str]:
        """Parts of ``config`` this agent will ignore. Check before you spend."""
        out = []
        if config.settings and "settings" not in self.supports:
            out.append("settings (including hooks)")
        if config.mcp_servers and "mcp_servers" not in self.supports:
            out.append("mcp_servers")
        return out


def _claude_argv(config: HarnessConfig, prompt: str, model: str) -> list[str]:
    argv = [
        "claude", "-p", "--verbose",
        "--model", model,
        "--output-format", "stream-json",
        "--permission-mode", "bypassPermissions",
        "--max-turns", str(config.max_turns),
    ]
    if config.system_prompt.strip():
        argv += ["--append-system-prompt", config.system_prompt]
    if config.tools is not None:
        argv += ["--tools", ",".join(config.tools)]
    for tool in config.effective_disallowed:
        argv += ["--disallowedTools", tool]
    if config.settings:
        argv += ["--settings", CONTAINER_SETTINGS_PATH]
    if config.mcp_servers:
        argv += ["--mcp-config", CONTAINER_MCP_PATH, "--strict-mcp-config"]
    argv += list(config.extra_argv)
    # `--` separator: the task prompt opens with `--- BEGIN ...` and would
    # otherwise be parsed as a flag.
    return argv + ["--", prompt]


def _acpx_argv(agent: str) -> Callable[[HarnessConfig, str, str], list[str]]:
    def build(config: HarnessConfig, prompt: str, model: str) -> list[str]:
        argv = [
            "acpx", agent, "exec",
            "--cwd", "/workspace",
            "--model", model,
            "--max-turns", str(config.max_turns),
            "--approve-all",
            "--non-interactive-permissions", "deny",
            "--format", "json",
        ]
        if config.system_prompt.strip():
            argv += ["--append-system-prompt", config.system_prompt]
        if config.tools is not None:
            argv += ["--allowed-tools", ",".join(config.tools)]
        if config.mcp_servers:
            argv += ["--mcp-config", CONTAINER_MCP_PATH]
        argv += list(config.extra_argv)
        return argv + ["--", prompt]
    return build


_ACP_SUPPORTS = frozenset({"system_prompt", "tools", "max_turns", "files",
                           "workspace_files", "env", "retry", "extra_argv",
                           "mcp_servers"})

HARNESSES: dict[str, Harness] = {
    "claude": Harness(
        name="claude", argv=_claude_argv, transcript="claude-stream-json",
        binary="claude", verified=True,
        supports=frozenset({"system_prompt", "tools", "disallowed_tools",
                            "max_turns", "files", "workspace_files", "settings",
                            "mcp_servers", "env", "retry", "extra_argv"}),
        notes="Claude Code's own CLI. Hooks via settings, tools via MCP, the lot. "
              "Verified here and comparable with our numbers. Start here.",
    ),
    "acpx:claude": Harness(
        name="acpx:claude", argv=_acpx_argv("claude"), transcript="acpx-json",
        binary="acpx", supports=_ACP_SUPPORTS,
        notes="The same agent over the Agent Client Protocol. No settings-file "
              "hooks; use retry instead.",
    ),
    "acpx:codex": Harness(
        name="acpx:codex", argv=_acpx_argv("codex"), transcript="acpx-json",
        binary="acpx", supports=_ACP_SUPPORTS,
        notes="Needs its own credentials in the container environment.",
    ),
    "acpx:pi": Harness(
        name="acpx:pi", argv=_acpx_argv("pi"), transcript="acpx-json",
        binary="acpx", supports=_ACP_SUPPORTS,
    ),
    "acpx:openclaw": Harness(
        name="acpx:openclaw", argv=_acpx_argv("openclaw"), transcript="acpx-json",
        binary="acpx", supports=_ACP_SUPPORTS,
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


def materialize(config: HarnessConfig, workspace: Path, bundle_dir: Path) -> None:
    """Write a configuration to disk so the container can see it.

    ``bundle_dir`` is mounted read-only at ``/harness``; the workspace files and
    the two JSON configs are written into the writable workspace. Paths were
    checked by :meth:`HarnessConfig.validate` before we got here.
    """
    workspace, bundle_dir = Path(workspace), Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for relative, contents in config.files.items():
        target = bundle_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
        if relative.endswith((".sh", ".py")):
            target.chmod(0o755)
    for relative, contents in config.workspace_files.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    if config.settings:
        (workspace / Path(CONTAINER_SETTINGS_PATH).name).write_text(
            json.dumps(dict(config.settings), indent=2))
    if config.mcp_servers:
        (workspace / Path(CONTAINER_MCP_PATH).name).write_text(
            json.dumps({"mcpServers": dict(config.mcp_servers)}, indent=2))


def probe(image: str | None = None) -> list[tuple[str, bool, str]]:
    """Which harnesses this container image can actually run. ``(name, ok, why)``."""
    import subprocess

    from qualkit.container import IMAGE, ContainerSpec

    image = image or IMAGE
    out: list[tuple[str, bool, str]] = []
    seen: dict[str, bool] = {}
    for name, harness in HARNESSES.items():
        if harness.binary not in seen:
            spec = ContainerSpec(image=image,
                                 argv=["sh", "-c", f"command -v {harness.binary}"],
                                 workdir=None)
            try:
                result = subprocess.run(spec.render(), capture_output=True,
                                        text=True, timeout=120)
                seen[harness.binary] = result.returncode == 0
            except Exception:  # noqa: BLE001
                seen[harness.binary] = False
        ok = seen[harness.binary]
        why = ("verified on this project" if harness.verified and ok
               else "binary present, never run end to end here" if ok
               else f"{harness.binary} not found in the image")
        out.append((name, ok, why))
    return out
