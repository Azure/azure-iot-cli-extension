# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from http.client import IncompleteRead
from unittest.mock import MagicMock, patch

import pytest
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)

from azext_iot import _factory
from azext_iot.adr.providers.software_update import SoftwareUpdateProvider

NAMESPACE = "test-namespace"
RG = "test-rg"
ENDPOINT = "updates.example.test"
PROVIDER = "Contoso"
UPDATE = "Thermostat"
VERSION = "1.0"


def _namespace(service_address=f"https://{ENDPOINT}"):
    return {
        "properties": {
            "updating": {
                "endpoints": {
                    "software-updates": {
                        "endpointType": "Microsoft.DeviceUpdate/updateInstances",
                        "linkingState": "Succeeded",
                        "serviceAddress": service_address,
                    },
                    "other": {
                        "endpointType": "Microsoft.Devices/IotHubs",
                        "serviceAddress": "hub.example.test",
                    },
                }
            }
        }
    }


@pytest.fixture()
def provider():
    with patch(
        "azext_iot.adr.providers.software_update.adr_service_factory"
    ) as registry_factory, patch(
        "azext_iot.adr.providers.software_update."
        "adr_software_update_data_service_factory"
    ) as data_factory:
        registry_client = MagicMock()
        data_client = MagicMock()
        registry_factory.return_value = registry_client
        data_factory.return_value = data_client
        registry_client.namespaces.get.return_value = _namespace()
        value = SoftwareUpdateProvider(MagicMock(cli_ctx=MagicMock()))
        value.client = data_client
        yield value


def test_provider_uses_registry_and_data_factories():
    cmd = MagicMock(cli_ctx=MagicMock())
    with patch(
        "azext_iot.adr.providers.software_update.adr_service_factory"
    ) as registry_factory, patch(
        "azext_iot.adr.providers.software_update."
        "adr_software_update_data_service_factory"
    ) as data_factory:
        value = SoftwareUpdateProvider(cmd)

    assert value.registry_client is registry_factory.return_value
    assert value.client is None
    registry_factory.assert_called_once_with(cmd.cli_ctx)
    data_factory.assert_not_called()


def test_wait_uses_standard_sdk_poller(provider):
    poller = MagicMock()
    with patch(
        "azext_iot.adr.providers.software_update."
        "provider_base.wait_for_terminal_state",
        return_value={"status": "Succeeded"},
    ) as wait:
        assert provider._await_terminal(poller, wait_sec=0) == {
            "status": "Succeeded"
        }

    wait.assert_called_once_with(poller, wait_sec=0)


@pytest.mark.parametrize(
    "service_address, expected",
    [
        (f"https://{ENDPOINT}", ENDPOINT),
        (f"http://{ENDPOINT}/", ENDPOINT),
        (ENDPOINT, ENDPOINT),
        (f"{ENDPOINT}:443", f"{ENDPOINT}:443"),
    ],
)
def test_resolve_endpoint_normalizes_service_address(
    provider, service_address, expected
):
    provider.registry_client.namespaces.get.return_value = _namespace(service_address)

    assert provider._resolve_endpoint(NAMESPACE, RG) == expected
    provider.registry_client.namespaces.get.assert_called_once_with(
        resource_group_name=RG,
        namespace_name=NAMESPACE,
    )


def test_resolve_endpoint_requires_software_update_link(provider):
    provider.registry_client.namespaces.get.return_value = {
        "properties": {"updating": {"endpoints": {}}}
    }

    with pytest.raises(ResourceNotFoundError, match="has no Software Updates link"):
        provider._resolve_endpoint(NAMESPACE, RG)


def test_resolve_endpoint_rejects_multiple_links(provider):
    namespace = _namespace()
    namespace["properties"]["updating"]["endpoints"]["second"] = {
        "endpointType": "microsoft.deviceupdate/updateinstances",
        "linkingState": "Succeeded",
        "serviceAddress": "second.example.test",
    }
    provider.registry_client.namespaces.get.return_value = namespace

    with pytest.raises(
        AzureResponseError, match="multiple ready Software Updates links"
    ):
        provider._resolve_endpoint(NAMESPACE, RG)


def test_resolve_endpoint_requires_ready_service_address(provider):
    provider.registry_client.namespaces.get.return_value = _namespace(None)

    with pytest.raises(AzureResponseError, match="No Software Updates link is ready"):
        provider._resolve_endpoint(NAMESPACE, RG)


def test_resolve_endpoint_ignores_failed_link_when_one_is_ready(provider):
    namespace = _namespace()
    namespace["properties"]["updating"]["endpoints"]["failed"] = {
        "endpointType": "Microsoft.DeviceUpdate/updateInstances",
        "linkingState": "Failed",
        "serviceAddress": "failed.example.test",
    }
    provider.registry_client.namespaces.get.return_value = namespace

    assert provider._resolve_endpoint(NAMESPACE, RG) == ENDPOINT


def test_resolve_endpoint_surfaces_link_failure(provider):
    provider.registry_client.namespaces.get.return_value = {
        "properties": {
            "updating": {
                "endpoints": {
                    "software-updates": {
                        "endpointType": "Microsoft.DeviceUpdate/updateInstances",
                        "linkingState": "Failed",
                        "linkingError": {
                            "code": "LinkFailed",
                            "message": "The service rejected the link.",
                        },
                    }
                }
            }
        }
    }

    with pytest.raises(
        AzureResponseError, match="Failed state.*service rejected"
    ):
        provider._resolve_endpoint(NAMESPACE, RG)


@pytest.mark.parametrize(
    "service_address",
    [
        "ftp://updates.example.test",
        "https://updates.example.test/path",
        "updates.example.test?secret=value",
        "updates.example.test#fragment",
    ],
)
def test_normalize_endpoint_rejects_invalid_addresses(service_address):
    with pytest.raises(AzureResponseError):
        SoftwareUpdateProvider._normalize_endpoint(service_address)


def test_parse_key_value_pairs(provider):
    assert provider._parse_key_value_pairs(None, "--values") == {}
    assert provider._parse_key_value_pairs(
        ["one=1", "url=https://example.test?a=b"], "--values"
    ) == {"one": "1", "url": "https://example.test?a=b"}


@pytest.mark.parametrize("value", ["missing-separator", "=value", "key="])
def test_parse_key_value_pairs_rejects_invalid_values(provider, value):
    with pytest.raises(InvalidArgumentValueError, match="key=value|non-empty"):
        provider._parse_key_value_pairs([value], "--values")


def test_parse_key_value_pairs_rejects_unsupported_key(provider):
    with pytest.raises(InvalidArgumentValueError, match="unsupported property"):
        provider._parse_key_value_pairs(
            ["other=value"], "--values", allowed_keys={"name"}
        )


def test_parse_files(provider):
    assert provider._parse_files(None) is None
    assert provider._parse_files(
        [
            ["filename=one.bin", "url=https://example.test/one"],
            ["filename=two.bin", "url=https://example.test/two"],
        ]
    ) == [
        {"filename": "one.bin", "url": "https://example.test/one"},
        {"filename": "two.bin", "url": "https://example.test/two"},
    ]


def test_parse_files_requires_filename_and_url(provider):
    with pytest.raises(InvalidArgumentValueError, match="both filename and url"):
        provider._parse_files([["filename=one.bin"]])


def test_calculate_url_metadata_streams_content():
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.side_effect = [b"hello ", b"world", b""]

    with patch(
        "azext_iot.adr.providers.software_update.urlopen",
        return_value=response,
    ) as open_url:
        size, digest = SoftwareUpdateProvider._calculate_url_metadata(
            "https://example.test/manifest.json"
        )

    assert size == 11
    assert digest == "uU0nuZNNPgilLlLX2n2r+sSE7+N6U4DukIj3rOLvzek="
    open_url.assert_called_once_with(
        "https://example.test/manifest.json", timeout=60
    )
    assert response.read.call_count == 3


@pytest.mark.parametrize(
    "source_error",
    [
        OSError("https://example.test/manifest.json?sig=do-not-log"),
        IncompleteRead(b"partial"),
    ],
)
def test_calculate_url_metadata_redacts_url_errors(source_error):
    with patch(
        "azext_iot.adr.providers.software_update.urlopen",
        side_effect=source_error,
    ), pytest.raises(AzureResponseError) as raised:
        SoftwareUpdateProvider._calculate_url_metadata(
            "https://example.test/manifest.json?sig=do-not-log"
        )

    assert "Unable to read the import manifest URL" in str(raised.value)
    assert "do-not-log" not in str(raised.value)


def test_list_updates(provider):
    expected = MagicMock()
    provider.client.software_update.list_updates.return_value = expected

    assert (
        provider.list_updates(NAMESPACE, RG, search="term", filter="filter")
        is expected
    )
    provider.client.software_update.list_updates.assert_called_once_with(
        search="term",
        filter="filter",
    )


def test_show_update(provider):
    expected = {"updateId": {"provider": PROVIDER}}
    provider.client.software_update.get_update.return_value = expected

    assert provider.show_update(NAMESPACE, RG, PROVIDER, UPDATE, VERSION) == expected
    provider.client.software_update.get_update.assert_called_once_with(
        provider=PROVIDER,
        name=UPDATE,
        version=VERSION,
    )


def test_delete_update_waits(provider):
    poller = MagicMock()
    provider.client.software_update.begin_delete_update.return_value = poller
    provider._wait = MagicMock(return_value=None)

    assert (
        provider.delete_update(
            NAMESPACE,
            RG,
            PROVIDER,
            UPDATE,
            VERSION,
            no_wait=True,
        )
        is None
    )
    provider.client.software_update.begin_delete_update.assert_called_once_with(
        provider=PROVIDER,
        name=UPDATE,
        version=VERSION,
    )
    provider._wait.assert_called_once_with(
        poller,
        f"Deleting update '{PROVIDER}/{UPDATE}/{VERSION}'...",
        no_wait=True,
    )


def test_import_update_builds_complete_request(provider):
    poller = MagicMock()
    provider.client.software_update.begin_import_update.return_value = poller
    provider._calculate_url_metadata = MagicMock()
    provider._wait = MagicMock(return_value={"status": "Succeeded"})

    result = provider.import_update(
        NAMESPACE,
        RG,
        "https://example.test/manifest",
        size=42,
        hashes=["sha256=digest"],
        friendly_name="Friendly",
        files=[
            [
                "filename=payload.bin",
                "url=https://example.test/payload",
            ]
        ],
        enable_scan=True,
        no_wait=False,
    )

    assert result == {"status": "Succeeded"}
    provider._calculate_url_metadata.assert_not_called()
    provider.client.software_update.begin_import_update.assert_called_once_with(
        import_update_request={
            "importUpdateInput": [
                {
                    "importManifest": {
                        "url": "https://example.test/manifest",
                        "sizeInBytes": 42,
                        "hashes": {"sha256": "digest"},
                    },
                    "files": [
                        {
                            "filename": "payload.bin",
                            "url": "https://example.test/payload",
                        }
                    ],
                    "friendlyName": "Friendly",
                }
            ],
            "enableScan": True,
        },
        logging_enable=False,
    )
    provider._wait.assert_called_once_with(
        poller,
        "Importing software update...",
        no_wait=False,
    )


def test_import_update_calculates_missing_metadata(provider):
    provider._calculate_url_metadata = MagicMock(return_value=(12, "digest"))
    provider._wait = MagicMock(return_value=MagicMock())

    provider.import_update(
        NAMESPACE,
        RG,
        "https://example.test/manifest",
    )

    provider._calculate_url_metadata.assert_called_once_with(
        "https://example.test/manifest"
    )
    request = provider.client.software_update.begin_import_update.call_args.kwargs[
        "import_update_request"
    ]
    assert request == {
        "importUpdateInput": [
            {
                "importManifest": {
                    "url": "https://example.test/manifest",
                    "sizeInBytes": 12,
                    "hashes": {"sha256": "digest"},
                }
            }
        ]
    }


def test_import_update_uses_calculated_size_with_supplied_hash(provider):
    provider._calculate_url_metadata = MagicMock(return_value=(12, "ignored"))
    provider._wait = MagicMock()

    provider.import_update(
        NAMESPACE,
        RG,
        "https://example.test/manifest",
        hashes=["sha256=supplied"],
    )

    request = provider.client.software_update.begin_import_update.call_args.kwargs[
        "import_update_request"
    ]
    assert request["importUpdateInput"][0]["importManifest"]["sizeInBytes"] == 12
    assert request["importUpdateInput"][0]["importManifest"]["hashes"] == {
        "sha256": "supplied"
    }


def test_import_update_requires_sha256(provider):
    with pytest.raises(InvalidArgumentValueError, match="sha256"):
        provider.import_update(
            NAMESPACE,
            RG,
            "https://example.test/manifest",
            size=1,
            hashes=["sha1=digest"],
        )
    provider.client.software_update.begin_import_update.assert_not_called()


@pytest.mark.parametrize("size", [0, -1])
def test_import_update_requires_positive_size(provider, size):
    with pytest.raises(InvalidArgumentValueError, match="greater than zero"):
        provider.import_update(
            NAMESPACE,
            RG,
            "https://example.test/manifest",
            size=size,
            hashes=["sha256=digest"],
        )
    provider.client.software_update.begin_import_update.assert_not_called()


def test_stage_update_returns_summary_without_import(provider):
    summary = {"readyToImport": True}
    with patch(
        "azext_iot.adr.providers.software_update.SoftwareUpdateStager"
    ) as stager_type:
        stager_type.return_value.stage.return_value = (summary, [])

        assert provider.stage_update(
            NAMESPACE,
            RG,
            ["manifest.json"],
            "storage",
            "updates",
        ) == summary

    stager_type.assert_called_once_with(
        cmd=provider.cmd,
        storage_account="storage",
        storage_account_subscription=None,
    )
    stager_type.return_value.stage.assert_called_once_with(
        manifest_paths=["manifest.json"],
        storage_container_name="updates",
        storage_prefix=None,
        overwrite=False,
        include_sas=False,
        sas_expiry_hours=4,
        friendly_name=None,
    )
    provider.client.software_update.begin_import_update.assert_not_called()


def test_stage_update_imports_batch(provider):
    items = [{"importManifest": {"url": "https://example.test/one?sig=secret"}}]
    poller = MagicMock()
    provider.client.software_update.begin_import_update.return_value = poller
    provider._wait = MagicMock(return_value={"status": "Succeeded"})
    with patch(
        "azext_iot.adr.providers.software_update.SoftwareUpdateStager"
    ) as stager_type:
        stager_type.return_value.stage.return_value = ({}, items)

        result = provider.stage_update(
            NAMESPACE,
            RG,
            ["root.json", "leaf.json"],
            "storage",
            "updates",
            enable_scan=False,
            then_import=True,
            no_wait=True,
        )

    assert result == {"status": "Succeeded"}
    provider.client.software_update.begin_import_update.assert_called_once_with(
        import_update_request={
            "importUpdateInput": items,
            "enableScan": False,
        },
        logging_enable=False,
    )
    provider._wait.assert_called_once_with(
        poller,
        "Importing software update...",
        no_wait=True,
    )


def test_stage_update_rejects_no_wait_without_import(provider):
    with pytest.raises(InvalidArgumentValueError, match="--then-import"):
        provider.stage_update(
            NAMESPACE,
            RG,
            ["manifest.json"],
            "storage",
            "updates",
            no_wait=True,
        )
    provider.registry_client.namespaces.get.assert_not_called()


def test_stage_update_rejects_enable_scan_without_import(provider):
    with pytest.raises(InvalidArgumentValueError, match="--then-import"):
        provider.stage_update(
            NAMESPACE,
            RG,
            ["manifest.json"],
            "storage",
            "updates",
            enable_scan=True,
        )
    provider.registry_client.namespaces.get.assert_not_called()


def test_list_update_files(provider):
    expected = MagicMock()
    provider.client.software_update.list_files.return_value = expected

    assert (
        provider.list_update_files(NAMESPACE, RG, PROVIDER, UPDATE, VERSION)
        is expected
    )
    provider.client.software_update.list_files.assert_called_once_with(
        provider=PROVIDER,
        name=UPDATE,
        version=VERSION,
    )


def test_show_update_file(provider):
    expected = {"fileId": "file-id"}
    provider.client.software_update.get_file.return_value = expected

    assert (
        provider.show_update_file(
            NAMESPACE,
            RG,
            PROVIDER,
            UPDATE,
            VERSION,
            "file-id",
        )
        == expected
    )
    provider.client.software_update.get_file.assert_called_once_with(
        provider=PROVIDER,
        name=UPDATE,
        version=VERSION,
        file_id="file-id",
    )


def test_operation_status_list_and_show(provider):
    statuses = MagicMock()
    provider.client.software_update.list_operation_statuses.return_value = statuses
    provider.client.software_update.get_operation_status.return_value = {
        "operationId": "operation"
    }

    assert provider.list_operation_statuses(NAMESPACE, RG) is statuses
    assert provider.show_operation_status(
        NAMESPACE, RG, "operation"
    ) == {"operationId": "operation"}
    provider.client.software_update.list_operation_statuses.assert_called_once_with()
    provider.client.software_update.get_operation_status.assert_called_once_with(
        operation_id="operation"
    )


def test_catalog_provider_name_and_version_discovery(provider):
    provider.client.software_update.list_providers.return_value = ["Contoso"]
    provider.client.software_update.list_names.return_value = ["Thermostat"]
    provider.client.software_update.list_versions.return_value = ["1.0"]

    assert provider.list_providers(NAMESPACE, RG) == ["Contoso"]
    assert provider.list_names(NAMESPACE, RG, PROVIDER) == ["Thermostat"]
    assert provider.list_versions(
        NAMESPACE, RG, PROVIDER, UPDATE, filter="filter"
    ) == ["1.0"]
    provider.client.software_update.list_providers.assert_called_once_with()
    provider.client.software_update.list_names.assert_called_once_with(
        provider=PROVIDER
    )
    provider.client.software_update.list_versions.assert_called_once_with(
        provider=PROVIDER,
        name=UPDATE,
        filter="filter",
    )


def test_software_update_data_factory_uses_generated_sdk():
    cli_ctx = MagicMock()
    client_path = (
        "azext_iot.sdk.deviceupdate.duregistrydata."
        "DeviceRegistrySoftwareUpdateClient"
    )
    with patch(client_path) as client_type:
        assert (
            _factory.adr_software_update_data_service_factory(
                cli_ctx, endpoint=ENDPOINT
            )
            is client_type.return_value
        )

    assert client_type.call_args.kwargs["endpoint"] == ENDPOINT
    assert client_type.call_args.kwargs["credential"] is _factory.AZURE_CLI_CREDENTIAL
    assert "user_agent_policy" in client_type.call_args.kwargs
    assert "http_logging_policy" in client_type.call_args.kwargs
