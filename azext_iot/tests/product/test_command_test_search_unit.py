# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import unittest
import mock
from knack.util import CLIError
from azext_iot.product.test.command_tests import search
from azext_iot.sdk.product.models import DeviceTestSearchOptions


class SearchClass(unittest.TestCase):
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.search_device_test")
    def test_search_not_called_when_no_criteria(self, mock_search):
        with self.assertRaises(CLIError):
            search(self)

    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.search_device_test")
    def test_search_called_with_product_id(self, mock_search):
        search(self, product_id="123")
        mock_search.assert_called_with(
            body=DeviceTestSearchOptions(
                product_id="123",
                dps_registration_id=None,
                dps_x509_certificate_common_name=None,
            )
        )

    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.search_device_test")
    def test_search_called_with_registration_id(self, mock_search):
        search(self, registration_id="123")
        mock_search.assert_called_with(
            body=DeviceTestSearchOptions(
                product_id=None,
                dps_registration_id="123",
                dps_x509_certificate_common_name=None,
            )
        )

    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.search_device_test")
    def test_search_called_with_certificate_name(self, mock_search):
        search(self, certificate_name="123")
        mock_search.assert_called_with(
            body=DeviceTestSearchOptions(
                product_id=None,
                dps_registration_id=None,
                dps_x509_certificate_common_name="123",
            )
        )
