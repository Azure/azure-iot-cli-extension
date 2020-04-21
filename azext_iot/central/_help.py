# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.help_files import helps


def load_central_help():
    helps[
        "iot central"
    ] = """
        type: group
        short-summary: Manage Azure Central (IoTC) solutions & infrastructure
    """

    _load_central_devices_help()
    _load_central_device_templates_help()


def _load_central_devices_help():
    helps[
        "iot central app device"
    ] = """
        type: group
        short-summary: Manage and configure IoTC devices
    """

    helps[
        "iot central app device create"
    ] = """
        type: command
        short-summary: Create a device in IoTC

        examples:
        - name: Create a device
          text: >
            az iot central app device create
            --app-id {appid}
            --device-id {deviceid}

        - name: Create a simulated device
          text: >
            az iot central app device create
            --app-id {appid}
            --device-id {deviceid}
            --instance-of {devicetemplateid}
            --simulated
    """

    helps[
        "iot central app device show"
    ] = """
        type: command
        short-summary: Get a device from IoTC

        examples:
        - name: Get a device
          text: >
            az iot central app device show
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central app device list"
    ] = """
        type: command
        short-summary: List all devices in IoTC

        examples:
        - name: Get a device
          text: >
            az iot central app device list
            --app-id {appid}
    """

    helps[
        "iot central app device delete"
    ] = """
        type: command
        short-summary: Delete a device from IoTC

        examples:
        - name: Get a device
          text: >
            az iot central app device list
            --app-id {appid}
            --device-id {deviceid}
    """


def _load_central_device_templates_help():
    helps[
        "iot central app device-template"
    ] = """
        type: group
        short-summary: Manage and configure IoTC device templates
    """

    helps[
        "iot central app device-template create"
    ] = """
        type: command
        short-summary: Create a device template in IoTC

        examples:
        - name: Create a device with payload read from a file
          text: >
            az iot central app device create
            --app-id {appid}
            --content {pathtofile}
            --device-template-id {devicetemplateid}

        - name: Create a device with payload read from raw json
          text: >
            az iot central app device create
            --app-id {appid}
            --content {json}
            --device-template-id {devicetemplateid}
    """

    helps[
        "iot central app device-template show"
    ] = """
        type: command
        short-summary: Get a device template from IoTC

        examples:
        - name: Get a device
          text: >
            az iot central app device show
            --app-id {appid}
            --device-template-id {devicetemplateid}
    """

    helps[
        "iot central app device-template list"
    ] = """
        type: command
        short-summary: List all device templates in IoTC

        examples:
        - name: Get a device
          text: >
            az iot central app device-template list
            --app-id {appid}
    """

    helps[
        "iot central app device-template map"
    ] = """
        type: command
        short-summary: Returns a mapping of device template name to device template id

        examples:
        - name: Get device template name to id mapping
          text: >
            az iot central app device-template map
            --app-id {appid}
    """

    helps[
        "iot central app device-template delete"
    ] = """
        type: command
        short-summary: Delete a device template from IoTC
        long-summary:
            Note: this is expected to fail
            if any devices are still registered to this template.

        examples:
        - name: Get a device
          text: >
            az iot central app device-template list
            --app-id {appid}
    """
