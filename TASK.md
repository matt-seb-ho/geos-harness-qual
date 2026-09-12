# Qualification task — self-improving harnesses for scientific simulation setup

## The short version

You have surveyed methods for self-improving / self-evolving agent harnesses.
Pick one, argue that it should work on *this* problem, implement it against the
starter kit in this repository, run it, and write up what happened.

**Time: about 20 hours of focused work, over ~3 weeks. Stop at 25.**
**Money: a $15 API ceiling. Expect to use about $8.**
**Deliverable: a pull request with your loop, your run log, and a 3–5 page report.**

The task is open-ended on purpose, so the time cap is real and it is part of the
exercise. Doing 20 hours of well-scoped work and saying clearly what you did not
get to is a *better* submission than 60 hours of sprawl. If you are at hour 20
with a loop that runs and a null result, you are done — write it up.

## The problem, in one paragraph

A frozen coding agent is given a natural-language specification of a
geomechanics simulation and must author a valid GEOS XML input deck. We do not
fine-tune the model. The only thing that changes is a small bundle of
always-visible text wrapped around the agent — a primer, a procedural
cheatsheet, negative constraints, and a stop policy. Call that bundle the
*adapter*. The research question is whether an automated loop can improve the
adapter better than the handwritten seed, and whether any improvement survives
on a physics family the loop never trained on.

The honest state of play: our own result so far is a **null**. Champion versus
seed was +0.116 with a 95% CI of [−0.083, +0.314], and the single task carrying
89% of that point estimate failed to replicate. The published literature
predicts a search this sample-starved returns its seed. **You are not expected
to beat that.** You are expected to run a real experiment and report what it
says.

## What to do

### 1. Choose, and justify (~3 hours, then check in)

Pick one technique from your survey. Write **one page** covering:

- what the method is, and what it assumes (a verifier? many rollouts? a
  reward model? gradient-free search over prompts? a memory that accumulates?);
- why those assumptions hold or fail here. The specifics that matter: ~17
  training rollouts is a *large* experiment at this budget; the score is
  structural similarity to a reference deck, not pass/fail; a rollout takes
  10–25 minutes; the gain we care about is the tail (runs that produce nothing)
  more than the mean;
- what you predict will happen, in a sentence, before you run anything.

**Send this to Matt before you implement.** It costs you an hour and it is the
cheapest point at which a wrong plan can be corrected. This check-in is not
optional and is part of what we are assessing.

### 2. Pick a base policy (15 minutes)

`qual harnesses` lists the coding agents this container can run: Claude Code's
own CLI, and codex / pi / openclaw / claude behind `acpx`. Only `claude` has
been run end to end here, and it is what our own numbers come from — take it
unless you have a reason not to, and say which you took.

Whichever you pick, keep it fixed. The harness is not a searchable component;
two candidates evaluated on different harnesses are not comparable.

### 3. Implement (~8 hours)

Fill in `evolve/loop.py`. Develop against the free mock runner (`qual evolve
--mock`) until the loop runs end to end, survives a failed rollout without
crashing, and writes a log you would be willing to show someone. Do not spend
real money before that is true.

The mock is a toy with a known answer — it rewards vocabulary overlap, which the
real task does not. Read `qualkit/mock.py` so you know exactly how it is fake.

### 4. Run it (~4 hours of your attention, more wall-clock)

```bash
qual baseline --seeds 2      # 8 rollouts, ~$1.07 — your incumbent
qual evolve --budget 9       # your loop, hard ceiling
```

Then evaluate your champion **once** on the test split — three tasks from two
physics families the loop never saw. Once. Not "once, and then again after a
tweak". If you evaluate on test twice, the second number is not a held-out
number and you have to say so.

### 5. Write it up (~4 hours)

3–5 pages. Structure it however you like, but it has to answer:

- what method, on what harness, and why it should have worked here;
- what you changed, and what the loop actually did — which edits were accepted,
  on what evidence;
- the numbers: seed versus champion on train, paired per task, with the
  interval; then the test result;
- **what you believe and what you do not.** Which parts of your result would you
  bet on, and what would change your mind? If it is a null, say so plainly and
  say what it would take to detect an effect this size;
- what you would do next with another $50 and another 20 hours;
- anything in the starter kit you think is wrong. Genuinely — the setup has
  known problems and finding another one is a good outcome.

## Budget, and how to not waste it

$15 ceiling. A rollout is **$0.134 billed** and about 12 minutes, measured — not
estimated, and not the $0.05 a transcript will tell you. So the ceiling is about
110 rollouts and every one of them should be answering a question:

| | rollouts | cost |
|---|---:|---:|
| seed baseline, 4 train tasks × 2 seeds | 8 | $1.07 |
| your search: ~8 candidates × 4 tasks × 1 seed | 32 | $4.29 |
| proposer LLM calls | — | ~$0.10 |
| re-running what breaks the first time | ~10 | $1.34 |
| champion and seed on 3 test tasks × 2 seeds | 12 | $1.61 |
| **total** | **~62** | **~$8.40** |

That is most of the ceiling, which is the point: at this price the budget is a
real constraint and deciding what *not* to evaluate is a large part of the
exercise. Cheap ways to buy room, in the order we would use them: evaluate
candidates at one seed and only re-run the finalists at two; kill a candidate
after two tasks if both are down; never re-evaluate an adapter you have already
scored (the ledger does this for you).

If you are approaching $15, something is wrong with the loop rather than with
the budget — stop and mail Matt rather than pushing on.

Wall-clock is the tighter constraint. At three-way parallelism a batch of 8
rollouts takes about 35 minutes, and a search round is a batch. Plan your runs
the day before you need the results.

## What we are assessing

In descending order of weight:

1. **Judgement about what to measure.** Did each rollout you bought answer a
   question? Did you reject bad proposals for free, before paying for them?
2. **Honesty of the numbers.** Paired comparisons, failures kept in, harness
   errors excluded and reported, test evaluated once. A clean null beats a
   flattering result every time.
3. **The reasoning in the one-pager and the write-up.** Whether you can say what
   a method assumes and whether those assumptions hold here.
4. **Code quality**, to the standard of "someone else can run this and see what
   it did". Not to the standard of a library.
5. Whether the number went up. Least important. It probably will not.

## Rules

- **Never show ground truth to the loop.** Not to the proposer, not in the
  adapter, not indirectly. `qual audit` checks the container side; the proposer
  side is on you. Use `qualkit.scoring.diagnose()`, which is derived only from
  the generated deck. A contaminated run is not a weak result, it is no result.
- **Do not edit the scorer, the task prompts, the corpus builder, or the
  container.** If you think one of them is wrong, say so in the write-up.
- **The simulator does not run, and that is not an oversight.** There is no
  GEOS binary in the container; the deck is scored structurally against a
  reference. Execution was measured here as a campaign's largest cost driver
  for output nothing reads. If your method needs execution feedback, write that
  up as the next experiment rather than trying to add it.
- **Do not raise the token budgets silently.** Raising them is allowed; not
  saying you did is not.
- **Evaluate on test once.**
- Use of AI coding assistants is fine and expected. Understanding what you
  submitted is not optional — assume you will be asked to explain any line of it.

## Getting unstuck

Mail Matt. Being stuck for two days on something that takes five minutes to
answer is a worse signal than asking. The one thing to ask about early rather
than late is anything involving spend: keys, ceilings, a run that looks like it
is burning money.
