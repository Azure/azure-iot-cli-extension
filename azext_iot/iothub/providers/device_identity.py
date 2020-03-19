# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from knack.util import CLIError
from azext_iot.common.shared import SdkType
from azext_iot.common.utility import unpack_msrest_error
from azext_iot.iothub.providers.base import IoTHubProvider, CloudError


logger = get_logger(__name__)


class DeviceIdentityProvider(IoTHubProvider):
    def get_device_stats(self):
        service_sdk = self.get_sdk(SdkType.service_sdk)
        try:
            return service_sdk.registry_manager.get_device_statistics()
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))
