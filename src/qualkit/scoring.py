"""Score a rollout workspace. Failures are zeros with a reason, never absences.

The convention here is load-bearing and is the one thing you should not change.
Every way of not producing a scorable deck -- the agent wrote nothing, the XML
does not parse, the container died -- lands on ``value=0.0`` with a distinct
``status``. It is never ``None`` and the rollout is never dropped.

Why: the quantity this whole line of work is about is the *tail* -- how often a
run falls off a cliff. If unscorable runs are discarded, the mean rises and the
thing you were measuring disappears. A predecessor of this harness scored
``treesim = None`` for every task across three rounds and reported a round mean
of 0 without anyone noticing, because "no score" and "score of zero" were the
same shape.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qualkit import treesim

#: Statuses that mean "we never got a deck to look at". Track their rate.
FAILURE_STATUSES = frozenset(
    {"no_workspace", "empty_workspace", "no_ground_truth", "parse_error",
     "scorer_error", "harness_error", "timeout"}
)


@dataclass(frozen=True)
class Score:
    """TreeSim in [0, 1] plus why, if it is zero."""

    task: str
    value: float
    status: str = "success"
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.status in FAILURE_STATUSES

    def to_json(self) -> dict[str, Any]:
        return {"task": self.task, "value": self.value, "status": self.status,
                "detail": self.detail}


def score_workspace(inputs_dir: Path, ground_truth_dir: Path, task: str) -> Score:
    """Score the decks in ``inputs_dir`` against ``ground_truth_dir``.

    ``inputs_dir`` is the ``inputs/`` directory of a finished rollout workspace;
    ``ground_truth_dir`` is ``tasks/ground_truth/<task>/``.
    """
    inputs_dir, ground_truth_dir = Path(inputs_dir), Path(ground_truth_dir)
    if not inputs_dir.is_dir():
        return Score(task, 0.0, "no_workspace", {"expected": str(inputs_dir)})
    if not any(p.is_file() for p in inputs_dir.rglob("*")):
        return Score(task, 0.0, "empty_workspace", {"inputs_dir": str(inputs_dir)})
    if not ground_truth_dir.is_dir():
        return Score(task, 0.0, "no_ground_truth", {"expected": str(ground_truth_dir)})
    try:
        result = treesim.evaluate_directories(ground_truth_dir, inputs_dir)
    except FileNotFoundError as exc:
        return Score(task, 0.0, "empty_workspace", {"error": str(exc)})
    except (ET.ParseError, ValueError) as exc:
        return Score(task, 0.0, "parse_error", {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 -- a scorer crash is a zero, not a lost rollout
        return Score(task, 0.0, "scorer_error", {"error": f"{type(exc).__name__}: {exc}"})

    return Score(
        task=task,
        value=float(result["treesim"]),
        status="success",
        detail={
            "section_scores": result["section_scores"],
            "missing_element_types": result["missing_element_types"],
            "extra_element_types": result["extra_element_types"],
            "n_extra": result["n_extra"],
            "match_summary": result["match_summary"],
            "gt_sections": result["gt_sections"],
            "gen_sections": result["gen_sections"],
            "attr_mismatches": result["attr_mismatches"],
        },
    )


def diagnose(score: Score, k: int = 6) -> str:
    """A short, human- and LLM-readable account of where a deck lost points.

    This is the feedback signal your loop is allowed to consume. It is derived
    only from the *generated* deck and the section scores -- it never quotes
    ground-truth values, which would turn your configuration into a place to
    store the answer. See ``docs/CONTAMINATION.md``.
    """
    if score.failed:
        return f"{score.status}: {score.detail.get('error', '')}".strip().rstrip(":")
    sections = score.detail.get("section_scores", {})
    worst = sorted(sections.items(), key=lambda kv: kv[1])[:k]
    missing = score.detail.get("missing_element_types", [])[:k]
    extra = score.detail.get("extra_element_types", [])[:k]
    lines = [f"treesim {score.value:.3f}"]
    if worst:
        lines.append("weakest sections: "
                     + ", ".join(f"{name} {val:.2f}" for name, val in worst))
    if missing:
        lines.append("element types the reference has and this deck does not: "
                     + ", ".join(missing))
    if extra:
        lines.append("element types this deck invented: " + ", ".join(extra))
    return "\n".join(lines)
