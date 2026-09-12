"""The mock runner is deterministic, free, and has a learnable gradient."""
from __future__ import annotations

import pytest

from qualkit import mock, tasks
from qualkit.config import load_seed

TASK = "kgdToughnessDominated"


def test_same_inputs_give_the_same_score(tmp_path):
    seed = load_seed()
    a = mock.run_rollout(seed, TASK, 1, results_root=tmp_path, verbose=False)
    b = mock.run_rollout(seed, TASK, 1, results_root=tmp_path, verbose=False)
    assert a.score.value == b.score.value


def test_different_seeds_give_different_scores(tmp_path):
    seed = load_seed()
    a = mock.run_rollout(seed, TASK, 1, results_root=tmp_path, verbose=False)
    b = mock.run_rollout(seed, TASK, 2, results_root=tmp_path, verbose=False)
    assert a.score.value != b.score.value, "a frozen agent is still a sampler"


def test_it_is_free(tmp_path):
    assert mock.run_rollout(load_seed(), TASK, 1, results_root=tmp_path,
                            verbose=False).cost.usd == 0.0


def test_naming_the_sections_helps(tmp_path):
    """The toy's gradient. It rewards vocabulary overlap; the real task does not.

    Note the mechanism: the text is in a bundled *file*, not the prompt. The mock
    counts every piece of text the configuration puts in front of the agent, so
    it cannot tell those apart. The real harness very much can.
    """
    seed = load_seed()
    richer = seed.with_changes(
        origin="test", files={"CHEATSHEET.md": " ".join(
            ["Solvers", "Mesh", "Geometry", "Events", "Constitutive",
             "ElementRegions", "NumericalMethods", "FieldSpecifications",
             "Outputs", "Tasks", "Functions"])})
    scores = [
        (sum(mock.run_rollout(a, t.task_id, s, results_root=tmp_path, verbose=False
                              ).score.value
             for t in tasks.load_tasks("train") for s in (1, 2)))
        for a in (seed, richer)
    ]
    assert scores[1] > scores[0] * 1.2
