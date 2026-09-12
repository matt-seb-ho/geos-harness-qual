"""YOUR CODE GOES HERE. Everything else in this repository is fixed.

Implement ``evolve``: given the seed adapter and a way to score adapters, return
a better one. How you do that is the point of the exercise -- pick a method from
your survey, say why it should work *on this task*, and implement it.

The contract
------------
::

    evolve(seed: Adapter, evaluator: Evaluator, train_tasks: list[str]) -> Adapter

``seed``
    The starting adapter. Immutable. ``seed.with_changes(origin="why", ...)``
    returns a new one; ``qualkit.adapter`` documents the four components you may
    change and their token budgets.

``evaluator``
    ``evaluator.evaluate(adapter, tasks, seeds) -> EvalResult``. **This is the
    only thing here that spends money.** It replays anything already in the
    ledger for free, refuses to start a rollout once the budget ceiling is hit,
    and validates the adapter before spending anything.

``train_tasks``
    Four task ids. The three test tasks are not passed to you and you should not
    go looking for them: they are a different physics family, and the one number
    that matters at the end is how your champion does on tasks it never saw.

Return the adapter you want evaluated on the test split. Set ``origin`` on
everything you build -- an archive of anonymous candidates cannot be written up.

What a good submission does
---------------------------
Not "gets the highest score". A null result, clearly established, is a perfectly
good outcome here and is the outcome the published literature predicts for a
search this sample-starved. What we are reading for:

* **the method is a real choice.** It comes from your survey, you can say what
  it assumes, and you can say why those assumptions might hold or fail here.
* **each evaluation buys something.** A rollout is $0.134 billed and ~12
  minutes, so a $15 ceiling is about 110 of them *in total*, and a single
  comparison at four tasks and two seeds is eight. Spending them well is most of
  the difficulty. Reject cheaply and often: an adapter over its token budget, or
  a proposal identical to one you already evaluated, should cost you nothing.
* **the numbers survive contact.** Paired per-task comparisons, failures counted
  as zeros, harness errors excluded and reported. ``qualkit.evaluate`` does this
  for you if you let it.
* **it is legible.** Someone should be able to read your log and see which edit
  was accepted, why, and what happened next.

Suggested shape, if you want one
--------------------------------
This is not the only shape and you are not required to follow it:

1. Measure the seed on the train split. That is your incumbent.
2. Loop: read the diagnostics from the incumbent's rollouts, propose one bounded
   edit with a prediction attached ("this should help tasks X and Y"), evaluate
   it, accept or reject, record the decision and whether the prediction held.
3. Stop when the budget is spent or nothing is improving.
4. Return the incumbent.

Things that will waste your money
---------------------------------
* Evaluating a candidate on one task. The between-task variance is larger than
  any adapter effect; a single-task win is noise.
* Rebuilding the same adapter twice. Adapter ids are content hashes -- check the
  ledger first, or just call ``evaluator.evaluate`` and let it replay.
* Letting the primer grow every round. An earlier version of this system grew
  its primer 12x over three rounds and got worse. The token budgets are there to
  stop that; do not raise them without saying so.
* Developing against real rollouts. Use ``--mock`` until the loop runs end to
  end. See ``evolve/README.md``.
"""

from __future__ import annotations

from qualkit.adapter import Adapter
from qualkit.evaluate import Evaluator, compare
from qualkit.llm import LLM
from qualkit.scoring import diagnose


def evolve(seed: Adapter, evaluator: Evaluator, train_tasks: list[str]) -> Adapter:
    """Return an adapter you believe is better than ``seed``.

    The stub below is not a method. It measures the seed, makes one hand-written
    edit, and keeps whichever won. It exists so ``qual evolve --mock`` runs out
    of the box and you can see the plumbing work before you replace it.
    """
    incumbent = seed
    incumbent_result = evaluator.evaluate(incumbent, train_tasks)
    print(incumbent_result.render())

    # --- replace everything below this line -------------------------------
    feedback = "\n\n".join(
        f"{r.task}:\n{diagnose(r.score)}" for r in incumbent_result.rollouts
    )
    print(f"\n[stub] diagnostics available to a proposer:\n{feedback[:500]}\n")

    challenger = incumbent.with_changes(
        origin="stub: one hand-written edit, not a method",
        cheatsheet=(
            "A complete GEOS deck defines Solvers, Mesh, Geometry, Events, "
            "NumericalMethods, ElementRegions, Constitutive, FieldSpecifications "
            "and Outputs. Read a comparable example under /geos_lib/inputFiles/ "
            "before writing, and keep the same section order."
        ),
    )
    challenger_result = evaluator.evaluate(challenger, train_tasks)
    print(challenger_result.render())

    result = compare(challenger_result, incumbent_result)
    print("\n" + result.render())
    accepted = result.mean_diff > 0
    print(f"\n[stub] {'accepted' if accepted else 'rejected'} the one edit")
    return challenger if accepted else incumbent
