# Guided namespace setup

Run `az iot adr ns setup` in a terminal. Setup is a guided command, not a
terminal application. It asks **one question at a time** directly below the
command. Accepted answers form one aligned block of `Label:  value` lines, the
**workspace**, which is updated in place as you answer, go back, change an
answer or review the plan (see [One workspace](#one-workspace)). There is no
alternate screen, full-screen frame, or mouse capture, so native text
selection, copying and scrolling keep working. Foreground and background are
the terminal's own. The only exceptions are two faint washes of that same
background, behind the focused list row and the plan under approval, and only
when the terminal reports its background color (see
[Motion and color](#motion-and-color)).

Setup owns onboarding. `az iot adr ns check -n <namespace> -g <resource-group>`
is a separate, read-only diagnostic. It takes parameters only and never prompts.

## What a fresh setup looks like

```text
  Azure Device Registry · namespace setup
  Reads Azure until you approve a plan · Ctrl+C cancels

  ✓ Subscription:      Contoso Dev  00000000-0000-0000-0000-000000000001
  ✓ Resource group:    rg-demo  eastus
  ✓ Namespace:         adr-demo  NEW · eastus

▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
  Plan  ✦ 4 new · ⇄ 2 links
  ✦ Outbound identity: system-assigned  NEW · namespace managed identity
  ✦ DPS:               adr-demo-dps  NEW · S1 · 1 unit · eastus
  ✦ IoT Hub:           adr-demo-hub  NEW · S1 · 1 unit · eastus
  ⇄ DPS:               adr-demo-dps  LINK · DPS system-assigned managed
                       identity
  ⇄ IoT Hub:           adr-demo-hub  LINK · IoT Hub system-assigned managed
                       identity
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀

  ? Approve:           adr-demo
    type adr-demo to apply · esc change · ctrl+c cancel
```

While you answer, the same block shows your answers (`✓ DPS:`, `✓ IoT Hub:`,
`✓ Software updates:`, `✓ CMS:`) under the scope rows. When the plan is read,
those rows are replaced by the plan in the same place.

Only the plan under approval sits on a **surface**: a faint, flat wash of the
terminal's own background, a breath lighter on a dark theme or darker on a
light one, leaning slightly toward the azure accent. There is no border,
stroke or shadow. The `▄` and `▀` rows above are half-height edges of that
same wash, which give the plan half a row of air above and below. They are
drawn in the wash color, so on screen they read as part of the surface, not
as a frame. The surface stops one column short of the terminal's width, and
rows inside it wrap one column earlier, so the wash never touches the last
column. Colored text on the surface is adjusted to keep at least 4.5:1
contrast with it (see [Motion and color](#motion-and-color)). When
**Change:** opens, the surface disappears with the plan, and it returns with
the next plan.

When the terminal doesn't report its background color, or with `NO_COLOR`,
`--plain` or 16 colors, nothing is painted. The plan heading then stands
between blank rows on the terminal's own background, exactly as in the sample
without its `▄` and `▀` rows.

Labels end with a colon, share one column and are drawn in the accent color.
Values are bold in the terminal's normal foreground, so a label never reads as
part of its value. Tags are bold color words: green `NEW`, teal `REUSE`, and
violet `LINK` and `LINKED`. `ROLE` and `WARNING` are amber, and `BLOCKED`
and errors are red. Details such as region, SKU or identity are secondary text after
the tag, never the value itself. Long names, resource IDs and paths wrap under
the value column instead of being cut off. The layout fits 80x24, and a wider
terminal only shortens wrapping.

Each plan row starts with a symbol for what it does, and the plan's headline
doubles as the legend, counting only the symbols the plan uses:

| Symbol | Meaning |
| --- | --- |
| `✦` | Create a resource or the namespace's outbound identity (`NEW`) |
| `⇄` | Link a DPS, IoT Hub or Device Update instance to the namespace (`LINK`) |
| `◇` | A role assignment that needs attention, under its row (see below) |
| `◐` | Update an existing resource or setting |
| `○` | Reuse an existing resource or link unchanged (`REUSE`, `LINKED`) |
| `·` | A read-only check |
| `✗` | Blocked: nothing in the plan can be applied until it is fixed |
| `!` | A warning, or a link left unchecked |
| `–` | Skipped |

The approval view leaves out role assignments and role checks that are
healthy. A link row says which identity it uses instead, for example
`LINK · IoT Hub system-assigned managed identity`. The engine still checks and
grants every role a link needs. `--plan-only` JSON, saved configurations,
scripts and receipts keep every role item. A role item that is blocked, a
warning or manual stays in view as a `Roles:` row with its message. Its `◇`
rows name each identity, role and scope, so the problem can be acted on.

Managed identities are always named in full and say whose they are: the
**namespace outbound managed identity** (the namespace's identity that calls
DPS, IoT Hub and Device Update), and the **DPS**, **IoT Hub** or **Device
Update managed identity** of a linked resource, with its system- or
user-assigned type. Setup expands only the labels it or the engine generates.
Resource names, resource IDs and role-definition names are always shown
verbatim, even when they contain `MI`, `hub` or `dps`.

## One workspace

Everything above the active question is one workspace. It is redrawn in place
when you go back, change an answer, get an error, review the plan, return from
**Change:** or after the plan is re-read. Going back and forth many times does
not leave copies of the subscription, resource group or plan in scrollback.

- The workspace is redrawn by moving the cursor up over its own rows and
  erasing below them. Shell history above the command, the setup header and
  the terminal's scrollback are never cleared or rewritten.
- Notes such as `Namespace changed · connectivity and capabilities are asked
  again.` appear once under the workspace. They clear when the next answer is
  accepted or a new plan is read.
- An error that belongs to one answer (a missing resource group, an unusable
  name, a lookup failure) is shown on that question, under your input. The
  input is kept so you can correct it.
- Approval, a finished `--plan-only` plan, the apply progress and the result are
  permanent. They stay in scrollback exactly as shown.

## Questions

Setup asks only what is still unresolved, in this order:

1. **Subscription** is shown, never asked. It is the CLI's selected
   subscription, or `--subscription`. Setup never switches it.
2. **Resource group:** pick from the list or type a name. A missing resource
   group is reported and asked again; setup does not create resource groups.
3. **Namespace:** pick an existing namespace in the resource group or type a new
   name. A new namespace shows `NEW` and its region (`--location`, otherwise the
   resource group's region). An existing namespace shows `REUSE`, and each
   existing DPS, IoT Hub or Software Updates link is shown as `LINKED`.
4. **Connectivity:** asked only for the halves that are not already linked.
   - **New DPS and IoT Hub** is the default. Names come from the namespace
     (`<namespace>-dps`, `<namespace>-hub`). It is followed by
     **IoT Hub tier:** (see [Tiers](#tiers)) and then the **IoT Hubs:**
     manager, where you can add more (see [Several IoT Hubs](#several-iot-hubs)).
     A fresh setup proposes one IoT Hub.
   - **Existing DPS and IoT Hubs** opens the DPS picker, then an IoT Hub picker
     where Space selects several. You can also type a name in the resource group
     or a full ARM resource ID. Each resource is checked as soon as you press
     Enter (see
     [Existing resources are checked immediately](#existing-resources-are-checked-immediately)).
   - **Namespace only** links nothing now. Links can be added later with
     `--dps` or `--hub`.

   If only one half is linked, only the other half is offered (for example
   **New IoT Hub** or **Skip IoT Hub**). It is never added silently. Esc at
   **IoT Hub tier:** returns to **Connectivity:**.
5. **Software updates:** `y/N`. Yes creates a Device Update instance named
   `<namespace>-su` and links it.
6. **CMS:** `y/N`. Yes configures Azure-managed certificate management (root
   and intermediate CA and a 30-day certificate policy).

Enter accepts the shown default. A `NEW` choice is only a proposal until you
approve the plan.

### Tiers

Setup offers only the tiers that the setup engine accepts for a resource it
creates and that can be linked to Azure Device Registry:

| Resource | Offered | Why |
| --- | --- | --- |
| New IoT Hub | **S1** (default), **S2**, **S3**, Standard tier | Hub creation validates S1, S2 and S3 only. Link preflight requires a Standard (S) tier hub, so Free (F1) and Basic (B1–B3) are not offered. |
| New DPS | **S1**, shown and never asked | S1 is the only DPS tier the engine creates. |
| Existing DPS or IoT Hub | Not asked | Its tier is shown for information. Setup never sends a tier or unit for an existing resource, so it never resizes one. |

The tier list shows daily message quotas per unit: S1 400,000, S2 6,000,000,
S3 300,000,000. Guided setup creates every new IoT Hub with **1 unit**. For more
units, use the explicit argument (`--hub resource-name=<hub> create-if-missing=true
identity=system-assigned sku=S2 unit=4`) or `"unit"` in a configuration file.
Azure validates the unit count. Each new IoT Hub has its own tier. The chosen
tier is kept when you go back or reopen that IoT Hub.
It is also kept in the plan, in **Save configuration**, in
**Repeat without prompts** (`sku=S2 unit=1`) and in the creation request.

### Existing resources are checked immediately

When you pick or type an existing DPS or IoT Hub, setup reads it before moving
on. The activity line shows `Checking IoT Hub <name>`. Setup uses the same lookup and
link checks that the plan uses, including the same-region check when the
namespace region is known. If the check passes, the answer row shows the
resource's region and SKU, and its state when it is not `Succeeded`.

The picker lists every resource group of the namespace's subscription, but only
resources in the namespace's region, because a linked DPS or IoT Hub must be in
the same region as its namespace. Its one-line caption says so:
`3 IoT Hubs in eastus · Contoso Dev · all resource groups · 1 in other regions
not shown · type to filter, or a resource ID`. While you search, it reads
`1 of 3 match`, or `No IoT Hub in eastus matches · enter checks what you
typed`. A typed resource ID from another region is not filtered out. It gets
the real check and its reason. A long caption wraps, and the prompt reserves
exactly the rows it needs. With
nothing chosen yet, focus starts on the first resource. When you reopen the
picker, your previous choice is highlighted if it is in the list (names and
resource IDs match in any case). If it isn't, for example a resource ID in another
resource group or subscription, nothing is highlighted, and Enter keeps that
choice instead of taking the first row. Each row shows the resource's resource group and tier, and its
state when it is not `Succeeded`. An IoT Hub on a tier that can't link is marked
`B1: not a Standard tier`. It can still be picked, and the immediate check
then says it can't be linked. When the list is longer than six rows, a footer says
`↑↓ for more`.

If the check fails, the question stays open with your input and shows the
reason:

| Problem | Message |
| --- | --- |
| Not found | `IoT Hub 'name' was not found in rg-demo. Check the name, or go back and choose New.` (or `at that resource ID`) |
| 401 or 403 | `Access denied reading IoT Hub 'name' (403). Choose another, or ask for read access to it.` |
| Resource ID of another kind | `That isn't an IoT Hub resource ID. Type a name in rg-demo, or its full resource ID.` |
| Name with spaces or slashes | `'bad name' isn't an IoT Hub name: names have no spaces or slashes.` |
| Any other Azure or validation error | `IoT Hub 'name' can't be linked: <first line of the error>` |

#### Another subscription

A DPS or IoT Hub can be in another resource group or another subscription of
the same Microsoft Entra directory. Managed identities can't reach across
directories, and new resources are always created in the namespace's
subscription. The last row of every existing-resource picker is
**Another subscription…** `now: Contoso Dev`. It is pinned under the list and
never filtered. Opening the picker, typing or a search without matches never
focuses it, so Enter keeps meaning "this resource". Reach it with ↑ from the
first row or ↓ past the last, then press Enter. Space on it marks nothing.

**Subscription:** lists the enabled subscriptions in the namespace's directory,
with the namespace's subscription first. Its caption says how many it doesn't
show: `2 subscriptions in this directory · 2 not shown: other directory or
disabled · type to filter`. Enter lists that subscription's resources in the
same picker, from all of its resource groups and in the namespace's region.
Setup reads them with that subscription for this one listing. It never changes
the namespace, its subscription or your CLI profile, and it never searches
every subscription by itself. Esc returns to the picker unchanged. If the
subscriptions can't be listed, the reason is shown, and a full resource ID can
still be typed.

Your search text and IoT Hub marks, with their count, travel with you both
ways. A marked IoT Hub from another subscription stays at the top of the list,
with its subscription named. Resource IDs match in any letter case, so a typed
ID of a listed Hub is that Hub, never a second copy.

Wherever a chosen resource is shown (its answer row, the IoT Hubs manager and
the plan), a resource outside the namespace's resource group says where it is:
`in rg-contoso-edge`, or `in rg-shared, Contoso Shared Services` for another
subscription. The scope rows at the top describe only the namespace. Saved
configurations and **Repeat without prompts** use full resource IDs.

A failed lookup is never treated as success. Changing the resource group,
namespace or connectivity clears a resource you chose before, so it is chosen
and checked again. The plan still re-validates everything before approval.

### Default resource rules

- New DPS and IoT Hub are proposed only in a guided setup where nothing about
  connectivity was supplied or already linked.
- Default names are lowercase, use hyphens, and stay within the IoT Hub (50)
  and DPS (64) name limits. Derived Software Updates names are kept to 24
  characters as a conservative choice, not a service rule. They always end with
  `-dps`, `-hub` or `-su`. A typed IoT Hub or DPS name is checked against the
  same name rules setup uses for creation. A typed Software Updates instance name
  only has to be non-empty, because the repository has no local rule for it.
  Availability is checked when the plan is read. A name
  that is taken comes back to its name question (DPS name, IoT Hub name or
  Software Updates **Instance name**) with the Azure error.
- Existing namespace links are always reused, exactly as they are: same
  endpoint, target and identity (system- or user-assigned). They are included in
  the plan so setup re-checks their link state and role access. A link in a
  failed state blocks the plan; setup never replaces or re-identifies a link.
  A link that Azure describes without a target or identity is shown as
  `WARNING · existing link` and left unchanged; use check to inspect it.
- Existing IoT Hub links are re-checked only when the namespace has a healthy
  DPS link or the plan adds one, which the engine requires before Hub linking.
  Without a DPS, they are left unchanged and marked
  `unchecked · needs a DPS link`, so CMS or Software Updates can still be set up.
  A new IoT Hub is still blocked until a DPS is linked.
- Because existing links are re-checked, an existing linked target that can't be
  read, is still updating, or is no longer valid can block the plan until it is
  healthy again. The plan states the reason. Fix it in Azure and re-read, or
  use the atomic link commands.
- A rerun of a finished setup creates nothing. If its links need a role check,
  the plan shows them as `REUSE` rows (with any role problem) and asks for
  approval. If nothing needs to change,
  setup reports **Up to date**, or **No changes** when plan items need
  attention.
- A new namespace that gets links is given a system-assigned outbound identity.
  An existing namespace keeps its outbound identity. If that identity can't be
  used for links, setup shows the reason and asks **Outbound identity:**. Esc opens
  Change, where you can re-read the plan after fixing the identity in Azure. Setup
  never replaces the identity automatically.
- A discovered resource is never picked for you. Existing resources are used
  only when you choose them or supply them.
- Explicit input is never reinterpreted. With `--config`, `--dps`, `--hub`,
  `--su` or `--complete`, setup asks only for a missing resource group or
  namespace and plans exactly what was supplied. An explicit configuration with
  empty `links` stays namespace-only.
- `--yes`, `--no-input` and runs without a terminal never prompt and never
  propose resources.

### Several IoT Hubs

Guided setup links **up to 10 IoT Hubs** to a namespace, together with one DPS.
After the first IoT Hub, the **IoT Hubs:** manager lists what this setup will
link, with a count such as `3 of 10`:

```text
┃ ? IoT Hubs:          3 of 10
┃   ❯ adr-demo-hub           NEW  S1 · 1 unit
┃     line-2-hub             NEW  S3 · 1 unit
┃     plant-hub              REUSE  eastus · S1
┃     Add new IoT Hub        adr-demo-hub-2 · tier next
┃     Add existing IoT Hubs  in rg-demo or by ID · space selects several
┃     Continue               2 new · 1 existing
┃   ↑↓ choose · enter accept · esc back
```

- **Add new IoT Hub** asks for a name (the next free `<namespace>-hub-N` is
  proposed) and its tier.
- **Add existing IoT Hubs** opens the IoT Hub picker. Type to filter, press
  **Space** on each IoT Hub you want (a `✓` marks it, and the search clears for
  the next one), then press **Enter** to check them all. Space on a `✓` row
  unmarks it. A name or resource ID that isn't listed can be typed and marked
  with Space too. With an empty field (or only a search in it), Enter checks
  exactly the marked IoT Hubs; moving the pointer never adds one. If the field
  holds an IoT Hub that isn't marked yet, Enter doesn't drop it or add it on its
  own: it says `Space adds <name>`. With nothing marked, Enter takes the
  focused row or the typed text, as in any picker.
- If one IoT Hub fails its check, it is put back in the field with the reason,
  and the others stay marked. Correct it and press Space, then Enter; or clear
  the field (Ctrl+U) and press Enter to continue without it.
- **Enter on an IoT Hub row** opens it: **Change name and tier** (new) or
  **Choose another** (existing), and **Remove from setup**. Removing only takes
  it out of this setup; nothing in Azure is deleted or unlinked.
- **Continue** keeps the list. **Esc** leaves the manager and discards every
  change made in it since it was opened.

IoT Hubs that are already linked to the namespace are not listed as rows. They
always stay linked and count toward the 10. At 10, both Add rows say
`none left of 10`, and choosing one explains the limit. If a namespace already
has more than 10 linked IoT Hubs, all of them are kept and re-checked; guided
setup adds no more. The same IoT Hub can't be chosen twice, whether by name or
by resource ID, in any letter case. An endpoint name that is already used by
this setup or by a link on the namespace is refused at once, with the same
uniqueness rule the plan uses (endpoint names are unique across DPS, IoT Hub and
Software Updates links).

Every chosen IoT Hub is planned, saved by **Save configuration**, listed in
**Repeat without prompts** and applied. A plan problem about one IoT Hub opens
that IoT Hub in the manager. Changing the resource group or namespace clears the
chosen IoT Hubs, because they belong to the old scope.

The limit of 10 belongs to guided setup only. Explicit arguments and
configuration files are unchanged: repeat `--hub` (or list `links.hubs`) once
per IoT Hub. Each `--dps` and `--hub` needs `identity=system-assigned`. For a new
DPS and two new IoT Hubs:

```bash
az iot adr ns setup -n adr-multiple -g rg-demo \
  --dps resource-name=adr-multiple-dps create-if-missing=true identity=system-assigned \
  --hub resource-name=adr-multiple-hub-a create-if-missing=true identity=system-assigned sku=S1 \
  --hub resource-name=adr-multiple-hub-b create-if-missing=true identity=system-assigned sku=S2 \
  --namespace-outbound-identity system-assigned
```

To reuse existing resources, leave out `create-if-missing` and `sku`.

## Keys

| Where | Keys |
| --- | --- |
| Name lists | ↑ ↓ (or Ctrl+P / Ctrl+N) move · type to filter · Tab completes the highlighted name · Enter accepts |
| Choices (Connectivity, IoT Hubs, Change) | ↑ ↓ move · Enter accepts · 1–9 pick a numbered choice |
| Existing IoT Hubs picker | As name lists, plus Space marks or unmarks the focused IoT Hub (or the typed name or ID) · Enter checks the marked ones |
| Existing-resource pickers | ↑ from the first row (or ↓ past the last) reaches **Another subscription…** · Enter opens it with your search and marks kept |
| Text | Normal line editing · Enter accepts · Enter on an empty line accepts the shown default |
| `y/N` | `y` or `n` answers immediately · Enter accepts the default |
| Anywhere | Esc goes back one question (at the approval, Esc opens Change; in Change, Esc reads Azure again and returns to approval) · Ctrl+C cancels · Ctrl+D on an empty line cancels |

The active question has a focus rail: an accent `┃` down the left edge of every
row it uses, in the column that answered rows leave blank, so nothing moves or
wraps differently. Its `?` and label are bold accent, and the typed input is
bold. Answered questions are quiet: a check mark, a muted label and the value in
bold normal ink, never dim. Every list uses the same focus: the highlighted row
has a bold accent `❯` pointer and a bold accent name, and its details are shown
at full strength. When the terminal reports its background color, the
highlighted row also gets a faint wash, one width for every row of the list,
from the cell before the pointer to just past the longest row. On the wash,
the name is bold in the terminal's own foreground, and the pointer, matched
text, check marks and tags keep their colors adjusted to at least 4.5:1
contrast. With motion on, the wash fades in over one short step (half
strength, then full strength 60 ms later) and then stays still. Other rows keep
normal ink and no background. There is no box, reverse video or underline. A
list shows at most six rows around the highlight. Filtering matches anywhere in the name; names that start with
the typed text come first, and the matched text is bold magenta. A filter with
no matches shows no empty rows. At **Namespace:**, a name that is not in the list is
offered as `NEW`. A resource that cannot be listed (for example, when listing
is denied) can still be typed exactly.

## Review, change and approval

The plan lists every new, reused, updated and linked resource and the outbound
identity. Healthy role assignments and checks run without being listed (see
above). Nothing is written before approval.

- **Approve:** type the namespace name exactly and press Enter.
- **Esc** opens **Change:**, a single list of the answers you can change:
  - resource group and namespace
  - **DPS** with its current choice, for example `new · adr-demo-dps · S1 · 1 unit`,
    `existing · shared-dps` or `none · link later`
  - **IoT Hubs**, for example `2 new · 1 existing`, which opens the same
    [IoT Hubs manager](#several-iot-hubs)
  - **Software updates** (`yes · new adr-demo-su` or `no`) and CMS
  - region and tags (new namespace only)
  - **Outbound identity**

  The DPS row is shown for a guided setup when no DPS is linked yet. It opens one
  editor: first **New**, **Existing** or **None**, then the name or the
  existing-resource picker. The IoT Hubs row is shown for every guided setup
  and opens the manager, where IoT Hubs can be added beside linked ones. Esc
  steps back inside an editor, and Esc at its first step (or in the manager)
  returns to **Change:** without changing anything. DPS and IoT Hubs are edited
  independently, so you can mix a new DPS with existing IoT Hubs.
  **Software updates** asks `y/N` and then the instance name.
  A plan error about a resource opens its editor at the step that can fix it,
  with the error shown and your previous value filled in. For example, a name
  that is taken opens the name question, and a tier conflict with an existing
  hub of the same name opens that IoT Hub's name and tier in the manager. With
  several IoT Hubs, the problem opens the one it is about.

  **Change:** stays open while you work in it. Finishing an editor, Esc out of
  an editor and **Save configuration** all return to **Change:**, with focus on
  the row you used. You can make several changes in one visit. The workspace
  shows your answers, updated after each edit, in place of the plan.

  Its first row is **Back to approval** `reads Azure again for a fresh plan`.
  A blocked plan shows **Re-read plan** `reads Azure again` instead. Choosing
  that row, or pressing Esc in **Change:** itself, always reads Azure again and
  shows a fresh plan for approval. It does so even when nothing was changed or
  an editor was cancelled, so you approve what Azure holds now. **Change:** also
  offers **Save configuration** and **Cancel setup**.
- Changing the resource group or namespace clears the answers that depend on
  it (connectivity, capabilities, and any region or tags you set during setup)
  and says so. A region and tags supplied as arguments are kept.
- **Save configuration** writes the equivalent strict JSON to a *new* file and
  never overwrites one. It notes the path and
  `az iot adr ns setup --config @<file>` for automation.
- **Ctrl+C** before approval writes nothing:
  `Cancelled · nothing was written to Azure.`

After approval, setup reads Azure again and compares the plan with the one you
approved. If anything changed, the new plan replaces the old one in the
workspace with a note, and must be approved again. If that re-read fails,
nothing is applied: the error is noted and approval is asked again. Fingerprint
and generation checks from the engine still apply.

`--plan-only` stops after the plan and writes nothing. With `--output-script`,
it also writes the planned commands. Without `--plan-only`, the script is
rendered and its destination checked before approval is asked. The file is
written after approval and the re-read, before anything is applied. A plan
that can't be scripted (for example, one that creates a Software Updates
instance) is reported before approval, and you can change an answer or cancel.

## Applying, results and recovery

```text
  Applying · Ctrl+C stops before the next Azure request
  ✓ Create namespace
  ⠹ Link IoT Hub main  12s
```

Progress lists the Azure operations that were actually observed. Only changes
stay in scrollback; reads are shown transiently. The activity line and elapsed time
appear only while a request is in flight, and there is no percentage or ETA.

- The first **Ctrl+C** stops before the next request. The current request may
  still finish in Azure.
- A second **Ctrl+C** stops watching. The result then says which request may
  still complete.
- Nothing is rolled back. A rerun re-reads Azure and resumes.

The result is **Done**, **Done** with warnings (each warning is listed),
**Stopped**, **Failed**, or **Blocked** (finished with blockers), with the
number of changes completed. After approval, a Ctrl+C while setup is finishing
can only shorten the output. The result still reports what was applied, and
the receipt is written at most once. It is followed by the receipt
path and the read-only check command. Submitted link requests are reported as
submitted, not as ready. When the answers are reproducible as arguments, setup
also prints **Repeat without prompts**: the equivalent `az iot adr ns setup …
--yes` command. When CMS is enabled, use **Save configuration** and
`--config` instead.

## Plain terminals and automation

| Situation | Behaviour |
| --- | --- |
| Terminal (stdin and stderr) | Guided prompts. `-o json` and `--plan-only` still work; the UI is on stderr and stdout carries only the result. |
| `--plain` in a terminal | The same questions as numbered plain-text prompts. Type a number or a name; `[default]` is accepted with Enter; `:back` or `:edit` goes back; `:quit` cancels. |
| `--no-input`, `--yes`, or no terminal | Never prompts. Plans exactly the supplied arguments or configuration and applies only with `--yes`. |

```bash
# Read-only configuration validation and plan.
az iot adr ns setup --config @plant-a.json --no-input --plan-only

# Explicit approval for unattended execution.
az iot adr ns setup --config @plant-a.json --yes

# Independent, read-only verification after onboarding (no prompts).
az iot adr ns check -n plant-a -g devices-rg
```

See [the configuration schema](adr-setup-config.md) for configuration files.

## Motion and color

Setup colors text. It never uses reverse video or underline, never dims
selected or essential text, and never guesses the background or assumes a
dark terminal. It picks the palette from the color depth the terminal reports:

- **Terminal palette**, used with 16 colors or when the depth is unknown.
  Accents are the terminal's own ANSI colors: blue labels, green `NEW`, cyan
  `REUSE`, magenta `LINK`, yellow `ROLE`, red errors. The terminal's theme
  already tunes these for its background.
- **Slate palette**, used at 256 colors (`TERM=xterm-256color` without
  `COLORTERM`) and with 24-bit color (`COLORTERM=truecolor` or `24bit`). It uses
  Azure blue `#2f81c9` for labels and matches, jade `#1f8e6e` for `NEW`, slate
  teal `#5c8390` for `REUSE`, indigo `#6f74d0` for links, ochre `#a8741c` for
  roles and warnings, and coral red `#d64f58` for errors. The colors share
  one lightness and differ in hue. That keeps them cohesive and readable on light
  and dark backgrounds alike: at least 4:1 contrast on white, black, `#1e1e1e`
  and Windows Terminal's `#0c0c0c`, and at least 3.3:1 on One Dark, Solarized dark
  and light, light gray and Ubuntu's aubergine. At 256 colors, each color is
  sent as its nearest xterm entry (for example jade becomes color 29). Those
  entries keep at least 3:1 contrast on the same backgrounds, and no 24-bit
  codes are sent.

### The terminal's background

The two washes (the focused list row and the plan surface) are drawn only when
setup knows the background. Before its first line, an interactive run asks the
terminal once, with the standard background-color query (OSC 11) followed by a
device-attributes query (DA1), which every terminal answers, in order:

- It asks only when stdin and stderr are the same terminal, colors are on
  (no `NO_COLOR`, `--plain` or `TERM=dumb`), the depth is 256 or 24-bit, and the
  platform has POSIX terminal control. Windows consoles are not asked.
- It waits at most 0.5 seconds. Terminals answer within milliseconds, and the
  DA1 answer ends the wait at once when no color is coming.
- Keys you type meanwhile are kept, in order, and become the first prompt's
  input. Nothing is echoed, flushed or dropped.
- An answer that arrives later, even split across reads, is removed from the
  keys every prompt reads, so it never becomes text in a field and never acts
  as Esc. While an answer is still due, a prompt waits 0.3 seconds (instead of
  0.05) after an Esc to tell your Esc from the start of an answer; your Esc
  still goes back. Echo stays off between prompts until that answer arrives.
- When setup ends, it only restores the terminal's settings. It never reads,
  drops or re-inserts keys: anything typed after the last prompt stays in the
  terminal for the shell. If the terminal disconnects, there is nothing to
  restore and setup ends normally; any other terminal error is reported.
- If the question itself fails (it can't be written, a read fails, or Ctrl+C
  arrives while waiting), the terminal's own settings, echo included, come back
  at once, before the error or the cancel is reported. From the question on,
  everything up to the end of the run, including starting the first prompt,
  sits inside the same restore.
- Without an answer, or with an answer setup can't read, nothing is painted:
  the focus is the pointer and bold, and the plan stands on the terminal's own
  background.

From the reported color, setup derives the washes: the surface is lifted
toward white on a dark background (6%) or lowered toward black on a light one
(3.5%), with a 4% lean toward the accent; the focus wash leans further toward
the accent. Each wash must differ from the background by a contrast between
1.05:1 (visible) and 1.4:1 (never loud), or none is drawn; a mid-gray
background therefore gets none. At 256 colors, each wash is the nearest xterm
entry within those limits that is not the background's own. Colored text on a
wash is moved toward the foreground side, in its own hue (or to the nearest
xterm entry at 256 colors), until it has at least 4.5:1 contrast with the wash
and, for the focus, with the background it fades in from. Bold values stay in
the terminal's own foreground.

### Effects

Effects are small and appear only during real work:

- The title `Azure Device Registry` is a bold gradient when color is on. At 256
  and 24-bit color it runs teal `#119994` → azure `#2f81c9` → violet `#945bd6` →
  rose `#ca478d`. That hue range is wide enough to see across a short title,
  and each step stays at least 3:1 against the background. In the terminal
  palette, it steps through cyan, blue and magenta. Otherwise it is plain bold.
- Setup has one animation, used for every wait on Azure: listing subscriptions
  and resources, checking resources, reading and re-reading the plan, and
  applying it. It is a bold Braille spinner (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) in the mark column
  at the start of the activity line, the same glyph and style from the very
  first frame: `  ⠋ Getting your plan ready`. The glyph advances every 80 ms,
  and its color glides along the wordmark gradient and back over 2.4 seconds.
  The text never moves; after one second, the elapsed seconds follow it
  (`  ⠴ Checking IoT Hub hub-a  4s`). There is no bar, percentage or ETA,
  because Azure doesn't report progress for these operations; the spinner only
  means "still working". It stops, and its line is erased, as soon as the
  operation returns. While setup waits at a prompt, nothing animates and no
  timer runs.
- Reading the plan, first and after **Change:**, says
  `Getting your plan ready`. The read just before applying says
  `Re-reading Azure before applying`.

Motion is off with `--plain`, when stderr is not a terminal, with `NO_COLOR`,
with `TERM=dumb`, and with `TEXTUAL_ANIMATIONS=none`. In those cases each wait
in a repainting terminal is one still line with a single still glyph,
`  ⠿ Checking IoT Hub hub-a`, written once and left unchanged until it is
erased. No timer ticks, and the focus wash appears at full strength without
fading. `--plain` prints ordinary operation messages, such as
`Getting your plan ready…`, without repainting or erasing them.

## Terminal notes

- Prompts redraw only their own few lines and erase themselves when answered.
  The workspace above them is redrawn in place.
- A plan taller than the terminal can scroll its top rows out of view. Those
  rows are reused while they are unchanged. If they change, the new workspace
  is drawn below the rows still visible, so a stale copy of the old top rows
  can remain in scrollback.
- After the terminal is resized, the next update draws the workspace below the
  old one instead of over it, because the terminal may have re-wrapped the old
  rows.
- With `--plain`, `TERM=dumb`, or stderr that is not a terminal, nothing is
  redrawn. Only rows that changed are printed again, below the earlier ones.
- On Windows consoles, keystrokes typed while changes are applied may echo.
- Setup does not need a particular font. The design previews use JetBrains Mono.
