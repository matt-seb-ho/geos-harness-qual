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
from qualkit.treesim import expand_with_variants, variant_stem_keys

#: The full GEOS checkout the curated tree is cut from. Override with
#: ``GEOS_SOURCE_DIR``. On the lab server the default is already correct; off
#: it, clone GEOS (see README) and point this at the checkout.
GEOS_SOURCE_DIR = Path(os.environ.get(
    "GEOS_SOURCE_DIR", "/data/shared/geophysics_agent_data/data/GEOS"))

#: File extensions that leak a deck. ``.geos`` is in the list because a `.geos`
#: dependency file of a blocked deck carries the same content; the ``.xml``-only
#: assumption is the exact shape of a leak an earlier version of this pipeline
#: shipped.
LEAKY_EXTENSIONS: tuple[str, ...] = ("xml", "geos")

#: Matches the RST label in ``example_pairs.jsonl``'s ``title`` field, e.g.
#: ``.. _TutorialDeadOilEgg:``. Same expression the research harness uses --
#: an equality test against a reconstructed string is brittle to whitespace.
EXAMPLE_LABEL_RE = re.compile(r"\s*\.\.\s*_([^:]+):")

#: Maps a task id to the documentation page its specification was mined from.
#: Without this, the agent can read the prose the task was written from, which
#: is most of the way to the deck.
EXAMPLE_PAIRS = Path(os.environ.get(
    "GEOS_EXAMPLE_PAIRS",
    "/data/shared/geophysics_agent_data/data/eval/example_pairs.jsonl"))

#: A copy ceiling at or above this makes a task unusable: copying scores about
#: as well as solving, so a loop can win on it without authoring anything and
#: the task stops measuring what it claims to. Set from the one task this test
#: actually cut (0.856) and the next-highest survivor (0.776).
DEGENERATE_CEILING = 0.80

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


def blocked_deck_names(task_id: str, source: Path | None = None) -> set[str]:
    """Lowercased basenames of every file that leaks this task's answer.

    Three steps, and skipping the second is the usual mistake:

    1. the task's own ground-truth decks;
    2. **their variant siblings anywhere in the GEOS tree.** Given
       ``kgdToughnessDominated_base.xml`` the tree also ships ``_benchmark`` and
       ``_smoke`` variants of the same problem, sharing nearly every parameter.
       Block only the exact filename and the benchmark has stopped measuring
       authoring and started measuring file search.

    Stem normalisation is :func:`qualkit.treesim.variant_stem_keys`, vendored
    from the research harness, which is in turn the rule SIGA's runs used: strip
    the known variant suffixes transitively, then drop any key shorter than 10
    characters or in the generic set (``base``, ``benchmark``, ``input``,
    ``model``...) so ``base.xml`` does not blank the whole corpus.
    """
    task = tasks.get(task_id)
    exact = {
        path.name.lower()
        for path in task.ground_truth_dir.rglob("*")
        if path.is_file() and path.suffix.lower().lstrip(".") in LEAKY_EXTENSIONS
    }
    source = Path(source or GEOS_SOURCE_DIR)
    if not source.is_dir():
        return exact
    # Scanned over the whole source tree, not just inputFiles: a variant sibling
    # sitting in a test directory leaks exactly as much as one sitting next to
    # the original.
    return expand_with_variants(exact, source, LEAKY_EXTENSIONS)


def blocked_doc_paths(task_id: str, pairs: Path | None = None) -> set[str]:
    """Documentation pages the task specification was mined from, if known.

    The specification for each task was generated from a GEOS example page. That
    page is most of the way to the deck, and several specifications go further
    and name their reference files outright -- see ``docs/CONTAMINATION.md``.
    """
    pairs = Path(pairs or EXAMPLE_PAIRS)
    if not pairs.is_file():
        return set()
    out: set[str] = set()
    for line in pairs.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        match = EXAMPLE_LABEL_RE.match(str(row.get("title", "")))
        rst_path = str(row.get("rst_path", "")).strip()
        if match and rst_path and match.group(1) == task_id:
            out.add(rst_path)
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


# ---------------------------------------------------------------------------
# The deep audit: what could an agent get by copying?
# ---------------------------------------------------------------------------

def _long_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if len(line.strip()) > 25]


def _shared_runs(candidate: str, reference_ngrams: set[str], n: int = 3) -> int:
    lines = _long_lines(candidate)
    return sum(1 for i in range(len(lines) - n + 1)
               if "\n".join(lines[i:i + n]) in reference_ngrams)


def copy_ceiling(task_id: str, root: Path | None = None, *,
                 shortlist: int = 20, min_shared_runs: int = 3
                 ) -> tuple[float, str | None]:
    """Best TreeSim obtainable by copying something the agent can still read.

    The name-based masking removes a task's decks and their variant siblings --
    the policy SIGA's published runs used. What it deliberately does *not*
    remove is a different example that happens to share a skeleton, because
    learning from a comparable example is the signal this benchmark is built on.
    Where that line falls cannot be settled by a filename rule, so it is
    measured: score every readable deck against the reference and report the
    best one.

    **This is not a cheat detector.** Reading a comparable example is the
    intended workflow -- the seed prompt points at ``/geos_lib/inputFiles/`` on
    purpose -- and on a benchmark built from one family of examples the nearest
    sibling is always structurally close. What the number tells you is how much
    of a score is authoring rather than retrieval, and whether a task has gone
    *degenerate*: if copying scores about as well as solving, a loop can win
    without authoring anything and the task has stopped measuring what it
    claims to.

    Measured 2026-09-12, the seven tasks sit at 0.43-0.78 against a target of
    1.0, so retrieval leaves real headroom everywhere. On three of the four
    training tasks the ceiling is *above* the seed agent's score -- which is a
    finding rather than a flaw, and an obvious first thing for a loop to go
    after. One task was cut on this test:
    ``ExampleThermoporoelasticConsolidation``, ceiling 0.856 against a seed of
    0.87/0.61, where a plastic variant of the same problem that no suffix rule
    reduces to the answer's stem scored as well as doing the task.

    Returns ``(ceiling, filename)``. Minutes, not seconds; costs nothing.
    """
    import shutil
    import tempfile

    from qualkit.treesim import evaluate_directories

    task = tasks.get(task_id)
    dest_root = Path(root or CORPUS_ROOT) / task_id
    if not dest_root.is_dir():
        build(task_id, root=root)

    reference: set[str] = set()
    for deck in task.ground_truth_dir.glob("*.xml"):
        lines = _long_lines(deck.read_text(errors="replace"))
        reference |= {"\n".join(lines[i:i + 3]) for i in range(len(lines) - 2)}

    scored: list[tuple[int, Path]] = []
    for path in dest_root.rglob("*.xml"):
        runs = _shared_runs(path.read_text(errors="replace"), reference)
        if runs >= min_shared_runs:
            scored.append((runs, path))
    scored.sort(reverse=True, key=lambda pair: pair[0])

    best, culprit = 0.0, None
    for _, path in scored[:shortlist]:
        staging = Path(tempfile.mkdtemp())
        try:
            # Copy the whole directory, which is what an agent that found one
            # useful file would actually have access to.
            for sibling in path.parent.glob("*.xml"):
                shutil.copy(sibling, staging / sibling.name)
            value = float(evaluate_directories(task.ground_truth_dir, staging)["treesim"])
        except Exception:  # noqa: BLE001 -- an unscorable candidate is a 0, not a crash
            value = 0.0
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if value > best:
            best, culprit = value, path.name
    return best, culprit
