"""A minimal LLM client for the proposer half of your loop.

Most self-improvement methods need a model somewhere other than inside the
rollout: to write the next primer, to summarise what went wrong, to pick which
component to edit. That model is *not* the frozen agent and does not have to be
the same one. This is a thin wrapper over the OpenRouter chat API -- no
dependencies, no framework, ~60 lines -- so you can see exactly what is sent.

It is a separate budget line, and a small one: a proposer call costs a fraction
of a cent against $0.134 for a rollout. If your proposer spend is visible next
to your rollout spend, something has gone wrong.

One rule that is not optional: **the proposer must never see ground truth.**
Not a reference deck, not a value copied out of one. If it does, your adapter
becomes a place to store the answer and every score after that is meaningless.
``qualkit.scoring.diagnose`` gives you feedback derived only from the generated
deck; use that. See ``docs/CONTAMINATION.md``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API_URL = "https://openrouter.ai/api/v1/chat/completions"

#: The proposer model. Free to differ from the rollout model -- and it is worth
#: asking in your write-up whether it should.
PROPOSER_MODEL = os.environ.get("QUAL_PROPOSER_MODEL", "z-ai/glm-5.3-flash")


class ProposerError(RuntimeError):
    """A proposer call that failed. Never let one kill a search silently."""


@dataclass
class LLM:
    model: str = PROPOSER_MODEL
    api_key_env: str = "OPENROUTER_API_KEY"
    timeout_s: float = 180.0
    max_retries: int = 3
    #: Every call, for the run log. A search whose proposals cannot be read
    #: afterwards cannot be written up.
    transcript: list[dict] = field(default_factory=list)

    def complete(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 4000, temperature: float = 0.7) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProposerError(f"{self.api_key_env} is not set")
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        payload = json.dumps({"model": self.model, "messages": messages,
                              "max_tokens": max_tokens,
                              "temperature": temperature}).encode()
        request = urllib.request.Request(
            API_URL, data=payload,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "User-Agent": "geos-harness-qual"})
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    data = json.load(response)
                text = data["choices"][0]["message"]["content"] or ""
                self.transcript.append({"prompt": prompt, "system": system,
                                        "response": text, "model": self.model,
                                        "usage": data.get("usage", {})})
                return text
            except urllib.error.HTTPError as exc:
                body = exc.read().decode(errors="replace")[:300]
                last = ProposerError(f"HTTP {exc.code}: {body}")
                # 429 is a rate limit, not a bug; back off and try again.
                if exc.code not in (429, 500, 502, 503):
                    break
            except Exception as exc:  # noqa: BLE001
                last = ProposerError(f"{type(exc).__name__}: {exc}")
            time.sleep(2 ** attempt)
        raise last or ProposerError("call failed for an unknown reason")

    def save_transcript(self, path) -> None:
        from pathlib import Path
        Path(path).write_text(json.dumps(self.transcript, indent=2) + "\n")
