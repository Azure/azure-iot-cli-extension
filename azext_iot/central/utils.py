from azext_iot.central.models.enum import DeviceStatus
from knack.util import CLIError

def parse_device_status(device) -> DeviceStatus:
        if hasattr(device, 'approved') and not device.approved:
            return DeviceStatus.blocked

        if hasattr(device, 'instance_of') and not device.instance_of or hasattr(device, 'template') and not device.template:
            return DeviceStatus.unassociated

        if not device.provisioned:
            return DeviceStatus.registered

        return DeviceStatus.provisioned


def dps_populate_essential_info(dps_info, device_status: DeviceStatus):
    error = {
        DeviceStatus.provisioned: "None.",
        DeviceStatus.registered: "Device is not yet provisioned.",
        DeviceStatus.blocked: "Device is blocked from connecting to IoT Central application."
        " Unblock the device in IoT Central and retry. Learn more: https://aka.ms/iotcentral-docs-dps-SAS",
        DeviceStatus.unassociated: "Device does not have a valid template associated with it.",
    }

    filtered_dps_info = {
        "status": dps_info.get("status"),
        "error": error.get(device_status),
    }
    return filtered_dps_info

def process_version(supported_versions, version):
    if version == None:
        version = supported_versions[-1]
    return version

def throw_unsupported_version(supported_versions):
    raise CLIError(
        "Unsupported version, please select version from: " + ', '.join(supported_versions)
    )