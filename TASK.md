# Qualification task — self-improving harnesses for scientific simulation setup

## The short version

You have surveyed methods for self-improving / self-evolving agent harnesses.
Pick one, argue that it should work on *this* problem, implement it against the
starter kit in this repository, and run it.

**Time: about 15 hours of work, over ~3 weeks. Stop at 18.**
**Money: a $15 API ceiling. Expect to use about $7.**
**Deliverable: a pull request with your loop, the run log it produced, and a
short note — about a page — on what you tried and what happened.**

The task is open-ended on purpose, so the time cap is real and it is part of the
exercise. Fifteen hours is not enough to do this comfortably; you will have to
decide what not to do, and that decision is something we are reading for. If you
are at hour 15 with a loop that runs and a null result, you are done.

## The problem, in one paragraph

A frozen coding agent is given a natural-language specification of a
geomechanics simulation and must author a valid GEOS XML input deck. We do not
fine-tune the model. What we *do* change is everything else: the prompt, the
tools it has, the context it carries, the hooks that fire, what it is allowed to
retry. The research question is whether an automated loop can improve that
harness better than a hand-written starting point, and whether any improvement
survives on a physics family the loop never trained on.

The honest state of play: our own result so far is a **null**. Champion versus
seed was +0.116 with a 95% CI of [−0.083, +0.314], and the single task carrying
89% of that point estimate failed to replicate. The published literature
predicts a search this sample-starved returns its seed. **You are not expected
to beat that.** You are expected to run a real experiment and report what it
says.

## What you can change

Everything about the harness except the model. `qualkit/config.py` is the full
list; the shape of it is:

- **the prompt** — the system prompt, and files the agent finds in its workspace;
- **tools** — which exist, which are withheld, and new ones you add as MCP
  servers;
- **files** — anything at all, mounted at `/harness`: a cheatsheet it reads on
  demand, a skill, a hook script, notes your loop accumulates between rounds;
- **hooks** — a `Stop` hook that inspects the deck and refuses to let the turn
  end, for instance;
- **retries** — shell checks against the finished workspace, and what the agent
  is told when one fails;
- **context and turns** — the turn cap, environment, raw CLI flags.

**There are no size limits and no token budgets.** An earlier version of this
kit had them; that was the wrong instinct. What the kit does instead is measure
the thing a budget was protecting — see the next section.

Five things are fixed, all about whether the experiment means anything rather
than about taste: the model, no subagent tools, no web tools, the task prompt,
and the scorer. `HarnessConfig.validate()` enforces the first three and raises
before anything is spent. `README.md` has the reasons.

## Better in which direction?

Three, and they do not move together:

- **performance** — mean TreeSim against the reference deck;
- **reliability** — how often a rollout produces nothing usable. The published
  work says this is the one that matters most here, and it is the one a mean
  hides;
- **efficiency** — wall-clock, tool calls, dollars per rollout.

`EvalResult` reports all three and `compare()` gives the change in all three. A
configuration that holds the score and halves the cost is a result. So is one
that trades a little score for a collapse in the failure rate. **Say which you
are optimising for before you run it**, then report what actually moved.

## What to do

### 1. Choose, and justify — then check in

Pick one technique from your survey. Write **one page**:

- what the method is, and what it assumes (a verifier? many rollouts? a reward
  model? gradient-free search over prompts? a memory that accumulates?);
- why those assumptions hold or fail here. The specifics that matter: ~17
  training rollouts is a *large* experiment at this budget; the score is
  structural similarity to a reference deck, not pass/fail; a rollout takes
  ~12 minutes and $0.134; and the part of the harness you want to move may not
  be the prompt at all;
- which of the three directions you are going for;
- what you predict will happen, in a sentence, before you run anything.

**Send this to Matt before you implement.** This check-in is not optional and is
part of what we are assessing — it is the cheapest point at which a wrong plan
can be corrected.

### 2. Pick a base policy

`qual harnesses` lists the coding agents this container can run: Claude Code's
own CLI, and codex / pi / openclaw / claude behind `acpx`. Only `claude` has
been run end to end here, and it is what our own numbers come from — take it
unless you have a reason not to, and say which you took. Keep it fixed: the
agent is not part of the search space.

### 3. Implement

Fill in `evolve/loop.py`. Develop against the free mock runner (`qual evolve
--mock`) until the loop runs end to end and survives a failed rollout without
crashing. Do not spend real money before that is true.

The mock is a toy with a known answer, and it is blind to most of what you can
now change — tools, hooks, MCP, turn caps and cost all do nothing there. Read
`qualkit/mock.py` so you know exactly how it is fake, and if your method works
through something the mock cannot see, say so and test it another way.

### 4. Run it

```bash
qual baseline --seeds 2      # 8 rollouts, ~$1.07 — your incumbent
qual evolve --budget 9       # your loop, hard ceiling
```

Expect **one** real search run, not two; budget your debugging for the mock,
where it is free. Then evaluate your champion **once** on the test split — three
tasks from two physics families the loop never saw. Once. If you evaluate on
test twice, the second number is not a held-out number and you have to say so.

### 5. Report back — briefly

About a page, plus whatever the kit produced on its own (`runs/ledger.jsonl`,
your decision log, the champion configuration). This is the least interesting
part of the work and it should not eat your time. What it has to contain:

- what method, on what harness, which direction you were optimising, and why;
- what actually happened — the paired numbers on train, then the test result;
- **one honest paragraph**: what would you bet on, what would change your mind.
  If it is a null, say so plainly;
- what you would do next with another $50;
- what you left out, and why. That is a scoping decision, not an apology;
- anything in the kit you think is wrong. The setup has known problems and
  finding another one is a good outcome.

Bullet points are fine. Prose is not required and length is not a virtue.

## Budget

$15 ceiling. A rollout is **$0.134 billed** and about 12 minutes, measured — not
the $0.05 a transcript will tell you. So the ceiling is about 110 rollouts and
each one should be answering a question:

| | rollouts | cost |
|---|---:|---:|
| seed baseline, 4 train tasks × 2 seeds | 8 | $1.07 |
| your search: ~6 candidates × 4 tasks × 1 seed | 24 | $3.22 |
| proposer LLM calls | — | ~$0.10 |
| re-running what breaks the first time | ~8 | $1.07 |
| champion and seed on 3 test tasks × 2 seeds | 12 | $1.61 |
| **total** | **~52** | **~$7.10** |

Cheap ways to buy room, in the order we would use them: evaluate candidates at
one seed and re-run only the finalists at two; kill a candidate after two tasks
if both are down; never re-score a configuration you have already scored (the
ledger does this for you).

If you are approaching $15, something is wrong with the loop rather than with
the budget — stop and mail Matt rather than pushing on.

Wall-clock is the tighter constraint and it is the one that will actually bite.
At three-way parallelism a batch of 8 rollouts takes about 35 minutes, so a
six-candidate search is an afternoon you are not at the keyboard for. Start it
and go and do something else.

## What we are assessing

In descending order of weight:

1. **Judgement about what to measure.** Did each rollout you bought answer a
   question? Did you reject bad candidates for free, before paying for them?
2. **Honesty of the numbers.** Paired comparisons, failures kept in,
   infrastructure errors excluded and reported, test evaluated once. A clean
   null beats a flattering result every time.
3. **The reasoning in the one-pager.** Whether you can say what a method assumes
   and whether those assumptions hold here.
4. **Code quality**, to the standard of "someone else can run this and see what
   it did". Not to the standard of a library.
5. The write-up, as a vehicle for the above rather than a thing in itself.
6. Whether the number went up. Least important. It probably will not.

## If you are running out of time

Cut in this order. Each of these is a legitimate scoping decision as long as you
say you made it:

1. **Fewer candidates.** Four rounds you understand beat ten you do not.
2. **A shorter note, never a skipped one.** Half a page of honest reporting on a
   half-finished search is a complete submission.
3. **Report the train result and say the test evaluation is outstanding.** Do
   not skip it silently and do not rush it — a held-out number you evaluated
   twice is worth less than one you did not evaluate.
4. **Drop the method and hand in the analysis.** If the loop never worked, say
   what you built, where it broke, and what the seed baseline says. That is a
   real result about this problem and we will read it as one.

What not to cut: the check-in, the paired comparison, and honesty about
failures. Those are the assessment.

## Rules

- **Never show ground truth to the loop.** Not to the proposer, not in the
  configuration, not indirectly. `qual audit` checks the container side; the
  proposer side is on you. Use `qualkit.scoring.diagnose()`, which is derived
  only from the generated deck. A contaminated run is not a weak result, it is
  no result.
- **Reading a comparable example is allowed and intended.** The tasks come from
  the GEOS example collection, so the corpus is full of decks that resemble the
  answer without being it. The answer itself and its variants are masked; what
  remains is fair game. `qual audit --deep` reports the **copy ceiling** — the
  best score obtainable by copying something readable — which is 0.43–0.78
  across the seven tasks, and on three of the four training tasks it is *above*
  what the seed harness scores. That is a real opening, and taking it is not
  cheating. Just be able to tell the difference in your note: a configuration
  scoring at the ceiling has learned to copy; one scoring above it has learned
  something else.
- **Do not edit the scorer, the task prompts, the corpus builder, or the
  container image.** If you think one of them is wrong, say so in the note.
- **The simulator does not run, and that is not an oversight.** There is no GEOS
  binary in the container; the deck is scored structurally against a reference.
  Execution was measured here as a campaign's largest cost driver for output
  nothing reads. Schema validation *is* available — `xmllint` is in the image
  and the schema is in the corpus — and nothing wires it up for you.
- **Evaluate on test once.**
- Use of AI coding assistants is fine and expected. Understanding what you
  submitted is not optional — assume you will be asked to explain any line.

## Getting unstuck

Mail Matt. Being stuck for two days on something that takes five minutes to
answer is a worse signal than asking. Ask early rather than late about anything
involving spend: keys, ceilings, a run that looks like it is burning money.
