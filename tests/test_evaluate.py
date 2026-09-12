"""The evaluation and comparison rules, exercised on the free mock runner."""
from __future__ import annotations

import pytest

from qualkit import mock, tasks
from qualkit.adapter import Adapter, load_seed
from qualkit.evaluate import EvalResult, Evaluator, compare
from qualkit.ledger import BudgetGuard, Ledger
from qualkit.rollout import Cost, Rollout
from qualkit.scoring import Score

TRAIN = [t.task_id for t in tasks.load_tasks("train")]


@pytest.fixture
def evaluator(tmp_path):
    return Evaluator(ledger=Ledger(tmp_path / "l.jsonl"), runner=mock.run_rollout,
                     seeds=(1, 2), results_root=tmp_path / "runs", verbose=False,
                     max_parallel=2)


def _result(values: dict[str, float], status: str = "success") -> EvalResult:
    rollouts = tuple(
        Rollout(task=task, adapter_id="cand_x", seed=1,
                score=Score(task, value, status), cost=Cost())
        for task, value in values.items()
    )
    return EvalResult("cand_x", rollouts)


def test_seeds_are_repeats_not_separate_cells(evaluator):
    result = evaluator.evaluate(load_seed(), TRAIN)
    assert len(result.rollouts) == len(TRAIN) * 2
    assert set(result.by_task()) == set(TRAIN), "two seeds, one cell per task"


def test_second_evaluation_is_free(evaluator):
    seed = load_seed()
    evaluator.evaluate(seed, TRAIN)
    before = len(evaluator.ledger.rows())
    evaluator.evaluate(seed, TRAIN)
    assert len(evaluator.ledger.rows()) == before, "an identical adapter must replay"


def test_over_budget_adapter_never_reaches_a_runner(tmp_path):
    calls = []

    def explode(*args, **kwargs):
        calls.append(args)
        raise AssertionError("should never run")

    evaluator = Evaluator(ledger=Ledger(tmp_path / "l.jsonl"), runner=explode,
                          verbose=False)
    with pytest.raises(Exception):
        evaluator.evaluate(Adapter(primer="word " * 5000), TRAIN)
    assert not calls


def test_failures_are_counted_not_dropped():
    result = _result({"a": 0.9, "b": 0.9, "c": 0.0}, status="success")
    failed = _result({"a": 0.9, "b": 0.9, "c": 0.0}, status="empty_workspace")
    assert result.mean == pytest.approx(0.6)
    assert failed.zero_rate == 1.0, "every rollout has a failure status here"


def test_harness_errors_are_excluded_from_the_score_and_counted():
    ok = Rollout("a", "c", 1, Score("a", 0.8, "success"), Cost())
    broken = Rollout("b", "c", 1, Score("b", 0.0, "harness_error"), Cost())
    result = EvalResult("c", (ok, broken))
    assert result.mean == pytest.approx(0.8), "a dead container is not a bad adapter"
    assert result.harness_errors == 1


def test_compare_is_paired_per_task():
    after = _result({"a": 0.6, "b": 0.5})
    before = _result({"a": 0.5, "b": 0.5})
    result = compare(after, before, resamples=2000)
    assert result.mean_diff == pytest.approx(0.05)
    assert result.per_task == {"a": pytest.approx(0.1), "b": pytest.approx(0.0)}


def test_compare_refuses_disjoint_evaluations():
    with pytest.raises(ValueError, match="share no tasks"):
        compare(_result({"a": 1.0}), _result({"b": 1.0}))


def test_compare_flags_partial_overlap_rather_than_silently_dropping():
    result = compare(_result({"a": 0.6, "b": 0.6}), _result({"a": 0.5}), resamples=500)
    assert result.n_tasks == 1 and "not in both" in result.note


def test_compare_flags_harness_errors():
    broken = EvalResult("c", (
        Rollout("a", "c", 1, Score("a", 0.9, "success"), Cost()),
        Rollout("b", "c", 1, Score("b", 0.0, "harness_error"), Cost()),
    ))
    result = compare(broken, _result({"a": 0.5}), resamples=500)
    assert "harness errors" in result.note


def test_budget_guard_blocks_before_spending(tmp_path):
    guard = BudgetGuard(ceiling_usd=0.0, baseline_usd=0.0, estimated_only=True)
    evaluator = Evaluator(ledger=Ledger(tmp_path / "l.jsonl"), runner=mock.run_rollout,
                          budget=guard, verbose=False, results_root=tmp_path)
    from qualkit.ledger import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        evaluator.evaluate(load_seed(), TRAIN)


def test_transcript_turn_count_prefers_the_harness_figure(tmp_path):
    """Counting records with a usage block gives ~2x the real turn count."""
    import json

    from qualkit.rollout import parse_events

    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in [
        {"type": "assistant", "message": {"usage": {"input_tokens": 10, "output_tokens": 1},
                                          "content": [{"type": "tool_use"}]}},
        {"type": "user", "message": {"usage": {"input_tokens": 10, "output_tokens": 0}}},
        {"type": "assistant", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
        {"type": "result", "num_turns": 2, "total_cost_usd": 99.0},
    ]))
    cost = parse_events(path)
    assert cost.turns == 2, "three usage blocks, two actual turns"
    assert cost.tool_calls == 1
    assert cost.usd < 0.01, "the harness's own total_cost_usd is not the bill"
