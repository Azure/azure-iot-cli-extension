# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.help_files import helps

helps['iot device twin'] = """
    type: group
    short-summary: Manage device twins in your Azure IoT hub.
"""

helps['iot device twin show'] = """
    type: command
    short-summary: Output device twin definition.
"""

helps['iot device twin update'] = """
    type: command
    short-summary: Update device twin definition.
"""

helps['iot device method'] = """
    type: command
    short-summary: Invoke method on device.
"""

helps['iot device sas'] = """
    type: command
    short-summary: Generate a shared access signature token for the given device.
    long-summary: In preview.
"""

helps['iot device simulate'] = """
    type: command
    short-summary: Simulate a device on your Azure IoT hub.
    long-summary: In preview.
"""

helps['iot hub message send'] = """
    type: command
    short-summary: Send a cloud-to-device message.
"""

helps['iot device message send'] = """
    type: command
    short-summary: Send a device-to-cloud message.
    examples:
        - name: Send a device-to-cloud message to an IoT Hub with a default message using amqp, mqtt or http.
          text: >
            az iot device message send --hub-name MyIotHub --device-id MyDevice
        - name: Send a device-to-cloud message to an IoT Hub with a custom message.
          text: >
            az iot device message send --hub-name MyIotHub --device-id MyDevice --data "Custom Message"
"""
