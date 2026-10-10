# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""A quiet, persistent status line. Errors and approvals are never animated."""

from rich.text import Text
from textual.widgets import Static


class FlashLine(Static):
    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.text = ""

    def flash(self, message, level="info"):
        self.text = message
        token = {"error": "error", "warning": "warn"}.get(level, "")
        style = getattr(self.app, "theme_tokens", {}).get(token, "")
        self.update(Text(message, style=style))
