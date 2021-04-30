# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import responses
import json
import urllib
from knack.cli import CLIError
from azext_iot.digitaltwins import commands_models as subject
from azext_iot.tests.generators import generate_generic_id
from msrest.paging import Paged

instance_name = generate_generic_id()
hostname = "{}.subdomain.domain".format(instance_name)
resource_group = 'myrg'
api_version = "2020-10-31"


def generate_model_id():
    normal_id = "dtmi:com:{}:{};1".format(generate_generic_id(), generate_generic_id())
    url_id = urllib.parse.quote_plus(normal_id)
    return normal_id, url_id


model_id, url_model_id = generate_model_id()
generic_result = json.dumps({"result": generate_generic_id()})


def generate_model_result(model_id=None):
    model_id = model_id if model_id else generate_model_id()[0]
    return {
        "model": {
            "@context" : ["dtmi:com:context;2"],
            "@id" : model_id,
            "@type" : "Interface"
        },
        "id": model_id
    }


@pytest.fixture
def control_and_data_plane_client(mocker, fixture_cmd):
    from azext_iot.sdk.digitaltwins.controlplane import AzureDigitalTwinsManagementClient
    from azext_iot.sdk.digitaltwins.dataplane import AzureDigitalTwinsAPI
    from azext_iot.digitaltwins.providers.auth import DigitalTwinAuthentication

    patched_get_raw_token = mocker.patch(
        "azure.cli.core._profile.Profile.get_raw_token"
    )
    patched_get_raw_token.return_value = (
        mocker.MagicMock(name="creds"),
        mocker.MagicMock(name="subscription"),
        mocker.MagicMock(name="tenant"),
    )

    control_plane_patch = mocker.patch(
        "azext_iot.digitaltwins.providers.digitaltwins_service_factory"
    )
    control_plane_patch.return_value = AzureDigitalTwinsManagementClient(
        credentials=DigitalTwinAuthentication(
            fixture_cmd, "00000000-0000-0000-0000-000000000000"
        ),
        subscription_id="00000000-0000-0000-0000-000000000000",
    )

    data_plane_patch = mocker.patch(
        "azext_iot.digitaltwins.providers.base.DigitalTwinsProvider.get_sdk"
    )

    data_plane_patch.return_value = AzureDigitalTwinsAPI(
        credentials=DigitalTwinAuthentication(
            fixture_cmd, "00000000-0000-0000-0000-000000000000"
        ),
        base_url="https://{}/".format(hostname)
    )

    return control_plane_patch, data_plane_patch


# @pytest.fixture
# def start_model_response(mocked_response, control_and_data_plane_client):
#     mocked_response.assert_all_requests_are_fired = False

#     mocked_response.add(
#         method=responses.GET,
#         content_type="application/json",
#         url=re.compile(
#             "https://management.azure.com/subscriptions/(.*)/"
#             "providers/Microsoft.DigitalTwins/digitalTwinsInstances"
#         ),
#         status=200,
#         match_querystring=False,
#         body=json.dumps({"hostName": hostname}),
#     )

#     yield mocked_response


def check_resource_group_name_call(service_client, resource_group_input):
    if ("management.azure.com/subscriptions" in service_client.calls[0].request.url):
        return 1
    return 0


class TestAddModels(object):
    @pytest.fixture(params=[200, 201])
    def service_client(self, mocked_response, control_and_data_plane_client, request):
        mocked_response.add(
            method=responses.POST,
            url="https://{}/models".format(
                hostname
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "models, num_direntry, from_directory, resource_group_name",
        [
            # Inline models, last one shows that inline models wins
            (generate_model_result(), None, None, None),
            ([generate_model_result()], None, None, None),
            ([generate_model_result(), generate_model_result()], None, None, None),
            (generate_model_result(), None, ".", None),

            # From_directory
            (generate_model_result(), 0, ".", None),
            (generate_model_result(), 1, ".", None),
            (generate_model_result(), 2, "./bar/", None),
            (generate_model_result(), 3, "./bar/", None),
            (generate_model_result(), 7, "./foo/", None),

            ([generate_model_result()], 0, ".", None),
            ([generate_model_result()], 1, ".", None),
            ([generate_model_result()], 2, "./bar/", None),
            ([generate_model_result()], 3, "./bar/", None),
            ([generate_model_result()], 7, "./foo/", None),

            (generate_model_result(), None, None, resource_group),
        ]
    )
    def test_add_models(
        self,
        mocker,
        fixture_cmd,
        service_client,
        models,
        num_direntry,
        from_directory,
        resource_group_name
    ):
        # Make function use code for from_directory if there is a directory and # of entries
        expected_payload = []
        if from_directory and num_direntry is not None:
            # need to patch scantree if directory, returns list of entry that has names
            patched_scantree = mocker.patch(
                'azext_iot.digitaltwins.providers.model.scantree'
            )

            # Have random file names, with third one for a file to be ignored
            directory_files = []
            for f in range(num_direntry):
                file_name = generate_generic_id() + [".json", ".dtdl", ".txt"][f % 3]
                file_mock = mocker.MagicMock()
                file_mock.name = file_name
                file_mock.path = file_name
                directory_files.append(
                    file_mock
                )
                if f % 3 != 2:
                    expected_payload.append(models)

            patched_scantree.return_value = directory_files

            # need to patch process_json_arg because the files do not exist
            patched_process_json_arg = mocker.patch(
                'azext_iot.digitaltwins.providers.model.process_json_arg'
            )

            # returns list of models or dict (one model)
            patched_process_json_arg.return_value = (
                models
            )

            # need to null models so that directory gets processed
            models = None
        else:
            if isinstance(models, list):
                expected_payload.extend(models)
            elif isinstance(models, dict):
                expected_payload.append(models)

        result = subject.add_models(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            models=str(models) if models else None,
            from_directory=from_directory,
            resource_group_name=resource_group_name
        )

        request_body = json.loads(service_client.calls[0].request.body)
        assert request_body == expected_payload
        assert result == json.loads(generic_result)

    def test_add_model_no_models_directory(self, fixture_cmd):
        with pytest.raises(CLIError):
            subject.add_models(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                models=None,
                from_directory=None,
            )

    @pytest.fixture(params=[400, 401, 403, 500])
    def service_client_error(self, mocked_response, control_and_data_plane_client, request):
        mocked_response.assert_all_requests_are_fired = False
        mocked_response.add(
            method=responses.POST,
            url="https://{}/models".format(
                hostname
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_add_models_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError):
            subject.add_models(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                models=str(generate_model_result()),
                from_directory=None,
                resource_group_name=None
            )


class TestShowModel(object):
    @pytest.fixture
    def service_client(self, mocked_response, control_and_data_plane_client):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/models/{}".format(
                hostname, url_model_id
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "definition, resource_group_name",
        [
            (False, None),
            (True, None),
            (False, resource_group)
        ]
    )
    def test_show_model(self, fixture_cmd, service_client, definition, resource_group_name):
        result = subject.show_model(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            model_id=model_id,
            definition=definition,
            resource_group_name=resource_group_name
        )

        lower_definition = str(definition).lower()
        request = service_client.calls[0].request
        assert request.method == "GET"
        assert "?includeModelDefinition={}".format(lower_definition) in request.url
        assert result == json.loads(generic_result)

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, control_and_data_plane_client, request):
        mocked_response.assert_all_requests_are_fired = False
        mocked_response.add(
            method=responses.GET,
            url="https://{}/models/{}".format(
                hostname, url_model_id
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_show_model_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError):
            subject.show_model(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                model_id=model_id,
                definition=False,
                resource_group_name=None
            )


class TestListModels(object):
    @pytest.fixture
    def service_client(self, mocked_response, control_and_data_plane_client):
        yield mocked_response

    @pytest.mark.parametrize(
        "definition, resource_group_name, num_results, num_dependencies, num_per_page",
        [
            (False, None, 0, 0, 1),
            (True, None, 0, 0, 1),
            (False, None, 0, 1, 1),
            (True, None, 0, 1, 1),
            (True, None, 1, 0, 1),
            (False, None, 1, 0, 1),
            (True, None, 2, 1, 1),
            (False, None, 3, 1, 2),
            (True, None, 3, 2, 3),
            (False, resource_group, 1, 0, 1)
        ]
    )
    def test_list_models(
        self,
        fixture_cmd,
        service_client,
        definition,
        resource_group_name,
        num_results,
        num_dependencies,
        num_per_page
    ):
        # Create the query portion of the url, create random dependencies
        query_url = "?"
        dependencies_for = []
        for i in range(num_dependencies):
            dependency_id, dependency_url_id = generate_model_id()
            dependencies_for.append(dependency_id)
            query_url += "dependenciesFor={}&".format(dependency_url_id)
        query_url += "includeModelDefinition={}".format(str(definition).lower())

        # Set up number of pages, setting it to 1 if result is []
        numpages = max(1, int(num_results / num_per_page))
        serv_result = [generate_model_result() for _ in range(num_results)]

        # Create and add the mocked responses
        for i in range(numpages):
            if i == 0:
                url = "https://{}/models?{}".format(hostname, query_url)
            else:
                url = "https://{}/models?{}?{}".format(hostname, query_url, str(i))

            if numpages - i == 1:
                contToken = None
                value = serv_result[i * num_per_page:]
            else:
                contToken = "https://{}/models?{}?{}".format(hostname, query_url, str(i + 1))
                value = serv_result[i * num_per_page:(i + 1) * num_per_page]

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

        result = subject.list_models(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            definition=definition,
            dependencies_for=dependencies_for,
            resource_group_name=resource_group_name
        )

        print(serv_result)

        assert isinstance(result, Paged)
        unpacked_result = []
        try:
            while True:
                unpacked_result.extend(result.advance_page())
        except StopIteration:
            pass

        # query in the url takes care of dependencies + model definition
        assert [{"model" : model.model, "id" : model.id} for model in unpacked_result] == serv_result


class TestUpdateModel(object):
    @pytest.fixture
    def service_client(self, mocked_response, control_and_data_plane_client):
        mocked_response.assert_all_requests_are_fired = False

        mocked_response.add(
            method=responses.GET,
            url="https://{}/models/{}".format(
                hostname, url_model_id
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/models/{}".format(
                hostname, url_model_id
            ),
            body=generic_result,
            status=204,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "decommission, resource_group_name",
        [
            (None, None),
            (True, None),
            (False, None),
            (False, resource_group)
        ]
    )
    def test_update_model(self, fixture_cmd, service_client, decommission, resource_group_name):
        result = subject.update_model(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            model_id=model_id,
            decommission=decommission,
            resource_group_name=resource_group_name
        )

        if decommission is None:
            # No updates or calls if decommission is None
            assert len(service_client.calls) == 0
            assert result is None
            return

        patch_request = service_client.calls[0].request
        assert patch_request.method == "PATCH"
        request_body = json.loads(patch_request.body)[0]
        assert request_body["op"] == "replace"
        assert request_body["path"] == "/decommissioned"
        assert request_body["value"] == decommission

        get_request = service_client.calls[1].request
        assert get_request.method == "GET"

        assert result == json.loads(generic_result)

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500), (400, 204), (401, 204), (500, 204)])
    def service_client_error(self, mocked_response, control_and_data_plane_client, request):
        mocked_response.assert_all_requests_are_fired = False

        mocked_response.add(
            method=responses.GET,
            url="https://{}/models/{}".format(
                hostname, url_model_id
            ),
            body=generic_result,
            status=request.param[0],
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/models/{}".format(
                hostname, url_model_id
            ),
            body=generic_result,
            status=request.param[1],
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_update_model_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError):
            subject.update_model(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                model_id=model_id,
                decommission=True,
                resource_group_name=None
            )


class TestDeleteModel(object):
    @pytest.fixture
    def service_client(self, mocked_response, control_and_data_plane_client):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/models/{}".format(
                hostname, url_model_id
            ),
            body=generic_result,
            status=204,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "resource_group_name",
        [None, resource_group]
    )
    def test_delete_model(self, fixture_cmd, service_client, resource_group_name):
        result = subject.delete_model(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            model_id=model_id,
            resource_group_name=resource_group_name
        )

        assert result is None

    @pytest.fixture(params=[400, 401, 500])
    def service_client_error(self, mocked_response, control_and_data_plane_client, request):
        mocked_response.assert_all_requests_are_fired = False
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/models/{}".format(
                hostname, url_model_id
            ),
            body=generic_result,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_delete_model_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError):
            subject.delete_model(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                model_id=model_id,
                resource_group_name=None
            )


class TestDeleteAllModels(object):
    def generate_model(self, service_client, model_ids=None, num_dependencies=0):
        model_id, url_model_id = model_ids if model_ids else generate_model_id()

        # Start making list call with dependencies, result should include self
        url = "https://{}/models?dependenciesFor={}&".format(hostname, url_model_id)
        value = [generate_model_result(model_id=model_id)]

        # Add depedencies to value and create those model calls
        for i in range(num_dependencies):
            dependant_id, url_dependant_id = generate_model_id()
            # Use i to help simulate different number of dependencies
            value.extend(
                self.generate_model(
                    service_client,
                    model_ids=(dependant_id, url_dependant_id),
                    num_dependencies=i
                )
            )

        # List call for current model with dependencies
        url += "includeModelDefinition=false&api-version={}".format(api_version)
        service_client.add(
            method=responses.GET,
            url=url,
            body=json.dumps({
                "value" : value,
                "nextLink" : None
            }),
            status=200,
            content_type="application/json",
            match_querystring=True
        )

        # Delete call for current model, have some failures
        service_client.add(
            method=responses.DELETE,
            url="https://{}/models/{}".format(hostname, url_model_id),
            body=generic_result,
            status=204 if num_dependencies % 2 == 0 else 400,
            content_type="application/json",
            match_querystring=False,
        )

        # Collect model values for the first List call
        return value

    @pytest.fixture
    def service_client(self, mocked_response, control_and_data_plane_client):
        yield mocked_response

    @pytest.mark.parametrize(
        "resource_group_name, model_dependencies",
        [
            (None, []),
            (None, [0]),
            (None, [0, 0, 0]),  # three models not dependent on each other
            (None, [1]),
            (None, [2]),
            (None, [1, 1, 0]),
            (None, [1, 0, 2, 0]),
            (resource_group, [0]),
        ]
    )
    def test_delete_all_models(self, fixture_cmd, service_client, resource_group_name, model_dependencies):
        # Generate the calls for each model: List call with dependencies + Delete call
        all_models = []
        for num in model_dependencies:
            all_models.extend(self.generate_model(service_client, num_dependencies=num))

        # First List call
        service_client.add(
            method=responses.GET,
            url="https://{}/models?includeModelDefinition=false&api-version={}".format(hostname, api_version),
            body=json.dumps({"value" : all_models, "nextLink": None}),
            status=200,
            content_type="application/json",
            match_querystring=True,
        )

        result = subject.delete_all_models(
            cmd=fixture_cmd,
            name_or_hostname=hostname,
            resource_group_name=resource_group_name
        )

        all_request = service_client.calls[0].request
        assert all_request.method == "GET"
        assert "/models?includeModelDefinition=false" in all_request.url

        # Check that each model had depedencies listed
        for i in range(len(all_models)):
            list_request = service_client.calls[1 + i].request
            assert list_request.method == "GET"
            assert "/models?dependenciesFor=" in list_request.url

        # Check that models were deleted
        start = 1 + len(all_models)
        for i in range(len(all_models)):
            delete_request = service_client.calls[start + i].request
            assert delete_request.method == "DELETE"

        assert result is None

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500), (400, 204), (401, 204), (500, 204)])
    def service_client_error(self, mocked_response, control_and_data_plane_client, request):
        mocked_response.assert_all_requests_are_fired = False
        # only failures unaccounted for are those from unpacking the list pager
        model_id, url_model_id = generate_model_id()

        mocked_response.add(
            method=responses.GET,
            url=(
                "https://{}/models?dependenciesFor={}&"
                "includeModelDefinition=false&api-version={}"
            ).format(url_model_id, hostname, api_version),
            body=json.dumps({"value" : generic_result, "nextLink": None}),
            status=request.param[0],
            content_type="application/json",
            match_querystring=True,
        )

        mocked_response.add(
            method=responses.GET,
            url="https://{}/models?includeModelDefinition=false&api-version={}".format(
                hostname,
                api_version
            ),
            body=json.dumps({
                "value" : generate_model_result(model_id=model_id),
                "nextLink": None
            }),
            status=request.param[1],
            content_type="application/json",
            match_querystring=True,
        )

        yield mocked_response

    def test_delete_all_models_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError):
            subject.delete_all_models(
                cmd=fixture_cmd,
                name_or_hostname=hostname,
                resource_group_name=None
            )
