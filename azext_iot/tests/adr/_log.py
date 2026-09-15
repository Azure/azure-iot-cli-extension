# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Dual-path logging for ADR integration tests.

Emits colored output via ``print()`` when ``PRETTY_LOG=1`` is set in the
environment, escaping characters unsupported by the output stream; otherwise
falls back to plain ``logger.warning()`` for standard pytest log capture.

Usage::

    # ADRLiveScenarioTest.cmd() logs commands automatically.
    _log(L.OK, "Device '%s' found", device_id)

To change the visual style (prefix, color) for any log type, edit only
the ``_STYLES`` dict below.  Call sites never reference prefixes or colors.
"""

import os
import re
import shlex
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import unquote

from knack.log import get_logger

logger = get_logger(__name__)

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
    "_time": ("  Δ ", "dim"),
}

_SECRET_NAMES = {
    "accesskey", "accesstoken", "accountkey", "apikey", "authenticationkey",
    "authorization", "certificate", "clientsecret", "connectionstring",
    "connectionstrings", "credential", "credentials", "key", "keys", "login",
    "password", "primarykey", "privatekey", "sastoken", "sasurl", "secondarykey",
    "secret", "secretkey", "secrets", "sharedaccesskey", "sig", "signature",
    "symmetrickey", "token",
}
_OPAQUE_OPTIONS = {"body", "data", "headers", "parameters", "payload", "properties", "set"}
_SECRET_ASSIGNMENT = re.compile(r"""(?:^|[?&;,\s{'"])([\w.-]+)['"]?\s*[:=]""")


def _argument_name(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower().replace("-", "").replace("_", "")


def _contains_secret(value: str) -> bool:
    decoded = unquote(value)
    return (
        any(_argument_name(match[1]) in _SECRET_NAMES for match in _SECRET_ASSIGNMENT.finditer(decoded))
        or re.search(r"(?i)(?:^|[\s:=])(?:Bearer|Basic|SharedAccessSignature)\s+", decoded) is not None
        or re.search(r"://[^/\s]*@", decoded) is not None
        or "PRIVATE KEY-----" in decoded
    )


def _redact_command(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "az [command omitted: invalid shell quoting]"

    output = []
    redact_next = False
    redact_values = False
    for token in tokens:
        if redact_next:
            output.append("***")
            redact_next = False
            continue
        if token.startswith("-"):
            option, separator, value = token.partition("=")
            sensitive = (
                _argument_name(option) in _SECRET_NAMES | _OPAQUE_OPTIONS
                or option in {"-p", "-k", "--pk", "--sk"}
            )
            redact_values = sensitive
            redact_next = sensitive and not separator
            if separator and (sensitive or _contains_secret(value)):
                output.append(f"{option}=***")
            elif _contains_secret(token):
                output.append("***")
            else:
                output.append(token)
        elif redact_values or _contains_secret(token):
            output.append("***")
        else:
            output.append(token)

    if not output or output[0] != "az":
        output.insert(0, "az")
    return shlex.join(output).replace("\n", r"\n").replace("\r", r"\r").replace("\033", r"\x1b")


def log_command(command: str, expect_failure: bool = False):
    suffix = "  (expect failure)" if expect_failure else ""
    _log(LogKind.CMD, "%s%s", _redact_command(command), suffix)


def _pretty_log_enabled() -> bool:
    return os.environ.get("PRETTY_LOG") == "1"


def _print_pretty(text: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        text = text.encode(encoding, errors="backslashreplace").decode(encoding)
    print(text, flush=True)


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
    if _pretty_log_enabled():
        text = full % args if args else full
        ansi = _ANSI.get(color, "")
        _print_pretty(f"{ansi}{text}{_ANSI_RESET}" if ansi else text)
    else:
        logger.warning(full, *args)


def _raw_log(msg: str = "", *args):
    """Emit a plain log line with no prefix or color."""
    if _pretty_log_enabled():
        text = msg % args if args else msg
        _print_pretty(text)
    else:
        if msg:
            logger.warning(msg, *args)


@contextmanager
def timed_step(label: str, *args):
    """Context manager: logs a step header on entry, elapsed time on exit.

    Usage::

        with timed_step("Step 3 > Refresh group"):
            cmd(...)
    """
    _log(LogKind.STEP, label, *args)
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        _log("_time", "(%s)", _fmt_duration(elapsed))
