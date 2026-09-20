# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Owned registry-only lifecycle."""

import shlex
from functools import partial
from urllib.parse import unquote, urlsplit

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError, RequiredArgumentMissingError
from azure.core.exceptions import HttpResponseError

from azext_iot._factory import adr_service_factory
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    CleanupLedger, is_resource_not_found_error, resource_is_absent, wait_for_condition,
)
from azext_iot.tests.adr._log import LogKind, _log
from azext_iot.tests.adr._readiness import delete_test_namespace
from azext_iot.tests.adr.conftest import (
    TEST_ARM_ENDPOINT, TEST_LOCATION, TEST_RG, TEST_SUBSCRIPTION, generate_adr_namespace_name,
)
from azext_iot.tests.generators import generate_generic_id


PREFIX = "iot adr ns registry-device"
WAIT = "--timeout 600 --interval 10"


def _owned_resource(getter, resource_id):
    """Read one bound SDK resource; only its exact HTTP GET 404 proves absence."""
    try:
        resource = getter()
    except HttpResponseError as error:
        response = error.response
        request = getattr(response, "request", None)
        url = getattr(request, "url", None)
        if (
            error.status_code == 404 and getattr(response, "status_code", None) == 404
            and is_resource_not_found_error(error)
            and getattr(request, "method", None) == "GET" and isinstance(url, str)
            and urlsplit(url).scheme == "https"
            and urlsplit(url).netloc.casefold() == urlsplit(TEST_ARM_ENDPOINT).netloc.casefold()
            and unquote(urlsplit(url).path).casefold() == resource_id.casefold()
        ):
            _log(LogKind.RESULT, "Owned resource GET returned HTTP 404: %s", resource_id)
            return None
        raise
    assert isinstance(resource, dict) and isinstance(resource.get("id"), str), "Malformed owned resource GET."
    assert resource["id"].casefold() == resource_id.casefold(), "Owned resource GET returned a different ARM ID."
    return resource


def _assert_owned_absent(getter, resource_id):
    assert _owned_resource(getter, resource_id) is None, f"Expected HTTP 404 for owned target: {resource_id}"


def _remove_owned(test, group, args, getter, resource_id):
    if _owned_resource(getter, resource_id) is not None:
        test.cmd(f"{group} delete {args} --yes")
    wait_for_condition(
        lambda: _owned_resource(getter, resource_id), lambda resource: resource is None,
        description=f"owned resource absence: {resource_id}", timeout=120, interval=5,
        is_retryable_error=lambda _error: False,
    )


def _assert_absent(test, command):
    assert resource_is_absent(test, command), f"Expected HTTP 404 for owned/missing target: {command}"


class _RegistryDeviceScenario(ADRLiveScenarioTest):
    def cmd(self, command, checks=None, expect_failure=False):
        # SDK ownership reads use TEST_SUBSCRIPTION. CLI mutations/readbacks must
        # use the same target, even when this context cached another login default
        # before the separate preflight process ran. Keep the ADR logging wrapper.
        return super().cmd(
            f"{command} --subscription {shlex.quote(TEST_SUBSCRIPTION)}",
            checks=checks, expect_failure=expect_failure,
        )


@pytest.mark.usefixtures("set_cwd")
class TestADRRegistryDeviceLifecycle(_RegistryDeviceScenario):
    @pytest.mark.timeout(2100, func_only=False)
    def test_registry_device_lifecycle(self):
        namespace = generate_adr_namespace_name()
        name = f"registry{generate_generic_id()}"
        external = f"external-{name}"
        scope = shlex.join(["--ns", namespace, "-g", TEST_RG])
        args = f"{scope} -n {name}"
        child_args = f"{scope} --rdn {name}"
        attribute_args = f"{child_args} -n owned"
        client = adr_service_factory(self.cli_ctx, subscription_id=TEST_SUBSCRIPTION)
        self.addCleanup(client.close)
        sdk_scope = {"resource_group_name": TEST_RG, "namespace_name": namespace}
        namespace_id = (
            f"/subscriptions/{TEST_SUBSCRIPTION}/resourceGroups/{TEST_RG}"
            f"/providers/Microsoft.DeviceRegistry/namespaces/{namespace}"
        )
        device_id = f"{namespace_id}/registryDevices/{name}"
        attribute_id = f"{device_id}/attributes/owned"
        namespace_getter = partial(client.namespaces.get, **sdk_scope)
        device_getter = partial(client.registry_devices.get, **sdk_scope, registry_device_name=name)
        attribute_getter = partial(
            client.registry_device_attributes.get, **sdk_scope, registry_device_name=name, attribute_name="owned",
        )
        with CleanupLedger() as cleanup:
            _assert_owned_absent(namespace_getter, namespace_id)
            cleanup.register(
                "namespace",
                lambda: delete_test_namespace(self, namespace, TEST_RG, namespace_getter=namespace_getter),
                depends_on=("device",),
            )
            # Until absence establishes ownership, cleanup may only read the child.
            # A collision must quarantine the parent, not cascade-delete a stranger.
            cleanup.register("device", lambda: _assert_owned_absent(device_getter, device_id))
            self.cmd(f"iot adr ns create -n {namespace} -g {TEST_RG} --location {TEST_LOCATION}")
            _assert_owned_absent(device_getter, device_id)
            cleanup.dismiss("device")
            cleanup.register("device", lambda: _remove_owned(self, PREFIX, args, device_getter, device_id))
            self.cmd(
                f"{PREFIX} create {args} --external-device-id {external} "
                "--manufacturer Contoso --model Test --hardware-revision 1 --software-revision 1 "
                "--tags owner=registry-integration --no-wait"
            )
            self.cmd(f"{PREFIX} wait {scope} --external-device-id {external} {WAIT}")
            created = self.cmd(f"{PREFIX} show {args}").get_output_in_json()
            assert created["name"] == name
            assert created["properties"]["externalDeviceId"] == external
            assert created["properties"]["enablementState"] == "Enabled"
            by_external = self.cmd(f"{PREFIX} show {scope} --external-device-id {external}").get_output_in_json()
            assert by_external["id"].casefold() == created["id"].casefold()
            listed = self.cmd(f"{PREFIX} list {scope}").get_output_in_json()
            assert created["id"].casefold() in [device["id"].casefold() for device in listed]
            self.cmd(f"{PREFIX} wait {args} --exists {WAIT}")
            with pytest.raises(RequiredArgumentMissingError, match="Nothing to update"):
                self.cmd(f"{PREFIX} update {args}")
            self.cmd(f"{PREFIX} update {args} --enablement-state Disabled --software-revision 2 --no-wait")
            self.cmd(f"{PREFIX} wait {args} --custom \"properties.enablementState=='Disabled'\" {WAIT}")
            self.cmd(f"{PREFIX} wait {args} --updated {WAIT}")
            updated = self.cmd(f"{PREFIX} show {args}").get_output_in_json()
            assert updated["properties"]["softwareRevision"] == "2"
            for field in ("externalDeviceId", "manufacturer", "model", "hardwareRevision"):
                assert updated["properties"][field] == created["properties"][field]
            assert updated["tags"] == created["tags"]
            self.cmd(f"{PREFIX} update {args} --enablement-state Enabled --tags owner=registry-updated")
            self.cmd(f"{PREFIX} wait {args} --updated {WAIT}")
            assert self.cmd(f"{PREFIX} show {args}").get_output_in_json()["tags"] == {"owner": "registry-updated"}

            # Auth/capability metadata is read-only and is not created by bare device CRUD.
            for child in ("auth", "capability"):
                listed = self.cmd(f"{PREFIX} {child} list {child_args}").get_output_in_json()
                assert isinstance(listed, list)
                _assert_absent(self, f"{PREFIX} {child} show {child_args} -n missing-{name}")
            for verb in ("show-keys", "revoke-certs"):
                suffix = " --yes" if verb == "revoke-certs" else ""
                _assert_absent(self, f"{PREFIX} auth {verb} {child_args} -n missing-{name}{suffix}")
            self.cmd(f"{PREFIX} auth wait {child_args} -n missing-{name} --deleted {WAIT}")

            # Establish the read-only dependency before checking for a collision.
            cleanup.dismiss("device")
            cleanup.register(
                "device", lambda: _remove_owned(self, PREFIX, args, device_getter, device_id), depends_on=("attribute",),
            )
            cleanup.register("attribute", lambda: _assert_owned_absent(attribute_getter, attribute_id))
            _assert_owned_absent(attribute_getter, attribute_id)
            cleanup.dismiss("attribute")
            cleanup.register(
                "attribute",
                lambda: _remove_owned(self, f"{PREFIX} attribute", attribute_args, attribute_getter, attribute_id),
            )
            attribute = self.cmd(
                f"{PREFIX} attribute create {attribute_args} " + "--properties '{{}}'"
            ).get_output_in_json()
            assert attribute["properties"]["reportedBy"] == "User"
            shown = self.cmd(f"{PREFIX} attribute show {attribute_args}").get_output_in_json()
            assert shown["id"].casefold() == attribute["id"].casefold()
            listed = wait_for_condition(
                lambda: self.cmd(f"{PREFIX} attribute list {child_args}").get_output_in_json(),
                lambda items: attribute["id"].casefold() in [item["id"].casefold() for item in items],
                description="owned registry-device attribute list visibility",
                timeout=120, interval=5, is_retryable_error=lambda _error: False,
            )
            assert attribute["id"].casefold() in [item["id"].casefold() for item in listed]
            # Replace only the User contract, with no invented schema identifiers or backend fields.
            self.cmd(f"{PREFIX} attribute create {attribute_args}")
            readback = self.cmd(f"{PREFIX} attribute show {attribute_args}").get_output_in_json()
            assert readback["properties"]["reportedBy"] == "User"
            with pytest.raises(InvalidArgumentValueError, match="service-owned"):
                self.cmd(
                    f"{PREFIX} attribute create {attribute_args} "
                    """--properties '{{"reportedBy":"Microsoft.DeviceUpdate"}}'"""
                )
            _remove_owned(self, f"{PREFIX} attribute", attribute_args, attribute_getter, attribute_id)
            cleanup.dismiss("attribute")
            self.cmd(f"{PREFIX} delete {args} --yes --no-wait")
            self.cmd(f"{PREFIX} wait {args} --deleted {WAIT}")
            _assert_absent(self, f"{PREFIX} show {args}")
            _assert_absent(self, f"{PREFIX} show {scope} --external-device-id {external}")
            cleanup.dismiss("device")
