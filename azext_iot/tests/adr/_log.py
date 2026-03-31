# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Dual-path logging for ADR integration tests.

Emits colored output via ``print()`` when ``PRETTY_LOG=1`` is set in the
environment; otherwise falls back to plain ``logger.warning()`` for standard
pytest log capture.

Usage::

    _log(L.CMD, "az %s", some_cmd)
    _log(L.OK, "Device '%s' found", device_id)

To change the visual style (prefix, color) for any log type, edit only
the ``_STYLES`` dict below.  Call sites never reference prefixes or colors.
"""

import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from knack.log import get_logger

logger = get_logger(__name__)

_PRETTY_LOG = os.environ.get("PRETTY_LOG")

_ANSI_RESET = "\033[0m"
_ANSI = {
    "gold": "\033[38;2;202;157;100m",  # #CA9D64 Earthsong yellow – sandy gold
    "sage": "\033[38;2;153;166;103m",  # #99A667 Earthsong green – sage olive
    "sky": "\033[38;2;116;175;198m",   # #74AFC6 soft steel blue – commands
    "terra": "\033[38;2;181;92;56m",    # #B55C38 Earthsong red – terracotta
    "clay": "\033[38;2;170;163;155m",  # #AAA39B Earthsong light warm gray – output
    "dim": "\033[38;2;84;74;70m",     # #544A46 Earthsong bright black – warm gray
}


class LogKind:
    """Log-type constants for ``_log()``.  Use these instead of raw strings."""
    TEST = "test"
    STEP = "step"
    CMD = "cmd"
    RESULT = "result"
    OK = "ok"
    WARN = "warn"


_STYLES = {
    LogKind.TEST: ("▶ TEST: ", "gold"),
    LogKind.STEP: ("", "gold"),
    LogKind.CMD: ("  › ", "sky"),
    LogKind.RESULT: ("  ↳ ", "clay"),
    LogKind.OK: ("  ✓ ", "sage"),
    LogKind.WARN: ("  ⚠ ", "terra"),
    # internal-only styles (not exposed via L, used by helpers below)
    "_pass": ("✓ PASS ", "sage"),
    "_fail": ("✗ FAIL ", "terra"),
    "_time": ("  ⏱ ", "dim"),
}


def _ts() -> str:
    """Return current UTC timestamp as a short string for log lines."""
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _fmt_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m{secs:.0f}s"


def _log(kind: str, msg: str = "", *args):
    """Unified log function.  *kind* must be an ``L.*`` constant or internal key.

    Special behaviour by kind:
    - ``L.TEST``: emits a blank line before the message.
    - ``L.STEP``: emits a blank line and appends ``· HH:MM:SS`` timestamp.

    Raises ``ValueError`` for unknown *kind* values (catches typos immediately).
    """
    style = _STYLES.get(kind)
    if style is None:
        raise ValueError(f"Unknown log type: {kind!r}. Use an L.* constant.")
    prefix, color = style

    # Special pre-processing per kind
    if kind in (LogKind.TEST, LogKind.STEP):
        _raw_log("")  # blank separator line
    if kind == LogKind.STEP:
        text = msg % args if args else msg
        msg = f"{text} · {_ts()}"
        args = ()

    full = prefix + msg
    if _PRETTY_LOG:
        text = full % args if args else full
        ansi = _ANSI.get(color, "")
        print(f"{ansi}{text}{_ANSI_RESET}", flush=True) if ansi else print(text, flush=True)
    else:
        logger.warning(full, *args)


def _raw_log(msg: str = "", *args):
    """Emit a plain log line with no prefix or color."""
    if _PRETTY_LOG:
        text = msg % args if args else msg
        print(text, flush=True)
    else:
        if msg:
            logger.warning(msg, *args)


@contextmanager
def timed_step(label: str, *args):
    """Context manager: logs a step header on entry, elapsed time on exit.

    Usage::

        with timed_step("Step 3 ❯ Sync credentials"):
            cmd(...)
    """
    _log(LogKind.STEP, label, *args)
    start = time.monotonic()
    yield
    elapsed = time.monotonic() - start
    _log("_time", "(%s)", _fmt_duration(elapsed))
