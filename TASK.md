# Qualification task — self-improving harnesses for scientific simulation setup

## The short version

You have surveyed methods for self-improving / self-evolving agent harnesses.
Pick one, argue that it should work on *this* problem, implement it against the
starter kit here, run it, and tell us what you found out.

**Time: about 15 hours of work, over ~3 weeks. Stop at 18.**
**Money: yours, and it should be small — a few dollars. See "Cost" below.**
**Deliverable: a pull request with your loop, the run log it produced, and a
short note — about a page — on what you did and what you learned.**

Fifteen hours is not enough to do this comfortably, and that is the point: you
will have to decide what not to do. If you are at hour 15 with a loop that runs
and a null result, you are done.

## What we are actually looking for

Not the highest score. Our own result on this problem is a null, and the
published literature predicts a search this sample-starved returns its seed.

What we want to see is **how you think about the problem, and how you find
things out**. Concretely:

- **Do you look at the data?** Read a task specification. Open a reference deck.
  Run one rollout and read its whole transcript — what the agent searched for,
  what it read, where the turns went, what it wrote. `qual inspect` exists for
  this and it is the most useful command in the kit.
- **Are your decisions grounded in something you observed**, rather than in what
  the method's paper says should happen? "I changed X because in run 3 the agent
  spent 19 turns grepping for a file that was not there" is the sentence we are
  hoping to read.
- **Do you check what you believe?** When a number moves, do you go and find out
  why, or do you accept it?

Depth beats breadth here, and if cost or time is a constraint, **go deep on a
small set**. Four rollouts you have read line by line teach you more — and tell
us more about you — than forty you skimmed. A submission that runs one careful
comparison on two tasks, with a clear account of what the transcripts showed, is
a strong submission.

An illustration of why, from building this kit. Scoring the seven tasks looked
fine. Then one transcript got read, and it contained:

```
cd /geos_lib && git show HEAD:inputFiles/.../spe11b_vti_source_base.xml
```

The agent had recovered a deliberately removed reference deck out of git
history. Re-checking the research harness's 80-rollout screen found **59 of 80
rollouts running git against the corpus, and 29 tasks where a git command
returned their own blocked deck**. That is a benchmark-invalidating bug, found
by reading one log, invisible in every score. This kit is immune to it (see
`docs/CONTAMINATION.md`) — but the lesson is the method, not the bug.

## The problem, in one paragraph

A frozen coding agent is given a natural-language specification of a
geomechanics simulation and must author a valid GEOS XML input deck. We do not
fine-tune the model. What we *do* change is everything else: the prompt, the
tools it has, the context it carries, the hooks that fire, what it is allowed to
retry. The research question is whether an automated loop can improve that
harness better than a hand-written starting point, and whether any improvement
survives on a physics family the loop never trained on.

## What you can change

Everything about the harness except the model. `qualkit/config.py` is the full
list; the shape of it:

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

There are no size limits and no token budgets. Five things are fixed, all about
whether the experiment means anything rather than about taste: the model, no
subagent tools, no web tools, the task prompt, and the scorer.
`HarnessConfig.validate()` enforces the first three and raises before anything
is spent. `README.md` has the reasons.

## Better in which direction?

Three, and they do not move together:

- **performance** — mean TreeSim against the reference deck;
- **reliability** — how often a rollout produces nothing usable. The published
  work says this is the one that matters most here, and it is what a mean hides;
- **efficiency** — wall-clock, tool calls, dollars per rollout.

`EvalResult` reports all three and `compare()` gives the change in all three.
**Say which you are optimising for before you run**, then report what moved.
Efficiency is a particularly good target if you are watching your spend: making
the harness cheaper is a real result and costs less to demonstrate.

## What to do

### 1. Look before you plan

Before picking a method, spend an hour with the actual material. Read a task
spec. Read the reference deck it is scored against. Run `qual mock` and then one
real rollout, and read the transcript end to end with `qual inspect`. You will
have opinions after that hour which you cannot have before it, and they are the
opinions we want in the one-pager.

### 2. Choose, and justify — then check in

Pick one technique from your survey. Write **one page**:

- what the method is, and what it assumes (a verifier? many rollouts? a reward
  model? gradient-free search over prompts? a memory that accumulates?);
- why those assumptions hold or fail here — and where you can, point at
  something you actually saw in a transcript;
- which of the three directions you are going for;
- what you predict will happen, in a sentence, before you run anything.

**Send this to Matt before you implement.** Not optional, and part of what we
are assessing — it is the cheapest point at which a wrong plan can be corrected.

### 3. Pick a base policy

`qual harnesses` lists the coding agents this container can run: Claude Code's
own CLI, and claude / codex / pi behind `acpx`. Only `claude` has been run end
to end here — take it unless you have a reason not to, and say which you took.
Keep it fixed; the agent is not part of the search space.

### 4. Implement

Fill in `evolve/loop.py`. Develop against the free mock runner (`qual evolve
--mock`) until the loop runs end to end and survives a failed rollout without
crashing. Do not spend real money before that is true.

The mock is a toy with a known answer, and it is blind to most of what you can
change — tools, hooks, MCP, turn caps and cost all do nothing there. Read
`qualkit/mock.py` so you know exactly how it is fake.

### 5. Run it, and read what comes back

```bash
qual baseline --seeds 2      # the seed configuration on the train split
qual evolve --budget 3       # your loop, with a hard ceiling
qual inspect runs/<...>      # and then actually read some of them
```

Then evaluate your champion **once** on the test split — three tasks from two
physics families the loop never saw. Once. If you evaluate on test twice, the
second number is not a held-out number and you have to say so.

### 6. Report back — briefly

About a page, plus whatever the kit produced on its own (`runs/ledger.jsonl`,
your decision log, the champion configuration). This is the least interesting
part of the work and it should not eat your time. Bullet points are fine. What
it has to contain:

- what method, on what harness, which direction you were optimising, and why;
- **what you observed** — at least one concrete thing you learned from reading a
  transcript or a deck that changed what you did;
- the numbers: paired per task on train, then the test result;
- one honest paragraph: what would you bet on, what would change your mind. If
  it is a null, say so plainly;
- what you would do next, and what you left out and why;
- anything in the kit you think is wrong. The setup has known problems and
  finding another one is a good outcome.

## Cost

**Bring your own OpenRouter key.** We cannot issue keys to people outside the
group, so this runs on yours. That also means we are asking you to spend your
own money, so: **keep it small, and we will not read a bigger bill as a better
submission.**

A rollout is about **$0.11–0.13** on `z-ai/glm-5.3-flash` and takes 11–13
minutes. Sensible shapes:

| | rollouts | cost |
|---|---:|---:|
| the frugal version: 2 train tasks × 1 seed, 4 candidates, 2 test tasks | ~14 | **~$1.80** |
| the standard version: 4 train tasks × 1 seed, 6 candidates, 3 test × 2 seeds | ~44 | ~$5.70 |

**The frugal version is a complete submission.** It is fewer cells, so the
comparison is noisier, and saying so clearly is itself part of doing it well.
Whatever you spend, put a hard per-key limit on your OpenRouter key so a runaway
loop cannot surprise you, and pass `--budget` to every command that spends.

If money is genuinely a blocker, say so before you start rather than quietly
cutting the work — there are cheaper models and there is the mock runner, and it
is a better conversation to have up front.

Wall-clock is the tighter constraint anyway. At three-way parallelism a batch of
8 rollouts takes about 35 minutes. Start a run and go and do something else.

## What we are assessing

In descending order of weight:

1. **How you find things out.** Did you read the transcripts, the decks, the
   logs? Are your decisions traceable to something you observed?
2. **Judgement about what to measure.** Did each rollout you bought answer a
   question? Did you reject bad candidates for free, before paying for them?
3. **Honesty of the numbers.** Paired comparisons, failures kept in,
   infrastructure errors excluded and reported, test evaluated once. A clean
   null beats a flattering result every time.
4. **The reasoning in the one-pager.** Whether you can say what a method assumes
   and whether those assumptions hold here.
5. **Code quality**, to the standard of "someone else can run this and see what
   it did". Not to the standard of a library.
6. The write-up, as a vehicle for the above rather than a thing in itself.
7. Whether the number went up. Least important. It probably will not.

## If you are running out of time or money

Cut in this order. Each is a legitimate scoping decision as long as you say you
made it:

1. **Fewer tasks and fewer candidates, more reading.** Two tasks understood
   beat six skimmed. This is the first cut and it costs you the least.
2. **A shorter note, never a skipped one.**
3. **Report the train result and say the test evaluation is outstanding.** Do
   not skip it silently and do not rush it.
4. **Drop the method and hand in the analysis.** If the loop never worked, say
   what you built, where it broke, and what the seed baseline and the
   transcripts say. That is a real result about this problem.

What not to cut: the check-in, the paired comparison, and honesty about
failures.

## Rules

- **Never show ground truth to the loop.** Not to the proposer, not in the
  configuration, not indirectly. `qual audit` checks the container side; the
  proposer side is on you. Use `qualkit.scoring.diagnose()`, which is derived
  only from the generated deck. A contaminated run is not a weak result, it is
  no result.
- **Reading a comparable example is allowed and intended.** The tasks come from
  the GEOS example collection, so the corpus is full of decks that resemble the
  answer without being it. The answer and its variants are masked; the rest is
  fair game. `qual audit --deep` reports the **copy ceiling** — the best score
  obtainable by copying something readable — which is 0.43–0.78 across the seven
  tasks, and on three of the four training tasks it is *above* what the seed
  harness scores. That is a real opening and taking it is not cheating. Just be
  able to tell the difference in your note.
- **Do not edit the scorer, the task prompts, the corpus builder, or the
  container image.** If you think one is wrong, say so in the note.
- **The simulator does not run, and that is not an oversight.** There is no GEOS
  binary in the container. Schema validation *is* available — `xmllint` is in
  the image and the schema is in the corpus — and nothing wires it up for you.
- **Evaluate on test once.**
- Use of AI coding assistants is fine and expected. Understanding what you
  submitted is not optional — assume you will be asked to explain any line.

## Getting unstuck

Mail Matt. Being stuck for two days on something that takes five minutes to
answer is a worse signal than asking.
