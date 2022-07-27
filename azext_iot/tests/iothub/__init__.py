# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from time import sleep
from typing import List
from azext_iot.tests.helpers import add_test_tag, assign_rbac_role, create_cosmos_db, create_event_hub, create_managed_identity, create_service_bus_queue, create_service_bus_topic, create_storage_account
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests import CaptureOutputLiveScenarioTest

from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.tests.test_constants import ResourceTypes

DATAPLANE_AUTH_TYPES = [
    AuthenticationTypeDataplane.key.value,
    AuthenticationTypeDataplane.login.value,
    "cstring",
]

PRIMARY_THUMBPRINT = create_self_signed_certificate(
    subject="aziotcli", valid_days=1, cert_output_dir=None
)["thumbprint"]
SECONDARY_THUMBPRINT = create_self_signed_certificate(
    subject="aziotcli", valid_days=1, cert_output_dir=None
)["thumbprint"]

DEVICE_TYPES = ["non-edge", "edge"]
PREFIX_DEVICE = "test-device-"
PREFIX_EDGE_DEVICE = "test-edge-device-"
PREFIX_DEVICE_MODULE = "test-module-"
PREFIX_CONFIG = "test-config-"
PREFIX_EDGE_CONFIG = "test-edgedeploy-"
PREFIX_JOB = "test-job-"
USER_ROLE = "IoT Hub Data Contributor"
DEFAULT_CONTAINER = "devices"

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)
ENTITY_RG = settings.env.azext_iot_testrg
ENTITY_NAME = settings.env.azext_iot_testhub or "test-hub-" + generate_generic_id()
STORAGE_ACCOUNT = settings.env.azext_iot_teststorageaccount or "hubstore" + generate_generic_id()[:4]
STORAGE_CONTAINER = settings.env.azext_iot_teststoragecontainer or DEFAULT_CONTAINER
MAX_RBAC_ASSIGNMENT_TRIES = settings.env.azext_iot_rbac_max_tries or 10
ROLE_ASSIGNMENT_REFRESH_TIME = 120

# Endpoints
EP_RG = settings.env.azext_iot_ep_rg or ENTITY_RG
EP_EVENTHUB_NAMESPACE = settings.env.azext_iot_eventhub_namespace or ("testeh" + generate_generic_id())
EP_EVENTHUB_INSTANCE = settings.env.azext_iot_eventhub_instance or ("testevent" + generate_generic_id())
EP_EVENTHUB_POLICY = settings.env.azext_iot_eventhub_policy or ("testpolicy" + generate_generic_id())
EP_SERVICEBUS_NAMESPACE = settings.env.azext_iot_servicebus_namespace or ("testsb" + generate_generic_id())
EP_SERVICEBUS_QUEUE = settings.env.azext_iot_servicebus_queue or ("testqueue" + generate_generic_id())
EP_SERVICEBUS_TOPIC = settings.env.azext_iot_servicebus_topic or ("testtopic" + generate_generic_id())
EP_SERVICEBUS_POLICY = settings.env.azext_iot_servicebus_policy or ("testpolicy" + generate_generic_id())
EP_COSMOS_NAMESPACE = settings.env.azext_iot_cosmos_namespace or ("testcos" + generate_generic_id())
EP_COSMOS_DATABASE = settings.env.azext_iot_cosmos_database or ("testdb" + generate_generic_id())
EP_COSMOS_COLLECTION = settings.env.azext_iot_cosmos_collection or ("testcol" + generate_generic_id())
EP_COSMOS_PARTITION_PATH = "/test"
USER_IDENTITY = settings.env.azext_iot_user_identity or ("testuser" + generate_generic_id())


class IoTLiveScenarioTest(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario):
        assert test_scenario
        self.entity_rg = ENTITY_RG
        self.entity_name = ENTITY_NAME
        super(IoTLiveScenarioTest, self).__init__(test_scenario)

        if hasattr(self, 'storage_cstring'):
            self._create_storage_account()

        if not settings.env.azext_iot_testhub:
            hubs_list = self.cmd(
                'iot hub list -g "{}"'.format(self.entity_rg)
            ).get_output_in_json()

            target_hub = None
            for hub in hubs_list:
                if hub["name"] == self.entity_name:
                    target_hub = hub
                    break

            if not target_hub:
                if hasattr(self, 'storage_cstring'):
                    self.cmd(
                        "iot hub create --name {} --resource-group {} --fc {} --fcs {} --sku S1 ".format(
                            self.entity_name, self.entity_rg,
                            self.storage_container, self.storage_cstring
                        )
                    )
                else:
                    self.cmd(
                        "iot hub create --name {} --resource-group {} --sku S1 ".format(
                            self.entity_name, self.entity_rg
                        )
                    )
                sleep(ROLE_ASSIGNMENT_REFRESH_TIME)

                target_hub = self.cmd(
                    "iot hub show -n {} -g {}".format(self.entity_name, self.entity_rg)
                ).get_output_in_json()

                account = self.cmd("account show").get_output_in_json()
                user = account["user"]

                if user["name"] is None:
                    raise Exception("User not found")

                tries = 0
                while tries < MAX_RBAC_ASSIGNMENT_TRIES:
                    role_assignments = self.get_role_assignments(target_hub["id"], USER_ROLE)
                    role_assignment_principal_names = [assignment["principalName"] for assignment in role_assignments]
                    if user["name"] in role_assignment_principal_names:
                        break
                    # else assign IoT Hub Data Contributor role to current user and check again
                    self.cmd(
                        'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                            user["name"], USER_ROLE, target_hub["id"]
                        )
                    )
                    sleep(10)

                if tries == MAX_RBAC_ASSIGNMENT_TRIES:
                    raise Exception(
                        "Reached max ({}) number of tries to assign RBAC role. Please re-run the test later "
                        "or with more max number of tries.".format(MAX_RBAC_ASSIGNMENT_TRIES)
                    )

        self.region = self.get_region()
        self.connection_string = self.get_hub_cstring()
        add_test_tag(
            cmd=self.cmd,
            name=self.entity_name,
            rg=self.entity_rg,
            rtype=ResourceTypes.hub.value,
            test_tag=test_scenario
        )

    def clean_up(self, device_ids: List[str] = None, config_ids: List[str] = None):
        if device_ids:
            device = device_ids.pop()
            self.cmd(
                "iot hub device-identity delete -d {} --login {}".format(
                    device, self.connection_string
                ),
                checks=self.is_empty(),
            )

            for device in device_ids:
                self.cmd(
                    "iot hub device-identity delete -d {} -n {} -g {}".format(
                        device, self.entity_name, self.entity_rg
                    ),
                    checks=self.is_empty(),
                )

        if config_ids:
            config = config_ids.pop()
            self.cmd(
                "iot hub configuration delete -c {} --login {}".format(
                    config, self.connection_string
                ),
                checks=self.is_empty(),
            )

            for config in config_ids:
                self.cmd(
                    "iot hub configuration delete -c {} -n {} -g {}".format(
                        config, self.entity_name, self.entity_rg
                    ),
                    checks=self.is_empty(),
                )

    def generate_device_names(self, count=1, edge=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_DEVICE if not edge else PREFIX_EDGE_DEVICE, length=32
            )
            for i in range(count)
        ]
        return names

    def generate_module_names(self, count=1):
        return [
            self.create_random_name(prefix=PREFIX_DEVICE_MODULE, length=32)
            for i in range(count)
        ]

    def generate_config_names(self, count=1, edge=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_CONFIG if not edge else PREFIX_EDGE_CONFIG, length=32
            )
            for i in range(count)
        ]
        return names

    def generate_job_names(self, count=1):
        return [
            self.create_random_name(prefix=PREFIX_JOB, length=32) for i in range(count)
        ]

    def _create_storage_account(self):
        """
        Create a storage account and container if a storage account was not created yet.
        Populate the following variables if needed:
          - storage_account_name
          - storage_container
          - storage_cstring
        """
        self.storage_account_name = STORAGE_ACCOUNT
        self.storage_container = STORAGE_CONTAINER

        self.storage_cstring = create_storage_account(
            cmd=self.cmd,
            account_name=self.storage_account_name,
            container_name=self.storage_container,
            rg=self.entity_rg,
            resource_name=self.entity_name,
            create_account=(not settings.env.azext_iot_teststorageaccount)
        )

    def _assign_storage_account_roles(self):
        scope = ""
        assign_rbac_role(
            cmd=self.cmd,
            assignee=self.entity_identity,
            scope=scope, #eventhub id
            role="Storage Blob Data Contributor",
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES
        )

        if hasattr(self, "user_identity_principal_id"):
            assign_rbac_role(
                cmd=self.cmd,
                assignee=self.user_identity_principal_id,
                scope=scope, #eventhub id
                role="Storage Blob Data Contributor",
                max_tries=MAX_RBAC_ASSIGNMENT_TRIES
            )


    def _delete_storage_account(self):
        """
        Delete the storage account if it was created.
        """
        if not settings.env.azext_iot_teststorageaccount:
            self.cmd(
                "storage account delete -n {} -g {} -y".format(
                    STORAGE_ACCOUNT, self.entity_rg
                ),
            )

        elif not settings.env.azext_iot_teststoragecontainer:
            self.cmd(
                "storage container delete -n {} --connection-string '{}'".format(
                    STORAGE_ACCOUNT, self.storage_cstring
                ),
            )

    def _create_cosmos_db(self):
        cosmos_cs = create_cosmos_db(
            cmd=self.cmd,
            account_name=EP_COSMOS_NAMESPACE,
            database_name=EP_COSMOS_DATABASE,
            collection_name=EP_COSMOS_COLLECTION,
            partition_key_path=EP_COSMOS_PARTITION_PATH,
            rg=EP_RG,
            resource_name=ENTITY_NAME,
            create_account=(not settings.env.azext_iot_cosmos_namespace),
            create_database=(not settings.env.azext_iot_cosmos_database),
            create_collection=(not settings.env.azext_iot_cosmos_collection)
        )

        scope = "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.EventHub/namespaces/{}/eventhubs/{}".format(
            self.entity_sub,
            EP_RG,
            EP_EVENTHUB_NAMESPACE,
            EP_EVENTHUB_INSTANCE
        )

        assign_rbac_role(
            cmd=self.cmd,
            assignee=self.entity_identity,
            scope=scope, #eventhub id
            role="Azure Event Hubs Data Sender",
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES
        )

        if hasattr(self, "user_identity_principal_id"):
            assign_rbac_role(
                cmd=self.cmd,
                assignee=self.user_identity_principal_id,
                scope=scope, #eventhub id
                role="Azure Event Hubs Data Sender",
                max_tries=MAX_RBAC_ASSIGNMENT_TRIES
            )

        return cosmos_cs

    def _delete_cosmos_db(self):
        """
        Delete the cosmos db account if it was created.
        """
        if not settings.env.azext_iot_cosmos_namespace:
            self.cmd(
                'cosmosdb delete --resource-group {} --name {} -y'.format(
                    EP_RG, EP_COSMOS_NAMESPACE
                )
            )
        elif not settings.env.azext_iot_cosmos_database:
            self.cmd(
                'cosmosdb sql database delete --resource-group {} --account-name {} --name {} -y'.format(
                    EP_RG, EP_COSMOS_NAMESPACE, EP_COSMOS_DATABASE
                )
            )
        elif not settings.env.azext_iot_cosmos_collection:
            self.cmd(
                'cosmosdb sql collection delete --resource-group {} --account-name {} --database-name {} --name {} -y'.format(
                    EP_RG, EP_COSMOS_NAMESPACE, EP_COSMOS_DATABASE, EP_COSMOS_COLLECTION
                )
            )

    def _create_eventhub(self):
        eventhub_cs = create_event_hub(
            cmd=self.cmd,
            namespace_name=EP_EVENTHUB_NAMESPACE,
            eventhub_name=EP_EVENTHUB_INSTANCE,
            policy_name=EP_EVENTHUB_POLICY,
            rg=EP_RG,
            resource_name=ENTITY_NAME,
            create_namespace=(not settings.env.azext_iot_eventhub_namespace),
            create_eventhub=(not settings.env.azext_iot_eventhub_instance),
            create_policy=(not settings.env.azext_iot_eventhub_policy)
        )

        scope = "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.EventHub/namespaces/{}/eventhubs/{}".format(
            self.entity_sub,
            EP_RG,
            EP_EVENTHUB_NAMESPACE,
            EP_EVENTHUB_INSTANCE
        )

        assign_rbac_role(
            cmd=self.cmd,
            assignee=self.entity_identity,
            scope=scope, #eventhub id
            role="Azure Event Hubs Data Sender",
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES
        )

        if hasattr(self, "user_identity_principal_id"):
            print("user identity")
            assign_rbac_role(
                cmd=self.cmd,
                assignee=self.user_identity_principal_id,
                scope=scope, #eventhub id
                role="Azure Event Hubs Data Sender",
                max_tries=MAX_RBAC_ASSIGNMENT_TRIES
            )

        return eventhub_cs

    def _delete_eventhub(self):
        """
        Delete the eventhub if it was created.
        """
        if not settings.env.azext_iot_cosmos_namespace:
            self.cmd(
                'eventhubs namespace delete --resource-group {} --name {}'.format(
                    EP_RG, EP_EVENTHUB_NAMESPACE
                )
            )
        elif not settings.env.azext_iot_eventhub_instance:
            self.cmd(
                'eventhubs eventhub delete --resource-group {} --namespace-name {} --name {}'.format(
                    EP_RG, EP_EVENTHUB_NAMESPACE, EP_EVENTHUB_INSTANCE
                )
            )
        elif not settings.env.azext_iot_eventhub_policy:
            self.cmd(
                'eventhubs eventhub authorization-rule delete --resource-group {} --namespace-name {} --eventhub-name {} --name {}'.format(
                    EP_RG, EP_EVENTHUB_NAMESPACE, EP_EVENTHUB_INSTANCE, EP_EVENTHUB_POLICY
                )
            )

    def _create_service_bus_topic_queue(self):
        role = "Azure Service Bus Data Sender"
        topic_cs = create_service_bus_topic(
            cmd=self.cmd,
            namespace_name=EP_SERVICEBUS_NAMESPACE,
            topic_name=EP_SERVICEBUS_TOPIC,
            policy_name=EP_SERVICEBUS_POLICY,
            rg=EP_RG,
            resource_name=ENTITY_NAME,
            create_namespace=(not settings.env.azext_iot_servicebus_namespace),
            create_topic=(not settings.env.azext_iot_servicebus_topic),
            create_policy=(not settings.env.azext_iot_servicebus_policy)
        )

        scope = "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.ServiceBus/namespaces/{}/topics/{}".format(
            self.entity_sub,
            EP_RG,
            EP_SERVICEBUS_NAMESPACE,
            EP_SERVICEBUS_TOPIC
        )

        assign_rbac_role(
            cmd=self.cmd,
            assignee=self.entity_identity,
            scope=scope, #eventhub id
            role=role,
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES
        )

        if hasattr(self, "user_identity_principal_id"):
            assign_rbac_role(
                cmd=self.cmd,
                assignee=self.user_identity_principal_id,
                scope=scope, #eventhub id
                role=role,
                max_tries=MAX_RBAC_ASSIGNMENT_TRIES
            )

        queue_cs = create_service_bus_queue(
            cmd=self.cmd,
            namespace_name=EP_SERVICEBUS_NAMESPACE,
            queue_name=EP_SERVICEBUS_QUEUE,
            policy_name=EP_SERVICEBUS_POLICY,
            rg=EP_RG,
            resource_name=ENTITY_NAME,
            create_namespace=False,
            create_queue=(not settings.env.azext_iot_servicebus_queue),
            create_policy=(not settings.env.azext_iot_servicebus_policy)
        )

        scope = "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.ServiceBus/namespaces/{}/queues/{}".format(
            self.entity_sub,
            EP_RG,
            EP_SERVICEBUS_NAMESPACE,
            EP_SERVICEBUS_QUEUE
        )

        assign_rbac_role(
            cmd=self.cmd,
            assignee=self.entity_identity,
            scope=scope, #queue id
            role=role,
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES
        )

        if hasattr(self, "user_identity_principal_id"):
            assign_rbac_role(
                cmd=self.cmd,
                assignee=self.user_identity_principal_id,
                scope=scope, #queue id
                role=role,
                max_tries=MAX_RBAC_ASSIGNMENT_TRIES
            )

        return topic_cs, queue_cs

    def _delete_service_bus_topic_queue(self):
        """
        Delete the service bus topic and queue if it was created.
        """
        if not settings.env.azext_iot_servicebus_namespace:
            self.cmd(
                'servicebus namespace delete --resource-group {} --name {}'.format(
                    EP_RG, EP_SERVICEBUS_NAMESPACE
                )
            )
        else:
            if not settings.env.azext_iot_servicebus_topic:
                self.cmd(
                    'servicebus topic delete --resource-group {} --namespace-name {} --name {}'.format(
                        EP_RG, EP_SERVICEBUS_NAMESPACE, EP_SERVICEBUS_TOPIC
                    )
                )
            elif not settings.env.azext_iot_servicebus_policy:
                self.cmd(
                    'servicebus topic authorization-rule delete --resource-group {} --namespace-name {} --topic-name {} --name {}'.format(
                        EP_RG, EP_SERVICEBUS_NAMESPACE, EP_SERVICEBUS_TOPIC, EP_SERVICEBUS_POLICY
                    )
                )

            if not settings.env.azext_iot_servicebus_queue:
                self.cmd(
                    'servicebus queue delete --resource-group {} --namespace-name {} --name {}'.format(
                        EP_RG, EP_SERVICEBUS_NAMESPACE, EP_SERVICEBUS_QUEUE
                    )
                )
            elif not settings.env.azext_iot_servicebus_policy:
                self.cmd(
                    'servicebus queue authorization-rule delete --resource-group {} --namespace-name {} --queue-name {} --name {}'.format(
                        EP_RG, EP_SERVICEBUS_NAMESPACE, EP_SERVICEBUS_QUEUE, EP_SERVICEBUS_POLICY
                    )
                )

    def _create_user_identity(self):
        """Set self.user_identity_id"""
        if hasattr(self, "user_identity_id"):
            return

        identities = self.cmd(f"identity list -g {EP_RG}").get_output_in_json()

        target_identity = None
        for identity in identities:
            if identity["name"].lower() == USER_IDENTITY.lower():
                target_identity = identity

        if not target_identity:
            target_identity = create_managed_identity(cmd=self.cmd, name=USER_IDENTITY, rg=EP_RG)

        self.user_identity_id = target_identity["id"]
        self.user_identity_principal_id = target_identity["principalId"]
        self.cmd(
            "iot hub identity assign -n {} -g {} --user {}".format(
                self.entity_name, self.entity_rg, self.user_identity_id
            )
        )

    def _delete_user_identity(self):
        if settings.env.azext_iot_user_identity:
            self.cmd(
                f"identity delete -n {USER_IDENTITY} -g {EP_RG}"
            )

    def enable_hub_system_identity(self):
        """Set self.entity_identity"""
        if hasattr(self, "entity_identity"):
            return

        identity = self.cmd(
            "iot hub show -n {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()["identity"]

        if identity.get("principalId"):
            self.entity_identity = identity.get("principalId")

        # Need to enable
        self.entity_identity = self.cmd(
            "iot hub identity assign -n {} -g {} --system".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()["principalId"]


    def tearDown(self):
        device_list = []
        device_list.extend(d["deviceId"] for d in self.cmd(
            f"iot hub device-identity list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json())

        config_list = []
        config_list.extend(c["id"] for c in self.cmd(
            f"iot edge deployment list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json())

        config_list.extend(c["id"] for c in self.cmd(
            f"iot hub configuration list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json())

        self.clean_up(device_ids=device_list, config_ids=config_list)

    def get_region(self):
        result = self.cmd(
            "iot hub show -n {}".format(self.entity_name)
        ).get_output_in_json()
        locations_set = result["properties"]["locations"]
        for loc in locations_set:
            if loc["role"] == "primary":
                return loc["location"]

    def get_hub_sub(self):
        return self.cmd(
            "iot hub show -n {} -g {}".format(self.entity_name, self.entity_rg)
        ).get_output_in_json()["subscriptionid"]

    def get_hub_cstring(self, policy="iothubowner"):
        return self.cmd(
            "iot hub connection-string show -n {} -g {} --policy-name {}".format(
                self.entity_name, self.entity_rg, policy
            )
        ).get_output_in_json()["connectionString"]

    def set_cmd_auth_type(self, command: str, auth_type: str) -> str:
        if auth_type not in DATAPLANE_AUTH_TYPES:
            raise RuntimeError(f"auth_type of: {auth_type} is unsupported.")

        # cstring takes precedence
        if auth_type == "cstring":
            return f"{command} --login {self.connection_string}"

        return f"{command} --auth-type {auth_type}"

    def get_role_assignments(self, scope, role):
        role_assignments = self.cmd(
            'role assignment list --scope "{}" --role "{}"'.format(
                scope, role
            )
        ).get_output_in_json()

        return role_assignments

    @pytest.fixture(scope='class', autouse=True)
    def tearDownSuite(self):
        yield None
        print("tearDownSuite")
        if not settings.env.azext_iot_testhub:
            self.cmd(
                "iot hub delete --name {} --resource-group {}".format(
                    ENTITY_NAME, ENTITY_RG
                )
            )
        if hasattr(self, "storage_cstring"):
            self._delete_storage_account()
