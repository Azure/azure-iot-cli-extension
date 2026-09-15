# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Owned identity roundtrips and a responding PnP device on the preview dataplane."""

import hashlib
import json
from queue import Queue
from shlex import quote
from threading import Event

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError

from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES, IoTLiveScenarioTest
from azext_iot.tests.iothub._sas_phase import AUTH_TYPES as SAS_AUTH_TYPES, enabled as sas_phase_enabled


AUTH_TYPES = SAS_AUTH_TYPES if sas_phase_enabled() else DATAPLANE_AUTH_TYPES


def _fingerprint(value):
    # Never put authentication dictionaries/keys in assertion introspection output.
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class TestHubPreview(IoTLiveScenarioTest):
    @pytest.mark.timeout(900, func_only=False)
    def test_identity_roundtrip(self):
        for auth_phase in AUTH_TYPES:
            parent, device = self.generate_device_names(2, edge=True)
            module = self.generate_module_names(1)[0]

            def command(text):
                # The test SDK formats braces after these literal CLI arguments are built.
                text = text.replace("{", "{{").replace("}", "}}")
                return self.cmd(self.set_cmd_auth_type(
                    f"{text} -n {self.entity_name} -g {self.entity_rg}", auth_type=auth_phase,
                ))

            for identifier in (parent, device):
                command(f"iot hub device-identity create -d {identifier} --ee")
            before = command(f"iot hub device-identity show -d {device}").get_output_in_json()
            assert not before.get("adrDeviceProperties"), "This case requires an unlinked Hub; use the linked suite separately."
            auth_before = _fingerprint(before["authentication"])
            attributes = {"owner": device, "adrDeviceProperties": "user-owned nested name"}
            after = command(
                f"iot hub device-identity update -d {device} --status disabled --status-reason preview "
                f"--set {quote('attributes=' + json.dumps(attributes))}"
            ).get_output_in_json()
            auth_after = _fingerprint(after["authentication"])
            assert auth_before == auth_after
            assert after["attributes"] == attributes
            assert after["status"] == "disabled" and after["statusReason"] == "preview"
            for action in (
                "--set adrDeviceProperties.uuid=forged", "--remove adrDeviceProperties",
                "--add adrDeviceProperties uuid=forged",
            ):
                with pytest.raises(InvalidArgumentValueError, match="owned"):
                    command(f"iot hub device-identity update -d {device} {action}")
            command(f"iot hub device-identity parent set -d {device} --pd {parent}")
            parented = command(f"iot hub device-identity show -d {device}").get_output_in_json()
            parent_identity = command(f"iot hub device-identity show -d {parent}").get_output_in_json()
            assert parented["parentScopes"] == [parent_identity["deviceScope"]]
            assert parented["attributes"] == attributes
            command(f"iot hub device-identity renew-key -d {device} --kt swap")
            swapped = command(f"iot hub device-identity show -d {device}").get_output_in_json()
            expected = _fingerprint(before["authentication"]["symmetricKey"]["primaryKey"])
            actual = _fingerprint(swapped["authentication"]["symmetricKey"]["secondaryKey"])
            assert expected == actual
            assert swapped["attributes"] == attributes and swapped["parentScopes"] == parented["parentScopes"]
            # Isolate module CRUD from the disabled-status roundtrip, without undoing
            # the key swap or hiding a service authorization failure.
            enabled = command(f"iot hub device-identity update -d {device} --status enabled").get_output_in_json()
            assert enabled["status"] == "enabled"
            auth_enabled = _fingerprint(enabled["authentication"])
            auth_swapped = _fingerprint(swapped["authentication"])
            assert auth_enabled == auth_swapped
            assert enabled["attributes"] == attributes and enabled["parentScopes"] == parented["parentScopes"]
            module_before = command(f"iot hub module-identity create -d {device} -m {module}").get_output_in_json()
            auth_before = _fingerprint(module_before["authentication"])
            module_after = command(
                f"iot hub module-identity update -d {device} -m {module} "
                f"--set {quote('attributes=' + json.dumps(attributes))}"
            ).get_output_in_json()
            auth_after = _fingerprint(module_after["authentication"])
            assert auth_before == auth_after
            assert module_after["attributes"] == attributes

    @pytest.mark.timeout(300 * len(AUTH_TYPES), func_only=False)
    def test_responding_digital_twin(self):
        from azure.iot.device import IoTHubDeviceClient, MethodResponse

        device = self.generate_device_names(1)[0]
        self.cmd(f"iot hub device-identity create -d {device} -n {self.entity_name} -g {self.entity_rg}")
        client = IoTHubDeviceClient.create_from_connection_string(
            self.get_device_cstring(device), product_info="dtmi:com:example:TemperatureController;2",
            connection_retry=False, auto_connect=False,
        )
        desired = Event()
        failures = Queue()

        def respond(request):
            try:
                client.send_method_response(MethodResponse.create_from_method_request(
                    request, status=200, payload={"method": request.name, "received": request.payload},
                ))
            except Exception as error:  # A callback exception must fail the test, not disappear on the SDK thread.
                failures.put(error)

        try:
            client.connect()
            client.on_method_request_received = respond
            client.on_twin_desired_properties_patch_received = lambda patch: desired.set() if "thermostat1" in patch else None
            client.patch_twin_reported_properties({
                "serialNumber": device, "thermostat1": {"__t": "c", "temperature": 21},
            })
            for index, auth_phase in enumerate(AUTH_TYPES):
                def command(text):
                    text = text.replace("{", "{{").replace("}", "}}")
                    return self.cmd(self.set_cmd_auth_type(
                        f"{text} -d {device} -n {self.entity_name} -g {self.entity_rg}", auth_type=auth_phase,
                    ))

                twin = command("iot hub digital-twin show").get_output_in_json()
                assert twin["serialNumber"] == device
                assert twin["thermostat1"]["temperature"] == 21
                desired.clear()
                patch = json.dumps([{"op": "add", "path": "/thermostat1/targetTemperature", "value": 22 + index}])
                command(f"iot hub digital-twin update --patch {quote(patch)}")
                assert desired.wait(60), "The responding device never received the requested desired-property patch."
                for component, name, payload in (
                    (None, "reboot", 0), ("thermostat1", "getMaxMinReport", "2026-01-01T00:00:00Z"),
                ):
                    component_flag = f"--component-path {component}" if component else ""
                    result = command(
                        f"iot hub digital-twin invoke-command --cn {name} {component_flag} "
                        f"--payload {quote(json.dumps(payload))} --cto 15 --rto 30"
                    ).get_output_in_json()
                    if not failures.empty():
                        raise failures.get_nowait()
                    assert str(result["status"]) == "200"
                    assert result["payload"] == {"method": f"{component}*{name}" if component else name, "received": payload}
        finally:
            client.shutdown()
