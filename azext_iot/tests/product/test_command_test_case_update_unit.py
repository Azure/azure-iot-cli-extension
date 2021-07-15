# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import unittest
from unittest import mock
from knack.util import CLIError
from azext_iot.product.test.command_test_cases import update


class TestTestCaseUpdate(unittest.TestCase):
    def __init__(self, test_case):
        self.test_id = "3beb0e67-33d0-4896-b69b-91c7b7ce8fab"
        super(TestTestCaseUpdate, self).__init__(test_case)

    @mock.patch("os.path.exists")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.update_test_cases")
    def test_update_with_missing_file(self, mock_api, mock_exists):
        mock_exists.return_value = False

        with self.assertRaises(CLIError) as context:
            update(
                self,
                test_id=self.test_id,
                configuration_file="missingFile.json"
            )

            self.assertEqual(
                "If attestation type is x509, certificate path is required",
                str(context.exception),
            )
            mock_api.assert_not_called()

    @mock.patch("os.path.exists")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.update_test_cases")
    @mock.patch("azext_iot.product.test.command_test_cases.process_json_arg")
    def test_update(self, mock_json_parser, mock_api, mock_exists):
        mock_exists.return_value = True
        mock_json_payload = {}
        mock_json_parser.return_value = mock_json_payload

        update(
            self,
            test_id=self.test_id,
            configuration_file="configurationFile.json"
        )

        mock_api.assert_called_with(
            device_test_id=self.test_id,
            certification_badge_test_cases=mock_json_payload
        )
