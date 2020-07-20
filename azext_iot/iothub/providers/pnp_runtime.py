# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from knack.log import get_logger
from knack.util import CLIError
from azext_iot.common.shared import SdkType
from azext_iot.common.utility import unpack_msrest_error, process_json_arg
from azext_iot.iothub.providers.base import (
    IoTHubProvider,
    CloudError,
)


logger = get_logger(__name__)


class PnPRuntimeProvider(IoTHubProvider):
    def __init__(self, cmd, hub_name=None, rg=None, login=None):
        super(PnPRuntimeProvider, self).__init__(
            cmd=cmd, hub_name=hub_name, rg=rg, login=login
        )
        self.runtime_sdk = self.get_sdk(SdkType.pnp_sdk).digital_twin

    def invoke_device_command(
        self,
        device_id,
        command_name,
        timeout=30,
        payload="{}",
        component_path=None,
        connect_timeout=None,
        response_timeout=None,
    ):

        # Prevent msrest locking up shell
        self.runtime_sdk.config.retry_policy.retries = 1

        try:
            if payload:
                payload = process_json_arg(payload, argument_name="payload")

            api_timeout_kwargs = {
                "connect_timeout_in_seconds": timeout,
                "response_timeout_in_seconds": timeout,
            }
            response = (
                self.runtime_sdk.invoke_component_command(
                    id=device_id,
                    command_name=command_name,
                    payload=payload,
                    timeout=timeout,
                    component_path=component_path,
                    raw=True,
                    **api_timeout_kwargs,
                ).response
                if component_path
                else self.runtime_sdk.invoke_root_level_command(
                    id=device_id,
                    command_name=command_name,
                    payload=payload,
                    timeout=timeout,
                    raw=True,
                    **api_timeout_kwargs,
                ).response
            )

            return {
                "payload": response.json(),
                "status": response.headers.get("x-ms-command-statuscode"),
            }

        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def get_digital_twin(self, device_id):
        return self.runtime_sdk.get_digital_twin(id=device_id, raw=True).response.json()

    def patch_digital_twin(self, device_id, json_patch):
        json_patch = process_json_arg(content=json_patch, argument_name="json-patch")

        json_patch_collection = []
        if isinstance(json_patch, dict):
            json_patch_collection.append(json_patch)
        if isinstance(json_patch, list):
            json_patch_collection.extend(json_patch)

        logger.info("Patch payload %s", json.dumps(json_patch_collection))

        try:
            # Currently no response text is returned from the update
            self.runtime_sdk.update_digital_twin(
                id=device_id, digital_twin_patch=json_patch_collection, if_match="*", raw=True
            ).response

            return self.get_digital_twin(device_id=device_id)
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))
