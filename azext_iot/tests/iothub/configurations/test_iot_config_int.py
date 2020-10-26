# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import random
import json

from ... import IoTLiveScenarioTest
from ...conftest import get_context_path
from ...settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC
from azext_iot.common.utility import read_file_content

settings = DynamoSettings(ENV_SET_TEST_IOTHUB_BASIC)
LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg

edge_content_path = get_context_path(__file__, "test_edge_deployment.json")
edge_content_layered_path = get_context_path(
    __file__, "test_edge_deployment_layered.json"
)
edge_content_v11_path = get_context_path(__file__, "test_edge_deployment_v11.json")
edge_content_v1_path = get_context_path(__file__, "test_edge_deployment_v1.json")
edge_content_malformed_path = get_context_path(
    __file__, "test_edge_deployment_malformed.json"
)
generic_metrics_path = get_context_path(__file__, "test_config_generic_metrics.json")
adm_content_module_path = get_context_path(__file__, "test_adm_module_content.json")
adm_content_device_path = get_context_path(__file__, "test_adm_device_content.json")


class TestIoTEdgeSetModules(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTEdgeSetModules, self).__init__(
            test_case, LIVE_HUB, LIVE_RG
        )

    def test_edge_set_modules(self):
        edge_device_count = 1
        edge_device_ids = self.generate_device_names(edge_device_count, True)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            )
        )

        self.kwargs["edge_content"] = read_file_content(edge_content_path)

        # Content from file
        self.cmd(
            "iot edge set-modules -d {} -n {} -g {} -k '{}'".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, edge_content_path
            ),
            checks=[self.check("length([*])", 3)],
        )

        # Content inline
        self.cmd(
            "iot edge set-modules -d {} -n {} -g {} --content '{}'".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, "{edge_content}"
            ),
            self.check("length([*])", 3),
        )

        # Using connection string - content from file
        self.cmd(
            "iot edge set-modules -d {} --login {} -k '{}'".format(
                edge_device_ids[0], self.connection_string, edge_content_v1_path
            ),
            checks=[self.check("length([*])", 4)],
        )

        # Error schema validation - Malformed deployment
        self.cmd(
            "iot edge set-modules -d {} -n {} -g {} -k '{}'".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, edge_content_malformed_path
            ),
            expect_failure=True,
        )


class TestIoTEdgeDeployments(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTEdgeDeployments, self).__init__(
            test_case, LIVE_HUB, LIVE_RG
        )

    def test_edge_deployments(self):
        config_count = 5
        config_ids = self.generate_config_names(config_count)

        self.kwargs["generic_metrics"] = read_file_content(generic_metrics_path)
        self.kwargs["edge_content"] = read_file_content(edge_content_path)
        self.kwargs["edge_content_layered"] = read_file_content(
            edge_content_layered_path
        )
        self.kwargs["edge_content_v1"] = read_file_content(edge_content_v1_path)
        self.kwargs["edge_content_malformed"] = read_file_content(
            edge_content_malformed_path
        )
        self.kwargs["labels"] = '{"key0": "value0"}'

        priority = random.randint(1, 10)
        condition = "tags.building=9 and tags.environment='test'"

        # Content inline
        # Note: $schema is included as a nested property in the sample content.
        self.cmd(
            """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
            --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                "{labels}",
                "{edge_content}",
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
                self.check(
                    "content.modulesContent",
                    json.loads(self.kwargs["edge_content"])["content"][
                        "modulesContent"
                    ],
                ),
                self.check("metrics.queries", {}),
            ],
        )

        # Using connection string - content + metrics from file. Configurations must be lowercase and will be lower()'ed.
        # Note: $schema is included as a nested property in the sample content.
        self.cmd(
            "iot edge deployment create -d {} --login {} --pri {} --tc \"{}\" --lab '{}' -k '{}' --metrics '{}'".format(
                config_ids[1].upper(),
                self.connection_string,
                priority,
                condition,
                "{labels}",
                edge_content_path,
                edge_content_path,
            ),
            checks=[
                self.check("id", config_ids[1].lower()),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
                self.check(
                    "content.modulesContent",
                    json.loads(self.kwargs["edge_content"])["content"][
                        "modulesContent"
                    ],
                ),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["edge_content"])["metrics"]["queries"],
                ),
            ],
        )

        # Using connection string - layered deployment with content + metrics from file.
        # No labels, target-condition or priority
        self.cmd(
            "iot edge deployment create -d {} --login {} -k '{}' --metrics '{}' --layered".format(
                config_ids[2].upper(),
                self.connection_string,
                edge_content_layered_path,
                generic_metrics_path,
            ),
            checks=[
                self.check("id", config_ids[2].lower()),
                self.check("priority", 0),
                self.check("targetCondition", ""),
                self.check("labels", None),
                self.check(
                    "content.modulesContent",
                    json.loads(self.kwargs["edge_content_layered"])["content"][
                        "modulesContent"
                    ],
                ),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["generic_metrics"])["metrics"]["queries"],
                ),
            ],
        )

        # Content inline - Edge v1 format
        self.cmd(
            """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
            --target-condition \"{}\" --labels '{}' --content '{}' --metrics '{}'""".format(
                config_ids[3],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                "{labels}",
                "{edge_content_v1}",
                "{generic_metrics}",
            ),
            checks=[
                self.check("id", config_ids[3]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
                self.check(
                    "content.modulesContent",
                    json.loads(self.kwargs["edge_content_v1"])["content"][
                        "moduleContent"
                    ],
                ),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["generic_metrics"])["metrics"]["queries"],
                ),
            ],
        )

        # Error schema validation - Malformed deployment content causes validation error
        self.cmd(
            """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
            --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                config_ids[1],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                "{labels}",
                "{edge_content_malformed}",
            ),
            expect_failure=True,
        )

        # Error schema validation - Layered deployment without flag causes validation error
        self.cmd(
            """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
            --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                config_ids[1],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                "{labels}",
                "{edge_content_layered}",
            ),
            expect_failure=True,
        )

        # Uses IoT Edge hub schema version 1.1
        self.cmd(
            """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
            --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                config_ids[4],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                "{labels}",
                edge_content_v11_path,
            ),
            checks=[
                self.check("id", config_ids[4]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
                self.check(
                    "content.modulesContent",
                    json.loads(read_file_content(edge_content_v11_path))["modulesContent"],
                ),
                self.check("metrics.queries", {}),
            ],
        )

        # Show deployment
        self.cmd(
            "iot edge deployment show --deployment-id {} --hub-name {} --resource-group {}".format(
                config_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
            ],
        )

        # Show deployment - using connection string
        self.cmd(
            "iot edge deployment show -d {} --login {}".format(
                config_ids[1], self.connection_string
            ),
            checks=[
                self.check("id", config_ids[1]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
            ],
        )

        # Update deployment
        new_priority = random.randint(1, 10)
        new_condition = "tags.building=43 and tags.environment='dev'"
        self.kwargs["new_labels"] = '{"key": "super_value"}'
        self.cmd(
            "iot edge deployment update -d {} -n {} -g {} --set priority={} targetCondition=\"{}\" labels='{}'".format(
                config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                new_priority,
                new_condition,
                "{new_labels}",
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", new_priority),
                self.check("targetCondition", new_condition),
                self.check("labels", json.loads(self.kwargs["new_labels"])),
            ],
        )

        # Update deployment - using connection string
        new_priority = random.randint(1, 10)
        new_condition = "tags.building=40 and tags.environment='kindaprod'"
        self.kwargs["new_labels"] = '{"key": "legit_value"}'
        self.cmd(
            "iot edge deployment update -d {} -n {} -g {} --set priority={} targetCondition=\"{}\" labels='{}'".format(
                config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                new_priority,
                new_condition,
                "{new_labels}",
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", new_priority),
                self.check("targetCondition", new_condition),
                self.check("labels", json.loads(self.kwargs["new_labels"])),
            ],
        )

        # Evaluate metrics of a deployment
        user_metric_name = "mymetric"
        system_metric_name = "appliedCount"
        config_output = self.cmd(
            "iot edge deployment show --login {} --deployment-id {}".format(
                self.connection_string, config_ids[1]
            )
        ).get_output_in_json()

        # Default metric type is user
        self.cmd(
            "iot edge deployment show-metric --metric-id {} --deployment-id {} --hub-name {}".format(
                user_metric_name, config_ids[1], LIVE_HUB
            ),
            checks=[
                self.check("metric", user_metric_name),
                self.check(
                    "query", config_output["metrics"]["queries"][user_metric_name]
                ),
            ],
        )

        # System metric - using connection string
        self.cmd(
            "iot edge deployment show-metric --metric-id {} --login '{}' --deployment-id {} --metric-type {}".format(
                system_metric_name, self.connection_string, config_ids[1], "system"
            ),
            checks=[
                self.check("metric", system_metric_name),
                self.check(
                    "query",
                    config_output["systemMetrics"]["queries"][system_metric_name],
                ),
            ],
        )

        # Error - metric does not exist, using connection string
        self.cmd(
            "iot edge deployment show-metric -m {} --login {} -d {}".format(
                "doesnotexist", self.connection_string, config_ids[0]
            ),
            expect_failure=True,
        )

        config_list_check = [
            self.check("length([*])", config_count),
            self.exists("[?id=='{}']".format(config_ids[0])),
            self.exists("[?id=='{}']".format(config_ids[1])),
            self.exists("[?id=='{}']".format(config_ids[2])),
            self.exists("[?id=='{}']".format(config_ids[3]))
        ]

        # List all edge deployments
        self.cmd(
            "iot edge deployment list -n {} -g {}".format(LIVE_HUB, LIVE_RG),
            checks=config_list_check,
        )

        # List all edge deployments - using connection string
        self.cmd(
            "iot edge deployment list --login {}".format(self.connection_string),
            checks=config_list_check,
        )

        # Explicitly delete an edge deployment
        self.cmd(
            "iot edge deployment delete -d {} -n {} -g {}".format(
                config_ids[0], LIVE_HUB, LIVE_RG
            )
        )
        del self.config_ids[0]

        # Explicitly delete an edge deployment - using connection string
        self.cmd(
            "iot edge deployment delete -d {} --login {}".format(
                config_ids[1], self.connection_string
            )
        )
        del self.config_ids[0]


class TestIoTHubConfigurations(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubConfigurations, self).__init__(
            test_case, LIVE_HUB, LIVE_RG
        )

    def test_device_configurations(self):
        config_count = 3
        config_ids = self.generate_config_names(config_count)
        edge_config_ids = self.generate_config_names(1, True)

        self.kwargs["generic_metrics"] = read_file_content(generic_metrics_path)
        self.kwargs["adm_content_device"] = read_file_content(adm_content_device_path)
        self.kwargs["adm_content_module"] = read_file_content(adm_content_module_path)
        self.kwargs["edge_content"] = read_file_content(edge_content_path)
        self.kwargs["labels"] = '{"key0": "value0"}'

        priority = random.randint(1, 10)
        condition = "tags.building=9 and tags.environment='test'"

        # Device content inline
        # Note: $schema is included as a nested property in the sample content.
        self.cmd(
            """iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
            --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                "{labels}",
                "{adm_content_device}",
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
                self.check(
                    "content.deviceContent",
                    json.loads(self.kwargs["adm_content_device"])["content"][
                        "deviceContent"
                    ],
                ),
                self.check("metrics.queries", {}),
            ],
        )

        # Using connection string - module content + metrics from file. Configurations must be lowercase and will be lower()'ed.
        # Note: $schema is included as a nested property in the sample content.
        module_condition = "{} {}".format("FROM devices.modules WHERE", condition)
        self.cmd(
            "iot hub configuration create -c {} --login {} --pri {} --tc \"{}\" --lab '{}' -k '{}' --metrics '{}'".format(
                config_ids[1].upper(),
                self.connection_string,
                priority,
                module_condition,
                "{labels}",
                adm_content_module_path,
                adm_content_module_path,
            ),
            checks=[
                self.check("id", config_ids[1].lower()),
                self.check("priority", priority),
                self.check("targetCondition", module_condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
                self.check(
                    "content.moduleContent",
                    json.loads(self.kwargs["adm_content_module"])["content"][
                        "moduleContent"
                    ],
                ),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["adm_content_module"])["metrics"]["queries"],
                ),
            ],
        )

        # Using connection string - device content + metrics from file. Configurations must be lowercase and will be lower()'ed.
        # No labels, target-condition or priority
        self.cmd(
            "iot hub configuration create -c {} --login {} -k '{}' --metrics '{}'".format(
                config_ids[2].upper(),
                self.connection_string,
                adm_content_device_path,
                generic_metrics_path,
            ),
            checks=[
                self.check("id", config_ids[2].lower()),
                self.check("priority", 0),
                self.check("targetCondition", ""),
                self.check("labels", None),
                self.check(
                    "content.deviceContent",
                    json.loads(self.kwargs["adm_content_device"])["content"][
                        "deviceContent"
                    ],
                ),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["generic_metrics"])["metrics"]["queries"],
                ),
            ],
        )

        # Error validation - Malformed configuration content causes validation error
        # In this case we attempt to use an edge deployment ^_^
        self.cmd(
            """iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
            --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                config_ids[1],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                "{labels}",
                "{edge_content}",
            ),
            expect_failure=True,
        )

        # Error validation - Module configuration target condition must start with 'from devices.modules where'
        module_condition = "{} {}".format("FROM devices.modules WHERE", condition)
        self.cmd(
            "iot hub configuration create -c {} --login {} -k '{}'".format(
                config_ids[1].upper(),
                self.connection_string,
                adm_content_module_path,
            ),
            expect_failure=True,
        )

        # Show ADM configuration
        self.cmd(
            "iot hub configuration show --config-id {} --hub-name {} --resource-group {}".format(
                config_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
            ],
        )

        # Show ADM configuration - using connection string
        self.cmd(
            "iot hub configuration show -c {} --login {}".format(
                config_ids[1], self.connection_string
            ),
            checks=[
                self.check("id", config_ids[1]),
                self.check("priority", priority),
                self.check("targetCondition", module_condition),
                self.check("labels", json.loads(self.kwargs["labels"])),
            ],
        )

        # Update deployment
        new_priority = random.randint(1, 10)
        new_condition = "tags.building=43 and tags.environment='dev'"
        self.kwargs["new_labels"] = '{"key": "super_value"}'
        self.cmd(
            "iot hub configuration update -c {} -n {} -g {} --set priority={} targetCondition=\"{}\" labels='{}'".format(
                config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                new_priority,
                new_condition,
                "{new_labels}",
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", new_priority),
                self.check("targetCondition", new_condition),
                self.check("labels", json.loads(self.kwargs["new_labels"])),
            ],
        )

        # Update deployment - using connection string
        new_priority = random.randint(1, 10)
        new_condition = "tags.building=40 and tags.environment='kindaprod'"
        self.kwargs["new_labels"] = '{"key": "legit_value"}'
        self.cmd(
            "iot hub configuration update -c {} -n {} -g {} --set priority={} targetCondition=\"{}\" labels='{}'".format(
                config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                new_priority,
                new_condition,
                "{new_labels}",
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", new_priority),
                self.check("targetCondition", new_condition),
                self.check("labels", json.loads(self.kwargs["new_labels"])),
            ],
        )

        # Evaluate metrics of a deployment
        user_metric_name = "mymetric"
        system_metric_name = "appliedCount"
        config_output = self.cmd(
            "iot hub configuration show --login {} --config-id {}".format(
                self.connection_string, config_ids[1]
            )
        ).get_output_in_json()

        # Default metric type is user
        self.cmd(
            "iot hub configuration show-metric --metric-id {} --config-id {} --hub-name {}".format(
                user_metric_name, config_ids[1], LIVE_HUB
            ),
            checks=[
                self.check("metric", user_metric_name),
                self.check(
                    "query", config_output["metrics"]["queries"][user_metric_name]
                ),
            ],
        )

        # System metric - using connection string
        self.cmd(
            "iot hub configuration show-metric --metric-id {} --login '{}' --config-id {} --metric-type {}".format(
                system_metric_name, self.connection_string, config_ids[1], "system"
            ),
            checks=[
                self.check("metric", system_metric_name),
                self.check(
                    "query",
                    config_output["systemMetrics"]["queries"][system_metric_name],
                ),
            ],
        )

        # Error - metric does not exist, using connection string
        self.cmd(
            "iot hub configuration show-metric -m {} --login {} -c {}".format(
                "doesnotexist", self.connection_string, config_ids[0]
            ),
            expect_failure=True,
        )

        # Create Edge deployment to ensure it doesn't show up on ADM list
        self.cmd(
            """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --content '{}'""".format(
                edge_config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                "{edge_content}",
            )
        )

        config_list_check = [
            self.check("length([*])", config_count),
            self.exists("[?id=='{}']".format(config_ids[0])),
            self.exists("[?id=='{}']".format(config_ids[1])),
            self.exists("[?id=='{}']".format(config_ids[2]))
        ]

        # List all ADM configurations
        self.cmd(
            "iot hub configuration list -n {} -g {}".format(LIVE_HUB, LIVE_RG),
            checks=config_list_check,
        )

        # List all ADM configurations - using connection string
        self.cmd(
            "iot hub configuration list --login {}".format(self.connection_string),
            checks=config_list_check,
        )

        # Explicitly delete an ADM configuration
        self.cmd(
            "iot hub configuration delete -c {} -n {} -g {}".format(
                config_ids[0], LIVE_HUB, LIVE_RG
            )
        )
        del self.config_ids[0]

        # Explicitly delete an ADM configuration - using connection string
        self.cmd(
            "iot hub configuration delete -c {} --login {}".format(
                config_ids[1], self.connection_string
            )
        )
        del self.config_ids[0]
