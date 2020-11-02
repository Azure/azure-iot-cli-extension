# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import pytest
import responses
import json
from uuid import uuid4
from random import randint
from knack.cli import CLIError
from azext_iot.operations import hub as subject
from azext_iot.common.utility import read_file_content, evaluate_literal
from ...conftest import build_mock_response, path_service_client, mock_target, get_context_path

config_id = "myconfig-{}".format(str(uuid4()).replace("-", ""))


@pytest.fixture
def sample_config_show(set_cwd):
    path = "test_config_modules_show.json"
    result = json.loads(read_file_content(path))
    return result


@pytest.fixture
def sample_config_edge_malformed(set_cwd):
    path = "test_edge_deployment_malformed.json"
    result = json.dumps(json.loads(read_file_content(path)))
    return result


@pytest.fixture(params=["file", "inlineA", "inlineB", "layered", "v1", "v11"])
def sample_config_edge(set_cwd, request):
    path = "test_edge_deployment.json"
    layered_path = "test_edge_deployment_layered.json"
    v1_path = "test_edge_deployment_v1.json"
    v11_path = "test_edge_deployment_v11.json"

    payload = None
    if request.param == "inlineA":
        payload = json.dumps(json.loads(read_file_content(path)))
    elif request.param == "inlineB":
        payload = json.dumps(json.loads(read_file_content(path))["content"])
    elif request.param == "file":
        payload = get_context_path(__file__, path)
    elif request.param == "layered":
        payload = json.dumps(json.loads(read_file_content(layered_path)))
    elif request.param == "v1":
        payload = json.dumps(json.loads(read_file_content(v1_path)))
    elif request.param == "v11":
        payload = json.dumps(json.loads(read_file_content(v11_path)))

    return (request.param, payload)


@pytest.fixture(params=["file", "inlineA", "inlineB", None])
def sample_config_metrics(set_cwd, request):
    path = "test_config_generic_metrics.json"

    payload = None
    if request.param == "inlineA":
        payload = json.dumps(json.loads(read_file_content(path)))
    elif request.param == "inlineB":
        payload = json.dumps(json.loads(read_file_content(path))["metrics"])
    elif request.param == "file":
        payload = get_context_path(__file__, path)

    return (request.param, payload)


@pytest.fixture(params=["moduleFile", "moduleInline", "deviceFile", "deviceInline"])
def sample_config_adm(set_cwd, request):
    path_device = "test_adm_device_content.json"
    path_module = "test_adm_module_content.json"

    payload = None
    if request.param == "moduleFile":
        payload = get_context_path(__file__, path_module)
    elif request.param == "moduleInline":
        payload = json.dumps(json.loads(read_file_content(path_module)))
    elif request.param == "deviceFile":
        payload = get_context_path(__file__, path_device)
    elif request.param == "deviceInline":
        payload = json.dumps(json.loads(read_file_content(path_device)))

    return (request.param, payload)


class TestConfigMetricShow:
    @pytest.fixture
    def service_client(
        self, mocked_response, fixture_ghcs, request, sample_config_show
    ):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/configurations/{}".format(mock_target["entity"], config_id),
            body=json.dumps(sample_config_show),
            headers={},
            status=200,
            content_type="application/json",
            match_querystring=False
        )

        mocked_response.add(
            method=responses.POST,
            url="https://{}/devices/query".format(mock_target["entity"]),
            body="[]",
            headers={"x-ms-continuation": ""},
            status=200,
            content_type="application/json",
            match_querystring=False
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "metric_id, content_type, metric_type",
        [
            ("appliedCount", "modulesContent", "system"),
            ("mymetric", "modulesContent", "user"),
            ("appliedCount", "moduleContent", "system"),
            ("mymetric", "moduleContent", "user"),
            ("appliedCount", "deviceContent", "system"),
            ("mymetric", "deviceContent", "user"),
        ],
    )
    def test_config_metric_show(
        self,
        fixture_cmd,
        service_client,
        metric_id,
        content_type,
        metric_type,
        sample_config_show,
    ):
        from functools import partial

        target_method = (
            partial(subject.iot_edge_deployment_metric_show)
            if content_type == "modulesContent"
            else partial(subject.iot_hub_configuration_metric_show)
        )
        result = target_method(
            cmd=fixture_cmd,
            config_id=config_id,
            metric_type=metric_type,
            metric_id=metric_id,
            hub_name=mock_target["entity"],
        )
        expected = sample_config_show

        metric_type_key = "systemMetrics" if metric_type == "system" else "metrics"
        assert result["metric"] == metric_id
        assert result["query"] == expected[metric_type_key]["queries"][metric_id]

        assert len(service_client.calls) == 2
        query_request = service_client.calls[1].request
        query_body = json.loads(query_request.body)

        assert query_body["query"] == expected[metric_type_key]["queries"][metric_id]

    @pytest.mark.parametrize(
        "metric_id, content_type, metric_type",
        [
            ("doesnotexist0", "modules", "system"),
            ("doesnotexist1", "modules", "user"),
            ("doesnotexist2", "modules", "sometype"),
            ("doesnotexist3", "device", "system"),
            ("doesnotexist4", "device", "user"),
            ("doesnotexist5", "device", "sometype"),
            ("doesnotexist6", "module", "system"),
            ("doesnotexist7", "module", "user"),
            ("doesnotexist8", "module", "sometype"),
        ],
    )
    def test_config_metric_show_invalid_args(
        self, fixture_cmd, service_client, metric_id, content_type, metric_type
    ):
        from functools import partial
        service_client.assert_all_requests_are_fired = False

        with pytest.raises(CLIError):
            target_method = (
                partial(subject.iot_edge_deployment_metric_show)
                if content_type == "modulesContent"
                else partial(subject.iot_hub_configuration_metric_show)
            )

            target_method(
                cmd=fixture_cmd,
                config_id=config_id,
                metric_type=metric_type,
                metric_id=metric_id,
                hub_name=mock_target["entity"],
            )


class TestConfigShow:
    @pytest.fixture(params=[200])
    def serviceclient(
        self, mocker, fixture_ghcs, fixture_sas, request, sample_config_show
    ):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, sample_config_show
        )
        return service_client

    def test_config_show(self, serviceclient, fixture_cmd):
        result = subject.iot_hub_configuration_show(
            fixture_cmd, config_id=config_id, hub_name=mock_target["entity"]
        )

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert "{}/configurations/{}?".format(mock_target["entity"], config_id) in url
        assert method == "GET"
        assert isinstance(result, dict)

    def test_config_show_error(self, serviceclient_generic_error, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_show(
                fixture_cmd, config_id=config_id, hub_name=mock_target["entity"]
            )


class TestConfigCreate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "config_id, hub_name, target_condition, priority, labels",
        [
            (
                "UPPERCASEID",
                mock_target["entity"],
                "tags.building=43 and tags.environment='test'",
                randint(0, 100),
                '{"key1":"value1"}',
            ),
            (
                "lowercaseid",
                mock_target["entity"],
                "tags.building=43 and tags.environment='test'",
                randint(0, 100),
                None,
            ),
            ("mixedCaseId", mock_target["entity"], None, None, None),
        ],
    )
    def test_config_create_edge(
        self,
        fixture_cmd,
        serviceclient,
        sample_config_edge,
        sample_config_metrics,
        config_id,
        hub_name,
        target_condition,
        priority,
        labels,
    ):
        subject.iot_edge_deployment_create(
            cmd=fixture_cmd,
            config_id=config_id,
            hub_name=hub_name,
            content=sample_config_edge[1],
            target_condition=target_condition,
            priority=priority,
            labels=labels,
            metrics=sample_config_metrics[1],
            layered=(sample_config_edge[0] == "layered"),
        )

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = json.loads(args[0][0].body)

        assert "{}/configurations/{}?".format(hub_name, config_id.lower()) in url
        assert method == "PUT"
        assert body["id"] == config_id.lower()
        assert body.get("targetCondition") == target_condition
        assert body.get("priority") == priority
        assert body.get("labels") == evaluate_literal(labels, dict)

        if sample_config_edge[0] == "inlineB" or sample_config_edge[0] == "v11":
            assert (
                body["content"]["modulesContent"]
                == json.loads(sample_config_edge[1])["modulesContent"]
            )
        elif sample_config_edge[0] == "file":
            assert (
                body["content"]["modulesContent"]
                == json.loads(read_file_content(sample_config_edge[1]))["content"][
                    "modulesContent"
                ]
            )
        elif sample_config_edge[0] == "v1":
            assert (
                body["content"]["modulesContent"]
                == json.loads(sample_config_edge[1])["content"]["moduleContent"]
            )
        else:
            assert (
                body["content"]["modulesContent"]
                == json.loads(sample_config_edge[1])["content"]["modulesContent"]
            )

        self._assert_config_metrics_request(sample_config_metrics, body)

    @pytest.mark.parametrize(
        "config_id, hub_name, target_condition, priority, labels",
        [
            (
                "lowercaseid",
                mock_target["entity"],
                "tags.building=43 and tags.environment='test'",
                randint(0, 100),
                None,
            )
        ],
    )
    def test_config_create_edge_malformed(
        self,
        fixture_cmd,
        serviceclient,
        sample_config_edge_malformed,
        config_id,
        hub_name,
        target_condition,
        priority,
        labels,
    ):
        with pytest.raises(CLIError) as exc:
            subject.iot_edge_deployment_create(
                cmd=fixture_cmd,
                config_id=config_id,
                hub_name=hub_name,
                content=sample_config_edge_malformed,
                target_condition=target_condition,
                priority=priority,
                labels=labels,
            )

        exception_obj = json.loads(str(exc.value))
        assert "validationErrors" in exception_obj
        for error_element in exception_obj["validationErrors"]:
            assert "description" in error_element
            assert "contentPath" in error_element
            assert "schemaPath" in error_element

    @pytest.mark.parametrize(
        "config_id, hub_name, target_condition, priority, labels",
        [
            (
                "UPPERCASEID",
                mock_target["entity"],
                "tags.building=43 and tags.environment='test'",
                randint(0, 100),
                '{"key1":"value1"}',
            ),
            (
                "lowercaseid",
                mock_target["entity"],
                "tags.building=43 and tags.environment='test'",
                randint(0, 100),
                None,
            ),
            ("mixedCaseId", mock_target["entity"], None, None, None),
        ],
    )
    def test_config_create_adm(
        self,
        fixture_cmd,
        serviceclient,
        sample_config_adm,
        sample_config_metrics,
        config_id,
        hub_name,
        target_condition,
        priority,
        labels,
    ):

        contentKey = (
            "moduleContent"
            if sample_config_adm[0].startswith("module")
            else "deviceContent"
        )

        if contentKey == "moduleContent":
            # Enforce the query prefix for success the case
            target_condition = "FROM devices.modules WHERE {}".format(target_condition)

        subject.iot_hub_configuration_create(
            cmd=fixture_cmd,
            config_id=config_id,
            hub_name=hub_name,
            content=sample_config_adm[1],
            target_condition=target_condition,
            priority=priority,
            labels=labels,
            metrics=sample_config_metrics[1],
        )

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = json.loads(args[0][0].body)

        assert "{}/configurations/{}?".format(hub_name, config_id.lower()) in url
        assert method == "PUT"
        assert body["id"] == config_id.lower()
        assert body.get("targetCondition") == target_condition
        assert body.get("priority") == priority
        assert body.get("labels") == evaluate_literal(labels, dict)

        if sample_config_adm[0].endswith("Inline"):
            assert (
                body["content"][contentKey]
                == json.loads(sample_config_adm[1])["content"][contentKey]
            )
        elif sample_config_adm[0].endswith("File"):
            assert (
                body["content"][contentKey]
                == json.loads(read_file_content(sample_config_adm[1]))["content"][
                    contentKey
                ]
            )

        self._assert_config_metrics_request(sample_config_metrics, body)

    def _assert_config_metrics_request(self, sample_config_metrics, body):
        if sample_config_metrics[0]:
            if sample_config_metrics[0] == "inlineA":
                assert (
                    body["metrics"] == json.loads(sample_config_metrics[1])["metrics"]
                )
            elif sample_config_metrics[0] == "inlineB":
                assert body["metrics"] == json.loads(sample_config_metrics[1])
            else:
                assert (
                    body["metrics"]
                    == json.loads(read_file_content(sample_config_metrics[1]))[
                        "metrics"
                    ]
                )
        else:
            assert body["metrics"] == {}

    @pytest.mark.parametrize(
        "config_id, hub_name, target_condition, priority, labels",
        [
            (
                "lowercaseid",
                mock_target["entity"],
                "tags.building=43 and tags.environment='test'",
                randint(0, 100),
                None,
            )
        ],
    )
    def test_config_create_adm_invalid(
        self,
        fixture_cmd,
        serviceclient,
        config_id,
        hub_name,
        target_condition,
        priority,
        labels,
    ):
        with pytest.raises(CLIError) as exc1:
            subject.iot_hub_configuration_create(
                cmd=fixture_cmd,
                config_id=config_id,
                hub_name=hub_name,
                content=get_context_path(__file__, "test_edge_deployment.json"),
                target_condition=target_condition,
                priority=priority,
                labels=labels,
            )

        # API does not support both deviceContent and moduleContent at the same time.
        content = json.dumps({"deviceContent": {}, "moduleContent": {}})
        with pytest.raises(CLIError) as exc2:
            subject.iot_hub_configuration_create(
                cmd=fixture_cmd,
                config_id=config_id,
                hub_name=hub_name,
                content=content,
                target_condition=target_condition,
                priority=priority,
                labels=labels,
            )

        for exc in [exc1, exc2]:
            assert (
                str(exc.value)
                == "Automatic device configuration payloads require property: deviceContent or moduleContent"
            )

        # Module configurations target condition needs to start with 'from devices.modules where'
        content = json.dumps({"moduleContent": {"key": "value"}})
        with pytest.raises(CLIError) as exc3:
            subject.iot_hub_configuration_create(
                cmd=fixture_cmd,
                config_id=config_id,
                hub_name=hub_name,
                content=content,
                target_condition=target_condition,
                priority=priority,
                labels=labels,
            )

        assert (
            str(exc3.value)
            == "The target condition for a module configuration must start with 'from devices.modules where'"
        )

    @pytest.mark.parametrize(
        "config_id, hub_name, target_condition, priority, labels",
        [
            (
                "lowercaseid",
                mock_target["entity"],
                "tags.building=43 and tags.environment='test'",
                randint(0, 100),
                None,
            )
        ],
    )
    def test_config_create_error(
        self,
        fixture_cmd,
        serviceclient_generic_error,
        sample_config_edge,
        config_id,
        hub_name,
        target_condition,
        priority,
        labels,
    ):
        with pytest.raises(CLIError):
            subject.iot_edge_deployment_create(
                cmd=fixture_cmd,
                config_id=config_id,
                hub_name=hub_name,
                content=sample_config_edge[1],
                target_condition=target_condition,
                priority=priority,
                labels=labels,
            )


class TestConfigDelete:
    @pytest.fixture(params=[(200, 204)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        etag = str(uuid4())
        service_client.expected_etag = etag
        side_effect = [
            build_mock_response(mocker, request.param[0], {"etag": etag}),
            build_mock_response(mocker, request.param[1]),
        ]
        service_client.side_effect = side_effect
        return service_client

    def test_config_delete(self, serviceclient, fixture_cmd):
        subject.iot_hub_configuration_delete(
            fixture_cmd, config_id=config_id, hub_name=mock_target["entity"]
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "DELETE"
        assert "{}/configurations/{}?".format(mock_target["entity"], config_id) in url
        assert headers["If-Match"] == '"{}"'.format(serviceclient.expected_etag)

    @pytest.mark.parametrize("expected_error", [CLIError])
    def test_config_delete_invalid_args(
        self,
        fixture_cmd,
        serviceclient_generic_invalid_or_missing_etag,
        expected_error,
    ):
        with pytest.raises(expected_error):
            subject.iot_hub_configuration_delete(
                fixture_cmd, config_id=config_id, hub_name=mock_target["entity"]
            )

    def test_config_delete_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_delete(
                fixture_cmd, config_id=config_id, hub_name=mock_target["entity"]
            )


class TestConfigUpdate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    def test_config_update(self, fixture_cmd, serviceclient, sample_config_show):
        subject.iot_hub_configuration_update(
            cmd=fixture_cmd,
            config_id=config_id,
            hub_name=mock_target["entity"],
            parameters=sample_config_show,
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = json.loads(args[0][0].body)
        headers = args[0][0].headers

        assert "{}/configurations/{}?".format(mock_target["entity"], config_id) in url
        assert method == "PUT"

        assert headers["If-Match"] == '"{}"'.format(sample_config_show["etag"])

        assert body["id"] == sample_config_show["id"]
        assert body.get("metrics") == sample_config_show.get("metrics")
        assert body.get("targetCondition") == sample_config_show.get("targetCondition")
        assert body.get("priority") == sample_config_show.get("priority")
        assert body.get("labels") == sample_config_show.get("labels")

    def test_config_update_invalid_args(
        self, fixture_cmd, serviceclient, sample_config_show
    ):
        from copy import deepcopy

        request = deepcopy(sample_config_show)
        request["etag"] = None

        with pytest.raises(CLIError):
            subject.iot_hub_configuration_update(
                cmd=fixture_cmd,
                config_id=config_id,
                hub_name=mock_target["entity"],
                parameters=request,
            )

        request = deepcopy(sample_config_show)
        request["labels"] = "not a dictionary"

        with pytest.raises(CLIError) as exc_label:
            subject.iot_hub_configuration_update(
                cmd=fixture_cmd,
                config_id=config_id,
                hub_name=mock_target["entity"],
                parameters=request,
            )

        type_name = "class" if "class" in str(type) else "type"
        assert str(exc_label.value) == ("The property \"labels\" must be of <{0} 'dict'> but is <{0} 'str'>. "
                                        "Input: not a dictionary. Review inline JSON examples here --> "
                                        "https://github.com/Azure/azure-iot-cli-extension/wiki/Tips".format(type_name))

    def test_config_update_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_update(
                cmd=fixture_cmd,
                config_id=config_id,
                hub_name=mock_target["entity"],
                parameters={},
            )


class TestConfigList:
    @pytest.fixture(params=[10, 0, 1000])
    def service_client(self, mocked_response, fixture_ghcs, request):
        result = []
        size = request.param

        # Create mock edge deployments and ADM device and module configurations
        for i in range(size):
            result.append({
                "id": "edgeDeployment{}".format(i),
                "content": {"modulesContent": {"key": {}}},
            })
            result.append({
                "id": "moduleConfiguration{}".format(i),
                "content": {"moduleContent": {"key": {}}},
            })
            result.append({
                "id": "deviceConfiguration{}".format(i),
                "content": {"deviceContent": {"key": {}}},
            })

        mocked_response.add(
            method=responses.GET,
            url="https://{}/configurations".format(mock_target["entity"]),
            body=json.dumps(result),
            headers={"x-ms-continuation": ""},
            status=200,
            content_type="application/json",
            match_querystring=False
        )

        mocked_response.expected_size = size
        yield mocked_response

    @pytest.mark.parametrize("top", [1, 100, 1000, None])
    def test_config_list(self, fixture_cmd, service_client, top):
        result = subject.iot_hub_configuration_list(
            cmd=fixture_cmd, hub_name=mock_target["entity"], top=top
        )
        assert json.dumps(result)

        # Total configurations are double for ADM in this scenario
        assert len(result) == top or len(result) == service_client.expected_size * 2

        list_request = service_client.calls[0].request
        assert "top=" not in list_request.url

    @pytest.mark.parametrize("top", [1, 100, 1000, None])
    def test_deployment_list(self, fixture_cmd, service_client, top):
        result = subject.iot_edge_deployment_list(
            cmd=fixture_cmd, hub_name=mock_target["entity"], top=top
        )
        assert json.dumps(result)

        assert len(result) == top or len(result) == service_client.expected_size

        list_request = service_client.calls[0].request
        assert "top=" not in list_request.url

    @pytest.mark.parametrize("top", [-1, 0, 101])
    def test_config_list_invalid_args(self, fixture_cmd, top):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_list(
                cmd=fixture_cmd, hub_name=mock_target["entity"], top=top
            )

    def test_config_list_error(self, fixture_cmd, service_client_generic_errors):
        service_client_generic_errors.assert_all_requests_are_fired = False
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_list(
                cmd=fixture_cmd, hub_name=mock_target["entity"]
            )


class TestConfigApply:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.side_effect = [
            build_mock_response(mocker),
            build_mock_response(mocker, payload=[]),
        ]
        return service_client

    @pytest.mark.parametrize(
        "device_id, hub_name", [("test-device-01", mock_target["entity"])]
    )
    def test_config_apply_edge(
        self, fixture_cmd, serviceclient, device_id, hub_name, sample_config_edge
    ):
        # Not yet supporting layered deployments
        if sample_config_edge[0] == "layered":
            return

        result = subject.iot_edge_set_modules(
            cmd=fixture_cmd,
            device_id=device_id,
            hub_name=mock_target["entity"],
            content=sample_config_edge[1],
        )

        # For the actual apply configuration call
        args = serviceclient.call_args_list[0]
        url = args[0][0].url
        method = args[0][0].method
        body = json.loads(args[0][0].body)

        assert method == "POST"
        assert (
            "{}/devices/{}/applyConfigurationContent?".format(
                mock_target["entity"], device_id
            )
            in url
        )

        if sample_config_edge[0] == "inlineB" or sample_config_edge[0] == "v11":
            assert (
                body["modulesContent"]
                == json.loads(sample_config_edge[1])["modulesContent"]
            )
        elif sample_config_edge[0] == "file":
            assert (
                body["modulesContent"]
                == json.loads(read_file_content(sample_config_edge[1]))["content"][
                    "modulesContent"
                ]
            )
        elif sample_config_edge[0] == "v1":
            assert (
                body["modulesContent"]
                == json.loads(sample_config_edge[1])["content"]["moduleContent"]
            )
        else:
            assert (
                body["modulesContent"]
                == json.loads(sample_config_edge[1])["content"]["modulesContent"]
            )

        # For returning the set of module identities applied to the device
        args = serviceclient.call_args_list[1]
        url = args[0][0].url
        method = args[0][0].method

        assert method == "GET"
        assert "{}/devices/{}/modules?".format(mock_target["entity"], device_id) in url
        assert result is not None

    @pytest.mark.parametrize(
        "device_id, hub_name", [("test-device-01", mock_target["entity"])]
    )
    def test_config_apply_edge_malformed(
        self,
        fixture_cmd,
        serviceclient,
        device_id,
        hub_name,
        sample_config_edge_malformed,
    ):
        with pytest.raises(CLIError) as exc:
            subject.iot_edge_set_modules(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name=mock_target["entity"],
                content=sample_config_edge_malformed,
            )

        exception_obj = json.loads(str(exc.value))
        assert "validationErrors" in exception_obj
        for error_element in exception_obj["validationErrors"]:
            assert "description" in error_element
            assert "contentPath" in error_element
            assert "schemaPath" in error_element

    @pytest.mark.parametrize(
        "device_id, hub_name", [("test-device-01", mock_target["entity"])]
    )
    def test_config_apply_edge_error(
        self,
        fixture_cmd,
        serviceclient_generic_error,
        device_id,
        hub_name,
        sample_config_edge_malformed,
    ):
        with pytest.raises(CLIError):
            subject.iot_edge_set_modules(
                cmd=fixture_cmd,
                device_id=device_id,
                hub_name=mock_target["entity"],
                content=sample_config_edge_malformed,
            )
