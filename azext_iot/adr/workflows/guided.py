# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Guided ``az iot adr ns setup`` for interactive terminals.

One question at a time on stderr. Accepted answers stay in ordinary scrollback as an aligned
``Label:  value`` transcript; nothing is redrawn, no alternate screen is used and the mouse is never
captured. Answers compose the strict setup configuration (``configuration.load_config``), which the
shared ``NamespaceWorkflow`` engine plans and applies after one typed approval. Azure is only read until
that approval.
"""

import asyncio
import codecs
import errno
from contextlib import contextmanager
from copy import deepcopy
import json
import math
import os
import queue
import re
import shlex
import shutil
import sys
import textwrap
import threading
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence

from azure.cli.core.azclierror import AzCLIError, AzureResponseError, InvalidArgumentValueError
from azure.core.exceptions import AzureError, ClientAuthenticationError, ResourceNotFoundError
from knack.util import CLIError
from rich.cells import cell_len
from rich.console import Console
from rich.style import Style
from rich.text import Span, Text

from azext_iot.adr.rbac import LINK_ROLE_MATRIX
from azext_iot.adr.workflows.configuration import (
    load_config,
    request_config,
    validate_endpoint,
    validate_identity,
)
from azext_iot.adr.workflows.input import (
    BackRequested,
    WorkflowCancelled,
    _config_pairs,
    build_setup_request,
    parse_endpoint,
)
from azext_iot.adr.workflows.namespace import NamespaceWorkflow, _has_healthy_dps
from azext_iot.adr.workflows.services import is_not_found

# Layout: two-column indent, a one-cell mark plus space, then a label column wide enough for
# "Software updates:" and a two-space gap. Values therefore always start at column 23.
INDENT = 2
MARK = 2
LABEL = 19
CAPTION_INDENT = INDENT + MARK + 2  # a picker caption hangs under the list names
MAX_WIDTH = 88
LIST_ROWS = 6  # searchable name lists: a short window that filtering narrows
CHOICE_ROWS = 14  # fixed choice lists (Connectivity, Change) are shown whole; still fits 80x24
# Focus: the active question owns an accent rail down its left edge (in the indent column, so nothing moves or
# wraps differently), an accent "?" and a bold accent label; the focused list row has an accent pointer and an
# accent bold name. When setup knows the terminal's background, that row also lies on a faint wash of it, where the
# name is bold in the terminal's own foreground and its colours stay 4.5:1 legible (``focus_inks``). Answered
# questions are quiet: a jade check, a muted label, the value in bold. No box, no reverse video, no underline.
RAIL = "┃"
POINTER = "❯"
# A newly focused row's wash settles in two steps: half strength at once, full ``FOCUS_SETTLE`` seconds later. One
# extra repaint per move, none while idle, none without motion.
FOCUS_SETTLE, FOCUS_FROM = 0.06, 0.5
# The one animation: while Azure is actually being waited on (reads, checks, plan reads, writes), the operation line
# leads with the classic Braille spinner, in the mark column so the text never moves, from its very first frame at
# 12.5 frames a second (inside the 10-15 fps that reads as smooth without busy redraws). Its colour glides along the
# wordmark's aurora and back. It means "still working", never a percentage or ETA: nothing trails the text but the
# elapsed seconds, after the first one. Without motion (reduced motion, NO_COLOR, TERM=dumb) the line shows the one
# still glyph, all six dots of the same cell, drawn once: no timer, nothing else that moves.
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STILL = "⠿"
FRAME = 0.08
SPIN_COLOR = 2.4  # seconds for the spinner's colour to travel the aurora and back

# Colour roles, "Azure slate": one azure brand hue, kept for focus, with muted jade, slate, periwinkle, ochre, brick,
# a quiet slate-blue for answered labels and a violet for search matches around it,
# all at the same mid luminance (~0.205) and moderate saturation, so they read as one set. Foreground colours: never
# reverse video, underline, or dim essential text. Every colour keeps at least 3.3:1 contrast on white, black and
# the common light and dark themes (One Dark, Solarized, VS Code's #1e1e1e), so it needs no background detection
# and never assumes a dark terminal; on the two washes (``Tints``) they are adjusted to 4.5:1. A 24-bit terminal
# shows them exactly; a 256-colour one (the usual xterm-256color without COLORTERM) shows their nearest 256-colour
# entries, which keep 3:1 or better;
# a 16-colour terminal (or NO_COLOR stripped of colour) uses its own ANSI palette, which its theme already tunes.
RGB = {
    "accent": "#2f81c9", "label": "#627fa1", "create": "#1f8e6e", "reuse": "#5c8390", "link": "#6f74d0",
    "role": "#a8741c", "warn": "#a8741c", "bad": "#d64f58", "match": "#9f62cb",
}
PALETTES = {
    "ansi": {  # 16 colours: answered labels keep blue, and focus is told apart by the rail, pointer and bold
        "accent": "blue", "label": "blue", "create": "green", "reuse": "cyan", "link": "magenta", "role": "yellow",
        "warn": "yellow", "bad": "red", "match": "magenta",
    },
    "256": RGB,
    "truecolor": RGB,
}
# The title wordmark and the spinner: an "aurora" ramp, teal → azure → violet → rose. Colour on thin glyphs is hard
# to see, so the ramp spans ~140° of hue (cool to rose, never through green/yellow/red: not a rainbow) with a
# lightness step at the teal end; every stop keeps 3:1 or better on light and dark backgrounds, and the 256-colour
# entries are four distinct steps. ANSI: cyan → blue → magenta.
GRADIENTS = {"ansi": ("cyan", "blue", "magenta"), "256": ("#119994", "#2f81c9", "#945bd6", "#ca478d")}
GRADIENTS["truecolor"] = GRADIENTS["256"]

# Rich styles are theme names, resolved by the Screen's console for its palette (see ``theme``).
BOLD = Style(bold=True)
DIM = Style(dim=True)
PLAIN = Style()
ACCENT = "setup.accent"
ACCENT_BOLD = "setup.accent.bold"
LABEL_STYLE = "setup.label"
GOOD = "setup.good"
GOOD_BOLD = "setup.good.bold"
REUSE_BOLD = "setup.reuse"
LINK_BOLD = "setup.link"
ROLE_BOLD = "setup.role"
WARN_BOLD = "setup.warn"
BAD_BOLD = "setup.bad"
THEME_ROLES = {
    ACCENT: ("accent", False), ACCENT_BOLD: ("accent", True), LABEL_STYLE: ("label", False),
    GOOD: ("create", False), GOOD_BOLD: ("create", True), REUSE_BOLD: ("reuse", True), LINK_BOLD: ("link", True),
    ROLE_BOLD: ("role", True), WARN_BOLD: ("warn", True), BAD_BOLD: ("bad", True),
}


def theme(palette: str):
    from rich.theme import Theme

    colors = PALETTES[palette]
    return Theme({name: Style(color=colors[role], bold=bold) for name, (role, bold) in THEME_ROLES.items()},
                 inherit=True)


WASHED = ".washed"  # a theme name's variant for text on the approval surface (``Screen.surface``)


def washed_theme(inks: Dict[str, str]):
    """Every theme colour, made legible on the approval surface (``Tints.rich_inks``)."""
    from rich.theme import Theme

    return Theme({name + WASHED: Style(color=inks[role], bold=bold) for name, (role, bold) in THEME_ROLES.items()},
                 inherit=True)


def _washed(style):
    return style + WASHED if isinstance(style, str) and style in THEME_ROLES else style


def prompt_style(palette: str = "ansi") -> Dict[str, str]:
    """The prompt's style for a palette; prompt_toolkit spells ANSI names "ansiblue"."""
    colors = {role: color if color.startswith("#") else "ansi" + color for role, color in PALETTES[palette].items()}
    # One focus language for every prompt: the accent rail, mark, label and pointer, and the focused row's name in
    # accent bold. Accent means "focused" and nothing else here; search matches have their own hue.
    return {
        "rail": colors["accent"],
        "mark": f"{colors['accent']} bold",
        "label": f"{colors['accent']} bold",
        "input": "bold",
        "placeholder": "italic",
        "pointer": f"{colors['accent']} bold",
        "name": "",
        # prompt_toolkit's default UI style gives "selected" reverse video; the focused row is colour + bold only.
        "selected": f"{colors['accent']} bold noreverse",
        "match": f"{colors['match']} bold",
        "selected-match": f"{colors['match']} bold noreverse",
        "detail": "dim",
        "selected-detail": "noreverse",
        "caption": f"{colors['accent']}",
        "action": colors["accent"],
        "new": f"{colors['create']} bold",
        "reuse": f"{colors['reuse']} bold",
        "marked": f"{colors['create']} bold",
        "key": "bold",
        "hint": "dim",
        "error": colors["bad"],
        "error-mark": f"{colors['bad']} bold",
        "choice": "bold",
        "choice-default": f"{colors['accent']} bold",
    }


def sgr(color: str, *, bold: bool = False, palette: str = "truecolor") -> str:
    """The escape sequence for one foreground colour (status line only; everything else goes through Rich), at the
    palette's depth: a 256-colour terminal gets the nearest 256-colour entry, never 24-bit codes."""
    from rich.color import Color, ColorSystem

    parsed = Color.parse(color)
    if palette == "256":
        parsed = parsed.downgrade(ColorSystem.EIGHT_BIT)
    return "\x1b[" + ";".join((("1",) if bold else ()) + tuple(parsed.get_ansi_codes())) + "m"


def mix(a: str, b: str, part: float) -> str:
    """The hex colour ``part`` of the way from ``a`` to ``b``."""
    x, y = (tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) for color in (a, b))
    return "#" + "".join(f"{round(p + (q - p) * part):02x}" for p, q in zip(x, y))


def along(stops: Sequence[str], part: float) -> str:
    """The colour ``part`` (0-1) of the way along two or more stops: interpolated for hex stops, nearest stop for
    ANSI."""
    position = part * (len(stops) - 1)
    low = min(int(position), len(stops) - 2)
    rest = position - low
    if not stops[low].startswith("#"):
        return stops[low + round(rest)]
    return mix(stops[low], stops[low + 1], rest)


def gradient(stops: Sequence[str], count: int) -> List[str]:
    """``count`` colours spread evenly over the stops."""
    if count <= 1 or len(stops) == 1:
        return [stops[0]] * max(count, 0)
    return [along(stops, index / (count - 1)) for index in range(count)]


def luminance(color: str) -> float:
    """WCAG relative luminance of a hex colour."""
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two hex colours (1 to 21)."""
    low, high = sorted((luminance(a), luminance(b)))
    return (high + 0.05) / (low + 0.05)


# The xterm-256 entries above the 16 themeable ones: the 6x6x6 cube and the grey ramp, as (index, '#rrggbb').
_LEVELS = (0, 0x5F, 0x87, 0xAF, 0xD7, 0xFF)
XTERM = [(16 + index, "#%02x%02x%02x" % (_LEVELS[index // 36], _LEVELS[index // 6 % 6], _LEVELS[index % 6]))
         for index in range(216)] + [(232 + index, "#%02x%02x%02x" % ((8 + 10 * index,) * 3)) for index in range(24)]


def _distance(a: str, b: str) -> int:
    return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2 for i in (1, 3, 5))


def xterm(color: str) -> tuple:
    """(index, hex) of the nearest xterm-256 entry above the 16 themeable ones, the same choice prompt_toolkit makes;
    Rich is given the index itself, so both draw exactly one entry."""
    return min(XTERM, key=lambda entry: _distance(entry[1], color))


class Tints(NamedTuple):
    """Two faint washes of the terminal's own background, toward the azure accent, for the focused list row and the
    approval surface, and the palette's colours made legible on each. ``focus``, ``surface`` and ``inks`` are hex
    for prompt_toolkit; the ``rich_`` ones are the same, or the exact xterm entry ('color(N)') at 256 colours."""
    background: str
    focus: str
    surface: str
    rich_focus: str
    rich_surface: str
    inks: Dict[str, str] = {}  # role -> colour on the focused row's wash
    rich_inks: Dict[str, str] = {}  # role -> colour on the approval surface


# Coloured text on a wash keeps at least this contrast (WCAG AA for text): a colour that falls short is moved toward
# the terminal's foreground side, in its own hue, until it reaches it.
INK_CONTRAST = 4.5


def legible(color: str, grounds: Sequence[str], palette: str) -> tuple:
    """(hex, rich) for ``color`` with INK_CONTRAST on every one of ``grounds`` (all dark or all light): unchanged
    when it already has it. Otherwise, in 24-bit colour, the least step toward white (or black) that reaches it, in
    its own hue; at 256 colours, the nearest xterm entry that does (the cube is too coarse to step through)."""
    if palette == "256":
        readable = [entry for entry in XTERM if all(contrast(entry[1], ground) >= INK_CONTRAST for ground in grounds)]
        readable = readable or [max(XTERM, key=lambda entry: min(contrast(entry[1], ground) for ground in grounds))]
        index, drawn = min(readable, key=lambda entry: _distance(entry[1], color))
        return drawn, f"color({index})"
    toward = "#ffffff" if luminance(grounds[0]) < TINT_DARK else "#000000"
    steps = (mix(color, toward, step / 20) for step in range(21))
    candidate = next((step for step in steps if all(contrast(step, ground) >= INK_CONTRAST for ground in grounds)),
                     toward)  # a wash right at the dark/light line: the most contrast there is
    return candidate, candidate


# A dark background (by luminance) is lifted toward white, a light one lowered toward black, and both lean a little
# toward the accent, so the wash belongs to the terminal's theme rather than painting one of its own.
TINT_DARK = 0.18
TINT_LIFT = {"dark": 0.06, "light": 0.035}  # the surface: frosted, a breath lighter (or darker) than the terminal
TINT_FOCUS = {"dark": 0.14, "light": 0.11}  # the focused row: a little more, and bluer
TINT_ACCENT = 0.04
TINT_SEEN, TINT_MOST = 1.05, 1.4  # the contrast of a wash with the terminal's background: visible, never loud


def surface_tints(background: str, palette: str) -> Optional[Tints]:
    """The washes for a known background, or None when they can't be shown faithfully (16 colours, a mid-tone
    background no faint wash shows on, or 256 colours with no faint entry near the wash), so setup keeps the
    terminal's own background."""
    if palette not in ("256", "truecolor"):
        return None
    tone = "dark" if luminance(background) < TINT_DARK else "light"
    toward = "#ffffff" if tone == "dark" else "#000000"

    def surface(scale):
        return mix(mix(background, toward, TINT_LIFT[tone] * scale), RGB["accent"], TINT_ACCENT * scale)

    def focus(scale):
        return mix(background, RGB["accent"], TINT_FOCUS[tone] * scale)

    if palette == "truecolor":
        washes = focus(1), surface(1)
        if not all(TINT_SEEN <= contrast(wash, background) <= TINT_MOST for wash in washes):
            return None  # a mid-tone background: a wash this faint can't be seen, so none is drawn
        return finished(Tints(background, *washes, *washes))
    base = xterm(background)[0]
    # 256 colours: the entry nearest each wash that is not the background's own and stays faint against the real
    # background; the cube's steps are coarse, so without such an entry there is no wash at all.
    faint = [entry for entry in XTERM if entry[0] != base and TINT_SEEN <= contrast(entry[1], background) <= TINT_MOST]
    if not faint:
        return None
    (focus_index, focus_hex), (surface_index, surface_hex) = (
        min(faint, key=lambda entry: _distance(entry[1], wash(1))) for wash in (focus, surface))
    return finished(Tints(background, focus_hex, surface_hex, f"color({focus_index})", f"color({surface_index})"))


def finished(tints: Tints) -> Tints:
    """The washes with every palette colour made legible on them. Focus also allows for the native background: the
    wash fades in from it after a move."""
    palette = "truecolor" if tints.focus == tints.rich_focus else "256"
    inks = {role: legible(color, (tints.focus, tints.background), palette)[0] for role, color in RGB.items()}
    rich = {role: legible(color, (tints.surface,), palette)[1] for role, color in RGB.items()}
    return tints._replace(inks=inks, rich_inks=rich)


KIND_LABELS = {"dps": "DPS", "hub": "IoT Hub", "software-updates": "Software updates"}
KIND_WORDS = {"dps": "DPS", "hub": "IoT Hub", "software-updates": "Software Updates"}
# Whose managed identity a link's "linked" principal is (rbac.LINK_ROLE_MATRIX). Generated wording only: resource
# names, IDs and role-definition names are always printed verbatim, never rewritten.
IDENTITY_OWNERS = {"dps": "DPS", "hub": "IoT Hub", "software-updates": "Device Update"}
# New IoT Hub tiers setup can create: exactly WorkflowServices.validate_target_creation and
# configuration.validate_endpoint (S1, S2, S3); Free/Basic hubs can't link to ADR (link_preflight requires a
# Standard S-tier Hub). Daily messages are per unit. DPS has one tier, S1, so it is shown, never offered as a choice.
# Guided setup creates 1 unit; more units are an explicit --hub unit=N or config choice that Azure validates.
HUB_TIERS = (
    ("S1", "400,000 messages/day per unit"),
    ("S2", "6,000,000 messages/day per unit"),
    ("S3", "300,000,000 messages/day per unit"),
)
DEFAULT_TIER = "S1"
DPS_TIER = "S1"
NAME_PROMPTS = {"dps": "DPS name:", "hub": "IoT Hub name:", "software-updates": "Instance name:"}
SECTIONS = {"dps": "provisioning", "hub": "messaging", "software-updates": "updating"}
# Typed DPS/IoT Hub names use the same limits as WorkflowServices.validate_target_creation. Software Updates
# instance names have no local rule (Azure's name check decides); 24 caps only the derived default, conservatively.
NAME_LIMITS = {"dps": 64, "hub": 50}
DERIVED_NAME_CAPS = dict(NAME_LIMITS, **{"software-updates": 24})
NAME_SUFFIX = {"dps": "dps", "hub": "hub", "software-updates": "su"}
TARGET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]")
NAMESPACE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")
SYSTEM = {"type": "SystemAssigned"}
UNREADABLE_LINK = "unchecked · Azure didn't report its target or identity, so setup leaves it as is · run check"
NEEDS_DPS_LINK = "unchecked · needs a DPS link, so setup leaves it as is · link a DPS or run check"
QUESTIONS = ("resource_group", "namespace", "connectivity", "software_updates", "cms")
# Guided setup links at most this many IoT Hubs to a namespace, counting the ones already linked. It is a limit of
# the guided collection only: explicit --hub arguments and --config keep the engine's own rules.
MAX_HUBS = 10
PERMANENT = ("Create", "Link", "Configure", "Wait", "Refresh")


# The value of a target list's "Another subscription…" row (never a resource); the terminal prompt returns it
# followed by the text in the field, so a search survives the detour.
SCOPE = "\x00subscription"


def _region_key(location) -> str:
    """Azure region names compare without case or spaces ("East US" is eastus)."""
    return str(location or "").replace(" ", "").casefold()


class Row(NamedTuple):
    value: str
    title: str
    detail: str = ""
    tag: str = ""


class SetupStopped(KeyboardInterrupt):
    """Stop before the next operation; an already-submitted request may still complete.

    A KeyboardInterrupt, not an Exception: the engine's readiness checks record ordinary errors with broad
    ``except Exception`` handlers, and a stop must pass through them to setup's interrupt handling, which keeps
    the completed items. termination_kind still tells it apart from a real interrupt.
    """


class Approved(NamedTuple):
    request: Any
    config: Dict[str, Any]


class OutboundIdentityProblem(InvalidArgumentValueError):
    """The existing namespace outbound identity can't be used for links; only the user may replace it."""


def derive_name(namespace: str, kind: str, number: int = 1) -> str:
    """A valid default target name from the namespace: lowercase, hyphenated, within the kind's limit. Further
    IoT Hubs are numbered (``-hub-2``); the stem is shortened so the number always fits."""
    suffix = NAME_SUFFIX[kind] + (f"-{number}" if number > 1 else "")
    stem = re.sub(r"[^a-z0-9]+", "-", namespace.casefold()).strip("-")
    stem = stem[:DERIVED_NAME_CAPS[kind] - len(suffix) - 1].rstrip("-")
    return f"{stem or 'adr'}-{suffix}"


def tier_detail(kind: str, choice: Dict[str, Any]) -> str:
    """A new target's tier and units as created: DPS has the one tier; a new IoT Hub keeps the chosen one."""
    tier = choice.get("sku") or (DPS_TIER if kind == "dps" else DEFAULT_TIER)
    return f"{tier} · {choice.get('unit') or 1} unit"


def identity_value(identity: str) -> tuple:
    """(value, detail) for the namespace outbound identity: its name, and which managed identity it is."""
    if validate_identity(identity, "namespace.outboundIdentity") == "system-assigned":
        return "system-assigned", "namespace managed identity"
    return _short(identity), "namespace user-assigned managed identity"


def target_name_error(name: str, kind: str) -> str:
    """IoT Hub and DPS rules match services.validate_target_creation. Device Update instance names have no local
    rule in this repo; Azure's name availability check, run when the plan is read, decides."""
    limit = NAME_LIMITS.get(kind)
    if limit is None:
        return "" if name.strip() else "Enter a Device Update instance name."
    if 3 <= len(name) <= limit and TARGET_NAME.fullmatch(name):
        return ""
    return f"{KIND_LABELS[kind]} names are 3–{limit} letters, digits or hyphens, starting and ending alphanumeric."


def plan_fingerprint(plan: Dict[str, Any]) -> str:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def termination_kind(error: Optional[BaseException]) -> str:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, SetupStopped):
            return "stopped"
        if isinstance(error, KeyboardInterrupt):
            return "interrupted"
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return "failed"


def motion_allowed(stream, plain: bool) -> bool:
    """Animate only on a real colour terminal. NO_COLOR, TERM=dumb and TEXTUAL_ANIMATIONS=none (the reduced-motion
    setting this extension's other terminal views already honour) disable it."""
    return bool(
        not plain
        and getattr(stream, "isatty", lambda: False)()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "") != "dumb"
        and os.environ.get("TEXTUAL_ANIMATIONS", "").casefold() != "none"
    )


def pretty_label(label: str) -> str:
    """Engine labels read '<Verb> <kind> <name>': only that kind word is spelled out; names stay verbatim."""
    verb, space, rest = label.partition(" ")
    kind, gap, tail = rest.partition(" ")
    if space and kind in KIND_WORDS:
        return f"{verb} {KIND_WORDS[kind]}{gap}{tail}"
    return label


# The principal labels rbac._format_role_requirement generates into engine messages (role preflight and failures),
# spelled out wherever guided setup shows engine text. Whole multi-word phrases only: resource names and IDs can't
# contain spaces, official role names never say "MI", and structured results keep the engine's text verbatim.
ENGINE_IDENTITY_LABELS = (
    (re.compile(r"\bnamespace outbound MI\b"), lambda match: "namespace outbound managed identity"),
    (re.compile(r"\bnamespace system-assigned MI\b"), lambda match: "namespace system-assigned managed identity"),
    (re.compile(r"\b(DPS|HUB|SU) selected inbound MI\b"), lambda match: "{} managed identity".format(
        {"DPS": "DPS", "HUB": "IoT Hub", "SU": "Device Update"}[match.group(1)])),
)


def identity_words(text: Any) -> str:
    text = str(text or "")
    for pattern, spelled in ENGINE_IDENTITY_LABELS:
        text = pattern.sub(spelled, text)
    return text


def _short(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _first_line(error: BaseException) -> str:
    return next((line.strip() for line in str(error).splitlines() if line.strip()), type(error).__name__)


def _quote(value: str) -> str:
    return shlex.quote(str(value))


def endpoint_map(namespace: Optional[Dict[str, Any]], kind: str) -> Dict[str, Any]:
    return (((namespace or {}).get("properties") or {}).get(SECTIONS[kind]) or {}).get("endpoints") or {}


def linked_endpoints(namespace: Optional[Dict[str, Any]], kind: str) -> List[Dict[str, str]]:
    """Existing namespace endpoint links of one kind, read from the namespace resource."""
    links = []
    for name, link in sorted(endpoint_map(namespace, kind).items()):
        link = link if isinstance(link, dict) else {}
        links.append({
            "endpoint": name,
            "resource": _short(link.get("resourceId") or link.get("resource_id") or name),
            "state": str(link.get("linkingState") or link.get("linking_state") or ""),
        })
    return links


def existing_link_config(kind: str, name: str, link: Any) -> Optional[Dict[str, Any]]:
    """An existing link as an exact config endpoint (same endpoint, target and identity), so the engine re-checks
    its health and access; None when Azure didn't return a usable target or identity. Never guesses one."""
    link = link if isinstance(link, dict) else {}
    identity = link.get("inboundCallerIdentity") or link.get("inbound_caller_identity") or {}
    assigned = identity.get("userAssignedIdentity") or identity.get("user_assigned_identity")
    endpoint = {
        "endpointName": name, "resourceId": link.get("resourceId") or link.get("resource_id"),
        "identity": dict(SYSTEM) if identity.get("type") == "SystemAssigned" else {
            "type": "UserAssigned", "userAssignedResourceId": assigned} if identity.get("type") == "UserAssigned" else None,
    }
    try:
        validate_endpoint(endpoint, kind, f"existing {KIND_LABELS[kind]} link {name}")
    except InvalidArgumentValueError:
        return None
    return endpoint


def equivalent_command(config: Dict[str, Any]) -> Optional[List[str]]:
    """The same setup as one unattended command, or None when arguments cannot express it (CMS)."""
    if (config.get("cms") or {}).get("enabled") or config.get("checkStatus"):
        return None
    namespace = config["namespace"]
    lines = [
        f"az iot adr ns setup -n {_quote(namespace['name'])} -g {_quote(namespace['resourceGroup'])}",
        f"--subscription {_quote(config['subscriptionId'])}",
    ]
    if namespace.get("location"):
        lines.append(f"--location {_quote(namespace['location'])}")
    if namespace.get("tags") is not None:
        lines.append("--tags " + " ".join(_quote(f"{key}={value}") for key, value in sorted(namespace["tags"].items())))
    if namespace.get("outboundIdentity"):
        lines.append("--outbound-identity " + _quote(validate_identity(namespace["outboundIdentity"], "identity")))
    links = config.get("links") or {}
    endpoints = [("--dps", links.get("dps"))] + [("--hub", hub) for hub in links.get("hubs", [])]
    endpoints.append(("--su", links.get("softwareUpdates")))
    for option, endpoint in endpoints:
        if endpoint:
            lines.append(option + " " + " ".join(_quote(pair) for pair in _config_pairs(endpoint)))
    lines.append("--yes")
    return lines


def command_rows(lines: Sequence[str], room: int) -> List[tuple]:
    """(indent, text) rows: each logical line's shell words packed within ``room`` cells, quoting kept intact.

    The command starts at indent 0, further option lines at 2, and wrapped words of one option at 4."""
    rows = []
    for index, line in enumerate(lines):
        depth = 2 if index else 0
        row = ""
        for word in shlex.split(line):
            word = _quote(word)
            joined = f"{row} {word}" if row else word
            if row and cell_len(joined) > room - depth:
                rows.append((depth, row))
                row, depth = word, 4
            else:
                row = joined
        rows.append((depth, row))
    return rows


# --------------------------------------------------------------------------------------------
# The terminal's background
# --------------------------------------------------------------------------------------------

# Asked once per guided run, before its first line: the background colour (OSC 11), then the device attributes
# (DA1), which every terminal answers, in order, so a DA1 answer with no colour before it means "no colour coming".
BACKGROUND_QUERY = "\x1b]11;?\x1b\\\x1b[c"
BACKGROUND_WAIT = 0.5  # seconds; terminals answer within milliseconds, so only a silent one waits this long
COLOR_SPEC = re.compile(r"[0-9A-Za-z:/#]{0,48}")
DA1_PARAMS = re.compile(r"[0-9;]{0,48}")
# While an answer may still be on its way, the prompt waits this long for what follows an Esc (normally 0.05 s).
LATE_ESCAPE = 0.3


def parse_background(spec: str) -> Optional[str]:
    """An OSC 11 colour ('rgb:1e1e/1e1e/1e1e' with 1-4 hex digits per channel, 'rgba:…' whose alpha is ignored,
    or '#rgb' to '#rrrrggggbbbb') as '#rrggbb'; None for anything else, so nothing is guessed."""
    if spec.startswith("#"):
        digits = spec[1:]
        size = len(digits) // 3
        parts = [digits[index * size:(index + 1) * size] for index in range(3)] if len(digits) % 3 == 0 else []
    else:
        kind, _, body = spec.partition(":")
        parts = body.split("/")
        parts = parts[:3] if (kind, len(parts)) in (("rgb", 3), ("rgba", 4)) else []
    if not parts or not all(1 <= len(part) <= 4 and re.fullmatch(r"[0-9A-Fa-f]+", part) for part in parts):
        return None
    return "#" + "".join(f"{round(int(part, 16) * 255 / (16 ** len(part) - 1)):02x}" for part in parts)


class TerminalReplies:
    """Keeps the terminal's answers to the background query out of what the user types.

    Until the DA1 answer has arrived (at the probe, or later over a slow link), an answer may still be on its way.
    Every keystroke a prompt reads passes through ``feed``, which removes whole answers, even when they are split
    across reads, and passes everything else on unchanged and in order. Only an Esc, or text that can still become
    an answer, is held: text that turns out not to be one is released at once, and a lone Esc at the prompt's Esc
    timeout (``flush``), so it still means Back. Once DA1 has arrived nothing is outstanding and ``feed`` is a plain
    pass-through. The answers' own text never reaches a field, the screen or scrollback."""

    def __init__(self, outstanding=("osc", "da1")):
        self.outstanding = set(outstanding)
        self.held = ""
        self.background: Optional[str] = None
        self.terminal = None  # (descriptor, settings) to restore when echo was left off for a late answer

    def _state(self, text: str) -> str:
        """'osc' or 'da1' for a whole outstanding answer, 'more' while ``text`` can still become one, else ''."""
        if "osc" in self.outstanding:
            head = "\x1b]11;"
            if head.startswith(text):
                return "more"
            if text.startswith(head):
                body = text[len(head):]
                for end in ("\x07", "\x1b\\"):
                    if body.endswith(end) and COLOR_SPEC.fullmatch(body[:-len(end)]):
                        return "osc"
                if COLOR_SPEC.fullmatch(body[:-1] if body.endswith("\x1b") else body):
                    return "more"
        if "da1" in self.outstanding:
            head = "\x1b[?"
            if head.startswith(text):
                return "more"
            if text.startswith(head):
                body = text[len(head):]
                if body.endswith("c") and DA1_PARAMS.fullmatch(body[:-1]):
                    return "da1"
                if DA1_PARAMS.fullmatch(body):
                    return "more"
        return ""

    def feed(self, text: str) -> str:
        if not self.outstanding and not self.held:
            return text
        passed = []
        for char in text:
            if self.held:
                candidate = self.held + char
                state = self._state(candidate)
                if state == "more":
                    self.held = candidate
                    continue
                self.held = ""
                if state:
                    self._answered(state, candidate)
                    continue
                passed.append(candidate[:-1])  # not an answer: the user's own keys, in order
            if char == "\x1b" and self.outstanding:
                self.held = char
            else:
                passed.append(char)
        return "".join(passed)

    def _answered(self, kind: str, text: str):
        if kind == "osc":
            self.background = parse_background(text[5:-1] if text.endswith("\x07") else text[5:-2])
            self.outstanding.discard("osc")
        else:  # answers arrive in order: after DA1 no colour is coming
            self.outstanding.clear()

    def flush(self) -> str:
        """At a prompt's Esc timeout: a lone Esc is the user's; a longer partial answer waits for the rest."""
        if self.held == "\x1b":
            self.held = ""
            return "\x1b"
        return ""

    def attach(self, source):
        """Route a prompt_toolkit input's text through ``feed`` and ``flush``, once per input."""
        parser = getattr(source, "vt100_parser", None)
        if parser is None or getattr(parser, "adr_replies", None) is self:
            return
        feed, flush = parser.feed, parser.flush

        def flushed():
            held = self.flush()
            if held:
                feed(held)
            flush()

        parser.feed = lambda data: feed(self.feed(data))
        parser.flush = flushed
        parser.adr_replies = self

    def close(self):
        """At the end of the run: the terminal's own settings (echo) come back. Nothing is read, dropped or put back:
        keys typed after the last prompt stay in the terminal for the shell."""
        if self.terminal:
            descriptor, settings = self.terminal
            self.terminal = None
            _apply_settings(descriptor, settings)


def _apply_settings(descriptor, settings):
    """Set the terminal's input settings now; a terminal that has gone away (EIO) has none left to set."""
    import termios

    try:
        termios.tcsetattr(descriptor, termios.TCSANOW, settings)
    except termios.error as error:
        if error.args[0] != errno.EIO:
            raise


def _quiet(settings) -> list:
    """Terminal settings for reading answers: no echo, no line editing, and reads that never wait."""
    import termios

    quiet = list(settings)
    quiet[3] &= ~(termios.ICANON | termios.ECHO)
    quiet[6] = list(settings[6])
    quiet[6][termios.VMIN], quiet[6][termios.VTIME] = 0, 0
    return quiet


def _read(descriptor) -> bytes:
    """One read of what the terminal sent; b"" once it has hung up (EIO). Any other failure is raised."""
    try:
        return os.read(descriptor, 1024)
    except OSError as error:
        if error.errno != errno.EIO:
            raise
        return b""


def probe_background(stdin, write: Callable[[str], Any], timeout: float = BACKGROUND_WAIT):
    """Ask the terminal behind ``stdin`` for its background, once. Returns (replies, typed): ``replies.background``
    is the colour when the terminal said, and ``typed`` is what the user typed meanwhile, for the first prompt.
    (None, "") when there is no POSIX terminal to ask. Input is read without echo and nothing is flushed. If the DA1
    answer hasn't come by ``timeout``, echo stays off (``replies.close`` restores it) so a late answer can't be
    echoed, and the prompts remove it when it comes."""
    try:
        import termios
    except ImportError:  # Windows consoles: no probe; setup keeps the terminal's own background
        return None, ""
    try:
        descriptor = stdin.fileno()
        saved = termios.tcgetattr(descriptor)
    except (AttributeError, OSError, ValueError, termios.error):
        return None, ""
    import select

    replies = TerminalReplies()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    typed = []
    try:  # every way out of here but a normal return leaves the terminal's own settings, at once
        _apply_settings(descriptor, _quiet(saved))
        write(BACKGROUND_QUERY)
        deadline = time.monotonic() + timeout
        while replies.outstanding:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([descriptor], [], [], left)[0]:
                break
            chunk = _read(descriptor)
            if not chunk:
                break
            typed.append(replies.feed(decoder.decode(chunk)))
        typed.append(replies.feed(decoder.decode(b"", final=True)))
        settings = saved
        if replies.outstanding:  # until the run ends (``close``): lines as usual, but no echo of a late answer
            settings = list(saved)
            settings[3] &= ~termios.ECHO
        _apply_settings(descriptor, settings)
    except BaseException:  # a failed query, read or Ctrl+C: echo is back before it is raised; nothing is kept
        _apply_settings(descriptor, saved)
        raise
    if replies.outstanding:  # only once echo is really off: from here the run's ``release`` restores it
        replies.terminal = (descriptor, saved)
    return replies, "".join(typed)


def same_terminal(first, second) -> bool:
    """Whether two streams are the same terminal, so an answer to a query written to one arrives on the other;
    assumed when the platform can't tell."""
    try:
        return os.ttyname(first.fileno()) == os.ttyname(second.fileno())
    except (AttributeError, OSError, ValueError):
        return True


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------


class Screen:
    """Human output on stderr: permanent lines, one transient activity line for real, observed work, and one
    *workspace* — a block repainted in place, directly above the active question.

    The workspace is redrawn by moving the cursor up over its own rows and erasing below; nothing above it (the
    shell history, the header) is ever touched, and the terminal's scrollback is never cleared. Prompts report
    the rows they may use (``reserve``), so the painter knows how many workspace rows are still on screen. Rows
    that scrolled into scrollback are reused only when unchanged; see ``show``. Without a terminal (pipes,
    ``--plain``, ``TERM=dumb``) the workspace is append-only and prints just the rows that changed."""

    def __init__(self, stream=None, *, plain=False, console=None, motion=None):
        self.stream = stream or sys.stderr
        self.plain = plain
        self.console = console or Console(
            file=self.stream, highlight=False, markup=False, emoji=False, soft_wrap=False,
            color_system=None if plain else "auto",
        )
        self.live = not plain and getattr(self.stream, "isatty", lambda: False)()
        self.repaint = self.live and os.environ.get("TERM", "") != "dumb"
        self.motion = motion_allowed(self.stream, plain) if motion is None else motion
        self.colors = self.motion or (self.live and "NO_COLOR" not in os.environ)
        # The palette follows the depth the console really renders (Rich: COLORTERM, TERM=*-256color, Windows
        # Terminal): exact 24-bit colours, their nearest 256-colour entries, or the terminal's own 16 ANSI colours.
        system = None if self.console.no_color else self.console.color_system
        self.palette = system if system in ("truecolor", "256") else "ansi"
        self.console.push_theme(theme(self.palette))
        self._tints: Optional[Tints] = None  # set by ``probe`` when the terminal tells its background
        self.replies: Optional[TerminalReplies] = None
        self._inset = 0
        self._lock = threading.Lock()
        self._status = ""
        self._line = ""
        self._blank = True
        self._region: List[Text] = []
        self._region_columns = 0
        self._reserve = 1

    @property
    def width(self) -> int:
        return max(40, min(self.console.width, MAX_WIDTH))

    @property
    def tints(self) -> Optional[Tints]:
        return self._tints

    @tints.setter
    def tints(self, tints: Optional[Tints]):
        self._tints = tints
        if tints:
            self.console.push_theme(washed_theme(tints.rich_inks))

    def probe(self, stdin=None) -> str:
        """Learn the terminal's background (``probe_background``), only where a wash of it can be shown: a repainting
        terminal with 256 or 24-bit colour, and colour allowed. Returns what the user typed meanwhile. Without an
        answer ``tints`` stays None and setup keeps the terminal's own background: nothing is guessed."""
        stdin = stdin or sys.stdin
        if not (self.repaint and self.colors and not self.console.no_color and self.palette != "ansi"):
            return ""
        if not getattr(stdin, "isatty", lambda: False)() or not same_terminal(stdin, self.stream):
            return ""

        def write(text):
            with self._lock:
                self.stream.write(text)
                self.stream.flush()

        self.replies, typed = probe_background(stdin, write)
        if self.replies and self.replies.background:
            self.tints = surface_tints(self.replies.background, self.palette)
        return typed

    def release(self):
        """The run is over: the terminal's input settings are its own again."""
        if self.replies:
            self.replies.close()

    @contextmanager
    def inset(self):
        """Rows built inside wrap one cell short of the width when they will be washed (``surface``), so the wash
        never reaches the terminal's last column."""
        previous, self._inset = self._inset, 1 if self.tints and self.repaint else 0
        try:
            yield
        finally:
            self._inset = previous

    def size(self):
        """(columns, rows) of the terminal behind the stream; the console's idea of it otherwise."""
        try:
            size = os.get_terminal_size(self.stream.fileno())
            return size.columns, size.lines
        except (AttributeError, OSError, ValueError):
            return self.console.size.width, self.console.size.height

    def print(self, renderable=None):
        """A permanent line. Any workspace above it becomes ordinary scrollback first."""
        self.commit()
        self._emit(renderable)

    def _emit(self, renderable=None):
        self.clear_status()
        renderable = renderable if renderable is not None else ""
        self.console.print(renderable, width=self.width)
        self._blank = renderable == "" or (isinstance(renderable, Text) and not renderable.plain.strip())

    def blank(self):
        if not self._blank:
            self.print("")

    # ---- line builders (shared by permanent output and the workspace) ----

    def hanging_lines(self, prefix: Text, body: Text, indent: int) -> List[Text]:
        """prefix + body as single terminal rows, body wrapping under itself; long names and IDs fold, never hide."""
        lines = body.wrap(self.console, max(12, self.width - indent - self._inset), overflow="fold") if (
            body.plain) else [Text()]
        rows = []
        for index, line in enumerate(lines):
            line.rstrip()
            out = prefix.copy() if index == 0 else Text(" " * indent)
            out.append_text(line)
            rows.append(out)
        return rows

    def fact_lines(self, label, value, detail="", *, tag="", tag_style=PLAIN, mark="✓", mark_style=GOOD,
                   value_style=BOLD, extra=()) -> List[Text]:
        body = Text()
        body.append(str(value), value_style)
        if tag:
            body.append("  ")
            body.append(tag, tag_style)
        if detail:
            body.append("  " if not tag else " · ", DIM)
            body.append(str(detail), DIM)
        prefix = Text(" " * INDENT)
        prefix.append(mark.ljust(MARK), mark_style)
        prefix.append(label, LABEL_STYLE)
        prefix.append(" " * max(1, LABEL - cell_len(label)))
        indent = INDENT + MARK + LABEL
        rows = self.hanging_lines(prefix, body, indent)
        for line in extra:
            rows += self.hanging_lines(Text(" " * indent), line if isinstance(line, Text) else Text(str(line)), indent)
        return rows

    def surface(self, title: str, summary: Text, body: Sequence[Text]) -> List[Text]:
        """The approval region: its heading and the plan. On a terminal whose background is known (``probe``), a
        frosted wash of that background lies behind it, one cell short of the width, with half-row caps of the very
        same wash above and below so the text has air: no border, no stroke, no motion. Otherwise, and in plain
        output, the heading stands between blank lines on the terminal's own background."""
        heading = Text(" " * INDENT)
        heading.append(title, BOLD)
        heading.append("  ")
        rows = self.hanging_lines(heading, summary, INDENT + cell_len(title) + 2) + list(body)
        if not (self.tints and self.repaint):
            return [Text()] + rows + [Text()]
        span = self.width - 1
        ink = Style(color=self.tints.rich_surface)
        washed = [Text("▄" * span, ink)]
        for row in rows:
            # The row's colours, legible on the wash (Tints.rich_inks); bold values keep the terminal's foreground.
            row = Text(row.plain, style=_washed(row.style), spans=[
                Span(part.start, part.end, _washed(part.style)) for part in row.spans])
            row.pad_right(span - cell_len(row.plain))
            row.stylize_before(Style(bgcolor=self.tints.rich_surface))  # under the row's own colours
            washed.append(row)
        return washed + [Text("▀" * span, ink)]

    def note_lines(self, message, *, mark="↺", style=ACCENT, timing="") -> List[Text]:
        prefix = Text(" " * INDENT)
        prefix.append(mark.ljust(MARK), style)
        body = message.copy() if isinstance(message, Text) else Text(str(message))
        if timing:
            body.append("  " + timing, DIM)
        return self.hanging_lines(prefix, body, INDENT + MARK)

    # ---- permanent output ----

    def fact(self, label, value, detail="", **options):
        for line in self.fact_lines(label, value, detail, **options):
            self.print(line)

    def note(self, message, *, mark="↺", style=ACCENT, timing=""):
        for line in self.note_lines(message, mark=mark, style=style, timing=timing):
            self.print(line)

    # ---- the workspace ----

    def reserve(self, rows: int):
        """A prompt (or the activity line) may use this many rows under the workspace before its next repaint."""
        self._reserve = max(self._reserve, rows)

    def commit(self):
        """Leave the workspace as it is, as ordinary scrollback; the next ``show`` starts a new one below."""
        self._region = []
        self._reserve = 1

    def _render(self, lines: Sequence[Text]) -> str:
        with self.console.capture() as captured:
            for line in lines:
                self.console.print(line, width=self.width)
        return captured.get()

    def show(self, lines: Sequence[Text]):
        """Replace the workspace with ``lines`` (each a single row no wider than ``width``)."""
        lines = list(lines)
        old = self._region
        if lines == old:
            return
        if not self.repaint:
            same = next((index for index, (a, b) in enumerate(zip(old, lines)) if a != b), min(len(old), len(lines)))
            for line in lines[same:]:
                self._emit(line)
            self._region = lines
            return
        self.clear_status()
        columns, rows = self.size()
        up, start = 0, 0
        if old and columns == self._region_columns:
            # Rows above the screen can't be redrawn. The prompts since the last repaint pushed at most
            # ``excess`` workspace rows there; they are kept if unchanged, otherwise the new workspace is drawn
            # whole from the first row still on screen (the stale rows stay in scrollback, nothing above is lost).
            frozen = min(len(old), max(0, len(old) + self._reserve - (rows - 1)))
            up = len(old) - frozen
            start = frozen if lines[:frozen] == old[:frozen] else 0
        # A different width means the terminal may have re-flowed the old rows: they are left alone.
        output = (f"\x1b[{up}A" if up else "") + "\r\x1b[J" + self._render(lines[start:])
        with self._lock:
            self.stream.write(output)
            self.stream.flush()
        self._region, self._region_columns, self._reserve = lines, columns, 1
        self._blank = not lines or not lines[-1].plain.strip()

    def step(self, message, timing="", *, mark="✓", style=GOOD):
        self.note(message, mark=mark, style=style, timing=timing)

    def error(self, message):
        self.note(message, mark="✗", style=BAD_BOLD)

    def warn(self, message):
        self.note(message, mark="!", style=WARN_BOLD)

    def command(self, lines: Sequence[str], heading: str):
        """A copyable shell command: whole arguments per line with ``\\`` continuations, never a mid-token break."""
        self.print(Text(" " * INDENT + heading, DIM))
        rows = command_rows(lines, self.width - INDENT - MARK - 2)
        for index, (depth, row) in enumerate(rows):
            text = Text(" " * (INDENT + MARK + depth))
            text.append(row + (" \\" if index < len(rows) - 1 else ""), ACCENT)
            self.clear_status()
            # soft_wrap: a single argument wider than the terminal is wrapped by the terminal, not by a newline.
            self.console.print(text, soft_wrap=True)
        self._blank = False

    # ---- transient activity line (never part of scrollback) ----

    def brand(self, title: str) -> Text:
        """The title wordmark: bold, with the palette's gradient on a colour terminal."""
        text = Text()
        if not self.colors or self.console.no_color:
            text.append(title, BOLD)
            return text
        for char, color in zip(title, gradient(GRADIENTS[self.palette], len(title))):
            text.append(char, Style(color=color, bold=True))
        return text

    def _spinner(self, elapsed: float) -> str:
        """The spinner's frame at ``elapsed`` seconds: the next Braille glyph every frame, its colour gliding along
        the aurora and back (an eased cosine, so it lingers at the ends). Bold, so a thin glyph keeps its colour."""
        glyph = SPINNER[int(elapsed / FRAME) % len(SPINNER)]
        color = along(GRADIENTS[self.palette], (1 - math.cos(2 * math.pi * elapsed / SPIN_COLOR)) / 2)
        return f"{sgr(color, bold=True, palette=self.palette)}{glyph}\x1b[0m"

    def status(self, message: str, started: Optional[float] = None):
        """The transient operation line: the spinner in the mark column from the first frame, and the elapsed
        seconds after the first one. Without motion (reduced motion, NO_COLOR, TERM=dumb) it is drawn once with the
        still glyph and never changes while the work lasts: no timer, nothing else that moves."""
        if not self.live:
            return
        spinning = self.motion and self.colors and started is not None
        elapsed = time.monotonic() - started if spinning else 0.0
        suffix = f"  {int(elapsed)}s" if elapsed >= 1 else ""
        room = max(10, self.width - INDENT - MARK - cell_len(suffix) - 1)
        if cell_len(message) > room:
            message = message[:room - 1] + "…"
        if spinning:
            mark = self._spinner(elapsed)
        elif self.colors:
            mark = f"{sgr(PALETTES[self.palette]['accent'], bold=True, palette=self.palette)}{STILL}\x1b[0m"
        else:
            mark = STILL
        line = f"{' ' * INDENT}{mark} {message}" + (f"\x1b[2m{suffix}\x1b[0m" if suffix else "")
        with self._lock:
            if line == self._line:  # nothing moved (no motion): no redundant repaint
                return
            self.stream.write("\r\x1b[2K" + line)
            self.stream.flush()
            self._status, self._line = message, line

    def clear_status(self):
        with self._lock:
            if self._status:
                self.stream.write("\r\x1b[2K")
                self.stream.flush()
                self._status, self._line = "", ""

    @contextmanager
    def activity(self, message: str):
        """Show genuine read activity; the line disappears when the read returns or fails."""
        if self.plain:
            self.stream.write(f"{message}…\n")
            self.stream.flush()
            yield
            return
        started = time.monotonic()
        done = threading.Event()
        self.status(message, started)
        ticker = None
        if self.motion:
            def tick():
                while not done.wait(FRAME):
                    self.status(message, started)
            ticker = threading.Thread(target=tick, name="adr-setup-activity", daemon=True)
            ticker.start()
        try:
            yield
        finally:
            done.set()
            if ticker:
                ticker.join()
            self.clear_status()


# --------------------------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------------------------


class Picker:
    """Filtering and highlight state for one inline list. Pure, so it is unit-testable without a terminal."""

    def __init__(self, rows: Sequence[Row], default: str = "", create: str = "", text: str = "", *,
                 filterable: bool = True, focus_first: bool = False, action: Optional[Row] = None):
        self.rows = list(rows)
        # A command row pinned under the list, never filtered (e.g. "Another subscription…"). Only arrows focus it:
        # opening, typing or a search with no match never lands on it, so Enter keeps meaning "this answer".
        self.action = action
        self.default = default
        self.create = create
        self.text = text
        self.filterable = filterable
        self.focus_first = focus_first  # a resource picker always shows which row Enter takes
        self.limit = LIST_ROWS if filterable else CHOICE_ROWS
        self.index = -1
        self.top = 0
        self.reset()

    @property
    def query(self) -> str:
        return self.text.strip()

    def visible(self) -> List[Row]:
        return self.matches() + ([self.action] if self.action else [])

    def matches(self) -> List[Row]:
        query = self.query.casefold()
        if not query:
            return list(self.rows)
        starts = [row for row in self.rows if row.title.casefold().startswith(query)]
        found = starts + [row for row in self.rows if query in row.title.casefold() and row not in starts]
        if self.create and not any(row.title.casefold() == query for row in self.rows):
            found.insert(0, Row(self.query, self.query, self.create, "NEW"))
        return found

    def reset(self):
        rows = self.matches()
        if self.query:
            self.index = 0 if rows else -1
        else:
            # The default is highlighted when it is a local row (names and resource IDs compare case-insensitively).
            # A default that isn't one (a resource ID elsewhere, or a typed name) stays the answer Enter accepts:
            # only an empty field focuses the first row, so Enter never silently swaps a previous choice.
            default = self.default.casefold()
            self.index = next(
                (index for index, row in enumerate(rows) if default and default in (row.value.casefold(),
                                                                                    row.title.casefold())),
                0 if self.focus_first and rows and not default else -1,
            )
        self.top = 0
        self._scroll()

    def set_text(self, text: str):
        self.text = text
        self.reset()

    def move(self, step: int):
        rows = self.visible()
        if not rows:
            return
        if self.index < 0:
            self.index = 0 if step > 0 else len(rows) - 1
        else:
            self.index = (self.index + step) % len(rows)
        self._scroll()

    def _scroll(self):
        if self.index < 0:
            return
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + self.limit:
            self.top = self.index - self.limit + 1

    def current(self) -> Optional[Row]:
        rows = self.visible()
        return rows[self.index] if 0 <= self.index < len(rows) else None

    def acting(self) -> bool:
        """The command row is focused (the user moved onto it)."""
        return self.action is not None and self.current() == self.action

    def completion(self) -> Optional[str]:
        """Tab text: the highlighted existing row, or the first existing match when the typed NEW entry is highlighted."""
        rows = [row for row in self.visible() if row in self.rows]
        row = self.current()
        if row in self.rows:
            return row.title
        return rows[0].title if rows else None

    def accept(self) -> Optional[str]:
        """The highlighted row, else the typed text, else the default; None when there is nothing to accept."""
        row = self.current()
        if row:
            return row.value
        return self.query or self.default or None


def _hint_fragments(pairs):
    fragments = [("", " " * (INDENT + MARK))]
    for index, (key, description) in enumerate(pairs):
        if index:
            fragments.append(("class:hint", " · "))
        if key:
            fragments.append(("class:key", key))
        if description:
            fragments.append(("class:hint", (" " if key else "") + description))
    return fragments


def wrapped_lines(text: str, columns: int, indent: int) -> List[str]:
    """The rows a hanging block of text occupies: drawing and row reservation share this, so they always agree."""
    return textwrap.wrap(text, max(8, min(columns, MAX_WIDTH) - indent - 1), break_on_hyphens=False) or [""]


def wrapped_fragments(text: str, style: str, columns: int, indent: int):
    """Word-wrap help or error text into a hanging block; prompt_toolkit's own wrapping splits words."""
    lines = wrapped_lines(text, columns, indent)
    fragments = []
    for index, line in enumerate(lines):
        fragments.extend([("", ("\n" if index else "") + " " * indent), (style, line)])
    return fragments


def _match_fragments(title: str, query: str, selected: bool):
    base = "class:selected" if selected else "class:name"
    match = "class:selected-match" if selected else "class:match"
    start = title.casefold().find(query.casefold()) if query else -1
    if start < 0:
        return [(base, title)]
    end = start + len(query)
    return [(base, title[:start]), (match, title[start:end]), (base, title[end:])]


def list_fragments(picker: Picker, columns: int, *, captioned: bool = False, marked=None, focus: str = "",
                   inks: Optional[Dict[str, str]] = None):
    """The list window. ``marked`` (a multi-select's chosen values) adds a check column after the pointer. ``focus``
    (a prompt_toolkit background such as 'bg:#24303c') washes the focused row from the cell left of its pointer to
    a width all rows of the window share, so the wash keeps its size as focus moves; ``inks`` (``focus_inks``)
    restyles that row's text so it stays legible on the wash."""
    rows = picker.visible()
    if not rows:
        return []
    window = rows[picker.top:picker.top + picker.limit]
    name_width = min(max(cell_len(row.title) for row in window), 40)
    built = []
    for offset, row in enumerate(window):
        selected = picker.top + offset == picker.index
        cells = [("class:pointer", POINTER + " ") if selected else ("", "  ")]
        used = INDENT + MARK + 2 + max(cell_len(row.title), name_width)
        if marked is not None:
            cells.append(("class:marked", "✓ ") if row.value in marked else ("", "  "))
            used += 2
        if row == picker.action:  # a command, not a resource: never search-highlighted
            cells.append(("class:selected" if selected else "class:action", row.title))
        else:
            cells.extend(_match_fragments(row.title, picker.query, selected))
        cells.append(("", " " * max(0, name_width - cell_len(row.title))))
        if row.tag:
            cells.append(("class:new" if row.tag == "NEW" else "class:reuse", "  " + row.tag))
            used += 2 + len(row.tag)
        room = columns - used - 3
        if row.detail and room > 8:
            detail = row.detail if cell_len(row.detail) <= room else row.detail[:room - 1] + "…"
            cells.append(("class:selected-detail" if selected else "class:detail", "  " + detail))
        built.append((selected, cells))
    # One cell of air after the longest row, never into the last column.
    span = min(max(sum(cell_len(text) for _, text in cells) for _, cells in built) + 1, columns - INDENT - MARK - 1)
    fragments = []
    for selected, cells in built:
        if selected and focus:
            pad = max(0, span - sum(cell_len(text) for _, text in cells))
            fragments.append(("", " " * (INDENT + MARK - 1)))
            fragments.extend((f"{inks.get(style, style) if inks else style} {focus}".strip(), text)
                             for style, text in [("", " ")] + cells + [("", " " * pad)])
        else:
            fragments.append(("", " " * (INDENT + MARK)))
            fragments.extend(cells)
        fragments.append(("", "\n"))
    if len(rows) > picker.limit:
        last = min(len(rows), picker.top + picker.limit)
        more = "type to filter" if picker.filterable and not captioned else "↑↓ for more"  # caption says it
        fragments.append((
            "class:hint",
            f"{' ' * (INDENT + MARK + 2)}{picker.top + 1}–{last} of {len(rows)} · {more}",
        ))
    else:
        fragments.pop()  # no trailing newline under a short list
    return fragments


def focus_inks(tints: Optional[Tints]) -> Dict[str, str]:
    """The focused row's styles on its wash: the name and detail in the terminal's own foreground (bold name), and
    the pointer, match, check and tags in their colours made legible on the wash (``Tints.inks``, 4.5:1 or more)."""
    if not tints:
        return {}
    ink = tints.inks
    return {
        "class:pointer": f"{ink['accent']} bold",
        "class:selected": "bold noreverse",
        "class:selected-match": f"{ink['match']} bold noreverse",
        "class:selected-detail": "noreverse",
        "class:marked": f"{ink['create']} bold",
        "class:new": f"{ink['create']} bold",
        "class:reuse": f"{ink['reuse']} bold",
    }


def caption_fragments(picker: Picker, caption, columns: int):
    """One line between the question and its list: how many resources there are, or why there are none."""
    text = caption(len([row for row in picker.visible() if row in picker.rows]), len(picker.rows), picker.query)
    return wrapped_fragments(text, "class:caption", columns, CAPTION_INDENT) if text else []


def caption_height(picker: Picker, caption, columns: int) -> int:
    """The most rows the caption can wrap to while the user types: unfiltered, some matches, or none."""
    if not caption:
        return 0
    total = len(picker.rows)
    texts = (caption(total, total, ""), caption(total, total, "?"), caption(0, total, "?"))
    return max(len(wrapped_lines(text, columns, CAPTION_INDENT)) if text else 0 for text in texts)


def prompt_height(picker: Picker, columns: int, *, label="", value="", help_text=None, error="", hint=(),
                  caption=None, grow=0) -> int:
    """The most rows one prompt can occupy: its question (a long value wraps), help, caption, list window with its
    "more" line, an inline error (room for one even before any is shown) and the key hints."""
    room = max(8, columns - INDENT - MARK - LABEL)
    question = 1 + (cell_len(label) > LABEL) + cell_len(value) // room
    width = max(8, min(columns, MAX_WIDTH) - INDENT - MARK - LABEL - 1)
    help_rows = len(textwrap.wrap(help_text, width, break_on_hyphens=False)) if help_text else 0
    total = len(picker.rows) + bool(picker.create) + bool(picker.action) + grow
    list_rows = min(total, picker.limit) + (total > picker.limit)
    error_rows = max(1, len(textwrap.wrap(error, max(8, min(columns, MAX_WIDTH) - INDENT - MARK - 1),
                                          break_on_hyphens=False)))
    return (question + help_rows + caption_height(picker, caption, columns) + list_rows + error_rows
            + hint_height(hint, columns))


def hint_height(hint, columns: int) -> int:
    """Key hints fit one row; on a very narrow terminal they wrap, continuing under the hint column."""
    keys = cell_len("".join(text for _, text in _hint_fragments(hint)))
    return 1 + max(0, -(-(keys - columns) // max(1, columns - INDENT - MARK)))


class TerminalPrompter:
    """prompt_toolkit inline prompts: one active question, erased when answered (the workspace shows the answer).

    ``reserve`` is told the most rows a prompt can take (question, help, list window, an inline error, keys), so
    the workspace above knows how far the terminal may scroll before it is repainted."""

    def __init__(self, stream=None, *, input=None, output=None, reserve=None,  # pylint: disable=redefined-builtin
                 palette="ansi", tints: Optional[Tints] = None, motion=False, replies=None, typed=""):
        self.stream = stream or sys.stderr
        self.input = input
        self.output = output
        self.reserve = reserve or (lambda rows: None)
        self.palette = palette  # the Screen's, so prompts and the workspace share one set of colours
        self.tints = tints  # the Screen's washes; None keeps the terminal's own background
        self.motion = motion
        self.replies = replies  # removes late answers to the Screen's background query from the keys
        self.typed = typed  # keys typed during that query, for the first prompt

    def _input(self):
        """The input this prompt reads: answers to the background query are filtered out of it, and keys typed
        while setup asked come first."""
        from prompt_toolkit.application.current import get_app_session

        source = self.input or get_app_session().input
        if self.replies:
            self.replies.attach(source)
        if self.typed:
            from prompt_toolkit.input.typeahead import store_typeahead
            from prompt_toolkit.input.vt100_parser import Vt100Parser

            keys = []
            parser = Vt100Parser(keys.append)
            parser.feed(self.typed)
            parser.flush()
            store_typeahead(source, keys)
            self.typed = ""
        return source

    def _output(self):
        if self.output is None:
            from prompt_toolkit.output.defaults import create_output

            self.output = create_output(stdout=self.stream)
        return self.output

    def ask(self, label, rows=(), *, default="", initial="", error="", create="", hint=None, caption=None,
            focus_first=False, action=None):
        return self._run(label, rows, text=True, default=default, initial=initial, error=error, create=create,
                         hint=hint, caption=caption, focus_first=focus_first, action=action)

    def select(self, label, rows, *, default="", error="", hint=None, help="",  # pylint: disable=redefined-builtin
               summary=""):
        return self._run(label, rows, text=False, default=default, error=error, help_text=help, summary=summary,
                         hint=hint or [("↑↓", "choose"), ("enter", "accept"), ("esc", "back")])

    def ask_many(self, label, rows=(), *, limit, marked=(), initial="", error="", caption=None, hint=None,
                 action=None):
        """A searchable list where Space marks several rows (names and resource IDs never contain spaces) and Enter
        takes them; with nothing marked, Enter takes the focused row or typed text, like ``ask``. Enter on the
        ``action`` row returns ``[action.value + the field's text]`` followed by the marks, so the search and the
        marks survive whatever it opens."""
        return self._run(label, rows, text=True, initial=initial, error=error, caption=caption, focus_first=True,
                         multi=(limit, list(marked)), action=action, hint=hint or [
                             ("↑↓", "choose"), ("space", "select"), ("enter", "check"), ("tab", "complete"),
                             ("esc", "back")])

    def confirm(self, label, *, default=False, hint=""):
        answer = self._run(label, (), text=False, default="y" if default else "n", confirm=True, help_text=hint,
                           hint=[("y", "yes"), ("n", "no"), ("enter", "default"), ("esc", "back")])
        return answer == "y"

    def _run(self, label, rows, *, text, default="", initial="", error="", create="", hint=None, confirm=False,
             help_text="", caption=None, focus_first=False, summary="", multi=None, action=None):
        from prompt_toolkit.application import Application
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.document import Document
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import ConditionalContainer, Float, FloatContainer, HSplit, Layout, VSplit, Window
        from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
        from prompt_toolkit.output.color_depth import ColorDepth
        from prompt_toolkit.styles import Style as PromptStyle

        picker = Picker(rows, default=default, create=create, text=initial, filterable=text, focus_first=focus_first,
                        action=action)
        if not text and picker.index < 0 and rows:
            picker.index = 0  # a choice list always has a focused row, even without (or with a stale) default
        state = {"error": error}
        limit, marked = multi if multi else (0, None)
        if caption and multi:
            # The caption also counts the marked rows; its height allows for the longest count.
            base = caption

            def caption(shown, total, query, most=False):
                count = limit if most else len(marked)
                return base(shown, total, query) + (f" · {count} selected" if count else "")
        buffer = Buffer(document=Document(initial, len(initial)), multiline=False)

        def changed(_buffer):
            state["error"] = ""
            picker.set_text(buffer.text)

        buffer.on_text_changed += changed
        bindings = KeyBindings()

        def finish(event, value):
            event.app.exit(result=value)

        moved = {"at": None}
        inks = focus_inks(self.tints)

        def wash():
            """The focused row's wash: half strength just after a move, full once it settles."""
            if not self.tints:
                return ""
            if moved["at"] is not None and time.monotonic() - moved["at"] < FOCUS_SETTLE:
                return "bg:" + mix(self.tints.background, self.tints.focus, FOCUS_FROM)
            return "bg:" + self.tints.focus

        def settle(event):
            """After a move with motion: the new row's wash fades in, one repaint at half strength and one, a moment
            later, at full; then nothing is redrawn until the next key."""
            if self.motion and self.tints:
                moved["at"] = time.monotonic()
                asyncio.get_running_loop().call_later(FOCUS_SETTLE, event.app.invalidate)

        @bindings.add("up")
        @bindings.add("c-p")
        def _up(event):
            picker.move(-1)
            settle(event)

        @bindings.add("down")
        @bindings.add("c-n")
        def _down(event):
            picker.move(1)
            settle(event)

        @bindings.add("enter")
        def _enter(event):
            if confirm:
                finish(event, default)
                return
            if picker.acting():  # the command row, reached with the arrows; the field's text and marks travel with it
                chosen = action.value + buffer.text
                finish(event, [chosen] + list(marked) if multi else chosen)
                return
            if multi and marked:
                # An empty field, or a search that only filters the list, commits exactly the marks: moving the
                # pointer never adds a Hub. A Hub itself in the field (a listed one typed in full, or a name or ID
                # matching none, e.g. put back after a failed check) is neither dropped nor added unasked: Space adds.
                value = pending()
                if value is None:
                    finish(event, list(marked))
                elif len(marked) < limit:
                    state["error"] = f"Space adds {value} · or clear the field to check the {len(marked)} selected."
                else:
                    state["error"] = (f"{limit} at most here · unmark one to add {value}, or clear the field to "
                                      f"check the {len(marked)} selected.")
                return
            value = picker.accept()
            if value is None:
                state["error"] = "Type a value or choose one with ↑↓." if rows else "Type a value."
                return
            finish(event, [value] if multi else value)

        if multi:
            def pending():
                """The Hub the field names that isn't marked yet, else None (empty, or only a search)."""
                query = picker.query
                if not query:
                    return None
                exact = next((row for row in picker.rows if query.casefold() in (
                    row.value.casefold(), row.title.casefold())), None)
                if exact:
                    return None if exact.value in marked else exact.title
                return None if picker.matches() else _short(query)

            @bindings.add(" ")
            def _mark(_event):
                row = picker.current()
                value = row.value if row else picker.query
                if not value or picker.acting():  # a command can't be marked
                    return
                if not row:  # a name or ID typed in another case is that listed row, never a second one
                    row = next((row for row in picker.rows if value.casefold() in (
                        row.value.casefold(), row.title.casefold())), None)
                    value = row.value if row else value
                if value in marked:
                    marked.remove(value)
                elif len(marked) >= limit:
                    state["error"] = f"{limit} at most here · space on a ✓ row unmarks it · enter checks them."
                    return
                else:
                    marked.append(value)
                    if not row:  # a typed name or resource ID joins the list, so it shows its ✓ and can be unmarked
                        picker.rows.append(Row(value, value, "typed · checked on enter"))
                state["error"] = ""
                if buffer.text:  # the search is done: the field is ready for the next one
                    buffer.text = ""

        @bindings.add("tab")
        def _complete(_event):
            title = picker.completion()
            if text and title:
                buffer.document = Document(title, len(title))

        @bindings.add("escape", eager=True)
        def _back(event):
            event.app.exit(exception=BackRequested())

        @bindings.add("c-c")
        def _cancel(event):
            event.app.exit(exception=KeyboardInterrupt())

        @bindings.add("c-d")
        def _eof(event):
            if not buffer.text:
                event.app.exit(exception=KeyboardInterrupt())

        if confirm:
            for key, value in (("y", "y"), ("Y", "y"), ("n", "n"), ("N", "n")):
                bindings.add(key)(lambda event, value=value: finish(event, value))
        elif not text:
            for number, row in enumerate(rows[:9], start=1):
                bindings.add(str(number))(lambda event, row=row: finish(event, row.value))

        head = [("", " " * INDENT), ("class:mark", "? "), ("class:label", label.ljust(LABEL))]
        if summary:
            head.append(("class:choice", summary))
        if confirm:  # the default answer, the one Enter takes, carries the focus colour
            head += [("class:choice-default", "Y"), ("class:choice", "/n")] if default == "y" else [
                ("class:choice", "y/"), ("class:choice-default", "N")]

        def columns():
            return self._output().get_size().columns

        # Every window is content-sized (dont_extend_height): an inline prompt must not stretch to the
        # bottom of the terminal, which would push its list and help away from the question. A row the terminal
        # is too narrow for continues under its own text, never in the rail's column.
        def block(content, hang=INDENT + MARK, **options):
            return Window(FormattedTextControl(content, **options), wrap_lines=True, dont_extend_height=True,
                          always_hide_cursor=True,
                          get_line_prefix=lambda _line, wrapped: [("", " " * hang)] if wrapped else [])

        if text:
            placeholder = ConditionalProcessor(
                AfterInput(default, style="class:placeholder"), filter=Condition(lambda: not buffer.text),
            )
            prefix = Window(FormattedTextControl(head), width=Dimension.exact(INDENT + MARK + LABEL),
                            dont_extend_width=True, dont_extend_height=True)
            field = Window(BufferControl(buffer, input_processors=[placeholder]), style="class:input",
                           wrap_lines=True, dont_extend_height=True)
            first = VSplit([prefix, field])
            focus = field
        else:
            first = block(head, focusable=True, show_cursor=False)
            focus = first
        parts = [first]
        if help_text:
            # The explanation hangs under the answer column and wraps on word boundaries.
            parts.append(block(lambda: wrapped_fragments(help_text, "class:detail", columns(),
                                                         INDENT + MARK + LABEL)))
        if caption:
            parts.append(ConditionalContainer(block(lambda: caption_fragments(picker, caption, columns())),
                                              filter=Condition(lambda: bool(caption_fragments(picker, caption, columns())))))
        if rows or multi or action:  # typed values a multi-select marks join its list
            # Hidden while filtering leaves no match: an empty list must not leave a blank row under the question.
            def listing():
                return list_fragments(picker, columns(), captioned=bool(caption), marked=marked, focus=wash(),
                                      inks=inks)

            parts.append(ConditionalContainer(block(listing, hang=INDENT + MARK + 2),
                                              filter=Condition(lambda: bool(picker.visible()))))
        problem = ConditionalContainer(
            block(lambda: [("", " " * INDENT), ("class:error-mark", "✗ ")] + wrapped_fragments(
                state["error"], "class:error", columns(), INDENT + MARK)[1:]),
            filter=Condition(lambda: bool(state["error"])),
        )
        if hint is None:
            hint = [("↑↓", "choose"), ("enter", "accept"), ("tab", "complete"), ("esc", "back")] if rows else [
                ("enter", "accept"), ("esc", "back"),
            ]
        footer = block(_hint_fragments(hint))
        self.reserve(prompt_height(
            picker, columns(), label=label, value=initial or default or summary, help_text=help_text, error=error,
            hint=hint, caption=(lambda shown, total, query: caption(shown, total, query, most=True)) if (
                caption and multi) else caption, grow=limit))  # each typed mark can add a list row
        # The focus rail: one accent column down the whole active prompt, drawn over the indent's first (always
        # blank) column, so it adds no width, no row and no wrapping, and goes when the prompt is erased. It is
        # exactly as tall as the prompt's content, never the free rows prompt_toolkit may have below it.
        content = HSplit(parts + [problem, footer])
        body = FloatContainer(content, floats=[Float(
            Window(char=RAIL, style="class:rail", width=1), left=0, top=0, width=1,
            height=lambda: content.preferred_height(columns(), 10 ** 4).preferred,
        )])
        app = Application(
            layout=Layout(body, focused_element=focus),
            key_bindings=bindings,
            style=PromptStyle.from_dict(prompt_style(self.palette)),
            # Hex colours render at the Screen's depth (24-bit, or nearest 256-colour); ANSI keeps the terminal's own.
            color_depth={"truecolor": ColorDepth.TRUE_COLOR, "256": ColorDepth.DEPTH_8_BIT}.get(self.palette),
            full_screen=False,
            erase_when_done=True,
            mouse_support=False,
            include_default_pygments_style=False,
            input=self._input(),
            output=self._output(),
        )
        # While an answer to the background query may still arrive, an Esc waits a little longer for what follows
        # it, so a slow answer split after its Esc is still recognised; a lone Esc still means Back.
        app.ttimeoutlen = LATE_ESCAPE if self.replies and self.replies.outstanding else 0.05
        app.timeoutlen = 0.05
        return app.run()


class PlainPrompter:
    """Line prompts without ANSI for --plain: numbered choices, [defaults], and :back / :quit commands."""

    def __init__(self, stream=None, reader=None):
        self.stream = stream or sys.stderr
        self.reader = reader or sys.stdin.readline

    def _write(self, text):
        self.stream.write(text)
        self.stream.flush()

    def _line(self, prompt):
        self._write(prompt)
        line = self.reader()
        if not line:
            raise KeyboardInterrupt()
        answer = line.strip()
        if answer in (":back", ":edit"):
            raise BackRequested()
        if answer in (":quit", ":q"):
            raise KeyboardInterrupt()
        return answer

    def ask(self, label, rows=(), *, default="", initial="", error="", create="", free=True, hint=None, caption=None,
            focus_first=False, help="", action=None):  # pylint: disable=redefined-builtin
        del initial, create, focus_first
        rows = list(rows) + ([action] if action else [])  # the command is the last number
        if error:
            self._write(f"  ! {error}\n")
        if help:
            self._wrapped(help)
        if caption:
            self._write(f"    {caption(len(rows) - bool(action), len(rows) - bool(action), '')}\n")
        for number, row in enumerate(rows, start=1):
            detail = f"  {row.detail}" if row.detail else ""
            self._write(f"    {number}) {row.title}{detail}\n")
        if hint:
            self._write("    " + " · ".join(" ".join(part for part in pair if part) for pair in hint) + "\n")
        suffix = f" [{default}]" if default else ""
        while True:
            answer = self._line(f"  {label}{suffix} ")
            if not answer and default:
                return default
            if answer.isdigit() and 1 <= int(answer) <= len(rows):
                return rows[int(answer) - 1].value
            match = next((row.value for row in rows if row.title.casefold() == answer.casefold()), None)
            if match:
                return match
            if answer and free:
                return answer
            self._write("  ! Enter a listed number" + (" or a value" if free else "") + ". :back goes back.\n")

    def select(self, label, rows, *, default="", error="", hint=None, help="",  # pylint: disable=redefined-builtin
               summary=""):
        del hint  # numbered choices and :back already say how to answer
        default_title = next((row.title for row in rows if row.value == default), rows[0].title)
        value = self.ask(label, rows, default=default_title, error=error, free=False,
                         help=" · ".join(part for part in (summary, help) if part))
        return next((row.value for row in rows if value in (row.value, row.title)), value)

    def ask_many(self, label, rows=(), *, limit, marked=(), initial="", error="", caption=None, hint=None,
                 action=None):
        """Numbers or names separated by spaces or commas; each a listed row or a typed name or resource ID.
        Enter alone keeps the marked values a previous answer left (shown in brackets). The ``action`` row's
        number returns ``[action.value]`` and the marks, like the terminal prompt."""
        del hint, initial
        rows = list(rows) + ([action] if action else [])
        if error:
            self._write(f"  ! {error}\n")
        if caption:
            self._write(f"    {caption(len(rows) - bool(action), len(rows) - bool(action), '')}\n")
        for number, row in enumerate(rows, start=1):
            detail = f"  {row.detail}" if row.detail else ""
            self._write(f"    {number}) {row.title}{detail}\n")
        titles = {row.value: row.title for row in rows}
        suffix = f" [{' '.join(titles.get(value, value) for value in marked)}]" if marked else ""
        while True:
            answer = self._line(f"  {label}{suffix} (numbers or names, up to {limit}) ")
            if not answer and marked:
                return list(marked)
            values = []
            for token in re.split(r"[\s,]+", answer):
                if token.isdigit() and 1 <= int(token) <= len(rows):
                    values.append(rows[int(token) - 1].value)
                elif token:
                    values.append(next((row.value for row in rows if token.casefold() in (
                        row.title.casefold(), row.value.casefold())), token))
            values = list(dict.fromkeys(values))
            if action and action.value in values:
                if len(values) == 1:
                    return [action.value] + list(marked)
                # Never one silently dropped: the command and a selection are separate answers.
                self._write(f"  ! Enter {len(rows)} alone to choose {action.title.rstrip('…')}; the "
                            f"{'marks are' if marked else 'list is'} kept. Then choose resources there.\n")
                continue
            if values and len(values) <= limit:
                return values
            self._write(f"  ! Enter 1 to {limit} numbers or names. :back goes back.\n" if values else
                        "  ! Enter one or more numbers or names. :back goes back.\n")

    def _wrapped(self, text):
        width = max(20, min(shutil.get_terminal_size().columns, MAX_WIDTH) - 5)
        self._write("".join(f"    {line}\n" for line in textwrap.wrap(text, width, break_on_hyphens=False)))

    def confirm(self, label, *, default=False, hint=""):
        if hint:
            self._wrapped(hint)
        while True:
            answer = self._line(f"  {label} {'[Y/n]' if default else '[y/N]'} ").casefold()
            if not answer:
                return default
            if answer in ("y", "yes", "n", "no"):
                return answer.startswith("y")
            self._write("  ! Enter y or n. :back goes back.\n")


# --------------------------------------------------------------------------------------------
# Apply progress
# --------------------------------------------------------------------------------------------


class Progress:
    """NamespaceWorkflow progress adapter: forwards observed operations to the UI thread as events."""

    def __init__(self):
        self.events: "queue.Queue" = queue.Queue()
        self.stop = threading.Event()
        self.items: List[Any] = []

    def observe_items(self, items):
        self.items = items

    def run(self, label, operation, *args, workflow_scope=None, mutation=False, handled_error=None, **kwargs):
        del workflow_scope
        if self.stop.is_set():
            raise SetupStopped("Stopped before the next Azure request.")
        self.events.put(("start", label, mutation))
        try:
            result = operation(*args, **kwargs)
        except Exception as error:
            if handled_error and handled_error(error):
                self.events.put(("done", label, mutation))
            else:
                self.events.put(("fail", label, mutation, error))
            raise
        self.events.put(("done", label, mutation))
        return result


class PlanTarget:
    """Plan-read progress that only remembers which endpoint the engine is checking ("Validate hub <endpoint>"),
    so a problem that names no resource (``--hub.resourceName is unavailable``) still reaches the right IoT Hub.
    It runs each operation exactly as the engine would without progress."""

    LABEL = re.compile(r"Validate (dps|hub|software-updates) (\S+)$")

    def __init__(self):
        self.current: Optional[tuple] = None

    def run(self, label, operation, *args, workflow_scope=None, mutation=False, handled_error=None, **kwargs):
        del workflow_scope, mutation, handled_error
        match = self.LABEL.match(label)
        if not match:
            self.current = None
        elif match.group(2) != "creation":  # "Validate hub creation" continues the endpoint checked before it
            self.current = (match.group(1), match.group(2).casefold())
        return operation(*args, **kwargs)


@contextmanager
def quiet_providers():
    from azext_iot.adr.providers.base import console

    previous = console.quiet
    console.quiet = True
    try:
        yield
    finally:
        console.quiet = previous


@contextmanager
def no_echo(stream):
    """Hide stray keystrokes during apply so they cannot tear the activity line; Ctrl+C still works."""
    try:
        import termios
    except ImportError:  # termios is POSIX-only; other consoles keep their default echo
        yield
        return
    try:
        descriptor = stream.fileno()
        previous = termios.tcgetattr(descriptor)
    except (AttributeError, OSError, ValueError, termios.error):  # not a terminal: nothing to hide
        yield
        return
    changed = list(previous)
    changed[3] &= ~termios.ECHO
    termios.tcsetattr(descriptor, termios.TCSANOW, changed)
    try:
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSANOW, previous)


# --------------------------------------------------------------------------------------------
# Guided flow
# --------------------------------------------------------------------------------------------


def _plan_order(item):
    key = item.get("id", "")
    stages = (
        lambda: key == "namespace" or (key.startswith("namespace-") and key != "namespace-status"),
        lambda: key.startswith("resource-"),
        lambda: key.startswith(("link-", "roles-")) or key in {"dps-allocation-warning", "hub-prerequisite"},
        lambda: key.startswith("cms-"),
        lambda: key == "namespace-status",
    )
    return next((index for index, match in enumerate(stages) if match()), len(stages))


def ordered_items(plan):
    """Plan rows in execution order, each link followed by its role row; skipped capabilities last."""
    items = sorted(plan.get("items", []), key=_plan_order)
    roles = {item["id"][len("roles-"):]: item for item in items if item.get("id", "").startswith("roles-")}
    result = []
    for item in items:
        if item.get("id", "").startswith("roles-"):
            continue
        result.append(item)
        if item.get("id", "").startswith("link-"):
            role = roles.pop(item["id"][len("link-"):], None)
            if role:
                result.append(role)
    return result + list(roles.values())


# Plan glyphs: one shape per kind of change, so the plan also reads without colour (NO_COLOR, --plain). Creating a
# resource, linking it and assigning roles are separate kinds of change and never share a glyph.
TAGS = {
    "new": ("✦", "NEW", GOOD_BOLD),
    "link": ("⇄", "LINK", LINK_BOLD),
    "role": ("◇", "ROLES", ROLE_BOLD),
    "update": ("◐", "UPDATE", ACCENT_BOLD),
    "reuse": ("○", "REUSE", REUSE_BOLD),
    "check": ("·", "CHECK", PLAIN),
    "blocked": ("✗", "BLOCKED", BAD_BOLD),
    "warning": ("!", "WARNING", WARN_BOLD),
    "skip": ("–", "SKIP", DIM),
    "manual": ("!", "MANUAL", WARN_BOLD),
}


def item_tag(item, new_namespace=False) -> str:
    state, action = item.get("state"), item.get("action")
    if new_namespace and item.get("id") == "namespace-outbound-identity" and state == "Planned":
        return "new"
    if state in ("Blocked", "Failed"):
        return "blocked"
    if state == "Warning":
        return "warning"
    if state == "Manual":
        return "manual"
    if action == "skip":
        return "skip"
    if action == "role":
        return "role"
    if state == "Planned":
        return {"create": "new", "link": "link", "configure": "update", "check": "check"}.get(action, "update")
    return "check" if action == "check" else "reuse"


def item_kind(key: str) -> str:
    prefixes = {kind: (f"resource-{kind}-", f"link-{kind}-", f"roles-{kind}-", f"skip-{kind}") for kind in KIND_LABELS}
    return next((kind for kind, starts in prefixes.items() if key.startswith(starts)), "")


def item_label(item) -> str:
    key = item.get("id", "")
    fixed = {
        "namespace": "Namespace:", "namespace-tags": "Tags:", "namespace-outbound-identity": "Outbound identity:",
        "namespace-status": "Readiness:", "cms-root": "CMS:", "cms-intermediate": "CMS:", "cms-policy": "CMS:",
        "dps-allocation-warning": "DPS:", "hub-prerequisite": "IoT Hub:",
    }
    if key in fixed:
        return fixed[key]
    if key.startswith("roles-"):
        return "Roles:"
    kind = item_kind(key)
    return KIND_LABELS[kind] + ":" if kind else "Check:"


def inbound_identity(kind: str, details: Dict[str, Any]) -> str:
    """The managed identity a link's target uses toward the namespace, e.g. 'IoT Hub system-assigned managed
    identity' — built from parts; a user-assigned identity's name is appended verbatim."""
    owner = IDENTITY_OWNERS.get(kind, "Target")
    assigned = _short(details.get("userAssignedIdentity"))
    if assigned:
        return f"{owner} user-assigned managed identity {assigned}"
    kind_of = str(details.get("identityType") or "").replace("-", "").lower()  # 'system-assigned' or 'SystemAssigned'
    if kind_of in ("systemassigned", "userassigned"):
        return f"{owner} {kind_of[:-8]}-assigned managed identity"
    return f"{owner} managed identity"


def item_detail(item, namespace, *, identity=True) -> str:
    details = item.get("details") or {}
    key = item.get("id", "")
    parts = []
    if key.startswith("resource-") and details.get("sku"):
        parts += [str(details["sku"]), f"{details.get('unit', 1)} unit"]
    if details.get("location"):
        parts.append(str(details["location"]))
    if key == "namespace-outbound-identity":
        parts.append("namespace managed identity")
    elif key.startswith("link-"):
        if str(item.get("target")) != _short(details.get("resourceId")):
            parts.append("endpoint " + str(item.get("target")))
        if identity and (details.get("userAssignedIdentity") or details.get("identityType")):
            parts.append(inbound_identity(item_kind(key), details))
    elif key.startswith("roles-"):  # shown only when it needs attention; its tag and message say what
        parts.append("role access for the link")
    elif key.startswith("cms-"):
        parts.append({"cms-root": "root CA", "cms-intermediate": "intermediate CA",
                      "cms-policy": "certificate policy"}[key])
    if details.get("tags"):
        parts.append(" ".join(f"{name}={value}" for name, value in sorted(details["tags"].items())))
    del namespace
    return " · ".join(part for part in parts if part)


def role_lines(item, namespace, inbound: str = "") -> List[Text]:
    """A link's service-to-service roles (rbac.LINK_ROLE_MATRIX), one row per identity and scope:
    'Namespace outbound managed identity → Contributor on hub'. Role names and scopes are verbatim."""
    details = item.get("details") or {}
    kind = item_kind(item.get("id", ""))
    link_type = "su" if kind == "software-updates" else kind
    target = _short(details.get("targetScope") or item.get("target"))
    principals = {
        "namespace": "Namespace outbound managed identity",
        "linked": inbound or f"{IDENTITY_OWNERS.get(kind, 'Target')} managed identity",
        "namespace_system": "Namespace system-assigned managed identity",
    }
    groups: Dict[tuple, List[str]] = {}
    for rule in LINK_ROLE_MATRIX.get(link_type, ()):
        scope = target if rule.scope == "target" else namespace
        groups.setdefault((principals[rule.principal], scope), []).append(rule.role)
    lines = []
    for (principal, scope), roles in groups.items():
        line = Text(principal)
        line.append(" → ", DIM)
        for index, role in enumerate(roles):
            line.append(", " if index else "", DIM)
            line.append(role, BOLD)
        line.append(" on ", DIM)
        line.append(scope)
        lines.append(line)
    return lines


# Role checks aren't counted: the approval view leaves roles to the engine (see ``plan_entries``).
COUNTED = (("new", "new"), ("link", "link"), ("update", "update"), ("reuse", "reuse"), ("blocked", "blocked"),
           ("warning", "warning"))


def plan_counts(items, new_namespace=False) -> List[tuple]:
    """(tag, count, words) per kind of change, in reading order; the plan heading shows them with their glyphs,
    so it doubles as the legend."""
    counts: Dict[str, int] = {}
    for item in items:
        tag = item_tag(item, new_namespace)
        counts[tag] = counts.get(tag, 0) + 1
    return [
        (tag, counts[tag], label + ("s" if counts[tag] != 1 and tag in ("link", "update", "warning") else ""))
        for tag, label in COUNTED if counts.get(tag)
    ]


class Entry(NamedTuple):
    key: str
    label: str
    value: str
    detail: str
    tag: str
    extra: List[Any]
    roles: List[Text] = []


ATTENTION = ("blocked", "warning", "manual")


def plan_entries(items, namespace, new_namespace=False, where: Callable[[str], str] = lambda _: "") -> List[Entry]:
    """Compact plan rows. The namespace row is left to the scope rows above the plan unless it changes; Azure-managed
    CMS pieces with the same outcome share one row. Problems never merge.

    Role assignments and role checks are the engine's business: it still checks and grants them, and the JSON plan,
    saved configuration and script keep them in full, but the approval view shows only what is created, reused,
    updated and linked. A role item that needs attention (blocked, warning, manual) stays, with its message and the
    identity, roles and scope it concerns, so the problem remains actionable. ``where`` names a target's resource
    group and subscription when they aren't the namespace's, so a target elsewhere never reads as a local one."""
    entries: List[Entry] = []
    inbound: Dict[str, str] = {}
    for item in items:
        key, tag = item.get("id", ""), item_tag(item, new_namespace)
        message = identity_words(item.get("message")) if tag in ATTENTION else ""
        if key == "namespace" and tag in ("new", "reuse", "check"):
            continue
        if key.startswith("roles-") and tag not in ATTENTION:
            continue
        previous = entries[-1] if entries else None
        if key.startswith("link-"):
            inbound[key[len("link-"):]] = inbound_identity(item_kind(key), item.get("details") or {})
        name = _short(item.get("target")) if str(item.get("target", "")).startswith("/") else item.get("target")
        if key == "namespace-outbound-identity":
            name = _short((item.get("details") or {}).get("userAssignedIdentity")) or "system-assigned"
        if key.startswith("cms-") and not message and previous and previous.key.startswith("cms-") and (
                previous.tag == tag and not previous.extra):
            names = previous.detail if previous.key == "cms-*" else previous.value
            entries[-1] = previous._replace(key="cms-*", value="Azure-managed", detail=f"{names} · {name}")
            continue
        extra: List[Any] = [Text(message)] if message else []
        roles = role_lines(item, namespace, inbound.get(key[len("roles-"):], "")) if key.startswith("roles-") else []
        target = str(item.get("target") or "")
        scope = where(target if target.startswith("/") else (item.get("details") or {}).get("resourceId") or "")
        detail = " · ".join(part for part in (scope, item_detail(item, namespace)) if part)
        entries.append(Entry(key, item_label(item), str(name or ""), detail, tag, extra, roles))
    return entries


class GuidedSetup:
    """Progressive questions → strict config → plan → typed approval → apply, on the shared engine.

    Everything up to approval lives in one *workspace* repainted in place (``Screen.show``): the resolved scope,
    then either the answers (while asking or changing them) or the plan (while reviewing it), then short notes.
    Going back, changing an answer, a blocked plan or a re-read update that block; they never append copies."""

    def __init__(self, services, subscription_id, *, screen, prompter, arguments=None, config=None,
                 plan_only=False, output_script=None, persist=None, write_script=None, check_script=None):
        arguments = arguments or {}
        self.services = services
        self.subscription = subscription_id
        self.subscription_name = subscription_id
        self.screen = screen
        self.prompter = prompter
        self.arguments = arguments
        self.config = config
        self.plan_only = plan_only
        self.output_script = output_script
        self.persist = persist or (lambda result: result)
        self.write_script = write_script or (lambda path, items: None)
        self.check_script = check_script or (lambda path, items: None)
        given = (config or {}).get("namespace", {})
        self.rg = arguments.get("resource_group_name") or given.get("resourceGroup")
        self.namespace = arguments.get("namespace_name") or given.get("name")
        self.fixed = {"resource_group": bool(self.rg), "namespace": bool(self.namespace)}
        self.location = arguments.get("location")
        self.tags = arguments.get("tags")
        self.fixed_location = bool(self.location or given.get("location"))
        self.fixed_tags = self.tags is not None or "tags" in given
        self.outbound = arguments.get("namespace_outbound_identity")
        self.fixed_outbound = bool(self.outbound)
        self.explicit = config is not None or any(
            arguments.get(key) for key in ("dps", "hubs", "software_updates", "complete_connectivity")
        )
        self.rg_info: Optional[Dict[str, Any]] = None
        self.ns_info: Optional[Dict[str, Any]] = None
        self.ns_read = False
        self.choices: Dict[str, Any] = {}  # "dps": one choice; "hub": the chosen IoT Hubs, a list
        self.pending: Optional[Dict[str, Any]] = None  # targets checked while Connectivity is asked
        self.managing = False  # the IoT Hubs manager is open: it shows the chosen Hubs, the workspace doesn't
        self.hub_slots: Dict[int, int] = {}  # links.hubs index → chosen IoT Hub, for routing plan problems
        self.plan_target: Optional[tuple] = None  # (kind, endpoint name) the failed plan read was checking
        self.names: Dict[str, str] = {}
        self.software_updates = False
        self.cms = False
        self.shown: set = set()  # answers given in this run (shown in the workspace)
        # Listings, by key: target and namespace lists hold [(Row, location)] or [Row]; subscriptions (rows, excluded).
        self.cache: Dict[tuple, Any] = {}
        self.tenant = ""  # the namespace subscription's directory: other subscriptions are offered only within it
        self.subscription_names: Dict[str, str] = {}  # case-folded subscription ID → display name, as listed
        self.plan: Optional[Dict[str, Any]] = None
        self.unassessed: List[tuple] = []
        self.mode = "answers"
        self.notes: List[tuple] = []

    # ---- small helpers -------------------------------------------------------------------

    def _read(self, message, operation, *args):
        with self.screen.activity(message):
            return operation(*args)

    def _rows(self, key, message, loader, to_row, instead="an exact name"):
        if key not in self.cache:
            try:
                with self.screen.activity(message):
                    rows = [to_row(item) for item in loader() if item.get("name")]
            except Exception as error:  # noqa: BLE001 - listing is optional; the reason is shown, exact input still works
                self.say(f"Couldn't list {key[0]}: {error}. Type {instead} instead.")
                return []
            self.cache[key] = rows
        return self.cache[key]

    def _new_location(self):
        return self.location or (self.config or {}).get("namespace", {}).get("location") or (
            self.rg_info or {}).get("location")

    def _tags(self):
        return self.tags if self.tags is not None else (self.config or {}).get("namespace", {}).get("tags")

    def _linked(self, kind):
        return linked_endpoints(self.ns_info, kind)

    def _name(self, kind):
        return self.names.get(kind) or derive_name(self.namespace, kind)

    def _invalidate(self, reason):
        """A new scope drops every answer that depended on the old one; supplied arguments are kept."""
        supplied = (self.arguments.get("location"), self.arguments.get("tags"))
        reset = " · region and tags reset" if (self.location, self.tags) != supplied else ""
        self.location, self.tags = supplied
        self.choices.clear()
        self.names.clear()
        self.software_updates = self.cms = False
        self.shown -= {"software_updates", "cms"}
        self.plan = None
        self.notes.append((f"{reason} · connectivity and capabilities are asked again{reset}.", "↺", ACCENT))

    # ---- the workspace -------------------------------------------------------------------

    def refresh(self):
        self.screen.show(self.view())

    def say(self, message, *, mark="!", style=WARN_BOLD):
        """A short note under the workspace, kept until the next answer is accepted; never repeated."""
        if (message, mark, style) not in self.notes:
            self.notes.append((message, mark, style))
        self.refresh()

    def _accepted(self):
        """An answer was accepted: notes about the previous state no longer apply."""
        self.notes = []

    def view(self) -> List[Text]:
        if self.mode == "plan" and self.plan is not None:  # the plan and its notes, on the approval surface
            return self._scope_lines() + self._plan_lines()
        lines = self._scope_lines() + self._answer_lines()
        for message, mark, style in self.notes:
            lines += self.screen.note_lines(message, mark=mark, style=style)
        return lines

    def _scope_lines(self) -> List[Text]:
        fact = self.screen.fact_lines
        lines = []
        if self.rg_info is not None:
            lines += fact("Resource group:", self.rg, self.rg_info.get("location") or "")
        if not self.ns_read:
            return lines
        if self.ns_info is None:
            tags = " ".join(f"{key}={value}" for key, value in sorted((self._tags() or {}).items()))
            detail = " · ".join(part for part in (self._new_location() or "resource group region", tags) if part)
            return lines + fact("Namespace:", self.namespace, detail, tag="NEW", tag_style=GOOD_BOLD)
        state = ((self.ns_info.get("properties") or {}).get("provisioningState")) or ""
        detail = " · ".join(part for part in (self.ns_info.get("location"), state if state != "Succeeded" else "")
                            if part)
        return lines + fact("Namespace:", self.namespace, detail, tag="REUSE", tag_style=REUSE_BOLD)

    def _answer_lines(self) -> List[Text]:
        fact = self.screen.fact_lines
        lines = []
        for kind in KIND_LABELS:
            for link in self._linked(kind):
                lines += fact(KIND_LABELS[kind] + ":", link["resource"], " · ".join(
                    part for part in (f"endpoint {link['endpoint']}", link["state"]) if part),
                    tag="LINKED", tag_style=LINK_BOLD)
        if self.explicit:
            if self.ns_read:
                lines += fact("Settings:", "as supplied", "from --config" if self.config is not None else
                              "from arguments")
        else:
            chosen = self.choices if self.pending is None else self.pending
            dps = None if self._linked("dps") else chosen.get("dps")
            hubs = chosen.get("hub")  # None until asked; IoT Hubs added in Change can sit beside linked ones
            hub_asked = hubs is not None and not self._linked("hub") and not self.managing
            nothing = [kind for kind, asked, none in (
                ("dps", dps is not None, dps is not None and dps["mode"] == "none"),
                ("hub", hub_asked, not hubs)) if asked and none]
            asked = (dps is not None) + hub_asked
            if nothing and len(nothing) == asked:
                lines += fact("Connectivity:", "Namespace only" if asked == 2 else f"No {KIND_LABELS[nothing[0]]}",
                              "link later")
            else:
                if dps is not None:
                    no_dps = fact("DPS:", "No", "link later")
                    lines += self._target_fact("dps", dps) if dps["mode"] != "none" else no_dps
                for hub in [] if self.managing else hubs or []:  # the open manager lists them itself
                    lines += self._target_fact("hub", hub)
                if hub_asked and not hubs:
                    lines += fact("IoT Hub:", "No", "link later")
            if "software_updates" in self.shown and not self._linked("software-updates"):
                lines += fact("Software updates:", self._name("software-updates"), "Device Update instance",
                              tag="NEW", tag_style=GOOD_BOLD) if self.software_updates else fact(
                    "Software updates:", "No", "add later with --su")
            if "cms" in self.shown:
                lines += fact("CMS:", "Azure-managed", "root · intermediate · policy · 30 days", tag="NEW",
                              tag_style=GOOD_BOLD) if self.cms else fact("CMS:", "No", "certificate management off")
        if self.outbound and "identity" in self.shown:
            lines += fact("Outbound identity:", *identity_value(self.outbound))
        return lines

    def _target_fact(self, kind, choice) -> List[Text]:
        if choice["mode"] == "new":
            return self.screen.fact_lines(KIND_LABELS[kind] + ":", choice["name"], tier_detail(kind, choice),
                                          tag="NEW", tag_style=GOOD_BOLD)
        return self.screen.fact_lines(KIND_LABELS[kind] + ":", choice["name"], choice.get("detail", ""), tag="REUSE",
                                      tag_style=REUSE_BOLD)

    def _plan_lines(self) -> List[Text]:
        with self.screen.inset():  # washed rows wrap a cell short of the width
            return self._washed_plan()

    def _washed_plan(self) -> List[Text]:
        items = [item for item in ordered_items(self.plan) if item.get("action") != "skip"]
        new_namespace = any(item.get("id") == "namespace" and item.get("action") == "create" for item in items)
        counts = plan_counts(items, new_namespace) + (
            [("warning", len(self.unassessed), "unchecked")] if self.unassessed else [])
        # The heading counts each kind of change behind its glyph, so it is also the plan's legend.
        summary = Text()
        for index, (tag, count, label) in enumerate(counts):
            mark, _, style = TAGS[tag]
            summary.append(" · " if index else "", DIM)
            summary.append(mark + " ", style)
            summary.append(str(count), BOLD)
            summary.append(" " + label)
        lines: List[Text] = []
        role_mark, _, role_style = TAGS["role"]
        for entry in plan_entries(items, self.namespace, new_namespace, self._elsewhere):
            mark, tag, style = TAGS[entry.tag]
            lines += self.screen.fact_lines(entry.label, entry.value, entry.detail, tag=tag, tag_style=style,
                                            mark=mark, mark_style=style, extra=entry.extra)
            # Role rows sit under the link, indented from the label column so an identity and its roles fit a row.
            for role in entry.roles:
                prefix = Text(" " * (INDENT + MARK + 2))
                prefix.append(role_mark + " ", role_style)
                lines += self.screen.hanging_lines(prefix, role, INDENT + MARK + 4)
        mark, tag, style = TAGS["warning"]
        for kind, endpoint, reason in self.unassessed:
            lines += self.screen.fact_lines(KIND_LABELS[kind] + ":", endpoint, "existing link", tag=tag,
                                            tag_style=style, mark=mark, mark_style=style, extra=[Text(reason)])
        if self.notes:
            lines.append(Text())
        for message, mark, style in self.notes:
            lines += self.screen.note_lines(message, mark=mark, style=style)
        return self.screen.surface("Plan", summary, lines)

    # ---- questions -----------------------------------------------------------------------

    def ask(self, names=QUESTIONS, *, allow_back=False):
        """Ask unresolved questions in order. Esc returns to the previously asked question."""
        names = [name for name in names if not (self.explicit and name not in ("resource_group", "namespace"))]
        index, asked = 0, []
        while index < len(names):
            try:
                prompted = getattr(self, "_q_" + names[index])()
            except BackRequested:
                if asked:
                    index = asked.pop()
                    continue
                if allow_back:
                    raise
                self.say("This is the first question · Ctrl+C cancels.", mark="·", style=DIM)
                continue
            if prompted:
                asked.append(index)
            index += 1

    def _q_resource_group(self):
        prompted = False
        error = value = ""
        self.refresh()
        rows = [] if self.fixed["resource_group"] else self._rows(
            ("resource groups",), "Loading resource groups",
            self.services.list_resource_groups, lambda item: Row(item["name"], item["name"], item.get("location") or ""),
        )
        while True:
            if self.fixed["resource_group"]:
                value = self.rg
            else:
                prompted = True
                value = self.prompter.ask("Resource group:", rows, default=self.rg or "", error=error,
                                          initial=value if error else "")
            info = self._read(f"Reading resource group {value}", self.services.show_resource_group, value)
            if info is not None:
                break
            error = f"Resource group '{value}' was not found in {self.subscription_name}. Create it first, or choose another."
            if self.fixed["resource_group"]:
                raise InvalidArgumentValueError(error)
        changed = bool(self.rg_info) and value.casefold() != str(self.rg).casefold()
        self.rg, self.rg_info = value, info
        self._accepted()
        if changed:
            self.ns_read = False
            self.ns_info = None
            self._invalidate("Resource group changed")
        self.refresh()
        return prompted

    def _q_namespace(self):
        prompted = False
        error = value = ""
        rows = [] if self.fixed["namespace"] else self._rows(
            ("namespaces", self.rg.casefold()), f"Loading namespaces in {self.rg}",
            lambda: self.services.list_namespaces(self.rg),
            lambda item: Row(item["name"], item["name"], " · ".join(
                part for part in (item.get("location"), item.get("provisioningState")) if part)),
        )
        previous = self.namespace if self.ns_read else None
        while True:
            if self.fixed["namespace"]:
                value = self.namespace
            else:
                prompted = True
                value = self.prompter.ask("Namespace:", rows, default=self.namespace or "", error=error,
                                          create=f"created in {self.rg}", initial=value if error else "")
            if not NAMESPACE_NAME.fullmatch(value):
                error = "Namespace names start with a letter or digit and use letters, digits, '.', '_' or '-'."
                if self.fixed["namespace"]:
                    raise InvalidArgumentValueError(error)
                continue
            break
        self.ns_info = self._read(f"Reading namespace {value}", self.services.show_namespace, value, self.rg)
        self.namespace, self.ns_read = value, True
        self._accepted()
        if previous and previous.casefold() != value.casefold():
            self._invalidate("Namespace changed")
        self.refresh()
        return prompted

    def _mode_rows(self, missing):
        """New / Existing / None for the missing DPS and/or IoT Hub; New shows the names it would create."""
        both = len(missing) == 2
        what = "DPS and IoT Hub" if both else KIND_LABELS[missing[0]]
        hubs = self.choices.get("hub") or []

        def planned(kind):
            if kind == "dps":
                return self._name("dps")
            if len(hubs) > 1:
                return f"{len(hubs)} IoT Hubs chosen"
            return hubs[0]["name"] if hubs else self._next_hub_name([])

        names = " · ".join(planned(kind) for kind in missing)
        if "hub" not in missing:
            tier = tier_detail("dps", {})
        elif hubs:
            tier = "review IoT Hubs next"
        else:
            tier = "Standard tier next"
        return [
            Row("new", f"New {what}", f"{names} · {tier}"),
            Row("existing", f"Existing {what if 'hub' not in missing else what + 's'}",
                f"choose in {self.rg} · checked when you enter it"),
            Row("none", "Namespace only" if both else f"Skip {what}", "link later"),
        ]

    def _mode(self, kind):
        """The Connectivity answer a current choice corresponds to; a mixed IoT Hub collection reads as New."""
        if kind == "dps":
            return self.choices["dps"]["mode"]
        hubs = self.choices["hub"]
        if not hubs:
            return "none"
        return "existing" if all(hub["mode"] == "existing" for hub in hubs) else "new"

    def _q_connectivity(self):
        missing = [kind for kind in ("dps", "hub") if not self._linked(kind)]
        if not missing:
            return False
        rows = self._mode_rows(missing)
        current = {self._mode(kind) for kind in missing if kind in self.choices}
        default = current.pop() if len(current) == 1 else "new"
        while True:
            mode = self.prompter.select("Connectivity:", rows, default=default)
            # A checked DPS shows in the workspace while the IoT Hubs are chosen; Back drops it again.
            self.pending = {}
            try:
                for kind in missing:
                    self.pending[kind] = self._connect_hubs(mode) if kind == "hub" else self._target_choice(
                        kind, mode, ask_name=False)
                    self.refresh()
            except BackRequested:
                default = mode
                continue
            finally:
                choices, self.pending = self.pending, None
                self.refresh()
            break
        self._accepted()
        self._commit_targets(choices)
        return True

    def _commit_targets(self, choices):
        self.choices.update(choices)
        for kind, choice in choices.items():
            if kind != "hub" and choice["mode"] == "new":
                self.names[kind] = choice["name"]
        self.refresh()

    def _edit_target(self, kind, error=""):
        """The DPS editor: New (name) / Existing (searchable, checked on entry) / None.

        It starts from the current answer and changes nothing until it completes; Esc steps back inside it, and
        out of it from its first step. A plan problem opens the step that can fix it, with the problem shown."""
        label = KIND_LABELS[kind]
        current = self.choices.get(kind) or {"mode": "none"}
        mode = current["mode"] if error and current["mode"] != "none" else None
        while True:
            if mode is None:
                mode = self.prompter.select(label + ":", self._mode_rows([kind]), default=current["mode"])
            try:
                choice = self._target_choice(kind, mode, ask_name=True, error=error)
            except BackRequested:
                mode, error = None, ""
                continue
            break
        self._commit_targets({kind: choice})

    def _target_choice(self, kind, mode, *, ask_name, error=""):
        if mode == "new":
            return self._new_target(kind, ask_name=ask_name, error=error)
        if mode == "existing":
            return self._choose_existing(kind, error=error)
        return {"mode": "none"}

    def _new_target(self, kind, *, ask_name, error=""):
        """A new DPS: S1, its only tier, so only its name is asked (in its editor)."""
        previous = self.choices.get(kind) or {}
        name = previous.get("name") if previous.get("mode") == "new" else self._name(kind)
        if ask_name:
            name = self._ask_name(kind, name, error)
        return {"mode": "new", "name": name}

    def _ask_name(self, kind, name, error="", check=None):
        """A new resource's name; ``check`` adds the setup's own rules (an IoT Hub name already in it)."""
        what = "Device Update instance" if kind == "software-updates" else KIND_LABELS[kind]
        while True:
            value = self.prompter.ask(NAME_PROMPTS[kind], default=name, error=error,
                                      hint=[("", f"new {what} name"), ("esc", "back")])
            error = target_name_error(value, kind) or (check(value) if check else "")
            if not error:
                return value

    def _ask_tier(self, tier):
        rows = [Row(name, f"{name} Standard", detail) for name, detail in HUB_TIERS]
        return self.prompter.select(
            "IoT Hub tier:", rows, default=tier,
            help="1 unit · Free and Basic tiers can't link to ADR",
        )

    # ---- the IoT Hubs collection -------------------------------------------------------
    #
    # Guided setup keeps the chosen IoT Hubs as a list of drafts ({"mode": "new", "name", "sku", "unit"} or
    # {"mode": "existing", "value", "name", "detail"}). One manager adds, changes and removes them: Connectivity
    # opens it after the first IoT Hub, and Change opens the same one. It edits a copy: Continue keeps the result,
    # Esc keeps what was there before. Removing a draft only takes it out of this setup; linked IoT Hubs are never
    # offered for removal, and nothing in Azure is deleted or unlinked.

    def _connect_hubs(self, mode):
        """The IoT Hubs for a Connectivity answer: none, or the first one (New: the derived name and a tier;
        Existing: one or several picked) and then the manager. Hubs already chosen are kept, not re-asked."""
        if mode == "none":
            return []
        drafts = list(self.choices.get("hub") or [])
        focus = "done"
        if not drafts:
            drafts = [self._new_hub([], ask_name=False)] if mode == "new" else self._choose_existing_hubs([])
        elif all(draft["mode"] != mode for draft in drafts):
            focus = "add-" + mode  # the answer's way to add, focused; nothing is added or dropped unasked
        return self._manage_hubs(drafts, focus=focus)

    def _manage_hubs(self, drafts, *, focus="done", open_index=None, error=""):
        """The IoT Hubs manager: one row per chosen IoT Hub, then Add new, Add existing and Continue."""
        drafts = [dict(draft) for draft in drafts]
        field_error, error = (error, "") if open_index is not None else ("", error)
        linked = len(self._linked("hub"))
        note = ""
        managing, self.managing = self.managing, True  # the list is the manager's; the workspace doesn't repeat it
        self.refresh()
        try:
            while True:
                if open_index is not None:
                    choice, open_index = f"hub:{open_index}", None
                else:
                    help_text = note or (f"{linked} linked IoT Hub{'s' if linked > 1 else ''} stay linked and "
                                         f"count toward {MAX_HUBS}." if linked else "")
                    choice = self.prompter.select("IoT Hubs:", self._hub_rows(drafts), default=focus, error=error,
                                                  help=help_text, summary=self._hub_count(drafts))
                    error = note = ""
                focus = choice
                if choice == "done":
                    return drafts
                if choice in ("add-new", "add-existing"):
                    if self._hub_room(drafts) <= 0:
                        error = self._hub_limit(drafts)
                        continue
                    try:
                        if choice == "add-new":
                            drafts.append(self._new_hub(drafts))
                        else:
                            drafts.extend(self._choose_existing_hubs(drafts))
                    except BackRequested:
                        pass
                    continue
                index = int(choice.split(":")[1])
                try:
                    changed = self._edit_hub(drafts, index, error=field_error)
                except BackRequested:
                    continue
                finally:
                    field_error = ""
                if changed is None:
                    removed = drafts.pop(index)
                    note = f"Removed {removed['name']} from this setup · nothing in Azure is deleted."
                    focus = f"hub:{index}" if index < len(drafts) else "add-new"
                else:
                    drafts[index] = changed
        finally:
            self.managing = managing
            self.refresh()

    def _hub_rows(self, drafts):
        rows = [Row(f"hub:{index}", draft["name"], tier_detail("hub", draft) if draft["mode"] == "new" else (
            draft.get("detail") or "existing"), "NEW" if draft["mode"] == "new" else "REUSE")
            for index, draft in enumerate(drafts)]
        room = self._hub_room(drafts) > 0
        full = f"none left of {MAX_HUBS}"
        return rows + [
            Row("add-new", "Add new IoT Hub", f"{self._next_hub_name(drafts)} · tier next" if room else full),
            Row("add-existing", "Add existing IoT Hubs", f"in {self.rg} or by ID · space selects several" if room
                else full),
            Row("done", "Continue", self._hub_summary(drafts)),
        ]

    def _hub_room(self, drafts):
        return MAX_HUBS - len(self._linked("hub")) - len(drafts)

    def _hub_count(self, drafts):
        total = len(self._linked("hub")) + len(drafts)
        return f"{total} of {MAX_HUBS}" if total <= MAX_HUBS else f"{total} · all linked ones are kept"

    def _hub_limit(self, drafts):
        if drafts:
            return f"Guided setup links {MAX_HUBS} IoT Hubs at most. Remove one from this setup to add another."
        return (f"{len(self._linked('hub'))} IoT Hubs are already linked; guided setup links {MAX_HUBS} at most. "
                "They all stay linked.")

    def _hub_summary(self, drafts):
        new = sum(draft["mode"] == "new" for draft in drafts)
        linked = len(self._linked("hub"))
        parts = [f"{new} new" if new else "", f"{len(drafts) - new} existing" if len(drafts) > new else "",
                 f"{linked} linked" if linked else ""]
        return " · ".join(part for part in parts if part) or "no IoT Hub · link later"

    def _edit_hub(self, drafts, index, error=""):
        """One chosen IoT Hub: change it (a new one's name and tier, or another existing one) or remove it from
        this setup. Returns the changed draft, or None to remove it; Esc leaves it as it was."""
        draft, others = drafts[index], drafts[:index] + drafts[index + 1:]
        action = "change" if error else None  # a plan problem opens the field that can fix it
        while True:
            if action is None:
                action = self.prompter.select("IoT Hub:", [
                    Row("change", "Change name and tier", tier_detail("hub", draft)) if draft["mode"] == "new" else
                    Row("change", "Choose another", f"instead of {draft['name']}"),
                    Row("remove", "Remove from setup", "nothing in Azure is deleted"),
                ], summary=draft["name"])
            if action == "remove":
                return None
            try:
                if draft["mode"] == "new":
                    return self._new_hub(others, previous=draft, error=error)
                return self._choose_existing("hub", error=error, previous=draft, others=others)
            except BackRequested:
                action, error = None, ""

    def _new_hub(self, others, *, previous=None, ask_name=True, error=""):
        """A new IoT Hub: its name (unique in this setup), then its tier. Back from the tier returns to the name
        when it was asked here, else to the step before."""
        previous = previous or {}
        name, tier = previous.get("name") or self._next_hub_name(others), previous.get("sku") or DEFAULT_TIER
        while True:
            if ask_name:
                name = self._ask_name("hub", name, error, check=lambda value: self._hub_conflict(value, others))
                error = ""
            try:
                tier = self._ask_tier(tier)
            except BackRequested:
                if ask_name:
                    continue
                raise
            return {"mode": "new", "name": name, "sku": tier, "unit": 1}

    def _next_hub_name(self, others):
        """The derived IoT Hub name, numbered past the names this setup and the namespace's links already use."""
        number = 1
        while self._hub_conflict(derive_name(self.namespace, "hub", number), others):
            number += 1
        return derive_name(self.namespace, "hub", number)

    def _target_key(self, kind, value):
        """(resource ID, endpoint name), both case-folded, as the engine compares them; None for malformed input
        (its own check explains that). A name is a resource in this resource group, so a name and its ID match."""
        try:
            endpoint = parse_endpoint([("resource-id=" if value.startswith("/") else "resource-name=") + value,
                                       "identity=system-assigned"], kind, self.rg, self.subscription)
        except InvalidArgumentValueError:
            return None
        return endpoint.resource_id.rstrip("/").casefold(), endpoint.endpoint_name.casefold()

    def _taken(self, others):
        """Every (resource ID, endpoint name, where) this setup already requests besides the IoT Hub being chosen:
        the namespace's links (they are kept), the DPS and Software updates answers and the other chosen Hubs."""
        taken = []
        for kind in KIND_LABELS:
            for name, link in endpoint_map(self.ns_info, kind).items():
                link = link if isinstance(link, dict) else {}
                target = str(link.get("resourceId") or link.get("resource_id") or "")
                taken.append((target.rstrip("/").casefold(), name.casefold(), "linked"))
        chosen = dict(self.choices, **(self.pending or {}))
        dps = chosen.get("dps") or {"mode": "none"}
        requested = [("hub", draft) for draft in others]
        if dps["mode"] != "none" and not self._linked("dps"):
            requested.append(("dps", dps))
        for kind, choice in requested:
            key = self._target_key(kind, choice["name"] if choice["mode"] == "new" else choice["value"])
            if key:
                taken.append(key + ("setup",))
        if self.software_updates and not self._linked("software-updates"):
            taken.append(("", self._name("software-updates").casefold(), "setup"))
        return taken

    def _hub_conflict(self, value, others):
        """Why this IoT Hub can't join the setup (already linked or chosen, by name or ID in any letter case, or
        its endpoint name is taken), else "". The engine's own uniqueness rules, applied as soon as it's entered."""
        key = self._target_key("hub", value)
        if key is None:
            return ""
        target, endpoint = key
        for other_target, other_endpoint, where in self._taken(others):
            if target == other_target:
                return (f"IoT Hub '{_short(value)}' is already linked to {self.namespace}; it stays linked."
                        if where == "linked" else f"IoT Hub '{_short(value)}' is already in this setup.")
            if endpoint == other_endpoint:
                place = f"by a link on {self.namespace}" if where == "linked" else "in this setup"
                return (f"Endpoint name '{_short(value)}' is already used {place}; endpoint names are unique across "
                        "DPS, IoT Hub and Software updates links.")
        return ""

    # ---- existing targets: any resource group of the namespace's subscription, or another one in its directory ----

    def _region(self):
        return (self.ns_info or {}).get("location") or self._new_location()

    def _subscription_name(self, subscription):
        if subscription.casefold() == self.subscription.casefold():
            return self.subscription_name
        return self.subscription_names.get(subscription.casefold(), subscription)

    def _elsewhere(self, resource_id):
        """Where a target lives when it isn't the namespace's resource group: "in rg" or "in rg, subscription".
        Names are globally unique, so this is all a reader needs to tell scopes apart; "" for the namespace's."""
        found = re.match(r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/", str(resource_id or ""), re.IGNORECASE)
        if not found:
            return ""
        subscription, group = found.groups()
        if subscription.casefold() != self.subscription.casefold():
            return f"in {group}, {self._subscription_name(subscription)}"
        return f"in {group}" if group.casefold() != (self.rg or "").casefold() else ""

    def _target_rows(self, kind, subscription):
        """(rows, hidden): the subscription's targets in the namespace's region, from every resource group, and how
        many are elsewhere. A target must be in the namespace's region, so others are never offered as choices
        (a typed ID of one still gets the real check and its reason)."""
        label = KIND_LABELS[kind]
        plural = label if label == "DPS" else label + "s"
        name = self._subscription_name(subscription)

        def describe(item):
            sku = item.get("sku")
            standard = kind != "hub" or not sku or str(sku).upper().startswith("S")
            group = item.get("resourceGroup") or next(iter(re.findall(
                r"/resourceGroups/([^/]+)", str(item.get("id") or ""), re.IGNORECASE)), "")
            return " · ".join(str(part) for part in (
                group, sku if standard else f"{sku}: not a Standard tier",
                item.get("provisioningState") if item.get("provisioningState") != "Succeeded" else "") if part)

        listed = self._rows(
            (f"{plural} in {name}", kind, subscription.casefold()), f"Loading {plural} in {name}",
            lambda: self.services.list_link_targets(
                kind, None, None if subscription.casefold() == self.subscription.casefold() else subscription),
            lambda item: (Row(item.get("id") or item["name"], item["name"], describe(item)), item.get("location")),
            instead="an exact name or resource ID",
        )
        region = _region_key(self._region())
        rows = [row for row, location in listed if not region or _region_key(location) == region]
        return rows, len(listed) - len(rows)

    def _target_caption(self, kind, subscription, count, hidden=0, elsewhere=0):
        """``count`` rows offered; ``hidden`` already in this setup; ``elsewhere`` in other regions."""
        label = KIND_LABELS[kind]
        plural = label if label == "DPS" else label + "s"
        region = self._region()
        scope = " · ".join(part for part in (f"in {region}" if region else "", self._subscription_name(subscription),
                                             "all resource groups") if part)
        notes = "".join(part for part in (
            f" · {hidden} already in this setup" if hidden else "",
            f" · {elsewhere} in other regions not shown" if elsewhere else "") if part)

        def caption(shown, total, query):
            if not count:
                return f"No {label} to choose {scope}{notes} · type a name, or any resource ID"
            if query and not shown:
                return f"No {label} {scope.split(' · ')[0]} matches · enter checks what you typed"
            if query:  # ``total``: every row searched, with marks carried from another subscription or typed
                return f"{shown} of {total} match"
            return f"{count} {label if count == 1 else plural} {scope}{notes} · type to filter, or a resource ID"
        return caption

    def _scope_action(self, subscription):
        return Row(SCOPE, "Another subscription…", f"now: {self._subscription_name(subscription)}")

    def _subscriptions(self):
        """(rows, excluded): enabled subscriptions in the namespace subscription's directory, the namespace's first.
        Managed identities don't reach across directories, so other directories (and disabled subscriptions) are
        counted, never offered. Listing problems are shown; the namespace's subscription is always there."""
        key = ("subscriptions",)
        if key not in self.cache:
            try:
                with self.screen.activity("Loading subscriptions"):
                    listed = list(self.services.list_subscriptions())
            except Exception as error:  # noqa: BLE001 - optional; the namespace's subscription still works
                self.say(f"Couldn't list subscriptions: {error}. Type a full resource ID instead.")
                listed = []
            tenant = self.tenant or next((str(item.get("tenantId") or "") for item in listed
                                          if str(item.get("id") or "").casefold() == self.subscription.casefold()), "")
            rows = [Row(self.subscription, self.subscription_name, "namespace subscription")]
            for item in listed:
                ident = str(item.get("id") or "")
                if ident.casefold() == self.subscription.casefold():
                    continue
                if not tenant or str(item.get("tenantId") or "").casefold() != tenant.casefold() or str(
                        item.get("state") or "").casefold() != "enabled":
                    continue
                self.subscription_names[ident.casefold()] = str(item.get("name") or ident)
                rows.append(Row(ident, str(item.get("name") or ident), ident))
            if not listed:
                return rows, 0  # not cached: a later visit retries the listing
            others = [item for item in listed if str(item.get("id") or "").casefold() != self.subscription.casefold()]
            self.cache[key] = (rows, len(others) - (len(rows) - 1))
        return self.cache[key]

    def _choose_subscription(self, current):
        """Where the target list looks next; Esc keeps ``current``. Never changes the namespace or the CLI profile."""
        rows, excluded = self._subscriptions()
        count = len(rows)

        def caption(shown, total, query):
            del total
            if query and not shown:
                return "No subscription in this directory matches"
            if query:
                return f"{shown} of {count} match"
            noun = "subscription" if count == 1 else "subscriptions"
            return (f"{count} {noun} in this directory" + (
                f" · {excluded} not shown: other directory or disabled" if excluded else "") + " · type to filter")

        error = ""
        while True:
            try:
                value = self.prompter.ask("Subscription:", rows, default=current, error=error, caption=caption,
                                          focus_first=True, hint=[("↑↓", "choose"), ("enter", "list its resources"),
                                                                  ("esc", "back")])
            except BackRequested:
                return current
            row = next((row for row in rows if value.casefold() in (row.value.casefold(), row.title.casefold())), None)
            if row:
                return row.value
            error = ("Choose a listed subscription: linked resources must be in an enabled subscription of this "
                     "directory.")

    def _choose_existing(self, kind, error="", *, previous=None, others=None):
        """An existing target is resolved and checked as soon as it is entered; problems stay on this field.
        For an IoT Hub (``others``: the rest of the collection), Hubs already in the setup aren't listed.
        "Another subscription…" lists another subscription's targets in place; what was typed stays in the field
        (and a cancelled choice of subscription changes nothing at all)."""
        label = KIND_LABELS[kind]
        previous = self.choices.get(kind, {}) if previous is None else previous
        default = previous.get("value", "") if previous.get("mode") == "existing" else ""
        typed, subscription = "", self.subscription
        while True:
            listed, elsewhere = self._target_rows(kind, subscription)
            rows = [row for row in listed if others is None or not self._hub_conflict(row.value, others)]
            caption = self._target_caption(kind, subscription, len(rows), len(listed) - len(rows), elsewhere)
            value = self.prompter.ask(
                label + ":", rows, default=default, error=error, initial=typed, caption=caption, focus_first=True,
                action=self._scope_action(subscription),
                hint=[("↑↓", "choose"), ("enter", "check"), ("tab", "complete"), ("esc", "back")])
            if value.startswith(SCOPE):
                typed, chosen = value[len(SCOPE):], self._choose_subscription(subscription)
                error = error if chosen == subscription else ""
                subscription = chosen
                continue
            row = next((row for row in rows if value.casefold() in (row.value.casefold(), row.title.casefold())),
                       None)
            value = row.value if row else value
            error = self._hub_conflict(value, others) if others is not None else ""
            if not error:
                detail, error = self._check_existing(kind, value)
            if not error:
                break
            typed = row.title if row else value  # the field keeps what was entered, ready to correct
        return {"mode": "existing", "value": value, "name": row.title if row else _short(value), "detail": detail}

    def _choose_existing_hubs(self, drafts):
        """Existing IoT Hubs, several at once: Space marks rows (or a typed name or ID), Enter checks each one in
        turn. The first that can't join stays in the field with its reason; the others stay marked. Marks are
        resource IDs, so they (and the count) stay while "Another subscription…" lists another subscription."""
        marked, typed, error, checked = [], "", "", {}
        subscription = self.subscription
        known: Dict[str, Row] = {}  # every row listed so far, by ID: marks from another scope keep their names
        while True:
            listed, elsewhere = self._target_rows("hub", subscription)
            available = [row for row in listed if not self._hub_conflict(row.value, drafts)]
            here = self._subscription_name(subscription)
            for row in available:  # a carried mark always names its subscription; the listed rows stay compact
                known[row.value.casefold()] = row._replace(detail=" · ".join(part for part in (row.detail, here) if part))
            caption = self._target_caption("hub", subscription, len(available), len(listed) - len(available),
                                           elsewhere)
            # Resource IDs compare case-insensitively: a mark typed in another case is the listed row it names,
            # so it shows as that row's ✓, never as a second, unmarked-looking copy.
            canonical, seen = [], set()
            for value in marked:
                value = known[value.casefold()].value if value.casefold() in known else value
                if value.casefold() not in seen:
                    seen.add(value.casefold())
                    canonical.append(value)
            marked = canonical
            shown = {row.value for row in available}
            carried = [known.get(value.casefold(), Row(value, value, "typed · checked on enter")) for value in marked
                       if value not in shown]
            values = self.prompter.ask_many("IoT Hubs:", carried + available, limit=self._hub_room(drafts),
                                            marked=marked, initial=typed, error=error, caption=caption,
                                            action=self._scope_action(subscription))
            if values and values[0].startswith(SCOPE):
                marked, typed, chosen = values[1:], values[0][len(SCOPE):], self._choose_subscription(subscription)
                error = error if chosen == subscription else ""
                subscription = chosen
                continue
            picked = []
            for entered in values:
                row = next((row for row in carried + available if entered.casefold() in (
                    row.value.casefold(), row.title.casefold())), None)
                value = row.value if row else entered
                error = self._hub_conflict(value, drafts + picked)
                if not error and value not in checked:
                    checked[value], error = self._check_existing("hub", value)
                if error:
                    checked.pop(value, None)  # only successful checks are remembered
                    marked = [other for other in values if other != entered]
                    typed = row.title if row else value
                    break
                picked.append({"mode": "existing", "value": value, "name": row.title if row else _short(value),
                               "detail": checked[value]})
            else:
                return picked

    def _check_existing(self, kind, value):
        """(detail, "") for a target that exists and can be linked, else ("", the reason). Uses the same lookup and
        checks as the plan; expected lookup failures are explained, anything unexpected propagates."""
        label = KIND_LABELS[kind]
        article = "an" if label[0] in "AEIOU" else "a"
        by_id = value.startswith("/")
        try:
            endpoint = parse_endpoint([("resource-id=" if by_id else "resource-name=") + value,
                                       "identity=system-assigned"], kind, self.rg, self.subscription)
        except InvalidArgumentValueError:
            if by_id:
                return "", f"That isn't {article} {label} resource ID. Type a name in {self.rg}, or its full resource ID."
            return "", f"'{value}' isn't {article} {label} name: names have no spaces or slashes."
        name = endpoint.endpoint_name
        location = (self.ns_info or {}).get("location") or self._new_location()
        try:
            with self.screen.activity(f"Checking {label} {name}"):
                resource = self.services.resolve_resource(endpoint)
                if location:
                    self.services.validate_setup_target(endpoint, resource, location)
        except (CLIError, AzureError) as error:  # CLIError: also knack's, e.g. a subscription not in the profile
            where = "at that resource ID" if by_id else f"in {self.rg}"
            if is_not_found(error) or isinstance(error, ResourceNotFoundError):
                return "", f"{label} '{name}' was not found {where}. Check the name, or go back and choose New."
            status = getattr(error, "status_code", None)
            if status in (401, 403) or isinstance(error, ClientAuthenticationError):
                return "", (f"Access denied reading {label} '{name}' ({status or 'unauthorized'}). "
                            "Choose another, or ask for read access to it.")
            return "", f"{label} '{name}' can't be linked: {identity_words(_first_line(error))}"
        state = (resource.get("properties") or {}).get("provisioningState")
        return " · ".join(str(part) for part in (
            self._elsewhere(endpoint.resource_id), resource.get("location"), (resource.get("sku") or {}).get("name"),
            state if state != "Succeeded" else "") if part), ""

    def _q_software_updates(self):
        if self._linked("software-updates"):
            return False
        name = self._name("software-updates")
        answer = self.prompter.confirm(
            "Software updates:", default=self.software_updates,
            hint=f"y creates Device Update instance {name} and links it · enter keeps the default",
        )
        self._accepted()
        self.software_updates = answer
        self.shown.add("software_updates")
        self.refresh()
        return True

    def _q_cms(self):
        answer = self.prompter.confirm(
            "CMS:", default=self.cms,
            hint="y adds Azure-managed certificates: root CA, intermediate CA, default policy · 30 days",
        )
        self._accepted()
        self.cms = answer
        self.shown.add("cms")
        self.refresh()
        return True

    # ---- configuration -------------------------------------------------------------------

    @staticmethod
    def _endpoint(choice):
        choice = choice or {}
        if choice.get("mode") == "new":
            endpoint = {"resourceName": choice["name"], "identity": dict(SYSTEM), "createIfMissing": True}
            if choice.get("sku"):  # the chosen tier is what gets created (only on a new resource)
                endpoint.update(sku=choice["sku"], unit=choice.get("unit") or 1)
            return endpoint
        if choice.get("mode") == "existing":
            # Reuse never carries a tier: the SKU shown for an existing resource is information, not a resize.
            key = "resourceId" if choice["value"].startswith("/") else "resourceName"
            return {key: choice["value"], "identity": dict(SYSTEM)}
        return None

    def _explicit_config(self):
        arguments = dict(self.arguments)
        arguments.update(namespace_name=self.namespace, resource_group_name=self.rg)
        request = build_setup_request(
            subscription_id=self.subscription, config=self.config, **arguments,
        )
        return request_config(request)

    def _existing_links(self):
        """Existing links, kept exactly so the plan re-checks them; links Azure described incompletely are listed
        separately instead of being guessed. Setup never replaces or re-identifies a link."""
        links: Dict[str, Any] = {}
        self.unassessed = []
        for kind, key in (("dps", "dps"), ("hub", "hubs"), ("software-updates", "softwareUpdates")):
            for name, link in sorted(endpoint_map(self.ns_info, kind).items()):
                endpoint = existing_link_config(kind, name, link)
                if endpoint is None or (kind != "hub" and key in links):
                    self.unassessed.append((kind, name, UNREADABLE_LINK))
                elif kind == "hub":
                    links.setdefault(key, []).append(endpoint)
                else:
                    links[key] = endpoint
        return links

    def compose(self) -> Dict[str, Any]:
        self.hub_slots = {}
        if self.explicit:
            config = self._explicit_config()
        else:
            links = self._existing_links()
            dps = self._endpoint(self.choices.get("dps"))
            hubs = [self._endpoint(choice) for choice in self.choices.get("hub") or []]
            if dps:
                links["dps"] = dps
            if "dps" not in links and not _has_healthy_dps(self.ns_info):
                # The engine re-checks Hub links only alongside a healthy or requested DPS. Without one, existing
                # Hub links are left as they are (not re-checked) so CMS or Software Updates can still be set up.
                # A new Hub chosen here still goes to the engine, which blocks it until a DPS is linked.
                self.unassessed += [("hub", endpoint["endpointName"], NEEDS_DPS_LINK)
                                    for endpoint in links.pop("hubs", [])]
            if hubs:  # after the kept links, in the order chosen; every one is sent
                kept = links.setdefault("hubs", [])
                self.hub_slots = {len(kept) + index: index for index in range(len(hubs))}
                kept.extend(hubs)
            if self.software_updates:
                links["softwareUpdates"] = {
                    "resourceName": self._name("software-updates"), "identity": dict(SYSTEM), "createIfMissing": True,
                }
            namespace = {"name": self.namespace, "resourceGroup": self.rg}
            if links and self.ns_info is None and not self.outbound:
                namespace["outboundIdentity"] = "system-assigned"  # a new namespace needs one before linking
            config = {"schemaVersion": 1, "namespace": namespace, "links": links}
            if self.cms:
                config["cms"] = {"enabled": True}
        namespace = config["namespace"]
        if self.location:
            namespace["location"] = self.location
        if self.tags is not None:
            namespace["tags"] = self.tags
        if self.outbound:  # supplied, or chosen in Change (also in explicit mode)
            namespace["outboundIdentity"] = self.outbound
        if isinstance(namespace.get("outboundIdentity"), str):
            identity = validate_identity(namespace["outboundIdentity"], "namespace.outboundIdentity")
            namespace["outboundIdentity"] = dict(SYSTEM) if identity == "system-assigned" else {
                "type": "UserAssigned", "userAssignedResourceId": identity}
        config["subscriptionId"] = self.subscription
        return load_config(config)

    def _check_outbound(self, config):
        """Links on an existing namespace use its current outbound identity. When Azure can't resolve it, the user
        decides: choose one in Change, or fix it in Azure and re-read. It is never replaced automatically."""
        if self.ns_info is None or not config.get("links") or config["namespace"].get("outboundIdentity"):
            return
        try:
            self._read("Checking the namespace outbound identity", self.services.namespace_outbound_principal,
                       self.ns_info)
        except (InvalidArgumentValueError, AzureResponseError) as error:
            raise OutboundIdentityProblem(
                f"The namespace outbound identity can't be used for links: {error} "
                "Choose an outbound identity, or fix it in Azure and re-read."
            ) from error

    # ---- plan, review and approval -------------------------------------------------------

    def read_plan(self, config, message="Getting your plan ready"):
        request = build_setup_request(None, None, self.subscription, config=config)
        tracker = PlanTarget()
        try:
            with self.screen.activity(message):
                plan, _ = NamespaceWorkflow(self.services, tracker).plan_setup(request)
        finally:
            self.plan_target = tracker.current
        return request, plan

    def approve(self):
        error = ""
        while True:
            try:
                typed = self.prompter.ask(
                    "Approve:", error=error,
                    hint=[("type", f"{self.namespace} to apply"), ("esc", "change"), ("ctrl+c", "cancel")],
                )
            except BackRequested:
                return False
            if typed == self.namespace:
                return True
            error = f"Type {self.namespace} exactly to apply, or press Esc to change the plan."

    def change_menu(self, *, blocked=False):
        """One compact change route over the answers. It stays open: after an edit (or Esc out of one, or Save) it
        comes back with the same row focused, so several answers can change in one visit. Leaving it (Esc, or its
        first row) always returns to a plan read again from Azure, never to the plan shown before the visit."""
        focus = None
        while True:
            self.mode = "answers"
            self.refresh()
            rows = self._change_rows(blocked)
            default = focus if any(row.value == focus for row in rows) else rows[0].value
            try:
                choice = self.prompter.select("Change:", rows, default=default)
            except BackRequested:
                return
            focus = choice
            if choice == "quit":
                raise WorkflowCancelled()
            if choice in ("back", "reread"):
                return
            if choice == "save":
                self.save()
                continue
            try:
                self.edit(choice)
            except BackRequested:  # the editor restored its answer; Change stays open
                continue

    def _change_rows(self, blocked) -> List[Row]:
        guided = not self.explicit
        new_namespace = self.ns_info is None
        rows = [Row("reread", "Re-read plan", "reads Azure again") if blocked else
                Row("back", "Back to approval", "reads Azure again for a fresh plan")]
        options = (
            ("resource_group", "Resource group", self.rg, not self.fixed["resource_group"]),
            ("namespace", "Namespace", self.namespace, not self.fixed["namespace"]),
            # One complete editor per resource: DPS (new + name, existing, or none; not once linked) and the IoT Hubs
            # manager, the same one Connectivity opens (linked IoT Hubs stay; more can be added beside them).
            ("dps", "DPS", self._target_summary("dps"), guided and not self._linked("dps")),
            ("hubs", "IoT Hubs", self._hub_summary(self.choices.get("hub") or []), guided),
            ("software_updates", "Software updates", "yes · new " + self._name("software-updates")
             if self.software_updates else "no", guided and not self._linked("software-updates")),
            ("cms", "CMS", "yes" if self.cms else "no", guided),
            ("region", "Region", self._new_location() or "", new_namespace and not self.fixed_location),
            ("tags", "Tags", " ".join(f"{k}={v}" for k, v in sorted((self.tags or {}).items())) or "none",
             new_namespace and not self.fixed_tags),
            ("identity", "Outbound identity", identity_value(self.outbound)[0] if self.outbound else
             "the namespace's current one" if self.ns_info is not None else "system-assigned when linking",
             not self.fixed_outbound and not (self.config or {}).get("namespace", {}).get("outboundIdentity")),
        )
        rows += [Row(key, title, detail) for key, title, detail, shown in options if shown]
        return rows + [Row("save", "Save configuration", "JSON for --config"),
                       Row("quit", "Cancel setup", "nothing written")]

    def _target_summary(self, kind):
        choice = self.choices.get(kind) or {"mode": "none"}
        if choice["mode"] == "new":
            return f"new · {choice['name']} · {tier_detail(kind, choice)}"
        if choice["mode"] == "existing":
            return f"existing · {choice['name']}"
        return "none · link later"

    def _edit_software_updates(self):
        """Software updates yes/no, then the new instance's name; Esc from the question leaves both unchanged."""
        before = (self.software_updates, dict(self.names), set(self.shown))
        try:
            while True:
                self._q_software_updates()
                if not self.software_updates:
                    return
                try:
                    self.names["software-updates"] = self._ask_name("software-updates", self._name("software-updates"))
                except BackRequested:
                    continue
                return
        except BackRequested:
            self.software_updates, self.names, self.shown = before
            raise

    def edit(self, choice, error=""):
        if choice in ("resource_group", "namespace", "cms"):
            self.ask(QUESTIONS[QUESTIONS.index(choice):] if choice != "cms" else (choice,), allow_back=True)
            return
        if choice == "dps":
            self._edit_target(choice, error)
        elif choice == "hubs" or choice.startswith("hub:"):  # the manager; a plan problem opens its IoT Hub
            self.choices["hub"] = self._manage_hubs(
                self.choices.get("hub") or [], open_index=int(choice[4:]) if choice != "hubs" else None,
                error=error)
        elif choice == "software_updates":
            self._edit_software_updates()
        elif choice == "name-software-updates":  # a plan problem with the instance name (e.g. taken)
            self.names["software-updates"] = self._ask_name("software-updates", self._name("software-updates"), error)
        elif choice == "region":
            while True:
                value = self.prompter.ask("Region:", default=self._new_location() or "", error=error,
                                          hint=[("", "Azure region name, for example eastus"), ("esc", "back")])
                error = "" if re.fullmatch(r"[a-z0-9]+", value) else "Use a region name such as eastus or westeurope."
                if not error:
                    break
            self.location = value
        elif choice == "tags":
            while True:
                value = self.prompter.ask("Tags:", initial=" ".join(
                    f"{k}={v}" for k, v in sorted((self.tags or {}).items())), error=error,
                    hint=[("", "key=value pairs separated by spaces; empty for none"), ("esc", "back")])
                try:
                    self.tags = parse_tags(value)
                    break
                except InvalidArgumentValueError as invalid:
                    error = str(invalid)
        else:  # identity
            while True:
                value = self.prompter.ask(
                    "Outbound identity:", [Row("system-assigned", "system-assigned",
                                               "the namespace's own system-assigned managed identity")],
                    default=self.outbound or "system-assigned", error=error,
                    hint=[("tab", "complete"), ("", "or a user-assigned managed identity resource ID"),
                          ("esc", "back")])
                try:
                    validate_identity(value, "namespace.outboundIdentity")
                    break
                except InvalidArgumentValueError as invalid:
                    error = str(invalid)
            self.outbound = value
            self.shown.add("identity")
        self._accepted()
        self.refresh()

    def save(self):
        try:
            config = self.compose()
        except AzCLIError as error:
            self.say(f"Couldn't build the configuration: {error}", mark="✗", style=BAD_BOLD)
            return
        error = ""
        default = f"{self.namespace}-setup.json"
        while True:
            try:
                path = self.prompter.ask("Save to:", default=default, error=error,
                                         hint=[("", "new file; existing files are never overwritten"), ("esc", "back")])
            except BackRequested:
                return
            try:
                with open(os.path.expanduser(path), "x", encoding="utf-8") as handle:
                    handle.write(json.dumps(config, indent=2, sort_keys=True) + "\n")
            except FileExistsError:
                error = f"{path} already exists. Choose a new file name."
                continue
            except OSError as failure:
                error = f"Couldn't write {path}: {failure.strerror or failure}."
                continue
            break
        self.notes += [(f"Saved {path} · strict setup configuration", "✓", GOOD),
                       (f"Rerun or automate: az iot adr ns setup --config @{_quote(path)}", "·", DIM)]
        self.refresh()

    def plan_error(self, error):
        """The answer that can fix a plan read failure, or None."""
        message = str(error)
        if isinstance(error, OutboundIdentityProblem):
            return "identity"
        config_paths = {"dps": "links.dps", "hub": "links.hubs", "software-updates": "links.softwareUpdates"}

        def names(name):  # a whole resource name, never a fragment of another word
            return bool(name) and re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", message) is not None

        for kind in ("dps", "hub", "software-updates"):
            if self.explicit:
                continue
            if kind == "hub":
                hub = self._hub_error(message, names)
                if hub:
                    return hub
                continue
            choice = self.choices.get(kind, {})
            if f"--{kind}." in message or config_paths[kind] in message or names(choice.get("name")) or (
                    kind == "software-updates" and self.software_updates and (
                        "Update Instance" in message or names(self._name(kind)))):
                return "name-software-updates" if kind == "software-updates" else kind  # its editor
        if "namespace.location" in message and not self.fixed_location:
            return "region"
        return None

    def _hub_error(self, message, names):
        """The chosen IoT Hub a plan problem is about: by its links.hubs index, by its name, or by the endpoint the
        plan was checking when a message names neither ("hub:<n>"); "hubs" (the manager) when it can't tell."""
        hubs = self.choices.get("hub") or []
        if not hubs:
            return None
        index = re.search(r"links\.hubs\[(\d+)\]", message)
        if index:  # a kept link's problem isn't a chosen IoT Hub's: Change, with the problem shown
            slot = self.hub_slots.get(int(index.group(1)))
            return None if slot is None else f"hub:{slot}"
        for number, hub in enumerate(hubs):
            if names(hub["name"]):
                return f"hub:{number}"
        if "--hub." not in message and "links.hubs" not in message:
            return None
        for number, hub in enumerate(hubs):
            key = self._target_key("hub", hub["name"] if hub["mode"] == "new" else hub["value"])
            if key and self.plan_target == ("hub", key[1]):
                return f"hub:{number}"
        return "hubs"

    def _plan_failed(self, error):
        """Show a failed plan read and go to the answer that can fix it (inline on its field), else to Change."""
        message = identity_words(error)
        field = self.plan_error(error)
        self.mode = "answers"
        self.notes = []
        problem = (message, "✗", BAD_BOLD)
        if field is None or field in QUESTIONS:
            self.notes.append(problem)
        if field == "identity":
            self.notes.append(("Setup never replaces an existing outbound identity on its own.", "·", DIM))
        self.refresh()
        if field is None:
            self.change_menu(blocked=True)
            return
        try:
            self.edit(field, error=message)
        except BackRequested:
            if problem not in self.notes:
                self.notes.insert(0, problem)
            self.change_menu(blocked=True)

    def _blocked(self, plan):
        self.notes = [("The plan is blocked. Change an answer, or fix the cause in Azure and re-read.", "!", WARN_BOLD)]
        for item in ordered_items(plan):
            if item_tag(item) == "blocked":
                self.notes.append((f"{item_label(item)} {_short(item.get('target'))} · "
                                   f"{identity_words(item.get('message')) or 'blocked'}", "✗", BAD_BOLD))

    # ---- run -----------------------------------------------------------------------------

    def header(self):
        title = Text(" " * INDENT)
        title.append_text(self.screen.brand("Azure Device Registry"))
        title.append(" · namespace setup", PLAIN)
        self.screen.blank()
        self.screen.print(title)
        self.screen.print(Text(" " * INDENT + "Reads Azure until you approve a plan · Ctrl+C cancels", DIM))
        self.screen.blank()
        with self.screen.activity("Reading subscription"):
            subscription = self.services.show_subscription(self.subscription)
        if not subscription:
            raise InvalidArgumentValueError(
                f"Subscription '{self.subscription}' is not accessible. Select another with --subscription.")
        self.subscription_name = subscription.get("displayName") or subscription.get("display_name") or self.subscription
        self.tenant = str(subscription.get("tenantId") or subscription.get("tenant_id") or "")
        self.subscription_names[self.subscription.casefold()] = self.subscription_name
        self.screen.fact("Subscription:", self.subscription_name, self.subscription
                         if self.subscription_name != self.subscription else "")

    def run(self):
        """Everything before apply is cancellable with nothing written; apply reports its own true outcome."""
        try:
            self.header()
            self.ask()
            approved = self.review_and_apply()
        except (KeyboardInterrupt, WorkflowCancelled):
            try:
                self.screen.clear_status()
                self.screen.commit()
                self.screen.blank()
                self.screen.note("Cancelled · nothing was written to Azure.", mark="✗", style=DIM)
            except KeyboardInterrupt:
                pass
            return None
        if isinstance(approved, Approved):
            return self.apply(approved.request, approved.config)
        return approved

    def _reached_unchanged(self, plan):
        """A plan with nothing to apply: honest about warnings and links setup couldn't assess."""
        attention = [item for item in plan.get("items", []) if item.get("state") in ("Warning", "Manual")]
        self.screen.blank()
        if attention or self.unassessed:
            count = len(attention) + len(self.unassessed)
            needs = f"{count} items above need" if count != 1 else "1 item above needs"
            self.screen.fact("No changes:", self.namespace, f"nothing to apply · {needs} attention",
                             mark="!", mark_style=WARN_BOLD)
        else:
            self.screen.fact("Up to date:", self.namespace, "Azure already matches this setup · nothing to apply")
        self._check_hint()

    def _script_problem(self, plan):
        """--output-script is rendered and its destination checked before approval; written only after it."""
        if not self.output_script or self.plan_only:
            return False
        try:
            self.check_script(self.output_script, plan.get("items", []))
        except AzCLIError as error:
            self.notes = [(f"--output-script: {error}", "✗", BAD_BOLD),
                          ("Change an answer, or cancel and choose another --output-script.", "·", DIM)]
            return True
        return False

    def review_and_apply(self):
        reread = True
        while True:
            if reread:
                # Supplied arguments/config the user must fix on the command line fail like unattended setup.
                config = self.compose() if self.explicit else None
                try:
                    config = config or self.compose()
                    self._check_outbound(config)
                    request, plan = self.read_plan(config)
                except Exception as error:  # noqa: BLE001 - shown to the user and routed to the answer that fixes it
                    self._plan_failed(error)
                    continue
                self.plan = plan
                self.notes = []
            reread = True
            self.mode = "plan"
            self.refresh()
            if self.plan_only:
                self.screen.commit()
                self._write_script(plan)
                self._suggest(config, "Plan only · nothing was written. Apply it with:")
                return plan
            if plan["state"] == "Succeeded":
                self.screen.commit()
                self._reached_unchanged(plan)
                return plan
            if plan["state"] == "Blocked":
                self._blocked(plan)
                self.change_menu(blocked=True)
                continue
            if self._script_problem(plan):
                self.change_menu(blocked=True)
                continue
            if not self.approve():
                self.change_menu()  # leaving Change always reads Azure again
                continue
            try:
                request, current = self.read_plan(config, "Re-reading Azure before applying")
            except Exception as error:  # noqa: BLE001 - nothing was written; reported, approval is asked again
                self.say(f"Couldn't re-read Azure before applying: {error} Nothing was written; approve again to "
                         "retry.", mark="✗", style=BAD_BOLD)
                reread = False
                continue
            if plan_fingerprint(current) != plan_fingerprint(plan):
                self.plan = plan = current
                self.notes = [("Azure changed since you reviewed the plan. Review the updated plan.", "!", WARN_BOLD)]
                reread = False
                continue
            self.screen.commit()
            self._write_script(plan)
            self.screen.fact("Approved:", self.namespace, "applying the plan above")
            self.screen.blank()
            self.screen.print(Text(" " * INDENT + "Applying · Ctrl+C stops before the next Azure request", DIM))
            return Approved(request, config)

    def _write_script(self, plan):
        if self.output_script:
            self.write_script(self.output_script, plan.get("items", []))
            self.screen.fact("Script:", self.output_script, "commands for the planned changes")

    def _suggest(self, config, heading):
        lines = equivalent_command(config)
        self.screen.blank()
        if lines:
            self.screen.command(lines, heading)
        else:
            self.screen.print(Text(" " * INDENT + heading.replace(" Apply it with:", "") +
                                   " Save the configuration from Change to automate CMS setup with --config.", DIM))

    # ---- apply ---------------------------------------------------------------------------

    def apply(self, request, config):
        progress = Progress()
        outcome: Dict[str, Any] = {}

        def work():
            try:
                with quiet_providers():
                    outcome["result"] = NamespaceWorkflow(self.services, progress=progress).setup(request)
            except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001 - handed to the UI thread and reported
                outcome["error"] = error
            finally:
                progress.events.put(("end",))

        started = time.monotonic()
        current = {"label": "", "since": started}
        worker = threading.Thread(target=work, name="adr-setup-apply", daemon=True)
        detached = False
        with no_echo(sys.stdin):
            worker.start()
            while not detached:
                try:
                    if self._pump(progress, current):
                        break
                except KeyboardInterrupt:
                    detached = progress.stop.is_set()
                    progress.stop.set()
                    if not detached:
                        try:
                            self.screen.warn("Stopping after the current Azure request · "
                                             "Ctrl+C again stops watching.")
                        except KeyboardInterrupt:
                            detached = True
        # From here the outcome is fixed: Ctrl+C can cut output short, never change the result or persist it twice.
        try:
            self.screen.clear_status()
        except KeyboardInterrupt:
            pass
        elapsed = time.monotonic() - started
        result = None
        while result is None:
            try:
                if detached:
                    result = self._detached_result(request, progress, current["label"])
                elif "error" in outcome:
                    result = self._failed_result(request, progress, outcome["error"])
                else:
                    result = outcome["result"]
            except KeyboardInterrupt:
                continue
        try:
            self.persist(result)
        except KeyboardInterrupt:
            if not result.get("receipt"):
                result["receiptError"] = "interrupted before the receipt was saved"
        try:
            self.summary(result, config, elapsed, outcome.get("error"), current["label"] if detached else "")
        except KeyboardInterrupt:
            pass
        return result

    def _pump(self, progress, current):
        try:
            event = progress.events.get(timeout=FRAME)
        except queue.Empty:
            if current["label"]:
                self.screen.status(pretty_label(current["label"]), current["since"])
            return False
        kind, label = event[0], event[1] if len(event) > 1 else ""
        if kind == "end":
            return True
        if kind == "start":
            current.update(label=label, since=time.monotonic())
            self.screen.status(pretty_label(label), current["since"])
            return False
        seconds = int(time.monotonic() - current["since"])
        timing = f"{seconds}s" if seconds else ""
        if kind == "fail":
            self.screen.step(pretty_label(label), timing, mark="✗", style=BAD_BOLD)
        elif event[2] or label.startswith(PERMANENT):
            self.screen.step(pretty_label(label), timing)
        current.update(label="")
        return False

    def _failed_result(self, request, progress, error):
        result = deepcopy(getattr(error, "result", None))
        if result is None:
            items = [item.as_dict() for item in progress.items]
            result = {
                "command": "az iot adr ns setup", "state": "Failed", "namespace": request.namespace_name,
                "resourceGroup": request.resource_group_name, "summary": {},
                "items": items + [{"id": "execution", "action": "apply", "state": "Failed",
                                   "target": request.namespace_name, "message": str(error)}],
            }
        kind = termination_kind(error)
        if kind in ("stopped", "interrupted"):
            result["state"] = "Stopped"
            for item in result["items"]:
                if item.get("id") == "execution":
                    item["state"] = "Stopped"
                    if kind == "stopped":
                        item["message"] = "Stopped before the next Azure request."
        return result

    @staticmethod
    def _detached_result(request, progress, label):
        items = [item.as_dict() for item in list(progress.items)]
        items.append({
            "id": "execution", "action": "apply", "state": "Stopped", "target": request.namespace_name,
            "message": f"Stopped watching while '{label}' was in progress; that request may still complete in Azure."
            if label else "Stopped watching; a submitted request may still complete in Azure.",
        })
        summary: Dict[str, int] = {}
        for item in items:
            summary[item["state"]] = summary.get(item["state"], 0) + 1
        return {"command": "az iot adr ns setup", "state": "Stopped", "namespace": request.namespace_name,
                "resourceGroup": request.resource_group_name, "summary": summary, "items": items}

    def _check_hint(self):
        self.screen.blank()
        self.screen.command([
            f"az iot adr ns check -n {_quote(self.namespace)} -g {_quote(self.rg)}",
            f"--subscription {_quote(self.subscription)}"], "Check readiness (read-only):")

    def summary(self, result, config, elapsed, error, watching):
        minutes, seconds = divmod(int(elapsed), 60)
        took = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
        changed = sum(item.get("state") == "Succeeded" for item in result.get("items", []))
        self.screen.blank()
        state = result.get("state")
        if state == "Succeeded":
            self.screen.fact("Done:", f"{self.namespace} is set up", f"{changed} changes · {took}",
                             mark="✓", mark_style=GOOD_BOLD)
        elif state == "Warning":
            warnings = [item for item in result.get("items", []) if item.get("state") == "Warning"]
            self.screen.fact("Done:", self.namespace, f"applied with {len(warnings)} warning"
                             f"{'s' if len(warnings) != 1 else ''} · {changed} changes · {took}",
                             mark="!", mark_style=WARN_BOLD)
            for item in warnings:
                self.screen.note(f"{item_label(item)} {identity_words(item.get('message')) or 'needs attention'}",
                                 mark="!", style=WARN_BOLD)
        if state in ("Succeeded", "Warning"):
            submitted = sum(item.get("message") == "Link request submitted." for item in result.get("items", []))
            if submitted:
                self.screen.note(f"{submitted} link request{'s' if submitted != 1 else ''} submitted; "
                                 "linking can take a few minutes. Check confirms readiness.", mark="·", style=DIM)
        else:
            verb = state if state in ("Stopped", "Blocked") else "Failed"
            blocked = "finished with blockers · " if state == "Blocked" else ""
            self.screen.fact(f"{verb}:", self.namespace, f"{blocked}{changed} changes completed · {took}",
                             mark="✗" if state != "Blocked" else "!", mark_style=BAD_BOLD if state != "Blocked"
                             else WARN_BOLD)
            for item in result.get("items", []):
                if item.get("state") in ("Failed", "Blocked", "Stopped") and item.get("message"):
                    self.screen.note(identity_words(item["message"]), mark="·", style=DIM)
            self.screen.note(
                "Submitted requests may continue in Azure; nothing was rolled back. "
                "Rerun the same setup to re-read Azure and resume." if changed or error or watching
                else "No changes were made by this attempt.", mark="·", style=DIM)
        if result.get("receipt"):
            self.screen.fact("Receipt:", result["receipt"], value_style=PLAIN, mark="·", mark_style=DIM)
        elif result.get("receiptError"):
            self.screen.warn(f"Couldn't save the receipt: {result['receiptError']}")
        self._check_hint()
        lines = equivalent_command(config)
        if lines:
            self.screen.blank()
            self.screen.command(lines, "Repeat without prompts:")


def parse_tags(value: str) -> Optional[Dict[str, str]]:
    tags = {}
    for pair in shlex.split(value or ""):
        key, separator, item = pair.partition("=")
        if not separator or not key.strip():
            raise InvalidArgumentValueError(f"Tag '{pair}' must use key=value.")
        tags[key.strip()] = item
    return tags or None


def run_guided_setup(services, subscription_id, *, config=None, arguments=None, plain=False, plan_only=False,
                     output_script=None, persist: Optional[Callable] = None, write_script: Optional[Callable] = None,
                     check_script: Optional[Callable] = None, screen=None, prompter=None):
    owned = screen is None
    if owned:
        screen = Screen(plain=plain)
    try:  # from the probe on, whatever happens, the terminal's own settings come back (``release``)
        typed = screen.probe() if owned else ""  # a real run asks the terminal for its background once, first
        prompter = prompter or (PlainPrompter(screen.stream) if plain else TerminalPrompter(
            screen.stream, reserve=screen.reserve, palette=screen.palette, tints=screen.tints, motion=screen.motion,
            replies=screen.replies, typed=typed))
        return GuidedSetup(
            services, subscription_id, screen=screen, prompter=prompter, arguments=arguments, config=config,
            plan_only=plan_only, output_script=output_script, persist=persist, write_script=write_script,
            check_script=check_script,
        ).run()
    finally:
        screen.release()
