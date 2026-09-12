"""Build the read-only GEOS corpus each rollout sees, with the answers removed.

Two jobs, and they pull in opposite directions.

**Curation.** The research harness mounts a near-complete GEOS checkout:
4,462 files, 435 MB, including 1,539 C++ sources the agent can spend turns
reading. SIGA's published runs mounted a curated 231-file tree and used 2.4x
fewer tool calls per rollout on byte-identical task specs. Search cost scales
with the size of the territory, so this builds the small tree: example decks,
documentation, and the schema. No C++, no build system, no test harness.

**Contamination.** The agent must not be able to read the answer. For a task
that means three things, and blocking only the first is the usual mistake:

1. the task's own ground-truth decks;
2. their *variant siblings* -- given ``Foo_base.xml`` the GEOS tree usually
   also contains ``Foo_benchmark.xml`` and ``Foo_smoke.xml``, which share
   nearly every parameter;
3. the documentation page the task specification was written from.

So the corpus is built **per task**, and a task's corpus is missing that task's
answers. Hardlinks, not symlinks: a symlink can be followed out of the mount,
a hardlink to a file that was never linked simply does not exist in there.

This is enforcement, not convention. A capability granted at the mount level is
invisible from inside the loop, which is exactly how a full simulator binary sat
unnoticed in this project's container for five weeks.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from qualkit import tasks
from qualkit.treesim import GENERIC_STEMS, MIN_STEM_LENGTH, VARIANT_SUFFIXES

#: The full GEOS checkout the curated tree is cut from. Override with
#: ``GEOS_SOURCE_DIR``. On the lab server the default is already correct; off
#: it, clone GEOS (see README) and point this at the checkout.
GEOS_SOURCE_DIR = Path(os.environ.get(
    "GEOS_SOURCE_DIR", "/data/shared/geophysics_agent_data/data/GEOS"))

#: Maps a task id to the documentation page its specification was mined from.
#: Without this, the agent can read the prose the task was written from, which
#: is most of the way to the deck.
EXAMPLE_PAIRS = Path(os.environ.get(
    "GEOS_EXAMPLE_PAIRS",
    "/data/shared/geophysics_agent_data/data/eval/example_pairs.jsonl"))

#: Where per-task corpora are built. Must be on the same filesystem as
#: ``GEOS_SOURCE_DIR`` for hardlinks to work; falls back to copying if not.
CORPUS_ROOT = Path(os.environ.get("QUAL_CORPUS_ROOT", str(
    Path.home() / ".cache" / "geos-harness-qual" / "corpus")))

#: What goes in. Everything else stays out.
INCLUDE: tuple[tuple[str, str], ...] = (
    ("inputFiles", "*.xml"),                      # example decks
    ("src/docs/sphinx", "*.rst"),                 # narrative documentation
    ("src/coreComponents/schema", "schema.xsd"),  # the authoritative element list
)

#: Where each included tree lands inside the container's /geos_lib.
DEST_OF_SOURCE: dict[str, str] = {
    "inputFiles": "inputFiles",
    "src/docs/sphinx": "docs",
    "src/coreComponents/schema": "schema",
}


@dataclass(frozen=True)
class CorpusReport:
    task_id: str
    root: Path
    n_files: int
    n_bytes: int
    blocked_names: tuple[str, ...]
    blocked_docs: tuple[str, ...]
    hardlinked: bool

    def render(self) -> str:
        return (f"{self.task_id}: {self.n_files} files, {self.n_bytes / 1e6:.1f} MB at "
                f"{self.root} ({'hardlinks' if self.hardlinked else 'copies'}); "
                f"blocked {len(self.blocked_names)} decks, {len(self.blocked_docs)} doc pages")


def _stem_keys(filename: str) -> set[str]:
    """Variant stem keys for a deck filename. Same rule the research repo uses."""
    stem = Path(filename).stem.lower()
    keys = {stem}
    for suffix in VARIANT_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            keys.add(stem[: -len(suffix)])
    return {k for k in keys if k not in GENERIC_STEMS and len(k) >= MIN_STEM_LENGTH}


def blocked_deck_names(task_id: str, source: Path | None = None) -> set[str]:
    """Lowercased basenames of every deck that leaks this task's answer."""
    task = tasks.get(task_id)
    exact = {p.name.lower() for p in task.ground_truth_dir.glob("*.xml")}
    keys: set[str] = set()
    for name in exact:
        keys |= _stem_keys(name)
    blocked = set(exact)
    source = Path(source or GEOS_SOURCE_DIR)
    if keys and source.is_dir():
        for path in (source / "inputFiles").rglob("*.xml"):
            if _stem_keys(path.name) & keys:
                blocked.add(path.name.lower())
    return blocked


def blocked_doc_paths(task_id: str, pairs: Path | None = None) -> set[str]:
    """Documentation pages the task specification was mined from, if known."""
    pairs = Path(pairs or EXAMPLE_PAIRS)
    if not pairs.is_file():
        return set()
    label = f".. _{task_id}:"
    out: set[str] = set()
    for line in pairs.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (row.get("title") or "").strip() == label and row.get("rst_path"):
            out.add(str(row["rst_path"]))
    return out


def build(task_id: str, *, source: Path | None = None, root: Path | None = None,
          force: bool = False) -> CorpusReport:
    """Materialise the corpus for one task. Idempotent unless ``force``."""
    source = Path(source or GEOS_SOURCE_DIR)
    if not source.is_dir():
        raise FileNotFoundError(
            f"GEOS source tree not found at {source}. Set GEOS_SOURCE_DIR, or clone "
            f"GEOS (see README 'Setup') and point it at the checkout."
        )
    dest_root = Path(root or CORPUS_ROOT) / task_id
    stamp = dest_root / ".corpus.json"
    if stamp.is_file() and not force:
        cached = json.loads(stamp.read_text())
        return CorpusReport(
            task_id=cached["task_id"], root=dest_root,
            n_files=cached["n_files"], n_bytes=cached["n_bytes"],
            blocked_names=tuple(cached["blocked_names"]),
            blocked_docs=tuple(cached["blocked_docs"]),
            hardlinked=cached["hardlinked"],
        )
    if dest_root.exists():
        shutil.rmtree(dest_root)

    blocked_names = blocked_deck_names(task_id, source)
    blocked_docs = blocked_doc_paths(task_id)
    n_files = n_bytes = 0
    hardlinked = True

    for rel_src, pattern in INCLUDE:
        src_dir = source / rel_src
        if not src_dir.is_dir():
            continue
        dest_dir = dest_root / DEST_OF_SOURCE[rel_src]
        for path in sorted(src_dir.rglob(pattern)):
            if not path.is_file():
                continue
            if path.name.lower() in blocked_names:
                continue
            rel_to_source = str(path.relative_to(source))
            if rel_to_source in blocked_docs:
                continue
            target = dest_dir / path.relative_to(src_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(path, target)
            except OSError:
                shutil.copy2(path, target)
                hardlinked = False
            n_files += 1
            n_bytes += path.stat().st_size

    report = CorpusReport(task_id, dest_root, n_files, n_bytes,
                          tuple(sorted(blocked_names)), tuple(sorted(blocked_docs)),
                          hardlinked)
    stamp.write_text(json.dumps(
        {"task_id": task_id, "n_files": n_files, "n_bytes": n_bytes,
         "blocked_names": list(report.blocked_names),
         "blocked_docs": list(report.blocked_docs),
         "hardlinked": hardlinked}, indent=2) + "\n")
    return report


def build_all(*, force: bool = False) -> list[CorpusReport]:
    return [build(t.task_id, force=force) for t in tasks.load_tasks()]


def audit(task_id: str, root: Path | None = None) -> list[str]:
    """Every way this task's corpus still leaks. Empty list is the pass condition.

    Run this before you trust a score. It is cheap, and a contaminated run is
    not a bad result -- it is no result.
    """
    dest_root = Path(root or CORPUS_ROOT) / task_id
    problems: list[str] = []
    if not dest_root.is_dir():
        return [f"no corpus built at {dest_root}"]
    blocked = blocked_deck_names(task_id)
    for path in dest_root.rglob("*"):
        if path.is_symlink():
            problems.append(f"symlink in corpus (can be followed out): {path}")
        if path.is_file() and path.name.lower() in blocked:
            problems.append(f"blocked deck present: {path}")
    gt_texts = {p.read_text(errors="replace")
                for p in tasks.get(task_id).ground_truth_dir.glob("*.xml")}
    for path in dest_root.rglob("*.xml"):
        if path.read_text(errors="replace") in gt_texts:
            problems.append(f"byte-identical copy of a ground-truth deck: {path}")
    return problems
