# Minimal namespace setup

Run `az iot adr ns setup` in an interactive terminal. The four steps are
**Namespace**, **Connectivity**, **Capabilities**, and **Review**. Click controls
or use Tab, arrow keys, Space, and Enter. The terminal supplies the font; select
JetBrains Mono in your terminal settings to match the design preview.

Setup owns onboarding, `az iot adr ns check` provides read-only diagnostics, and
the separate namespace UI provides resource browsing and CRUD.

## Onboarding

1. Name a new namespace or browse existing namespaces in a resource group.
   Region, tags, and outbound identity are under **More options**.
2. Use existing DPS/Hub resources, explicitly create a new DPS and 1, 2, or 4
   Hubs, or skip connectivity. New Hubs default to S1 with one unit; they retain
   the release command's local-auth-disabled default.
3. Optionally enable Software Updates or **Azure-managed** certificate
   management. Certificate management creates or reuses a compatible root CA,
   intermediate CA, and device certificate policy. External PKI is deliberately
   outside setup; use the individual CA commands or the portal for that workflow.
4. Review resource and role-assignment changes. Expand role details or commands
   only when needed. Type the namespace name, then choose **Create / apply**.

Review performs reads, not writes. Setup rereads Azure immediately before
applying. If the plan has changed, it returns to review and requires fresh
approval. A blocked plan cannot be applied.

## Start at review from JSON

```bash
az iot adr ns setup --config @plant-a.json --subscription <subscription-id>
```

See [the configuration schema](adr-setup-config.md) for complete examples.
Use one file per namespace. Invalid syntax, unknown fields, incompatible values,
and a subscription mismatch fail explicitly; they do not silently select a
different setup. Only documented omitted optional values receive defaults.

Valid input skips directly to review. Use **Back** to edit normal fields or
**Edit full JSON configuration** for advanced settings. Editing JSON invalidates
approval until **Validate and review** succeeds. **Save config** writes to a new
file and never overwrites an existing one.

## Interaction and recovery

| Key or button | Action |
| --- | --- |
| Esc / Back | Return to the previous input step |
| Ctrl+Enter / Continue | Advance; at review, apply only after typed approval |
| Ctrl+S / Save config | Save configuration to the entered new file path |
| Ctrl+R / Re-check or Retry | Reread Azure and review again |
| Ctrl+X / Stop watching | Stop before the next workflow operation |
| Ctrl+Q / Close | Close when idle; request a stop when busy |

The UI uses one accent, a literal change plan, a bounded operation log, and an
elapsed-time spinner only while work is active. It does not invent percentages
or completion times. Animation never triggers API polling.

Stop does **not** cancel an already-submitted Azure request. The current call
may finish before setup stops; completed changes are not rolled back. After a
failure or stop, reread the plan before retrying. Setup retains compatible
resources that already exist.

## Plain terminals and automation

`--plain` retains the line-oriented experience. `--no-input`, redirected output,
explicit structured output, `--plan-only`, and `--yes` avoid the full-screen UI.

```bash
# Read-only configuration validation and plan.
az iot adr ns setup --config @plant-a.json --no-input --plan-only

# Explicit approval for unattended execution.
az iot adr ns setup --config @plant-a.json --no-input --yes

# Independent, read-only verification after onboarding.
az iot adr ns check -n plant-a -g devices-rg
```

No mouse support is required for any operation. Select a terminal at least 80
columns wide for the intended layout; longer forms and plans scroll vertically.
