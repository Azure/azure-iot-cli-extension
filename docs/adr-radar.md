# Radar: minimal ADR resource browsing

```bash
az iot adr ns ui -g devices-rg
az iot adr ns ui -g devices-rg --read-only
```

Radar uses one table or detail view, one accent, and contextual menus.
Choose JetBrains Mono in your terminal settings to match the design preview;
the CLI does not install or change terminal fonts.

**No namespace creation or onboarding is included.** Setup owns onboarding,
check owns diagnostics, and radar owns browsing and basic CRUD. The setup/check
commands are independent features; radar does not invoke them.

## Navigation

| Mouse or key | Action |
| --- | --- |
| Click a row / Enter | Open the selected resource's details |
| Namespace selector | Return to the namespace collection |
| Resource selector / `:` | Switch resource kinds |
| `/` | Filter the current, cached rows locally |
| Click a column heading / `s` | Sort; selecting the same column reverses order |
| `r` | Refresh from Azure, respecting service backoff |
| `a` / footer Actions | Open actions applicable to this resource |
| `o` / operations selector | View submitted operations and results |
| Esc | Leave filtering or return to the previous view |
| `?` | Help and available resource kinds |
| `q` / Ctrl+Q | Quit; if an operation is running, choose Keep watching or Quit anyway |

Child collections are available as detail-view buttons and contextual keys.
Tables fit the terminal width; details retain fields that do not fit. The
intended minimum layout is 80 columns. Refresh runs off the UI thread and only
the visible collection polls. Filtering and animation do not make API calls.

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
all existing tags requires typed confirmation, as do deletes and CA rotation.
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
