"""Read one rollout: what the agent actually did, where the time went, what it cost.

The single most useful habit in this project is opening a transcript. Almost
every defect in the research pipeline -- eight of them, six sitting between a
rollout and its reported score -- was found by running the thing and reading its
output. None were found by reading code. A score of 0.41 tells you a
configuration is mediocre; the transcript tells you that it spent nineteen turns
grepping for a file that was never there.

So this module exists to make that cheap. ``qual inspect <workspace>`` renders a
finished rollout as:

* the tool mix -- where the turns went, by tool;
* the trace -- every call in order, with its salient argument, so you can watch
  the agent search, guess, write and check;
* which example decks it read, which is the retrieval question in concrete form;
* the deck it produced, scored, with the weakest sections named.

Nothing here is clever. It is a transcript reader, and reading transcripts is
the job.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

#: Tool arguments worth showing, in the order we look for them. A tool call is
#: only legible if you can see what it was called *on*.
_SALIENT = ("command", "file_path", "pattern", "path", "query", "url", "xml_path")


@dataclass
class Call:
    index: int
    tool: str
    detail: str
    timestamp: str | None = None

    def render(self, width: int = 96) -> str:
        detail = self.detail.replace("\n", " ")
        if len(detail) > width:
            detail = detail[: width - 1] + "…"
        return f"  {self.index:>3}  {self.tool:<28} {detail}"


@dataclass
class Trace:
    workspace: Path
    calls: list[Call] = field(default_factory=list)
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    result: dict[str, Any] = field(default_factory=dict)
    tools_offered: list[str] = field(default_factory=list)
    first_ts: str | None = None
    last_ts: str | None = None

    @property
    def tool_mix(self) -> Counter:
        return Counter(call.tool for call in self.calls)

    @property
    def elapsed_seconds(self) -> float | None:
        if not (self.first_ts and self.last_ts):
            return None
        try:
            start = datetime.fromisoformat(self.first_ts.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.last_ts.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (end - start).total_seconds()

    def corpus_reads(self) -> Counter:
        """Which parts of ``/geos_lib`` the agent actually looked at.

        The retrieval question in concrete form: did it find a comparable
        example, or did it author from the prompt alone?
        """
        hits: Counter = Counter()
        for call in self.calls:
            for token in call.detail.split():
                token = token.strip("'\"(),")
                if token.startswith("/geos_lib"):
                    parts = Path(token).parts
                    hits[Path(*parts[:4]).as_posix() if len(parts) > 3 else token] += 1
        return hits


def read_trace(workspace: Path) -> Trace:
    """Parse a rollout workspace's transcript. Tolerant of partial files."""
    workspace = Path(workspace)
    events_path = workspace / "events.jsonl"
    if not events_path.is_file():
        candidates = sorted(workspace.glob("events.attempt*.jsonl"))
        if not candidates:
            raise FileNotFoundError(f"no transcript under {workspace}")
        events_path = candidates[0]

    trace = Trace(workspace=workspace)
    index = 0
    for line in events_path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            trace.tools_offered = list(event.get("tools") or [])
        if event.get("type") == "result":
            trace.result = event
            if "num_turns" in event:
                trace.turns = int(event["num_turns"])
        stamp = event.get("timestamp")
        if stamp:
            trace.first_ts = trace.first_ts or stamp
            trace.last_ts = stamp
        message = event.get("message") or {}
        usage = message.get("usage") or event.get("usage") or {}
        if usage:
            trace.input_tokens += int(usage.get("input_tokens", 0) or 0)
            trace.output_tokens += int(usage.get("output_tokens", 0) or 0)
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            index += 1
            payload = block.get("input") or {}
            detail = next((str(payload[key]) for key in _SALIENT if payload.get(key)),
                          json.dumps(payload)[:200])
            trace.calls.append(Call(index, str(block.get("name", "?")), detail, stamp))
    return trace


def render(trace: Trace, *, full: bool = False, limit: int = 40) -> str:
    """A readable account of one rollout."""
    lines: list[str] = [f"workspace: {trace.workspace}"]
    elapsed = trace.elapsed_seconds
    lines.append(
        f"turns {trace.turns or '?'}   tool calls {len(trace.calls)}   "
        + (f"elapsed {elapsed:.0f}s   " if elapsed else "")
        + f"tokens {trace.input_tokens:,} in / {trace.output_tokens:,} out"
    )
    if trace.result.get("stop_reason"):
        lines.append(f"stop reason: {trace.result['stop_reason']}"
                     + ("   IS_ERROR" if trace.result.get("is_error") else ""))
    if trace.tools_offered:
        lines.append(f"tools offered: {', '.join(sorted(trace.tools_offered))}")

    lines.append("\ntool mix")
    for tool, count in trace.tool_mix.most_common():
        share = 100 * count / max(1, len(trace.calls))
        lines.append(f"  {tool:<32} {count:>4}  {share:4.0f}%")

    reads = trace.corpus_reads()
    lines.append("\nwhat it read from the corpus"
                 + ("" if reads else "  -- nothing. It authored from the prompt alone."))
    for path, count in reads.most_common(12):
        lines.append(f"  {path:<48} {count:>4}")

    shown = trace.calls if full else trace.calls[:limit]
    lines.append(f"\ntrace ({len(shown)} of {len(trace.calls)} calls"
                 + ("" if full else "; --full for all") + ")")
    lines.extend(call.render() for call in shown)

    inputs = trace.workspace / "inputs"
    if inputs.is_dir():
        written = sorted(p.name for p in inputs.rglob("*") if p.is_file())
        lines.append(f"\ndeck written: {', '.join(written) if written else 'NOTHING'}")
    return "\n".join(lines)
