# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Themes: style tokens and application stylesheet.

`core` emits abstract style tokens (``ok``, ``warn``, ``error``...) rather than colours, so
the model layer stays presentation-free and a theme can be swapped without touching it.

Accessibility: colour is never the only signal. Status columns carry their state as text,
and the high-contrast theme is provided for low-colour or low-vision use.
"""

from typing import Dict

from textual.theme import Theme

from azext_iot.adr.ui.core.spec import (
    STYLE_ACTIVE,
    STYLE_ERROR,
    STYLE_MUTED,
    STYLE_OK,
    STYLE_WARN,
)

DEFAULT_THEME = "dark"
LIGHT_THEME = "light"
HIGH_CONTRAST_THEME = "high-contrast"

#: Exact visual roles supplied for radr. Rich-rendered widgets use these directly; the
#: Textual themes below map the same roles onto standard CSS variables.
_DARK_PALETTE = {
    "background": "#1C2128",
    "panel": "#22272E",
    "panel_border": "#373E47",
    "title_bg": "#3B4655",
    "title_fg": "#F0F3F6",
    "text": "#DADFE7",
    "dim": "#768390",
    "accent": "#78A9C8",
    "column": "#7294AE",
    "do_bg": "#2D333B",
    "do_fg": "#E6EDF3",
    "selected_bg": "#343B44",
    "selected_fg": "#F0F3F6",
    "success": "#8FAF8B",
    "warning": "#C7A56A",
    "error": "#C46F79",
}

_LIGHT_PALETTE = {
    "background": "#ECEFF4",
    "panel": "#F7F9FB",
    "panel_border": "#D6DCE5",
    "title_bg": "#5E81AC",
    "title_fg": "#ECEFF4",
    "text": "#2E3440",
    "dim": "#7A869A",
    "accent": "#5E81AC",
    "column": "#4C6E96",
    "do_bg": "#D8DEE9",
    "do_fg": "#2E3440",
    "selected_bg": "#CBD5E1",
    "selected_fg": "#2E3440",
    "success": "#5E7A45",
    "warning": "#96702A",
    "error": "#A6474F",
}

PALETTES = {
    DEFAULT_THEME: _DARK_PALETTE,
    LIGHT_THEME: _LIGHT_PALETTE,
}

DARK_BASE_THEME = "radr-night"
LIGHT_BASE_THEME = "radr-daylight"
HIGH_CONTRAST_BASE_THEME = "textual-ansi"

RADR_DARK_THEME = Theme(
    name=DARK_BASE_THEME,
    primary=_DARK_PALETTE["accent"],
    secondary=_DARK_PALETTE["column"],
    accent=_DARK_PALETTE["accent"],
    warning=_DARK_PALETTE["warning"],
    error=_DARK_PALETTE["error"],
    success=_DARK_PALETTE["success"],
    foreground=_DARK_PALETTE["text"],
    background=_DARK_PALETTE["background"],
    surface=_DARK_PALETTE["panel"],
    panel=_DARK_PALETTE["panel_border"],
    boost=_DARK_PALETTE["selected_bg"],
    dark=True,
    luminosity_spread=0.10,
    variables={
        "success": _DARK_PALETTE["success"],
        "warning": _DARK_PALETTE["warning"],
        "error": _DARK_PALETTE["error"],
        "text": _DARK_PALETTE["text"],
        "text-muted": _DARK_PALETTE["dim"],
        "primary-darken-1": _DARK_PALETTE["title_bg"],
        "primary-background": _DARK_PALETTE["title_fg"],
        "secondary-background": _DARK_PALETTE["do_bg"],
        "foreground-lighten-1": _DARK_PALETTE["do_fg"],
    },
)

RADR_LIGHT_THEME = Theme(
    name=LIGHT_BASE_THEME,
    primary=_LIGHT_PALETTE["accent"],
    secondary=_LIGHT_PALETTE["column"],
    accent=_LIGHT_PALETTE["accent"],
    warning=_LIGHT_PALETTE["warning"],
    error=_LIGHT_PALETTE["error"],
    success=_LIGHT_PALETTE["success"],
    foreground=_LIGHT_PALETTE["text"],
    background=_LIGHT_PALETTE["background"],
    surface=_LIGHT_PALETTE["panel"],
    panel=_LIGHT_PALETTE["panel_border"],
    boost=_LIGHT_PALETTE["selected_bg"],
    dark=False,
    luminosity_spread=0.10,
    variables={
        "success": _LIGHT_PALETTE["success"],
        "warning": _LIGHT_PALETTE["warning"],
        "error": _LIGHT_PALETTE["error"],
        "text": _LIGHT_PALETTE["text"],
        "text-muted": _LIGHT_PALETTE["dim"],
        "primary-darken-1": _LIGHT_PALETTE["title_bg"],
        "primary-background": _LIGHT_PALETTE["title_fg"],
        "secondary-background": _LIGHT_PALETTE["do_bg"],
        "foreground-lighten-1": _LIGHT_PALETTE["do_fg"],
    },
)

RADR_THEMES = (RADR_DARK_THEME, RADR_LIGHT_THEME)


def normalize_theme(name: str = None) -> str:
    value = (name or DEFAULT_THEME).strip().lower()
    if value == "default":
        return DEFAULT_THEME
    return value if value in THEMES else DEFAULT_THEME


def base_theme_for(name: str = None) -> str:
    return {
        DEFAULT_THEME: DARK_BASE_THEME,
        LIGHT_THEME: LIGHT_BASE_THEME,
        HIGH_CONTRAST_THEME: HIGH_CONTRAST_BASE_THEME,
    }[normalize_theme(name)]


# Drawn from the same palette as the base theme, so status colours sit beside the
# chrome rather than fighting it. Muted on purpose: status should be legible, not loud.
_DARK_TOKENS: Dict[str, str] = {
    STYLE_OK: _DARK_PALETTE["success"],
    STYLE_WARN: _DARK_PALETTE["warning"],
    STYLE_ERROR: _DARK_PALETTE["error"],
    STYLE_MUTED: _DARK_PALETTE["dim"],
    STYLE_ACTIVE: _DARK_PALETTE["accent"],
}

_LIGHT_TOKENS: Dict[str, str] = {
    STYLE_OK: _LIGHT_PALETTE["success"],
    STYLE_WARN: _LIGHT_PALETTE["warning"],
    STYLE_ERROR: _LIGHT_PALETTE["error"],
    STYLE_MUTED: _LIGHT_PALETTE["dim"],
    STYLE_ACTIVE: _LIGHT_PALETTE["accent"],
}

_HIGH_CONTRAST_TOKENS: Dict[str, str] = {
    STYLE_OK: "bold bright_green",
    STYLE_WARN: "bold bright_yellow",
    STYLE_ERROR: "bold bright_red",
    STYLE_MUTED: "bright_white",
    STYLE_ACTIVE: "bold bright_cyan",
}

THEMES: Dict[str, Dict[str, str]] = {
    DEFAULT_THEME: _DARK_TOKENS,
    LIGHT_THEME: _LIGHT_TOKENS,
    HIGH_CONTRAST_THEME: _HIGH_CONTRAST_TOKENS,
}


def resolve_theme(name: str = None) -> Dict[str, str]:
    """Return a token map, falling back to the default for an unknown name."""
    return THEMES[normalize_theme(name)]


def resolve_palette(name: str = None) -> Dict[str, str]:
    """Return non-semantic presentation roles for Rich-rendered widgets."""
    normalized = normalize_theme(name)
    if normalized == HIGH_CONTRAST_THEME:
        return {
            "background": "default",
            "panel": "default",
            "panel_border": "white",
            "title_bg": "blue",
            "title_fg": "bright_white",
            "text": "white",
            "dim": "bright_black",
            "accent": "bright_cyan",
            "column": "bright_blue",
            "do_bg": "blue",
            "do_fg": "bright_white",
            "selected_bg": "blue",
            "selected_fg": "bright_white",
            "success": "bright_green",
            "warning": "bright_yellow",
            "error": "bright_red",
        }
    return PALETTES[normalized]


def style_for(token: str, theme: Dict[str, str] = None) -> str:
    """Resolve a style token to a rich style string; unknown tokens render unstyled."""
    if not token:
        return ""
    return (theme or _DARK_TOKENS).get(token, "")


APP_CSS = """
/* Design notes
   - A border says where focus is: near-invisible ($panel) until focused ($primary).
     Borrowed from Harlequin, which uses exactly this to orient the eye.
   - Panes carry their name in the border title, so no row is spent on a heading.
   - Chrome is flat and quiet; only content and the focused pane carry weight.
   - Sizes are proportional (fr), so the layout holds from 80 columns upward. */

Screen {
    layout: vertical;
    background: $background;
}

/* ---------- chrome: one line each, no borders, deliberately recessive ---------- */

ContextBar {
    height: 1;
    padding: 0 2;
    background: $primary-darken-1;
    color: $primary-background;
}

InfoPanel {
    height: auto;
    max-height: 4;
    padding: 0 2;
    color: $text-muted;
}

/* The guide is the one piece of chrome allowed more than a row. A left rule sets it
   apart from the bars above and below without spending a border on it. */
PageGuide {
    height: auto;
    max-height: 14;
    padding: 1 2;
    margin: 1 2 0 2;
    color: $text;
    background: $surface;
}

HintBar {
    height: auto;
    max-height: 2;
    padding: 0 2;
    margin: 1 0 0 0;
    color: $text-muted;
}

Breadcrumbs {
    height: 1;
    padding: 0 2;
    color: $text;
    text-style: bold;
}

FlashLine {
    height: 1;
    padding: 0 2;
}

OperationsTray {
    height: 1;
    padding: 0 2;
    color: $text-muted;
}

/* ---------- content: bordered, focus-aware ---------- */

#browse-body {
    height: 1fr;
}

#rows-pane {
    height: 1fr;
    border: round $primary;
    border-title-color: $primary;
    border-title-style: bold;
    background: $surface;
    padding: 0 1;
}

#rows-pane > DataTable,
#rows-pane > DataTable:focus {
    border: none;
    padding: 0;
}

DataTable {
    height: 1fr;
    border: round $panel;
    background: $surface;
    padding: 0 1;
}

DataTable:focus {
    border: round $primary;
}

DataTable {
    border-title-color: $primary;
    border-title-style: bold;
}

DataTable > .datatable--header {
    text-style: bold;
    color: $secondary;
    background: $surface;
}

DataTable > .datatable--cursor {
    background: $boost;
    color: $primary-background;
    text-style: bold;
}

DataTable > .datatable--hover {
    background: $boost 60%;
}

/* Striping alternated two greys that read as noise against this palette. Rows are
   separated by the cursor and hover instead. */
DataTable > .datatable--odd-row,
DataTable > .datatable--even-row {
    background: $surface;
}

#status-line {
    height: auto;
    padding: 0 2;
    color: $text-muted;
}

/* ---------- inputs ---------- */

Input {
    border: round $panel;
    background: $surface;
    padding: 0 1;
}

Input:focus {
    border: round $primary;
}

Button {
    min-width: 12;
    height: 3;
    margin-left: 1;
}

/* ---------- guided setup: rail and working pane ---------- */

#setup-layout {
    height: 1fr;
    margin: 0 1;
    background: $background;
}

.rail {
    width: 1fr;
    min-width: 34;
    max-width: 50;
    padding: 0 1 0 0;
    background: transparent;
    border: none;
    border-right: solid $panel;
}

.pane {
    width: 3fr;
    padding: 0 0 0 1;
    border: none;
    background: $surface;
}

#rail-title {
    height: 2;
    padding: 0 2;
    content-align: left middle;
    color: $primary;
    text-style: bold;
}

#step-list {
    height: 1fr;
    background: transparent;
    border: none;
}

#step-list > ListItem {
    height: auto;
    layout: vertical;
    padding: 1 1;
    background: transparent;
}

#step-list .step-title {
    width: 100%;
    height: 1;
    padding: 0 1;
    text-style: bold;
}

#step-list .step-title.step-muted {
    color: $text-muted;
    text-style: none;
}

#step-list .step-resources {
    width: 100%;
    height: auto;
    padding: 0 2;
    color: $text;
}

#step-list > ListItem.-highlight {
    background: transparent;
    text-style: bold;
    color: $text;
}

#step-list > ListItem.selected-step > .step-title {
    background: $primary-darken-1;
    color: $primary-background;
    text-style: bold;
}

#step-list:focus > ListItem.-highlight {
    background: transparent;
    color: $text;
}

#step-heading {
    height: auto;
    min-height: 3;
    padding: 1 2;
    background: $primary-darken-1;
    color: $primary-background;
    text-style: bold;
}

#step-body {
    height: auto;
    padding: 1 2 0 2;
}

#candidate-status {
    height: auto;
    padding: 0 1;
    color: $text-muted;
}

#candidate-loading {
    height: 3;
    margin: 1 2;
    color: $primary;
}

#candidates {
    height: 1fr;
    min-height: 8;
    /* The pane already draws a border; a second one inside it reads as clutter. */
    border: none;
    background: transparent;
    padding: 0;
}

#candidates > .datatable--header,
#candidates > .datatable--odd-row,
#candidates > .datatable--even-row {
    background: $surface;
}

#candidates > .datatable--cursor {
    background: transparent;
    color: $text;
}

#candidates:focus > .datatable--cursor {
    background: $boost;
    color: $primary-background;
}

#create-form {
    height: auto;
    width: 100%;
    max-width: 96;
    border: none;
    background: transparent;
    padding: 1 2;
    margin: 0;
}

#create-kicker {
    height: 1;
    color: $primary;
    text-style: bold;
}

#create-title {
    height: auto;
    text-style: bold;
    margin-top: 1;
}

#create-subtitle {
    height: auto;
    color: $text-muted;
    margin-bottom: 1;
}

#create-form .form-field {
    height: 3;
    width: 100%;
}

#create-form .form-label {
    width: 18;
    content-align: left middle;
    text-style: bold;
    color: $text-muted;
}

#create-form .form-field Input {
    width: 1fr;
}

#create-form-hint {
    height: auto;
    margin: 1 0 0 18;
    padding: 0 1;
    color: $text-muted;
}

#create-error {
    height: auto;
    margin-left: 18;
}

#create-form .modal-buttons {
    height: 2;
    align-horizontal: right;
    padding: 1 0 0 0;
}

#create-cancel,
#create-plan,
#create-confirm {
    width: auto;
    min-width: 8;
    height: 1;
    margin: 0 0 0 2;
    padding: 0 1;
    border: none;
    background: transparent;
    color: $text-muted;
}

/* ---------- managed identity chooser ---------- */

#identity-dialog {
    width: 72%;
    max-width: 100%;
    height: 80%;
    max-height: 100%;
    border: none;
    border-left: solid $panel;
    background: $surface;
    padding: 1 3;
}

#identity-dialog > Static,
#identity-dialog > Label {
    height: auto;
}

#identity-context {
    margin-top: 1;
    text-style: bold;
}

#identity-current {
    height: auto;
    color: $primary;
    text-style: bold;
    margin-bottom: 1;
}

#identity-explanation,
#identity-status {
    color: $text-muted;
    margin-bottom: 1;
}

#identity-actions {
    height: auto;
    margin: 1 0;
}

#identity-actions Button {
    width: 1fr;
    min-width: 18;
    height: 1;
    margin-right: 1;
    padding: 0 1;
    border: none;
    background: transparent;
    color: $text-muted;
}

#identity-actions Button:focus {
    border: none;
    background: $primary-darken-1;
    color: $primary-background;
}

#identity-loading {
    height: 3;
    color: $primary;
}

#identity-table {
    height: 1fr;
    min-height: 12;
    border: none;
    padding: 0;
}

#identity-filter {
    height: 3;
    margin-bottom: 1;
    border: round $panel;
}

#identity-filter:focus {
    border: round $primary;
}

#identity-new-form {
    height: auto;
    padding-top: 1;
}

#identity-new-form .section-title {
    height: auto;
    margin-bottom: 1;
    text-style: bold;
    color: $primary;
}

#identity-new-form .form-field {
    height: 3;
}

#identity-new-form .form-label {
    width: 18;
    content-align: left middle;
    color: $text-muted;
    text-style: bold;
}

#identity-new-form .form-field Input {
    width: 1fr;
}

#identity-error {
    height: auto;
    margin-left: 18;
}

#identity-new-form .modal-buttons {
    height: 2;
    padding: 1 0 0 0;
}

#identity-new-back,
#identity-new-confirm,
#identity-cancel {
    width: auto;
    min-width: 8;
    height: 1;
    margin-left: 1;
    padding: 0 1;
    border: none;
    background: transparent;
    color: $text-muted;
}

#identity-new-confirm {
    color: $primary;
    text-style: bold;
}

#identity-new-back:focus,
#identity-new-confirm:focus,
#identity-cancel:focus {
    border: none;
    background: $primary-darken-1;
    color: $primary-background;
}

#identity-footer {
    dock: bottom;
    height: 2;
    padding: 1 0 0 0;
    align-horizontal: left;
    border-top: solid $panel;
}

#identity-cancel {
    margin-left: 0;
}

/* ---------- guided setup execution ---------- */

#execution-layout {
    height: 1fr;
    margin: 0 1;
    padding: 0 1;
    background: $surface;
}

#execution-heading {
    height: auto;
    min-height: 2;
    padding: 1 1 0 1;
}

#execution-summary {
    height: auto;
    padding: 0 1 1 1;
    color: $text-muted;
}

#execution-table {
    height: 2fr;
    min-height: 10;
    border: round $panel;
}

#execution-detail {
    height: 1fr;
    min-height: 6;
    margin-top: 1;
    padding: 1 2;
    border: round $panel;
    background: $background;
}

#create-confirm {
    color: $primary;
    text-style: bold;
}

#create-cancel:hover,
#create-cancel:focus,
#create-plan:hover,
#create-plan:focus,
#create-confirm:hover,
#create-confirm:focus {
    background: $boost;
    color: $primary-background;
    text-style: bold;
}

#command-hint {
    height: auto;
    padding: 0 2;
    color: $accent;
}

/* ---------- dialogs: reserved for confirm and error only ---------- */

ModalBox {
    width: 76;
    height: auto;
    max-height: 24;
    border: round $primary;
    background: $surface;
    padding: 1 2;
}

ModalBox.danger {
    border: round $error;
}

.modal-title {
    width: 100%;
    height: auto;
    background: $primary-darken-1;
    color: $primary-background;
    text-style: bold;
    padding: 0 1;
    margin-bottom: 1;
}

/* Applies to every dialog, not only ModalBox: the operations and plan dialogs use
   #help-body and were rendering with unstyled, overlapping buttons. */
.modal-buttons {
    height: auto;
    width: 100%;
    align-horizontal: right;
    padding: 1 1 0 0;
}

/* Every modal is centred; only HelpScreen was, so dialogs appeared in the corner. */
ModalScreen {
    align: center middle;
    background: $background 60%;
}

/* The identity workspace is a right-side sheet so the onboarding rail remains visible. */
IdentityChoiceDialog {
    align: right middle;
}

#help-body {
    width: 84;
    max-width: 90%;
    /* Shrink to the content: an empty operations list should not fill the screen. */
    height: auto;
    max-height: 80%;
    border: round $primary;
    background: $surface;
    padding: 1 2;
}

#help-body > Static,
#help-body > Label {
    height: auto;
}

#json-body {
    padding: 0 1;
}
"""
