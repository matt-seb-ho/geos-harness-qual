"""``qual`` -- everything you can do without writing code.

    qual doctor                     can this machine run a rollout?
    qual tasks                      the seven tasks, families, splits
    qual harnesses                  which coding agents this image can run
    qual corpus [--force]           build the per-task read-only GEOS trees
    qual audit                      prove no task's corpus leaks its answer
    qual score <workspace> <task>   score a finished workspace, free
    qual mock                       run the seed adapter on the mock, free
    qual baseline [--seeds 2]       measure the seed on the train split (COSTS MONEY)
    qual run <task> [--seed 1]      one real rollout, for debugging (COSTS MONEY)
    qual evolve [--mock]            run your loop in evolve/loop.py
    qual report <ledger.jsonl>      re-derive every number from the ledger, free

Anything that spends money says so before it starts and asks for confirmation
unless ``--yes`` is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from qualkit import corpus, tasks
from qualkit.adapter import Adapter, load_seed
from qualkit.evaluate import Evaluator, compare
from qualkit.ledger import BudgetGuard, Ledger
from qualkit.rollout import MEASURED_USD_PER_ROLLOUT
from qualkit.scoring import diagnose, score_workspace

DEFAULT_LEDGER = Path("runs/ledger.jsonl")
DEFAULT_CEILING = float(os.environ.get("QUAL_BUDGET_USD", "15"))


def _load_env(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _harness_runner(harness: str | None):
    """A real runner bound to one harness, so it matches ``run_rollout``'s signature."""
    import functools

    from qualkit import agents
    from qualkit.rollout import run_rollout

    agents.get(harness)  # fail now, with a list of names, not mid-search
    return functools.partial(run_rollout, harness=harness)


def _confirm(message: str, yes: bool) -> bool:
    if yes:
        return True
    reply = input(f"{message} [y/N] ").strip().lower()
    return reply in {"y", "yes"}


# -- commands ---------------------------------------------------------------

def cmd_doctor(args) -> int:
    from qualkit.container import preflight
    problems = preflight()
    try:
        source = corpus.GEOS_SOURCE_DIR
        if not source.is_dir():
            problems.append(f"GEOS source tree not found at {source} (set GEOS_SOURCE_DIR)")
    except Exception as exc:  # noqa: BLE001
        problems.append(str(exc))
    for task in tasks.load_tasks():
        if not task.instructions_path.is_file():
            problems.append(f"missing instructions for {task.task_id}")
        if not any(task.ground_truth_dir.glob("*.xml")):
            problems.append(f"missing ground truth for {task.task_id}")
    if problems:
        print("this machine cannot run a real rollout yet:")
        for p in problems:
            print(f"  - {p}")
        print("\nthe mock runner works regardless: `qual mock`")
        return 1
    print("ready: container, corpus source, tasks and ground truth all present")
    return 0


def cmd_harnesses(args) -> int:
    from qualkit import agents
    print("the base policy. Pick one and keep it fixed for the whole experiment.\n")
    for name, ok, why in agents.probe():
        mark = "ok " if ok else "-- "
        print(f"{mark} {name:<16} {why}")
        notes = agents.HARNESSES[name].notes
        if notes:
            print(f"{'':20}{notes}")
    print(f"\ncurrent: {agents.DEFAULT_HARNESS}  (set QUAL_HARNESS to change it)")
    return 0


def cmd_tasks(args) -> int:
    print(f"{'split':6} {'family':12} {'2026-09-11 seed':16} task")
    for task in tasks.load_tasks():
        scores = "/".join(f"{v:.2f}" for v in task.seed_score_2026_09_11)
        print(f"{task.split:6} {task.family:12} {scores:16} {task.task_id}")
        if task.note:
            print(f"{'':36}{task.note}")
    return 0


def cmd_corpus(args) -> int:
    for report in corpus.build_all(force=args.force):
        print(report.render())
    return 0


def cmd_audit(args) -> int:
    failures = 0
    for task in tasks.load_tasks():
        problems = corpus.audit(task.task_id)
        status = "ok" if not problems else f"{len(problems)} PROBLEMS"
        print(f"{task.task_id:<48} {status}")
        for problem in problems:
            print(f"    {problem}")
        failures += len(problems)
    print("\nclean" if not failures else f"\n{failures} leaks -- do not trust any score until these are fixed")
    return 0 if not failures else 1


def cmd_score(args) -> int:
    score = score_workspace(Path(args.workspace), tasks.get(args.task).ground_truth_dir,
                            args.task)
    print(f"{score.value:.4f}  {score.status}")
    print(diagnose(score))
    if args.json:
        print(json.dumps(score.to_json(), indent=2))
    return 0


def cmd_mock(args) -> int:
    from qualkit import mock
    evaluator = Evaluator(ledger=Ledger(Path(args.ledger)), runner=mock.run_rollout,
                          seeds=tuple(range(1, args.seeds + 1)),
                          results_root=Path("runs-mock"))
    result = evaluator.evaluate(load_seed(), [t.task_id for t in tasks.load_tasks(args.split)])
    print(result.render())
    return 0


def cmd_run(args) -> int:
    from qualkit.rollout import run_rollout
    if not _confirm(f"run one real rollout on {args.task} "
                    f"(~${MEASURED_USD_PER_ROLLOUT:.2f}, ~12 min)?", args.yes):
        return 1
    result = run_rollout(load_seed(), args.task, args.seed, harness=args.harness)
    print(json.dumps(result.to_json(), indent=2)[:2000])
    return 0


def cmd_baseline(args) -> int:
    task_ids = [t.task_id for t in tasks.load_tasks(args.split)]
    n = len(task_ids) * args.seeds
    if not _confirm(f"measure the seed adapter on {len(task_ids)} {args.split} tasks "
                    f"x {args.seeds} seeds = {n} rollouts "
                    f"(~${MEASURED_USD_PER_ROLLOUT * n:.2f}, "
                    f"~{n * 12 / args.parallel:.0f} min)?", args.yes):
        return 1
    guard = BudgetGuard(ceiling_usd=args.budget)
    print(guard.render())
    ledger = Ledger(Path(args.ledger))
    evaluator = Evaluator(ledger=ledger, budget=guard,
                          seeds=tuple(range(1, args.seeds + 1)),
                          max_parallel=args.parallel,
                          runner=_harness_runner(args.harness))
    result = evaluator.evaluate(load_seed(), task_ids)
    print()
    print(result.render())
    print(guard.render())
    Path(args.ledger).with_suffix(".baseline.json").write_text(
        json.dumps(result.to_json(), indent=2) + "\n")
    return 0


def cmd_evolve(args) -> int:
    sys.path.insert(0, str(Path.cwd()))
    from evolve.loop import evolve  # noqa: PLC0415 -- the student's code
    from qualkit import mock

    task_ids = [t.task_id for t in tasks.load_tasks("train")]
    runner = mock.run_rollout if args.mock else _harness_runner(args.harness)
    if not args.mock and not _confirm(
            f"run your evolution loop for real, ceiling ${args.budget:.2f}?", args.yes):
        return 1
    guard = BudgetGuard(ceiling_usd=(0.0 if args.mock else args.budget))
    evaluator = Evaluator(ledger=Ledger(Path(args.ledger)), budget=None if args.mock else guard,
                          runner=runner, seeds=tuple(range(1, args.seeds + 1)),
                          max_parallel=args.parallel,
                          results_root=Path("runs-mock" if args.mock else "runs"))
    seed_adapter = load_seed()
    champion = evolve(seed_adapter, evaluator, task_ids)
    champion.save(Path(args.out))
    print(f"\nchampion written to {args.out}")

    before = evaluator.evaluate(seed_adapter, task_ids)
    after = evaluator.evaluate(champion, task_ids)
    print()
    print(compare(after, before).render())
    return 0


def cmd_report(args) -> int:
    from qualkit.evaluate import EvalResult
    from qualkit.ledger import _rollout_from_json
    rows = [json.loads(line) for line in Path(args.ledger).read_text().splitlines() if line.strip()]
    by_adapter: dict[str, list] = {}
    for row in rows:
        by_adapter.setdefault(row["adapter_id"], []).append(_rollout_from_json(row))
    for adapter_id, rollouts in by_adapter.items():
        print(EvalResult(adapter_id, tuple(rollouts)).render())
        print()
    estimated = sum(r.get("cost", {}).get("usd", 0.0) for r in rows)
    print(f"{len(rows)} rollouts, ~${estimated:.2f} estimated from transcripts "
          f"(not a billed figure -- see qualkit/ledger.py)")
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(prog="qual", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("tasks").set_defaults(func=cmd_tasks)
    sub.add_parser("harnesses").set_defaults(func=cmd_harnesses)

    p = sub.add_parser("corpus"); p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_corpus)

    sub.add_parser("audit").set_defaults(func=cmd_audit)

    p = sub.add_parser("score")
    p.add_argument("workspace"); p.add_argument("task")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("mock")
    p.add_argument("--seeds", type=int, default=2)
    p.add_argument("--split", default="train")
    p.add_argument("--ledger", default="runs-mock/ledger.jsonl")
    p.set_defaults(func=cmd_mock)

    p = sub.add_parser("run")
    p.add_argument("task"); p.add_argument("--seed", type=int, default=1)
    p.add_argument("--harness", default=None)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("baseline")
    p.add_argument("--seeds", type=int, default=2)
    p.add_argument("--split", default="train")
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--budget", type=float, default=DEFAULT_CEILING)
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    p.add_argument("--harness", default=None)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("evolve")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--seeds", type=int, default=1)
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--budget", type=float, default=DEFAULT_CEILING)
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    p.add_argument("--out", default="adapter/champion")
    p.add_argument("--harness", default=None)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_evolve)

    p = sub.add_parser("report"); p.add_argument("ledger")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
