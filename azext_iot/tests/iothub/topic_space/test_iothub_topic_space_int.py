# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
import json
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_CONNECTION_STRING

settings = DynamoSettings(ENV_SET_TEST_IOTHUB_CONNECTION_STRING)
LIVE_HUB_CS = settings.env.azext_iot_testhub_connection_string


class TestIoTHubTopicSpace(CaptureOutputLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubTopicSpace, self).__init__(test_case)

    def test_overall_topic_space(self):
        topic_types = ["LowFanout", "PublishOnly"]
        topic_templates = [
            f"t{generate_generic_id()}",
            f"t{generate_generic_id()},t{generate_generic_id()}",
            f"'[t{generate_generic_id()},t{generate_generic_id()}]'",
            f"t{generate_generic_id()}/#",
            f"t{generate_generic_id()}/+",
            f"t{generate_generic_id()}/+/t{generate_generic_id()}",
            f"'\"t{generate_generic_id()}/+/" + "${service.device}\"'",
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

        initial_count =self.cmd(
            "iot hub topic-space list -l {}".format(
                LIVE_HUB_CS
            )
        ).get_output_in_json()


        if len(initial_count) != 0:
            for topic in initial_count:
                self.cmd(
                    "iot hub topic-space delete -l {} --topic-name {}".format(
                        LIVE_HUB_CS,
                        topic["name"],
                    )
                )

        # Generate topic spaces
        for x in range(len(topic_names)):
            tname = topic_names[x]
            ttype = topic_types[x % len(topic_types)]
            ttemplate = topic_templates[x]
            print(tname, ttype, ttemplate)

            topic = self.cmd(
                "iot hub topic-space create -l {} --topic-name {} --topic-type {} --topic-template {}".format(
                    LIVE_HUB_CS,
                    tname,
                    ttype,
                    ttemplate
                )
            ).get_output_in_json()
            assert_topic_space_attributes(topic, tname, ttype, ttemplate)

            # Update templates
            ttemplate = ttemplate.replace("t", "d")
            topic = self.cmd(
                "iot hub topic-space update -l {} --topic-name {} --topic-type {} --topic-template {}".format(
                    LIVE_HUB_CS,
                    tname,
                    ttype,
                    ttemplate
                )
            ).get_output_in_json()
            assert_topic_space_attributes(topic, tname, ttype, ttemplate)

            topic = self.cmd(
                "iot hub topic-space show -l {} --topic-name {} ".format(
                    LIVE_HUB_CS,
                    tname
                )
            ).get_output_in_json()
            assert_topic_space_attributes(topic, tname, ttype, ttemplate)

        # Check that type cannot be changed
        self.cmd(
            "iot hub topic-space create -l {} --topic-name {} --topic-type {} --topic-template {}".format(
                LIVE_HUB_CS,
                topic_names[0],
                topic_types[1],
                topic_templates[0]
            ),
            expect_failure=True
        )

        # Check that templates cannot be overlapped
        self.cmd(
            "iot hub topic-space create -l {} --topic-name {} --topic-type {} --topic-template {}".format(
                LIVE_HUB_CS,
                generate_generic_id(),
                topic_types[0],
                "#"
            ),
            expect_failure=True
        )

        topics = self.cmd(
            "iot hub topic-space list -l {}".format(
                LIVE_HUB_CS
            )
        ).get_output_in_json()
        assert len(topics) == len(topic_names)

        for tname in topic_names:
            self.cmd(
                "iot hub topic-space delete -l {} --topic-name {}".format(
                    LIVE_HUB_CS,
                    tname,
                )
            )

        topics = self.cmd(
            "iot hub topic-space list -l {}".format(
                LIVE_HUB_CS
            )
        ).get_output_in_json()
        assert len(topics) == 0

    def test_topic_space_templates(self):
        # Clear topics if need be
        topics = self.cmd(
            "iot hub topic-space list -l {}".format(
                LIVE_HUB_CS
            )
        ).get_output_in_json()
        if len(topics) != 0:
            for topic in topics:
                self.cmd(
                    "iot hub topic-space delete -l {} --topic-name {}".format(
                        LIVE_HUB_CS,
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
            # "hello,hello", "#,an/y/th/in/g", "+,#", "/+,/finance", "+/+,/+", "+/+,+/", "+/+,/",
            # "/${hello},/${hello  }", ""
        ]
        non_working_templates = [
            " #", " +", "h#", "h+", "#/", "+ ", "$", "$d", "/$", "/$d", "${d}#", "${d}+", ",d",
            "/${he llo}"
            # "hello,hello", "#,an/y/th/in/g", "+,#", "/+,/finance", "+/+,/+", "+/+,+/", "+/+,/",
            # "/${hello},/${hello  }", ""
        ]
        non_working_templates.extend(non_working_multiples)

        for template in working_templates:
            topic = self.cmd(
                "iot hub topic-space create -l {} --topic-name {} --topic-type {} --topic-template '{}'".format(
                    LIVE_HUB_CS,
                    topic_name,
                    "LowFanout",
                    template
                )
            ).get_output_in_json()
            assert_topic_space_attributes(topic, topic_name, "LowFanout", template)

        for template in non_working_templates:
            topic = self.cmd(
                "iot hub topic-space create -l {} --topic-name {} --topic-type {} --topic-template '{}'".format(
                    LIVE_HUB_CS,
                    topic_name,
                    "LowFanout",
                    template
                ),
                expect_failure=True
            )
        self.cmd(
            "iot hub topic-space delete -l {} --topic-name {}".format(
                LIVE_HUB_CS,
                topic_name,
            )
        )


        # Multiple topic_names
        # Add limit tests?


def assert_topic_space_attributes(result, expected_name, expected_type, input_template):
    expected_template = list(re.split(",", input_template.strip("[]'")))
    assert result["name"] == expected_name
    assert result["properties"]["topicspaceType"] == expected_type
    assert result["properties"]["topicTemplates"] == expected_template
