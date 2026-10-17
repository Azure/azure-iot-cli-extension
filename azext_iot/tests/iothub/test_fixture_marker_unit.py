# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from azext_iot.tests.helpers import get_closest_marker
from azext_iot.tests.iothub import conftest as fixtures
from azext_iot.tests.settings import HUB_TEST_LOCATION


@pytest.fixture
def function_marker(request):
    return get_closest_marker(request)


@pytest.fixture(scope="module")
def module_marker(request):
    return get_closest_marker(request)


@pytest.fixture(scope="class")
def class_marker(request):
    return get_closest_marker(request)


@pytest.fixture(scope="session")
def session_marker(request):
    return get_closest_marker(request)


@pytest.fixture(scope="module")
def dynamic_marker(request):
    return get_closest_marker(request)


@pytest.mark.hub_infrastructure(count=2, sys_identity=True)
def test_first_marker_is_not_session_wide_configuration(function_marker):
    assert function_marker.kwargs == {"count": 2, "sys_identity": True}


def test_unmarked_consumer_keeps_default_infrastructure(function_marker):
    assert function_marker is None


@pytest.mark.hub_infrastructure(count=0)
def test_function_consumer_can_request_no_hubs(function_marker):
    assert function_marker.kwargs == {"count": 0}


@pytest.mark.hub_infrastructure(count=1)
def test_module_fixture_uses_its_actual_consumer(module_marker):
    assert module_marker.kwargs == {"count": 1}


@pytest.mark.hub_infrastructure(count=2)
class TestClassMarker:
    @pytest.mark.hub_infrastructure(count=1)
    def test_function_marker_overrides_class_for_class_fixture(self, class_marker):
        assert class_marker.kwargs == {"count": 1}


@pytest.mark.hub_infrastructure(count=1)
def test_session_fixture_uses_its_actual_consumer(session_marker):
    assert session_marker.kwargs == {"count": 1}


@pytest.mark.hub_infrastructure(count=1)
def test_dynamic_fixture_uses_its_requesting_test(request):
    assert request.getfixturevalue("dynamic_marker").kwargs == {"count": 1}


@pytest.mark.parametrize("settings,expected_count", [(None, 1), ({"count": 1}, 1), ({"count": 2}, 2)])
def test_hub_provisioner_does_not_borrow_other_test_identity_settings(mocker, settings, expected_count):
    unrelated = Mock()
    unrelated.get_closest_marker.return_value = SimpleNamespace(kwargs={"count": 2, "sys_identity": True})
    consumer = Mock()
    consumer.get_closest_marker.return_value = None if settings is None else SimpleNamespace(kwargs=settings)
    request = SimpleNamespace(
        node=Mock(), _pyfuncitem=consumer, session=SimpleNamespace(items=[unrelated, consumer]),
    )
    cli = mocker.patch.object(fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {
        "location": HUB_TEST_LOCATION,
        "properties": {"disableLocalAuth": True},
    }

    hubs = fixtures._iot_hubs_provisioner(request)

    assert len(hubs) == expected_count
    assert cli.invoke.call_count == expected_count
    for call in cli.invoke.call_args_list:
        assert "--system-assigned-mi" not in call.args[0]
        assert "--user-assigned-mi" not in call.args[0]
        assert f"--location {HUB_TEST_LOCATION}" in call.args[0]
        assert "--disable-local-auth true" in call.args[0]
