# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os

from inspect import getsourcefile
from time import sleep
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.common.utility import ensure_azure_namespace_path
from azext_iot.common.utility import read_file_content
from azext_iot.tests.settings import DynamoSettings
from typing import Optional, TypeVar, List

ensure_azure_namespace_path()

from azure.iot.device import ProvisioningDeviceClient, IoTHubDeviceClient
from knack.log import get_logger


logger = get_logger(__name__)
cli = EmbeddedCLI()

SubRequest = TypeVar('SubRequest')
Mark = TypeVar('Mark')

GLOBAL_PROVISIONING_HOST = "global.azure-devices-provisioning.net"
TAG_ENV_VAR = [
    "definition_id",
    "job_display_name",
    "job_id",
    "use_tags"
]

CERT_ENDING = "-cert.pem"
KEY_ENDING = "-key.pem"
DATAPLANE_AUTH_TYPES = [
    AuthenticationTypeDataplane.key.value,
    AuthenticationTypeDataplane.login.value,
    "cstring",
]

settings = DynamoSettings(opt_env_set=TAG_ENV_VAR)
# Make sure that TEST_PIPELINE_ID is only populated if correct variables are present
TEST_PIPELINE_ID = "{} {} {}".format(
    settings.env.definition_id,
    settings.env.job_display_name,
    settings.env.job_id
).strip()
USE_TAGS = str(settings.env.use_tags).lower() == "true"


def load_json(filename):
    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))
    return json.loads(read_file_content(filename))


def dps_connect_device(device_id: str, credentials: dict) -> IoTHubDeviceClient:
    id_scope = credentials["idScope"]
    key = credentials["symmetricKey"]["primaryKey"]

    provisioning_device_client = ProvisioningDeviceClient.create_from_symmetric_key(
        provisioning_host=GLOBAL_PROVISIONING_HOST,
        registration_id=device_id,
        id_scope=id_scope,
        symmetric_key=key,
    )

    registration_result = provisioning_device_client.register()
    if registration_result.status == "assigned":
        device_client = IoTHubDeviceClient.create_from_symmetric_key(
            symmetric_key=key,
            hostname=registration_result.registration_state.assigned_hub,
            device_id=registration_result.registration_state.device_id,
        )
        device_client.connect()
        return device_client


def add_test_tag(cmd, name: str, rg: str, rtype: str, test_tag: str):
    if USE_TAGS:
        current_tags = cmd(
            f"resource show -n {name} -g {rg} --resource-type {rtype}"
        ).get_output_in_json()["tags"]

        if current_tags.get(test_tag):
            current_tags[test_tag] = int(current_tags[test_tag]) + 1
        else:
            current_tags[test_tag] = 1

        if TEST_PIPELINE_ID:
            current_tags["pipeline_id"] = f"'{TEST_PIPELINE_ID}'"

        new_tags = " ".join(f"{k}={v}" for k, v in current_tags.items())
        cmd(f"resource tag -n {name} -g {rg} --resource-type {rtype} --tags {new_tags} -i")


def create_storage_account(
    cmd,
    account_name: str,
    container_name: str,
    rg: str,
    resource_name: str,
    create_account: bool = True,
) -> str:
    """
    Create a storage account (if needed) and container and return storage connection string.
    """
    if create_account:
        storage_list = cmd(
            'storage account list -g "{}"'.format(rg)
        ).get_output_in_json()

        target_storage = None
        for storage in storage_list:
            if storage["name"] == account_name:
                target_storage = storage
                break

        if not target_storage:
            cmd(
                "storage account create -n {} -g {} --tags iot_resource={}".format(
                    account_name, rg, resource_name
                )
            )

    storage_cstring = cmd(
        "storage account show-connection-string -n {} -g {}".format(
            account_name, rg
        )
    ).get_output_in_json()["connectionString"]

    # Will not do anything if container exists.
    cmd(
        "storage container create -n {} --connection-string '{}'".format(
            container_name, storage_cstring
        ),
    )

    return storage_cstring


def tags_to_dict(tags: str) -> dict:
    result = {}
    split_tags = tags.split()
    for tag in split_tags:
        kvp = tag.split("=")
        result[kvp[0]] = kvp[1]
    return result


def get_closest_marker(request: SubRequest) -> Mark:
    for item in request.session.items:
        if item.get_closest_marker("hub_infrastructure"):
            return item.get_closest_marker("hub_infrastructure")
    return request.node.get_closest_marker("hub_infrastructure")


def get_agent_public_ip():
    """
    Poke the Wikipedia website to get Public IP.
    """
    import requests
    return requests.head("https://www.wikipedia.org").headers["X-Client-IP"]


def get_role_assignments(
    scope: str,
    assignee: str = None,
    role: str = None,
) -> List[dict]:
    """
    Get rbac permissions of resource.
    """
    role_flag = ""
    assignee_flag = ""

    if role:
        role_flag = '--role "{}"'.format(role)

    if assignee:
        assignee_flag = '--assignee "{}"'.format(assignee)

    return cli.invoke(
        f'role assignment list --scope "{scope}" {role_flag} {assignee_flag}'
    ).as_json()


def assign_role_assignment(
    role: str,
    scope: str,
    assignee: str,
    max_tries=10,
    wait=10,
):
    """
    Assign rbac permissions to resource.
    """
    output = None
    tries = 0
    principal_kpis = ["name", "principalId", "principalName"]
    while tries < max_tries:
        flat_assignment_kpis = []
        role_assignments = get_role_assignments(scope=scope, role=role)
        logger.info(f"Role assignments for the role of '{role}' against scope '{scope}': {role_assignments}")
        for role_assignment in role_assignments:
            for principal_kpi in principal_kpis:
                if principal_kpi in role_assignment and role_assignment[principal_kpi]:
                    flat_assignment_kpis.append(role_assignment[principal_kpi])
        if assignee in flat_assignment_kpis:
            break
        # else assign role to scope and check again
        output = cli.invoke(
            f'role assignment create --assignee "{assignee}" --role "{role}" --scope "{scope}"'
        )
        if not output.success():
            logger.warning(f"Failed to assign '{assignee}' the role of '{role}' against scope '{scope}'.")
            break

        sleep(wait)
        tries += 1


def delete_role_assignment(
    scope: str,
    assignee: str,
    role: str = None,
):
    """
    Delete rbac permissions of resource.
    """
    role_flag = ""

    if role:
        role_flag = "--role '{}'".format(role)

    cli.invoke(
        f"role assignment delete --scope '{scope}' --assignee '{assignee}' {role_flag}"
    )


def clean_up_iothub_device_config(
    hub_name: str,
    rg: str
):
    device_list = []
    device_list.extend(d["deviceId"] for d in cli.invoke(
        f"iot hub device-twin list -n {hub_name} -g {rg}"
    ).as_json())

    deployment_list = []
    deployment_list.extend(c["id"] for c in cli.invoke(
        f"iot edge deployment list -n {hub_name} -g {rg}"
    ).as_json())

    config_list = []
    config_list.extend(c["id"] for c in cli.invoke(
        f"iot hub configuration list -n {hub_name} -g {rg}"
    ).as_json())

    if device_list:
        for device in device_list:
            cli.invoke(
                "iot hub device-identity delete -d {} -n {} -g {}".format(
                    device, hub_name, rg
                )
            )

    if deployment_list:
        for deployment in deployment_list:
            cli.invoke(
                "iot edge deployment delete -d {} -n {} -g {}".format(
                    deployment, hub_name, rg
                )
            )

    if config_list:
        for config in config_list:
            cli.invoke(
                "iot hub configuration delete -c {} -n {} -g {}".format(
                    config, hub_name, rg
                )
            )


def create_test_cert(
    tracked_certs: List[str],
    subject: str = "aziotcli",
    cert_only: bool = True,
    file_prefix: Optional[str] = None
) -> str:
    """
    Creates a test certificate and appends it to the tracked certificates while returning the thumbprint.
    Will create key certificate if specified.
    """
    output_dir = os.getcwd()
    thumbprint = create_self_signed_certificate(
        subject=subject,
        valid_days=1,
        cert_output_dir=output_dir,
        cert_only=cert_only,
        file_prefix=file_prefix,
        sha_version=256,
    )["thumbprint"]
    tracked_certs.append(subject + CERT_ENDING)
    if not cert_only:
        tracked_certs.append(subject + KEY_ENDING)
    return thumbprint


def set_cmd_auth_type(command: str, auth_type: str, cstring: str) -> str:
    """Append the dataplane command auth type."""
    if auth_type not in DATAPLANE_AUTH_TYPES:
        raise RuntimeError(f"auth_type of: {auth_type} is unsupported.")

    # cstring takes precedence
    if auth_type == "cstring":
        return f"{command} --login {cstring}"

    return f"{command} --auth-type {auth_type}"


class MockLogger:
    def info(self, msg):
        print(msg)

    def warn(self, msg):
        print(msg)

    def error(self, msg):
        print(msg)
