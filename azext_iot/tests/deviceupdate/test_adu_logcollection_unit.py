# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import re
from datetime import datetime
from typing import List, Optional

import pytest
import responses
from requests import PreparedRequest

from azext_iot.deviceupdate import commands_log as subject
from azext_iot.sdk.deviceupdate.dataplane._serialization import Model
from azext_iot.tests.deviceupdate.conftest import (mock_account_id,
                                                   mock_instance_id)
from azext_iot.tests.generators import generate_generic_id

existing_mock_collection_id = generate_generic_id()


class TestAduLogCollection(object):
    def gen_arbitrary_log(
        self, operation_id: Optional[str] = None, device_list: Optional[List[dict]] = None, description: Optional[str] = None
    ) -> dict:
        log_object = {}
        log_object["operationId"] = operation_id if operation_id else generate_generic_id()
        log_object["deviceList"] = device_list if device_list else [{"deviceId": generate_generic_id()}]
        log_object["createdDateTime"] = str(datetime.now())
        log_object["lastActionDateTime"] = str(datetime.now())
        log_object["status"] = "Running"
        log_object["description"] = description if description else f"{generate_generic_id()} {generate_generic_id()}"
        return log_object

    def log_create_callback(self, request: PreparedRequest):
        headers = {"Content-Type": "application/json; charset=utf-8"}
        request_body_payload = json.loads(request.body)
        return (
            201,
            headers,
            json.dumps(
                self.gen_arbitrary_log(
                    operation_id=request_body_payload["operationId"],
                    device_list=request_body_payload["deviceList"],
                    description=request_body_payload.get("description"),
                )
            ),
        )

    def log_list_callback(self, request: PreparedRequest):
        headers = {"Content-Type": "application/json; charset=utf-8"}
        response_payload = []
        for _ in range(3):
            response_payload.append(self.gen_arbitrary_log())
        return (200, headers, json.dumps({"value": response_payload}))

    def log_show_callback(self, request: PreparedRequest):
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if "/detailedStatus?" in request.path_url:
            detailed_log = self.gen_arbitrary_log(operation_id=existing_mock_collection_id)
            del detailed_log["deviceList"]
            detailed_log["deviceStatus"] = [
                {
                    "deviceId": generate_generic_id(),
                    "moduleId": generate_generic_id(),
                    "status": "mock",
                    "resultCode": "0",
                    "extendedResultCode": "000",
                    "logLocation": "/path/to/log",
                }
            ]
            return (200, headers, json.dumps(detailed_log))

        return (200, headers, json.dumps(self.gen_arbitrary_log(operation_id=existing_mock_collection_id)))

    @pytest.fixture()
    def service_client(self, mocked_response):
        mocked_response.assert_all_requests_are_fired = False
        mocked_response.add_callback(
            responses.PUT,
            re.compile(r"https://(.*).api.adu.microsoft.com/deviceUpdate/(.*)/management/deviceDiagnostics/logCollections/(.*)"),
            callback=self.log_create_callback,
        )
        mocked_response.add_callback(
            responses.GET,
            re.compile(
                r"https://(.*).api.adu.microsoft.com/deviceUpdate/(.*)/management/deviceDiagnostics/logCollections/{}".format(
                    existing_mock_collection_id
                )
            ),
            callback=self.log_show_callback,
        )
        mocked_response.add_callback(
            responses.GET,
            re.compile(r"https://(.*).api.adu.microsoft.com/deviceUpdate/(.*)/management/deviceDiagnostics/logCollections"),
            callback=self.log_list_callback,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "op_id, agent_id_input, expected_device_list, description",
        [
            (generate_generic_id(), [["deviceId=d0"]], [{"deviceId": "d0"}], None),
            (generate_generic_id(), [["deviceId=d0", "moduleId=m0"]], [{"deviceId": "d0", "moduleId": "m0"}], None),
            (
                generate_generic_id(),
                [["deviceId=d0"], ["deviceId=d1", "moduleId=m1"]],
                [{"deviceId": "d0"}, {"deviceId": "d1", "moduleId": "m1"}],
                f"{generate_generic_id()} {generate_generic_id()}",
            ),
        ],
    )
    def test_adu_create_device_log_collection(
        self,
        fixture_cmd,
        discovery_client,
        profile_mock,
        service_client,
        op_id,
        agent_id_input,
        expected_device_list,
        description,
    ):
        result = subject.collect_logs(
            cmd=fixture_cmd,
            name=mock_account_id,
            instance_name=mock_instance_id,
            log_collection_id=op_id,
            agent_id=agent_id_input,
            description=description,
        )
        assert result.log_collection_id == op_id
        assert result.serialize()["deviceList"] == expected_device_list
        assert result.created_date_time
        assert result.last_action_date_time
        assert result.status

        if description:
            result.description == description

    def test_adu_list_device_log_collection(
        self,
        fixture_cmd,
        discovery_client,
        profile_mock,
        service_client,
    ):
        result = subject.list_log_collections(
            cmd=fixture_cmd,
            name=mock_account_id,
            instance_name=mock_instance_id,
        )
        assert result
        for r in result:
            assert_common_log_model_attributes(r)

    def test_adu_show_device_log_collection(
        self,
        fixture_cmd,
        discovery_client,
        profile_mock,
        service_client,
    ):
        show_result = subject.show_log_collection(
            cmd=fixture_cmd,
            name=mock_account_id,
            instance_name=mock_instance_id,
            log_collection_id=existing_mock_collection_id
        )
        assert_common_log_model_attributes(show_result)

    def test_adu_show_detailed_device_log_collection(
        self,
        fixture_cmd,
        discovery_client,
        profile_mock,
        service_client,
    ):
        show_detailed_result = subject.show_log_collection(
            cmd=fixture_cmd,
            name=mock_account_id,
            instance_name=mock_instance_id,
            log_collection_id=existing_mock_collection_id,
            detailed_status=True,
        )
        assert_common_log_object_attributes(show_detailed_result.serialize(), True)


def assert_common_log_object_attributes(serialized_log_object: dict, detailed: bool = False):
    assert serialized_log_object["operationId"]
    assert serialized_log_object["createdDateTime"]
    assert serialized_log_object["lastActionDateTime"]
    assert serialized_log_object["status"]
    assert "description" in serialized_log_object
    if detailed:
        assert serialized_log_object["deviceStatus"]
        assert serialized_log_object["deviceStatus"][0]["status"]
        assert serialized_log_object["deviceStatus"][0]["resultCode"]
        assert serialized_log_object["deviceStatus"][0]["extendedResultCode"]
        assert serialized_log_object["deviceStatus"][0]["logLocation"]
    else:
        assert serialized_log_object["deviceList"]


def assert_common_log_model_attributes(serialized_log_model: Model):
    assert serialized_log_model.log_collection_id
    assert serialized_log_model.device_list
    assert serialized_log_model.description
    assert serialized_log_model.created_date_time
    assert serialized_log_model.last_action_date_time
    assert serialized_log_model.status
