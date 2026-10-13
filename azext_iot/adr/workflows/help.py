# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.help_files import helps


def load_adr_workflow_help():
    helps[
        "iot adr ns check"
    ] = """
  type: command
  short-summary: Check namespace connectivity readiness.
  long-summary: |
    Read the namespace, configured endpoint links, linked resources, identities, and
    scoped role assignments for the specified namespace. Supply --name and
    --resource-group; a configured default resource group is also accepted.
    Check never prompts, opens an interactive UI, or changes Azure resources.
    Findings are reported together. Successful and warning results support
    --output json. Blocked or failed checks exit nonzero and report diagnostics
    on stderr instead of returning a JSON result.
  examples:
    - name: Check a namespace
      text: az iot adr ns check -n factory-ns -g factory-rg
    - name: Return structured namespace diagnostics
      text: az iot adr ns check -n factory-ns -g factory-rg --output json
  """

    helps[
        "iot adr ns setup"
    ] = """
  type: command
  short-summary: Configure namespace identity and endpoint connectivity.
  long-summary: |
    Create or adopt a namespace, configure DPS, IoT Hub and Software Updates links,
    and optionally configure Azure-managed certificate management.
    In a terminal, setup is a guided command: it asks one question at a time
    below the command and keeps accepted answers in normal scrollback. Values
    already supplied by arguments, --config or CLI defaults are shown, not asked
    again. A new guided setup proposes one new DPS and one new IoT Hub named
    after the namespace; existing resources and a namespace-only setup can be
    chosen instead, and existing namespace links are always reused.
    The plan lists every new, reused and linked resource and role check before
    anything is written. Type the namespace name to approve it, or press Esc to
    change an answer. Use --plain for numbered prompts without color or motion.
    With --yes, --no-input or without a terminal, setup never prompts and never
    proposes resources: it plans exactly the supplied arguments or --config
    and applies only with --yes. Invalid --config input is reported without
    substituting defaults.
    The command plans from live state, skips satisfied work, and
    delegates each link to the atomic link command, which validates target
    readiness and creates missing service-to-service role assignments for an
    authorized caller before namespace mutation. Before applying, the plan is
    read again and any change is shown for approval.
    When link inputs omit --outbound-identity, the current namespace outbound
    identity is reused and never replaced implicitly.
    Namespace tags can be supplied with --tags key=value and are included in
    the review plan before a missing namespace is created.
  examples:
    - name: Preview DPS and Hub setup
      text: |
        az iot adr ns setup -n factory-ns -g factory-rg \\
          --outbound-identity system-assigned \\
          --dps endpoint=primary resource-id=/subscriptions/.../provisioningServices/factory-dps identity=system-assigned \\
          --hub endpoint=primary resource-id=/subscriptions/.../IotHubs/factory-hub identity=system-assigned \\
          --plan-only
    - name: Set up a namespace with guided prompts (proposes a new DPS and IoT Hub)
      text: az iot adr ns setup
    - name: Apply setup from a config file
      text: az iot adr ns setup -n factory-ns -g factory-rg --config setup.yaml --yes
    - name: Review a saved JSON configuration and approve it in the terminal
      text: az iot adr ns setup --config factory.json
    - name: Inspect a configuration without changing Azure resources
      text: az iot adr ns setup --config factory.json --plan-only --no-input
  """
