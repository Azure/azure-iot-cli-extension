# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Neutral terminal palettes. Font choice belongs to the terminal, not the application."""

from textual.theme import Theme

DEFAULT_THEME = "terminal"
DARK_THEME = "dark"
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
    # Minimal design tokens (ADR_RADAR_MINIMAL_PREVIEW.html): faint rules, dialog surface,
    # hover wash, text on the accent pill, input placeholders and separators.
    "faint": "#262b33", "dialog": "#12151b", "hover": "#13171d", "on_accent": "#071018",
    "placeholder": "#5b626c", "separator": "#4a515b", "backdrop": "#000000",
}
_LIGHT_PALETTE = dict(_DARK_PALETTE, background="#fafafa", panel="#fafafa", panel_border="#d5d9de",
                      text="#20252b", dim="#535b65", accent="#245f8e",
                      selected_bg="#e5edf3", selected_fg="#245f8e", success="#20252b",
                      warning="#805b00", error="#a03030", faint="#d5d9de", dialog="#f2f3f5",
                      hover="#eef1f4", on_accent="#ffffff", placeholder="#8a9099",
                      separator="#b0b6bd", title_bg="#fafafa", title_fg="#20252b",
                      do_bg="#e5edf3", do_fg="#20252b")
_TERMINAL_PALETTE = dict.fromkeys(_DARK_PALETTE, "default")
# Rich "default" foreground is resolved to RGB by Textual 6; leave it unset to inherit ANSI CSS.
_TERMINAL_PALETTE.update(dict.fromkeys(
    ("text", "dim", "column", "title_fg", "do_fg", "placeholder", "separator"), ""))
_TERMINAL_PALETTE.update(
    accent="blue", selected_fg="blue", success="green", warning="yellow", error="red",
    faint="blue", panel_border="blue",
)
PALETTES = {DEFAULT_THEME: _TERMINAL_PALETTE, DARK_THEME: _DARK_PALETTE, LIGHT_THEME: _LIGHT_PALETTE}


def _css_color(color):
    return color if color.startswith("#") else "ansi_" + (color or "default")


def css_variables(palette):
    """Radar CSS variables; injected for every theme so the stylesheet always resolves."""
    return {
        name: _css_color(palette[key]) for name, key in (
            ("radar-dim", "dim"), ("radar-faint", "faint"),
            ("radar-sel", "selected_bg"), ("radar-dialog", "dialog"),
            ("radar-hover", "hover"), ("radar-on-accent", "on_accent"),
            ("radar-placeholder", "placeholder"), ("radar-backdrop", "backdrop"),
        )
    }


def _make_theme(name, palette, dark):
    return Theme(
        name=name, primary=palette["accent"], secondary=palette["accent"], accent=palette["accent"],
        foreground=palette["text"], background=palette["background"], surface=palette["panel"],
        panel=palette["panel"], success=palette["success"], warning=palette["warning"],
        error=palette["error"], dark=dark, variables=dict(
            css_variables(palette),
            **{
                "block-cursor-background": palette["selected_bg"], "block-cursor-foreground": palette["text"],
                "block-cursor-text-style": "none", "block-cursor-blurred-background": palette["selected_bg"],
                "block-cursor-blurred-foreground": palette["text"], "block-cursor-blurred-text-style": "none",
                "block-hover-background": palette["hover"], "input-cursor-background": palette["text"],
                "input-cursor-foreground": palette["background"], "input-selection-background": palette["selected_bg"],
                "scrollbar": palette["faint"], "scrollbar-hover": palette["dim"], "scrollbar-active": palette["dim"],
                "scrollbar-background": palette["background"], "scrollbar-background-hover": palette["background"],
                "scrollbar-background-active": palette["background"], "scrollbar-corner-color": palette["background"],
                "button-focus-text-style": "bold", "footer-background": palette["background"],
            }
        ),
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
    return {DEFAULT_THEME: "textual-ansi", DARK_THEME: DARK_BASE_THEME, LIGHT_THEME: LIGHT_BASE_THEME,
            HIGH_CONTRAST_THEME: HIGH_CONTRAST_BASE_THEME}[normalize_theme(name)]


def next_theme(name):
    return {DEFAULT_THEME: DARK_THEME, DARK_THEME: LIGHT_THEME, LIGHT_THEME: DEFAULT_THEME}[name]


def resolve_theme(name=None):
    return THEMES[normalize_theme(name)]


def resolve_palette(name=None):
    if normalize_theme(name) == HIGH_CONTRAST_THEME:
        palette = dict.fromkeys(_DARK_PALETTE, "white")
        palette.update(dict.fromkeys(
            ("background", "panel", "selected_bg", "title_bg", "do_bg", "dialog", "hover",
             "on_accent", "backdrop"), "black"))
        return palette
    return PALETTES[normalize_theme(name)]


def style_for(token, theme=None):
    return (theme or THEMES[DEFAULT_THEME]).get(token, "")


#: Width of the centred flow, in cells. The approved preview measures ~91 cells of content at
#: 8.4px per cell (max-width 96ch less its padding); 92 places table columns where it does.
FRAME_WIDTH = 92

# The minimal layout: one centred FRAME_WIDTH-column flow (full width minus 2-column margins on narrower
# terminals). Header, title, content and the key line are single rows separated by single blank
# rows; nothing is boxed except dialogs. Default Textual chrome (footer, tall borders, tinted
# surfaces, block buttons) is deliberately overridden here.
APP_CSS = """
Screen { layout: vertical; background: $background; color: $foreground; }
Screen:ansi { scrollbar-color: ansi_blue; }
ChromeScreen { padding: 0 2; align-horizontal: center; overflow: hidden hidden; }
#frame { width: __FRAME_WIDTH__; max-width: 100%; height: 100%; layout: vertical; }
#header { height: 1; margin-bottom: 1; }
#resource-selector { width: auto; height: 1; }
#context { width: 1fr; height: 1; }
#namespace-selector, #group-selector { width: auto; height: 1; text-wrap: nowrap; }
#subscription-selector { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
.ctx:hover, #resource-selector:hover, #operations:hover { text-style: underline; }
#operations { width: auto; height: 1; padding-left: 2; }
#title-row { height: 1; margin-bottom: 1; }
#title-line { width: auto; height: 1; text-wrap: nowrap; }
#title-tail { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
/* Page controls name their accelerator ("a actions"); focus shows as the selection tint, the
   same cue as the table cursor, so the keyboard position is always visible. */
.page-control { width: auto; height: 1; margin-left: 3; text-wrap: nowrap; }
.page-control:hover { text-style: underline; }
Clickable:focus { background: $radar-sel; text-style: underline; }
Clickable:ansi:focus { text-style: bold reverse; }
#content { height: auto; margin-bottom: 1; scrollbar-size-vertical: 1; }
#flash-line { height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
#keys-line { height: 1; margin-top: 1; }
/* The search field sits at the right end of the title row: a quiet "/ search …" until used. */
#search-mark { width: 2; height: 1; }
#filter-input { width: 30; max-width: 40%; height: 1; border: none; padding: 0; background: $background; }
#filter-input:focus { border: none; background-tint: transparent 0%; }
#empty-line { height: 1; padding-left: 2; color: $radar-dim; }
DataTable { height: auto; background: $background; color: $foreground; scrollbar-size-vertical: 1; }
DataTable:focus { background-tint: transparent 0%; }
DataTable > .datatable--header, DataTable:focus > .datatable--header {
    background: $background; color: $radar-dim; text-style: none; background-tint: transparent 0%;
}
DataTable > .datatable--cursor, DataTable:focus > .datatable--cursor {
    background: $radar-sel; color: $foreground; text-style: none;
}
DataTable > .datatable--hover { background: $radar-hover; }
DataTable:ansi > .datatable--cursor, DataTable:ansi:focus > .datatable--cursor { text-style: bold reverse; }
DataTable:ansi > .datatable--hover { text-style: underline; }
DataTable > .datatable--header-hover { background: $background; }
DataTable > .datatable--even-row, DataTable:dark > .datatable--even-row { background: $background; }
.detail-name { height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
.detail-fields { height: auto; }
.detail-label { height: 1; margin-top: 1; color: $radar-dim; }
#detail-links { height: auto; }
#detail-links .link-row { height: 1; }
#detail-links Clickable { width: auto; height: 1; margin-right: 3; }
#detail-read { height: auto; }
#json-body { height: auto; margin-top: 1; }
#operation-rows { height: auto; }
/* Same 1-cell gutter as the table: blank until selected, then the accent bar on the selection
   tint (the preview's inset 2px accent shadow). */
OperationRow { height: auto; margin-bottom: 1; border-left: blank; }
OperationRow .op-mark { width: 14; height: 1; }
OperationRow .op-body { width: 1fr; height: auto; }
#ops-note { height: auto; }
OperationRow.-selected { background: $radar-sel; border-left: wide $primary; }
OperationRow:hover { background: $radar-hover; }
OperationRow.-selected:hover { background: $radar-sel; }
OperationRow:ansi.-selected { text-style: bold; }

ModalScreen { align: center middle; background: $radar-backdrop 53%; padding: 0; }
ModalScreen:ansi { background: ansi_default; }
/* One surface with one line: the frame is filled and owns the rounded border, the inner scroll
   area is transparent, so there is no second band between the line and the fill. */
.dialog-frame {
    width: 64; max-width: 100%; height: auto; max-height: 100%;
    background: $radar-dialog; border: round $radar-faint; padding: 0;
}
.dialog {
    width: 100%; height: auto; max-height: 100%;
    background: $radar-dialog; padding: 1 2;
    scrollbar-size-vertical: 1; scrollbar-background: $radar-dialog;
}
.dialog Static, .dialog Label { background: $radar-dialog; }
.dialog-title { height: 1; text-style: bold; text-wrap: nowrap; text-overflow: ellipsis; }
.dialog-context { height: auto; color: $radar-dim; }
.dialog-gap { height: 1; }
.dialog-text { height: auto; margin-top: 1; }
.dialog-note { height: auto; margin-top: 1; color: $radar-dim; }
.dialog-hint { height: 1; margin-top: 1; color: $radar-dim; }
.dialog-command { height: auto; margin-top: 1; }
.field-row { height: 2; margin-top: 1; }
.field-label { width: 16; height: 1; }
.field-hint { height: 1; padding-left: 16; color: $radar-dim; }
.dialog Input {
    height: 2; border: none; border-bottom: wide $radar-faint; padding: 0;
    background: $radar-dialog; width: 1fr;
}
.dialog Input:focus { border: none; border-bottom: wide $primary; background-tint: transparent 0%; }
Input > .input--placeholder { color: $radar-placeholder; }
#command-input { margin-top: 0; width: 100%; height: 2; }
#resource-options { margin-top: 0; }
#list-more { height: 1; color: $radar-dim; }
#scope-tabs { height: 1; margin-top: 1; }
.scope-tab { width: auto; height: 1; margin-right: 3; text-wrap: nowrap; }
.scope-tab:hover, #scope-status:hover { text-style: underline; }
#scope-input { margin-top: 1; width: 100%; height: 2; }
#scope-options { margin-top: 0; }
#scope-status, #scope-context { height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
ScopeDialog .dialog-buttons { height: 1; padding-top: 0; }
CommandBar .dialog-buttons { height: 1; padding-top: 0; }
.dialog-buttons { height: 2; padding-top: 1; dock: bottom; background: $radar-dialog; }
.dialog-buttons KeysLine { width: 1fr; background: $radar-dialog; }
.dialog-buttons Static { width: 1fr; height: 1; color: $radar-dim; padding: 0; text-wrap: nowrap;
                         text-overflow: ellipsis; }
Button {
    height: 1; min-width: 0; width: auto; border: none; padding: 0 1; margin: 0 2 0 0;
    background: $radar-dialog; color: $foreground; text-style: none;
}
Button:hover { background: $radar-hover; border: none; }
Button:focus { text-style: bold underline; background: $radar-sel; background-tint: transparent 0%; }
Button.-active { background: $radar-sel; border: none; tint: transparent 0%; }
Button.-primary { background: $primary; color: $radar-on-accent; text-style: bold; border: none; }
Button.-primary:hover { background: $primary; border: none; }
Button.-primary:focus { background: $primary; text-style: bold underline; }
Button:ansi:focus, Button:ansi.-active { background: ansi_default; color: ansi_default; text-style: bold reverse; }
Button:ansi.-primary { background: ansi_default; color: ansi_blue; text-style: bold underline; }
Button:ansi.-primary:focus { color: ansi_default; text-style: bold reverse; }
Button:disabled, Button.-primary:disabled {
    background: $radar-faint; color: $radar-dim; text-style: none; text-opacity: 100%;
}
OptionList {
    height: auto; max-height: 14; border: none; padding: 0; margin-top: 1; background: $radar-dialog;
    scrollbar-size-vertical: 0;
}
OptionList:focus { border: none; background-tint: transparent 0%; }
OptionList > .option-list--option { padding: 0; }
OptionList > .option-list--option-highlighted, OptionList:focus > .option-list--option-highlighted {
    background: $radar-sel; color: $foreground; text-style: none;
}
OptionList > .option-list--option-hover { background: $radar-hover; }
OptionList:ansi > .option-list--option-highlighted { text-style: bold reverse; }
OptionList:ansi > .option-list--option-hover { text-style: underline; }
OptionList > .option-list--option-disabled { color: $radar-placeholder; }
#form-error { height: auto; margin-top: 1; color: $error; }
.help-rows { height: auto; }
""".replace("__FRAME_WIDTH__", str(FRAME_WIDTH))
