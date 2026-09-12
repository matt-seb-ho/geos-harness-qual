# geos-harness-qual

A frozen coding agent, a scientific simulator it has to write an input file for,
and a small bundle of text wrapped around the agent that you are allowed to
change. Your job is to write the loop that changes it.

Everything except that loop is already here and is not yours to edit: the seven
tasks, the container, the read-only GEOS corpus with the answers filtered out of
it, the scorer, the budget guard, and the comparison statistics.

**Start with [`TASK.md`](TASK.md)** — what to deliver and how long to spend.
This file is about how to drive the kit.

---

## Setup

```bash
git clone <this repo> && cd geos-harness-qual
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'          # there are no runtime dependencies
cp .env.example .env             # then paste in the key Matt gives you
pytest                           # ~50 tests, a few seconds, no network
qual doctor                      # what this machine can and cannot do
```

`qual doctor` will tell you if the container is missing. On the lab server it is
already built under the name `geos-eval` and `enroot` is the backend, because
the docker daemon is root-only there. Nothing below the "costs money" line works
without it; everything above does.

If you are not on the lab server, you need the GEOS source tree to build the
corpus from — `git clone https://github.com/GEOS-DEV/GEOS` and set
`GEOS_SOURCE_DIR` at the checkout. Only XML, RST and the schema are read, so a
shallow clone is enough.

## The five-minute version

```bash
qual tasks                # the seven tasks, their families, their split
qual harnesses            # which coding agents this image can run
qual mock                 # the seed config against the toy runner. Free.
qual evolve --mock        # the stub loop in evolve/loop.py. Free.
```

Then open [`evolve/loop.py`](evolve/loop.py) and replace the stub.

## What the pieces are

| | |
|---|---|
| [`tasks/`](tasks/) | seven GEOS tasks: a natural-language specification per task, and the reference deck it is scored against. The reference decks are **never** mounted into a container. |
| [`harness/seed/`](harness/seed/) | the starting configuration: a five-line prompt, the default tool set, one attempt, no hooks, no extra tools. What you must beat. |
| `qualkit.agents` | which coding agent runs inside the container. Claude Code is the default and the only one verified here; `acpx` in the image also fronts codex, pi and openclaw. |
| `qualkit.config` | the harness configuration — everything except the model — and the five things that are fixed. |
| `qualkit.rollout` | one rollout: materialise the configuration, run the agent in a container against one task, score the result. The unit of cost. |
| `qualkit.corpus` | builds the read-only `/geos_lib` tree each rollout sees, **per task**, with that task's answers and their variant siblings removed. |
| `qualkit.scoring` | TreeSim: structural similarity between the generated deck and the reference, in [0, 1]. Vendored from the research repo; do not edit it. |
| `qualkit.evaluate` | scores a configuration over tasks and seeds on all three axes, compares two of them pairwise with a bootstrap interval, and refuses comparisons that are not like-for-like. |
| `qualkit.ledger` | append-only record of every rollout (so a crashed run resumes instead of paying twice) and a hard budget ceiling. |
| `qualkit.mock` | a free, offline, deterministic fake agent. Develop against this. |
| [`evolve/loop.py`](evolve/loop.py) | **yours.** |

## What you may change: everything but the model

The object your loop evolves is a `HarnessConfig` — the whole harness, not a
prompt. `qualkit/config.py` is the authority; the shape of it:

| | |
|---|---|
| `system_prompt` | text appended to the agent's system prompt |
| `tools` / `disallowed_tools` | which tools exist at all, and which are withheld |
| `files` | anything, mounted read-only at `/harness`: hook scripts, MCP servers, a cheatsheet the agent reads on demand, notes your loop accumulates |
| `workspace_files` | files placed in `/workspace` before the agent starts — `CLAUDE.md`, a checklist, a template |
| `settings` | the harness's own settings JSON. **Hooks live here** — `Stop`, `PostToolUse`, `PreToolUse` |
| `mcp_servers` | new tools, as MCP server definitions |
| `max_turns`, `env`, `extra_argv` | context budget, environment, any other CLI flag |
| `retry` | a host-side loop: shell checks against the finished workspace, and what the agent is told when one fails |

**There are no size limits and no token budgets.** An earlier version of this
kit imposed them; that was the wrong instinct. A configuration that wins on
score while tripling cost is not obviously worse than one that does neither — it
depends what you are optimising for, and deciding that is your job. So the kit
measures the thing a budget was protecting instead, and reports it next to the
score.

### Better in which direction?

Three, and they do not move together. `EvalResult` reports all three; `compare()`
gives the change in all three:

```
cfg_1ecba84903ef  score 0.7312  zero-rate 0.00  687s and 64 tool calls per rollout  n=8
```

- **performance** — mean TreeSim against the reference deck
- **reliability** — how often a rollout produced nothing usable. The published
  work says this is the one that matters here, and it is what a mean hides
- **efficiency** — wall-clock, tool calls, dollars

Nothing in the kit decides which you are optimising. Say so before you run, and
report what actually moved.

### What is fixed, and why

Five things, all about whether the experiment means anything rather than about
design taste:

1. **The model.** The premise is optimisation around a frozen model.
2. **No subagent tools** (`Task`/`Agent`/`TaskCreate`). A rollout nominally on
   one model once spawned a subagent on a different, stronger one that took 85%
   of the bill — which breaks the frozen-model premise silently.
3. **No web tools** (`WebSearch`/`WebFetch`). Every GEOS deck is public on GitHub
   and the container has network, so a fetch tool routes straight around the
   corpus filtering. (The research harness does *not* currently block these.
   That is a difference, and arguably a bug on our side.)
4. **The task prompt.** It defines the deliverable, so it must be identical
   across configurations or two candidates are solving different tasks. That is
   why the scope note ("write the deck, don't run the simulation") lives there
   and not in the configuration, where your loop could delete it.
5. **The scorer and the ground truth.** Not reachable from a rollout at all;
   scoring happens on the host after the container exits.

`HarnessConfig.validate()` enforces 1–3 and raises before any rollout is spent.

## Choosing the base policy

The agent inside the container is a *choice*, not a constant. `qual harnesses`
lists what this image can run:

```
claude          Claude Code's own CLI — verified here, and what the research
                harness runs, so your numbers are comparable with ours
acpx:claude     the same agent over the Agent Client Protocol
acpx:codex      acpx:pi          > also fronted by acpx, which is already in the image.
acpx:openclaw   /  Unverified: flags are right, nobody has run one end to end.
```

Pick with `--harness` or `QUAL_HARNESS`. Two rules:

- **Pick one and keep it fixed.** The harness is not a searchable component. Two
  candidates evaluated on different harnesses are not comparable, and "my method
  works on harness A" is a different claim from "my method works".
- **`claude` is the safe default.** If you pick another one, budget an hour for
  getting it to authenticate and write files, and check `parse_events` actually
  reads its transcript — an unparsed transcript costs you the per-rollout
  telemetry, though not the score or the spend limit.

Comparing harnesses is a genuinely interesting second experiment (does an
configuration found on one transfer to another?) and it is on the research programme's
list. It is not this exercise; if you have budget left and want to try it, say
so as a separate section.

## What is in the container, and what is not

Worth knowing before you design anything, because half of it is reachable and
nothing is wired up for you.

**The GEOS corpus**, read-only at `/geos_lib`, built per task with that task's
answers removed:

```
/geos_lib/inputFiles/        ~743 example decks (.xml)
/geos_lib/docs/              ~98 documentation pages (.rst) — user guide,
                             tutorials, basic and advanced examples
/geos_lib/schema/schema.xsd  the authoritative element and attribute list
```

That is the curated tree, not the full checkout: no C++, no build system, no
tests. The research harness mounts 4,462 files and 435 MB; this is 842 files and
4 MB, which is most of why a rollout here takes 687 s rather than 1,453 s.

**Tools in the image**: `xmllint`, `python3`, `uv`, `node`, `git`, a normal
shell. So schema validation works today:

```bash
xmllint --noout --schema /geos_lib/schema/schema.xsd inputs/deck.xml
```

On a deck it rejects, that prints the **complete list of elements GEOS will
accept at that point** — the richest feedback signal available in this setup,
and free. Nothing in the seed configuration uses it. Telling the agent to use
it, or making it a `Stop` hook, or wrapping it as an MCP tool, are all things
your loop could do.

**Not in the container**, deliberately:

| | why |
|---|---|
| the `geosx` binary | execution is out of the loop — see below |
| a retrieval / RAG server | the research harness has one; the corpus here is 4 MB, so `Grep` and `Glob` reach all of it. Building retrieval over it is a legitimate thing for a configuration to do |
| an `xmllint` MCP wrapper | the binary is there; the tool wrapper is not |
| ground truth | never mounted; scoring happens on the host |

## The simulator does not run

There is no GEOS binary in the container. The agent authors a deck and cannot
execute it, which matches the setup the published SIGA results were measured on.

This is deliberate, and it is the single biggest lever on what a rollout costs.
When the simulator *was* reachable, agents ran 7.3 solves per rollout — for
output nothing reads, since the deck is scored structurally against a reference.
Removing it cut wall-clock 41% and cost 31%. A later attempt to keep the binary
but block non-validation use made things *worse*: solve attempts doubled, cost
rose 59%, because a refusal invites another variation rather than ending the
line of inquiry.

So: not mounted at all. Schema validation is the substitute and it is free. If
your method wants execution feedback, that is a real design discussion — put it
in the note as the experiment you would run next, with what it would cost.

## Spending money

Everything above this line is free. Below it, each rollout is **$0.134 billed
and about 12 minutes** — measured on this kit on 2026-09-12, and the same
figure the research harness measures against account deltas.

```bash
qual baseline --seeds 2        # seed config, 4 train tasks x 2 seeds = 8 rollouts
qual run <task>                # one rollout, for debugging
qual evolve --budget 9         # your loop, with a hard ceiling
qual report runs/ledger.jsonl  # re-derive every number from the ledger, free
```

Three habits the kit tries to make automatic, all of them bought with real
mistakes on this project:

1. **Price from the account, never from the transcript.** On the smoke rollout
   that validated this kit, the transcript estimate was **$0.028** and the bill
   was **$0.134** — under by 4.7×, because the gateway bills the resent
   conversation and the provider reported no cache-read tokens. The research
   repo hit the same wall from the other direction, over-predicting 2.25× on a
   different provider. A transcript cannot price a run. `BudgetGuard` reads
   `/api/v1/credits`; the `~$` in progress output is only for watching a run
   move.
2. **Failures are zeros and stay in the average.** A configuration that scores
   0.9 on three tasks and produces nothing on the fourth is not a 0.9
   configuration.
3. **Never compare means.** Between-task variance dwarfs the configuration
   effect at this sample size. `compare()` is paired, per task, with an interval — and at
   four tasks that interval will usually span zero. That is the honest answer.

## Contamination

The agent must not be able to read the answer. For each task, three things are
removed from its corpus: the reference decks, their variant siblings (given
`Foo_base.xml` the GEOS tree usually also has `Foo_smoke.xml`, which shares
nearly every parameter), and the documentation page the specification was
written from. Hardlinks, not symlinks — a symlink can be followed out of a
read-only mount.

```bash
qual audit    # must print "clean" before you believe any score
```

The agent also has no web tools. `WebSearch` and `WebFetch` are disallowed
because every GEOS example deck is public on GitHub, and a fetch tool is a
route straight around the corpus filter. (The research harness does not
currently block them. That is a difference, and arguably a bug on our side.)

The same rule applies to your loop: **never put ground truth in front of the
proposer.** `qualkit.scoring.diagnose()` gives you feedback derived only from
the generated deck. A contaminated run is not a weak result, it is no result.
See [`docs/CONTAMINATION.md`](docs/CONTAMINATION.md).

## Where the numbers in `qual tasks` come from

The `2026-09-11 seed` column is what the *research* harness scored on each task
at two seeds, from an 80-rollout screen over 40 tasks. Read it as a prior, not a
baseline: that run used a much larger corpus, a retrieval server and a stop
hook, none of which are here. Your `qual baseline` is the number your result is
measured against.

Those numbers are also why there are seven tasks and not forty-six. Twelve tasks
in the pool score a flat 1.000 at both seeds — no headroom, so no candidate can
beat the seed on them — and several never produce a deck at all. These seven are
the ones with measured room to move.
