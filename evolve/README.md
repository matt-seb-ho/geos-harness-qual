# Your loop

Implement `evolve()` in `loop.py`. Nothing else in this repository should need
to change; if you think it does, that is worth a paragraph in your write-up.

## Read one rollout before you write any code

```bash
qual inspect runs/<config>-s1-<task>
```

It prints the tool mix, the call-by-call trace, which parts of the corpus the
agent actually opened, and the deck it produced with its weakest sections named.
An hour with that output will give you opinions about what to change that no
amount of reading the method's paper will.

This is not advice, it is the highest-weighted thing in the assessment. See
`TASK.md`, "What we are actually looking for".

## The order to do things in

```bash
qual mock                 # the seed config on the toy runner. Free, ~10 seconds.
qual evolve --mock        # your loop on the toy runner. Free. Iterate here.
qual doctor               # can this machine run a real rollout?
qual baseline --seeds 2   # the seed on the train split, for real. 8 rollouts, ~$1.00
qual inspect runs/<...>   # and then read some of them
qual evolve --budget 3    # your loop, for real, with a hard ceiling
```

Everything before `qual doctor` is free and runs in seconds. Stay there until
your loop runs end to end, handles a failed rollout without crashing, and writes
a log you would be willing to show someone.

## The mock is a toy, and knowing how it is a toy matters

`qualkit/mock.py` deletes parts of the reference deck, and deletes less when any
text the configuration puts in front of the agent happens to contain the names
of the things the deck needs. So the mock rewards vocabulary overlap and
retries, and nothing else.

It is **blind** to tools, hooks, MCP servers, turn caps and cost. If your method
works through one of those, the mock can tell you that your loop runs — which is
what it is for — and nothing at all about whether the method works. Say so
rather than reading its numbers as encouragement.

## What the evaluator will not let you do

- run a configuration that breaks the validity floor — a forbidden tool, a
  model override — rejected before any spend
- start a rollout after the budget ceiling is reached
- pay twice for the same `(config, task, seed)` — it replays from the ledger
- compare two evaluations that do not cover the same tasks

These are guardrails, not obstacles. If one is in your way, the thing it is
protecting is probably the thing you were about to get wrong.

## Check what your harness can actually honour

Not every agent supports every part of a configuration — ACP has no
settings-file hooks, for instance. Rather than silently ignoring them:

```python
from qualkit import agents
agents.get("acpx:codex").unsupported(my_config)   # -> ['settings (including hooks)']
```

`run_rollout` prints this too. A configuration whose whole mechanism is being
ignored will still produce a plausible score, which is the worst way to find
out.
