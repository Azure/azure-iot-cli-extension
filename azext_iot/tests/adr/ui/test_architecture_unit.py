# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Architectural guards.

These encode the design doc's structural rules so a regression fails a test rather than
being discovered later as a maintenance problem.
"""

import pathlib

import pytest

UI_ROOT = pathlib.Path(__file__).resolve().parents[3] / "adr" / "ui"

#: Kind identifiers that must never appear as literals in the generic machinery.
KIND_LITERALS = ("namespace", "device", "attribute", "group", "job", "certificate")


def read(*parts: str) -> str:
    return (UI_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_ui_root_exists():
    assert UI_ROOT.is_dir(), f"expected the UI package at {UI_ROOT}"


def test_browse_screen_has_no_per_kind_branching():
    """The step 4 gate: one screen serves every kind, driven only by its spec."""
    source = read("screens", "browse.py")
    for literal in KIND_LITERALS:
        assert f'"{literal}"' not in source, (
            f"browse.py references the kind '{literal}'. The generic screen must be "
            "driven by ResourceSpec alone, or adding a kind stops being a one-file change."
        )


def test_overview_screen_has_no_per_kind_branching():
    """Hierarchy summaries are declared on specs, never special-cased in the screen."""
    source = read("screens", "overview.py")
    for literal in KIND_LITERALS:
        assert f'"{literal}"' not in source


def test_core_is_free_of_the_ui_framework():
    """Layering rule: core stays framework-free so it is testable without a terminal."""
    for module in ("spec.py", "table.py"):
        source = read("core", module)
        assert "textual" not in source, f"core/{module} must not import the UI framework"


def test_core_does_not_import_screens_or_widgets():
    """Dependency rule: core may not import from the layers above it."""
    for module in ("spec.py", "table.py"):
        source = read("core", module)
        for upper in ("ui.screens", "ui.widgets", "ui.app"):
            assert upper not in source, f"core/{module} must not depend on {upper}"


def test_entry_point_does_not_import_the_framework_at_module_scope():
    """The framework is imported lazily so no other command pays the cost."""
    source = read("entry.py")
    module_scope = source.split("def adr_ui_launch")[0]
    assert "import textual" not in module_scope
    assert "from textual" not in module_scope
    assert "from azext_iot.adr.ui.app import" in source, "the app import stays inside the function"


def test_entry_point_silences_the_provider_console():
    """PR2: providers print rich spinners that would corrupt the screen."""
    source = read("entry.py")
    assert "console.quiet = True" in source


@pytest.mark.parametrize("module", ["spec", "table"])
def test_core_modules_are_importable_without_a_terminal(module):
    __import__(f"azext_iot.adr.ui.core.{module}")


def test_app_has_no_per_kind_branching():
    """The application must not know any kind by name.

    Child scoping is declared on the spec (``scope_key`` / ``scope_extra``), so adding a
    kind stays a one-file change. This guard exists because an earlier revision carried a
    kind-to-scope-key map here.
    """
    source = read("app.py")
    for literal in KIND_LITERALS:
        assert f'"{literal}"' not in source, (
            f"app.py references the kind '{literal}'; declare it on the ResourceSpec instead"
        )


def test_row_loading_happens_off_the_ui_thread():
    """Rule C1: the source performs network I/O from M1 and must never block the UI."""
    source = read("screens", "browse.py")
    assert "run_worker" in source and "thread=True" in source
    assert "call_from_thread" in source, "worker results must be marshalled back to the UI"
    assert "if self._loading:" in source, (
        "rule C2: an overlapping refresh is dropped, never cancelling the in-flight request"
    )


def test_widgets_do_not_import_core_internals():
    """Chrome widgets are presentation only; they must not reach into the model."""
    for module in ("chrome.py", "dialogs.py"):
        source = read("widgets", module)
        assert "core.table" not in source, f"widgets/{module} must not depend on the table model"


def test_no_method_shadows_a_framework_method():
    """Overriding a framework method by accident breaks the UI in obscure ways.

    This has bitten twice: `_render` on a Static, and `run_action` on the App. A scan is
    cheaper than rediscovering it each time.
    """
    import re

    from textual.app import App
    from textual.screen import Screen
    from textual.widgets import Static

    bases = {"App": set(dir(App)), "Screen": set(dir(Screen)), "Static": set(dir(Static))}
    targets = {
        ("app.py",): "App",
        ("screens", "base.py"): "Screen",
        ("screens", "browse.py"): "Screen",
        ("screens", "detail.py"): "Screen",
        ("screens", "help.py"): "Screen",
        ("screens", "overview.py"): "Screen",
        ("widgets", "chrome.py"): "Static",
        ("widgets", "tray.py"): "Static",
    }
    # Textual dispatches these by name on purpose; overriding them is the intended API.
    allowed_prefixes = ("on_", "action_", "watch_", "compose", "validate_", "check_")

    collisions = []
    for parts, base in targets.items():
        source = read(*parts)
        for match in re.finditer(r"^    def ([a-zA-Z_]\w*)\(", source, re.M):
            name = match.group(1)
            if name.startswith(allowed_prefixes) or name == "__init__":
                continue
            if name in bases[base]:
                collisions.append(f"{'/'.join(parts)}: {name}() shadows {base}.{name}")
    assert not collisions, "framework methods shadowed: " + "; ".join(collisions)


def test_tables_declare_explicit_column_widths():
    """Auto-width collides at 80-120 columns and pushes the decisive column off screen."""
    source = read("screens", "onboard", "screen.py")
    assert "width=" in source, "candidate table must size its columns explicitly"


def test_every_modal_is_centred():
    """Only HelpScreen was centred, so other dialogs rendered in the top-left corner."""
    from azext_iot.adr.ui.theme import APP_CSS

    assert "ModalScreen {" in APP_CSS
    modal_block = APP_CSS.split("ModalScreen {", 1)[1].split("}", 1)[0]
    assert "align: center middle" in modal_block


def test_status_colours_come_from_the_designed_palette():
    """Raw ANSI green/red is loud; the tokens track the base theme's palette."""
    from azext_iot.adr.ui.theme import DEFAULT_THEME, THEMES

    for token, colour in THEMES[DEFAULT_THEME].items():
        assert colour.startswith("#"), f"{token} should use a designed colour, got {colour}"


def test_daylight_and_night_palettes_are_both_designed():
    from azext_iot.adr.ui.theme import (
        DEFAULT_THEME,
        LIGHT_THEME,
        PALETTES,
        RADR_DARK_THEME,
        RADR_LIGHT_THEME,
        THEMES,
        base_theme_for,
    )

    expected_night = {
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
    expected_day = {
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
    assert base_theme_for(DEFAULT_THEME) == "radr-night"
    assert base_theme_for(LIGHT_THEME) == "radr-daylight"
    assert PALETTES[DEFAULT_THEME] == expected_night
    assert PALETTES[LIGHT_THEME] == expected_day
    assert RADR_DARK_THEME.primary == expected_night["accent"]
    assert RADR_LIGHT_THEME.primary == expected_day["accent"]
    assert RADR_DARK_THEME.background == expected_night["background"]
    assert RADR_LIGHT_THEME.background == expected_day["background"]
    assert THEMES[DEFAULT_THEME] != THEMES[LIGHT_THEME]
    assert all(colour.startswith("#") for colour in THEMES[LIGHT_THEME].values())


def test_presentation_colors_are_centralized_in_the_theme_module():
    """No page may silently opt out of the supplied day/night palettes."""
    import re

    offenders = []
    for path in UI_ROOT.rglob("*.py"):
        if path.parts[-2:] == ("theme", "__init__.py"):
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(r"#[0-9A-Fa-f]{6}", source):
            offenders.append(f"{path.relative_to(UI_ROOT)} contains a hex color")
        if re.search(
            r"""style\s*=\s*["'][^"']*\b(?:cyan|green|yellow|red|blue|magenta)\b""",
            source,
        ):
            offenders.append(f"{path.relative_to(UI_ROOT)} contains a named color")
    assert not offenders, "; ".join(offenders)


def test_page_guide_uses_the_dedicated_do_line_roles():
    source = read("widgets", "chrome.py")
    assert 'palette.get("do_bg"' in source
    assert 'palette.get("do_fg"' in source


def test_guides_and_steps_do_not_draw_decorative_left_blocks():
    from azext_iot.adr.ui.theme import APP_CSS

    guide = APP_CSS.split("PageGuide {", 1)[1].split("}", 1)[0]
    step = APP_CSS.split("#step-list > ListItem.-highlight {", 1)[1].split(
        "}", 1
    )[0]
    focused_step = APP_CSS.split(
        "#step-list:focus > ListItem.-highlight {", 1
    )[1].split("}", 1)[0]
    assert "border-left" not in guide
    assert "border-left" not in step
    assert "border-left" not in focused_step


def test_onboarding_is_one_workspace_not_two_nested_cards():
    from azext_iot.adr.ui.theme import APP_CSS

    rail = APP_CSS.split(".rail {", 1)[1].split("}", 1)[0]
    pane = APP_CSS.split(".pane {", 1)[1].split("}", 1)[0]
    form = APP_CSS.split("#create-form {", 1)[1].split("}", 1)[0]
    assert "background: transparent" in rail and "border: none" in rail
    assert "background: $surface" in pane and "border: none" in pane
    assert "background: transparent" in form and "border: none" in form


def test_selected_table_row_has_explicit_cross_theme_contrast():
    from azext_iot.adr.ui.theme import APP_CSS

    cursor = APP_CSS.split("DataTable > .datatable--cursor {", 1)[1].split("}", 1)[0]
    assert "background: $boost" in cursor
    assert "color: $primary-background" in cursor


def test_browse_rows_do_not_expose_unimplemented_space_marking():
    source = read("screens", "browse.py")
    assert 'Binding("space"' not in source
    assert '"* "' not in source
    repaint = source.split("def _repaint", 1)[1].split("def _sync_chrome", 1)[0]
    assert '"! "' not in repaint


def test_onboarding_focus_uses_matching_step_and_detail_headers():
    from azext_iot.adr.ui.theme import APP_CSS

    step = APP_CSS.split("#step-list > ListItem.-highlight {", 1)[1].split(
        "}", 1
    )[0]
    heading = APP_CSS.split("#step-heading {", 1)[1].split("}", 1)[0]
    assert "background: transparent" in step
    assert "background: $primary-darken-1" in heading
    title = APP_CSS.split(
        "#step-list > ListItem.selected-step > .step-title {", 1
    )[1].split("}", 1)[0]
    assert "background: $primary-darken-1" in title
    assert "color: $primary-background" in title


def test_unfocused_candidate_table_does_not_highlight_a_resource():
    from azext_iot.adr.ui.theme import APP_CSS

    unfocused = APP_CSS.split("#candidates > .datatable--cursor {", 1)[1].split(
        "}", 1
    )[0]
    focused = APP_CSS.split("#candidates:focus > .datatable--cursor {", 1)[1].split(
        "}", 1
    )[0]
    assert "background: transparent" in unfocused
    assert "background: $boost" in focused


def test_create_form_actions_are_flat_and_theme_integrated():
    from azext_iot.adr.ui.theme import APP_CSS

    actions = APP_CSS.split("#create-cancel,", 1)[1].split("}", 1)[0]
    assert "border: none" in actions
    assert "background: transparent" in actions
    assert "height: 1" in actions


# -- page guides ---------------------------------------------------------------------


def _real_specs():
    from azext_iot.adr.ui.kinds import build_registry

    class OfflineSession:
        def list_from(self, *args, **kwargs):
            return []

        def provider(self, name):
            return None

        def call(self, func, *args, **kwargs):
            return None

    return list(build_registry(OfflineSession()).all())


def test_every_kind_explains_itself():
    """A page that cannot say what it is leaves the customer guessing against live Azure."""
    missing = [spec.kind for spec in _real_specs() if spec.guide is None]
    assert not missing, f"these kinds have no page guide: {missing}"


def test_every_guide_says_what_runs_behind_it():
    """'What is this actually doing to my subscription' is the question that matters most."""
    missing = [spec.kind for spec in _real_specs() if not (spec.guide and spec.guide.runs)]
    assert not missing, f"these guides do not say what they run: {missing}"


def _real_commands():
    """Every `iot adr ns ...` command the extension actually registers."""
    import re

    source = read("..", "command_map.py")
    commands = set()
    for block in re.split(r"with self\.command_group\(", source)[1:]:
        group = re.search(r'"([^"]+)"', block)
        if not group:
            continue
        body = block.split("with self.command_group(")[0]
        for verb in re.findall(r'cmd_group\.(?:custom_|show_|wait_)?command\(\s*\n?\s*"([^"]+)"', body):
            commands.add(f"{group.group(1)} {verb}")
    return commands


def test_guides_cite_commands_that_actually_exist():
    """Hand-written command names drift. Anything cited must be a real command."""
    import re

    real = _real_commands()
    assert "iot adr ns list" in real, "the command table could not be parsed"

    failures = []
    for spec in _real_specs():
        for cited in re.findall(r"az (iot adr ns [a-z|\- ]+)", spec.guide.runs or ""):
            words = []
            for word in cited.split():
                # Flags are not part of the command name; the first one ends it.
                if word.startswith("-"):
                    break
                words.append(word)
            # Expand alternatives written as `dps|hub|su`, then check each spelling.
            spellings = [""]
            for word in words:
                spellings = [
                    f"{prefix} {choice}".strip()
                    for prefix in spellings
                    for choice in word.split("|")
                ]
            for spelling in spellings:
                if spelling not in real:
                    failures.append(f"{spec.kind}: 'az {spelling}' is not a real command")
    assert not failures, "\n".join(failures)


def test_guides_do_not_repeat_the_key_hints():
    """The hint bar is generated from real bindings; a hand-written copy would drift."""
    for spec in _real_specs():
        rows = dict(spec.guide.rows())
        assert "press enter" not in rows.get("about", "").lower()
        assert "arrow" not in rows.get("about", "").lower()


def test_guides_stay_short_enough_to_read():
    """Four labelled rows at most: orientation, action, Azure call, limitation."""
    for spec in _real_specs():
        rows = spec.guide.rows()
        assert len(rows) <= 4, f"{spec.kind} guide has {len(rows)} rows"
        for label, value in rows:
            assert len(value) <= 190, f"{spec.kind} '{label}' is {len(value)} characters"


def test_no_global_key_is_shadowed_by_a_drill_down_child():
    """A screen binding wins over an app binding, so a clash silently disables the global.

    This is exactly how 'g' for the page guide became unreachable on the namespace list,
    where 'g' already opened Groups.
    """
    from azext_iot.adr.ui.app import RadrApp
    from azext_iot.adr.ui.screens.browse import BrowseScreen

    child_keys = {
        child.key
        for spec in _real_specs()
        for child in spec.children
        if child.key
    }
    screen_keys = {binding.key for binding in BrowseScreen.BINDINGS}
    taken = child_keys | screen_keys
    clashes = [
        binding.key for binding in RadrApp.BINDINGS
        if binding.key in taken
    ]
    assert not clashes, f"these global keys are shadowed on the browse screen: {clashes}"
