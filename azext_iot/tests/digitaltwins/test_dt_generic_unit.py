# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.digitaltwins.providers import generic as subject


class TestLROCheckStateHelper(object):
    @pytest.mark.parametrize(
        "test_input", [
            {},
            {"foo": "bar"},
            {"provisioning_state": "bar"},
            {"properties": {"foo": "bar"}},
            {"properties": {"provisioning_state": "foo"}},
            {"provisioning_state": "bar", "properties": {"provisioning_state": "foo"}}
        ]
    )
    def test_get_provisioning_state(self, test_input):
        output = subject._get_provisioning_state(test_input)
        if test_input.get("provisioning_state"):
            assert output == test_input["provisioning_state"]
        elif test_input.get("properties") and test_input.get("properties").get("provisioning_state"):
            assert output == test_input["properties"]["provisioning_state"]
        else:
            assert output is None
