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
