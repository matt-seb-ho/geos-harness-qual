"""The seven tasks, their families, and the train/test split.

Why seven and not forty-six
---------------------------
The full GEOS pool is 46 tasks. A 40-task screen at two seeds was run on
2026-09-11 (80 rollouts, ~7 h wall-clock) and it says most of the pool is
useless for a search: twelve tasks score a flat 1.000 at both seeds -- no
headroom, so no candidate can beat the seed on them -- and several never
produce a deck at all. The seven here are the ones with measured headroom and
reproducible scores. ``seed_score_2026_09_11`` records what the *research*
harness got, at two seeds, so you can tell a real regression from noise.

Read those numbers as a prior, not a baseline. They came from a different
configuration (a 4,462-file corpus, a RAG server, a stop hook). Your first
paid run re-measures the seed on *this* setup, and that is the number your
result is compared against.

Why families, and why the split is by family
--------------------------------------------
These are not seven independent tasks. They are four physics families with
heavy structural sharing: two wellbore decks share mesh idioms, boundary
stanzas and solver blocks that neither shares with a fracture deck. Split them
at random and an adapter can learn a family from one member and score on its
sibling without generalising at all -- and the split reports that as held-out
performance.

So a family lives entirely in one split. Test scores are consequently *lower*
than a random split would give. That is the point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parents[2] / "tasks"

#: Families, and which split each one lives in. TEST is fracture + driver:
#: structurally the most distant from the wellbore/poroelastic bulk, so it is
#: the honest generalisation probe rather than the convenient one.
SPLIT_OF_FAMILY: dict[str, str] = {
    "wellbore": "train",
    "poroelastic": "train",
    "fracture": "test",
    "driver": "test",
}


@dataclass(frozen=True)
class Task:
    task_id: str
    family: str
    split: str
    #: Mean and per-seed TreeSim from the 2026-09-11 screen, research harness.
    seed_score_2026_09_11: tuple[float, ...]
    note: str = ""

    @property
    def dir(self) -> Path:
        return TASKS_DIR / self.task_id

    @property
    def instructions_path(self) -> Path:
        return self.dir / "instructions.txt"

    @property
    def ground_truth_dir(self) -> Path:
        return TASKS_DIR / "ground_truth" / self.task_id

    def instructions(self) -> str:
        return self.instructions_path.read_text()


TASKS: tuple[Task, ...] = (
    Task("ExampleVerticalPoroElastoPlasticWellbore", "wellbore", "train",
         (0.528, 0.524), "most reproducible mid-range task in the pool"),
    Task("AdvancedExamplePureThermalDiffusionWellbore", "wellbore", "train",
         (0.344, 0.354), "hardest of the seven; lots of headroom"),
    Task("TutorialPoroelasticity", "poroelastic", "train",
         (0.488, 0.417), "Terzaghi consolidation; multi-file deck"),
    Task("ExampleThermoporoelasticConsolidation", "poroelastic", "train",
         (0.871, 0.613), "high variance between seeds -- watch this one"),
    Task("ExamplesingleFracCompression", "fracture", "test",
         (0.778, 0.824), ""),
    Task("kgdToughnessDominated", "fracture", "test",
         (0.861, 0.869), ""),
    Task("triaxialDriverExample", "driver", "test",
         (0.903, 0.864), "no mesh; a constitutive-model driver deck"),
)

TASKS_BY_ID: dict[str, Task] = {t.task_id: t for t in TASKS}


def load_tasks(split: str | None = None) -> list[Task]:
    """All tasks, or one split of them. ``split`` is "train" or "test"."""
    if split is None:
        return list(TASKS)
    split = split.lower()
    if split not in {"train", "test"}:
        raise ValueError(f"split must be 'train' or 'test', not {split!r}")
    return [t for t in TASKS if t.split == split]


def get(task_id: str) -> Task:
    try:
        return TASKS_BY_ID[task_id]
    except KeyError:
        raise KeyError(
            f"unknown task {task_id!r}; known tasks: {', '.join(TASKS_BY_ID)}"
        ) from None


def manifest() -> dict:
    """The task table as plain JSON, for a run log or a write-up."""
    return {
        "tasks": [
            {"task_id": t.task_id, "family": t.family, "split": t.split,
             "seed_score_2026_09_11": list(t.seed_score_2026_09_11),
             "note": t.note}
            for t in TASKS
        ],
        "split_of_family": SPLIT_OF_FAMILY,
    }


def write_manifest(path: Path = TASKS_DIR / "manifest.json") -> Path:
    path.write_text(json.dumps(manifest(), indent=2) + "\n")
    return path
