# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
import pytest
import responses
import json
from knack.cli import CLIError
from azext_iot.digitaltwins import commands_twins as subject
from msrest.paging import Paged
from msrest.exceptions import ClientRequestError
from azext_iot.tests.digitaltwins.dt_helpers import (
    etag,
    generate_generic_id,
    generate_relationship,
    generate_twin_result,
    generic_result,
    model_id,
    resource_group,
    twin_id
)
from azext_iot.tests.conftest import hostname

target_twin_id = generate_generic_id()
relationship_id = generate_generic_id()
component_path = generate_generic_id()

generic_query = "select * from digitaltwins"
models_result = json.dumps({"id": model_id})
generic_patch_1 = json.dumps({"a" : "b"})
generic_patch_2 = json.dumps({"a" : "b", "c" : "d"})


@pytest.fixture
def start_twin_response(mocked_response, fixture_dt_client):
    mocked_response.assert_all_requests_are_fired = False

    mocked_response.add(
        method=responses.GET,
        content_type="application/json",
        url=re.compile(
            "https://management.azure.com/subscriptions/(.*)/"
            "providers/Microsoft.DigitalTwins/digitalTwinsInstances"
        ),
        status=200,
        match_querystring=False,
        body=json.dumps({"hostName": hostname}),
    )

    yield mocked_response


class TestTwinQueryTwins(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        yield mocked_response

    @pytest.mark.parametrize(
        "query_command, show_cost, servresult, numresultsperpage",
        [
            (generic_query, True, [], 1),
            (generic_query, False, [], 1),
            (generic_query, True, [generate_twin_result()], 1),
            (generic_query, False, [generate_twin_result()], 1),
            (generic_query, True, [generate_twin_result(), generate_twin_result()], 2),
            (generic_query, True, [generate_twin_result(), generate_twin_result(), generate_twin_result()], 2)
        ]
    )
    def test_query_twins(
        self, fixture_cmd, service_client, query_command, show_cost, servresult, numresultsperpage
    ):
        # Set up number of pages, setting it to 1 if result is []
        numpages = int(len(servresult) / numresultsperpage)
        if numpages == 0:
            numpages += 1
        cost = 0

        # Create and add the mocked responses
        for i in range(numpages):
            if i == 0:
                url = "https://{}/query".format(hostname)
            else:
                url = "https://{}/query?{}".format(hostname, str(i))

            if numpages - i == 1:
                contToken = None
                value = servresult[i * numresultsperpage:]
            else:
                contToken = "https://{}/query?{}".format(hostname, str(i + 1))
                value = servresult[i * numresultsperpage:(i + 1) * numresultsperpage]

            cost += 0.5 + i
            service_client.add(
                method=responses.POST,
                url=url,
                body=json.dumps({
                    "value" : value,
                    "continuationToken" : contToken
                }),
                status=200,
                content_type="application/json",
                match_querystring=False,
                headers={
                    "Query-Charge": str(0.5 + i)
                }
            )

        # Create expected result
        query_result = {
            "result": servresult
        }
        if show_cost:
            query_result["cost"] = cost

        result = subject.query_twins(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            query_command=query_command,
            show_cost=show_cost,
            resource_group_name=None
        )

        assert result == query_result

    @pytest.fixture(params=[(400, 200), (401, 200), (500, 200), (200, 400), (200, 401), (200, 500)])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.POST,
            url="https://{}/query".format(
                hostname
            ),
            body=json.dumps({
                "value": [generate_twin_result()],
                "continuationToken": "https://{}/query?2".format(hostname)
            }),
            status=request.param[0],
            content_type="application/json",
            match_querystring=False,
            headers={
                "Query-Charge": "1.0"
            }
        )

        mocked_response.add(
            method=responses.POST,
            url="https://{}/query?2".format(
                hostname
            ),
            body=json.dumps({"value": [generate_twin_result()]}),
            status=request.param[1],
            content_type="application/json",
            match_querystring=False,
            headers={
                "Query-Charge": "1.0"
            }
        )

        yield mocked_response

    def test_query_twins_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError):
            subject.query_twins(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                query_command=generic_query,
                show_cost=False,
                resource_group_name=None
            )
            # For some reason the new responses pkg doesnt fail on the first 500...
            status_codes = [call.response.status_code for call in service_client_error.calls]
            assert status_codes == [500, 200]
            raise CLIError()


class TestTwinCreateTwin(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "if_none_match, properties, resource_group_name",
        [
            (False, None, None),
            (True, None, None),
            (False, None, resource_group),
            (False, generic_patch_1, None),
            (False, generic_patch_2, None)
        ]
    )
    def test_create_twin(self, fixture_cmd, service_client, if_none_match, properties, resource_group_name):
        result = subject.create_twin(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            model_id=model_id,
            if_none_match=if_none_match,
            properties=properties,
            resource_group_name=resource_group_name
        )

        twin_request = service_client.calls[0].request
        assert twin_request.method == "PUT"
        assert "{}/digitaltwins/{}".format(hostname, twin_id) in twin_request.url

        twin_request_body = json.loads(twin_request.body)
        assert twin_request_body["$dtId"] == twin_id
        assert twin_request_body["$metadata"]["$model"] == model_id

        if if_none_match:
            assert twin_request.headers["If-None-Match"] == "*"

        if properties:
            for (key, value) in json.loads(properties).items():
                assert twin_request_body[key] == value

        assert result == json.loads(generic_result)

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_create_twin_error(self, fixture_cmd, service_client_error):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.create_twin(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                model_id=model_id,
                properties=None
            )
        if service_client_error.calls[0].response.status_code == 500:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinShowTwin(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "resource_group_name",
        [None, resource_group]
    )
    def test_show_twin(self, fixture_cmd, service_client, resource_group_name):
        result = subject.show_twin(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            resource_group_name=resource_group_name
        )

        assert result == json.loads(generic_result)

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "resource_group_name",
        [None, resource_group]
    )
    def test_show_twin_error(self, fixture_cmd, service_client_error, resource_group_name):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.show_twin(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                resource_group_name=resource_group_name
            )
        if service_client_error.calls[0].response.status_code == 500:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinUpdateTwin(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=202,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=json.dumps(generate_twin_result()),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "json_patch, resource_group_name, etag",
        [
            (json.dumps({}), None, None),
            (json.dumps({}), resource_group, None),
            (json.dumps({}), None, etag),
            (generic_patch_1, None, None),
            (generic_patch_2, None, None)
        ]
    )
    def test_update_twin(self, fixture_cmd, service_client, json_patch, resource_group_name, etag):
        result = subject.update_twin(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            json_patch=json_patch,
            resource_group_name=resource_group_name,
            etag=etag
        )

        # check patch request
        patch_request = service_client.calls[0].request
        assert patch_request.method == "PATCH"

        expected_request_body = [json.loads(json_patch)]
        assert json.loads(patch_request.body) == expected_request_body

        assert patch_request.headers["If-Match"] == etag if etag else "*"

        # check get request
        get_request = service_client.calls[1].request
        assert get_request.method == "GET"

        assert result == generate_twin_result()

    def test_update_twin_invalid_patch(self, fixture_cmd, service_client):
        # CLIError is raised when --json-patch is not dict or list
        with pytest.raises(CLIError) as e:
            subject.update_twin(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                json_patch="'{op:add,path:/setPointTemp,value:50.2}'",
                resource_group_name=None,
                etag=None
            )
        assert str(e.value) == "--json-patch content must be an object or array. Actual type was: str"

    @pytest.fixture(params=[(400, 200), (401, 200), (500, 200), (202, 400), (202, 401), (202, 500)])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=request.param[0],
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=request.param[1],
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_update_twin_error(self, fixture_cmd, service_client_error):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.update_twin(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                json_patch=generic_patch_1,
                resource_group_name=None,
                etag=None
            )
        status_codes = [call.response.status_code for call in service_client_error.calls]
        # Retries 5 times
        if status_codes == [202] + [500] * 5:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinDeleteTwin(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=204,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "resource_group_name, etag",
        [(None, None), (resource_group, None), (None, etag)]
    )
    def test_delete_twin(self, fixture_cmd, service_client, resource_group_name, etag):
        result = subject.delete_twin(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            resource_group_name=resource_group_name,
            etag=etag
        )

        delete_request = service_client.calls[0].request
        assert delete_request.method == "DELETE"
        assert delete_request.headers["If-Match"] == etag if etag else "*"

        assert result is None

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/digitaltwins/{}".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "resource_group_name, etag",
        [(None, None), (resource_group, None), (None, etag)]
    )
    def test_delete_twin_error(self, fixture_cmd, service_client_error, resource_group_name, etag):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.delete_twin(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                resource_group_name=resource_group_name,
                etag=etag
            )
        if service_client_error.calls[0].response.status_code == 500:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinDeleteAllTwin(object):
    @pytest.fixture
    def service_client_all(self, mocked_response, start_twin_response):
        yield mocked_response

    @pytest.mark.parametrize(
        "number_twins", [0, 1, 3]
    )
    def test_delete_twin_all(self, mocker, fixture_cmd, service_client_all, number_twins):

        # Create query call and delete calls
        query_result = []
        for i in range(number_twins):
            twin = generate_twin_result(randomized=True)
            query_result.append(twin)
            # Query calls to check if there are any relationships
            service_client_all.add(
                method=responses.GET,
                url="https://{}/digitaltwins/{}/incomingrelationships".format(
                    hostname, twin["$dtId"]
                ),
                body=json.dumps({
                    "value" : [],
                    "nextLink" : None
                }),
                status=200,
                content_type="application/json",
                match_querystring=False
            )
            service_client_all.add(
                method=responses.GET,
                url="https://{}/digitaltwins/{}/relationships".format(
                    hostname, twin["$dtId"]
                ),
                body=json.dumps({
                    "value" : [],
                    "nextLink" : None
                }),
                status=200,
                content_type="application/json",
                match_querystring=False
            )
            # Delete call
            service_client_all.add(
                method=responses.DELETE,
                url="https://{}/digitaltwins/{}".format(
                    hostname, twin["$dtId"]
                ),
                body=generic_result,
                status=204 if i % 2 == 0 else 400,
                content_type="application/json",
                match_querystring=False,
            )
        # Query call for twins to delete
        service_client_all.add(
            method=responses.POST,
            url="https://{}/query".format(
                hostname
            ),
            body=json.dumps({
                "value": query_result,
                "continuationToken": None
            }),
            status=200,
            content_type="application/json",
            match_querystring=False,
            headers={
                "Query-Charge": "1.0"
            }
        )

        # Call the delete all command
        result = subject.delete_all_twin(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
        )

        delete_request = service_client_all.calls[0].request
        assert delete_request.method == "POST"

        # Check delete calls
        for i in range(number_twins):
            query1_request = service_client_all.calls[1 + 3 * i].request
            assert query1_request.method == "GET"
            assert query_result[i]["$dtId"] in query1_request.url

            query2_request = service_client_all.calls[2 + 3 * i].request
            assert query2_request.method == "GET"
            assert query_result[i]["$dtId"] in query2_request.url

            delete_request = service_client_all.calls[3 + 3 * i].request
            assert delete_request.method == "DELETE"
            assert query_result[i]["$dtId"] in delete_request.url

        assert result is None


class TestTwinCreateRelationship(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "relationship, if_none_match, properties, resource_group_name",
        [
            ("contains", False, None, None),
            ("", False, None, None),
            ("contains", True, None, None),
            ("contains", False, generic_patch_1, None),
            ("contains", False, generic_patch_2, None),
            ("contains", False, None, resource_group)
        ]
    )
    def test_create_relationship(self, fixture_cmd, service_client, relationship, if_none_match, properties, resource_group_name):
        result = subject.create_relationship(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            target_twin_id=target_twin_id,
            relationship_id=relationship_id,
            relationship=relationship,
            if_none_match=if_none_match,
            properties=properties,
            resource_group_name=resource_group_name
        )

        # check body
        put_request = service_client.calls[0].request
        assert put_request.method == "PUT"
        assert "{}/digitaltwins/{}/relationships/{}".format(hostname, twin_id, relationship_id) in put_request.url
        result_request_body = json.loads(put_request.body)

        assert result_request_body["$targetId"] == target_twin_id
        assert result_request_body["$relationshipName"] == relationship

        if if_none_match:
            assert put_request.headers["If-None-Match"] == "*"

        if properties:
            for (key, value) in json.loads(properties).items():
                assert result_request_body[key] == value

        assert result == json.loads(generic_result)

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_create_relationship_error(self, fixture_cmd, service_client_error):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.create_relationship(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                target_twin_id=target_twin_id,
                relationship_id=relationship_id,
                relationship=""
            )
        if service_client_error.calls[0].response.status_code == 500:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinShowRelationship(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize("resource_group_name", [None, resource_group])
    def test_show_relationship(self, fixture_cmd, service_client, resource_group_name):
        result = subject.show_relationship(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            relationship_id=relationship_id,
            resource_group_name=resource_group_name
        )

        assert result == json.loads(generic_result)

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_show_relationship_error(self, fixture_cmd, service_client_error):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.show_relationship(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                relationship_id=relationship_id,
                resource_group_name=None
            )
        if service_client_error.calls[0].response.status_code == 500:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinUpdateRelationship(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=204,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "json_patch, resource_group_name, etag",
        [
            (json.dumps({}), None, None),
            (generic_patch_1, None, None),
            (generic_patch_1, resource_group, None),
            (generic_patch_1, None, etag),
            (generic_patch_2, None, None)
        ]
    )
    def test_update_relationship(self, fixture_cmd, service_client, json_patch, resource_group_name, etag):
        result = subject.update_relationship(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            relationship_id=relationship_id,
            json_patch=json_patch,
            resource_group_name=resource_group_name,
            etag=etag
        )
        # check patch request
        patch_request = service_client.calls[0].request
        assert patch_request.method == "PATCH"

        expected_request_body = [json.loads(json_patch)]
        assert json.loads(patch_request.body) == expected_request_body

        assert patch_request.headers["If-Match"] == etag if etag else "*"

        # check get request
        get_request = service_client.calls[1].request
        assert get_request.method == "GET"

        assert result == json.loads(generic_result)

    def test_update_relationship_invalid_patch(self, fixture_cmd, service_client):
        # CLIError is raised when --json-patch is not dict or list
        with pytest.raises(CLIError) as e:
            subject.update_relationship(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                relationship_id=relationship_id,
                json_patch="'{op:add,path:/setPointTemp,value:50.2}'",
                resource_group_name=None,
                etag=None
            )
        assert str(e.value) == "--json-patch content must be an object or array. Actual type was: str"

    @pytest.fixture(params=[(400, 200), (401, 200), (500, 200), (204, 400), (204, 401), (204, 500)])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=request.param[0],
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=request.param[1],
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_update_relationship_error(self, fixture_cmd, service_client_error):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.update_relationship(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                relationship_id=relationship_id,
                json_patch=generic_patch_1,
                resource_group_name=None,
                etag=None
            )
        status_codes = [call.response.status_code for call in service_client_error.calls]
        # Retries 5 times
        if status_codes == [204] + [500] * 5:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinListRelationship(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        yield mocked_response

    @pytest.mark.parametrize(
        "incoming_relationships, relationship, resource_group_name, servresult, numresultsperpage",
        [
            (False, None, None, [], 1),
            (True, None, None, [], 1),
            (False, "", None, [], 1),
            (True, "", None, [], 1),
            (False, "", None, [generate_relationship("")], 1),
            (False, "contains", None, [], 1),
            (True, "contains", None, [], 1),
            (False, "contains", None, [generate_relationship("contains")], 1),
            (True, "contains", None, [generate_relationship("contains")], 1),
            (False, "contains", None, [generate_relationship("other")], 1),
            (True, "contains", None, [generate_relationship("other")], 2),
            (False, "contains", None, [generate_relationship("other"),
                                       generate_relationship("contains"),
                                       generate_relationship("contains"),
                                       generate_relationship("other")], 2),
            (True, "contains", None, [generate_relationship("other"),
                                      generate_relationship("contains"),
                                      generate_relationship("contains"),
                                      generate_relationship("other")], 1),
            (False, None, resource_group, [], 1)
        ]
    )
    def test_list_relationship(
        self,
        fixture_cmd,
        service_client,
        incoming_relationships,
        relationship,
        resource_group_name,
        servresult,
        numresultsperpage
    ):
        # Set up number of pages, setting it to 1 if result is []
        numpages = int(len(servresult) / numresultsperpage)
        if numpages == 0:
            numpages += 1
        relationship = "incomingrelationships" if incoming_relationships else "relationships"

        # Create and add the mocked responses
        for i in range(numpages):
            if i == 0:
                url = "https://{}/digitaltwins/{}/{}".format(hostname, twin_id, relationship)
            else:
                url = "https://{}/digitaltwins/{}/{}?{}".format(hostname, twin_id, relationship, str(i))

            if numpages - i == 1:
                contToken = None
                value = servresult[i * numresultsperpage:]
            else:
                contToken = "https://{}/digitaltwins/{}/{}?{}".format(hostname, twin_id, relationship, str(i + 1))
                value = servresult[i * numresultsperpage:(i + 1) * numresultsperpage]

            service_client.add(
                method=responses.GET,
                url=url,
                body=json.dumps({
                    "value" : value,
                    "nextLink" : contToken
                }),
                status=200,
                content_type="application/json",
                match_querystring=False
            )

        result = subject.list_relationships(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            incoming_relationships=incoming_relationships,
            relationship=relationship,
            resource_group_name=resource_group_name
        )

        # Check result, unpack if it is a Paged object
        if incoming_relationships:
            expected_result = [
                x
                for x in servresult
                if x["$relationshipName"] and x["$relationshipName"] == relationship
            ]
            assert result == expected_result
        else:
            assert isinstance(result, Paged)
            unpacked_result = []
            try:
                while True:
                    unpacked_result.extend(result.advance_page())
            except StopIteration:
                pass

            assert unpacked_result == servresult

    @pytest.fixture(params=[(400, 200), (401, 200), (500, 200), (200, 400), (200, 401), (200, 500)])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/incomingrelationships".format(
                hostname, twin_id
            ),
            body=json.dumps({
                "value": [generate_relationship("contains")],
                "nextLink": "https://{}/digitaltwins/{}/incomingrelationships?2".format(hostname, twin_id)
            }),
            status=request.param[0],
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/incomingrelationships?2".format(
                hostname, twin_id
            ),
            body=json.dumps({"value": [generate_relationship("contains")]}),
            status=request.param[1],
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_list_relationship_error(self, fixture_cmd, service_client_error):
        with pytest.raises((CLIError, ClientRequestError)):
            subject.list_relationships(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                incoming_relationships=True,
                relationship=None,
                resource_group_name=None
            )
            # For some reason the new responses pkg doesnt fail on the first 500...
            status_codes = [call.response.status_code for call in service_client_error.calls]
            assert status_codes == [500, 200]
            raise CLIError()


class TestTwinDeleteRelationship(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=204,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "resource_group_name, etag",
        [(None, None), (resource_group, None), (None, etag)]
    )
    def test_delete_relationship(self, fixture_cmd, service_client, resource_group_name, etag):
        result = subject.delete_relationship(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            relationship_id=relationship_id,
            resource_group_name=resource_group_name,
            etag=etag
        )

        delete_request = service_client.calls[0].request
        assert delete_request.method == "DELETE"
        assert delete_request.headers["If-Match"] == etag if etag else "*"

        assert result is None

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/digitaltwins/{}/relationships/{}".format(
                hostname, twin_id, relationship_id
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_delete_relationship_error(self, fixture_cmd, service_client_error):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.delete_relationship(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                relationship_id=relationship_id,
                resource_group_name=None,
                etag=None
            )
        if service_client_error.calls[0].response.status_code == 500:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinDeleteAllRelationship(object):
    @pytest.fixture
    def service_client_all(self, mocked_response, start_twin_response):
        yield mocked_response

    @pytest.mark.parametrize(
        "incoming, outcoming",
        [
            (0, 0),
            (1, 0),
            (0, 1),
            (1, 1),
            (3, 0),
            (0, 3),
            (3, 3),
        ]
    )
    def test_delete_relationship_all(self, mocker, fixture_cmd, service_client_all, incoming, outcoming):
        # Create query call with incoming_relationships=True
        incoming_query = []
        for i in range(incoming):
            relationship = generate_relationship("contains")
            incoming_query.append(relationship)
            service_client_all.add(
                method=responses.DELETE,
                url="https://{}/digitaltwins/{}/relationships/{}".format(
                    hostname, relationship["$sourceId"], relationship["$relationshipId"]
                ),
                body=generic_result,
                status=204 if i % 2 == 0 else 400,
                content_type="application/json",
                match_querystring=False,
            )
        service_client_all.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/incomingrelationships".format(
                hostname, twin_id
            ),
            body=json.dumps({
                "value" : incoming_query,
                "nextLink" : None
            }),
            status=200,
            content_type="application/json",
            match_querystring=False
        )

        # Create query call with incoming_relationships=False
        outcoming_query = []
        for i in range(incoming):
            relationship = generate_relationship("contains")
            outcoming_query.append(relationship)
            service_client_all.add(
                method=responses.DELETE,
                url="https://{}/digitaltwins/{}/relationships/{}".format(
                    hostname, twin_id, relationship["$relationshipId"]
                ),
                body=generic_result,
                status=204 if i % 2 == 0 else 400,
                content_type="application/json",
                match_querystring=False,
            )
        service_client_all.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/relationships".format(
                hostname, twin_id
            ),
            body=json.dumps({
                "value" : outcoming_query,
                "nextLink" : None
            }),
            status=200,
            content_type="application/json",
            match_querystring=False
        )

        # Run the delete all command
        result = subject.delete_all_relationship(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
        )

        # First two calls should be the query calls
        assert service_client_all.calls[0].request.method == "GET"
        assert service_client_all.calls[1].request.method == "GET"

        call_num = 2
        for i in range(len(incoming_query)):
            delete_request = service_client_all.calls[call_num + i].request
            assert delete_request.method == "DELETE"
            assert incoming_query[i]["$relationshipId"] in delete_request.url

        call_num += len(incoming_query)
        for i in range(len(outcoming_query)):
            delete_request = service_client_all.calls[call_num + i].request
            assert delete_request.method == "DELETE"
            assert outcoming_query[i]["$relationshipId"] in delete_request.url
        assert len(service_client_all.calls) == call_num + len(outcoming_query)

        assert result is None

    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        yield mocked_response

    @pytest.mark.parametrize(
        "number_twins", [0, 1, 3]
    )
    def test_delete_relationships_all_twins(self, mocker, fixture_cmd, service_client, number_twins):
        # Create query call and delete calls
        query_result = []
        for i in range(number_twins):
            twin = generate_twin_result(randomized=True)
            query_result.append(twin)
            # Query calls to check if there are any relationships
            service_client.add(
                method=responses.GET,
                url="https://{}/digitaltwins/{}/incomingrelationships".format(
                    hostname, twin["$dtId"]
                ),
                body=json.dumps({
                    "value" : [],
                    "nextLink" : None
                }),
                status=200,
                content_type="application/json",
                match_querystring=False
            )
            service_client.add(
                method=responses.GET,
                url="https://{}/digitaltwins/{}/relationships".format(
                    hostname, twin["$dtId"]
                ),
                body=json.dumps({
                    "value" : [],
                    "nextLink" : None
                }),
                status=200,
                content_type="application/json",
                match_querystring=False
            )
            # the only difference between this and delete_all_twins is no twin delete call
        # Query call for twins to delete
        service_client.add(
            method=responses.POST,
            url="https://{}/query".format(
                hostname
            ),
            body=json.dumps({
                "value": query_result,
                "continuationToken": None
            }),
            status=200,
            content_type="application/json",
            match_querystring=False,
            headers={
                "Query-Charge": "1.0"
            }
        )

        # Call the delete all command
        result = subject.delete_all_relationship(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
        )

        delete_request = service_client.calls[0].request
        assert delete_request.method == "POST"

        # Check delete calls
        for i in range(number_twins):
            query1_request = service_client.calls[1 + 2 * i].request
            assert query1_request.method == "GET"
            assert query_result[i]["$dtId"] in query1_request.url

            query2_request = service_client.calls[2 + 2 * i].request
            assert query2_request.method == "GET"
            assert query_result[i]["$dtId"] in query2_request.url

        assert result is None


class TestTwinSendTelemetry(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.POST,
            url="https://{}/digitaltwins/{}/telemetry".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=204,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.POST,
            url="https://{}/digitaltwins/{}/components/{}/telemetry".format(
                hostname, twin_id, component_path
            ),
            body=generic_result,
            status=204,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "dt_id, component_path, telemetry, telemetry_source_time, resource_group_name",
        [
            (None, None, json.dumps({}), None, None),
            ("DT_ID", None, json.dumps({}), None, None),
            (None, component_path, json.dumps({}), None, None),
            (None, None, generic_patch_1, None, None),
            (None, None, generic_patch_2, None, None),
            (None, None, generic_patch_2, "2019-10-12T07:20:50.52Z", None),
            (None, None, json.dumps({}), None, resource_group)
        ]
    )
    def test_send_telemetry(
        self, fixture_cmd, service_client, dt_id, component_path, telemetry, telemetry_source_time, resource_group_name
    ):
        result = subject.send_telemetry(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            dt_id=dt_id,
            component_path=component_path,
            telemetry=telemetry,
            telemetry_source_time=telemetry_source_time,
            resource_group_name=resource_group_name,
        )

        start = 0
        if component_path:
            component_telemetry_request = service_client.calls[start].request
            assert component_telemetry_request.method == "POST"
            assert (
                "{}/digitaltwins/{}/components/{}/telemetry".format(hostname, twin_id, component_path)
                in component_telemetry_request.url
            )

            expected_request_body = json.loads(telemetry)
            assert json.loads(component_telemetry_request.body) == expected_request_body

            if dt_id:
                component_telemetry_request.headers["Message-Id"] == dt_id

            start += 1

        # Check POST telemetry
        twin_telemetry_request = service_client.calls[start].request
        assert twin_telemetry_request.method == "POST"
        assert "{}/digitaltwins/{}/telemetry".format(hostname, twin_id) in twin_telemetry_request.url

        expected_request_body = json.loads(telemetry)
        assert json.loads(twin_telemetry_request.body) == expected_request_body

        if dt_id:
            twin_telemetry_request.headers["Message-Id"] == dt_id
        if telemetry_source_time:
            twin_telemetry_request.headers["Telemetry-Source-Time"] == telemetry_source_time

        assert result is None

    @pytest.fixture(params=[(400, 204), (401, 204), (500, 204), (204, 400), (204, 401), (204, 500)])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.POST,
            url="https://{}/digitaltwins/{}/telemetry".format(
                hostname, twin_id
            ),
            body=generic_result,
            status=request.param[0],
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.POST,
            url="https://{}/digitaltwins/{}/components/{}/telemetry".format(
                hostname, twin_id, component_path
            ),
            body=generic_result,
            status=request.param[1],
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_send_telemetry_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError):
            subject.send_telemetry(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                dt_id=None,
                component_path=component_path,
                telemetry=json.dumps({}),
                resource_group_name=None,
            )


class TestTwinShowComponent(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/components/{}".format(
                hostname, twin_id, component_path
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize("resource_group_name", [None, resource_group])
    def test_show_component(self, fixture_cmd, service_client, resource_group_name):
        result = subject.show_component(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            component_path=component_path,
            resource_group_name=resource_group_name,
        )

        assert result == json.loads(generic_result)

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/components/{}".format(
                hostname, twin_id, component_path
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_show_component_error(self, fixture_cmd, service_client_error):
        with pytest.raises((CLIError, ClientRequestError)) as e:
            subject.show_component(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                component_path=component_path,
                resource_group_name=None,
            )
        if service_client_error.calls[0].response.status_code == 500:
            assert isinstance(e.value, ClientRequestError)
        else:
            assert isinstance(e.value, CLIError)


class TestTwinUpdateComponent(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/digitaltwins/{}/components/{}".format(
                hostname, twin_id, component_path
            ),
            body=generic_result,
            status=204,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}/components/{}".format(
                hostname, twin_id, component_path
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "json_patch, resource_group_name, etag",
        [
            (json.dumps({}), None, None),
            (generic_patch_1, None, None),
            (generic_patch_2, None, None),
            (generic_patch_1, resource_group, None),
            (generic_patch_1, None, etag)
        ]
    )
    def test_update_component(self, fixture_cmd, service_client, json_patch, resource_group_name, etag):
        result = subject.update_component(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            twin_id=twin_id,
            component_path=component_path,
            json_patch=json_patch,
            resource_group_name=resource_group_name,
            etag=etag
        )
        # check patch request
        patch_request = service_client.calls[0].request
        assert patch_request.method == "PATCH"

        expected_request_body = [json.loads(json_patch)]
        assert json.loads(patch_request.body) == expected_request_body

        assert patch_request.headers["If-Match"] == etag if etag else "*"

        # check get request
        get_request = service_client.calls[1].request
        assert get_request.method == "GET"

        assert result == json.loads(generic_result)

    def test_update_component_invalid_patch(self, fixture_cmd, service_client):
        # CLIError is raised when --json-patch is not dict or list
        with pytest.raises(CLIError) as e:
            subject.update_component(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                component_path=component_path,
                json_patch="'{op:add,path:/setPointTemp,value:50.2}'",
                resource_group_name=None,
                etag=None
            )
        assert str(e.value) == "--json-patch content must be an object or array. Actual type was: str"

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, start_twin_response, request):
        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/digitaltwins/{}/components/{}".format(
                hostname, twin_id, component_path
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_update_component_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError):
            subject.update_component(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                twin_id=twin_id,
                component_path=component_path,
                json_patch=generic_patch_1,
                resource_group_name=None,
                etag=None
            )
