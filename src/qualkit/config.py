"""The harness configuration: everything about the agent except the model.

This is the object your loop evolves. It is deliberately not a small set of
text fields -- the premise of the work is that *the harness* is the thing being
optimised, and a harness is more than its prompt. All of the following are
yours to change, together or separately:

==================  ============================================================
``system_prompt``   text appended to the agent's system prompt
``tools``           which tools exist at all
``disallowed_tools``  which are withheld
``files``           anything, mounted read-only at ``/harness`` in the container:
                    hook scripts, MCP servers, skills, reference notes, a
                    procedural cheatsheet the agent reads on demand
``workspace_files`` files placed in ``/workspace`` before the agent starts --
                    ``CLAUDE.md``, a scratch template, a checklist
``settings``        the harness's own settings JSON. **Hooks live here**: Stop,
                    PostToolUse, PreToolUse
``mcp_servers``     new tools, as MCP server definitions
``max_turns``       context and turn budget
``env``             environment variables inside the container
``retry``           a host-side loop: shell checks against the finished
                    workspace, and what the agent is told when one fails
``extra_argv``      escape hatch -- any other flag the CLI takes
==================  ============================================================

**There are no token budgets and no size limits.** An earlier version of this
kit imposed them; that was the wrong instinct. A configuration that wins on
score while tripling cost is not obviously worse than one that does neither --
it depends what you are optimising for, and deciding that is your job, not the
kit's. What the kit does instead is *measure* the thing a budget was trying to
protect: :class:`~qualkit.evaluate.EvalResult` reports score, reliability and
efficiency side by side, and :func:`~qualkit.evaluate.compare` reports the
change in all three. If your configuration buys a point of score with a doubling
of cost, you will see it, and you can argue either way in the write-up.

What is fixed, and why
----------------------
Five things, all of them about whether the experiment means anything rather than
about design taste:

1. **The model.** The whole premise is optimisation around a frozen model. Vary
   it and you are measuring something else.
2. **No subagent tools** (``Task``/``Agent``/``TaskCreate``). Not a style rule: a
   rollout nominally on one model once spawned a subagent on a different,
   stronger one that took 85% of the bill. That breaks the frozen-model premise
   silently.
3. **No web tools** (``WebSearch``/``WebFetch``). Every GEOS deck is public on
   GitHub and the container has network, so a fetch tool routes straight around
   the corpus filtering and the benchmark stops measuring authoring.
4. **The task prompt.** It defines the deliverable, so it must be identical
   across configurations, or two candidates are solving different tasks.
5. **The scorer and the ground truth.** Not reachable from inside a rollout at
   all; scoring happens on the host after the container exits.

:meth:`HarnessConfig.validate` enforces 1-3 and raises before any rollout is
spent. Free rejections are where bad proposals should die.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "harness" / "seed"

#: Tools no configuration may enable, with the reason each one is here. Not
#: design constraints -- validity constraints. See the module docstring.
FORBIDDEN_TOOLS: dict[str, str] = {
    "Task": "spawns a subagent, which can run a different model than the one named",
    "Agent": "same",
    "TaskCreate": "same",
    "WebSearch": "every GEOS deck is on GitHub; this routes around the corpus filter",
    "WebFetch": "same",
}

#: Where the ``files`` bundle is mounted inside the container.
CONTAINER_HARNESS_DIR = "/harness"


class ConfigError(ValueError):
    """A configuration that must not be run. Always raised before any spend."""


@dataclass(frozen=True)
class RetryPolicy:
    """A host-driven loop: check the finished workspace, push back, run again.

    Harness-agnostic, so it works on a CLI with no hook mechanism of its own. If
    your harness *does* have hooks (Claude Code does -- ``settings["hooks"]``),
    that is the other way to do this and it keeps the agent inside one session.
    Both are legitimate; they cost different things and that is worth measuring.

    ``checks`` are shell commands run in the container with the finished
    workspace as the working directory. A non-zero exit means "not done", and
    its combined output is what the agent is shown if ``feedback`` says so.
    """

    max_attempts: int = 1
    checks: tuple[str, ...] = ()
    #: "none" | "terse" | "verbose". Verbose forwards the check's own output,
    #: which for `xmllint --schema` is the entire list of legal elements at the
    #: point of failure -- the richest signal available here.
    feedback: str = "terse"

    def validate(self) -> None:
        if not 1 <= self.max_attempts <= 6:
            raise ConfigError(f"max_attempts must be 1..6, got {self.max_attempts}")
        if self.feedback not in {"none", "terse", "verbose"}:
            raise ConfigError(f"unknown feedback mode {self.feedback!r}")

    def to_json(self) -> dict[str, Any]:
        return {"max_attempts": self.max_attempts, "checks": list(self.checks),
                "feedback": self.feedback}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "RetryPolicy":
        return cls(max_attempts=int(data.get("max_attempts", 1)),
                   checks=tuple(data.get("checks", ())),
                   feedback=str(data.get("feedback", "terse")))


@dataclass(frozen=True)
class HarnessConfig:
    """One harness. Immutable; edit with :meth:`with_changes`."""

    system_prompt: str = ""
    #: ``None`` leaves the harness's own default tool set alone.
    tools: tuple[str, ...] | None = None
    disallowed_tools: tuple[str, ...] = ()
    max_turns: int = 60
    #: ``relative/path -> contents``, mounted read-only at ``/harness``.
    files: Mapping[str, str] = field(default_factory=dict)
    #: ``relative/path -> contents``, written into ``/workspace`` before the run.
    workspace_files: Mapping[str, str] = field(default_factory=dict)
    #: The harness's settings JSON. Hooks go here.
    settings: Mapping[str, Any] = field(default_factory=dict)
    #: MCP server definitions, rendered to an MCP config file.
    mcp_servers: Mapping[str, Any] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    extra_argv: tuple[str, ...] = ()
    #: Free text: where this configuration came from. Fill it in -- an archive of
    #: anonymous candidates is very hard to write up.
    origin: str = "seed"
    parent_id: str | None = None

    # -- identity ---------------------------------------------------------
    @property
    def cid(self) -> str:
        """Content hash. Identical configurations share an id, so caching is safe."""
        payload = json.dumps(self.to_json(include_provenance=False), sort_keys=True)
        return "cfg_" + hashlib.sha256(payload.encode()).hexdigest()[:12]

    def size(self) -> dict[str, int]:
        """Rough bytes per part. For your own reporting; nothing enforces it."""
        return {
            "system_prompt": len(self.system_prompt),
            "files": sum(len(v) for v in self.files.values()),
            "workspace_files": sum(len(v) for v in self.workspace_files.values()),
            "settings": len(json.dumps(dict(self.settings))),
            "mcp_servers": len(json.dumps(dict(self.mcp_servers))),
        }

    # -- validity ---------------------------------------------------------
    def validate(self) -> None:
        """Raise :class:`ConfigError` if this configuration must not be run."""
        enabled = set(self.tools or ())
        bad = sorted(enabled & set(FORBIDDEN_TOOLS))
        if bad:
            raise ConfigError(
                "these tools break the experiment rather than the style guide: "
                + "; ".join(f"{name} ({FORBIDDEN_TOOLS[name]})" for name in bad)
            )
        if not 1 <= self.max_turns <= 400:
            raise ConfigError(f"max_turns must be 1..400, got {self.max_turns}")
        for path in list(self.files) + list(self.workspace_files):
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ConfigError(f"file path must be relative and contained: {path!r}")
        for key in ("model", "--model"):
            if key in self.extra_argv:
                raise ConfigError(
                    "the model is frozen: optimisation around a fixed model is the "
                    "premise of the experiment, so extra_argv may not set it"
                )
        self.retry.validate()

    @property
    def effective_disallowed(self) -> tuple[str, ...]:
        """What is actually passed to the CLI: your list plus the validity floor."""
        return tuple(sorted(set(self.disallowed_tools) | set(FORBIDDEN_TOOLS)))

    # -- editing ----------------------------------------------------------
    def with_changes(self, *, origin: str, **changes: Any) -> "HarnessConfig":
        """A new configuration with some parts replaced. ``origin`` is required.

        Requiring a note is deliberate: the most useful artifact this exercise
        can produce is a legible account of why each accepted edit was made, and
        that cannot be reconstructed afterwards.
        """
        if not str(origin).strip():
            raise ConfigError("with_changes() needs a non-empty origin note")
        return replace(self, origin=origin, parent_id=self.cid, **changes)

    def with_file(self, path: str, contents: str, *, origin: str) -> "HarnessConfig":
        """Add or replace one file in the ``/harness`` bundle."""
        return self.with_changes(origin=origin, files={**dict(self.files), path: contents})

    # -- serialization -----------------------------------------------------
    def to_json(self, *, include_provenance: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "system_prompt": self.system_prompt,
            "tools": list(self.tools) if self.tools is not None else None,
            "disallowed_tools": list(self.disallowed_tools),
            "max_turns": self.max_turns,
            "files": dict(self.files),
            "workspace_files": dict(self.workspace_files),
            "settings": dict(self.settings),
            "mcp_servers": dict(self.mcp_servers),
            "env": dict(self.env),
            "retry": self.retry.to_json(),
            "extra_argv": list(self.extra_argv),
        }
        if include_provenance:
            data |= {"origin": self.origin, "parent_id": self.parent_id, "cid": self.cid}
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "HarnessConfig":
        tools = data.get("tools")
        return cls(
            system_prompt=data.get("system_prompt", ""),
            tools=tuple(tools) if tools is not None else None,
            disallowed_tools=tuple(data.get("disallowed_tools", ())),
            max_turns=int(data.get("max_turns", 60)),
            files=dict(data.get("files", {})),
            workspace_files=dict(data.get("workspace_files", {})),
            settings=dict(data.get("settings", {})),
            mcp_servers=dict(data.get("mcp_servers", {})),
            env=dict(data.get("env", {})),
            retry=RetryPolicy.from_json(data.get("retry", {})),
            extra_argv=tuple(data.get("extra_argv", ())),
            origin=data.get("origin", "unknown"),
            parent_id=data.get("parent_id"),
        )

    # -- on disk -----------------------------------------------------------
    def save(self, directory: Path) -> Path:
        """Write as a directory a human can read in a diff.

        ``config.json`` holds the knobs; ``files/`` and ``workspace/`` hold the
        bundles as real files, so a champion configuration is browsable rather
        than a wall of escaped JSON.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        payload = self.to_json()
        for key, subdir in (("files", "files"), ("workspace_files", "workspace")):
            bundle = payload.pop(key)
            for relative, contents in bundle.items():
                target = directory / subdir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents)
        (directory / "config.json").write_text(json.dumps(payload, indent=2) + "\n")
        return directory

    @classmethod
    def load(cls, directory: Path = SEED_DIR) -> "HarnessConfig":
        directory = Path(directory)
        if not directory.is_dir():
            raise ConfigError(f"no configuration directory at {directory}")
        data = dict(json.loads((directory / "config.json").read_text()))
        for key, subdir in (("files", "files"), ("workspace_files", "workspace")):
            root = directory / subdir
            # Dotfiles are scaffolding (.gitkeep keeps an empty bundle dir in
            # git); they are not part of the configuration and must not change
            # its content hash.
            data[key] = {
                str(path.relative_to(root)): path.read_text()
                for path in sorted(root.rglob("*"))
                if path.is_file() and not path.name.startswith(".")
            } if root.is_dir() else {}
        return cls.from_json(data)


def load_seed() -> HarnessConfig:
    """The starting configuration: your loop's input, and the thing to beat."""
    return HarnessConfig.load(SEED_DIR)


def diff(before: HarnessConfig, after: HarnessConfig) -> list[str]:
    """Human-readable summary of what changed. Use it in your decision log."""
    out: list[str] = []
    if before.system_prompt != after.system_prompt:
        out.append(f"system_prompt: {len(before.system_prompt)} -> "
                   f"{len(after.system_prompt)} chars")
    for name in ("tools", "disallowed_tools", "extra_argv"):
        a, b = getattr(before, name), getattr(after, name)
        if a != b:
            out.append(f"{name}: {a} -> {b}")
    if before.max_turns != after.max_turns:
        out.append(f"max_turns: {before.max_turns} -> {after.max_turns}")
    for name in ("files", "workspace_files"):
        a, b = dict(getattr(before, name)), dict(getattr(after, name))
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        if added or removed or changed:
            out.append(f"{name}: +{added} -{removed} ~{changed}")
    for name in ("settings", "mcp_servers", "env"):
        if dict(getattr(before, name)) != dict(getattr(after, name)):
            out.append(f"{name} changed")
    if before.retry != after.retry:
        out.append(f"retry: {before.retry.to_json()} -> {after.retry.to_json()}")
    return out or ["no change"]
