# geos-harness-qual

A coding agent has to write a GEOS simulation input deck from a written
description. The model is fixed; everything around it is yours to change. This
repository contains the tasks, the container, the scorer and the evaluation
machinery. You write the loop that changes the harness.

**Start with [`TASK.md`](TASK.md)** — what to do and what we are looking for.
This file explains how to drive the kit.

## Setup

```bash
git clone https://github.com/matt-seb-ho/geos-harness-qual && cd geos-harness-qual
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'          # no runtime dependencies
cp .env.example .env             # then paste in your OpenRouter key
pytest                           # ~66 tests, a few seconds, offline
qual doctor                      # what this machine can and cannot do
```

On the lab server the container already exists as `geos-eval` and the backend is
`enroot`, because the docker daemon is root-only there. `qual doctor` tells you
which of the two below you still need.

**The container.** [`run/Dockerfile`](run/Dockerfile) is the image, and it is
the same file the lab server's was built from. Nothing GEOS-specific is in it —
the corpus is a mount, not a layer — so it is ubuntu:24.04 plus `xmllint`,
python3, uv, node, git and the agent CLIs.

```bash
docker build -t geos-eval -f run/Dockerfile run/   # then QUAL_CONTAINER_BACKEND=docker
bash run/build_enroot_image.sh                     # no docker daemon; several minutes
```

**The corpus.** Off the lab server you also need the GEOS source tree to build
it from: clone `https://github.com/GEOS-DEV/GEOS` and set `GEOS_SOURCE_DIR` to
the checkout. Only XML, RST and the schema are read.

## First five minutes

```bash
qual tasks                # the seven tasks, families, splits
qual mock                 # the starting configuration on the mock runner, free
qual evolve --mock        # the stub loop in evolve/loop.py, free
```

Then open [`evolve/loop.py`](evolve/loop.py) and replace the stub.

## What you change

Your loop edits a `HarnessConfig`. It covers everything about the harness except
the model:

| | |
|---|---|
| `system_prompt` | appended to the agent's system prompt |
| `tools` / `disallowed_tools` | which tools exist, which are withheld |
| `files` | any files, mounted read-only at `/harness`: hook scripts, MCP servers, a cheatsheet the agent reads when it wants it, notes your loop accumulates |
| `workspace_files` | files placed in `/workspace` before the agent starts |
| `settings` | the harness's settings JSON. Hooks go here |
| `mcp_servers` | new tools |
| `max_turns`, `env`, `extra_argv` | turn limit, environment, any other CLI flag |
| `retry` | shell checks run against the finished workspace, and what the agent is told when one fails |

There are no size limits. A configuration that raises the score while tripling
the cost may or may not be worth having — that depends on what you are trying to
improve, which is your decision, so the kit measures cost instead of capping it.

Five things are fixed, because varying them would make the comparison
meaningless rather than because they are off-limits by taste:

1. **The model.** The premise is improving the harness around a fixed model.
2. **No subagent tools** (`Task`, `Agent`, `TaskCreate`). A rollout nominally on
   one model once spawned a subagent on a different, larger model that accounted
   for 85% of the bill. That breaks the fixed-model premise without any visible
   sign.
3. **No web tools** (`WebSearch`, `WebFetch`). Every GEOS deck is on GitHub and
   the container has network access, so a fetch tool gets around the corpus
   filtering entirely.
4. **The task prompt.** It defines the deliverable, so it has to be identical
   across configurations. This is why the instruction not to run the simulation
   lives there and not in the configuration, where your loop could delete it.
5. **The scorer and the reference decks.** Not reachable from inside a rollout;
   scoring happens on the host after the container exits.

`HarnessConfig.validate()` enforces 1–3 and raises before any rollout runs.

## What is measured

```
cfg_1ecba84903ef  score 0.7312  zero-rate 0.00  687s and 64 tool calls per rollout  n=8
```

- **score** — mean structural similarity (TreeSim) to the reference deck, 0 to 1
- **zero-rate** — fraction of rollouts that produced nothing usable
- **wall-clock and tool calls** — per rollout

`compare()` gives the change in all three between two configurations, paired per
task with a bootstrap interval. Nothing in the kit decides which one you are
optimising.

Three rules the evaluation enforces, each from a mistake made earlier in this
project:

1. **Cost comes from the account balance, not the transcript.** On the rollout
   used to check this kit, the transcript estimate was $0.028, the CLI's own
   `total_cost_usd` field said $3.974, and the actual bill was $0.134. The `~$`
   in progress output is for watching a run move, not for reporting.
2. **Failures are zeros and stay in the average.** A configuration that scores
   0.9 on three tasks and produces nothing on the fourth is not a 0.9
   configuration.
3. **Comparisons are paired per task.** Between-task variance is much larger
   than the difference between two configurations, so comparing means is close
   to meaningless. At four tasks the interval will usually include zero; that is
   the honest answer at this sample size.

## What is in the container

The GEOS corpus, read-only at `/geos_lib`, built separately for each task with
that task's answers removed:

```
/geos_lib/inputFiles/        ~743 example decks (.xml)
/geos_lib/docs/              ~98 documentation pages (.rst)
/geos_lib/schema/schema.xsd  the list of elements and attributes GEOS accepts
```

This is a curated subset, not the full checkout: no C++, no build system, no
version control history. The research harness mounts 4,462 files and 435 MB;
this is 842 files and 4 MB, which is most of why a rollout here takes about 690
seconds rather than 1,450.

Also installed: `xmllint`, `python3`, `uv`, `node`, `git`, a normal shell —
[`run/Dockerfile`](run/Dockerfile) is the whole of it. So schema validation
works:

```bash
xmllint --noout --schema /geos_lib/schema/schema.xsd inputs/deck.xml
```

On a deck it rejects, that prints the complete list of elements GEOS will accept
at that point, which is the most detailed feedback available here, and it is
free. The starting configuration does not use it.

Not present, deliberately: the `geosx` binary, a retrieval server, an `xmllint`
MCP wrapper, and the reference decks.

### The simulator does not run

There is no GEOS binary in the container. The agent writes a deck and cannot
execute it, which matches the setup the published SIGA results used.

This is the largest single factor in what a rollout costs. When the simulator
was reachable, agents ran 7.3 solves per rollout, for output that nothing reads —
the deck is scored structurally against a reference. Removing it cut wall-clock
41% and cost 31%. Keeping the binary but refusing non-validation calls was
worse: solve attempts doubled and cost rose 59%, because a refusal prompts
another variation rather than ending the attempt.

Schema validation is the substitute, and it is free. If your method needs
execution feedback, describe it in your note as the next experiment.

## Choosing the agent

The agent inside the container is a choice. `qual harnesses` lists what this
image can run:

```
claude          Claude Code's own CLI. Verified here, and what the research
                harness uses, so the numbers are comparable with ours.
acpx:claude     the same agent over the Agent Client Protocol
acpx:codex      also available through acpx, which is in the image.
acpx:pi         Unverified: the flags are right, nobody has run one end to end.
```

Select with `--harness` or `QUAL_HARNESS`. **Pick one and keep it fixed** — two
configurations evaluated on different agents are not comparable. Take `claude`
unless you have a reason not to; the others need their own credentials, and ACP
has no settings-file hooks, so a configuration built on hooks will do nothing
there. `agents.get(name).unsupported(config)` reports that rather than letting
it pass silently.

## Contamination

The agent must not be able to read the answer. For each task, three things are
removed from its corpus: the reference decks (`.xml` and `.geos`), their variant
siblings anywhere in the GEOS tree (given `Foo_base.xml` the tree usually also
has `Foo_smoke.xml`, which shares nearly every parameter), and the documentation
page the description was written from. This is the rule SIGA's published runs
used; [`docs/CONTAMINATION.md`](docs/CONTAMINATION.md) states it exactly.

It matters more than it sounds. Several task descriptions name their own
reference files: `TutorialPoroelasticity` ends by pointing at
`inputFiles/poromechanics/PoroElastic_Terzaghi_base_direct.xml`. That file is
not there, and neither is `_base_iterative`, which the description never
mentions and which is not in the reference directory either.

The corpus is also assembled from an include list rather than produced by
deleting files from a copy of the GEOS checkout. The research harness does the
latter, which copies `.git` along with it, and in its 40-task screen 29 tasks
recovered their own removed decks with `git show`. A file that is removed but
recoverable is not removed.

```bash
qual audit           # must print "clean" before you trust a score
qual audit --deep    # also measures what copying could achieve. Minutes, free.
```

`qual audit --deep` scores every deck still readable in a task's corpus against
that task's reference. Reading a comparable example is the intended workflow, so
this is not a cheat detector — it tells you how much of a score is retrieval
rather than authoring. The seven tasks sit between 0.43 and 0.78 against a
target of 1.0. One task was removed from the set for reaching 0.856.

The same rule applies to your loop: **do not put reference decks in front of the
proposer.** `qualkit.scoring.diagnose()` gives feedback derived only from the
generated deck.

## Reading a rollout

```bash
qual inspect runs/<config>-s1-<task>
```

Prints the tool mix, the call-by-call trace with the argument of each call,
which parts of the corpus the agent actually opened, and the deck it produced
with its weakest sections named. This is the most useful command here. See
`TASK.md`.

## The tasks

`qual tasks` prints them with two numbers each. The first is what the research
harness scored at two seeds in a 40-task screen. Treat it as background, not as
your baseline: it came from a different configuration, and that configuration
had the git-history leak described above, so for four of these seven tasks it is
an upper bound on a contaminated run. Your `qual baseline` is the number your
result is compared against.

The second is the copy ceiling. Both are explained in `docs/CONTAMINATION.md`.

Seven tasks rather than forty-six because the rest are unusable: twelve score a
flat 1.000 at both seeds, several never produce a deck, and one is degenerate on
the copy ceiling. These seven have measured room to improve.

## Commands

| | |
|---|---|
| `qual doctor` | can this machine run a rollout |
| `qual tasks` | the seven tasks |
| `qual harnesses` | which agents this image can run |
| `qual corpus` | build the per-task corpora |
| `qual audit [--deep]` | check for leaks; `--deep` measures the copy ceiling |
| `qual inspect <ws>` | read one rollout |
| `qual score <ws> <task>` | score a finished workspace |
| `qual mock` | the starting configuration on the mock runner |
| `qual run <task>` | one real rollout |
| `qual baseline` | the starting configuration on the train split |
| `qual evolve [--mock]` | your loop |
| `qual report <ledger>` | re-derive every number from the ledger |

Everything above `qual run` is free.

## Layout

```
tasks/          seven task descriptions and their reference decks
harness/seed/   the starting configuration
src/qualkit/    tasks, config, agents, corpus, rollout, scoring, evaluate,
                ledger, inspect, mock, llm, cli
evolve/loop.py  yours
tests/          offline, a few seconds
```
