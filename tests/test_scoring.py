"""The scorer, and the convention that failures are zeros."""
from __future__ import annotations

from pathlib import Path

import pytest

from qualkit import tasks
from qualkit.scoring import diagnose, score_workspace


@pytest.mark.parametrize("task", [t.task_id for t in tasks.load_tasks()])
def test_ground_truth_scores_one(task):
    """A deck scored against itself is 1.0. If this breaks, the metric moved."""
    gt = tasks.get(task).ground_truth_dir
    score = score_workspace(gt, gt, task)
    assert score.status == "success"
    assert score.value == pytest.approx(1.0)


def test_missing_workspace_is_a_zero_with_a_reason(tmp_path):
    score = score_workspace(tmp_path / "nope", tasks.get("kgdToughnessDominated").ground_truth_dir,
                            "kgdToughnessDominated")
    assert score.value == 0.0 and score.status == "no_workspace" and score.failed


def test_empty_workspace_is_a_zero_with_a_reason(tmp_path):
    (tmp_path / "inputs").mkdir()
    score = score_workspace(tmp_path / "inputs",
                            tasks.get("kgdToughnessDominated").ground_truth_dir,
                            "kgdToughnessDominated")
    assert score.value == 0.0 and score.status == "empty_workspace"


def test_unparseable_deck_is_a_zero_not_an_exception(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "deck.xml").write_text("<Problem><Mesh></Problem>")
    score = score_workspace(inputs, tasks.get("kgdToughnessDominated").ground_truth_dir,
                            "kgdToughnessDominated")
    assert score.value == 0.0 and score.failed


def test_partial_deck_scores_between_zero_and_one(tmp_path):
    import xml.etree.ElementTree as ET
    from qualkit.treesim import load_and_resolve_dir

    task = "kgdToughnessDominated"
    root = load_and_resolve_dir(tasks.get(task).ground_truth_dir)
    out = ET.Element(root.tag)
    for section in list(root)[:2]:
        out.append(section)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    ET.ElementTree(out).write(inputs / "deck.xml")
    score = score_workspace(inputs, tasks.get(task).ground_truth_dir, task)
    assert 0.0 < score.value < 1.0
    assert "weakest sections" in diagnose(score)
