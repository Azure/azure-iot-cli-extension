# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.monitor.handlers import _internal
from azext_iot.monitor.handlers.base_handler import AbstractBaseEventsHandler

"""
Use this handler if you aren't sure which handler is right for you
"""


class CommonHandler(AbstractBaseEventsHandler):
    def __init__(
        self,
        device_id=None,
        devices=None,
        pnp_context=None,
        interface_name=None,
        content_type=None,
        properties=None,
        output=None,
        validate_messages=None,
        simulate_errors=None,
        central_device_provider=None,
    ):
        self.device_id = device_id
        self.devices = devices
        self.pnp_context = pnp_context
        self.interface_name = interface_name
        self.content_type = content_type
        self.properties = properties
        self.output = output
        self.validate_messages = validate_messages
        self.simulate_errors = simulate_errors
        self.central_device_provider = central_device_provider
        pass

    def parse_message(self, message):
        _internal.parse_message(
            message,
            device_id=self.device_id,
            devices=self.devices,
            pnp_context=self.pnp_context,
            interface_name=self.interface_name,
            content_type=self.content_type,
            properties=self.properties,
            output=self.output,
            validate_messages=self.validate_messages,
            simulate_errors=self.simulate_errors,
            central_device_provider=self.central_device_provider,
        )
