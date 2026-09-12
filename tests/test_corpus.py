"""Contamination: the corpus must not contain the answer.

These are the tests to run before you believe a score. They skip when the GEOS
source tree is not reachable -- which means they skip on a laptop and run on the
machine that actually has the data, where they matter.
"""
from __future__ import annotations

import pytest

from qualkit import corpus, tasks

pytestmark = pytest.mark.skipif(
    not corpus.GEOS_SOURCE_DIR.is_dir(),
    reason=f"no GEOS source tree at {corpus.GEOS_SOURCE_DIR}",
)

TASK = "kgdToughnessDominated"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return corpus.build(TASK, root=tmp_path_factory.mktemp("corpus"))


def test_ground_truth_decks_are_absent(built):
    names = {p.name.lower() for p in built.root.rglob("*.xml")}
    for deck in tasks.get(TASK).ground_truth_dir.glob("*.xml"):
        assert deck.name.lower() not in names


def test_variant_siblings_are_blocked_too(built):
    """Blocking Foo_base.xml but leaving Foo_smoke.xml measures file search."""
    assert any(name.endswith("_smoke.xml") or name.endswith("_benchmark.xml")
               for name in built.blocked_names), built.blocked_names


def test_variant_stem_rule_matches_the_published_policy():
    """The rule SIGA's runs used: strip suffixes transitively, then filter.

    Pinned because it is the whole masking policy, and a plausible-looking
    "simplification" of it (one pass instead of a fixpoint, or dropping the
    length floor) quietly stops blocking things.
    """
    from qualkit.treesim import variant_stem_keys

    # transitive: _base_iterative reduces past _base as well
    assert "poroelastic_terzaghi" in variant_stem_keys("PoroElastic_Terzaghi_base_iterative.xml")
    assert "poroelastic_terzaghi" in variant_stem_keys("PoroElastic_Terzaghi_smoke.xml")
    # generic and short stems are dropped, or base.xml blanks the corpus
    assert variant_stem_keys("base.xml") == set()
    assert variant_stem_keys("smoke.xml") == set()
    assert variant_stem_keys("short.xml") == set()


def test_geos_dependency_files_are_leaky_too(built):
    """A .geos table file of a blocked deck carries the same content."""
    from qualkit import corpus
    assert "geos" in corpus.LEAKY_EXTENSIONS
    names = corpus.blocked_deck_names("triaxialDriverExample")
    assert any(name.endswith(".geos") for name in names), names


def test_specifications_that_name_their_own_answer_still_do_not_leak():
    """TutorialPoroelasticity's spec ends by naming its reference files."""
    from qualkit import corpus, tasks
    spec = tasks.get("TutorialPoroelasticity").instructions()
    assert "PoroElastic_Terzaghi_base_direct.xml" in spec, "spec no longer names it"
    assert "poroelastic_terzaghi_base_direct.xml" in corpus.blocked_deck_names(
        "TutorialPoroelasticity")


def test_the_source_documentation_page_is_blocked(built):
    assert built.blocked_docs, "the page the spec was mined from must not be readable"
    for doc in built.blocked_docs:
        assert not (built.root / "docs" / doc.split("sphinx/")[-1]).exists()


def test_no_symlinks(built):
    """A symlink can be followed out of a read-only mount. A hardlink cannot."""
    assert not [p for p in built.root.rglob("*") if p.is_symlink()]


def test_corpus_is_curated_not_complete(built):
    """The full tree is ~4,500 files and 435 MB; search cost scales with it."""
    assert built.n_files < 2000
    assert not list(built.root.rglob("*.cpp"))


def test_audit_passes_for_every_task(tmp_path_factory):
    root = tmp_path_factory.mktemp("audit")
    for task in tasks.load_tasks():
        corpus.build(task.task_id, root=root)
        assert corpus.audit(task.task_id, root=root) == []


def test_no_task_is_degenerate():
    """Copying a readable deck must not score as well as solving the task.

    Guards the recorded ceilings rather than recomputing them -- the real
    measurement is `qual audit --deep`, which takes minutes. If you change the
    task set, run it and update `tasks.py`.
    """
    for task in tasks.load_tasks():
        assert task.copy_ceiling < corpus.DEGENERATE_CEILING, (
            f"{task.task_id} ceiling {task.copy_ceiling}: a loop could win here "
            f"by plagiarising")


def test_no_version_control_history_in_the_corpus(built):
    """A blocked file recoverable from git history is not a blocked file.

    The research harness copies the whole GEOS checkout minus a block list,
    which copies `.git` too -- and in its 40-task screen, 29 tasks recovered
    their own blocked decks with `git show`. This kit assembles the tree from an
    include list, so there is nothing to recover from.
    """
    import subprocess

    for vcs in (".git", ".hg", ".svn"):
        assert not (built.root / vcs).exists(), vcs
    probe = subprocess.run(["git", "-C", str(built.root), "rev-parse", "--git-dir"],
                           capture_output=True, text=True)
    assert probe.returncode != 0, "the corpus resolves to a git repository"
