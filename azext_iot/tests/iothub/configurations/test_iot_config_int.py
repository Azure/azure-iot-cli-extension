# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import random
import json
from time import sleep
import pytest

from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.conftest import get_context_path
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES, ROLE_ASSIGNMENT_REFRESH_TIME
from azext_iot.common.utility import read_file_content, process_json_arg, get_current_user
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.tests.settings import UserTypes

edge_content_path = get_context_path(__file__, "test_edge_deployment.json")
edge_content_layered_path = get_context_path(
    __file__, "test_edge_deployment_layered.json"
)
edge_content_v11_path = get_context_path(__file__, "test_edge_deployment_v11.json")
edge_content_v1_path = get_context_path(__file__, "test_edge_deployment_v1.json")
edge_billable_module_path = get_context_path(__file__, "test_edge_deployment_billable_module.json")
edge_content_malformed_path = get_context_path(
    __file__, "test_edge_deployment_malformed.json"
)
generic_metrics_path = get_context_path(__file__, "test_config_generic_metrics.json")
adm_content_module_path = get_context_path(__file__, "test_adm_module_content.json")
adm_content_device_path = get_context_path(__file__, "test_adm_device_content.json")
sleep(ROLE_ASSIGNMENT_REFRESH_TIME)
current_user = get_current_user()


class TestIoTConfigurations(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTConfigurations, self).__init__(
            test_case
        )

    def test_edge_set_modules(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
            edge_device_count = 1
            edge_device_ids = self.generate_device_names(edge_device_count, True)

            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                        edge_device_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase,
                )
            )

            self.kwargs["edge_content"] = read_file_content(edge_content_path)

            # Content inline
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge set-modules -d {} -n {} -g {} --content '{}'".format(
                        edge_device_ids[0], self.entity_name, self.entity_rg, "{edge_content}"
                    ),
                    auth_type=auth_phase,
                ),
                self.check("length([*])", 3),
            )

            # Content from file
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge set-modules -d {} -n {} -g {} -k '{}'".format(
                        edge_device_ids[0], self.entity_name, self.entity_rg, edge_content_v1_path
                    ),
                    auth_type=auth_phase,
                ),
                checks=[self.check("length([*])", 4)],
            )

            # Apply billable edge module (requires AAD Auth)
            # @avagraw - The billable edge modules can only be applied using user tokens (service principals are not supported)
            if current_user["type"] == UserTypes.user.value:
                billable_module_content = process_json_arg(edge_billable_module_path, argument_name="content")
                purchase_module = list(billable_module_content["modulesPurchase"].keys())[0]
                self.cmd(
                    self.set_cmd_auth_type(
                        "iot edge set-modules -d {} -n {} -g {} -k '{}'".format(
                            edge_device_ids[0], self.entity_name, self.entity_rg, edge_billable_module_path
                        ),
                        auth_type=AuthenticationTypeDataplane.login.value,
                    ),
                    checks=[
                        self.check("length([*])", 5),
                        self.exists("[?moduleId=='{}']".format(purchase_module))
                    ],
                )

            # Error schema validation - Malformed deployment
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge set-modules -d {} -n {} -g {} -k '{}'".format(
                        edge_device_ids[0], self.entity_name, self.entity_rg, edge_content_malformed_path
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

    def test_edge_deployments(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
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
                self.set_cmd_auth_type(
                    """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                        config_ids[0],
                        self.entity_name,
                        self.entity_rg,
                        priority,
                        condition,
                        "{labels}",
                        "{edge_content}",
                    ),
                    auth_type=auth_phase,
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

            # Content + metrics from file. Configurations must be lowercase and will be lower()'ed.
            # Note: $schema is included as a nested property in the sample content.
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge deployment create -d {} --pri {} --tc \"{}\" --lab '{}' -k '{}' --metrics '{}' -n {} -g {}".format(
                        config_ids[1].upper(),
                        priority,
                        condition,
                        "{labels}",
                        edge_content_path,
                        edge_content_path,
                        self.entity_name,
                        self.entity_rg
                    ),
                    auth_type=auth_phase
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

            # Layered deployment with content + metrics from file.
            # No labels, target-condition or priority
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge deployment create -d {} -k '{}' --metrics '{}' --layered -n {} -g {}".format(
                        config_ids[2].upper(),
                        edge_content_layered_path,
                        generic_metrics_path,
                        self.entity_name,
                        self.entity_rg,
                    ),
                    auth_type=auth_phase
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
                self.set_cmd_auth_type(
                    """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels '{}' --content '{}' --metrics '{}'""".format(
                        config_ids[3],
                        self.entity_name,
                        self.entity_rg,
                        priority,
                        condition,
                        "{labels}",
                        "{edge_content_v1}",
                        "{generic_metrics}",
                    ),
                    auth_type=auth_phase,
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
                self.set_cmd_auth_type(
                    """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                        config_ids[1],
                        self.entity_name,
                        self.entity_rg,
                        priority,
                        condition,
                        "{labels}",
                        "{edge_content_malformed}",
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Error schema validation - Layered deployment without flag causes validation error
            self.cmd(
                self.set_cmd_auth_type(
                    """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                        config_ids[1],
                        self.entity_name,
                        self.entity_rg,
                        priority,
                        condition,
                        "{labels}",
                        "{edge_content_layered}",
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Uses IoT Edge hub schema version 1.1
            self.cmd(
                self.set_cmd_auth_type(
                    """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                        config_ids[4],
                        self.entity_name,
                        self.entity_rg,
                        priority,
                        condition,
                        "{labels}",
                        edge_content_v11_path,
                    ),
                    auth_type=auth_phase,
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

            # Edge billable module deployment (requires AAD Auth)
            # @avagraw - Following snippet can be uncommented when API starts supporting deployment of billable edge modules
            # self.cmd(
            #     self.set_cmd_auth_type(
            #         """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
            #         --target-condition \"{}\" --labels '{}' --content '{}'""".format(
            #             config_ids[5],
            #             self.entity_name,
            #             self.entity_rg,
            #             priority,
            #             condition,
            #             "{labels}",
            #             edge_billable_module_path,
            #         ),
            #         auth_type=AuthenticationTypeDataplane.login.value,
            #     ),
            #     checks=[
            #         self.check("id", config_ids[5]),
            #         self.check("priority", priority),
            #         self.check("targetCondition", condition),
            #         self.check("labels", json.loads(self.kwargs["labels"])),
            #         self.check(
            #             "content.modulesContent",
            #             json.loads(read_file_content(edge_billable_module_path))["modulesContent"],
            #         ),
            #         self.check(
            #             "content.modulesPurchase",
            #             json.loads(read_file_content(edge_billable_module_path))["modulesPurchase"],
            #         ),
            #         self.check("metrics.queries", {}),
            #     ],
            # )

            # Show edge billable module deployment
            # @avagraw - Following snippet can be uncommented when API starts supporting deployment of billable edge modules
            # self.cmd(
            #     self.set_cmd_auth_type(
            #         "iot edge deployment show --deployment-id {} --hub-name {} --resource-group {}".format(
            #             config_ids[5], self.entity_name, self.entity_rg
            #         ),
            #         auth_type=auth_phase,
            #     ),
            #     checks=[
            #         self.check("id", config_ids[5]),
            #         self.check("priority", priority),
            #         self.check("targetCondition", condition),
            #         self.check("labels", json.loads(self.kwargs["labels"])),
            #     ],
            # )

            # Show deployment
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge deployment show --deployment-id {} --hub-name {} --resource-group {}".format(
                        config_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase,
                ),
                checks=[
                    self.check("id", config_ids[0]),
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
                self.set_cmd_auth_type(
                    "iot edge deployment update -d {} -n {} -g {} --set priority={} targetCondition=\"{}\" labels='{}'".format(
                        config_ids[0],
                        self.entity_name,
                        self.entity_rg,
                        new_priority,
                        new_condition,
                        "{new_labels}",
                    ),
                    auth_type=auth_phase
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
                self.set_cmd_auth_type(
                    "iot edge deployment show --deployment-id {} -n {} -g {}".format(
                        config_ids[1],
                        self.entity_name,
                        self.entity_rg
                    ),
                    auth_type=auth_phase
                )
            ).get_output_in_json()

            # Default metric type is user
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge deployment show-metric --metric-id {} --deployment-id {} --hub-name {}".format(
                        user_metric_name, config_ids[1], self.entity_name
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("metric", user_metric_name),
                    self.check(
                        "query", config_output["metrics"]["queries"][user_metric_name]
                    ),
                ],
            )

            # System metric
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge deployment show-metric --metric-id {} --deployment-id {} --metric-type {} -n {} -g {}".format(
                        system_metric_name, config_ids[1], "system", self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("metric", system_metric_name),
                    self.check(
                        "query",
                        config_output["systemMetrics"]["queries"][system_metric_name],
                    ),
                ],
            )

            # Error - metric does not exist
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge deployment show-metric -m {} -d {} -n {} -g {}".format(
                        "doesnotexist", config_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase
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
                self.set_cmd_auth_type(
                    "iot edge deployment list -n {} -g {}".format(self.entity_name, self.entity_rg),
                    auth_type=auth_phase
                ),
                checks=config_list_check,
            )

            # Explicitly delete an edge deployment
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge deployment delete -d {} -n {} -g {}".format(
                        config_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase
                )
            )

            # Validate deletion
            self.cmd(
                self.set_cmd_auth_type(
                    "iot edge deployment show -d {} -n {} -g {}".format(
                        config_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            self.tearDown()

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

        for auth_phase in DATAPLANE_AUTH_TYPES:
            # Device content inline
            # Note: $schema is included as a nested property in the sample content.
            self.cmd(
                self.set_cmd_auth_type(
                    """iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                        config_ids[0],
                        self.entity_name,
                        self.entity_rg,
                        priority,
                        condition,
                        "{labels}",
                        "{adm_content_device}",
                    ),
                    auth_type=auth_phase
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

            # Module content + metrics from file.
            # Configurations must be lowercase and will be lower()'ed.
            # Note: $schema is included as a nested property in the sample content.
            module_condition = "{} {}".format("FROM devices.modules WHERE", condition)
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub configuration create -c {} --pri {} --tc \"{}\" --lab '{}' -k '{}' -m '{}' -n {} -g {}".format(
                        config_ids[1].upper(),
                        priority,
                        module_condition,
                        "{labels}",
                        adm_content_module_path,
                        adm_content_module_path,
                        self.entity_name,
                        self.entity_rg
                    ),
                    auth_type=auth_phase,
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

            # Device content + metrics from file.
            # Configurations must be lowercase and will be lower()'ed.
            # No labels, target-condition or priority
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub configuration create -c {} -k '{}' --metrics '{}' -n {} -g {}".format(
                        config_ids[2].upper(),
                        adm_content_device_path,
                        generic_metrics_path,
                        self.entity_name,
                        self.entity_rg
                    ),
                    auth_type=auth_phase
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
                self.set_cmd_auth_type(
                    """iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels '{}' --content '{}'""".format(
                        config_ids[1],
                        self.entity_name,
                        self.entity_rg,
                        priority,
                        condition,
                        "{labels}",
                        "{edge_content}",
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Error validation - Module configuration target condition must start with 'from devices.modules where'
            module_condition = "{} {}".format("FROM devices.modules WHERE", condition)
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub configuration create -c {} -k '{}' -n {} -g {}".format(
                        config_ids[1].upper(),
                        adm_content_module_path,
                        self.entity_name,
                        self.entity_rg
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Show ADM configuration
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub configuration show --config-id {} --hub-name {} --resource-group {}".format(
                        config_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("id", config_ids[0]),
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
                self.set_cmd_auth_type(
                    "iot hub configuration update -c {} -n {} -g {} --set priority={} targetCondition=\"{}\" labels='{}'".format(
                        config_ids[0],
                        self.entity_name,
                        self.entity_rg,
                        new_priority,
                        new_condition,
                        "{new_labels}",
                    ),
                    auth_type=auth_phase,
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
                self.set_cmd_auth_type(
                    "iot hub configuration show --config-id {} -n {} -g {}".format(
                        config_ids[1], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            # Default metric type is user
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub configuration show-metric --metric-id {} --config-id {} --hub-name {}".format(
                        user_metric_name, config_ids[1], self.entity_name
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("metric", user_metric_name),
                    self.check(
                        "query", config_output["metrics"]["queries"][user_metric_name]
                    ),
                ],
            )

            # System metric
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub configuration show-metric --metric-id {} --config-id {} --metric-type {} -n {} -g {}".format(
                        system_metric_name, config_ids[1], "system", self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase,
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
                self.set_cmd_auth_type(
                    "iot hub configuration show-metric -m {} -c {} -n {} -g {}".format(
                        "doesnotexist", config_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Create Edge deployment to ensure it doesn't show up on ADM list
            self.cmd(
                self.set_cmd_auth_type(
                    """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --content '{}'""".format(
                        edge_config_ids[0],
                        self.entity_name,
                        self.entity_rg,
                        "{edge_content}",
                    ),
                    auth_type=auth_phase
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
                self.set_cmd_auth_type(
                    "iot hub configuration list -n {} -g {}".format(self.entity_name, self.entity_rg),
                    auth_type=auth_phase
                ),
                checks=config_list_check,
            )

            # Explicitly delete an ADM configuration
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub configuration delete -c {} -n {} -g {}".format(
                        config_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase
                )
            )

            # Validate deletion
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub configuration show -c {} -n {} -g {}".format(
                        config_ids[0], self.entity_name, self.entity_rg
                    ),
                    auth_type=auth_phase,
                ),
                expect_failure=True
            )

            self.tearDown()

    @pytest.mark.skipif(
        current_user["type"] != UserTypes.user.value,
        reason="Edge module image terms operations are supported only when using real user AAD tokens (not service principals)"
    )
    def test_edge_module_image_terms(self):

        offerId = "jlian-test-offer-paid"
        planId = "premium"
        publisherId = "azure-iot"
        urn = "azure-iot:jlian-test-offer-paid:sku:latest"

        self.setup_edge_module_image_terms_tests(offerId, planId, publisherId)

        offer_checks = [
            self.check("product", offerId),
            self.check("plan", planId),
            self.check("publisher", publisherId),
        ]

        # Show IoT Edge module terms offer
        self.cmd(
            "iot edge module image terms show --offer {} --plan {} --publisher {}".format(
                offerId, planId, publisherId
            ),
            checks=offer_checks.append(self.check("accepted", "false"))
        )

        # Accept IoT Edge module terms offer
        self.cmd(
            "iot edge module image terms accept --offer {} --plan {} --publisher {}".format(
                offerId, planId, publisherId
            ),
            checks=offer_checks.append(self.check("accepted", "true"))
        )

        # Show the accepted IoT Edge module terms offer using URN
        # self.cmd(
        #     "iot edge module image terms show --urn {}".format(
        #         urn
        #     ),
        #     checks=offer_checks.append(self.check("accepted", "true"))
        # )

        # Cancel IoT Edge module terms offer
        self.cmd(
            "iot edge module image terms cancel --offer {} --plan {} --publisher {}".format(
                offerId, planId, publisherId
            ),
            checks=offer_checks.append(self.check("accepted", "false"))
        )

        # Error - providing offer, plan and publisher when URN is already provided
        self.cmd(
            "iot edge module image terms show --urn {} --offer {} --plan {} --publisher {}".format(
                urn, offerId, planId, publisherId
            ),
            expect_failure=True,
        )

        # Error - invalid offer
        self.cmd(
            "iot edge module image terms show --offer {} --plan {} --publisher {}".format(
                "invalid_offer", planId, publisherId
            ),
            expect_failure=True,
        )

        # Error - invalid publisher
        self.cmd(
            "iot edge module image terms show --offer {} --plan {} --publisher {}".format(
                offerId, planId, "invalid_publisher"
            ),
            expect_failure=True,
        )
