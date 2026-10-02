# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Operations tray.

Almost every Device Registry mutation is a long-running operation, so the UI starts one,
returns immediately, and tracks it here to a terminal state. Nothing in the UI ever blocks
on a poller.

Polling reuses the provider's own terminal-wait helper rather than reimplementing it: that
logic carries the service's async-status workaround and its endpoint-level failure
extraction, and this module is the single place that depends on it.

This module is deliberately free of any UI framework import.
"""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional, Tuple

#: Newest first, and bounded: a long session must not accumulate operations forever.
MAX_TRACKED = 50


class OpState(Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self is not OpState.RUNNING


@dataclass
class Operation:
    """One long-running operation, from initiation to terminal state."""

    id: int
    label: str
    target: str
    command: str = ""
    state: OpState = OpState.RUNNING
    error: Optional[str] = None
    detail: Optional[str] = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: Optional[float] = None
    #: Kinds whose cached data this operation invalidates once it succeeds.
    refreshes: Tuple[str, ...] = ()
    acknowledged: bool = False

    def elapsed(self, now: Optional[float] = None) -> float:
        end = self.finished_at if self.finished_at is not None else (now or time.monotonic())
        return end - self.started_at

    def describe(self, now: Optional[float] = None) -> str:
        seconds = int(self.elapsed(now))
        clock = f"{seconds // 60:02d}:{seconds % 60:02d}"
        if self.state is OpState.RUNNING:
            return f"{self.label} {self.target} - running {clock}"
        if self.state is OpState.SUCCEEDED:
            return f"{self.label} {self.target} - succeeded in {clock}"
        return f"{self.label} {self.target} - failed: {self.error}"


class OperationTracker:
    """Owns the set of tracked operations and drives their pollers.

    Thread-safe: operations are started from the UI thread and completed from workers.
    """

    def __init__(self, provider_waiter: Optional[Callable[[Any], Any]] = None):
        """``provider_waiter`` drives a poller to a terminal state and returns its result."""
        self._waiter = provider_waiter or _reject_missing_waiter
        self._operations: List[Operation] = []
        self._lock = threading.RLock()
        self._next_id = 1

    # -- registration ------------------------------------------------------

    def start(self, label: str, target: str, command: str = "",
              refreshes: Tuple[str, ...] = ()) -> Operation:
        with self._lock:
            operation = Operation(
                id=self._next_id,
                label=label,
                target=target,
                command=command,
                refreshes=tuple(refreshes),
            )
            self._next_id += 1
            self._operations.insert(0, operation)
            del self._operations[MAX_TRACKED:]
            return operation

    # -- completion --------------------------------------------------------

    def await_poller(self, operation: Operation, poller) -> Operation:
        """Drive ``poller`` to a terminal state. Blocking: call from a worker thread.

        A provider that completed inline returns something other than a poller, which is
        treated as immediate success.
        """
        try:
            if poller is not None and hasattr(poller, "result"):
                self._waiter(poller)
            self.succeed(operation)
        except Exception as error:  # noqa: BLE001 - the tray is the boundary for mutations
            self.fail(operation, error)
        return operation

    def succeed(self, operation: Operation) -> None:
        with self._lock:
            operation.state = OpState.SUCCEEDED
            operation.finished_at = time.monotonic()
            operation.error = None

    def fail(self, operation: Operation, error) -> None:
        with self._lock:
            operation.state = OpState.FAILED
            operation.finished_at = time.monotonic()
            operation.error = str(error) or error.__class__.__name__
            operation.detail = getattr(error, "detail", None)

    def acknowledge(self, operation_id: int) -> None:
        """Dismiss a finished operation. Failures persist until this is called."""
        with self._lock:
            for operation in self._operations:
                if operation.id == operation_id:
                    operation.acknowledged = True
                    return

    def prune(self, keep_seconds: float = 6.0, now: Optional[float] = None) -> None:
        """Drop succeeded operations after a moment; keep failures until acknowledged."""
        moment = now if now is not None else time.monotonic()
        with self._lock:
            self._operations = [
                operation
                for operation in self._operations
                if not (
                    operation.state is OpState.SUCCEEDED
                    and operation.finished_at is not None
                    and moment - operation.finished_at >= keep_seconds
                )
                and not (operation.state is OpState.FAILED and operation.acknowledged)
            ]

    # -- queries -----------------------------------------------------------

    @property
    def operations(self) -> List[Operation]:
        with self._lock:
            return list(self._operations)

    @property
    def running(self) -> List[Operation]:
        return [op for op in self.operations if op.state is OpState.RUNNING]

    @property
    def failed(self) -> List[Operation]:
        return [op for op in self.operations if op.state is OpState.FAILED]

    def summary(self, now: Optional[float] = None) -> str:
        operations = self.operations
        if not operations:
            return ""
        running = [op for op in operations if op.state is OpState.RUNNING]
        if running:
            head = running[0].describe(now)
            others = len(running) - 1
            return f"{head} (+{others} more)" if others else head
        return operations[0].describe(now)

    def refresh_targets(self) -> Tuple[str, ...]:
        """Kinds to invalidate for operations that have just succeeded."""
        kinds: List[str] = []
        for operation in self.operations:
            if operation.state is OpState.SUCCEEDED:
                kinds.extend(kind for kind in operation.refreshes if kind not in kinds)
        return tuple(kinds)

    def clear(self) -> None:
        with self._lock:
            self._operations.clear()


def make_session_waiter(session) -> Callable[[Any], Any]:
    """Build a waiter that drives a poller with the providers' own terminal-wait logic.

    Any provider will do: the helper only needs an authenticated client to poll with, and
    the session caches provider instances. This is the single sanctioned use of a
    non-public provider method, isolated here so a future change has one call site
    (design doc section 4.4).
    """

    def wait(poller):
        provider = session.provider("namespace")
        return provider._await_terminal(poller)

    return wait


def _reject_missing_waiter(poller):
    raise RuntimeError(
        "OperationTracker was constructed without a waiter; pass make_session_waiter(session)."
    )
