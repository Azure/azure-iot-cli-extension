# Radar: minimal ADR resource browsing

```bash
az iot adr ns ui -g devices-rg
az iot adr ns ui -g devices-rg --read-only
```

Radar is one centred column (92 cells wide, or the terminal width less a
2-cell margin): a prompt header (`❯ radar▌`, the namespace, resource group and
subscription, and the operations state), a title row with the row count, the
page's own controls and the search field, the table or detail, and one short
line of keys. There is no footer, boxed panel or tinted surface; only dialogs
are boxed. The selected row is marked by an accent `▎` bar and a subtle row
background in explicit dark/light themes; terminal mode uses reverse video.
Choose JetBrains Mono in your
terminal settings to match the design preview; the CLI does not install or
change terminal fonts.

The default theme is **terminal**: background, foreground, and accent colors
follow the terminal's current palette, including light backgrounds and
transparency. Changing the terminal's colors also changes radar without a restart.
Use `--theme dark`, `--theme light`, or `--theme high-contrast` for an explicit
override. `Ctrl+T` cycles **terminal → dark → light → terminal**; the Go to menu
offers the same action without requiring a shortcut. High contrast remains fixed
for the session.

Tables show the primary columns only (for example NAME / STATUS / LOCATION for
namespaces, NAME / TYPE / STATUS for linked resources, with short display types
`dps`, `hub`, `su`). Secondary fields such as targets, identities, counts and age
are in the detail view and in wide mode (`Ctrl+W`). The resource group column
appears only when two listed rows share a name.

**No namespace creation or onboarding is included.** Setup owns onboarding,
check owns diagnostics, and radar owns browsing and basic CRUD. The setup/check
commands are independent features; radar does not invoke them.

## Subscription and resource group

The resource group and subscription in the header are controls: click one, or
Tab to it and press Enter, to open the scope picker on that list (`@` is a
shortcut for the resource group list). Type to filter, use ↑↓ and Enter to
choose, Tab to switch between the two lists, and Esc to leave without changing
anything. Choosing a subscription moves to its resource groups; nothing changes
until a resource group (or "all resource groups") is chosen.

- Subscriptions come from your `az login` profile only. Radar never runs
  `az account set` or changes `az configure` defaults; each scope uses its own
  copy of the CLI context, and read commands it shows include `--subscription`.
- Resource groups are listed once per subscription (at most 1000, cached for
  five minutes) and filtered locally as you type. A typed name that is not in the
  list can still be used; a name Azure would reject (for example one with a
  space) is explained in the status line (`Not a valid name`) and Enter keeps it for correcting.
  The last row, "reload list", relists (↑ from the first row wraps to it; an
  optional `Ctrl+R` or a click on the status line does the same). When listing
  is not authorized or fails, the picker says so, keeps "type a name"
  available, and offers a "retry listing" row instead.
- Switching scope replaces the open pages and invalidates any open form or
  review. Results from the previous scope are never shown under the new one, and
  cached rows are keyed by subscription and resource group. Operations already
  submitted keep their own scope and are labelled with it; a write is never
  redirected to the newly selected subscription or resource group.

## Search

The search field is always visible in the title row; Shift+Tab from the table,
a click, or `/` reaches it. Typing filters the loaded rows by every
column, including wide-only columns, locally (every word must match; `!word` hides matches) and
never calls Azure. ↑↓ moves through matches while typing, Enter keeps the search
and returns to the table, and Esc clears it.

## Keys and controls

| Key | Action |
| --- | --- |
| Tab / Shift+Tab | Move between the header, title-row and page controls, the search field and the table |
| ↑↓ | Move in tables, lists and pickers |
| Enter | Open the selected row, press the focused control, accept a dialog |
| Space | Press the focused control or button |
| Esc | Back, close a dialog, clear the search; on the first page it says how to leave (Go to › Quit radar) |
| `q` | Quit (also in the `❯ radar` list); with an operation running, Keep watching is the default |
| `?` | Help and the optional shortcuts (also in the `❯ radar` list) |

The key line shows only what applies, for example
`Enter open  Tab controls  : go to  q quit  ? help`. Page controls have plain
labels and appear only when they apply: `Actions`, `Raw JSON`, a detail page's
child lists (`Links`, `Devices`, ...) and the operations page's `Re-read`,
`Stop watching` and `Dismiss finished`. Everything clickable is also a Tab stop.

The `❯ radar` prompt (the first Tab stop on every page, or `:`) opens the go-to
list: resource kinds first, then a short "radar" group with help, list
commands (refresh now, sort by…), view settings that change something on the
current page (show all or fewer columns, next terminal/dark/light theme; not offered in
high contrast) and quit. "Sort by…" lists the displayed columns; choosing the
current one reverses it. When the go-to list is taller than the terminal, the
row under it says how many entries are out of view above and below. With an operation running,
the quit dialog starts on Keep watching; Tab to Quit anyway and press Enter to
leave.

Letter shortcuts are optional and listed in help rather than on screen: `/`
search, `a` actions, `:` go to, `@` resource group, `o` operations, `y` raw
JSON, `r` refresh now (lists also refresh on their own), `s` the sort list (or click a
column heading), `Ctrl+W` wide columns, `Ctrl+T` terminal/dark/light, `Ctrl+R` reload the
picker list, and each page's own letters (child lists; `r`/`x`/`d` on the
operations page). No shortcut fires while typing in a field.

Details show the resource's fields as `label  value` rows, then the child
collections under "open", and, when one exists, the equivalent `az` read
command. Raw JSON is shown only on request. Tables fit the terminal width;
details retain fields that do not fit. The intended minimum layout is 80
columns. Refresh runs off the UI thread and only the visible collection polls.

The actions control lists only actions that apply to the selected row's type
and state (a hub link never lists DPS or Software Updates row actions; "wait"
appears only for an Accepted link). A short note explains why a familiar action
is absent when that is useful. The dialog shows the exact command Review will
run once every argument is known.

## Actions

Namespaces support update/delete, but not create. Devices, groups, jobs,
certificate authorities/policies, and standalone Software Updates instances
provide basic CRUD. Links provide add, wait, retry/update, and remove through the
release link providers. Schema registries, device classes, group members, job
runs, and software-update catalog metadata are browse-only; advanced workflow
and file-transfer commands remain in the ordinary CLI.

Before a write, radar displays its scope and equivalent command. Create checks
for an existing name instead of deliberately replacing it. Update forms start
from the selected record's current values; an unchanged submit is rejected.
Tags are a complete replacement object, prefilled with existing tags. Clearing
all existing tags requires typed confirmation, as do deletes and CA rotation;
Enter with a different name says so and sends nothing.
The provider rechecks the resource and its etag when supplied by Azure.

`--read-only` disables mutation options and independently guards execution.
Link add/update may create required role assignments for an authorized caller;
the review discloses those writes rather than describing them as read-only
validation. Certificate material and known credential fields are redacted.

## Honest progress and recovery

Operations show elapsed time and actual completion or failure, never invented
percentages. A namespace admits only one simultaneous mutation, with a bounded
overall worker count. Submitted Azure operations are not rolled back.

**Stop watching does not cancel an Azure request.** Background results can still
arrive. Quit does not wait for a slow background read. With an operation running,
Quit anyway leaves immediately; submitted requests may continue in Azure, but
unstarted steps may not run. The CLI reports unfinished outcomes as unknown and
prints their requested commands (a queued call might not have been sent).
Re-read current state before reviewing a retry;
radar never blindly replays a failed write. Read failures remain visible, and
cached rows are marked stale instead of being presented as a successful empty
collection.
