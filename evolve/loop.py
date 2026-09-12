"""YOUR CODE GOES HERE. Everything else in this repository is fixed.

Implement ``evolve``: given a starting harness configuration and a way to score
one, return a better one. How you do that is the point of the exercise -- pick a
self-improvement technique from your survey, say why it should work *on this
problem*, and implement it.

The contract
------------
::

    evolve(seed: HarnessConfig, evaluator: Evaluator,
           train_tasks: list[str]) -> HarnessConfig

``seed``
    The starting configuration. Immutable;
    ``seed.with_changes(origin="why", ...)`` returns a new one.
    ``qualkit/config.py`` is the list of what you can change, which is
    everything about the harness except the model: the system prompt, the tool
    list, files mounted at ``/harness``, files dropped in the workspace, hooks,
    MCP servers, the turn cap, environment, a retry loop, and raw CLI flags.

``evaluator``
    ``evaluator.evaluate(config, tasks, seeds) -> EvalResult``. **The only thing
    here that spends money.** It replays anything already in the ledger for
    free, refuses to start a rollout once the budget ceiling is hit, and
    validates the configuration before spending anything.

``train_tasks``
    Four task ids. The three test tasks are not passed to you and you should not
    go looking for them: they are different physics families, and the number
    that matters at the end is how your champion does on tasks it never saw.

Return the configuration you want evaluated on the test split. Set ``origin`` on
everything you build.

Better in which direction?
--------------------------
Three, and they do not have to move together. ``EvalResult`` reports all three
and ``compare()`` gives you the change in all three:

* **performance** -- mean TreeSim against the reference deck;
* **reliability** -- how often a rollout produces nothing usable at all. This is
  the one the published work says matters most here, and the one a mean hides;
* **efficiency** -- wall-clock, tool calls, dollars per rollout.

A configuration that holds the score and halves the cost is a result. So is one
that trades 3% of score for a collapse in the failure rate. **Say which you were
optimising for, before you run it**, and then report what actually moved.

What a good submission does
---------------------------
Not "gets the highest score". A null result, clearly established, is a perfectly
good outcome here and is the outcome the published literature predicts for a
search this sample-starved. What we are reading for:

* **the method is a real choice.** It comes from your survey, you can say what
  it assumes, and you can say why those assumptions might hold or fail here.
* **each evaluation buys something.** A rollout is $0.134 and ~12 minutes, so
  the ceiling is about 110 of them and a single comparison at four tasks and two
  seeds is eight. Reject cheaply and often: a configuration identical to one you
  already scored, or one the harness cannot honour
  (``agents.get(...).unsupported(config)``), should cost you nothing.
* **the numbers survive contact.** Paired per-task comparisons, failures counted
  as zeros, infrastructure errors excluded and reported. ``qualkit.evaluate``
  does this for you if you let it.
* **it is legible.** Someone should be able to read your log and see which
  change was accepted, why, and what happened next.

Some of what is reachable, to argue with
----------------------------------------
Not a menu to work through -- a sense of the space, so "improve the harness"
does not read as "improve the prompt":

* **Prompt.** ``system_prompt``, and workspace files the agent reads on its own.
* **Procedural memory.** A cheatsheet in ``files`` that the prompt points at, so
  it costs context only when read. Does it beat the same text always-on?
* **Tools.** Drop tools it wastes turns on; add one via ``mcp_servers``. The
  image has ``xmllint`` and the corpus has the schema, so
  ``xmllint --noout --schema /geos_lib/schema/schema.xsd inputs/deck.xml`` works
  today -- and on a rejected deck it prints the *complete list of elements GEOS
  will accept there*, which is the richest feedback available in this setup.
  Nothing wires it up for you.
* **Hooks.** ``settings["hooks"]`` with a ``Stop`` hook script shipped in
  ``files``: check the deck and refuse to let the turn end. Claude Code only.
* **Retries.** ``config.retry``: the same idea host-side, works on any harness,
  costs a fresh context each attempt. Which is cheaper? Nobody here knows.
* **Context and turns.** ``max_turns``. Our cap of 60 is inherited, not derived.
* **Retrieval.** The corpus is 842 files and 4 MB, and the tasks come from that
  same example collection, so the deck that most resembles the answer is in
  there (the answer itself and its variants are not). ``qual audit --deep``
  measures what pure copying gets: 0.43-0.78, and *above the seed agent* on
  three of the four training tasks. A configuration that reliably finds and
  adapts the nearest example is a legitimate and probably cheap win.

Things that will waste your money
---------------------------------
* Evaluating a candidate on one task. Between-task variance is larger than any
  configuration effect; a single-task win is noise.
* Re-scoring something you already scored. Config ids are content hashes -- just
  call ``evaluator.evaluate`` and let it replay.
* Developing against real rollouts. Use ``--mock`` until the loop runs end to
  end. Note what the mock cannot see, though: it is blind to tools, hooks, MCP
  and turn caps, so a method working through those needs a different offline
  test, or none.
* Changing several things at once and then not being able to say which worked.
"""

from __future__ import annotations

from qualkit.config import HarnessConfig, diff
from qualkit.evaluate import Evaluator, compare
from qualkit.llm import LLM
from qualkit.scoring import diagnose


def evolve(seed: HarnessConfig, evaluator: Evaluator,
           train_tasks: list[str]) -> HarnessConfig:
    """Return a configuration you believe is better than ``seed``.

    The stub below is not a method. It measures the seed, makes one hand-written
    change, and keeps whichever won. It exists so ``qual evolve --mock`` runs out
    of the box and you can watch the plumbing work before you replace it.
    """
    incumbent = seed
    incumbent_result = evaluator.evaluate(incumbent, train_tasks)
    print(incumbent_result.render())

    # --- replace everything below this line -------------------------------
    feedback = "\n\n".join(
        f"{r.task}:\n{diagnose(r.score)}" for r in incumbent_result.rollouts
    )
    print(f"\n[stub] diagnostics a proposer could read:\n{feedback[:500]}\n")

    challenger = incumbent.with_changes(
        origin="stub: one hand-written change, not a method",
        files={
            "CHEATSHEET.md": (
                "A complete GEOS deck defines Solvers, Mesh, Geometry, Events, "
                "NumericalMethods, ElementRegions, Constitutive, "
                "FieldSpecifications and Outputs.\n"
                "Find a comparable example under /geos_lib/inputFiles/ and keep "
                "its section order.\n"
            )
        },
        system_prompt=incumbent.system_prompt
        + "\n- Read `/harness/CHEATSHEET.md` before writing anything.\n",
    )
    print(f"[stub] change: {'; '.join(diff(incumbent, challenger))}")

    challenger_result = evaluator.evaluate(challenger, train_tasks)
    print(challenger_result.render())

    verdict = compare(challenger_result, incumbent_result)
    print("\n" + verdict.render())
    accepted = verdict.mean_diff > 0
    print(f"\n[stub] {'accepted' if accepted else 'rejected'} the one change")
    return challenger if accepted else incumbent
