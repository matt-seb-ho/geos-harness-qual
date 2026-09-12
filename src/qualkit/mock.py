"""A free, offline, deterministic stand-in for the real rollout.

**This is not a simulation of the agent. It is a toy with a known answer.** It
exists so you can build and debug the whole evolution loop -- proposal,
evaluation, acceptance, archive, reporting -- without spending a cent or waiting
twenty minutes per rollout. Develop here; spend real money only once the loop
runs end to end.

How the toy works, stated plainly so you never mistake it for evidence: the mock
agent starts from the reference deck and *deletes* parts of it. How much it
deletes depends on (a) a deterministic pseudo-random draw keyed on
``(task, seed, adapter id)`` and (b) whether the adapter's text mentions the
names of the sections and element types the deck needs. An adapter that names
useful things loses less. So the mock has a real, learnable gradient -- and it
is a gradient over *vocabulary overlap*, which is emphatically not what the real
task rewards.

Two consequences you should plan for:

1. A loop that scores well on the mock has been debugged, not validated.
2. If your method's only mechanism is "put more GEOS words in the primer", the
   mock will love it and the real runs will not. That gap is itself worth
   reporting.
"""

from __future__ import annotations

import hashlib
import random
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from qualkit import tasks
from qualkit.adapter import Adapter
from qualkit.rollout import Cost, Rollout
from qualkit.scoring import score_workspace
from qualkit.treesim import load_and_resolve_dir

#: Fraction of the reference deck's subtrees the mock agent keeps when the
#: adapter says nothing useful at all. Chosen so the seed scores in the same
#: band the real seed does (~0.4-0.6 on the train split), which keeps the loop's acceptance
#: thresholds in a realistic range while you develop.
BASE_KEEP = 0.65

#: How much naming a section or element type in the adapter helps. Deliberately
#: generous: an effect you cannot see is useless for debugging.
MENTION_BONUS = 0.35


def _rng(adapter: Adapter, task_id: str, seed: int) -> random.Random:
    key = f"{adapter.cid}|{task_id}|{seed}".encode()
    return random.Random(int(hashlib.sha256(key).hexdigest()[:16], 16))


def _keep_probability(adapter: Adapter, tag: str) -> float:
    text = (adapter.primer + adapter.cheatsheet + adapter.constraints).lower()
    return min(1.0, BASE_KEEP + (MENTION_BONUS if tag.lower() in text else 0.0))


def run_rollout(adapter: Adapter, task_id: str, seed: int = 1, *,
                results_root: Path | None = None, verbose: bool = True,
                **_ignored) -> Rollout:
    """Same signature and return type as ``qualkit.rollout.run_rollout``. Free."""
    started = time.time()
    task = tasks.get(task_id)
    results_root = Path(results_root or Path.cwd() / "runs-mock")
    workspace = results_root / f"{adapter.cid}-s{seed}-{task_id}"
    if workspace.exists():
        shutil.rmtree(workspace)
    (workspace / "inputs").mkdir(parents=True)

    rng = _rng(adapter, task_id, seed)
    root = load_and_resolve_dir(task.ground_truth_dir)
    out = ET.Element(root.tag, dict(root.attrib))
    kept = dropped = 0
    for section in root:
        if not isinstance(section.tag, str):
            continue
        if rng.random() > _keep_probability(adapter, section.tag):
            dropped += 1
            continue
        copy = ET.SubElement(out, section.tag, dict(section.attrib))
        for child in section:
            if not isinstance(child.tag, str):
                continue
            if rng.random() > _keep_probability(adapter, child.tag):
                dropped += 1
                continue
            copy.append(child)
            kept += 1

    # The stop policy has a real effect in the mock too: each retry recovers one
    # dropped subtree, so a loop that searches over retries sees a gradient.
    for _ in range(adapter.stop_policy.max_retries):
        missing = [s for s in root if isinstance(s.tag, str)
                   and s.tag not in {c.tag for c in out}]
        if missing:
            out.append(missing[0])

    ET.ElementTree(out).write(workspace / "inputs" / "deck.xml")
    score = score_workspace(workspace / "inputs", task.ground_truth_dir, task_id)
    cost = Cost(usd=0.0, input_tokens=0, output_tokens=0,
                tool_calls=kept + dropped, turns=1 + adapter.stop_policy.max_retries,
                wall_seconds=time.time() - started)
    if verbose:
        print(f"    [mock {task_id} s{seed}] {score.value:.4f} {score.status}", flush=True)
    return Rollout(task=task_id, adapter_id=adapter.cid, seed=seed, score=score,
                   cost=cost, workspace=str(workspace), attempts=1)
