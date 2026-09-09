# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64
from unittest.mock import MagicMock

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    BadRequestError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)
from azure.core import MatchConditions

import azext_iot.operations.dps as subject
from azext_iot.common.shared import (
    AllocationType,
    AttestationType,
    ReprovisionType,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        (
            None,
            {"updateHubAssignment": True, "migrateDeviceData": True},
        ),
        (
            ReprovisionType.reprovisionandmigratedata.value,
            {"updateHubAssignment": True, "migrateDeviceData": True},
        ),
        (
            ReprovisionType.reprovisionandresetdata.value,
            {"updateHubAssignment": True, "migrateDeviceData": False},
        ),
        (
            ReprovisionType.never.value,
            {"updateHubAssignment": False, "migrateDeviceData": False},
        ),
    ],
)
def test_reprovision_policy_is_raw_mapping(value, expected):
    assert subject._get_reprovision_policy(value) == expected


def test_reprovision_policy_rejects_unknown_value():
    with pytest.raises(InvalidArgumentValueError, match="Invalid"):
        subject._get_reprovision_policy("unknown")


def test_twin_helpers_build_and_preserve_raw_mappings():
    assert subject._get_twin_collection("") == {}
    assert subject._get_twin_collection(None) == {}
    assert subject._get_twin_collection('{"site": "one"}') == {"site": "one"}
    assert subject._get_initial_twin('{"tag": 1}', '{"desired": 2}') == {
        "tags": {"tag": 1},
        "properties": {"desired": {"desired": 2}},
    }
    record = {
        "initialTwin": {
            "tags": {"site": "one", "$metadata": {}},
            "properties": {
                "desired": {"interval": 5, "$version": 3}
            },
        }
    }
    assert subject._get_updated_inital_twin(record) == {
        "tags": {"site": "one"},
        "properties": {"desired": {"interval": 5}},
    }


def test_drop_none_and_readonly_enrollment_fields():
    enrollment = {
        "etag": "etag",
        "createdDateTimeUtc": "now",
        "registrationState": {},
        "optional": None,
        "attestation": {
            "type": "x509",
            "x509": {
                "clientCertificates": {
                    "primary": {"certificate": "cert", "info": {"version": 3}}
                }
            },
        },
        "initialTwin": {
            "tags": {"site": "one", "metadata": {}},
            "properties": {"desired": {"interval": 5, "version": 2}},
        },
        "optionalDeviceInformation": {
            "manufacturer": "Contoso",
            "count": 1,
            "metadata": {},
            "version": 2,
        },
    }

    result = subject._drop_readonly_enrollment(enrollment)

    assert {"etag", "createdDateTimeUtc", "registrationState", "optional"}.isdisjoint(result)
    assert result["attestation"]["x509"]["clientCertificates"]["primary"] == {
        "certificate": "cert"
    }
    assert result["initialTwin"]["tags"] == {"site": "one"}
    assert result["initialTwin"]["properties"]["desired"] == {"interval": 5}
    assert result["optionalDeviceInformation"] == {
        "manufacturer": "Contoso"
    }


def test_etag_arguments_use_azure_core_match_conditions():
    assert subject._etag_arguments() == {
        "match_condition": MatchConditions.IfPresent
    }
    assert subject._etag_arguments("etag") == {
        "etag": "etag",
        "match_condition": MatchConditions.IfNotModified,
    }


def test_modeless_query_follows_continuation_and_honors_top():
    query = MagicMock()

    def response(*_args, **kwargs):
        callback = kwargs["cls"]
        continuation = kwargs.get("x_ms_continuation")
        if continuation is None:
            return callback(None, [{"id": 1}, {"id": 2}], {"x-ms-continuation": "next"})
        return callback(None, [{"id": 3}], {})

    query.side_effect = response
    assert subject._execute_dps_query(query, [{"query": "SELECT *"}]) == [
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]

    query.reset_mock(side_effect=True)
    query.side_effect = response
    assert subject._execute_dps_query(query, ["group"], top=2) == [
        {"id": 1},
        {"id": 2},
    ]
    assert query.call_count == 1


def test_adr_certificate_reference_requires_complete_authority():
    assert not subject._validate_adr_certificate_reference()
    assert subject._validate_adr_certificate_reference(
        "namespace", "ca", "policy"
    ) == {
        "namespaceName": "namespace",
        "certificateAuthorityName": "ca",
        "certificatePolicyName": "policy",
    }
    assert subject._validate_adr_certificate_reference(
        "namespace", "ca", credential_policy_name="legacy-alias"
    )["certificatePolicyName"] == "legacy-alias"
    with pytest.raises(RequiredArgumentMissingError, match="together"):
        subject._validate_adr_certificate_reference(
            adr_namespace="namespace", adr_certificate_policy_name="policy"
        )


def test_x509_mapping_helpers(mocker):
    mocker.patch.object(subject, "open_certificate", return_value="CERT")
    assert subject._get_certificate_info(None) is None
    assert subject._get_certificate_info("cert.pem") == {"certificate": "CERT"}
    with pytest.raises(RequiredArgumentMissingError, match="certificate path"):
        subject._get_attestation_with_x509_client_cert(None, None)

    client = subject._get_attestation_with_x509_client_cert("primary.pem", None)
    assert client == {
        "type": "x509",
        "x509": {
            "clientCertificates": {"primary": {"certificate": "CERT"}}
        },
    }
    signing = subject._get_attestation_with_x509_signing_cert(
        "primary.pem", None
    )
    assert signing["x509"]["signingCertificates"]["primary"]["certificate"] == "CERT"
    ca = subject._get_attestation_with_x509_ca_cert("root", "secondary")
    assert ca["x509"]["caReferences"] == {
        "primary": "root",
        "secondary": "secondary",
    }


def test_x509_update_helpers_add_remove_and_fallback(mocker):
    mocker.patch.object(subject, "open_certificate", return_value="NEW")
    client = {
        "type": "x509",
        "x509": {
            "clientCertificates": {
                "primary": {"certificate": "OLD"},
                "secondary": {"certificate": "OLD2"},
            }
        },
    }
    result = subject._get_updated_attestation_with_x509_client_cert(
        client, "new.pem", None, False, True
    )
    assert result["x509"]["clientCertificates"] == {
        "primary": {"certificate": "NEW"}
    }

    signing = subject._get_updated_attestation_with_x509_signing_cert(
        {"type": "x509", "x509": {"signingCertificates": {"primary": {}}}},
        None,
        "secondary.pem",
        True,
        False,
    )
    assert signing["x509"]["signingCertificates"] == {
        "secondary": {"certificate": "NEW"}
    }
    fallback = subject._get_updated_attestation_with_x509_signing_cert(
        {"type": "x509", "x509": {}}, "new.pem", None, False, False
    )
    assert "signingCertificates" in fallback["x509"]

    ca = subject._get_updated_attestation_with_x509_ca_cert(
        {"type": "x509", "x509": {"caReferences": {"primary": "old"}}},
        "new",
        "secondary",
        True,
        False,
    )
    assert ca["x509"]["caReferences"] == {
        "primary": "new",
        "secondary": "secondary",
    }
    fallback_ca = subject._get_updated_attestation_with_x509_ca_cert(
        {"type": "x509", "x509": {}}, "root", None, False, False
    )
    assert fallback_ca["x509"]["caReferences"] == {"primary": "root"}


@pytest.mark.parametrize(
    "helper, attestation",
    [
        (
            subject._can_remove_primary_certificate,
            {
                "x509": {
                    "signingCertificates": {
                        "primary": {},
                        "secondary": None,
                    }
                }
            },
        ),
        (
            subject._can_remove_secondary_certificate,
            {
                "x509": {
                    "caReferences": {
                        "primary": None,
                        "secondary": "secondary",
                    }
                }
            },
        ),
    ],
)
def test_certificate_removal_requires_the_other_certificate(helper, attestation):
    assert helper(False, attestation) is True
    assert helper(True, attestation) is False


@pytest.mark.parametrize(
    "attestation_type, values, message",
    [
        ("tpm", {"certificate_path": "cert"}, "certificate"),
        ("tpm", {"remove_certificate": True}, "remove"),
        ("tpm", {"primary_key": "key"}, "key"),
        ("x509", {"endorsement_key": "key"}, "endorsement"),
        ("x509", {"secondary_key": "key"}, "key"),
        ("symmetricKey", {"certificate_path": "cert"}, "certificate"),
        ("symmetricKey", {"remove_secondary_certificate": True}, "remove"),
        ("symmetricKey", {"endorsement_key": "key"}, "endorsement"),
    ],
)
def test_attestation_update_validation(attestation_type, values, message):
    arguments = {
        "endorsement_key": None,
        "certificate_path": None,
        "secondary_certificate_path": None,
        "remove_certificate": False,
        "remove_secondary_certificate": False,
        "primary_key": None,
        "secondary_key": None,
        **values,
    }
    with pytest.raises(ArgumentUsageError, match=message):
        subject._validate_arguments_for_attestation_mechanism(
            attestation_type, **arguments
        )


def test_symmetric_attestation_key_update_is_valid():
    subject._validate_arguments_for_attestation_mechanism(
        AttestationType.symmetricKey.value,
        None,
        None,
        None,
        False,
        False,
        "primary",
        "secondary",
    )


@pytest.mark.parametrize(
    "policy, hub_name, hubs, webhook, version, error_type",
    [
        ("static", "hub", None, None, None, MutuallyExclusiveArgumentError),
        ("unknown", None, ["hub"], None, None, RequiredArgumentMissingError),
        ("static", None, None, None, None, RequiredArgumentMissingError),
        ("static", None, ["one", "two"], None, None, InvalidArgumentValueError),
        ("custom", None, None, None, None, RequiredArgumentMissingError),
        (None, None, ["hub"], None, None, RequiredArgumentMissingError),
    ],
)
def test_allocation_policy_validation_errors(
    policy, hub_name, hubs, webhook, version, error_type
):
    with pytest.raises(error_type):
        subject._validate_allocation_policy_for_enrollment(
            policy, hub_name, hubs, webhook, version
        )


def test_allocation_policy_uses_current_mapping():
    current = {
        "allocationPolicy": AllocationType.custom.value,
        "iotHubs": ["hub"],
        "customAllocationDefinition": {
            "webhookUrl": "https://example.test",
            "apiVersion": "2026-11-02-preview",
        },
    }
    subject._validate_allocation_policy_for_enrollment(
        None, None, None, None, None, current_enrollment=current
    )


def test_compute_device_key_paths(mocker):
    key = base64.b64encode(b"secret").decode()
    assert subject.iot_dps_compute_device_key(
        MagicMock(), "registration", symmetric_key=key
    )
    with pytest.raises(RequiredArgumentMissingError):
        subject.iot_dps_compute_device_key(MagicMock(), "registration")

    mocker.patch.object(subject, "DPSDiscovery")
    resolver = mocker.patch.object(subject, "SdkResolver")
    resolver.return_value.get_sdk.return_value.enrollment_group.get_attestation_mechanism.return_value = {
        "type": "tpm"
    }
    with pytest.raises(BadRequestError, match="symmetric key"):
        subject.iot_dps_compute_device_key(
            MagicMock(), "registration", "group", "dps"
        )


def _mock_sdk(mocker):
    mocker.patch.object(subject, "DPSDiscovery")
    resolver = mocker.patch.object(subject, "SdkResolver")
    return resolver.return_value.get_sdk.return_value


def test_individual_update_covers_tpm_and_new_certificate_reference(mocker):
    sdk = _mock_sdk(mocker)
    sdk.individual_enrollment.get.return_value = {
        "etag": "old",
        "attestation": {
            "type": "tpm",
            "tpm": {"endorsementKey": "old"},
        },
        "allocationPolicy": "hashed",
        "initialTwin": {"tags": {}, "properties": {"desired": {}}},
    }

    subject.iot_dps_device_enrollment_update(
        MagicMock(),
        "enrollment",
        dps_name="dps",
        endorsement_key="new",
        device_id="device",
        provisioning_status="enabled",
        reprovision_policy="never",
        edge_enabled=True,
        device_information='{"serial": "one"}',
        adr_namespace="namespace",
        adr_ca_name="ca",
        adr_certificate_policy_name="policy",
    )

    body = sdk.individual_enrollment.create_or_update.call_args.args[1]
    assert body["attestation"]["tpm"]["endorsementKey"] == "new"
    assert body["deviceId"] == "device"
    assert body["optionalDeviceInformation"] == {"serial": "one"}
    assert body["namespaceName"] == "namespace"


def test_individual_update_covers_symmetric_and_custom_allocation(mocker):
    sdk = _mock_sdk(mocker)
    sdk.individual_enrollment.get.return_value = {
        "attestation": {"type": "symmetricKey"},
        "allocationPolicy": "custom",
        "customAllocationDefinition": {
            "webhookUrl": "https://old",
            "apiVersion": "old",
        },
        "namespaceName": "namespace",
        "certificateAuthorityName": "ca",
        "certificatePolicyName": "old-policy",
        "initialTwin": {"tags": {}, "properties": {"desired": {}}},
    }
    sdk.individual_enrollment.get_attestation_mechanism.return_value = {
        "type": "symmetricKey",
        "symmetricKey": {"primaryKey": "old", "secondaryKey": "old"},
    }

    subject.iot_dps_device_enrollment_update(
        MagicMock(),
        "enrollment",
        dps_name="dps",
        primary_key="primary",
        secondary_key="secondary",
        webhook_url="https://new",
        api_version="new",
        adr_certificate_policy_name="new-policy",
    )

    body = sdk.individual_enrollment.create_or_update.call_args.args[1]
    assert body["attestation"]["symmetricKey"] == {
        "primaryKey": "primary",
        "secondaryKey": "secondary",
    }
    assert body["customAllocationDefinition"] == {
        "webhookUrl": "https://new",
        "apiVersion": "new",
    }
    assert body["namespaceName"] == "namespace"
    assert body["certificateAuthorityName"] == "ca"
    assert body["certificatePolicyName"] == "new-policy"


@pytest.mark.parametrize(
    "attestation, kwargs, expected_container",
    [
        (
            {
                "type": "x509",
                "x509": {
                    "signingCertificates": {
                        "primary": {"certificate": "old"},
                        "secondary": {"certificate": "old"},
                    }
                },
            },
            {"certificate_path": "new.pem"},
            "signingCertificates",
        ),
        (
            {
                "type": "x509",
                "x509": {
                    "caReferences": {
                        "primary": "old",
                        "secondary": "old-secondary",
                    }
                },
            },
            {"root_ca_name": "new-ca"},
            "caReferences",
        ),
    ],
)
def test_group_update_covers_both_x509_authority_forms(
    mocker, attestation, kwargs, expected_container
):
    sdk = _mock_sdk(mocker)
    sdk.enrollment_group.get.return_value = {
        "attestation": attestation,
        "allocationPolicy": "hashed",
        "initialTwin": {"tags": {}, "properties": {"desired": {}}},
    }
    mocker.patch.object(subject, "open_certificate", return_value="CERT")

    subject.iot_dps_device_enrollment_group_update(
        MagicMock(), "group", dps_name="dps", **kwargs
    )

    body = sdk.enrollment_group.create_or_update.call_args.args[1]
    assert expected_container in body["attestation"]["x509"]


def test_group_update_covers_symmetric_fields_and_reference(mocker):
    sdk = _mock_sdk(mocker)
    sdk.enrollment_group.get.return_value = {
        "attestation": {"type": "symmetricKey"},
        "allocationPolicy": "hashed",
        "initialTwin": {"tags": {}, "properties": {"desired": {}}},
    }
    sdk.enrollment_group.get_attestation_mechanism.return_value = {
        "type": "symmetricKey",
        "symmetricKey": {"primaryKey": "old", "secondaryKey": "old"},
    }

    subject.iot_dps_device_enrollment_group_update(
        MagicMock(),
        "group",
        dps_name="dps",
        primary_key="primary",
        secondary_key="secondary",
        iot_hub_host_name="hub",
        provisioning_status="enabled",
        reprovision_policy="never",
        edge_enabled=True,
        adr_namespace="namespace",
        adr_ca_name="ca",
        adr_certificate_policy_name="policy",
    )

    body = sdk.enrollment_group.create_or_update.call_args.args[1]
    assert body["iotHubs"] == ["hub"]
    assert body["capabilities"] == {"iotEdge": True}
    assert body["certificatePolicyName"] == "policy"


@pytest.mark.parametrize(
    "function_name, operation_path, kwargs",
    [
        (
            "iot_dps_device_enrollment_list",
            "individual_enrollment.query",
            {},
        ),
        (
            "iot_dps_device_enrollment_get",
            "individual_enrollment.get",
            {"enrollment_id": "enrollment"},
        ),
        (
            "iot_dps_device_enrollment_delete",
            "individual_enrollment.delete",
            {"enrollment_id": "enrollment"},
        ),
        (
            "iot_dps_device_enrollment_group_list",
            "enrollment_group.query",
            {},
        ),
        (
            "iot_dps_device_enrollment_group_get",
            "enrollment_group.get",
            {"enrollment_id": "group"},
        ),
        (
            "iot_dps_device_enrollment_group_delete",
            "enrollment_group.delete",
            {"enrollment_id": "group"},
        ),
        (
            "iot_dps_registration_list",
            "device_registration_state.query",
            {"enrollment_id": "group"},
        ),
        (
            "iot_dps_registration_get",
            "device_registration_state.get",
            {"registration_id": "registration"},
        ),
        (
            "iot_dps_registration_delete",
            "device_registration_state.delete",
            {"registration_id": "registration"},
        ),
    ],
)
def test_service_http_errors_use_shared_handler(
    mocker, function_name, operation_path, kwargs
):
    sdk = _mock_sdk(mocker)
    operation = sdk
    for part in operation_path.split("."):
        operation = getattr(operation, part)
    operation.side_effect = subject.HttpResponseError("failure")
    handler = mocker.patch.object(
        subject, "handle_service_exception", return_value="translated"
    )

    getattr(subject, function_name)(
        MagicMock(), dps_name="dps", **kwargs
    )

    handler.assert_called_once()


def test_get_show_keys_warning_and_symmetric_replacement(mocker, caplog):
    sdk = _mock_sdk(mocker)
    sdk.individual_enrollment.get.side_effect = [
        {"attestation": {"type": "x509"}},
        {"attestation": {"type": "symmetricKey"}},
    ]
    sdk.individual_enrollment.get_attestation_mechanism.return_value = {
        "type": "symmetricKey",
        "symmetricKey": {"primaryKey": "key"},
    }

    subject.iot_dps_device_enrollment_get(
        MagicMock(), "one", dps_name="dps", show_keys=True
    )
    result = subject.iot_dps_device_enrollment_get(
        MagicMock(), "two", dps_name="dps", show_keys=True
    )

    assert "only supported for symmetric key" in caplog.text
    assert result["attestation"]["symmetricKey"]["primaryKey"] == "key"


def test_connection_string_listing_and_key_selection(mocker, caplog):
    discovery = mocker.patch.object(subject, "DPSDiscovery").return_value
    active = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/"
              "Microsoft.Devices/provisioningServices/active",
        "name": "active",
        "properties": {
            "state": "Active",
            "serviceOperationsHostName": "active.example.test",
        },
    }
    inactive = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/"
              "Microsoft.Devices/provisioningServices/inactive",
        "name": "inactive",
        "properties": {
            "state": "Suspended",
            "serviceOperationsHostName": "inactive.example.test",
        },
    }
    discovery.get_resources.return_value = [active, inactive]
    discovery.get_policies.return_value = [
        {
            "keyName": "owner",
            "primaryKey": "primary",
            "secondaryKey": "secondary",
        }
    ]

    result = subject.iot_dps_connection_string_show(
        MagicMock(), show_all=True, key_type="secondary"
    )

    assert result[0]["name"] == "active"
    assert "secondary" in result[0]["connectionString"][0]
    assert "skipped" in caplog.text


def test_connection_string_single_and_missing_resource(mocker):
    discovery = mocker.patch.object(subject, "DPSDiscovery").return_value
    resource = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/"
              "Microsoft.Devices/provisioningServices/dps",
        "name": "dps",
        "properties": {"serviceOperationsHostName": "dps.example.test"},
    }
    discovery.find_resource.side_effect = [resource, None]
    discovery.find_policy.return_value = {
        "keyName": "owner",
        "primaryKey": "primary",
        "secondaryKey": "secondary",
    }

    result = subject.iot_dps_connection_string_show(
        MagicMock(), dps_name="dps"
    )
    assert "primary" in result["connectionString"]
    assert (
        subject.iot_dps_connection_string_show(
            MagicMock(), dps_name="missing"
        )
        is None
    )


def test_group_show_keys_warning(mocker, caplog):
    sdk = _mock_sdk(mocker)
    sdk.enrollment_group.get.return_value = {
        "attestation": {"type": "x509"}
    }
    subject.iot_dps_device_enrollment_group_get(
        MagicMock(), "group", dps_name="dps", show_keys=True
    )
    assert "only supported for symmetric key enrollment groups" in caplog.text


def test_group_create_rejects_mixed_certificate_sources(mocker):
    _mock_sdk(mocker)
    with pytest.raises(MutuallyExclusiveArgumentError):
        subject.iot_dps_device_enrollment_group_create(
            MagicMock(),
            "group",
            dps_name="dps",
            certificate_path="certificate.pem",
            root_ca_name="root",
        )


def test_group_update_rejects_mixed_certificate_sources(mocker):
    sdk = _mock_sdk(mocker)
    sdk.enrollment_group.get.return_value = {
        "attestation": {
            "type": "x509",
            "x509": {"signingCertificates": {"primary": {}}},
        },
        "initialTwin": {},
    }
    with pytest.raises(MutuallyExclusiveArgumentError):
        subject.iot_dps_device_enrollment_group_update(
            MagicMock(),
            "group",
            dps_name="dps",
            certificate_path="certificate.pem",
            root_ca_name="root",
        )


@pytest.mark.parametrize(
    "remove_primary, remove_secondary, attestation, message",
    [
        (
            True,
            True,
            {
                "type": "x509",
                "x509": {"signingCertificates": {"primary": {}, "secondary": {}}},
            },
            "at least one certificate$",
        ),
        (
            True,
            False,
            {
                "type": "x509",
                "x509": {"signingCertificates": {"primary": {}, "secondary": None}},
            },
            "only primary",
        ),
        (
            False,
            True,
            {
                "type": "x509",
                "x509": {"caReferences": {"primary": None, "secondary": "ca"}},
            },
            "only secondary",
        ),
    ],
)
def test_group_update_rejects_removing_required_certificate(
    mocker, remove_primary, remove_secondary, attestation, message
):
    sdk = _mock_sdk(mocker)
    sdk.enrollment_group.get.return_value = {
        "attestation": attestation,
        "initialTwin": {},
    }
    with pytest.raises(RequiredArgumentMissingError, match=message):
        subject.iot_dps_device_enrollment_group_update(
            MagicMock(),
            "group",
            dps_name="dps",
            remove_certificate=remove_primary,
            remove_secondary_certificate=remove_secondary,
        )


@pytest.mark.parametrize(
    "function_name, setup",
    [
        (
            "iot_dps_device_enrollment_update",
            lambda sdk: setattr(
                sdk.individual_enrollment.get,
                "side_effect",
                subject.HttpResponseError("failure"),
            ),
        ),
        (
            "iot_dps_device_enrollment_group_update",
            lambda sdk: setattr(
                sdk.enrollment_group.get,
                "side_effect",
                subject.HttpResponseError("failure"),
            ),
        ),
    ],
)
def test_update_http_errors_use_shared_handler(
    mocker, function_name, setup
):
    sdk = _mock_sdk(mocker)
    setup(sdk)
    handler = mocker.patch.object(subject, "handle_service_exception")
    getattr(subject, function_name)(
        MagicMock(), "record", dps_name="dps"
    )
    handler.assert_called_once()


def test_group_create_http_error_uses_shared_handler(mocker):
    sdk = _mock_sdk(mocker)
    sdk.enrollment_group.create_or_update.side_effect = (
        subject.HttpResponseError("failure")
    )
    handler = mocker.patch.object(subject, "handle_service_exception")
    subject.iot_dps_device_enrollment_group_create(
        MagicMock(), "group", dps_name="dps"
    )
    handler.assert_called_once()


def test_compute_device_key_online_success_and_http_error(mocker):
    key = base64.b64encode(b"secret").decode()
    sdk = _mock_sdk(mocker)
    sdk.enrollment_group.get_attestation_mechanism.return_value = {
        "type": "symmetricKey",
        "symmetricKey": {"primaryKey": key},
    }
    assert subject.iot_dps_compute_device_key(
        MagicMock(), "registration", "group", "dps"
    )

    sdk.enrollment_group.get_attestation_mechanism.side_effect = (
        subject.HttpResponseError("failure")
    )
    with pytest.raises(subject.AzureResponseError):
        subject.iot_dps_compute_device_key(
            MagicMock(), "registration", "group", "dps"
        )


def test_connection_string_listing_missing_and_policy_failure(mocker, caplog):
    discovery = mocker.patch.object(subject, "DPSDiscovery").return_value
    discovery.get_resources.side_effect = [
        None,
        [
            {
                "id": "/subscriptions/sub/resourceGroups/rg/providers/"
                      "Microsoft.Devices/provisioningServices/dps",
                "name": "dps",
                "properties": {
                    "state": "Active",
                    "serviceOperationsHostName": "dps.example.test",
                },
            }
        ],
    ]
    with pytest.raises(subject.ResourceNotFoundError):
        subject.iot_dps_connection_string_show(MagicMock())

    discovery.find_policy.side_effect = RuntimeError("missing policy")
    assert subject.iot_dps_connection_string_show(MagicMock()) == []
    assert "does not have the target policy" in caplog.text


def test_certificate_helper_secondary_removals_and_alternate_checks():
    signing = {
        "x509": {
            "signingCertificates": {
                "primary": {"certificate": "one"},
                "secondary": {"certificate": "two"},
            }
        }
    }
    subject._get_updated_attestation_with_x509_signing_cert(
        signing, None, None, False, True
    )
    assert "secondary" not in signing["x509"]["signingCertificates"]

    ca = {"x509": {"caReferences": {"primary": "one", "secondary": "two"}}}
    subject._get_updated_attestation_with_x509_ca_cert(
        ca, None, None, False, True
    )
    assert "secondary" not in ca["x509"]["caReferences"]

    assert not subject._can_remove_primary_certificate(
        True, {"x509": {"caReferences": {"secondary": None}}}
    )
    assert not subject._can_remove_secondary_certificate(
        True, {"x509": {"signingCertificates": {"primary": None}}}
    )
