# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.utility import unpack_msrest_error
from azext_iot.digitaltwins.providers.base import DigitalTwinsProvider
from azext_iot.digitaltwins.providers import ErrorResponseException
from knack.log import get_logger
from knack.util import CLIError

logger = get_logger(__name__)


class RouteProvider(DigitalTwinsProvider):
    def __init__(self, cmd, name, rg=None):
        super(RouteProvider, self).__init__(cmd=cmd, name=name, rg=rg)
        self.sdk = self.get_sdk().event_routes

    def get(self, route_name):
        try:
            return self.sdk.get_by_id(route_name)
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def list(self, top=None):  # top is guarded for int() in arg def
        from azext_iot.sdk.digitaltwins.dataplane.models import EventRoutesListOptions

        list_options = EventRoutesListOptions(max_item_count=top)

        try:
            return self.sdk.list(event_routes_list_options=list_options,)
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def create(self, route_name, endpoint_name, filter=None):
        if not filter:
            filter = "true"

        # TODO: Adding routes does not return an object
        try:
            self.sdk.add(id=route_name, endpoint_name=endpoint_name, filter=filter)
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

        return self.get(route_name=route_name)

    def delete(self, route_name):
        try:
            return self.sdk.delete(id=route_name)
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))
