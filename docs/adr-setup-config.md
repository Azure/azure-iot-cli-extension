# ADR namespace setup configuration

Setup accepts **one namespace per configuration**. Use a JSON object string, a
JSON file path, or `@path`. Legacy `.yaml` / `.yml` files remain supported.
Configuration is validated before setup plans or writes resources. Interactive
setup can review and edit it; automation uses the same engine without prompts.

For interactive navigation and review, see the [ADR setup UI guide](adr-setup-ui.md).

```sh
az iot adr ns setup --subscription 00000000-0000-0000-0000-000000000000 \
  --config @namespace.json --no-input --plan-only

# Apply only after reviewing the current plan:
az iot adr ns setup --subscription 00000000-0000-0000-0000-000000000000 \
  --config @namespace.json --no-input --yes
```

## Minimal JSON

No identity, connectivity link, or certificate capability is mandatory:

```json
{
  "schemaVersion": 1,
  "namespace": {
    "name": "my-registry",
    "resourceGroup": "my-resource-group"
  }
}
```

The resource group must already exist. Namespace creation uses its region unless
`namespace.location` is provided. An existing namespace is reused. Setup does
not move it or silently replace its location. Tags apply only on namespace
creation; differing tags on reuse produce a warning, not an implicit update.

## Full example

Use globally available Hub/DPS names. The example creates missing targets, or
validates and reuses existing targets. Outbound and target identities have
different responsibilities; selecting a namespace identity does not implicitly
select a target's identity.

```json
{
  "schemaVersion": 1,
  "subscriptionId": "00000000-0000-0000-0000-000000000000",
  "namespace": {
    "name": "my-registry",
    "resourceGroup": "my-resource-group",
    "location": "eastus",
    "tags": {"owner": "device-team"},
    "outboundIdentity": {"type": "SystemAssigned"}
  },
  "links": {
    "dps": {
      "resourceName": "my-globally-unique-dps",
      "endpointName": "provisioning",
      "identity": "system-assigned",
      "createIfMissing": true,
      "sku": "S1",
      "unit": 1
    },
    "hubs": [
      {
        "resourceName": "my-globally-unique-hub",
        "endpointName": "messaging",
        "identity": {"type": "SystemAssigned"},
        "createIfMissing": true,
        "sku": "S1",
        "unit": 1,
        "availability": "Available",
        "allocationWeight": 100
      }
    ]
  },
  "cms": {
    "enabled": true,
    "rootName": "root",
    "intermediateName": "intermediate",
    "policyName": "default",
    "validityDays": 30
  },
  "checkStatus": true
}
```

## Schema and defaults

All keys are case-sensitive. Unknown keys are errors at every level.

| Object | Accepted fields |
| --- | --- |
| Root | `schemaVersion`, `subscriptionId`, `namespace`, `links`, `cms`, `checkStatus` |
| `namespace` | `name`, `resourceGroup`, `location`, `tags`, `outboundIdentity` |
| `links` | `dps` (object), `hubs` (array of objects), `softwareUpdates` (object) |
| Every endpoint | `resourceName` **or** `resourceId`, `endpointName`, `identity`, `createIfMissing`; name-selected targets may also have `resourceGroup`, `subscription` |
| Hub only | `availability` (`Available` or `Disabled`), `allocationWeight` (integer 1–1000) |
| Hub and DPS only | `sku`, `unit` (positive integer), requiring `createIfMissing: true` |
| `cms` | `enabled`, `rootName`, `intermediateName`, `policyName`, `validityDays` |

- `schemaVersion` defaults to integer `1`; other versions are rejected.
- `subscriptionId`, if present, must be a subscription UUID matching the selected
  CLI subscription. Use `--subscription` explicitly to select it. Setup never
  runs `az account set` or changes the global account.
- Namespace `name` and `resourceGroup` may be omitted while editing a partial
  interactive configuration. Both are required by the noninteractive builder.
- Tags are an object with string keys and values. Empty tag values are allowed.
- An endpoint requires exactly one target selector and an explicit identity.
  `resourceName` defaults to the namespace resource group and selected
  subscription. `resourceId` cannot be combined with `resourceName`,
  `resourceGroup`, or `subscription`.
- `endpointName` defaults to the target resource name. Endpoint names and target
  resource IDs must be unique across requested links.
- `createIfMissing` defaults to `false`. Missing targets without it are errors.
  Creation defaults are Standard `S1`, one unit. Supported Hub SKUs are `S1`,
  `S2`, `S3`; DPS supports `S1`. On existing targets explicitly supplied SKU/unit
  values are constraints, **not requests to update them**.
- `softwareUpdates` uses a `Microsoft.DeviceUpdate/updateInstances` ARM ID or
  resource name and the same identity/create-if-missing fields; it has no
  Hub/DPS SKU/unit fields.
- `checkStatus` defaults to `false`. When true it runs the existing read-only
  namespace diagnostics after apply. It does not add a CMS diagnostic scan.
- CMS is omitted/disabled by default. To enable, supply `{"enabled": true}`.
  Defaults are root `root`, ICA `intermediate`, policy `default`, and 30 days.
  Validity must be an integer **1–90** inclusive. Root and ICA names must differ.
  Disable with `false` or `{"enabled": false}`. Disabled CMS cannot include
  names or validity options; doing so is an error, not a silently ignored choice.

Identity values accept `"system-assigned"`, `"SystemAssigned"`,
`{"type": "SystemAssigned"}`, a complete UAMI ARM ID, or:

```json
{
  "type": "UserAssigned",
  "userAssignedResourceId": "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-resource-group/providers/Microsoft.ManagedIdentity/userAssignedIdentities/my-identity"
}
```

`userAssignedResourceId` without `type` is also accepted for compatibility.
System-assigned identity cannot include a UAMI ID. Existing target resources must
already have the selected managed identity attached and a resolvable principal.
New Hub/DPS resources receive the explicitly selected identity at creation.

## Errors and overrides

Configuration is copied and validated; callers' dictionaries are not mutated.
Duplicate JSON/YAML keys, unknown keys, wrong scalar/object types, wrong resource
types, malformed identities/ARM IDs, conflicting selectors, and incompatible
endpoint options are errors with a field path. JSON syntax errors include
line/column information. `assignRoles` is not supported and is never ignored.

Explicit CLI namespace name, resource group, location, or tags must agree with
the corresponding configuration value. Conflicts fail; neither source silently
overrides the other. Legacy capability flags cannot be combined with `--config`.

## Planning, reuse, permissions, and recovery

Planning is read-only. It checks existing targets, same-region linking,
provisioning state, Standard Hub SKU, identity prerequisites, and creation name
availability before any namespace or connectivity mutation. Creation in another
subscription is not supported by setup; create that target separately with its
atomic command and rerun setup to link it. Resource-ID reads use the target's
subscription. Target resource groups must exist. Region-specific creation
options not exposed in this simple schema (for example Qatar Hub data residency)
must be configured with the atomic command first.

Hub/DPS writes use the release core create functions and scoped factories,
preserving release defaults, including Hub `disableLocalAuth: true`.
Existing targets are reused, never intentionally PUT or overwritten by setup.
Plans show concrete, subscription-pinned commands. Do not use exported create
commands as an unconditional upsert script: rerun setup to recompute reuse.
Concurrent resource changes can invalidate a plan; do not run competing setup
processes against the same namespace or target.

Link role assignments remain owned by the atomic link providers and their
central role matrix. A reused link can still need role repair. Consequently a
plan's `roles-*` item is `action: role`, `state: Planned`, with
`roleValidation: pending`, required role descriptions, and principal/scope details
where known. It is **not** a zero-write promise. Caller role-assignment permission
may be required. Pending links are awaited, not re-added. Failed/conflicting
links block setup with guidance to inspect and use atomic recovery/update.

CMS supports **Azure-managed certificates only**:

1. Root CA.
2. ICA with issuer type `Microsoft`, pointing to that root in the same namespace.
3. Certificate policy under that ICA with matching validity.

Setup reads the desired names and validates the entire existing chain before
other writes. Type, issuer, validity, or readiness conflicts block setup instead
of replacing resources. An external ICA is never converted. The underlying
atomic external-PKI commands remain available and unchanged, but are not a
setup capability. CMS adds no service-role grants; the caller still needs ARM
read/create permissions for these resources.

CMS reads and write results expose only allowlisted metadata to the workflow,
not certificates, CSRs, or chains. Policy creation follows confirmed CA
readiness. Unknown, failed, or in-progress resources are refused with guidance
to inspect/wait and rerun; setup never blindly replays them. It does not revoke,
rotate, activate external CAs, or automatically roll back. Partial execution
errors retain the successful-step result; retries re-read and reuse completed
resources. Review the refreshed plan before confirming again.

## Engine/UI interface

`configuration.load_config(value)` accepts a dictionary, JSON object string, or
path and returns a validated detached dictionary. `{"namespace": {}}` is valid
for an unfinished interactive form.

`configuration.request_config(request)` exports a legacy `SetupRequest` to the
same schema for deterministic TUI prefill. UI-only skipped rows have no desired
resource effect and are not exported. The final form calls:

```python
request = build_setup_request(
    namespace_name=None,
    resource_group_name=None,
    subscription_id=selected_subscription,
    config=configuration,
    interactive=False,
    no_input=True,
)
```

Compute a fresh plan and compare it with the confirmed plan before apply.
`NamespaceWorkflow.setup` also plans again before mutation. CMS progress uses
the existing `run(..., mutation=True, workflow_scope="cms")` adapter.
