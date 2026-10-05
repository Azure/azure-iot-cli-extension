# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help updates for CLI core commands.
"""

from knack.help_files import helps


def patch_core_help():

    # add DPS create example for local authentication
    if "iot dps create" in helps:
        helps[
            "iot dps create"
        ] += """
  - name: Create an Azure IoT Hub Device Provisioning Service with SAS key (local) authentication disabled, requiring Azure RBAC
    text: >
        az iot dps create --name MyDps --resource-group MyResourceGroup --disable-local-auth
"""

    # add DPS update example for local authentication
    if "iot dps update" in helps:
        helps[
            "iot dps update"
        ] += """
  - name: Disable SAS key (local) authentication on an existing Device Provisioning Service, requiring Azure RBAC
    text: >
        az iot dps update --name MyDps --resource-group MyResourceGroup --disable-local-auth
"""
