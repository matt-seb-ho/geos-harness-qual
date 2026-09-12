"""Where the money went, and a hard stop before it is all gone.

Three things live here, and all three exist because of something that actually
went wrong on this project.

**Bracket every batch with an account-balance read.** The obvious way to price a
run -- count tokens in the transcript, multiply by list price -- over-predicted
the true bill by 2.25x here, and not by a constant factor: estimated fresh input
alone exceeded the real total, which forces a negative implied cache-read price.
The model is not mis-scaled, its structure is wrong. So the estimate in
``Cost.usd`` is for progress display only, and the number you *report* comes from
``/api/v1/credits`` read before and after. Two API calls, no tokens, exact.

**Stop before the budget is gone, not after.** ``BudgetGuard`` refuses to start
a rollout once the ceiling is reached. Running out of money mid-search is not a
graceful degradation: you lose the comparison, because a half-evaluated
candidate cannot be compared with a fully evaluated one.

**Record every rollout to an append-only file.** A search is hours long and
things crash. The ledger is keyed on ``(adapter id, task, seed, model)`` so a
resumed run replays what it already paid for instead of buying it twice. The
model is part of the key deliberately: without it, a resume happily serves
rollouts produced by a *different* model as though they were this run's, which
nearly turned one corpus into another campaign's baseline here.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from qualkit.rollout import MODEL, Cost, Rollout
from qualkit.scoring import Score

CREDITS_URL = "https://openrouter.ai/api/v1/credits"


class BudgetExceeded(RuntimeError):
    """Raised instead of starting a rollout that would overspend."""


def read_credits(*, api_key_env: str = "OPENROUTER_API_KEY",
                 timeout_s: float = 20.0) -> tuple[float, float]:
    """``(spent_usd, total_credits_usd)`` for the account. Free, exact, two fields."""
    key = os.environ.get(api_key_env)
    if not key:
        raise RuntimeError(f"{api_key_env} is not set")
    request = urllib.request.Request(
        CREDITS_URL, headers={"Authorization": f"Bearer {key}",
                              "User-Agent": "geos-harness-qual"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        data = json.load(response).get("data", {})
    return float(data.get("total_usage", 0.0)), float(data.get("total_credits", 0.0))


@dataclass
class BudgetGuard:
    """A hard ceiling in dollars, measured against the account, not the transcript.

    ``ceiling_usd`` is spend *from the moment the guard is created*, so it is
    your experiment's budget rather than the account's history.
    """

    ceiling_usd: float
    baseline_usd: float | None = None
    #: Set when the account cannot be read (no key, no network). The guard then
    #: falls back to the transcript estimate, which is wrong but monotone, and
    #: says so every time it is rendered.
    estimated_only: bool = False
    _estimate: float = 0.0

    def __post_init__(self) -> None:
        if self.baseline_usd is None:
            try:
                self.baseline_usd, _ = read_credits()
            except Exception:  # noqa: BLE001 -- degrade, do not block development
                self.baseline_usd = 0.0
                self.estimated_only = True

    def spent(self) -> float:
        if self.estimated_only:
            return self._estimate
        try:
            now, _ = read_credits()
        except Exception:  # noqa: BLE001
            return max(self._estimate, 0.0)
        return max(0.0, now - (self.baseline_usd or 0.0))

    def record_estimate(self, cost: Cost) -> None:
        self._estimate += cost.usd

    def remaining(self) -> float:
        return self.ceiling_usd - self.spent()

    def check(self) -> None:
        """Raise :class:`BudgetExceeded` if another rollout must not start."""
        spent = self.spent()
        if spent >= self.ceiling_usd:
            raise BudgetExceeded(
                f"spent ${spent:.2f} of ${self.ceiling_usd:.2f}"
                + (" (transcript estimate; account unreadable)" if self.estimated_only else "")
            )

    def render(self) -> str:
        spent = self.spent()
        source = "estimated" if self.estimated_only else "billed"
        return (f"budget: ${spent:.2f} / ${self.ceiling_usd:.2f} {source}, "
                f"${self.remaining():.2f} left")


@dataclass
class Ledger:
    """Append-only record of every rollout, and the replay it makes possible."""

    path: Path
    model: str = MODEL
    _rows: dict[tuple, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rows = {}
        if self.path.is_file():
            for line in self.path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._rows[self._key_of(row)] = row

    @staticmethod
    def _key_of(row: dict) -> tuple:
        return (row.get("adapter_id"), row.get("task"), row.get("seed"),
                row.get("model"))

    def key(self, adapter_id: str, task: str, seed: int) -> tuple:
        return (adapter_id, task, seed, self.model)

    def get(self, adapter_id: str, task: str, seed: int) -> Rollout | None:
        row = self._rows.get(self.key(adapter_id, task, seed))
        return _rollout_from_json(row) if row else None

    def append(self, rollout: Rollout) -> None:
        row = rollout.to_json()
        self._rows[self._key_of(row)] = row
        with self.path.open("a") as sink:
            sink.write(json.dumps(row) + "\n")

    def rows(self) -> list[dict]:
        return list(self._rows.values())

    def total_estimated_usd(self) -> float:
        return sum(r.get("cost", {}).get("usd", 0.0) for r in self.rows())

    def log_event(self, event: str, **detail: Any) -> None:
        """Write a decision to the sidecar log. Decisions must be auditable."""
        path = self.path.with_suffix(".decisions.jsonl")
        with path.open("a") as sink:
            sink.write(json.dumps(
                {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "event": event, **detail}) + "\n")


def _rollout_from_json(row: dict) -> Rollout:
    score = row.get("score", {})
    cost = row.get("cost", {})
    return Rollout(
        task=row["task"], adapter_id=row["adapter_id"], seed=row["seed"],
        score=Score(task=score.get("task", row["task"]),
                    value=float(score.get("value", 0.0)),
                    status=score.get("status", "success"),
                    detail=score.get("detail", {})),
        cost=Cost(**{k: v for k, v in cost.items() if k in Cost.__annotations__}),
        workspace=row.get("workspace"), attempts=row.get("attempts", 1),
        error=row.get("error"),
    )
