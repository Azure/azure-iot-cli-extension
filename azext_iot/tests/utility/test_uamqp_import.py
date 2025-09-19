# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

from unittest import mock


class TestUamqpImport(object):
    def test_import_error(self):
        """
        This test should throw if any module is importing uamqp
        Add any new top level modules here to ensure they aren't importing uamqp
        """
        with mock.patch.dict("sys.modules", {"uamqp": None}):
            import azext_iot.assets
            import azext_iot.central
            import azext_iot.common
            import azext_iot.dps
            import azext_iot.iothub
            import azext_iot.models

            assert azext_iot.assets
            assert azext_iot.central
            assert azext_iot.common
            assert azext_iot.dps
            assert azext_iot.iothub
            assert azext_iot.models
