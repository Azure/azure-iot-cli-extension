# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
NOTICE: These tests are to be phased out and introduced in more modern form.
        Try not to add any new content, only fixes if necessary.
        Look at IoT Hub jobs or configuration tests for a better example. Also use responses fixtures
        like mocked_response for http request mocking.
"""

import pytest
import json
import os
import responses
import re
from azext_iot.operations import hub as subject
from azext_iot.common.utility import read_file_content
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.constants import TRACING_PROPERTY
from azext_iot.tests.generators import create_req_monitor_events, generate_generic_id
from knack.util import CLIError
from azext_iot.tests.conftest import (
    fixture_cmd,
    build_mock_response,
    path_service_client,
    mock_target,
    generate_cs,
)
from azext_iot.common.shared import DeviceAuthApiType
from pathlib import Path

CWD = os.path.dirname(os.path.abspath(__file__))
device_id = "mydevice"
child_device_id = "child_device1"
module_id = "mymod"
config_id = "myconfig"
message_etag = "3k28zb44-0d00-4ddd-ade3-6110eb94c476"
c2d_purge_response = {"deviceId": device_id, "moduleId": None, "totalMessagesPurged": 3}

generic_cs_template = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"


mock_target["cs"] = generate_cs()

# TODO generalize all fixtures across DPS/Hub unit tests


def generate_device_create_req(
    ee=False,
    auth="shared_private_key",
    pk=None,
    sk=None,
    ptp="123",
    stp="321",
    status="enabled",
    status_reason=None,
    valid_days=None,
    output_dir=None,
    device_scope=None,
):
    return {
        "client": None,
        "device_id": device_id,
        "hub_name": mock_target["entity"],
        "ee": ee,
        "auth": auth,
        "pk": pk,
        "sk": sk,
        "ptp": ptp,
        "stp": stp,
        "status": status,
        "status_reason": status_reason,
        "valid_days": valid_days,
        "output_dir": output_dir,
        "device_scope": device_scope
    }


class TestDeviceCreate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "req",
        [
            (generate_device_create_req()),
            (generate_device_create_req(pk=generate_generic_id(), sk=generate_generic_id())),
            (generate_device_create_req(ee=True)),
            (generate_device_create_req(ee=True, auth="x509_ca")),
            (generate_device_create_req(ee=True, auth="x509_thumbprint")),
            (generate_device_create_req(ee=True, auth="x509_thumbprint", stp=None)),
            (generate_device_create_req(auth="x509_ca")),
            (generate_device_create_req(auth="x509_thumbprint")),
            (generate_device_create_req(auth="x509_thumbprint", stp=None)),
            (
                generate_device_create_req(
                    auth="x509_thumbprint", ptp=None, stp=None, valid_days=30
                )
            ),
            (generate_device_create_req(status="disabled", status_reason="reasons")),
            (generate_device_create_req(device_scope=generate_generic_id()))
        ],
    )
    def test_device_create(self, serviceclient, req):
        subject.iot_device_create(
            fixture_cmd,
            req["device_id"],
            req["hub_name"],
            req["ee"],
            req["auth"],
            req["pk"],
            req["sk"],
            req["ptp"],
            req["stp"],
            req["status"],
            req["status_reason"],
            req["valid_days"],
            req["output_dir"],
            req["device_scope"]
        )

        args = serviceclient.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target["entity"], device_id) in url
        assert args[0][0].method == "PUT"
        body = args[0][2]

        assert body["deviceId"] == req["device_id"]
        assert body["status"] == req["status"]
        if req.get("status_reason"):
            assert body["statusReason"] == req["status_reason"]
        assert body["capabilities"]["iotEdge"] == req["ee"]

        if req.get("device_scope"):
            assert body["deviceScope"] == req["device_scope"]

        if req["auth"] == "shared_private_key":
            assert body["authentication"]["type"] == DeviceAuthApiType.sas.value
            if all([req["pk"], req["pk"]]):
                assert body["authentication"]["symmetricKey"]["primaryKey"] == req["pk"]
                assert body["authentication"]["symmetricKey"]["secondaryKey"] == req["sk"]
            else:
                assert body["authentication"]["symmetricKey"] == {}
        elif req["auth"] == "x509_ca":
            assert body["authentication"]["type"] == DeviceAuthApiType.certificateAuthority.value
            assert not body["authentication"].get("x509Thumbprint")
            assert not body["authentication"].get("symmetricKey")
        elif req["auth"] == "x509_thumbprint":
            assert body["authentication"]["type"] == DeviceAuthApiType.selfSigned.value
            x509tp = body["authentication"]["x509Thumbprint"]
            assert x509tp["primaryThumbprint"]
            if req["stp"] is None:
                assert x509tp.get("secondaryThumbprint") is None
            else:
                assert x509tp["secondaryThumbprint"] == req["stp"]

    @pytest.mark.parametrize(
        "req, exp",
        [
            (
                generate_device_create_req(ee=True, auth="x509_thumbprint", ptp=None),
                CLIError,
            ),
            (generate_device_create_req(auth="doesnotexist"), CLIError),
            (
                generate_device_create_req(auth="x509_thumbprint", ptp=None, stp=""),
                CLIError,
            ),
            (generate_device_create_req(pk=generate_generic_id()), CLIError),
            (generate_device_create_req(sk=generate_generic_id()), CLIError)
        ],
    )
    def test_device_create_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_create(
                cmd=None,
                device_id=req["device_id"],
                hub_name=req["hub_name"],
                edge_enabled=req["ee"],
                auth_method=req["auth"],
                primary_key=req["pk"],
                secondary_key=req["sk"],
                primary_thumbprint=req["ptp"],
                secondary_thumbprint=req["stp"],
                status=req["status"],
            )

    @pytest.mark.parametrize("req", [(generate_device_create_req())])
    def test_device_create_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_create(
                cmd=None,
                device_id=req["device_id"],
                hub_name=req["hub_name"],
                edge_enabled=req["ee"],
                auth_method=req["auth"],
                primary_key=req["pk"],
                secondary_key=req["sk"],
                primary_thumbprint=req["ptp"],
                secondary_thumbprint=req["stp"],
                status=req["status"],
            )


def generate_device_show(**kvp):
    payload = {
        "authentication": {
            "symmetricKey": {"primaryKey": None, "secondaryKey": None},
            "x509Thumbprint": {"primaryThumbprint": None, "secondaryThumbprint": None},
            "type": DeviceAuthApiType.sas.value,
        },
        "capabilities": {"iotEdge": True},
        "deviceId": device_id,
        "status": "disabled",
        "statusReason": "unknown reason",
    }
    for k in kvp:
        if payload.get(k):
            payload[k] = kvp[k]
    return payload


def device_update_con_arg(
    edge_enabled=None,
    status=None,
    status_reason=None,
    auth_method=None,
    primary_thumbprint=None,
    secondary_thumbprint=None,
    primary_key=None,
    secondary_key=None,
):
    return {
        "edge_enabled": edge_enabled,
        "status": status,
        "status_reason": status_reason,
        "auth_method": auth_method,
        "primary_thumbprint": primary_thumbprint,
        "secondary_thumbprint": secondary_thumbprint,
        "primary_key": primary_key,
        "secondary_key": secondary_key,
    }


class TestDeviceUpdate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize(
        "req",
        [
            (generate_device_show(capabilities={"iotEdge": False})),
            (generate_device_show(status="enabled")),
            (
                generate_device_show(
                    authentication={
                        "symmetricKey": {"primaryKey": "", "secondaryKey": ""},
                        "type": DeviceAuthApiType.sas.value,
                    }
                )
            ),
            (
                generate_device_show(
                    authentication={
                        "x509Thumbprint": {
                            "primaryThumbprint": "123",
                            "secondaryThumbprint": "321",
                        },
                        "type": DeviceAuthApiType.selfSigned.value,
                    }
                )
            ),
            (
                generate_device_show(
                    authentication={"type": DeviceAuthApiType.certificateAuthority.value},
                    etag=generate_generic_id(),
                )
            ),
        ],
    )
    def test_device_update(self, fixture_cmd, serviceclient, req):
        subject.iot_device_update(
            cmd=fixture_cmd,
            device_id=req["deviceId"],
            hub_name=mock_target["entity"],
            parameters=req,
            etag=req.get("etag"),
        )
        args = serviceclient.call_args
        assert (
            "{}/devices/{}?".format(mock_target["entity"], device_id) in args[0][0].url
        )
        assert args[0][0].method == "PUT"

        body = args[0][2]
        assert body["deviceId"] == req["deviceId"]
        assert body["status"] == req["status"]
        assert body["capabilities"]["iotEdge"] == req["capabilities"]["iotEdge"]
        assert req["authentication"]["type"] == body["authentication"]["type"]
        if req["authentication"]["type"] == DeviceAuthApiType.certificateAuthority.value:
            assert not body["authentication"].get("x509Thumbprint")
            assert not body["authentication"].get("symmetricKey")
        elif req["authentication"]["type"] == DeviceAuthApiType.selfSigned.value:
            assert body["authentication"]["x509Thumbprint"]["primaryThumbprint"]
            assert body["authentication"]["x509Thumbprint"]["secondaryThumbprint"]

        headers = args[0][1]
        target_etag = req.get("etag")
        assert headers["If-Match"] == '"{}"'.format(target_etag if target_etag else "*")

    @pytest.mark.parametrize(
        "req, arg",
        [
            (
                generate_device_show(capabilities={"iotEdge": False}),
                device_update_con_arg(edge_enabled=True),
            ),
            (
                generate_device_show(status="disabled"),
                device_update_con_arg(status="enabled"),
            ),
            (generate_device_show(), device_update_con_arg(status_reason="test")),
            (
                generate_device_show(),
                device_update_con_arg(
                    auth_method="shared_private_key",
                    primary_key="primarykeyUpdated",
                    secondary_key="secondarykeyUpdated",
                ),
            ),
            (
                generate_device_show(
                    authentication={
                        "type": DeviceAuthApiType.selfSigned.value,
                        "symmetricKey": {"primaryKey": None, "secondaryKey": None},
                        "x509Thumbprint": {
                            "primaryThumbprint": "123",
                            "secondaryThumbprint": "321",
                        },
                    }
                ),
                device_update_con_arg(
                    auth_method="shared_private_key",
                    primary_key="primary_key",
                    secondary_key="secondary_key",
                ),
            ),
            (
                generate_device_show(
                    authentication={
                        "type": DeviceAuthApiType.certificateAuthority.value,
                        "symmetricKey": {"primaryKey": None, "secondaryKey": None},
                        "x509Thumbprint": {
                            "primaryThumbprint": None,
                            "secondaryThumbprint": None,
                        },
                    }
                ),
                device_update_con_arg(
                    auth_method="x509_thumbprint",
                    primary_thumbprint="primary_thumbprint",
                    secondary_thumbprint="secondary_thumbprint",
                ),
            ),
            (generate_device_show(), device_update_con_arg(auth_method="x509_ca",)),
            (generate_device_show(), device_update_con_arg(primary_key="secondary_key", secondary_key="primary_key")),
            (
                generate_device_show(
                    authentication={
                        "type": DeviceAuthApiType.selfSigned.value,
                        "symmetricKey": {"primaryKey": None, "secondaryKey": None},
                        "x509Thumbprint": {
                            "primaryThumbprint": "123",
                            "secondaryThumbprint": "321",
                        },
                    }
                ),
                device_update_con_arg(primary_thumbprint="321", secondary_thumbprint="123")
            )
        ],
    )
    def test_iot_device_custom(self, fixture_cmd, serviceclient, req, arg):
        instance = subject.update_iot_device_custom(
            instance=req,
            edge_enabled=arg["edge_enabled"],
            status=arg["status"],
            status_reason=arg["status_reason"],
            auth_method=arg["auth_method"],
            primary_thumbprint=arg["primary_thumbprint"],
            secondary_thumbprint=arg["secondary_thumbprint"],
            primary_key=arg["primary_key"],
            secondary_key=arg["secondary_key"],
        )

        if arg["edge_enabled"]:
            assert instance["capabilities"]["iotEdge"] == arg["edge_enabled"]
        if arg["status"]:
            assert instance["status"] == arg["status"]
        if arg["status_reason"]:
            assert instance["statusReason"] == arg["status_reason"]
        if arg["auth_method"]:
            if arg["auth_method"] == "shared_private_key":
                assert instance["authentication"]["type"] == DeviceAuthApiType.sas.value
                instance["authentication"]["symmetricKey"]["primaryKey"] == arg[
                    "primary_key"
                ]
                instance["authentication"]["symmetricKey"]["secondaryKey"] == arg[
                    "secondary_key"
                ]
            if arg["auth_method"] == "x509_thumbprint":
                assert instance["authentication"]["type"] == DeviceAuthApiType.selfSigned.value
                if arg["primary_thumbprint"]:
                    instance["authentication"]["x509Thumbprint"][
                        "primaryThumbprint"
                    ] = arg["primary_thumbprint"]
                if arg["secondary_thumbprint"]:
                    instance["authentication"]["x509Thumbprint"][
                        "secondaryThumbprint"
                    ] = arg["secondary_thumbprint"]
            if arg["auth_method"] == "x509_ca":
                assert instance["authentication"]["type"] == DeviceAuthApiType.certificateAuthority.value

    @pytest.mark.parametrize(
        "req, arg, exp",
        [
            (
                generate_device_show(),
                device_update_con_arg(
                    auth_method="shared_private_key", primary_key="primarykeyUpdated",
                ),
                CLIError,
            ),
            (
                generate_device_show(),
                device_update_con_arg(auth_method="x509_thumbprint",),
                CLIError,
            ),
            (
                generate_device_show(),
                device_update_con_arg(auth_method="Unknown",),
                ValueError,
            ),
            (
                generate_device_show(),
                device_update_con_arg(primary_thumbprint="newThumbprint",),
                ValueError,
            ),
            (
                generate_device_show(
                    authentication={
                        "type": DeviceAuthApiType.selfSigned.value,
                        "symmetricKey": {"primaryKey": None, "secondaryKey": None},
                        "x509Thumbprint": {
                            "primaryThumbprint": "123",
                            "secondaryThumbprint": "321",
                        },
                    }
                ),
                device_update_con_arg(primary_key='updated_key'),
                ValueError
            )
        ],
    )
    def test_iot_device_custom_invalid_args(self, serviceclient, req, arg, exp):
        with pytest.raises(exp):
            subject.update_iot_device_custom(
                instance=req,
                edge_enabled=arg["edge_enabled"],
                status=arg["status"],
                status_reason=arg["status_reason"],
                auth_method=arg["auth_method"],
                primary_thumbprint=arg["primary_thumbprint"],
                secondary_thumbprint=arg["secondary_thumbprint"],
                primary_key=arg["primary_key"],
                secondary_key=arg["secondary_key"],
            )

    @pytest.mark.parametrize(
        "req, exp",
        [
            (
                generate_device_show(
                    authentication={
                        "x509Thumbprint": {
                            "primaryThumbprint": "",
                            "secondaryThumbprint": "",
                        },
                        "type": DeviceAuthApiType.selfSigned.value,
                    }
                ),
                CLIError,
            ),
            (generate_device_show(authentication={"type": "doesnotexist"}), CLIError),
        ],
    )
    def test_device_update_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_update(
                cmd=fixture_cmd,
                device_id=req["deviceId"],
                hub_name=mock_target["entity"],
                parameters=req,
            )

    @pytest.mark.parametrize("req", [(generate_device_show())])
    def test_device_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_update(
                cmd=fixture_cmd,
                device_id=req["deviceId"],
                hub_name=mock_target["entity"],
                parameters=req,
            )


class TestDeviceRegenerateKey:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        kvp = {}
        kvp.setdefault(
            "authentication",
            {
                "symmetricKey": {"primaryKey": "123", "secondaryKey": "321"},
                "type": DeviceAuthApiType.sas.value,
            },
        )
        test_side_effect = [
            build_mock_response(mocker, 200, generate_device_show(**kvp)),
            build_mock_response(mocker, 200, {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize(
        "req, etag",
        [("primary", generate_generic_id()), ("secondary", None), ("swap", None)],
    )
    def test_device_key_regenerate(self, fixture_cmd, serviceclient, req, etag):
        subject.iot_device_key_regenerate(
            cmd=fixture_cmd,
            hub_name=mock_target["entity"],
            device_id=device_id,
            renew_key_type=req,
            etag=etag
        )
        args = serviceclient.call_args
        assert (
            "{}/devices/{}?".format(mock_target["entity"], device_id) in args[0][0].url
        )
        assert args[0][0].method == "PUT"

        body = args[0][2]
        if req == "primary":
            assert body["authentication"]["symmetricKey"]["primaryKey"] != "123"
        if req == "secondary":
            assert body["authentication"]["symmetricKey"]["secondaryKey"] != "321"
        if req == "swap":
            assert body["authentication"]["symmetricKey"]["primaryKey"] == "321"
            assert body["authentication"]["symmetricKey"]["secondaryKey"] == "123"

        headers = args[0][1]
        assert headers["If-Match"] == '"{}"'.format(etag if etag else "*")

    @pytest.fixture(params=[200])
    def serviceclient_invalid_args(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        kvp = {}
        kvp.setdefault("authentication", {"type": "test"})
        test_side_effect = [
            build_mock_response(mocker, 200, generate_device_show(**kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize(
        "req, exp", [("primary", CLIError), ("secondary", CLIError), ("swap", CLIError)]
    )
    def test_device_key_regenerate_invalid_args(
        self, fixture_cmd, serviceclient_invalid_args, req, exp
    ):
        with pytest.raises(exp):
            subject.iot_device_key_regenerate(
                cmd=fixture_cmd,
                hub_name=mock_target["entity"],
                device_id=device_id,
                renew_key_type=req,
            )

    @pytest.mark.parametrize("req", ["primary", "secondary", "swap"])
    def test_device_key_regenerate_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_key_regenerate(
                cmd=fixture_cmd,
                hub_name=mock_target["entity"],
                device_id=device_id,
                renew_key_type=req,
            )


class TestDeviceDelete:
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("target_etag", [generate_generic_id(), None])
    def test_device_delete(self, serviceclient, target_etag):
        subject.iot_device_delete(
            cmd=fixture_cmd,
            device_id=device_id,
            hub_name=mock_target["entity"],
            etag=target_etag,
        )
        args = serviceclient.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target["entity"], device_id) in url
        assert args[0][0].method == "DELETE"
        headers = args[0][1]
        assert headers["If-Match"] == '"{}"'.format(target_etag if target_etag else "*")

    def test_device_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_delete(fixture_cmd, device_id, mock_target["entity"])


# Starting PoC for improving/simplyfing unit tests
class TestDeviceShow:
    def test_device_show(self, fixture_cmd, mocked_response, fixture_ghcs):
        device_id = generate_generic_id()
        mocked_response.add(
            method=responses.GET,
            url=re.compile(
                "https://{}/devices/{}".format(mock_target["entity"], device_id)
            ),
            body=json.dumps(generate_device_show(deviceId=device_id)),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        result = subject.iot_device_show(
            cmd=fixture_cmd, device_id=device_id, hub_name=mock_target["entity"]
        )
        assert result["deviceId"] == device_id

    def test_device_show_error(self, fixture_cmd, service_client_generic_errors):
        with pytest.raises(CLIError):
            subject.iot_device_show(
                cmd=fixture_cmd, device_id=device_id, hub_name=mock_target["entity"]
            )


class TestDeviceTwinList:
    @pytest.fixture(params=[10, 0])
    def service_client(self, mocked_response, fixture_ghcs, request):
        result = []
        size = request.param
        for _ in range(size):
            result.append(generate_device_show())

        mocked_response.add(
            method=responses.POST,
            url="https://{}/devices/query".format(mock_target["entity"]),
            body=json.dumps(result),
            headers={"x-ms-continuation": ""},
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.expected_size = size
        yield mocked_response

    @pytest.mark.parametrize("top, edge", [(10, True), (1000, False)])
    def test_device_list(self, fixture_cmd, service_client, top, edge):
        result = subject.iot_device_twin_list(
            cmd=fixture_cmd, hub_name=mock_target["entity"], top=top, edge_enabled=edge
        )
        list_request = service_client.calls[0].request

        body = json.loads(list_request.body)
        headers = list_request.headers

        if edge:
            assert (
                body["query"]
                == "select * from devices where capabilities.iotEdge = true"
            )
        else:
            assert body["query"] == "select * from devices"

        assert json.dumps(result)
        assert len(result) == service_client.expected_size
        assert headers["x-ms-max-item-count"] == str(top)

    @pytest.mark.parametrize("top", [-2, 0])
    def test_device_list_invalid_args(self, fixture_cmd, top):
        with pytest.raises(CLIError):
            subject.iot_device_twin_list(
                cmd=fixture_cmd, hub_name=mock_target["entity"], top=top
            )

    def test_device_list_error(self, fixture_cmd, service_client_generic_errors):
        service_client_generic_errors.assert_all_requests_are_fired = False
        with pytest.raises(CLIError):
            subject.iot_device_twin_list(
                cmd=fixture_cmd, hub_name=mock_target["entity"],
            )


def generate_module_create_req(
    mid=module_id, **kwargs
):
    r = generate_device_create_req(**kwargs)
    r["module_id"] = mid
    return r


class TestDeviceModuleCreate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "req",
        [
            (generate_module_create_req(auth="shared_private_key")),
            (generate_module_create_req(pk=generate_generic_id(), sk=generate_generic_id())),
            (generate_module_create_req(auth="x509_ca")),
            (generate_module_create_req(auth="x509_thumbprint")),
            (generate_module_create_req(auth="x509_thumbprint", stp=None)),
            (
                generate_module_create_req(
                    auth="x509_thumbprint", ptp=None, stp=None, valid_days=30
                )
            ),
        ],
    )
    def test_device_module_create(self, serviceclient, req):
        subject.iot_device_module_create(
            cmd=fixture_cmd,
            device_id=req["device_id"],
            hub_name=req["hub_name"],
            module_id=req["module_id"],
            auth_method=req["auth"],
            primary_key=req["pk"],
            secondary_key=req["sk"],
            primary_thumbprint=req["ptp"],
            secondary_thumbprint=req["stp"],
            valid_days=req.get("valid_days"),
        )

        args = serviceclient.call_args
        assert (
            "{}/devices/{}/modules/{}?".format(
                mock_target["entity"], device_id, module_id
            )
            in args[0][0].url
        )
        assert args[0][0].method == "PUT"

        body = args[0][2]
        assert body["deviceId"] == req["device_id"]
        assert body["moduleId"] == req["module_id"]

        if req["auth"] == "shared_private_key":
            assert body["authentication"]["type"] == DeviceAuthApiType.sas.value
            if all([req["pk"], req["pk"]]):
                assert body["authentication"]["symmetricKey"]["primaryKey"] == req["pk"]
                assert body["authentication"]["symmetricKey"]["secondaryKey"] == req["sk"]
            else:
                assert body["authentication"]["symmetricKey"] == {}
        elif req["auth"] == "x509_ca":
            assert body["authentication"]["type"] == DeviceAuthApiType.certificateAuthority.value
            assert not body["authentication"].get("x509Thumbprint")
            assert not body["authentication"].get("symmetricKey")
        elif req["auth"] == "x509_thumbprint":
            assert body["authentication"]["type"] == DeviceAuthApiType.selfSigned.value
            x509tp = body["authentication"]["x509Thumbprint"]
            assert x509tp["primaryThumbprint"]
            if req["stp"] is None:
                assert x509tp.get("secondaryThumbprint") is None
            else:
                assert x509tp["secondaryThumbprint"] == req["stp"]

    @pytest.mark.parametrize(
        "req, exp",
        [
            (
                generate_module_create_req(ee=True, auth="x509_thumbprint", ptp=None),
                CLIError,
            ),
            (generate_module_create_req(auth="doesnotexist"), CLIError),
            (
                generate_module_create_req(auth="x509_thumbprint", ptp=None, stp=""),
                CLIError,
            ),
            (generate_module_create_req(pk=generate_generic_id()), CLIError),
            (generate_module_create_req(sk=generate_generic_id()), CLIError)
        ],
    )
    def test_device_module_create_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_module_create(
                cmd=fixture_cmd,
                device_id=req["device_id"],
                module_id=req["module_id"],
                hub_name=req["hub_name"],
                auth_method=req["auth"],
                primary_key=req["pk"],
                secondary_key=req["sk"],
                primary_thumbprint=req["ptp"],
            )

    @pytest.mark.parametrize("req", [(generate_module_create_req())])
    def test_device_module_create_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_module_create(
                cmd=fixture_cmd,
                device_id=req["device_id"],
                hub_name=req["hub_name"],
                module_id=req["module_id"],
            )


def generate_device_module_show(**kvp):
    payload = generate_device_show(**kvp)
    payload["moduleId"] = module_id
    return payload


class TestDeviceModuleUpdate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize(
        "req",
        [
            (
                generate_device_module_show(
                    authentication={
                        "symmetricKey": {"primaryKey": "", "secondaryKey": ""},
                        "type": DeviceAuthApiType.sas.value,
                    },
                    etag=generate_generic_id(),
                )
            ),
            (
                generate_device_module_show(
                    authentication={
                        "x509Thumbprint": {
                            "primaryThumbprint": "123",
                            "secondaryThumbprint": "321",
                        },
                        "type": DeviceAuthApiType.selfSigned.value,
                    }
                )
            ),
            (
                generate_device_module_show(
                    authentication={"type": DeviceAuthApiType.certificateAuthority.value}
                )
            ),
        ],
    )
    def test_device_module_update(self, serviceclient, req):
        subject.iot_device_module_update(
            cmd=fixture_cmd,
            device_id=req["deviceId"],
            module_id=req["moduleId"],
            hub_name=mock_target["entity"],
            parameters=req,
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = args[0][2]

        assert (
            "{}/devices/{}/modules/{}?".format(
                mock_target["entity"], device_id, module_id
            )
            in url
        )
        assert method == "PUT"
        assert body["deviceId"] == req["deviceId"]
        assert body["moduleId"] == req["moduleId"]
        assert not body.get("capabilities")
        assert req["authentication"]["type"] == body["authentication"]["type"]
        if req["authentication"]["type"] == DeviceAuthApiType.certificateAuthority.value:
            assert not body["authentication"].get("x509Thumbprint")
            assert not body["authentication"].get("symmetricKey")
        elif req["authentication"]["type"] == DeviceAuthApiType.selfSigned.value:
            assert body["authentication"]["x509Thumbprint"]["primaryThumbprint"]
            assert body["authentication"]["x509Thumbprint"]["secondaryThumbprint"]

        target_etag = req.get("etag")
        headers = args[0][1]
        assert headers["If-Match"] == '"{}"'.format(target_etag if target_etag else "*")

    @pytest.mark.parametrize(
        "req, exp",
        [
            (
                generate_device_module_show(
                    authentication={
                        "x509Thumbprint": {
                            "primaryThumbprint": "",
                            "secondaryThumbprint": "",
                        },
                        "type": DeviceAuthApiType.selfSigned.value,
                    }
                ),
                CLIError,
            ),
            (
                generate_device_module_show(authentication={"type": "doesnotexist"}),
                CLIError,
            ),
        ],
    )
    def test_device_module_update_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_module_update(
                cmd=fixture_cmd,
                device_id=req["deviceId"],
                module_id=req["moduleId"],
                hub_name=mock_target["entity"],
                parameters=req,
            )

    @pytest.mark.parametrize("req", [(generate_device_module_show())])
    def test_device_module_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_module_update(
                cmd=fixture_cmd,
                device_id=req["deviceId"],
                hub_name=mock_target["entity"],
                module_id=req["moduleId"],
                parameters=req,
            )


class TestDeviceModuleDelete:
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("target_etag", [generate_generic_id(), None])
    def test_device_module_delete(self, serviceclient, target_etag):
        subject.iot_device_module_delete(
            cmd=fixture_cmd,
            device_id=device_id,
            module_id=module_id,
            hub_name=mock_target["entity"],
            etag=target_etag,
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][1]

        assert "devices/{}/modules/{}?".format(device_id, module_id) in url
        assert method == "DELETE"
        assert headers["If-Match"] == '"{}"'.format(target_etag if target_etag else "*")

    def test_device_module_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_delete(
                cmd=fixture_cmd,
                device_id=device_id,
                module_id=module_id,
                hub_name=mock_target["entity"],
            )


class TestDeviceModuleShow:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    def test_device_module_show(self, serviceclient):
        result = subject.iot_device_module_show(
            cmd=fixture_cmd, device_id=device_id, module_id=module_id, hub_name=mock_target["entity"]
        )
        assert json.dumps(result)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert "devices/{}/modules/{}?".format(device_id, module_id) in url
        assert method == "GET"

    def test_device_module_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_show(
                cmd=fixture_cmd,
                device_id=device_id,
                module_id=module_id,
                hub_name=mock_target["entity"],
            )


class TestDeviceModuleList:
    @pytest.fixture(params=[(200, 10), (200, 0)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        result = []
        size = request.param[1]
        for _ in range(size):
            result.append(generate_device_module_show())
        service_client.expected_size = size
        service_client.return_value = build_mock_response(
            mocker, request.param[0], result
        )
        return service_client

    @pytest.mark.parametrize("top", [10, 1000])
    def test_device_module_list(self, serviceclient, top):
        result = subject.iot_device_module_list(
            cmd=fixture_cmd, device_id=device_id, hub_name=mock_target["entity"], top=top
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert method == "GET"
        assert "{}/devices/{}/modules?".format(mock_target["entity"], device_id) in url
        assert len(result) == serviceclient.expected_size

    def test_device_module_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_list(
                cmd=fixture_cmd, device_id=device_id, hub_name=mock_target["entity"]
            )


def change_dir():
    from inspect import getsourcefile

    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))


def generate_device_twin_show(file_handle=False, **kvp):
    if file_handle:
        change_dir()
        path = os.path.join(Path(CWD).parent, "test_generic_twin.json")
        return path

    payload = {"deviceId": device_id}
    for k in kvp:
        payload[k] = kvp[k]
    return payload


class TestDeviceTwinShow:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, payload=generate_device_twin_show()
        )
        return service_client

    def test_device_twin_show(self, serviceclient):
        result = subject.iot_device_twin_show(
            cmd=fixture_cmd, device_id=device_id, hub_name=mock_target["entity"]
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert json.dumps(result)
        assert method == "GET"
        assert "{}/twins/{}?".format(mock_target["entity"], device_id) in url

    def test_device_twin_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_twin_show(
                cmd=None, device_id=device_id, hub_name=mock_target["entity"]
            )


class TestDeviceTwinUpdate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, payload=generate_device_twin_show()
        )
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize(
        "req",
        [
            generate_device_twin_show(
                properties={"desired": {"key": "value"}}, etag="abcd"
            ),
            generate_device_twin_show(properties={"desired": {"key": "value"}}),
        ],
    )
    def test_device_twin_update(self, serviceclient, req):
        subject.iot_device_twin_update(
            cmd=fixture_cmd,
            device_id=req["deviceId"],
            hub_name=mock_target["entity"],
            parameters=req,
            etag=req.get("etag"),
        )
        args = serviceclient.call_args
        body = args[0][2]
        assert body == req
        assert "twins/{}".format(device_id) in args[0][0].url

        target_etag = req.get("etag")
        headers = args[0][1]
        assert headers["If-Match"] == '"{}"'.format(target_etag if target_etag else "*")

    @pytest.mark.parametrize("req", [generate_device_twin_show()])
    def test_device_twin_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_twin_update(
                cmd=fixture_cmd,
                device_id=req["deviceId"],
                hub_name=mock_target["entity"],
                parameters=req,
            )


class TestDeviceTwinReplace:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, generate_device_twin_show(moduleId=module_id)
        )
        return service_client

    # Replace does a GET/SHOW first
    @pytest.mark.parametrize(
        "req, isfile, etag",
        [
            (
                generate_device_twin_show(moduleId=module_id),
                False,
                generate_generic_id(),
            ),
            (
                generate_device_twin_show(
                    moduleId=module_id, properties={"desired": {"key": "value"}}
                ),
                False,
                None,
            ),
            (generate_device_twin_show(file_handle=True), True, None),
        ],
    )
    def test_device_twin_replace(self, serviceclient, req, isfile, etag):
        if not isfile:
            req = json.dumps(req)
        subject.iot_device_twin_replace(
            cmd=fixture_cmd,
            device_id=device_id,
            hub_name=mock_target["entity"],
            target_json=req,
            etag=etag,
        )
        args = serviceclient.call_args
        body = args[0][2]
        if isfile:
            content = str(read_file_content(req))
            assert body == json.loads(content)
        else:
            assert body == json.loads(req)
        assert "{}/twins/{}?".format(mock_target["entity"], device_id) in args[0][0].url
        assert args[0][0].method == "PUT"

        headers = args[0][1]
        assert headers["If-Match"] == '"{}"'.format(etag if etag else "*")

    @pytest.mark.parametrize("req", [(generate_device_twin_show(moduleId=module_id))])
    def test_device_twin_replace_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_twin_replace(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name=mock_target["entity"],
                target_json=json.dumps(req),
            )


class TestDeviceModuleTwinShow:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, payload=generate_device_twin_show()
        )
        return service_client

    def test_device_module_twin_show(self, serviceclient):
        result = subject.iot_device_module_twin_show(
            cmd=fixture_cmd, device_id=device_id, hub_name=mock_target["entity"], module_id=module_id
        )
        args = serviceclient.call_args
        assert "twins/{}".format(device_id) in args[0][0].url
        assert "modules/{}".format(module_id) in args[0][0].url
        assert json.dumps(result)

    def test_device_module_twin_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_twin_show(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name=mock_target["entity"],
                module_id=module_id,
            )


class TestDeviceModuleTwinUpdate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, payload=generate_device_twin_show(moduleId=module_id)
        )
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize(
        "req",
        [
            (
                generate_device_twin_show(
                    moduleId=module_id,
                    properties={"desired": {"key": "value"}},
                    etag=generate_generic_id(),
                )
            ),
            (
                generate_device_twin_show(
                    moduleId=module_id, properties={"desired": {"key": "value"}}
                )
            ),
        ],
    )
    def test_device_module_twin_update(self, serviceclient, req):
        subject.iot_device_module_twin_update(
            cmd=fixture_cmd,
            device_id=req["deviceId"],
            hub_name=mock_target["entity"],
            module_id=module_id,
            parameters=req,
            etag=req.get("etag"),
        )
        args = serviceclient.call_args
        body = args[0][2]
        assert body == req
        assert (
            "twins/{}/modules/{}?".format(req["deviceId"], module_id) in args[0][0].url
        )

        target_etag = req.get("etag")
        headers = args[0][1]
        assert headers["If-Match"] == '"{}"'.format(target_etag if target_etag else "*")

    @pytest.mark.parametrize("req", [(generate_device_twin_show(moduleId=module_id))])
    def test_device_module_twin_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_module_twin_update(
                cmd=fixture_cmd,
                device_id=req["deviceId"],
                hub_name=mock_target["entity"],
                module_id=module_id,
                parameters=req,
            )


class TestDeviceModuleTwinReplace:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, payload=generate_device_twin_show(moduleId=module_id)
        )
        return service_client

    # Replace does a GET/SHOW first
    @pytest.mark.parametrize(
        "req, isfile, etag",
        [
            (
                generate_device_twin_show(moduleId=module_id),
                False,
                generate_generic_id(),
            ),
            (
                generate_device_twin_show(
                    moduleId=module_id, properties={"desired": {"key": "value"}}
                ),
                False,
                None,
            ),
            (generate_device_twin_show(file_handle=True), True, None),
        ],
    )
    def test_device_module_twin_replace(self, serviceclient, req, isfile, etag):
        if not isfile:
            req = json.dumps(req)
        subject.iot_device_module_twin_replace(
            cmd=fixture_cmd,
            device_id=device_id,
            hub_name=mock_target["entity"],
            module_id=module_id,
            target_json=req,
            etag=etag,
        )
        args = serviceclient.call_args
        body = args[0][2]
        if isfile:
            content = str(read_file_content(req))
            assert body == json.loads(content)
        else:
            assert body == json.loads(req)
        assert "twins/{}/modules/{}?".format(device_id, module_id) in args[0][0].url
        assert args[0][0].method == "PUT"

        headers = args[0][1]
        assert headers["If-Match"] == '"{}"'.format(etag if etag else "*")

    @pytest.mark.parametrize("req", [(generate_device_twin_show(moduleId=module_id))])
    def test_device_module_twin_replace_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_module_twin_replace(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name=mock_target["entity"],
                module_id=module_id,
                target_json=json.dumps(req),
            )


generic_query = "select * from devices"


class TestQuery:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        return service_client

    @pytest.mark.parametrize(
        "query, servresult, servtotal, top",
        [
            (generic_query, [generate_device_twin_show()], 6, 3),
            (
                generic_query,
                [generate_device_twin_show(), generate_device_twin_show()],
                5,
                2,
            ),
            (
                generic_query,
                [generate_device_twin_show(), generate_device_twin_show()],
                6,
                None,
            ),
            (generic_query, [generate_device_show() for i in range(0, 12)], 100, 51),
            (generic_query, [generate_device_twin_show()], 1, 100),
        ],
    )
    def test_query_basic(self, serviceclient, query, servresult, servtotal, top):
        pagesize = len(servresult)
        continuation = []

        for i in range(int(servtotal / pagesize)):
            continuation.append(generate_generic_id())
        if servtotal % pagesize != 0:
            continuation.append(generate_generic_id())
        continuation[-1] = None

        serviceclient.return_value = build_mock_response(
            status_code=200, payload=servresult, headers_get_side_effect=continuation
        )

        result = subject.iot_query(
            cmd=None, hub_name=mock_target["entity"], query_command=query, top=top
        )

        if top and top < servtotal:
            targetcount = top
        else:
            targetcount = servtotal

        assert len(result) == targetcount

        if pagesize >= targetcount:
            assert serviceclient.call_count == 1
        else:
            if targetcount % pagesize == 0:
                assert serviceclient.call_count == int(targetcount / pagesize)
            else:
                assert serviceclient.call_count == int(targetcount / pagesize) + 1

        args = serviceclient.call_args_list[0]
        headers = args[0][1]
        body = args[0][2]
        assert body["query"] == query

        if top:
            targetcount = top
            if pagesize < top:
                for i in range(1, len(serviceclient.call_args_list)):
                    headers = serviceclient.call_args_list[i][0][1]
                    targetcount = targetcount - pagesize
                    assert headers["x-ms-max-item-count"] == str(targetcount)
            else:
                assert headers["x-ms-max-item-count"] == str(targetcount)
        else:
            assert not headers.get("x-ms-max-item-count")

    @pytest.mark.parametrize("top", [-2, 0])
    def test_query_invalid_args(self, top):
        with pytest.raises(CLIError):
            subject.iot_query(
                cmd=None, hub_name=mock_target["entity"], query_command=generic_query, top=top
            )

    def test_query_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_query(
                cmd=None, hub_name=mock_target["entity"], query_command=generic_query
            )


class TestDeviceMethodInvoke:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, {"payload": "value", "status": 0}
        )
        return service_client

    @pytest.mark.parametrize("methodbody", ['{"key":"value"}', None])
    def test_device_method(self, serviceclient, methodbody):
        payload = methodbody
        device_method = "mymethod"
        timeout = 100
        subject.iot_device_method(
            cmd=fixture_cmd,
            device_id=device_id,
            hub_name=mock_target["entity"],
            method_name=device_method,
            method_payload=payload,
            timeout=timeout,
        )
        args = serviceclient.call_args
        body = args[0][2]
        url = args[0][0].url
        method = args[0][0].method

        assert method == "POST"
        assert body["methodName"] == device_method

        if methodbody:
            assert body["payload"] == json.loads(payload)
        elif "payload" in body.keys():
            # We must ensure null is passed for payload.
            assert body["payload"] is None

        assert body["responseTimeoutInSeconds"] == timeout
        assert body["connectTimeoutInSeconds"] == timeout
        assert "{}/twins/{}/methods?".format(mock_target["entity"], device_id) in url

    @pytest.mark.parametrize(
        "req, etype, exp",
        [
            ("badformat", "payload", CLIError),
            ('{"key":"valu', "payload", CLIError),
            (1000, "timeout", CLIError),
            (5, "timeout", CLIError),
        ],
    )
    def test_device_method_invalid_args(self, serviceclient, req, etype, exp):
        with pytest.raises(exp):
            if etype == "payload":
                subject.iot_device_method(
                    fixture_cmd,
                    device_id=device_id,
                    hub_name=mock_target["entity"],
                    method_name="mymethod",
                    method_payload=req,
                )
            if etype == "timeout":
                subject.iot_device_method(
                    fixture_cmd,
                    device_id=device_id,
                    hub_name=mock_target["entity"],
                    method_name="mymethod",
                    method_payload='{"key":"value"}',
                    timeout=req,
                )

    def test_device_method_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_method(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name=mock_target["entity"],
                method_name="mymethod",
                method_payload='{"key":"value"}',
            )


class TestDeviceModuleMethodInvoke:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, {"payload": "value", "status": 0}
        )
        return service_client

    @pytest.mark.parametrize("methodbody", ['{"key":"value"}', None])
    def test_device_module_method(self, serviceclient, methodbody):
        payload = methodbody
        module_method = "mymethod"
        timeout = 100
        subject.iot_device_module_method(
            cmd=fixture_cmd,
            device_id=device_id,
            module_id=module_id,
            method_name=module_method,
            hub_name=mock_target["entity"],
            method_payload=payload,
            timeout=timeout,
        )
        args = serviceclient.call_args
        body = args[0][2]
        url = args[0][0].url
        method = args[0][0].method

        assert method == "POST"
        assert body["methodName"] == module_method

        if methodbody:
            assert body["payload"] == json.loads(payload)
        elif "payload" in body.keys():
            # We must ensure null is passed for payload.
            assert body["payload"] is None

        assert body["responseTimeoutInSeconds"] == timeout
        assert body["connectTimeoutInSeconds"] == timeout
        assert (
            "{}/twins/{}/modules/{}/methods?".format(
                mock_target["entity"], device_id, module_id
            )
            in url
        )

    @pytest.mark.parametrize(
        "req, etype, exp",
        [
            ("doesnotexist", "payload", CLIError),
            ('{"key":"valu', "payload", CLIError),
            (1000, "timeout", CLIError),
            (5, "timeout", CLIError),
        ],
    )
    def test_device_module_method_invalid_args(self, serviceclient, req, etype, exp):
        with pytest.raises(exp):
            if etype == "payload":
                subject.iot_device_module_method(
                    cmd=fixture_cmd,
                    device_id=device_id,
                    module_id=module_id,
                    method_name="mymethod",
                    hub_name=mock_target["entity"],
                    method_payload=req,
                )
            if etype == "timeout":
                subject.iot_device_module_method(
                    cmd=fixture_cmd,
                    device_id=device_id,
                    module_id=module_id,
                    method_name="mymethod",
                    hub_name=mock_target["entity"],
                    method_payload='{"key":"value"}',
                    timeout=req,
                )

    def test_device_method_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_method(
                cmd=fixture_cmd,
                device_id=device_id,
                module_id=module_id,
                method_name="mymethod",
                hub_name=mock_target["entity"],
                method_payload='{"key":"value"}',
            )


class TestSasTokenAuth:
    def test_generate_sas_token(self):
        # Prepare parameters
        uri = "iot-hub-for-test.azure-devices.net/devices/iot-device-for-test"
        policy_name = "iothubowner"
        access_key = "+XLy+MVZ+aTeOnVzN2kLeB16O+kSxmz6g3rS6fAf6rw="
        expiry = 1471940363

        # Action
        sas_auth = SasTokenAuthentication(uri, None, access_key, expiry)
        token = sas_auth.generate_sas_token(absolute=True)

        # Assertion
        assert "SharedAccessSignature " in token
        assert "sig=SIumZ1ACqqPJZ2okHDlW9MSYKykEpqsQY3z6FMOICd4%3D" in token
        assert "se=1471940363" in token
        assert (
            "sr=iot-hub-for-test.azure-devices.net%2Fdevices%2Fiot-device-for-test"
            in token
        )
        assert "skn=" not in token

        # Prepare parameters
        uri = "iot-hub-for-test.azure-devices.net"

        # Action
        sas_auth = SasTokenAuthentication(uri, policy_name, access_key, expiry)
        token = sas_auth.generate_sas_token(absolute=True)

        # Assertion
        assert "SharedAccessSignature " in token
        assert "sig=770sPjjYxRYpNz8%2FhEN7XR5XU5KDGYGTinSP8YyeTXw%3D" in token
        assert "se=1471940363" in token
        assert "sr=iot-hub-for-test.azure-devices.net" in token
        assert "skn=iothubowner" in token

        # Prepare parameters
        uri = "iot-hub-for-test.azure-devices.net/devices/iot-device-for-test/modules/module-for-test"

        # Action
        sas_auth = SasTokenAuthentication(uri, policy_name, access_key, expiry)
        token = sas_auth.generate_sas_token(absolute=True)

        # Assertion
        assert "SharedAccessSignature " in token
        assert "sig=JwAxBBBPYA0E%2FTHdnrXzUfBfuZ7deH6pppCniJ23Uu0%3D" in token
        assert "se=1471940363" in token
        assert (
            "sr=iot-hub-for-test.azure-devices.net%2Fdevices%2Fiot-device-for-test%2Fmodules%2Fmodule-for-test"
            in token
        )
        assert "skn=iothubowner" in token


class TestMonitorEvents:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param)
        existing_target = fixture_ghcs.return_value
        existing_target["events"] = {}
        existing_target["events"]["partition_ids"] = []
        return service_client

    @pytest.mark.parametrize(
        "req",
        [
            (
                create_req_monitor_events(
                    device_id="mydevice",
                    device_query="select * from devices",
                    consumer_group="group1",
                    content_type="application/json",
                    enqueued_time="54321",
                    timeout="30",
                    hub_name="myhub",
                    resource_group_name="myrg",
                    yes=True,
                    properties="sys anno app",
                    repair=True,
                    login=mock_target["cs"],
                )
            )
        ],
    )
    def test_monitor_events_entrypoint(
        self, fixture_cmd, fixture_monitor_events_entrypoint, req
    ):
        subject.iot_hub_monitor_events(
            cmd=fixture_cmd,
            device_id=req["device_id"],
            device_query=req["device_query"],
            consumer_group=req["consumer_group"],
            content_type=req["content_type"],
            enqueued_time=req["enqueued_time"],
            timeout=req["timeout"],
            hub_name=req["hub_name"],
            resource_group_name=req["resource_group_name"],
            yes=req["yes"],
            properties=req["properties"],
            repair=req["repair"],
            login=req["login"],
        )

        monitor_events_args = fixture_monitor_events_entrypoint.call_args[1]

        attribute_set = [
            "device_id",
            "device_query",
            "consumer_group",
            "enqueued_time",
            "content_type",
            "timeout",
            "login",
            "hub_name",
            "resource_group_name",
            "yes",
            "properties",
            "repair",
        ]

        assert "interface" not in monitor_events_args

        for attribute in attribute_set:
            if req[attribute]:
                assert monitor_events_args[attribute] == req[attribute]
            else:
                assert not monitor_events_args[attribute]

    @pytest.mark.parametrize("timeout, exception", [(-1, CLIError)])
    def test_monitor_events_invalid_args(
        self, fixture_cmd, serviceclient, timeout, exception
    ):
        with pytest.raises(exception):
            subject.iot_hub_monitor_events(
                fixture_cmd, mock_target["entity"], device_id, timeout=timeout
            )


def generate_parent_device(**kvp):
    payload = {
        "etag": "abcd",
        "capabilities": {"iotEdge": True},
        "deviceId": device_id,
        "status": "disabled",
        "deviceScope": "ms-azure-iot-edge://{}-1234".format(device_id),
        "parentScopes": ["ms-azure-iot-edge://{}-5678".format(device_id)],
    }
    for k in kvp:
        if payload.get(k):
            payload[k] = kvp[k]
    return payload


def generate_child_device(**kvp):
    payload = {
        "etag": "abcd",
        "capabilities": {"iotEdge": False},
        "deviceId": child_device_id,
        "status": "disabled",
        "deviceScope": "",
    }
    for k in kvp:
        payload[k] = kvp[k]
    return payload


class TestEdgeOffline:

    # get-parent
    @pytest.fixture(params=[(200, 200)])
    def sc_getparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[0], generate_parent_device()),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_get_parent(self, sc_getparent):
        result = subject.iot_device_get_parent(
            fixture_cmd, child_device_id, mock_target["entity"]
        )
        args = sc_getparent.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target["entity"], device_id) in url
        assert args[0][0].method == "GET"
        assert json.dumps(result)

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_getparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        if request.param[1] == 0:
            child_kvp.setdefault("parentScopes", [])
        if request.param[1] == 1:
            child_kvp.setdefault("deviceId", "")
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            )
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_getparent_invalid_args(self, sc_invalid_args_getparent, exp):
        with pytest.raises(exp):
            subject.iot_device_get_parent(fixture_cmd, device_id, mock_target["entity"])

    def test_device_getparent_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_get_parent(fixture_cmd, device_id, mock_target["entity"])

    # set-parent
    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_setparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        if request.param[1] == 1:
            child_kvp.setdefault("parentScopes", ["abcd"])
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[0], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_set_parent(self, sc_setparent):
        subject.iot_device_set_parent(
            fixture_cmd, child_device_id, device_id, True, mock_target["entity"]
        )
        args = sc_setparent.call_args
        url = args[0][0].url
        body = args[0][2]
        assert "{}/devices/{}?".format(mock_target["entity"], child_device_id) in url
        assert args[0][0].method == "PUT"
        assert body["deviceId"] == child_device_id
        assert body["deviceScope"] == generate_parent_device().get("deviceScope")

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_setparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        parent_kvp = {}
        child_kvp = {}
        if request.param[1] == 0:
            parent_kvp.setdefault("capabilities", {"iotEdge": False})
        if request.param[1] == 1:
            child_kvp.setdefault("parentScopes", ["abcd"])
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], generate_parent_device(**parent_kvp)
            ),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_setparent_invalid_args(self, sc_invalid_args_setparent, exp):
        with pytest.raises(exp):
            subject.iot_device_set_parent(
                fixture_cmd, child_device_id, device_id, False, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def sc_setparent_error(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device()),
            build_mock_response(mocker, request.param[1], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_setparent_error(self, sc_setparent_error):
        with pytest.raises(CLIError):
            subject.iot_device_set_parent(
                fixture_cmd, child_device_id, device_id, False, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 200)])
    def sc_invalid_etag_setparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault("etag", None)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_setparent_invalid_etag(self, sc_invalid_etag_setparent, exp):
        with pytest.raises(exp):
            subject.iot_device_set_parent(
                fixture_cmd, child_device_id, device_id, True, mock_target["entity"]
            )

    # add-children
    @pytest.fixture(params=[(200, 0), (200, 1), (200, 2)])
    def sc_addchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        if request.param[1] == 1:
            child_kvp.setdefault("parentScopes", ["abcd"])
        if request.param[1] == 1:
            child_kvp.setdefault("capabilities", {"iotEdge": True})
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[0], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_children_add(self, sc_addchildren):
        subject.iot_device_children_add(
            None, device_id, [child_device_id], True, mock_target["entity"]
        )
        args = sc_addchildren.call_args
        url = args[0][0].url
        body = args[0][2]
        assert "{}/devices/{}?".format(mock_target["entity"], child_device_id) in url
        assert args[0][0].method == "PUT"
        assert body["deviceId"] == child_device_id
        assert body["deviceScope"] == generate_parent_device().get(
            "deviceScope"
        ) or body["parentScopes"] == [generate_parent_device().get("deviceScope")]

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_addchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        parent_kvp = {}
        child_kvp = {}
        if request.param[1] == 0:
            parent_kvp.setdefault("capabilities", {"iotEdge": False})
        if request.param[1] == 1:
            child_kvp.setdefault("parentScopes", ["abcd"])
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], generate_parent_device(**parent_kvp)
            ),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_addchildren_invalid_args(self, sc_invalid_args_addchildren, exp):
        with pytest.raises(exp):
            subject.iot_device_children_add(
                fixture_cmd, device_id, [child_device_id], False, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def sc_addchildren_error(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device()),
            build_mock_response(mocker, request.param[1], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_addchildren_error(self, sc_addchildren_error):
        with pytest.raises(CLIError):
            subject.iot_device_children_add(
                fixture_cmd, device_id, [child_device_id], True, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 200)])
    def sc_invalid_etag_addchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault("etag", None)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_addchildren_invalid_etag(self, sc_invalid_etag_setparent, exp):
        with pytest.raises(exp):
            subject.iot_device_children_add(
                fixture_cmd, device_id, [child_device_id], True, mock_target["entity"]
            )

    # list-children
    @pytest.fixture
    def sc_listchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        result = []
        result.append(generate_child_device(**child_kvp))
        test_side_effect = [
            build_mock_response(mocker, 200, generate_parent_device()),
            build_mock_response(mocker, 200, result, {"x-ms-continuation": None}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_children_list(self, sc_listchildren):
        result = subject.iot_device_children_list(
            fixture_cmd, device_id, mock_target["entity"]
        )
        args = sc_listchildren.call_args
        url = args[0][0].url
        assert "{}/devices/query?".format(mock_target["entity"]) in url
        assert args[0][0].method == "POST"
        assert result == [child_device_id]

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_listchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        parent_kvp = {}
        if request.param[1] == 0:
            parent_kvp.setdefault("capabilities", {"iotEdge": False})
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], generate_parent_device(**parent_kvp)
            ),
            build_mock_response(
                mocker, request.param[0], [], {"x-ms-continuation": None}
            ),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_listchildren_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_children_list(
                fixture_cmd, device_id, mock_target["entity"]
            )

    # remove-children
    @pytest.fixture(params=[(200, 200)])
    def sc_removechildrenlist(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[0], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_children_remove_list(self, sc_removechildrenlist):
        subject.iot_device_children_remove(
            fixture_cmd, device_id, [child_device_id], False, mock_target["entity"]
        )
        args = sc_removechildrenlist.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target["entity"], child_device_id) in url
        assert args[0][0].method == "PUT"

    @pytest.fixture(params=[(200, 0), (200, 1), (200, 2), (200, 3)])
    def sc_invalid_args_removechildrenlist(
        self, mocker, fixture_ghcs, fixture_sas, request
    ):
        service_client = mocker.patch(path_service_client)
        parent_kvp = {}
        child_kvp = {}
        if request.param[1] == 0:
            parent_kvp.setdefault("capabilities", {"iotEdge": False})
        if request.param[1] == 2:
            child_kvp.setdefault("parentScopes", [""])
        if request.param[1] == 2:
            child_kvp.setdefault("deviceScope", "")
        if request.param[1] == 3:
            child_kvp.setdefault("deviceScope", "other")
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], generate_parent_device(**parent_kvp)
            ),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_removechildrenlist_invalid_args(
        self, sc_invalid_args_removechildrenlist, exp
    ):
        with pytest.raises(exp):
            subject.iot_device_children_remove(
                fixture_cmd, device_id, [child_device_id], False, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 200)])
    def sc_invalid_etag_removechildrenlist(
        self, mocker, fixture_ghcs, fixture_sas, request
    ):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        child_kvp.setdefault("etag", None)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[0], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_removechildrenlist_invalid_etag(
        self, sc_invalid_etag_removechildrenlist, exp
    ):
        with pytest.raises(exp):
            subject.iot_device_children_remove(
                fixture_cmd, device_id, [child_device_id], False, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def sc_removechildrenlist_error(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[1], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_removechildrenlist_error(self, sc_removechildrenlist_error):
        with pytest.raises(CLIError):
            subject.iot_device_children_remove(
                fixture_cmd, device_id, child_device_id, False, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 200)])
    def sc_removechildrenall(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        result = []
        result.append(generate_child_device(**child_kvp))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], result, {"x-ms-continuation": None}
            ),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[0], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_children_remove_all(self, sc_removechildrenall):
        subject.iot_device_children_remove(
            fixture_cmd, device_id, None, True, mock_target["entity"]
        )
        args = sc_removechildrenall.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target["entity"], child_device_id) in url
        assert args[0][0].method == "PUT"

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_removechildrenall(
        self, mocker, fixture_ghcs, fixture_sas, request
    ):
        service_client = mocker.patch(path_service_client)
        parent_kvp = {}
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        result = []
        result.append(generate_child_device(**child_kvp))
        if request.param[1] == 0:
            parent_kvp.setdefault("capabilities", {"iotEdge": False})
        if request.param[1] == 1:
            result = []
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], generate_parent_device(**parent_kvp)
            ),
            build_mock_response(
                mocker, request.param[0], result, {"x-ms-continuation": None}
            ),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_removechildrenall_invalid_args(
        self, sc_invalid_args_removechildrenall, exp
    ):
        with pytest.raises(exp):
            subject.iot_device_children_remove(
                fixture_cmd, device_id, None, True, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 200)])
    def sc_invalid_etag_removechildrenall(
        self, mocker, fixture_ghcs, fixture_sas, request
    ):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        child_kvp.setdefault("etag", None)
        result = []
        result.append(generate_child_device(**child_kvp))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], result, {"x-ms-continuation": None}
            ),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[0], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_removechildrenall_invalid_etag(
        self, sc_invalid_etag_removechildrenall, exp
    ):
        with pytest.raises(exp):
            subject.iot_device_children_remove(
                fixture_cmd, device_id, None, True, mock_target["entity"]
            )

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def sc_removechildrenall_error(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        child_kvp = {}
        child_kvp.setdefault(
            "parentScopes", [generate_parent_device().get("deviceScope")]
        )
        result = []
        result.append(generate_child_device(**child_kvp))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(
                mocker, request.param[0], result, {"x-ms-continuation": None}
            ),
            build_mock_response(
                mocker, request.param[0], generate_child_device(**child_kvp)
            ),
            build_mock_response(mocker, request.param[1], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_removechildrenall_error(self, sc_removechildrenall_error):
        with pytest.raises(CLIError):
            subject.iot_device_children_remove(
                fixture_cmd, device_id, None, True, mock_target["entity"]
            )


class TestDeviceDistributedTracing:
    @pytest.fixture(params=[(200, 200)])
    def sc_distributed_tracing_show(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        twin_kvp = {}
        twin_kvp.setdefault("capabilities", {"iotEdge": False})
        twin_kvp.setdefault(
            "properties",
            {
                "desired": {
                    TRACING_PROPERTY: {"sampling_mode": 1, "sampling_rate": 50}
                },
                "reported": {},
            },
        )
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], payload=generate_device_twin_show(**twin_kvp)
            )
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_distributed_tracing_show(self, sc_distributed_tracing_show):
        result = subject.iot_hub_distributed_tracing_show(
            fixture_cmd, mock_target["entity"], device_id
        )
        args = sc_distributed_tracing_show.call_args
        url = args[0][0].url
        assert "{}/twins/{}?".format(mock_target["entity"], device_id) in url
        assert args[0][0].method == "GET"
        assert result["deviceId"] == device_id
        assert result["samplingMode"] == "enabled"
        assert result["samplingRate"] == "50%"
        assert not result["isSynced"]
        assert json.dumps(result)

    @pytest.fixture(params=[(200, 0), (200, 1), (200, 2)])
    def sc_invalid_args_distributed_tracing_show(
        self, mocker, fixture_ghcs, fixture_sas, request
    ):
        service_client = mocker.patch(path_service_client)
        twin_kvp = {}
        twin_kvp.setdefault("capabilities", {"iotEdge": False})
        if request.param[1] == 0:
            mock_target["location"] = "westus"
        if request.param[1] == 1:
            mock_target["sku_tier"] = "Basic"
        if request.param[1] == 2:
            twin_kvp.setdefault("capabilities", {"iotEdge": True})
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], payload=generate_device_twin_show(**twin_kvp)
            )
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_distributed_tracing_show_invalid_args(
        self, sc_invalid_args_distributed_tracing_show, exp
    ):
        with pytest.raises(exp):
            subject.iot_hub_distributed_tracing_show(
                fixture_cmd, mock_target["entity"], device_id
            )

    def test_distributed_tracing_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_hub_distributed_tracing_show(
                fixture_cmd, mock_target["entity"], device_id
            )

    @pytest.fixture(params=[(200, 0), (200, 1), (200, 2)])
    def sc_distributed_tracing_update(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        twin_kvp = {}
        twin_kvp.setdefault("capabilities", {"iotEdge": False})
        mock_target["location"] = "westus2"
        mock_target["sku_tier"] = "Standard"
        if request.param[1] == 0:
            twin_kvp.setdefault(
                "properties",
                {
                    "desired": {
                        TRACING_PROPERTY: {"sampling_mode": 1, "sampling_rate": 50}
                    },
                    "reported": {},
                },
            )
        if request.param[1] == 1:
            twin_kvp.setdefault("properties", {"desired": {}, "reported": {}})
        if request.param[1] == 2:
            twin_kvp.setdefault(
                "properties",
                {
                    "desired": {
                        TRACING_PROPERTY: {"sampling_mode": 2, "sampling_rate": 0}
                    },
                    "reported": {},
                },
            )
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], payload=generate_device_twin_show(**twin_kvp)
            ),
            build_mock_response(
                mocker,
                request.param[0],
                generate_device_twin_show(
                    properties={
                        "desired": {
                            TRACING_PROPERTY: {"sampling_mode": 1, "sampling_rate": 58}
                        },
                        "reported": {},
                    }
                ),
            ),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_distributed_tracing_update(self, sc_distributed_tracing_update):
        result = subject.iot_hub_distributed_tracing_update(
            fixture_cmd, mock_target["entity"], device_id, "on", 58
        )
        args = sc_distributed_tracing_update.call_args
        url = args[0][0].url
        assert "{}/twins/{}?".format(mock_target["entity"], device_id) in url
        assert args[0][0].method == "PATCH"
        assert result["deviceId"] == device_id
        assert result["samplingMode"] == "enabled"
        assert result["samplingRate"] == "58%"
        assert not result["isSynced"]
        assert json.dumps(result)

    @pytest.fixture(params=[(200, 0), (200, 1), (200, 2)])
    def sc_invalid_args_distributed_tracing_update(
        self, mocker, fixture_ghcs, fixture_sas, request
    ):
        service_client = mocker.patch(path_service_client)
        twin_kvp = {}
        twin_kvp.setdefault("capabilities", {"iotEdge": False})
        if request.param[1] == 0:
            mock_target["location"] = "westus"
        if request.param[1] == 1:
            mock_target["sku_tier"] = "Basic"
        if request.param[1] == 2:
            twin_kvp.setdefault("capabilities", {"iotEdge": True})
        test_side_effect = [
            build_mock_response(
                mocker, request.param[0], payload=generate_device_twin_show(**twin_kvp)
            )
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_distributed_tracing_update_invalid_args(
        self, sc_invalid_args_distributed_tracing_update, exp
    ):
        with pytest.raises(exp):
            subject.iot_hub_distributed_tracing_update(
                fixture_cmd, mock_target["entity"], device_id, "on", 58
            )

    def test_distributed_tracing_update_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_hub_distributed_tracing_update(
                fixture_cmd, mock_target["entity"], device_id, "on", 58
            )
