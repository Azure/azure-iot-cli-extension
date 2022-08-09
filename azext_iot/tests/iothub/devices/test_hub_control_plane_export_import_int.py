import random
import pytest
import json
import os
import time
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL
from azure.cli.command_modules.iot.tests.latest._test_utils import _create_test_cert, _delete_test_cert
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.test_constants import ResourceTypes
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.helpers import add_test_tag
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)
CWD = os.path.dirname(os.path.abspath(__file__))

CERT_FILE = "test_cert.cer"
KEY_FILE = "test_key.cer"
DATAPLANE_AUTH_TYPES.remove("cstring")


class TestHubControlPlaneExportImport(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestHubControlPlaneExportImport, self).__init__(test_case)
        self.dest_hub = settings.env.azext_iot_desthub or "test-hub-" + generate_generic_id()
        self.dest_hub_rg = settings.env.azext_iot_destrg or settings.env.azext_iot_testrg
        self.cli = EmbeddedCLI()

        hub_id = self.cli.invoke(f"iot hub show -n {self.entity_name} -g {self.entity_rg}").as_json()["id"]
        self.subscription_id = hub_id.split("/")[2]

        # create destination hub

        if not settings.env.azext_iot_desthub:
            self.create_hub(self.dest_hub, self.dest_hub_rg)

        add_test_tag(
            cmd=self.cmd,
            name=self.dest_hub,
            rg=self.dest_hub_rg,
            rtype=ResourceTypes.hub.value,
            test_tag=test_case
        )

        self.dest_hub_cstring = self.cmd(
            f"iot hub connection-string show -n {self.dest_hub} -g {self.dest_hub_rg}"
        ).get_output_in_json()["connectionString"]

        self.filename = generate_generic_id() + ".json"

    @pytest.fixture(scope="class", autouse=True)
    def setup_class(self):

        self.clean_up_hub(self.entity_name, self.entity_rg)

        # add identities
        self.uid = "/subscriptions/a386d5ea-ea90-441a-8263-d816368c84a1/resourcegroups/mirabai/providers/" + \
            "Microsoft.ManagedIdentity/userAssignedIdentities/mirabaiidentity"
        self.cli.invoke("iot hub identity assign -n {} -g {} --system-assigned".format(self.entity_name, self.entity_rg))
        self.cli.invoke("iot hub identity assign -n {} -g {} --user-assigned {}".format(self.entity_name, self.entity_rg,
                                                                                        self.uid))

        rg = "mirabai"
        eventhub_endpointuri = "sb://mirabaieventhub.servicebus.windows.net"
        servicebus_endpointuri = "sb://mirabaiservicebus.servicebus.windows.net"
        eventhub_entity_path = "eventhub1"
        queue_entity_path = "queue1"
        topic_entity_path = "topic1"
        storage_account = "mirabaistorage"

        # add a certificate

        _create_test_cert(CERT_FILE, KEY_FILE, "testcert", 3, random.randint(1, 10))

        self.cli.invoke(
            "iot hub certificate create --hub-name {} --name cert1 --path {} -g {} -v True".format(self.entity_name, CERT_FILE,
                                                                                                   self.entity_rg)
        )

        # add endpoints

        storage_cstring = self.cli.invoke(
            f"storage account show-connection-string --name {storage_account} -g {rg}"
        ).as_json()["connectionString"]

        self.cli.invoke(f"iot hub routing-endpoint create -n eventhub-systemid -r {rg} -g {self.entity_rg} -s "
                        f"{self.subscription_id} -t eventhub --hub-name {self.entity_name} --endpoint-uri {eventhub_endpointuri}"
                        f" --entity-path {eventhub_entity_path} --auth-type identityBased")

        self.cli.invoke(f"iot hub routing-endpoint create -n queue-systemid -r {rg} -g {self.entity_rg} -s "
                        f"{self.subscription_id} -t servicebusqueue --hub-name {self.entity_name} --endpoint-uri "
                        f"{servicebus_endpointuri} --entity-path {queue_entity_path} --auth-type identityBased")

        self.cli.invoke(f"iot hub routing-endpoint create -n topic-userid -r {rg} -g {self.entity_rg} -s "
                        f"{self.subscription_id} -t servicebustopic --hub-name {self.entity_name} --endpoint-uri "
                        f"{servicebus_endpointuri} --entity-path {topic_entity_path} --auth-type identityBased --identity "
                        f"{self.uid}")

        self.cli.invoke(f"iot hub routing-endpoint create -n storagecontainer-key -r {rg} -g {self.entity_rg} -s "
                        f"{self.subscription_id} -t azurestoragecontainer --hub-name {self.entity_name} -c {storage_cstring} "
                        f"--container container1  -b 350 -w 250 --encoding json")

        # add routes

        self.cli.invoke(f"iot hub route create --endpoint eventhub-systemid --hub-name {self.entity_name} -g {self.entity_rg}"
                        f" --name route1 --source devicelifecycleevents --condition false --enabled true")
        self.cli.invoke(f"iot hub route create --endpoint storagecontainer-key --hub-name {self.entity_name} -g {self.entity_rg}"
                        f" --name route2 --source twinchangeevents --condition true --enabled false")

    @pytest.fixture(scope="class", autouse=True)
    def teardown_module(self):
        yield

        if os.path.isfile(self.filename):
            os.remove(self.filename)

        _delete_test_cert(CERT_FILE, KEY_FILE, KEY_FILE)

        if settings.env.azext_iot_testhub:
            self.clean_up_hub(self.entity_name, self.entity_rg)

        # tears down destination hub
        if not settings.env.azext_iot_desthub:
            self.cmd("iot hub delete -n {} -g {}".format(self.dest_hub, self.dest_hub_rg))
        else:
            self.clean_up_hub(self.dest_hub, self.dest_hub_rg)

    def clean_up_hub(self, hub_name, rg):

        routes = self.cli.invoke(f"iot hub route list --hub-name {hub_name} -g {rg}").as_json()
        for route in routes:
            self.cli.invoke(f"iot hub route delete --hub-name {hub_name} -g {rg} --name {route['name']}")

        certificates = self.cli.invoke("iot hub certificate list --hub-name {} -g {}".format(hub_name, rg)).as_json()
        for c in certificates["value"]:
            self.cli.invoke("iot hub certificate delete --name {} --etag {} --hub-name {} -g {}".format(c["name"], c["etag"],
                                                                                                        hub_name, rg))

        endpoints = self.cli.invoke(f"iot hub routing-endpoint list --hub-name {hub_name} -g {rg}").as_json()
        eventHubs = endpoints["eventHubs"]
        serviceBusQueues = endpoints["serviceBusQueues"]
        serviceBusTopics = endpoints["serviceBusTopics"]
        storageContainers = endpoints["storageContainers"]
        for ep in eventHubs:
            self.cli.invoke("iot hub routing-endpoint delete --hub-name {} -g {} --endpoint-name {} --endpoint-type \
                eventhub".format(hub_name, rg, ep["name"]))
        for ep in serviceBusQueues:
            self.cli.invoke("iot hub routing-endpoint delete --hub-name {} -g {} --endpoint-name {} --endpoint-type \
                servicebusqueue".format(hub_name, rg, ep["name"]))
        for ep in serviceBusTopics:
            self.cli.invoke("iot hub routing-endpoint delete --hub-name {} -g {} --endpoint-name {} --endpoint-type \
                servicebustopic".format(hub_name, rg, ep["name"]))
        for ep in storageContainers:
            self.cli.invoke("iot hub routing-endpoint delete --hub-name {} -g {} --endpoint-name {} --endpoint-type \
                azurestoragecontainer".format(hub_name, rg, ep["name"]))

    def compare_certs(self, cert1, cert2):
        assert cert1["name"] == cert2["name"]
        assert cert1["properties"]["certificate"] == cert2["properties"]["certificate"]
        assert cert1["properties"]["isVerified"] == cert2["properties"]["isVerified"]

    def compare_endpoints(self, endpoints1, endpoints2, endpoint_type):
        for endpoint in endpoints1:
            target = None
            for ep in endpoints2:
                if endpoint["name"] == ep["name"]:
                    target = ep
                    break

            assert target
            assert endpoint["authenticationType"] == target["authenticationType"]
            assert endpoint["identity"] == target["identity"]
            assert endpoint["resourceGroup"] == target["resourceGroup"]
            assert endpoint["subscriptionId"] == target["subscriptionId"]
            assert endpoint["connectionString"] == target["connectionString"]
            if "entityPath" in endpoint:
                assert endpoint["entityPath"] == target["entityPath"]

            if endpoint_type == "storageContainers":
                assert endpoint["maxChunkSizeInBytes"] == target["maxChunkSizeInBytes"]
                assert endpoint["batchFrequencyInSeconds"] == target["batchFrequencyInSeconds"]
                assert endpoint["containerName"] == target["containerName"]
                assert endpoint["encoding"] == target["encoding"]
                assert endpoint["fileNameFormat"] == target["fileNameFormat"]

    def compare_routes(self, routes1, routes2):
        assert len(routes1) == len(routes2)

        for route in routes1:
            target = None
            for r in routes2:
                if route["name"] == r["name"]:
                    target = r
                    break

            assert target
            assert route["condition"] == target["condition"]
            assert route["endpointNames"] == target["endpointNames"]
            assert route["isEnabled"] == target["isEnabled"]
            assert route["source"] == target["source"]

    def compare_hub_to_file(self):
        with open(self.filename, 'r', encoding='utf-8') as f:
            hub_info = json.load(f)

        # compare certificates

        file_certs = hub_info["certificates"]
        hub_certs = self.cli.invoke(
            "iot hub certificate list --hub-name {} -g {}".format(self.entity_name, self.entity_rg)
        ).as_json()["value"]
        assert (len(file_certs) == len(hub_certs) == 1)
        for i in range(len(file_certs)):
            self.compare_certs(file_certs[i], hub_certs[i])

        # compare endpoints

        file_endpoints = hub_info["endpoints"]
        hub_endpoints = self.cli.invoke(
            f"iot hub routing-endpoint list --hub-name {self.entity_name} -g {self.entity_rg}"
        ).as_json()
        for ep_type in ["eventHubs", "serviceBusQueues", "serviceBusTopics", "storageContainers"]:
            assert len(file_endpoints[ep_type]) == len(hub_endpoints[ep_type])
            self.compare_endpoints(file_endpoints[ep_type], hub_endpoints[ep_type], ep_type)

        # compare routes

        file_routes = hub_info["routes"]
        hub_routes = self.cli.invoke(f"iot hub route list --hub-name {self.entity_name} -g {self.entity_rg}").as_json()
        self.compare_routes(file_routes, hub_routes)

    def compare_hubs(self):

        # compare certificates

        orig_hub_certs = self.cli.invoke(
            "iot hub certificate list --hub-name {} -g {}".format(self.entity_name, self.entity_rg)
        ).as_json()["value"]
        dest_hub_certs = self.cli.invoke(
            "iot hub certificate list --hub-name {} -g {}".format(self.dest_hub, self.dest_hub_rg)
        ).as_json()["value"]
        assert (len(orig_hub_certs) == len(dest_hub_certs))
        for i in range(len(orig_hub_certs)):
            self.compare_certs(orig_hub_certs[i], dest_hub_certs[i])

        # compare endpoints

        orig_hub_endpoints = self.cli.invoke(
            f"iot hub routing-endpoint list --hub-name {self.entity_name} -g {self.entity_rg}"
        ).as_json()
        dest_hub_endpoints = self.cli.invoke(
            f"iot hub routing-endpoint list --hub-name {self.dest_hub} -g {self.dest_hub_rg}"
        ).as_json()
        for ep_type in ["eventHubs", "serviceBusQueues", "serviceBusTopics", "storageContainers"]:
            assert len(orig_hub_endpoints[ep_type]) == len(dest_hub_endpoints[ep_type])
            self.compare_endpoints(orig_hub_endpoints[ep_type], dest_hub_endpoints[ep_type], ep_type)

        # compare routes

        orig_hub_routes = self.cli.invoke(f"iot hub route list --hub-name {self.entity_name} -g {self.entity_rg}").as_json()
        dest_hub_routes = self.cli.invoke(f"iot hub route list --hub-name {self.dest_hub} -g {self.dest_hub_rg}").as_json()
        self.compare_routes(orig_hub_routes, dest_hub_routes)

    def test_export_import(self):

        # DATAPLANE_AUTH_TYPES = ["key"] # FOR TESTING PURPOSES ONLY

        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub state export -n {self.entity_name} -f {self.filename} -g {self.entity_rg} --force",
                    auth_type=auth_phase
                )
            )
            time.sleep(1)
            self.compare_hub_to_file()

        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.clean_up_hub(self.entity_name, self.entity_rg)
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub state import -n {self.entity_name} -f {self.filename} -g {self.entity_rg} -r",
                    auth_type=auth_phase
                )
            )
            time.sleep(1)  # gives the hub time to update before the checks
            self.compare_hub_to_file()

    def test_migrate(self):

        # DATAPLANE_AUTH_TYPES = ["key"] # FOR TESTING PURPOSES ONLY

        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub state migrate --origin-hub {self.entity_name} --origin-resource-group {self.entity_rg} "
                    f"--destination-hub {self.dest_hub} --destination-resource-group {self.dest_hub_rg} -r",
                    auth_type=auth_phase
                )
            )

            time.sleep(1)  # gives the hub time to update before the checks
            self.compare_hubs()
            self.clean_up_hub(self.dest_hub, self.dest_hub_rg)
