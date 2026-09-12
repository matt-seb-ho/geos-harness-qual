"""The adapter: the only thing your loop is allowed to change.

An adapter is a small bundle of always-visible text wrapped around a *frozen*
coding agent. The model does not change. The container does not change. The
task prompt does not change. Four components do:

==================  ============================================================
``primer``          goes into the system prompt. What GEOS is, where things are.
``cheatsheet``      procedural memory: how to do the recurring steps.
``constraints``     negative rules -- what not to do, and what the validator
                    rejects.
``stop_policy``     config, not prose: how many times the agent is pushed to
                    fix its deck before the rollout ends, and what it is told.
==================  ============================================================

Every component has a token budget, enforced here rather than suggested. The
first version of this system had no budget and its primer grew 12x over three
unmonitored rounds -- an always-on artifact that got longer every round, which
is both the cost failure and the over-specification failure at once. If a
proposal exceeds the budget it is rejected *before* any rollout is spent:
free rejections are where bad proposals should die.

``Adapter`` is immutable. ``with_changes()`` returns a new one, and the id is a
hash of the content, so two identical adapters are the same adapter and a
cached evaluation is safe to reuse.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "adapter" / "seed"

#: Token ceilings per component. A "token" here is counted by :func:`count_tokens`,
#: which is a word/punctuation approximation -- close enough to budget with and
#: it costs no API call. Raise these in your own experiment if you want, but
#: *say that you did*: seed headroom is a confound, and a search given a bigger
#: ceiling is not the same experiment as one given a smaller one.
TOKEN_BUDGET: dict[str, int] = {
    "primer": 1200,
    "cheatsheet": 1500,
    "constraints": 600,
}

TEXT_COMPONENTS: tuple[str, ...] = ("primer", "cheatsheet", "constraints")

#: Feedback the stop policy may hand back to the agent when its deck is
#: incomplete. Richer is not automatically better -- it costs turns.
FEEDBACK_SHAPES: frozenset[str] = frozenset({"none", "minimal", "structured"})

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def count_tokens(text: str) -> int:
    """Approximate token count. Deterministic, offline, and good enough to budget."""
    return len(_TOKEN_RE.findall(text or ""))


class AdapterError(ValueError):
    """An adapter that cannot be run. Always raised before a rollout is spent."""


@dataclass(frozen=True)
class StopPolicy:
    """When a rollout is allowed to end, and what the agent is told if it is not.

    This is *config*, not code: your loop can search over it without being able
    to rewrite the harness. ``max_retries=0`` disables the check entirely, which
    is the cheapest setting and the seed's.
    """

    max_retries: int = 0
    feedback_shape: str = "minimal"
    #: Checks that must pass before the agent may stop. "parse" is XML
    #: well-formedness; "required_sections" is the four top-level GEOS blocks.
    checks: tuple[str, ...] = ("parse",)

    KNOWN_CHECKS = ("parse", "required_sections")

    def validate(self) -> None:
        if not 0 <= self.max_retries <= 5:
            raise AdapterError(f"max_retries must be in 0..5, got {self.max_retries}")
        if self.feedback_shape not in FEEDBACK_SHAPES:
            raise AdapterError(
                f"feedback_shape {self.feedback_shape!r} not in {sorted(FEEDBACK_SHAPES)}"
            )
        unknown = set(self.checks) - set(self.KNOWN_CHECKS)
        if unknown:
            raise AdapterError(
                f"unknown checks {sorted(unknown)}; known: {list(self.KNOWN_CHECKS)}"
            )

    def to_json(self) -> dict[str, Any]:
        return {"max_retries": self.max_retries,
                "feedback_shape": self.feedback_shape,
                "checks": list(self.checks)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "StopPolicy":
        return cls(
            max_retries=int(data.get("max_retries", 0)),
            feedback_shape=str(data.get("feedback_shape", "minimal")),
            checks=tuple(data.get("checks", ("parse",))),
        )


@dataclass(frozen=True)
class Adapter:
    """Four components and a provenance note. Immutable; edit via :meth:`with_changes`."""

    primer: str
    cheatsheet: str = ""
    constraints: str = ""
    stop_policy: StopPolicy = field(default_factory=StopPolicy)
    #: Free text: where this adapter came from. Your loop should fill it in --
    #: an archive of anonymous candidates is very hard to write up.
    origin: str = "seed"
    parent_id: str | None = None

    # -- identity ---------------------------------------------------------
    @property
    def cid(self) -> str:
        """Content hash. Identical adapters share an id, so caching is safe."""
        payload = json.dumps(self.to_json(include_provenance=False), sort_keys=True)
        return "cand_" + hashlib.sha256(payload.encode()).hexdigest()[:12]

    def component(self, name: str) -> str:
        if name not in TEXT_COMPONENTS:
            raise AdapterError(f"no text component named {name!r}")
        return getattr(self, name)

    def token_counts(self) -> dict[str, int]:
        return {name: count_tokens(self.component(name)) for name in TEXT_COMPONENTS}

    # -- validity ---------------------------------------------------------
    def validate(self) -> None:
        """Raise :class:`AdapterError` if this adapter may not be run.

        Called by :func:`qualkit.evaluate.evaluate_adapter` before anything is
        spent. Call it yourself in the proposer too -- a rejection that costs
        nothing is worth more than one that costs six rollouts.
        """
        if not self.primer.strip():
            raise AdapterError("primer is empty; the agent would be told nothing at all")
        over = [
            f"{name} {n} > {TOKEN_BUDGET[name]}"
            for name, n in self.token_counts().items()
            if n > TOKEN_BUDGET[name]
        ]
        if over:
            raise AdapterError("component over token budget: " + "; ".join(over))
        self.stop_policy.validate()

    # -- editing ----------------------------------------------------------
    def with_changes(self, *, origin: str, **changes: Any) -> "Adapter":
        """A new adapter with some components replaced. ``origin`` is required.

        Requiring a note is deliberate: the single most useful artifact this
        exercise can produce is a legible account of *why* each accepted edit
        was made, and that is impossible to reconstruct afterwards.
        """
        if not str(origin).strip():
            raise AdapterError("with_changes() needs a non-empty origin note")
        return replace(self, origin=origin, parent_id=self.cid, **changes)

    # -- what the agent actually sees --------------------------------------
    def system_prompt(self) -> str:
        """The text appended to the agent's system prompt, in a fixed order.

        Order and headings are fixed on purpose: if the loop could also search
        over layout, two adapters with identical content could score
        differently and the comparison would stop meaning anything.
        """
        parts = [self.primer.strip()]
        if self.cheatsheet.strip():
            parts.append("# Procedure\n\n" + self.cheatsheet.strip())
        if self.constraints.strip():
            parts.append("# Constraints\n\n" + self.constraints.strip())
        return "\n\n---\n\n".join(parts) + "\n"

    # -- serialization -----------------------------------------------------
    def to_json(self, *, include_provenance: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "primer": self.primer,
            "cheatsheet": self.cheatsheet,
            "constraints": self.constraints,
            "stop_policy": self.stop_policy.to_json(),
        }
        if include_provenance:
            data |= {"origin": self.origin, "parent_id": self.parent_id, "cid": self.cid}
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Adapter":
        return cls(
            primer=data.get("primer", ""),
            cheatsheet=data.get("cheatsheet", ""),
            constraints=data.get("constraints", ""),
            stop_policy=StopPolicy.from_json(data.get("stop_policy", {})),
            origin=data.get("origin", "unknown"),
            parent_id=data.get("parent_id"),
        )

    def save(self, directory: Path) -> Path:
        """Write the adapter as a directory of files a human can read in a diff."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "PRIMER.md").write_text(self.primer)
        (directory / "cheatsheet.md").write_text(self.cheatsheet)
        (directory / "constraints.md").write_text(self.constraints)
        (directory / "manifest.json").write_text(json.dumps(
            {"stop_policy": self.stop_policy.to_json(), "origin": self.origin,
             "parent_id": self.parent_id, "cid": self.cid,
             "token_counts": self.token_counts()},
            indent=2) + "\n")
        return directory

    @classmethod
    def load(cls, directory: Path = SEED_DIR) -> "Adapter":
        directory = Path(directory)
        if not directory.is_dir():
            raise AdapterError(f"no adapter directory at {directory}")
        manifest = {}
        manifest_path = directory / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())

        def read(name: str) -> str:
            path = directory / name
            return path.read_text() if path.is_file() else ""

        return cls(
            primer=read("PRIMER.md"),
            cheatsheet=read("cheatsheet.md"),
            constraints=read("constraints.md"),
            stop_policy=StopPolicy.from_json(manifest.get("stop_policy", {})),
            origin=manifest.get("origin", f"loaded from {directory}"),
            parent_id=manifest.get("parent_id"),
        )


def load_seed() -> Adapter:
    """The starting adapter. Your loop's input, and the thing you must beat."""
    return Adapter.load(SEED_DIR)


def diff(before: Adapter, after: Adapter) -> list[str]:
    """Human-readable summary of what changed between two adapters."""
    out: list[str] = []
    for name in TEXT_COMPONENTS:
        a, b = before.component(name), after.component(name)
        if a != b:
            out.append(f"{name}: {count_tokens(a)} -> {count_tokens(b)} tokens")
    if before.stop_policy != after.stop_policy:
        out.append(f"stop_policy: {before.stop_policy.to_json()} -> "
                   f"{after.stop_policy.to_json()}")
    return out or ["no change"]
