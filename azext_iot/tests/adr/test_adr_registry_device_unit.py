# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import inspect
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError as CLIResourceNotFoundError,
)

from azext_iot.adr import commands_registry_device
from azure.core.exceptions import ResourceNotFoundError

from azext_iot.adr.common import (
    ADU_ATTRIBUTE_NAME,
    DeviceAttributeReportedType,
    RegistryDeviceAuthenticationType,
    RegistryDeviceEnablementState,
)
from azext_iot.adr.providers.registry_device import RegistryDeviceProvider
from azext_iot.tests.adr.conftest import _spec_adr_client

RG = "test-rg"
NS = "test-namespace"
DEVICE = "test-registry-device"
PROFILE = "default"


def _completed_poller(result):
    poller = Mock()
    poller.done.return_value = True
    poller.result.return_value = result
    return poller


@pytest.fixture()
def registry_device_provider():
    with patch("azext_iot.adr.providers.base.adr_service_factory") as factory:
        factory.return_value = _spec_adr_client()
        yield RegistryDeviceProvider(Mock(cli_ctx=Mock()))


def test_create_builds_exact_camel_case_body_and_waits(registry_device_provider):
    expected = {"name": DEVICE}
    poller = _completed_poller(expected)
    registry_device_provider.client.registry_devices.begin_create_or_replace.return_value = poller

    result = registry_device_provider.create(
        registry_device_name=DEVICE,
        namespace_name=NS,
        resource_group_name=RG,
        location="eastus",
        tags={"environment": "test"},
        enablement_state=RegistryDeviceEnablementState.disabled.value,
        external_device_id="external-42",
        manufacturer="Contoso",
        model="X100",
        hardware_revision="2.0",
        software_revision="3.1",
    )

    assert result == expected
    poller.result.assert_called_once_with()
    registry_device_provider.client.registry_devices.begin_create_or_replace.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        resource={
            "location": "eastus",
            "tags": {"environment": "test"},
            "properties": {
                "enablementState": "Disabled",
                "externalDeviceId": "external-42",
                "manufacturer": "Contoso",
                "model": "X100",
                "hardwareRevision": "2.0",
                "softwareRevision": "3.1",
            },
        },
    )


def test_create_defaults_enabled_and_inherits_namespace_location(
    registry_device_provider,
):
    registry_device_provider.client.namespaces.get.return_value = {"location": "westus2"}
    registry_device_provider.client.registry_devices.begin_create_or_replace.return_value = (
        _completed_poller({})
    )

    registry_device_provider.create(
        registry_device_name=DEVICE,
        namespace_name=NS,
        resource_group_name=RG,
    )

    registry_device_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
    )
    call = registry_device_provider.client.registry_devices.begin_create_or_replace.call_args
    assert call.kwargs["resource"] == {
        "location": "westus2",
        "properties": {"enablementState": "Enabled"},
    }


def test_external_device_id_is_create_only_but_can_be_used_for_lookup(
    registry_device_provider,
):
    provider_create = inspect.signature(registry_device_provider.create).parameters
    provider_update = inspect.signature(registry_device_provider.update).parameters
    provider_show = inspect.signature(registry_device_provider.show).parameters
    command_create = inspect.signature(
        commands_registry_device.adr_registry_device_create
    ).parameters
    command_update = inspect.signature(
        commands_registry_device.adr_registry_device_update
    ).parameters
    command_show = inspect.signature(
        commands_registry_device.adr_registry_device_show
    ).parameters

    assert "external_device_id" in provider_create
    assert "external_device_id" in command_create
    assert "external_device_id" in provider_show
    assert "external_device_id" in command_show
    assert "external_device_id" not in provider_update
    assert "external_device_id" not in command_update

    with pytest.raises(TypeError):
        registry_device_provider.update(
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            external_device_id="not-updateable",
        )
    registry_device_provider.client.registry_devices.begin_update.assert_not_called()


def test_show_by_external_id_follows_paged_iterator(
    registry_device_provider,
):
    expected = {
        "name": "materialized-device",
        "properties": {"externalDeviceId": "external-42"},
    }

    def paged_results():
        yield {
            "name": "first-page",
            "properties": {"externalDeviceId": "other"},
        }
        yield expected

    registry_device_provider.client.registry_devices.list_by_namespace.return_value = (
        paged_results()
    )

    assert registry_device_provider.show(
        namespace_name=NS,
        resource_group_name=RG,
        external_device_id="external-42",
    ) == expected


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({}, RequiredArgumentMissingError),
        (
            {
                "registry_device_name": DEVICE,
                "external_device_id": "external-42",
            },
            MutuallyExclusiveArgumentError,
        ),
    ],
)
def test_show_requires_exactly_one_lookup_key(
    registry_device_provider, kwargs, error
):
    with pytest.raises(error, match="exactly one"):
        registry_device_provider.show(
            namespace_name=NS,
            resource_group_name=RG,
            **kwargs,
        )


def test_show_by_external_id_reports_zero_and_multiple_matches(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_devices
    operations.list_by_namespace.return_value = iter([])
    with pytest.raises(CLIResourceNotFoundError, match="materialization"):
        registry_device_provider.show(
            namespace_name=NS,
            resource_group_name=RG,
            external_device_id="external-42",
        )

    operations.list_by_namespace.return_value = iter(
        [
            {
                "name": "device-b",
                "properties": {"externalDeviceId": "external-42"},
            },
            {
                "name": "device-a",
                "properties": {"externalDeviceId": "external-42"},
            },
        ]
    )
    with pytest.raises(
        AzureResponseError, match="device-a, device-b.*Use --name"
    ):
        registry_device_provider.show(
            namespace_name=NS,
            resource_group_name=RG,
            external_device_id="external-42",
        )


def test_update_builds_exact_body_for_all_writable_fields_and_waits(
    registry_device_provider,
):
    expected = {"name": DEVICE, "properties": {"enablementState": "Disabled"}}
    poller = _completed_poller(expected)
    registry_device_provider.client.registry_devices.begin_update.return_value = poller

    result = registry_device_provider.update(
        registry_device_name=DEVICE,
        namespace_name=NS,
        resource_group_name=RG,
        tags={"environment": "production"},
        enablement_state="Disabled",
        manufacturer="Fabrikam",
        model="X200",
        hardware_revision="2.1",
        software_revision="4.0",
    )

    assert result == expected
    poller.result.assert_called_once_with()
    registry_device_provider.client.registry_devices.begin_update.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        properties={
            "tags": {"environment": "production"},
            "properties": {
                "enablementState": "Disabled",
                "manufacturer": "Fabrikam",
                "model": "X200",
                "hardwareRevision": "2.1",
                "softwareRevision": "4.0",
            },
        },
    )


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"tags": {}}, {"tags": {}}),
        ({"manufacturer": ""}, {"properties": {"manufacturer": ""}}),
        ({"model": ""}, {"properties": {"model": ""}}),
        ({"hardware_revision": ""}, {"properties": {"hardwareRevision": ""}}),
        ({"software_revision": ""}, {"properties": {"softwareRevision": ""}}),
    ],
)
def test_update_preserves_explicit_clear_values(
    registry_device_provider, kwargs, expected
):
    registry_device_provider.client.registry_devices.begin_update.return_value = (
        _completed_poller({})
    )

    registry_device_provider.update(
        registry_device_name=DEVICE,
        namespace_name=NS,
        resource_group_name=RG,
        **kwargs,
    )

    call = registry_device_provider.client.registry_devices.begin_update.call_args
    assert call.kwargs["properties"] == expected


def test_update_rejects_empty_patch(registry_device_provider):
    with pytest.raises(RequiredArgumentMissingError, match="Nothing to update"):
        registry_device_provider.update(
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
        )

    registry_device_provider.client.registry_devices.begin_update.assert_not_called()


@pytest.mark.parametrize("operation", ["create", "update"])
def test_registry_device_rejects_invalid_enablement_state(
    registry_device_provider, operation
):
    kwargs = {
        "registry_device_name": DEVICE,
        "namespace_name": NS,
        "resource_group_name": RG,
        "enablement_state": "Unknown",
    }
    if operation == "create":
        kwargs["location"] = "eastus"

    with pytest.raises(InvalidArgumentValueError, match="Enabled.*Disabled"):
        getattr(registry_device_provider, operation)(**kwargs)


def test_show_list_and_delete_select_registry_device_operations(
    registry_device_provider,
):
    registry_device_provider.client.registry_devices.get.return_value = {"name": DEVICE}
    registry_device_provider.client.registry_devices.list_by_namespace.return_value = iter(
        [{"name": "one"}, {"name": "two"}]
    )
    poller = _completed_poller(None)
    registry_device_provider.client.registry_devices.begin_delete.return_value = poller

    assert registry_device_provider.show(DEVICE, NS, RG) == {"name": DEVICE}
    assert registry_device_provider.list(NS, RG) == [
        {"name": "one"},
        {"name": "two"},
    ]
    assert registry_device_provider.delete(DEVICE, NS, RG) is None
    poller.result.assert_called_once_with()

    registry_device_provider.client.registry_devices.get.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
    )
    registry_device_provider.client.registry_devices.list_by_namespace.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
    )
    registry_device_provider.client.registry_devices.begin_delete.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
    )


@pytest.mark.parametrize("operation", ["create", "update", "delete", "revoke"])
def test_mutations_honor_no_wait(registry_device_provider, operation):
    poller = _completed_poller({"name": DEVICE})

    if operation == "create":
        registry_device_provider.client.registry_devices.begin_create_or_replace.return_value = poller
        result = registry_device_provider.create(
            DEVICE,
            NS,
            RG,
            location="eastus",
            no_wait=True,
        )
    elif operation == "update":
        registry_device_provider.client.registry_devices.begin_update.return_value = poller
        result = registry_device_provider.update(
            DEVICE,
            NS,
            RG,
            manufacturer="Contoso",
            no_wait=True,
        )
    elif operation == "delete":
        registry_device_provider.client.registry_devices.begin_delete.return_value = poller
        result = registry_device_provider.delete(DEVICE, NS, RG, no_wait=True)
    else:
        auth_operations = (
            registry_device_provider.client.registry_device_authentication_profiles
        )
        auth_operations.get.return_value = {
            "properties": {
                "authenticationType": "CertificateAuthoritySignedX509Certificate"
            }
        }
        auth_operations.begin_revoke_certificates.return_value = poller
        result = registry_device_provider.auth_revoke_certs(
            PROFILE,
            DEVICE,
            NS,
            RG,
            no_wait=True,
        )

    assert result is poller
    poller.result.assert_not_called()


def test_auth_list_and_show_select_expected_operations(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_device_authentication_profiles
    operations.list_by_device.return_value = iter(
        [{"name": "profile-one"}, {"name": "profile-two"}]
    )
    operations.get.return_value = {"name": PROFILE}

    assert registry_device_provider.auth_list(DEVICE, NS, RG) == [
        {"name": "profile-one"},
        {"name": "profile-two"},
    ]
    assert registry_device_provider.auth_show(PROFILE, DEVICE, NS, RG) == {
        "name": PROFILE
    }

    operations.list_by_device.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
    )
    operations.get.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        authentication_profile_name=PROFILE,
    )


def test_get_keys_validates_type_and_warns_without_logging_secrets(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_device_authentication_profiles
    operations.get.return_value = {
        "properties": {"authenticationType": "SymmetricKey"}
    }
    keys = {
        "symmetricKey": {
            "primaryKey": "primary-key-value",
            "secondaryKey": "secondary-key-value",
        }
    }
    operations.get_keys.return_value = keys

    with patch(
        "azext_iot.adr.providers.registry_device.logger.warning"
    ) as warning:
        result = registry_device_provider.auth_show_keys(
            PROFILE,
            DEVICE,
            NS,
            RG,
        )

    assert result == keys
    operations.get.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        authentication_profile_name=PROFILE,
    )
    operations.get_keys.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        authentication_profile_name=PROFILE,
        logging_enable=False,
    )
    warning.assert_called_once()
    warning_text = repr(warning.call_args)
    assert "secret" in warning_text.lower()
    assert "primary-key-value" not in warning_text
    assert "secondary-key-value" not in warning_text


@pytest.mark.parametrize(
    "profile",
    [
        {"properties": {"authenticationType": "CertificateAuthority"}},
        {"properties": {"authenticationType": "SelfSignedX509Certificate"}},
        {"properties": {}},
        None,
    ],
)
def test_get_keys_rejects_non_symmetric_profiles(
    registry_device_provider, profile
):
    operations = registry_device_provider.client.registry_device_authentication_profiles
    operations.get.return_value = profile

    with pytest.raises(InvalidArgumentValueError, match="SymmetricKey"):
        registry_device_provider.auth_show_keys(
            PROFILE,
            DEVICE,
            NS,
            RG,
        )

    operations.get.assert_called_once()
    operations.get_keys.assert_not_called()


def test_revoke_certificates_requires_managed_x509_and_waits(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_device_authentication_profiles
    operations.get.return_value = {
        "properties": {
            "authenticationType": (
                RegistryDeviceAuthenticationType
                .certificate_authority_signed_x509_certificate.value
            )
        }
    }
    poller = _completed_poller(None)
    operations.begin_revoke_certificates.return_value = poller

    assert (
        registry_device_provider.auth_revoke_certs(
            PROFILE,
            DEVICE,
            NS,
            RG,
        )
        is None
    )
    poller.result.assert_called_once_with()
    operations.get.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        authentication_profile_name=PROFILE,
    )
    operations.begin_revoke_certificates.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        authentication_profile_name=PROFILE,
    )


@pytest.mark.parametrize(
    "authentication_type",
    [
        "CertificateAuthority",
        "SymmetricKey",
        "SelfSignedX509Certificate",
        None,
    ],
)
def test_revoke_certificates_rejects_ineligible_profiles(
    registry_device_provider, authentication_type
):
    operations = registry_device_provider.client.registry_device_authentication_profiles
    operations.get.return_value = {
        "properties": {"authenticationType": authentication_type}
    }

    with pytest.raises(
        InvalidArgumentValueError,
        match="CertificateAuthoritySignedX509Certificate",
    ):
        registry_device_provider.auth_revoke_certs(
            PROFILE,
            DEVICE,
            NS,
            RG,
        )

    operations.get.assert_called_once()
    operations.begin_revoke_certificates.assert_not_called()


@pytest.mark.parametrize(
    "operation_group, list_method, show_method, child_name, name_argument",
    [
        (
            "registry_device_attributes",
            "attribute_list",
            "attribute_show",
            "reported",
            "attribute_name",
        ),
        (
            "registry_device_capabilities",
            "capability_list",
            "capability_show",
            "iotHub",
            "capability_name",
        ),
    ],
)
def test_attribute_and_capability_list_show_operation_selection(
    registry_device_provider,
    operation_group,
    list_method,
    show_method,
    child_name,
    name_argument,
):
    operations = getattr(registry_device_provider.client, operation_group)
    operations.list_by_device.return_value = iter([{"name": child_name}])
    operations.get.return_value = {"name": child_name}

    assert getattr(registry_device_provider, list_method)(DEVICE, NS, RG) == [
        {"name": child_name}
    ]
    assert getattr(registry_device_provider, show_method)(
        child_name,
        DEVICE,
        NS,
        RG,
    ) == {"name": child_name}

    operations.list_by_device.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
    )
    operations.get.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        **{name_argument: child_name},
    )


COMMAND_CASES = [
    (
        "adr_registry_device_create",
        "create",
        {
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
            "location": "eastus",
            "tags": {"environment": "test"},
            "enablement_state": "Disabled",
            "external_device_id": "external-42",
            "manufacturer": "Contoso",
            "model": "X100",
            "hardware_revision": "2.0",
            "software_revision": "3.0",
            "no_wait": True,
        },
    ),
    (
        "adr_registry_device_show",
        "show",
        {
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
        },
    ),
    (
        "adr_registry_device_list",
        "list",
        {"namespace_name": NS, "resource_group_name": RG},
    ),
    (
        "adr_registry_device_update",
        "update",
        {
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
            "tags": {"environment": "test"},
            "enablement_state": "Enabled",
            "manufacturer": "Contoso",
            "model": "X200",
            "hardware_revision": "2.1",
            "software_revision": "4.0",
            "no_wait": True,
        },
    ),
    (
        "adr_registry_device_delete",
        "delete",
        {
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
            "no_wait": True,
        },
    ),
    (
        "adr_registry_device_auth_list",
        "auth_list",
        {
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
        },
    ),
    (
        "adr_registry_device_auth_show",
        "auth_show",
        {
            "authentication_profile_name": PROFILE,
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
        },
    ),
    (
        "adr_registry_device_auth_show_keys",
        "auth_show_keys",
        {
            "authentication_profile_name": PROFILE,
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
        },
    ),
    (
        "adr_registry_device_auth_revoke_certs",
        "auth_revoke_certs",
        {
            "authentication_profile_name": PROFILE,
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
            "no_wait": True,
        },
    ),
    (
        "adr_registry_device_attribute_list",
        "attribute_list",
        {
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
        },
    ),
    (
        "adr_registry_device_attribute_show",
        "attribute_show",
        {
            "attribute_name": "reported",
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
        },
    ),
    (
        "adr_registry_device_capability_list",
        "capability_list",
        {
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
        },
    ),
    (
        "adr_registry_device_capability_show",
        "capability_show",
        {
            "capability_name": "iotHub",
            "registry_device_name": DEVICE,
            "namespace_name": NS,
            "resource_group_name": RG,
        },
    ),
]


@pytest.mark.parametrize("function_name, provider_method, kwargs", COMMAND_CASES)
def test_command_wrappers_delegate_exactly(
    function_name, provider_method, kwargs
):
    cmd = Mock()
    sentinel = object()
    with patch.object(
        commands_registry_device,
        "RegistryDeviceProvider",
    ) as provider_type:
        provider = provider_type.return_value
        getattr(provider, provider_method).return_value = sentinel

        result = getattr(commands_registry_device, function_name)(cmd, **kwargs)

    assert result is sentinel
    provider_type.assert_called_once_with(cmd)
    getattr(provider, provider_method).assert_called_once_with(**kwargs)


def test_command_wrappers_have_explicit_typed_parameters():
    for function_name, _, _ in COMMAND_CASES:
        parameters = inspect.signature(
            getattr(commands_registry_device, function_name)
        ).parameters
        assert not any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        assert all(
            parameter.annotation is not inspect.Parameter.empty
            for name, parameter in parameters.items()
            if name != "cmd"
        )


def test_show_wrapper_forwards_external_device_id():
    cmd = Mock()
    with patch.object(
        commands_registry_device, "RegistryDeviceProvider"
    ) as provider_type:
        commands_registry_device.adr_registry_device_show(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            external_device_id="external-42",
        )

    provider_type.return_value.show.assert_called_once_with(
        registry_device_name=None,
        namespace_name=NS,
        resource_group_name=RG,
        external_device_id="external-42",
    )


def test_attribute_create_defaults_to_user_reported(registry_device_provider):
    operations = registry_device_provider.client.registry_device_attributes
    operations.create_or_replace.return_value = {"name": "siteInfo"}

    result = registry_device_provider.attribute_create(
        attribute_name="siteInfo",
        registry_device_name=DEVICE,
        namespace_name=NS,
        resource_group_name=RG,
    )

    assert result == {"name": "siteInfo"}
    operations.create_or_replace.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        attribute_name="siteInfo",
        resource={"properties": {"reportedBy": DeviceAttributeReportedType.user.value}},
    )


def test_attribute_create_merges_property_bag_and_schema(registry_device_provider):
    operations = registry_device_provider.client.registry_device_attributes

    registry_device_provider.attribute_create(
        attribute_name="siteInfo",
        registry_device_name=DEVICE,
        namespace_name=NS,
        resource_group_name=RG,
        reported_by=DeviceAttributeReportedType.user.value,
        schema="https://contoso.com/schemas/site.json",
        properties='{"site": "plant-3", "rack": 12}',
    )

    resource = operations.create_or_replace.call_args.kwargs["resource"]
    assert resource["properties"] == {
        "site": "plant-3",
        "rack": 12,
        "reportedBy": DeviceAttributeReportedType.user.value,
        "schema": "https://contoso.com/schemas/site.json",
    }


@pytest.mark.parametrize("marker", ["", "@"])
def test_attribute_properties_accept_plain_and_at_prefixed_real_file(
    registry_device_provider, marker
):
    properties_path = (
        Path(__file__).parents[1]
        / "iothub"
        / "core"
        / "test_messaging_data.json"
    )

    registry_device_provider.attribute_create(
        attribute_name="siteInfo",
        registry_device_name=DEVICE,
        namespace_name=NS,
        resource_group_name=RG,
        properties=f"{marker}{properties_path}",
    )

    resource = (
        registry_device_provider.client.registry_device_attributes
        .create_or_replace.call_args.kwargs["resource"]
    )
    assert resource["properties"]["customJSONProperties"][0] == {
        "key": "customProperty1",
        "value": "customValue1",
    }
    assert resource["properties"]["reportedBy"] == "User"


def test_attribute_create_rejects_service_owned_reported_by_option(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_device_attributes

    with pytest.raises(InvalidArgumentValueError, match="service-owned"):
        registry_device_provider.attribute_create(
            attribute_name="agent",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            reported_by=DeviceAttributeReportedType.adu.value,
        )

    operations.create_or_replace.assert_not_called()


def test_attribute_create_rejects_service_owned_reported_by_in_properties(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_device_attributes

    with pytest.raises(InvalidArgumentValueError, match="service-owned"):
        registry_device_provider.attribute_create(
            attribute_name="agent",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            properties=(
                '{"reportedBy": "Microsoft.DeviceUpdate", '
                '"deviceClassId": "abc"}'
            ),
        )

    operations.create_or_replace.assert_not_called()


def test_attribute_create_rejects_unknown_reported_by_in_properties(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_device_attributes

    with pytest.raises(InvalidArgumentValueError, match="must be 'User'"):
        registry_device_provider.attribute_create(
            attribute_name="site",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            properties='{"reportedBy": "Other.Service"}',
        )

    operations.create_or_replace.assert_not_called()


def test_attribute_create_accepts_user_reported_by_in_properties(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_device_attributes
    registry_device_provider.attribute_create(
        attribute_name="site",
        registry_device_name=DEVICE,
        namespace_name=NS,
        resource_group_name=RG,
        properties='{"reportedBy": "User", "rack": 12}',
    )

    resource = operations.create_or_replace.call_args.kwargs["resource"]
    assert resource["properties"] == {"reportedBy": "User", "rack": 12}


@pytest.mark.parametrize("reported_by", ["user", "Microsoft.DeviceRegistry", ""])
def test_attribute_create_rejects_unknown_reported_by(
    registry_device_provider, reported_by
):
    with pytest.raises(InvalidArgumentValueError):
        registry_device_provider.attribute_create(
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            reported_by=reported_by,
        )

    registry_device_provider.client.registry_device_attributes.create_or_replace.assert_not_called()


@pytest.mark.parametrize("properties", ['["a", "b"]', '"just-a-string"', "42"])
def test_attribute_create_rejects_non_object_properties(
    registry_device_provider, properties
):
    with pytest.raises(InvalidArgumentValueError):
        registry_device_provider.attribute_create(
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            properties=properties,
        )


@pytest.mark.parametrize("properties", ["{bad", '{"a":}', '{"a": 1'])
def test_attribute_create_rejects_malformed_json(
    registry_device_provider, properties
):
    with pytest.raises(InvalidArgumentValueError):
        registry_device_provider.attribute_create(
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            properties=properties,
        )


def test_attribute_delete_is_synchronous(registry_device_provider):
    operations = registry_device_provider.client.registry_device_attributes
    operations.delete.return_value = None

    assert (
        registry_device_provider.attribute_delete(
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
        )
        is None
    )

    operations.delete.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        attribute_name="siteInfo",
    )
    assert not hasattr(operations, "begin_delete")


def test_attribute_command_wrappers_delegate(fixture_cmd):
    with patch.object(
        commands_registry_device, "RegistryDeviceProvider"
    ) as provider_class:
        provider = provider_class.return_value

        commands_registry_device.adr_registry_device_attribute_create(
            fixture_cmd,
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            reported_by=DeviceAttributeReportedType.user.value,
            schema="https://contoso.com/schemas/site.json",
            properties='{"site": "plant-3"}',
        )
        provider.attribute_create.assert_called_once_with(
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
            reported_by=DeviceAttributeReportedType.user.value,
            schema="https://contoso.com/schemas/site.json",
            properties='{"site": "plant-3"}',
        )

        commands_registry_device.adr_registry_device_attribute_delete(
            fixture_cmd,
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
        )
        provider.attribute_delete.assert_called_once_with(
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
        )


def test_attribute_create_does_not_warn_for_user_reported(
    registry_device_provider, caplog
):
    with caplog.at_level("WARNING"):
        registry_device_provider.attribute_create(
            attribute_name="siteInfo",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
        )

    assert "Azure Device Update" not in caplog.text


@pytest.mark.parametrize(
    "alias", ["software-update", "software_update", "softwareUpdate", "Software-Update"]
)
def test_attribute_show_falls_back_to_adu_attribute_for_alias(
    registry_device_provider, alias, caplog
):
    """PM-requested alias: `-n software-update` resolves to the ADU attribute."""
    operations = registry_device_provider.client.registry_device_attributes
    expected = {"name": ADU_ATTRIBUTE_NAME}
    operations.get.side_effect = [ResourceNotFoundError("nope"), expected]

    with caplog.at_level("WARNING"):
        assert (
            registry_device_provider.attribute_show(alias, DEVICE, NS, RG) == expected
        )

    # The literal name is always tried first, then the canonical ADU name.
    assert [
        call.kwargs["attribute_name"] for call in operations.get.call_args_list
    ] == [alias, ADU_ATTRIBUTE_NAME]
    assert ADU_ATTRIBUTE_NAME in caplog.text


def test_attribute_show_prefers_a_real_attribute_over_the_alias(
    registry_device_provider, caplog
):
    """A customer-authored attribute literally named software-update must win."""
    operations = registry_device_provider.client.registry_device_attributes
    expected = {"name": "software-update", "properties": {"reportedBy": "User"}}
    operations.get.return_value = expected

    with caplog.at_level("WARNING"):
        assert (
            registry_device_provider.attribute_show(
                "software-update", DEVICE, NS, RG
            )
            == expected
        )

    operations.get.assert_called_once()
    assert caplog.text == ""


def test_attribute_show_does_not_alias_unrelated_missing_names(
    registry_device_provider,
):
    operations = registry_device_provider.client.registry_device_attributes
    operations.get.side_effect = ResourceNotFoundError("nope")

    with pytest.raises(ResourceNotFoundError):
        registry_device_provider.attribute_show("firmware", DEVICE, NS, RG)

    operations.get.assert_called_once()


def test_attribute_list_and_delete_do_not_alias(registry_device_provider):
    """The alias is scoped to `show` only."""
    operations = registry_device_provider.client.registry_device_attributes
    operations.delete.side_effect = ResourceNotFoundError("nope")

    with pytest.raises(ResourceNotFoundError):
        registry_device_provider.attribute_delete(
            attribute_name="software-update",
            registry_device_name=DEVICE,
            namespace_name=NS,
            resource_group_name=RG,
        )

    operations.delete.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NS,
        registry_device_name=DEVICE,
        attribute_name="software-update",
    )
