import pytest
import json
import os
import time
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.test_constants import ResourceTypes
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.helpers import add_test_tag

resource_test_env_vars = [
    "azext_iot_testhub",
    "azext_iot_desthub",
    "azext_iot_destrg",
    "azext_dt_ep_rg",
    "azext_dt_ep_eventhub_namespace",
    "azext_dt_ep_eventhub_topic",
    "azext_dt_ep_servicebus_namespace",
    "azext_dt_ep_servicebus_topic",
    "azext_dt_ep_servicebus_queue",
    "azext_iot_teststorageaccount",
    "azext_iot_teststoragecontainer"
]

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=resource_test_env_vars)
CWD = os.path.dirname(os.path.abspath(__file__))

DATAPLANE_AUTH_TYPES = [AuthenticationTypeDataplane.key.value, AuthenticationTypeDataplane.login.value]

EP_RG = settings.env.azext_dt_ep_rg or settings.env.azext_iot_testrg
EVENTHUB_NAMESPACE = settings.env.azext_dt_ep_eventhub_namespace or "testEHnamespace" + generate_generic_id()
EVENTHUB = settings.env.azext_dt_ep_eventhub_topic or "testeventhub" + generate_generic_id()
STORAGE_ACCOUNT = settings.env.azext_iot_teststorageaccount or "teststorage" + generate_generic_id()[:13]
STORAGE_CONTAINER = settings.env.azext_iot_teststoragecontainer or "container" + generate_generic_id()[:13]
SERVICEBUS_NAMESPACE = settings.env.azext_dt_ep_servicebus_namespace or "testServiceBus" + generate_generic_id()
SERVICEBUS_QUEUE = settings.env.azext_dt_ep_servicebus_queue or "queue" + generate_generic_id()
SERVICEBUS_TOPIC = settings.env.azext_dt_ep_servicebus_topic or "topic" + generate_generic_id()
DEST_HUB = settings.env.azext_iot_desthub or "test-hub-" + generate_generic_id()


class TestHubControlPlaneExportImport(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestHubControlPlaneExportImport, self).__init__(test_case)

        self.dest_hub = DEST_HUB
        self.dest_hub_rg = settings.env.azext_iot_destrg or settings.env.azext_iot_testrg
        self.cli = EmbeddedCLI()

        self.hub_id = self.cli.invoke(f"iot hub show -n {self.entity_name} -g {self.entity_rg}").as_json()["id"]
        self.subscription_id = self.hub_id.split("/")[2]

        self.filename = generate_generic_id() + ".json"
        self.test_case = test_case

    @pytest.fixture(scope="class", autouse=True)
    def setup_class(self):

        # create destination hub

        if not settings.env.azext_iot_desthub:
            self.create_hub(self.dest_hub, self.dest_hub_rg)

        add_test_tag(
            cmd=self.cmd,
            name=self.dest_hub,
            rg=self.dest_hub_rg,
            rtype=ResourceTypes.hub.value,
            test_tag=self.test_case
        )

        self.dest_hub_cstring = self.cmd(
            f"iot hub connection-string show -n {self.dest_hub} -g {self.dest_hub_rg}"
        ).get_output_in_json()["connectionString"]

        self.clean_up_hub(self.entity_name, self.entity_rg)

        # create identity
        self.identity_name = "userAssignedId" + generate_generic_id()
        self.uid = self.cli.invoke(f"identity create -n {self.identity_name} -g {self.entity_rg}").as_json()["id"]

        # assign identities
        self.cli.invoke("iot hub identity assign -n {} -g {} --system-assigned".format(self.entity_name, self.entity_rg))
        self.cli.invoke("iot hub identity assign -n {} -g {} --user-assigned {}".format(self.entity_name, self.entity_rg,
                                                                                        self.uid))

        # assign system identity to destination hub too, so we can assign it roles later
        self.cli.invoke("iot hub identity assign -n {} -g {} --system-assigned".format(self.dest_hub, self.dest_hub_rg))

        if not settings.env.azext_dt_ep_eventhub_namespace:
            self.cli.invoke(
                f"eventhubs namespace create --name {EVENTHUB_NAMESPACE} -g {EP_RG} --mi-system-assigned True"
            )

            self.cli.invoke(
                f"eventhubs eventhub create -n {EVENTHUB} --namespace-name {EVENTHUB_NAMESPACE} -g {EP_RG}"
            )

        if not settings.env.azext_iot_teststorageaccount:
            self.cli.invoke(f"storage account create --name {STORAGE_ACCOUNT} -g {EP_RG}")
            self.cli.invoke(f"storage container create -n {STORAGE_CONTAINER} -g {EP_RG} --account-name {STORAGE_ACCOUNT}")

        if not settings.env.azext_dt_ep_servicebus_namespace:
            self.cli.invoke(
                f"servicebus namespace create -n {SERVICEBUS_NAMESPACE} -g {self.entity_rg}"
            )

            self.cli.invoke(
                f"servicebus queue create -n {SERVICEBUS_QUEUE} --namespace-name {SERVICEBUS_NAMESPACE} -g {self.entity_rg}"
            )

            self.cli.invoke(
                f"servicebus topic create -n {SERVICEBUS_TOPIC} --namespace-name {SERVICEBUS_NAMESPACE} -g {self.entity_rg}"
            )

        # add a certificate

        cert = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["certificate"]
        cert_file = "testCert" + generate_generic_id() + ".cer"
        with open(cert_file, 'w', encoding='utf-8') as f:
            f.write(cert)

        self.cli.invoke(
            "iot hub certificate create --hub-name {} --name cert1 --path {} -g {} -v True".format(self.entity_name, cert_file,
                                                                                                   self.entity_rg)
        )

        if os.path.isfile(cert_file):
            os.remove(cert_file)

        # add endpoints

        username = self.cli.invoke("account show").as_json()["user"]["name"]
        orig_ids = self.cli.invoke(
            f"iot hub show -n {self.entity_name} -g {self.entity_rg}"
        ).as_json()["identity"]
        dest_ids = self.cli.invoke(
            f"iot hub show -n {self.dest_hub} -g {self.dest_hub_rg}"
        ).as_json()["identity"]
        orig_principal_id = orig_ids["principalId"]
        dest_principal_id = dest_ids["principalId"]
        user_id = orig_ids["userAssignedIdentities"][self.uid]["principalId"]

        eh = self.cli.invoke(f"eventhubs namespace show -n {EVENTHUB_NAMESPACE} -g {EP_RG}").as_json()
        servicebus_info = self.cli.invoke(f"servicebus namespace show -n {SERVICEBUS_NAMESPACE} -g {EP_RG}").as_json()
        queue = self.cli.invoke(
            f"servicebus queue show -n {SERVICEBUS_QUEUE} --namespace-name {SERVICEBUS_NAMESPACE} -g {EP_RG}"
        ).as_json()
        topic = self.cli.invoke(
            f"servicebus topic show -n {SERVICEBUS_TOPIC} --namespace-name {SERVICEBUS_NAMESPACE} -g {EP_RG}"
        ).as_json()

        # put endpoint uri in correct format
        eventhub_endpointuri = eh["serviceBusEndpoint"]
        eventhub_endpointuri = eventhub_endpointuri[:eventhub_endpointuri.find(".net") + 4]
        if eventhub_endpointuri[:5] == "https":
            eventhub_endpointuri = "sb" + eventhub_endpointuri[5:]

        # put servicebus uri in correct format
        servicebus_endpointuri = servicebus_info["serviceBusEndpoint"]
        servicebus_endpointuri = servicebus_endpointuri[:servicebus_endpointuri.find(".net") + 4]
        if servicebus_endpointuri[:5] == "https":
            servicebus_endpointuri = "sb" + servicebus_endpointuri[5:]

        self.cli.invoke(
            f"role assignment create --role 'IoT Hub Data Contributor' --scope {self.hub_id} --assignee {username}"
        )
        self.cli.invoke(
            f"role assignment create --role 'Azure Event Hubs Data Sender' --scope {eh['id']} --assignee {orig_principal_id}"
        )
        self.cli.invoke(
            f"role assignment create --role 'Azure Service Bus Data Sender' --scope {queue['id']} --assignee {orig_principal_id}"
        )
        self.cli.invoke(
            f"role assignment create --role 'Azure Event Hubs Data Sender' --scope {eh['id']} --assignee {dest_principal_id}"
        )
        self.cli.invoke(
            f"role assignment create --role 'Azure Service Bus Data Sender' --scope {queue['id']} --assignee {dest_principal_id}"
        )
        self.cli.invoke(
            f"role assignment create --role 'Azure Service Bus Data Sender' --scope {topic['id']} --assignee {user_id}"
        )

        self.cli.invoke(f"iot hub routing-endpoint create -n eventhub-systemid -r {EP_RG} -g {self.entity_rg} -s "
                        f"{self.subscription_id} -t eventhub --hub-name {self.entity_name} --endpoint-uri {eventhub_endpointuri}"
                        f" --entity-path {EVENTHUB} --auth-type identityBased")

        self.cli.invoke(f"iot hub routing-endpoint create -n queue-systemid -r {EP_RG} -g {self.entity_rg} -s "
                        f"{self.subscription_id} -t servicebusqueue --hub-name {self.entity_name} --endpoint-uri "
                        f"{servicebus_endpointuri} --entity-path {SERVICEBUS_QUEUE} --auth-type identityBased")

        self.cli.invoke(f"iot hub routing-endpoint create -n topic-userid -r {EP_RG} -g {self.entity_rg} -s "
                        f"{self.subscription_id} -t servicebustopic --hub-name {self.entity_name} --endpoint-uri "
                        f"{servicebus_endpointuri} --entity-path {SERVICEBUS_TOPIC} --auth-type identityBased --identity "
                        f"{self.uid}")

        storage_cstring = self.cli.invoke(
            f"storage account show-connection-string --name {STORAGE_ACCOUNT} -g {EP_RG}"
        ).as_json()["connectionString"]
        self.cli.invoke(f"iot hub routing-endpoint create -n storagecontainer-key -r {EP_RG} -g {self.entity_rg} -s "
                        f"{self.subscription_id} -t azurestoragecontainer --hub-name {self.entity_name} -c {storage_cstring} "
                        f"--container {STORAGE_CONTAINER}  -b 350 -w 250 --encoding json")

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

        self.clean_up_hub(self.entity_name, self.entity_rg)
        self.clean_up_hub(self.dest_hub, self.dest_hub_rg)

        if not settings.env.azext_dt_ep_eventhub_namespace:
            self.cli.invoke(f"eventhubs namespace delete -n {EVENTHUB_NAMESPACE} -g {EP_RG}")
        if not settings.env.azext_iot_teststorageaccount:
            self.cli.invoke(f"storage account delete -y -n {STORAGE_ACCOUNT} -g {EP_RG}")
        if not settings.env.azext_dt_ep_servicebus_namespace:
            self.cli.invoke(f"servicebus namespace delete -n {SERVICEBUS_NAMESPACE} -g {self.entity_rg}")
        self.cli.invoke(f"identity delete -n {self.identity_name} -g {self.entity_rg}")

        super().tearDown()

        # tears down destination hub
        if not settings.env.azext_iot_desthub:
            self.cmd("iot hub delete -n {} -g {}".format(self.dest_hub, self.dest_hub_rg))

    def clean_up_hub(self, hub_name, rg):

        routes = self.cli.invoke(f"iot hub route list --hub-name {hub_name} -g {rg}").as_json()
        for route in routes:
            self.cli.invoke(f"iot hub route delete --hub-name {hub_name} -g {rg} --name {route['name']}")

        endpoints = self.cli.invoke(f"iot hub routing-endpoint list --hub-name {hub_name} -g {rg}").as_json()
        eventHubs = endpoints["eventHubs"]
        serviceBusQueues = endpoints["serviceBusQueues"]
        serviceBusTopics = endpoints["serviceBusTopics"]
        storageContainers = endpoints["storageContainers"]
        for ep in eventHubs:
            self.cli.invoke(f"iot hub routing-endpoint delete --hub-name {hub_name} -g {rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type eventhub")
        for ep in serviceBusQueues:
            self.cli.invoke(f"iot hub routing-endpoint delete --hub-name {hub_name} -g {rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type servicebusqueue")
        for ep in serviceBusTopics:
            self.cli.invoke(f"iot hub routing-endpoint delete --hub-name {hub_name} -g {rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type servicebustopic")
        for ep in storageContainers:
            self.cli.invoke(f"iot hub routing-endpoint delete --hub-name {hub_name} -g {rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type azurestoragecontainer")

        certificates = self.cli.invoke("iot hub certificate list --hub-name {} -g {}".format(hub_name, rg)).as_json()
        for c in certificates["value"]:
            self.cli.invoke("iot hub certificate delete --name {} --etag {} --hub-name {} -g {}".format(c["name"], c["etag"],
                                                                                                        hub_name, rg))

        userAssignedIds = self.cli.invoke(f"iot hub identity show -n {hub_name} -g {rg}").as_json()["userAssignedIdentities"]
        if userAssignedIds:
            userAssignedIds = " ".join(userAssignedIds.keys())
            self.cli.invoke(f"iot hub identity remove -n {hub_name} -g {rg} --user-assigned {userAssignedIds}")

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
