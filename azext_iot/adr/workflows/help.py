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
    scoped role assignments. Guided mode can browse accessible scope resources or
    accept exact names and ARM IDs. This command never changes Azure resources.
  examples:
    - name: Check a namespace
      text: az iot adr ns check -n factory-ns -g factory-rg
    - name: Enter namespace scope interactively
      text: az iot adr ns check
  """

    helps[
        "iot adr ns setup"
    ] = """
  type: command
  short-summary: Configure namespace identity and endpoint connectivity.
  long-summary: |
    Create or adopt a namespace and configure selected DPS, IoT Hub, or Software
    Updates links. The command plans from live state, skips satisfied work, and
    delegates each link to the atomic link command, which validates target
    readiness and creates missing service-to-service role assignments for an
    authorized caller before namespace mutation. The final typed confirmation
    covers every planned mutation.
    When link inputs omit --outbound-identity, the current namespace outbound
    identity is reused and never replaced implicitly.
    Namespace tags can be supplied with --tags key=value and are included in
    the review plan before a missing namespace is created.
    Guided prompts accept :back, :help, and :quit and retry invalid resources
    without exiting the command. Accessible resources can be browsed and filtered;
    when listing is denied, exact names and ARM IDs remain available.
  examples:
    - name: Preview DPS and Hub setup
      text: |
        az iot adr ns setup -n factory-ns -g factory-rg \\
          --outbound-identity system-assigned \\
          --dps endpoint=primary resource-id=/subscriptions/.../provisioningServices/factory-dps identity=system-assigned \\
          --hub endpoint=primary resource-id=/subscriptions/.../IotHubs/factory-hub identity=system-assigned \\
          --plan-only
    - name: Enter setup inputs interactively
      text: az iot adr ns setup
    - name: Apply setup from a config file
      text: az iot adr ns setup -n factory-ns -g factory-rg --config setup.yaml --yes
  """
