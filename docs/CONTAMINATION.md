# Contamination

The agent must not be able to read the answer, and neither must your loop. This
is the one class of mistake that cannot be fixed after the fact: a contaminated
run is not a weak result, it is no result, and it costs the whole budget that
produced it.

There are two boundaries, and the kit only defends one of them for you.

## The container boundary — defended by the kit

Every rollout mounts a **per-task** GEOS corpus at `/geos_lib`, read-only, built
by `qualkit/corpus.py`. Three things are removed for that task:

1. **the reference decks themselves** — every `.xml` and `.geos` file in
   `tasks/ground_truth/<task>/`;
2. **their variant siblings, anywhere in the GEOS tree.** Given
   `kgdToughnessDominated_base.xml`, the tree also ships `_benchmark` and
   `_smoke` variants of the same problem that share nearly every parameter.
   Blocking only the exact filename leaves the answer sitting next to it under
   a different name, and the benchmark quietly stops measuring authoring and
   starts measuring file search;
3. **the documentation page the specification was mined from.** The task's
   natural-language spec was generated from a GEOS example page. That page is
   most of the way to the deck.

### The exact rule

Same rule SIGA's published runs used, via the vendored
`treesim.variant_stem_keys`:

- lowercase the stem, then strip these suffixes **transitively** until nothing
  more comes off — `_base_iterative`, `_base_direct`, `_iterative_base`,
  `_direct_base`, `_iterative`, `_direct`, `_benchmark`, `_smoke`, `_base`;
- drop any resulting key shorter than **10 characters**, or in the generic set
  `{base, benchmark, input, inputs, problem, model, smoke}`. Without this,
  `base.xml` blanks most of the corpus rather than one answer;
- block every file in the source tree whose own keys intersect the blocked set.

Two deliberate differences from SIGA, both widening the block: `.geos`
dependency files are treated as leaky alongside `.xml` (a table file of a
blocked deck carries the same content), and the scan covers the whole source
tree rather than `inputFiles/` alone.

Hardlinks, not symlinks: a symlink can be followed out of the mount to its
target; a hardlink to a file that was never linked simply does not exist inside.

This matters more than it sounds, because **several task specifications name
their own reference files**. `TutorialPoroelasticity` ends with:

> The reference implementation files are located at:
> `inputFiles/poromechanics/PoroElastic_Terzaghi_base_direct.xml`,
> `inputFiles/poromechanics/PoroElastic_Terzaghi_smoke.xml`

The agent is told where the answer lives. It is not there:

```
$ qual audit
TutorialPoroelasticity                           ok
# blocked: poroelastic_terzaghi_base_direct.xml, poroelastic_terzaghi_smoke.xml,
#          poroelastic_terzaghi_benchmark.xml, poroelastic_terzaghi_base_iterative.xml
#          + src/docs/sphinx/basicExamples/poromechanics/Example.rst
```

Note the fourth one. `_base_iterative` is not mentioned by the specification and
is not in the ground truth directory — variant expansion found it. That is the
difference between blocking a filename and blocking an answer.

`tasks/ground_truth/` is never mounted into a container at all — scoring happens
on the host, after the container exits.

```bash
qual audit    # must print "clean"
```

Run it before you believe a score, and again after anything that touches the
corpus. It is free and takes seconds.

## The copy ceiling — the part a filename rule cannot settle

Name-based masking removes the answer and its variants. It does not remove a
*different* example that happens to share a skeleton — and it should not, because
reading a comparable example is the intended workflow. The seed prompt points at
`/geos_lib/inputFiles/` on purpose.

So where that line falls is measured rather than argued:

```bash
qual audit --deep     # minutes, free
```

It scores every deck still readable in a task's corpus against that task's
reference and reports the best. Measured 2026-09-12:

| task | copy ceiling | seed agent |
|---|---:|---|
| ExampleSPE11b | 0.432 | 0.51 / 0.51 |
| TutorialPoroelasticity | 0.509 | 0.49 / 0.42 |
| AdvancedExamplePureThermalDiffusionWellbore | 0.580 | 0.34 / 0.35 |
| ExamplesingleFracCompression | 0.591 | 0.78 / 0.82 |
| kgdToughnessDominated | 0.591 | 0.86 / 0.87 |
| ExampleVerticalPoroElastoPlasticWellbore | 0.615 | 0.53 / 0.52 |
| triaxialDriverExample | 0.776 | 0.90 / 0.86 |

Two things to read off this.

**Nothing here is degenerate.** All seven sit well below 1.0, so retrieval alone
leaves real headroom and a configuration still has to author most of the deck. A
task is cut when the ceiling reaches 0.80 — copying then scores about as well as
solving, and a loop can win on it without authoring anything.
`ExampleThermoporoelasticConsolidation` was cut for exactly this: ceiling
**0.856** against a seed of 0.87/0.61, via `ThermoPoroPlastic_consolidation_base.xml`,
a *plastic* variant of the same problem that no suffix rule reduces to the
answer's stem. It is replaced by `ExampleSPE11b`.

**On three of the four training tasks the ceiling is above the seed agent's
score.** Copying the nearest readable example currently does better than the
seed harness does. That is a finding, not a flaw, and it is the most obvious
thing in this kit for a loop to go after: a configuration that reliably finds
and adapts the closest example should beat the seed. That is authoring assisted
by retrieval, not plagiarism — and the ceiling is how you tell the difference,
because a configuration scoring *at* the ceiling has learned to copy, while one
scoring above it has learned something else.

## The proposer boundary — yours

Your loop reads the results of rollouts and writes new harness configurations.
If ground-truth content reaches it, the configuration becomes a place to store
the answer, and every score after that measures retrieval of something you
already had.

The rule is simple: **the proposer may see the generated deck and the score, and
nothing derived from the reference deck's contents.**

Use `qualkit.scoring.diagnose(score)`. It reports section scores, which element
types the generated deck is missing *by name of type*, and which types it
invented. Those come from the comparison, so the type names do leak the fact
that a type is relevant — that is the same signal `geosx --validate-input` gives
for free from the public schema, and it is why this much is allowed.

What is not allowed, and what it looks like when it goes wrong:

| do not | why |
|---|---|
| read `tasks/ground_truth/` from `evolve/` | the obvious one |
| pass `score.detail["attr_mismatches"]` to the proposer | mismatch text quotes reference attribute values |
| write a task-specific value into the configuration (a mesh size, a bulk modulus) | the same configuration runs on every task, so this is storing the answer key |
| let the configuration name a specific ground-truth filename | same |

The third one is the one that actually happens. It rarely looks like cheating
while you are doing it — it looks like "the loop learned that this task needs
`nx=280`". Write the test that catches it: a champion configuration should
contain no numeric literal that appears in a reference deck and nowhere else.
That applies to every part of it, `files` and `workspace_files` included — the
bundle is a much more comfortable hiding place than a prompt.

## If you find a leak

Say so, in the write-up, with the rollouts it affected. Finding a leak in the
kit is a good outcome and one we would want to know about — this project has
shipped several, including a full simulator binary that sat unnoticed in the
container for five weeks because nothing at the mount level distinguished
"validate this file" from "run the simulation".
