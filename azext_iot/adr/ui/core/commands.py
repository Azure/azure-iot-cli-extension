# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Equivalent-command rendering.

Every action shows the `az` command that does the same thing, before and after it runs.
The command is built from the same argument mapping the action passes to its provider, so
the preview cannot drift from what actually executes (design doc risk R9).

This module is deliberately free of any UI framework import.
"""

import shlex
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: Scope keys mapped to the CLI flags that carry them. Ordered so generated commands read
#: the way the documentation writes them.
_FLAGS: Tuple[Tuple[str, str], ...] = (
    ("namespace_name", "--ns"),
    ("resource_group_name", "-g"),
    ("registry_device_name", "--device"),
    ("certificate_authority_name", "--ca-name"),
    ("group_name", "--group-name"),
    ("job_name", "--job-name"),
    ("endpoint_name", "--endpoint-name"),
    ("authentication_profile_name", "-n"),
    ("attribute_name", "-n"),
    ("run_name", "-n"),
    ("update_instance_name", "-n"),
)
_FLAG_BY_KEY = dict(_FLAGS)
_KEY_ORDER = [key for key, _ in _FLAGS]


def quote(value: Any) -> str:
    """Quote one value for a POSIX shell without permitting expansion."""
    return shlex.quote(str(value))


def render(command: str, name: Optional[str] = None, scope: Optional[Dict[str, Any]] = None,
           options: Optional[Dict[str, Any]] = None, flags: Iterable[str] = ()) -> str:
    """Render one `az` command line.

    ``command`` is the command path without the leading ``az``. ``name`` becomes ``-n``.
    ``scope`` supplies the standard location flags; ``options`` are extra ``--key value``
    pairs; ``flags`` are valueless switches such as ``--yes``.
    """
    parts: List[str] = ["az", command]
    if name is not None:
        parts += ["-n", quote(name)]

    scope = scope or {}
    for key in _KEY_ORDER:
        value = scope.get(key)
        if not value:
            continue
        flag = _FLAG_BY_KEY[key]
        if flag == "-n" and name is not None:
            continue
        parts += [flag, quote(value)]

    for key, value in (options or {}).items():
        if value is None or value == "":
            continue
        parts += [key if key.startswith("-") else f"--{key.replace('_', '-')}", quote(value)]

    parts += list(flags)
    return " ".join(parts)


def wrap(command: str, width: int = 96) -> str:
    """Wrap a long command across lines with shell continuations, for display."""
    if len(command) <= width:
        return command
    tokens = _shell_lexemes(command)
    lines: List[str] = []
    current = tokens[0]
    for token in tokens[1:]:
        # Keep a flag and its value together so a wrapped command stays runnable.
        if len(current) + 1 + len(token) > width and current.strip() and not current.endswith("-n"):
            lines.append(current)
            current = "    " + token
        else:
            current = f"{current} {token}"
    lines.append(current)
    return " \\\n".join(lines)


def _shell_lexemes(command: str) -> List[str]:
    """Split on unquoted whitespace while preserving the original shell syntax."""
    tokens: List[str] = []
    current: List[str] = []
    quote_character = ""
    escaped = False
    for character in command:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\" and quote_character != "'":
            current.append(character)
            escaped = True
            continue
        if quote_character:
            current.append(character)
            if character == quote_character:
                quote_character = ""
            continue
        if character in ("'", '"'):
            quote_character = character
            current.append(character)
            continue
        if character.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(character)
    if current:
        tokens.append("".join(current))
    return tokens
