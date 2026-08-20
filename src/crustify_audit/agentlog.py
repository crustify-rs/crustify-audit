"""agentlog.py — per-agent transcript + usage.

Minimal by comparison with crustify-cli's, which has to reconcile usage across
a wave of concurrent agents. One agent means one file and one usage record, so
this is a context manager over two paths and nothing more.

Cost is computed from token counts by a rate table, never from
provider-reported dollars -- the same rule crustify-cli's log_cost.py follows,
for the same reason: providers report post-discount figures that are not
comparable across runs.
"""
from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path


class AgentLog:
    def __init__(self, stem: Path) -> None:
        self.stem = stem
        self.transcript = stem.with_suffix(".log")
        self.usage = stem.with_suffix(".usage.json")
        self._fh = None
        self._started = time.time()

    def write(self, text: str) -> None:
        if self._fh is not None:
            self._fh.write(text)
            self._fh.flush()

    def record_usage(self, rows: list[dict], session_id: str = "") -> None:
        self.usage.write_text(json.dumps({
            "session_id": session_id,
            "started_at": self._started,
            "ended_at": time.time(),
            "records": rows,
        }, indent=2) + "\n")


@contextlib.contextmanager
def open_agent_log(logs_dir: Path, stage: str):
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log = AgentLog(logs_dir / f"{stage}-{stamp}")
    log._fh = log.transcript.open("w")
    try:
        yield log
    finally:
        if log._fh:
            log._fh.close()
