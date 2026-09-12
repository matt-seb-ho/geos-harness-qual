# Qualification task

Implement a self-evolving harness loop and see whether it improves on a
hand-written starting harness at configuring GEOS simulations.

Pick a technique from your survey of self-improving agent methods, argue that it
applies here, implement it in `evolve/loop.py`, run it, and tell us what you
found. Everything except the loop is provided.

## The setup

A coding agent is given a description of a geomechanics simulation and has to
write a GEOS XML input deck. The model is fixed. Everything around the model is
not: the prompt, the tools, the files the agent can read, hooks, retries, the
turn limit. That bundle is a `HarnessConfig`, and it is what your loop edits.

The question is whether an automated loop can produce a better configuration
than the hand-written starting one, and whether the improvement holds on tasks
from physics families the loop never trained on.

Our own result is a null: +0.116 with a 95% CI of [−0.083, +0.314], and the one
task carrying most of that estimate failed to replicate. The literature predicts
a search with this few samples returns its starting point. You are not expected
to beat that. You are expected to run a real experiment and report what it
shows.

`README.md` explains the kit. Read it after this.

## What we are looking for

How you think about the problem and how you find things out, more than the
score.

- **Read the data.** Open a task description. Open the reference deck it is
  scored against. Run one rollout and read the whole transcript with `qual
  inspect` — what the agent searched for, what it opened, where the turns went,
  what it wrote.
- **Ground your decisions in what you saw**, not in what the method's paper says
  should happen. "I changed X because in run 3 the agent spent 19 turns looking
  for a file that was not there" is the kind of sentence we want to read.
- **Check what you believe.** When a number moves, find out why.

Depth beats breadth. Four rollouts you have read carefully teach you more than
forty you skimmed, and tell us more about you. A submission that runs one
careful comparison on two tasks, with a clear account of what the transcripts
showed, is a good submission.

Here is why, from building this kit. The seven tasks scored plausibly. Then one
transcript got read, and it contained:

```
cd /geos_lib && git show HEAD:inputFiles/.../spe11b_vti_source_base.xml
```

The agent had recovered a reference deck that the contamination filter had
removed, out of git history. Checking the rest of that run found 59 of 80
rollouts running git against the corpus and 29 tasks getting their own removed
deck back. That invalidates the benchmark, it was invisible in every score, and
it was found by reading one log. This kit does not have that bug
(`docs/CONTAMINATION.md`), but the method is the point.

## Steps

**1. Look at the material first.** Read a task description and the deck it is
scored against. Run `qual mock`, then one real rollout, and read the transcript
end to end. You will have opinions afterwards that you cannot have before.

**2. Pick a method and write one page.** What it is; what it assumes; whether
those assumptions hold here and how you know; which of the three outcomes below
you are trying to improve; what you predict will happen. **Send this to Matt
before you implement it.** It is the cheapest point at which a wrong plan can be
corrected, and it is part of what we are assessing.

**3. Implement `evolve/loop.py`.** Develop against the free mock runner (`qual
evolve --mock`) until the loop runs end to end and survives a failed rollout.
Do not spend money before that works. The mock is a toy and it cannot see most
of what you can change — read `qualkit/mock.py` so you know how it is fake.

**4. Run it, and read what comes back.**

```bash
qual baseline --seeds 2      # the starting configuration, on the train split
qual evolve --budget 3       # your loop
qual inspect runs/<...>      # then read some of them
```

**5. Evaluate the result once on the test split.** Three tasks, two physics
families the loop never saw. Once. If you evaluate twice, the second number is
not a held-out number and you have to say so.

**6. Write about a page.** Bullet points are fine. What method and why; at least
one concrete thing you learned from reading a transcript that changed what you
did; the paired numbers on train and then the test result; what you would bet on
and what would change your mind; what you left out; anything in the kit you
think is wrong.

## Three ways to be better

They do not move together, and the kit reports all three:

- **performance** — mean structural similarity to the reference deck;
- **reliability** — how often a rollout produces nothing usable at all;
- **efficiency** — wall-clock, tool calls and dollars per rollout.

Say which one you are trying to improve before you run, then report what
actually moved. Efficiency is a good target if you want to spend less: making
the harness cheaper is a real result and costs less to demonstrate.

## Model and cost

**Use `z-ai/glm-5.3-flash` and do not change it.** The premise is that you
improve the harness around a fixed model, so a comparison across two models
measures something else. The kit defaults to it.

You supply your own OpenRouter key; we cannot issue keys outside the group. A
rollout costs about $0.12 and takes 11–13 minutes. Set a spend limit on the key,
pass `--budget` to anything that spends, and keep the total small — a larger
bill is not a better submission. If cost is a problem, say so before you start.

## Rules

- **Never let the loop see ground truth.** Not the proposer, not the
  configuration, not indirectly. `qual audit` checks the container; the proposer
  is on you. Use `qualkit.scoring.diagnose()`, which is derived only from the
  generated deck. A contaminated run is not a weak result, it is no result.
- **Reading a comparable example is allowed and intended.** The tasks come from
  the GEOS example collection, so the corpus contains decks that resemble the
  answer without being it. The answer and its variants are removed; the rest is
  fair. `qual audit --deep` reports the best score obtainable by copying
  something readable: 0.43–0.78 across the seven tasks, and on three of the four
  training tasks that is higher than the starting harness scores. Using that is
  not cheating, but be able to say in your note whether your configuration
  learned to copy or learned something else.
- **Do not edit the scorer, the task prompts, the corpus builder, or the
  container image.** If you think one is wrong, say so in the note.
- **The simulator does not run.** There is no GEOS binary in the container.
  Schema validation is available — `xmllint` is installed and the schema is in
  the corpus — and nothing sets it up for you.
- **Evaluate on test once.**
- AI coding assistants are fine and expected. Understanding what you submitted
  is not optional; assume you will be asked to explain any line.

## If you have to cut

In this order, and say which you did:

1. **Fewer tasks and candidates, more reading.** Two tasks understood beat six
   skimmed. Cut this first.
2. **A shorter note, never a skipped one.**
3. **Report the train result and say the test evaluation is outstanding.**
4. **Drop the method and hand in the analysis.** If the loop never worked, say
   what you built, where it broke, and what the baseline and the transcripts
   show. That is a real result.

Do not cut the check-in, the paired comparison, or honesty about failures.

## Getting unstuck

Email Matt. Being stuck for two days on something that takes five minutes to
answer is worse than asking.
