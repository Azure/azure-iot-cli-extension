# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.central.models.edge import EdgeModule
from azext_iot.central.providers import (
    CentralFileUploadProvider,
    CentralOrganizationProvider,
    CentralRoleProvider,
    CentralDeviceGroupProvider,
    CentralDeviceTemplateProvider,
    CentralJobProvider,
    CentralUserProvider,
    CentralQueryProvider,
    CentralDestinationProvider,
    CentralExportProvider,
)
from azext_iot.central.models.enum import ApiVersion
import pytest
import json
import responses
from copy import deepcopy
from unittest import mock
from datetime import datetime
from knack.util import CLIError, todict
from azure.cli.core.mock import DummyCli
from azext_iot.central import commands_device
from azext_iot.central import commands_monitor
from azext_iot.central.providers import CentralDeviceProvider
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.monitor.property import PropertyMonitor
from azext_iot.monitor.models.enum import Severity
from azext_iot.tests.helpers import load_json
from azext_iot.tests.test_constants import FileNames
from azext_iot.constants import PNP_DTDLV2_COMPONENT_MARKER
from azext_iot.central.models.v1_1_preview import (
    DeviceGroupV1_1_preview,
    OrganizationV1_1_preview,
    JobV1_1_preview,
    FileUploadV1_1_preview,
    QueryReponseV1_1_preview,
)
from azext_iot.central.models.v1 import RoleV1, TemplateV1, UserV1
from azext_iot.central.services._utility import get_object

device_id = "mydevice"
app_id = "myapp"
device_twin_result = {"deviceId": "{}".format(device_id)}
resource = "shared_resource"
success_resp = {"result": "success"}


@pytest.fixture()
def fixture_cmd(mocker):
    # Placeholder for later use
    cmd = mock.MagicMock()
    cmd.cli_ctx = DummyCli()
    return cmd


@pytest.fixture()
def fixture_requests_post(mocker):
    class MockJsonObject:
        def get(self, _value):
            return ""

        def value(self):
            return "fixture_requests_post value"

    class ReturnObject:
        def json(self):
            return MockJsonObject()

    mock = mocker.patch("requests.post")
    mock.return_value = ReturnObject()


@pytest.fixture()
def fixture_azure_profile(mocker):
    mock = mocker.patch("azure.cli.core._profile.Profile.__init__")
    mock.return_value = None

    mock_method = mocker.patch("azure.cli.core._profile.Profile.get_raw_token")

    class MockTokenWithGet:
        def get(self, _value, _default):
            return "value"

    mock_method.return_value = [
        ["raw token 0 - A", "raw token 0 -b", MockTokenWithGet()],
        "raw token 1",
        "raw token 2",
    ]


@pytest.fixture()
def fixture_get_iot_central_tokens(mocker):
    mock = mocker.patch("azext_iot.common._azure.get_iot_central_tokens")

    mock.return_value = {
        "id": {
            "eventhubSasToken": {
                "hostname": "part1/part2/part3",
                "entityPath": "entityPath",
                "sasToken": "sasToken",
            },
            "expiry": "0000",
        }
    }


class TestCentralHelpers:
    def test_get_iot_central_tokens(self, fixture_requests_post, fixture_azure_profile):
        from azext_iot.common._azure import get_iot_central_tokens

        class Cmd:
            cli_ctx = ""

        # Test to ensure get_iot_central_tokens calls requests.post and tokens are returned
        assert (
            get_iot_central_tokens(Cmd(), "app_id", "", "api-uri").value()
            == "fixture_requests_post value"
        )

    def test_get_aad_token(self, fixture_azure_profile):
        from azext_iot.common.auth import get_aad_token

        class Cmd:
            cli_ctx = ""

        # Test to ensure _get_aad_token is called and returns the right values based on profile.get_raw_tokens
        assert get_aad_token(Cmd(), "resource") == {
            "accessToken": "raw token 0 -b",
            "expiresOn": "value",
            "subscription": "raw token 1",
            "tenant": "raw token 2",
            "tokenType": "raw token 0 - A",
        }


class TestMonitorEvents:
    @pytest.mark.parametrize("timeout, exception", [(-1, CLIError)])
    def test_monitor_events_invalid_args(self, timeout, exception, fixture_cmd):
        with pytest.raises(exception):
            commands_monitor.monitor_events(fixture_cmd, app_id, timeout=timeout)


class TestCentralDeviceProvider:
    _device = load_json(FileNames.central_device_file)
    _edge_devices = list(load_json(FileNames.central_edge_devices_file))
    _edge_children = list(load_json(FileNames.central_edge_children_file))
    _device_template = load_json(FileNames.central_device_template_file)
    _edge_template = load_json(FileNames.central_edge_template_file)
    _device_twin = load_json(FileNames.central_device_twin_file)
    _device_properties = load_json(FileNames.central_device_properties_file)
    _edge_modules = load_json(FileNames.central_edge_modules_file)
    _device_component = load_json(FileNames.central_device_component_file)

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_return_device(self, mock_device_svc, mock_device_template_svc):
        # setup
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_device_svc.get_device.return_value = get_object(
            self._device, "Device", api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_device_template_svc.get_device_template.return_value = (
            self._device_template
        )

        # act
        device = provider.get_device("someDeviceId")
        # check that caching is working
        device = provider.get_device("someDeviceId")

        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_svc.get_device.call_count == 1
        assert mock_device_svc.get_device_template.call_count == 0

        assert todict(device) == todict(self._device)

    @mock.patch("azext_iot.central.services.device")
    def test_should_return_list_edge(self, mock_device_svc):
        # setup
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )

        devices = [
            get_object(device, "Device", api_version=ApiVersion.v1_1_preview.value)
            for device in self._edge_devices
        ]
        mock_device_svc.list_devices.return_value = devices

        # act
        edge_devices = [
            todict(dev)
            for dev in provider.list_devices(
                filter="type eq 'GatewayDevice' or type eq 'EdgeDevice'"
            )
        ]
        # verify
        assert mock_device_svc.list_devices.call_count == 1
        assert edge_devices == self._edge_devices

    @mock.patch("azext_iot.central.services.device")
    def test_should_return_list_children(self, mock_device_svc):
        # setup
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )

        children = [
            get_object(device, "Device", api_version=ApiVersion.v1_1_preview.value)
            for device in self._edge_children
        ]
        mock_device_svc.list_devices.return_value = children

        joined = "' or id eq '".join([child.id for child in children])
        filter = f"id eq '{joined}'"

        # act
        children_devices = [todict(dev) for dev in provider.list_devices(filter=filter)]
        # verify
        assert mock_device_svc.list_devices.call_count == 1
        assert children_devices == self._edge_children

    @mock.patch("azext_iot.central.services.device.requests")
    @mock.patch("azext_iot.central.services.device.get_aad_token")
    def test_should_list_device_modules(self, get_aad_token_svc, req_svc):
        # setup
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        response = mock.MagicMock()
        response.status_code = 200
        response.json.return_value = self._edge_modules
        req_svc.get.return_value = response

        # act
        modules = [
            todict(computed) for computed in provider.list_device_modules("edge0")
        ]

        # verify
        # call counts should be at most 1
        assert req_svc.get.call_count == 1
        parsed_modules = [
            todict(EdgeModule(_module)) for _module in self._edge_modules.get("modules")
        ]
        assert parsed_modules == modules

    @mock.patch("azext_iot.central.services.device")
    def test_should_list_components(self, mock_device_svc):
        # setup
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_device_svc.list_device_module_components.return_value = self._device_component

        # act
        components = [
            todict(component) for component in provider.list_device_module_components("someDeviceId").get("value")
        ]

        # verify
        assert mock_device_svc.list_device_module_components.call_count == 1
        assert components == self._device_component["value"]

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_return_device_template(
        self, mock_device_svc, mock_device_template_svc
    ):
        # setup
        provider = CentralDeviceTemplateProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_device_svc.get_device.return_value = self._device
        mock_device_template_svc.get_device_template.return_value = (
            self._device_template
        )

        # act
        template = provider.get_device_template("someDeviceTemplate")
        # check that caching is working
        template = provider.get_device_template("someDeviceTemplate")

        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_template_svc.get_device_template.call_count == 1
        assert template == self._device_template

    @mock.patch("azext_iot.central.services.device_template")
    def test_should_update_device_template_name(self, mock_device_template_svc):
        # setup
        provider = CentralDeviceTemplateProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        existing = get_object(
            self._device_template, "Template", api_version=ApiVersion.ga_2022_05_31.value
        )
        display_name = "NewName"
        mock_device_template_svc.get_device_template.return_value = existing
        updated_template_dict = deepcopy(self._device_template)
        updated_template_dict["displayName"] = display_name
        mock_device_template_svc.update_device_template.return_value = get_object(
            updated_template_dict, "Template", api_version=ApiVersion.ga_2022_05_31.value
        )

        # act
        template = provider.update_device_template(
            device_template_id=existing.id, payload=updated_template_dict
        )

        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_template_svc.update_device_template.call_count == 1
        assert template.name == display_name

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_update_device_name(self, mock_device_svc, mock_device_template_svc):
        # setup
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        existing = get_object(self._device, "Device", api_version=ApiVersion.ga_2022_05_31.value)
        display_name = "NewName"
        mock_device_svc.get_device.return_value = existing
        updated_device = deepcopy(existing)
        updated_device.display_name = display_name
        mock_device_svc.update_device.return_value = updated_device
        mock_device_template_svc.get_device_template.return_value = (
            self._device_template
        )

        # act
        device = provider.update_device(device_id=existing.id, device_name=display_name)

        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_svc.update_device.call_count == 1
        assert mock_device_svc.get_device_template.call_count == 0
        assert device.display_name == display_name

    @mock.patch("azext_iot.central.services.device")
    def test_should_return_correct_device_version(self, mock_device_svc):
        # setup
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.preview.value
        )
        existing = get_object(
            self._device, "Device", api_version=ApiVersion.preview.value
        )
        mock_device_svc.get_device.return_value = existing

        # act
        device = provider.get_device(device_id=existing.id)

        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_svc.get_device.call_count == 1
        assert device.instance_of == self._device["template"]

    @mock.patch("azext_iot.central.services.device")
    def test_device_twin_show_calls_get_twin(self, mock_device_svc):
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_device_svc.get_device_twin.return_value = self._device_twin

        twin = provider.get_device_twin("someDeviceId")
        assert twin == self._device_twin

    @mock.patch("azext_iot.central.services.device")
    def test_should_return_attestation(self, mock_device_svc):
        device_attestation = {
            "type": "symmetricKey",
            "symmetricKey": {
                "primaryKey": "<primary key>",
                "secondaryKey": "<secondary key>"
            }
        }
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_device_svc.get_device_attestation.return_value = device_attestation
        attestation = provider.get_device_attestation("someDeviceId")
        assert attestation == device_attestation

    @mock.patch("azext_iot.central.services.device")
    def test_should_return_properties(self, mock_device_svc):
        provider = CentralDeviceProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_device_svc.get_device_properties_or_telemetry_value.return_value = self._device_properties

        properties = provider.get_device_properties("someDeviceId")
        assert properties == self._device_properties


class TestCentralDeviceGroupProvider:
    _device_groups = [
        DeviceGroupV1_1_preview(group)
        for group in load_json(FileNames.central_device_group_file)
    ]
    _device_group = load_json(FileNames.central_device_group_file)[0]

    @mock.patch("azext_iot.central.services.device_group")
    def test_should_return_device_groups(self, mock_device_group_svc):

        # setup
        provider = CentralDeviceGroupProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_device_group_svc.list_device_groups.return_value = self._device_groups

        # act
        device_groups = provider.list_device_groups()
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_group_svc.list_device_groups.call_count == 1
        assert set(device_groups) == set(self._device_groups)

    @mock.patch("azext_iot.central.services.device_group")
    def test_should_fail_device_groups(self, mock_device_group_svc):

        # setup
        provider = CentralDeviceGroupProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_device_group_svc.list_device_groups.return_value = self._device_groups

        # act
        device_groups = provider.list_device_groups()
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_group_svc.list_device_groups.call_count == 1
        assert set(device_groups) == set(self._device_groups)

    @mock.patch("azext_iot.central.services.device_group")
    def test_should_update_device_group_name(self, mock_device_group_svc):
        # setup
        provider = CentralDeviceGroupProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        existing = get_object(
            self._device_group, "DeviceGroup", api_version=ApiVersion.ga_2022_05_31.value
        )
        display_name = "NewDeviceGroupName"
        mock_device_group_svc.get_device_group.return_value = existing
        updated_device_group_dict = deepcopy(self._device_group)
        updated_device_group_dict["displayName"] = display_name
        mock_device_group_svc.update_device_group.return_value = get_object(
            updated_device_group_dict, "DeviceGroup", api_version=ApiVersion.ga_2022_05_31.value
        )

        # act
        device_group = provider.update_device_group(
            device_group_id=existing.id,
            display_name=display_name,
        )

        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_group_svc.update_device_group.call_count == 1
        assert device_group.display_name == display_name


class TestCentralRoleProvider:
    _roles = [RoleV1(role) for role in load_json(FileNames.central_role_file)]

    @mock.patch("azext_iot.central.services.role")
    def test_should_return_roles(self, mock_role_svc):

        # setup
        provider = CentralRoleProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_role_svc.list_roles.return_value = self._roles

        # act
        roles = provider.list_roles()
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_role_svc.list_roles.call_count == 1
        assert set(roles) == set(self._roles)

    @mock.patch("azext_iot.central.services.role")
    def test_should_return_role(self, mock_role_svc):
        # setup
        provider = CentralRoleProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_role_svc.get_role.return_value = self._roles[0]

        # act
        role = provider.get_role(self._roles[0].id)
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_role_svc.get_role.call_count == 1
        assert role.id == self._roles[0].id


class TestCentralUserProvider:
    _users = [UserV1(user) for user in load_json(FileNames.central_user_file)]

    @mock.patch("azext_iot.central.services.user")
    def test_should_return_users(self, mock_user_svc):

        # setup
        provider = CentralUserProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_user_svc.get_user_list.return_value = self._users

        # act
        users = provider.get_user_list()
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_user_svc.get_user_list.call_count == 1
        assert set(users) == set(self._users)

    @mock.patch("azext_iot.central.services.user")
    def test_should_return_user(self, mock_user_svc):
        # setup
        provider = CentralUserProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_user_svc.get_user.return_value = self._users[0]

        # act
        user = provider.get_user(self._users[0].id)
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_user_svc.get_user.call_count == 1
        assert user.id == self._users[0].id

    @mock.patch("azext_iot.central.services.user")
    def test_should_update_user(self, mock_user_svc):
        current_user = self._users[0]
        updated_user = deepcopy(current_user)
        updated_user.roles[0]["role"] = "new_role"
        # setup
        provider = CentralUserProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_user_svc.add_or_update_email_user.return_value = updated_user

        # act
        user = provider.update_email_user(
            current_user.id, email=current_user.email, roles="new_role"
        )
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_user_svc.add_or_update_email_user.call_count == 1
        assert user.roles[0]["role"] == "new_role"

    @mock.patch("azext_iot.central.services.user")
    def test_should_update_user_with_org(self, mock_user_svc):
        current_user = self._users[0]
        updated_user = deepcopy(current_user)
        updated_user.roles[0]["role"] = "new_role"
        updated_user.roles[0]["organization"] = "new_org"
        # setup
        provider = CentralUserProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_user_svc.add_or_update_email_user.return_value = updated_user

        # act
        user = provider.update_email_user(
            current_user.id, email=current_user.email, roles="new_org\\new_role"
        )
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_user_svc.add_or_update_email_user.call_count == 1
        assert user.roles[0]["role"] == "new_role"
        assert user.roles[0]["organization"] == "new_org"


class TestCentralOrganizationProvider:
    _orgs = [
        OrganizationV1_1_preview(org)
        for org in load_json(FileNames.central_organization_file)
    ]

    @mock.patch("azext_iot.central.services.organization")
    def test_should_return_orgs(self, mock_org_svc):

        # setup
        provider = CentralOrganizationProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_org_svc.list_orgs.return_value = self._orgs

        # act
        orgs = provider.list_organizations()
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_org_svc.list_orgs.call_count == 1
        assert set(orgs) == set(self._orgs)

    @mock.patch("azext_iot.central.services.organization")
    def test_should_return_org(self, mock_org_svc):
        # setup
        provider = CentralOrganizationProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_org_svc.get_org.return_value = self._orgs[0]

        # act
        org = provider.get_organization(self._orgs[0].id)
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_org_svc.get_org.call_count == 1
        assert org.id == self._orgs[0].id

    @mock.patch("azext_iot.central.services.organization")
    def test_should_update_org(self, mock_org_svc):
        current_org = self._orgs[0]
        updated_org = deepcopy(current_org)
        updated_org.display_name = "new_name"
        # setup
        provider = CentralOrganizationProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.ga_2022_05_31.value
        )
        mock_org_svc.create_or_update_org.return_value = updated_org

        # act
        org = provider.create_or_update_organization(
            current_org.id, org_name="new_name", update=True, parent_org=None
        )
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_org_svc.create_or_update_org.call_count == 1
        assert org.display_name == "new_name"


class TestCentralJobProvider:
    _jobs = [JobV1_1_preview(job) for job in load_json(FileNames.central_job_file)]

    @mock.patch("azext_iot.central.services.job")
    def test_should_return_jobs(self, mock_job_svc):

        # setup
        provider = CentralJobProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_job_svc.list_jobs.return_value = self._jobs

        # act
        jobs = provider.list_jobs()
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_job_svc.list_jobs.call_count == 1
        assert set(jobs) == set(self._jobs)

    @mock.patch("azext_iot.central.services.job")
    def test_should_return_job(self, mock_job_svc):
        # setup
        provider = CentralJobProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_job_svc.get_job.return_value = self._jobs[0]

        # act
        job = provider.get_job(self._jobs[0].id)
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_job_svc.get_job.call_count == 1
        assert job.id == self._jobs[0].id


class TestCentralFileuploadProvider:
    _fileupload = FileUploadV1_1_preview(load_json(FileNames.central_fileupload_file))

    @mock.patch("azext_iot.central.services.file_upload")
    def test_should_return_fileupload(self, mock_fileupload_svc):
        # setup
        provider = CentralFileUploadProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_fileupload_svc.get_fileupload.return_value = self._fileupload

        # act
        fileupload = provider.get_fileupload()
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_fileupload_svc.get_fileupload.call_count == 1
        assert fileupload.connection_string == self._fileupload.connection_string

    @mock.patch("azext_iot.central.services.file_upload")
    def test_should_update_fileupload(self, mock_fileupload_svc):

        updated_file_upload = deepcopy(self._fileupload)
        updated_file_upload.container = "new_container"
        # setup
        provider = CentralFileUploadProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_fileupload_svc.createorupdate_fileupload.return_value = updated_file_upload

        # act
        fileupload = provider.update_fileupload(
            container="new_container", connection_string=None, account=None, sasTtl=None
        )
        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_fileupload_svc.createorupdate_fileupload.call_count == 1
        assert fileupload.container == "new_container"


class TestCentralQueryProvider:
    _query_response = QueryReponseV1_1_preview(
        load_json(FileNames.central_query_response_file)
    )

    @mock.patch("azext_iot.central.services.query")
    def test_should_return_query_response(self, mock_query_svc):
        # setup
        provider = CentralQueryProvider(
            cmd=None,
            query=None,
            app_id=app_id,
            api_version=ApiVersion.v1_1_preview.value,
        )
        mock_query_svc.query_run.return_value = self._query_response

        # act
        query_response = provider.query_run()
        # verify
        assert mock_query_svc.query_run.call_count == 1
        assert query_response.results == self._query_response.results


class TestCentralDestinationProvider:
    _destinations = list(load_json(FileNames.central_destination_file))

    @mock.patch("azext_iot.central.services.destination")
    def test_should_return_list_destinations(self, mock_destination_svc):
        # setup
        provider = CentralDestinationProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_destination_svc.list_destinations.return_value = self._destinations

        # act
        destinations = provider.list_destinations()
        # verify
        assert mock_destination_svc.list_destinations.call_count == 1
        assert destinations == self._destinations

    @mock.patch("azext_iot.central.services.destination")
    def test_should_return_get_destination(self, mock_destination_svc):
        # setup
        provider = CentralDestinationProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_destination_svc.get_destination.return_value = self._destinations[0]

        # act
        destination = provider.get_destination(self._destinations[0]["id"])
        # verify
        assert mock_destination_svc.get_destination.call_count == 1
        assert destination == self._destinations[0]

    @mock.patch("azext_iot.central.services.destination")
    def test_should_success_add_destinatio(self, mock_destination_svc):
        # setup
        provider = CentralDestinationProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_destination_svc.add_destination.return_value = self._destinations[0]

        # act
        destination = provider.add_destination(
            self._destinations[0]["id"], self._destinations[0]
        )
        # verify
        assert mock_destination_svc.add_destination.call_count == 1
        assert provider._destinations[destination["id"]] == self._destinations[0]

    @mock.patch("azext_iot.central.services.destination")
    def test_should_success_update_destination(self, mock_destination_svc):
        # setup
        provider = CentralDestinationProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_destination_svc.update_destination.return_value = self._destinations[0]

        # act
        provider.add_destination(self._destinations[0]["id"], self._destinations[0])
        destination = provider.update_destination(self._destinations[0]["id"], None)
        # verify
        assert mock_destination_svc.add_destination.call_count == 1
        assert mock_destination_svc.update_destination.call_count == 1
        assert provider._destinations[destination["id"]] == self._destinations[0]

    @mock.patch("azext_iot.central.services.destination")
    def test_should_success_delete_destination(self, mock_destination_svc):
        # setup
        provider = CentralDestinationProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_destination_svc.add_destination.return_value = self._destinations[0]

        # act
        provider.add_destination(self._destinations[0]["id"], self._destinations[0])
        provider.delete_destination(self._destinations[0]["id"])
        # verify
        assert mock_destination_svc.add_destination.call_count == 1
        assert mock_destination_svc.delete_destination.call_count == 1
        assert len(provider._destinations) == 0


class TestCentralExportProvider:
    _exports = list(load_json(FileNames.central_export_file))

    @mock.patch("azext_iot.central.services.export")
    def test_should_return_list_exports(self, mock_export_svc):
        # setup
        provider = CentralExportProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_export_svc.list_exports.return_value = self._exports

        # act
        exports = provider.list_exports()
        # verify
        assert mock_export_svc.list_exports.call_count == 1
        assert exports == self._exports

    @mock.patch("azext_iot.central.services.export")
    def test_should_return_get_export(self, mock_export_svc):
        # setup
        provider = CentralExportProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_export_svc.get_export.return_value = self._exports[0]

        # act
        export = provider.get_export(self._exports[0]["id"])
        # verify
        assert mock_export_svc.get_export.call_count == 1
        assert export == self._exports[0]

    @mock.patch("azext_iot.central.services.export")
    def test_should_success_add_export(self, mock_export_svc):
        # setup
        provider = CentralExportProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_export_svc.add_export.return_value = self._exports[0]

        # act
        export = provider.add_export(self._exports[0]["id"], self._exports[0])
        # verify
        assert mock_export_svc.add_export.call_count == 1
        assert export == self._exports[0]
        assert provider._exports[export["id"]] == export

    @mock.patch("azext_iot.central.services.export")
    def test_should_success_update_export(self, mock_export_svc):
        # setup
        provider = CentralExportProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_export_svc.update_export.return_value = self._exports[0]

        # act
        provider.add_export(self._exports[0]["id"], self._exports[0])
        export = provider.update_export(self._exports[0]["id"], None)
        # verify
        assert mock_export_svc.add_export.call_count == 1
        assert mock_export_svc.update_export.call_count == 1
        assert provider._exports[export["id"]] == self._exports[0]

    @mock.patch("azext_iot.central.services.export")
    def test_should_success_delete_export(self, mock_export_svc):
        # setup
        provider = CentralExportProvider(
            cmd=None, app_id=app_id, api_version=ApiVersion.v1_1_preview.value
        )
        mock_export_svc.add_export.return_value = self._exports[0]

        # act
        export = provider.add_export(self._exports[0]["id"], self._exports[0])
        provider.delete_export(export["id"])
        # verify
        assert mock_export_svc.add_export.call_count == 1
        assert mock_export_svc.delete_export.call_count == 1
        assert len(provider._exports) == 0


class TestCentralPropertyMonitor:
    _device_twin = load_json(FileNames.central_device_twin_file)
    _duplicate_property_template = load_json(
        FileNames.central_property_validation_template_file
    )

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_return_updated_properties(
        self, mock_device_svc, mock_device_template_svc
    ):
        # setup
        device_twin_data = json.dumps(self._device_twin)
        raw_twin = json.loads(
            device_twin_data.replace("current_time", datetime.now().isoformat())
        )

        twin = DeviceTwin(raw_twin)
        twin_next = DeviceTwin(raw_twin)
        twin_next.reported_property.version = twin.reported_property.version + 1
        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )
        result = monitor._compare_properties(
            twin_next.reported_property, twin.reported_property
        )
        assert len(result) == 1

        assert len(result["device_info"]) == 9
        assert result["device_info"]["manufacturer"]
        assert result["device_info"]["model"]
        assert result["device_info"]["osName"]
        assert result["device_info"]["processorArchitecture"]
        assert result["device_info"]["swVersion"]
        assert result["device_info"]["processorManufacturer"]
        assert result["device_info"]["totalStorage"]
        assert result["device_info"]["totalMemory"]

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_return_no_properties(
        self, mock_device_svc, mock_device_template_svc
    ):
        # test to check that no property updates are reported when version is not upadted
        # setup
        device_twin_data = json.dumps(self._device_twin)
        raw_twin = json.loads(
            device_twin_data.replace("current_time", datetime.now().isoformat())
        )

        twin = DeviceTwin(raw_twin)
        twin_next = DeviceTwin(raw_twin)
        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )
        result = monitor._compare_properties(
            twin_next.reported_property, twin.reported_property
        )
        assert result is None

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_declared_multiple_interfaces(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = TemplateV1(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )

        model = {"Model": "test_model"}

        issues = monitor._validate_payload_against_entities(
            model,
            list(model.keys())[0],
            Severity.warning,
        )

        assert (
            issues[0].details == "Duplicate property: 'Model' found under following "
            "interfaces ['urn:sampleApp:groupOne_bz:_rpgcmdpo:1', 'urn:sampleApp:groupTwo_bz:myxqftpsr:2', "
            "'urn:sampleApp:groupThree_bz:myxqftpsr:2'] "
            "in the device model. Either provide the interface name as part "
            "of the device payload or make the propery name unique in the device model"
        )

        version = {"OsName": "test_osName"}

        issues = monitor._validate_payload_against_entities(
            version,
            list(version.keys())[0],
            Severity.warning,
        )

        assert len(issues) == 0

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_name_miss_under_interface(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = TemplateV1(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )

        # invalid interface / property
        definition = {"definition": "test_definition"}

        issues = monitor._validate_payload_against_entities(
            definition,
            list(definition.keys())[0],
            Severity.warning,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device template."
            " Following capabilities have NOT been defined in the device template '['definition']'."
            " Following capabilities have been defined in the device template (grouped by interface)"
            " '{'urn:sampleApp:groupOne_bz:2': ['addRootProperty', 'addRootPropertyReadOnly', 'addRootProperty2'],"
            " 'urn:sampleApp:groupOne_bz:_rpgcmdpo:1': ['Model', 'Version', 'TotalStorage'],"
            " 'urn:sampleApp:groupTwo_bz:myxqftpsr:2': ['Model', 'Manufacturer'],"
            " 'urn:sampleApp:groupThree_bz:myxqftpsr:2': ['Manufacturer', 'Version', 'Model', 'OsName']}'. "
        )

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_severity_level(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = TemplateV1(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )

        # severity level info
        definition = {"definition": "test_definition"}

        issues = monitor._validate_payload_against_entities(
            definition,
            list(definition.keys())[0],
            Severity.info,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device template. "
            "Following capabilities have NOT been defined in the device template "
            "'['definition']'. Following capabilities have been defined in the device template "
            "(grouped by interface) '{'urn:sampleApp:groupOne_bz:2': "
            "['addRootProperty', 'addRootPropertyReadOnly', 'addRootProperty2'], "
            "'urn:sampleApp:groupOne_bz:_rpgcmdpo:1': ['Model', 'Version', 'TotalStorage'], "
            "'urn:sampleApp:groupTwo_bz:myxqftpsr:2': ['Model', 'Manufacturer'], "
            "'urn:sampleApp:groupThree_bz:myxqftpsr:2': ['Manufacturer', 'Version', 'Model', 'OsName']}'. "
        )

        # severity level error
        issues = monitor._validate_payload_against_entities(
            definition,
            list(definition.keys())[0],
            Severity.error,
        )

        assert len(issues) == 0

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_name_miss_under_component(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = TemplateV1(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )

        # invalid component property
        definition = {
            PNP_DTDLV2_COMPONENT_MARKER: "c",
            "data": {"definition": "test_definition"},
        }

        issues = monitor._validate_payload_against_entities(
            definition,
            list(definition.keys())[0],
            Severity.warning,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device template. "
            "Following capabilities have NOT been defined in the device template '['data']'. "
            "Following capabilities have been defined in the device template (grouped by components) "
            "'{'_rpgcmdpo': ['component1Prop', 'testComponent', 'component1PropReadonly', 'component1Prop2'], "
            "'RS40OccupancySensorV36fy': ['component2prop', 'testComponent', 'component2PropReadonly', "
            "'component2Prop2', 'component1Telemetry']}'. "
        )


class TestFailover:
    @pytest.fixture
    def service_client(
        self, mocked_response, fixture_cmd, fixture_get_iot_central_tokens
    ):

        mocked_response.add(
            method=responses.POST,
            url="https://myapp.azureiotcentral.com/system/iothub/devices/{}/manual-failover".format(
                device_id
            ),
            body=json.dumps(success_resp),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_should_run_manual_failover(self, service_client):
        # act
        result = commands_device.run_manual_failover(
            fixture_cmd, app_id, device_id, ttl_minutes=10, token="Shared sig"
        )
        # assert
        assert result == success_resp

    def test_should_fail_negative_ttl(self):
        with pytest.raises(CLIError):
            # act
            commands_device.run_manual_failover(
                fixture_cmd, app_id, device_id, ttl_minutes=-10, token="Shared sig"
            )


class TestFailback:
    @pytest.fixture
    def service_client(
        self, mocked_response, fixture_cmd, fixture_get_iot_central_tokens
    ):

        mocked_response.add(
            method=responses.POST,
            url="https://myapp.azureiotcentral.com/system/iothub/devices/{}/manual-failback".format(
                device_id
            ),
            body=json.dumps(success_resp),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_should_run_manual_failover(self, service_client):
        # act
        result = commands_device.run_manual_failback(
            fixture_cmd, app_id, device_id, token="Shared sig"
        )
        # assert
        assert result == success_resp
