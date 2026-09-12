"""A free, offline, deterministic stand-in for the real rollout.

**This is not a simulation of the agent. It is a toy with a known answer.** It
exists so you can build and debug the whole evolution loop -- proposal,
evaluation, acceptance, archive, reporting -- without spending a cent or waiting
twenty minutes per rollout. Develop here; spend real money only once the loop
runs end to end.

How the toy works, stated plainly so you never mistake it for evidence: the mock
agent starts from the reference deck and *deletes* parts of it. How much it
deletes depends on (a) a deterministic pseudo-random draw keyed on
``(task, seed, config id)`` and (b) whether any text the configuration puts in
front of the agent -- system prompt, bundled files, workspace files -- mentions
the names of the sections and element types the deck needs. A configuration that
names useful things loses less, and more retry attempts recover more. So the
mock has a real, learnable gradient -- and it is a gradient over *vocabulary
overlap and retries*, which is emphatically not what the real task rewards.

Three consequences you should plan for:

1. A loop that scores well on the mock has been debugged, not validated.
2. If your method's only mechanism is "put more GEOS words in the prompt", the
   mock will love it and the real runs will not. That gap is itself worth
   reporting.
3. The mock is blind to most of what a configuration can now change. Tools,
   hooks, MCP servers and turn caps do nothing here. If your method works
   through one of those, the mock cannot tell you anything and you should say
   so rather than reading its numbers as encouragement.
"""

from __future__ import annotations

import hashlib
import random
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from qualkit import tasks
from qualkit.config import HarnessConfig
from qualkit.rollout import Cost, Rollout
from qualkit.scoring import score_workspace
from qualkit.treesim import load_and_resolve_dir

#: Fraction of the reference deck's subtrees the mock agent keeps when the
#: configuration says nothing useful at all. Chosen so the seed scores in the same
#: band the real seed does (~0.4-0.6 on the train split), which keeps the loop's acceptance
#: thresholds in a realistic range while you develop.
BASE_KEEP = 0.65

#: How much naming a section or element type in the configuration helps. Deliberately
#: generous: an effect you cannot see is useless for debugging.
MENTION_BONUS = 0.35


def _visible_text(config: HarnessConfig) -> str:
    """Every piece of text the configuration puts in front of the agent."""
    return "\n".join([config.system_prompt, *config.files.values(),
                      *config.workspace_files.values()])


def _rng(config: HarnessConfig, task_id: str, seed: int) -> random.Random:
    key = f"{config.cid}|{task_id}|{seed}".encode()
    return random.Random(int(hashlib.sha256(key).hexdigest()[:16], 16))


def _keep_probability(config: HarnessConfig, tag: str) -> float:
    text = _visible_text(config).lower()
    return min(1.0, BASE_KEEP + (MENTION_BONUS if tag.lower() in text else 0.0))


def run_rollout(config: HarnessConfig, task_id: str, seed: int = 1, *,
                results_root: Path | None = None, verbose: bool = True,
                **_ignored) -> Rollout:
    """Same signature and return type as ``qualkit.rollout.run_rollout``. Free."""
    started = time.time()
    task = tasks.get(task_id)
    results_root = Path(results_root or Path.cwd() / "runs-mock")
    workspace = results_root / f"{config.cid}-s{seed}-{task_id}"
    if workspace.exists():
        shutil.rmtree(workspace)
    (workspace / "inputs").mkdir(parents=True)

    rng = _rng(config, task_id, seed)
    root = load_and_resolve_dir(task.ground_truth_dir)
    out = ET.Element(root.tag, dict(root.attrib))
    kept = dropped = 0
    for section in root:
        if not isinstance(section.tag, str):
            continue
        if rng.random() > _keep_probability(config, section.tag):
            dropped += 1
            continue
        copy = ET.SubElement(out, section.tag, dict(section.attrib))
        for child in section:
            if not isinstance(child.tag, str):
                continue
            if rng.random() > _keep_probability(config, child.tag):
                dropped += 1
                continue
            copy.append(child)
            kept += 1

    # The stop policy has a real effect in the mock too: each retry recovers one
    # dropped subtree, so a loop that searches over retries sees a gradient.
    for _ in range(config.retry.max_attempts - 1):
        missing = [s for s in root if isinstance(s.tag, str)
                   and s.tag not in {c.tag for c in out}]
        if missing:
            out.append(missing[0])

    ET.ElementTree(out).write(workspace / "inputs" / "deck.xml")
    score = score_workspace(workspace / "inputs", task.ground_truth_dir, task_id)
    cost = Cost(usd=0.0, input_tokens=0, output_tokens=0,
                tool_calls=kept + dropped, turns=1 + config.retry.max_attempts - 1,
                wall_seconds=time.time() - started)
    if verbose:
        print(f"    [mock {task_id} s{seed}] {score.value:.4f} {score.status}", flush=True)
    return Rollout(task=task_id, config_id=config.cid, seed=seed, score=score,
                   cost=cost, workspace=str(workspace), attempts=1)
