# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Exercise the validation scenarios through the candidate CLI without network access."""

import pytest
from azure.cli.core._profile import Profile
from azure.cli.core.azclierror import (
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    logger as cli_error_logger,
)
from azure.core.exceptions import (
    ClientAuthenticationError,
    ResourceNotFoundError,
    ServiceRequestError,
)

from azext_iot.tests.adr import test_adr_update_instance_int as update_validation
from azext_iot.tests.adr import test_adr_validation_negatives_int as namespace_validation


_SCENARIOS = (
    (
        namespace_validation.TestADRValidationNegatives,
        "test_adr_validation_negatives",
        MutuallyExclusiveArgumentError,
        21,
    ),
    (
        update_validation.TestADRUpdateInstanceValidation,
        "test_update_instance_validation_negatives",
        RequiredArgumentMissingError,
        2,
    ),
)


@pytest.fixture
def scenario_factory(request, offline_cli):
    def create(scenario_type, method):
        scenario = scenario_type(method)
        scenario.setUp()
        request.addfinalizer(scenario.doCleanups)
        return scenario

    return create


@pytest.fixture(params=_SCENARIOS, ids=["cross-surface", "update-instance"])
def validation_scenario(request, scenario_factory):
    scenario_type, method, error_type, command_count = request.param
    scenario = scenario_factory(scenario_type, method)
    return scenario, getattr(scenario, method), error_type, command_count


@pytest.fixture
def namespace_lookup(mocker):
    not_found = ResourceNotFoundError("offline namespace does not exist")
    not_found.status_code = 404
    return mocker.patch(
        "azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get",
        side_effect=not_found,
    )


def test_validation_scenarios_use_actual_cli_guards(
    validation_scenario, namespace_lookup, mocker
):
    scenario, run, _, command_count = validation_scenario
    commands = mocker.spy(scenario, "cmd")
    run()
    assert commands.call_count == command_count
    assert all(not call.kwargs.get("expect_failure") for call in commands.call_args_list)
    if isinstance(scenario, namespace_validation.TestADRValidationNegatives):
        namespace_lookup.assert_called_once_with(
            resource_group_name=namespace_validation.TEST_RG,
            namespace_name="validation-ns-does-not-matter",
        )
    else:
        namespace_lookup.assert_not_called()


@pytest.mark.parametrize("error_type", [ClientAuthenticationError, ServiceRequestError])
def test_validation_scenarios_reject_credential_failures(
    validation_scenario, mocker, error_type
):
    _, run, _, _ = validation_scenario
    error = error_type("unrelated credential or transport failure")
    mocker.patch(
        "azure.cli.core._profile.Profile.get_login_credentials", side_effect=error
    )
    with pytest.raises(error_type) as raised:
        run()
    assert raised.value is error


def test_validation_scenarios_reject_wrong_guard_message(validation_scenario, mocker):
    _, run, error_type, _ = validation_scenario
    mocker.patch(
        "azure.cli.core._profile.Profile.get_login_credentials",
        side_effect=error_type("unrelated argument error"),
    )
    with pytest.raises(AssertionError, match="Regex pattern did not match"):
        run()


@pytest.mark.parametrize("error_type", [ClientAuthenticationError, ServiceRequestError])
def test_namespace_identity_guard_rejects_lookup_failures(
    scenario_factory, namespace_lookup, error_type
):
    scenario = scenario_factory(
        namespace_validation.TestADRValidationNegatives, "test_adr_validation_negatives"
    )
    error = error_type("namespace lookup failed")
    namespace_lookup.side_effect = error
    with pytest.raises(error_type) as raised:
        scenario.test_adr_validation_negatives()
    assert raised.value is error
    namespace_lookup.assert_called_once()


@pytest.mark.parametrize("error_type", [ClientAuthenticationError, ServiceRequestError])
def test_update_instance_identity_guard_rejects_credential_failures(
    scenario_factory, mocker, error_type
):
    scenario = scenario_factory(
        update_validation.TestADRUpdateInstanceValidation,
        "test_update_instance_validation_negatives",
    )
    error = error_type("second command credential failure")
    credentials = Profile.get_login_credentials.return_value
    profile = mocker.patch(
        "azure.cli.core._profile.Profile.get_login_credentials",
        side_effect=[credentials, error],
    )
    with pytest.raises(error_type) as raised:
        scenario.test_update_instance_validation_negatives()
    assert raised.value is error
    assert profile.call_count == 2


@pytest.mark.parametrize(
    "exit_code,message",
    [
        (1, "'device' is misspelled or not recognized by the system."),
        (2, "unrelated parser failure"),
    ],
)
def test_parser_rejections_require_exit_code_and_message(
    offline_cli, mocker, exit_code, message
):
    scenario = namespace_validation.TestADRValidationNegatives("test_adr_validation_negatives")

    def fail(*args, **kwargs):
        cli_error_logger.error(message)
        raise SystemExit(exit_code)

    mocker.patch.object(scenario, "cmd", side_effect=fail)
    with pytest.raises(AssertionError):
        scenario._assert_parser_error(
            "iot adr ns registry-device show",
            "'registry-device' is misspelled or not recognized by the system.",
        )
