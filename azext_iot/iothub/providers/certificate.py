# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from typing import Dict, Optional
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.digitaltwins.common import ABORT_MSG
from azext_iot.iothub.common import (
    CA_REVERT_WARNING,
    CA_TRANSITION_API_VERSION,
    CA_TRANSITION_WARNING,
    CONT_INPUT_MSG,
    DEFAULT_ROOT_AUTHORITY,
    HUB_PROVIDER,
    NO_CHANGE_MSG,
    CertificateAuthorityVersions
)
from azext_iot.iothub.providers.base import IoTHubProvider
from azure.cli.core.azclierror import ManualInterrupt
from knack.log import get_logger
from knack.prompting import prompt_y_n


logger = get_logger(__name__)


class CertificateProvider(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: str,
        rg: Optional[str] = None,
    ):
        super(CertificateProvider, self).__init__(
            cmd=cmd, hub_name=hub_name, rg=rg
        )
        self.cli = EmbeddedCLI()
        if self.target.get("resourcegroup") is None:
            resource = self.discovery.find_resource(hub_name)
            self.target["resourcegroup"] = resource.additional_properties.get("resourcegroup")

    def iot_hub_certificate_root_authority_show(self) -> Optional[Dict[str, str]]:
        # Since a newly created IoT Hub has empty rootCertificate property
        return self._get_target_properties().get("rootCertificate") or DEFAULT_ROOT_AUTHORITY

    def iot_hub_certificate_root_authority_set(
        self,
        ca_version: str,
        yes: bool = False
    ) -> Optional[Dict[str, str]]:
        properties = self._get_target_properties()
        current_target = properties.get("rootCertificate")
        root_ca = current_target and current_target.get("enableRootCertificateV2")

        # Check if changes are needed
        if ca_version == CertificateAuthorityVersions.v1.value and root_ca:
            logger.warning(CA_REVERT_WARNING)
            if not yes and not prompt_y_n(msg=CONT_INPUT_MSG, default="n"):
                raise ManualInterrupt(ABORT_MSG)
        elif ca_version == CertificateAuthorityVersions.v2.value and not root_ca:
            logger.warning(CA_TRANSITION_WARNING)
            if not yes and not prompt_y_n(msg=CONT_INPUT_MSG, default="n"):
                raise ManualInterrupt(ABORT_MSG)
        else:
            logger.warning(NO_CHANGE_MSG.format(ca_version))
            return

        command = "resource update -n {} -g {} --api-version {} --resource-type {}".format(
            self.target["name"],
            self.target["resourcegroup"],
            CA_TRANSITION_API_VERSION,
            HUB_PROVIDER
        )

        if root_ca is None:
            properties["rootCertificate"] = {"enableRootCertificateV2": not root_ca}
            dumped = json.dumps(properties).replace('"', '\\"')
            command += f" --set properties=\"{dumped}\""
        else:
            command += f" --set properties.rootCertificate.enableRootCertificateV2={not root_ca}"

        result = self.cli.invoke(command)
        if not result.success():
            return
        return result.as_json()["properties"].get("rootCertificate")

    def _get_target_properties(self) -> Optional[Dict[str, str]]:
        result = self.cli.invoke(
            "resource show -n {} -g {} --api-version {} --resource-type {}".format(
                self.target["name"],
                self.target['resourcegroup'],
                CA_TRANSITION_API_VERSION,
                HUB_PROVIDER
            )
        )
        if not result.success():
            # Error will already be printed out
            return
        return result.as_json()["properties"]
