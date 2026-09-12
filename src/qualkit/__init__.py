"""Everything in this package is fixed infrastructure. Your code goes in ``evolve/``.

Read in this order if you want to understand the kit:

``tasks``       the seven tasks, their physics families, the train/test split
``adapter``     the four things your loop may change, and their token budgets
``rollout``     one task, one adapter, one container run, one score
``corpus``      the read-only GEOS tree a rollout sees, with the answers removed
``scoring``     TreeSim, and the convention that failures are zeros
``evaluate``    scoring an adapter over tasks and seeds; comparing two adapters
``ledger``      the spend ceiling, and the replay that makes a crash survivable
``mock``        a free offline fake agent, for building the loop without paying
``llm``         a thin OpenRouter client, if your proposer needs a model
"""

__all__ = ["adapter", "corpus", "evaluate", "ledger", "llm", "mock", "rollout",
           "scoring", "tasks", "treesim"]
