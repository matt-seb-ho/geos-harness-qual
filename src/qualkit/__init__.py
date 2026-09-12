"""Everything in this package is fixed infrastructure. Your code goes in ``evolve/``.

Read in this order if you want to understand the kit:

``tasks``       the seven tasks, their physics families, the train/test split
``config``      the harness configuration -- everything except the model, and
                the five things that are fixed because varying them would make
                the experiment meaningless
``agents``      which coding agent runs inside the container, and what parts of
                a configuration each one can honour
``rollout``     one task, one configuration, one container run, one score
``corpus``      the read-only GEOS tree a rollout sees, with the answers removed
``scoring``     TreeSim, and the convention that failures are zeros
``evaluate``    score, reliability and efficiency over tasks and seeds; paired
                comparison of two configurations
``ledger``      the spend ceiling, and the replay that makes a crash survivable
``mock``        a free offline fake agent, for building the loop without paying
``llm``         a thin OpenRouter client, if your proposer needs a model
"""

__all__ = ["agents", "config", "corpus", "evaluate", "ledger", "llm", "mock",
           "rollout", "scoring", "tasks", "treesim"]
