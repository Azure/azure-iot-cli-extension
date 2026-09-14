# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Control-plane state scenarios share infrastructure only within this loadfile group."""

import json
import time

import pytest
from azure.cli.core.azclierror import ResourceNotFoundError, RequiredArgumentMissingError

from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.iothub.conftest import generate_hub_id
from azext_iot.tests.iothub.state import _state_helpers as state
from azext_iot.tests.settings import HUB_TEST_LOCATION


setup_hub_states_controlplane = state.setup_hub_states_controlplane
setup_file = state.setup_file


@pytest.mark.hub_infrastructure(count=2, sys_identity=True, user_identity=True, storage=True, desired_tags="abc=def")
@pytest.mark.timeout(state.CONTROLPLANE_LIFECYCLE_TIMEOUT, func_only=False)
def test_migrate_controlplane(setup_hub_states_controlplane):
    origin_name = setup_hub_states_controlplane[0]["name"]
    origin_rg = setup_hub_states_controlplane[0]["rg"]
    dest_name = setup_hub_states_controlplane[1]["name"]

    state._invoke_state(
        f"iot hub state migrate --origin-hub {origin_name} --origin-resource-group {origin_rg} "
        f"--destination-hub {dest_name} --destination-resource-group {origin_rg} -r --aspects {state.CONTROLPLANE}",
    )

    time.sleep(1)  # gives the hub time to update before the checks
    state.compare_hubs_controlplane(origin_name, dest_name, origin_rg)


@pytest.mark.hub_infrastructure(
    count=1, sys_identity=True, user_identity=True, storage=True, desired_tags="abc=def", system_endpoints=False
)
@pytest.mark.timeout(state.CONTROLPLANE_LIFECYCLE_TIMEOUT, func_only=False)
def test_migrate_controlplane_with_create(setup_hub_states_controlplane):
    """Create and compare two fresh destinations, with explicit and default destination RG."""
    origin_name = setup_hub_states_controlplane[0]["name"]
    origin_rg = setup_hub_states_controlplane[0]["rg"]
    dest_name = generate_hub_id()
    setup_hub_states_controlplane.append({"name": dest_name})
    state.delete_system_endpoints(origin_name, origin_rg)

    state._invoke_state(
        f"iot hub state migrate --origin-hub {origin_name} --origin-resource-group {origin_rg} "
        f"--destination-hub {dest_name} --destination-resource-group {origin_rg} -r --aspects {state.CONTROLPLANE}",
    )
    time.sleep(1)
    state.compare_hubs_controlplane(origin_name, dest_name, origin_rg)

    dest_name2 = generate_hub_id()
    setup_hub_states_controlplane.append({"name": dest_name2})
    state._invoke_state(
        f"iot hub state migrate --origin-hub {origin_name} --origin-resource-group {origin_rg} "
        f"--destination-hub {dest_name2} -r --aspects {state.CONTROLPLANE}",
    )
    time.sleep(1)
    state.compare_hubs_controlplane(origin_name, dest_name2, origin_rg)


@pytest.mark.hub_infrastructure(count=1)
def test_mirgate_hub_dataplane_error(provisioned_only_iot_hubs_module):
    """A dataplane-only migration cannot create a missing destination."""
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    hub_rg = provisioned_only_iot_hubs_module[0]["rg"]
    fake_hub_name = "fakehub"
    fake_hub_rg = "fakerg"
    result = state.cli.invoke(
        f"iot hub state migrate --origin-hub {hub_name} --origin-resource-group {hub_rg} "
        f"--destination-hub {fake_hub_name} --destination-resource-group {fake_hub_rg} --aspects {state.DATAPLANE}"
    )
    assert isinstance(result.get_error(), ResourceNotFoundError)


@pytest.mark.hub_infrastructure(count=1, sys_identity=True, user_identity=True, storage=True, desired_tags="abc=def")
@pytest.mark.timeout(state.CONTROLPLANE_LIFECYCLE_TIMEOUT, func_only=False)
def test_export_import_controlplane(setup_hub_states_controlplane):
    filename = setup_hub_states_controlplane[0]["filename"]
    hub_name = setup_hub_states_controlplane[0]["name"]
    hub_rg = setup_hub_states_controlplane[0]["rg"]
    hub_location = setup_hub_states_controlplane[0]["hub"]["location"]

    state._invoke_state(
        f"iot hub state export -n {hub_name} -f {filename} -g {hub_rg} -r --aspects {state.CONTROLPLANE}",
    )
    state.compare_hub_controlplane_to_file(filename, hub_name, hub_rg)
    state.clean_up_hub_controlplane(hub_name, hub_rg, hub_location)
    time.sleep(5)
    state._invoke_state(
        f"iot hub state import -n {hub_name} -f {filename} -g {hub_rg} -r --aspects {state.CONTROLPLANE}",
    )
    time.sleep(10)  # gives the hub time to update before the checks
    state.compare_hub_controlplane_to_file(filename, hub_name, hub_rg)


@pytest.mark.hub_infrastructure(
    count=1, sys_identity=True, user_identity=True, storage=True, desired_tags="abc=def", system_endpoints=False
)
@pytest.mark.timeout(state.CONTROLPLANE_LIFECYCLE_TIMEOUT, func_only=False)
def test_export_import_controlplane_with_create(setup_hub_states_controlplane):
    """Export a source and import into a fresh destination."""
    filename = setup_hub_states_controlplane[0]["filename"]
    hub_name = setup_hub_states_controlplane[0]["name"]
    hub_rg = setup_hub_states_controlplane[0]["rg"]
    dest_name = generate_hub_id()
    setup_hub_states_controlplane.append({"name": dest_name})
    state.delete_system_endpoints(hub_name, hub_rg)

    state._invoke_state(
        f"iot hub state export -n {hub_name} -f {filename} -g {hub_rg} -r --aspects {state.CONTROLPLANE}",
    )
    state.compare_hub_controlplane_to_file(filename, hub_name, hub_rg)
    time.sleep(5)
    state._invoke_state(
        f"iot hub state import -n {dest_name} -f {filename} -g {hub_rg} -r --aspects {state.CONTROLPLANE}",
    )
    time.sleep(10)  # gives the hub time to update before the checks
    state.compare_hub_controlplane_to_file(filename, dest_name, hub_rg)


@pytest.mark.hub_infrastructure(count=1)
def test_custom_scenarios_controlplane(provisioned_only_iot_hubs_module, provisioned_event_hub_module, setup_file):
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    hub_rg = provisioned_only_iot_hubs_module[0]["rg"]
    state.delete_system_endpoints(hub_name, hub_rg)

    eventhub_cstring = provisioned_event_hub_module["connectionString"]
    endpoint_name = generate_generic_id()
    state.cli.invoke(
        f"resource update -n {hub_name} -g {hub_rg} --resource-type Microsoft.Devices/IotHubs "
        f"--add properties.routing.endpoints.eventHubs connectionString='{eventhub_cstring}' name={endpoint_name}"
    )
    time.sleep(60)

    state._invoke_state(
        f"iot hub state export -n {hub_name} -f {setup_file} -g {hub_rg} -r --aspects {state.CONTROLPLANE}",
    )
    with open(setup_file, 'r', encoding='utf-8') as f:
        hub_info = json.load(f)
    hub_resource = hub_info["arm"]["resources"][0]
    eventhub_endpoints = hub_resource["properties"]["routing"]["endpoints"]["eventHubs"]
    assert len(eventhub_endpoints) == 0


@pytest.mark.hub_infrastructure(count=0)
def test_export_import_migrate_missing_hubs_error():
    filename = "./somefile.json"
    hub_name = "fakehub"
    hub_rg = "fakerg"
    result = state.cli.invoke(
        f"iot hub state export -n {hub_name} -f {filename} -g {hub_rg}"
    )
    assert isinstance(result.get_error(), ResourceNotFoundError)

    result = state.cli.invoke(
        f"iot hub state export -n {hub_name} -f {filename}"
    )
    assert isinstance(result.get_error(), ResourceNotFoundError)

    result = state.cli.invoke(
        f"iot hub state import -n {hub_name} -f {filename} -g {hub_rg} --aspects {state.DATAPLANE}"
    )
    assert isinstance(result.get_error(), ResourceNotFoundError)

    result = state.cli.invoke(
        f"iot hub state import -n {hub_name} -f {filename} --aspects {state.DATAPLANE}"
    )
    assert isinstance(result.get_error(), RequiredArgumentMissingError)

    result = state.cli.invoke(
        f"iot hub state migrate --origin-hub {hub_name} --origin-resource-group {hub_rg} "
        f"--destination-hub {hub_name} --destination-resource-group {hub_rg}"
    )
    assert isinstance(result.get_error(), ResourceNotFoundError)


@pytest.mark.hub_infrastructure(count=1)
def test_export_endpoint_resource_name_starting_with_scheme_char(
    provisioned_only_iot_hubs_module, setup_file
):
    """Export must keep a routing endpoint."""
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    hub_rg = provisioned_only_iot_hubs_module[0]["rg"]
    state.delete_system_endpoints(hub_name, hub_rg)

    sb_namespace = ("sb" + generate_generic_id())[:24]
    topic_name = "topic1"
    endpoint_name = generate_generic_id()
    try:
        state.cli.invoke(
            f"servicebus namespace create --name {sb_namespace} -g {hub_rg} --sku Standard --location {HUB_TEST_LOCATION}"
        )
        state.cli.invoke(
            f"servicebus topic create --namespace-name {sb_namespace} -g {hub_rg} --name {topic_name}"
        )
        state.cli.invoke(
            f"servicebus topic authorization-rule create --namespace-name {sb_namespace} -g {hub_rg} "
            f"--topic-name {topic_name} --name iothubroute --rights Send"
        )
        endpoint_cstring = state.cli.invoke(
            f"servicebus topic authorization-rule keys list --namespace-name {sb_namespace} -g {hub_rg} "
            f"--topic-name {topic_name} --name iothubroute"
        ).as_json()["primaryConnectionString"]
        state.cli.invoke(
            f"iot hub message-endpoint create servicebus-topic -n {hub_name} -g {hub_rg} "
            f"--en {endpoint_name} -c '{endpoint_cstring}' --erg {hub_rg}"
        )
        time.sleep(10)  # gives the hub time to update before the export

        state._invoke_state(
            f"iot hub state export -n {hub_name} -f {setup_file} -g {hub_rg} -r --aspects {state.CONTROLPLANE}",
        )
        with open(setup_file, "r", encoding="utf-8") as f:
            hub_info = json.load(f)
        topics = hub_info["arm"]["resources"][0]["properties"]["routing"]["endpoints"]["serviceBusTopics"]
        exported = [ep for ep in topics if ep["name"] == endpoint_name]
        assert len(exported) == 1, "endpoint was dropped from export (namespace likely corrupted)"
        assert sb_namespace in exported[0]["connectionString"]
    finally:
        state.cli.invoke(f"iot hub message-endpoint delete -n {hub_name} -g {hub_rg} --en {endpoint_name} -y")
        state.cli.invoke(f"servicebus namespace delete --name {sb_namespace} -g {hub_rg}")


@pytest.mark.hub_infrastructure(count=1)
# This last item includes shared module teardown; a passing lifecycle exceeded 35 minutes.
@pytest.mark.timeout(45 * 60, func_only=False)
def test_export_cosmosdb_endpoint_resource_name_starting_with_scheme_char(
    provisioned_only_iot_hubs_module, setup_file
):
    """Export must keep a Cosmos DB routing endpoint."""
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    hub_rg = provisioned_only_iot_hubs_module[0]["rg"]
    state.delete_system_endpoints(hub_name, hub_rg)

    cosmos_account = ("scos" + generate_generic_id())[:40]
    database_name = "routedb"
    container_name = "routecontainer"
    endpoint_name = generate_generic_id()
    try:
        state.cli.invoke(
            f"cosmosdb create --name {cosmos_account} -g {hub_rg} "
            f"--locations regionName={HUB_TEST_LOCATION} failoverPriority=0"
        )
        state.cli.invoke(
            f"cosmosdb sql database create --account-name {cosmos_account} -g {hub_rg} --name {database_name}"
        )
        state.cli.invoke(
            f"cosmosdb sql container create --account-name {cosmos_account} -g {hub_rg} "
            f"--database-name {database_name} --name {container_name} -p /deviceid"
        )
        endpoint_cstring = state.cli.invoke(
            f"cosmosdb keys list --name {cosmos_account} -g {hub_rg} --type connection-strings"
        ).as_json()["connectionStrings"][0]["connectionString"]
        state.cli.invoke(
            f"iot hub message-endpoint create cosmosdb-container -n {hub_name} -g {hub_rg} "
            f"--en {endpoint_name} --db {database_name} --container {container_name} "
            f"-c '{endpoint_cstring}' --erg {hub_rg}"
        )
        time.sleep(10)  # gives the hub time to update before the export

        state._invoke_state(
            f"iot hub state export -n {hub_name} -f {setup_file} -g {hub_rg} -r --aspects {state.CONTROLPLANE}",
        )
        with open(setup_file, "r", encoding="utf-8") as f:
            hub_info = json.load(f)
        containers = hub_info["arm"]["resources"][0]["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"]
        exported = [ep for ep in containers if ep["name"] == endpoint_name]
        assert len(exported) == 1, "endpoint was dropped from export (account name likely corrupted)"
        assert cosmos_account in exported[0]["endpointUri"]
    finally:
        state.cli.invoke(f"iot hub message-endpoint delete -n {hub_name} -g {hub_rg} --en {endpoint_name} -y")
        state.cli.invoke(f"cosmosdb delete --name {cosmos_account} -g {hub_rg} -y")
