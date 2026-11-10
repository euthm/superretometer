"""Operational limits for the merge adapter; no gate or warrant semantics.

The CLI supervises a disposable process group. A slow verifier is bounded just
like a slow recorder, even during CPU-bound JSON validation. Direct Python API
callers must provide their own process supervision.
"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import threading
import time

from .contracts import EvidenceError


DEFAULT_LIMITS = {
    "max_source_files": 10_000,
    "max_receipt_bytes": 16 * 1024 * 1024,
    "operation_timeout_seconds": 900,
}


def limits_for(policy):
    supplied = policy.get("resource_limits", {})
    if not isinstance(supplied, dict) or set(supplied) - DEFAULT_LIMITS.keys():
        raise EvidenceError("resource_limits has unknown fields or is not a mapping")
    limits = {**DEFAULT_LIMITS, **supplied}
    for key, value in limits.items():
        if key == "operation_timeout_seconds":
            valid = type(value) in (int, float) and math.isfinite(value) and value > 0
        else:
            valid = type(value) is int and value > 0
        if not valid:
            raise EvidenceError(f"resource_limits.{key} must be a positive finite "
                                + ("number" if key == "operation_timeout_seconds" else "integer"))
    return limits


def enforce_sources(count, limits):
    if count > limits["max_source_files"]:
        raise EvidenceError(
            f"Source budget exceeded: {count} files > {limits['max_source_files']}. "
            "Review an explicit bounded policy with a rationale, or review higher "
            "resource_limits for full coverage. Coverage was not changed."
        )


def enforce_receipt(size, limits):
    if size > limits["max_receipt_bytes"]:
        raise EvidenceError(
            f"Receipt budget exceeded: {size} bytes > {limits['max_receipt_bytes']}. "
            "Receipt was not parsed. Review resource_limits or create a new capture "
            "under a reviewed bounded policy; do not edit historical receipts."
        )


class Progress:
    """NDJSON diagnostics on stderr; stdout remains a single final JSON result."""
    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stderr
        self.started = time.monotonic()

    def emit(self, phase, **details):
        print(json.dumps({"event": "ch-progress", "phase": phase,
                          "elapsed_seconds": round(time.monotonic() - self.started, 3),
                          **details}, sort_keys=True), file=self.stream, flush=True)


def _stop_group(proc):
    # start_new_session isolates this group from the caller's terminal/session.
    # Kill the whole group, including orphaned test children, not just the worker.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.communicate()


def supervise(command, timeout_seconds, *, progress=None, heartbeat_seconds=5):
    """Return worker stdout/exit only after completion; never publish early approval.

    POSIX process-group supervision is explicit. Unsupported hosts reject rather
    than silently running without the operational deadline. A deadline applies
    after reviewed policy validation, across worker startup/preflight/execution/
    validation/export. OS scheduling and process reap can add cleanup latency.
    """
    if os.name != "posix":
        raise EvidenceError("Merge guard deadline supervision requires a POSIX host")
    if threading.current_thread() is not threading.main_thread():
        raise EvidenceError("Merge guard signal supervision requires the main thread")
    reporter = progress if progress is not None else Progress()
    started = time.monotonic()
    previous_term = signal.getsignal(signal.SIGTERM)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    proc = None
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, start_new_session=True)
        while True:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            try:
                output, _ = proc.communicate(timeout=min(heartbeat_seconds, remaining))
                if time.monotonic() - started > timeout_seconds:
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                return output, proc.returncode
            except subprocess.TimeoutExpired:
                if time.monotonic() - started >= timeout_seconds:
                    raise
                reporter.emit("waiting", worker_pid=proc.pid)
    except subprocess.TimeoutExpired as exc:
        reporter.emit("deadline_exceeded", limit_seconds=timeout_seconds)
        raise EvidenceError(f"Operation deadline exceeded ({timeout_seconds}s); "
                            "worker group stopped, partial artifacts retained, no approval") from exc
    except KeyboardInterrupt as exc:
        reporter.emit("interrupted")
        raise EvidenceError("Operation interrupted; worker group stopped, "
                            "partial artifacts retained, no approval") from exc
    finally:
        try:
            if proc is not None:
                _stop_group(proc)
        finally:
            signal.signal(signal.SIGTERM, previous_term)
