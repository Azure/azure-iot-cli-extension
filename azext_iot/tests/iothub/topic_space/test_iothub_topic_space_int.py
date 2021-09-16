# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.iothub import IoTLiveScenarioTest

# Set up since connection to test hub is only through connection string
# from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_CONNECTION_STRING
# settings = DynamoSettings(ENV_SET_TEST_IOTHUB_CONNECTION_STRING)
# LIVE_HUB_CS = settings.env.azext_iot_testhub_connection_string


class TestIoTHubTopicSpace(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubTopicSpace, self).__init__(test_case)

    def test_overall_topic_space(self):
        file_name = "./example_topic.json"
        topic_types = ["LowFanout", "PublishOnly"]
        topic_templates = [
            f"t{generate_generic_id()}",
            f"t{generate_generic_id()} t{generate_generic_id()}",
            f"t{generate_generic_id()}/#",
            f"t{generate_generic_id()}/+",
            f"t{generate_generic_id()}/+/t{generate_generic_id()}",
            f"t{generate_generic_id()}/+/" + "${service.device}",
            f"t{generate_generic_id()}/+/" + "${service.device|service.pipeline}",
        ]
        topic_names = [
            f"ts_{generate_generic_id()}" for _ in range(len(topic_templates))
        ]

        self.kwargs["service"] = json.dumps(
            {
                "device": "{service.device}",
                "pipeline": "{service.pipeline}"
            }
        )

        initial_count = self.cmd(
            "iot hub topic-space list -n {} -g {}".format(
                self.entity_name,
                self.entity_rg,
            )
        ).get_output_in_json()

        if len(initial_count) != 0:
            for topic in initial_count:
                self.cmd(
                    "iot hub topic-space delete -n {} -g {} --tsn {}".format(
                        self.entity_name,
                        self.entity_rg,
                        topic["name"],
                    )
                )

        # Generate topic spaces
        for x in range(len(topic_names)):
            tname = topic_names[x]
            ttype = topic_types[x % len(topic_types)]
            ttemplate = topic_templates[x]
            expected_template = ttemplate.split(" ")

            topic = self.cmd(
                "iot hub topic-space create -n {} -g {} --tsn {} --tst {} --template {}".format(
                    self.entity_name,
                    self.entity_rg,
                    tname,
                    ttype,
                    ttemplate
                )
            ).get_output_in_json()
            assert_topic_space_attributes(topic, tname, ttype, expected_template)

            # Update templates
            ttemplate = ttemplate.replace("t", "d")
            expected_template = ttemplate.split(" ")
            topic = self.cmd(
                "iot hub topic-space update -n {} -g {} --tsn {} --template {}".format(
                    self.entity_name,
                    self.entity_rg,
                    tname,
                    ttemplate
                )
            ).get_output_in_json()
            assert_topic_space_attributes(topic, tname, ttype, expected_template)

            topic = self.cmd(
                "iot hub topic-space show -n {} -g {} --tsn {} ".format(
                    self.entity_name,
                    self.entity_rg,
                    tname
                )
            ).get_output_in_json()
            assert_topic_space_attributes(topic, tname, ttype, expected_template)

        # Check that type cannot be changed
        self.cmd(
            "iot hub topic-space create -n {} -g {} --tsn {} --tst {} --template {}".format(
                self.entity_name,
                self.entity_rg,
                topic_names[0],
                topic_types[1],
                topic_templates[0]
            ),
            expect_failure=True
        )

        # Check that templates cannot be overlapped
        self.cmd(
            "iot hub topic-space create -n {} -g {} --tsn {} --tst {} --template {}".format(
                self.entity_name,
                self.entity_rg,
                generate_generic_id(),
                topic_types[0],
                "#"
            ),
            expect_failure=True
        )

        topics = self.cmd(
            "iot hub topic-space list -n {} -g {}".format(
                self.entity_name,
                self.entity_rg,
            )
        ).get_output_in_json()
        assert len(topics) == len(topic_names)

        for tname in topic_names:
            self.cmd(
                "iot hub topic-space delete -n {} -g {} --tsn {}".format(
                    self.entity_name,
                    self.entity_rg,
                    tname,
                )
            )

        topics = self.cmd(
            "iot hub topic-space list -n {} -g {}".format(
                self.entity_name,
                self.entity_rg,
            )
        ).get_output_in_json()
        assert len(topics) == 0

        # File read check
        fake_file = "./example_json2.json"
        file_topic_name = "ts_{}".format(generate_generic_id())
        topic = self.cmd(
            "iot hub topic-space create -n {} -g {} --tsn {} --tst {} --template {} {}".format(
                self.entity_name,
                self.entity_rg,
                file_topic_name,
                topic_types[0],
                file_name,
                fake_file
            )
        ).get_output_in_json()
        with open(file_name) as f:
            expected_template = json.loads(f.read())
            expected_template.append(fake_file)
            assert_topic_space_attributes(topic, file_topic_name, topic_types[0], expected_template)

        self.cmd(
            "iot hub topic-space delete -n {} -g {} --tsn {}".format(
                self.entity_name,
                self.entity_rg,
                file_topic_name,
            )
        )

    def test_topic_space_templates(self):
        # Clear topics if need be
        topics = self.cmd(
            "iot hub topic-space list -n {} -g {}".format(
                self.entity_name,
                self.entity_rg,
            )
        ).get_output_in_json()
        if len(topics) != 0:
            for topic in topics:
                self.cmd(
                    "iot hub topic-space delete -n {} -g {} --tsn {}".format(
                        self.entity_name,
                        self.entity_rg,
                        topic["name"],
                    )
                )

        self.kwargs["hello"] = "{hello}"
        self.kwargs["   hello"] = "{   hello}"
        self.kwargs["hello  "] = "{hello  }"
        self.kwargs["   hello  "] = "{   hello  }"
        self.kwargs["d"] = "{d}"
        self.kwargs["he llo"] = "{he llo}"
        # json.dumps(
        #     {
        #         "device": "{service.device}",
        #         "pipeline": "{service.pipeline}"
        #     }
        # )

        topic_name = "ts_{}".format(generate_generic_id())
        working_templates = [
            " ", "/", "+", "#", "\\", "/+", "/#", "//", "/ ", "+/", " /", "/ /", "+/+",
            "hello,HELLO", "hello,/hello", "+,/finance", "+,+/+,+/+/+,+/+/+/+",
            "d${hello}", "/${hello}", "/${hello  }", "/${   hello}", "/${   hello  }",
            "d${hello}x{hello}"
        ]
        non_working_multiples = [
            "hello,hello", "#,an/y/th/in/g", "+,#", "/+,/finance", "+/+,/+", "+/+,+/", "+/+,/",
            "/${hello},/${hello  }"
        ]
        non_working_templates = [
            " #", " +", "h#", "h+", "#/", "+ ", "$", "$d", "/$", "/$d", "${d}#", "${d}+", ",d",
            "/${he llo}"
            # "hello,hello", "#,an/y/th/in/g", "+,#", "/+,/finance", "+/+,/+", "+/+,+/", "+/+,/",
            # "/${hello},/${hello  }", ""
        ]
        # non_working_templates.extend(non_working_multiples)

        for template in working_templates:
            expected_template = template.split(",")
            template = "' '".join(expected_template)
            topic = self.cmd(
                "iot hub topic-space create -n {} -g {} --tsn {} --tst {} --template '{}'".format(
                    self.entity_name,
                    self.entity_rg,
                    topic_name,
                    "LowFanout",
                    template
                )
            ).get_output_in_json()
            assert_topic_space_attributes(topic, topic_name, "LowFanout", expected_template)

        for template in non_working_templates:
            expected_template = template.split(",")
            template = "' '".join(expected_template)
            topic = self.cmd(
                "iot hub topic-space create -n {} -g {} --tsn {} --tst {} --template '{}'".format(
                    self.entity_name,
                    self.entity_rg,
                    topic_name,
                    "LowFanout",
                    template
                ),
                expect_failure=True
            )

        non_working_multiples = [t.split(",") for t in non_working_multiples]
        topic_name2 = "ts_{}".format(generate_generic_id())

        for pair in non_working_multiples:
            # So this does not affect the pair
            self.cmd(
                "iot hub topic-space delete -n {} -g {} --tsn {}".format(
                    self.entity_name,
                    self.entity_rg,
                    topic_name,
                )
            )
            self.cmd(
                "iot hub topic-space create -n {} -g {} --tsn {} --tst {} --template {}".format(
                    self.entity_name,
                    self.entity_rg,
                    topic_name,
                    "LowFanout",
                    pair[0]
                )
            )
            self.cmd(
                "iot hub topic-space create -n {} -g {} --tsn {} --tst {} --template {}".format(
                    self.entity_name,
                    self.entity_rg,
                    topic_name2,
                    "LowFanout",
                    pair[1]
                ),
                expect_failure=True
            )

        self.cmd(
            "iot hub topic-space delete -n {} -g {} --tsn {}".format(
                self.entity_name,
                self.entity_rg,
                topic_name,
            )
        )


def assert_topic_space_attributes(result, expected_name, expected_type, expected_template):
    assert result["name"] == expected_name
    assert result["properties"]["topicspaceType"] == expected_type
    assert result["properties"]["topicTemplates"] == expected_template
