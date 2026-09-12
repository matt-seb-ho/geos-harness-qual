"""Evaluate an adapter, and compare two of them honestly.

The comparison rules here are not decoration. They are the difference between a
result and a number.

**Paired, per task.** With four training tasks and two seeds you have eight
numbers, and the between-task variance dwarfs any adapter effect. Comparing two
adapters by their means is therefore close to meaningless. Compare them
task-by-task on the *same* tasks at the *same* seeds and look at the
differences. ``compare()`` does this and refuses when the two evaluations do not
cover the same cells.

**Failures are zeros and stay in.** A candidate that scores 0.9 on three tasks
and produces nothing on the fourth is not a 0.9 adapter. Dropping unscorable
rollouts is the single easiest way to manufacture a positive result, and this
project has watched it nearly happen: timed-out rollouts were once scored before
their workspace finished copying, producing fabricated zeros that then nominated
their own tasks as search anchors.

**Infrastructure failures are not model failures.** A container that could not
start, an API 429, a missing image -- those are excluded from the score and
counted separately, because averaging them into a candidate's score measures
your network, not your adapter. ``EvalResult.harness_errors`` is that count, and
a comparison with any harness errors in it should be rerun, not reported.

**A confidence interval, not a winner.** ``compare()`` returns a paired mean
difference with a bootstrap interval. At n=4 tasks that interval will usually
span zero. That is the honest answer at this sample size and saying so is worth
more than picking whichever adapter came out ahead.
"""

from __future__ import annotations

import random
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from qualkit import rollout as real_rollout
from qualkit import tasks as task_registry
from qualkit.adapter import Adapter
from qualkit.ledger import BudgetExceeded, BudgetGuard, Ledger
from qualkit.rollout import Cost, Rollout

#: Statuses that mean the harness failed, not the adapter. Never averaged in.
HARNESS_STATUSES = frozenset({"harness_error", "no_ground_truth", "scorer_error"})


@dataclass(frozen=True)
class EvalResult:
    adapter_id: str
    rollouts: tuple[Rollout, ...]
    origin: str = ""

    # -- the cells ---------------------------------------------------------
    @property
    def scored(self) -> tuple[Rollout, ...]:
        return tuple(r for r in self.rollouts if r.score.status not in HARNESS_STATUSES)

    @property
    def harness_errors(self) -> int:
        return len(self.rollouts) - len(self.scored)

    def by_task(self) -> dict[str, float]:
        """Mean score per task, over seeds. Seeds are repeats, not separate cells."""
        out: dict[str, list[float]] = {}
        for r in self.scored:
            out.setdefault(r.task, []).append(r.score.value)
        return {task: statistics.mean(values) for task, values in sorted(out.items())}

    # -- headline numbers ---------------------------------------------------
    @property
    def mean(self) -> float:
        per_task = self.by_task()
        return statistics.mean(per_task.values()) if per_task else 0.0

    @property
    def zero_rate(self) -> float:
        """Fraction of scored rollouts that produced nothing usable. The tail."""
        if not self.scored:
            return 1.0
        return sum(1 for r in self.scored if r.score.failed) / len(self.scored)

    @property
    def cost(self) -> Cost:
        total = Cost()
        for r in self.rollouts:
            total = total + r.cost
        return total

    def render(self) -> str:
        lines = [f"{self.adapter_id}  mean {self.mean:.4f}  "
                 f"zero-rate {self.zero_rate:.2f}  "
                 f"n={len(self.scored)} rollouts  ~${self.cost.usd:.2f}"]
        if self.harness_errors:
            lines.append(f"  !! {self.harness_errors} harness errors, excluded from the score")
        for task, value in self.by_task().items():
            lines.append(f"    {task:<48} {value:.4f}")
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {"adapter_id": self.adapter_id, "origin": self.origin,
                "mean": self.mean, "zero_rate": self.zero_rate,
                "by_task": self.by_task(), "harness_errors": self.harness_errors,
                "cost": self.cost.to_json(),
                "rollouts": [r.to_json() for r in self.rollouts]}


@dataclass
class Evaluator:
    """Runs rollouts, replays what the ledger already has, and stops at the ceiling.

    This is what your loop calls. It is deliberately the *only* thing in the
    starter kit that spends money, so there is exactly one place to look when
    you want to know why a run cost what it did.
    """

    ledger: Ledger
    budget: BudgetGuard | None = None
    #: Swap in ``qualkit.mock.run_rollout`` to develop for free.
    runner: Callable[..., Rollout] = real_rollout.run_rollout
    seeds: tuple[int, ...] = (1,)
    max_parallel: int = 3
    results_root: Path | None = None
    verbose: bool = True

    def evaluate(self, adapter: Adapter, tasks: Sequence[str] | None = None,
                 seeds: Sequence[int] | None = None) -> EvalResult:
        """Score one adapter on some tasks. Validates first; replays what it can."""
        adapter.validate()  # free rejection, before anything is spent
        task_ids = list(tasks) if tasks is not None else [
            t.task_id for t in task_registry.load_tasks("train")]
        seed_list = list(seeds if seeds is not None else self.seeds)

        pending: list[tuple[str, int]] = []
        done: list[Rollout] = []
        for task_id in task_ids:
            for seed in seed_list:
                cached = self.ledger.get(adapter.cid, task_id, seed)
                if cached is not None:
                    done.append(cached)
                else:
                    pending.append((task_id, seed))

        if self.verbose and done:
            print(f"  replayed {len(done)} rollout(s) from the ledger", flush=True)

        if pending and self.budget is not None:
            self.budget.check()

        if pending:
            with ThreadPoolExecutor(max_workers=self.max_parallel) as pool:
                futures = {
                    pool.submit(self._one, adapter, task_id, seed): (task_id, seed)
                    for task_id, seed in pending
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result is not None:
                        done.append(result)

        return EvalResult(adapter.cid, tuple(done), adapter.origin)

    def _one(self, adapter: Adapter, task_id: str, seed: int) -> Rollout | None:
        if self.budget is not None:
            try:
                self.budget.check()
            except BudgetExceeded as exc:
                if self.verbose:
                    print(f"    [{task_id} s{seed}] skipped: {exc}", flush=True)
                return None
        result = self.runner(adapter, task_id, seed,
                             results_root=self.results_root, verbose=self.verbose)
        self.ledger.append(result)
        if self.budget is not None:
            self.budget.record_estimate(result.cost)
        return result


# -- comparison --------------------------------------------------------------

@dataclass(frozen=True)
class Comparison:
    """A paired difference with an interval, plus everything needed to doubt it."""

    challenger: str
    incumbent: str
    per_task: dict[str, float]
    mean_diff: float
    ci: tuple[float, float]
    n_tasks: int
    note: str = ""

    @property
    def significant(self) -> bool:
        """Interval excludes zero. At n=4 this is rare and should be."""
        return self.ci[0] > 0 or self.ci[1] < 0

    def render(self) -> str:
        verdict = "excludes zero" if self.significant else "spans zero"
        lines = [f"{self.challenger} vs {self.incumbent}: "
                 f"paired mean {self.mean_diff:+.4f}, "
                 f"95% CI [{self.ci[0]:+.4f}, {self.ci[1]:+.4f}] ({verdict}), "
                 f"n={self.n_tasks} tasks"]
        for task, delta in sorted(self.per_task.items(), key=lambda kv: kv[1]):
            lines.append(f"    {task:<48} {delta:+.4f}")
        if self.note:
            lines.append(f"    note: {self.note}")
        return "\n".join(lines)


def compare(challenger: EvalResult, incumbent: EvalResult, *,
            resamples: int = 10_000, seed: int = 0) -> Comparison:
    """Paired per-task difference with a bootstrap CI. Refuses unmatched cells."""
    a, b = challenger.by_task(), incumbent.by_task()
    shared = sorted(set(a) & set(b))
    if not shared:
        raise ValueError("the two evaluations share no tasks; nothing to compare")
    missing = sorted((set(a) ^ set(b)))
    per_task = {task: a[task] - b[task] for task in shared}
    deltas = [per_task[t] for t in shared]
    mean_diff = statistics.mean(deltas)

    rng = random.Random(seed)
    means = sorted(
        statistics.mean([rng.choice(deltas) for _ in deltas])
        for _ in range(resamples)
    )
    lo = means[int(0.025 * resamples)]
    hi = means[min(int(0.975 * resamples), resamples - 1)]

    note = ""
    if missing:
        note = ("compared on shared tasks only; not in both evaluations: "
                + ", ".join(missing))
    if challenger.harness_errors or incumbent.harness_errors:
        note = (note + " | " if note else "") + (
            f"harness errors present ({challenger.harness_errors} vs "
            f"{incumbent.harness_errors}) -- rerun rather than report")
    if len(shared) < 4:
        note = (note + " | " if note else "") + (
            f"n={len(shared)} tasks: the interval is wide by construction")
    return Comparison(challenger.adapter_id, incumbent.adapter_id, per_task,
                      mean_diff, (lo, hi), len(shared), note)
