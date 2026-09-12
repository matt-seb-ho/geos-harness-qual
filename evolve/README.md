# Your loop

Implement `evolve()` in `loop.py`. Nothing else here should need to change; if
you think it does, that is worth a sentence in your note.

## Read one rollout before you write any code

```bash
qual inspect runs/<config>-s1-<task>
```

It prints the tool mix, the call-by-call trace, which parts of the corpus the
agent opened, and the deck it produced with its weakest sections named. An hour
with that output will give you opinions about what to change that reading the
method's paper will not.

This is the highest-weighted item in the assessment. See `TASK.md`.

## Order to do things in

```bash
qual mock                 # the starting configuration on the mock runner. Free, ~10s.
qual evolve --mock        # your loop on the mock runner. Free. Iterate here.
qual doctor               # can this machine run a real rollout?
qual baseline --seeds 2   # the starting configuration, for real. 8 rollouts, ~$1.
qual inspect runs/<...>   # then read some of them
qual evolve --budget 3    # your loop, for real, with a ceiling
```

Everything before `qual doctor` is free and runs in seconds. Stay there until
your loop runs end to end, survives a failed rollout without crashing, and
writes a log you would be willing to show someone.

## The mock is a toy

`qualkit/mock.py` deletes parts of the reference deck, and deletes less when any
text the configuration puts in front of the agent mentions the names of the
things the deck needs. So it rewards vocabulary overlap and retries, and nothing
else.

It cannot see tools, hooks, MCP servers, turn limits or cost. If your method
works through one of those, the mock can tell you that your loop runs, which is
what it is for, and nothing about whether the method works. Say so rather than
treating its numbers as evidence.

## What the evaluator will not let you do

- run a configuration that breaks one of the five fixed constraints — rejected
  before any spend
- start a rollout after the budget ceiling is reached
- pay twice for the same `(config, task, seed)`; it replays from the ledger
- compare two evaluations that do not cover the same tasks

If one of these is in your way, the thing it is protecting is probably the thing
you were about to get wrong.

## Check what your agent supports

Not every agent supports every part of a configuration. ACP has no
settings-file hooks, for instance:

```python
from qualkit import agents
agents.get("acpx:codex").unsupported(my_config)   # -> ['settings (including hooks)']
```

`run_rollout` prints this too. A configuration whose mechanism is being ignored
will still produce a plausible score, which is the worst way to find out.
