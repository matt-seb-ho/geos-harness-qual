# Your loop

Implement `evolve()` in `loop.py`. Nothing else in this repository should need
to change; if you think it does, that is worth a paragraph in your write-up.

## The order to do things in

```bash
qual mock                 # the seed adapter on the toy runner. Free, ~10 seconds.
qual evolve --mock        # your loop on the toy runner. Free. Iterate here.
qual doctor               # can this machine run a real rollout?
qual baseline --seeds 2   # the seed on the train split, for real. 8 rollouts, ~$1.07
qual evolve --budget 9    # your loop, for real, with a hard ceiling
```

Everything before `qual doctor` is free and runs in seconds. Stay there until
your loop runs end to end, handles a failed rollout without crashing, and writes
a log you would be willing to show someone.

## The mock is a toy, and knowing how it is a toy matters

`qualkit/mock.py` deletes parts of the reference deck, and deletes less when the
adapter's text happens to contain the names of the things the deck needs. So the
mock rewards vocabulary overlap. The real task does not. A method that only
moves the mock's number is a method that has not been tested — and noticing that
in your write-up is worth more than a good mock score.

## What the evaluator will not let you do

- run an adapter that is over its token budget (rejected before any spend)
- start a rollout after the budget ceiling is reached
- pay twice for the same `(adapter, task, seed)` — it replays from the ledger
- compare two evaluations that do not cover the same tasks

These are guardrails, not obstacles. If one of them is in your way, the thing it
is protecting is probably the thing you were about to get wrong.
