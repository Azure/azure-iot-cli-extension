# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""CLI entry point for the Device Registry terminal UI (`az iot adr ns ui`).

This module is imported when the command table is built, so it must stay cheap: the UI
framework is imported lazily inside :func:`adr_ui_launch`.
"""

from contextlib import contextmanager, nullcontext
from typing import Optional

from azure.cli.core.azclierror import CLIInternalError

# Single source of truth for the floor; the store enforces the same value at runtime.
from azext_iot.adr.ui.core.store import MIN_INTERVAL_SEC as MIN_REFRESH_INTERVAL_SEC

_TEXTUAL_MISSING_MSG = (
    "The terminal UI requires the 'textual' package, which is missing from this "
    "installation. Reinstall the extension with 'az extension add --name azure-iot "
    "--upgrade', or for a source checkout run 'pip install \"textual>=6.0,<7.0\"'."
)


@contextmanager
def _silence_provider_console():
    """Disable provider Live displays while Textual owns the terminal."""
    from azext_iot.adr.providers.base import console

    quiet, status = console.quiet, console.status
    console.quiet = True
    console.status = lambda *_args, **_kwargs: nullcontext()
    try:
        yield
    finally:
        console.status = status
        console.quiet = quiet


def adr_ui_launch(
    cmd,
    resource_group_name: Optional[str] = None,
    namespace_name: Optional[str] = None,
    read_only: bool = False,
    refresh_interval: Optional[int] = None,
    theme: Optional[str] = None,
    log_file: Optional[str] = None,
):
    """Launch the terminal UI. Returns nothing; the UI owns the terminal until it exits."""
    try:
        from azext_iot.adr.ui.app import RadrApp
    except ModuleNotFoundError as error:  # pragma: no cover - depends on install shape
        missing = str(error.name or "")
        if missing != "textual" and not missing.startswith("textual."):
            raise
        raise CLIInternalError(_TEXTUAL_MISSING_MSG) from error

    from azext_iot.adr.ui.core import diagnostics

    # Under --debug a path is implied: a crash in a full-screen UI is otherwise opaque.
    if not log_file and getattr(getattr(cmd, "cli_ctx", None), "verbosity", 0):
        log_file = diagnostics.default_log_path()
    active_log = diagnostics.configure(log_file)

    interval = max(refresh_interval or MIN_REFRESH_INTERVAL_SEC, MIN_REFRESH_INTERVAL_SEC)
    app = RadrApp(
        cmd=cmd,
        resource_group_name=resource_group_name,
        namespace_name=namespace_name,
        read_only=read_only,
        refresh_interval=interval,
        theme_name=theme,
        log_path=active_log,
    )
    with _silence_provider_console():
        app.run()
