# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""A quiet, persistent status line. Errors and approvals are never animated."""

from rich.style import Style
from rich.text import Text
from textual.widgets import Static


class FlashLine(Static):
    """One row under the content: errors in the error colour, warnings in amber, notes dim."""

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.text = ""

    def flash(self, message, level="info"):
        self.text = message
        palette = getattr(self.app, "theme_palette", None) or {}
        color = palette.get({"error": "error", "warning": "warning"}.get(level, "dim"), "")
        prefix = "\u2717 " if level == "error" and message else ""
        self.update(Text(prefix + message, style=Style.parse(color), no_wrap=True, overflow="ellipsis"))
