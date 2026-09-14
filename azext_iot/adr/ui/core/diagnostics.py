# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Diagnostic logging.

A full-screen UI cannot print, so anything worth diagnosing goes to a file the customer
can tail in another terminal. Off unless a path is given.

This module is deliberately free of any UI framework import.
"""

import logging
import os
from typing import Optional

LOGGER_NAME = "radr"
DEFAULT_LOG_NAME = "radr.log"

_logger = logging.getLogger(LOGGER_NAME)
_logger.addHandler(logging.NullHandler())
_logger.propagate = False


def default_log_path() -> str:
    """Beside the CLI's own configuration, so it is easy to find and easy to clean."""
    base = os.environ.get("AZURE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".azure"
    )
    return os.path.join(base, DEFAULT_LOG_NAME)


def configure(path: Optional[str]) -> Optional[str]:
    """Start file logging. Returns the path in use, or None when logging is off."""
    for handler in list(_logger.handlers):
        if isinstance(handler, logging.FileHandler):
            _logger.removeHandler(handler)
            handler.close()
    if not path:
        return None
    resolved = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    handler = logging.FileHandler(resolved, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    )
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG)
    _logger.info("radr session started; logging to %s", resolved)
    return resolved


def log(message: str, *args) -> None:
    _logger.info(message, *args)


def warn(message: str, *args) -> None:
    _logger.warning(message, *args)


def exception(message: str, *args) -> None:
    _logger.exception(message, *args)
