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
qual mock                 # the seed adapter against the toy runner. Free.
qual evolve --mock        # the stub loop in evolve/loop.py. Free.
```

Then open [`evolve/loop.py`](evolve/loop.py) and replace the stub.

## What the pieces are

| | |
|---|---|
| [`tasks/`](tasks/) | seven GEOS tasks: a natural-language specification per task, and the reference deck it is scored against. The reference decks are **never** mounted into a container. |
| [`adapter/seed/`](adapter/seed/) | the starting adapter: a five-line primer, an empty cheatsheet, no constraints. This is what you must beat. |
| `qualkit.agents` | which coding agent runs inside the container. Claude Code is the default and the only one verified here; `acpx` in the image also fronts codex, pi and openclaw. |
| `qualkit.rollout` | one rollout: materialise the adapter, run the agent in a container against one task, score the result. The unit of cost. |
| `qualkit.corpus` | builds the read-only `/geos_lib` tree each rollout sees, **per task**, with that task's answers and their variant siblings removed. |
| `qualkit.scoring` | TreeSim: structural similarity between the generated deck and the reference, in [0, 1]. Vendored from the research repo; do not edit it. |
| `qualkit.evaluate` | scores an adapter over tasks and seeds, compares two adapters pairwise with a bootstrap interval, and refuses comparisons that are not like-for-like. |
| `qualkit.ledger` | append-only record of every rollout (so a crashed run resumes instead of paying twice) and a hard budget ceiling. |
| `qualkit.mock` | a free, offline, deterministic fake agent. Develop against this. |
| [`evolve/loop.py`](evolve/loop.py) | **yours.** |

## The adapter: what you may change

Four components, each with a token budget enforced before any rollout is spent:

| component | budget | what it is |
|---|---|---|
| `primer` | 1200 | goes in the system prompt. What GEOS is, where things are. |
| `cheatsheet` | 1500 | procedural memory: how to do the recurring steps. |
| `constraints` | 600 | negative rules — what not to do, what the validator rejects. |
| `stop_policy` | — | config: retries before the rollout ends, what the agent is told, which checks run. |

The budgets exist because the first version of this system had none, and its
primer grew twelvefold over three rounds while getting worse. You may raise
them in your own experiment — but say that you did, because seed headroom is a
confound and a search with a bigger ceiling is not the same experiment.

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
adapter found on one transfer to another?) and it is on the research programme's
list. It is not this exercise; if you have budget left and want to try it, say
so as a separate section.

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

So: not mounted at all. If your method wants execution feedback, that is a real
design discussion — put it in the write-up as the experiment you would run next,
with what it would cost.

## What you may not change

The model, the harness (once chosen), the container, the task prompt, the
corpus, and the scorer. Those are what make two candidates comparable. If your
method needs one of them to move, that is a finding — write it down, do not
quietly edit it.

The scope note ("write the deck, don't run the simulation") lives in the *task
prompt* rather than the adapter, deliberately: in the adapter it would be a
component your loop could delete, and two candidates would then be solving
different tasks.

## Spending money

Everything above this line is free. Below it, each rollout is **$0.134 billed
and about 12 minutes** — measured on this kit on 2026-09-12, and the same
figure the research harness measures against account deltas.

```bash
qual baseline --seeds 2        # seed adapter, 4 train tasks x 2 seeds = 8 rollouts
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
2. **Failures are zeros and stay in the average.** An adapter that scores 0.9 on
   three tasks and produces nothing on the fourth is not a 0.9 adapter.
3. **Never compare means.** Between-task variance dwarfs the adapter effect at
   this sample size. `compare()` is paired, per task, with an interval — and at
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
