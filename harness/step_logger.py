"""
step_logger.py — append-only JSONL logger for one agent run against one target.

The harness (OpenCode wrapper) calls `log_step(...)` once per agent action. Each
line is a self-contained JSON record, so a run file is streamable and crash-safe.
The scorer (scorer.py) consumes these files; keep the schema stable.

Design notes:
  - We log the *cumulative token count* at each step so success/failure can be
    plotted against context pressure (the "saturation boundary").
  - We hash stdout/stderr instead of storing them verbatim: this keeps run files
    small AND gives a cheap near-duplicate signal for loop detection (identical
    hash on consecutive steps == no state change).
  - `ground_truth_cmd` (optional) lets the scorer compare an emitted command
    against a known-good reference for command-validity scoring.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional


def _sha1(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8", "replace")).hexdigest()


@dataclass
class StepRecord:
    run_id: str
    step: int
    ts: float                      # epoch seconds
    target: str                    # e.g. "sqli-labs" / "dvwa@high" / "waf-sqli"
    command: str                   # raw command the agent emitted
    tool: str                      # "sqlmap" | "curl" | "shell" | ...
    exit_code: Optional[int]
    cumulative_tokens: int         # prompt+completion tokens consumed so far
    stdout_sha1: str
    stderr_sha1: str
    stdout_len: int
    stderr_len: int
    command_valid: Optional[bool] = None   # harness/scorer may fill this in
    note: str = ""
    extra: dict = field(default_factory=dict)


class RunLogger:
    def __init__(self, out_dir: str, target: str, model: str,
                 run_id: Optional[str] = None, condition: str = ""):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.target = target
        self.model = model
        self.condition = condition
        self.step = 0
        os.makedirs(out_dir, exist_ok=True)
        self.path = os.path.join(out_dir, f"run_{self.run_id}.jsonl")
        # First line is a run header so the scorer knows model/target/condition
        # without args. `condition` is what separates blind / informed / oneshot
        # when analyze.py groups runs, so keep it in the header.
        self._write({
            "type": "header",
            "run_id": self.run_id,
            "target": target,
            "model": model,
            "condition": condition,
            "ts_start": time.time(),
        })

    def _write(self, obj: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def log_step(
        self,
        command: str,
        tool: str,
        cumulative_tokens: int,
        stdout: str = "",
        stderr: str = "",
        exit_code: Optional[int] = None,
        command_valid: Optional[bool] = None,
        note: str = "",
        **extra,
    ) -> StepRecord:
        self.step += 1
        rec = StepRecord(
            run_id=self.run_id,
            step=self.step,
            ts=time.time(),
            target=self.target,
            command=command,
            tool=tool,
            exit_code=exit_code,
            cumulative_tokens=cumulative_tokens,
            stdout_sha1=_sha1(stdout),
            stderr_sha1=_sha1(stderr),
            stdout_len=len(stdout or ""),
            stderr_len=len(stderr or ""),
            command_valid=command_valid,
            note=note,
            extra=extra,
        )
        self._write({"type": "step", **asdict(rec)})
        return rec

    def log_probe(self, after_tokens: int, retained, question: str = "",
                  facts_known: Optional[int] = None) -> None:
        """Amnesia checkpoint (family 2): did the agent still hold a key fact here?

        Called by the harness at every PROBE_EVERY-token boundary.
          `retained`    True/False if a fact was established and (not) recalled;
                        None when nothing had been discovered yet to retain.
          `facts_known` how many ground-truth facts existed at this checkpoint, so
                        the scorer can measure retention ONLY over probes where
                        there was something to forget (None/0 => not measurable).
        Collapsing None->False here would make every fact-less probe look like
        amnesia, so the tri-state is preserved on disk."""
        self._write({
            "type": "probe",
            "run_id": self.run_id,
            "step": self.step,
            "after_tokens": after_tokens,
            "retained": (None if retained is None else bool(retained)),
            "facts_known": facts_known,
            "question": question,
        })

    def finish(self, success: bool, reason: str = "") -> None:
        """Mark the run outcome. `success` = ground-truth flag/row extracted."""
        self._write({
            "type": "footer",
            "run_id": self.run_id,
            "ts_end": time.time(),
            "steps": self.step,
            "success": bool(success),
            "reason": reason,
        })


if __name__ == "__main__":
    # Tiny smoke test so the file is runnable on its own.
    import tempfile

    tmp = tempfile.mkdtemp(prefix="bench_runs_")
    log = RunLogger(tmp, target="sqli-labs", model="qwen2.5-coder-7b")
    log.log_step("sqlmap -u http://172.20.0.11/Less-1/?id=1 --batch --dbs",
                 tool="sqlmap", cumulative_tokens=1200, stdout="available databases [2]:",
                 exit_code=0, command_valid=True)
    log.log_step("sqlmap -u http://172.20.0.11/Less-1/?id=1 --batch --dbs",  # duplicate -> loop
                 tool="sqlmap", cumulative_tokens=2600, stdout="available databases [2]:",
                 exit_code=0, command_valid=True)
    log.finish(success=True, reason="extracted users table")
    print("wrote", log.path)
