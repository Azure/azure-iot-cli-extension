# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
import responses
import re
from azext_iot.iothub import commands_device_messaging as subject
from azext_iot.common.utility import validate_key_value_pairs
from azext_iot.iothub.providers import mqtt as mqtt_subject
from knack.util import CLIError
from azext_iot.tests.conftest import (
    fixture_cmd,
    build_mock_response,
    path_service_client,
    mock_target,
)


device_id = "mydevice"
message_etag = "3k28zb44-0d00-4ddd-ade3-6110eb94c476"
c2d_purge_response = {"deviceId": device_id, "moduleId": None, "totalMessagesPurged": 3}


class TestCloudToDeviceMessaging:
    @pytest.fixture(params=["full", "min"])
    def c2d_receive_scenario(self, fixture_ghcs, mocked_response, request):
        from azext_iot.tests.generators import create_c2d_receive_response

        if request.param == "full":
            payload = create_c2d_receive_response()
        else:
            payload = create_c2d_receive_response(minimum=True)

        mocked_response.add(
            method=responses.GET,
            url=re.compile(
                "https://{}/devices/{}/messages/deviceBound".format(
                    mock_target["entity"], device_id
                )
            ),
            body=payload["body"],
            headers=payload["headers"],
            status=200,
            match_querystring=False,
        )

        yield (mocked_response, payload)

    @pytest.fixture()
    def c2d_receive_ack_scenario(self, fixture_ghcs, mocked_response):
        from azext_iot.tests.generators import create_c2d_receive_response
        payload = create_c2d_receive_response()
        mocked_response.add(
            method=responses.GET,
            url=(
                "https://{}/devices/{}/messages/deviceBound".format(
                    mock_target["entity"], device_id
                )
            ),
            body=payload["body"],
            headers=payload["headers"],
            status=200,
            match_querystring=False,
        )

        eTag = payload["headers"]["etag"].strip('"')
        # complete / reject
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/devices/{}/messages/deviceBound/{}".format(
                mock_target["entity"], device_id, eTag
            ),
            body="",
            headers=payload["headers"],
            status=204,
            match_querystring=False,
        )

        # abandon
        mocked_response.add(
            method=responses.POST,
            url="https://{}/devices/{}/messages/deviceBound/{}/abandon".format(
                mock_target["entity"], device_id, eTag
            ),
            body="",
            headers=payload["headers"],
            status=204,
            match_querystring=False,
        )

        yield (mocked_response, payload)

    @pytest.fixture()
    def c2d_ack_complete_scenario(self, fixture_ghcs, mocked_response):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/devices/{}/messages/deviceBound/{}".format(
                mock_target["entity"], device_id, message_etag
            ),
            body="",
            status=204,
            match_querystring=False,
        )
        yield mocked_response

    @pytest.fixture()
    def c2d_ack_reject_scenario(self, fixture_ghcs, mocked_response):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/devices/{}/messages/deviceBound/{}?reject=".format(
                mock_target["entity"], device_id, message_etag
            ),
            body="",
            status=204,
            match_querystring=False,
        )
        yield mocked_response

    @pytest.fixture()
    def c2d_ack_abandon_scenario(self, fixture_ghcs, mocked_response):
        mocked_response.add(
            method=responses.POST,
            url="https://{}/devices/{}/messages/deviceBound/{}/abandon".format(
                mock_target["entity"], device_id, message_etag
            ),
            body="",
            status=204,
            match_querystring=False,
        )
        yield mocked_response

    @pytest.fixture()
    def c2d_purge_scenario(self, fixture_ghcs, mocked_response):
        import json

        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/devices/{}/commands".format(
                mock_target["entity"], device_id
            ),
            body=json.dumps(c2d_purge_response),
            content_type="application/json",
            status=200,
        )
        yield mocked_response

    def test_c2d_receive(self, c2d_receive_scenario):
        service_client = c2d_receive_scenario[0]
        sample_c2d_receive = c2d_receive_scenario[1]

        timeout = 120
        result = subject.iot_c2d_message_receive(
            cmd=fixture_cmd, device_id=device_id, hub_name_or_hostname=mock_target["entity"], lock_timeout=timeout
        )
        request = service_client.calls[0].request
        url = request.url
        headers = request.headers

        assert (
            "{}/devices/{}/messages/deviceBound?".format(
                mock_target["entity"], device_id
            )
            in url
        )
        assert headers["IotHub-MessageLockTimeout"] == str(timeout)

        assert (
            result["properties"]["system"]["iothub-ack"]
            == sample_c2d_receive["headers"]["iothub-ack"]
        )
        assert (
            result["properties"]["system"]["iothub-correlationid"]
            == sample_c2d_receive["headers"]["iothub-correlationid"]
        )
        assert (
            result["properties"]["system"]["iothub-deliverycount"]
            == sample_c2d_receive["headers"]["iothub-deliverycount"]
        )
        assert (
            result["properties"]["system"]["iothub-expiry"]
            == sample_c2d_receive["headers"]["iothub-expiry"]
        )
        assert (
            result["properties"]["system"]["iothub-enqueuedtime"]
            == sample_c2d_receive["headers"]["iothub-enqueuedtime"]
        )
        assert (
            result["properties"]["system"]["iothub-messageid"]
            == sample_c2d_receive["headers"]["iothub-messageid"]
        )
        assert (
            result["properties"]["system"]["iothub-sequencenumber"]
            == sample_c2d_receive["headers"]["iothub-sequencenumber"]
        )
        assert (
            result["properties"]["system"]["iothub-userid"]
            == sample_c2d_receive["headers"]["iothub-userid"]
        )
        assert (
            result["properties"]["system"]["iothub-to"]
            == sample_c2d_receive["headers"]["iothub-to"]
        )

        assert result["etag"] == sample_c2d_receive["headers"]["etag"].strip('"')

        if sample_c2d_receive.get("body"):
            assert result["data"] == sample_c2d_receive["body"]

    def test_c2d_receive_ack(self, c2d_receive_ack_scenario):
        service_client = c2d_receive_ack_scenario[0]
        sample_c2d_receive = c2d_receive_ack_scenario[1]

        timeout = 120
        for ack in ["complete", "reject", "abandon"]:
            result = subject.iot_c2d_message_receive(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name_or_hostname=mock_target["entity"],
                lock_timeout=timeout,
                complete=(ack == "complete"),
                reject=(ack == "reject"),
                abandon=(ack == "abandon"),
            )
            retrieve, action = service_client.calls[0], service_client.calls[1]

            # retrieve call
            request = retrieve.request
            url = request.url
            headers = request.headers
            assert (
                "{}/devices/{}/messages/deviceBound?".format(
                    mock_target["entity"], device_id
                )
                in url
            )
            assert headers["IotHub-MessageLockTimeout"] == str(timeout)

            assert (
                result["properties"]["system"]["iothub-ack"]
                == sample_c2d_receive["headers"]["iothub-ack"]
            )
            assert (
                result["properties"]["system"]["iothub-correlationid"]
                == sample_c2d_receive["headers"]["iothub-correlationid"]
            )
            assert (
                result["properties"]["system"]["iothub-deliverycount"]
                == sample_c2d_receive["headers"]["iothub-deliverycount"]
            )
            assert (
                result["properties"]["system"]["iothub-expiry"]
                == sample_c2d_receive["headers"]["iothub-expiry"]
            )
            assert (
                result["properties"]["system"]["iothub-enqueuedtime"]
                == sample_c2d_receive["headers"]["iothub-enqueuedtime"]
            )
            assert (
                result["properties"]["system"]["iothub-messageid"]
                == sample_c2d_receive["headers"]["iothub-messageid"]
            )
            assert (
                result["properties"]["system"]["iothub-sequencenumber"]
                == sample_c2d_receive["headers"]["iothub-sequencenumber"]
            )
            assert (
                result["properties"]["system"]["iothub-userid"]
                == sample_c2d_receive["headers"]["iothub-userid"]
            )
            assert (
                result["properties"]["system"]["iothub-to"]
                == sample_c2d_receive["headers"]["iothub-to"]
            )

            assert result["etag"] == sample_c2d_receive["headers"]["etag"].strip('"')

            if sample_c2d_receive.get("body"):
                assert result["data"] == sample_c2d_receive["body"]

            # ack call - complete / reject / abandon
            request = action.request
            url = request.url
            headers = request.headers
            method = request.method

            # all ack calls go to the same base URL
            assert (
                "{}/devices/{}/messages/deviceBound/".format(
                    mock_target["entity"], device_id
                )
                in url
            )
            # check complete
            if ack == "complete":
                assert method == "DELETE"
            # check reject
            if ack == "reject":
                assert method == "DELETE"
                assert "reject=" in url
            # check abandon
            if ack == "abandon":
                assert method == "POST"
                assert "/abandon" in url
            service_client.calls.reset()

    def test_c2d_receive_ack_errors(self, fixture_ghcs):
        with pytest.raises(CLIError):
            subject.iot_c2d_message_receive(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name_or_hostname=mock_target["entity"],
                abandon=True,
                complete=True,
            )
            subject.iot_c2d_message_receive(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name_or_hostname=mock_target["entity"],
                abandon=False,
                complete=True,
                reject=True,
            )
            subject.iot_c2d_message_receive(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name_or_hostname=mock_target["entity"],
                complete=True,
                reject=True,
            )

    def test_c2d_complete(self, c2d_ack_complete_scenario):
        service_client = c2d_ack_complete_scenario
        result = subject.iot_c2d_message_complete(
            fixture_cmd, device_id, message_etag, hub_name_or_hostname=mock_target["entity"]
        )

        request = service_client.calls[0].request
        url = request.url
        method = request.method

        assert result is None
        assert method == "DELETE"
        assert (
            "{}/devices/{}/messages/deviceBound/{}?".format(
                mock_target["entity"], device_id, message_etag
            )
            in url
        )

    def test_c2d_reject(self, c2d_ack_reject_scenario):
        service_client = c2d_ack_reject_scenario

        result = subject.iot_c2d_message_reject(
            fixture_cmd, device_id, message_etag, hub_name_or_hostname=mock_target["entity"]
        )

        request = service_client.calls[0].request
        url = request.url
        method = request.method

        assert result is None
        assert method == "DELETE"
        assert (
            "{}/devices/{}/messages/deviceBound/{}?".format(
                mock_target["entity"], device_id, message_etag
            )
            in url
        )
        assert "reject=" in url

    def test_c2d_abandon(self, c2d_ack_abandon_scenario):
        service_client = c2d_ack_abandon_scenario

        result = subject.iot_c2d_message_abandon(
            fixture_cmd, device_id, message_etag, hub_name_or_hostname=mock_target["entity"]
        )

        request = service_client.calls[0].request
        url = request.url
        method = request.method

        assert result is None
        assert method == "POST"
        assert (
            "{}/devices/{}/messages/deviceBound/{}/abandon?".format(
                mock_target["entity"], device_id, message_etag
            )
            in url
        )

    def test_c2d_receive_and_ack_errors(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_c2d_message_receive(
                fixture_cmd, device_id, hub_name_or_hostname=mock_target["entity"]
            )
            subject.iot_c2d_message_abandon(
                fixture_cmd, device_id, hub_name_or_hostname=mock_target["entity"], etag=""
            )
            subject.iot_c2d_message_complete(
                fixture_cmd, device_id, hub_name_or_hostname=mock_target["entity"], etag=""
            )
            subject.iot_c2d_message_reject(
                fixture_cmd, device_id, hub_name_or_hostname=mock_target["entity"], etag=""
            )

    def test_c2d_message_purge(self, c2d_purge_scenario):
        result = subject.iot_c2d_message_purge(fixture_cmd, device_id)
        request = c2d_purge_scenario.calls[0].request
        url = request.url
        method = request.method

        assert method == "DELETE"
        assert (
            "https://{}/devices/{}/commands".format(mock_target["entity"], device_id)
            in url
        )
        assert result
        assert result.total_messages_purged == 3
        assert result.device_id == device_id
        assert not result.module_id


class TestDeviceSimulate:
    @pytest.fixture(params=[204])
    def serviceclient(
        self, mocker, fixture_ghcs, fixture_sas, request, fixture_device,
        fixture_device_messaging_iot_device_show_sas, fixture_update_device_twin
    ):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "rs, mc, mi, protocol, properties, mrc, mrp, irp",
        [
            ("complete", 1, 1, "http", None, None, None, None),
            ("reject", 1, 1, "http", None, None, None, None),
            ("abandon", 2, 1, "http", "iothub-app-myprop=myvalue;iothub-messageid=1", None, None, None),
            ("complete", 1, 1, "http", "invalidprop;content-encoding=utf-16", None, None, None),
            ("complete", 1, 1, "http", "iothub-app-myprop=myvalue;content-type=application/text", None, None, None),
            ("complete", 3, 1, "mqtt", None, None, None, None),
            ("complete", 3, 1, "mqtt", "invalid", None, None, None),
            ("complete", 2, 1, "mqtt", "myprop=myvalue;$.ce=utf-16", 201, None, None),
            ("complete", 2, 1, "mqtt", "myprop=myvalue;$.ce=utf-16", None, "{'result':'method succeded'}", None),
            ("complete", 2, 1, "mqtt", "myinvalidprop;myvalidprop=myvalidpropvalue", 204, "{'result':'method succeded'}", None),
            ("complete", 2, 1, "mqtt", "myinvalidprop;myvalidprop=myvalidpropvalue", None, None, "{'rep_1':'val1', 'rep_2':2}"),
        ],
    )
    def test_device_simulate(
        self, serviceclient, mqttclient_cs, rs, mc, mi, protocol, properties, mrc, mrp, irp
    ):
        from azext_iot.iothub.providers.device_messaging import _simulate_get_default_properties
        subject.iot_simulate_device(
            cmd=fixture_cmd,
            device_id=device_id,
            hub_name_or_hostname=mock_target["entity"],
            receive_settle=rs,
            msg_count=mc,
            msg_interval=mi,
            protocol_type=protocol,
            properties=properties,
            method_response_code=mrc,
            method_response_payload=mrp,
            init_reported_properties=irp
        )

        properties_to_send = _simulate_get_default_properties(protocol)
        properties_to_send.update(validate_key_value_pairs(properties) or {})

        if protocol == "http":
            args = serviceclient.call_args_list
            result = []
            for call in args:
                c = call[0]
                if c[0].method == "POST":
                    result.append(c)
            assert len(result) == mc

            # result[?][1] are the http request headers
            assert result[0][1] == properties_to_send

            # result[?][2] is the http request body (prior to stringify)
            assert json.dumps(result[0][2])

        if protocol == "mqtt":
            assert mc == mqttclient_cs().send_message.call_count

            if properties is None or properties == "invalid":
                assert mqttclient_cs().send_message.call_args[0][0].custom_properties == {
                    '$.ce': 'utf-8', '$.ct': 'application/json'}

            elif properties == "myprop=myvalue;$.ce=utf-16":
                assert mqttclient_cs().send_message.call_args[0][0].custom_properties == {
                    '$.ce': 'utf-16', '$.ct': 'application/json', 'myprop': 'myvalue'}

            elif properties == "myinvalidprop;myvalidprop=myvalidpropvalue":
                assert mqttclient_cs().send_message.call_args[0][0].custom_properties == {
                    '$.ce': 'utf-8', '$.ct': 'application/json', 'myvalidprop': 'myvalidpropvalue'}

            # mqtt msg body - which is a json string
            assert json.loads(mqttclient_cs().send_message.call_args[0][0].data)
            assert serviceclient.call_count == 0
            assert mqttclient_cs().shutdown.call_count == 1

    @pytest.mark.parametrize(
        "rs, mc, mi, protocol, exception, mrc, mrp, irp",
        [
            ("complete", 2, 0, "mqtt", CLIError, None, None, None),
            ("complete", 0, 1, "mqtt", CLIError, None, None, None),
            ("complete", 1, 1, "mqtt", CLIError, 200, "invalid_method_response_payload", None),
            ("complete", 1, 1, "mqtt", CLIError, None, None, "invalid_reported_properties_format"),
            ("reject", 1, 1, "mqtt", CLIError, None, None, None),
            ("abandon", 1, 0, "http", CLIError, None, None, None),
            ("complete", 0, 1, "http", CLIError, 201, None, None),
            ("complete", 0, 1, "http", CLIError, None, "{'result':'method succeded'}", None),
            ("complete", 0, 1, "http", CLIError, 201, "{'result':'method succeded'}", None),
            ("complete", 0, 1, "http", CLIError, None, None, "{'rep_prop_1':'val1', 'rep_prop_2':'val2'}"),
        ],
    )
    def test_device_simulate_invalid_args(
        self, serviceclient, rs, mc, mi, protocol, exception, mrc, mrp, irp
    ):
        with pytest.raises(exception):
            subject.iot_simulate_device(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name_or_hostname=mock_target["entity"],
                receive_settle=rs,
                msg_count=mc,
                msg_interval=mi,
                protocol_type=protocol,
                method_response_code=mrc,
                method_response_payload=mrp,
                init_reported_properties=irp
            )

    def test_device_simulate_http_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_simulate_device(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name_or_hostname=mock_target["entity"],
                protocol_type="http",
            )

    def test_device_simulate_mqtt_error(self, mqttclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_simulate_device(
                cmd=fixture_cmd, device_id=device_id, hub_name_or_hostname=mock_target["entity"]
            )


class TestMQTTClientSetup:
    def test_mqtt_provider_creation_sas_device(self, mqttclient_cs):
        mqtt_subject.MQTTProvider(
            hub_hostname=mock_target["entity"],
            device_id="test_device_id",
            device_conn_string="test_conn_string"
        )

    def test_mqtt_provider_creation_bad_sas_device(self, mqttclient_cs):
        with pytest.raises(CLIError):
            mqtt_subject.MQTTProvider(
                hub_hostname=mock_target["entity"],
                device_id="test_device_id",
                device_conn_string="test_conn_string;x509=true"
            )

    def test_mqtt_provider_creation_sx509_device(self, mqttclient_x509):
        mqtt_subject.MQTTProvider(
            hub_hostname=mock_target["entity"],
            device_id="test_device_id",
            x509_files={
                "certificateFile": "cert",
                "keyFile": "key",
                "passphrase": "pass"
            }
        )
