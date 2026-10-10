# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Neutral terminal palettes. Font choice belongs to the terminal, not the application."""

from textual.theme import Theme

DEFAULT_THEME = "dark"
LIGHT_THEME = "light"
HIGH_CONTRAST_THEME = "high-contrast"
DARK_BASE_THEME = "radar-dark"
LIGHT_BASE_THEME = "radar-light"
HIGH_CONTRAST_BASE_THEME = "textual-ansi"

_DARK_PALETTE = {
    "background": "#0e1014", "panel": "#0e1014", "panel_border": "#262b33",
    "text": "#d7dae0", "dim": "#8b929c", "accent": "#7cc4fa",
    "selected_bg": "#161b22", "selected_fg": "#7cc4fa", "column": "#8b929c",
    "success": "#d7dae0", "warning": "#e3b341", "error": "#f47067",
    "title_bg": "#0e1014", "title_fg": "#d7dae0", "do_bg": "#161b22", "do_fg": "#d7dae0",
}
_LIGHT_PALETTE = dict(_DARK_PALETTE, background="#fafafa", panel="#fafafa",
                      text="#20252b", dim="#535b65", accent="#245f8e",
                      selected_bg="#e5edf3", selected_fg="#245f8e", success="#20252b",
                      warning="#805b00", error="#a03030")
PALETTES = {DEFAULT_THEME: _DARK_PALETTE, LIGHT_THEME: _LIGHT_PALETTE}


def _make_theme(name, palette, dark):
    return Theme(
        name=name, primary=palette["accent"], secondary=palette["accent"], accent=palette["accent"],
        foreground=palette["text"], background=palette["background"], surface=palette["panel"],
        panel=palette["panel"], success=palette["success"], warning=palette["warning"],
        error=palette["error"], dark=dark,
    )


RADR_DARK_THEME = _make_theme(DARK_BASE_THEME, _DARK_PALETTE, True)
RADR_LIGHT_THEME = _make_theme(LIGHT_BASE_THEME, _LIGHT_PALETTE, False)
RADR_THEMES = (RADR_DARK_THEME, RADR_LIGHT_THEME)
THEMES = {
    name: {"ok": palette["success"], "warn": palette["warning"], "error": palette["error"],
           "muted": palette["dim"], "active": palette["accent"]}
    for name, palette in PALETTES.items()
}
THEMES[HIGH_CONTRAST_THEME] = {
    "ok": "white", "warn": "bold yellow", "error": "bold red", "muted": "white", "active": "bold cyan",
}


def normalize_theme(name=None):
    value = (name or DEFAULT_THEME).strip().lower()
    return value if value in THEMES else DEFAULT_THEME


def base_theme_for(name=None):
    return {DEFAULT_THEME: DARK_BASE_THEME, LIGHT_THEME: LIGHT_BASE_THEME,
            HIGH_CONTRAST_THEME: HIGH_CONTRAST_BASE_THEME}[normalize_theme(name)]


def resolve_theme(name=None):
    return THEMES[normalize_theme(name)]


def resolve_palette(name=None):
    if normalize_theme(name) == HIGH_CONTRAST_THEME:
        return dict.fromkeys(_DARK_PALETTE, "white")
    return PALETTES[normalize_theme(name)]


def style_for(token, theme=None):
    return (theme or THEMES[DEFAULT_THEME]).get(token, "")


APP_CSS = """
Screen { layout: vertical; background: $background; color: $foreground; }
#selectors { height: 1; margin: 1 2 0 2; }
#selectors Button {
    height: 1; min-width: 0; width: auto; border: none;
    background: $background; padding: 0 1; margin: 0 1 0 0;
}
#namespace-selector { max-width: 40%; }
#resource-selector { max-width: 35%; }
#operations { dock: right; }
#context-bar { height: 2; margin: 0 3; color: $text-muted; }
#browse-body { height: 1fr; margin: 0 2; }
#rows-pane { height: 1fr; border: none; }
DataTable { height: 1fr; background: $background; color: $foreground; }
DataTable > .datatable--header { background: $background; color: $text-muted; text-style: none; }
DataTable > .datatable--cursor { background: $primary 12%; color: $primary; text-style: bold; }
DataTable:focus > .datatable--cursor { background: $primary 20%; color: $primary; text-style: bold; }
DataTable > .datatable--hover { background: $primary 8%; }
#status-line { height: auto; max-height: 3; color: $text-muted; }
#filter-input { height: 3; }
#flash-line { height: auto; max-height: 3; margin: 0 2; }
Footer { background: $background; }
FooterKey { background: $background; }
FooterKey .footer-key--key { background: $background; color: $primary; }
FooterKey .footer-key--description { background: $background; color: $text-muted; }
VerticalScroll { height: 1fr; padding: 0 2; }
#json-body { height: auto; }
ModalScreen { align: center middle; background: $background 70%; }
#help-body, ModalBox {
    width: 72; max-width: 96%; height: auto; max-height: 90%;
    background: $surface; border: solid $panel; padding: 1 2;
}
.modal-title { text-style: bold; margin-bottom: 1; }
.modal-buttons { height: 3; margin-top: 1; dock: bottom; background: $surface; }
#help-body > #close { dock: bottom; }
Button { height: 3; min-width: 10; background: $background; border: tall $panel; }
Button:focus { color: $primary; text-style: bold; border: tall $primary; }
Button:hover { background: $primary 12%; }
#selectors Button:focus { background: $primary 20%; text-style: bold; }
Button.-primary { background: $primary; color: $background; }
Input { border: tall $panel; background: $background; }
Input:focus { border: tall $primary; }
OptionList { height: auto; max-height: 12; border: none; background: $background; }
OptionList > .option-list--option-highlighted { background: $primary 20%; color: $primary; }
#form-error { height: auto; color: $error; }
"""
