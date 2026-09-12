"""One rollout: give a frozen agent a task inside a container, then score it.

A rollout is the unit of cost. It is ~10-25 minutes of wall clock and a few
cents, and everything your loop does is ultimately denominated in these. The
contract is deliberately narrow:

    run_rollout(adapter, task, seed) -> Rollout

and the only thing that varies between two rollouts of the same task is the
adapter. The model, the container, the corpus, the task prompt and the scoring
are fixed. If you find yourself wanting to change one of them to make your
method work, that is a finding for the write-up, not an edit.

**Run and score are one call that cannot be half-performed.** Scoring happens on
the way out, on every path -- non-zero exit, timeout, missing workspace. In an
earlier version of this system they were two steps in a shell script and the
second was simply never invoked, so three rounds of search consumed a score of
``None`` and reported a round mean of zero.

The retry loop is here rather than inside the container. The research harness
runs it as a ``Stop`` hook so the agent never sees a turn boundary; this runs it
as a second invocation against the same workspace. Simpler, visible in the
transcript, and searchable in exactly the same way -- but say which one you used
if you compare numbers with ours.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from qualkit import agents, corpus, tasks
from qualkit.adapter import Adapter
from qualkit.container import IMAGE, ContainerSpec, Mount, prepare_workspace
from qualkit.scoring import Score, score_workspace

#: The rollout model. A gateway slug, not an Anthropic model id -- the agent is
#: Claude Code the *harness*, pointed at OpenRouter. Measured on this project:
#: glm-5.3-flash scores indistinguishably from models seven times its price.
MODEL = os.environ.get("QUAL_MODEL", "z-ai/glm-5.3-flash")

#: Hard ceiling on agent turns. Measured on the research harness: rollouts that
#: hit the wall-clock timeout averaged 199 turns against 84 for those that
#: finished, and input tokens -- the whole bill -- grow superlinearly in turns
#: because each turn resends the conversation. A runaway rollout costs ~3.4x a
#: completed one and returns nothing. SIGA's published runs averaged 25 tool
#: calls on these same specs, so 60 is generous rather than binding.
MAX_TURNS = int(os.environ.get("QUAL_MAX_TURNS", "60"))

#: Wall-clock ceiling per container invocation.
TIMEOUT_S = float(os.environ.get("QUAL_TIMEOUT_S", "1500"))

#: What the deliverable is, and what is out of scope. This lives in the TASK
#: prompt, deliberately, not in the adapter: it defines the task, so it must be
#: identical across every candidate. Inside the adapter it would be a component
#: your loop could delete, and two candidates would then be solving different
#: tasks -- the confound this whole setup exists to avoid.
SCOPE_NOTE = """

--- SCOPE ---
Deliverable: the XML input deck, written to /workspace/inputs/. You are scored
on the deck's structure against a reference deck; nothing downstream reads
simulation output.
Do NOT run the simulation. There is no GEOS binary in this container, no solver
runs, no timestepping. It cannot raise your score and it cannot work here.
Once the deck is written and parses, you are finished.
--- END SCOPE ---"""


@dataclass(frozen=True)
class Cost:
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    wall_seconds: float = 0.0

    def __add__(self, other: "Cost") -> "Cost":
        return Cost(*(a + b for a, b in zip(
            (self.usd, self.input_tokens, self.output_tokens, self.tool_calls,
             self.turns, self.wall_seconds),
            (other.usd, other.input_tokens, other.output_tokens, other.tool_calls,
             other.turns, other.wall_seconds))))

    def to_json(self) -> dict[str, Any]:
        return {"usd": round(self.usd, 6), "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "tool_calls": self.tool_calls,
                "turns": self.turns, "wall_seconds": round(self.wall_seconds, 1)}


@dataclass(frozen=True)
class Rollout:
    task: str
    adapter_id: str
    seed: int
    score: Score
    cost: Cost
    workspace: str | None = None
    attempts: int = 1
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"task": self.task, "adapter_id": self.adapter_id, "seed": self.seed,
                "score": self.score.to_json(), "cost": self.cost.to_json(),
                "workspace": self.workspace, "attempts": self.attempts,
                "error": self.error, "model": MODEL}


def build_task_prompt(task_id: str) -> str:
    """The prompt the agent receives. Fixed across candidates; do not search it."""
    spec = tasks.get(task_id).instructions().strip()
    return ("--- BEGIN SIMULATION SPECIFICATION ---\n"
            f"{spec}\n"
            "--- END SIMULATION SPECIFICATION ---" + SCOPE_NOTE)


def build_argv(adapter: Adapter, prompt: str, *, model: str = MODEL,
               max_turns: int = MAX_TURNS, harness: str | None = None) -> list[str]:
    """The command run inside the container. Shape depends on the harness."""
    return agents.get(harness).argv(adapter, prompt, model, max_turns)


def build_spec(adapter: Adapter, task_id: str, workspace: Path, corpus_dir: Path,
               prompt: str, *, model: str = MODEL, max_turns: int = MAX_TURNS,
               harness: str | None = None) -> ContainerSpec:
    """Mounts, environment and argv for one rollout.

    Note what is *not* mounted: there is no GEOS binary, no solver, no
    validator. The agent authors a deck and cannot run it. That is deliberate
    and it matches the setup the published SIGA results were measured on.
    Letting the agent execute the simulator was measured on this project at
    7.3 solve invocations per rollout and was the single largest cost driver of
    a campaign -- for output that scoring never reads, since the deck is scored
    structurally against a reference. Removing it cut wall-clock 41% and cost
    31%.

    Ground truth is not mounted either. Scoring happens on the host after the
    container exits.
    """
    return ContainerSpec(
        image=IMAGE,
        mounts=[
            Mount(corpus_dir, "/geos_lib", read_only=True),
            Mount(workspace, "/workspace"),
        ],
        env=[
            "HOME=/workspace/.claude_home",
            "XDG_CONFIG_HOME=/workspace/.claude_home/.config",
            "UV_CACHE_DIR=/workspace/.uv_cache",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY=",
            "OPENROUTER_API_KEY",
            # A coding CLI reads a "provider/model" string as a native model id
            # and 404s against a gateway unless told otherwise. These two are the
            # missing signal.
            f"ANTHROPIC_CUSTOM_MODEL_OPTION={model}",
            f"ANTHROPIC_CUSTOM_MODEL_OPTION_NAME={model} via gateway",
        ],
        argv=build_argv(adapter, prompt, model=model, max_turns=max_turns,
                        harness=harness),
    )


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    if not env.get("ANTHROPIC_AUTH_TOKEN"):
        env["ANTHROPIC_AUTH_TOKEN"] = env.get("OPENROUTER_API_KEY", "")
    # A real Anthropic key in the environment wins over the gateway hint and
    # produces a model_not_found 404. Blank it.
    env["ANTHROPIC_API_KEY"] = ""
    return env


# -- the checks the stop policy may require ---------------------------------

def check_parse(workspace: Path) -> list[str]:
    decks = sorted((workspace / "inputs").rglob("*.xml"))
    if not decks:
        return ["no XML deck was written to /workspace/inputs/"]
    problems = []
    for deck in decks:
        try:
            ET.parse(deck)
        except ET.ParseError as exc:
            problems.append(f"{deck.name} is not well-formed XML: {exc}")
    return problems


def check_required_sections(workspace: Path) -> list[str]:
    from qualkit.treesim import REQUIRED_SECTIONS, load_and_resolve_dir
    try:
        root = load_and_resolve_dir(workspace / "inputs")
    except Exception as exc:  # noqa: BLE001
        return [f"deck could not be loaded: {exc}"]
    present = {child.tag for child in root if isinstance(child.tag, str)}
    missing = [s for s in REQUIRED_SECTIONS if s not in present]
    return [f"required top-level sections absent: {', '.join(missing)}"] if missing else []


CHECKS = {"parse": check_parse, "required_sections": check_required_sections}


def run_checks(adapter: Adapter, workspace: Path) -> list[str]:
    problems: list[str] = []
    for name in adapter.stop_policy.checks:
        problems.extend(CHECKS[name](workspace))
    return problems


def retry_prompt(adapter: Adapter, problems: list[str]) -> str:
    """What the agent is told when its deck did not pass. Shape is searchable."""
    shape = adapter.stop_policy.feedback_shape
    if shape == "none":
        return "Your deck is not finished. Fix it in /workspace/inputs/."
    if shape == "minimal":
        return ("Your deck in /workspace/inputs/ did not pass the output check. "
                "Fix it and write the corrected deck to the same directory.")
    return ("Your deck in /workspace/inputs/ did not pass the output check:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\nFix these and write the corrected deck to the same directory. "
              "Do not start over; edit what is there.")


# -- transcript accounting --------------------------------------------------

#: List prices for the default model, $/million tokens.
#:
#: **This estimate is wrong, and it is here to be wrong visibly.** One rollout of
#: ``TutorialPoroelasticity`` on this kit, 2026-09-12, priced three ways:
#:
#: =========================================  =========  ================
#: source                                     says       off by
#: =========================================  =========  ================
#: token arithmetic below                     $0.028     4.7x too low
#: the CLI's own ``result.total_cost_usd``    $3.974     30x too high
#: **account balance before/after**           **$0.134**  the actual bill
#: =========================================  =========  ================
#:
#: Both errors have causes, and neither is a bug you can patch around. The token
#: math sees fresh ``input_tokens`` per turn while the gateway bills the whole
#: resent conversation, and this provider reported no cache-read tokens at all,
#: so the cached bulk of the run is invisible. The CLI's own figure prices the
#: tokens at the model list price it *assumes*, which is not what the gateway
#: charges for a third-party model. The research repo hit the same wall from the
#: other direction: its estimate over-predicted 2.25x on a different provider.
#:
#: The lesson is not "use a better multiplier". It is that **a transcript cannot
#: price a run**, in either direction, and a budget that trusts one is not a
#: budget. ``qualkit.ledger.BudgetGuard`` reads the account balance instead.
#: Use the ``~$`` in progress output to watch a run move, never to report a cost.
PRICE_PER_MTOK = (float(os.environ.get("QUAL_PRICE_IN", "0.075")),
                  float(os.environ.get("QUAL_PRICE_OUT", "0.25")))

#: Billed dollars per rollout, measured against account deltas rather than
#: transcripts. $0.134 on the research harness (n=6, 2026-09-08) and $0.134 on
#: this kit (n=1, 2026-09-12) -- the curated corpus halved wall-clock (1453s ->
#: 687s) without moving the bill. Used to size a run before you start it.
MEASURED_USD_PER_ROLLOUT = 0.134


def parse_events(events_path: Path, transcript: str = "claude-stream-json") -> Cost:
    """Tool calls, turns and token usage from a harness transcript.

    Tool calls are counted from ``tool_use`` blocks rather than read off a
    summary field: efficiency is a constraint here, and a number nobody
    recomputes drifts.

    An unrecognised or unparseable transcript returns a zero ``Cost`` rather
    than raising. That loses the *progress estimate* for that rollout and
    nothing else: the score comes from the workspace and the spend limit comes
    from the account balance, so neither depends on this parse. If you add a
    harness and its numbers come back zero, this is the function to extend.
    """
    if not events_path.is_file():
        return Cost()
    text = events_path.read_text(errors="replace")
    if transcript == "acpx-json":
        return _cost_from_acpx(text)
    return _cost_from_stream_json(text)


def _cost_from_stream_json(text: str) -> Cost:
    turns = tool_calls = fresh_in = out = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") or {}
        usage = message.get("usage") or event.get("usage") or {}
        if usage:
            fresh_in += int(usage.get("input_tokens", 0) or 0)
            out += int(usage.get("output_tokens", 0) or 0)
        # The harness reports its own turn count on the final `result` record.
        # Prefer it. Counting records that carry a `usage` block instead gives
        # a number ~2x larger -- it includes tool results and sub-steps -- and
        # quoting that as "turns" is how this project once reported a 3-5x gap
        # against a published baseline that turned out to be 2.4x.
        if event.get("type") == "result" and "num_turns" in event:
            turns = int(event["num_turns"])
        content = message.get("content")
        if isinstance(content, list):
            tool_calls += sum(1 for block in content
                              if isinstance(block, dict) and block.get("type") == "tool_use")
    return _cost(fresh_in, out, tool_calls, turns)


def _cost_from_acpx(text: str) -> Cost:
    """Tolerant walk over acpx's JSON output.

    Deliberately structural rather than schema-aware: acpx emits whatever the
    underlying agent reports, so this looks for usage-shaped and tool-call-shaped
    objects anywhere in the tree instead of assuming a layout that would break on
    the next agent. Unverified -- check it against a real transcript before you
    quote a number from it.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # acpx may also emit one JSON object per line.
        objects = []
        for line in text.splitlines():
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        data = objects
    fresh_in = out = tool_calls = turns = 0

    def walk(node) -> None:
        nonlocal fresh_in, out, tool_calls, turns
        if isinstance(node, dict):
            if "input_tokens" in node or "prompt_tokens" in node:
                turns += 1
                fresh_in += int(node.get("input_tokens") or node.get("prompt_tokens") or 0)
                out += int(node.get("output_tokens") or node.get("completion_tokens") or 0)
            kind = node.get("type") or node.get("kind")
            if kind in ("tool_use", "tool_call", "toolCall"):
                tool_calls += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return _cost(fresh_in, out, tool_calls, turns)


def _cost(fresh_in: int, out: int, tool_calls: int, turns: int) -> Cost:
    usd = (fresh_in * PRICE_PER_MTOK[0] + out * PRICE_PER_MTOK[1]) / 1e6
    return Cost(usd=usd, input_tokens=fresh_in, output_tokens=out,
                tool_calls=tool_calls, turns=turns)


# -- the rollout ------------------------------------------------------------

def run_rollout(adapter: Adapter, task_id: str, seed: int = 1, *,
                results_root: Path | None = None, model: str = MODEL,
                max_turns: int = MAX_TURNS, timeout_s: float = TIMEOUT_S,
                harness: str | None = None, keep_workspace: bool = True,
                verbose: bool = True) -> Rollout:
    """Run one task once, with one adapter, and score it. Never raises."""
    task = tasks.get(task_id)
    agent = agents.get(harness)
    results_root = Path(results_root or os.environ.get(
        "QUAL_RESULTS_ROOT", Path.cwd() / "runs"))
    workspace = results_root / f"{adapter.cid}-s{seed}-{task_id}"
    if workspace.exists():
        shutil.rmtree(workspace)
    prepare_workspace(workspace)
    corpus_dir = corpus.build(task_id).root

    events_path = workspace / "events.jsonl"
    prompt = build_task_prompt(task_id)
    total = Cost()
    started = time.time()
    attempts = 0
    error: str | None = None

    for attempt in range(adapter.stop_policy.max_retries + 1):
        attempts += 1
        spec = build_spec(adapter, task_id, workspace, corpus_dir, prompt,
                          model=model, max_turns=max_turns, harness=agent.name)
        argv = spec.render()
        if verbose:
            print(f"    [{task_id} s{seed}] attempt {attempts} starting", flush=True)
        attempt_events = workspace / f"events.attempt{attempt}.jsonl"
        try:
            with attempt_events.open("w") as sink:
                proc = subprocess.run(argv, env=child_env(), stdout=sink,
                                      stderr=subprocess.PIPE, text=True,
                                      timeout=timeout_s)
            if proc.returncode != 0:
                error = f"container exited {proc.returncode}: {proc.stderr.strip()[-500:]}"
        except subprocess.TimeoutExpired:
            error = f"timed out after {timeout_s:.0f}s"
        except FileNotFoundError as exc:
            error = f"cannot launch container: {exc}"
            break
        total = total + parse_events(attempt_events, agent.transcript)
        with events_path.open("a") as sink:
            sink.write(attempt_events.read_text(errors="replace"))

        problems = run_checks(adapter, workspace)
        if not problems or attempt == adapter.stop_policy.max_retries:
            break
        prompt = retry_prompt(adapter, problems)

    total = replace(total, wall_seconds=time.time() - started)
    score = score_workspace(workspace / "inputs", task.ground_truth_dir, task_id)
    if score.failed and error:
        score = Score(task_id, 0.0, score.status, {**score.detail, "harness": error})
    if verbose:
        print(f"    [{task_id} s{seed}] {score.value:.4f} {score.status} "
              f"({total.tool_calls} tool calls, {total.wall_seconds:.0f}s, "
              f"~${total.usd:.3f})", flush=True)

    if not keep_workspace:
        shutil.rmtree(workspace, ignore_errors=True)
    return Rollout(task=task_id, adapter_id=adapter.cid, seed=seed, score=score,
                   cost=total, workspace=str(workspace) if keep_workspace else None,
                   attempts=attempts, error=error)
